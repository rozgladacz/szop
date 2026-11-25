"""HTTP acceptance for ADR-0060, with signed sessions and file-based SQLite."""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app import config, models
from app.db import Base, get_db, utcnow
from app.routers import agent_proposals, auth, bot_proposal_attempts
from app.security import hash_password
from app.services import bot_proposal_producer
from app.services.engine.action_codec import action_from_json
from app.services.engine.actions import ManeuverAction, ShootAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.persistence import load_latest_checkpoint, save_checkpoint
from app.services.engine.state import Position, WeaponProfile
from app.services.engine.state_codec import battle_state_to_json
from test_battle_action_proposals import _battle_snapshot
from test_bot_proposals import safe_state

ORIGIN = "https://szop.example"
ORIGIN_HEADER = {"Origin": ORIGIN}
SIGNER_KEY = "isolated-p4-session"
COMMAND = {"schema_version": 1, "side": 0, "kind": "priority", "seed": 19,
           "protocol": 1, "expected_sequence": 0}


def attempt_path(harness, *, stamp=None):
    stamp = datetime.now(UTC) if stamp is None else stamp
    return f"/battles/{harness.battle_id}/bot-proposal-attempts/{int(stamp.timestamp()*1000)}-{uuid4()}"


def set_cookie(api, owner_id, generation=None):
    payload = {"user_id": owner_id}
    if generation is not None:
        payload["owner_created_at"] = generation.isoformat(timespec="microseconds")
    signed = TimestampSigner(SIGNER_KEY).sign(base64.b64encode(json.dumps(payload).encode()))
    api.cookies.clear()
    api.cookies.set("session", signed.decode("ascii"))


@pytest.fixture
def p4(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOT_PROPOSAL_ORIGIN", ORIGIN)
    monkeypatch.setattr(config, "SESSION_HTTPS_ONLY", True)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p4.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        owner = models.User(username="p4-owner", password_hash=hash_password("test-password"))
        other = models.User(username="p4-other", password_hash="unused", role=models.USER_ROLE_ADMIN)
        agent = models.User(username="p4-agent", password_hash="unused", role=models.USER_ROLE_AGENT)
        session.add_all([owner, other, agent])
        session.flush()
        state = safe_state()
        battle = models.Battle(
            p1_user_id=owner.id, p2_user_id=other.id, current_round=state.round,
            rng_seed=2026, status="active",
        )
        session.add(battle)
        session.flush()
        save_checkpoint(session, battle.id, 0, state, DeterministicDice(2026))

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=SIGNER_KEY, https_only=True, same_site="lax")
    app.include_router(auth.router)
    app.include_router(agent_proposals.router)
    app.include_router(bot_proposal_attempts.router)

    def get_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = get_session
    statements = []

    def count_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.split()[0].upper())

    event.listen(engine, "before_cursor_execute", count_sql)
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as api:
        set_cookie(api, owner.id, owner.created_at)
        yield SimpleNamespace(
            api=api, app=app, engine=engine, sessions=sessions, statements=statements,
            owner=owner, other=other, agent=agent, battle_id=battle.id,
        )
    engine.dispose()


def post(harness, path=None, **fields):
    return harness.api.post(path or attempt_path(harness), headers=ORIGIN_HEADER, json={**COMMAND, **fields})


def replace_checkpoint(harness, state, *, version=1, metadata_version=1):
    with harness.sessions.begin() as db:
        checkpoint = db.scalar(select(models.BattleCheckpoint))
        checkpoint.state_json = json.dumps(battle_state_to_json(state, version=version))
        battle = db.get(models.Battle, harness.battle_id)
        battle.current_round = state.round
        battle.activation_protocol_version = metadata_version


def snapshot(harness):
    with harness.sessions() as db:
        return _battle_snapshot(db, harness.battle_id)


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("mode", ["maneuver", "defend", "special"])
def test_one_decision_creates_only_pending_until_separate_approval(p4, monkeypatch, mode):
    replace_checkpoint(p4, safe_state(mode))
    old_snapshot = snapshot(p4)
    decide_calls = []
    factory = bot_proposal_producer.make_player

    def make_measured_player(kind, seed):
        player = factory(kind, seed)

        def choose(state, side):
            sql_before = tuple(p4.statements)
            decide_calls.append((kind, seed, side))
            action = player.choose_action(state, side)
            assert tuple(p4.statements) == sql_before
            return action

        return SimpleNamespace(choose_action=choose)

    monkeypatch.setattr(bot_proposal_producer, "make_player", make_measured_player)
    url = attempt_path(p4)
    p4.statements.clear()
    created = post(p4, url)
    assert created.status_code == 201
    assert created.headers["location"] == url
    assert created.headers["cache-control"] == "private, no-store"
    assert p4.statements.count("SELECT") == 4
    assert p4.statements.count("INSERT") == 3
    assert snapshot(p4) == old_snapshot
    result = created.json()
    assert result["status"] == "proposal_created"
    assert result["reason"] is None
    assert result["expected_sequence"] == result["actual_sequence"] == 0
    assert datetime.fromisoformat(result["created_at"]).tzinfo == UTC
    proposal = f"/agent_proposals/{result['proposal_id']}"
    proposal_body = p4.api.get(proposal).json()
    assert proposal_body["payload"]["action"]["action_type"] == mode
    assert proposal_body["status"] == "pending" and proposal_body["token_id"] is None
    assert proposal_body["owner_user_id"] == proposal_body["agent_user_id"] == p4.owner.id
    with p4.sessions() as db:
        audit = db.scalar(select(models.AgentAuditLog))
        assert json.loads(audit.params_json) == {
            "action": "create", "proposal_id": result["proposal_id"],
            "proposal_action": "battle:action", "token_id": None, "producer": "server/priority-v1",
            "battle_id": p4.battle_id, "expected_sequence": 0,
            "attempt_digest": db.scalar(select(models.BotProposalAttempt.command_sha256)),
        }

    # Reconcile using only the attempt ID, then repeat without selecting again.
    p4.statements.clear()
    recovered = p4.api.get(url)
    assert recovered.status_code == 200 and recovered.json() == result
    assert p4.statements.count("SELECT") == 1
    p4.statements.clear()
    retried = post(p4, url)
    assert retried.status_code == 200 and retried.json() == result
    assert p4.statements.count("SELECT") == 2 and p4.statements.count("INSERT") == 0
    assert_error(post(p4, url, seed=20), 409, "attempt_payload_conflict")
    assert decide_calls == [("priority", 19, 0)]
    assert_error(p4.api.post(proposal + "/approve"), 403, "origin_rejected")
    assert snapshot(p4) == old_snapshot

    approval = p4.api.post(proposal + "/approve", headers=ORIGIN_HEADER)
    assert approval.status_code == 200 and approval.json()["status"] == "executed"
    approved_snapshot = snapshot(p4)
    assert approved_snapshot != old_snapshot
    assert p4.api.post(proposal + "/approve", headers=ORIGIN_HEADER).json() == approval.json()
    assert snapshot(p4) == approved_snapshot
    assert post(p4, url).json() == result and decide_calls == [("priority", 19, 0)]


def test_login_and_registration_add_generation_without_affecting_legacy_pending(p4, monkeypatch):
    p4.api.cookies.clear()
    assert_error(post(p4), 401, "owner_session_required")
    login = p4.api.post("/auth/login", data={"username": p4.owner.username, "password": "test-password"})
    assert login.status_code == 303 and "secure" in login.headers["set-cookie"].lower()
    assert post(p4).status_code == 201
    p4.api.get("/auth/logout")
    assert_error(post(p4), 401, "owner_session_required")
    monkeypatch.setattr(auth, "get_registration_open", lambda: True)
    assert p4.api.post("/auth/register", data={"username": "registered", "password": "new"}).status_code == 303
    assert_error(post(p4), 404, "not_found")  # fresh session, foreign battle

    with p4.sessions.begin() as db:
        old = models.AgentProposal(
            owner_user_id=p4.owner.id, agent_user_id=p4.agent.id,
            action="legacy", summary="Legacy pending", payload_json="{}",
        )
        db.add(old)
        db.flush()
        old_id = old.id
    set_cookie(p4.api, p4.owner.id)
    assert [item["id"] for item in p4.api.get("/agent_proposals").json()] == [old_id]
    assert p4.api.post(f"/agent_proposals/{old_id}/approve").json()["status"] == "approved"


def test_scope_distinguishes_stale_session_from_foreign_resource(p4):
    url = attempt_path(p4)
    result = post(p4, url).json()
    proposal = f"/agent_proposals/{result['proposal_id']}"
    set_cookie(p4.api, p4.other.id, p4.other.created_at)
    assert_error(post(p4, url), 404, "not_found")
    assert_error(p4.api.get(url), 404, "not_found")
    assert p4.api.get(proposal).status_code == 404
    set_cookie(p4.api, p4.agent.id, p4.agent.created_at)
    assert_error(post(p4), 401, "owner_session_required")
    set_cookie(p4.api, p4.owner.id)  # signed session from before P4
    assert_error(post(p4), 401, "owner_session_required")
    assert p4.api.get(proposal).status_code == 404
    assert p4.api.get("/agent_proposals").json() == []

    new_generation = utcnow() + timedelta(days=1)
    with p4.sessions.begin() as db:
        db.get(models.User, p4.owner.id).created_at = new_generation
    set_cookie(p4.api, p4.owner.id, p4.owner.created_at)
    assert_error(post(p4), 401, "owner_session_required")
    assert_error(p4.api.get(url), 401, "owner_session_required")
    assert p4.api.post(proposal + "/approve", headers=ORIGIN_HEADER).status_code == 404
    set_cookie(p4.api, p4.owner.id, new_generation)
    assert_error(post(p4), 404, "not_found")
    assert p4.api.post(proposal + "/reject", headers=ORIGIN_HEADER).status_code == 404
    assert p4.api.get("/agent_proposals").json() == []


@pytest.mark.parametrize("headers", [
    [],
    [("Origin", "null")],
    [("Origin", "http://szop.example")],
    [("Origin", ORIGIN + "/")],
    [("Origin", ORIGIN), ("Origin", ORIGIN)],
    [("Origin", "https://foreign.example"), ("X-Forwarded-Host", "foreign.example")],
])
def test_origin_is_taken_only_from_one_explicit_allowed_value(p4, headers):
    assert_error(p4.api.post(attempt_path(p4), headers=headers, json=COMMAND), 403, "origin_rejected")


def test_secure_configuration_and_bearer_are_fail_closed(p4, monkeypatch):
    url = attempt_path(p4)
    assert_error(p4.api.post(url, headers={**ORIGIN_HEADER, "Authorization": "Bearer ignored"},
                            json=COMMAND), 401, "owner_session_required")
    monkeypatch.setattr(config, "SESSION_HTTPS_ONLY", False)
    assert_error(p4.api.get(url), 404, "not_found")
    monkeypatch.setattr(config, "BOT_PROPOSAL_ORIGIN", "http://example.com")
    assert_error(p4.api.get(url), 404, "not_found")
    monkeypatch.setattr(config, "BOT_PROPOSAL_ORIGIN", "http://127.0.0.1:8000")
    assert_error(p4.api.get(url), 404, "not_found")  # enabled, but the attempt does not exist
    local = p4.api.post(url, headers={"Origin": "http://127.0.0.1:8000"}, json=COMMAND)
    assert local.status_code == 201


@pytest.mark.parametrize(("raw", "media", "status", "code"), [
    (b"{}", "text/plain", 415, "unsupported_media_type"),
    (b"{}", "application/json; charset=latin-1", 415, "unsupported_media_type"),
    (b" " * 1025, "application/json", 413, "command_too_large"),
    (b'{"side":0,"side":1}', "application/json", 422, "invalid_command"),
    (b"\xff", "application/json", 422, "invalid_command"),
    (b"[]", "application/json", 422, "invalid_command"),
    (b"[" * 1024, "application/json", 422, "invalid_command"),
    (b'{"schema_version":1,"side":true,"kind":"priority","seed":19,"protocol":1,"expected_sequence":0}',
     "application/json", 422, "invalid_command"),
    (b'{"schema_version":1,"side":0,"kind":"priority","seed":19,"protocol":1,"expected_sequence":0,"owner_user_id":1}',
     "application/json", 422, "invalid_command"),
])
def test_command_is_bounded_strict_json(p4, raw, media, status, code):
    response = p4.api.post(attempt_path(p4), headers={**ORIGIN_HEADER, "Content-Type": media}, content=raw)
    assert_error(response, status, code)
    with p4.sessions() as db:
        assert db.scalars(select(models.BotProposalAttempt)).all() == []


def test_head_is_checked_before_active_side_and_retry_window_survives_expiry(p4, monkeypatch):
    monkeypatch.setattr(bot_proposal_producer, "make_player", lambda *_: pytest.fail("must gate before bot"))
    set_cookie(p4.api, p4.other.id, p4.other.created_at)
    assert post(p4, side=1).json()["reason"] == "unsupported_context"
    result = post(p4, side=1, expected_sequence=3).json()
    assert result["status"] == "stale" and result["actual_sequence"] == 0
    old = attempt_path(p4, stamp=datetime.now(UTC) - timedelta(hours=25))
    assert_error(post(p4, old, side=1), 410, "attempt_expired")
    assert_error(post(p4, old), 404, "not_found")
    assert_error(post(p4, attempt_path(p4, stamp=datetime.now(UTC) + timedelta(minutes=3)), side=1),
                 422, "invalid_command")


@pytest.mark.parametrize(("mode", "reason"), [
    ("no_candidate", "no_candidate"),
    ("unsupported_action", "unsupported_action"),
    ("invalid_action", "invalid_action"),
    ("mismatch", "unsupported_protocol"),
    ("v3", "unsupported_protocol"),
    ("missing", "checkpoint_unavailable"),
])
def test_no_proposal_has_no_fallback_or_mutation(p4, monkeypatch, mode, reason):
    if mode == "mismatch":
        replace_checkpoint(p4, replace(safe_state(), initiative_player=0), version=2, metadata_version=1)
    if mode == "v3":
        replace_checkpoint(p4, safe_state(), metadata_version=3)
    if mode == "missing":
        with p4.sessions.begin() as db:
            db.delete(db.scalar(select(models.BattleCheckpoint)))
    action = {
        "no_candidate": None,
        "unsupported_action": ShootAction(1, 2, WeaponProfile("bow", "bow", 24, 1)),
        "invalid_action": ManeuverAction(1, Position(100, 100)),
    }.get(mode)
    monkeypatch.setattr(bot_proposal_producer, "make_player",
                        lambda *_: SimpleNamespace(choose_action=lambda *_: action))
    before = snapshot(p4)
    response = post(p4)
    assert response.status_code == 201
    assert response.json()["status"] == "no_proposal"
    assert response.json()["reason"] == reason and response.json()["proposal_id"] is None
    assert snapshot(p4) == before
    with p4.sessions() as db:
        assert db.scalars(select(models.AgentProposal)).all() == []


def test_late_approval_is_stale_and_server_reject_requires_origin(p4):
    first = post(p4).json()
    second = post(p4).json()
    third = post(p4).json()
    route = f"/agent_proposals/{third['proposal_id']}/reject"
    assert_error(p4.api.post(route), 403, "origin_rejected")
    rejected = p4.api.post(route, headers=ORIGIN_HEADER).json()
    assert rejected["status"] == "rejected"
    assert p4.api.post(route, headers=ORIGIN_HEADER).json() == rejected
    conflict = p4.api.post(f"/agent_proposals/{third['proposal_id']}/approve", headers=ORIGIN_HEADER)
    assert conflict.status_code == 409 and conflict.headers["cache-control"] == "private, no-store"
    assert p4.api.post(f"/agent_proposals/{first['proposal_id']}/approve", headers=ORIGIN_HEADER).status_code == 200
    before = snapshot(p4)
    stale = p4.api.post(f"/agent_proposals/{second['proposal_id']}/approve", headers=ORIGIN_HEADER)
    assert stale.json()["status"] == "stale"
    assert snapshot(p4) == before


def test_busy_and_two_clients_preserve_one_committed_result(p4):
    url = attempt_path(p4)
    with p4.engine.connect() as holder:
        holder.exec_driver_sql("BEGIN IMMEDIATE")
        assert_error(post(p4, url), 503, "attempt_temporarily_unavailable")
        assert_error(p4.api.get(url), 404, "not_found")
        holder.rollback()

    def submit_from_client():
        with TestClient(p4.app, base_url=ORIGIN) as api:
            set_cookie(api, p4.owner.id, p4.owner.created_at)
            return api.post(url, headers=ORIGIN_HEADER, json=COMMAND)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _: submit_from_client(), range(2))
    assert sorted((first.status_code, second.status_code)) == [200, 201]
    assert first.json() == second.json() == p4.api.get(url).json()
    with p4.sessions() as db:
        assert len(db.scalars(select(models.AgentProposal)).all()) == 1
        assert load_latest_checkpoint(db, p4.battle_id).sequence_at == 0


def test_lost_receipt_can_be_read_after_commit_without_a_second_proposal(p4, monkeypatch):
    url = attempt_path(p4)
    before = snapshot(p4)
    reply = bot_proposal_attempts._reply

    def lost_receipt(result, *, created=False):
        if created:
            raise TimeoutError("isolate failure after the write")
        return reply(result)

    monkeypatch.setattr(bot_proposal_attempts, "_reply", lost_receipt)
    with pytest.raises(TimeoutError):
        post(p4, url)
    recovered = p4.api.get(url)
    assert recovered.status_code == 200 and recovered.json()["status"] == "proposal_created"
    assert post(p4, url).json() == recovered.json()
    assert snapshot(p4) == before
    with p4.sessions() as db:
        assert len(db.scalars(select(models.AgentProposal)).all()) == 1
        assert len(db.scalars(select(models.AgentAuditLog)).all()) == 1


def test_same_owner_can_explicitly_select_their_active_second_side(p4):
    state = replace(safe_state(), active_player=1)
    replace_checkpoint(p4, state)
    with p4.sessions.begin() as db:
        db.get(models.Battle, p4.battle_id).p2_user_id = p4.owner.id
    assert post(p4, side=0).json()["reason"] == "unsupported_context"
    result = post(p4, side=1).json()
    assert result["status"] == "proposal_created"
    proposal = p4.api.get(f"/agent_proposals/{result['proposal_id']}").json()
    chosen = action_from_json(proposal["payload"]["action"]).unit_id
    assert next(unit for unit in state.blobs if unit.id == chosen).owner_player == 1
