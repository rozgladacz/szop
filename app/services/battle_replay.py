"""Bounded, read-only reconstruction of a persisted battle state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .engine.persistence import (
    load_earliest_checkpoint,
    load_events,
    load_latest_checkpoint,
)
from .engine.state import BattleState, apply_events

MAX_REPLAY_EVENTS = 10_000


class BattleReplayError(RuntimeError):
    """Base class for controlled replay failures."""


class BattleReplayConflict(BattleReplayError):
    """Persisted data cannot be reconstructed and verified safely."""


class BattleReplayLimitExceeded(BattleReplayError):
    """The persisted replay tail exceeds the fixed workload cap."""


@dataclass(frozen=True, slots=True)
class ReplayedBattleState:
    battle_id: int
    base_sequence: int
    replayed_through_sequence: int
    event_count: int
    state: BattleState


def replay_battle_state(db: Session, *, battle_id: int) -> ReplayedBattleState:
    """Rebuild state from the earliest checkpoint and verify the log-end state."""
    try:
        base = load_earliest_checkpoint(db, battle_id)
        current = load_latest_checkpoint(db, battle_id)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise BattleReplayConflict from exc
    if base is None or current is None:
        raise BattleReplayConflict

    try:
        events = load_events(
            db,
            battle_id,
            since=base.sequence_at,
            limit=MAX_REPLAY_EVENTS + 1,
        )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise BattleReplayConflict from exc
    if len(events) > MAX_REPLAY_EVENTS:
        raise BattleReplayLimitExceeded

    try:
        for expected_sequence, event in enumerate(
            events,
            start=base.sequence_at + 1,
        ):
            if (
                type(event.sequence) is not int
                or event.sequence != expected_sequence
            ):
                raise BattleReplayConflict
        if base.sequence_at + len(events) != current.sequence_at:
            raise BattleReplayConflict
        replayed = apply_events(base.state, events)
    except BattleReplayConflict:
        raise
    except Exception as exc:
        raise BattleReplayConflict from exc

    if replayed != current.state:
        raise BattleReplayConflict
    return ReplayedBattleState(
        battle_id=battle_id,
        base_sequence=base.sequence_at,
        replayed_through_sequence=current.sequence_at,
        event_count=len(events),
        state=replayed,
    )
