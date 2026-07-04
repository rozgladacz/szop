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


class BattleEventSequenceConflict(RuntimeError):
    """Event stream changed since the caller read its latest sequence."""

    def __init__(
        self,
        battle_id: int,
        *,
        expected_latest_sequence: int,
        actual_latest_sequence: int,
    ) -> None:
        self.battle_id = battle_id
        self.expected_latest_sequence = expected_latest_sequence
        self.actual_latest_sequence = actual_latest_sequence
        super().__init__(
            "Battle event sequence conflict for "
            f"battle_id={battle_id}: expected latest "
            f"{expected_latest_sequence}, actual latest {actual_latest_sequence}"
        )


def latest_event_sequence(session: "Session", battle_id: int) -> int:
    """Zwraca największy zapisany `sequence` dla bitwy albo 0 dla pustego logu."""
    from sqlalchemy import func, select

    from app.models import BattleEvent as BattleEventRow

    value = session.execute(
        select(func.max(BattleEventRow.sequence)).where(
            BattleEventRow.battle_id == battle_id
        )
    ).scalar_one()
    return int(value or 0)


def save_events(
    session: "Session",
    battle_id: int,
    events: "tuple[EngineEvent, ...] | list[EngineEvent]",
    *,
    flush: bool = True,
    expected_latest_sequence: int | None = None,
) -> int:
    """Dopisuje `events` do `battle_events` dla danej bitwy (append-only).

    Każdy event → jeden wiersz `BattleEvent` ORM: `event_type` =
    `type(e).__name__`, `payload_json` = `json.dumps(event_to_json(e))`,
    `sequence` = `e.sequence`. NIE commituje (caller zarządza transakcją).
    Gdy `expected_latest_sequence` jest podane, funkcja najpierw sprawdza, czy
    aktualny koniec strumienia nadal ma tę wartość, oraz wymaga by nowe eventy
    były dokładnie kolejnym ciągłym ogonem (`expected+1...`). To precondition dla
    przyszłych write endpointów B4; DB `UniqueConstraint` nadal broni przed
    wyścigiem między sprawdzeniem i INSERT-em.

    Args:
        session: aktywna sesja SQLAlchemy.
        battle_id: id bitwy (FK `battles.id`).
        events: sekwencja engine eventów (`events.BattleEvent` union).
        flush: gdy True (default) wymusza `session.flush()` — INSERT trafia do
            bazy i egzekwuje `UniqueConstraint(battle_id, sequence)` (duplikat
            → `IntegrityError`) bez commitu.
        expected_latest_sequence: opcjonalny optimistic-lock guard. Jeśli
            aktualny max sequence różni się od oczekiwanego, rzuca
            `BattleEventSequenceConflict` bez dopisywania eventów.

    Returns:
        Liczba zapisanych wierszy.
    """
    # Lokalny import — unika cyklu engine→models→db przy starcie pakietu engine.
    from app.models import BattleEvent as BattleEventRow

    if expected_latest_sequence is not None:
        if expected_latest_sequence < 0:
            raise ValueError("expected_latest_sequence must be >= 0")
        actual = latest_event_sequence(session, battle_id)
        if actual != expected_latest_sequence:
            raise BattleEventSequenceConflict(
                battle_id,
                expected_latest_sequence=expected_latest_sequence,
                actual_latest_sequence=actual,
            )
        expected_sequences = range(
            expected_latest_sequence + 1,
            expected_latest_sequence + 1 + len(events),
        )
        if [event.sequence for event in events] != list(expected_sequences):
            raise ValueError(
                "guarded save_events requires contiguous event sequences after "
                "expected_latest_sequence"
            )

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
