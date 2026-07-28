from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.db import Base
from app.services import battle_activations as activation_service
from app.services.battle_activations import (
    BattleActivationActionForbidden,
    BattleActivationActionInvalid,
    BattleActivationActionNotFound,
    BattleActivationActionSequenceConflict,
    BattleActivationActionUnavailable,
    BattleActivationActionUpgradeRequired,
    BattleActivationActionWriteConflict,
    BattleActivationPassInvalid,
    BattleActivationPassNotFound,
    BattleActivationPassSequenceConflict,
    BattleActivationPassUnavailable,
    BattleActivationPassUpgradeRequired,
    BattleActivationPassWriteConflict,
    BattleActivationStartForbidden,
    BattleActivationStartInvalid,
    BattleActivationStartNotFound,
    BattleActivationStartSequenceConflict,
    BattleActivationStartUnavailable,
    BattleActivationStartUpgradeRequired,
    BattleActivationStartWriteConflict,
    stage_battle_activation_action,
    stage_battle_activation_pass,
    stage_battle_activation_start,
)
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction, ManeuverAction
from app.services.engine.activation_protocol import (
    ActivationProtocolErrorReason,
    commit_activation_action,
    continue_activation,
    pass_interrupt_priority,
    start_activation,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivationActionCommitted,
    ActivationStarted,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    MoveExecuted,
    StatusRemoved,
)
from app.services.engine.persistence import (
    BattleCheckpointSequenceConflict,
    load_events,
    load_latest_checkpoint,
    save_checkpoint,
    save_events,
)
from app.services.engine.state import (
    ActivationPhase,
    BattleState,
    Lokalizacja,
    Position,
    UnitBlob,
    apply_events,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
)


@dataclass(frozen=True, slots=True)
class ActivationWorld:
    engine: object
    sessions: sessionmaker[Session]
    p1_id: int
    p2_id: int
    outsider_id: int


@pytest.fixture
def activation_world(tmp_path: Path) -> ActivationWorld:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'activation-service.sqlite3'}",
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with sessions() as session:
        users = [
            models.User(username=name, password_hash="x")
            for name in ("activation-p1", "activation-p2", "activation-outsider")
        ]
        session.add_all(users)
        session.commit()
        return ActivationWorld(
            engine=engine,
            sessions=sessions,
            p1_id=users[0].id,
            p2_id=users[1].id,
            outsider_id=users[2].id,
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
    active_player: int = 0,
    initiative_player: int | None = 0,
    selected_statuses: tuple[str, ...] = (),
    selected_models_alive: int = 1,
    selected_location: Lokalizacja = Lokalizacja.FRONT,
    extra_units_per_player: int = 0,
) -> BattleState:
    units = [
        _unit(
            11,
            0,
            models_alive=selected_models_alive,
            location=selected_location,
            status_flags=selected_statuses,
        ),
        _unit(21, 1),
    ]
    for offset in range(extra_units_per_player):
        units.extend(
            (
                _unit(100 + offset, 0),
                _unit(200 + offset, 1),
            )
        )
    return BattleState(
        round=1,
        active_player=active_player,
        activations_remaining=(1 + extra_units_per_player,) * 2,
        blobs=tuple(units),
        terrain=(),
        initiative_player=initiative_player,
    )


def _persist_battle(
    world: ActivationWorld,
    *,
    state: BattleState | None = None,
    p1_id: int | None = None,
    p2_id: int | None = None,
    status: str = "active",
    protocol_version: int = 2,
    checkpoint_version: int | None = None,
    with_checkpoint: bool = True,
) -> int:
    persisted_state = state or _idle_state()
    with world.sessions() as session:
        battle = models.Battle(
            p1_user_id=world.p1_id if p1_id is None else p1_id,
            p2_user_id=world.p2_id if p2_id is None else p2_id,
            current_round=persisted_state.round,
            rng_seed=2026,
            status=status,
            activation_protocol_version=protocol_version,
        )
        session.add(battle)
        session.flush()
        if with_checkpoint:
            save_checkpoint(
                session,
                battle.id,
                0,
                persisted_state,
                DeterministicDice(2026),
                state_version=(
                    protocol_version
                    if checkpoint_version is None
                    else checkpoint_version
                ),
            )
        session.commit()
        return battle.id


def _stream_snapshot(
    world: ActivationWorld,
    battle_id: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    with world.sessions() as session:
        event_sequences = tuple(
            session.scalars(
                select(models.BattleEvent.sequence)
                .where(models.BattleEvent.battle_id == battle_id)
                .order_by(models.BattleEvent.sequence)
            )
        )
        checkpoint_sequences = tuple(
            session.scalars(
                select(models.BattleCheckpoint.sequence_at)
                .where(models.BattleCheckpoint.battle_id == battle_id)
                .order_by(models.BattleCheckpoint.sequence_at)
            )
        )
        return event_sequences, checkpoint_sequences


def _persist_started_battle(
    world: ActivationWorld,
    *,
    state: BattleState | None = None,
    p1_id: int | None = None,
    p2_id: int | None = None,
    extra_units_per_player: int = 0,
) -> tuple[int, object]:
    initial = state or _idle_state(
        extra_units_per_player=extra_units_per_player
    )
    battle_id = _persist_battle(
        world,
        state=initial,
        p1_id=p1_id,
        p2_id=p2_id,
    )
    participant_ids = (
        world.p1_id if p1_id is None else p1_id,
        world.p2_id if p2_id is None else p2_id,
    )
    caller_user_id = participant_ids[initial.active_player]
    selected_unit_id = 11 if initial.active_player == 0 else 21
    with world.sessions() as session:
        staged = stage_battle_activation_start(
            session,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
            selected_unit_id=selected_unit_id,
            expected_sequence=0,
        )
        session.commit()
    return battle_id, staged


def _pass_guards(state: BattleState) -> dict[str, int]:
    activation = state.activation
    assert activation is not None
    assert activation.window is not None
    return {
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
        "expected_window_version": activation.window.version,
    }


def _persist_action_ready_battle(
    world: ActivationWorld,
    *,
    state: BattleState | None = None,
    p1_id: int | None = None,
    p2_id: int | None = None,
    extra_units_per_player: int = 0,
) -> int:
    battle_id, _ = _persist_started_battle(
        world,
        state=state,
        p1_id=p1_id,
        p2_id=p2_id,
        extra_units_per_player=extra_units_per_player,
    )
    participant_ids = (
        world.p1_id if p1_id is None else p1_id,
        world.p2_id if p2_id is None else p2_id,
    )
    for _ in range(2):
        with world.sessions() as session:
            checkpoint = load_latest_checkpoint(session, battle_id)
            assert checkpoint is not None
            activation = checkpoint.state.activation
            assert activation is not None
            assert activation.window is not None
            priority_player = activation.window.priority_player
            stage_battle_activation_pass(
                session,
                battle_id=battle_id,
                caller_user_id=participant_ids[priority_player],
                expected_sequence=checkpoint.sequence_at,
                **_pass_guards(checkpoint.state),
            )
            session.commit()
    return battle_id


def _action_guards(state: BattleState) -> dict[str, int]:
    activation = state.activation
    assert activation is not None
    return {
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
    }


def test_stage_start_persists_exact_batch_checkpoint_and_restart_safe_rng(
    activation_world: ActivationWorld,
) -> None:
    initial = _idle_state(selected_statuses=(STATUS_PRZYGOTOWANY,))
    battle_id = _persist_battle(activation_world, state=initial)
    expected = start_activation(initial, selected_unit_id=11, sequence=1)
    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        before_rng = before.dice.to_checkpoint()
        before_rng_json = session.scalar(
            select(models.BattleCheckpoint.rng_json).where(
                models.BattleCheckpoint.battle_id == battle_id,
                models.BattleCheckpoint.sequence_at == 0,
            )
        )

        staged = stage_battle_activation_start(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            selected_unit_id=11,
            expected_sequence=0,
        )

        assert staged.previous_sequence == 0
        assert staged.new_sequence == 3
        assert staged.events == expected.events
        assert [type(item) for item in staged.events] == [
            ActivationStarted,
            StatusRemoved,
            InterruptWindowOpened,
        ]
        assert [item.sequence for item in staged.events] == [1, 2, 3]
        assert staged.state == expected.state
        assert staged.state == apply_events(initial, staged.events)
        assert staged.state.activation is not None
        assert staged.state.activation.phase is ActivationPhase.BEFORE_ACTION
        assert staged.dice.to_checkpoint() == before_rng

        with activation_world.sessions() as uncommitted_reader:
            unseen = load_latest_checkpoint(uncommitted_reader, battle_id)
            assert unseen is not None
            assert unseen.sequence_at == 0
            assert load_events(uncommitted_reader, battle_id) == []

        session.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.sequence_at == staged.new_sequence
        assert checkpoint.state == staged.state
        assert checkpoint.dice.to_checkpoint() == before_rng
        assert tuple(load_events(restarted, battle_id)) == staged.events
        checkpoint_rows = restarted.scalar(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == battle_id)
        )
        assert checkpoint_rows == 2
        assert _stream_snapshot(activation_world, battle_id) == (
            (1, 2, 3),
            (0, 3),
        )
        assert restarted.scalar(
            select(models.BattleCheckpoint.rng_json).where(
                models.BattleCheckpoint.battle_id == battle_id,
                models.BattleCheckpoint.sequence_at == staged.new_sequence,
            )
        ) == before_rng_json

    live_dice = DeterministicDice.from_checkpoint(before_rng)
    restarted_dice = DeterministicDice.from_checkpoint(
        checkpoint.dice.to_checkpoint()
    )
    assert live_dice.roll_d6(32) == restarted_dice.roll_d6(32)


def test_missing_and_foreign_battles_share_the_same_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    foreign_id = _persist_battle(activation_world)
    with activation_world.sessions() as session:
        failures = []
        for battle_id in (foreign_id, foreign_id + 999):
            with pytest.raises(BattleActivationStartNotFound) as exc_info:
                stage_battle_activation_start(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    selected_unit_id=11,
                    expected_sequence=0,
                )
            failures.append((type(exc_info.value), str(exc_info.value)))

    assert failures[0] == failures[1]
    assert _stream_snapshot(activation_world, foreign_id) == ((), (0,))


def test_two_owner_matrix_enforces_active_side_and_selected_unit_ownership(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_battle(activation_world)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartForbidden):
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p2_id,
                selected_unit_id=21,
                expected_sequence=0,
            )
        with pytest.raises(BattleActivationStartInvalid) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=21,
                expected_sequence=0,
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_SELECTION
    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


def test_same_owner_sandbox_resolves_control_from_current_active_player(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_battle(
        activation_world,
        state=_idle_state(active_player=1, initiative_player=0),
        p1_id=activation_world.p1_id,
        p2_id=activation_world.p1_id,
    )
    with activation_world.sessions() as session:
        staged = stage_battle_activation_start(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            selected_unit_id=21,
            expected_sequence=0,
        )
        session.commit()

    assert staged.state.activation is not None
    assert staged.state.activation.controlling_player == 1


@pytest.mark.parametrize(
    ("field", "value", "error_type", "reason"),
    [
        ("battle_id", True, BattleActivationStartNotFound, None),
        ("caller_user_id", False, BattleActivationStartNotFound, None),
        (
            "selected_unit_id",
            True,
            BattleActivationStartInvalid,
            ActivationProtocolErrorReason.INVALID_SELECTION,
        ),
        (
            "selected_unit_id",
            0,
            BattleActivationStartInvalid,
            ActivationProtocolErrorReason.INVALID_SELECTION,
        ),
        ("selected_unit_id", "11", BattleActivationStartInvalid, None),
        ("expected_sequence", True, BattleActivationStartInvalid, None),
        ("expected_sequence", -1, BattleActivationStartInvalid, None),
        ("expected_sequence", "0", BattleActivationStartInvalid, None),
    ],
)
def test_malformed_and_bool_inputs_fail_without_writes(
    activation_world: ActivationWorld,
    field: str,
    value: object,
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    battle_id = _persist_battle(activation_world)
    kwargs = {
        "battle_id": battle_id,
        "caller_user_id": activation_world.p1_id,
        "selected_unit_id": 11,
        "expected_sequence": 0,
    }
    kwargs[field] = value
    with activation_world.sessions() as session:
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_start(session, **kwargs)
        if reason is not None:
            assert exc_info.value.reason is reason

    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


def test_v1_battle_fails_upgrade_required_without_touching_checkpoint(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
        checkpoint_version=1,
    )
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartUpgradeRequired):
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )

    assert _stream_snapshot(activation_world, battle_id) == before


def test_stale_sequence_fails_before_pure_transition_or_writes(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_battle(activation_world)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartSequenceConflict) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=7,
            )

    assert exc_info.value.expected_sequence == 7
    assert exc_info.value.actual_sequence == 0
    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


def test_missing_stale_and_protocol_mismatched_checkpoints_are_unavailable(
    activation_world: ActivationWorld,
) -> None:
    missing_id = _persist_battle(activation_world, with_checkpoint=False)
    stale_id = _persist_battle(activation_world)
    mismatch_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=2,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        stale_event = MoveExecuted(
            sequence=1,
            unit_id=11,
            from_pos=(11.0, 0.0),
            to_pos=(12.0, 0.0),
        )
        save_events(
            session,
            stale_id,
            [stale_event],
            expected_latest_sequence=0,
        )
        session.commit()

    for battle_id, expected_sequence in (
        (missing_id, 0),
        (stale_id, 1),
        (mismatch_id, 0),
    ):
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationStartUnavailable) as exc_info:
                stage_battle_activation_start(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    selected_unit_id=11,
                    expected_sequence=0,
                )
        assert exc_info.value.actual_sequence == expected_sequence


@pytest.mark.parametrize("status", ["pending", "finished"])
def test_inactive_battle_status_rejects_without_writes(
    activation_world: ActivationWorld,
    status: str,
) -> None:
    battle_id = _persist_battle(activation_world, status=status)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartInvalid) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


@pytest.mark.parametrize(
    "state",
    [
        replace(_idle_state(), is_game_over=True),
        start_activation(_idle_state(), selected_unit_id=11).state,
    ],
    ids=["game-over", "already-running"],
)
def test_invalid_activation_phase_rejects_atomically(
    activation_world: ActivationWorld,
    state: BattleState,
) -> None:
    battle_id = _persist_battle(activation_world, state=state)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartInvalid) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


@pytest.mark.parametrize(
    "state",
    [
        _idle_state(selected_models_alive=0),
        _idle_state(selected_location=Lokalizacja.ZAPLECZE),
        _idle_state(selected_statuses=(STATUS_AKTYWOWANY,)),
    ],
    ids=["dead", "off-field", "already-activated"],
)
def test_illegal_selected_unit_invariants_remain_in_pure_start_ssot(
    activation_world: ActivationWorld,
    state: BattleState,
) -> None:
    battle_id = _persist_battle(activation_world, state=state)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartInvalid) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_SELECTION
    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


def test_caller_rollback_after_checkpoint_stage_removes_whole_batch(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    battle_id = _persist_battle(activation_world)
    real_save_checkpoint = activation_service.save_checkpoint

    def fail_after_checkpoint(*args, **kwargs):
        real_save_checkpoint(*args, **kwargs)
        raise BattleCheckpointSequenceConflict(
            args[1],
            sequence_at=args[2],
            latest_sequence=args[2] - 1,
        )

    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        fail_after_checkpoint,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartWriteConflict):
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == ((), (0,))


def test_concurrent_head_change_is_reported_and_never_appends_service_batch(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    battle_id = _persist_battle(activation_world)
    real_save_events = activation_service.save_events
    raced = False

    def race_before_guard(db, persisted_battle_id, events, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            with activation_world.sessions() as competitor:
                real_save_events(
                    competitor,
                    battle_id,
                    [
                        MoveExecuted(
                            sequence=1,
                            unit_id=11,
                            from_pos=(11.0, 0.0),
                            to_pos=(12.0, 0.0),
                        )
                    ],
                    expected_latest_sequence=0,
                )
                competitor.commit()
        return real_save_events(db, persisted_battle_id, events, **kwargs)

    monkeypatch.setattr(activation_service, "save_events", race_before_guard)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationStartSequenceConflict) as exc_info:
            stage_battle_activation_start(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                selected_unit_id=11,
                expected_sequence=0,
            )
        session.rollback()

    assert exc_info.value.actual_sequence == 1
    with activation_world.sessions() as session:
        stored = load_events(session, battle_id)
        assert len(stored) == 1
        assert type(stored[0]) is MoveExecuted
        assert session.scalar(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == battle_id)
        ) == 1


def test_success_query_shape_is_five_selects_without_n_plus_one(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_id = _persist_battle(activation_world)
    large_id = _persist_battle(
        activation_world,
        state=_idle_state(extra_units_per_player=12),
    )
    statements: list[str] = []
    save_event_calls = 0
    save_checkpoint_calls = 0
    real_save_events = activation_service.save_events
    real_save_checkpoint = activation_service.save_checkpoint

    def count_save_events(*args, **kwargs):
        nonlocal save_event_calls
        save_event_calls += 1
        return real_save_events(*args, **kwargs)

    def count_save_checkpoint(*args, **kwargs):
        nonlocal save_checkpoint_calls
        save_checkpoint_calls += 1
        return real_save_checkpoint(*args, **kwargs)

    def capture_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    monkeypatch.setattr(activation_service, "save_events", count_save_events)
    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        count_save_checkpoint,
    )

    select_counts = []
    event.listen(
        activation_world.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        for battle_id in (small_id, large_id):
            statements.clear()
            with activation_world.sessions() as session:
                stage_battle_activation_start(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    selected_unit_id=11,
                    expected_sequence=0,
                )
                select_counts.append(
                    sum(
                        statement.lstrip().upper().startswith("SELECT")
                        for statement in statements
                    )
                )
                session.rollback()
    finally:
        event.remove(
            activation_world.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert select_counts == [5, 5]
    assert save_event_calls == 2
    assert save_checkpoint_calls == 2


def test_stage_pass_persists_both_explicit_passes_across_restarts_with_raw_rng(
    activation_world: ActivationWorld,
) -> None:
    initial = _idle_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    with activation_world.sessions() as first_session:
        before_first = load_latest_checkpoint(first_session, battle_id)
        assert before_first is not None
        first_rng_json = first_session.scalar(
            select(models.BattleCheckpoint.rng_json).where(
                models.BattleCheckpoint.battle_id == battle_id,
                models.BattleCheckpoint.sequence_at == started.new_sequence,
            )
        )
        expected_first = pass_interrupt_priority(
            before_first.state,
            caller_player=0,
            sequence=before_first.sequence_at + 1,
            **_pass_guards(before_first.state),
        )

        first_pass = stage_battle_activation_pass(
            first_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before_first.sequence_at,
            **_pass_guards(before_first.state),
        )

        assert first_pass.events == expected_first.events
        assert [type(item) for item in first_pass.events] == [
            InterruptPriorityPassed
        ]
        assert first_pass.previous_sequence == started.new_sequence
        assert first_pass.new_sequence == started.new_sequence + 1
        assert first_pass.state == apply_events(
            before_first.state,
            first_pass.events,
        )
        assert first_pass.state.activation is not None
        assert first_pass.state.activation.window is not None
        assert first_pass.state.activation.window.priority_player == 1
        assert first_pass.state.activation.window.passed_players == (0,)
        assert (
            first_pass.dice.to_checkpoint()
            == before_first.dice.to_checkpoint()
        )
        with activation_world.sessions() as uncommitted_reader:
            unseen = load_latest_checkpoint(uncommitted_reader, battle_id)
            assert unseen is not None
            assert unseen.sequence_at == started.new_sequence
            assert load_events(
                uncommitted_reader,
                battle_id,
                since=started.new_sequence,
            ) == []
        first_session.commit()

    with activation_world.sessions() as second_session:
        before_second = load_latest_checkpoint(second_session, battle_id)
        assert before_second is not None
        assert before_second.state == first_pass.state
        expected_second = pass_interrupt_priority(
            before_second.state,
            caller_player=1,
            sequence=before_second.sequence_at + 1,
            **_pass_guards(before_second.state),
        )

        second_pass = stage_battle_activation_pass(
            second_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p2_id,
            expected_sequence=before_second.sequence_at,
            **_pass_guards(before_second.state),
        )

        assert second_pass.events == expected_second.events
        assert [type(item) for item in second_pass.events] == [
            InterruptPriorityPassed,
            InterruptWindowClosed,
        ]
        assert second_pass.previous_sequence == first_pass.new_sequence
        assert second_pass.new_sequence == first_pass.new_sequence + 2
        assert second_pass.state == apply_events(
            before_second.state,
            second_pass.events,
        )
        assert second_pass.state.activation is not None
        assert second_pass.state.activation.phase is ActivationPhase.ACTION_READY
        assert second_pass.state.activation.window is None
        assert (
            second_pass.dice.to_checkpoint()
            == before_second.dice.to_checkpoint()
        )
        second_session.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.sequence_at == second_pass.new_sequence
        assert checkpoint.state == second_pass.state
        pass_events = tuple(
            load_events(
                restarted,
                battle_id,
                since=started.new_sequence,
            )
        )
        assert pass_events == (*first_pass.events, *second_pass.events)
        assert checkpoint.state == apply_events(started.state, pass_events)
        rng_rows = tuple(
            restarted.scalars(
                select(models.BattleCheckpoint.rng_json)
                .where(models.BattleCheckpoint.battle_id == battle_id)
                .order_by(models.BattleCheckpoint.sequence_at)
            )
        )
        assert rng_rows
        assert set(rng_rows) == {first_rng_json}
        assert _stream_snapshot(activation_world, battle_id) == (
            (1, 2, 3, 4, 5),
            (0, 2, 3, 5),
        )


def test_pass_two_owner_requires_the_current_priority_owner_each_time(
    activation_world: ActivationWorld,
) -> None:
    battle_id, started = _persist_started_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as wrong_first:
        with pytest.raises(BattleActivationPassInvalid) as exc_info:
            stage_battle_activation_pass(
                wrong_first,
                battle_id=battle_id,
                caller_user_id=activation_world.p2_id,
                expected_sequence=started.new_sequence,
                **_pass_guards(started.state),
            )
    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_CALLER
    assert _stream_snapshot(activation_world, battle_id) == before

    with activation_world.sessions() as first_session:
        first_pass = stage_battle_activation_pass(
            first_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            **_pass_guards(started.state),
        )
        first_session.commit()
    after_first = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as repeated:
        with pytest.raises(BattleActivationPassInvalid) as exc_info:
            stage_battle_activation_pass(
                repeated,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=first_pass.new_sequence,
                **_pass_guards(first_pass.state),
            )
    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_CALLER
    assert _stream_snapshot(activation_world, battle_id) == after_first


def test_pass_same_owner_maps_each_explicit_call_from_durable_priority(
    activation_world: ActivationWorld,
) -> None:
    owner_id = activation_world.p1_id
    battle_id, started = _persist_started_battle(
        activation_world,
        state=_idle_state(active_player=0, initiative_player=1),
        p1_id=owner_id,
        p2_id=owner_id,
    )
    assert started.state.activation is not None
    assert started.state.activation.controlling_player == 0
    assert started.state.activation.window is not None
    assert started.state.activation.window.priority_player == 1

    with activation_world.sessions() as first_session:
        first_pass = stage_battle_activation_pass(
            first_session,
            battle_id=battle_id,
            caller_user_id=owner_id,
            expected_sequence=started.new_sequence,
            **_pass_guards(started.state),
        )
        first_session.commit()
    assert first_pass.events[0].passed_player == 1
    assert first_pass.state.activation.window.priority_player == 0

    with activation_world.sessions() as second_session:
        second_pass = stage_battle_activation_pass(
            second_session,
            battle_id=battle_id,
            caller_user_id=owner_id,
            expected_sequence=first_pass.new_sequence,
            **_pass_guards(first_pass.state),
        )
        second_session.commit()
    assert second_pass.events[0].passed_player == 0
    assert second_pass.state.activation.phase is ActivationPhase.ACTION_READY


def test_pass_missing_and_foreign_battles_share_the_same_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    foreign_id, started = _persist_started_battle(activation_world)
    before = _stream_snapshot(activation_world, foreign_id)
    failures = []

    for battle_id in (foreign_id, foreign_id + 999):
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationPassNotFound) as exc_info:
                stage_battle_activation_pass(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    expected_sequence=started.new_sequence,
                    **_pass_guards(started.state),
                )
            failures.append((type(exc_info.value), str(exc_info.value)))

    assert failures[0] == failures[1]
    assert _stream_snapshot(activation_world, foreign_id) == before


@pytest.mark.parametrize(
    ("field", "value", "error_type", "reason"),
    [
        ("battle_id", True, BattleActivationPassNotFound, None),
        ("battle_id", "1", BattleActivationPassNotFound, None),
        ("battle_id", 0, BattleActivationPassNotFound, None),
        ("caller_user_id", False, BattleActivationPassNotFound, None),
        ("caller_user_id", "1", BattleActivationPassNotFound, None),
        ("caller_user_id", 0, BattleActivationPassNotFound, None),
        ("expected_sequence", True, BattleActivationPassInvalid, None),
        ("expected_sequence", -1, BattleActivationPassInvalid, None),
        ("expected_sequence", "2", BattleActivationPassInvalid, None),
        (
            "activation_id",
            True,
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "activation_id",
            "1",
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "activation_id",
            0,
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            "1",
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            False,
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_window_version",
            0,
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
        (
            "expected_window_version",
            True,
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
        (
            "expected_window_version",
            "1",
            BattleActivationPassInvalid,
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
    ],
)
def test_pass_strict_inputs_reject_bool_coercion_and_invalid_ranges_without_writes(
    activation_world: ActivationWorld,
    field: str,
    value: object,
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    battle_id, started = _persist_started_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    kwargs = {
        "battle_id": battle_id,
        "caller_user_id": activation_world.p1_id,
        "expected_sequence": started.new_sequence,
        **_pass_guards(started.state),
    }
    kwargs[field] = value

    with activation_world.sessions() as session:
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_pass(session, **kwargs)
        if reason is not None:
            assert exc_info.value.reason is reason

    assert _stream_snapshot(activation_world, battle_id) == before


def test_pass_rejects_v1_inactive_stale_sequence_and_wrong_phase_atomically(
    activation_world: ActivationWorld,
) -> None:
    v1_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
        checkpoint_version=1,
    )
    with activation_world.sessions() as v1_session:
        with pytest.raises(BattleActivationPassUpgradeRequired):
            stage_battle_activation_pass(
                v1_session,
                battle_id=v1_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                expected_window_version=1,
            )

    inactive_id, inactive_started = _persist_started_battle(activation_world)
    with activation_world.sessions() as updater:
        battle = updater.get(models.Battle, inactive_id)
        assert battle is not None
        battle.status = "finished"
        updater.commit()
    inactive_before = _stream_snapshot(activation_world, inactive_id)
    with activation_world.sessions() as inactive_session:
        with pytest.raises(BattleActivationPassInvalid) as exc_info:
            stage_battle_activation_pass(
                inactive_session,
                battle_id=inactive_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=inactive_started.new_sequence,
                **_pass_guards(inactive_started.state),
            )
    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, inactive_id) == inactive_before

    active_id, active_started = _persist_started_battle(activation_world)
    active_before = _stream_snapshot(activation_world, active_id)
    with activation_world.sessions() as stale_session:
        with pytest.raises(BattleActivationPassSequenceConflict) as exc_info:
            stage_battle_activation_pass(
                stale_session,
                battle_id=active_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=active_started.new_sequence + 1,
                **_pass_guards(active_started.state),
            )
    assert exc_info.value.actual_sequence == active_started.new_sequence
    assert _stream_snapshot(activation_world, active_id) == active_before

    idle_id = _persist_battle(activation_world)
    idle_before = _stream_snapshot(activation_world, idle_id)
    with activation_world.sessions() as idle_session:
        with pytest.raises(BattleActivationPassInvalid) as exc_info:
            stage_battle_activation_pass(
                idle_session,
                battle_id=idle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                expected_window_version=1,
            )
    assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, idle_id) == idle_before


def test_pass_missing_stale_and_protocol_mismatched_checkpoints_are_unavailable(
    activation_world: ActivationWorld,
) -> None:
    missing_id = _persist_battle(activation_world, with_checkpoint=False)
    stale_id = _persist_battle(activation_world)
    mismatch_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=2,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        save_events(
            session,
            stale_id,
            [
                MoveExecuted(
                    sequence=1,
                    unit_id=11,
                    from_pos=(11.0, 0.0),
                    to_pos=(12.0, 0.0),
                )
            ],
            expected_latest_sequence=0,
        )
        session.commit()

    for battle_id, actual_sequence in (
        (missing_id, 0),
        (stale_id, 1),
        (mismatch_id, 0),
    ):
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationPassUnavailable) as exc_info:
                stage_battle_activation_pass(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=0,
                    activation_id=1,
                    expected_activation_version=1,
                    expected_window_version=1,
                )
        assert exc_info.value.actual_sequence == actual_sequence


@pytest.mark.parametrize(
    ("guard", "reason"),
    [
        (
            {"activation_id": 999},
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            {"expected_activation_version": 999},
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            {"expected_window_version": 999},
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
    ],
)
def test_pass_stale_activation_and_window_guards_fail_without_writes(
    activation_world: ActivationWorld,
    guard: dict[str, int],
    reason: ActivationProtocolErrorReason,
) -> None:
    battle_id, started = _persist_started_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    guards = _pass_guards(started.state)
    guards.update(guard)

    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationPassInvalid) as exc_info:
            stage_battle_activation_pass(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                **guards,
            )

    assert exc_info.value.reason is reason
    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize("failure", ["checkpoint-conflict", "integrity-error"])
def test_pass_caller_rollback_after_checkpoint_stage_removes_whole_batch(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    battle_id, started = _persist_started_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    real_save_checkpoint = activation_service.save_checkpoint

    def fail_after_checkpoint(*args, **kwargs):
        real_save_checkpoint(*args, **kwargs)
        if failure == "integrity-error":
            raise IntegrityError(
                "checkpoint race",
                {},
                Exception("unique"),
            )
        raise BattleCheckpointSequenceConflict(
            args[1],
            sequence_at=args[2],
            latest_sequence=args[2] - 1,
        )

    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        fail_after_checkpoint,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationPassWriteConflict):
            stage_battle_activation_pass(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                **_pass_guards(started.state),
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_pass_concurrent_head_change_is_reported_without_partial_service_batch(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    battle_id, started = _persist_started_battle(activation_world)
    real_save_events = activation_service.save_events
    raced = False

    def race_before_guard(db, persisted_battle_id, events, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            with activation_world.sessions() as competitor:
                real_save_events(
                    competitor,
                    battle_id,
                    [
                        MoveExecuted(
                            sequence=started.new_sequence + 1,
                            unit_id=11,
                            from_pos=(11.0, 0.0),
                            to_pos=(12.0, 0.0),
                        )
                    ],
                    expected_latest_sequence=started.new_sequence,
                )
                competitor.commit()
        return real_save_events(db, persisted_battle_id, events, **kwargs)

    monkeypatch.setattr(activation_service, "save_events", race_before_guard)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationPassSequenceConflict) as exc_info:
            stage_battle_activation_pass(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                **_pass_guards(started.state),
            )
        session.rollback()

    assert exc_info.value.actual_sequence == started.new_sequence + 1
    with activation_world.sessions() as session:
        tail = load_events(
            session,
            battle_id,
            since=started.new_sequence,
        )
        assert len(tail) == 1
        assert type(tail[0]) is MoveExecuted
        assert session.scalar(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == battle_id)
        ) == 2


def test_pass_success_query_shape_is_five_selects_without_n_plus_one(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_id, small_started = _persist_started_battle(activation_world)
    large_id, large_started = _persist_started_battle(
        activation_world,
        extra_units_per_player=12,
    )
    statements: list[str] = []
    save_event_calls = 0
    save_checkpoint_calls = 0
    real_save_events = activation_service.save_events
    real_save_checkpoint = activation_service.save_checkpoint

    def count_save_events(*args, **kwargs):
        nonlocal save_event_calls
        save_event_calls += 1
        return real_save_events(*args, **kwargs)

    def count_save_checkpoint(*args, **kwargs):
        nonlocal save_checkpoint_calls
        save_checkpoint_calls += 1
        return real_save_checkpoint(*args, **kwargs)

    def capture_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    monkeypatch.setattr(activation_service, "save_events", count_save_events)
    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        count_save_checkpoint,
    )
    select_counts = []
    event.listen(
        activation_world.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        for battle_id, started in (
            (small_id, small_started),
            (large_id, large_started),
        ):
            statements.clear()
            with activation_world.sessions() as session:
                stage_battle_activation_pass(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=started.new_sequence,
                    **_pass_guards(started.state),
                )
                select_counts.append(
                    sum(
                        statement.lstrip().upper().startswith("SELECT")
                        for statement in statements
                    )
                )
                session.rollback()
    finally:
        event.remove(
            activation_world.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert select_counts == [5, 5]
    assert save_event_calls == 2
    assert save_checkpoint_calls == 2


def test_stage_action_persists_exact_first_delta_canonical_wire_and_restart_rng(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    action = DefendAction(unit_id=11)

    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        expected = commit_activation_action(
            before.state,
            caller_player=0,
            action=action,
            dice=before.dice,
            sequence=before.sequence_at + 1,
            **_action_guards(before.state),
        )
        staged = stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before.sequence_at,
            action_payload=action_to_json(action),
            **_action_guards(before.state),
        )

        assert staged.action_wire == action_to_json(action)
        assert staged.events == expected.events
        assert staged.state == expected.state
        assert staged.dice.to_checkpoint() == expected.dice.to_checkpoint()
        assert staged.previous_sequence == before.sequence_at
        assert staged.new_sequence == expected.next_sequence - 1
        assert [event.sequence for event in staged.events] == list(
            range(staged.previous_sequence + 1, staged.new_sequence + 1)
        )
        assert type(staged.events[-1]) is ActivationActionCommitted
        assert staged.state.activation is not None
        assert (
            staged.state.activation.phase
            is ActivationPhase.AWAITING_CONTINUATION
        )
        session.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.sequence_at == staged.new_sequence
        assert checkpoint.state == staged.state
        assert (
            checkpoint.dice.to_checkpoint()
            == staged.dice.to_checkpoint()
        )
        tail = tuple(
            load_events(
                restarted,
                battle_id,
                since=staged.previous_sequence,
            )
        )
        assert tail == staged.events
        assert checkpoint.state == apply_events(before.state, tail)
        assert checkpoint.dice.roll_d6(12) == expected.dice.roll_d6(12)
        assert restarted.scalar(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(
                models.BattleCheckpoint.battle_id == battle_id,
                models.BattleCheckpoint.sequence_at == staged.new_sequence,
            )
        ) == 1


def test_stage_action_accepts_reachable_second_action_without_local_limits(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    first_action = DefendAction(unit_id=11)
    with activation_world.sessions() as session:
        first_checkpoint = load_latest_checkpoint(session, battle_id)
        assert first_checkpoint is not None
        first = stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=first_checkpoint.sequence_at,
            action_payload=action_to_json(first_action),
            **_action_guards(first_checkpoint.state),
        )
        session.commit()

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        continued = continue_activation(
            checkpoint.state,
            caller_player=0,
            sequence=checkpoint.sequence_at + 1,
            **_action_guards(checkpoint.state),
        )
        first_pass = pass_interrupt_priority(
            continued.state,
            caller_player=0,
            sequence=continued.next_sequence,
            **_pass_guards(continued.state),
        )
        ready = pass_interrupt_priority(
            first_pass.state,
            caller_player=1,
            sequence=first_pass.next_sequence,
            **_pass_guards(first_pass.state),
        )
        protocol_events = (
            *continued.events,
            *first_pass.events,
            *ready.events,
        )
        save_events(
            session,
            battle_id,
            protocol_events,
            expected_latest_sequence=checkpoint.sequence_at,
        )
        save_checkpoint(
            session,
            battle_id,
            ready.next_sequence - 1,
            ready.state,
            checkpoint.dice,
            state_version=2,
        )
        session.commit()

    second_action = ManeuverAction(
        unit_id=11,
        target_position=Position(10, 0),
    )
    with activation_world.sessions() as session:
        before_second = load_latest_checkpoint(session, battle_id)
        assert before_second is not None
        expected_second = commit_activation_action(
            before_second.state,
            caller_player=0,
            action=second_action,
            dice=before_second.dice,
            sequence=before_second.sequence_at + 1,
            **_action_guards(before_second.state),
        )
        second = stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before_second.sequence_at,
            action_payload=action_to_json(second_action),
            **_action_guards(before_second.state),
        )
        session.commit()

    assert first.state.activation is not None
    assert first.state.activation.action_types == ("defend",)
    assert second.events == expected_second.events
    assert second.state == expected_second.state
    assert second.state.activation is not None
    assert second.state.activation.action_types == ("defend", "maneuver")
    assert (
        second.state.activation.phase
        is ActivationPhase.AWAITING_FINALIZATION
    )


def test_action_missing_and_foreign_battles_share_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    foreign_id = _persist_action_ready_battle(activation_world)
    payload = action_to_json(DefendAction(11))

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, foreign_id)
        assert checkpoint is not None
        for battle_id in (foreign_id, foreign_id + 100_000):
            with pytest.raises(BattleActivationActionNotFound):
                stage_battle_activation_action(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    expected_sequence=checkpoint.sequence_at,
                    action_payload=payload,
                    **_action_guards(checkpoint.state),
                )


def test_action_two_owner_and_same_owner_authorization_matrix(
    activation_world: ActivationWorld,
) -> None:
    two_owner_id = _persist_action_ready_battle(activation_world)
    two_owner_before = _stream_snapshot(activation_world, two_owner_id)
    payload = action_to_json(DefendAction(11))
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, two_owner_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationActionForbidden):
            stage_battle_activation_action(
                session,
                battle_id=two_owner_id,
                caller_user_id=activation_world.p2_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=payload,
                **_action_guards(checkpoint.state),
            )
        session.rollback()
    assert _stream_snapshot(activation_world, two_owner_id) == two_owner_before

    same_owner_state = _idle_state(active_player=1, initiative_player=0)
    same_owner_id = _persist_action_ready_battle(
        activation_world,
        state=same_owner_state,
        p1_id=activation_world.p1_id,
        p2_id=activation_world.p1_id,
    )
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, same_owner_id)
        assert checkpoint is not None
        staged = stage_battle_activation_action(
            session,
            battle_id=same_owner_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            action_payload=action_to_json(DefendAction(21)),
            **_action_guards(checkpoint.state),
        )
        session.commit()

    assert staged.state.activation is not None
    assert staged.state.activation.controlling_player == 1
    assert staged.state.activation.phase is ActivationPhase.AWAITING_CONTINUATION


@pytest.mark.parametrize(
    ("field", "value", "error_type", "reason"),
    [
        ("battle_id", True, BattleActivationActionNotFound, None),
        ("caller_user_id", False, BattleActivationActionNotFound, None),
        ("expected_sequence", True, BattleActivationActionInvalid, None),
        ("expected_sequence", -1, BattleActivationActionInvalid, None),
        (
            "activation_id",
            True,
            BattleActivationActionInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "activation_id",
            0,
            BattleActivationActionInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            False,
            BattleActivationActionInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            0,
            BattleActivationActionInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        ("action_payload", True, BattleActivationActionInvalid, None),
        (
            "action_payload",
            {
                "schema": "szop.action",
                "version": True,
                "action_type": "defend",
                "payload": {"unit_id": 11},
            },
            BattleActivationActionInvalid,
            None,
        ),
        (
            "action_payload",
            {
                "schema": "szop.action",
                "version": 1,
                "action_type": "defend",
                "payload": {"unit_id": True},
            },
            BattleActivationActionInvalid,
            None,
        ),
        (
            "action_payload",
            {
                "schema": "szop.action",
                "version": 1,
                "action_type": "defend",
                "payload": {"unit_id": 11},
                "extra": None,
            },
            BattleActivationActionInvalid,
            None,
        ),
    ],
)
def test_action_strict_inputs_reject_coercion_and_extra_fields_without_writes(
    activation_world: ActivationWorld,
    field: str,
    value: object,
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        kwargs = {
            "battle_id": battle_id,
            "caller_user_id": activation_world.p1_id,
            "expected_sequence": checkpoint.sequence_at,
            "action_payload": action_to_json(DefendAction(11)),
            **_action_guards(checkpoint.state),
        }
        kwargs[field] = value
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_action(session, **kwargs)
        if reason is not None:
            assert exc_info.value.reason is reason
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize(
    "action",
    [
        DefendAction(21),
        ManeuverAction(11, Position(100, 0)),
    ],
)
def test_action_unit_owner_and_leaf_legality_remain_in_pure_ssot(
    activation_world: ActivationWorld,
    action,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
        with pytest.raises(BattleActivationActionInvalid) as exc_info:
            stage_battle_activation_action(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=action_to_json(action),
                **_action_guards(checkpoint.state),
            )
        assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_ACTION
        assert checkpoint.dice.to_checkpoint() == rng_before
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_action_rejects_v1_inactive_stale_sequence_and_wrong_phase_atomically(
    activation_world: ActivationWorld,
) -> None:
    payload = action_to_json(DefendAction(11))

    v1_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationActionUpgradeRequired):
            stage_battle_activation_action(
                session,
                battle_id=v1_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                action_payload=payload,
            )

    inactive_id = _persist_action_ready_battle(activation_world)
    with activation_world.sessions() as session:
        battle = session.get(models.Battle, inactive_id)
        assert battle is not None
        battle.status = "finished"
        session.commit()
    inactive_before = _stream_snapshot(activation_world, inactive_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, inactive_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationActionInvalid) as exc_info:
            stage_battle_activation_action(
                session,
                battle_id=inactive_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=payload,
                **_action_guards(checkpoint.state),
            )
        assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, inactive_id) == inactive_before

    ready_id = _persist_action_ready_battle(activation_world)
    ready_before = _stream_snapshot(activation_world, ready_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, ready_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationActionSequenceConflict):
            stage_battle_activation_action(
                session,
                battle_id=ready_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at - 1,
                action_payload=payload,
                **_action_guards(checkpoint.state),
            )
        with pytest.raises(BattleActivationActionInvalid) as stale:
            stage_battle_activation_action(
                session,
                battle_id=ready_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                activation_id=checkpoint.state.activation.activation_id,
                expected_activation_version=(
                    checkpoint.state.activation.version + 1
                ),
                action_payload=payload,
            )
        assert stale.value.reason is ActivationProtocolErrorReason.STALE_ACTIVATION
        session.rollback()
    assert _stream_snapshot(activation_world, ready_id) == ready_before

    started_id, started = _persist_started_battle(activation_world)
    started_before = _stream_snapshot(activation_world, started_id)
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationActionInvalid) as wrong_phase:
            stage_battle_activation_action(
                session,
                battle_id=started_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                action_payload=payload,
                **_action_guards(started.state),
            )
        assert wrong_phase.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
        session.rollback()
    assert _stream_snapshot(activation_world, started_id) == started_before


def test_action_incoherent_or_malformed_current_checkpoint_is_unavailable(
    activation_world: ActivationWorld,
) -> None:
    payload = action_to_json(DefendAction(11))

    stale_id = _persist_action_ready_battle(activation_world)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, stale_id)
        assert checkpoint is not None
        save_events(
            session,
            stale_id,
            (
                MoveExecuted(
                    sequence=checkpoint.sequence_at + 1,
                    unit_id=11,
                    from_pos=(11.0, 0.0),
                    to_pos=(10.0, 0.0),
                ),
            ),
            expected_latest_sequence=checkpoint.sequence_at,
        )
        session.commit()
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationActionUnavailable) as stale:
            stage_battle_activation_action(
                session,
                battle_id=stale_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=payload,
                **_action_guards(checkpoint.state),
            )
        assert stale.value.actual_sequence == checkpoint.sequence_at + 1

    malformed_id = _persist_action_ready_battle(activation_world)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, malformed_id)
        assert checkpoint is not None
        row = session.scalar(
            select(models.BattleCheckpoint).where(
                models.BattleCheckpoint.battle_id == malformed_id,
                models.BattleCheckpoint.sequence_at == checkpoint.sequence_at,
            )
        )
        assert row is not None
        row.state_json = "{}"
        session.commit()
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationActionUnavailable):
            stage_battle_activation_action(
                session,
                battle_id=malformed_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=payload,
                **_action_guards(checkpoint.state),
            )

    mismatch_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=2,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationActionUnavailable):
            stage_battle_activation_action(
                session,
                battle_id=mismatch_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                action_payload=payload,
            )


@pytest.mark.parametrize("failure", ["checkpoint-conflict", "integrity-error"])
def test_action_caller_rollback_removes_the_whole_staged_write(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    real_save_checkpoint = activation_service.save_checkpoint

    def fail_after_checkpoint(*args, **kwargs):
        real_save_checkpoint(*args, **kwargs)
        if failure == "integrity-error":
            raise IntegrityError("checkpoint race", {}, Exception("unique"))
        raise BattleCheckpointSequenceConflict(
            args[1],
            sequence_at=args[2],
            latest_sequence=args[2] - 1,
        )

    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        fail_after_checkpoint,
    )
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationActionWriteConflict):
            stage_battle_activation_action(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                action_payload=action_to_json(DefendAction(11)),
                **_action_guards(checkpoint.state),
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_action_two_sessions_allow_at_most_one_winner(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    first_session = activation_world.sessions()
    second_session = activation_world.sessions()
    try:
        first_checkpoint = load_latest_checkpoint(first_session, battle_id)
        second_checkpoint = load_latest_checkpoint(second_session, battle_id)
        assert first_checkpoint is not None
        assert second_checkpoint is not None
        assert first_checkpoint.sequence_at == second_checkpoint.sequence_at
        first = stage_battle_activation_action(
            first_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=first_checkpoint.sequence_at,
            action_payload=action_to_json(DefendAction(11)),
            **_action_guards(first_checkpoint.state),
        )
        first_session.commit()

        with pytest.raises(BattleActivationActionSequenceConflict):
            stage_battle_activation_action(
                second_session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=second_checkpoint.sequence_at,
                action_payload=action_to_json(DefendAction(11)),
                **_action_guards(second_checkpoint.state),
            )
        second_session.rollback()
    finally:
        first_session.close()
        second_session.close()

    with activation_world.sessions() as session:
        assert tuple(
            load_events(
                session,
                battle_id,
                since=first.previous_sequence,
            )
        ) == first.events
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        assert checkpoint.sequence_at == first.new_sequence


def test_action_success_is_one_batch_one_checkpoint_and_five_selects(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_id = _persist_action_ready_battle(activation_world)
    large_id = _persist_action_ready_battle(
        activation_world,
        extra_units_per_player=30,
    )
    statements: list[str] = []
    save_event_calls = 0
    save_checkpoint_calls = 0
    real_save_events = activation_service.save_events
    real_save_checkpoint = activation_service.save_checkpoint

    def count_save_events(*args, **kwargs):
        nonlocal save_event_calls
        save_event_calls += 1
        return real_save_events(*args, **kwargs)

    def count_save_checkpoint(*args, **kwargs):
        nonlocal save_checkpoint_calls
        save_checkpoint_calls += 1
        return real_save_checkpoint(*args, **kwargs)

    def capture_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    monkeypatch.setattr(activation_service, "save_events", count_save_events)
    monkeypatch.setattr(
        activation_service,
        "save_checkpoint",
        count_save_checkpoint,
    )
    select_counts = []
    event.listen(
        activation_world.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        for battle_id in (small_id, large_id):
            statements.clear()
            with activation_world.sessions() as session:
                checkpoint = load_latest_checkpoint(session, battle_id)
                assert checkpoint is not None
                statements.clear()
                stage_battle_activation_action(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
                    action_payload=action_to_json(DefendAction(11)),
                    **_action_guards(checkpoint.state),
                )
                select_counts.append(
                    sum(
                        statement.lstrip().upper().startswith("SELECT")
                        for statement in statements
                    )
                )
                session.rollback()
    finally:
        event.remove(
            activation_world.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert select_counts == [5, 5]
    assert save_event_calls == 2
    assert save_checkpoint_calls == 2
