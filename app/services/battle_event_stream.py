"""Bounded, resumable SSE delivery for persisted battle events."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.services.engine.events import BattleEvent as EngineBattleEvent
from app.services.engine.persistence import load_events

DEFAULT_BATCH_SIZE = 100
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS = 15.0
KEEP_ALIVE_FRAME = b": keep-alive\n\n"


class SessionFactory(Protocol):
    def __call__(self) -> Session: ...


EventProjector = Callable[[EngineBattleEvent], dict[str, Any]]
Sleeper = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class BattleEventPoll:
    events: tuple[EngineBattleEvent, ...]
    terminal: bool


def session_factory_from_session(request_session: Session) -> sessionmaker[Session]:
    """Build independent short sessions from the request dependency's database.

    FastAPI 0.110 closes yield dependencies before a ``StreamingResponse`` body
    is sent. Capturing only the bind keeps production and ``get_db`` overrides
    aligned without retaining the request-scoped Session for the stream.
    """
    bind = request_session.get_bind()
    if isinstance(bind, Connection):
        bind = bind.engine
    return sessionmaker(
        bind=bind,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def poll_battle_events(
    session_factory: SessionFactory,
    *,
    battle_id: int,
    cursor: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BattleEventPoll:
    """Read one bounded batch, or check terminal state when the batch is empty.

    A poll with events executes one SELECT. An idle/terminal poll executes the
    bounded event SELECT plus one status SELECT. The Session is always closed
    before an event can be yielded to the network.
    """
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    with session_factory() as session:
        events = tuple(
            load_events(
                session,
                battle_id,
                since=cursor,
                limit=batch_size,
            )
        )
        if events:
            return BattleEventPoll(events=events, terminal=False)

        terminal_state = session.execute(
            select(
                models.Battle.status,
                func.max(models.BattleEvent.sequence),
            )
            .outerjoin(
                models.BattleEvent,
                models.BattleEvent.battle_id == models.Battle.id,
            )
            .where(models.Battle.id == battle_id)
            .group_by(models.Battle.id, models.Battle.status)
        ).one_or_none()
        if terminal_state is None:
            return BattleEventPoll(events=(), terminal=True)

        battle_status, latest_sequence = terminal_state
        return BattleEventPoll(
            events=(),
            terminal=(
                battle_status == "finished"
                and int(latest_sequence or 0) <= cursor
            ),
        )


def encode_battle_event_frame(
    event: EngineBattleEvent,
    *,
    project_event: EventProjector,
) -> bytes:
    """Encode one public event projection as a strict, compact SSE frame."""
    public_event = project_event(event)
    data = json.dumps(
        public_event,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return (
        f"id: {event.sequence}\n"
        "event: battle_event\n"
        f"data: {data}\n\n"
    ).encode("utf-8")


async def stream_battle_events(
    request: Request,
    *,
    session_factory: SessionFactory,
    battle_id: int,
    cursor: int,
    project_event: EventProjector,
    batch_size: int = DEFAULT_BATCH_SIZE,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    keep_alive_interval: float = DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS,
    sleep: Sleeper = asyncio.sleep,
    clock: Clock = time.monotonic,
) -> AsyncIterator[bytes]:
    """Yield backlog then follow the event log until disconnect or completion."""
    if poll_interval < 0:
        raise ValueError("poll_interval must be >= 0")
    if keep_alive_interval <= 0:
        raise ValueError("keep_alive_interval must be > 0")

    current_cursor = cursor
    last_activity = clock()
    while True:
        if await request.is_disconnected():
            return

        poll = poll_battle_events(
            session_factory,
            battle_id=battle_id,
            cursor=current_cursor,
            batch_size=batch_size,
        )
        if poll.events:
            for event in poll.events:
                if await request.is_disconnected():
                    return
                current_cursor = event.sequence
                yield encode_battle_event_frame(event, project_event=project_event)
            last_activity = clock()
            continue

        if poll.terminal:
            return

        now = clock()
        if now - last_activity >= keep_alive_interval:
            yield KEEP_ALIVE_FRAME
            last_activity = now
        await sleep(poll_interval)
