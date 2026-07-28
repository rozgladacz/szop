from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.db import Base
from app.services import battle_activations as activation_service
from app.services.battle_activations import (
    BattleActivationStartForbidden,
    BattleActivationStartInvalid,
    BattleActivationStartNotFound,
    BattleActivationStartSequenceConflict,
    BattleActivationStartUnavailable,
    BattleActivationStartUpgradeRequired,
    BattleActivationStartWriteConflict,
    stage_battle_activation_start,
)
from app.services.engine.activation_protocol import (
    ActivationProtocolErrorReason,
    start_activation,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivationStarted,
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
