"""D6.2 public HTTP consent flow, narrow capabilities and one-shot safety."""
from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import agent_proposals, battles
from app.security import hash_agent_token
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import ChargeAction, DefendAction, ManeuverAction, ShootAction, SpecialAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.persistence import save_checkpoint
from app.services.engine.state import Lokalizacja, Position, TerrainCircle, WeaponProfile, apply_events
from app.services.engine.state_codec import battle_state_to_json
from app.services.engine.status import STATUS_AKTYWOWANY, STATUS_PRZYSZPILONY, STATUS_WYCZERPANY
from szop_client import HttpClient, HttpRequest, HttpResponse
from szop_client import bot_proposals as adapter
from test_battle_action_proposals import _action_state, _battle_snapshot

TOKEN = "d6-connect-isolated-secret"


# === SECTION: Isolated public HTTP harness and domain snapshots ===
def safe_state(mode="maneuver"):
    state = _action_state()
    blobs = tuple(replace(b, melee_weapons=(), ranged_weapons=()) for b in state.blobs)
    if mode == "special":
        blobs = (replace(blobs[0], status_flags=(STATUS_WYCZERPANY,)), *blobs[1:])
    elif mode == "defend":
        # No living enemy/objective: priority naturally chooses Defend.
        # No alternate action is selected by the adapter.
        blobs = (blobs[0], replace(blobs[1], location=Lokalizacja.WYCOFANY, models_alive=0))
    return replace(state, blobs=blobs)


@pytest.fixture
def harness():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        owner = models.User(username="d6-owner", password_hash="x")
        other = models.User(username="d6-other", password_hash="x")
        agent = models.User(username="d6-agent", password_hash="x", role=models.USER_ROLE_AGENT)
        session.add_all([owner, other, agent])
        session.flush()
        token = models.AgentToken(
            agent_user_id=agent.id, owner_user_id=owner.id, token_hash=hash_agent_token(TOKEN),
            scope_json=json.dumps({"battle:read": True, "agent_proposals:create": True}),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        state = safe_state()
        battle = models.Battle(
            p1_user_id=owner.id, p2_user_id=owner.id, current_round=state.round, rng_seed=2026, status="active",
        )
        session.add_all([battle, token])
        session.flush()
        save_checkpoint(session, battle.id, 0, state, DeterministicDice(2026))
        session.commit()
        ids = (owner.id, other.id, token.id, battle.id)
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="d6-test-cookie")
    test_app.include_router(battles.router)
    test_app.include_router(agent_proposals.router)

    def get_session():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = get_session
    requests = []
    statements = []
    segments = []

    def count_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.split()[0].upper())

    event.listen(engine, "before_cursor_execute", count_sql)
    with TestClient(test_app) as api:
        def transport(request: HttpRequest) -> HttpResponse:
            requests.append((request.method, urlsplit(request.url).path))
            started = len(statements)
            response = api.request(
                request.method, urlsplit(request.url).path, headers=request.headers, content=request.body,
            )
            segments.append(statements[started:])
            return HttpResponse(response.status_code, response.content)

        client = HttpClient("http://testserver", token=TOKEN, transport=transport)
        yield SimpleNamespace(
            sessions=sessions, api=api, client=client, transport=transport, requests=requests,
            statements=statements, segments=segments, owner_id=ids[0], other_id=ids[1],
            token_id=ids[2], battle_id=ids[3],
        )
    engine.dispose()


def attempt(h, **kwargs):
    return adapter.BotProposalAttempt(
        h.client, **{"battle_id": h.battle_id, "perspective": 0, "decision_seed": 19, "kind": "priority", **kwargs},
    )


def set_state(h, state, *, version=1):
    with h.sessions() as session:
        checkpoint = session.scalar(select(models.BattleCheckpoint))
        checkpoint.state_json = json.dumps(battle_state_to_json(state, version=version))
        battle = session.get(models.Battle, h.battle_id)
        battle.current_round = state.round
        battle.activation_protocol_version = version
        session.commit()


def snapshot(h):
    with h.sessions() as session:
        return _battle_snapshot(session, h.battle_id)


def count_proposals(h):
    with h.sessions() as session:
        return len(session.scalars(select(models.AgentProposal)).all())


def login_session(api, user_id):
    cookie = TimestampSigner("d6-test-cookie").sign(
        base64.b64encode(json.dumps({"user_id": user_id}).encode())
    ).decode()
    api.cookies.clear()
    api.cookies.set("session", cookie)


# === SECTION: Real bot decisions, separate owner approval and replay ===
@pytest.mark.parametrize("mode", ["maneuver", "special", "defend"])
def test_real_priority_http_pending_approval_events_and_replay(harness, monkeypatch, mode):
    h = harness
    set_state(h, safe_state(mode))
    before = snapshot(h)
    seeds = []
    factory = adapter.make_player

    def measured_factory(kind, seed):
        seeds.append((kind, seed))
        player = factory(kind, seed)
        def choose(state, perspective):
            before_sql = len(h.statements)
            selected = player.choose_action(state, perspective)
            assert len(h.statements) == before_sql  # bot decision does no SQL
            return selected
        return SimpleNamespace(choose_action=choose)

    monkeypatch.setattr(adapter, "make_player", measured_factory)
    step = attempt(h)
    result = step.run()
    assert result.outcome == "pending", result
    assert result.action_type == mode
    assert result.expected_sequence == before[5] == 0
    assert result.decision_ms >= 0
    assert seeds == [("priority", 19)]
    assert h.requests == [("GET", f"/battles/{h.battle_id}"), ("GET", f"/battles/{h.battle_id}/state"),
                          ("POST", "/agent_proposals/battle-actions")]
    assert [segment.count("SELECT") for segment in h.segments] == [4, 5, 6]
    assert snapshot(h) == before
    assert count_proposals(h) == 1
    assert step.run() is result
    assert len(h.requests) == 3
    assert TOKEN not in repr(step) + repr(result)
    print(f"D6.2 {mode}: decision_ms={result.decision_ms:.3f}; SELECT=4+5+6; botSQL=0")

    # Separate existing owner session / consent endpoint. Adapter has no approval method.
    login_session(h.api, h.owner_id)
    approved = h.api.post(f"/agent_proposals/{result.proposal_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    after = snapshot(h)
    assert after[5] > before[5]
    events = h.client.get_events(h.battle_id)
    assert apply_events(before[6], events) == after[6]
    replayed = h.client.replay_battle(h.battle_id)
    assert replayed.state == after[6]
    again = h.api.post(f"/agent_proposals/{result.proposal_id}/approve")
    assert again.status_code == 200
    assert again.json()["result"] == approved.json()["result"]
    assert snapshot(h) == after
    with h.sessions() as session:
        audits = session.scalars(select(models.AgentAuditLog)).all()
        assert TOKEN not in repr([row.params_json for row in audits])
        assert all("Authorization" not in row.params_json and "rng" not in row.params_json for row in audits)


# === SECTION: Kind, protocol, state and candidate capability gates ===
@pytest.mark.parametrize("kind,code", [("missing", "unknown_kind"), ("claude", "unknown_kind"),
    ("PRIORITY", "unknown_kind"), ("priority3", "kind_not_supported"), (None, "unknown_kind")])
def test_kind_is_exact_registry_name_without_default_or_alias(harness, kind, code):
    assert attempt(harness, kind=kind).run().code == code
    assert not harness.requests


@pytest.mark.parametrize("version", [2, 3])
def test_v2_v3_metadata_block_before_checkpoint_and_post(harness, version):
    set_state(harness, replace(safe_state(), initiative_player=0), version=version)
    assert attempt(harness).run().code == "protocol_not_supported"
    assert len(harness.requests) == 1
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("change,code", [
    (lambda s: replace(s, is_game_over=True), "not_combat_round"),
    (lambda s: replace(s, round=0), "not_combat_round"),
    (lambda s: replace(s, active_player=1), "wrong_perspective"),
    (lambda s: replace(s, pending_effects=("unverified",)), "pending_context"),
    (lambda s: replace(s, pending_interrupts=("unverified",)), "pending_context"),
    (lambda s: replace(s, terrain=(TerrainCircle(Position(3, 0), 1, ("Niebezpieczny",)),)), "terrain_not_supported"),
    (lambda s: replace(s, terrain=(TerrainCircle(Position(3, 0), 1, ()),)), "terrain_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], passives=("szybki",)), *s.blobs[1:])), "abilities_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], ability_overrides=(("wolny", True),)), *s.blobs[1:])), "abilities_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], status_flags=(STATUS_PRZYSZPILONY,)), *s.blobs[1:])), "status_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], status_flags=("unknown",)), *s.blobs[1:])), "status_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], wounds_pending=1), *s.blobs[1:])), "pending_context"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], radius_inches=0), *s.blobs[1:])), "geometry_not_supported"),
    (lambda s: replace(s, blobs=(replace(s.blobs[0], radius_inches=10**400), *s.blobs[1:])), "geometry_not_supported"),
])
def test_capability_gate_is_fail_closed_before_bot_and_post(harness, monkeypatch, change, code):
    set_state(harness, change(safe_state()))
    monkeypatch.setattr(adapter, "make_player", lambda *_args: pytest.fail("must gate before bot"))
    assert attempt(harness).run().code == code
    assert all(method == "GET" for method, _ in harness.requests)
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("field,value", [("latest_sequence", 1), ("current_round", 3), ("battle_id", 999)])
def test_metadata_checkpoint_mismatch_does_not_mix_snapshot(harness, monkeypatch, field, value):
    metadata = harness.client.get_battle_metadata(harness.battle_id)
    harness.requests.clear()
    monkeypatch.setattr(harness.client, "get_battle_metadata", lambda _id: replace(metadata, **{field: value}))
    assert attempt(harness).run().code == "snapshot_changed"
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("field,value,code", [("version", 2, "protocol_not_supported"),
    ("battle_id", 99, "snapshot_changed")])
def test_checkpoint_protocol_and_identity_are_independent_guards(harness, monkeypatch, field, value, code):
    checkpoint = harness.client.get_state_checkpoint(harness.battle_id)
    monkeypatch.setattr(harness.client, "get_state_checkpoint", lambda _id: replace(checkpoint, **{field: value}))
    assert attempt(harness).run().code == code
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("ability,quality_override", [("brutalny", None), (None, 2)])
def test_weapon_abilities_and_overrides_are_not_supported(harness, ability, quality_override):
    state = safe_state()
    weapon = WeaponProfile("sword", "sword", 0, 1, attack_quality_override=quality_override,
                           weapon_abilities=(ability,) if ability else ())
    set_state(harness, replace(state, blobs=(replace(state.blobs[0], melee_weapons=(weapon,)), *state.blobs[1:])))
    assert attempt(harness).run().code == "abilities_not_supported"
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("shooting", [True, False])
def test_actual_priority_combat_candidate_is_blocked_without_fallback(harness, shooting):
    state = safe_state()
    weapon = WeaponProfile("bow", "bow", 24, 1) if shooting else WeaponProfile("sword", "sword", 0, 1)
    actor = replace(state.blobs[0], **{"ranged_weapons" if shooting else "melee_weapons": (weapon,)})
    enemy = replace(state.blobs[1], position=Position(4, 0))
    set_state(harness, replace(state, blobs=(actor, enemy)))
    assert attempt(harness).run().code == "action_not_supported"
    assert len(harness.requests) == 2
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("action", [
    ShootAction(1, 2, WeaponProfile("bow", "bow", 24, 1)),
    ChargeAction(1, 2, WeaponProfile("sword", "sword", 0, 1)),
    SpecialAction(1, "mobilizacja"), SpecialAction(1, "discard_exhausted"),
    SpecialAction(1, "discard_exhausted", {"extra": True}), ManeuverAction(1, Position(100, 100)),
])
def test_unsupported_chosen_action_has_no_replacement_or_post(harness, monkeypatch, action):
    monkeypatch.setattr(adapter, "make_player", lambda *_: SimpleNamespace(choose_action=lambda *_: action))
    assert attempt(harness).run().outcome == "unsupported"
    assert len(harness.requests) == 2
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("change", [
    lambda b: replace(b, models_alive=0), lambda b: replace(b, location=Lokalizacja.ZAPLECZE),
    lambda b: replace(b, status_flags=(STATUS_AKTYWOWANY,)), lambda b: replace(b, owner_player=1),
])
def test_invalid_selected_actor_is_rejected(harness, monkeypatch, change):
    state = safe_state()
    set_state(harness, replace(state, blobs=(change(state.blobs[0]), *state.blobs[1:])))
    monkeypatch.setattr(adapter, "make_player", lambda *_: SimpleNamespace(choose_action=lambda *_: DefendAction(1)))
    assert attempt(harness).run().code == "actor_not_supported"
    assert count_proposals(harness) == 0


# === SECTION: Server authority, stale CAS, uncertainty and one-shot ledger ===
@pytest.mark.parametrize("battle_version, checkpoint_version", [
    (2, 2), (3, 3), (2, 1), (1, 2), (1, 3), (1, 99),
])
def test_legacy_proposal_rejects_wrong_protocol_at_create_and_approval(
    harness, battle_version, checkpoint_version,
):
    h = harness
    payload = {
        "battle_id": h.battle_id,
        "expected_sequence": 0,
        "action": action_to_json(DefendAction(unit_id=1)),
        "summary": "One v1 step",
    }
    headers = {"Authorization": f"Bearer {TOKEN}"}
    path = "/agent_proposals/battle-actions"
    created = h.api.post(path, headers=headers, json=payload)
    assert created.status_code == 201
    pending = created.json()
    assert pending["status"] == "pending"
    proposal_path = f"/agent_proposals/{pending['id']}"

    version = checkpoint_version if checkpoint_version in (2, 3) else 1
    state = safe_state()
    if version != 1:
        state = replace(state, initiative_player=0)
    wire = battle_state_to_json(state, version=version)
    wire["version"] = checkpoint_version
    checkpoint_fields = select(
        models.BattleCheckpoint.sequence_at,
        models.BattleCheckpoint.state_json,
        models.BattleCheckpoint.rng_json,
    )
    with h.sessions() as session:
        session.get(models.Battle, h.battle_id).activation_protocol_version = battle_version
        session.scalar(select(models.BattleCheckpoint)).state_json = json.dumps(wire)
        session.commit()
        before = session.execute(checkpoint_fields).one()

    refused_create = h.api.post(path, headers=headers, json=payload)
    login_session(h.api, h.other_id)
    assert h.api.post(f"{proposal_path}/approve").status_code == 404
    login_session(h.api, h.owner_id)
    refused_approve = h.api.post(f"{proposal_path}/approve")
    assert refused_create.status_code == refused_approve.status_code == 409
    assert refused_create.json() == refused_approve.json() == {
        "detail": "Battle action proposals require a valid v1 battle and checkpoint."
    }
    assert h.api.get(proposal_path).json() == pending
    assert count_proposals(h) == 1
    with h.sessions() as session:
        assert session.execute(checkpoint_fields).all() == [before]
        assert session.scalar(select(models.BattleEvent)) is None


@pytest.mark.parametrize("mode,status", [("missing", 401), ("expired", 401), ("scope", 403), ("foreign", 404), ("absent", 404)])
def test_server_auth_scopes_and_no_oracle_remain_authoritative(harness, mode, status):
    h = harness
    with h.sessions() as session:
        token = session.get(models.AgentToken, h.token_id)
        if mode == "expired":
            token.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        elif mode == "scope":
            token.scope_json = json.dumps({"battle:read": True})
        elif mode == "foreign":
            battle = session.get(models.Battle, h.battle_id)
            battle.p1_user_id = battle.p2_user_id = h.other_id
        session.commit()
    if mode == "missing":
        h.client = HttpClient("http://testserver", transport=h.transport)
    before = snapshot(h)
    result = attempt(h, **({"battle_id": h.battle_id + 100} if mode == "absent" else {})).run()
    assert result.http_status == status
    assert count_proposals(h) == 0
    assert snapshot(h) == before  # auth audit/last_used may still write


def test_stale_between_checkpoint_and_post_is_not_retried(harness, monkeypatch):
    original = harness.client.propose_battle_action
    def stale(battle_id, **kwargs):
        # A separate existing owner action wins after our checkpoint was read.
        # The adapter still posts exactly the sequence from its own checkpoint.
        with harness.sessions() as session:
            battles.take_battle_action(
                battle_id, battles.BattleActionCreate(expected_sequence=0, action=action_to_json(DefendAction(1))),
                db=session, actor=battles.BattleActor(user_id=harness.owner_id),
            )
        assert kwargs["expected_sequence"] == 0
        return original(battle_id, **kwargs)
    monkeypatch.setattr(harness.client, "propose_battle_action", stale)
    step = attempt(harness)
    result = step.run()
    assert result.code == "stale_sequence"
    assert result.http_status == 409
    assert step.run() is result
    assert [m for m, _ in harness.requests].count("POST") == 1
    assert count_proposals(harness) == 0


@pytest.mark.parametrize("phase", ["read", "before_post", "after_post", "500", "malformed"])
def test_uncertain_transport_never_retries_or_leaks_and_requires_reconciliation(harness, phase):
    h = harness
    sent = []
    def transport(request):
        sent.append(request.method)
        if phase == "read" or (request.method == "POST" and phase == "before_post"):
            raise TimeoutError(TOKEN + " Authorization rng=secret")
        response = h.transport(request)
        if request.method == "POST":
            if phase == "after_post":
                raise ConnectionError(TOKEN)
            if phase == "500":
                return HttpResponse(500, TOKEN.encode())
            if phase == "malformed":
                return HttpResponse(201, TOKEN.encode())
        return response
    h.client = HttpClient("http://testserver", token=TOKEN, transport=transport)
    before = snapshot(h)
    step = attempt(h)
    result = step.run()
    assert result.outcome == ("unavailable" if phase == "read" else "uncertain")
    assert TOKEN not in repr(result) + repr(step)
    assert step.run() is result
    assert sent.count("POST") == (0 if phase == "read" else 1)
    assert count_proposals(h) == (0 if phase in ("read", "before_post") else 1)
    assert snapshot(h) == before


def test_same_instance_concurrent_call_creates_one_proposal(harness):
    step = attempt(harness)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: step.run(), [1, 2]))
    assert a is b and a.outcome == "pending"
    assert len(harness.requests) == 3
    assert count_proposals(harness) == 1


@pytest.mark.parametrize("status,code", [(403, "forbidden"), (422, "invalid_action")])
def test_post_rejection_has_safe_explicit_outcome_and_no_retry(harness, status, code):
    sent = []
    def transport(request):
        sent.append(request.method)
        if request.method == "POST":
            return HttpResponse(status, json.dumps({"detail": TOKEN}).encode())
        return harness.transport(request)
    harness.client = HttpClient("http://testserver", token=TOKEN, transport=transport)
    step = attempt(harness)
    result = step.run()
    assert result.code == code and result.http_status == status
    assert step.run() is result
    assert sent.count("POST") == 1
    assert count_proposals(harness) == 0
    assert TOKEN not in repr(result)


def test_no_candidate_and_invalid_arguments_are_explicit(harness):
    state = safe_state()
    set_state(harness, replace(state, blobs=tuple(replace(b, status_flags=(STATUS_AKTYWOWANY,)) for b in state.blobs)))
    assert attempt(harness).run().code == "no_candidate"
    assert count_proposals(harness) == 0
    harness.requests.clear()
    for kwargs in ({"decision_seed": True}, {"perspective": True}, {"battle_id": 0}):
        assert attempt(harness, **kwargs).run().code == "invalid_arguments"
    assert not harness.requests


def test_cli_token_is_environment_only_and_output_is_safe(harness, monkeypatch, capsys):
    monkeypatch.setenv("SZOP_AGENT_TOKEN", TOKEN)
    calls = []
    def client(url, **kwargs):
        calls.append((url, kwargs["timeout"], kwargs["token"]))
        return harness.client
    monkeypatch.setattr(adapter, "HttpClient", client)
    assert adapter.main(["--url", "http://testserver", "--battle-id", str(harness.battle_id),
                         "--perspective", "0", "--seed", "19", "--timeout", "3"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["outcome"] == "pending"
    assert TOKEN not in output
    assert calls == [("http://testserver", 3.0, TOKEN)]
