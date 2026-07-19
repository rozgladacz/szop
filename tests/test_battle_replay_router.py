from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from app.services import battle_replay as battle_replay_service
from app.services.battle_actions import stage_battle_action
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import StatusAdded
from app.services.engine.persistence import save_checkpoint, save_events
from app.services.engine.phases import deployment_round, setup_phase
from app.services.engine.state import apply_events
from app.services.engine.state_codec import battle_state_from_json

READ_TOKEN = "replay-read-secret"
WRONG_SCOPE_TOKEN = "replay-wrong-scope-secret"
STRANGER_TOKEN = "replay-stranger-secret"


@dataclass(frozen=True)
class ReplayWorld:
    app: FastAPI
    client: TestClient
    engine: Any
    sessions: Any
    owner_id: int
    opponent_id: int
    stranger_id: int
    battle_id: int
    base_state: Any


def _engine_state():
    state = setup_phase(
        [
            {
                "owner_player": 0,
                "units": [
                    {
                        "id": 1,
                        "position": (0, 0),
                        "models": 3,
                        "toughness": 10,
                    }
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {
                        "id": 2,
                        "position": (12, 0),
                        "models": 3,
                        "toughness": 10,
                    }
                ],
            },
        ],
        initiative_player=0,
    )
    state, _ = deployment_round(state, ())
    return state


def _add_agent_token(
    session: Session,
    *,
    owner_id: int,
    username: str,
    raw_token: str,
    scopes: dict[str, bool],
) -> None:
    agent_user = models.User(
        username=username,
        password_hash="unused",
        role=models.USER_ROLE_AGENT,
    )
    session.add(agent_user)
    session.flush()
    session.add(
        models.AgentToken(
            agent_user_id=agent_user.id,
            owner_user_id=owner_id,
            token_hash=hash_agent_token(raw_token),
            scope_json=json.dumps(scopes),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
    )


@pytest.fixture
def replay_world() -> ReplayWorld:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    base_state = _engine_state()

    with sessions() as session:
        owner = models.User(username="replay-owner", password_hash="unused")
        opponent = models.User(username="replay-opponent", password_hash="unused")
        stranger = models.User(username="replay-stranger", password_hash="unused")
        session.add_all([owner, opponent, stranger])
        session.flush()
        battle = models.Battle(
            p1_user_id=owner.id,
            p2_user_id=opponent.id,
            status="active",
            current_round=base_state.round,
            rng_seed=2026,
        )
        session.add(battle)
        session.flush()
        save_checkpoint(
            session,
            battle.id,
            0,
            base_state,
            DeterministicDice(seed=battle.rng_seed),
        )
        _add_agent_token(
            session,
            owner_id=owner.id,
            username="replay-agent-read",
            raw_token=READ_TOKEN,
            scopes={battles.BATTLE_READ_SCOPE: True},
        )
        _add_agent_token(
            session,
            owner_id=owner.id,
            username="replay-agent-wrong",
            raw_token=WRONG_SCOPE_TOKEN,
            scopes={"battle:write": True},
        )
        _add_agent_token(
            session,
            owner_id=stranger.id,
            username="replay-agent-stranger",
            raw_token=STRANGER_TOKEN,
            scopes={battles.BATTLE_READ_SCOPE: True},
        )
        session.commit()
        owner_id = owner.id
        opponent_id = opponent.id
        stranger_id = stranger.id
        battle_id = battle.id

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="replay-test-session")

    @test_app.post("/_test/session/{user_id}")
    def set_test_session(user_id: int, request: Request) -> dict[str, int]:
        request.session["user_id"] = user_id
        return {"user_id": user_id}

    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as client:
            yield ReplayWorld(
                app=test_app,
                client=client,
                engine=engine,
                sessions=sessions,
                owner_id=owner_id,
                opponent_id=opponent_id,
                stranger_id=stranger_id,
                battle_id=battle_id,
                base_state=base_state,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _login(world: ReplayWorld, user_id: int) -> None:
    response = world.client.post(f"/_test/session/{user_id}")
    assert response.status_code == 200


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _append_real_action(world: ReplayWorld):
    with world.sessions() as session:
        battle = session.get(models.Battle, world.battle_id)
        prepared = stage_battle_action(
            session,
            battle=battle,
            actor_user_id=world.owner_id,
            expected_sequence=0,
            action_payload=action_to_json(DefendAction(unit_id=1)),
        )
        session.commit()
        return prepared


def _domain_snapshot(world: ReplayWorld) -> tuple[Any, ...]:
    with world.sessions() as session:
        battle = session.get(models.Battle, world.battle_id)
        event_rows = session.execute(
            select(models.BattleEvent)
            .where(models.BattleEvent.battle_id == world.battle_id)
            .order_by(models.BattleEvent.sequence)
        ).scalars()
        checkpoint_rows = session.execute(
            select(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == world.battle_id)
            .order_by(models.BattleCheckpoint.sequence_at)
        ).scalars()
        return (
            (
                battle.p1_user_id,
                battle.p2_user_id,
                battle.current_round,
                battle.status,
                battle.winner_user_id,
                battle.rng_seed,
            ),
            tuple(
                (row.sequence, row.event_type, row.payload_json)
                for row in event_rows
            ),
            tuple(
                (row.sequence_at, row.state_json, row.rng_json)
                for row in checkpoint_rows
            ),
        )


def _decode_response_state(payload: dict[str, Any]):
    return battle_state_from_json(payload["state"])


def test_replay_route_is_unique_and_declares_no_request_body(
    replay_world: ReplayWorld,
) -> None:
    matching_routes = [
        route
        for route in replay_world.app.routes
        if getattr(route, "path", "") == "/battles/{battle_id}/replay"
        and "POST" in getattr(route, "methods", set())
    ]
    assert len(matching_routes) == 1
    operation = replay_world.app.openapi()["paths"]["/battles/{battle_id}/replay"][
        "post"
    ]
    assert "requestBody" not in operation


def test_session_participant_replays_real_action_without_domain_writes_or_rng(
    replay_world: ReplayWorld,
) -> None:
    prepared = _append_real_action(replay_world)
    before = _domain_snapshot(replay_world)
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "battle_id",
        "base_sequence",
        "replayed_through_sequence",
        "event_count",
        "verified_against_checkpoint",
        "state",
    }
    assert set(payload["state"]) == {"schema", "version", "state"}
    assert payload["battle_id"] == replay_world.battle_id
    assert payload["base_sequence"] == 0
    assert payload["replayed_through_sequence"] == prepared.new_sequence
    assert payload["event_count"] == len(prepared.events)
    assert payload["verified_against_checkpoint"] is True
    assert _decode_response_state(payload) == prepared.state
    serialized = json.dumps(payload, sort_keys=True)
    assert "rng_json" not in serialized
    assert "random_state" not in serialized
    assert _domain_snapshot(replay_world) == before


def test_replay_accepts_current_base_checkpoint_with_zero_events(
    replay_world: ReplayWorld,
) -> None:
    _login(replay_world, replay_world.opponent_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 200
    assert response.json()["base_sequence"] == 0
    assert response.json()["replayed_through_sequence"] == 0
    assert response.json()["event_count"] == 0
    assert _decode_response_state(response.json()) == replay_world.base_state


def test_replay_accepts_battle_read_agent_and_body_blind_audits(
    replay_world: ReplayWorld,
) -> None:
    before = _domain_snapshot(replay_world)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay",
        headers=_bearer(READ_TOKEN),
    )

    assert response.status_code == 200
    with replay_world.sessions() as session:
        audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    audit_payload = json.loads(audit.params_json)
    assert audit.route == f"/battles/{replay_world.battle_id}/replay"
    assert audit_payload == {
        "method": "POST",
        "path_params": {"battle_id": str(replay_world.battle_id)},
        "query_params": {},
        "scope": battles.BATTLE_READ_SCOPE,
        "status": "authorized",
    }
    assert READ_TOKEN not in audit.params_json
    assert "body" not in audit.params_json
    assert _domain_snapshot(replay_world) == before


def test_replay_auth_and_participant_scope_preserve_no_oracle(
    replay_world: ReplayWorld,
) -> None:
    path = f"/battles/{replay_world.battle_id}/replay"
    assert replay_world.client.post(path).status_code == 401
    assert (
        replay_world.client.post(path, headers=_bearer(WRONG_SCOPE_TOKEN)).status_code
        == 403
    )

    stranger_agent = replay_world.client.post(
        path,
        headers=_bearer(STRANGER_TOKEN),
    )
    assert stranger_agent.status_code == 404

    _login(replay_world, replay_world.stranger_id)
    foreign = replay_world.client.post(path)
    _login(replay_world, replay_world.owner_id)
    missing = replay_world.client.post(
        f"/battles/{replay_world.battle_id + 999}/replay"
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("missing", ["all", "current"])
def test_replay_missing_required_checkpoint_is_stable_conflict(
    replay_world: ReplayWorld,
    missing: str,
) -> None:
    if missing == "current":
        prepared = _append_real_action(replay_world)
    with replay_world.sessions() as session:
        statement = select(models.BattleCheckpoint).where(
            models.BattleCheckpoint.battle_id == replay_world.battle_id
        )
        checkpoints = session.execute(statement).scalars().all()
        for checkpoint in checkpoints:
            if missing == "all" or checkpoint.sequence_at == prepared.new_sequence:
                session.delete(checkpoint)
        session.commit()
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Battle replay could not be verified"}


def test_replay_gap_is_stable_conflict(replay_world: ReplayWorld) -> None:
    gap_event = StatusAdded(sequence=2, target_id=1, status="Aktywowany")
    current_state = apply_events(replay_world.base_state, [gap_event])
    with replay_world.sessions() as session:
        save_events(session, replay_world.battle_id, [gap_event])
        save_checkpoint(
            session,
            replay_world.battle_id,
            2,
            current_state,
            DeterministicDice(seed=2026),
        )
        session.commit()
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Battle replay could not be verified"}


def test_replay_checkpoint_mismatch_is_stable_conflict(
    replay_world: ReplayWorld,
) -> None:
    _append_real_action(replay_world)
    with replay_world.sessions() as session:
        checkpoints = session.execute(
            select(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == replay_world.battle_id)
            .order_by(models.BattleCheckpoint.sequence_at)
        ).scalars().all()
        checkpoints[-1].state_json = checkpoints[0].state_json
        session.commit()
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Battle replay could not be verified"}


def test_replay_corrupt_event_is_stable_conflict(replay_world: ReplayWorld) -> None:
    _append_real_action(replay_world)
    with replay_world.sessions() as session:
        event_row = session.execute(
            select(models.BattleEvent)
            .where(models.BattleEvent.battle_id == replay_world.battle_id)
            .order_by(models.BattleEvent.sequence)
        ).scalars().first()
        event_row.payload_json = "{invalid-json"
        session.commit()
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Battle replay could not be verified"}


def test_replay_reducer_failure_is_stable_conflict(
    replay_world: ReplayWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _append_real_action(replay_world)

    def fail_reducer(*_args, **_kwargs):
        raise RuntimeError("internal reducer detail")

    monkeypatch.setattr(battle_replay_service, "apply_events", fail_reducer)
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Battle replay could not be verified"}
    assert "internal reducer detail" not in response.text


def test_replay_event_cap_is_413_and_loads_only_limit_plus_one(
    replay_world: ReplayWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, int] = {}

    def oversized_events(_db, _battle_id, since=0, *, limit=None):
        observed["since"] = since
        observed["limit"] = limit
        return [
            StatusAdded(sequence=i, target_id=1, status="Aktywowany")
            for i in range(1, limit + 1)
        ]

    monkeypatch.setattr(battle_replay_service, "load_events", oversized_events)
    _login(replay_world, replay_world.owner_id)

    response = replay_world.client.post(
        f"/battles/{replay_world.battle_id}/replay"
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Battle replay exceeds event limit"}
    assert observed == {
        "since": 0,
        "limit": battle_replay_service.MAX_REPLAY_EVENTS + 1,
    }


def test_replay_service_has_fixed_four_select_query_shape(
    replay_world: ReplayWorld,
) -> None:
    prepared = _append_real_action(replay_world)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(replay_world.engine, "before_cursor_execute", capture_statement)
    try:
        with replay_world.sessions() as session:
            replayed = battle_replay_service.replay_battle_state(
                session,
                battle_id=replay_world.battle_id,
            )
    finally:
        event.remove(replay_world.engine, "before_cursor_execute", capture_statement)

    assert replayed.event_count == len(prepared.events)
    assert len(statements) == 4
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert sum("battle_checkpoints" in statement for statement in statements) == 2
    assert sum("battle_events" in statement for statement in statements) == 2
    event_batch = next(
        statement
        for statement in statements
        if "FROM battle_events" in statement and "ORDER BY" in statement
    )
    assert "LIMIT" in event_batch
