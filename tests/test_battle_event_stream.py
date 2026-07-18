from __future__ import annotations

import asyncio
import json
import re
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

from app import db as db_module
from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from app.services import battle_event_stream as event_stream_service
from app.services.battle_event_stream import (
    KEEP_ALIVE_FRAME,
    encode_battle_event_frame,
    poll_battle_events,
    stream_battle_events,
)
from app.services.engine.events import EffectApplied, StatusAdded
from app.services.engine.persistence import save_events

READ_TOKEN = "sse-read-secret"
WRONG_SCOPE_TOKEN = "sse-wrong-scope-secret"
STRANGER_TOKEN = "sse-stranger-secret"


@dataclass(frozen=True)
class _World:
    app: FastAPI
    client: TestClient
    sessions: Any
    owner_id: int
    stranger_id: int
    battle_id: int
    events: tuple[Any, ...]
    request_session_closes: list[int]


class _RequestProbe:
    def __init__(self) -> None:
        self.disconnected = False
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.disconnected


def _engine_and_sessions():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _add_agent_token(
    session: Session,
    *,
    owner_id: int,
    username: str,
    raw_token: str,
    scopes: dict[str, bool],
) -> None:
    agent = models.User(
        username=username,
        password_hash="unused",
        role=models.USER_ROLE_AGENT,
    )
    session.add(agent)
    session.flush()
    session.add(
        models.AgentToken(
            agent_user_id=agent.id,
            owner_user_id=owner_id,
            token_hash=hash_agent_token(raw_token),
            scope_json=json.dumps(scopes),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
    )


@pytest.fixture
def world() -> _World:
    engine, sessions = _engine_and_sessions()
    stream_events = (
        StatusAdded(sequence=1, target_id=7, status="Aktywowany"),
        EffectApplied(
            sequence=2,
            slug="żółw",
            target_unit_id=7,
            payload={"opis": "Zażółć gęślą jaźń"},
        ),
    )
    with sessions() as session:
        owner = models.User(username="sse-owner", password_hash="unused")
        opponent = models.User(username="sse-opponent", password_hash="unused")
        stranger = models.User(username="sse-stranger", password_hash="unused")
        session.add_all([owner, opponent, stranger])
        session.flush()
        battle = models.Battle(
            p1_user_id=owner.id,
            p2_user_id=opponent.id,
            status="finished",
            rng_seed=2026,
        )
        session.add(battle)
        session.flush()
        save_events(session, battle.id, stream_events)
        _add_agent_token(
            session,
            owner_id=owner.id,
            username="sse-agent-read",
            raw_token=READ_TOKEN,
            scopes={battles.BATTLE_READ_SCOPE: True},
        )
        _add_agent_token(
            session,
            owner_id=owner.id,
            username="sse-agent-wrong",
            raw_token=WRONG_SCOPE_TOKEN,
            scopes={"battle:write": True},
        )
        _add_agent_token(
            session,
            owner_id=stranger.id,
            username="sse-agent-stranger",
            raw_token=STRANGER_TOKEN,
            scopes={battles.BATTLE_READ_SCOPE: True},
        )
        session.commit()
        owner_id = owner.id
        stranger_id = stranger.id
        battle_id = battle.id

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="sse-test-session")

    @test_app.post("/_test/session/{user_id}")
    def set_test_session(user_id: int, request: Request) -> dict[str, int]:
        request.session["user_id"] = user_id
        return {"user_id": user_id}

    test_app.include_router(battles.router)
    request_session_closes: list[int] = []

    def override_get_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()
            request_session_closes.append(id(session))

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as client:
            yield _World(
                app=test_app,
                client=client,
                sessions=sessions,
                owner_id=owner_id,
                stranger_id=stranger_id,
                battle_id=battle_id,
                events=stream_events,
                request_session_closes=request_session_closes,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _bearer_headers(token: str = READ_TOKEN, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def _sse_ids(content: bytes) -> list[int]:
    return [int(value) for value in re.findall(rb"^id: ([0-9]+)$", content, re.M)]


def _expected_frames(events: tuple[Any, ...]) -> bytes:
    frames = []
    for domain_event in events:
        payload = battles._public_event_payload(domain_event)
        data = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        frames.append(
            (
                f"id: {domain_event.sequence}\n"
                "event: battle_event\n"
                f"data: {data}\n\n"
            ).encode("utf-8")
        )
    return b"".join(frames)


def test_events_path_has_exactly_one_get_route(world: _World) -> None:
    matching = [
        route
        for route in world.app.routes
        if getattr(route, "path", "") == "/battles/{battle_id}/events"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(matching) == 1


def test_json_polling_is_unchanged_without_accept_or_with_application_json(
    world: _World,
) -> None:
    path = f"/battles/{world.battle_id}/events?since=1"
    default_response = world.client.get(path, headers=_bearer_headers())
    json_response = world.client.get(
        path,
        headers=_bearer_headers(Accept="application/json"),
    )

    assert default_response.status_code == 200
    assert default_response.headers["content-type"] == "application/json"
    assert default_response.content == json_response.content
    assert default_response.json() == {
        "battle_id": world.battle_id,
        "events": [battles._public_event_payload(world.events[1])],
    }

    from_zero = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(Accept="application/json"),
    )
    assert [item["sequence"] for item in from_zero.json()["events"]] == [1, 2]


def test_finished_sse_has_exact_headers_bytes_unicode_and_terminal_close(
    world: _World,
) -> None:
    response = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(
            Accept="application/json, text/event-stream; q=0.8"
        ),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.content == _expected_frames(world.events)
    assert "Zażółć gęślą jaźń".encode() in response.content
    assert KEEP_ALIVE_FRAME not in response.content


@pytest.mark.parametrize(
    ("query", "last_event_id", "expected_ids"),
    [
        ("", None, [1, 2]),
        ("", "0", [1, 2]),
        ("?since=0", None, [1, 2]),
        ("", "1", [2]),
        ("?since=1", "1", [2]),
        ("", "2", []),
    ],
)
def test_sse_resume_cursor_is_strictly_after_last_seen_event(
    world: _World,
    query: str,
    last_event_id: str | None,
    expected_ids: list[int],
) -> None:
    headers = _bearer_headers(Accept="text/event-stream")
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    response = world.client.get(
        f"/battles/{world.battle_id}/events{query}",
        headers=headers,
    )

    assert response.status_code == 200
    assert _sse_ids(response.content) == expected_ids


def test_sse_rejects_conflicting_explicit_cursors_before_stream(
    world: _World,
) -> None:
    response = world.client.get(
        f"/battles/{world.battle_id}/events?since=0",
        headers=_bearer_headers(
            Accept="text/event-stream",
            **{"Last-Event-ID": "1"},
        ),
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "since and Last-Event-ID cursors must match"}


@pytest.mark.parametrize(
    "last_event_id",
    ["", "-1", "+1", "1.0", "abc", str(1 << 63), "9" * 5000],
)
def test_sse_rejects_invalid_last_event_id_with_stable_400(
    world: _World,
    last_event_id: str,
) -> None:
    response = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(
            Accept="text/event-stream",
            **{"Last-Event-ID": last_event_id},
        ),
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Last-Event-ID must be a non-negative decimal sequence"
    }


def test_last_event_id_does_not_change_json_polling(world: _World) -> None:
    response = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(
            Accept="application/json",
            **{"Last-Event-ID": "not-an-sse-cursor"},
        ),
    )
    assert response.status_code == 200
    assert [item["sequence"] for item in response.json()["events"]] == [1, 2]


def test_sse_rejects_since_outside_database_sequence_range(world: _World) -> None:
    response = world.client.get(
        f"/battles/{world.battle_id}/events?since={1 << 63}",
        headers=_bearer_headers(Accept="text/event-stream"),
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "since cursor is outside the event sequence range"
    }


def test_session_participant_auth_and_no_oracle_404(world: _World) -> None:
    world.client.post(f"/_test/session/{world.owner_id}")
    participant = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers={"Accept": "text/event-stream"},
    )
    assert participant.status_code == 200

    world.client.post(f"/_test/session/{world.stranger_id}")
    stranger = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers={"Accept": "text/event-stream"},
    )
    missing = world.client.get(
        f"/battles/{world.battle_id + 999}/events",
        headers={"Accept": "text/event-stream"},
    )
    assert stranger.status_code == missing.status_code == 404
    assert stranger.content == missing.content


def test_bearer_scope_auth_and_no_oracle_are_checked_at_connect(
    world: _World,
) -> None:
    allowed = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(Accept="text/event-stream"),
    )
    stranger = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(STRANGER_TOKEN, Accept="text/event-stream"),
    )
    missing = world.client.get(
        f"/battles/{world.battle_id + 999}/events",
        headers=_bearer_headers(Accept="text/event-stream"),
    )
    forbidden = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(WRONG_SCOPE_TOKEN, Accept="text/event-stream"),
    )
    unauthenticated = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers={"Accept": "text/event-stream"},
    )

    assert allowed.status_code == 200
    assert stranger.status_code == missing.status_code == 404
    assert stranger.content == missing.content
    assert forbidden.status_code == 403
    assert unauthenticated.status_code == 401


def test_sse_audit_excludes_bearer_and_last_event_id(world: _World) -> None:
    cursor = "987654321"
    response = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(
            Accept="text/event-stream",
            **{"Last-Event-ID": cursor},
        ),
    )
    assert response.status_code == 200

    with world.sessions() as session:
        audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.route == f"/battles/{world.battle_id}/events"
    assert READ_TOKEN not in audit.params_json
    assert cursor not in audit.params_json
    assert "Last-Event-ID" not in audit.params_json


def test_stream_uses_override_database_after_request_session_cleanup(
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_production_session():
        raise AssertionError("production SessionLocal must not be used")

    monkeypatch.setattr(db_module, "SessionLocal", forbidden_production_session)
    original_load_events = event_stream_service.load_events
    close_counts_seen: list[int] = []

    def guarded_load_events(*args, **kwargs):
        close_counts_seen.append(len(world.request_session_closes))
        return original_load_events(*args, **kwargs)

    monkeypatch.setattr(event_stream_service, "load_events", guarded_load_events)
    response = world.client.get(
        f"/battles/{world.battle_id}/events",
        headers=_bearer_headers(Accept="text/event-stream"),
    )

    assert response.status_code == 200
    assert close_counts_seen
    assert all(count >= 1 for count in close_counts_seen)


def test_active_stream_emits_keep_alive_observes_appended_event_and_disconnect() -> None:
    engine, sessions = _engine_and_sessions()
    try:
        with sessions() as session:
            battle = models.Battle(status="active", rng_seed=1)
            session.add(battle)
            session.commit()
            battle_id = battle.id

        request = _RequestProbe()
        now = [0.0]
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            now[0] += 15.0
            if len(sleep_calls) == 2:
                with sessions() as session:
                    save_events(
                        session,
                        battle_id,
                        [StatusAdded(1, 9, "Aktywowany")],
                    )
                    session.commit()

        async def exercise() -> tuple[bytes, bytes]:
            stream = stream_battle_events(
                request,  # type: ignore[arg-type]
                session_factory=sessions,
                battle_id=battle_id,
                cursor=0,
                project_event=battles._public_event_payload,
                poll_interval=0.25,
                keep_alive_interval=15.0,
                sleep=fake_sleep,
                clock=lambda: now[0],
            )
            keep_alive = await anext(stream)
            appended = await anext(stream)
            request.disconnected = True
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            return keep_alive, appended

        keep_alive, appended = asyncio.run(exercise())
        assert keep_alive == KEEP_ALIVE_FRAME
        assert _sse_ids(appended) == [1]
        assert sleep_calls == [0.25, 0.25]
        assert request.calls >= 3
    finally:
        engine.dispose()


def test_bounded_batches_preserve_backlog_order() -> None:
    engine, sessions = _engine_and_sessions()
    try:
        with sessions() as session:
            battle = models.Battle(status="finished", rng_seed=1)
            session.add(battle)
            session.flush()
            save_events(
                session,
                battle.id,
                [StatusAdded(i, i, "Aktywowany") for i in range(1, 6)],
            )
            session.commit()
            battle_id = battle.id

        async def collect() -> list[bytes]:
            return [
                chunk
                async for chunk in stream_battle_events(
                    _RequestProbe(),  # type: ignore[arg-type]
                    session_factory=sessions,
                    battle_id=battle_id,
                    cursor=0,
                    project_event=battles._public_event_payload,
                    batch_size=2,
                )
            ]

        chunks = asyncio.run(collect())
        assert [_sse_ids(chunk)[0] for chunk in chunks] == [1, 2, 3, 4, 5]
    finally:
        engine.dispose()


@pytest.mark.parametrize("event_count", [1, 25])
def test_event_poll_query_count_is_one_regardless_of_batch_event_count(
    event_count: int,
) -> None:
    engine, sessions = _engine_and_sessions()
    try:
        with sessions() as session:
            battle = models.Battle(status="active", rng_seed=1)
            session.add(battle)
            session.flush()
            save_events(
                session,
                battle.id,
                [StatusAdded(i, i, "Aktywowany") for i in range(1, event_count + 1)],
            )
            session.commit()
            battle_id = battle.id

        statements: list[str] = []

        def count_statement(*args) -> None:
            statements.append(args[2])

        event.listen(engine, "before_cursor_execute", count_statement)
        poll = poll_battle_events(
            sessions,
            battle_id=battle_id,
            cursor=0,
            batch_size=100,
        )
        event.remove(engine, "before_cursor_execute", count_statement)

        assert len(poll.events) == event_count
        assert len(statements) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("battle_status", ["active", "finished"])
def test_idle_or_terminal_poll_has_at_most_two_queries(battle_status: str) -> None:
    engine, sessions = _engine_and_sessions()
    try:
        with sessions() as session:
            battle = models.Battle(status=battle_status, rng_seed=1)
            session.add(battle)
            session.commit()
            battle_id = battle.id

        statements: list[str] = []

        def count_statement(*args) -> None:
            statements.append(args[2])

        event.listen(engine, "before_cursor_execute", count_statement)
        poll = poll_battle_events(sessions, battle_id=battle_id, cursor=0)
        event.remove(engine, "before_cursor_execute", count_statement)

        assert poll.events == ()
        assert poll.terminal is (battle_status == "finished")
        assert len(statements) == 2
    finally:
        engine.dispose()


def test_terminal_check_does_not_skip_a_concurrently_visible_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = _engine_and_sessions()
    try:
        with sessions() as session:
            battle = models.Battle(status="finished", rng_seed=1)
            session.add(battle)
            session.flush()
            save_events(session, battle.id, [StatusAdded(1, 1, "Aktywowany")])
            session.commit()
            battle_id = battle.id

        monkeypatch.setattr(event_stream_service, "load_events", lambda *a, **k: [])
        poll = poll_battle_events(sessions, battle_id=battle_id, cursor=0)

        assert poll.events == ()
        assert poll.terminal is False
    finally:
        engine.dispose()


def test_poll_session_closes_on_stream_cancellation() -> None:
    engine, sessions = _engine_and_sessions()
    closes: list[int] = []

    class TrackingSession(Session):
        def close(self) -> None:
            closes.append(id(self))
            super().close()

    tracking_sessions = sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
        future=True,
    )
    try:
        with sessions() as session:
            battle = models.Battle(status="active", rng_seed=1)
            session.add(battle)
            session.commit()
            battle_id = battle.id

        async def cancelled_sleep(_delay: float) -> None:
            raise asyncio.CancelledError

        async def exercise() -> None:
            stream = stream_battle_events(
                _RequestProbe(),  # type: ignore[arg-type]
                session_factory=tracking_sessions,
                battle_id=battle_id,
                cursor=0,
                project_event=battles._public_event_payload,
                sleep=cancelled_sleep,
            )
            with pytest.raises(asyncio.CancelledError):
                await anext(stream)
            await stream.aclose()

        asyncio.run(exercise())
        assert len(closes) == 1
    finally:
        engine.dispose()


def test_poll_session_closes_before_projection_exception() -> None:
    engine, sessions = _engine_and_sessions()
    closes: list[int] = []

    class TrackingSession(Session):
        def close(self) -> None:
            closes.append(id(self))
            super().close()

    tracking_sessions = sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
        future=True,
    )
    try:
        with sessions() as session:
            battle = models.Battle(status="finished", rng_seed=1)
            session.add(battle)
            session.flush()
            save_events(session, battle.id, [StatusAdded(1, 1, "Aktywowany")])
            session.commit()
            battle_id = battle.id

        def broken_projection(_event) -> dict[str, Any]:
            raise RuntimeError("projection failed")

        async def exercise() -> None:
            stream = stream_battle_events(
                _RequestProbe(),  # type: ignore[arg-type]
                session_factory=tracking_sessions,
                battle_id=battle_id,
                cursor=0,
                project_event=broken_projection,
            )
            with pytest.raises(RuntimeError, match="projection failed"):
                await anext(stream)
            await stream.aclose()

        asyncio.run(exercise())
        assert len(closes) == 1
    finally:
        engine.dispose()


def test_sse_encoder_rejects_non_finite_public_json() -> None:
    non_finite = EffectApplied(
        sequence=1,
        slug="bad",
        target_unit_id=1,
        payload={"value": float("nan")},
    )
    with pytest.raises(ValueError, match="Out of range float values"):
        encode_battle_event_frame(
            non_finite,
            project_event=battles._public_event_payload,
        )
