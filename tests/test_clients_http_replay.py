from __future__ import annotations

import copy
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
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from app.services.battle_actions import stage_battle_action
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.persistence import load_latest_checkpoint, save_checkpoint
from app.services.engine.phases import deployment_round, setup_phase
from app.services.engine.state import BattleState
from app.services.engine.state_codec import (
    battle_state_from_json,
    battle_state_to_json,
)
from szop_client import (
    BattleReplayResult,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
)

_RAW_TOKEN = "b5-replay-read-token"


def _state() -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(),
        terrain=(),
    )


def _replay_payload(*, battle_id: int = 42) -> dict[str, Any]:
    return {
        "battle_id": battle_id,
        "base_sequence": 7,
        "replayed_through_sequence": 9,
        "event_count": 2,
        "verified_against_checkpoint": True,
        "state": battle_state_to_json(_state()),
    }


def _json_response(payload: Any, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def test_replay_battle_posts_once_without_body_and_decodes_domain_state() -> None:
    seen: list[HttpRequest] = []
    payload = _replay_payload()

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(payload)

    result = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        transport=transport,
    ).replay_battle(42)

    assert result == BattleReplayResult(
        battle_id=42,
        base_sequence=7,
        replayed_through_sequence=9,
        event_count=2,
        verified_against_checkpoint=True,
        schema="szop.battle_state",
        version=1,
        state=_state(),
    )
    assert isinstance(result.state, BattleState)
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles/42/replay"
    assert request.headers == {
        "Accept": "application/json",
        "Authorization": "Bearer raw-token",
    }
    assert request.body is None


@pytest.mark.parametrize("battle_id", [True, 0, -1, "1"])
def test_replay_battle_rejects_invalid_id_before_transport(battle_id: Any) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError, match="battle_id must be an int >= 1"):
        HttpClient("http://localhost", transport=transport).replay_battle(battle_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("battle_id", True),
        ("battle_id", 0),
        ("base_sequence", True),
        ("base_sequence", -1),
        ("replayed_through_sequence", True),
        ("replayed_through_sequence", -1),
        ("event_count", True),
        ("event_count", -1),
        ("verified_against_checkpoint", False),
        ("verified_against_checkpoint", 1),
        ("schema", ""),
        ("schema", None),
        ("version", True),
        ("version", 0),
        ("state", {}),
    ],
)
def test_public_replay_result_rejects_invalid_values(field: str, value: Any) -> None:
    values = {
        "battle_id": 42,
        "base_sequence": 7,
        "replayed_through_sequence": 9,
        "event_count": 2,
        "verified_against_checkpoint": True,
        "schema": "szop.battle_state",
        "version": 1,
        "state": _state(),
    }
    values[field] = value

    with pytest.raises(ValueError):
        BattleReplayResult(**values)


def test_public_replay_result_rejects_inconsistent_sequence_relation() -> None:
    with pytest.raises(ValueError, match=r"base_sequence \+ event_count"):
        BattleReplayResult(
            battle_id=42,
            base_sequence=7,
            replayed_through_sequence=10,
            event_count=2,
            verified_against_checkpoint=True,
            schema="szop.battle_state",
            version=1,
            state=_state(),
        )


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _delete_path(payload: dict[str, Any], path: tuple[str, ...]) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


@pytest.mark.parametrize(
    ("operation", "path", "value"),
    [
        ("delete", ("event_count",), None),
        ("set", ("unexpected",), "field"),
        ("set", ("battle_id",), 43),
        ("set", ("battle_id",), True),
        ("set", ("base_sequence",), True),
        ("set", ("base_sequence",), -1),
        ("set", ("replayed_through_sequence",), True),
        ("set", ("replayed_through_sequence",), -1),
        ("set", ("replayed_through_sequence",), 10),
        ("set", ("event_count",), True),
        ("set", ("event_count",), -1),
        ("set", ("verified_against_checkpoint",), False),
        ("set", ("verified_against_checkpoint",), 1),
        ("set", ("verified_against_checkpoint",), "true"),
        ("set", ("state",), []),
        ("delete", ("state", "schema"), None),
        ("set", ("state", "unexpected"), "field"),
        ("set", ("state", "schema"), ""),
        ("set", ("state", "schema"), "unknown.battle_state"),
        ("set", ("state", "version"), True),
        ("set", ("state", "version"), 0),
        ("set", ("state", "version"), 999),
        ("set", ("state", "state"), {"$dataclass": "Unknown", "fields": {}}),
        ("set", ("rng_json",), {"seed": "secret"}),
        ("set", ("random_state",), "secret"),
        ("set", ("token",), "secret"),
        ("set", ("state", "rng"), {"seed": "secret"}),
        ("set", ("state", "state", "random_state"), "secret"),
    ],
)
def test_replay_battle_rejects_malformed_or_secret_bearing_payload(
    operation: str,
    path: tuple[str, ...],
    value: Any,
) -> None:
    payload = copy.deepcopy(_replay_payload())
    if operation == "delete":
        _delete_path(payload, path)
    else:
        _set_path(payload, path, value)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(HttpClientError, match="malformed payload"):
        HttpClient("http://localhost", transport=transport).replay_battle(42)


def test_replay_battle_rejects_non_object_root() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response([])

    with pytest.raises(HttpClientError, match="malformed payload"):
        HttpClient("http://localhost", transport=transport).replay_battle(42)


@pytest.mark.parametrize("status_code", [401, 403, 404, 409, 413])
def test_replay_battle_preserves_http_status_without_retry(status_code: int) -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response({"detail": "unavailable"}, status_code=status_code)

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient(
            "http://localhost",
            token="secret-token",
            transport=transport,
        ).replay_battle(42)

    assert exc_info.value.status_code == status_code
    assert len(seen) == 1
    assert "secret-token" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)


def test_public_replay_result_import_stays_lazy_for_db_orm_and_costs() -> None:
    code = (
        "import sys; import szop_client; "
        "assert szop_client.BattleReplayResult.__module__ == 'szop_client.types'; "
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
        self.responses: list[HttpResponse] = []

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
        decoded = HttpResponse(
            status_code=response.status_code,
            body=response.content,
        )
        self.responses.append(decoded)
        return decoded


@dataclass(frozen=True, slots=True)
class _RealReplayWorld:
    sessions: sessionmaker[Session]
    transport: _TestClientTransport
    http: HttpClient
    battle_id: int
    owner_id: int
    base_state: BattleState


def _engine_state() -> BattleState:
    state = setup_phase(
        [
            {
                "owner_player": 0,
                "units": [
                    {"id": 1, "position": (0, 0), "models": 3, "toughness": 10}
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {"id": 2, "position": (12, 0), "models": 3, "toughness": 10}
                ],
            },
        ],
        initiative_player=0,
    )
    state, _ = deployment_round(state, ())
    return state


@pytest.fixture
def real_replay_world() -> _RealReplayWorld:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        future=True,
    )
    base_state = _engine_state()
    with sessions() as session:
        owner = models.User(username="client-replay-owner", password_hash="x")
        opponent = models.User(
            username="client-replay-opponent",
            password_hash="x",
        )
        agent = models.User(
            username="client-replay-agent",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        session.add_all([owner, opponent, agent])
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
        session.add(
            models.AgentToken(
                agent_user_id=agent.id,
                owner_user_id=owner.id,
                token_hash=hash_agent_token(_RAW_TOKEN),
                scope_json=json.dumps({battles.BATTLE_READ_SCOPE: True}),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(days=1),
            )
        )
        session.commit()
        battle_id = battle.id
        owner_id = owner.id

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="client-replay-test")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as api_client:
            transport = _TestClientTransport(api_client)
            yield _RealReplayWorld(
                sessions=sessions,
                transport=transport,
                http=HttpClient(
                    "http://testserver",
                    token=_RAW_TOKEN,
                    transport=transport,
                ),
                battle_id=battle_id,
                owner_id=owner_id,
                base_state=base_state,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _append_real_action(world: _RealReplayWorld):
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


def _domain_snapshot(world: _RealReplayWorld) -> tuple[Any, ...]:
    with world.sessions() as session:
        battle = session.get(models.Battle, world.battle_id)
        events = session.scalars(
            select(models.BattleEvent)
            .where(models.BattleEvent.battle_id == world.battle_id)
            .order_by(models.BattleEvent.sequence)
        )
        checkpoints = session.scalars(
            select(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == world.battle_id)
            .order_by(models.BattleCheckpoint.sequence_at)
        )
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
                (row.sequence, row.event_type, row.payload_json) for row in events
            ),
            tuple(
                (row.sequence_at, row.state_json, row.rng_json)
                for row in checkpoints
            ),
        )


def test_real_replay_after_durable_action_is_typed_single_post_and_read_only(
    real_replay_world: _RealReplayWorld,
) -> None:
    prepared = _append_real_action(real_replay_world)
    before = _domain_snapshot(real_replay_world)
    requests_before = len(real_replay_world.transport.requests)

    result = real_replay_world.http.replay_battle(real_replay_world.battle_id)

    assert len(real_replay_world.transport.requests) == requests_before + 1
    request = real_replay_world.transport.requests[-1]
    assert request.method == "POST"
    assert request.body is None
    assert "Content-Type" not in request.headers
    assert request.headers["Authorization"] == f"Bearer {_RAW_TOKEN}"
    raw_payload = json.loads(real_replay_world.transport.responses[-1].body)
    assert result == BattleReplayResult(
        battle_id=real_replay_world.battle_id,
        base_sequence=0,
        replayed_through_sequence=prepared.new_sequence,
        event_count=len(prepared.events),
        verified_against_checkpoint=True,
        schema=raw_payload["state"]["schema"],
        version=raw_payload["state"]["version"],
        state=prepared.state,
    )
    assert battle_state_from_json(raw_payload["state"]) == result.state
    with real_replay_world.sessions() as session:
        current = load_latest_checkpoint(session, real_replay_world.battle_id)
        assert current is not None
        assert current.state == result.state
        assert current.sequence_at == result.replayed_through_sequence
    assert _domain_snapshot(real_replay_world) == before


def test_real_replay_zero_tail_returns_base_checkpoint_without_domain_writes(
    real_replay_world: _RealReplayWorld,
) -> None:
    before = _domain_snapshot(real_replay_world)

    result = real_replay_world.http.replay_battle(real_replay_world.battle_id)

    assert len(real_replay_world.transport.requests) == 1
    assert result.base_sequence == 0
    assert result.replayed_through_sequence == 0
    assert result.event_count == 0
    assert result.state == real_replay_world.base_state
    assert _domain_snapshot(real_replay_world) == before
