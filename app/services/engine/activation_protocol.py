"""Pure control-plane transitions for activation protocol v2 and private v3.

This module owns the durable protocol transitions plus the narrow mechanical
leaf boundaries from ADR-0056, including the pass-only attack lifecycle v3.
It performs no I/O.  Every live state returned here is derived by replaying
emitted events through ``apply_events``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Protocol, get_args

from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import (
    ACTION_TYPE_BY_CLASS,
    Action,
    ChargeAction,
    ShootAction,
    can_append_activation_action_type,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivePlayerChanged,
    AttackDeclared,
    AttackInterruptPriorityPassed,
    AttackInterruptWindowClosed,
    AttackInterruptWindowOpened,
    AttackResolved,
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
    AttackState,
    BattleState,
    ChargeAttackIntent,
    Lokalizacja,
    ShootAttackIntent,
    UnitBlob,
    WeaponProfile,
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
    STALE_ATTACK = "stale_attack"
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


@dataclass(frozen=True, slots=True)
class ActivationInterruptTransitionResult:
    """Interrupt transition plus the advanced, independently checkpointable RNG."""

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
        dice: DeterministicDice,
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
_MAX_ATTACK_RESOLUTION_EVENTS = 10_000


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


def _require_attack(
    activation: ActivationState,
    *,
    attack_id: int,
    expected_attack_version: int,
) -> AttackState:
    attack = activation.attack
    if attack is None:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    if (
        type(attack_id) is not int
        or attack_id < 1
        or type(expected_attack_version) is not int
        or expected_attack_version < 1
        or attack.attack_id != attack_id
        or attack.version != expected_attack_version
    ):
        _reject(ActivationProtocolErrorReason.STALE_ATTACK)
    return attack


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


def _clone_dice(
    dice: DeterministicDice,
    *,
    reason: ActivationProtocolErrorReason,
) -> DeterministicDice:
    if type(dice) is not DeterministicDice:
        _reject(reason)
    try:
        return DeterministicDice.from_checkpoint(dice.to_checkpoint())
    except Exception as exc:
        raise ActivationProtocolError(reason) from exc


def _canonical_weapon(
    actor: UnitBlob,
    *,
    weapon_slug: str,
    ranged: bool,
) -> WeaponProfile:
    if type(weapon_slug) is not str or not weapon_slug or len(weapon_slug) > 128:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    inventory = actor.ranged_weapons if ranged else actor.melee_weapons
    candidates = tuple(
        profile
        for profile in inventory
        if type(profile) is WeaponProfile and profile.slug == weapon_slug
    )
    if not candidates or any(
        not _same_weapon_profile(profile, candidates[0])
        for profile in candidates[1:]
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    return candidates[0]


def _same_weapon_profile(left: WeaponProfile, right: WeaponProfile) -> bool:
    """Compare canonical profiles without Python's bool/int or int/float coercion."""

    return all(
        type(getattr(left, field_.name)) is type(getattr(right, field_.name))
        and getattr(left, field_.name) == getattr(right, field_.name)
        for field_ in fields(WeaponProfile)
    )


def _canonical_attack_intent(
    state: BattleState,
    activation: ActivationState,
    action: Action,
) -> ShootAttackIntent | ChargeAttackIntent:
    if type(action) not in (ShootAction, ChargeAction):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    try:
        action_to_json(action)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    action_type = ACTION_TYPE_BY_CLASS[type(action)]
    if (
        type(action.unit_id) is not int
        or action.unit_id != activation.selected_unit_id
        or type(action.target_id) is not int
        or action.target_id < 0
        or type(action.weapon) is not WeaponProfile
        or not can_append_activation_action_type(action_type, activation.action_types)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    try:
        _validate_action(state, action)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    actor = next((blob for blob in state.blobs if blob.id == action.unit_id), None)
    target = next((blob for blob in state.blobs if blob.id == action.target_id), None)
    if (
        actor is None
        or target is None
        or actor.models_alive <= 0
        or actor.location is not Lokalizacja.FRONT
        or target.models_alive <= 0
        or target.location is not Lokalizacja.FRONT
        or type(actor.owner_player) is not int
        or actor.owner_player not in (0, 1)
        or type(target.owner_player) is not int
        or target.owner_player not in (0, 1)
        or target.owner_player == actor.owner_player
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    canonical_weapon = _canonical_weapon(
        actor,
        weapon_slug=action.weapon.slug,
        ranged=type(action) is ShootAction,
    )
    if not _same_weapon_profile(action.weapon, canonical_weapon):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    if type(action) is ShootAction:
        return ShootAttackIntent(
            attacker_unit_id=action.unit_id,
            target_unit_id=action.target_id,
            weapon_slug=canonical_weapon.slug,
        )
    if type(action.counter_attack_declared) is not bool:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    return ChargeAttackIntent(
        attacker_unit_id=action.unit_id,
        target_unit_id=action.target_id,
        weapon_slug=canonical_weapon.slug,
        counter_attack_declared=action.counter_attack_declared,
    )


def _canonical_action_from_attack(
    state: BattleState,
    activation: ActivationState,
    attack: AttackState,
) -> Action:
    actor = next(
        (blob for blob in state.blobs if blob.id == attack.intent.attacker_unit_id),
        None,
    )
    if actor is None:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    if type(attack.intent) is ShootAttackIntent:
        action: Action = ShootAction(
            unit_id=attack.intent.attacker_unit_id,
            target_id=attack.intent.target_unit_id,
            weapon=_canonical_weapon(
                actor,
                weapon_slug=attack.intent.weapon_slug,
                ranged=True,
            ),
        )
    elif type(attack.intent) is ChargeAttackIntent:
        action = ChargeAction(
            unit_id=attack.intent.attacker_unit_id,
            target_id=attack.intent.target_unit_id,
            weapon=_canonical_weapon(
                actor,
                weapon_slug=attack.intent.weapon_slug,
                ranged=False,
            ),
            counter_attack_declared=attack.intent.counter_attack_declared,
        )
    else:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    if _canonical_attack_intent(state, activation, action) != attack.intent:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    return action


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
    dice: DeterministicDice,
    sequence: int,
    outcome_executor: ActivationInterruptOutcomeExecutor,
) -> tuple[tuple[BattleEvent, ...], BattleState]:
    try:
        result = outcome_executor(
            state=protocol_state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
            dice=dice,
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
    dice: DeterministicDice,
    sequence: int,
    outcome_executor: ActivationInterruptOutcomeExecutor,
) -> ActivationInterruptTransitionResult:
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
        or type(dice) is not DeterministicDice
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
    working_dice = _clone_dice(
        dice,
        reason=ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
    )
    outcome_events, replay_state = _validated_interrupt_outcomes(
        protocol_state,
        source=source,
        ability_slug=ability_slug,
        payload=payload,
        dice=working_dice,
        sequence=sequence + 1,
        outcome_executor=outcome_executor,
    )
    events = (protocol_event, *outcome_events)
    return ActivationInterruptTransitionResult(
        state=replay_state,
        events=events,
        next_sequence=sequence + len(events),
        dice=working_dice,
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

    working_dice = _clone_dice(
        dice,
        reason=ActivationProtocolErrorReason.ILLEGAL_ACTION,
    )
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


def _declare_activation_attack(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    action: ShootAction | ChargeAction,
    dice: DeterministicDice,
    sequence: int,
) -> ActivationActionTransitionResult:
    """Persist one canonical attack intent without resolving it or moving RNG."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    if activation.phase is not ActivationPhase.ACTION_READY:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    _require_caller(caller_player, activation.controlling_player)
    if type(sequence) is not int or sequence < 1:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    intent = _canonical_attack_intent(state, activation, action)
    working_dice = _clone_dice(
        dice,
        reason=ActivationProtocolErrorReason.ILLEGAL_ACTION,
    )

    activation_version = activation.version + 1
    attack_id = sequence
    attack_ordinal = activation.action_count + 1
    events: tuple[BattleEvent, ...] = (
        AttackDeclared(
            sequence=sequence,
            activation_id=activation.activation_id,
            activation_version=activation_version,
            attack_id=attack_id,
            attack_version=1,
            attack_ordinal=attack_ordinal,
            intent=intent,
        ),
        AttackInterruptWindowOpened(
            sequence=sequence + 1,
            activation_id=activation.activation_id,
            activation_version=activation_version,
            attack_id=attack_id,
            attack_version=1,
            attack_ordinal=attack_ordinal,
            window_version=1,
            priority_player=activation.initiative_player,
        ),
    )
    try:
        result_state = apply_events(state, events)
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    return ActivationActionTransitionResult(
        state=result_state,
        events=events,
        next_sequence=sequence + len(events),
        dice=working_dice,
    )


def _commit_activation_action_v3(
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
    """Private v3 action dispatch: declare attacks, resolve nonattacks as v2."""

    if type(action) in (ShootAction, ChargeAction):
        return _declare_activation_attack(
            state,
            caller_player=caller_player,
            activation_id=activation_id,
            expected_activation_version=expected_activation_version,
            action=action,
            dice=dice,
            sequence=sequence,
        )
    return commit_activation_action(
        state,
        caller_player=caller_player,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
        action=action,
        dice=dice,
        sequence=sequence,
        outcome_executor=outcome_executor,
    )


def _pass_attack_interrupt_priority(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    attack_id: int,
    expected_attack_version: int,
    expected_window_version: int,
    sequence: int,
) -> ActivationTransitionResult:
    """Record one explicit attack-scope pass, handing off or closing."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    attack = _require_attack(
        activation,
        attack_id=attack_id,
        expected_attack_version=expected_attack_version,
    )
    window = attack.window
    if activation.phase is not ActivationPhase.ATTACK_WINDOW or window is None:
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    if (
        type(expected_window_version) is not int
        or expected_window_version < 1
        or window.version != expected_window_version
    ):
        _reject(ActivationProtocolErrorReason.STALE_WINDOW)
    _require_caller(caller_player, window.priority_player)
    if type(sequence) is not int or sequence < 1:
        _reject(ActivationProtocolErrorReason.ILLEGAL_INTERRUPT)

    activation_version = activation.version + 1
    attack_version = attack.version + 1
    window_version = window.version + 1
    closing = bool(window.passed_players)
    pass_event = AttackInterruptPriorityPassed(
        sequence=sequence,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        attack_id=attack.attack_id,
        attack_version=attack_version,
        attack_ordinal=attack.ordinal,
        window_version=window_version,
        passed_player=caller_player,
        next_priority_player=None if closing else 1 - caller_player,
    )
    if not closing:
        return _result(state, (pass_event,), sequence=sequence)
    close_event = AttackInterruptWindowClosed(
        sequence=sequence + 1,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        attack_id=attack.attack_id,
        attack_version=attack_version,
        attack_ordinal=attack.ordinal,
        window_version=window_version,
    )
    return _result(state, (pass_event, close_event), sequence=sequence)


def _resolve_activation_attack(
    state: BattleState,
    *,
    caller_player: int,
    activation_id: int,
    expected_activation_version: int,
    attack_id: int,
    expected_attack_version: int,
    dice: DeterministicDice,
    sequence: int,
    outcome_executor: ActivationActionOutcomeExecutor = _execute_single_action_outcomes,
) -> ActivationActionTransitionResult:
    """Resolve one closed v3 attack from canonical inventory on a private RNG."""

    _require_protocol_v2(state)
    activation = _require_activation(
        state,
        activation_id=activation_id,
        expected_activation_version=expected_activation_version,
    )
    attack = _require_attack(
        activation,
        attack_id=attack_id,
        expected_attack_version=expected_attack_version,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_RESOLUTION_READY
        or attack.window is not None
    ):
        _reject(ActivationProtocolErrorReason.INVALID_PHASE)
    _require_caller(caller_player, activation.controlling_player)
    if (
        type(sequence) is not int
        or sequence < 1
        or not callable(outcome_executor)
    ):
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)

    action = _canonical_action_from_attack(state, activation, attack)
    action_type = ACTION_TYPE_BY_CLASS[type(action)]
    working_dice = _clone_dice(
        dice,
        reason=ActivationProtocolErrorReason.ILLEGAL_ACTION,
    )
    outcome_state, outcome_events, next_sequence = _validated_action_outcomes(
        state,
        action=action,
        dice=working_dice,
        sequence=sequence,
        outcome_executor=outcome_executor,
    )
    if len(outcome_events) + 2 > _MAX_ATTACK_RESOLUTION_EVENTS:
        _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)

    activation_version = activation.version + 1
    resolved = AttackResolved(
        sequence=next_sequence,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        attack_id=attack.attack_id,
        attack_version=attack.version + 1,
        attack_ordinal=attack.ordinal,
    )
    committed = ActivationActionCommitted(
        sequence=next_sequence + 1,
        activation_id=activation.activation_id,
        activation_version=activation_version,
        action_type=action_type,
    )
    events = (*outcome_events, resolved, committed)
    try:
        result_state = apply_events(outcome_state, (resolved, committed))
        if result_state != apply_events(state, events):
            _reject(ActivationProtocolErrorReason.ILLEGAL_ACTION)
    except ActivationProtocolError:
        raise
    except Exception as exc:
        raise ActivationProtocolError(
            ActivationProtocolErrorReason.ILLEGAL_ACTION
        ) from exc
    return ActivationActionTransitionResult(
        state=result_state,
        events=events,
        next_sequence=next_sequence + 2,
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
    "ActivationInterruptTransitionResult",
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
