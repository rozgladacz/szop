from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.main import app as main_app
from app.routers import battles
from app.security import hash_agent_token
from app.services import battle_invites as battle_invite_service


FIXED_NOW = datetime(2026, 7, 19, 10, 30, 0)
RAW_TOKEN = "battle-invite-secret"
PUBLIC_FIELDS = {
    "id",
    "from_user_id",
    "to_user_id",
    "roster_id",
    "scenario",
    "status",
    "activation_protocol_version",
    "expires_at",
    "created_at",
    "updated_at",
}


@dataclass(frozen=True)
class ApiWorld:
    client: TestClient
    sessions: sessionmaker[Session]
    engine: object
    owner_id: int
    target_id: int
    admin_id: int
    agent_target_id: int
    other_id: int
    roster_id: int
    foreign_roster_id: int


@pytest.fixture()
def api_world(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="battle-invite-test")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db

    @test_app.post("/_test/session/{user_id}")
    def set_test_session(user_id: int, request: Request) -> dict[str, int]:
        request.session["user_id"] = user_id
        return {"user_id": user_id}

    with sessions() as session:
        owner = models.User(username="invite-owner", password_hash="x")
        target = models.User(username="invite-target", password_hash="x")
        admin = models.User(
            username="invite-admin",
            password_hash="x",
            is_admin=True,
            role=models.USER_ROLE_ADMIN,
        )
        agent_target = models.User(
            username="invite-agent-target",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        other = models.User(username="invite-other", password_hash="x")
        ruleset = models.RuleSet(name="Invite router rules")
        armory = models.Armory(name="Invite router armory", owner=owner)
        army = models.Army(
            name="Invite router army",
            owner=owner,
            ruleset=ruleset,
            armory=armory,
        )
        roster = models.Roster(
            name="Owner invite roster",
            owner=owner,
            army=army,
        )
        foreign_roster = models.Roster(
            name="Foreign invite roster",
            owner=other,
            army=army,
        )
        session.add_all(
            [
                owner,
                target,
                admin,
                agent_target,
                other,
                ruleset,
                armory,
                army,
                roster,
                foreign_roster,
            ]
        )
        session.commit()
        world_ids = {
            "owner_id": owner.id,
            "target_id": target.id,
            "admin_id": admin.id,
            "agent_target_id": agent_target.id,
            "other_id": other.id,
            "roster_id": roster.id,
            "foreign_roster_id": foreign_roster.id,
        }

    monkeypatch.setattr(battle_invite_service, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(models, "utcnow", lambda: FIXED_NOW)
    with TestClient(test_app) as client:
        yield ApiWorld(
            client=client,
            sessions=sessions,
            engine=engine,
            **world_ids,
        )
    engine.dispose()


def _login(world: ApiWorld, user_id: int | None = None) -> None:
    response = world.client.post(
        f"/_test/session/{user_id if user_id is not None else world.owner_id}"
    )
    assert response.status_code == 200


def _headers(raw_token: str = RAW_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def _invite_count(world: ApiWorld) -> int:
    with world.sessions() as session:
        return int(
            session.execute(
                select(func.count()).select_from(models.BattleInvite)
            ).scalar_one()
        )


def _seed_token(
    world: ApiWorld,
    *,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
) -> int:
    with world.sessions() as session:
        agent = models.User(
            username=f"agent-{raw_token}",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        token = models.AgentToken(
            agent_user=agent,
            owner_user_id=world.owner_id,
            token_hash=hash_agent_token(raw_token),
            scope_json=json.dumps(
                scopes
                if scopes is not None
                else {battles.BATTLE_INVITE_SCOPE: True}
            ),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        session.add_all([agent, token])
        session.commit()
        return token.id


def _post(
    world: ApiWorld,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
):
    return world.client.post(
        "/battles/invite",
        json=body if body is not None else {"roster_id": world.roster_id},
        headers=headers,
    )


def _statement_count(world: ApiWorld, *, body: dict[str, object], headers=None) -> int:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(world.engine, "before_cursor_execute", record)
    try:
        response = _post(world, body=body, headers=headers)
    finally:
        event.remove(world.engine, "before_cursor_execute", record)
    assert response.status_code == 201, response.text
    return len(statements)


def test_main_app_registers_exactly_one_battle_invite_post_route() -> None:
    routes = [
        route
        for route in main_app.routes
        if getattr(route, "path", None) == "/battles/invite"
    ]

    assert len(routes) == 1
    assert getattr(routes[0], "methods", set()) == {"POST"}


def test_session_user_creates_canonical_direct_pending_invite(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    response = _post(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
            "scenario": "  LuStRzAnA_A  ",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == PUBLIC_FIELDS
    assert payload["from_user_id"] == api_world.owner_id
    assert payload["to_user_id"] == api_world.target_id
    assert payload["roster_id"] == api_world.roster_id
    assert payload["scenario"] == "lustrzana_a"
    assert payload["status"] == models.BATTLE_INVITE_STATUS_PENDING
    assert payload["activation_protocol_version"] == 1
    assert datetime.fromisoformat(payload["expires_at"]) == FIXED_NOW + timedelta(
        hours=24
    )
    json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, payload["id"])
        assert invite is not None
        assert invite.from_user_id == api_world.owner_id
        assert invite.to_user_id == api_world.target_id
        assert invite.roster_id == api_world.roster_id
        assert invite.scenario == "lustrzana_a"
        assert invite.status == models.BATTLE_INVITE_STATUS_PENDING
        assert invite.activation_protocol_version == 1
        assert invite.expires_at == FIXED_NOW + timedelta(hours=24)
        assert invite.expires_at.tzinfo is None
        assert invite.created_at == FIXED_NOW
        assert invite.updated_at == FIXED_NOW
        assert invite.accepted_by_user_id is None
        assert invite.accepted_roster_id is None
        assert invite.battle_id is None


def test_session_user_creates_open_invite_with_default_expiry(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    response = _post(api_world)

    assert response.status_code == 201
    assert response.json()["to_user_id"] is None
    assert datetime.fromisoformat(response.json()["expires_at"]) == (
        FIXED_NOW + timedelta(hours=24)
    )


def test_explicit_v2_invite_is_public_and_persisted_immutably(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    response = _post(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
            "activation_protocol_version": 2,
        },
    )

    assert response.status_code == 201
    assert response.json()["activation_protocol_version"] == 2
    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, response.json()["id"])
        assert invite is not None
        assert invite.activation_protocol_version == 2


@pytest.mark.parametrize("expires_in_hours", [1, 168])
def test_explicit_expiry_bounds_are_persisted(
    api_world: ApiWorld,
    expires_in_hours: int,
) -> None:
    _login(api_world)

    response = _post(
        api_world,
        body={
            "roster_id": api_world.roster_id,
            "expires_in_hours": expires_in_hours,
        },
    )

    assert response.status_code == 201
    assert datetime.fromisoformat(response.json()["expires_at"]) == (
        FIXED_NOW + timedelta(hours=expires_in_hours)
    )


def test_admin_is_a_valid_direct_target(api_world: ApiWorld) -> None:
    _login(api_world)

    response = _post(
        api_world,
        body={
            "to_user_id": api_world.admin_id,
            "roster_id": api_world.roster_id,
        },
    )

    assert response.status_code == 201
    assert response.json()["to_user_id"] == api_world.admin_id


def test_agent_scope_maps_to_owner_and_writes_one_body_blind_audit(
    api_world: ApiWorld,
) -> None:
    token_id = _seed_token(api_world)

    response = _post(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
            "scenario": "lustrzana_a",
        },
        headers=_headers(),
    )

    assert response.status_code == 201
    assert response.json()["from_user_id"] == api_world.owner_id
    with api_world.sessions() as session:
        audits = session.execute(select(models.AgentAuditLog)).scalars().all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.user_id == api_world.owner_id
        assert audit.route == "/battles/invite"
        assert json.loads(audit.params_json) == {
            "method": "POST",
            "path_params": {},
            "query_params": {},
            "scope": battles.BATTLE_INVITE_SCOPE,
            "status": "authorized",
        }
        assert RAW_TOKEN not in audit.params_json
        assert str(api_world.roster_id) not in audit.params_json
        assert str(api_world.target_id) not in audit.params_json
        assert "lustrzana_a" not in audit.params_json
        token = session.get(models.AgentToken, token_id)
        assert token is not None
        assert token.last_used_at is not None


def test_wildcard_scope_keeps_existing_security_semantics(api_world: ApiWorld) -> None:
    raw_token = "battle-invite-wildcard"
    _seed_token(api_world, raw_token=raw_token, scopes={"*": True})

    response = _post(api_world, headers=_headers(raw_token))

    assert response.status_code == 201
    with api_world.sessions() as session:
        audit = session.execute(select(models.AgentAuditLog)).scalar_one()
        assert json.loads(audit.params_json)["scope"] == battles.BATTLE_INVITE_SCOPE


def test_missing_auth_is_401_and_missing_scope_is_403(api_world: ApiWorld) -> None:
    missing_auth = _post(api_world)
    raw_token = "battle-invite-wrong-scope"
    _seed_token(
        api_world,
        raw_token=raw_token,
        scopes={battles.BATTLE_CREATE_SCOPE: True},
    )
    missing_scope = _post(api_world, headers=_headers(raw_token))

    assert missing_auth.status_code == 401
    assert missing_scope.status_code == 403
    assert _invite_count(api_world) == 0
    with api_world.sessions() as session:
        assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


@pytest.mark.parametrize("roster_kind", ["missing", "foreign"])
def test_missing_and_foreign_rosters_share_bodyless_404_without_insert(
    api_world: ApiWorld,
    roster_kind: str,
) -> None:
    _login(api_world)
    roster_id = (
        api_world.foreign_roster_id
        if roster_kind == "foreign"
        else api_world.foreign_roster_id + 99_999
    )

    response = _post(api_world, body={"roster_id": roster_id})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert _invite_count(api_world) == 0


@pytest.mark.parametrize("target_kind", ["missing", "self", "agent"])
def test_missing_self_and_agent_targets_share_bodyless_404_without_insert(
    api_world: ApiWorld,
    target_kind: str,
) -> None:
    _login(api_world)
    target_id = {
        "missing": api_world.agent_target_id + 99_999,
        "self": api_world.owner_id,
        "agent": api_world.agent_target_id,
    }[target_kind]

    response = _post(
        api_world,
        body={"to_user_id": target_id, "roster_id": api_world.roster_id},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert _invite_count(api_world) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"to_user_id": 0, "roster_id": 1},
        {"to_user_id": True, "roster_id": 1},
        {"roster_id": 0},
        {"roster_id": True},
        {"roster_id": 1, "unexpected": "field"},
        {"roster_id": 1, "scenario": "   "},
        {"roster_id": 1, "scenario": "x" * 101},
        {"roster_id": 1, "scenario": 123},
        {"roster_id": 1, "expires_in_hours": 0},
        {"roster_id": 1, "expires_in_hours": 169},
        {"roster_id": 1, "expires_in_hours": True},
        {"roster_id": 1, "activation_protocol_version": 0},
        {"roster_id": 1, "activation_protocol_version": 4},
        {"roster_id": 1, "activation_protocol_version": True},
        {"roster_id": 1, "activation_protocol_version": "2"},
        {"roster_id": 1, "activation_protocol_version": 2.0},
        {"roster_id": 1, "activation_protocol_version": None},
    ],
)
def test_invalid_strict_request_returns_422_without_domain_write(
    api_world: ApiWorld,
    body: dict[str, object],
) -> None:
    _login(api_world)
    if type(body.get("roster_id")) is int and body.get("roster_id") == 1:
        body = {**body, "roster_id": api_world.roster_id}

    response = _post(api_world, body=body)

    assert response.status_code == 422
    assert _invite_count(api_world) == 0


def test_unknown_scenario_returns_constant_422_without_insert(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    response = _post(
        api_world,
        body={"roster_id": api_world.roster_id, "scenario": "not_registered"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown battle invite scenario"}
    assert _invite_count(api_world) == 0


def test_create_response_is_exact_and_excludes_internal_or_related_data(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    response = _post(api_world)

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == PUBLIC_FIELDS
    forbidden = {
        "accepted_by_user_id",
        "accepted_roster_id",
        "battle_id",
        "from_user",
        "to_user",
        "roster",
        "username",
        "password_hash",
    }
    assert forbidden.isdisjoint(payload)
    json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)


def test_identical_legal_posts_create_distinct_invites(api_world: ApiWorld) -> None:
    _login(api_world)
    body = {
        "to_user_id": api_world.target_id,
        "roster_id": api_world.roster_id,
    }

    first = _post(api_world, body=body)
    second = _post(api_world, body=body)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert _invite_count(api_world) == 2


def test_integrity_error_after_flush_rolls_back_and_next_request_succeeds(
    api_world: ApiWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(api_world)
    real_create = battle_invite_service.create_battle_invite

    def fail_after_flush(*args, **kwargs):
        real_create(*args, **kwargs)
        raise IntegrityError("controlled invite INSERT", {}, RuntimeError("race"))

    monkeypatch.setattr(
        battle_invite_service,
        "create_battle_invite",
        fail_after_flush,
    )
    failed = _post(api_world)

    assert failed.status_code == 409
    assert failed.json() == {"detail": "Battle invite could not be created"}
    assert _invite_count(api_world) == 0

    monkeypatch.setattr(
        battle_invite_service,
        "create_battle_invite",
        real_create,
    )
    succeeded = _post(api_world)

    assert succeeded.status_code == 201
    assert _invite_count(api_world) == 1


def test_service_is_transactionally_neutral_and_rollback_removes_flushed_invite(
    api_world: ApiWorld,
) -> None:
    with api_world.sessions() as session:
        invite = battle_invite_service.create_battle_invite(
            session,
            from_user_id=api_world.owner_id,
            to_user_id=api_world.target_id,
            roster_id=api_world.roster_id,
            scenario="LUSTRZANA_A",
            expires_in_hours=24,
            now=FIXED_NOW,
        )
        assert invite.id is not None
        assert invite.scenario == "lustrzana_a"
        session.rollback()

    assert _invite_count(api_world) == 0


def test_session_sql_statement_bound_is_constant_for_open_and_direct(
    api_world: ApiWorld,
) -> None:
    _login(api_world)

    open_count = _statement_count(
        api_world,
        body={"roster_id": api_world.roster_id},
    )
    direct_count = _statement_count(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
        },
    )
    v2_count = _statement_count(
        api_world,
        body={
            "roster_id": api_world.roster_id,
            "activation_protocol_version": 2,
        },
    )

    assert open_count == 3
    assert direct_count == 4
    assert v2_count == open_count


def test_session_sql_bound_does_not_scale_with_roster_units_or_invite_history(
    api_world: ApiWorld,
) -> None:
    _login(api_world)
    baseline_open = _statement_count(
        api_world,
        body={"roster_id": api_world.roster_id},
    )
    baseline_direct = _statement_count(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
        },
    )

    with api_world.sessions() as session:
        roster = session.get(models.Roster, api_world.roster_id)
        assert roster is not None
        unit = models.Unit(
            army_id=roster.army_id,
            name="Invite SQL unit",
            quality=4,
            defense=4,
            toughness=3,
        )
        session.add(unit)
        session.flush()
        session.add_all(
            [
                models.RosterUnit(
                    roster_id=api_world.roster_id,
                    unit_id=unit.id,
                    position=index,
                )
                for index in range(12)
            ]
        )
        session.add_all(
            [
                models.BattleInvite(
                    from_user_id=api_world.owner_id,
                    roster_id=api_world.roster_id,
                    scenario="lustrzana_a",
                    status=models.BATTLE_INVITE_STATUS_PENDING,
                    expires_at=FIXED_NOW + timedelta(hours=24),
                )
                for _ in range(20)
            ]
        )
        session.commit()

    populated_open = _statement_count(
        api_world,
        body={"roster_id": api_world.roster_id},
    )
    populated_direct = _statement_count(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
        },
    )

    assert (baseline_open, populated_open) == (3, 3)
    assert (baseline_direct, populated_direct) == (4, 4)


def test_agent_auth_and_audit_have_separate_constant_statement_bound(
    api_world: ApiWorld,
) -> None:
    raw_token = "battle-invite-sql"
    _seed_token(api_world, raw_token=raw_token)

    open_count = _statement_count(
        api_world,
        body={"roster_id": api_world.roster_id},
        headers=_headers(raw_token),
    )
    direct_count = _statement_count(
        api_world,
        body={
            "to_user_id": api_world.target_id,
            "roster_id": api_world.roster_id,
        },
        headers=_headers(raw_token),
    )

    assert open_count == 6
    assert direct_count == 7
