"""Transactionally neutral persistence for durable activation-protocol steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..battle_protocol import ACTIVATION_PROTOCOL_VERSION_V2
from .engine.action_codec import ActionCodecError, action_from_json, action_to_json
from .engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    commit_activation_action,
    continue_activation,
    finalize_activation,
    pass_interrupt_priority,
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


class BattleActivationPassError(RuntimeError):
    """Base error for the durable activation-pass service boundary."""


class BattleActivationPassNotFound(BattleActivationPassError):
    """The battle is missing or outside the participant scope."""


class BattleActivationPassUpgradeRequired(BattleActivationPassError):
    """The battle uses the legacy activation protocol."""


class BattleActivationPassUnavailable(BattleActivationPassError):
    """The battle has no coherent resumable v2 checkpoint at its current head."""

    def __init__(self, *, actual_sequence: int | None = None) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current v2 battle checkpoint is unavailable")


class BattleActivationPassSequenceConflict(BattleActivationPassError):
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


class BattleActivationPassInvalid(BattleActivationPassError):
    """The input or current domain state cannot accept this explicit pass."""

    def __init__(
        self,
        detail: str,
        *,
        reason: ActivationProtocolErrorReason | None = None,
    ) -> None:
        self.detail = detail
        self.reason = reason
        super().__init__(detail)


class BattleActivationPassWriteConflict(BattleActivationPassError):
    """A guarded event/checkpoint write lost a concurrent race."""


class BattleActivationActionError(RuntimeError):
    """Base error for the durable activation-action service boundary."""


class BattleActivationActionNotFound(BattleActivationActionError):
    """The battle is missing or outside the participant scope."""


class BattleActivationActionUpgradeRequired(BattleActivationActionError):
    """The battle uses the legacy activation protocol."""


class BattleActivationActionUnavailable(BattleActivationActionError):
    """The battle has no coherent resumable v2 checkpoint at its current head."""

    def __init__(self, *, actual_sequence: int | None = None) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current v2 battle checkpoint is unavailable")


class BattleActivationActionSequenceConflict(BattleActivationActionError):
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


class BattleActivationActionForbidden(BattleActivationActionError):
    """The participant does not control the durable activation."""


class BattleActivationActionInvalid(BattleActivationActionError):
    """The input or current domain state cannot commit this activation action."""

    def __init__(
        self,
        detail: str,
        *,
        reason: ActivationProtocolErrorReason | None = None,
    ) -> None:
        self.detail = detail
        self.reason = reason
        super().__init__(detail)


class BattleActivationActionWriteConflict(BattleActivationActionError):
    """A guarded event/checkpoint write lost a concurrent race."""


class BattleActivationContinueError(RuntimeError):
    """Base error for the durable activation-continue service boundary."""


class BattleActivationContinueNotFound(BattleActivationContinueError):
    """The battle is missing or outside the participant scope."""


class BattleActivationContinueUpgradeRequired(BattleActivationContinueError):
    """The battle uses the legacy activation protocol."""


class BattleActivationContinueUnavailable(BattleActivationContinueError):
    """The battle has no coherent resumable v2 checkpoint at its current head."""

    def __init__(self, *, actual_sequence: int | None = None) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current v2 battle checkpoint is unavailable")


class BattleActivationContinueSequenceConflict(BattleActivationContinueError):
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


class BattleActivationContinueForbidden(BattleActivationContinueError):
    """The participant does not control the durable activation."""


class BattleActivationContinueInvalid(BattleActivationContinueError):
    """The input or current domain state cannot continue this activation."""

    def __init__(
        self,
        detail: str,
        *,
        reason: ActivationProtocolErrorReason | None = None,
    ) -> None:
        self.detail = detail
        self.reason = reason
        super().__init__(detail)


class BattleActivationContinueWriteConflict(BattleActivationContinueError):
    """A guarded event/checkpoint write lost a concurrent race."""


class BattleActivationFinalizeError(RuntimeError):
    """Base error for the durable activation-finalize service boundary."""


class BattleActivationFinalizeNotFound(BattleActivationFinalizeError):
    """The battle is missing or outside the participant scope."""


class BattleActivationFinalizeUpgradeRequired(BattleActivationFinalizeError):
    """The battle uses the legacy activation protocol."""


class BattleActivationFinalizeUnavailable(BattleActivationFinalizeError):
    """The battle has no coherent resumable v2 checkpoint at its current head."""

    def __init__(self, *, actual_sequence: int | None = None) -> None:
        self.actual_sequence = actual_sequence
        super().__init__("Current v2 battle checkpoint is unavailable")


class BattleActivationFinalizeSequenceConflict(BattleActivationFinalizeError):
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


class BattleActivationFinalizeForbidden(BattleActivationFinalizeError):
    """The participant does not control the durable activation."""


class BattleActivationFinalizeInvalid(BattleActivationFinalizeError):
    """The input or current domain state cannot finalize this activation."""

    def __init__(
        self,
        detail: str,
        *,
        reason: ActivationProtocolErrorReason | None = None,
    ) -> None:
        self.detail = detail
        self.reason = reason
        super().__init__(detail)


class BattleActivationFinalizeWriteConflict(BattleActivationFinalizeError):
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


@dataclass(frozen=True, slots=True)
class StagedBattleActivationPass:
    """One staged v2 priority pass and its resumable durable result."""

    battle_id: int
    previous_sequence: int
    new_sequence: int
    state: BattleState
    events: tuple[BattleEvent, ...]
    dice: DeterministicDice


@dataclass(frozen=True, slots=True)
class StagedBattleActivationAction:
    """One staged v2 action and its canonical, resumable durable result."""

    battle_id: int
    previous_sequence: int
    new_sequence: int
    action_wire: dict[str, Any]
    state: BattleState
    events: tuple[BattleEvent, ...]
    dice: DeterministicDice


@dataclass(frozen=True, slots=True)
class StagedBattleActivationContinue:
    """One staged v2 continuation and its second interrupt window."""

    battle_id: int
    previous_sequence: int
    new_sequence: int
    state: BattleState
    events: tuple[BattleEvent, ...]
    dice: DeterministicDice


@dataclass(frozen=True, slots=True)
class StagedBattleActivationFinalize:
    """One staged v2 terminal activation delta and its resumable result."""

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
        controlled_player=checkpoint.state.active_player,
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


def stage_battle_activation_pass(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
    expected_sequence: int,
    activation_id: int,
    expected_activation_version: int,
    expected_window_version: int,
) -> StagedBattleActivationPass:
    """Stage exactly one explicit v2 priority pass without ending a transaction."""

    try:
        _validate_identity(
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationPassNotFound from exc
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise BattleActivationPassInvalid("Invalid expected sequence")
    if (
        type(activation_id) is not int
        or activation_id < 1
        or type(expected_activation_version) is not int
        or expected_activation_version < 1
    ):
        raise BattleActivationPassInvalid(
            "Invalid activation guard",
            reason=ActivationProtocolErrorReason.STALE_ACTIVATION,
        )
    if (
        type(expected_window_version) is not int
        or expected_window_version < 1
    ):
        raise BattleActivationPassInvalid(
            "Invalid window guard",
            reason=ActivationProtocolErrorReason.STALE_WINDOW,
        )

    try:
        battle = _get_participant_battle(
            db,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationPassNotFound from exc
    if battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V2:
        raise BattleActivationPassUpgradeRequired
    if battle.status != "active":
        raise BattleActivationPassInvalid(
            "Battle is not active",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )

    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        raise BattleActivationPassUnavailable from exc
    if checkpoint is None:
        raise BattleActivationPassUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActivationPassSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )
    if (
        type(checkpoint.state.initiative_player) is not int
        or checkpoint.state.initiative_player not in (0, 1)
    ):
        raise BattleActivationPassUnavailable(
            actual_sequence=checkpoint.sequence_at
        )

    activation = checkpoint.state.activation
    priority_player = (
        activation.window.priority_player
        if activation is not None and activation.window is not None
        else 0
    )
    try:
        caller_player = _caller_player(
            battle,
            caller_user_id=caller_user_id,
            controlled_player=priority_player,
        )
    except BattleActivationStartInvalid as exc:
        raise BattleActivationPassUnavailable(
            actual_sequence=checkpoint.sequence_at
        ) from exc

    try:
        transition = pass_interrupt_priority(
            checkpoint.state,
            caller_player=caller_player,
            activation_id=activation_id,
            expected_activation_version=expected_activation_version,
            expected_window_version=expected_window_version,
            sequence=checkpoint.sequence_at + 1,
        )
    except ActivationProtocolError as exc:
        if exc.reason is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED:
            raise BattleActivationPassUnavailable(
                actual_sequence=checkpoint.sequence_at
            ) from exc
        raise BattleActivationPassInvalid(
            "Activation pass is not legal",
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
        raise BattleActivationPassSequenceConflict(
            expected_sequence=exc.expected_latest_sequence,
            actual_sequence=exc.actual_latest_sequence,
        ) from exc
    except (BattleCheckpointSequenceConflict, IntegrityError) as exc:
        raise BattleActivationPassWriteConflict from exc

    return StagedBattleActivationPass(
        battle_id=battle.id,
        previous_sequence=checkpoint.sequence_at,
        new_sequence=new_sequence,
        state=transition.state,
        events=transition.events,
        dice=checkpoint.dice,
    )


def stage_battle_activation_action(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
    expected_sequence: int,
    activation_id: int,
    expected_activation_version: int,
    action_payload: Mapping[str, Any],
) -> StagedBattleActivationAction:
    """Stage exactly one legal v2 activation action without ending a transaction."""

    try:
        _validate_identity(
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationActionNotFound from exc
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise BattleActivationActionInvalid("Invalid expected sequence")
    if (
        type(activation_id) is not int
        or activation_id < 1
        or type(expected_activation_version) is not int
        or expected_activation_version < 1
    ):
        raise BattleActivationActionInvalid(
            "Invalid activation guard",
            reason=ActivationProtocolErrorReason.STALE_ACTIVATION,
        )

    try:
        battle = _get_participant_battle(
            db,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationActionNotFound from exc
    if battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V2:
        raise BattleActivationActionUpgradeRequired
    if battle.status != "active":
        raise BattleActivationActionInvalid(
            "Battle is not active",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )

    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        raise BattleActivationActionUnavailable from exc
    if checkpoint is None:
        raise BattleActivationActionUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActivationActionSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )
    if (
        type(checkpoint.state.initiative_player) is not int
        or checkpoint.state.initiative_player not in (0, 1)
    ):
        raise BattleActivationActionUnavailable(
            actual_sequence=checkpoint.sequence_at
        )

    try:
        action = action_from_json(action_payload)
        canonical_action = action_to_json(action)
    except (ActionCodecError, TypeError, ValueError) as exc:
        raise BattleActivationActionInvalid("Invalid action payload") from exc

    activation = checkpoint.state.activation
    controlled_player = (
        activation.controlling_player if activation is not None else 0
    )
    try:
        caller_player = _caller_player(
            battle,
            caller_user_id=caller_user_id,
            controlled_player=controlled_player,
        )
    except BattleActivationStartInvalid as exc:
        raise BattleActivationActionUnavailable(
            actual_sequence=checkpoint.sequence_at
        ) from exc

    try:
        transition = commit_activation_action(
            checkpoint.state,
            caller_player=caller_player,
            activation_id=activation_id,
            expected_activation_version=expected_activation_version,
            action=action,
            dice=checkpoint.dice,
            sequence=checkpoint.sequence_at + 1,
        )
    except ActivationProtocolError as exc:
        if exc.reason is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED:
            raise BattleActivationActionUnavailable(
                actual_sequence=checkpoint.sequence_at
            ) from exc
        if exc.reason is ActivationProtocolErrorReason.INVALID_CALLER:
            raise BattleActivationActionForbidden from exc
        raise BattleActivationActionInvalid(
            "Activation action is not legal",
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
            transition.dice,
            state_version=ACTIVATION_PROTOCOL_VERSION_V2,
        )
    except BattleEventSequenceConflict as exc:
        raise BattleActivationActionSequenceConflict(
            expected_sequence=exc.expected_latest_sequence,
            actual_sequence=exc.actual_latest_sequence,
        ) from exc
    except (BattleCheckpointSequenceConflict, IntegrityError) as exc:
        raise BattleActivationActionWriteConflict from exc

    return StagedBattleActivationAction(
        battle_id=battle.id,
        previous_sequence=checkpoint.sequence_at,
        new_sequence=new_sequence,
        action_wire=canonical_action,
        state=transition.state,
        events=transition.events,
        dice=transition.dice,
    )


def stage_battle_activation_continue(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
    expected_sequence: int,
    activation_id: int,
    expected_activation_version: int,
) -> StagedBattleActivationContinue:
    """Stage the explicit second-action choice without ending a transaction."""

    try:
        _validate_identity(
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationContinueNotFound from exc
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise BattleActivationContinueInvalid("Invalid expected sequence")
    if (
        type(activation_id) is not int
        or activation_id < 1
        or type(expected_activation_version) is not int
        or expected_activation_version < 1
    ):
        raise BattleActivationContinueInvalid(
            "Invalid activation guard",
            reason=ActivationProtocolErrorReason.STALE_ACTIVATION,
        )

    try:
        battle = _get_participant_battle(
            db,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationContinueNotFound from exc
    if battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V2:
        raise BattleActivationContinueUpgradeRequired
    if battle.status != "active":
        raise BattleActivationContinueInvalid(
            "Battle is not active",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )

    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        raise BattleActivationContinueUnavailable from exc
    if checkpoint is None:
        raise BattleActivationContinueUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActivationContinueSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )
    if (
        type(checkpoint.state.initiative_player) is not int
        or checkpoint.state.initiative_player not in (0, 1)
    ):
        raise BattleActivationContinueUnavailable(
            actual_sequence=checkpoint.sequence_at
        )

    activation = checkpoint.state.activation
    controlled_player = (
        activation.controlling_player if activation is not None else 0
    )
    try:
        caller_player = _caller_player(
            battle,
            caller_user_id=caller_user_id,
            controlled_player=controlled_player,
        )
    except BattleActivationStartInvalid as exc:
        raise BattleActivationContinueUnavailable(
            actual_sequence=checkpoint.sequence_at
        ) from exc

    try:
        transition = continue_activation(
            checkpoint.state,
            caller_player=caller_player,
            activation_id=activation_id,
            expected_activation_version=expected_activation_version,
            sequence=checkpoint.sequence_at + 1,
        )
    except ActivationProtocolError as exc:
        if exc.reason is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED:
            raise BattleActivationContinueUnavailable(
                actual_sequence=checkpoint.sequence_at
            ) from exc
        if exc.reason is ActivationProtocolErrorReason.INVALID_CALLER:
            raise BattleActivationContinueForbidden from exc
        raise BattleActivationContinueInvalid(
            "Activation continuation is not legal",
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
        raise BattleActivationContinueSequenceConflict(
            expected_sequence=exc.expected_latest_sequence,
            actual_sequence=exc.actual_latest_sequence,
        ) from exc
    except (BattleCheckpointSequenceConflict, IntegrityError) as exc:
        raise BattleActivationContinueWriteConflict from exc

    return StagedBattleActivationContinue(
        battle_id=battle.id,
        previous_sequence=checkpoint.sequence_at,
        new_sequence=new_sequence,
        state=transition.state,
        events=transition.events,
        dice=checkpoint.dice,
    )


def stage_battle_activation_finalize(
    db: Session,
    *,
    battle_id: int,
    caller_user_id: int,
    expected_sequence: int,
    activation_id: int,
    expected_activation_version: int,
    recovery_uses: tuple[object, ...],
) -> StagedBattleActivationFinalize:
    """Stage one explicit empty-recovery finalization without ending a transaction."""

    try:
        _validate_identity(
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationFinalizeNotFound from exc
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise BattleActivationFinalizeInvalid("Invalid expected sequence")
    if (
        type(activation_id) is not int
        or activation_id < 1
        or type(expected_activation_version) is not int
        or expected_activation_version < 1
    ):
        raise BattleActivationFinalizeInvalid(
            "Invalid activation guard",
            reason=ActivationProtocolErrorReason.STALE_ACTIVATION,
        )
    if type(recovery_uses) is not tuple or recovery_uses:
        raise BattleActivationFinalizeInvalid(
            "Invalid recovery choice",
            reason=ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        )

    try:
        battle = _get_participant_battle(
            db,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
        )
    except BattleActivationStartNotFound as exc:
        raise BattleActivationFinalizeNotFound from exc
    if battle.activation_protocol_version != ACTIVATION_PROTOCOL_VERSION_V2:
        raise BattleActivationFinalizeUpgradeRequired
    if battle.status != "active":
        raise BattleActivationFinalizeInvalid(
            "Battle is not active",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )

    try:
        checkpoint = load_latest_checkpoint(db, battle.id)
    except (TypeError, ValueError) as exc:
        raise BattleActivationFinalizeUnavailable from exc
    if checkpoint is None:
        raise BattleActivationFinalizeUnavailable(
            actual_sequence=latest_event_sequence(db, battle.id)
        )
    if expected_sequence != checkpoint.sequence_at:
        raise BattleActivationFinalizeSequenceConflict(
            expected_sequence=expected_sequence,
            actual_sequence=checkpoint.sequence_at,
        )
    if (
        type(checkpoint.state.initiative_player) is not int
        or checkpoint.state.initiative_player not in (0, 1)
    ):
        raise BattleActivationFinalizeUnavailable(
            actual_sequence=checkpoint.sequence_at
        )

    activation = checkpoint.state.activation
    controlled_player = (
        activation.controlling_player if activation is not None else 0
    )
    try:
        caller_player = _caller_player(
            battle,
            caller_user_id=caller_user_id,
            controlled_player=controlled_player,
        )
    except BattleActivationStartInvalid as exc:
        raise BattleActivationFinalizeUnavailable(
            actual_sequence=checkpoint.sequence_at
        ) from exc

    try:
        transition = finalize_activation(
            checkpoint.state,
            caller_player=caller_player,
            activation_id=activation_id,
            expected_activation_version=expected_activation_version,
            recovery_uses=recovery_uses,
            sequence=checkpoint.sequence_at + 1,
        )
    except ActivationProtocolError as exc:
        if exc.reason is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED:
            raise BattleActivationFinalizeUnavailable(
                actual_sequence=checkpoint.sequence_at
            ) from exc
        if exc.reason is ActivationProtocolErrorReason.INVALID_CALLER:
            raise BattleActivationFinalizeForbidden from exc
        raise BattleActivationFinalizeInvalid(
            "Activation finalization is not legal",
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
        raise BattleActivationFinalizeSequenceConflict(
            expected_sequence=exc.expected_latest_sequence,
            actual_sequence=exc.actual_latest_sequence,
        ) from exc
    except (BattleCheckpointSequenceConflict, IntegrityError) as exc:
        raise BattleActivationFinalizeWriteConflict from exc

    return StagedBattleActivationFinalize(
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
    controlled_player: int,
) -> int:
    controls_p1 = battle.p1_user_id == caller_user_id
    controls_p2 = battle.p2_user_id == caller_user_id
    if controls_p1 and controls_p2:
        if type(controlled_player) is int and controlled_player in (0, 1):
            return controlled_player
        raise BattleActivationStartInvalid(
            "Battle has no valid active player",
            reason=ActivationProtocolErrorReason.INVALID_PHASE,
        )
    return 0 if controls_p1 else 1


__all__ = [
    "BattleActivationActionError",
    "BattleActivationActionForbidden",
    "BattleActivationActionInvalid",
    "BattleActivationActionNotFound",
    "BattleActivationActionSequenceConflict",
    "BattleActivationActionUnavailable",
    "BattleActivationActionUpgradeRequired",
    "BattleActivationActionWriteConflict",
    "BattleActivationContinueError",
    "BattleActivationContinueForbidden",
    "BattleActivationContinueInvalid",
    "BattleActivationContinueNotFound",
    "BattleActivationContinueSequenceConflict",
    "BattleActivationContinueUnavailable",
    "BattleActivationContinueUpgradeRequired",
    "BattleActivationContinueWriteConflict",
    "BattleActivationFinalizeError",
    "BattleActivationFinalizeForbidden",
    "BattleActivationFinalizeInvalid",
    "BattleActivationFinalizeNotFound",
    "BattleActivationFinalizeSequenceConflict",
    "BattleActivationFinalizeUnavailable",
    "BattleActivationFinalizeUpgradeRequired",
    "BattleActivationFinalizeWriteConflict",
    "BattleActivationPassError",
    "BattleActivationPassInvalid",
    "BattleActivationPassNotFound",
    "BattleActivationPassSequenceConflict",
    "BattleActivationPassUnavailable",
    "BattleActivationPassUpgradeRequired",
    "BattleActivationPassWriteConflict",
    "BattleActivationStartError",
    "BattleActivationStartForbidden",
    "BattleActivationStartInvalid",
    "BattleActivationStartNotFound",
    "BattleActivationStartSequenceConflict",
    "BattleActivationStartUnavailable",
    "BattleActivationStartUpgradeRequired",
    "BattleActivationStartWriteConflict",
    "StagedBattleActivationAction",
    "StagedBattleActivationContinue",
    "StagedBattleActivationFinalize",
    "StagedBattleActivationPass",
    "StagedBattleActivationStart",
    "stage_battle_activation_action",
    "stage_battle_activation_continue",
    "stage_battle_activation_finalize",
    "stage_battle_activation_pass",
    "stage_battle_activation_start",
]
