from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from szop_client import (
    BattleInviteMetadata,
    BattleMetadata,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
)


def _json_response(payload: Any, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload).encode("utf-8"),
    )


def _invite_payload(*, to_user_id: int | None = 12) -> dict[str, Any]:
    return {
        "id": 31,
        "from_user_id": 10,
        "to_user_id": to_user_id,
        "roster_id": 21,
        "scenario": "lustrzana_a",
        "status": "pending",
        "expires_at": "2026-07-20T10:00:00",
        "created_at": "2026-07-19T10:00:00",
        "updated_at": "2026-07-19T10:00:00",
    }


def _battle_payload() -> dict[str, Any]:
    return {
        "battle_id": 41,
        "p1_user_id": 10,
        "p2_user_id": 12,
        "p1_roster_id": 21,
        "p2_roster_id": 22,
        "winner_user_id": None,
        "current_round": 1,
        "rng_seed": 777,
        "status": "active",
        "latest_sequence": 2,
        "adaptation_report": None,
    }


@pytest.mark.parametrize(
    ("to_user_id", "scenario"),
    [(12, "  LuStRzAnA_A  "), (None, "lustrzana_a")],
    ids=["direct", "open"],
)
def test_create_battle_invite_posts_exact_contract_once_and_decodes_metadata(
    to_user_id: int | None,
    scenario: str,
) -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_invite_payload(to_user_id=to_user_id), status_code=201)

    result = HttpClient(
        "https://szop.example/api/",
        token="invite-token",
        timeout=7.5,
        transport=transport,
    ).create_battle_invite(
        roster_id=21,
        to_user_id=to_user_id,
        scenario=scenario,
        expires_in_hours=48,
    )

    assert result == BattleInviteMetadata(
        invite_id=31,
        from_user_id=10,
        to_user_id=to_user_id,
        roster_id=21,
        scenario="lustrzana_a",
        status="pending",
        expires_at=datetime(2026, 7, 20, 10, 0),
        created_at=datetime(2026, 7, 19, 10, 0),
        updated_at=datetime(2026, 7, 19, 10, 0),
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles/invite"
    assert request.headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer invite-token",
    }
    assert json.loads(request.body or b"") == {
        "to_user_id": to_user_id,
        "roster_id": 21,
        "scenario": scenario,
        "expires_in_hours": 48,
    }
    assert request.timeout == 7.5


def test_accept_battle_invite_posts_once_and_reuses_battle_metadata_decoder() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_battle_payload())

    result = HttpClient(
        "https://szop.example/api",
        token="accept-token",
        timeout=6.0,
        transport=transport,
    ).accept_battle_invite(31, roster_id=22)

    assert result == BattleMetadata(
        battle_id=41,
        p1_user_id=10,
        p2_user_id=12,
        p1_roster_id=21,
        p2_roster_id=22,
        winner_user_id=None,
        current_round=1,
        rng_seed=777,
        status="active",
        latest_sequence=2,
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles/invite/31/accept"
    assert request.headers["Authorization"] == "Bearer accept-token"
    assert json.loads(request.body or b"") == {"roster_id": 22}
    assert request.timeout == 6.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"roster_id": True},
        {"roster_id": 0},
        {"roster_id": 1, "to_user_id": True},
        {"roster_id": 1, "to_user_id": 0},
        {"roster_id": 1, "scenario": 7},
        {"roster_id": 1, "scenario": "   "},
        {"roster_id": 1, "scenario": "x" * 101},
        {"roster_id": 1, "expires_in_hours": True},
        {"roster_id": 1, "expires_in_hours": 0},
        {"roster_id": 1, "expires_in_hours": 169},
    ],
)
def test_create_battle_invite_rejects_invalid_input_before_transport(
    kwargs: dict[str, Any],
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).create_battle_invite(
            **kwargs
        )


@pytest.mark.parametrize(
    ("invite_id", "roster_id"),
    [(True, 1), (0, 1), (1, True), (1, 0)],
)
def test_accept_battle_invite_rejects_invalid_ids_before_transport(
    invite_id: Any,
    roster_id: Any,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).accept_battle_invite(
            invite_id,
            roster_id=roster_id,
        )


def _without(payload: dict[str, Any], key: str) -> dict[str, Any]:
    mutated = dict(payload)
    mutated.pop(key)
    return mutated


@pytest.mark.parametrize(
    "payload",
    [
        [],
        _without(_invite_payload(), "id"),
        {**_invite_payload(), "id": True},
        {**_invite_payload(), "id": 0},
        {**_invite_payload(), "status": "accepted"},
        {**_invite_payload(), "to_user_id": True},
        {**_invite_payload(), "to_user_id": 0},
        {**_invite_payload(), "scenario": ""},
        {**_invite_payload(), "expires_at": "not-a-timestamp"},
        {**_invite_payload(), "created_at": "2026-07-19T10:00:00+00:00"},
        {**_invite_payload(), "updated_at": 123},
        {**_invite_payload(), "battle_id": 41},
    ],
)
def test_create_battle_invite_rejects_malformed_payload(payload: Any) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload, status_code=201)

    with pytest.raises(
        HttpClientError,
        match="POST create battle invite returned malformed payload",
    ):
        HttpClient(
            "http://localhost",
            transport=transport,
        ).create_battle_invite(roster_id=21)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        _without(_battle_payload(), "battle_id"),
        {**_battle_payload(), "p2_roster_id": True},
    ],
)
def test_accept_battle_invite_rejects_malformed_battle_public(payload: Any) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="POST accept battle invite returned malformed payload",
    ):
        HttpClient(
            "http://localhost",
            transport=transport,
        ).accept_battle_invite(31, roster_id=22)


@pytest.mark.parametrize("status_code", [401, 403, 404, 409, 422])
@pytest.mark.parametrize("operation", ["create", "accept"])
def test_battle_invite_methods_preserve_safe_http_error_status(
    status_code: int,
    operation: str,
) -> None:
    raw_token = "invite-secret-token"

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(
            {"detail": f"Bearer {raw_token}"},
            status_code=status_code,
        )

    client = HttpClient("http://localhost", token=raw_token, transport=transport)
    with pytest.raises(HttpClientError) as exc_info:
        if operation == "create":
            client.create_battle_invite(roster_id=21)
        else:
            client.accept_battle_invite(31, roster_id=22)

    assert exc_info.value.status_code == status_code
    assert raw_token not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)


def test_public_invite_type_rejects_invalid_values() -> None:
    baseline = {
        "invite_id": 31,
        "from_user_id": 10,
        "to_user_id": None,
        "roster_id": 21,
        "scenario": "lustrzana_a",
        "status": "pending",
        "expires_at": datetime(2026, 7, 20, 10, 0),
        "created_at": datetime(2026, 7, 19, 10, 0),
        "updated_at": datetime(2026, 7, 19, 10, 0),
    }
    invalid = (
        ("invite_id", True),
        ("from_user_id", 0),
        ("to_user_id", True),
        ("roster_id", 0),
        ("scenario", ""),
        ("status", "accepted"),
        ("expires_at", datetime.fromisoformat("2026-07-20T10:00:00+00:00")),
    )

    for field, value in invalid:
        with pytest.raises(ValueError):
            BattleInviteMetadata(**{**baseline, field: value})


def test_public_invite_and_http_imports_stay_lazy_for_db_orm_and_costs() -> None:
    code = (
        "import sys; import szop_client; "
        "szop_client.BattleInviteMetadata; szop_client.HttpClient; "
        "prefixes=('app.models','app.db','app.services.costs'); "
        "loaded=sorted(name for name in sys.modules if any("
        "name == prefix or name.startswith(prefix + '.') for prefix in prefixes)); "
        "print(','.join(loaded)); raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


class _TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        parsed = urlsplit(request.url)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        response = self._client.request(
            request.method,
            target,
            headers=request.headers,
            content=request.body,
        )
        return HttpResponse(status_code=response.status_code, body=response.content)


@dataclass(frozen=True, slots=True)
class _RealInviteWorld:
    sessions: sessionmaker[Session]
    transport: _TestClientTransport
    inviter_client: HttpClient
    target_client: HttpClient
    other_client: HttpClient
    wrong_scope_client: HttpClient
    inviter_id: int
    target_id: int
    other_id: int
    inviter_roster_id: int
    target_roster_id: int
    target_second_roster_id: int
    other_roster_id: int
    raw_tokens: tuple[str, ...]


def _seed_real_invite_world(sessions: sessionmaker[Session]) -> dict[str, Any]:
    raw_tokens = (
        "real-invite-owner-token",
        "real-accept-target-token",
        "real-accept-other-token",
        "real-wrong-scope-token",
    )
    with sessions() as session:
        inviter = models.User(username="client-inviter", password_hash="x")
        target = models.User(username="client-target", password_hash="x")
        other = models.User(username="client-other", password_hash="x")
        ruleset = models.RuleSet(name="Client invite rules")
        armory = models.Armory(name="Client invite armory", owner=inviter)
        army = models.Army(
            name="Client invite army",
            owner=inviter,
            ruleset=ruleset,
            armory=armory,
        )
        weapon = models.Weapon(
            name="Client invite blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
            armory=armory,
        )
        unit = models.Unit(
            name="Client invite infantry",
            quality=4,
            defense=5,
            toughness=3,
            typical_models=2,
            army=army,
            default_weapon=weapon,
        )
        session.add_all(
            [inviter, target, other, ruleset, armory, army, weapon, unit]
        )
        session.flush()
        session.add(
            models.UnitWeapon(
                unit=unit,
                weapon=weapon,
                is_default=True,
                default_count=1,
                is_primary=True,
            )
        )

        roster_specs = (
            ("Client inviter roster", inviter),
            ("Client target roster", target),
            ("Client target second roster", target),
            ("Client other roster", other),
        )
        rosters: list[models.Roster] = []
        for position, (name, owner) in enumerate(roster_specs):
            roster = models.Roster(name=name, owner=owner, army=army)
            session.add(roster)
            session.flush()
            session.add(
                models.RosterUnit(
                    roster=roster,
                    unit=unit,
                    count=1,
                    position=position,
                )
            )
            rosters.append(roster)

        token_specs = (
            (
                "client-invite-agent",
                inviter,
                raw_tokens[0],
                {battles.BATTLE_INVITE_SCOPE: True},
            ),
            (
                "client-target-agent",
                target,
                raw_tokens[1],
                {battles.BATTLE_ACCEPT_SCOPE: True},
            ),
            (
                "client-other-agent",
                other,
                raw_tokens[2],
                {battles.BATTLE_ACCEPT_SCOPE: True},
            ),
            (
                "client-wrong-scope-agent",
                target,
                raw_tokens[3],
                {battles.BATTLE_INVITE_SCOPE: True},
            ),
        )
        for username, owner, raw_token, scopes in token_specs:
            agent = models.User(
                username=username,
                password_hash="x",
                role=models.USER_ROLE_AGENT,
            )
            session.add(
                models.AgentToken(
                    agent_user=agent,
                    owner_user=owner,
                    token_hash=hash_agent_token(raw_token),
                    scope_json=json.dumps(scopes),
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    + timedelta(days=1),
                )
            )
        session.commit()
        return {
            "inviter_id": inviter.id,
            "target_id": target.id,
            "other_id": other.id,
            "inviter_roster_id": rosters[0].id,
            "target_roster_id": rosters[1].id,
            "target_second_roster_id": rosters[2].id,
            "other_roster_id": rosters[3].id,
            "raw_tokens": raw_tokens,
        }


@pytest.fixture()
def real_invite_world() -> Any:
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
    seeded = _seed_real_invite_world(sessions)
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="http-client-invite-test")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as api_client:
            transport = _TestClientTransport(api_client)

            def http(raw_token: str) -> HttpClient:
                return HttpClient(
                    "http://testserver",
                    token=raw_token,
                    transport=transport,
                )

            yield _RealInviteWorld(
                sessions=sessions,
                transport=transport,
                inviter_client=http(seeded["raw_tokens"][0]),
                target_client=http(seeded["raw_tokens"][1]),
                other_client=http(seeded["raw_tokens"][2]),
                wrong_scope_client=http(seeded["raw_tokens"][3]),
                **seeded,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _domain_counts(world: _RealInviteWorld) -> tuple[int, int, int]:
    with world.sessions() as session:
        return tuple(
            int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (
                models.Battle,
                models.BattleEvent,
                models.BattleCheckpoint,
            )
        )


def test_real_transport_direct_open_idempotency_errors_and_body_blind_audit(
    real_invite_world: _RealInviteWorld,
) -> None:
    world = real_invite_world
    before = len(world.transport.requests)
    direct = world.inviter_client.create_battle_invite(
        roster_id=world.inviter_roster_id,
        to_user_id=world.target_id,
        scenario="  LuStRzAnA_A  ",
    )
    assert len(world.transport.requests) == before + 1
    assert direct.from_user_id == world.inviter_id
    assert direct.to_user_id == world.target_id
    assert direct.scenario == "lustrzana_a"
    assert direct.status == "pending"

    with pytest.raises(HttpClientError) as foreign_acceptor:
        world.other_client.accept_battle_invite(
            direct.invite_id,
            roster_id=world.other_roster_id,
        )
    assert foreign_acceptor.value.status_code == 404

    with pytest.raises(HttpClientError) as foreign_roster:
        world.target_client.accept_battle_invite(
            direct.invite_id,
            roster_id=world.other_roster_id,
        )
    assert foreign_roster.value.status_code == 404

    with pytest.raises(HttpClientError) as missing_scope:
        world.wrong_scope_client.accept_battle_invite(
            direct.invite_id,
            roster_id=world.target_roster_id,
        )
    assert missing_scope.value.status_code == 403

    accepted = world.target_client.accept_battle_invite(
        direct.invite_id,
        roster_id=world.target_roster_id,
    )
    assert accepted.p1_user_id == world.inviter_id
    assert accepted.p2_user_id == world.target_id
    assert accepted.p1_roster_id == world.inviter_roster_id
    assert accepted.p2_roster_id == world.target_roster_id
    assert accepted.status == "active"
    after_first_accept = _domain_counts(world)
    assert after_first_accept[0] == 1
    assert after_first_accept[1] > 0
    assert after_first_accept[2] == 1

    requests_before_retry = len(world.transport.requests)
    retried = world.target_client.accept_battle_invite(
        direct.invite_id,
        roster_id=world.target_roster_id,
    )
    assert len(world.transport.requests) == requests_before_retry + 1
    assert retried.battle_id == accepted.battle_id
    assert _domain_counts(world) == after_first_accept

    with pytest.raises(HttpClientError) as terminal_conflict:
        world.target_client.accept_battle_invite(
            direct.invite_id,
            roster_id=world.target_second_roster_id,
        )
    assert terminal_conflict.value.status_code == 409
    assert _domain_counts(world) == after_first_accept

    open_invite = world.inviter_client.create_battle_invite(
        roster_id=world.inviter_roster_id,
    )
    assert open_invite.to_user_id is None
    open_battle = world.other_client.accept_battle_invite(
        open_invite.invite_id,
        roster_id=world.other_roster_id,
    )
    assert open_battle.battle_id != accepted.battle_id
    assert open_battle.p1_user_id == world.inviter_id
    assert open_battle.p2_user_id == world.other_id
    assert open_battle.p2_roster_id == world.other_roster_id
    final_counts = _domain_counts(world)
    assert final_counts[0] == 2
    assert final_counts[1] > after_first_accept[1]
    assert final_counts[2] == 2

    with world.sessions() as session:
        audits = session.scalars(
            select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
        ).all()
        assert audits
        for audit in audits:
            params = json.loads(audit.params_json)
            assert set(params) == {
                "method",
                "path_params",
                "query_params",
                "scope",
                "status",
            }
            assert params["method"] == "POST"
            assert set(params["path_params"]) <= {"invite_id"}
            assert params["query_params"] == {}
            assert params["scope"] in {
                battles.BATTLE_INVITE_SCOPE,
                battles.BATTLE_ACCEPT_SCOPE,
            }
            assert params["status"] == "authorized"
            for raw_token in world.raw_tokens:
                assert raw_token not in audit.params_json
