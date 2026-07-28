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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.battle_protocol import ACTIVATION_PROTOCOL_VERSION_V1
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    BattleEvent as EngineEvent,
    event_to_json,
    json_to_event,
)
from app.services.engine.state import BattleState
from app.services.engine.state_codec import (
    battle_state_from_json,
    battle_state_to_json,
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


class BattleCheckpointSequenceConflict(RuntimeError):
    """Checkpoint sequence does not match the current end of the event log."""

    def __init__(
        self,
        battle_id: int,
        *,
        sequence_at: int,
        latest_sequence: int,
    ) -> None:
        self.battle_id = battle_id
        self.sequence_at = sequence_at
        self.latest_sequence = latest_sequence
        super().__init__(
            "Battle checkpoint sequence conflict for "
            f"battle_id={battle_id}: checkpoint at {sequence_at}, "
            f"latest event sequence {latest_sequence}"
        )


@dataclass(frozen=True, slots=True)
class LoadedBattleCheckpoint:
    """Domain objects restored from one coherent persisted checkpoint."""

    battle_id: int
    sequence_at: int
    state: BattleState
    dice: DeterministicDice


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
    *,
    limit: int | None = None,
) -> list[EngineEvent]:
    """Odczytuje eventy bitwy w kolejności `sequence`, rekonstruując dataclassy.

    Args:
        session: aktywna sesja SQLAlchemy.
        battle_id: id bitwy.
        since: zwraca tylko eventy z `sequence > since` (0 = wszystkie). Dla
            inkrementalnego pollingu (B4 `GET /battles/{id}/events?since=N`).
        limit: opcjonalny maksymalny rozmiar batcha. `None` zachowuje historyczne
            zachowanie bez limitu.

    Returns:
        Lista `events.BattleEvent` (dataclassy) posortowana rosnąco po
        `sequence`. Pusta gdy brak eventów.
    """
    from sqlalchemy import select

    from app.models import BattleEvent as BattleEventRow

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer or None")

    statement = (
        select(BattleEventRow)
        .where(
            BattleEventRow.battle_id == battle_id,
            BattleEventRow.sequence > since,
        )
        .order_by(BattleEventRow.sequence)
    )
    if limit is not None:
        statement = statement.limit(limit)
    rows = session.execute(statement).scalars().all()

    return [json_to_event(json.loads(row.payload_json)) for row in rows]


def save_checkpoint(
    session: "Session",
    battle_id: int,
    sequence_at: int,
    state: BattleState,
    dice: DeterministicDice,
    *,
    state_version: int = ACTIVATION_PROTOCOL_VERSION_V1,
    flush: bool = True,
) -> None:
    """Persist state and RNG iff ``sequence_at`` is the current event-log end.

    The helper is transactionally neutral: it never commits or rolls back.
    Callers should save/flush events first and commit both writes together.
    """
    from app.models import BattleCheckpoint as BattleCheckpointRow

    if type(sequence_at) is not int or sequence_at < 0:
        raise ValueError("sequence_at must be >= 0")
    state_json = _canonical_json(
        battle_state_to_json(state, version=state_version)
    )
    rng_json = _canonical_json(dice.to_checkpoint())
    latest_sequence = latest_event_sequence(session, battle_id)
    if sequence_at != latest_sequence:
        raise BattleCheckpointSequenceConflict(
            battle_id,
            sequence_at=sequence_at,
            latest_sequence=latest_sequence,
        )
    row = BattleCheckpointRow(
        battle_id=battle_id,
        sequence_at=sequence_at,
        state_json=state_json,
        rng_json=rng_json,
    )
    session.add(row)
    if flush:
        session.flush()


def load_latest_checkpoint(
    session: "Session",
    battle_id: int,
) -> LoadedBattleCheckpoint | None:
    """Load the checkpoint exactly matching the current event-log end.

    A stale checkpoint is not resumable because its RNG position may lag behind
    persisted events, so this function returns ``None`` instead of exposing it.
    """
    from sqlalchemy import select

    from app.models import BattleCheckpoint as BattleCheckpointRow

    latest_sequence = latest_event_sequence(session, battle_id)
    row = session.execute(
        select(BattleCheckpointRow).where(
            BattleCheckpointRow.battle_id == battle_id,
            BattleCheckpointRow.sequence_at == latest_sequence,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _decode_checkpoint_row(row)


def load_earliest_checkpoint(
    session: "Session",
    battle_id: int,
) -> LoadedBattleCheckpoint | None:
    """Load the earliest durable checkpoint for one battle."""
    from sqlalchemy import select

    from app.models import BattleCheckpoint as BattleCheckpointRow

    row = session.execute(
        select(BattleCheckpointRow)
        .where(BattleCheckpointRow.battle_id == battle_id)
        .order_by(BattleCheckpointRow.sequence_at)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return _decode_checkpoint_row(row)


def _decode_checkpoint_row(row) -> LoadedBattleCheckpoint:
    """Decode one ORM checkpoint through the shared state and RNG codecs."""
    return LoadedBattleCheckpoint(
        battle_id=row.battle_id,
        sequence_at=row.sequence_at,
        state=battle_state_from_json(json.loads(row.state_json)),
        dice=DeterministicDice.from_checkpoint(json.loads(row.rng_json)),
    )


def _canonical_json(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
