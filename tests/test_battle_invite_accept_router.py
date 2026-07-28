from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.main import app as main_app
from app.routers import battles
from app.security import hash_agent_token
from app.services import battle_creation
from app.services import battle_invites as battle_invite_service
from app.services.agents.maps import build_map
from app.services.engine.persistence import load_events, load_latest_checkpoint


FIXED_NOW = datetime(2026, 7, 19, 12, 0, 0)
FIXED_SEED = 41
ACCEPT_CONFLICT = {"detail": "Battle invite could not be accepted"}


@dataclass(frozen=True)
class WorldIds:
    inviter_id: int
    target_id: int
    admin_id: int
    other_id: int
    agent_user_id: int
    inviter_roster_id: int
    target_roster_id: int
    target_second_roster_id: int
    admin_roster_id: int
    other_roster_id: int
    agent_roster_id: int


@dataclass(frozen=True)
class ApiWorld:
    client: TestClient
    sessions: sessionmaker[Session]
    engine: Any
    ids: WorldIds


def _enable_sqlite_foreign_keys(engine: Any) -> None:
    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _seed_world(sessions: sessionmaker[Session]) -> WorldIds:
    with sessions() as session:
        inviter = models.User(username="accept-inviter", password_hash="x")
        target = models.User(username="accept-target", password_hash="x")
        admin = models.User(
            username="accept-admin",
            password_hash="x",
            is_admin=True,
            role=models.USER_ROLE_ADMIN,
        )
        other = models.User(username="accept-other", password_hash="x")
        agent_user = models.User(
            username="accept-session-agent",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name="Accept router rules")
        armory = models.Armory(name="Accept router armory")
        army = models.Army(
            name="Accept router army",
            ruleset=ruleset,
            armory=armory,
        )
        weapon = models.Weapon(
            name="Accept blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
            armory=armory,
        )
        unit = models.Unit(
            name="Accept infantry",
            quality=4,
            defense=5,
            toughness=3,
            typical_models=2,
            army=army,
            default_weapon=weapon,
        )
        session.add_all(
            [
                inviter,
                target,
                admin,
                other,
                agent_user,
                ruleset,
                armory,
                army,
                weapon,
                unit,
            ]
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
            ("Inviter roster", inviter),
            ("Target roster", target),
            ("Target second roster", target),
            ("Admin roster", admin),
            ("Other roster", other),
            ("Agent roster", agent_user),
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
        session.commit()
        return WorldIds(
            inviter_id=inviter.id,
            target_id=target.id,
            admin_id=admin.id,
            other_id=other.id,
            agent_user_id=agent_user.id,
            inviter_roster_id=rosters[0].id,
            target_roster_id=rosters[1].id,
            target_second_roster_id=rosters[2].id,
            admin_roster_id=rosters[3].id,
            other_roster_id=rosters[4].id,
            agent_roster_id=rosters[5].id,
        )


def _test_app(sessions: sessionmaker[Session], *, with_session_route: bool) -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="battle-accept-test")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    if with_session_route:
        @test_app.post("/_test/session/{user_id}")
        def set_session(user_id: int, request: Request) -> dict[str, int]:
            request.session["user_id"] = user_id
            return {"user_id": user_id}

    return test_app


@pytest.fixture()
def api_world(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    ids = _seed_world(sessions)
    test_app = _test_app(sessions, with_session_route=True)
    monkeypatch.setattr(battle_invite_service, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(battle_invite_service, "_new_rng_seed", lambda: FIXED_SEED)
    monkeypatch.setattr(models, "utcnow", lambda: FIXED_NOW)
    try:
        with TestClient(test_app) as client:
            yield ApiWorld(client=client, sessions=sessions, engine=engine, ids=ids)
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _login(world: ApiWorld, user_id: int) -> None:
    response = world.client.post(f"/_test/session/{user_id}")
    assert response.status_code == 200


def _invite(
    world: ApiWorld,
    *,
    to_user_id: int | None,
    status: str = models.BATTLE_INVITE_STATUS_PENDING,
    expires_at: datetime | None = None,
    scenario: str = "lustrzana_a",
    accepted_by_user_id: int | None = None,
    accepted_roster_id: int | None = None,
    battle_id: int | None = None,
) -> int:
    with world.sessions() as session:
        invite = models.BattleInvite(
            from_user_id=world.ids.inviter_id,
            to_user_id=to_user_id,
            roster_id=world.ids.inviter_roster_id,
            scenario=scenario,
            status=status,
            expires_at=expires_at or FIXED_NOW + timedelta(hours=24),
            accepted_by_user_id=accepted_by_user_id,
            accepted_roster_id=accepted_roster_id,
            battle_id=battle_id,
        )
        session.add(invite)
        session.commit()
        return invite.id


def _accept(
    world: ApiWorld,
    invite_id: int,
    roster_id: int,
    *,
    headers: dict[str, str] | None = None,
):
    return world.client.post(
        f"/battles/invite/{invite_id}/accept",
        json={"roster_id": roster_id},
        headers=headers,
    )


def _seed_token(
    sessions: sessionmaker[Session],
    *,
    owner_user_id: int,
    raw_token: str,
    scopes: dict[str, bool],
) -> int:
    with sessions() as session:
        agent = models.User(
            username=f"agent-{raw_token}",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        token = models.AgentToken(
            agent_user=agent,
            owner_user_id=owner_user_id,
            token_hash=hash_agent_token(raw_token),
            scope_json=json.dumps(scopes),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        session.add_all([agent, token])
        session.commit()
        return token.id


def _bearer(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def _domain_counts(world: ApiWorld) -> tuple[int, int, int]:
    with world.sessions() as session:
        return tuple(
            int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (
                models.Battle,
                models.BattleEvent,
                models.BattleCheckpoint,
            )
        )


def test_route_table_has_exact_accept_post_without_dynamic_collision() -> None:
    routes = [
        route
        for route in main_app.routes
        if getattr(route, "path", None) == "/battles/invite/{invite_id}/accept"
    ]
    assert len(routes) == 1
    assert getattr(routes[0], "methods", set()) == {"POST"}
    assert routes[0].endpoint is battles.accept_battle_invite


@pytest.mark.parametrize(
    ("target_kind", "to_user_attr", "roster_attr"),
    [
        ("direct-user", "target_id", "target_roster_id"),
        ("direct-admin", "admin_id", "admin_roster_id"),
        ("open", None, "target_roster_id"),
    ],
)
def test_direct_admin_and_open_success_persist_complete_battle_graph(
    api_world: ApiWorld,
    target_kind: str,
    to_user_attr: str | None,
    roster_attr: str,
) -> None:
    del target_kind
    acceptor_id = (
        api_world.ids.target_id
        if to_user_attr is None
        else getattr(api_world.ids, to_user_attr)
    )
    roster_id = getattr(api_world.ids, roster_attr)
    invite_id = _invite(
        api_world,
        to_user_id=None if to_user_attr is None else acceptor_id,
    )
    _login(api_world, acceptor_id)

    response = _accept(api_world, invite_id, roster_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["p1_user_id"] == api_world.ids.inviter_id
    assert payload["p2_user_id"] == acceptor_id
    assert payload["p1_roster_id"] == api_world.ids.inviter_roster_id
    assert payload["p2_roster_id"] == roster_id
    assert payload["rng_seed"] == FIXED_SEED
    assert payload["status"] == "active"
    assert payload["current_round"] == 1
    assert payload["adaptation_report"] is not None
    assert "activation_protocol_version" not in payload

    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, invite_id)
        battle = session.get(models.Battle, payload["battle_id"])
        assert invite is not None
        assert battle is not None
        assert battle.activation_protocol_version == 1
        assert invite.status == models.BATTLE_INVITE_STATUS_ACCEPTED
        assert invite.accepted_by_user_id == acceptor_id
        assert invite.accepted_roster_id == roster_id
        assert invite.battle_id == battle.id
        events = load_events(session, battle.id)
        checkpoint = load_latest_checkpoint(session, battle.id)
        fixture = build_map("lustrzana_a", FIXED_SEED)
        assert events
        assert [item.sequence for item in events] == list(
            range(1, len(events) + 1)
        )
        assert checkpoint is not None
        assert checkpoint.sequence_at == events[-1].sequence == payload["latest_sequence"]
        assert checkpoint.state.round == battle.current_round == 1
        assert checkpoint.state.active_player == FIXED_SEED & 1
        assert checkpoint.state.initiative_player is None
        assert checkpoint.state.terrain == fixture.terrain
        assert checkpoint.state.objectives == fixture.objectives
        assert checkpoint.dice.seed == FIXED_SEED
        checkpoint_count = session.scalar(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == battle.id)
        )
        assert checkpoint_count == 1


def test_idempotent_retry_returns_same_battle_without_domain_writes(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    _login(api_world, api_world.ids.target_id)

    first = _accept(api_world, invite_id, api_world.ids.target_roster_id)
    before_retry = _domain_counts(api_world)
    second = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert first.status_code == second.status_code == 200
    assert first.json()["battle_id"] == second.json()["battle_id"]
    assert first.json()["adaptation_report"] is not None
    assert second.json()["adaptation_report"] is None
    assert _domain_counts(api_world) == before_retry


def test_accept_service_is_transactionally_neutral_and_caller_rollback_is_total(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    with api_world.sessions() as session:
        result = battle_invite_service.stage_battle_invite_acceptance(
            session,
            invite_id=invite_id,
            acceptor_user_id=api_world.ids.target_id,
            accepted_roster_id=api_world.ids.target_roster_id,
            now=FIXED_NOW,
            rng_seed_factory=lambda: FIXED_SEED,
        )
        assert isinstance(result, battle_invite_service.BattleInviteAccepted)
        assert result.created is True
        assert result.battle.id is not None
        session.rollback()

    assert _domain_counts(api_world) == (0, 0, 0)
    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, invite_id)
        assert invite is not None
        assert invite.status == models.BATTLE_INVITE_STATUS_PENDING
        assert invite.battle_id is None


def test_bearer_scope_and_wildcard_succeed_with_one_body_blind_audit(
    api_world: ApiWorld,
) -> None:
    for raw_token, scopes in (
        ("accept-exact", {battles.BATTLE_ACCEPT_SCOPE: True}),
        ("accept-wildcard", {"*": True}),
    ):
        invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
        _seed_token(
            api_world.sessions,
            owner_user_id=api_world.ids.target_id,
            raw_token=raw_token,
            scopes=scopes,
        )
        response = _accept(
            api_world,
            invite_id,
            api_world.ids.target_roster_id,
            headers=_bearer(raw_token),
        )
        assert response.status_code == 200, response.text

    with api_world.sessions() as session:
        audits = session.scalars(
            select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
        ).all()
        assert len(audits) == 2
        for audit in audits:
            payload = json.loads(audit.params_json)
            assert audit.route.startswith("/battles/invite/")
            assert payload == {
                "method": "POST",
                "path_params": {"invite_id": payload["path_params"]["invite_id"]},
                "query_params": {},
                "scope": battles.BATTLE_ACCEPT_SCOPE,
                "status": "authorized",
            }
            assert "roster_id" not in audit.params_json
            assert "scenario" not in audit.params_json
            assert "Authorization" not in audit.params_json
            assert "accept-exact" not in audit.params_json
            assert "accept-wildcard" not in audit.params_json


def test_missing_auth_is_401_and_valid_token_without_accept_scope_is_403(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    unauthenticated = _accept(
        api_world,
        invite_id,
        api_world.ids.target_roster_id,
    )
    _seed_token(
        api_world.sessions,
        owner_user_id=api_world.ids.target_id,
        raw_token="accept-wrong-scope",
        scopes={battles.BATTLE_INVITE_SCOPE: True},
    )
    forbidden = _accept(
        api_world,
        invite_id,
        api_world.ids.target_roster_id,
        headers=_bearer("accept-wrong-scope"),
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert _domain_counts(api_world) == (0, 0, 0)
    with api_world.sessions() as session:
        assert session.scalar(select(models.AgentAuditLog.id)) is None


def test_bearer_owner_with_agent_role_is_also_hidden_by_no_oracle(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=None)
    _seed_token(
        api_world.sessions,
        owner_user_id=api_world.ids.agent_user_id,
        raw_token="accept-agent-owner",
        scopes={battles.BATTLE_ACCEPT_SCOPE: True},
    )

    response = _accept(
        api_world,
        invite_id,
        api_world.ids.agent_roster_id,
        headers=_bearer("accept-agent-owner"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert _domain_counts(api_world) == (0, 0, 0)


@pytest.mark.parametrize(
    "case",
    [
        "missing-invite",
        "author",
        "wrong-direct-target",
        "session-agent",
        "missing-roster",
        "foreign-roster",
    ],
)
def test_no_oracle_cases_share_bodyless_404(api_world: ApiWorld, case: str) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    user_id = api_world.ids.target_id
    roster_id = api_world.ids.target_roster_id
    if case == "missing-invite":
        invite_id += 99_999
    elif case == "author":
        user_id = api_world.ids.inviter_id
        roster_id = api_world.ids.inviter_roster_id
    elif case == "wrong-direct-target":
        user_id = api_world.ids.other_id
        roster_id = api_world.ids.other_roster_id
    elif case == "session-agent":
        user_id = api_world.ids.agent_user_id
        roster_id = api_world.ids.agent_roster_id
    elif case == "missing-roster":
        roster_id += 99_999
    elif case == "foreign-roster":
        roster_id = api_world.ids.other_roster_id
    _login(api_world, user_id)

    response = _accept(api_world, invite_id, roster_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert _domain_counts(api_world) == (0, 0, 0)


def test_open_invite_loser_sees_bodyless_404_after_first_acceptor_wins(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=None)
    _login(api_world, api_world.ids.target_id)
    winner = _accept(api_world, invite_id, api_world.ids.target_roster_id)
    _login(api_world, api_world.ids.other_id)
    loser = _accept(api_world, invite_id, api_world.ids.other_roster_id)

    assert winner.status_code == 200
    assert loser.status_code == 404
    assert loser.json() == {"detail": "Not Found"}
    assert _domain_counts(api_world)[0] == 1


def test_expired_pending_is_committed_with_empty_linkage_and_no_battle(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(
        api_world,
        to_user_id=api_world.ids.target_id,
        expires_at=FIXED_NOW,
    )
    _login(api_world, api_world.ids.target_id)

    response = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert response.status_code == 409
    assert response.json() == ACCEPT_CONFLICT
    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, invite_id)
        assert invite is not None
        assert invite.status == models.BATTLE_INVITE_STATUS_EXPIRED
        assert (
            invite.accepted_by_user_id,
            invite.accepted_roster_id,
            invite.battle_id,
        ) == (None, None, None)
    assert _domain_counts(api_world) == (0, 0, 0)


@pytest.mark.parametrize(
    "invite_status",
    [models.BATTLE_INVITE_STATUS_DECLINED, models.BATTLE_INVITE_STATUS_EXPIRED],
)
def test_declined_and_expired_invites_return_constant_409(
    api_world: ApiWorld,
    invite_status: str,
) -> None:
    invite_id = _invite(
        api_world,
        to_user_id=api_world.ids.target_id,
        status=invite_status,
    )
    _login(api_world, api_world.ids.target_id)
    response = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert response.status_code == 409
    assert response.json() == ACCEPT_CONFLICT
    assert _domain_counts(api_world) == (0, 0, 0)


def test_same_acceptor_retry_with_different_roster_is_conflict(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    _login(api_world, api_world.ids.target_id)
    first = _accept(api_world, invite_id, api_world.ids.target_roster_id)
    before = _domain_counts(api_world)
    retry = _accept(api_world, invite_id, api_world.ids.target_second_roster_id)

    assert first.status_code == 200
    assert retry.status_code == 409
    assert retry.json() == ACCEPT_CONFLICT
    assert _domain_counts(api_world) == before


@pytest.mark.parametrize("broken", ["source-owner", "scenario"])
def test_broken_source_roster_or_scenario_returns_constant_409(
    api_world: ApiWorld,
    broken: str,
) -> None:
    invite_id = _invite(
        api_world,
        to_user_id=api_world.ids.target_id,
        scenario="unavailable" if broken == "scenario" else "lustrzana_a",
    )
    if broken == "source-owner":
        with api_world.sessions() as session:
            session.execute(
                update(models.Roster)
                .where(models.Roster.id == api_world.ids.inviter_roster_id)
                .values(owner_id=api_world.ids.other_id)
            )
            session.commit()
    _login(api_world, api_world.ids.target_id)

    response = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert response.status_code == 409
    assert response.json() == ACCEPT_CONFLICT
    assert _domain_counts(api_world) == (0, 0, 0)


def test_inconsistent_accepted_linkage_returns_constant_409(
    api_world: ApiWorld,
) -> None:
    with api_world.sessions() as session:
        mismatched = models.Battle(
            p1_user_id=api_world.ids.inviter_id,
            p2_user_id=api_world.ids.target_id,
            p1_roster_id=api_world.ids.inviter_roster_id,
            p2_roster_id=api_world.ids.target_second_roster_id,
            rng_seed=7,
            status="active",
        )
        session.add(mismatched)
        session.commit()
        battle_id = mismatched.id
    invite_id = _invite(
        api_world,
        to_user_id=api_world.ids.target_id,
        status=models.BATTLE_INVITE_STATUS_ACCEPTED,
        accepted_by_user_id=api_world.ids.target_id,
        accepted_roster_id=api_world.ids.target_roster_id,
        battle_id=battle_id,
    )
    _login(api_world, api_world.ids.target_id)

    response = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert response.status_code == 409
    assert response.json() == ACCEPT_CONFLICT
    assert _domain_counts(api_world) == (1, 0, 0)


def test_missing_linked_battle_returns_constant_409(api_world: ApiWorld) -> None:
    missing_battle_id = 999_999
    with api_world.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            models.BattleInvite.__table__.insert(),
            {
                "from_user_id": api_world.ids.inviter_id,
                "to_user_id": api_world.ids.target_id,
                "roster_id": api_world.ids.inviter_roster_id,
                "scenario": "lustrzana_a",
                "status": models.BATTLE_INVITE_STATUS_ACCEPTED,
                "expires_at": FIXED_NOW + timedelta(hours=1),
                "accepted_by_user_id": api_world.ids.target_id,
                "accepted_roster_id": api_world.ids.target_roster_id,
                "battle_id": missing_battle_id,
                "created_at": FIXED_NOW,
                "updated_at": FIXED_NOW,
            },
        )
        connection.commit()
        invite_id = connection.scalar(select(func.max(models.BattleInvite.id)))
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    _login(api_world, api_world.ids.target_id)

    response = _accept(api_world, int(invite_id), api_world.ids.target_roster_id)

    assert response.status_code == 409
    assert response.json() == ACCEPT_CONFLICT


def test_strict_accept_body_rejects_bool_extra_and_status_linkage_fields(
    api_world: ApiWorld,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    _login(api_world, api_world.ids.target_id)
    invalid_bodies = (
        {"roster_id": True},
        {"roster_id": 0},
        {"roster_id": api_world.ids.target_roster_id, "status": "accepted"},
        {"roster_id": api_world.ids.target_roster_id, "battle_id": 1},
        {"roster_id": api_world.ids.target_roster_id, "scenario": "lustrzana_a"},
        {"roster_id": api_world.ids.target_roster_id, "seed": 7},
        {"roster_id": api_world.ids.target_roster_id, "initiative": 0},
        {"roster_id": api_world.ids.target_roster_id, "expires_at": "now"},
    )

    for body in invalid_bodies:
        response = api_world.client.post(
            f"/battles/invite/{invite_id}/accept",
            json=body,
        )
        assert response.status_code == 422
    assert _domain_counts(api_world) == (0, 0, 0)


def test_integrity_error_after_partial_stage_rolls_back_then_next_request_works(
    api_world: ApiWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    _login(api_world, api_world.ids.target_id)
    real_save_checkpoint = battle_creation.save_checkpoint

    def fail_after_checkpoint(*args, **kwargs):
        real_save_checkpoint(*args, **kwargs)
        raise IntegrityError("controlled checkpoint race", {}, RuntimeError("race"))

    monkeypatch.setattr(
        battle_creation,
        "save_checkpoint",
        fail_after_checkpoint,
    )
    failed = _accept(api_world, invite_id, api_world.ids.target_roster_id)

    assert failed.status_code == 409
    assert failed.json() == ACCEPT_CONFLICT
    assert _domain_counts(api_world) == (0, 0, 0)
    with api_world.sessions() as session:
        invite = session.get(models.BattleInvite, invite_id)
        assert invite is not None
        assert invite.status == models.BATTLE_INVITE_STATUS_PENDING
        assert invite.battle_id is None

    monkeypatch.setattr(
        battle_creation,
        "save_checkpoint",
        real_save_checkpoint,
    )
    succeeded = _accept(api_world, invite_id, api_world.ids.target_roster_id)
    assert succeeded.status_code == 200, succeeded.text
    assert _domain_counts(api_world)[0] == 1


def _record_accept_statements(
    world: ApiWorld,
    *,
    invite_id: int,
    roster_id: int,
) -> list[str]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(world.engine, "before_cursor_execute", record)
    try:
        response = _accept(world, invite_id, roster_id)
    finally:
        event.remove(world.engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    return statements


def test_sql_control_plane_is_constant_for_one_vs_twelve_units_and_history(
    api_world: ApiWorld,
) -> None:
    _login(api_world, api_world.ids.target_id)
    small_invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    small = _record_accept_statements(
        api_world,
        invite_id=small_invite_id,
        roster_id=api_world.ids.target_roster_id,
    )

    with api_world.sessions() as session:
        army_id = session.get(models.Roster, api_world.ids.inviter_roster_id).army_id
        weapon_id = session.scalar(
            select(models.Unit.default_weapon_id).where(
                models.Unit.default_weapon_id.is_not(None)
            )
        )
        assert weapon_id is not None
        for index in range(11):
            unit = models.Unit(
                name=f"SQL unit {index}",
                quality=4,
                defense=5,
                toughness=3,
                typical_models=1,
                army_id=army_id,
                default_weapon_id=weapon_id,
            )
            session.add(unit)
            session.flush()
            session.add_all(
                [
                    models.UnitWeapon(
                        unit_id=unit.id,
                        weapon_id=weapon_id,
                        is_default=True,
                        default_count=1,
                        is_primary=True,
                    ),
                    models.RosterUnit(
                        roster_id=api_world.ids.inviter_roster_id,
                        unit_id=unit.id,
                        count=1,
                        position=index + 1,
                    ),
                    models.RosterUnit(
                        roster_id=api_world.ids.target_roster_id,
                        unit_id=unit.id,
                        count=1,
                        position=index + 1,
                    ),
                ]
            )
        session.add_all(
            [
                models.BattleInvite(
                    from_user_id=api_world.ids.inviter_id,
                    to_user_id=api_world.ids.target_id,
                    roster_id=api_world.ids.inviter_roster_id,
                    scenario="lustrzana_a",
                    expires_at=FIXED_NOW + timedelta(hours=24),
                )
                for _ in range(20)
            ]
        )
        session.commit()
    large_invite_id = _invite(api_world, to_user_id=api_world.ids.target_id)
    large = _record_accept_statements(
        api_world,
        invite_id=large_invite_id,
        roster_id=api_world.ids.target_roster_id,
    )

    small_selects = [sql for sql in small if sql.lstrip().upper().startswith("SELECT")]
    large_selects = [sql for sql in large if sql.lstrip().upper().startswith("SELECT")]
    assert len(small_selects) == len(large_selects) == 13
    assert len(large) > len(small)  # required per-unit event INSERTs, not ORM N+1 reads
    for statement in large:
        normalized = " ".join(statement.lower().split())
        if "battle_invites" in normalized:
            assert "battle_invites.id" in normalized


@dataclass(frozen=True)
class ConcurrentWorld:
    app: FastAPI
    sessions: sessionmaker[Session]
    engine: Any
    ids: WorldIds


def _concurrent_world(tmp_path: Path) -> ConcurrentWorld:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'invite-accept-concurrency.db'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        future=True,
    )
    ids = _seed_world(sessions)
    return ConcurrentWorld(
        app=_test_app(sessions, with_session_route=False),
        sessions=sessions,
        engine=engine,
        ids=ids,
    )


def _concurrent_invite(
    world: ConcurrentWorld,
    *,
    to_user_id: int | None,
) -> int:
    with world.sessions() as session:
        invite = models.BattleInvite(
            from_user_id=world.ids.inviter_id,
            to_user_id=to_user_id,
            roster_id=world.ids.inviter_roster_id,
            scenario="lustrzana_a",
            expires_at=FIXED_NOW + timedelta(hours=24),
        )
        session.add(invite)
        session.commit()
        return invite.id


def _run_concurrent_accepts(
    world: ConcurrentWorld,
    *,
    invite_id: int,
    requests: tuple[tuple[str, int], tuple[str, int]],
) -> list[tuple[int, dict[str, Any]]]:
    results: list[tuple[int, dict[str, Any]]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def accept(raw_token: str, roster_id: int) -> None:
        try:
            with TestClient(world.app) as client:
                response = client.post(
                    f"/battles/invite/{invite_id}/accept",
                    json={"roster_id": roster_id},
                    headers=_bearer(raw_token),
                )
            with lock:
                results.append((response.status_code, response.json()))
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=accept, args=request)
        for request in requests
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    return results


def _synchronize_accept_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(2)
    real_stage = battle_invite_service.stage_battle_invite_acceptance

    def synchronized_stage(*args, **kwargs):
        barrier.wait(timeout=20)
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(
        battle_invite_service,
        "stage_battle_invite_acceptance",
        synchronized_stage,
    )
    monkeypatch.setattr(battle_invite_service, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(battle_invite_service, "_new_rng_seed", lambda: FIXED_SEED)


def _assert_one_complete_concurrent_result(
    world: ConcurrentWorld,
    *,
    invite_id: int,
) -> models.BattleInvite:
    with world.sessions() as session:
        invite = session.get(models.BattleInvite, invite_id)
        assert invite is not None
        assert invite.status == models.BATTLE_INVITE_STATUS_ACCEPTED
        battle_ids = session.scalars(select(models.Battle.id)).all()
        assert battle_ids == [invite.battle_id]
        event_battle_ids = set(session.scalars(select(models.BattleEvent.battle_id)))
        checkpoint_battle_ids = set(
            session.scalars(select(models.BattleCheckpoint.battle_id))
        )
        assert event_battle_ids == checkpoint_battle_ids == {invite.battle_id}
        assert session.scalar(select(func.count()).select_from(models.BattleCheckpoint)) == 1
        session.expunge(invite)
        return invite


def test_file_sqlite_concurrent_same_acceptor_returns_one_battle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _concurrent_world(tmp_path)
    try:
        invite_id = _concurrent_invite(world, to_user_id=world.ids.target_id)
        _seed_token(
            world.sessions,
            owner_user_id=world.ids.target_id,
            raw_token="concurrent-same",
            scopes={battles.BATTLE_ACCEPT_SCOPE: True},
        )
        _synchronize_accept_stage(monkeypatch)
        results = _run_concurrent_accepts(
            world,
            invite_id=invite_id,
            requests=(
                ("concurrent-same", world.ids.target_roster_id),
                ("concurrent-same", world.ids.target_roster_id),
            ),
        )

        assert [status for status, _ in results] == [200, 200]
        assert len({payload["battle_id"] for _, payload in results}) == 1
        invite = _assert_one_complete_concurrent_result(
            world,
            invite_id=invite_id,
        )
        assert invite.accepted_by_user_id == world.ids.target_id
        assert invite.accepted_roster_id == world.ids.target_roster_id
    finally:
        world.app.dependency_overrides.clear()
        world.engine.dispose()


def test_file_sqlite_concurrent_open_invite_has_one_winner_and_zero_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _concurrent_world(tmp_path)
    try:
        invite_id = _concurrent_invite(world, to_user_id=None)
        _seed_token(
            world.sessions,
            owner_user_id=world.ids.target_id,
            raw_token="concurrent-target",
            scopes={battles.BATTLE_ACCEPT_SCOPE: True},
        )
        _seed_token(
            world.sessions,
            owner_user_id=world.ids.other_id,
            raw_token="concurrent-other",
            scopes={battles.BATTLE_ACCEPT_SCOPE: True},
        )
        _synchronize_accept_stage(monkeypatch)
        results = _run_concurrent_accepts(
            world,
            invite_id=invite_id,
            requests=(
                ("concurrent-target", world.ids.target_roster_id),
                ("concurrent-other", world.ids.other_roster_id),
            ),
        )

        assert sorted(status for status, _ in results) == [200, 404]
        invite = _assert_one_complete_concurrent_result(
            world,
            invite_id=invite_id,
        )
        accepted_pairs = {
            (world.ids.target_id, world.ids.target_roster_id),
            (world.ids.other_id, world.ids.other_roster_id),
        }
        assert (invite.accepted_by_user_id, invite.accepted_roster_id) in accepted_pairs
    finally:
        world.app.dependency_overrides.clear()
        world.engine.dispose()
