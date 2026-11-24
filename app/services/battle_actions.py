"""Shared orchestration for validated, atomic persisted battle actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models
from ..battle_protocol import ACTIVATION_PROTOCOL_VERSION_V1
from .engine.action_codec import (
    ActionCodecError,
    action_from_json,
    action_to_json,
)
from .engine.dice import DeterministicDice
from .engine.events import BattleEvent
from .engine.persistence import (
    latest_event_sequence,
    load_latest_checkpoint,
    save_checkpoint,
    save_events,
)
from .engine.phases import round_end_phase
from .engine.resolver import IllegalActionError, apply, should_end_round
from .engine.state import BattleState


# === SECTION: Errors and prepared result ===

class BattleActionError(RuntimeError):
    """Base error for the public battle-action orchestration seam."""


class BattleActionNotFound(BattleActionError):
    """The battle is missing or outside the participant scope."""


class BattleActionUnavailable(BattleActionError):
    """The battle has no resumable checkpoint at the current event-log end."""

    def __init__(self, *, actual_sequence: int) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current battle checkpoint is unavailable")


class BattleActionProposalProtocolConflict(BattleActionError):
    """Legacy action proposals require a coherent v1 battle and checkpoint."""

    def __init__(self) -> None:
        super().__init__("Battle action proposals require a valid v1 battle and checkpoint.")


class BattleActionSequenceConflict(BattleActionError):
    """The frozen optimistic sequence no longer matches the battle."""

    def __init__(self, *, expected_sequence: int, actual_sequence: int) -> None:
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        super().__init__("Battle event sequence conflict")


class BattleActionInvalid(BattleActionError):
    """The wire action is malformed or illegal in the current state."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class BattleActionForbidden(BattleActionError):
    """The participant does not control the proposed actor side."""


@dataclass(frozen=True, slots=True)
class PreparedBattleAction:
    battle_id: int
    previous_sequence: int
    new_sequence: int
    action_wire: dict[str, Any]
    state: BattleState
    events: tuple[BattleEvent, ...]
    dice: DeterministicDice


# === SECTION: Participant access and pure validation ===

def get_participant_battle(
    db: Session,
    *,
    battle_id: int,
    user_id: int,
) -> models.Battle:
    """Load one participant-scoped battle without revealing foreign IDs."""
    battle = db.execute(
        select(models.Battle).where(
            models.Battle.id == battle_id,
            or_(
                models.Battle.p1_user_id == user_id,
                models.Battle.p2_user_id == user_id,
            ),
        )
    ).scalar_one_or_none()
    if battle is None:
        raise BattleActionNotFound
    return battle


def prepare_battle_action(
    db: Session,
    *,
    battle: models.Battle,
    actor_user_id: int,
    expected_sequence: int,
    action_payload: Mapping[str, Any],
    require_v1_protocol: bool = False,
) -> PreparedBattleAction:
    """Resolve an action in isolation, optionally requiring a v1 checkpoint."""
    if (
        require_v1_protocol
        and battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V1
    ):
        raise BattleActionProposalProtocolConflict
    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        if not require_v1_protocol:
            raise
        raise BattleActionProposalProtocolConflict from exc
    if checkpoint is None:
        raise BattleActionUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if require_v1_protocol and checkpoint.version != ACTIVATION_PROTOCOL_VERSION_V1:
        raise BattleActionProposalProtocolConflict
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActionSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )

    try:
        action = action_from_json(action_payload)
        canonical_action = action_to_json(action)
    except (ActionCodecError, TypeError, ValueError) as exc:
        raise BattleActionInvalid("Invalid action payload") from exc

    acting_blob = next(
        (blob for blob in checkpoint.state.blobs if blob.id == action.unit_id),
        None,
    )
    if acting_blob is None:
        raise BattleActionInvalid("Illegal action")
    player_user_ids = (battle.p1_user_id, battle.p2_user_id)
    if (
        acting_blob.owner_player not in (0, 1)
        or player_user_ids[acting_blob.owner_player] != actor_user_id
    ):
        raise BattleActionForbidden

    try:
        result = apply(
            checkpoint.state,
            action,
            checkpoint.dice,
            sequence=checkpoint.sequence_at + 1,
        )
        new_state = result.state
        persisted_events = list(result.events)
        next_sequence = result.next_sequence
        if should_end_round(new_state):
            new_state, round_events = round_end_phase(
                new_state,
                sequence=next_sequence,
            )
            persisted_events.extend(round_events)
            next_sequence += len(round_events)
    except (IllegalActionError, TypeError, ValueError) as exc:
        raise BattleActionInvalid("Illegal action") from exc

    return PreparedBattleAction(
        battle_id=battle.id,
        previous_sequence=checkpoint.sequence_at,
        new_sequence=next_sequence - 1,
        action_wire=canonical_action,
        state=new_state,
        events=tuple(persisted_events),
        dice=checkpoint.dice,
    )


# === SECTION: Atomic event/checkpoint persistence ===

def stage_battle_action(
    db: Session,
    *,
    battle: models.Battle,
    actor_user_id: int,
    expected_sequence: int,
    action_payload: Mapping[str, Any],
    require_v1_protocol: bool = False,
) -> PreparedBattleAction:
    """Stage one action, checkpoint, and metadata update without committing."""
    prepared = prepare_battle_action(
        db,
        battle=battle,
        actor_user_id=actor_user_id,
        expected_sequence=expected_sequence,
        action_payload=action_payload,
        require_v1_protocol=require_v1_protocol,
    )
    save_events(
        db,
        battle.id,
        prepared.events,
        expected_latest_sequence=prepared.previous_sequence,
    )
    save_checkpoint(
        db,
        battle.id,
        prepared.new_sequence,
        prepared.state,
        prepared.dice,
    )
    battle.current_round = prepared.state.round
    battle.status = "finished" if prepared.state.is_game_over else "active"
    battle.winner_user_id = (
        _winner_user_id(battle, prepared.state.score)
        if prepared.state.is_game_over
        else None
    )
    return prepared


def _winner_user_id(
    battle: models.Battle,
    score: tuple[int, int],
) -> int | None:
    if score[0] > score[1]:
        return battle.p1_user_id
    if score[1] > score[0]:
        return battle.p2_user_id
    return None
