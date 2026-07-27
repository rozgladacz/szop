from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.services.engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    continue_activation,
    pass_interrupt_priority,
    start_activation,
)
from app.services.engine.events import (
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationInterruptTriggered,
    ActivationStarted,
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
    )


def _idle_state(
    *,
    initiative_player: int | None = 0,
    active_player: int = 0,
    own_statuses: tuple[str, ...] = (),
) -> BattleState:
    return BattleState(
        round=1,
        active_player=active_player,
        activations_remaining=(1, 1),
        blobs=(
            _unit(11, 0, status_flags=own_statuses),
            _unit(21, 1),
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
