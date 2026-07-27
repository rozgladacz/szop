"""Pure control-plane transitions for durable activation protocol v2.

This module owns only the non-mechanical start/pass/continue operations from
ADR-0056.  It performs no I/O or RNG work.  Every live state returned here is
derived by replaying the emitted events through ``apply_events``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.engine.events import (
    ActivationContinuationChosen,
    ActivationStarted,
    BattleEvent,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    StatusRemoved,
)
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    BattleState,
    Lokalizacja,
    UnitBlob,
    apply_events,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
)


class ActivationProtocolErrorReason(str, Enum):
    """Stable internal reasons for future service/transport mapping."""

    PROTOCOL_UPGRADE_REQUIRED = "battle_protocol_upgrade_required"
    INVALID_PHASE = "invalid_phase"
    INVALID_SELECTION = "invalid_selection"
    INVALID_CALLER = "invalid_caller"
    STALE_ACTIVATION = "stale_activation"
    STALE_WINDOW = "stale_window"
    ILLEGAL_CONTINUE = "illegal_continue"


class ActivationProtocolError(ValueError):
    """A control-plane transition is illegal for the supplied state/guards."""

    def __init__(self, reason: ActivationProtocolErrorReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class ActivationTransitionResult:
    """Immutable output shared by all pure activation protocol transitions."""

    state: BattleState
    events: tuple[BattleEvent, ...]
    next_sequence: int


def _reject(reason: ActivationProtocolErrorReason) -> None:
    raise ActivationProtocolError(reason)


def _require_protocol_v2(state: BattleState) -> int:
    initiative_player = state.initiative_player
    if type(initiative_player) is not int or initiative_player not in (0, 1):
        _reject(ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED)
    return initiative_player


def _require_activation(
    state: BattleState,
    *,
    activation_id: int,
    expected_activation_version: int,
) -> ActivationState:
    activation = state.activation
    if activation is None:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    if (
        type(activation_id) is not int
        or activation_id < 1
        or type(expected_activation_version) is not int
        or expected_activation_version < 1
        or activation.activation_id != activation_id
        or activation.version != expected_activation_version
    ):
        _reject(ActivationProtocolErrorReason.STALE_ACTIVATION)
    return activation


def _require_caller(caller_player: int, expected_player: int) -> None:
    if (
        type(caller_player) is not int
        or caller_player not in (0, 1)
        or caller_player != expected_player
    ):
        _reject(ActivationProtocolErrorReason.INVALID_CALLER)


def _selected_unit(state: BattleState, selected_unit_id: int) -> UnitBlob:
    if (
        state.is_game_over
        or type(state.active_player) is not int
        or state.active_player not in (0, 1)
        or type(selected_unit_id) is not int
        or selected_unit_id < 1
    ):
        _reject(
            ActivationProtocolErrorReason.INVALID_PHASE
            if state.is_game_over
            else ActivationProtocolErrorReason.INVALID_SELECTION
        )
    unit = next((blob for blob in state.blobs if blob.id == selected_unit_id), None)
    if (
        unit is None
        or type(unit.owner_player) is not int
        or unit.owner_player not in (0, 1)
        or unit.owner_player != state.active_player
        or unit.models_alive <= 0
        or unit.location is not Lokalizacja.FRONT
        or STATUS_AKTYWOWANY in unit.status_flags
    ):
        _reject(ActivationProtocolErrorReason.INVALID_SELECTION)
    return unit


def _result(
    state: BattleState,
    events: tuple[BattleEvent, ...],
    *,
    sequence: int,
) -> ActivationTransitionResult:
    return ActivationTransitionResult(
        state=apply_events(state, events),
        events=events,
        next_sequence=sequence + len(events),
    )


def start_activation(
    state: BattleState,
    *,
    selected_unit_id: int,
    sequence: int = 1,
) -> ActivationTransitionResult:
    """Start one v2 activation and open its first BEFORE_ACTION window."""

    initiative_player = _require_protocol_v2(state)
    if state.activation is not None:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    selected_unit = _selected_unit(state, selected_unit_id)

    activation_id = sequence
    events: list[BattleEvent] = [
        ActivationStarted(
            sequence=sequence,
            activation_id=activation_id,
            activation_version=1,
            selected_unit_id=selected_unit.id,
            controlling_player=state.active_player,
            initiative_player=initiative_player,
        )
    ]
    if STATUS_PRZYGOTOWANY in selected_unit.status_flags:
        events.append(
            StatusRemoved(
                sequence=sequence + len(events),
                target_id=selected_unit.id,
                status=STATUS_PRZYGOTOWANY,
            )
        )
    events.append(
        InterruptWindowOpened(
            sequence=sequence + len(events),
            activation_id=activation_id,
            activation_version=1,
            window_ordinal=1,
            window_version=1,
            priority_player=initiative_player,
        )
    )
    return _result(state, tuple(events), sequence=sequence)


def pass_interrupt_priority(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    expected_window_version: int,
    sequence: int = 1,
) -> ActivationTransitionResult:
    """Record one explicit pass, handing off or closing the current window."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    window = activation.window
    if activation.phase is not ActivationPhase.BEFORE_ACTION or window is None:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    if (
        type(expected_window_version) is not int
        or expected_window_version < 1
        or window.version != expected_window_version
    ):
        _reject(ActivationProtocolErrorReason.STALE_WINDOW)
    _require_caller(caller_player, window.priority_player)

    activation_version = activation.version + 1
    window_version = window.version + 1
    closing = bool(window.passed_players)
    pass_event = InterruptPriorityPassed(
        sequence=sequence,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        window_ordinal=window.ordinal,
        window_version=window_version,
        passed_player=caller_player,
        next_priority_player=None if closing else 1 - caller_player,
    )
    if not closing:
        return _result(state, (pass_event,), sequence=sequence)

    close_event = InterruptWindowClosed(
        sequence=sequence + 1,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        window_ordinal=window.ordinal,
        window_version=window_version,
    )
    return _result(state, (pass_event, close_event), sequence=sequence)


def continue_activation(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    sequence: int = 1,
) -> ActivationTransitionResult:
    """Choose the second action and atomically open BEFORE_ACTION window two."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    if (
        activation.phase is not ActivationPhase.AWAITING_CONTINUATION
        or activation.action_count != 1
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_CONTINUE)
    _require_caller(caller_player, activation.controlling_player)

    activation_version = activation.version + 1
    events: tuple[BattleEvent, ...] = (
        ActivationContinuationChosen(
            sequence=sequence,
            activation_id=activation.activation_id,
            activation_version=activation_version,
            continue_activation=True,
        ),
        InterruptWindowOpened(
            sequence=sequence + 1,
            activation_id=activation.activation_id,
            activation_version=activation_version,
            window_ordinal=2,
            window_version=1,
            priority_player=activation.initiative_player,
        ),
    )
    return _result(state, events, sequence=sequence)


__all__ = [
    "ActivationProtocolError",
    "ActivationProtocolErrorReason",
    "ActivationTransitionResult",
    "continue_activation",
    "pass_interrupt_priority",
    "start_activation",
]
