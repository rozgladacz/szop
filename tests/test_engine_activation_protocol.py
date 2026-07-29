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
    commit_activation_action,
    continue_activation,
    finalize_activation,
    pass_interrupt_priority,
    start_activation,
    trigger_activation_interrupt,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.interrupts import (
    execute_ready_activation_interrupt_outcomes,
)
from app.services.engine.events import (
    ActivePlayerChanged,
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
    MoveExecuted,
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
)
from app.services.engine.state_codec import (
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
    sequence: int,
):
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

    def mismatched_executor(*, state, source, ability_slug, payload, sequence):
        _, events = _fake_outcome_executor(
            state=state,
            source=source,
            ability_slug=ability_slug,
            payload=payload,
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

    def skipped_sequence_executor(*, state, source, ability_slug, payload, sequence):
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

    def marker_count_executor(*, state, source, ability_slug, payload, sequence):
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

    def nested_executor(*, state, source, ability_slug, payload, sequence):
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

    def invalid_event_executor(*, state, source, ability_slug, payload, sequence):
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

    def oversized_executor(*, state, source, ability_slug, payload, sequence):
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

    def trigger(current):
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
            sequence=started.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )

    interrupted = trigger(started.state)
    restarted = trigger(_restart(started.state))
    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in interrupted.events
    ]
    assert restarted.state == interrupted.state
    assert restarted.next_sequence == interrupted.next_sequence
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

    def trigger(current):
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
            sequence=started.next_sequence,
            outcome_executor=execute_ready_activation_interrupt_outcomes,
        )

    interrupted = trigger(started.state)
    restarted = trigger(_restart(started.state))
    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in interrupted.events
    ]
    assert restarted.state == interrupted.state
    assert restarted.next_sequence == interrupted.next_sequence
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
        state=_action_idle_state(actor_statuses=(STATUS_WYCZERPANY,)),
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
