"""Pure control-plane transitions for durable activation protocol v2.

This module owns the durable protocol transitions plus the narrow mechanical
leaf boundaries from ADR-0056.  It performs no I/O.  Every live state returned
here is derived by replaying emitted events through ``apply_events``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, get_args

from app.services.engine.actions import (
    ACTION_TYPE_BY_CLASS,
    Action,
    can_append_activation_action_type,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivePlayerChanged,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    BattleEvent,
    InitiativeTransferred,
    InterruptTriggered,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    SCHEMA_VERSION,
    StatusRemoved,
    _PROTOCOL_EVENT_TYPES,
)
from app.services.engine.phases import _apply_single_action, _finalize_activation
from app.services.engine.resolver import _validate_action
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    BattleState,
    Lokalizacja,
    UnitBlob,
    apply_events,
    effective_passives,
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
    ILLEGAL_ACTION = "illegal_action"
    ILLEGAL_INTERRUPT = "illegal_interrupt"
    ILLEGAL_RECOVERY = "illegal_recovery"
    INTERRUPT_LIMIT_REACHED = "interrupt_limit_reached"


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


@dataclass(frozen=True, slots=True)
class ActivationActionTransitionResult:
    """Action transition plus the advanced, independently checkpointable RNG."""

    state: BattleState
    events: tuple[BattleEvent, ...]
    next_sequence: int
    dice: DeterministicDice


class ActivationActionOutcomeExecutor(Protocol):
    """Injected leaf resolving exactly one action and its regroup outcomes."""

    def __call__(
        self,
        *,
        state: BattleState,
        action: Action,
        dice: DeterministicDice,
        sequence: int,
    ) -> tuple[BattleState, tuple[BattleEvent, ...], int]: ...


class ActivationInterruptOutcomeExecutor(Protocol):
    """Injected leaf that resolves one verified interrupt into outcome events."""

    def __call__(
        self,
        *,
        state: BattleState,
        source: UnitBlob,
        ability_slug: str,
        payload: Mapping[str, Any],
        sequence: int,
    ) -> tuple[BattleState, tuple[BattleEvent, ...]]: ...


class _ActivationRecoveryOutcomeExecutor(Protocol):
    """Injected leaf resolving only the explicit recovery choice."""

    def __call__(
        self,
        *,
        state: BattleState,
        actor_id: int,
        recovery_uses: tuple[object, ...],
        sequence: int,
    ) -> tuple[BattleState, tuple[BattleEvent, ...], int]: ...


_BATTLE_EVENT_TYPES = get_args(BattleEvent)
_MAX_ACCEPTED_INTERRUPTS_PER_WINDOW = 64
_MAX_INTERRUPT_OUTCOME_EVENTS = 64
_MAX_FINALIZATION_OUTCOME_EVENTS = 64


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
        or selected_unit_id < 0
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


def _interrupt_source(
    state: BattleState,
    *,
    caller_player: int,
    source_unit_id: int,
    ability_slug: str,
) -> UnitBlob:
    if (
        type(source_unit_id) is not int
        or source_unit_id < 0
        or type(ability_slug) is not str
        or not ability_slug
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    source = next((blob for blob in state.blobs if blob.id == source_unit_id), None)
    if (
        source is None
        or type(source.owner_player) is not int
        or source.owner_player != caller_player
        or source.models_alive <= 0
        or source.location is not Lokalizacja.FRONT
        or ability_slug not in effective_passives(source)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    return source


def _validated_interrupt_outcomes(
    protocol_state: BattleState,
    *,
    source: UnitBlob,
    ability_slug: str,
    payload: Mapping[str, Any],
    sequence: int,
    outcome_executor: ActivationInterruptOutcomeExecutor,
) -> tuple[tuple[BattleEvent, ...], BattleState]:
    try:
        result = outcome_executor(
            state=protocol_state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
            sequence=sequence,
        )
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
        ) from exc

    if type(result) is not tuple or len(result) != 2:
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    outcome_state, outcome_events = result
    if (
        type(outcome_state) is not BattleState
        or type(outcome_events) is not tuple
        or not 1 <= len(outcome_events) <= _MAX_INTERRUPT_OUTCOME_EVENTS
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)

    interrupt_markers: list[InterruptTriggered] = []
    for offset, event in enumerate(outcome_events):
        if (
            type(event) not in _BATTLE_EVENT_TYPES
            or type(event) in _PROTOCOL_EVENT_TYPES
            or type(getattr(event, "sequence", None)) is not int
            or event.sequence != sequence + offset
            or type(getattr(event, "version", None)) is not int
            or event.version != SCHEMA_VERSION
        ):
            _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
        if type(event) is InterruptTriggered:
            interrupt_markers.append(event)

    if len(interrupt_markers) != 1:
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    marker = interrupt_markers[0]
    if (
        type(marker.interrupt_point) is not str
        or marker.interrupt_point != "before_action"
        or type(marker.source_unit_id) is not int
        or marker.source_unit_id != source.id
        or type(marker.slug) is not str
        or marker.slug != ability_slug
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)

    try:
        replay_state = apply_events(protocol_state, outcome_events)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
        ) from exc
    if outcome_state != replay_state:
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    return outcome_events, replay_state


def _execute_single_action_outcomes(
    *,
    state: BattleState,
    action: Action,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Narrow adapter preserving the resolver validator and mechanical leaf."""

    _validate_action(state, action)
    return _apply_single_action(state, action, dice, sequence)


def _validated_action_outcomes(
    state: BattleState,
    *,
    action: Action,
    dice: DeterministicDice,
    sequence: int,
    outcome_executor: ActivationActionOutcomeExecutor,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    try:
        result = outcome_executor(
            state=state,
            action=action,
            dice=dice,
            sequence=sequence,
        )
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc

    if type(result) is not tuple or len(result) != 3:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    outcome_state, outcome_events, next_sequence = result
    if (
        type(outcome_state) is not BattleState
        or type(outcome_events) is not tuple
        or not outcome_events
        or type(next_sequence) is not int
        or next_sequence != sequence + len(outcome_events)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)

    for offset, event in enumerate(outcome_events):
        if (
            type(event) not in _BATTLE_EVENT_TYPES
            or type(event) in _PROTOCOL_EVENT_TYPES
            or type(getattr(event, "sequence", None)) is not int
            or event.sequence != sequence + offset
            or type(getattr(event, "version", None)) is not int
            or event.version != SCHEMA_VERSION
        ):
            _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)

    try:
        replay_state = apply_events(state, outcome_events)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    if outcome_state != replay_state:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    return replay_state, outcome_events, next_sequence


def _execute_empty_recovery_outcomes(
    *,
    state: BattleState,
    actor_id: int,
    recovery_uses: tuple[object, ...],
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Resolve the only supported recovery choice as an exact no-op."""

    if recovery_uses:
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)
    return state, (), sequence


def _validated_terminal_outcome_result(
    state: BattleState,
    *,
    result: object,
    sequence: int,
    require_empty: bool,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    if type(result) is not tuple or len(result) != 3:
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)
    outcome_state, outcome_events, next_sequence = result
    if (
        type(outcome_state) is not BattleState
        or type(outcome_events) is not tuple
        or len(outcome_events) > _MAX_FINALIZATION_OUTCOME_EVENTS
        or type(next_sequence) is not int
        or next_sequence != sequence + len(outcome_events)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)

    for offset, event in enumerate(outcome_events):
        if (
            type(event) not in _BATTLE_EVENT_TYPES
            or type(event) in _PROTOCOL_EVENT_TYPES
            or type(getattr(event, "sequence", None)) is not int
            or event.sequence != sequence + offset
            or type(getattr(event, "version", None)) is not int
            or event.version != SCHEMA_VERSION
        ):
            _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)

    try:
        replay_state = apply_events(state, outcome_events)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY
        ) from exc
    if outcome_state != replay_state:
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)
    if require_empty and outcome_events:
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)
    return replay_state, outcome_events, next_sequence


def _validated_recovery_outcomes(
    state: BattleState,
    *,
    actor_id: int,
    recovery_uses: tuple[object, ...],
    sequence: int,
    outcome_executor: _ActivationRecoveryOutcomeExecutor,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    try:
        result = outcome_executor(
            state=state,
            actor_id=actor_id,
            recovery_uses=recovery_uses,
            sequence=sequence,
        )
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY
        ) from exc
    return _validated_terminal_outcome_result(
        state,
        result=result,
        sequence=sequence,
        require_empty=True,
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


def trigger_activation_interrupt(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    expected_window_version: int,
    source_unit_id: int,
    ability_slug: str,
    payload: Mapping[str, Any],
    sequence: int,
    outcome_executor: ActivationInterruptOutcomeExecutor,
) -> ActivationTransitionResult:
    """Atomically accept one interrupt and its bounded mechanical outcomes."""

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
    if window.interrupt_count >= _MAX_ACCEPTED_INTERRUPTS_PER_WINDOW:
        _reject(ActivationProtocolErrorReason.INTERRUPT_LIMIT_REACHED)
    if (
        not isinstance(payload, Mapping)
        or type(sequence) is not int
        or sequence < 1
        or not callable(outcome_executor)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)
    source = _interrupt_source(
        state,
        caller_player=caller_player,
        source_unit_id=source_unit_id,
        ability_slug=ability_slug,
    )

    protocol_event = ActivationInterruptTriggered(
        sequence=sequence,
        activation_id=activation.activation_id,
        activation_version=activation.version + 1,
        window_ordinal=window.ordinal,
        window_version=window.version + 1,
        priority_player=window.priority_player,
    )
    protocol_state = apply_events(state, (protocol_event,))
    outcome_events, replay_state = _validated_interrupt_outcomes(
        protocol_state,
        source=source,
        ability_slug=ability_slug,
        payload=payload,
        sequence=sequence + 1,
        outcome_executor=outcome_executor,
    )
    events = (protocol_event, *outcome_events)
    return ActivationTransitionResult(
        state=replay_state,
        events=events,
        next_sequence=sequence + len(events),
    )


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


def commit_activation_action(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    action: Action,
    dice: DeterministicDice,
    sequence: int,
    outcome_executor: ActivationActionOutcomeExecutor = _execute_single_action_outcomes,
) -> ActivationActionTransitionResult:
    """Resolve and commit exactly one selected-unit action in ``ACTION_READY``."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    if activation.phase is not ActivationPhase.ACTION_READY:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    _require_caller(caller_player, activation.controlling_player)

    action_type = ACTION_TYPE_BY_CLASS.get(type(action))
    if (
        action_type is None
        or type(getattr(action, "unit_id", None)) is not int
        or action.unit_id != activation.selected_unit_id
        or not can_append_activation_action_type(
            action_type,
            activation.action_types,
        )
        or type(dice) is not DeterministicDice
        or type(sequence) is not int
        or sequence < 1
        or not callable(outcome_executor)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)

    try:
        working_dice = DeterministicDice.from_checkpoint(dice.to_checkpoint())
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    outcome_state, outcome_events, next_sequence = _validated_action_outcomes(
        state,
        action=action,
        dice=working_dice,
        sequence=sequence,
        outcome_executor=outcome_executor,
    )
    committed = ActivationActionCommitted(
        sequence=next_sequence,
        activation_id=activation.activation_id,
        activation_version=activation.version + 1,
        action_type=action_type,
    )
    events = (*outcome_events, committed)
    try:
        result_state = apply_events(outcome_state, (committed,))
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    return ActivationActionTransitionResult(
        state=result_state,
        events=events,
        next_sequence=next_sequence + 1,
        dice=working_dice,
    )


def finalize_activation(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    recovery_uses: tuple[object, ...],
    sequence: int,
    recovery_outcome_executor: _ActivationRecoveryOutcomeExecutor = (
        _execute_empty_recovery_outcomes
    ),
) -> ActivationTransitionResult:
    """Finalize one v2 activation after one or two committed actions.

    Recovery remains an explicit player decision.  Until source-correct
    recovery handlers exist, only the exact empty tuple is accepted.
    """

    initiative_player = _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    legal_phase = (
        activation.phase is ActivationPhase.AWAITING_CONTINUATION
        and activation.action_count == 1
    ) or (
        activation.phase is ActivationPhase.AWAITING_FINALIZATION
        and activation.action_count == 2
    )
    if (
        not legal_phase
        or initiative_player != activation.initiative_player
        or state.active_player != activation.controlling_player
    ):
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    _require_caller(caller_player, activation.controlling_player)
    if (
        type(recovery_uses) is not tuple
        or recovery_uses
        or type(sequence) is not int
        or sequence < 1
        or not callable(recovery_outcome_executor)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_RECOVERY)

    events: list[BattleEvent] = []
    protocol_state = state
    next_sequence = sequence
    if activation.phase is ActivationPhase.AWAITING_CONTINUATION:
        continuation_event = ActivationContinuationChosen(
            sequence=next_sequence,
            activation_id=activation.activation_id,
            activation_version=activation.version + 1,
            continue_activation=False,
        )
        events.append(continuation_event)
        protocol_state = apply_events(protocol_state, (continuation_event,))
        next_sequence += 1

    recovery_state, recovery_events, next_sequence = _validated_recovery_outcomes(
        protocol_state,
        actor_id=activation.selected_unit_id,
        recovery_uses=recovery_uses,
        sequence=next_sequence,
        outcome_executor=recovery_outcome_executor,
    )
    events.extend(recovery_events)

    try:
        finalization_result = _finalize_activation(
            recovery_state,
            activation.selected_unit_id,
            next_sequence,
        )
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY
        ) from exc
    _, finalization_events, next_sequence = _validated_terminal_outcome_result(
        recovery_state,
        result=finalization_result,
        sequence=next_sequence,
        require_empty=False,
    )
    events.extend(finalization_events)

    terminal_events: tuple[BattleEvent, ...] = (
        ActivationFinalized(
            sequence=next_sequence,
            activation_id=activation.activation_id,
        ),
        InitiativeTransferred(
            sequence=next_sequence + 1,
            activation_id=activation.activation_id,
            previous_initiative_player=activation.initiative_player,
            new_initiative_player=1 - activation.initiative_player,
        ),
        ActivePlayerChanged(
            sequence=next_sequence + 2,
            activation_id=activation.activation_id,
            previous_active_player=activation.controlling_player,
            new_active_player=1 - activation.controlling_player,
        ),
    )
    events.extend(terminal_events)
    result_events = tuple(events)
    try:
        replay_state = apply_events(state, result_events)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY
        ) from exc
    return ActivationTransitionResult(
        state=replay_state,
        events=result_events,
        next_sequence=sequence + len(result_events),
    )


__all__ = [
    "ActivationActionOutcomeExecutor",
    "ActivationActionTransitionResult",
    "ActivationInterruptOutcomeExecutor",
    "ActivationProtocolError",
    "ActivationProtocolErrorReason",
    "ActivationTransitionResult",
    "commit_activation_action",
    "continue_activation",
    "finalize_activation",
    "pass_interrupt_priority",
    "start_activation",
    "trigger_activation_interrupt",
]
