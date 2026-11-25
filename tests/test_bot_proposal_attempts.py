from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from threading import Event, current_thread
from time import perf_counter
from types import SimpleNamespace

import pytest
from sqlalchemy import URL, create_engine, event, inspect, select, update
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.services import bot_proposal_attempts as ledger
from app.services.battle_actions import prepare_battle_action, stage_battle_action
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction
from test_battle_action_proposals import _battle_snapshot, _persist_battle

ACCOUNT_CREATED = datetime(2026, 9, 1, 12)
NOW = datetime(2026, 11, 25, 12)
UUID = "550e8400-e29b-41d4-a716-446655440000"


def attempt_id(issued=NOW, uuid=UUID):
    millis = (issued - datetime(1970, 1, 1)) // timedelta(milliseconds=1)
    return f"{millis:013d}-{uuid}"


def command_for(battle_id, /, **changes):
    fields = dict(
        battle_id=battle_id, attempt_id=attempt_id(), schema_version=1,
        side=0, kind="priority", seed=19, protocol=1, expected_sequence=0,
    )
    return ledger.BotProposalCommand(**(fields | changes))


@pytest.fixture
def ledger_battle(tmp_path):
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "attempts.sqlite")),
        connect_args={"timeout": 0.25},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = models.User(username="owner", password_hash="x", created_at=ACCOUNT_CREATED)
        other = models.User(username="other", password_hash="x", created_at=ACCOUNT_CREATED)
        session.add_all([owner, other])
        session.flush()
        battle = _persist_battle(session, p1=owner, p2=other)
        battle.created_at = ACCOUNT_CREATED + timedelta(days=1)
        session.commit()
        owner_id, other_id, battle_id = owner.id, other.id, battle.id
    yield SimpleNamespace(engine=engine, owner_id=owner_id, other_id=other_id, battle_id=battle_id)
    engine.dispose()


def prepare(db, battle, command):
    result = prepare_battle_action(
        db, battle=battle, actor_user_id=battle.p1_user_id,
        expected_sequence=command.expected_sequence,
        action_payload=action_to_json(DefendAction(unit_id=1)),
        require_v1_protocol=True,
    )
    return ledger.BotProposalDecision(result.previous_sequence, prepared=result)


def submit(h, command=None, *, decide=prepare, stamp=NOW, owner=None, generation=ACCOUNT_CREATED):
    return ledger.create_bot_proposal_attempt(
        h.engine, command if command is not None else command_for(h.battle_id),
        owner_user_id=owner if owner is not None else h.owner_id, owner_created_at=generation,
        decide=decide, now=lambda: stamp,
    )


def read(h, *, stamp=NOW, owner=None, generation=ACCOUNT_CREATED, key=None):
    return ledger.get_bot_proposal_attempt(
        h.engine, owner_user_id=owner if owner is not None else h.owner_id,
        owner_created_at=generation, battle_id=h.battle_id,
        attempt_id=key if key is not None else attempt_id(), now=lambda: stamp,
    )


def records(h):
    with Session(h.engine) as session:
        return tuple(list(session.scalars(select(model))) for model in (
            models.BotProposalAttempt, models.AgentProposal, models.AgentAuditLog,
        ))


def snapshot(h):
    with Session(h.engine) as session:
        return _battle_snapshot(session, h.battle_id)


def assert_error(code, operation, *args, **kwargs):
    with pytest.raises(ledger.BotProposalAttemptError) as error:
        operation(*args, **kwargs)
    assert error.value.code == code


def unexpected_prepare(*_):
    pytest.fail("Preparation unexpectedly ran")


def test_schema_and_canonical_command(ledger_battle):
    inspector = inspect(ledger_battle.engine)
    unique = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("bot_proposal_attempts")
    }
    assert {("owner_user_id", "owner_created_at", "attempt_id"), ("proposal_id",)} <= unique
    assert any(index["column_names"] == ["created_at"] for index in inspector.get_indexes("bot_proposal_attempts"))
    foreign_key, = inspector.get_foreign_keys("bot_proposal_attempts")
    assert foreign_key["referred_table"] == "agent_proposals"
    assert foreign_key["constrained_columns"] == ["proposal_id"]
    assert foreign_key["options"]["ondelete"] == "RESTRICT"

    command = command_for(42, attempt_id=f"1795572300000-{UUID}", expected_sequence=37)
    expected = (
        '{"attempt_id":"1795572300000-550e8400-e29b-41d4-a716-446655440000",'
        '"battle_id":42,"expected_sequence":37,"kind":"priority",'
        '"owner_created_at":"2026-09-01T12:00:00.000000Z","owner_user_id":7,'
        '"protocol":1,"schema_version":1,"seed":19,"side":0}'
    )
    assert command.canonical_json(7, ACCOUNT_CREATED) == expected


@pytest.mark.parametrize("changes", [
    {"battle_id": 0}, {"battle_id": 2**53}, {"protocol": 2}, {"schema_version": True},
    {"side": False}, {"side": 2}, {"seed": -(2**53)}, {"seed": "19"}, {"kind": "Priority"},
    {"expected_sequence": -1}, {"expected_sequence": 1.0},
    {"attempt_id": f"1795572300000-{UUID.upper()}"}, {"attempt_id": f"795572300000-{UUID}"},
    {"attempt_id": f"1795572300000-{UUID.replace('-41d4-', '-51d4-')}"},
])
def test_invalid_command_contract(changes):
    # Validate command fields directly, before acquiring the ledger's write lock.
    assert_error("invalid_command", lambda: command_for(1, **changes))


def test_commit_retry_from_new_connection_keeps_proposal_and_audit(ledger_battle):
    h = ledger_battle
    before = snapshot(h)
    result, created = submit(h)
    assert created and result.status == "proposal_created"
    assert result.actual_sequence == result.expected_sequence == 0
    assert result.expires_at == NOW + timedelta(days=1)
    h.engine.dispose()
    assert submit(h, decide=unexpected_prepare) == (result, False)
    assert read(h) == result
    assert snapshot(h) == before

    (attempt,), (proposal,), (audit,) = records(h)
    assert attempt.command_sha256 == sha256(attempt.command_json.encode("utf-8")).hexdigest()
    assert proposal.id == result.proposal_id
    assert proposal.owner_user_id == proposal.agent_user_id == h.owner_id
    assert proposal.token_id is None
    assert proposal.producer_owner_created_at == ACCOUNT_CREATED
    assert proposal.status == models.AGENT_PROPOSAL_STATUS_PENDING
    assert audit.user_id == audit.agent_user_id == h.owner_id
    audit_details = json.loads(audit.params_json)
    assert audit_details["producer"] == "server/priority-v1"
    assert audit_details["action"] == "create"
    assert audit_details["attempt_digest"] == attempt.command_sha256

    assert_error("attempt_payload_conflict", submit, h, command_for(h.battle_id, seed=20),
                 decide=unexpected_prepare)
    assert read(h) == result


def test_retry_returns_original_result_after_battle_head_advances(ledger_battle):
    h = ledger_battle
    original, _ = submit(h)
    with Session(h.engine) as db:
        advanced = stage_battle_action(
            db,
            battle=db.get(models.Battle, h.battle_id),
            actor_user_id=h.owner_id,
            expected_sequence=0,
            action_payload=action_to_json(DefendAction(unit_id=1)),
            require_v1_protocol=True,
        )
        db.commit()
    assert advanced.new_sequence > original.actual_sequence
    before_retry = snapshot(h)
    assert submit(h, decide=unexpected_prepare) == (original, False)
    assert snapshot(h) == before_retry
    assert [len(group) for group in records(h)] == [1, 1, 1]


def test_audit_failure_rolls_back_already_flushed_proposal(ledger_battle, monkeypatch):
    h = ledger_battle
    before = snapshot(h)
    audit = ledger.audit_proposal

    def broken_audit(session, **fields):
        audit(session, **fields)
        session.flush()
        raise RuntimeError("Synthetic audit failure")

    with monkeypatch.context() as changes:
        changes.setattr(ledger, "audit_proposal", broken_audit)
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            submit(h)
    assert records(h) == ([], [], [])
    assert snapshot(h) == before
    assert_error("not_found", read, h)
    assert submit(h)[1]
    assert [len(group) for group in records(h)] == [1, 1, 1]


@pytest.mark.parametrize("same_payload", [True, False])
def test_parallel_writer_waits_and_observes_committed_result(ledger_battle, same_payload):
    h = ledger_battle
    first_preparing = Event()
    second_begin = Event()
    allow_commit = Event()

    def before_sql(_conn, _cursor, sql, _params, _context, _many):
        if sql == "BEGIN IMMEDIATE" and current_thread().name == "attempt-second_0":
            second_begin.set()

    def decide(db, battle, command):
        first_preparing.set()
        assert allow_commit.wait(5)
        return prepare(db, battle, command)

    event.listen(h.engine, "before_cursor_execute", before_sql)
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="attempt-first") as first_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="attempt-second") as second_pool,
    ):
        first = first_pool.submit(submit, h, decide=decide)
        try:
            assert first_preparing.wait(5)
            command = command_for(h.battle_id, seed=19 if same_payload else 20)
            second = second_pool.submit(submit, h, command, decide=unexpected_prepare)
            assert second_begin.wait(5)
            assert_error("not_found", read, h)
        finally:
            allow_commit.set()

        first_result, created = first.result(timeout=5)
        assert created
        if same_payload:
            assert second.result(timeout=5) == (first_result, False)
        else:
            assert_error("attempt_payload_conflict", second.result, timeout=5)
    assert [len(group) for group in records(h)] == [1, 1, 1]


def test_busy_timeout_is_bounded_and_restored(ledger_battle):
    h = ledger_battle
    with h.engine.connect() as holder:
        holder.exec_driver_sql("BEGIN IMMEDIATE")
        start = perf_counter()
        assert_error("attempt_temporarily_unavailable", submit, h, decide=unexpected_prepare)
        assert perf_counter() - start >= 1.5
        holder.rollback()
    with h.engine.connect() as first, h.engine.connect() as second:
        assert first.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 250
        assert second.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 250
    assert records(h) == ([], [], [])


def test_retention_prunes_only_a_bounded_batch_and_keeps_proposal(ledger_battle):
    h = ledger_battle
    first, _ = submit(h)
    second_command = command_for(h.battle_id, attempt_id=attempt_id(NOW + timedelta(seconds=1)))
    second, _ = submit(h, second_command, stamp=NOW + timedelta(seconds=1))
    expired = NOW + timedelta(days=30)

    assert_error("attempt_expired", submit, h, stamp=first.expires_at, decide=unexpected_prepare)
    assert read(h, stamp=expired - timedelta(microseconds=1)) == first
    assert_error("not_found", read, h, stamp=expired)
    assert read(h, key=second.attempt_id, stamp=expired) == second
    assert ledger.purge_bot_proposal_attempts(h.engine, batch_size=1, now=lambda: expired) == 1
    assert ledger.purge_bot_proposal_attempts(h.engine, batch_size=1, now=lambda: expired) == 0
    assert_error("attempt_expired", submit, h, stamp=expired, decide=unexpected_prepare)
    assert [len(group) for group in records(h)] == [1, 2, 2]


def test_future_clock_boundaries_and_stable_stale_outcome(ledger_battle):
    h = ledger_battle
    future_id = attempt_id(NOW + timedelta(minutes=2))
    future = command_for(h.battle_id, attempt_id=future_id)
    too_far = replace(future, attempt_id=attempt_id(NOW + timedelta(minutes=2, milliseconds=1)))
    assert_error("invalid_command", submit, h, too_far, decide=unexpected_prepare)

    def stale(_db, _battle, _command):
        return ledger.BotProposalDecision(actual_sequence=9, reason="head_changed")

    result, created = submit(h, future, decide=stale)
    assert created and result.status == "stale" and result.actual_sequence == 9
    assert result.reason == "head_changed" and result.proposal_id is None
    assert submit(h, future, decide=unexpected_prepare) == (result, False)
    assert [len(group) for group in records(h)] == [1, 0, 0]


def test_scope_checks_generation_and_current_side(ledger_battle):
    h = ledger_battle
    first, _ = submit(h)
    assert_error("not_found", read, h, owner=h.other_id)
    assert_error("not_found", submit, h, owner=h.other_id, decide=unexpected_prepare)
    other_side = command_for(h.battle_id, side=1)
    assert_error("not_found", submit, h, other_side, decide=unexpected_prepare)

    other, created = submit(
        h, other_side, owner=h.other_id,
        decide=lambda *_: ledger.BotProposalDecision(0, "unsupported_context"),
    )
    assert created and other.status == "no_proposal" and other.reason == "unsupported_context"
    assert read(h, owner=h.other_id) == other
    assert read(h) == first

    newer_generation = ACCOUNT_CREATED + timedelta(days=2)
    with h.engine.begin() as connection:
        connection.execute(update(models.User).where(models.User.id == h.owner_id)
                           .values(created_at=newer_generation))
    assert_error("owner_session_required", read, h)
    assert_error("owner_session_required", submit, h, decide=unexpected_prepare)
    assert_error("not_found", read, h, generation=newer_generation)
    assert_error("not_found", submit, h, generation=newer_generation, decide=unexpected_prepare)
