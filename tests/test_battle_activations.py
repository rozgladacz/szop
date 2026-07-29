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
from app.services.engine import interrupts as interrupts_module
from app.services.battle_activations import (
    BattleActivationActionForbidden,
    BattleActivationActionInvalid,
    BattleActivationActionNotFound,
    BattleActivationActionSequenceConflict,
    BattleActivationActionUnavailable,
    BattleActivationActionUpgradeRequired,
    BattleActivationActionWriteConflict,
    BattleActivationContinueForbidden,
    BattleActivationContinueInvalid,
    BattleActivationContinueNotFound,
    BattleActivationContinueSequenceConflict,
    BattleActivationContinueUnavailable,
    BattleActivationContinueUpgradeRequired,
    BattleActivationContinueWriteConflict,
    BattleActivationFinalizeForbidden,
    BattleActivationFinalizeInvalid,
    BattleActivationFinalizeNotFound,
    BattleActivationFinalizeSequenceConflict,
    BattleActivationFinalizeUnavailable,
    BattleActivationFinalizeUpgradeRequired,
    BattleActivationFinalizeWriteConflict,
    BattleActivationInterruptForbidden,
    BattleActivationInterruptInvalid,
    BattleActivationInterruptNotFound,
    BattleActivationInterruptSequenceConflict,
    BattleActivationInterruptUnavailable,
    BattleActivationInterruptUpgradeRequired,
    BattleActivationInterruptWriteConflict,
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
    stage_battle_activation_continue,
    stage_battle_activation_finalize,
    stage_battle_activation_interrupt,
    stage_battle_activation_pass,
    stage_battle_activation_start,
)
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction, ManeuverAction
from app.services.engine.activation_protocol import (
    ActivationProtocolErrorReason,
    commit_activation_action,
    continue_activation,
    finalize_activation,
    pass_interrupt_priority,
    start_activation,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    ActivePlayerChanged,
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    InitiativeTransferred,
    InterruptTriggered,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    MeleeBalanceReset,
    MoveExecuted,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
)
from app.services.engine.interrupts import (
    execute_ready_activation_interrupt_outcomes,
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
    WeaponProfile,
    apply_events,
    effective_passives,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
    STATUS_WYCZERPANY,
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
    passives: tuple[str, ...] = (),
    position: Position | None = None,
) -> UnitBlob:
    return UnitBlob(
        id=unit_id,
        owner_player=owner_player,
        position=position or Position(float(unit_id), 0),
        radius_inches=1,
        models_alive=models_alive,
        toughness_per_model=3,
        status_flags=status_flags,
        passives=passives,
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


def _persist_awaiting_continuation_battle(
    world: ActivationWorld,
    *,
    state: BattleState | None = None,
    p1_id: int | None = None,
    p2_id: int | None = None,
    extra_units_per_player: int = 0,
) -> int:
    battle_id = _persist_action_ready_battle(
        world,
        state=state,
        p1_id=p1_id,
        p2_id=p2_id,
        extra_units_per_player=extra_units_per_player,
    )
    initial = state or _idle_state(
        extra_units_per_player=extra_units_per_player
    )
    participant_ids = (
        world.p1_id if p1_id is None else p1_id,
        world.p2_id if p2_id is None else p2_id,
    )
    selected_unit_id = 11 if initial.active_player == 0 else 21
    with world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=participant_ids[initial.active_player],
            expected_sequence=checkpoint.sequence_at,
            action_payload=action_to_json(DefendAction(selected_unit_id)),
            **_action_guards(checkpoint.state),
        )
        session.commit()
    return battle_id


def _persist_awaiting_finalization_battle(
    world: ActivationWorld,
    *,
    state: BattleState | None = None,
    p1_id: int | None = None,
    p2_id: int | None = None,
    extra_units_per_player: int = 0,
) -> int:
    battle_id = _persist_awaiting_continuation_battle(
        world,
        state=state,
        p1_id=p1_id,
        p2_id=p2_id,
        extra_units_per_player=extra_units_per_player,
    )
    initial = state or _idle_state(
        extra_units_per_player=extra_units_per_player
    )
    participant_ids = (
        world.p1_id if p1_id is None else p1_id,
        world.p2_id if p2_id is None else p2_id,
    )
    selected_unit_id = 11 if initial.active_player == 0 else 21
    caller_user_id = participant_ids[initial.active_player]

    with world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        stage_battle_activation_continue(
            session,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
            expected_sequence=checkpoint.sequence_at,
            **_action_guards(checkpoint.state),
        )
        session.commit()

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

    with world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
            expected_sequence=checkpoint.sequence_at,
            action_payload=action_to_json(
                ManeuverAction(
                    selected_unit_id,
                    Position(float(selected_unit_id - 1), 0),
                )
            ),
            **_action_guards(checkpoint.state),
        )
        session.commit()
    return battle_id


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


def test_continue_opens_durable_second_window_and_completes_second_action_chain(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_action_ready_battle(activation_world)
    first_action = DefendAction(11)
    with activation_world.sessions() as session:
        before_first = load_latest_checkpoint(session, battle_id)
        assert before_first is not None
        first = stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before_first.sequence_at,
            action_payload=action_to_json(first_action),
            **_action_guards(before_first.state),
        )
        session.commit()

    with activation_world.sessions() as restarted:
        before_continue = load_latest_checkpoint(restarted, battle_id)
        assert before_continue is not None
        assert before_continue.state == first.state
        assert before_continue.sequence_at == first.new_sequence
        rng_before_continue = before_continue.dice.to_checkpoint()
        expected_continue = continue_activation(
            before_continue.state,
            caller_player=0,
            sequence=before_continue.sequence_at + 1,
            **_action_guards(before_continue.state),
        )
        continued = stage_battle_activation_continue(
            restarted,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before_continue.sequence_at,
            **_action_guards(before_continue.state),
        )

        assert continued.events == expected_continue.events
        assert continued.state == expected_continue.state
        assert continued.previous_sequence == before_continue.sequence_at
        assert continued.new_sequence == expected_continue.next_sequence - 1
        assert [type(item) for item in continued.events] == [
            ActivationContinuationChosen,
            InterruptWindowOpened,
        ]
        choice, opened = continued.events
        assert choice.continue_activation is True
        assert opened.window_ordinal == 2
        assert opened.priority_player == 0
        assert continued.state.activation is not None
        assert continued.state.activation.phase is ActivationPhase.BEFORE_ACTION
        assert continued.state.activation.window is not None
        assert continued.state.activation.window.ordinal == 2
        assert (
            continued.dice.to_checkpoint()
            == rng_before_continue
            == before_continue.dice.to_checkpoint()
        )
        assert continued.state == apply_events(
            before_continue.state,
            continued.events,
        )
        restarted.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == continued.state
        assert checkpoint.sequence_at == continued.new_sequence
        assert checkpoint.dice.to_checkpoint() == rng_before_continue
        first_pass = stage_battle_activation_pass(
            restarted,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            **_pass_guards(checkpoint.state),
        )
        restarted.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == first_pass.state
        assert checkpoint.sequence_at == first_pass.new_sequence
        assert checkpoint.dice.to_checkpoint() == rng_before_continue
        ready = stage_battle_activation_pass(
            restarted,
            battle_id=battle_id,
            caller_user_id=activation_world.p2_id,
            expected_sequence=checkpoint.sequence_at,
            **_pass_guards(checkpoint.state),
        )
        assert ready.state.activation is not None
        assert ready.state.activation.phase is ActivationPhase.ACTION_READY
        restarted.commit()

    second_action = ManeuverAction(11, Position(10, 0))
    with activation_world.sessions() as restarted:
        before_second = load_latest_checkpoint(restarted, battle_id)
        assert before_second is not None
        assert before_second.state == ready.state
        assert before_second.sequence_at == ready.new_sequence
        assert before_second.dice.to_checkpoint() == rng_before_continue
        expected_second = commit_activation_action(
            before_second.state,
            caller_player=0,
            action=second_action,
            dice=before_second.dice,
            sequence=before_second.sequence_at + 1,
            **_action_guards(before_second.state),
        )
        second = stage_battle_activation_action(
            restarted,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before_second.sequence_at,
            action_payload=action_to_json(second_action),
            **_action_guards(before_second.state),
        )
        assert second.events == expected_second.events
        assert second.state == expected_second.state
        assert second.state.activation is not None
        assert (
            second.state.activation.phase
            is ActivationPhase.AWAITING_FINALIZATION
        )
        restarted.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        tail = tuple(
            load_events(
                restarted,
                battle_id,
                since=before_continue.sequence_at,
            )
        )
        assert checkpoint.state == second.state
        assert checkpoint.state == apply_events(before_continue.state, tail)
        assert checkpoint.sequence_at == second.new_sequence
        assert checkpoint.dice.to_checkpoint() == second.dice.to_checkpoint()
        assert checkpoint.dice.roll_d6(12) == second.dice.roll_d6(12)


def test_continue_missing_and_foreign_battles_share_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    foreign_id = _persist_awaiting_continuation_battle(activation_world)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, foreign_id)
        assert checkpoint is not None
        for battle_id in (foreign_id, foreign_id + 100_000):
            with pytest.raises(BattleActivationContinueNotFound):
                stage_battle_activation_continue(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    expected_sequence=checkpoint.sequence_at,
                    **_action_guards(checkpoint.state),
                )


def test_continue_two_owner_and_same_owner_authorization_matrix(
    activation_world: ActivationWorld,
) -> None:
    two_owner_id = _persist_awaiting_continuation_battle(activation_world)
    two_owner_before = _stream_snapshot(activation_world, two_owner_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, two_owner_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
        with pytest.raises(BattleActivationContinueForbidden):
            stage_battle_activation_continue(
                session,
                battle_id=two_owner_id,
                caller_user_id=activation_world.p2_id,
                expected_sequence=checkpoint.sequence_at,
                **_action_guards(checkpoint.state),
            )
        assert checkpoint.dice.to_checkpoint() == rng_before
        session.rollback()
    assert _stream_snapshot(activation_world, two_owner_id) == two_owner_before

    same_owner_state = _idle_state(active_player=1, initiative_player=0)
    same_owner_id = _persist_awaiting_continuation_battle(
        activation_world,
        state=same_owner_state,
        p1_id=activation_world.p1_id,
        p2_id=activation_world.p1_id,
    )
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, same_owner_id)
        assert checkpoint is not None
        staged = stage_battle_activation_continue(
            session,
            battle_id=same_owner_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            **_action_guards(checkpoint.state),
        )
        session.commit()

    assert staged.state.activation is not None
    assert staged.state.activation.controlling_player == 1
    assert staged.state.activation.window is not None
    assert staged.state.activation.window.priority_player == 0


@pytest.mark.parametrize(
    ("field", "value", "error_type", "reason"),
    [
        ("battle_id", True, BattleActivationContinueNotFound, None),
        ("caller_user_id", False, BattleActivationContinueNotFound, None),
        ("expected_sequence", True, BattleActivationContinueInvalid, None),
        ("expected_sequence", -1, BattleActivationContinueInvalid, None),
        (
            "activation_id",
            True,
            BattleActivationContinueInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "activation_id",
            0,
            BattleActivationContinueInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            False,
            BattleActivationContinueInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            0,
            BattleActivationContinueInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
    ],
)
def test_continue_strict_inputs_reject_coercion_without_writes(
    activation_world: ActivationWorld,
    field: str,
    value: object,
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        kwargs = {
            "battle_id": battle_id,
            "caller_user_id": activation_world.p1_id,
            "expected_sequence": checkpoint.sequence_at,
            **_action_guards(checkpoint.state),
        }
        kwargs[field] = value
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_continue(session, **kwargs)
        if reason is not None:
            assert exc_info.value.reason is reason
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_continue_rejects_v1_inactive_stale_guards_and_wrong_phase_atomically(
    activation_world: ActivationWorld,
) -> None:
    v1_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationContinueUpgradeRequired):
            stage_battle_activation_continue(
                session,
                battle_id=v1_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
            )

    inactive_id = _persist_awaiting_continuation_battle(activation_world)
    with activation_world.sessions() as session:
        battle = session.get(models.Battle, inactive_id)
        assert battle is not None
        battle.status = "finished"
        session.commit()
    inactive_before = _stream_snapshot(activation_world, inactive_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, inactive_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationContinueInvalid) as exc_info:
            stage_battle_activation_continue(
                session,
                battle_id=inactive_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                **_action_guards(checkpoint.state),
            )
        assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, inactive_id) == inactive_before

    continuation_id = _persist_awaiting_continuation_battle(activation_world)
    continuation_before = _stream_snapshot(activation_world, continuation_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, continuation_id)
        assert checkpoint is not None
        activation = checkpoint.state.activation
        assert activation is not None
        with pytest.raises(BattleActivationContinueSequenceConflict):
            stage_battle_activation_continue(
                session,
                battle_id=continuation_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at - 1,
                **_action_guards(checkpoint.state),
            )
        with pytest.raises(BattleActivationContinueInvalid) as wrong_id:
            stage_battle_activation_continue(
                session,
                battle_id=continuation_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                activation_id=activation.activation_id + 1,
                expected_activation_version=activation.version,
            )
        assert (
            wrong_id.value.reason
            is ActivationProtocolErrorReason.STALE_ACTIVATION
        )
        with pytest.raises(BattleActivationContinueInvalid) as wrong_version:
            stage_battle_activation_continue(
                session,
                battle_id=continuation_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                activation_id=activation.activation_id,
                expected_activation_version=activation.version + 1,
            )
        assert (
            wrong_version.value.reason
            is ActivationProtocolErrorReason.STALE_ACTIVATION
        )
        session.rollback()
    assert (
        _stream_snapshot(activation_world, continuation_id)
        == continuation_before
    )

    wrong_phase_id = _persist_action_ready_battle(activation_world)
    wrong_phase_before = _stream_snapshot(activation_world, wrong_phase_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, wrong_phase_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationContinueInvalid) as wrong_phase:
            stage_battle_activation_continue(
                session,
                battle_id=wrong_phase_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                **_action_guards(checkpoint.state),
            )
        assert (
            wrong_phase.value.reason
            is ActivationProtocolErrorReason.ILLEGAL_CONTINUE
        )
        session.rollback()
    assert _stream_snapshot(activation_world, wrong_phase_id) == wrong_phase_before


def test_continue_incoherent_or_malformed_current_checkpoint_is_unavailable(
    activation_world: ActivationWorld,
) -> None:
    stale_id = _persist_awaiting_continuation_battle(activation_world)
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
        with pytest.raises(BattleActivationContinueUnavailable) as stale:
            stage_battle_activation_continue(
                session,
                battle_id=stale_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                **_action_guards(checkpoint.state),
            )
        assert stale.value.actual_sequence == checkpoint.sequence_at + 1

    for malformed_state in ("{}", "unreachable-action-count"):
        malformed_id = _persist_awaiting_continuation_battle(activation_world)
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
            if malformed_state == "{}":
                row.state_json = "{}"
            else:
                changed = row.state_json.replace(
                    '"action_count":1',
                    '"action_count":0',
                ).replace(
                    '"action_types":["defend"]',
                    '"action_types":[]',
                )
                assert changed != row.state_json
                row.state_json = changed
            session.commit()
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationContinueUnavailable):
                stage_battle_activation_continue(
                    session,
                    battle_id=malformed_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
                    **_action_guards(checkpoint.state),
                )

    mismatch_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=2,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationContinueUnavailable):
            stage_battle_activation_continue(
                session,
                battle_id=mismatch_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
            )


@pytest.mark.parametrize("failure", ["checkpoint-conflict", "integrity-error"])
def test_continue_caller_rollback_removes_the_whole_staged_write(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
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
        with pytest.raises(BattleActivationContinueWriteConflict):
            stage_battle_activation_continue(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                **_action_guards(checkpoint.state),
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_continue_success_remains_staged_until_caller_commits(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        stage_battle_activation_continue(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            **_action_guards(checkpoint.state),
        )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_continue_two_sessions_allow_at_most_one_winner(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    first_session = activation_world.sessions()
    second_session = activation_world.sessions()
    try:
        first_checkpoint = load_latest_checkpoint(first_session, battle_id)
        second_checkpoint = load_latest_checkpoint(second_session, battle_id)
        assert first_checkpoint is not None
        assert second_checkpoint is not None
        assert first_checkpoint.sequence_at == second_checkpoint.sequence_at
        first = stage_battle_activation_continue(
            first_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=first_checkpoint.sequence_at,
            **_action_guards(first_checkpoint.state),
        )
        first_session.commit()

        with pytest.raises(BattleActivationContinueSequenceConflict):
            stage_battle_activation_continue(
                second_session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=second_checkpoint.sequence_at,
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


def test_continue_success_is_one_batch_one_checkpoint_and_five_selects(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_id = _persist_awaiting_continuation_battle(activation_world)
    large_id = _persist_awaiting_continuation_battle(
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
                stage_battle_activation_continue(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
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


def test_finalize_after_one_action_persists_exact_terminal_delta_and_allows_next_start(
    activation_world: ActivationWorld,
) -> None:
    initial = _idle_state()
    actor, target = initial.blobs
    terminal_state = replace(
        initial,
        blobs=(
            replace(
                actor,
                damage_balance=2,
                ability_overrides=(("ordered", True),),
            ),
            replace(target, ability_overrides=(("cursed", True),)),
        ),
    )
    battle_id = _persist_awaiting_continuation_battle(
        activation_world,
        state=terminal_state,
    )
    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        rng_before = before.dice.to_checkpoint()
        expected = finalize_activation(
            before.state,
            caller_player=0,
            recovery_uses=(),
            sequence=before.sequence_at + 1,
            **_action_guards(before.state),
        )

        staged = stage_battle_activation_finalize(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before.sequence_at,
            recovery_uses=(),
            **_action_guards(before.state),
        )

        assert staged.previous_sequence == before.sequence_at
        assert staged.new_sequence == expected.next_sequence - 1
        assert staged.events == expected.events
        assert staged.state == expected.state
        assert staged.state == apply_events(before.state, staged.events)
        assert isinstance(staged.events[0], ActivationContinuationChosen)
        assert staged.events[0].continue_activation is False
        assert [type(item) for item in staged.events[1:-3]] == [
            StatusAdded,
            MeleeBalanceReset,
            AbilityOverridesCleared,
            AbilityOverridesCleared,
        ]
        assert [type(item) for item in staged.events[-3:]] == [
            ActivationFinalized,
            InitiativeTransferred,
            ActivePlayerChanged,
        ]
        assert staged.state.activation is None
        finalized_actor = next(
            blob for blob in staged.state.blobs if blob.id == 11
        )
        assert STATUS_AKTYWOWANY in finalized_actor.status_flags
        assert finalized_actor.damage_balance == 0
        assert all(not blob.ability_overrides for blob in staged.state.blobs)
        assert staged.state.initiative_player == 1
        assert staged.state.active_player == 1
        assert staged.dice.to_checkpoint() == rng_before
        session.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.sequence_at == staged.new_sequence
        assert checkpoint.state == staged.state
        assert checkpoint.dice.to_checkpoint() == rng_before
        assert tuple(
            load_events(
                restarted,
                battle_id,
                since=staged.previous_sequence,
            )
        ) == staged.events
        assert checkpoint.state == apply_events(before.state, staged.events)
        future_live = DeterministicDice.from_checkpoint(
            staged.dice.to_checkpoint()
        ).roll_d6(12)
        future_restarted = DeterministicDice.from_checkpoint(
            checkpoint.dice.to_checkpoint()
        ).roll_d6(12)
        assert future_restarted == future_live

        next_activation = stage_battle_activation_start(
            restarted,
            battle_id=battle_id,
            caller_user_id=activation_world.p2_id,
            selected_unit_id=21,
            expected_sequence=checkpoint.sequence_at,
        )
        assert next_activation.state.activation is not None
        assert next_activation.state.activation.selected_unit_id == 21
        restarted.rollback()


def test_finalize_after_two_actions_omits_continue_choice_and_survives_restart(
    activation_world: ActivationWorld,
) -> None:
    initial = _idle_state()
    actor, target = initial.blobs
    terminal_state = replace(
        initial,
        blobs=(
            replace(actor, ability_overrides=(("ordered", True),)),
            replace(target, ability_overrides=(("cursed", True),)),
        ),
    )
    battle_id = _persist_awaiting_finalization_battle(
        activation_world,
        state=terminal_state,
    )
    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        assert before.state.activation is not None
        assert (
            before.state.activation.phase
            is ActivationPhase.AWAITING_FINALIZATION
        )
        rng_before = before.dice.to_checkpoint()
        expected = finalize_activation(
            before.state,
            caller_player=0,
            recovery_uses=(),
            sequence=before.sequence_at + 1,
            **_action_guards(before.state),
        )

        staged = stage_battle_activation_finalize(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=before.sequence_at,
            recovery_uses=(),
            **_action_guards(before.state),
        )

        assert staged.events == expected.events
        assert staged.state == expected.state
        assert not any(
            isinstance(item, ActivationContinuationChosen)
            for item in staged.events
        )
        assert [type(item) for item in staged.events[-3:]] == [
            ActivationFinalized,
            InitiativeTransferred,
            ActivePlayerChanged,
        ]
        assert staged.state.activation is None
        finalized_actor = next(
            blob for blob in staged.state.blobs if blob.id == 11
        )
        assert STATUS_AKTYWOWANY in finalized_actor.status_flags
        assert all(not blob.ability_overrides for blob in staged.state.blobs)
        assert staged.dice.to_checkpoint() == rng_before
        session.commit()

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        tail = tuple(
            load_events(
                restarted,
                battle_id,
                since=staged.previous_sequence,
            )
        )
        assert tail == staged.events
        assert checkpoint.state == staged.state
        assert checkpoint.state == apply_events(before.state, tail)
        assert checkpoint.dice.to_checkpoint() == rng_before
        future_live = DeterministicDice.from_checkpoint(
            staged.dice.to_checkpoint()
        ).roll_d6(12)
        future_restarted = DeterministicDice.from_checkpoint(
            checkpoint.dice.to_checkpoint()
        ).roll_d6(12)
        assert future_restarted == future_live


def test_finalize_missing_and_foreign_battles_share_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    foreign_id = _persist_awaiting_continuation_battle(activation_world)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, foreign_id)
        assert checkpoint is not None
        for battle_id in (foreign_id, foreign_id + 100_000):
            with pytest.raises(BattleActivationFinalizeNotFound):
                stage_battle_activation_finalize(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    expected_sequence=checkpoint.sequence_at,
                    recovery_uses=(),
                    **_action_guards(checkpoint.state),
                )


def test_finalize_two_owner_and_same_owner_authorization_matrix(
    activation_world: ActivationWorld,
) -> None:
    two_owner_id = _persist_awaiting_continuation_battle(activation_world)
    before = _stream_snapshot(activation_world, two_owner_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, two_owner_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
        with pytest.raises(BattleActivationFinalizeForbidden):
            stage_battle_activation_finalize(
                session,
                battle_id=two_owner_id,
                caller_user_id=activation_world.p2_id,
                expected_sequence=checkpoint.sequence_at,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        assert checkpoint.dice.to_checkpoint() == rng_before
        session.rollback()
    assert _stream_snapshot(activation_world, two_owner_id) == before

    same_owner_state = _idle_state(active_player=1, initiative_player=0)
    same_owner_id = _persist_awaiting_continuation_battle(
        activation_world,
        state=same_owner_state,
        p1_id=activation_world.p1_id,
        p2_id=activation_world.p1_id,
    )
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, same_owner_id)
        assert checkpoint is not None
        staged = stage_battle_activation_finalize(
            session,
            battle_id=same_owner_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            recovery_uses=(),
            **_action_guards(checkpoint.state),
        )
        session.commit()

    assert staged.state.activation is None
    assert staged.state.active_player == 0
    assert staged.state.initiative_player == 1
    finalized_actor = next(blob for blob in staged.state.blobs if blob.id == 21)
    assert STATUS_AKTYWOWANY in finalized_actor.status_flags


@pytest.mark.parametrize(
    ("field", "value", "error_type", "reason"),
    [
        ("battle_id", True, BattleActivationFinalizeNotFound, None),
        ("caller_user_id", False, BattleActivationFinalizeNotFound, None),
        ("expected_sequence", True, BattleActivationFinalizeInvalid, None),
        ("expected_sequence", -1, BattleActivationFinalizeInvalid, None),
        (
            "activation_id",
            True,
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "activation_id",
            0,
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            False,
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            0,
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "recovery_uses",
            [],
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        ),
        (
            "recovery_uses",
            (object(),),
            BattleActivationFinalizeInvalid,
            ActivationProtocolErrorReason.ILLEGAL_RECOVERY,
        ),
    ],
)
def test_finalize_strict_inputs_reject_without_writes_or_rng_change(
    activation_world: ActivationWorld,
    field: str,
    value: object,
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
        kwargs = {
            "battle_id": battle_id,
            "caller_user_id": activation_world.p1_id,
            "expected_sequence": checkpoint.sequence_at,
            "recovery_uses": (),
            **_action_guards(checkpoint.state),
        }
        kwargs[field] = value
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_finalize(session, **kwargs)
        if reason is not None:
            assert exc_info.value.reason is reason
        assert checkpoint.dice.to_checkpoint() == rng_before
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_finalize_rejects_v1_inactive_stale_guards_and_wrong_phase_atomically(
    activation_world: ActivationWorld,
) -> None:
    v1_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationFinalizeUpgradeRequired):
            stage_battle_activation_finalize(
                session,
                battle_id=v1_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                recovery_uses=(),
            )

    inactive_id = _persist_awaiting_continuation_battle(activation_world)
    with activation_world.sessions() as session:
        battle = session.get(models.Battle, inactive_id)
        assert battle is not None
        battle.status = "finished"
        session.commit()
    inactive_before = _stream_snapshot(activation_world, inactive_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, inactive_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationFinalizeInvalid) as exc_info:
            stage_battle_activation_finalize(
                session,
                battle_id=inactive_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        assert exc_info.value.reason is ActivationProtocolErrorReason.INVALID_PHASE
    assert _stream_snapshot(activation_world, inactive_id) == inactive_before

    finalize_id = _persist_awaiting_continuation_battle(activation_world)
    finalize_before = _stream_snapshot(activation_world, finalize_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, finalize_id)
        assert checkpoint is not None
        activation = checkpoint.state.activation
        assert activation is not None
        with pytest.raises(BattleActivationFinalizeSequenceConflict):
            stage_battle_activation_finalize(
                session,
                battle_id=finalize_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at - 1,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        for activation_id, activation_version in (
            (activation.activation_id + 1, activation.version),
            (activation.activation_id, activation.version + 1),
        ):
            with pytest.raises(BattleActivationFinalizeInvalid) as stale:
                stage_battle_activation_finalize(
                    session,
                    battle_id=finalize_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
                    activation_id=activation_id,
                    expected_activation_version=activation_version,
                    recovery_uses=(),
                )
            assert (
                stale.value.reason
                is ActivationProtocolErrorReason.STALE_ACTIVATION
            )
        session.rollback()
    assert _stream_snapshot(activation_world, finalize_id) == finalize_before

    wrong_phase_id = _persist_action_ready_battle(activation_world)
    wrong_phase_before = _stream_snapshot(activation_world, wrong_phase_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, wrong_phase_id)
        assert checkpoint is not None
        with pytest.raises(BattleActivationFinalizeInvalid) as wrong_phase:
            stage_battle_activation_finalize(
                session,
                battle_id=wrong_phase_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        assert (
            wrong_phase.value.reason
            is ActivationProtocolErrorReason.INVALID_PHASE
        )
        session.rollback()
    assert _stream_snapshot(activation_world, wrong_phase_id) == wrong_phase_before


def test_finalize_incoherent_or_malformed_current_checkpoint_is_unavailable(
    activation_world: ActivationWorld,
) -> None:
    stale_id = _persist_awaiting_continuation_battle(activation_world)
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
        with pytest.raises(BattleActivationFinalizeUnavailable) as stale:
            stage_battle_activation_finalize(
                session,
                battle_id=stale_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        assert stale.value.actual_sequence == checkpoint.sequence_at + 1

    for malformed_state in ("{}", "unreachable-action-count"):
        malformed_id = _persist_awaiting_continuation_battle(activation_world)
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
            if malformed_state == "{}":
                row.state_json = "{}"
            else:
                changed = row.state_json.replace(
                    '"action_count":1',
                    '"action_count":2',
                )
                assert changed != row.state_json
                row.state_json = changed
            session.commit()
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationFinalizeUnavailable):
                stage_battle_activation_finalize(
                    session,
                    battle_id=malformed_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
                    recovery_uses=(),
                    **_action_guards(checkpoint.state),
                )

    mismatch_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=2,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationFinalizeUnavailable):
            stage_battle_activation_finalize(
                session,
                battle_id=mismatch_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                recovery_uses=(),
            )


@pytest.mark.parametrize("failure", ["checkpoint-conflict", "integrity-error"])
def test_finalize_caller_rollback_removes_the_whole_staged_write(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
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
        with pytest.raises(BattleActivationFinalizeWriteConflict):
            stage_battle_activation_finalize(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=checkpoint.sequence_at,
                recovery_uses=(),
                **_action_guards(checkpoint.state),
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before


def test_finalize_success_remains_staged_until_caller_commits(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        stage_battle_activation_finalize(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            recovery_uses=(),
            **_action_guards(checkpoint.state),
        )
        session.rollback()
    assert _stream_snapshot(activation_world, battle_id) == before


def test_finalize_two_sessions_allow_at_most_one_winner(
    activation_world: ActivationWorld,
) -> None:
    battle_id = _persist_awaiting_continuation_battle(activation_world)
    first_session = activation_world.sessions()
    second_session = activation_world.sessions()
    try:
        first_checkpoint = load_latest_checkpoint(first_session, battle_id)
        second_checkpoint = load_latest_checkpoint(second_session, battle_id)
        assert first_checkpoint is not None
        assert second_checkpoint is not None
        first = stage_battle_activation_finalize(
            first_session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=first_checkpoint.sequence_at,
            recovery_uses=(),
            **_action_guards(first_checkpoint.state),
        )
        first_session.commit()

        with pytest.raises(BattleActivationFinalizeSequenceConflict):
            stage_battle_activation_finalize(
                second_session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=second_checkpoint.sequence_at,
                recovery_uses=(),
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


def test_finalize_success_is_one_batch_one_checkpoint_and_five_selects(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_id = _persist_awaiting_continuation_battle(activation_world)
    large_id = _persist_awaiting_continuation_battle(
        activation_world,
        extra_units_per_player=30,
    )
    statements: list[str] = []
    save_event_calls = 0
    save_checkpoint_calls = 0
    guarded_heads: list[int | None] = []
    real_save_events = activation_service.save_events
    real_save_checkpoint = activation_service.save_checkpoint

    def count_save_events(*args, **kwargs):
        nonlocal save_event_calls
        save_event_calls += 1
        guarded_heads.append(kwargs.get("expected_latest_sequence"))
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
                stage_battle_activation_finalize(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=checkpoint.sequence_at,
                    recovery_uses=(),
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
    assert all(type(sequence) is int for sequence in guarded_heads)


def _rozkaz_window_state(
    *,
    priority_player: int = 0,
    source_id: int | None = None,
    source_owner: int | None = None,
    source_models_alive: int = 1,
    source_location: Lokalizacja = Lokalizacja.FRONT,
    source_passives: tuple[str, ...] = ("rozkaz",),
    target_id: int | None = None,
    target_owner: int | None = None,
    target_models_alive: int = 1,
    target_location: Lokalizacja = Lokalizacja.FRONT,
    target_passives: tuple[str, ...] = (),
    target_position: Position = Position(5.0, 0.0),
    extra_units_per_player: int = 0,
) -> tuple[BattleState, int, int]:
    actual_source_id = source_id or (12 if priority_player == 0 else 22)
    actual_target_id = target_id or (11 if priority_player == 0 else 21)
    actual_source_owner = (
        priority_player if source_owner is None else source_owner
    )
    actual_target_owner = (
        priority_player if target_owner is None else target_owner
    )
    state = _idle_state(
        initiative_player=priority_player,
        extra_units_per_player=extra_units_per_player,
    )
    units = {blob.id: blob for blob in state.blobs}
    units[actual_source_id] = _unit(
        actual_source_id,
        actual_source_owner,
        models_alive=source_models_alive,
        location=source_location,
        passives=source_passives,
        position=Position(0.0, 0.0),
    )
    units[actual_target_id] = _unit(
        actual_target_id,
        actual_target_owner,
        models_alive=target_models_alive,
        location=target_location,
        passives=target_passives,
        position=target_position,
    )
    return (
        replace(state, blobs=tuple(units.values())),
        actual_source_id,
        actual_target_id,
    )


def _interrupt_guards(state: BattleState) -> dict[str, int]:
    activation = state.activation
    assert activation is not None
    assert activation.window is not None
    return {
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
        "expected_window_version": activation.window.version,
    }


def _rozkaz_payload(
    target_id: int,
    *,
    ability: str = "niewrazliwy",
    granted: bool = True,
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "ability": ability,
        "granted": granted,
    }


_STRAZNIK_RIFLE = WeaponProfile(
    slug="guardian_rifle",
    name="Guardian rifle",
    range_inches=24,
    attacks=3,
    ap=2,
    weapon_abilities=("niezawodny", "brutalny"),
)
_STRAZNIK_CANNON = WeaponProfile(
    slug="guardian_cannon",
    name="Guardian cannon",
    range_inches=30,
    attacks=2,
    ap=3,
    weapon_abilities=("precyzyjny",),
)


def _straznik_window_state(
    *,
    extra_units_per_player: int = 0,
) -> tuple[BattleState, int, tuple[int, int]]:
    source = replace(
        _unit(
            12,
            0,
            models_alive=2,
            passives=("straznik",),
            position=Position(0.0, 0.0),
        ),
        quality=4,
        ranged_weapons=(_STRAZNIK_RIFLE, _STRAZNIK_CANNON),
    )
    active = replace(
        _unit(21, 1, models_alive=6, position=Position(10.0, 0.0)),
        toughness_per_model=10,
        defense=9,
    )
    secondary = replace(
        _unit(22, 1, models_alive=6, position=Position(16.0, 0.0)),
        toughness_per_model=10,
        defense=9,
    )
    extras = tuple(
        _unit(100 + offset, 0, position=Position(30.0 + offset, 10.0))
        for offset in range(extra_units_per_player)
    ) + tuple(
        _unit(200 + offset, 1, position=Position(30.0 + offset, -10.0))
        for offset in range(extra_units_per_player)
    )
    return (
        BattleState(
            round=1,
            active_player=1,
            activations_remaining=(1 + extra_units_per_player,) * 2,
            blobs=(source, active, secondary, *extras),
            terrain=(),
            initiative_player=0,
        ),
        source.id,
        (active.id, secondary.id),
    )


def _straznik_payload(target_ids: tuple[int, int]) -> dict[str, object]:
    return {
        "assignments": [
            {
                "weapon_slug": _STRAZNIK_RIFLE.slug,
                "target_id": target_ids[0],
            },
            {
                "weapon_slug": _STRAZNIK_CANNON.slug,
                "target_id": target_ids[1],
            },
        ]
    }


def _rng_consuming_ready_interrupt_executor(
    *,
    state,
    source,
    ability_slug,
    payload,
    dice,
    sequence,
):
    dice.roll_d6(5)
    return execute_ready_activation_interrupt_outcomes(
        state=state,
        source=source,
        ability_slug=ability_slug,
        payload=payload,
        dice=dice,
        sequence=sequence,
    )


@pytest.mark.parametrize(
    ("priority_player", "same_owner"),
    [(0, False), (1, False), (1, True)],
    ids=["p1-priority", "p2-priority", "same-owner-p2-priority"],
)
def test_interrupt_success_uses_durable_priority_for_both_owners_and_same_owner(
    activation_world: ActivationWorld,
    priority_player: int,
    same_owner: bool,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        priority_player=priority_player
    )
    p2_id = activation_world.p1_id if same_owner else activation_world.p2_id
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
        p2_id=p2_id,
    )
    caller_user_id = (
        activation_world.p1_id
        if same_owner or priority_player == 0
        else activation_world.p2_id
    )

    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        before_rng = before.dice.to_checkpoint()
        staged = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=caller_user_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="rozkaz",
            payload=_rozkaz_payload(target_id),
            **_interrupt_guards(started.state),
        )
        session.commit()

    activation = staged.state.activation
    assert activation is not None
    assert activation.window is not None
    assert activation.version == 2
    assert activation.window.version == 2
    assert activation.window.priority_player == priority_player
    assert activation.window.passed_players == ()
    assert activation.window.interrupt_count == 1
    assert staged.dice.to_checkpoint() == before_rng
    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == staged.state
        assert checkpoint.dice.to_checkpoint() == before_rng
        assert tuple(
            load_events(restarted, battle_id, since=started.new_sequence)
        ) == staged.events


@pytest.mark.parametrize("same_owner", [False, True], ids=["two-owner", "same-owner"])
def test_straznik_service_persists_full_multi_target_delta_and_advanced_rng(
    activation_world: ActivationWorld,
    same_owner: bool,
) -> None:
    initial, source_id, target_ids = _straznik_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
        p2_id=activation_world.p1_id if same_owner else activation_world.p2_id,
    )
    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        input_rng = before.dice.to_checkpoint()
        staged = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="straznik",
            payload=_straznik_payload(target_ids),
            **_interrupt_guards(started.state),
        )
        session.commit()

    assert staged.dice.to_checkpoint() != input_rng
    assert staged.state == apply_events(started.state, staged.events)
    assert [event.sequence for event in staged.events] == list(
        range(started.new_sequence + 1, staged.new_sequence + 1)
    )
    assert type(staged.events[0]) is ActivationInterruptTriggered
    assert sum(type(event) is InterruptTriggered for event in staged.events) == 1
    marker = next(event for event in staged.events if type(event) is InterruptTriggered)
    assert marker.slug == "straznik"
    assert marker.payload == _straznik_payload(target_ids)
    shots = [event for event in staged.events if type(event) is ShotResolved]
    assert [shot.weapon_slug for shot in shots] == [
        _STRAZNIK_RIFLE.slug,
        _STRAZNIK_CANNON.slug,
    ]
    assert all(shot.wounds_dealt + shot.wounds_precise > 0 for shot in shots)
    assert type(staged.events[-1]) is StatusAdded
    assert staged.events[-1].target_id == source_id
    assert staged.events[-1].status == STATUS_WYCZERPANY

    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == staged.state
        assert checkpoint.dice.to_checkpoint() == staged.dice.to_checkpoint()
        assert tuple(
            load_events(restarted, battle_id, since=started.new_sequence)
        ) == staged.events


def test_interrupt_rng_consuming_executor_persists_atomic_advanced_checkpoint(
    activation_world: ActivationWorld,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        input_rng = before.dice.to_checkpoint()
        expected_dice = DeterministicDice.from_checkpoint(input_rng)
        expected_dice.roll_d6(5)
        staged = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="rozkaz",
            payload=_rozkaz_payload(target_id),
            outcome_executor=_rng_consuming_ready_interrupt_executor,
            **_interrupt_guards(started.state),
        )
        assert before.dice.to_checkpoint() == input_rng
        session.commit()

    assert staged.dice.to_checkpoint() == expected_dice.to_checkpoint()
    assert staged.state == apply_events(started.state, staged.events)
    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == staged.state
        assert checkpoint.dice.to_checkpoint() == expected_dice.to_checkpoint()
        future_persisted = DeterministicDice.from_checkpoint(
            checkpoint.dice.to_checkpoint()
        )
    future_expected = DeterministicDice.from_checkpoint(
        expected_dice.to_checkpoint()
    )
    assert future_persisted.roll_d6(8) == future_expected.roll_d6(8)


@pytest.mark.parametrize(
    ("ability", "granted", "target_passives"),
    [
        ("niewrazliwy", True, ()),
        ("nieustraszony", False, ("nieustraszony",)),
    ],
    ids=["grant-canonical-plus", "remove-canonical-minus"],
)
def test_interrupt_persists_exact_protocol_marker_canonical_marker_and_outcome(
    activation_world: ActivationWorld,
    ability: str,
    granted: bool,
    target_passives: tuple[str, ...],
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        target_passives=target_passives
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    with activation_world.sessions() as session:
        staged = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="rozkaz",
            payload=_rozkaz_payload(
                target_id,
                ability=ability,
                granted=granted,
            ),
            **_interrupt_guards(started.state),
        )
        session.commit()

    assert [type(item) for item in staged.events] == [
        ActivationInterruptTriggered,
        InterruptTriggered,
        AbilityOverrideApplied,
    ]
    assert [item.sequence for item in staged.events] == list(
        range(started.new_sequence + 1, staged.new_sequence + 1)
    )
    marker = staged.events[1]
    outcome = staged.events[2]
    assert marker.interrupt_point == "before_action"
    assert marker.slug == "rozkaz"
    assert marker.source_unit_id == source_id
    assert marker.target_unit_id == target_id
    assert marker.payload == {"ability": ability, "granted": granted}
    assert marker.consumes_round_limit is True
    assert outcome.target_id == target_id
    assert outcome.ability == ability
    assert outcome.granted is granted
    assert outcome.source_id == source_id
    assert staged.state == apply_events(started.state, staged.events)
    target = next(blob for blob in staged.state.blobs if blob.id == target_id)
    assert (ability in effective_passives(target)) is granted
    assert staged.state.used_interrupts_this_round == ((source_id, "rozkaz"),)


def test_interrupt_missing_and_foreign_battles_share_no_oracle_error(
    activation_world: ActivationWorld,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    foreign_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, foreign_id)
    failures = []

    for battle_id in (foreign_id, foreign_id + 999):
        with activation_world.sessions() as session:
            with pytest.raises(BattleActivationInterruptNotFound) as exc_info:
                stage_battle_activation_interrupt(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.outsider_id,
                    expected_sequence=started.new_sequence,
                    source_unit_id=source_id,
                    ability_slug="rozkaz",
                    payload=_rozkaz_payload(target_id),
                    **_interrupt_guards(started.state),
                )
            failures.append((type(exc_info.value), str(exc_info.value)))

    assert failures[0] == failures[1]
    assert _stream_snapshot(activation_world, foreign_id) == before


@pytest.mark.parametrize(
    (
        "caller_side",
        "source_owner",
        "source_models_alive",
        "source_location",
        "source_passives",
        "error_type",
        "reason",
    ),
    [
        (
            1,
            1,
            1,
            Lokalizacja.FRONT,
            ("rozkaz",),
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.INVALID_CALLER,
        ),
        (
            0,
            1,
            1,
            Lokalizacja.FRONT,
            ("rozkaz",),
            BattleActivationInterruptForbidden,
            None,
        ),
        (
            0,
            0,
            0,
            Lokalizacja.FRONT,
            ("rozkaz",),
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
        (
            0,
            0,
            1,
            Lokalizacja.ZAPLECZE,
            ("rozkaz",),
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
        (
            0,
            0,
            1,
            Lokalizacja.FRONT,
            (),
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
    ],
    ids=[
        "wrong-priority",
        "wrong-source-owner",
        "dead-source",
        "off-field-source",
        "source-without-ability",
    ],
)
def test_interrupt_rejects_wrong_priority_or_illegal_source_atomically(
    activation_world: ActivationWorld,
    caller_side: int,
    source_owner: int,
    source_models_alive: int,
    source_location: Lokalizacja,
    source_passives: tuple[str, ...],
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        source_owner=source_owner,
        source_models_alive=source_models_alive,
        source_location=source_location,
        source_passives=source_passives,
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=(
                    activation_world.p1_id
                    if caller_side == 0
                    else activation_world.p2_id
                ),
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(target_id),
                **_interrupt_guards(started.state),
            )

    if reason is not None:
        assert exc_info.value.reason is reason
    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize(
    (
        "target_owner",
        "target_models_alive",
        "target_location",
        "target_position",
    ),
    [
        (1, 1, Lokalizacja.FRONT, Position(5.0, 0.0)),
        (0, 0, Lokalizacja.FRONT, Position(5.0, 0.0)),
        (0, 1, Lokalizacja.ZAPLECZE, Position(5.0, 0.0)),
        (0, 1, Lokalizacja.FRONT, Position(20.0, 0.0)),
    ],
    ids=["enemy", "dead", "off-field", "out-of-range"],
)
def test_interrupt_rejects_illegal_target_atomically(
    activation_world: ActivationWorld,
    target_owner: int,
    target_models_alive: int,
    target_location: Lokalizacja,
    target_position: Position,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        target_id=13,
        target_owner=target_owner,
        target_models_alive=target_models_alive,
        target_location=target_location,
        target_position=target_position,
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(target_id),
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"target_id": True, "ability": "niewrazliwy", "granted": True},
        {"target_id": "11", "ability": "niewrazliwy", "granted": True},
        {"target_id": 11, "ability": 1, "granted": True},
        {"target_id": 11, "ability": "", "granted": True},
        {"target_id": 11, "ability": "niewrazliwy", "granted": 1},
        {"target_id": 11, "ability": "niewrazliwy", "granted": "true"},
        {
            "target_id": 11,
            "ability": "niewrazliwy",
            "granted": True,
            "extra": "transport",
        },
        {
            "target_id": 11,
            "ability": "niewrazliwy",
            "granted": True,
            "sequence": 999,
        },
        {"target_id": 11, "ability": "niewrazliwy", "granted": False},
        {"target_id": 11, "ability": "nieustraszony", "granted": True},
        {"target_id": 11, "ability": "wolny", "granted": False},
        {"target_id": 999, "ability": "niewrazliwy", "granted": True},
    ],
)
def test_interrupt_rejects_malformed_coercive_extra_and_direction_payloads(
    activation_world: ActivationWorld,
    payload: object,
) -> None:
    initial, source_id, _ = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=payload,
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"target_id": True, "ability": "niewrazliwy", "granted": True},
        {
            "target_id": 11,
            "ability": "niewrazliwy",
            "granted": True,
            "extra": "transport",
        },
        {
            "target_id": 11,
            "ability": "niewrazliwy",
            "granted": True,
            "sequence": 999,
        },
        {"target_id": 11, "ability": "niewrazliwy", "granted": False},
        {"target_id": 11, "ability": "wolny", "granted": False},
    ],
)
def test_interrupt_payload_shape_and_direction_fail_before_database_io(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    initial, source_id, _ = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("invalid payload reached persistence")

    monkeypatch.setattr(
        activation_service,
        "_get_participant_battle",
        forbidden_lookup,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=payload,
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT


@pytest.mark.parametrize(
    "payload",
    [
        {"target_id": True, "ability": "delikatny", "granted": True},
        {"target_id": 13, "ability": "delikatny", "granted": 1},
        {
            "target_id": 13,
            "ability": "delikatny",
            "granted": True,
            "extra": "transport",
        },
        {"target_id": 13, "ability": "niewrazliwy", "granted": True},
    ],
)
def test_klatwa_payload_fails_closed_before_database_io(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    initial, source_id, _ = _rozkaz_window_state(
        source_passives=("klatwa",),
        target_id=13,
        target_owner=1,
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("invalid Klątwa payload reached persistence")

    monkeypatch.setattr(
        activation_service,
        "_get_participant_battle",
        forbidden_lookup,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="klatwa",
                payload=payload,
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"assignments": []},
        {"assignments": ()},
        {
            "assignments": [
                {"weapon_slug": _STRAZNIK_RIFLE.slug, "target_id": True}
            ]
        },
        {
            "assignments": [
                {"weapon_slug": "", "target_id": 21},
            ]
        },
        {
            "assignments": [
                {
                    "weapon_slug": _STRAZNIK_RIFLE.slug,
                    "target_id": 21,
                    "attacks": 999,
                }
            ]
        },
        {
            "assignments": [
                {"weapon_slug": _STRAZNIK_RIFLE.slug, "target_id": 21},
                {"weapon_slug": _STRAZNIK_RIFLE.slug, "target_id": 22},
            ]
        },
        {
            "assignments": [
                {"weapon_slug": "a", "target_id": 21},
                {"weapon_slug": "b", "target_id": 22},
                {"weapon_slug": "c", "target_id": 23},
            ]
        },
    ],
)
def test_straznik_payload_fails_closed_before_database_io(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    initial, source_id, _target_ids = _straznik_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )

    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("invalid Strażnik payload reached persistence")

    monkeypatch.setattr(
        activation_service,
        "_get_participant_battle",
        forbidden_lookup,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="straznik",
                payload=payload,
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("expected_sequence", True, None),
        (
            "activation_id",
            True,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_activation_version",
            False,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            "expected_window_version",
            True,
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
        (
            "source_unit_id",
            False,
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
        (
            "ability_slug",
            50,
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
        (
            "payload",
            [],
            ActivationProtocolErrorReason.ILLEGAL_INTERRUPT,
        ),
    ],
)
def test_interrupt_strict_top_level_guards_reject_bool_and_coercion_before_io(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    reason: ActivationProtocolErrorReason | None,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    kwargs = {
        "battle_id": battle_id,
        "caller_user_id": activation_world.p1_id,
        "expected_sequence": started.new_sequence,
        "source_unit_id": source_id,
        "ability_slug": "rozkaz",
        "payload": _rozkaz_payload(target_id),
        **_interrupt_guards(started.state),
    }
    kwargs[field] = value

    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("invalid top-level input reached persistence")

    monkeypatch.setattr(
        activation_service,
        "_get_participant_battle",
        forbidden_lookup,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(session, **kwargs)

    assert exc_info.value.reason is reason


@pytest.mark.parametrize("slug", ["oznaczenie", "registry-only"])
def test_interrupt_rejects_registered_but_not_ready_slugs_without_writes(
    activation_world: ActivationWorld,
    slug: str,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        source_passives=(slug,)
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug=slug,
                payload=_rozkaz_payload(target_id),
                **_interrupt_guards(started.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert _stream_snapshot(activation_world, battle_id) == before


def test_straznik_private_rng_failure_does_not_stage_state_events_or_rng(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial, source_id, target_ids = _straznik_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before_stream = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
    real_resolve = interrupts_module._resolve_ranged_volley
    consumed: list[dict[str, object]] = []

    def fail_after_rolls(*args, **kwargs):
        result = real_resolve(*args, **kwargs)
        consumed.append(kwargs.get("dice", args[3]).to_checkpoint())
        raise RuntimeError("forced failure after Strażnik combat RNG")

    monkeypatch.setattr(
        interrupts_module,
        "_resolve_ranged_volley",
        fail_after_rolls,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="straznik",
                payload=_straznik_payload(target_ids),
                **_interrupt_guards(started.state),
            )
        session.rollback()

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert consumed and consumed[0] != rng_before
    assert _stream_snapshot(activation_world, battle_id) == before_stream
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == started.state
        assert checkpoint.dice.to_checkpoint() == rng_before


def test_interrupt_rejects_second_rozkaz_in_round_without_partial_delta(
    activation_world: ActivationWorld,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    with activation_world.sessions() as session:
        first = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="rozkaz",
            payload=_rozkaz_payload(target_id),
            **_interrupt_guards(started.state),
        )
        session.commit()
    before = _stream_snapshot(activation_world, battle_id)

    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptInvalid) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=first.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(target_id),
                **_interrupt_guards(first.state),
            )

    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert _stream_snapshot(activation_world, battle_id) == before


@pytest.mark.parametrize(
    ("guard", "error_type", "reason"),
    [
        (
            {"expected_sequence": 999},
            BattleActivationInterruptSequenceConflict,
            None,
        ),
        (
            {"activation_id": 999},
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            {"expected_activation_version": 999},
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.STALE_ACTIVATION,
        ),
        (
            {"expected_window_version": 999},
            BattleActivationInterruptInvalid,
            ActivationProtocolErrorReason.STALE_WINDOW,
        ),
    ],
)
def test_interrupt_rejects_stale_head_activation_and_window_guards(
    activation_world: ActivationWorld,
    guard: dict[str, int],
    error_type: type[Exception],
    reason: ActivationProtocolErrorReason | None,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)
    kwargs = {
        "battle_id": battle_id,
        "caller_user_id": activation_world.p1_id,
        "expected_sequence": started.new_sequence,
        "source_unit_id": source_id,
        "ability_slug": "rozkaz",
        "payload": _rozkaz_payload(target_id),
        **_interrupt_guards(started.state),
    }
    kwargs.update(guard)

    with activation_world.sessions() as session:
        with pytest.raises(error_type) as exc_info:
            stage_battle_activation_interrupt(session, **kwargs)

    if reason is not None:
        assert exc_info.value.reason is reason
    assert _stream_snapshot(activation_world, battle_id) == before


def test_interrupt_v1_and_missing_stale_or_mismatched_checkpoints_are_unavailable(
    activation_world: ActivationWorld,
) -> None:
    v1_id = _persist_battle(
        activation_world,
        state=_idle_state(initiative_player=None),
        protocol_version=1,
        checkpoint_version=1,
    )
    with activation_world.sessions() as session:
        with pytest.raises(BattleActivationInterruptUpgradeRequired):
            stage_battle_activation_interrupt(
                session,
                battle_id=v1_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=0,
                activation_id=1,
                expected_activation_version=1,
                expected_window_version=1,
                source_unit_id=11,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(11),
            )

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
            with pytest.raises(BattleActivationInterruptUnavailable) as exc_info:
                stage_battle_activation_interrupt(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=0,
                    activation_id=1,
                    expected_activation_version=1,
                    expected_window_version=1,
                    source_unit_id=11,
                    ability_slug="rozkaz",
                    payload=_rozkaz_payload(11),
                )
        assert exc_info.value.actual_sequence == actual_sequence


def test_interrupt_caller_rollback_removes_whole_staged_delta_and_checkpoint(
    activation_world: ActivationWorld,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()

    with activation_world.sessions() as session:
        stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug="rozkaz",
            payload=_rozkaz_payload(target_id),
            outcome_executor=_rng_consuming_ready_interrupt_executor,
            **_interrupt_guards(started.state),
        )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        assert checkpoint.dice.to_checkpoint() == rng_before


@pytest.mark.parametrize("failure", ["checkpoint-conflict", "integrity-error"])
def test_interrupt_write_conflict_rolls_back_events_and_checkpoint(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    before = _stream_snapshot(activation_world, battle_id)
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        rng_before = checkpoint.dice.to_checkpoint()
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
        with pytest.raises(BattleActivationInterruptWriteConflict):
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(target_id),
                outcome_executor=_rng_consuming_ready_interrupt_executor,
                **_interrupt_guards(started.state),
            )
        session.rollback()

    assert _stream_snapshot(activation_world, battle_id) == before
    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        assert checkpoint.dice.to_checkpoint() == rng_before


def test_interrupt_concurrent_head_change_reports_sequence_conflict_only(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state()
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    with activation_world.sessions() as session:
        rng_json_before = session.scalar(
            select(models.BattleCheckpoint.rng_json)
            .where(models.BattleCheckpoint.battle_id == battle_id)
            .order_by(models.BattleCheckpoint.sequence_at.desc())
            .limit(1)
        )
        assert rng_json_before is not None
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
                            from_pos=(5.0, 0.0),
                            to_pos=(6.0, 0.0),
                        )
                    ],
                    expected_latest_sequence=started.new_sequence,
                )
                competitor.commit()
        return real_save_events(db, persisted_battle_id, events, **kwargs)

    monkeypatch.setattr(activation_service, "save_events", race_before_guard)
    with activation_world.sessions() as session:
        with pytest.raises(
            BattleActivationInterruptSequenceConflict
        ) as exc_info:
            stage_battle_activation_interrupt(
                session,
                battle_id=battle_id,
                caller_user_id=activation_world.p1_id,
                expected_sequence=started.new_sequence,
                source_unit_id=source_id,
                ability_slug="rozkaz",
                payload=_rozkaz_payload(target_id),
                outcome_executor=_rng_consuming_ready_interrupt_executor,
                **_interrupt_guards(started.state),
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
        assert session.scalar(
            select(models.BattleCheckpoint.rng_json)
            .where(models.BattleCheckpoint.battle_id == battle_id)
            .order_by(models.BattleCheckpoint.sequence_at.desc())
            .limit(1)
        ) == rng_json_before


@pytest.mark.parametrize(
    ("ability_slug", "target_id", "target_owner", "ability", "granted"),
    [
        ("rozkaz", 11, 0, "niewrazliwy", True),
        ("klatwa", 13, 1, "delikatny", False),
    ],
)
def test_interrupt_restart_replay_then_pass_action_finalize_clears_override(
    activation_world: ActivationWorld,
    ability_slug: str,
    target_id: int,
    target_owner: int,
    ability: str,
    granted: bool,
) -> None:
    initial, source_id, target_id = _rozkaz_window_state(
        source_passives=(ability_slug,),
        target_id=target_id,
        target_owner=target_owner,
        target_passives=((ability,) if not granted else ()),
    )
    battle_id, started = _persist_started_battle(
        activation_world,
        state=initial,
    )
    with activation_world.sessions() as session:
        before = load_latest_checkpoint(session, battle_id)
        assert before is not None
        rng_before = before.dice.to_checkpoint()
        interrupted = stage_battle_activation_interrupt(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=started.new_sequence,
            source_unit_id=source_id,
            ability_slug=ability_slug,
            payload=_rozkaz_payload(
                target_id,
                ability=ability,
                granted=granted,
            ),
            **_interrupt_guards(started.state),
        )
        session.commit()

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == interrupted.state
        assert checkpoint.dice.to_checkpoint() == rng_before
        first_pass = stage_battle_activation_pass(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            **_pass_guards(checkpoint.state),
        )
        session.commit()

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        second_pass = stage_battle_activation_pass(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p2_id,
            expected_sequence=checkpoint.sequence_at,
            **_pass_guards(checkpoint.state),
        )
        session.commit()

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        committed = stage_battle_activation_action(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            action_payload=action_to_json(DefendAction(11)),
            **_action_guards(checkpoint.state),
        )
        session.commit()

    with activation_world.sessions() as session:
        checkpoint = load_latest_checkpoint(session, battle_id)
        assert checkpoint is not None
        finalized = stage_battle_activation_finalize(
            session,
            battle_id=battle_id,
            caller_user_id=activation_world.p1_id,
            expected_sequence=checkpoint.sequence_at,
            recovery_uses=(),
            **_action_guards(checkpoint.state),
        )
        session.commit()

    target = next(blob for blob in finalized.state.blobs if blob.id == target_id)
    assert target.ability_overrides == ()
    assert (ability in effective_passives(target)) is (not granted)
    assert any(type(item) is AbilityOverridesCleared for item in finalized.events)
    assert finalized.state.activation is None
    with activation_world.sessions() as restarted:
        checkpoint = load_latest_checkpoint(restarted, battle_id)
        assert checkpoint is not None
        assert checkpoint.state == finalized.state
        assert checkpoint.dice.to_checkpoint() == rng_before
        all_events = tuple(load_events(restarted, battle_id))
    assert finalized.state == apply_events(initial, all_events)
    assert (
        started.new_sequence
        < interrupted.new_sequence
        < first_pass.new_sequence
        < second_pass.new_sequence
        < committed.new_sequence
        < finalized.new_sequence
    )


def test_interrupt_success_is_one_batch_one_checkpoint_and_five_selects(
    activation_world: ActivationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_state, small_source, small_target = _rozkaz_window_state()
    large_state, large_source, large_target = _rozkaz_window_state(
        extra_units_per_player=30
    )
    small_id, small_started = _persist_started_battle(
        activation_world,
        state=small_state,
    )
    large_id, large_started = _persist_started_battle(
        activation_world,
        state=large_state,
        extra_units_per_player=30,
    )
    statements: list[str] = []
    save_event_calls = 0
    save_checkpoint_calls = 0
    guarded_heads: list[int | None] = []
    real_save_events = activation_service.save_events
    real_save_checkpoint = activation_service.save_checkpoint

    def count_save_events(*args, **kwargs):
        nonlocal save_event_calls
        save_event_calls += 1
        guarded_heads.append(kwargs.get("expected_latest_sequence"))
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
        for battle_id, started, source_id, target_id in (
            (small_id, small_started, small_source, small_target),
            (large_id, large_started, large_source, large_target),
        ):
            statements.clear()
            with activation_world.sessions() as session:
                stage_battle_activation_interrupt(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=started.new_sequence,
                    source_unit_id=source_id,
                    ability_slug="rozkaz",
                    payload=_rozkaz_payload(target_id),
                    outcome_executor=_rng_consuming_ready_interrupt_executor,
                    **_interrupt_guards(started.state),
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
    assert all(type(sequence) is int for sequence in guarded_heads)


def test_ready_handlers_match_service_query_and_statement_cost(
    activation_world: ActivationWorld,
) -> None:
    rozkaz_state, rozkaz_source, rozkaz_target = _rozkaz_window_state()
    klatwa_state, klatwa_source, klatwa_target = _rozkaz_window_state(
        source_passives=("klatwa",),
        target_id=13,
        target_owner=1,
    )
    rozkaz_id, rozkaz_started = _persist_started_battle(
        activation_world,
        state=rozkaz_state,
    )
    klatwa_id, klatwa_started = _persist_started_battle(
        activation_world,
        state=klatwa_state,
    )
    straznik_state, straznik_source, straznik_targets = _straznik_window_state(
        extra_units_per_player=30
    )
    straznik_id, straznik_started = _persist_started_battle(
        activation_world,
        state=straznik_state,
        extra_units_per_player=30,
    )
    cases = (
        (
            "rozkaz",
            rozkaz_id,
            rozkaz_started,
            rozkaz_source,
            _rozkaz_payload(rozkaz_target),
        ),
        (
            "klatwa",
            klatwa_id,
            klatwa_started,
            klatwa_source,
            _rozkaz_payload(
                klatwa_target,
                ability="delikatny",
                granted=True,
            ),
        ),
        (
            "straznik",
            straznik_id,
            straznik_started,
            straznik_source,
            _straznik_payload(straznik_targets),
        ),
    )
    statements: list[str] = []
    select_statements: dict[str, tuple[str, ...]] = {}

    def capture_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    event.listen(
        activation_world.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        for slug, battle_id, started, source_id, payload in cases:
            statements.clear()
            with activation_world.sessions() as session:
                stage_battle_activation_interrupt(
                    session,
                    battle_id=battle_id,
                    caller_user_id=activation_world.p1_id,
                    expected_sequence=started.new_sequence,
                    source_unit_id=source_id,
                    ability_slug=slug,
                    payload=payload,
                    **_interrupt_guards(started.state),
                )
                select_statements[slug] = tuple(
                    " ".join(statement.split())
                    for statement in statements
                    if statement.lstrip().upper().startswith("SELECT")
                )
                session.rollback()
    finally:
        event.remove(
            activation_world.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert (
        select_statements["rozkaz"]
        == select_statements["klatwa"]
        == select_statements["straznik"]
    )
    assert len(select_statements["straznik"]) == 5
