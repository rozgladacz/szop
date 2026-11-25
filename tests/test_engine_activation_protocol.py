from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace

import pytest

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    _commit_activation_action_v3,
    _pass_attack_interrupt_priority,
    _resolve_activation_attack,
    _trigger_attack_interrupt,
    commit_activation_action,
    continue_activation,
    finalize_activation,
    pass_interrupt_priority,
    start_activation,
    trigger_activation_interrupt,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.interrupts import (
    READY_INTERRUPT_HANDLERS,
    execute_ready_activation_interrupt_outcomes,
)
from app.services.engine.events import (
    ActivePlayerChanged,
    AttackAbilityOverrideApplied,
    AttackDeclared,
    AttackInterruptPriorityPassed,
    AttackInterruptTriggered,
    AttackInterruptWindowClosed,
    AttackInterruptWindowOpened,
    AttackResolved,
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    EffectApplied,
    InitiativeTransferred,
    InterruptTriggered,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    MeleeBalanceReset,
    MeleeResolved,
    MoveExecuted,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
    event_to_json,
)
from app.services.engine.state import (
    ActivationPhase,
    BattleState,
    Lokalizacja,
    Position,
    UnitBlob,
    WeaponProfile,
    apply_events,
    effective_passives,
    effective_attack_passives,
)
from app.services.engine.state_codec import (
    _battle_state_from_json_v3,
    _battle_state_to_json_v3,
    battle_state_from_json,
    battle_state_to_json,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
    STATUS_WYCZERPANY,
)

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
SWORD = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)


def _unit(
    unit_id: int,
    owner_player: int,
    *,
    models_alive: int = 1,
    location: Lokalizacja = Lokalizacja.FRONT,
    status_flags: tuple[str, ...] = (),
    passives: tuple[str, ...] = (),
) -> UnitBlob:
    return UnitBlob(
        id=unit_id,
        owner_player=owner_player,
        position=Position(float(unit_id), 0),
        radius_inches=1,
        models_alive=models_alive,
        toughness_per_model=3,
        status_flags=status_flags,
        location=location,
        passives=passives,
    )


def _idle_state(
    *,
    initiative_player: int | None = 0,
    active_player: int = 0,
    own_statuses: tuple[str, ...] = (),
    own_passives: tuple[str, ...] = ("test_interrupt",),
    enemy_passives: tuple[str, ...] = ("test_interrupt",),
) -> BattleState:
    return BattleState(
        round=1,
        active_player=active_player,
        activations_remaining=(1, 1),
        blobs=(
            _unit(11, 0, status_flags=own_statuses, passives=own_passives),
            _unit(21, 1, passives=enemy_passives),
        ),
        terrain=(),
        initiative_player=initiative_player,
    )


def _closed_first_window(*, sequence: int = 10):
    started = start_activation(
        _idle_state(),
        selected_unit_id=11,
        sequence=sequence,
    )
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=started.state.activation.activation_id,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )
    second_pass = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=2,
        expected_window_version=2,
        sequence=first_pass.next_sequence,
    )
    return started, first_pass, second_pass


def _after_first_action(*, sequence: int = 10):
    started, first_pass, closed = _closed_first_window(sequence=sequence)
    activation = closed.state.activation
    committed = ActivationActionCommitted(
        sequence=closed.next_sequence,
        activation_id=activation.activation_id,
        activation_version=activation.version + 1,
        action_type="defend",
    )
    state = apply_events(closed.state, (committed,))
    return started, first_pass, closed, committed, state


def _restart(state: BattleState) -> BattleState:
    payload = json.loads(json.dumps(battle_state_to_json(state, version=2)))
    return battle_state_from_json(payload)


def _restart_v3(state: BattleState) -> BattleState:
    payload = json.loads(json.dumps(_battle_state_to_json_v3(state)))
    return _battle_state_from_json_v3(payload)


def _action_idle_state(
    *,
    actor_statuses: tuple[str, ...] = (),
    actor_overrides: tuple[tuple[str, bool], ...] = (),
) -> BattleState:
    actor = replace(
        _unit(11, 0, models_alive=5, status_flags=actor_statuses),
        position=Position(0, 0),
        ranged_weapons=(RIFLE,),
        melee_weapons=(SWORD,),
        ability_overrides=actor_overrides,
    )
    target = replace(
        _unit(21, 1, models_alive=20),
        position=Position(6, 0),
        melee_weapons=(SWORD,),
    )
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(actor, target),
        terrain=(),
        initiative_player=0,
        initial_toughness_snapshot=((11, 15), (21, 60)),
    )


def _ready_for_action(
    *,
    state: BattleState | None = None,
    sequence: int = 800,
):
    started = start_activation(
        _action_idle_state() if state is None else state,
        selected_unit_id=11,
        sequence=sequence,
    )
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=started.state.activation.activation_id,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )
    return pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=2,
        expected_window_version=2,
        sequence=first_pass.next_sequence,
    )


def _ready_for_second_action(first_result):
    continued = continue_activation(
        first_result.state,
        caller_player=0,
        activation_id=first_result.state.activation.activation_id,
        expected_activation_version=first_result.state.activation.version,
        sequence=first_result.next_sequence,
    )
    first_pass = pass_interrupt_priority(
        continued.state,
        caller_player=0,
        activation_id=continued.state.activation.activation_id,
        expected_activation_version=continued.state.activation.version,
        expected_window_version=1,
        sequence=continued.next_sequence,
    )
    return pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )


def _commit(
    state: BattleState,
    action,
    dice: DeterministicDice,
    *,
    sequence: int,
    caller_player: int = 0,
    expected_activation_version: int | None = None,
    outcome_executor=None,
):
    activation = state.activation
    kwargs = {}
    if outcome_executor is not None:
        kwargs["outcome_executor"] = outcome_executor
    return commit_activation_action(
        state,
        caller_player=caller_player,
        activation_id=activation.activation_id,
        expected_activation_version=(
            activation.version
            if expected_activation_version is None
            else expected_activation_version
        ),
        action=action,
        dice=dice,
        sequence=sequence,
        **kwargs,
    )


def _commit_v3(
    state: BattleState,
    action,
    dice: DeterministicDice,
    *,
    sequence: int,
    caller_player: int = 0,
    expected_activation_version: int | None = None,
    outcome_executor=None,
):
    activation = state.activation
    kwargs = {}
    if outcome_executor is not None:
        kwargs["outcome_executor"] = outcome_executor
    return _commit_activation_action_v3(
        state,
        caller_player=caller_player,
        activation_id=activation.activation_id,
        expected_activation_version=(
            activation.version
            if expected_activation_version is None
            else expected_activation_version
        ),
        action=action,
        dice=dice,
        sequence=sequence,
        **kwargs,
    )


def _pass_attack(
    state: BattleState,
    *,
    caller_player: int,
    sequence: int,
):
    activation = state.activation
    attack = activation.attack
    return _pass_attack_interrupt_priority(
        state,
        caller_player=caller_player,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        attack_id=attack.attack_id,
        expected_attack_version=attack.version,
        expected_window_version=attack.window.version,
        sequence=sequence,
    )


def _resolve_attack(
    state: BattleState,
    dice: DeterministicDice,
    *,
    sequence: int,
    caller_player: int = 0,
    outcome_executor=None,
):
    activation = state.activation
    attack = activation.attack
    kwargs = {}
    if outcome_executor is not None:
        kwargs["outcome_executor"] = outcome_executor
    return _resolve_activation_attack(
        state,
        caller_player=caller_player,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        attack_id=attack.attack_id,
        expected_attack_version=attack.version,
        dice=dice,
        sequence=sequence,
        **kwargs,
    )


def _finalize(
    state: BattleState,
    *,
    sequence: int,
    caller_player: int = 0,
    activation_id: int | None = None,
    expected_activation_version: int | None = None,
    recovery_uses: tuple[object, ...] = (),
    outcome_executor=None,
):
    activation = state.activation
    kwargs = {}
    if outcome_executor is not None:
        kwargs["recovery_outcome_executor"] = outcome_executor
    return finalize_activation(
        state,
        caller_player=caller_player,
        activation_id=(
            activation.activation_id if activation_id is None else activation_id
        ),
        expected_activation_version=(
            activation.version
            if expected_activation_version is None
            else expected_activation_version
        ),
        recovery_uses=recovery_uses,
        sequence=sequence,
        **kwargs,
    )


def _assert_rejected(
    state: BattleState,
    reason: ActivationProtocolErrorReason,
    operation,
) -> None:
    original = state
    with pytest.raises(ActivationProtocolError) as exc_info:
        operation()
    assert exc_info.value.reason is reason
    assert not hasattr(exc_info.value, "events")
    assert state is original
    assert state == original


def _fake_outcome_executor(
    *,
    state: BattleState,
    source: UnitBlob,
    ability_slug: str,
    payload,
    dice: DeterministicDice,
    sequence: int,
):
    del dice
    target_id = payload.get("target_id", source.id)
    events = (
        InterruptTriggered(
            sequence=sequence,
            interrupt_point="before_action",
            slug=ability_slug,
            source_unit_id=source.id,
            target_unit_id=target_id,
        ),
        AbilityOverrideApplied(
            sequence=sequence + 1,
            target_id=target_id,
            ability=payload.get("ability", "nieustraszony"),
            granted=True,
            source_id=source.id,
        ),
    )
    return apply_events(state, events), events


def _trigger(
    state: BattleState,
    *,
    caller_player: int,
    source_unit_id: int,
    sequence: int,
    outcome_executor=_fake_outcome_executor,
    ability_slug: str = "test_interrupt",
    payload=None,
    dice: DeterministicDice | None = None,
):
    activation = state.activation
    return trigger_activation_interrupt(
        state,
        caller_player=caller_player,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        expected_window_version=activation.window.version,
        source_unit_id=source_unit_id,
        ability_slug=ability_slug,
        payload={} if payload is None else payload,
        dice=DeterministicDice(2026) if dice is None else dice,
        sequence=sequence,
        outcome_executor=outcome_executor,
    )


def test_start_activation_emits_atomic_batch_and_replays_state() -> None:
    initial = _idle_state(own_statuses=(STATUS_PRZYGOTOWANY,))

    result = start_activation(initial, selected_unit_id=11, sequence=40)

    assert [type(event) for event in result.events] == [
        ActivationStarted,
        StatusRemoved,
        InterruptWindowOpened,
    ]
    assert [event.sequence for event in result.events] == [40, 41, 42]
    assert result.next_sequence == 43
    assert result.events[0].activation_id == 40
    assert result.events[0].activation_version == 1
    assert result.events[2].window_ordinal == 1
    assert result.events[2].window_version == 1
    assert result.events[2].priority_player == initial.initiative_player
    assert result.state == apply_events(initial, result.events)
    selected = next(blob for blob in result.state.blobs if blob.id == 11)
    assert STATUS_PRZYGOTOWANY not in selected.status_flags
    assert result.state.activation.phase is ActivationPhase.BEFORE_ACTION


def test_first_pass_only_hands_priority_to_the_other_player() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=70)
    activation = started.state.activation

    result = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        expected_window_version=activation.window.version,
        sequence=started.next_sequence,
    )

    assert len(result.events) == 1
    assert type(result.events[0]) is InterruptPriorityPassed
    assert result.events[0].next_priority_player == 1
    assert result.next_sequence == started.next_sequence + 1
    assert result.state == apply_events(started.state, result.events)
    assert result.state.activation.version == 2
    assert result.state.activation.window.priority_player == 1
    assert result.state.activation.window.passed_players == (0,)
    assert result.state.activation.window.interrupt_count == 0


def test_first_pass_preserves_accepted_interrupt_count() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=80)
    interrupted_event = ActivationInterruptTriggered(
        sequence=started.next_sequence,
        activation_id=started.state.activation.activation_id,
        activation_version=2,
        window_ordinal=1,
        window_version=2,
        priority_player=0,
    )
    interrupted = apply_events(started.state, (interrupted_event,))

    result = pass_interrupt_priority(
        interrupted,
        caller_player=0,
        activation_id=interrupted.activation.activation_id,
        expected_activation_version=2,
        expected_window_version=2,
        sequence=interrupted_event.sequence + 1,
    )

    assert result.state.activation.window.interrupt_count == 1
    assert result.state.activation.window.version == 3
    assert result.state.activation.window.passed_players == (0,)


def test_second_pass_closes_window_without_automatic_opponent_pass() -> None:
    _, first_pass, _ = _closed_first_window(sequence=90)
    activation = first_pass.state.activation

    result = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        expected_window_version=activation.window.version,
        sequence=first_pass.next_sequence,
    )

    assert [type(event) for event in result.events] == [
        InterruptPriorityPassed,
        InterruptWindowClosed,
    ]
    assert result.events[0].next_priority_player is None
    assert {event.activation_version for event in result.events} == {3}
    assert {event.window_version for event in result.events} == {3}
    assert result.state == apply_events(first_pass.state, result.events)
    assert result.state.activation.phase is ActivationPhase.ACTION_READY
    assert result.state.activation.window is None


def test_continue_activation_opens_second_window_from_initiative_snapshot() -> None:
    initial = _idle_state(initiative_player=1, active_player=0)
    started = start_activation(initial, selected_unit_id=11, sequence=110)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=1,
        activation_id=110,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )
    closed = pass_interrupt_priority(
        first_pass.state,
        caller_player=0,
        activation_id=110,
        expected_activation_version=2,
        expected_window_version=2,
        sequence=first_pass.next_sequence,
    )
    activation = closed.state.activation
    committed = ActivationActionCommitted(
        closed.next_sequence,
        110,
        activation.version + 1,
        "defend",
    )
    awaiting = apply_events(closed.state, (committed,))

    result = continue_activation(
        awaiting,
        caller_player=0,
        activation_id=110,
        expected_activation_version=awaiting.activation.version,
        sequence=committed.sequence + 1,
    )

    assert [type(event) for event in result.events] == [
        ActivationContinuationChosen,
        InterruptWindowOpened,
    ]
    assert result.events[0].continue_activation is True
    assert result.events[1].window_ordinal == 2
    assert result.events[1].priority_player == 1
    assert result.state == apply_events(awaiting, result.events)
    assert result.state.activation.action_count == 1
    assert result.state.activation.window.passed_players == ()
    assert result.state.activation.window.interrupt_count == 0


@pytest.mark.parametrize("checkpoint", ["start", "first-pass", "second-pass", "continue"])
def test_v2_checkpoint_restart_preserves_the_same_next_transition(checkpoint) -> None:
    started, first_pass, closed, committed, awaiting = _after_first_action()
    if checkpoint == "start":
        state = _idle_state()
        operation = lambda current: start_activation(
            current,
            selected_unit_id=11,
            sequence=200,
        )
    elif checkpoint == "first-pass":
        state = started.state
        operation = lambda current: pass_interrupt_priority(
            current,
            caller_player=0,
            activation_id=current.activation.activation_id,
            expected_activation_version=current.activation.version,
            expected_window_version=current.activation.window.version,
            sequence=started.next_sequence,
        )
    elif checkpoint == "second-pass":
        state = first_pass.state
        operation = lambda current: pass_interrupt_priority(
            current,
            caller_player=1,
            activation_id=current.activation.activation_id,
            expected_activation_version=current.activation.version,
            expected_window_version=current.activation.window.version,
            sequence=first_pass.next_sequence,
        )
    else:
        state = awaiting
        operation = lambda current: continue_activation(
            current,
            caller_player=0,
            activation_id=current.activation.activation_id,
            expected_activation_version=current.activation.version,
            sequence=committed.sequence + 1,
        )

    live_result = operation(state)
    restarted_result = operation(_restart(state))

    assert [event_to_json(event) for event in restarted_result.events] == [
        event_to_json(event) for event in live_result.events
    ]
    assert restarted_result.state == live_result.state
    assert restarted_result.next_sequence == live_result.next_sequence


def test_end_to_end_control_plane_sequence_through_second_window_close() -> None:
    initial = _idle_state(initiative_player=1, active_player=0)
    all_events = []

    started = start_activation(initial, selected_unit_id=11, sequence=300)
    all_events.extend(started.events)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=1,
        activation_id=300,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )
    all_events.extend(first_pass.events)
    first_closed = pass_interrupt_priority(
        first_pass.state,
        caller_player=0,
        activation_id=300,
        expected_activation_version=2,
        expected_window_version=2,
        sequence=first_pass.next_sequence,
    )
    all_events.extend(first_closed.events)
    first_activation = first_closed.state.activation
    committed = ActivationActionCommitted(
        first_closed.next_sequence,
        300,
        first_activation.version + 1,
        "defend",
    )
    awaiting = apply_events(first_closed.state, (committed,))
    all_events.append(committed)
    continued = continue_activation(
        awaiting,
        caller_player=0,
        activation_id=300,
        expected_activation_version=awaiting.activation.version,
        sequence=committed.sequence + 1,
    )
    all_events.extend(continued.events)
    second_pass = pass_interrupt_priority(
        continued.state,
        caller_player=1,
        activation_id=300,
        expected_activation_version=continued.state.activation.version,
        expected_window_version=1,
        sequence=continued.next_sequence,
    )
    all_events.extend(second_pass.events)
    second_closed = pass_interrupt_priority(
        second_pass.state,
        caller_player=0,
        activation_id=300,
        expected_activation_version=second_pass.state.activation.version,
        expected_window_version=2,
        sequence=second_pass.next_sequence,
    )
    all_events.extend(second_closed.events)

    assert [event.sequence for event in all_events] == list(
        range(300, second_closed.next_sequence)
    )
    assert second_closed.state == apply_events(initial, all_events)
    assert second_closed.state.activation.phase is ActivationPhase.ACTION_READY
    assert second_closed.state.activation.action_count == 1
    assert second_closed.state.activation.window is None


@pytest.mark.parametrize(
    ("selected_unit_id", "state_factory"),
    [
        (999, _idle_state),
        (21, _idle_state),
        (
            11,
            lambda: replace(
                _idle_state(),
                blobs=(_unit(11, 0, models_alive=0, location=Lokalizacja.WYCOFANY), _unit(21, 1)),
            ),
        ),
        (
            11,
            lambda: replace(
                _idle_state(),
                blobs=(_unit(11, 0, location=Lokalizacja.ZAPLECZE), _unit(21, 1)),
            ),
        ),
        (
            11,
            lambda: _idle_state(own_statuses=(STATUS_AKTYWOWANY,)),
        ),
    ],
)
def test_start_rejects_invalid_selection_atomically(
    selected_unit_id,
    state_factory,
) -> None:
    state = state_factory()
    _assert_rejected(
        state,
        ActivationProtocolErrorReason.INVALID_SELECTION,
        lambda: start_activation(
            state,
            selected_unit_id=selected_unit_id,
            sequence=400,
        ),
    )


def test_legacy_state_is_not_implicitly_upgraded_for_any_operation() -> None:
    legacy = _idle_state(initiative_player=None)
    operations = (
        lambda: start_activation(legacy, selected_unit_id=11),
        lambda: pass_interrupt_priority(
            legacy,
            caller_player=0,
            activation_id=1,
            expected_activation_version=1,
            expected_window_version=1,
        ),
        lambda: continue_activation(
            legacy,
            caller_player=0,
            activation_id=1,
            expected_activation_version=1,
        ),
        lambda: trigger_activation_interrupt(
            legacy,
            caller_player=0,
            activation_id=1,
            expected_activation_version=1,
            expected_window_version=1,
            source_unit_id=11,
            ability_slug="test_interrupt",
            payload={},
            dice=DeterministicDice(2026),
            sequence=1,
            outcome_executor=_fake_outcome_executor,
        ),
    )
    for operation in operations:
        _assert_rejected(
            legacy,
            ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED,
            operation,
        )


def test_invalid_phase_and_game_over_start_are_distinct_from_selection() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11)
    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.INVALID_PHASE,
        lambda: start_activation(started.state, selected_unit_id=11),
    )
    game_over = replace(_idle_state(), is_game_over=True)
    _assert_rejected(
        game_over,
        ActivationProtocolErrorReason.INVALID_PHASE,
        lambda: start_activation(game_over, selected_unit_id=11),
    )


def test_pass_rejects_stale_guards_caller_and_phase_atomically() -> None:
    started, _, closed = _closed_first_window()
    activation = started.state.activation
    cases = (
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=0,
                activation_id=activation.activation_id + 1,
                expected_activation_version=activation.version,
                expected_window_version=activation.window.version,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=0,
                activation_id=activation.activation_id,
                expected_activation_version=activation.version + 1,
                expected_window_version=activation.window.version,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=0,
                activation_id=True,
                expected_activation_version=activation.version,
                expected_window_version=activation.window.version,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_WINDOW,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=0,
                activation_id=activation.activation_id,
                expected_activation_version=activation.version,
                expected_window_version=activation.window.version + 1,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_WINDOW,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=0,
                activation_id=activation.activation_id,
                expected_activation_version=activation.version,
                expected_window_version=True,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.INVALID_CALLER,
            lambda: pass_interrupt_priority(
                started.state,
                caller_player=1,
                activation_id=activation.activation_id,
                expected_activation_version=activation.version,
                expected_window_version=activation.window.version,
            ),
            started.state,
        ),
        (
            ActivationProtocolErrorReason.INVALID_PHASE,
            lambda: pass_interrupt_priority(
                closed.state,
                caller_player=0,
                activation_id=closed.state.activation.activation_id,
                expected_activation_version=closed.state.activation.version,
                expected_window_version=3,
            ),
            closed.state,
        ),
    )
    for reason, operation, state in cases:
        _assert_rejected(state, reason, operation)


def test_continue_rejects_stale_caller_phase_and_illegal_choice_atomically() -> None:
    _, _, closed, committed, awaiting = _after_first_action()
    idle = _idle_state()
    cases = (
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda: continue_activation(
                awaiting,
                caller_player=0,
                activation_id=awaiting.activation.activation_id + 1,
                expected_activation_version=awaiting.activation.version,
            ),
            awaiting,
        ),
        (
            ActivationProtocolErrorReason.INVALID_CALLER,
            lambda: continue_activation(
                awaiting,
                caller_player=1,
                activation_id=awaiting.activation.activation_id,
                expected_activation_version=awaiting.activation.version,
            ),
            awaiting,
        ),
        (
            ActivationProtocolErrorReason.ILLEGAL_CONTINUE,
            lambda: continue_activation(
                closed.state,
                caller_player=0,
                activation_id=closed.state.activation.activation_id,
                expected_activation_version=closed.state.activation.version,
                sequence=committed.sequence + 1,
            ),
            closed.state,
        ),
        (
            ActivationProtocolErrorReason.INVALID_PHASE,
            lambda: continue_activation(
                idle,
                caller_player=0,
                activation_id=1,
                expected_activation_version=1,
            ),
            idle,
        ),
    )
    for reason, operation, state in cases:
        _assert_rejected(state, reason, operation)


def test_interrupt_from_initial_priority_is_atomic_and_replay_derived() -> None:
    initial = _idle_state()
    started = start_activation(initial, selected_unit_id=11, sequence=500)

    result = _trigger(
        started.state,
        caller_player=0,
        source_unit_id=11,
        sequence=started.next_sequence,
        payload={"target_id": 11},
    )

    assert [type(event) for event in result.events] == [
        ActivationInterruptTriggered,
        InterruptTriggered,
        AbilityOverrideApplied,
    ]
    assert [event.sequence for event in result.events] == [502, 503, 504]
    assert result.next_sequence == 505
    assert result.state == apply_events(started.state, result.events)
    activation = result.state.activation
    assert activation.version == 2
    assert activation.window.version == 2
    assert activation.window.interrupt_count == 1
    assert activation.window.priority_player == 0
    assert activation.window.passed_players == ()
    assert not hasattr(result.events[0], "source_unit_id")
    assert not hasattr(result.events[0], "ability_slug")


def test_interrupt_after_first_pass_preserves_pass_priority_and_can_then_close() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=510)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=510,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )

    interrupted = _trigger(
        first_pass.state,
        caller_player=1,
        source_unit_id=21,
        sequence=first_pass.next_sequence,
    )

    window = interrupted.state.activation.window
    assert interrupted.state.activation.version == 3
    assert window.version == 3
    assert window.interrupt_count == 1
    assert window.priority_player == 1
    assert window.passed_players == (0,)

    closed = pass_interrupt_priority(
        interrupted.state,
        caller_player=1,
        activation_id=510,
        expected_activation_version=3,
        expected_window_version=3,
        sequence=interrupted.next_sequence,
    )
    assert closed.state.activation.phase is ActivationPhase.ACTION_READY
    assert closed.state.activation.window is None


def test_interrupt_versions_and_count_increase_once_for_multi_event_outcome() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=520)

    result = _trigger(
        started.state,
        caller_player=0,
        source_unit_id=11,
        sequence=started.next_sequence,
    )

    protocol_events = [
        event for event in result.events if type(event) is ActivationInterruptTriggered
    ]
    assert len(protocol_events) == 1
    assert result.state.activation.version == started.state.activation.version + 1
    assert (
        result.state.activation.window.version
        == started.state.activation.window.version + 1
    )
    assert (
        result.state.activation.window.interrupt_count
        == started.state.activation.window.interrupt_count + 1
    )


def test_interrupt_rng_consuming_executor_returns_advanced_private_copy() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=525)
    input_dice = DeterministicDice(2026)
    input_checkpoint = copy.deepcopy(input_dice.to_checkpoint())
    expected_dice = DeterministicDice.from_checkpoint(input_checkpoint)
    expected_rolls = expected_dice.roll_d6(4)
    observed_rolls: tuple[int, ...] | None = None

    def consuming_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        nonlocal observed_rolls
        observed_rolls = dice.roll_d6(4)
        return _fake_outcome_executor(
            state=state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
            dice=dice,
            sequence=sequence,
        )

    result = _trigger(
        started.state,
        caller_player=0,
        source_unit_id=11,
        sequence=started.next_sequence,
        outcome_executor=consuming_executor,
        dice=input_dice,
    )

    assert observed_rolls == expected_rolls
    assert input_dice.to_checkpoint() == input_checkpoint
    assert result.dice is not input_dice
    assert result.dice.to_checkpoint() == expected_dice.to_checkpoint()
    assert result.state == apply_events(started.state, result.events)
    assert result.next_sequence == started.next_sequence + len(result.events)
    future_from_result = DeterministicDice.from_checkpoint(result.dice.to_checkpoint())
    future_from_expected = DeterministicDice.from_checkpoint(
        expected_dice.to_checkpoint()
    )
    assert future_from_result.roll_d6(8) == future_from_expected.roll_d6(8)


@pytest.mark.parametrize(
    "failure",
    ["raise", "malformed", "replay-mismatch", "protocol-event"],
)
def test_interrupt_rng_consumption_is_isolated_on_fail_closed_outcome(
    failure: str,
) -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=527)
    input_dice = DeterministicDice(2026)
    input_checkpoint = copy.deepcopy(input_dice.to_checkpoint())
    consumed_checkpoints: list[dict[str, object]] = []

    def failing_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        dice.roll_d6(3)
        consumed_checkpoints.append(dice.to_checkpoint())
        if failure == "raise":
            raise RuntimeError("after RNG consumption")
        if failure == "malformed":
            return (state,)
        outcome_state, outcome_events = _fake_outcome_executor(
            state=state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
            dice=dice,
            sequence=sequence,
        )
        if failure == "replay-mismatch":
            return state, outcome_events
        activation = state.activation
        nested = ActivationInterruptTriggered(
            sequence=sequence + len(outcome_events),
            activation_id=activation.activation_id,
            activation_version=activation.version + 1,
            window_ordinal=activation.window.ordinal,
            window_version=activation.window.version + 1,
            priority_player=activation.window.priority_player,
        )
        return outcome_state, (*outcome_events, nested)

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=failing_executor,
            dice=input_dice,
        ),
    )
    assert consumed_checkpoints
    assert consumed_checkpoints[0] != input_checkpoint
    assert input_dice.to_checkpoint() == input_checkpoint
    assert started.state.activation.version == 1
    assert started.state.activation.window.interrupt_count == 0


def test_interrupt_limit_64_rejects_before_executor() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=530)
    activation_id = started.state.activation.activation_id
    accepted = tuple(
        ActivationInterruptTriggered(
            sequence=started.next_sequence + index,
            activation_id=activation_id,
            activation_version=2 + index,
            window_ordinal=1,
            window_version=2 + index,
            priority_player=0,
        )
        for index in range(64)
    )
    at_limit = apply_events(started.state, accepted)
    called = False

    def executor(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("executor must not run at the protocol limit")

    _assert_rejected(
        at_limit,
        ActivationProtocolErrorReason.INTERRUPT_LIMIT_REACHED,
        lambda: _trigger(
            at_limit,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence + 64,
            outcome_executor=executor,
        ),
    )
    assert called is False


@pytest.mark.parametrize(
    ("source_unit_id", "state_factory"),
    [
        (999, _idle_state),
        (21, _idle_state),
        (
            12,
            lambda: replace(
                _idle_state(),
                blobs=_idle_state().blobs
                + (
                    _unit(
                        12,
                        0,
                        models_alive=0,
                        passives=("test_interrupt",),
                    ),
                ),
            ),
        ),
        (
            12,
            lambda: replace(
                _idle_state(),
                blobs=_idle_state().blobs
                + (
                    _unit(
                        12,
                        0,
                        location=Lokalizacja.ZAPLECZE,
                        passives=("test_interrupt",),
                    ),
                ),
            ),
        ),
        (
            12,
            lambda: replace(
                _idle_state(),
                blobs=_idle_state().blobs + (_unit(12, 0, passives=()),),
            ),
        ),
    ],
)
def test_interrupt_rejects_missing_wrong_owner_dead_off_field_or_missing_passive(
    source_unit_id,
    state_factory,
) -> None:
    started = start_activation(state_factory(), selected_unit_id=11, sequence=600)
    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=source_unit_id,
            sequence=started.next_sequence,
        ),
    )


def test_interrupt_rejects_stale_guards_wrong_priority_and_wrong_phase() -> None:
    started, _, closed = _closed_first_window(sequence=610)
    activation = started.state.activation
    common = {
        "state": started.state,
        "caller_player": 0,
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
        "expected_window_version": activation.window.version,
        "source_unit_id": 11,
        "ability_slug": "test_interrupt",
        "payload": {},
        "dice": DeterministicDice(2026),
        "sequence": started.next_sequence,
        "outcome_executor": _fake_outcome_executor,
    }
    cases = (
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            {**common, "activation_id": activation.activation_id + 1},
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            {**common, "expected_activation_version": activation.version + 1},
            started.state,
        ),
        (
            ActivationProtocolErrorReason.STALE_WINDOW,
            {**common, "expected_window_version": activation.window.version + 1},
            started.state,
        ),
        (
            ActivationProtocolErrorReason.INVALID_CALLER,
            {**common, "caller_player": 1, "source_unit_id": 21},
            started.state,
        ),
        (
            ActivationProtocolErrorReason.INVALID_PHASE,
            {
                **common,
                "state": closed.state,
                "activation_id": closed.state.activation.activation_id,
                "expected_activation_version": closed.state.activation.version,
                "expected_window_version": 3,
            },
            closed.state,
        ),
    )
    for reason, kwargs, state in cases:
        _assert_rejected(
            state,
            reason,
            lambda kwargs=kwargs: trigger_activation_interrupt(**kwargs),
        )


def test_interrupt_executor_exception_is_fail_closed() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=620)

    def exploding_executor(**_kwargs):
        raise RuntimeError("leaf failed")

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=exploding_executor,
        ),
    )


def test_interrupt_rejects_live_replay_state_mismatch() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=630)

    def mismatched_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        _, events = _fake_outcome_executor(
            state=state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
            dice=dice,
            sequence=sequence,
        )
        return state, events

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=mismatched_executor,
        ),
    )


def test_interrupt_rejects_non_contiguous_outcome_sequence() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=640)

    def skipped_sequence_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        del dice
        events = (
            InterruptTriggered(
                sequence + 1,
                "before_action",
                ability_slug,
                source.id,
            ),
        )
        return apply_events(state, events), events

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=skipped_sequence_executor,
        ),
    )


@pytest.mark.parametrize("marker_count", [0, 2])
def test_interrupt_requires_exactly_one_interrupt_triggered(marker_count) -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=650)

    def marker_count_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        del dice
        events = tuple(
            InterruptTriggered(
                sequence + index,
                "before_action",
                ability_slug,
                source.id,
            )
            for index in range(marker_count)
        )
        if not events:
            events = (
                AbilityOverrideApplied(
                    sequence,
                    source.id,
                    "nieustraszony",
                    True,
                    source.id,
                ),
            )
        return apply_events(state, events), events

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=marker_count_executor,
        ),
    )


def test_interrupt_rejects_nested_activation_protocol_event() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=660)

    def nested_executor(*, state, source, ability_slug, payload, dice, sequence):
        del dice
        activation = state.activation
        events = (
            InterruptTriggered(
                sequence,
                "before_action",
                ability_slug,
                source.id,
            ),
            ActivationInterruptTriggered(
                sequence + 1,
                activation.activation_id,
                activation.version + 1,
                activation.window.ordinal,
                activation.window.version + 1,
                activation.window.priority_player,
            ),
        )
        return state, events

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=nested_executor,
        ),
    )


@dataclass(frozen=True)
class _UnsupportedOutcomeEvent:
    sequence: int
    version: int = 1


@pytest.mark.parametrize(
    "event_factory",
    [
        lambda sequence, source_id: _UnsupportedOutcomeEvent(sequence),
        lambda sequence, source_id: object(),
        lambda sequence, source_id: InterruptTriggered(
            sequence,
            "before_action",
            "test_interrupt",
            source_id,
            version=2,
        ),
        lambda sequence, source_id: InterruptTriggered(
            True,
            "before_action",
            "test_interrupt",
            source_id,
        ),
        lambda sequence, source_id: InterruptTriggered(
            sequence,
            "after_action",
            "test_interrupt",
            source_id,
        ),
        lambda sequence, source_id: InterruptTriggered(
            sequence,
            "before_action",
            "other_slug",
            source_id,
        ),
        lambda sequence, source_id: InterruptTriggered(
            sequence,
            "before_action",
            "test_interrupt",
            True,
        ),
    ],
)
def test_interrupt_rejects_unsupported_malformed_or_noncanonical_event(
    event_factory,
) -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=670)

    def invalid_event_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        del dice
        return state, (event_factory(sequence, source.id),)

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=invalid_event_executor,
        ),
    )


def test_interrupt_rejects_more_than_64_outcome_events() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=680)

    def oversized_executor(
        *, state, source, ability_slug, payload, dice, sequence
    ):
        del dice
        events = (
            InterruptTriggered(
                sequence,
                "before_action",
                ability_slug,
                source.id,
            ),
            *(
                EffectApplied(
                    sequence + index,
                    f"annotation-{index}",
                    source.id,
                    source.id,
                )
                for index in range(1, 65)
            ),
        )
        return apply_events(state, events), events

    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        lambda: _trigger(
            started.state,
            caller_player=0,
            source_unit_id=11,
            sequence=started.next_sequence,
            outcome_executor=oversized_executor,
        ),
    )


@pytest.mark.parametrize(
    "override",
    [
        {"caller_player": True},
        {"activation_id": True},
        {"expected_activation_version": True},
        {"expected_window_version": True},
        {"source_unit_id": True},
        {"ability_slug": 7},
        {"payload": []},
        {"dice": object()},
        {"sequence": True},
        {"outcome_executor": None},
    ],
)
def test_interrupt_rejects_bool_and_non_integer_or_malformed_inputs(override) -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=690)
    activation = started.state.activation
    kwargs = {
        "state": started.state,
        "caller_player": 0,
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
        "expected_window_version": activation.window.version,
        "source_unit_id": 11,
        "ability_slug": "test_interrupt",
        "payload": {},
        "dice": DeterministicDice(2026),
        "sequence": started.next_sequence,
        "outcome_executor": _fake_outcome_executor,
        **override,
    }
    with pytest.raises(ActivationProtocolError):
        trigger_activation_interrupt(**kwargs)
    assert started.state.activation.version == 1
    assert started.state.activation.window.interrupt_count == 0


def test_v2_restart_interrupt_parity_and_later_explicit_close() -> None:
    started = start_activation(_idle_state(), selected_unit_id=11, sequence=700)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=700,
        expected_activation_version=1,
        expected_window_version=1,
        sequence=started.next_sequence,
    )

    live = _trigger(
        first_pass.state,
        caller_player=1,
        source_unit_id=21,
        sequence=first_pass.next_sequence,
    )
    restarted = _trigger(
        _restart(first_pass.state),
        caller_player=1,
        source_unit_id=21,
        sequence=first_pass.next_sequence,
    )

    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in live.events
    ]
    assert restarted.state == live.state
    assert restarted.next_sequence == live.next_sequence

    closed = pass_interrupt_priority(
        restarted.state,
        caller_player=1,
        activation_id=700,
        expected_activation_version=3,
        expected_window_version=3,
        sequence=restarted.next_sequence,
    )
    assert closed.state.activation.phase is ActivationPhase.ACTION_READY
    assert closed.state == apply_events(restarted.state, closed.events)


def test_builtin_rozkaz_full_v2_flow_replay_restart_limit_and_finalization() -> None:
    base = _action_idle_state()
    actor = replace(
        base.blobs[0],
        passives=("rozkaz", "nieustraszony"),
    )
    initial = replace(base, blobs=(actor, base.blobs[1]))
    started = start_activation(initial, selected_unit_id=11, sequence=710)
    payload = {
        "target_id": 11,
        "ability": "nieustraszony",
        "granted": False,
    }

    def trigger(current, dice):
        activation = current.activation
        return trigger_activation_interrupt(
            current,
            caller_player=0,
            activation_id=activation.activation_id,
            expected_activation_version=activation.version,
            expected_window_version=activation.window.version,
            source_unit_id=11,
            ability_slug="rozkaz",
            payload=payload,
            dice=dice,
            sequence=started.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )

    input_dice = DeterministicDice(73)
    input_rng = input_dice.to_checkpoint()
    interrupted = trigger(started.state, input_dice)
    restarted = trigger(
        _restart(started.state),
        DeterministicDice.from_checkpoint(input_rng),
    )
    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in interrupted.events
    ]
    assert restarted.state == interrupted.state
    assert restarted.next_sequence == interrupted.next_sequence
    assert input_dice.to_checkpoint() == input_rng
    assert interrupted.dice.to_checkpoint() == input_rng
    assert restarted.dice.to_checkpoint() == input_rng
    assert [type(event) for event in interrupted.events] == [
        ActivationInterruptTriggered,
        InterruptTriggered,
        AbilityOverrideApplied,
    ]
    interrupted_actor = next(
        blob for blob in interrupted.state.blobs if blob.id == 11
    )
    assert "nieustraszony" not in effective_passives(interrupted_actor)
    assert interrupted.state.used_interrupts_this_round == ((11, "rozkaz"),)

    preserved = interrupted.state
    with pytest.raises(ActivationProtocolError) as exc_info:
        trigger_activation_interrupt(
            preserved,
            caller_player=0,
            activation_id=preserved.activation.activation_id,
            expected_activation_version=preserved.activation.version,
            expected_window_version=preserved.activation.window.version,
            source_unit_id=11,
            ability_slug="rozkaz",
            payload=payload,
            dice=DeterministicDice(73),
            sequence=interrupted.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )
    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert interrupted.state is preserved

    first_pass = pass_interrupt_priority(
        interrupted.state,
        caller_player=0,
        activation_id=interrupted.state.activation.activation_id,
        expected_activation_version=interrupted.state.activation.version,
        expected_window_version=interrupted.state.activation.window.version,
        sequence=interrupted.next_sequence,
    )
    ready = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )
    committed = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(73),
        sequence=ready.next_sequence,
    )
    finalized = _finalize(
        committed.state,
        sequence=committed.next_sequence,
    )
    terminal_actor = next(blob for blob in finalized.state.blobs if blob.id == 11)
    assert terminal_actor.ability_overrides == ()
    complete_tail = tuple(
        event
        for transition in (
            started,
            interrupted,
            first_pass,
            ready,
            committed,
            finalized,
        )
        for event in transition.events
    )
    assert finalized.state == apply_events(initial, complete_tail)


def test_builtin_klatwa_full_v2_flow_replay_restart_limit_and_finalization() -> None:
    base = _action_idle_state()
    source = replace(base.blobs[0], passives=("klatwa",))
    target = replace(base.blobs[1], passives=("delikatny",))
    initial = replace(base, blobs=(source, target))
    started = start_activation(initial, selected_unit_id=11, sequence=760)
    payload = {
        "target_id": target.id,
        "ability": "delikatny",
        "granted": False,
    }

    def trigger(current, dice):
        activation = current.activation
        return trigger_activation_interrupt(
            current,
            caller_player=0,
            activation_id=activation.activation_id,
            expected_activation_version=activation.version,
            expected_window_version=activation.window.version,
            source_unit_id=source.id,
            ability_slug="klatwa",
            payload=payload,
            dice=dice,
            sequence=started.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )

    input_dice = DeterministicDice(79)
    input_rng = input_dice.to_checkpoint()
    interrupted = trigger(started.state, input_dice)
    restarted = trigger(
        _restart(started.state),
        DeterministicDice.from_checkpoint(input_rng),
    )
    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in interrupted.events
    ]
    assert restarted.state == interrupted.state
    assert restarted.next_sequence == interrupted.next_sequence
    assert input_dice.to_checkpoint() == input_rng
    assert interrupted.dice.to_checkpoint() == input_rng
    assert restarted.dice.to_checkpoint() == input_rng
    assert [type(event) for event in interrupted.events] == [
        ActivationInterruptTriggered,
        InterruptTriggered,
        AbilityOverrideApplied,
    ]
    interrupted_target = next(
        blob for blob in interrupted.state.blobs if blob.id == target.id
    )
    assert "delikatny" not in effective_passives(interrupted_target)
    assert interrupted.state.used_interrupts_this_round == ((source.id, "klatwa"),)

    with pytest.raises(ActivationProtocolError) as exc_info:
        trigger_activation_interrupt(
            interrupted.state,
            caller_player=0,
            activation_id=interrupted.state.activation.activation_id,
            expected_activation_version=interrupted.state.activation.version,
            expected_window_version=interrupted.state.activation.window.version,
            source_unit_id=source.id,
            ability_slug="klatwa",
            payload=payload,
            dice=DeterministicDice(79),
            sequence=interrupted.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )
    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT

    first_pass = pass_interrupt_priority(
        interrupted.state,
        caller_player=0,
        activation_id=interrupted.state.activation.activation_id,
        expected_activation_version=interrupted.state.activation.version,
        expected_window_version=interrupted.state.activation.window.version,
        sequence=interrupted.next_sequence,
    )
    ready = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )
    committed = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(79),
        sequence=ready.next_sequence,
    )
    finalized = _finalize(
        committed.state,
        sequence=committed.next_sequence,
    )
    terminal_target = next(
        blob for blob in finalized.state.blobs if blob.id == target.id
    )
    assert terminal_target.ability_overrides == ()
    assert "delikatny" in effective_passives(terminal_target)
    complete_tail = tuple(
        event
        for transition in (
            started,
            interrupted,
            first_pass,
            ready,
            committed,
            finalized,
        )
        for event in transition.events
    )
    assert finalized.state == apply_events(initial, complete_tail)


def test_first_action_bridge_commits_after_outcomes_without_finalizing() -> None:
    ready = _ready_for_action(
        state=_action_idle_state(actor_overrides=(("ordered", True),)),
        sequence=800,
    )
    dice = DeterministicDice(17)
    input_rng = dice.to_checkpoint()

    result = _commit(
        ready.state,
        DefendAction(11),
        dice,
        sequence=ready.next_sequence,
    )

    assert result.events
    assert isinstance(result.events[-1], ActivationActionCommitted)
    assert result.events[-1].action_type == "defend"
    assert [event.sequence for event in result.events] == list(
        range(ready.next_sequence, result.next_sequence)
    )
    assert all(
        not isinstance(event, ActivationActionCommitted)
        for event in result.events[:-1]
    )
    assert result.state == apply_events(ready.state, result.events)
    assert result.state.activation.action_count == 1
    assert result.state.activation.action_types == ("defend",)
    assert result.state.activation.phase is ActivationPhase.AWAITING_CONTINUATION
    assert result.state.active_player == ready.state.active_player == 0
    actor = next(blob for blob in result.state.blobs if blob.id == 11)
    assert STATUS_AKTYWOWANY not in actor.status_flags
    assert actor.ability_overrides == (("ordered", True),)
    assert dice.to_checkpoint() == input_rng


def test_second_action_bridge_uses_durable_history_and_awaits_finalization() -> None:
    ready = _ready_for_action(sequence=830)
    first = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(3),
        sequence=ready.next_sequence,
    )
    second_ready = _ready_for_second_action(first)

    second = _commit(
        second_ready.state,
        ManeuverAction(11, Position(1, 0)),
        first.dice,
        sequence=second_ready.next_sequence,
    )

    assert any(isinstance(event, MoveExecuted) for event in second.events[:-1])
    assert isinstance(second.events[-1], ActivationActionCommitted)
    assert second.events[-1].action_type == "maneuver"
    assert second.state == apply_events(second_ready.state, second.events)
    assert second.state.activation.action_count == 2
    assert second.state.activation.action_types == ("defend", "maneuver")
    assert second.state.activation.phase is ActivationPhase.AWAITING_FINALIZATION
    assert second.state.active_player == 0
    actor = next(blob for blob in second.state.blobs if blob.id == 11)
    assert actor.position == Position(1, 0)
    assert STATUS_AKTYWOWANY not in actor.status_flags


@pytest.mark.parametrize(
    ("action", "action_type"),
    [
        (ManeuverAction(11, Position(1, 0)), "maneuver"),
        (DefendAction(11), "defend"),
        (ShootAction(11, 21, RIFLE), "shoot"),
        (ChargeAction(11, 21, SWORD, counter_attack_declared=False), "charge"),
        (SpecialAction(11, "discard_exhausted"), "special"),
    ],
)
def test_action_bridge_uses_canonical_type_for_representative_actions(
    action,
    action_type: str,
) -> None:
    ready = _ready_for_action(
        state=_action_idle_state(
            actor_statuses=(STATUS_WYCZERPANY,) if action_type == "special" else (),
        ),
        sequence=860,
    )

    result = _commit(
        ready.state,
        action,
        DeterministicDice(29),
        sequence=ready.next_sequence,
    )

    assert result.events[-1].action_type == action_type
    assert result.state.activation.action_types == (action_type,)
    assert result.state.activation.phase is ActivationPhase.AWAITING_CONTINUATION


def test_closed_v3_attack_rechecks_the_current_shooting_lock():
    ready = _ready_for_action(sequence=875)
    dice = DeterministicDice(29)
    rng_before = dice.to_checkpoint()
    declared = _commit_v3(
        ready.state, ShootAction(11, 21, RIFLE), dice, sequence=ready.next_sequence,
    )
    first = _pass_attack(declared.state, caller_player=0, sequence=declared.next_sequence)
    closed = _pass_attack(first.state, caller_player=1, sequence=first.next_sequence)
    actor, target = closed.state.blobs
    locked = replace(closed.state, blobs=(actor, replace(target, position=Position(2, 0))))
    before = _battle_state_to_json_v3(locked)
    with pytest.raises(ActivationProtocolError) as exc:
        _resolve_attack(locked, dice, sequence=closed.next_sequence)
    assert exc.value.reason is ActivationProtocolErrorReason.ILLEGAL_ACTION
    assert _battle_state_to_json_v3(locked) == before
    assert dice.to_checkpoint() == rng_before
    resolved = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    assert resolved.state == apply_events(closed.state, resolved.events)


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"caller_player": 1}, ActivationProtocolErrorReason.INVALID_CALLER),
        (
            {"expected_activation_version": 1},
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            {"action": DefendAction(21)},
            ActivationProtocolErrorReason.ILLEGAL_ACTION,
        ),
    ],
)
def test_action_bridge_rejects_wrong_caller_version_or_selected_unit_atomically(
    override,
    reason: ActivationProtocolErrorReason,
) -> None:
    ready = _ready_for_action(sequence=890)
    dice = DeterministicDice(31)
    rng_before = dice.to_checkpoint()
    kwargs = {
        "state": ready.state,
        "caller_player": 0,
        "activation_id": ready.state.activation.activation_id,
        "expected_activation_version": ready.state.activation.version,
        "action": DefendAction(11),
        "dice": dice,
        "sequence": ready.next_sequence,
        **override,
    }

    _assert_rejected(
        ready.state,
        reason,
        lambda: commit_activation_action(**kwargs),
    )
    assert dice.to_checkpoint() == rng_before


def test_action_bridge_rejects_v1_wrong_phase_and_third_action() -> None:
    dice = DeterministicDice(37)
    with pytest.raises(ActivationProtocolError) as v1_error:
        commit_activation_action(
            _idle_state(initiative_player=None),
            caller_player=0,
            activation_id=1,
            expected_activation_version=1,
            action=DefendAction(11),
            dice=dice,
            sequence=1,
        )
    assert (
        v1_error.value.reason
        is ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED
    )

    started = start_activation(
        _action_idle_state(),
        selected_unit_id=11,
        sequence=920,
    )
    _assert_rejected(
        started.state,
        ActivationProtocolErrorReason.INVALID_PHASE,
        lambda: _commit(
            started.state,
            DefendAction(11),
            dice,
            sequence=started.next_sequence,
        ),
    )

    first_ready = _ready_for_action(sequence=930)
    first = _commit(
        first_ready.state,
        DefendAction(11),
        DeterministicDice(41),
        sequence=first_ready.next_sequence,
    )
    second_ready = _ready_for_second_action(first)
    second = _commit(
        second_ready.state,
        ManeuverAction(11, Position(1, 0)),
        first.dice,
        sequence=second_ready.next_sequence,
    )
    _assert_rejected(
        second.state,
        ActivationProtocolErrorReason.INVALID_PHASE,
        lambda: _commit(
            second.state,
            DefendAction(11),
            second.dice,
            sequence=second.next_sequence,
        ),
    )


@pytest.mark.parametrize(
    "action",
    [
        ShootAction(11, 21, RIFLE),
        ChargeAction(11, 21, SWORD, counter_attack_declared=False),
    ],
)
def test_action_bridge_rejects_repeated_shoot_or_charge_from_durable_history(
    action,
) -> None:
    ready = _ready_for_action(sequence=960)
    first = _commit(
        ready.state,
        action,
        DeterministicDice(43),
        sequence=ready.next_sequence,
    )
    second_ready = _ready_for_second_action(first)
    rng_before = first.dice.to_checkpoint()

    _assert_rejected(
        second_ready.state,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _commit(
            second_ready.state,
            action,
            first.dice,
            sequence=second_ready.next_sequence,
        ),
    )
    assert first.dice.to_checkpoint() == rng_before
    result_type = first.state.activation.action_types[0]
    assert second_ready.state.activation.action_types == (result_type,)
    assert result_type in {"shoot", "charge"}


def test_action_bridge_rejects_illegal_mechanical_action_atomically() -> None:
    ready = _ready_for_action(sequence=990)
    dice = DeterministicDice(47)
    rng_before = dice.to_checkpoint()

    _assert_rejected(
        ready.state,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _commit(
            ready.state,
            ManeuverAction(11, Position(100, 0)),
            dice,
            sequence=ready.next_sequence,
        ),
    )
    assert dice.to_checkpoint() == rng_before


def _action_effect_leaf(
    *,
    state: BattleState,
    action,
    dice: DeterministicDice,
    sequence: int,
):
    dice.roll_d6(3)
    events = (
        EffectApplied(
            sequence=sequence,
            slug="test_action",
            target_unit_id=action.unit_id,
        ),
    )
    return apply_events(state, events), events, sequence + 1


def test_action_leaf_rejects_live_replay_mismatch_and_preserves_rng() -> None:
    ready = _ready_for_action(sequence=1020)
    dice = DeterministicDice(53)
    rng_before = dice.to_checkpoint()

    def mismatch_executor(**kwargs):
        _, events, next_sequence = _action_effect_leaf(**kwargs)
        return replace(kwargs["state"], active_player=1), events, next_sequence

    _assert_rejected(
        ready.state,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _commit(
            ready.state,
            DefendAction(11),
            dice,
            sequence=ready.next_sequence,
            outcome_executor=mismatch_executor,
        ),
    )
    assert dice.to_checkpoint() == rng_before


@pytest.mark.parametrize("violation", ["sequence", "nested", "next-sequence"])
def test_action_leaf_rejects_non_contiguous_nested_or_broken_result_atomically(
    violation: str,
) -> None:
    ready = _ready_for_action(sequence=1050)
    dice = DeterministicDice(59)
    rng_before = dice.to_checkpoint()

    def invalid_executor(*, state, action, dice, sequence):
        dice.roll_d6(1)
        if violation == "nested":
            events = (
                ActivationActionCommitted(
                    sequence=sequence,
                    activation_id=state.activation.activation_id,
                    activation_version=state.activation.version + 1,
                    action_type="defend",
                ),
            )
        else:
            events = (
                EffectApplied(
                    sequence=sequence + (1 if violation == "sequence" else 0),
                    slug="test_action",
                    target_unit_id=action.unit_id,
                ),
            )
        return (
            apply_events(state, events),
            events,
            sequence + len(events) + (1 if violation == "next-sequence" else 0),
        )

    _assert_rejected(
        ready.state,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _commit(
            ready.state,
            DefendAction(11),
            dice,
            sequence=ready.next_sequence,
            outcome_executor=invalid_executor,
        ),
    )
    assert dice.to_checkpoint() == rng_before


def test_action_bridge_rng_and_restart_checkpoint_parity_across_two_actions() -> None:
    ready = _ready_for_action(sequence=1080)
    source_dice = DeterministicDice(61)
    source_dice.roll_d6(4)
    checkpoint = json.loads(json.dumps(source_dice.to_checkpoint()))

    live_first = _commit(
        ready.state,
        ShootAction(11, 21, RIFLE),
        source_dice,
        sequence=ready.next_sequence,
    )
    restarted_first = _commit(
        _restart(ready.state),
        ShootAction(11, 21, RIFLE),
        DeterministicDice.from_checkpoint(checkpoint),
        sequence=ready.next_sequence,
    )

    assert [event_to_json(event) for event in restarted_first.events] == [
        event_to_json(event) for event in live_first.events
    ]
    assert restarted_first.state == live_first.state
    assert restarted_first.next_sequence == live_first.next_sequence
    assert restarted_first.dice.to_checkpoint() == live_first.dice.to_checkpoint()
    assert source_dice.to_checkpoint() == checkpoint

    second_ready = _ready_for_second_action(live_first)
    second_rng = json.loads(json.dumps(live_first.dice.to_checkpoint()))
    live_second = _commit(
        second_ready.state,
        ChargeAction(11, 21, SWORD, counter_attack_declared=False),
        live_first.dice,
        sequence=second_ready.next_sequence,
    )
    restarted_second = _commit(
        _restart(second_ready.state),
        ChargeAction(11, 21, SWORD, counter_attack_declared=False),
        DeterministicDice.from_checkpoint(second_rng),
        sequence=second_ready.next_sequence,
    )

    assert [event_to_json(event) for event in restarted_second.events] == [
        event_to_json(event) for event in live_second.events
    ]
    assert restarted_second.state == live_second.state
    assert restarted_second.dice.to_checkpoint() == live_second.dice.to_checkpoint()
    assert live_second.state.activation.phase is ActivationPhase.AWAITING_FINALIZATION


def _state_with_terminal_effects() -> BattleState:
    state = _action_idle_state(actor_overrides=(("ordered", True),))
    actor, target = state.blobs
    return replace(
        state,
        blobs=(
            replace(actor, damage_balance=2),
            replace(target, ability_overrides=(("cursed", True),)),
        ),
    )


def _first_action_awaiting_finalization(*, sequence: int = 1200):
    ready = _ready_for_action(
        state=_state_with_terminal_effects(),
        sequence=sequence,
    )
    committed = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(67),
        sequence=ready.next_sequence,
    )
    return ready, committed


def _second_action_awaiting_finalization(*, sequence: int = 1300):
    ready, first = _first_action_awaiting_finalization(sequence=sequence)
    second_ready = _ready_for_second_action(first)
    second = _commit(
        second_ready.state,
        ManeuverAction(11, Position(1, 0)),
        first.dice,
        sequence=second_ready.next_sequence,
    )
    return ready, first, second_ready, second


def _assert_terminal_state(result, input_state: BattleState) -> None:
    assert result.state.activation is None
    actor = next(blob for blob in result.state.blobs if blob.id == 11)
    assert STATUS_AKTYWOWANY in actor.status_flags
    assert actor.damage_balance == 0
    assert all(not blob.ability_overrides for blob in result.state.blobs)
    assert result.state.initiative_player == 1
    assert result.state.active_player == 1
    assert [event.sequence for event in result.events] == list(
        range(result.events[0].sequence, result.next_sequence)
    )
    assert result.state == apply_events(input_state, result.events)


def test_finalize_after_first_action_orders_empty_recovery_and_terminal_events() -> None:
    _, committed = _first_action_awaiting_finalization(sequence=1200)

    result = _finalize(
        committed.state,
        sequence=committed.next_sequence,
        recovery_uses=(),
    )

    assert isinstance(result.events[0], ActivationContinuationChosen)
    assert result.events[0].continue_activation is False
    assert [type(event) for event in result.events[1:-3]] == [
        StatusAdded,
        MeleeBalanceReset,
        AbilityOverridesCleared,
        AbilityOverridesCleared,
    ]
    assert [type(event) for event in result.events[-3:]] == [
        ActivationFinalized,
        InitiativeTransferred,
        ActivePlayerChanged,
    ]
    _assert_terminal_state(result, committed.state)


def test_finalize_after_second_action_omits_continuation_and_orders_terminal_events() -> None:
    _, _, _, committed = _second_action_awaiting_finalization(sequence=1300)

    result = _finalize(
        committed.state,
        sequence=committed.next_sequence,
        recovery_uses=(),
    )

    assert not any(
        isinstance(event, ActivationContinuationChosen) for event in result.events
    )
    assert [type(event) for event in result.events[:-3]] == [
        StatusAdded,
        MeleeBalanceReset,
        AbilityOverridesCleared,
        AbilityOverridesCleared,
    ]
    assert [type(event) for event in result.events[-3:]] == [
        ActivationFinalized,
        InitiativeTransferred,
        ActivePlayerChanged,
    ]
    _assert_terminal_state(result, committed.state)


def test_finalize_transfers_from_durable_initiative_snapshot() -> None:
    initial = replace(_action_idle_state(), initiative_player=1)
    started = start_activation(initial, selected_unit_id=11, sequence=1350)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=1,
        activation_id=started.state.activation.activation_id,
        expected_activation_version=started.state.activation.version,
        expected_window_version=started.state.activation.window.version,
        sequence=started.next_sequence,
    )
    ready = pass_interrupt_priority(
        first_pass.state,
        caller_player=0,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )
    committed = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(69),
        sequence=ready.next_sequence,
    )

    result = _finalize(committed.state, sequence=committed.next_sequence)

    initiative_event = result.events[-2]
    active_event = result.events[-1]
    assert initiative_event == InitiativeTransferred(
        sequence=initiative_event.sequence,
        activation_id=started.state.activation.activation_id,
        previous_initiative_player=1,
        new_initiative_player=0,
    )
    assert active_event == ActivePlayerChanged(
        sequence=active_event.sequence,
        activation_id=started.state.activation.activation_id,
        previous_active_player=0,
        new_active_player=1,
    )
    assert result.state.initiative_player == 0
    assert result.state.active_player == 1
    assert result.state == apply_events(committed.state, result.events)


@pytest.mark.parametrize("two_actions", [False, True])
def test_finalize_v2_checkpoint_restart_parity_for_both_legal_phases(
    two_actions: bool,
) -> None:
    if two_actions:
        _, _, _, committed = _second_action_awaiting_finalization(sequence=1400)
    else:
        _, committed = _first_action_awaiting_finalization(sequence=1400)

    live = _finalize(committed.state, sequence=committed.next_sequence)
    restarted = _finalize(
        _restart(committed.state),
        sequence=committed.next_sequence,
    )

    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in live.events
    ]
    assert restarted.state == live.state
    assert restarted.next_sequence == live.next_sequence


@pytest.mark.parametrize("two_actions", [False, True])
def test_complete_v2_event_tail_replays_through_finalization(
    two_actions: bool,
) -> None:
    initial = _state_with_terminal_effects()
    started = start_activation(initial, selected_unit_id=11, sequence=1500)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=started.state.activation.activation_id,
        expected_activation_version=started.state.activation.version,
        expected_window_version=started.state.activation.window.version,
        sequence=started.next_sequence,
    )
    first_ready = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )
    first = _commit(
        first_ready.state,
        DefendAction(11),
        DeterministicDice(71),
        sequence=first_ready.next_sequence,
    )
    transitions = [started, first_pass, first_ready, first]
    committed = first

    if two_actions:
        continued = continue_activation(
            first.state,
            caller_player=0,
            activation_id=first.state.activation.activation_id,
            expected_activation_version=first.state.activation.version,
            sequence=first.next_sequence,
        )
        second_first_pass = pass_interrupt_priority(
            continued.state,
            caller_player=0,
            activation_id=continued.state.activation.activation_id,
            expected_activation_version=continued.state.activation.version,
            expected_window_version=continued.state.activation.window.version,
            sequence=continued.next_sequence,
        )
        second_ready = pass_interrupt_priority(
            second_first_pass.state,
            caller_player=1,
            activation_id=second_first_pass.state.activation.activation_id,
            expected_activation_version=second_first_pass.state.activation.version,
            expected_window_version=second_first_pass.state.activation.window.version,
            sequence=second_first_pass.next_sequence,
        )
        committed = _commit(
            second_ready.state,
            ManeuverAction(11, Position(1, 0)),
            first.dice,
            sequence=second_ready.next_sequence,
        )
        transitions.extend(
            [continued, second_first_pass, second_ready, committed]
        )

    finalized = _finalize(
        committed.state,
        sequence=committed.next_sequence,
    )
    transitions.append(finalized)
    complete_tail = tuple(
        event for transition in transitions for event in transition.events
    )

    assert finalized.state == apply_events(initial, complete_tail)
    assert finalized.state.activation is None


def test_finalize_rejects_protocol_guards_phase_and_malformed_action_count() -> None:
    _, committed = _first_action_awaiting_finalization(sequence=1600)
    state = committed.state
    cases = (
        (
            _idle_state(initiative_player=None),
            ActivationProtocolErrorReason.PROTOCOL_UPGRADE_REQUIRED,
            lambda legacy: finalize_activation(
                legacy,
                caller_player=0,
                activation_id=1,
                expected_activation_version=1,
                recovery_uses=(),
                sequence=1,
            ),
        ),
        (
            _idle_state(),
            ActivationProtocolErrorReason.INVALID_PHASE,
            lambda idle: finalize_activation(
                idle,
                caller_player=0,
                activation_id=1,
                expected_activation_version=1,
                recovery_uses=(),
                sequence=1,
            ),
        ),
        (
            state,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda current: _finalize(
                current,
                sequence=committed.next_sequence,
                activation_id=current.activation.activation_id + 1,
            ),
        ),
        (
            state,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
            lambda current: _finalize(
                current,
                sequence=committed.next_sequence,
                expected_activation_version=current.activation.version - 1,
            ),
        ),
        (
            state,
            ActivationProtocolErrorReason.INVALID_CALLER,
            lambda current: _finalize(
                current,
                sequence=committed.next_sequence,
                caller_player=1,
            ),
        ),
        (
            start_activation(
                _action_idle_state(),
                selected_unit_id=11,
                sequence=1650,
            ).state,
            ActivationProtocolErrorReason.INVALID_PHASE,
            lambda current: _finalize(current, sequence=1652),
        ),
    )
    for checked_state, reason, operation in cases:
        _assert_rejected(
            checked_state,
            reason,
            lambda checked_state=checked_state, operation=operation: operation(
                checked_state
            ),
        )

    malformed_activation = copy.copy(state.activation)
    object.__setattr__(malformed_activation, "action_count", 2)
    malformed_state = replace(state, activation=malformed_activation)
    _assert_rejected(
        malformed_state,
        ActivationProtocolErrorReason.INVALID_PHASE,
        lambda: _finalize(
            malformed_state,
            sequence=committed.next_sequence,
        ),
    )


@pytest.mark.parametrize("recovery_uses", [(object(),), ["not", "a", "tuple"]])
def test_finalize_rejects_nonempty_or_malformed_recovery_before_executor(
    recovery_uses,
) -> None:
    _, committed = _first_action_awaiting_finalization(sequence=1700)
    calls = 0

    def executor(**kwargs):
        nonlocal calls
        calls += 1
        return kwargs["state"], (), kwargs["sequence"]

    _assert_rejected(
        committed.state,
        ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        lambda: _finalize(
            committed.state,
            sequence=committed.next_sequence,
            recovery_uses=recovery_uses,
            outcome_executor=executor,
        ),
    )
    assert calls == 0


@pytest.mark.parametrize("sequence", [0, -1, True, "1700"])
def test_finalize_rejects_malformed_sequence_before_executor(sequence) -> None:
    _, committed = _first_action_awaiting_finalization(sequence=1750)
    calls = 0

    def executor(**kwargs):
        nonlocal calls
        calls += 1
        return kwargs["state"], (), kwargs["sequence"]

    _assert_rejected(
        committed.state,
        ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        lambda: _finalize(
            committed.state,
            sequence=sequence,
            outcome_executor=executor,
        ),
    )
    assert calls == 0


@pytest.mark.parametrize("actor_state", ["dead", "missing"])
def test_finalize_handles_dead_or_missing_actor_and_idempotent_empty_overrides(
    actor_state: str,
) -> None:
    ready = _ready_for_action(sequence=1800)
    committed = _commit(
        ready.state,
        DefendAction(11),
        DeterministicDice(73),
        sequence=ready.next_sequence,
    )
    if actor_state == "dead":
        actor, *others = committed.state.blobs
        blobs = (
            replace(
                actor,
                models_alive=0,
                location=Lokalizacja.WYCOFANY,
                status_flags=(),
            ),
            *others,
        )
    else:
        blobs = tuple(blob for blob in committed.state.blobs if blob.id != 11)
    terminal_input = replace(committed.state, blobs=tuple(blobs))

    result = _finalize(terminal_input, sequence=committed.next_sequence)

    assert result.state.activation is None
    assert result.state.initiative_player == 1
    assert result.state.active_player == 1
    assert [type(event) for event in result.events[-3:]] == [
        ActivationFinalized,
        InitiativeTransferred,
        ActivePlayerChanged,
    ]
    assert not any(
        isinstance(event, AbilityOverridesCleared) for event in result.events
    )
    assert result.state == apply_events(terminal_input, result.events)


@pytest.mark.parametrize(
    "violation",
    [
        "sequence",
        "nested",
        "unsupported",
        "unexpected-outcome",
        "live-replay",
        "exception",
    ],
)
def test_finalize_rejects_faulty_outcome_seam_atomically(violation: str) -> None:
    _, committed = _first_action_awaiting_finalization(sequence=1900)
    original = committed.state

    def invalid_executor(*, state, actor_id, recovery_uses, sequence):
        if violation == "exception":
            raise RuntimeError("boom")
        if violation == "nested":
            events = (
                ActivationFinalized(
                    sequence=sequence,
                    activation_id=state.activation.activation_id,
                ),
            )
            return state, events, sequence + 1
        if violation == "unsupported":
            events = (_UnsupportedOutcomeEvent(sequence),)
            return state, events, sequence + 1
        if violation == "unexpected-outcome":
            events = (
                EffectApplied(
                    sequence=sequence,
                    slug="unsupported_recovery",
                    target_unit_id=actor_id,
                ),
            )
            return apply_events(state, events), events, sequence + 1
        if violation == "sequence":
            events = (
                EffectApplied(
                    sequence=sequence + 1,
                    slug="bad_finalization",
                    target_unit_id=actor_id,
                ),
            )
            return state, events, sequence + 1
        return replace(state, active_player=1), (), sequence

    _assert_rejected(
        original,
        ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        lambda: _finalize(
            original,
            sequence=committed.next_sequence,
            outcome_executor=invalid_executor,
        ),
    )


# ---------------------------------------------------------------------------
# B4.4d.C2a2 — private protocol-v3 attack lifecycle
# ---------------------------------------------------------------------------


def _v3_ready_with_tail(
    initial: BattleState,
    *,
    sequence: int,
):
    started = start_activation(initial, selected_unit_id=11, sequence=sequence)
    first_pass = pass_interrupt_priority(
        started.state,
        caller_player=0,
        activation_id=started.state.activation.activation_id,
        expected_activation_version=started.state.activation.version,
        expected_window_version=started.state.activation.window.version,
        sequence=started.next_sequence,
    )
    ready = pass_interrupt_priority(
        first_pass.state,
        caller_player=1,
        activation_id=first_pass.state.activation.activation_id,
        expected_activation_version=first_pass.state.activation.version,
        expected_window_version=first_pass.state.activation.window.version,
        sequence=first_pass.next_sequence,
    )
    return started, first_pass, ready


def _assert_transition_equal(left, right) -> None:
    assert [event_to_json(event) for event in left.events] == [
        event_to_json(event) for event in right.events
    ]
    assert left.state == right.state
    assert left.next_sequence == right.next_sequence
    if hasattr(left, "dice"):
        assert left.dice.to_checkpoint() == right.dice.to_checkpoint()


@pytest.mark.parametrize(
    ("action", "action_type"),
    [
        (ShootAction(11, 21, RIFLE), "shoot"),
        (
            ChargeAction(11, 21, SWORD, counter_attack_declared=False),
            "charge",
        ),
    ],
)
def test_v3_pass_only_attack_lifecycle_restarts_replays_and_isolates_rng(
    action,
    action_type: str,
) -> None:
    initial = _action_idle_state()
    started, general_first_pass, ready = _v3_ready_with_tail(
        initial,
        sequence=3000,
    )
    complete_tail = [
        *started.events,
        *general_first_pass.events,
        *ready.events,
    ]
    dice = DeterministicDice(307)
    dice.roll_d6(4)
    declaration_rng = json.loads(json.dumps(dice.to_checkpoint()))

    declared = _commit_v3(
        ready.state,
        action,
        dice,
        sequence=ready.next_sequence,
    )
    restarted_declared = _commit_v3(
        _restart_v3(ready.state),
        action,
        DeterministicDice.from_checkpoint(declaration_rng),
        sequence=ready.next_sequence,
    )

    _assert_transition_equal(declared, restarted_declared)
    assert [type(event) for event in declared.events] == [
        AttackDeclared,
        AttackInterruptWindowOpened,
    ]
    assert dice.to_checkpoint() == declaration_rng
    assert declared.dice.to_checkpoint() == declaration_rng
    assert declared.state.activation.action_count == 0
    assert declared.state.activation.action_types == ()
    assert declared.state.activation.phase is ActivationPhase.ATTACK_WINDOW
    assert declared.state.activation.attack.intent.weapon_slug == action.weapon.slug
    assert _restart_v3(declared.state) == declared.state
    complete_tail.extend(declared.events)
    assert declared.state == apply_events(initial, complete_tail)

    first_pass = _pass_attack(
        declared.state,
        caller_player=0,
        sequence=declared.next_sequence,
    )
    restarted_first_pass = _pass_attack(
        _restart_v3(declared.state),
        caller_player=0,
        sequence=declared.next_sequence,
    )

    _assert_transition_equal(first_pass, restarted_first_pass)
    assert [type(event) for event in first_pass.events] == [
        AttackInterruptPriorityPassed
    ]
    assert first_pass.state.activation.attack.window.priority_player == 1
    assert first_pass.state.activation.action_count == 0
    assert declared.dice.to_checkpoint() == declaration_rng
    assert _restart_v3(first_pass.state) == first_pass.state
    complete_tail.extend(first_pass.events)
    assert first_pass.state == apply_events(initial, complete_tail)

    closed = _pass_attack(
        first_pass.state,
        caller_player=1,
        sequence=first_pass.next_sequence,
    )
    restarted_closed = _pass_attack(
        _restart_v3(first_pass.state),
        caller_player=1,
        sequence=first_pass.next_sequence,
    )

    _assert_transition_equal(closed, restarted_closed)
    assert [type(event) for event in closed.events] == [
        AttackInterruptPriorityPassed,
        AttackInterruptWindowClosed,
    ]
    assert closed.state.activation.phase is ActivationPhase.ATTACK_RESOLUTION_READY
    assert closed.state.activation.attack.window is None
    assert closed.state.activation.action_count == 0
    assert declared.dice.to_checkpoint() == declaration_rng
    assert _restart_v3(closed.state) == closed.state
    complete_tail.extend(closed.events)
    assert closed.state == apply_events(initial, complete_tail)

    resolve_rng = json.loads(json.dumps(declared.dice.to_checkpoint()))
    resolved = _resolve_attack(
        closed.state,
        declared.dice,
        sequence=closed.next_sequence,
    )
    restarted_resolved = _resolve_attack(
        _restart_v3(closed.state),
        DeterministicDice.from_checkpoint(resolve_rng),
        sequence=closed.next_sequence,
    )

    _assert_transition_equal(resolved, restarted_resolved)
    assert isinstance(resolved.events[-2], AttackResolved)
    assert isinstance(resolved.events[-1], ActivationActionCommitted)
    assert resolved.events[-1].action_type == action_type
    assert resolved.events[-2].activation_version == resolved.events[-1].activation_version
    assert declared.dice.to_checkpoint() == resolve_rng
    assert resolved.dice.to_checkpoint() != resolve_rng
    before_commit = apply_events(closed.state, resolved.events[:-1])
    assert before_commit.activation.action_count == 0
    assert before_commit.activation.action_types == ()
    assert before_commit.activation.attack is None
    assert before_commit.activation.phase is ActivationPhase.ACTION_READY
    assert resolved.state.activation.action_count == 1
    assert resolved.state.activation.action_types == (action_type,)
    assert resolved.state.activation.phase is ActivationPhase.AWAITING_CONTINUATION
    assert _restart_v3(resolved.state) == resolved.state
    complete_tail.extend(resolved.events)
    assert resolved.state == apply_events(initial, complete_tail)


@pytest.mark.parametrize(
    "action",
    [
        ManeuverAction(11, Position(1, 0)),
        DefendAction(11),
        SpecialAction(11, "discard_exhausted"),
    ],
)
def test_v3_nonattack_dispatch_is_exact_v2_semantics(action) -> None:
    initial = _action_idle_state(actor_statuses=(STATUS_WYCZERPANY,))
    _, _, ready = _v3_ready_with_tail(initial, sequence=3200)
    checkpoint = DeterministicDice(311).to_checkpoint()
    v2_input = DeterministicDice.from_checkpoint(checkpoint)
    v3_input = DeterministicDice.from_checkpoint(checkpoint)

    v2 = _commit(
        ready.state,
        action,
        v2_input,
        sequence=ready.next_sequence,
    )
    v3 = _commit_v3(
        _restart_v3(ready.state),
        action,
        v3_input,
        sequence=ready.next_sequence,
    )

    _assert_transition_equal(v2, v3)
    assert v2_input.to_checkpoint() == checkpoint
    assert v3_input.to_checkpoint() == checkpoint
    assert not any(
        type(event) in {AttackDeclared, AttackInterruptWindowOpened, AttackResolved}
        for event in v3.events
    )


def test_v2_attack_bridge_remains_atomic_and_has_no_pending_attack() -> None:
    ready = _ready_for_action(sequence=3300)

    result = _commit(
        ready.state,
        ShootAction(11, 21, RIFLE),
        DeterministicDice(313),
        sequence=ready.next_sequence,
    )

    assert result.state.activation.attack is None
    assert result.state.activation.action_types == ("shoot",)
    assert result.state.activation.phase is ActivationPhase.AWAITING_CONTINUATION
    assert not any(
        type(event) in {AttackDeclared, AttackInterruptWindowOpened, AttackResolved}
        for event in result.events
    )


def test_v3_declaration_uses_unambiguous_canonical_inventory_atomically() -> None:
    base = _action_idle_state()
    actor, target = base.blobs
    cases = (
        (base, ShootAction(11, 21, replace(RIFLE, attacks=99))),
        (base, ShootAction(11, 21, replace(RIFLE, slug="missing"))),
        (
            replace(
                base,
                blobs=(
                    replace(
                        actor,
                        ranged_weapons=(RIFLE, replace(RIFLE, attacks=3)),
                    ),
                    target,
                ),
            ),
            ShootAction(11, 21, RIFLE),
        ),
        (
            replace(
                base,
                blobs=(
                    replace(
                        actor,
                        ranged_weapons=(
                            RIFLE,
                            replace(RIFLE, range_inches=24.0),
                        ),
                    ),
                    target,
                ),
            ),
            ShootAction(11, 21, RIFLE),
        ),
        (
            replace(base, blobs=(actor, replace(target, owner_player=0))),
            ShootAction(11, 21, RIFLE),
        ),
        (base, ChargeAction(11, 21, SWORD, counter_attack_declared=1)),
    )

    for index, (state, action) in enumerate(cases):
        _, _, ready = _v3_ready_with_tail(state, sequence=3400 + index * 10)
        dice = DeterministicDice(317 + index)
        rng_before = dice.to_checkpoint()
        _assert_rejected(
            ready.state,
            ActivationProtocolErrorReason.ILLEGAL_ACTION,
            lambda ready=ready, action=action, dice=dice: _commit_v3(
                ready.state,
                action,
                dice,
                sequence=ready.next_sequence,
            ),
        )
        assert dice.to_checkpoint() == rng_before


def _closed_v3_attack(*, sequence: int = 3500):
    initial = _action_idle_state()
    _, _, ready = _v3_ready_with_tail(initial, sequence=sequence)
    declared = _commit_v3(
        ready.state,
        ShootAction(11, 21, RIFLE),
        DeterministicDice(331),
        sequence=ready.next_sequence,
    )
    first_pass = _pass_attack(
        declared.state,
        caller_player=0,
        sequence=declared.next_sequence,
    )
    closed = _pass_attack(
        first_pass.state,
        caller_player=1,
        sequence=first_pass.next_sequence,
    )
    return initial, declared, first_pass, closed


def test_v3_resolve_failure_after_partial_rng_preserves_input_state_and_rng() -> None:
    _, _, _, closed = _closed_v3_attack(sequence=3500)
    dice = DeterministicDice(337)
    rng_before = dice.to_checkpoint()

    def failing_executor(*, dice, **kwargs):
        del kwargs
        dice.roll_d6(8)
        raise RuntimeError("partial outcome failure")

    _assert_rejected(
        closed.state,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _resolve_attack(
            closed.state,
            dice,
            sequence=closed.next_sequence,
            outcome_executor=failing_executor,
        ),
    )
    assert dice.to_checkpoint() == rng_before
    assert closed.state.activation.phase is ActivationPhase.ATTACK_RESOLUTION_READY


def test_v3_resolve_reloads_canonical_inventory_and_rejects_drift() -> None:
    _, _, _, closed = _closed_v3_attack(sequence=3600)
    actor, target = closed.state.blobs
    drifted = replace(
        closed.state,
        blobs=(replace(actor, ranged_weapons=()), target),
    )
    dice = DeterministicDice(347)
    rng_before = dice.to_checkpoint()

    _assert_rejected(
        drifted,
        ActivationProtocolErrorReason.ILLEGAL_ACTION,
        lambda: _resolve_attack(
            drifted,
            dice,
            sequence=closed.next_sequence,
        ),
    )
    assert dice.to_checkpoint() == rng_before


def test_attack_trigger_and_override_reducers_update_only_attack_scope() -> None:
    initial = _action_idle_state(actor_overrides=(("ordered", True),))
    _, _, ready = _v3_ready_with_tail(initial, sequence=3700)
    declared = _commit_v3(
        ready.state,
        ShootAction(11, 21, RIFLE),
        DeterministicDice(349),
        sequence=ready.next_sequence,
    )
    activation = declared.state.activation
    attack = activation.attack
    trigger = AttackInterruptTriggered(
        sequence=declared.next_sequence,
        activation_id=activation.activation_id,
        activation_version=activation.version + 1,
        attack_id=attack.attack_id,
        attack_version=attack.version + 1,
        attack_ordinal=attack.ordinal,
        window_version=attack.window.version + 1,
        priority_player=attack.window.priority_player,
    )
    triggered = apply_events(declared.state, (trigger,))
    triggered_attack = triggered.activation.attack

    assert triggered.activation.version == activation.version + 1
    assert triggered_attack.version == attack.version + 1
    assert triggered_attack.window.version == attack.window.version + 1
    assert triggered_attack.window.interrupt_count == 1
    assert triggered_attack.window.priority_player == attack.window.priority_player
    assert triggered.used_interrupts_this_round == declared.state.used_interrupts_this_round

    override = AttackAbilityOverrideApplied(
        sequence=declared.next_sequence + 1,
        activation_id=activation.activation_id,
        activation_version=triggered.activation.version,
        attack_id=attack.attack_id,
        attack_version=triggered_attack.version,
        attack_ordinal=attack.ordinal,
        window_version=triggered_attack.window.version,
        attacker_unit_id=11,
        source_unit_id=12,
        ability_slug="furia",
    )
    overridden = apply_events(triggered, (override,))
    actor = next(blob for blob in overridden.blobs if blob.id == 11)

    assert len(overridden.activation.attack.ability_overrides) == 1
    stored_override = overridden.activation.attack.ability_overrides[0]
    assert stored_override.source_unit_id == 12
    assert stored_override.ability_slug == "furia"
    assert actor.ability_overrides == (("ordered", True),)


def test_attack_replay_rejects_closing_pass_without_first_player_pass() -> None:
    _, declared, _, _ = _closed_v3_attack(sequence=3750)
    activation = declared.state.activation
    attack = activation.attack
    triggered = apply_events(
        declared.state,
        (
            AttackInterruptTriggered(
                sequence=declared.next_sequence,
                activation_id=activation.activation_id,
                activation_version=activation.version + 1,
                attack_id=attack.attack_id,
                attack_version=attack.version + 1,
                attack_ordinal=attack.ordinal,
                window_version=attack.window.version + 1,
                priority_player=attack.window.priority_player,
            ),
        ),
    )
    activation = triggered.activation
    attack = activation.attack
    premature_close = AttackInterruptPriorityPassed(
        sequence=declared.next_sequence + 1,
        activation_id=activation.activation_id,
        activation_version=activation.version + 1,
        attack_id=attack.attack_id,
        attack_version=attack.version + 1,
        attack_ordinal=attack.ordinal,
        window_version=attack.window.version + 1,
        passed_player=attack.window.priority_player,
        next_priority_player=None,
    )

    with pytest.raises(ValueError, match="requires the first player's pass"):
        apply_events(triggered, (premature_close,))


def test_v3_second_attack_declaration_uses_second_ordinal() -> None:
    initial = _action_idle_state()
    _, _, first_ready = _v3_ready_with_tail(initial, sequence=3800)
    first = _commit_v3(
        first_ready.state,
        DefendAction(11),
        DeterministicDice(353),
        sequence=first_ready.next_sequence,
    )
    second_ready = _ready_for_second_action(first)

    declared = _commit_v3(
        second_ready.state,
        ChargeAction(11, 21, SWORD, counter_attack_declared=False),
        first.dice,
        sequence=second_ready.next_sequence,
    )

    assert declared.state.activation.attack.ordinal == 2
    assert declared.events[0].attack_ordinal == 2
    assert declared.state.activation.action_count == 1
    assert declared.state.activation.action_types == ("defend",)


# ---------------------------------------------------------------------------
# B4.4d.C2b — private source-correct Oznaczenie attack scope
# ---------------------------------------------------------------------------


def _marked_idle_state(*, actor_overrides=()) -> BattleState:
    base = _action_idle_state(actor_overrides=actor_overrides)
    source = replace(
        _unit(12, 0, passives=('oznaczenie',)),
        position=Position(20, 0),  # edge gap to declared target at x=6 is 12
    )
    return replace(
        base,
        blobs=(*base.blobs, source),
        activations_remaining=(2, 1),
        initial_toughness_snapshot=((*base.initial_toughness_snapshot, (12, 3))),
    )


def _marked_declared(*, state=None, action=None):
    initial = _marked_idle_state() if state is None else state
    started, general_first, ready = _v3_ready_with_tail(initial, sequence=4000)
    declared = _commit_v3(
        ready.state,
        ShootAction(11, 21, RIFLE) if action is None else action,
        DeterministicDice(401),
        sequence=ready.next_sequence,
    )
    return initial, started, general_first, ready, declared


def _mark_attack(state, dice, *, sequence, payload=None, source_unit_id=12, **guards):
    activation = state.activation
    attack = activation.attack
    args = dict(
        caller_player=attack.window.priority_player,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        attack_id=attack.attack_id,
        expected_attack_version=attack.version,
        expected_window_version=attack.window.version,
        source_unit_id=source_unit_id,
        ability_slug='oznaczenie',
        payload={'ability': 'planowanie'} if payload is None else payload,
        dice=dice,
        sequence=sequence,
    )
    args.update(guards)
    return _trigger_attack_interrupt(state, **args)


def test_v3_oznaczenie_full_tail_restarts_rng_and_scope_cleanup() -> None:
    initial = _marked_idle_state(actor_overrides=(('tarcza', True),))
    initial, started, general_first, ready, declared = _marked_declared(state=initial)
    tail = [*started.events, *general_first.events, *ready.events, *declared.events]
    dice = DeterministicDice(403)
    dice.roll_d6(3)
    before = dice.to_checkpoint()

    marked = _mark_attack(declared.state, dice, sequence=declared.next_sequence)
    restarted = _mark_attack(
        _restart_v3(declared.state),
        DeterministicDice.from_checkpoint(before),
        sequence=declared.next_sequence,
    )
    _assert_transition_equal(marked, restarted)
    assert [type(event) for event in marked.events] == [
        AttackInterruptTriggered, InterruptTriggered, AttackAbilityOverrideApplied,
    ]
    assert [event.sequence for event in marked.events] == list(
        range(declared.next_sequence, marked.next_sequence)
    )
    assert marked.events[1].payload == {'ability': 'planowanie'}
    assert marked.events[1].consumes_round_limit is True
    assert marked.events[1].target_unit_id == 11
    assert marked.state.used_interrupts_this_round == ((12, 'oznaczenie'),)
    assert marked.state.activation.version == declared.state.activation.version + 1
    assert marked.state.activation.attack.version == declared.state.activation.attack.version + 1
    assert marked.state.activation.attack.window.version == declared.state.activation.attack.window.version + 1
    assert marked.state.activation.attack.window.priority_player == 0
    actor = next(blob for blob in marked.state.blobs if blob.id == 11)
    target = next(blob for blob in marked.state.blobs if blob.id == 21)
    assert actor.ability_overrides == (('tarcza', True),)
    assert target.ability_overrides == ()
    assert 'planowanie' in effective_attack_passives(actor, marked.state.activation.attack)
    assert 'planowanie' not in effective_attack_passives(target, marked.state.activation.attack)
    assert 'planowanie' not in effective_passives(actor)
    assert dice.to_checkpoint() == before == marked.dice.to_checkpoint()
    tail.extend(marked.events)
    assert marked.state == apply_events(initial, tail)

    first = _pass_attack(marked.state, caller_player=0, sequence=marked.next_sequence)
    _assert_transition_equal(
        first,
        _pass_attack(_restart_v3(marked.state), caller_player=0, sequence=marked.next_sequence),
    )
    tail.extend(first.events)
    assert first.state == apply_events(initial, tail)
    closed = _pass_attack(first.state, caller_player=1, sequence=first.next_sequence)
    _assert_transition_equal(
        closed,
        _pass_attack(_restart_v3(first.state), caller_player=1, sequence=first.next_sequence),
    )
    tail.extend(closed.events)
    assert closed.state == apply_events(initial, tail)
    assert closed.state.activation.attack.ability_overrides == marked.state.activation.attack.ability_overrides
    assert dice.to_checkpoint() == before

    resolved = _resolve_attack(closed.state, marked.dice, sequence=closed.next_sequence)
    restarted_resolved = _resolve_attack(
        _restart_v3(closed.state),
        DeterministicDice.from_checkpoint(before),
        sequence=closed.next_sequence,
    )
    _assert_transition_equal(resolved, restarted_resolved)
    tail.extend(resolved.events)
    assert resolved.state == apply_events(initial, tail)
    assert resolved.state.activation.attack is None
    assert next(blob for blob in resolved.state.blobs if blob.id == 11).ability_overrides == (('tarcza', True),)
    assert resolved.dice.to_checkpoint() != before
    assert dice.to_checkpoint() == before
    assert resolved.dice.roll_d6(6) == restarted_resolved.dice.roll_d6(6)
    assert READY_INTERRUPT_HANDLERS == {'rozkaz', 'klatwa', 'straznik'}


def test_v3_oznaczenie_reaches_combat_only_for_declared_attacker(monkeypatch) -> None:
    from app.services.engine import effects

    seen = []

    def marked_attack_modifier(context):
        seen.append(context.blob.id)
        return 5

    monkeypatch.setitem(effects._ATTACK_MODIFIERS, 'planowanie', marked_attack_modifier)
    initial, _, _, _, declared = _marked_declared()
    marked = _mark_attack(declared.state, DeterministicDice(409), sequence=declared.next_sequence)
    closed = _pass_attack(marked.state, caller_player=0, sequence=marked.next_sequence)
    closed = _pass_attack(closed.state, caller_player=1, sequence=closed.next_sequence)
    resolved = _resolve_attack(closed.state, DeterministicDice(411), sequence=closed.next_sequence)
    assert seen == [11]
    assert next(event for event in resolved.events if type(event).__name__ == 'ShotResolved').attacker_id == 11

    # The defender attacks first in charge; the mark must not enter that role.
    charge_target = replace(next(b for b in initial.blobs if b.id == 21), models_alive=1)
    charge_initial = replace(
        initial,
        blobs=tuple(charge_target if b.id == 21 else b for b in initial.blobs),
        initial_toughness_snapshot=((11, 15), (21, 3), (12, 3)),
    )
    _, _, _, _, charge_declared = _marked_declared(
        state=charge_initial,
        action=ChargeAction(11, 21, SWORD, counter_attack_declared=True),
    )
    charge_marked = _mark_attack(
        charge_declared.state, DeterministicDice(413), sequence=charge_declared.next_sequence
    )
    charge_first = _pass_attack(
        charge_marked.state, caller_player=0, sequence=charge_marked.next_sequence
    )
    charge_closed = _pass_attack(
        charge_first.state, caller_player=1, sequence=charge_first.next_sequence
    )
    seen.clear()
    charge_resolved = _resolve_attack(
        charge_closed.state, DeterministicDice(419), sequence=charge_closed.next_sequence
    )
    assert seen == [11]
    melee_attackers = [e.attacker_id for e in charge_resolved.events if type(e).__name__ == 'MeleeResolved']
    assert melee_attackers == [21, 11]


# B4.4d.C2d1 — Furia outcomes, using real deterministic dice and v3 transitions.
_FURIA_SWORD = replace(SWORD, attacks=1)
_FURIA_RIFLE = replace(RIFLE, attacks=1)


def _furia_battle(*, native=False, podwojny=False, defender_passives=(), exhausted=False, fragile=False):
    state = _marked_idle_state()
    actor, defender, source = state.blobs
    weapon = replace(_FURIA_SWORD, weapon_abilities=("podwojny",)) if podwojny else _FURIA_SWORD
    actor = replace(
        actor, models_alive=1, toughness_per_model=1 if fragile else 8,
        passives=("furia",) if native else (), melee_weapons=(weapon,),
        ranged_weapons=(_FURIA_RIFLE,),
    )
    defender = replace(
        defender, models_alive=1, toughness_per_model=8,
        melee_weapons=(_FURIA_SWORD,), passives=defender_passives,
        status_flags=(STATUS_WYCZERPANY,) if exhausted else (),
    )
    return replace(
        state, blobs=(actor, defender, source),
        initial_toughness_snapshot=((11, actor.toughness_per_model), (21, 8), (12, 3)),
    )


def _close_furia_attack(declared, dice, *, marked):
    tail = []
    head = declared
    if marked:
        head = _mark_attack(
            head.state, dice, sequence=head.next_sequence, payload={"ability": "furia"},
        )
        tail.extend(head.events)
    for _ in range(2):
        head = _pass_attack(
            head.state, caller_player=head.state.activation.attack.window.priority_player,
            sequence=head.next_sequence,
        )
        tail.extend(head.events)
    return head, tail


@pytest.mark.parametrize(
    ("native", "marked", "podwojny", "seed", "expected_hits", "expected_wounds"),
    [
        (False, False, False, 225, 1, 1),
        (True, False, False, 225, 2, 2),
        (False, True, False, 225, 2, 2),
        (True, True, False, 225, 2, 2),
        (True, True, True, 225, 3, 2),
        (True, True, True, 58, 1, 1),
    ],
)
def test_v3_furia_counts_natural_sixes_before_defense(
    native, marked, podwojny, seed, expected_hits, expected_wounds, monkeypatch,
):
    initial = _furia_battle(native=native, podwojny=podwojny)
    weapon, = initial.blobs[0].melee_weapons
    _, started, first, ready, declared = _marked_declared(
        state=initial, action=ChargeAction(11, 21, weapon, counter_attack_declared=False),
    )
    dice = DeterministicDice(seed)
    before = dice.to_checkpoint()
    closed, close_tail = _close_furia_attack(declared, dice, marked=marked)
    prefix = (*started.events, *first.events, *ready.events, *declared.events, *close_tail)
    assert apply_events(initial, prefix) == closed.state

    calls = []
    original_roll = DeterministicDice.roll_d6

    def record_roll(self, count=1):
        result = original_roll(self, count)
        calls.append(result)
        return result

    with monkeypatch.context() as trace:
        trace.setattr(DeterministicDice, "roll_d6", record_roll)
        result = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)

    hit, = (event for event in result.events if isinstance(event, MeleeResolved))
    assert (hit.attacker_id, hit.defender_id, hit.weapon_slug) == (11, 21, weapon.slug)
    assert calls[0] == ((6,) if seed == 225 else (5,))
    assert len(calls[1]) == hit.hits == expected_hits
    assert hit.wounds_dealt + hit.wounds_precise == expected_wounds
    assert result.state.blobs[1].wounds_received == expected_wounds
    assert apply_events(initial, (*prefix, *result.events)) == result.state
    assert result.state.activation.attack is None
    assert result.state.blobs[0].passives == initial.blobs[0].passives
    assert dice.to_checkpoint() == before
    restarted = _resolve_attack(
        _restart_v3(closed.state), DeterministicDice.from_checkpoint(before),
        sequence=closed.next_sequence,
    )
    _assert_transition_equal(result, restarted)
    assert result.dice.roll_d6(6) == restarted.dice.roll_d6(6)


@pytest.mark.parametrize(
    ("passives", "counter", "exhausted", "fragile", "seed", "melee_hits"),
    [
        (("furia",), True, False, False, 376, [(21, 1), (11, 2)]),
        (("furia", "kontra"), True, False, False, 376, [(21, 1), (11, 1)]),
        (("kontra",), False, False, False, 376, [(11, 2)]),
        (("kontra",), True, True, False, 376, [(11, 2)]),
        (("furia",), True, False, True, 282, [(21, 1)]),
    ],
)
def test_v3_furia_respects_charge_and_counterattack_roles(
    passives, counter, exhausted, fragile, seed, melee_hits,
):
    initial = _furia_battle(defender_passives=passives, exhausted=exhausted, fragile=fragile)
    _, _, _, _, declared = _marked_declared(
        state=initial, action=ChargeAction(11, 21, _FURIA_SWORD, counter_attack_declared=counter),
    )
    dice = DeterministicDice(seed)
    closed, _ = _close_furia_attack(declared, dice, marked=True)
    result = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    assert [(e.attacker_id, e.hits) for e in result.events if isinstance(e, MeleeResolved)] == melee_hits
    if fragile:
        assert result.state.blobs[0].models_alive == 0


def test_v3_furia_mark_is_inert_for_shoot_and_cleared_before_next_charge():
    initial = _furia_battle()
    _, _, _, _, declared = _marked_declared(state=initial, action=ShootAction(11, 21, _FURIA_RIFLE))
    dice = DeterministicDice(376)  # Natural 6 for the shot and again for the charge.
    closed, _ = _close_furia_attack(declared, dice, marked=True)
    shot = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    assert next(e for e in shot.events if isinstance(e, ShotResolved)).hits == 1
    second_ready = _ready_for_second_action(shot)
    charge = _commit_v3(
        second_ready.state, ChargeAction(11, 21, _FURIA_SWORD, counter_attack_declared=False),
        shot.dice, sequence=second_ready.next_sequence,
    )
    assert charge.state.activation.attack.ability_overrides == ()
    closed, _ = _close_furia_attack(charge, shot.dice, marked=False)
    result = _resolve_attack(closed.state, shot.dice, sequence=closed.next_sequence)
    assert next(e for e in result.events if isinstance(e, MeleeResolved)).hits == 1


def test_v3_furia_failure_during_allocation_preserves_head_and_retry_rng(monkeypatch):
    from app.services.engine import combat

    initial = _furia_battle()
    _, _, _, _, declared = _marked_declared(
        state=initial, action=ChargeAction(11, 21, _FURIA_SWORD, counter_attack_declared=False),
    )
    dice = DeterministicDice(225)
    closed, _ = _close_furia_attack(declared, dice, marked=True)
    original = _restart_v3(closed.state)
    before = dice.to_checkpoint()
    expected = _resolve_attack(original, DeterministicDice.from_checkpoint(before), sequence=closed.next_sequence)

    allocations = []

    def fail_after_defense(_defender, wounds, **kwargs):
        allocations.append(wounds)
        raise RuntimeError("allocation failure after rolling defense against Furia")

    with monkeypatch.context() as failure:
        failure.setattr(combat, "_allocate_wounds_to_defender", fail_after_defense)
        _assert_rejected(
            closed.state, ActivationProtocolErrorReason.ILLEGAL_ACTION,
            lambda: _resolve_attack(closed.state, dice, sequence=closed.next_sequence),
        )
    assert allocations == [2]
    assert closed.state == original
    assert dice.to_checkpoint() == before
    retried = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    _assert_transition_equal(retried, expected)


def test_furia_native_is_inert_in_v1_and_v2_charge():
    from app.services.engine.resolver import apply

    native = _furia_battle(native=True)
    plain = _furia_battle()
    action = ChargeAction(11, 21, _FURIA_SWORD, counter_attack_declared=False)
    for state in (native, plain):
        v1_dice = DeterministicDice(225)
        v1 = apply(replace(state, initiative_player=None), action, v1_dice)
        ready = _ready_for_action(state=state)
        v2 = _commit(ready.state, action, DeterministicDice(225), sequence=ready.next_sequence)
        fingerprints = (
            next(e for e in v1.events if isinstance(e, MeleeResolved)).hits,
            v1_dice.to_checkpoint(),
            next(e for e in v2.events if isinstance(e, MeleeResolved)).hits,
            v2.dice.to_checkpoint(),
        )
        assert fingerprints[0] == fingerprints[2] == 1
        if state is native:
            expected_fingerprints = fingerprints
        else:
            assert fingerprints == expected_fingerprints


# B4.4d.C2d2 — canonical Podwójny aliases only in closed v3 melee.
_PODWOJNY_ALIASES = (
    ("podwojny",), ("rozrywajacy",), ("podwojny", "rozrywajacy"),
)


def _podwojny_battle(aliases, *, native=False, counter=False, kontra=False):
    state = _furia_battle(native=native, defender_passives=("furia", "kontra") if kontra else ("furia",))
    actor, defender, source = state.blobs
    actor = replace(actor, melee_weapons=(replace(_FURIA_SWORD, weapon_abilities=aliases),))
    if counter:
        defender = replace(defender, melee_weapons=actor.melee_weapons)
    return replace(state, blobs=(actor, defender, source))


def _resolve_podwojny_v3(initial, *, seed, marked=False, counter=False):
    weapon, = initial.blobs[0].melee_weapons
    _, started, first, ready, declared = _marked_declared(
        state=initial, action=ChargeAction(11, 21, weapon, counter_attack_declared=counter),
    )
    dice = DeterministicDice(seed)
    before = dice.to_checkpoint()
    closed, close_tail = _close_furia_attack(declared, dice, marked=marked)
    prefix = (*started.events, *first.events, *ready.events, *declared.events, *close_tail)
    assert apply_events(initial, prefix) == closed.state
    result = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    assert dice.to_checkpoint() == before
    assert apply_events(initial, (*prefix, *result.events)) == result.state
    restarted = _resolve_attack(
        _restart_v3(closed.state), DeterministicDice.from_checkpoint(before),
        sequence=closed.next_sequence,
    )
    _assert_transition_equal(result, restarted)
    future = result.dice.roll_d6(12)
    assert future == restarted.dice.roll_d6(12)
    return result, future


@pytest.mark.parametrize("native,marked", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("seed,natural_six", [(225, True), (58, False)])
def test_v3_podwojny_aliases_share_outcome_rng_and_replay(native, marked, seed, natural_six):
    """Poz. 66 i 7: Podwójny raz, Furia osobno, tylko naturalne 6."""
    fingerprints = []
    for aliases in _PODWOJNY_ALIASES:
        result, future = _resolve_podwojny_v3(
            _podwojny_battle(aliases, native=native), seed=seed, marked=marked,
        )
        event, = (e for e in result.events if isinstance(e, MeleeResolved))
        expected_hits = 2 + int(native or marked) if natural_six else 1
        assert event.hits == expected_hits
        fingerprints.append((result.events, result.next_sequence, result.dice.to_checkpoint(), future))
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]


@pytest.mark.parametrize("kontra", [False, True])
def test_v3_podwojny_aliases_cover_counter_and_main_after_kontra(kontra):
    """Poz. 66/10: Kontra odbiera Furię, nie zdolność własnej broni."""
    fingerprints = []
    for aliases in _PODWOJNY_ALIASES:
        initial = _podwojny_battle(aliases, native=True, counter=True, kontra=kontra)
        result, future = _resolve_podwojny_v3(initial, seed=225, marked=True, counter=True)
        # Seed 225: counter 6, two defense dice, then the charger's 6.
        # Defender's native Furia and the attack mark never add to the counter.
        assert [(e.attacker_id, e.hits) for e in result.events if isinstance(e, MeleeResolved)] == [
            (21, 2), (11, 2 if kontra else 3),
        ]
        fingerprints.append((result.events, result.next_sequence, result.dice.to_checkpoint(), future))
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]


@pytest.mark.parametrize("mismatch", ["open_window", "weapon", "counter_declaration"])
def test_podwojny_canonical_alias_requires_matching_closed_charge(mismatch):
    from app.services.engine.combat import resolve_charge_attack

    initial = _podwojny_battle(("rozrywajacy",))
    actor, defender, source = initial.blobs
    defender = replace(defender, status_flags=(STATUS_WYCZERPANY,))
    initial = replace(initial, blobs=(actor, defender, source))
    weapon, = actor.melee_weapons
    _, _, _, _, declared = _marked_declared(
        state=initial, action=ChargeAction(11, 21, weapon, counter_attack_declared=False),
    )
    dice = DeterministicDice(225)
    closed, _ = _close_furia_attack(declared, dice, marked=False)
    state = declared.state if mismatch == "open_window" else closed.state
    selected_weapon = replace(weapon, slug="other") if mismatch == "weapon" else weapon
    result = resolve_charge_attack(
        state, state.blobs[0], state.blobs[1], selected_weapon, dice, sequence=closed.next_sequence,
        counter_attack_declared=mismatch == "counter_declaration",
    )
    event, = (e for e in result.events if isinstance(e, MeleeResolved))
    assert event.hits == 1
    expected_dice = DeterministicDice(225)
    expected_dice.roll_d6(2)  # One hit test and one defense test, no alias bonus.
    assert dice.to_checkpoint() == expected_dice.to_checkpoint()


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("counter", [False, True])
def test_podwojny_aliases_preserve_legacy_melee_and_rng(version, counter):
    from app.services.engine.resolver import apply

    fingerprints = {}
    for aliases in ((), *_PODWOJNY_ALIASES):
        initial = _podwojny_battle(aliases, native=True, counter=counter, kontra=True)
        weapon, = initial.blobs[0].melee_weapons
        action = ChargeAction(11, 21, weapon, counter_attack_declared=counter)
        dice = DeterministicDice(225)
        if version == 1:
            result = apply(replace(initial, initiative_player=None), action, dice)
            final_dice = dice
        else:
            ready = _ready_for_action(state=initial)
            result = _commit(ready.state, action, dice, sequence=ready.next_sequence)
            final_dice = result.dice
        legacy_bonus = "podwojny" in aliases
        expected = [(21, 2 if legacy_bonus else 1), (11, 2 if legacy_bonus else 0)] if counter else [
            (11, 2 if legacy_bonus else 1),
        ]
        assert [(e.attacker_id, e.hits) for e in result.events if isinstance(e, MeleeResolved)] == expected
        fingerprints[aliases] = (result.events, final_dice.to_checkpoint(), final_dice.roll_d6(12))
    assert fingerprints[()] == fingerprints[("rozrywajacy",)]
    assert fingerprints[("podwojny",)] == fingerprints[("podwojny", "rozrywajacy")]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_podwojny_aliases_leave_ranged_outcome_and_rng_unchanged(version):
    from app.services.engine.resolver import apply

    fingerprints = {}
    for aliases in ((), *_PODWOJNY_ALIASES):
        initial = _furia_battle(native=True)
        actor, defender, source = initial.blobs
        weapon = replace(_FURIA_RIFLE, weapon_abilities=aliases)
        initial = replace(initial, blobs=(replace(actor, ranged_weapons=(weapon,)), defender, source))
        action = ShootAction(11, 21, weapon)
        dice = DeterministicDice(225)
        if version == 1:
            result = apply(replace(initial, initiative_player=None), action, dice)
            final_dice = dice
        elif version == 2:
            ready = _ready_for_action(state=initial)
            result = _commit(ready.state, action, dice, sequence=ready.next_sequence)
            final_dice = result.dice
        else:
            _, _, _, _, declared = _marked_declared(state=initial, action=action)
            closed, _ = _close_furia_attack(declared, dice, marked=True)
            result = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
            final_dice = result.dice
        shot, = (e for e in result.events if isinstance(e, ShotResolved))
        assert shot.hits == (2 if "podwojny" in aliases else 1)
        fingerprints[aliases] = (result.events, final_dice.to_checkpoint(), final_dice.roll_d6(12))
    assert fingerprints[()] == fingerprints[("rozrywajacy",)]
    assert fingerprints[("podwojny",)] == fingerprints[("podwojny", "rozrywajacy")]


@pytest.mark.parametrize('payload', [
    {}, {'ability': ''}, {'ability': True}, {'ability': 1},
    {'ability': 'tarcza'}, {'ability': 'delikatny'},
    {'ability': 'przygotowanie'}, {'ability': 'missing'},
    {'ability': 'planowanie', 'target_id': 21},
    {'ability': 'planowanie', 'sequence': 999},
    {'ability': 'planowanie', 'granted': True},
    {'ability': 'x' * 129},
])
def test_v3_oznaczenie_rejects_noncanonical_payload_without_mutation(payload) -> None:
    _, _, _, _, declared = _marked_declared()
    dice = DeterministicDice(421)
    before = dice.to_checkpoint()
    with pytest.raises(ActivationProtocolError) as error:
        _mark_attack(declared.state, dice, sequence=declared.next_sequence, payload=payload)
    assert error.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert dice.to_checkpoint() == before
    assert declared.state.activation.attack.window.interrupt_count == 0
    assert declared.state.used_interrupts_this_round == ()


def test_v3_oznaczenie_guards_source_range_limit_and_cached_catalog(monkeypatch) -> None:
    from app.services.rulesets import loader

    _, _, _, _, declared = _marked_declared()
    dice = DeterministicDice(423)
    before = dice.to_checkpoint()
    monkeypatch.setattr(loader, '_read_bytes', lambda _path: pytest.fail('runtime YAML I/O'))
    marked = _mark_attack(declared.state, dice, sequence=declared.next_sequence)
    assert marked.state.used_interrupts_this_round == ((12, 'oznaczenie'),)
    with pytest.raises(ActivationProtocolError) as used:
        _mark_attack(marked.state, dice, sequence=marked.next_sequence)
    assert used.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    duplicate = replace(marked.state, used_interrupts_this_round=())
    with pytest.raises(ActivationProtocolError):
        _mark_attack(duplicate, dice, sequence=marked.next_sequence)

    def changed_source(**changes):
        source = next(b for b in declared.state.blobs if b.id == 12)
        altered = replace(source, **changes)
        return replace(
            declared.state,
            blobs=tuple(altered if b.id == 12 else b for b in declared.state.blobs),
        )

    for state in (
        changed_source(models_alive=0),
        changed_source(location=Lokalizacja.ZAPLECZE),
        changed_source(passives=()),
        changed_source(passives=(), ability_overrides=(('oznaczenie', True),)),
        changed_source(position=Position(20.01, 0)),
        changed_source(owner_player=1),
    ):
        with pytest.raises(ActivationProtocolError):
            _mark_attack(state, dice, sequence=declared.next_sequence)
    actor = next(b for b in declared.state.blobs if b.id == 11)
    self_mark_state = replace(
        declared.state,
        blobs=tuple(replace(actor, passives=('oznaczenie',)) if b.id == 11 else b for b in declared.state.blobs),
    )
    with pytest.raises(ActivationProtocolError):
        _mark_attack(self_mark_state, dice, sequence=declared.next_sequence, source_unit_id=11)
    for guards, reason in (
        ({'caller_player': 1}, ActivationProtocolErrorReason.INVALID_CALLER),
        ({'expected_activation_version': 99}, ActivationProtocolErrorReason.STALE_ACTIVATION),
        ({'expected_attack_version': 99}, ActivationProtocolErrorReason.STALE_ATTACK),
        ({'expected_window_version': 99}, ActivationProtocolErrorReason.STALE_WINDOW),
        ({'attack_id': True}, ActivationProtocolErrorReason.STALE_ATTACK),
    ):
        with pytest.raises(ActivationProtocolError) as error:
            _mark_attack(declared.state, dice, sequence=declared.next_sequence, **guards)
        assert error.value.reason is reason
    assert dice.to_checkpoint() == before
    assert declared.state.used_interrupts_this_round == ()

    activation = declared.state.activation
    attack = activation.attack
    saturated_window = replace(attack.window, version=65, interrupt_count=64)
    saturated = replace(
        declared.state,
        activation=replace(
            activation, version=activation.version + 64,
            attack=replace(attack, version=65, window=saturated_window),
        ),
    )
    with pytest.raises(ActivationProtocolError) as error:
        _mark_attack(saturated, dice, sequence=declared.next_sequence)
    assert error.value.reason is ActivationProtocolErrorReason.INTERRUPT_LIMIT_REACHED


def test_v3_oznaczenie_handler_failure_preserves_head_and_rng(monkeypatch) -> None:
    from app.services.engine import activation_protocol

    _, _, _, _, declared = _marked_declared()
    dice = DeterministicDice(431)
    before = dice.to_checkpoint()

    def broken_handler(**_kwargs):
        raise RuntimeError('late handler failure')

    monkeypatch.setattr(
        activation_protocol, 'execute_oznaczenie_attack_interrupt_outcomes',
        broken_handler,
    )
    with pytest.raises(ActivationProtocolError) as error:
        _mark_attack(declared.state, dice, sequence=declared.next_sequence)
    assert error.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert declared.state.activation.attack.window.interrupt_count == 0
    assert declared.state.used_interrupts_this_round == ()
    assert dice.to_checkpoint() == before

    monkeypatch.setattr(
        activation_protocol, 'execute_oznaczenie_attack_interrupt_outcomes',
        lambda **kwargs: (kwargs['state'], ()),
    )
    with pytest.raises(ActivationProtocolError) as malformed:
        _mark_attack(declared.state, dice, sequence=declared.next_sequence)
    assert malformed.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert dice.to_checkpoint() == before


# C2d3: actual Ostrozny outcomes in closed ranged v3, not public publication.
def _ostrozny_battle(*, native=False, gap=17.0):
    state = _furia_battle()
    actor, target, source = state.blobs
    actor = replace(actor, passives=("ostrozny",) if native else (), quality=4,
                    radius_inches=1.0)
    target = replace(target, position=Position(3.0 + gap, 0), radius_inches=2.0)
    source = replace(source, position=Position(target.position.x, 5))
    return replace(state, blobs=(actor, target, source))


def _close_ostrozny(initial, *, marked=False):
    weapon = initial.blobs[0].ranged_weapons[0]
    _, started, first, ready, declared = _marked_declared(
        state=initial, action=ShootAction(11, 21, weapon),
    )
    prefix = [*started.events, *first.events, *ready.events, *declared.events]
    head = declared
    if marked:
        head = _mark_attack(head.state, DeterministicDice(7), sequence=head.next_sequence,
                            payload={"ability": "ostrozny"})
        prefix.extend(head.events)
    for _ in range(2):
        head = _pass_attack(head.state,
                            caller_player=head.state.activation.attack.window.priority_player,
                            sequence=head.next_sequence)
        prefix.extend(head.events)
    return head, prefix, declared


@pytest.mark.parametrize("native,marked", [(True, False), (False, True), (True, True), (False, False)])
@pytest.mark.parametrize("gap,near", [(11.999, True), (12.0, True), (12.001, False)])
def test_v3_ostrozny_real_hits_restart_replay_and_future_rng(native, marked, gap, near):
    initial = _ostrozny_battle(native=native, gap=gap)
    closed, prefix, _ = _close_ostrozny(initial, marked=marked)
    assert apply_events(initial, prefix) == closed.state
    dice = DeterministicDice(7)  # first natural 3: succeeds only with +1 at quality4
    before = dice.to_checkpoint()
    result = _resolve_attack(closed.state, dice, sequence=closed.next_sequence)
    shot, = (e for e in result.events if isinstance(e, ShotResolved))
    assert shot.hits == int((native or marked) and not near)
    assert apply_events(initial, (*prefix, *result.events)) == result.state
    assert result.state.activation.attack is None
    assert effective_passives(result.state.blobs[0]) == effective_passives(initial.blobs[0])
    assert dice.to_checkpoint() == before
    restarted = _resolve_attack(_restart_v3(closed.state),
                                DeterministicDice.from_checkpoint(before), sequence=closed.next_sequence)
    _assert_transition_equal(result, restarted)
    assert result.dice.roll_d6(12) == restarted.dice.roll_d6(12)
    # Resolved scope cannot grant a bonus to the next direct ranged call.
    from app.services.engine.combat import resolve_ranged_attack
    actor, target, _ = result.state.blobs
    after = resolve_ranged_attack(result.state, actor, target, actor.ranged_weapons[0],
                                  DeterministicDice(7), result.next_sequence)
    assert next(e for e in after.events if isinstance(e, ShotResolved)).hits == 0


@pytest.mark.parametrize("change", ["open", "actor", "target", "profile", "inventory", "other_state", "no_state"])
def test_ostrozny_closed_shoot_matcher_rejects_wrong_context(change):
    from app.services.engine.combat import _matching_closed_shoot, resolve_ranged_attack
    from app.services.engine.prediction import expected_damage

    initial = _ostrozny_battle(native=True)
    closed, _, declared = _close_ostrozny(initial)
    state = declared.state if change == "open" else closed.state
    actor, target, source = state.blobs
    weapon = actor.ranged_weapons[0]
    if change == "actor":
        actor = replace(actor, id=99)
    elif change == "target":
        target = replace(target, id=99)
    elif change == "profile":
        weapon = replace(weapon, attacks=2)
    elif change == "inventory":
        actor = replace(actor, ranged_weapons=())
        state = replace(state, blobs=(actor, target, source))
    elif change == "other_state":
        state = replace(state, blobs=(replace(actor, position=Position(0, 5)), target, source))
    elif change == "no_state":
        state = replace(state, activation=None)
    assert _matching_closed_shoot(state, actor, target, weapon) is None
    actual = resolve_ranged_attack(state, actor, target, weapon, DeterministicDice(7), 1)
    plain = resolve_ranged_attack(replace(state, activation=None), actor, target, weapon,
                                  DeterministicDice(7), 1)
    assert actual == plain
    assert expected_damage(actor, target, weapon, state=state) == expected_damage(actor, target, weapon)


@pytest.mark.parametrize("nearby", [False, True])
def test_ostrozny_prediction_matches_closed_v3_monte_carlo(nearby):
    from app.services.engine.combat import resolve_ranged_attack
    from app.services.engine.prediction import expected_damage
    import math

    initial = _ostrozny_battle(native=True)
    if nearby:
        actor, target, source = initial.blobs
        enemy = replace(target, id=99, position=Position(0, 8))
        initial = replace(initial, blobs=(actor, target, source, enemy))
    closed, _, _ = _close_ostrozny(initial)
    actor, target = closed.state.blobs[:2]
    weapon = actor.ranged_weapons[0]
    predicted = expected_damage(actor, target, weapon, state=closed.state)
    legacy = expected_damage(actor, target, weapon)
    assert (predicted.mean > legacy.mean) is (not nearby)
    values = []
    for seed in range(1000):
        outcome = resolve_ranged_attack(closed.state, actor, target, weapon, DeterministicDice(seed), 1)
        shot = next(e for e in outcome.events if isinstance(e, ShotResolved))
        values.append(shot.wounds_dealt + shot.wounds_precise)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    assert abs(mean - predicted.mean) <= 3 * math.sqrt(variance / len(values))


def test_ostrozny_failed_resolve_does_not_mutate_input_and_retries(monkeypatch):
    from app.services.engine import combat

    initial = _ostrozny_battle()
    closed, _, _ = _close_ostrozny(initial, marked=True)
    dice = DeterministicDice(7)
    before = dice.to_checkpoint()
    expected = _resolve_attack(closed.state, DeterministicDice(7), sequence=closed.next_sequence)
    original = _restart_v3(closed.state)

    def fail(*args, **kwargs):
        raise RuntimeError("allocation failure after Ostrozny hit")

    with monkeypatch.context() as failure:
        failure.setattr(combat, "_allocate_wounds_to_defender", fail)
        _assert_rejected(closed.state, ActivationProtocolErrorReason.ILLEGAL_ACTION,
                         lambda: _resolve_attack(closed.state, dice, sequence=closed.next_sequence))
    assert closed.state == original
    assert dice.to_checkpoint() == before
    _assert_transition_equal(_resolve_attack(closed.state, dice, sequence=closed.next_sequence), expected)


@pytest.mark.parametrize("seed", [2, 7, 225])
def test_ostrozny_native_preserves_legacy_ranged_and_melee_rng(seed):
    from app.services.engine.combat import resolve_ranged_attack, resolve_melee_attack

    initial = _ostrozny_battle(native=True)
    actor, target, _ = initial.blobs
    for resolver, weapon in [(resolve_ranged_attack, actor.ranged_weapons[0]),
                              (resolve_melee_attack, actor.melee_weapons[0])]:
        a, b = DeterministicDice(seed), DeterministicDice(seed)
        plain = replace(actor, passives=())
        actual = resolver(initial, actor, target, weapon, a, 1)
        expected = resolver(initial, plain, target, weapon, b, 1)
        assert actual.events == expected.events
        assert actual.new_defender == expected.new_defender
        assert replace(actual.new_attacker, passives=()) == expected.new_attacker
        assert a.to_checkpoint() == b.to_checkpoint()


@pytest.mark.parametrize("quality", [2, 3, 4, 6])
@pytest.mark.parametrize("seed,roll", [(2, 1), (7, 3), (225, 6)])
def test_ostrozny_respects_clamp_and_natural_one_six(quality, seed, roll):
    initial = _ostrozny_battle(native=True)
    actor, target, source = initial.blobs
    initial = replace(initial, blobs=(replace(actor, quality=quality), target, source))
    closed, _, _ = _close_ostrozny(initial)
    result = _resolve_attack(closed.state, DeterministicDice(seed), sequence=closed.next_sequence)
    shot = next(e for e in result.events if isinstance(e, ShotResolved))
    assert shot.hits == int(roll == 6 or (roll != 1 and roll >= max(2, quality - 1)))


@pytest.mark.parametrize("second_profile,source_correct,expected", [
    (False, False, [1, 1]), (True, False, [1, 0]), (False, True, [0, 0]),
])
def test_ostrozny_volley_qualifies_each_profile_before_allocation(
    second_profile, source_correct, expected, monkeypatch,
):
    from app.services.engine import combat

    closed, _, _ = _close_ostrozny(_ostrozny_battle(native=True))
    actor, target = closed.state.blobs[:2]
    weapon = actor.ranged_weapons[0]
    other = replace(weapon, slug="other") if second_profile else weapon
    modifiers = []
    original = combat._aggregate_passive_attack

    def record(*args, **kwargs):
        modifier = original(*args, **kwargs)
        modifiers.append(modifier)
        assert closed.state.blobs[1] == target
        return modifier

    monkeypatch.setattr(combat, "_aggregate_passive_attack", record)
    combat._resolve_ranged_volley(closed.state, actor, (
        combat._RangedProfileDeclaration(target, weapon),
        combat._RangedProfileDeclaration(target, other),
    ), DeterministicDice(7), 1, source_correct=source_correct)
    assert modifiers == expected


def test_ostrozny_rejects_closed_charge_intent_and_v2_ready_context():
    from app.services.engine.combat import _matching_closed_shoot
    from app.services.engine.state import ChargeAttackIntent

    closed, _, _ = _close_ostrozny(_ostrozny_battle(native=True))
    actor, target = closed.state.blobs[:2]
    attack = replace(closed.state.activation.attack,
                     intent=ChargeAttackIntent(actor.id, target.id, actor.ranged_weapons[0].slug, False))
    activation = replace(closed.state.activation, attack=attack)
    assert _matching_closed_shoot(replace(closed.state, activation=activation),
                                  actor, target, actor.ranged_weapons[0]) is None
    ready = replace(activation, phase=ActivationPhase.ACTION_READY, attack=None)
    assert _matching_closed_shoot(replace(closed.state, activation=ready),
                                  actor, target, actor.ranged_weapons[0]) is None
