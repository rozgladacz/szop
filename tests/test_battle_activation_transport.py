from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from app.services.engine.actions import DefendAction
from app.services.engine.persistence import load_latest_checkpoint
from app.services.engine.state import ActivationPhase
from app.services.engine.state_codec import battle_state_from_json
from szop_client import (
    HttpClient,
    HttpClientActivationError,
    HttpRequest,
    HttpResponse,
)


@dataclass(frozen=True)
class ActivationTransportIds:
    p0_user_id: int
    p1_user_id: int
    outsider_user_id: int
    p0_roster_id: int
    p0_second_roster_id: int
    p1_roster_id: int


@dataclass(frozen=True)
class ActivationTransportWorld:
    p0: TestClient
    p1: TestClient
    outsider: TestClient
    sessions: sessionmaker[Session]
    engine: Any
    ids: ActivationTransportIds


class CountingTestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        parsed = urlsplit(request.url)
        target = parsed.path
        if parsed.query:
            target = f"{target}?{parsed.query}"
        response = self.client.request(
            request.method,
            target,
            headers=request.headers,
            content=request.body,
        )
        return HttpResponse(status_code=response.status_code, body=response.content)


def _enable_sqlite_foreign_keys(engine: Any) -> None:
    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _seed_activation_transport_world(
    sessions: sessionmaker[Session],
) -> ActivationTransportIds:
    with sessions() as session:
        p0 = models.User(username="activation-p0", password_hash="x")
        p1 = models.User(username="activation-p1", password_hash="x")
        outsider = models.User(username="activation-outsider", password_hash="x")
        ruleset = models.RuleSet(name="Activation transport rules")
        armory = models.Armory(name="Activation transport armory")
        army = models.Army(
            name="Activation transport army",
            ruleset=ruleset,
            armory=armory,
        )
        weapon = models.Weapon(
            name="Activation blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
            armory=armory,
        )
        unit = models.Unit(
            name="Activation infantry",
            quality=4,
            defense=5,
            toughness=3,
            typical_models=2,
            army=army,
            default_weapon=weapon,
        )
        rozkaz = models.Ability(
            name="Rozkaz",
            type="aktywna",
            description="Transport fixture",
        )
        session.add_all(
            [
                p0,
                p1,
                outsider,
                ruleset,
                armory,
                army,
                weapon,
                unit,
                rozkaz,
            ]
        )
        session.flush()
        session.add_all(
            [
                models.UnitWeapon(
                    unit=unit,
                    weapon=weapon,
                    is_default=True,
                    default_count=1,
                    is_primary=True,
                ),
                models.UnitAbility(unit=unit, ability=rozkaz),
            ]
        )

        roster_specs = (
            ("Activation p0 roster", p0),
            ("Activation p0 second roster", p0),
            ("Activation p1 roster", p1),
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
                    count=3,
                    position=position,
                )
            )
            rosters.append(roster)
        session.commit()
        return ActivationTransportIds(
            p0_user_id=p0.id,
            p1_user_id=p1.id,
            outsider_user_id=outsider.id,
            p0_roster_id=rosters[0].id,
            p0_second_roster_id=rosters[1].id,
            p1_roster_id=rosters[2].id,
        )


def _activation_test_app(sessions: sessionmaker[Session]) -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="activation-transport")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db

    @test_app.post("/_test/session/{user_id}")
    def set_session(user_id: int, request: Request) -> dict[str, int]:
        request.session["user_id"] = user_id
        return {"user_id": user_id}

    return test_app


@pytest.fixture()
def activation_transport_world():
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
    ids = _seed_activation_transport_world(sessions)
    test_app = _activation_test_app(sessions)
    try:
        with ExitStack() as stack:
            p0 = stack.enter_context(TestClient(test_app))
            p1 = stack.enter_context(TestClient(test_app))
            outsider = stack.enter_context(TestClient(test_app))
            assert p0.post(f"/_test/session/{ids.p0_user_id}").status_code == 200
            assert p1.post(f"/_test/session/{ids.p1_user_id}").status_code == 200
            assert (
                outsider.post(f"/_test/session/{ids.outsider_user_id}").status_code
                == 200
            )
            yield ActivationTransportWorld(
                p0=p0,
                p1=p1,
                outsider=outsider,
                sessions=sessions,
                engine=engine,
                ids=ids,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _create_same_owner_battle(
    world: ActivationTransportWorld,
    *,
    protocol_version: int,
) -> dict[str, Any]:
    response = world.p0.post(
        "/battles",
        json={
            "p1_roster_id": world.ids.p0_roster_id,
            "p2_roster_id": world.ids.p0_second_roster_id,
            "rng_seed": 20260729,
            "initiative_player": 0,
            "activation_protocol_version": protocol_version,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_two_owner_battle(world: ActivationTransportWorld) -> dict[str, Any]:
    invited = world.p0.post(
        "/battles/invite",
        json={
            "to_user_id": world.ids.p1_user_id,
            "roster_id": world.ids.p0_roster_id,
            "activation_protocol_version": 2,
        },
    )
    assert invited.status_code == 201, invited.text
    accepted = world.p1.post(
        f"/battles/invite/{invited.json()['id']}/accept",
        json={"roster_id": world.ids.p1_roster_id},
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


def _seed_token(
    world: ActivationTransportWorld,
    *,
    owner_user_id: int,
    raw_token: str,
    scopes: dict[str, bool],
) -> None:
    with world.sessions() as session:
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


def _bearer(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def _stream_counts(
    world: ActivationTransportWorld,
    battle_id: int,
) -> tuple[int, int, int, str]:
    with world.sessions() as session:
        event_count = int(
            session.scalar(
                select(func.count()).select_from(models.BattleEvent).where(
                    models.BattleEvent.battle_id == battle_id
                )
            )
            or 0
        )
        checkpoint_count = int(
            session.scalar(
                select(func.count()).select_from(models.BattleCheckpoint).where(
                    models.BattleCheckpoint.battle_id == battle_id
                )
            )
            or 0
        )
        head = load_latest_checkpoint(session, battle_id)
        assert head is not None
        return (
            event_count,
            checkpoint_count,
            head.sequence_at,
            json.dumps(head.dice.to_checkpoint(), sort_keys=True),
        )


def _wire_state(response) -> Any:
    return battle_state_from_json(response.json()["state"])


def _activation_guards(response) -> dict[str, int]:
    state = _wire_state(response)
    activation = state.activation
    assert activation is not None
    guards = {
        "expected_sequence": response.json()["new_sequence"],
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
    }
    if activation.window is not None:
        guards["expected_window_version"] = activation.window.version
    return guards


def _client_activation_guards(result: Any) -> dict[str, int]:
    activation = result.state.activation
    assert activation is not None
    guards = {
        "expected_sequence": result.new_sequence,
        "activation_id": activation.activation_id,
        "expected_activation_version": activation.version,
    }
    if activation.window is not None:
        guards["expected_window_version"] = activation.window.version
    return guards


def _defend_action(unit_id: int = 1) -> dict[str, Any]:
    return {
        "schema": "szop.action",
        "version": 1,
        "action_type": "defend",
        "payload": {"unit_id": unit_id},
    }


def _start(world_client: TestClient, battle: dict[str, Any]):
    return world_client.post(
        f"/battles/{battle['battle_id']}/activations",
        json={
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 1,
        },
    )


def _pass(world_client: TestClient, battle_id: int, previous_response):
    return world_client.post(
        f"/battles/{battle_id}/interrupts",
        json={"operation": "pass", **_activation_guards(previous_response)},
    )


def _action(world_client: TestClient, battle_id: int, previous_response):
    guards = _activation_guards(previous_response)
    guards.pop("expected_window_version", None)
    return world_client.post(
        f"/battles/{battle_id}/actions",
        json={**guards, "action": _defend_action()},
    )


def _transition(
    world_client: TestClient,
    battle_id: int,
    previous_response,
    *,
    operation: str,
):
    guards = _activation_guards(previous_response)
    activation_id = guards.pop("activation_id")
    guards.pop("expected_window_version", None)
    body: dict[str, Any] = {"operation": operation, **guards}
    if operation == "finalize":
        body["recovery"] = {"uses": []}
    return world_client.post(
        f"/battles/{battle_id}/activations/{activation_id}/transitions",
        json=body,
    )


def _assert_exact_envelope(response, battle_id: int, version: int = 2) -> None:
    payload = response.json()
    assert set(payload) == {
        "battle_id",
        "previous_sequence",
        "new_sequence",
        "state",
        "events",
    }
    assert payload["battle_id"] == battle_id
    assert payload["new_sequence"] > payload["previous_sequence"]
    assert set(payload["state"]) == {"schema", "version", "state"}
    assert payload["state"]["schema"] == "szop.battle_state"
    assert payload["state"]["version"] == version
    assert [event["sequence"] for event in payload["events"]] == list(
        range(payload["previous_sequence"] + 1, payload["new_sequence"] + 1)
    )
    serialized = json.dumps(payload, sort_keys=True)
    assert "rng" not in serialized.lower()
    assert "user_id" not in serialized


@pytest.mark.parametrize("with_second_action", [False, True])
def test_same_owner_real_transport_completes_v2_activation_to_idle(
    activation_transport_world: ActivationTransportWorld,
    with_second_action: bool,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]

    started = _start(world.p0, battle)
    assert started.status_code == 201, started.text
    _assert_exact_envelope(started, battle_id)
    first_pass = _pass(world.p0, battle_id, started)
    assert first_pass.status_code == 202, first_pass.text
    second_pass = _pass(world.p0, battle_id, first_pass)
    assert second_pass.status_code == 200, second_pass.text
    assert _wire_state(second_pass).activation.phase is ActivationPhase.ACTION_READY

    first_action = _action(world.p0, battle_id, second_pass)
    assert first_action.status_code == 202, first_action.text
    if with_second_action:
        continued = _transition(
            world.p0,
            battle_id,
            first_action,
            operation="continue",
        )
        assert continued.status_code == 202, continued.text
        first_pass = _pass(world.p0, battle_id, continued)
        assert first_pass.status_code == 202, first_pass.text
        second_pass = _pass(world.p0, battle_id, first_pass)
        assert second_pass.status_code == 200, second_pass.text
        second_action = _action(world.p0, battle_id, second_pass)
        assert second_action.status_code == 202, second_action.text
        before_finalize = second_action
    else:
        before_finalize = first_action

    finalized = _transition(
        world.p0,
        battle_id,
        before_finalize,
        operation="finalize",
    )
    assert finalized.status_code == 200, finalized.text
    _assert_exact_envelope(finalized, battle_id)
    assert _wire_state(finalized).activation is None


def test_public_v2_flow_accepts_existing_first_roster_unit_id_zero(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    started = world.p0.post(
        f"/battles/{battle_id}/activations",
        json={
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 0,
        },
    )
    assert started.status_code == 201, started.text
    first_pass = _pass(world.p0, battle_id, started)
    second_pass = _pass(world.p0, battle_id, first_pass)
    guards = _activation_guards(second_pass)
    guards.pop("expected_window_version", None)
    action = world.p0.post(
        f"/battles/{battle_id}/actions",
        json={**guards, "action": _defend_action(0)},
    )
    assert action.status_code == 202
    finalized = _transition(
        world.p0,
        battle_id,
        action,
        operation="finalize",
    )
    assert finalized.status_code == 200
    assert _wire_state(finalized).activation is None


def test_two_owner_real_transport_enforces_priority_and_control_ownership(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_two_owner_battle(world)
    battle_id = battle["battle_id"]
    participant_clients = {
        world.ids.p0_user_id: world.p0,
        world.ids.p1_user_id: world.p1,
    }
    player_clients = (
        participant_clients[battle["p1_user_id"]],
        participant_clients[battle["p2_user_id"]],
    )
    state_response = player_clients[0].get(f"/battles/{battle_id}/state")
    assert state_response.status_code == 200
    state_payload = state_response.json()
    initial_state = battle_state_from_json(
        {
            "schema": state_payload["schema"],
            "version": state_payload["version"],
            "state": state_payload["state"],
        }
    )
    controlling_player = initial_state.active_player
    controlling_client = player_clients[controlling_player]
    other_client = player_clients[1 - controlling_player]
    selected_unit_id = next(
        blob.id
        for blob in initial_state.blobs
        if blob.owner_player == controlling_player and blob.id >= 1
    )
    started = controlling_client.post(
        f"/battles/{battle_id}/activations",
        json={
            "expected_sequence": state_response.json()["sequence_at"],
            "selected_unit_id": selected_unit_id,
        },
    )
    assert started.status_code == 201, started.text

    started_state = _wire_state(started)
    priority_player = started_state.activation.window.priority_player
    priority_client = player_clients[priority_player]
    next_priority_client = player_clients[1 - priority_player]
    priority_units = [
        blob.id
        for blob in started_state.blobs
        if blob.owner_player == priority_player and blob.id >= 1
    ]
    legal_interrupt = priority_client.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **_activation_guards(started),
            "source_unit_id": priority_units[-1],
            "ability_slug": "rozkaz",
            "payload": {
                "target_id": priority_units[0],
                "ability": "nieustraszony",
                "granted": False,
            },
        },
    )
    assert legal_interrupt.status_code == 200, legal_interrupt.text
    wrong_priority = _pass(next_priority_client, battle_id, legal_interrupt)
    assert wrong_priority.status_code == 409
    assert wrong_priority.json() == {
        "detail": {"code": "not_current_priority"}
    }
    first_pass = _pass(priority_client, battle_id, legal_interrupt)
    assert first_pass.status_code == 202
    second_pass = _pass(next_priority_client, battle_id, first_pass)
    assert second_pass.status_code == 200

    action_payload = _defend_action(selected_unit_id)
    action_guards = _activation_guards(second_pass)
    action_guards.pop("expected_window_version", None)
    wrong_controller = other_client.post(
        f"/battles/{battle_id}/actions",
        json={**action_guards, "action": action_payload},
    )
    assert wrong_controller.status_code == 403
    assert wrong_controller.json() == {"detail": {"code": "forbidden"}}
    action = controlling_client.post(
        f"/battles/{battle_id}/actions",
        json={**action_guards, "action": action_payload},
    )
    assert action.status_code == 202
    wrong_finalize = _transition(
        other_client,
        battle_id,
        action,
        operation="finalize",
    )
    assert wrong_finalize.status_code == 403
    finalized = _transition(
        controlling_client,
        battle_id,
        action,
        operation="finalize",
    )
    assert finalized.status_code == 200
    assert _wire_state(finalized).activation is None


def test_v1_new_routes_fail_closed_and_action_contract_stays_v1(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=1)
    battle_id = battle["battle_id"]
    start = _start(world.p0, battle)
    assert start.status_code == 409
    assert start.json() == {
        "detail": {"code": "battle_protocol_upgrade_required"}
    }
    interrupt = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "pass",
            "expected_sequence": battle["latest_sequence"],
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
        },
    )
    assert interrupt.status_code == 409
    assert interrupt.json() == {
        "detail": {"code": "battle_protocol_upgrade_required"}
    }
    transition = world.p0.post(
        f"/battles/{battle_id}/activations/1/transitions",
        json={
            "operation": "continue",
            "expected_sequence": battle["latest_sequence"],
            "expected_activation_version": 1,
        },
    )
    assert transition.status_code == 409
    assert transition.json() == {
        "detail": {"code": "battle_protocol_upgrade_required"}
    }

    action = world.p0.post(
        f"/battles/{battle_id}/actions",
        json={
            "expected_sequence": battle["latest_sequence"],
            "action": _defend_action(),
        },
    )
    assert action.status_code == 200, action.text
    _assert_exact_envelope(action, battle_id, version=1)


def test_v2_action_requires_both_strict_activation_guards(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    for patch in (
        {},
        {"activation_id": 1},
        {"expected_activation_version": 1},
    ):
        response = world.p0.post(
            f"/battles/{battle_id}/actions",
            json={
                "expected_sequence": battle["latest_sequence"],
                "action": _defend_action(),
                **patch,
            },
        )
        assert response.status_code == 422
        assert response.json() == {
            "detail": {"code": "activation_guard_required"}
        }


@pytest.mark.parametrize(
    ("patch", "expected_code"),
    [
        (
            {"activation_id": True, "expected_activation_version": 1},
            "activation_guard_required",
        ),
        (
            {"activation_id": "1", "expected_activation_version": 1},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1.0, "expected_activation_version": 1},
            "activation_guard_required",
        ),
        (
            {"activation_id": None, "expected_activation_version": 1},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1, "expected_activation_version": False},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1, "expected_activation_version": "1"},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1, "expected_activation_version": 1.0},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1, "expected_activation_version": None},
            "activation_guard_required",
        ),
        (
            {"activation_id": 1, "expected_activation_version": 1, "extra": 1},
            "illegal_action",
        ),
    ],
)
def test_v2_action_guard_types_are_strict_and_write_free(
    activation_transport_world: ActivationTransportWorld,
    patch: dict[str, Any],
    expected_code: str,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    before = _stream_counts(world, battle["battle_id"])
    response = world.p0.post(
        f"/battles/{battle['battle_id']}/actions",
        json={
            "expected_sequence": battle["latest_sequence"],
            "action": _defend_action(),
            **patch,
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": expected_code}}
    assert _stream_counts(world, battle["battle_id"]) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"operation": "unknown"},
        {"operation": "continue", "expected_sequence": 0},
        {
            "operation": "continue",
            "expected_sequence": True,
            "expected_activation_version": 1,
        },
        {
            "operation": "continue",
            "expected_sequence": "0",
            "expected_activation_version": 1,
        },
        {
            "operation": "continue",
            "expected_sequence": 0.0,
            "expected_activation_version": 1,
        },
        {
            "operation": "continue",
            "expected_sequence": None,
            "expected_activation_version": 1,
        },
        {
            "operation": "continue",
            "expected_sequence": 0,
            "expected_activation_version": False,
        },
        {
            "operation": "continue",
            "expected_sequence": 0,
            "expected_activation_version": "1",
        },
        {
            "operation": "continue",
            "expected_sequence": 0,
            "expected_activation_version": 1,
            "recovery": {"uses": []},
        },
        {
            "operation": "finalize",
            "expected_sequence": 0,
            "expected_activation_version": 1,
        },
        {
            "operation": "continue",
            "expected_sequence": 0,
            "expected_activation_version": 1,
            "extra": 1,
        },
    ],
)
def test_transition_union_is_closed_strict_and_write_free(
    activation_transport_world: ActivationTransportWorld,
    body: dict[str, Any],
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    before = _stream_counts(world, battle["battle_id"])
    response = world.p0.post(
        f"/battles/{battle['battle_id']}/activations/1/transitions",
        json=body,
    )
    assert response.status_code == 422
    expected_code = (
        "illegal_recovery"
        if body.get("operation") == "finalize" and "recovery" not in body
        else "invalid_phase"
    )
    assert response.json() == {"detail": {"code": expected_code}}
    assert _stream_counts(world, battle["battle_id"]) == before


def test_route_inventory_and_openapi_expose_activation_transport() -> None:
    paths = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in battles.router.routes
    }
    assert paths["/battles/{battle_id}/activations"] == {"POST"}
    assert paths["/battles/{battle_id}/interrupts"] == {"POST"}
    assert paths[
        "/battles/{battle_id}/activations/{activation_id}/transitions"
    ] == {"POST"}
    schema = FastAPI()
    schema.include_router(battles.router)
    openapi = schema.openapi()
    action_schema = openapi["components"]["schemas"]["BattleActionCreate"]
    assert set(action_schema["properties"]) == {
        "expected_sequence",
        "activation_id",
        "expected_activation_version",
        "action",
    }
    interrupt_schema = openapi["paths"]["/battles/{battle_id}/interrupts"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]
    assert interrupt_schema["discriminator"]["propertyName"] == "operation"
    assert set(
        openapi["paths"]["/battles/{battle_id}/interrupts"]["post"]["responses"]
    ) >= {"200", "202"}
    assert set(
        openapi["paths"][
            "/battles/{battle_id}/activations/{activation_id}/transitions"
        ]["post"]["responses"]
    ) >= {"200", "202"}
    assert set(
        openapi["paths"]["/battles/{battle_id}/actions"]["post"]["responses"]
    ) >= {"200", "202"}


def test_transport_success_persists_one_checkpoint_per_operation(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    with world.sessions() as session:
        before = int(
            session.scalar(
                select(func.count()).select_from(models.BattleCheckpoint).where(
                    models.BattleCheckpoint.battle_id == battle_id
                )
            )
            or 0
        )
    started = _start(world.p0, battle)
    assert started.status_code == 201
    with world.sessions() as session:
        after = int(
            session.scalar(
                select(func.count()).select_from(models.BattleCheckpoint).where(
                    models.BattleCheckpoint.battle_id == battle_id
                )
            )
            or 0
        )
        head = load_latest_checkpoint(session, battle_id)
        assert head is not None
        assert head.sequence_at == started.json()["new_sequence"]
    assert after == before + 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_sequence": 0},
        {"selected_unit_id": 1},
        {"expected_sequence": True, "selected_unit_id": 1},
        {"expected_sequence": "0", "selected_unit_id": 1},
        {"expected_sequence": 0.0, "selected_unit_id": 1},
        {"expected_sequence": None, "selected_unit_id": 1},
        {"expected_sequence": 0, "selected_unit_id": True},
        {"expected_sequence": 0, "selected_unit_id": "1"},
        {"expected_sequence": 0, "selected_unit_id": 1, "extra": 1},
    ],
)
def test_start_request_is_strict_and_write_free(
    activation_transport_world: ActivationTransportWorld,
    body: dict[str, Any],
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    before = _stream_counts(world, battle["battle_id"])
    response = world.p0.post(
        f"/battles/{battle['battle_id']}/activations",
        json=body,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_selection"}}
    assert _stream_counts(world, battle["battle_id"]) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"operation": "unknown"},
        {
            "operation": "pass",
            "expected_sequence": 0,
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
            "source_unit_id": 2,
        },
        {
            "operation": "interrupt",
            "expected_sequence": 0,
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
            "source_unit_id": 2,
            "ability_slug": "rozkaz",
        },
        {
            "operation": "pass",
            "expected_sequence": True,
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
        },
        {
            "operation": "pass",
            "expected_sequence": "0",
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
        },
        {
            "operation": "pass",
            "expected_sequence": 0,
            "activation_id": 1,
            "expected_activation_version": 1,
            "expected_window_version": 1,
            "extra": False,
        },
    ],
)
def test_interrupt_union_is_closed_strict_and_write_free(
    activation_transport_world: ActivationTransportWorld,
    body: dict[str, Any],
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    started = _start(world.p0, battle)
    assert started.status_code == 201
    before = _stream_counts(world, battle["battle_id"])
    response = world.p0.post(
        f"/battles/{battle['battle_id']}/interrupts",
        json=body,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "illegal_interrupt"}}
    assert _stream_counts(world, battle["battle_id"]) == before


def test_public_rozkaz_succeeds_and_nonready_slugs_fail_closed(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    started = _start(world.p0, battle)
    guards = _activation_guards(started)
    accepted = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **guards,
            "source_unit_id": 0,
            "ability_slug": "rozkaz",
            "payload": {
                "target_id": 1,
                "ability": "nieustraszony",
                "granted": False,
            },
        },
    )
    assert accepted.status_code == 200, accepted.text
    _assert_exact_envelope(accepted, battle_id)
    accepted_state = _wire_state(accepted)
    assert accepted_state.activation.window.priority_player == 0

    for slug in ("klatwa", "oznaczenie", "straznik", "registry-only"):
        before = _stream_counts(world, battle_id)
        rejected = world.p0.post(
            f"/battles/{battle_id}/interrupts",
            json={
                "operation": "interrupt",
                **_activation_guards(accepted),
                "source_unit_id": 2,
                "ability_slug": slug,
                "payload": {
                    "target_id": 1,
                    "ability": "nieustraszony",
                    "granted": False,
                },
            },
        )
        assert rejected.status_code == 422
        assert rejected.json() == {
            "detail": {"code": "unsupported_interrupt"}
        }
        assert _stream_counts(world, battle_id) == before


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"target_id": True, "ability": "nieustraszony", "granted": False},
        {"target_id": "1", "ability": "nieustraszony", "granted": False},
        {"target_id": 1, "ability": 1, "granted": False},
        {"target_id": 1, "ability": "nieustraszony", "granted": 0},
        {
            "target_id": 1,
            "ability": "nieustraszony",
            "granted": False,
            "extra": 1,
        },
    ],
)
def test_public_rozkaz_payload_is_strict_and_atomic(
    activation_transport_world: ActivationTransportWorld,
    payload: dict[str, Any],
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    started = _start(world.p0, battle)
    before = _stream_counts(world, battle["battle_id"])
    response = world.p0.post(
        f"/battles/{battle['battle_id']}/interrupts",
        json={
            "operation": "interrupt",
            **_activation_guards(started),
            "source_unit_id": 2,
            "ability_slug": "rozkaz",
            "payload": payload,
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "illegal_interrupt"}}
    assert _stream_counts(world, battle["battle_id"]) == before


def test_finalize_recovery_is_explicit_strict_empty_and_atomic(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    started = _start(world.p0, battle)
    first_pass = _pass(world.p0, battle_id, started)
    second_pass = _pass(world.p0, battle_id, first_pass)
    action = _action(world.p0, battle_id, second_pass)
    guards = _activation_guards(action)
    activation_id = guards.pop("activation_id")
    before = _stream_counts(world, battle_id)

    invalid_recoveries = (
        None,
        {},
        {"uses": "[]"},
        {"uses": [True]},
        {
            "uses": [
                {
                    "source_unit_id": 1,
                    "ability_slug": "latanie",
                    "payload": {"target_id": 1},
                }
            ]
        },
        {"uses": [], "extra": 1},
    )
    for recovery in invalid_recoveries:
        body = {"operation": "finalize", **guards}
        if recovery is not None:
            body["recovery"] = recovery
        response = world.p0.post(
            f"/battles/{battle_id}/activations/{activation_id}/transitions",
            json=body,
        )
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "illegal_recovery"}}
        assert _stream_counts(world, battle_id) == before

    finalized = world.p0.post(
        f"/battles/{battle_id}/activations/{activation_id}/transitions",
        json={
            "operation": "finalize",
            **guards,
            "recovery": {"uses": []},
        },
    )
    assert finalized.status_code == 200


def test_restart_safe_transport_resumes_each_durable_head_and_preserves_rng(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    initial = _stream_counts(world, battle_id)

    started = _start(world.p0, battle)
    after_start = _stream_counts(world, battle_id)
    assert after_start[2] == started.json()["new_sequence"]
    assert after_start[3] == initial[3]
    first_pass = _pass(world.p0, battle_id, started)
    after_pass = _stream_counts(world, battle_id)
    assert after_pass[2] == first_pass.json()["new_sequence"]
    assert after_pass[3] == initial[3]
    second_pass = _pass(world.p0, battle_id, first_pass)
    action = _action(world.p0, battle_id, second_pass)
    after_action = _stream_counts(world, battle_id)
    assert after_action[2] == action.json()["new_sequence"]
    assert after_action[3] == initial[3]

    state_response = world.p0.get(f"/battles/{battle_id}/state")
    assert state_response.status_code == 200
    assert state_response.json()["sequence_at"] == action.json()["new_sequence"]
    finalized = _transition(
        world.p0,
        battle_id,
        action,
        operation="finalize",
    )
    assert finalized.status_code == 200
    assert _stream_counts(world, battle_id)[3] == initial[3]


def test_stale_guards_duplicate_and_wrong_phase_have_stable_codes_no_writes(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    started = _start(world.p0, battle)
    first_pass = _pass(world.p0, battle_id, started)
    after_first_pass = _stream_counts(world, battle_id)

    duplicate = _pass(world.p0, battle_id, started)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": {"code": "stale_sequence"}}
    assert _stream_counts(world, battle_id) == after_first_pass

    stale_activation = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "pass",
            **{
                **_activation_guards(first_pass),
                "activation_id": 999999,
            },
        },
    )
    assert stale_activation.status_code == 409
    assert stale_activation.json() == {
        "detail": {"code": "stale_activation"}
    }
    stale_window = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "pass",
            **{
                **_activation_guards(first_pass),
                "expected_window_version": 999999,
            },
        },
    )
    assert stale_window.status_code == 409
    assert stale_window.json() == {"detail": {"code": "stale_window"}}
    assert _stream_counts(world, battle_id) == after_first_pass

    second_pass = _pass(world.p0, battle_id, first_pass)
    wrong_phase = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "pass",
            **_activation_guards(second_pass),
            "expected_window_version": 1,
        },
    )
    assert wrong_phase.status_code == 409
    assert wrong_phase.json() == {"detail": {"code": "invalid_phase"}}


def test_missing_and_foreign_battle_are_same_no_oracle_error_without_writes(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    before = _stream_counts(world, battle["battle_id"])
    bodies = []
    for battle_id in (battle["battle_id"], battle["battle_id"] + 999999):
        response = world.outsider.post(
            f"/battles/{battle_id}/activations",
            json={
                "expected_sequence": battle["latest_sequence"],
                "selected_unit_id": 1,
            },
        )
        assert response.status_code == 404
        bodies.append(response.json())
    assert bodies == [
        {"detail": {"code": "battle_not_found"}},
        {"detail": {"code": "battle_not_found"}},
    ]
    assert _stream_counts(world, battle["battle_id"]) == before


def test_agent_scopes_wildcard_and_body_blind_audit(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    _seed_token(
        world,
        owner_user_id=world.ids.p0_user_id,
        raw_token="act-only",
        scopes={battles.BATTLE_ACT_SCOPE: True},
    )
    _seed_token(
        world,
        owner_user_id=world.ids.p0_user_id,
        raw_token="interrupt-only",
        scopes={battles.BATTLE_INTERRUPT_SCOPE: True},
    )
    _seed_token(
        world,
        owner_user_id=world.ids.p0_user_id,
        raw_token="wildcard",
        scopes={"*": True},
    )

    denied = world.p0.post(
        f"/battles/{battle_id}/activations",
        headers=_bearer("interrupt-only"),
        json={
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 1,
        },
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "forbidden"}}
    started = world.p0.post(
        f"/battles/{battle_id}/activations",
        headers=_bearer("act-only"),
        json={
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 1,
        },
    )
    assert started.status_code == 201
    wrong_scope = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        headers=_bearer("act-only"),
        json={"operation": "pass", **_activation_guards(started)},
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json() == {"detail": {"code": "forbidden"}}
    bearer_pass = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        headers=_bearer("interrupt-only"),
        json={"operation": "pass", **_activation_guards(started)},
    )
    assert bearer_pass.status_code == 202
    second_bearer_pass = world.p0.post(
        f"/battles/{battle_id}/interrupts",
        headers=_bearer("interrupt-only"),
        json={"operation": "pass", **_activation_guards(bearer_pass)},
    )
    assert second_bearer_pass.status_code == 200
    action_guards = _activation_guards(second_bearer_pass)
    action_guards.pop("expected_window_version", None)
    denied_action = world.p0.post(
        f"/battles/{battle_id}/actions",
        headers=_bearer("interrupt-only"),
        json={**action_guards, "action": _defend_action()},
    )
    assert denied_action.status_code == 403
    assert denied_action.json() == {"detail": {"code": "forbidden"}}
    accepted_action = world.p0.post(
        f"/battles/{battle_id}/actions",
        headers=_bearer("act-only"),
        json={**action_guards, "action": _defend_action()},
    )
    assert accepted_action.status_code == 202

    wildcard_battle = _create_same_owner_battle(world, protocol_version=2)
    wildcard_start = world.p0.post(
        f"/battles/{wildcard_battle['battle_id']}/activations",
        headers=_bearer("wildcard"),
        json={
            "expected_sequence": wildcard_battle["latest_sequence"],
            "selected_unit_id": 1,
        },
    )
    assert wildcard_start.status_code == 201

    bearer_pass = world.p0.post(
        f"/battles/{wildcard_battle['battle_id']}/interrupts",
        headers=_bearer("wildcard"),
        json={"operation": "pass", **_activation_guards(wildcard_start)},
    )
    assert bearer_pass.status_code == 202
    with world.sessions() as session:
        audits = session.execute(select(models.AgentAuditLog)).scalars().all()
        serialized = "\n".join(audit.params_json for audit in audits)
        assert "act-only" not in serialized
        assert "wildcard" not in serialized
        assert "selected_unit_id" not in serialized
        assert "operation" not in serialized
        assert all(audit.route.startswith("/battles/") for audit in audits)
        for audit in audits:
            payload = json.loads(audit.params_json)
            assert "battle_id" in payload["path_params"]


def test_v2_missing_auth_uses_closed_unauthorized_envelope(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    world.outsider.cookies.clear()
    response = world.outsider.post(
        f"/battles/{battle['battle_id']}/activations",
        json={
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 1,
        },
    )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "unauthorized"}}


def test_interrupt_foreign_source_is_forbidden_but_missing_or_enemy_target_is_generic(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_two_owner_battle(world)
    battle_id = battle["battle_id"]
    participant_clients = {
        world.ids.p0_user_id: world.p0,
        world.ids.p1_user_id: world.p1,
    }
    player_clients = (
        participant_clients[battle["p1_user_id"]],
        participant_clients[battle["p2_user_id"]],
    )
    state_response = player_clients[0].get(f"/battles/{battle_id}/state")
    state_payload = state_response.json()
    initial_state = battle_state_from_json(
        {
            "schema": state_payload["schema"],
            "version": state_payload["version"],
            "state": state_payload["state"],
        }
    )
    controlling_player = initial_state.active_player
    controller = player_clients[controlling_player]
    selected_id = next(
        blob.id
        for blob in initial_state.blobs
        if blob.owner_player == controlling_player and blob.id >= 1
    )
    started = controller.post(
        f"/battles/{battle_id}/activations",
        json={
            "expected_sequence": state_payload["sequence_at"],
            "selected_unit_id": selected_id,
        },
    )
    assert started.status_code == 201
    started_state = _wire_state(started)
    priority_player = started_state.activation.window.priority_player
    priority_client = player_clients[priority_player]
    own_source_id = next(
        blob.id
        for blob in started_state.blobs
        if blob.owner_player == priority_player and blob.id >= 1
    )
    foreign_source_id = next(
        blob.id
        for blob in started_state.blobs
        if blob.owner_player != priority_player and blob.id >= 1
    )
    enemy_target_id = next(
        blob.id
        for blob in started_state.blobs
        if blob.owner_player != priority_player and blob.id >= 1
    )
    guards = _activation_guards(started)
    base_payload = {
        "target_id": selected_id,
        "ability": "nieustraszony",
        "granted": False,
    }
    before = _stream_counts(world, battle_id)
    stale_foreign_source = priority_client.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **{**guards, "activation_id": guards["activation_id"] + 1},
            "source_unit_id": foreign_source_id,
            "ability_slug": "rozkaz",
            "payload": base_payload,
        },
    )
    assert stale_foreign_source.status_code == 409
    assert stale_foreign_source.json() == {
        "detail": {"code": "stale_activation"}
    }
    foreign_source = priority_client.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **guards,
            "source_unit_id": foreign_source_id,
            "ability_slug": "rozkaz",
            "payload": base_payload,
        },
    )
    assert foreign_source.status_code == 403
    assert foreign_source.json() == {"detail": {"code": "forbidden"}}
    missing_source = priority_client.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **guards,
            "source_unit_id": 999999999,
            "ability_slug": "rozkaz",
            "payload": base_payload,
        },
    )
    assert missing_source.status_code == 422
    assert missing_source.json() == {
        "detail": {"code": "illegal_interrupt"}
    }
    enemy_target = priority_client.post(
        f"/battles/{battle_id}/interrupts",
        json={
            "operation": "interrupt",
            **guards,
            "source_unit_id": own_source_id,
            "ability_slug": "rozkaz",
            "payload": {
                **base_payload,
                "target_id": enemy_target_id,
            },
        },
    )
    assert enemy_target.status_code == 422
    assert enemy_target.json() == {
        "detail": {"code": "illegal_interrupt"}
    }
    assert _stream_counts(world, battle_id) == before


@pytest.mark.parametrize(
    "write_error",
    [
        IntegrityError("forced transport commit failure", {}, RuntimeError()),
        OperationalError("forced sqlite lock", {}, RuntimeError()),
    ],
)
def test_database_write_error_rolls_back_events_and_checkpoint(
    activation_transport_world: ActivationTransportWorld,
    monkeypatch: pytest.MonkeyPatch,
    write_error: Exception,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    before = _stream_counts(world, battle_id)

    def fail_commit(self) -> None:
        raise write_error

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = _start(world.p0, battle)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "write_conflict"}}
    assert _stream_counts(world, battle_id) == before


def test_response_serialization_failure_rolls_back_events_and_checkpoint(
    activation_transport_world: ActivationTransportWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    before = _stream_counts(world, battle["battle_id"])

    def fail_serialization(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("forced response serialization failure")

    monkeypatch.setattr(battles, "battle_state_to_json", fail_serialization)
    with pytest.raises(RuntimeError, match="forced response serialization failure"):
        _start(world.p0, battle)
    assert _stream_counts(world, battle["battle_id"]) == before


def test_full_request_sql_counts_are_constant_for_session_bearer_and_v1_action(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world

    def counted_request(request):
        statements: list[str] = []

        def capture(
            conn,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ) -> None:
            del conn, cursor, parameters, context, executemany
            statements.append(statement)

        event.listen(world.engine, "before_cursor_execute", capture)
        try:
            response = request()
        finally:
            event.remove(world.engine, "before_cursor_execute", capture)
        return response, sum(
            statement.lstrip().upper().startswith("SELECT")
            for statement in statements
        ), len(statements)

    session_battle = _create_same_owner_battle(world, protocol_version=2)
    session_response, session_selects, session_statements = counted_request(
        lambda: _start(world.p0, session_battle)
    )
    assert session_response.status_code == 201

    _seed_token(
        world,
        owner_user_id=world.ids.p0_user_id,
        raw_token="sql-bearer",
        scopes={battles.BATTLE_ACT_SCOPE: True},
    )
    bearer_battle = _create_same_owner_battle(world, protocol_version=2)
    world.outsider.cookies.clear()
    bearer_response, bearer_selects, bearer_statements = counted_request(
        lambda: world.outsider.post(
            f"/battles/{bearer_battle['battle_id']}/activations",
            headers=_bearer("sql-bearer"),
            json={
                "expected_sequence": bearer_battle["latest_sequence"],
                "selected_unit_id": 1,
            },
        )
    )
    assert bearer_response.status_code == 201

    v1_battle = _create_same_owner_battle(world, protocol_version=1)
    v1_response, v1_selects, v1_statements = counted_request(
        lambda: world.p0.post(
            f"/battles/{v1_battle['battle_id']}/actions",
            json={
                "expected_sequence": v1_battle["latest_sequence"],
                "action": _defend_action(),
            },
        )
    )
    assert v1_response.status_code == 200
    assert (session_selects, session_statements) == (6, 10)
    assert (bearer_selects, bearer_statements) == (7, 13)
    assert (v1_selects, v1_statements) == (6, 13)


def test_each_v2_session_mutation_has_constant_six_select_ceiling(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    select_counts: list[int] = []

    def counted(request):
        statements: list[str] = []

        def capture(
            conn,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ) -> None:
            del conn, cursor, parameters, context, executemany
            statements.append(statement)

        event.listen(world.engine, "before_cursor_execute", capture)
        try:
            response = request()
        finally:
            event.remove(world.engine, "before_cursor_execute", capture)
        select_counts.append(
            sum(
                statement.lstrip().upper().startswith("SELECT")
                for statement in statements
            )
        )
        return response

    started = counted(lambda: _start(world.p0, battle))
    interrupted = counted(
        lambda: world.p0.post(
            f"/battles/{battle_id}/interrupts",
            json={
                "operation": "interrupt",
                **_activation_guards(started),
                "source_unit_id": 2,
                "ability_slug": "rozkaz",
                "payload": {
                    "target_id": 1,
                    "ability": "nieustraszony",
                    "granted": False,
                },
            },
        )
    )
    first_pass = counted(lambda: _pass(world.p0, battle_id, interrupted))
    second_pass = counted(lambda: _pass(world.p0, battle_id, first_pass))
    first_action = counted(lambda: _action(world.p0, battle_id, second_pass))
    continued = counted(
        lambda: _transition(
            world.p0,
            battle_id,
            first_action,
            operation="continue",
        )
    )
    third_pass = counted(lambda: _pass(world.p0, battle_id, continued))
    fourth_pass = counted(lambda: _pass(world.p0, battle_id, third_pass))
    second_action = counted(lambda: _action(world.p0, battle_id, fourth_pass))
    finalized = counted(
        lambda: _transition(
            world.p0,
            battle_id,
            second_action,
            operation="finalize",
        )
    )
    assert finalized.status_code == 200
    assert select_counts == [6] * 10


def test_two_independent_http_sessions_allow_exactly_one_duplicate_winner(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    second_app = _activation_test_app(world.sessions)
    with TestClient(second_app) as second_client:
        assert (
            second_client.post(
                f"/_test/session/{world.ids.p0_user_id}"
            ).status_code
            == 200
        )
        body = {
            "expected_sequence": battle["latest_sequence"],
            "selected_unit_id": 1,
        }
        first = world.p0.post(
            f"/battles/{battle_id}/activations",
            json=body,
        )
        second = second_client.post(
            f"/battles/{battle_id}/activations",
            json=body,
        )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"detail": {"code": "stale_sequence"}}
    with world.sessions() as session:
        checkpoints = int(
            session.scalar(
                select(func.count()).select_from(models.BattleCheckpoint).where(
                    models.BattleCheckpoint.battle_id == battle_id
                )
            )
            or 0
        )
        head = load_latest_checkpoint(session, battle_id)
        assert head is not None
        assert head.sequence_at == first.json()["new_sequence"]
    assert checkpoints == 2


def test_http_client_same_owner_v2_flow_uses_one_post_per_mutation_and_sql_ceiling(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_same_owner_battle(world, protocol_version=2)
    battle_id = battle["battle_id"]
    transport = CountingTestClientTransport(world.p0)
    client = HttpClient("http://testserver", transport=transport)
    statements: list[str] = []

    def capture(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(world.engine, "before_cursor_execute", capture)
    try:
        started = client.start_activation(
            battle_id,
            expected_sequence=battle["latest_sequence"],
            selected_unit_id=1,
        )
        first_pass = client.pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(started),
        )
        second_pass = client.pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(first_pass),
        )
        action_guards = _client_activation_guards(second_pass)
        action_guards.pop("expected_window_version", None)
        first_action = client.commit_activation_action(
            battle_id,
            DefendAction(unit_id=1),
            **action_guards,
        )
        finalize_guards = _client_activation_guards(first_action)
        finalized = client.finalize_activation(
            battle_id,
            **finalize_guards,
            recovery_uses=[],
        )
    finally:
        event.remove(world.engine, "before_cursor_execute", capture)

    assert finalized.state.activation is None
    assert [request.method for request in transport.requests] == ["POST"] * 5
    assert [urlsplit(request.url).path for request in transport.requests] == [
        f"/battles/{battle_id}/activations",
        f"/battles/{battle_id}/interrupts",
        f"/battles/{battle_id}/interrupts",
        f"/battles/{battle_id}/actions",
        f"/battles/{battle_id}/activations/{started.state.activation.activation_id}/transitions",
    ]
    assert sum(
        statement.lstrip().upper().startswith("SELECT")
        for statement in statements
    ) == 30


def test_http_client_two_owner_tokens_restart_races_and_second_action(
    activation_transport_world: ActivationTransportWorld,
) -> None:
    world = activation_transport_world
    battle = _create_two_owner_battle(world)
    battle_id = battle["battle_id"]
    scopes = {
        battles.BATTLE_READ_SCOPE: True,
        battles.BATTLE_ACT_SCOPE: True,
        battles.BATTLE_INTERRUPT_SCOPE: True,
    }
    _seed_token(
        world,
        owner_user_id=world.ids.p0_user_id,
        raw_token="client-v2-p0",
        scopes=scopes,
    )
    _seed_token(
        world,
        owner_user_id=world.ids.p1_user_id,
        raw_token="client-v2-p1",
        scopes=scopes,
    )
    transports = {
        world.ids.p0_user_id: CountingTestClientTransport(world.p0),
        world.ids.p1_user_id: CountingTestClientTransport(world.p1),
    }
    clients = {
        world.ids.p0_user_id: HttpClient(
            "http://testserver",
            token="client-v2-p0",
            transport=transports[world.ids.p0_user_id],
        ),
        world.ids.p1_user_id: HttpClient(
            "http://testserver",
            token="client-v2-p1",
            transport=transports[world.ids.p1_user_id],
        ),
    }
    player_clients = (
        clients[battle["p1_user_id"]],
        clients[battle["p2_user_id"]],
    )
    player_transports = (
        transports[battle["p1_user_id"]],
        transports[battle["p2_user_id"]],
    )

    checkpoint = player_clients[0].get_state_checkpoint(battle_id)
    controlling_player = checkpoint.state.active_player
    controlling_client = player_clients[controlling_player]
    controlling_transport = player_transports[controlling_player]
    selected_unit_id = next(
        blob.id
        for blob in checkpoint.state.blobs
        if blob.owner_player == controlling_player and blob.id >= 1
    )

    def one_post(transport: CountingTestClientTransport, call):
        before = len(transport.requests)
        try:
            return call()
        finally:
            assert len(transport.requests) == before + 1
            assert transport.requests[-1].method == "POST"

    started = one_post(
        controlling_transport,
        lambda: controlling_client.start_activation(
            battle_id,
            expected_sequence=checkpoint.sequence_at,
            selected_unit_id=selected_unit_id,
        ),
    )
    with pytest.raises(HttpClientActivationError) as duplicate:
        one_post(
            controlling_transport,
            lambda: controlling_client.start_activation(
                battle_id,
                expected_sequence=checkpoint.sequence_at,
                selected_unit_id=selected_unit_id,
            ),
        )
    assert duplicate.value.detail_code == "stale_sequence"
    with world.sessions() as session:
        durable = load_latest_checkpoint(session, battle_id)
        assert durable is not None
        assert durable.sequence_at == started.new_sequence

    started_activation = started.state.activation
    assert started_activation is not None
    started_window = started_activation.window
    assert started_window is not None
    priority_player = started_window.priority_player
    priority_client = player_clients[priority_player]
    priority_transport = player_transports[priority_player]
    next_priority_player = 1 - priority_player
    next_priority_client = player_clients[next_priority_player]
    next_priority_transport = player_transports[next_priority_player]
    priority_units = [
        blob.id
        for blob in started.state.blobs
        if blob.owner_player == priority_player and blob.id >= 1
    ]
    interrupted = one_post(
        priority_transport,
        lambda: priority_client.interrupt(
            battle_id,
            **_client_activation_guards(started),
            source_unit_id=priority_units[-1],
            ability_slug="rozkaz",
            payload={
                "target_id": priority_units[0],
                "ability": "nieustraszony",
                "granted": False,
            },
        ),
    )

    interrupted_activation = interrupted.state.activation
    assert interrupted_activation is not None
    with pytest.raises(HttpClientActivationError) as stale_window:
        one_post(
            priority_transport,
            lambda: priority_client.pass_interrupt_priority(
                battle_id,
                expected_sequence=interrupted.new_sequence,
                activation_id=interrupted_activation.activation_id,
                expected_activation_version=interrupted_activation.version,
                expected_window_version=started_window.version,
            ),
        )
    assert stale_window.value.detail_code == "stale_window"

    first_pass = one_post(
        priority_transport,
        lambda: priority_client.pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(interrupted),
        ),
    )
    with pytest.raises(HttpClientActivationError) as stale_sequence:
        one_post(
            priority_transport,
            lambda: priority_client.pass_interrupt_priority(
                battle_id,
                **_client_activation_guards(interrupted),
            ),
        )
    assert stale_sequence.value.detail_code == "stale_sequence"
    second_pass = one_post(
        next_priority_transport,
        lambda: next_priority_client.pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(first_pass),
        ),
    )

    action_guards = _client_activation_guards(second_pass)
    action_guards.pop("expected_window_version", None)
    first_action = one_post(
        controlling_transport,
        lambda: controlling_client.commit_activation_action(
            battle_id,
            DefendAction(unit_id=selected_unit_id),
            **action_guards,
        ),
    )
    continued = one_post(
        controlling_transport,
        lambda: controlling_client.continue_activation(
            battle_id,
            **_client_activation_guards(first_action),
        ),
    )
    continued_activation = continued.state.activation
    assert continued_activation is not None
    continued_window = continued_activation.window
    assert continued_window is not None
    second_window_priority = continued_window.priority_player
    second_window_next = 1 - second_window_priority
    third_pass = one_post(
        player_transports[second_window_priority],
        lambda: player_clients[
            second_window_priority
        ].pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(continued),
        ),
    )
    fourth_pass = one_post(
        player_transports[second_window_next],
        lambda: player_clients[second_window_next].pass_interrupt_priority(
            battle_id,
            **_client_activation_guards(third_pass),
        ),
    )
    second_action_guards = _client_activation_guards(fourth_pass)
    second_action_guards.pop("expected_window_version", None)
    second_action = one_post(
        controlling_transport,
        lambda: controlling_client.commit_activation_action(
            battle_id,
            DefendAction(unit_id=selected_unit_id),
            **second_action_guards,
        ),
    )

    controlling_owner_id = (
        battle["p1_user_id"] if controlling_player == 0 else battle["p2_user_id"]
    )
    restarted_transport = CountingTestClientTransport(
        world.p0 if controlling_owner_id == world.ids.p0_user_id else world.p1
    )
    restarted_client = HttpClient(
        "http://testserver",
        token="client-v2-p0"
        if controlling_owner_id == world.ids.p0_user_id
        else "client-v2-p1",
        transport=restarted_transport,
    )
    restarted_checkpoint = restarted_client.get_state_checkpoint(battle_id)
    assert restarted_checkpoint.sequence_at == second_action.new_sequence
    assert restarted_checkpoint.state == second_action.state
    finalized = one_post(
        restarted_transport,
        lambda: restarted_client.finalize_activation(
            battle_id,
            expected_sequence=restarted_checkpoint.sequence_at,
            activation_id=restarted_checkpoint.state.activation.activation_id,
            expected_activation_version=restarted_checkpoint.state.activation.version,
            recovery_uses=(),
        ),
    )
    assert finalized.state.activation is None
    assert len(restarted_transport.requests) == 2
