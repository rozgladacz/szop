from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest

from app.services.engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    continue_activation,
    pass_interrupt_priority,
    start_activation,
    trigger_activation_interrupt,
)
from app.services.engine.events import (
    AbilityOverrideApplied,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationInterruptTriggered,
    ActivationStarted,
    EffectApplied,
    InterruptTriggered,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    StatusRemoved,
    event_to_json,
)
from app.services.engine.state import (
    ActivationPhase,
    BattleState,
    Lokalizacja,
    Position,
    UnitBlob,
    apply_events,
)
from app.services.engine.state_codec import (
    battle_state_from_json,
    battle_state_to_json,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
)


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
