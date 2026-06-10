"""B2 — Persystencja event-store (ADR-0010 / ADR-0046 / ADR-0050).

Warstwa-granica między czystym silnikiem (state/phases/combat — zero DB) a
bazą. Jedyny moduł `engine/` dotykający ORM. Zapisuje strumień
`events.BattleEvent` (16 typów) do tabeli `battle_events` i odczytuje go z
powrotem, rekonstruując dataclassy przez serializer z `events.py`.

Inwariant round-trip (GATE, ADR-0010):

    save_events(session, bid, evs)
    loaded = load_events(session, bid)
    apply_events(initial_state, loaded) == live_state_after_apply

Czyli: persystencja NIE traci informacji — replay z bazy jest bit-perfect
względem replayu in-memory. `payload_json` to `json.dumps(event_to_json(e))`;
pola `tuple` round-trip'ują przez list (JSON) z powrotem do tuple w
`json_to_event`.

Funkcje są **transakcyjnie neutralne** — NIE commitują. Caller (router B4 /
LocalClient B5 / test) zarządza transakcją. `save_events(flush=True)` wymusza
INSERT (egzekwując `UniqueConstraint(battle_id, sequence)`) bez commitu.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.services.engine.events import (
    BattleEvent as EngineEvent,
    event_to_json,
    json_to_event,
)

if TYPE_CHECKING:  # pragma: no cover - tylko type hints
    from sqlalchemy.orm import Session


def save_events(
    session: "Session",
    battle_id: int,
    events: "tuple[EngineEvent, ...] | list[EngineEvent]",
    *,
    flush: bool = True,
) -> int:
    """Dopisuje `events` do `battle_events` dla danej bitwy (append-only).

    Każdy event → jeden wiersz `BattleEvent` ORM: `event_type` =
    `type(e).__name__`, `payload_json` = `json.dumps(event_to_json(e))`,
    `sequence` = `e.sequence`. NIE commituje (caller zarządza transakcją).

    Args:
        session: aktywna sesja SQLAlchemy.
        battle_id: id bitwy (FK `battles.id`).
        events: sekwencja engine eventów (`events.BattleEvent` union).
        flush: gdy True (default) wymusza `session.flush()` — INSERT trafia do
            bazy i egzekwuje `UniqueConstraint(battle_id, sequence)` (duplikat
            → `IntegrityError`) bez commitu.

    Returns:
        Liczba zapisanych wierszy.
    """
    # Lokalny import — unika cyklu engine→models→db przy starcie pakietu engine.
    from app.models import BattleEvent as BattleEventRow

    count = 0
    for event in events:
        row = BattleEventRow(
            battle_id=battle_id,
            sequence=event.sequence,
            event_type=type(event).__name__,
            payload_json=json.dumps(event_to_json(event)),
        )
        session.add(row)
        count += 1
    if flush and count:
        session.flush()
    return count


def load_events(
    session: "Session",
    battle_id: int,
    since: int = 0,
) -> list[EngineEvent]:
    """Odczytuje eventy bitwy w kolejności `sequence`, rekonstruując dataclassy.

    Args:
        session: aktywna sesja SQLAlchemy.
        battle_id: id bitwy.
        since: zwraca tylko eventy z `sequence > since` (0 = wszystkie). Dla
            inkrementalnego pollingu (B4 `GET /battles/{id}/events?since=N`).

    Returns:
        Lista `events.BattleEvent` (dataclassy) posortowana rosnąco po
        `sequence`. Pusta gdy brak eventów.
    """
    from sqlalchemy import select

    from app.models import BattleEvent as BattleEventRow

    rows = session.execute(
        select(BattleEventRow)
        .where(
            BattleEventRow.battle_id == battle_id,
            BattleEventRow.sequence > since,
        )
        .order_by(BattleEventRow.sequence)
    ).scalars().all()

    return [json_to_event(json.loads(row.payload_json)) for row in rows]
