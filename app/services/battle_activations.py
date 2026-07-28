"""Transactionally neutral persistence for durable activation-protocol starts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..battle_protocol import ACTIVATION_PROTOCOL_VERSION_V2
from .engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    start_activation,
)
from .engine.dice import DeterministicDice
from .engine.events import BattleEvent
from .engine.persistence import (
    BattleCheckpointSequenceConflict,
    BattleEventSequenceConflict,
    latest_event_sequence,
    load_latest_checkpoint,
    save_checkpoint,
    save_events,
)
from .engine.state import BattleState


class BattleActivationStartError(RuntimeError):
    """Base error for the durable activation-start service boundary."""


class BattleActivationStartNotFound(BattleActivationStartError):
    """The battle is missing or outside the participant scope."""


class BattleActivationStartUpgradeRequired(BattleActivationStartError):
    """The battle uses the legacy activation protocol."""


class BattleActivationStartUnavailable(BattleActivationStartError):
    """The battle has no coherent resumable v2 checkpoint at its current head."""

    def __init__(self, *, actual_sequence: int | None = None) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current v2 battle checkpoint is unavailable")


class BattleActivationStartSequenceConflict(BattleActivationStartError):
    """The caller's optimistic sequence no longer matches the durable head."""

    def __init__(
        self,
        *,
        expected_sequence: int,
        actual_sequence: int,
    ) -> None:
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        super().__init__("Battle event sequence conflict")


class BattleActivationStartForbidden(BattleActivationStartError):
    """The participant does not control the currently active side."""


class BattleActivationStartInvalid(BattleActivationStartError):
    """The input or current domain state cannot start an activation."""

    def __init__(
        self,
        detail: str,
        *,
        reason: ActivationProtocolErrorReason | None = None,
    ) -> None:
        self.detail = detail
        self.reason = reason
        super().__init__(detail)


class BattleActivationStartWriteConflict(BattleActivationStartError):
    """A guarded event/checkpoint write lost a concurrent race."""


@dataclass(frozen=True, slots=True)
class StagedBattleActivationStart:
    """A staged v2 activation start suitable for a future shared envelope."""

    battle_id: int
    previous_sequence: int
    new_sequence: int
    state: BattleState
    events: tuple[BattleEvent, ...]
    dice: DeterministicDice


def stage_battle_activation_start(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
    selected_unit_id: int,
    expected_sequence: int,
) -> StagedBattleActivationStart:
    """Stage one v2 activation start without committing or rolling back."""

    _validate_identity(battle_id=battle_id, caller_user_id=caller_user_id)
    if type(selected_unit_id) is not int or selected_unit_id < 1:
        raise BattleActivationStartInvalid(
            "Invalid selected unit",
            reason=ActivationProtocolErrorReason.INVALID_SELECTION,
        )
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise BattleActivationStartInvalid("Invalid expected sequence")

    battle = _get_participant_battle(
        db,
        battle_id=battle_id,
        caller_user_id=caller_user_id,
    )
    if battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V2:
        raise BattleActivationStartUpgradeRequired
    if battle.status != "active":
        raise BattleActivationStartInvalid(
            "Battle is not active",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )

    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        raise BattleActivationStartUnavailable from exc
    if checkpoint is None:
        raise BattleActivationStartUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActivationStartSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )
    if (
        type(checkpoint.state.initiative_player) is not int
        or checkpoint.state.initiative_player not in (0, 1)
    ):
        raise BattleActivationStartUnavailable(
            actual_sequence=checkpoint.sequence_at
        )

    caller_player = _caller_player(
        battle,
        caller_user_id=caller_user_id,
        active_player=checkpoint.state.active_player,
    )
    if caller_player != checkpoint.state.active_player:
        raise BattleActivationStartForbidden

    try:
        transition = start_activation(
            checkpoint.state,
            selected_unit_id=selected_unit_id,
            sequence=checkpoint.sequence_at + 1,
        )
    except ActivationProtocolError as exc:
        if exc.reason is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED:
            raise BattleActivationStartUnavailable(
                actual_sequence=checkpoint.sequence_at
            ) from exc
        raise BattleActivationStartInvalid(
            "Activation start is not legal",
            reason=exc.reason,
        ) from exc

    new_sequence = transition.next_sequence - 1
    try:
        save_events(
            db,
            battle.id,
            transition.events,
            expected_latest_sequence=checkpoint.sequence_at,
        )
        save_checkpoint(
            db,
            battle.id,
            new_sequence,
            transition.state,
            checkpoint.dice,
            state_version=ACTIVATION_PROTOCOL_VERSION_V2,
        )
    except BattleEventSequenceConflict as exc:
        raise BattleActivationStartSequenceConflict(
            expected_sequence=exc.expected_latest_sequence,
            actual_sequence=exc.actual_latest_sequence,
        ) from exc
    except (BattleCheckpointSequenceConflict, IntegrityError) as exc:
        raise BattleActivationStartWriteConflict from exc

    return StagedBattleActivationStart(
        battle_id=battle.id,
        previous_sequence=checkpoint.sequence_at,
        new_sequence=new_sequence,
        state=transition.state,
        events=transition.events,
        dice=checkpoint.dice,
    )


def _validate_identity(*, battle_id: int, caller_user_id: int) -> None:
    if (
        type(battle_id) is not int
        or battle_id < 1
        or type(caller_user_id) is not int
        or caller_user_id < 1
    ):
        raise BattleActivationStartNotFound


def _get_participant_battle(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
) -> models.Battle:
    battle = db.execute(
        select(models.Battle).where(
            models.Battle.id == battle_id,
            or_(
                models.Battle.p1_user_id == caller_user_id,
                models.Battle.p2_user_id == caller_user_id,
            ),
        )
    ).scalar_one_or_none()
    if battle is None:
        raise BattleActivationStartNotFound
    return battle


def _caller_player(
    battle: models.Battle,
    *,
    caller_user_id: int,
    active_player: int,
) -> int:
    controls_p1 = battle.p1_user_id == caller_user_id
    controls_p2 = battle.p2_user_id == caller_user_id
    if controls_p1 and controls_p2:
        if type(active_player) is int and active_player in (0, 1):
            return active_player
        raise BattleActivationStartInvalid(
            "Battle has no valid active player",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )
    return 0 if controls_p1 else 1


__all__ = [
    "BattleActivationStartError",
    "BattleActivationStartForbidden",
    "BattleActivationStartInvalid",
    "BattleActivationStartNotFound",
    "BattleActivationStartSequenceConflict",
    "BattleActivationStartUnavailable",
    "BattleActivationStartUpgradeRequired",
    "BattleActivationStartWriteConflict",
    "StagedBattleActivationStart",
    "stage_battle_activation_start",
]
