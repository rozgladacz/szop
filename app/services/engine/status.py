"""B3.9.a — Kanoniczne status flagi oddziału (`SZOP_Rozjemca.md pkt 22`).

Single source of truth dla 4 statusów MVP:
- `Aktywowany` (pkt 22.d) — oddział wykonał aktywację w tej rundzie; reset na końcu rundy (pkt 8.c.i)
- `Wyczerpany` (pkt 22.a) — oddział wyczerpał aktywne zdolności/akcje
- `Przyszpilony` (pkt 22.b) — oddział nie kontroluje celów, otrzymuje -1 do obrony
- `Ufortyfikowany` (pkt 22.c) — oddział po Obronie; +1 do obrony, odrzucany na początku własnej aktywacji

Przed B3.9 te same stringi były duplikowane w `effects.py`, `phases.py` i `combat.py` (dziura D
z post-B3 code review). Refactor wprowadza `StatusFlag(str, Enum)` żeby:

1. Mieć jedno miejsce na enumerację (drift-proof — nowy status = nowy `StatusFlag` member).
2. Zachować pełną kompatybilność z istniejącym kodem trzymającym `status_flags: tuple[str, ...]`
   — `StatusFlag` dziedziczy z `str`, więc `"Aktywowany" in (StatusFlag.AKTYWOWANY,) is True`
   i `StatusFlag.AKTYWOWANY == "Aktywowany"` jest True. Tuple może mieszać enum i str
   bez zmiany semantyki porównań.
3. Mieć idempotentne helpery `add_status` / `remove_status` w jednym miejscu — przed B3.9
   były 2 kopie w `phases.py` (`_add_status`/`_remove_status`) + inline `replace(...)` w
   `combat.py` (ścieżka kontrataku).

ADR-0046 (event-sourced mutations, fazy B3.9.d) dodaje obok tego event types
`StatusAdded`/`StatusRemoved` — runtime mutacje statusu pójdą przez te eventy zamiast
bezpośredniego `add_status` na bloba w "live state". Ten moduł zostaje jako podstawa
dla reducerów `apply_events`.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.engine.state import UnitBlob


class StatusFlag(str, Enum):
    """Status oddziału per `SZOP_Rozjemca.md pkt 22`.

    Dziedziczy z `str` żeby `StatusFlag.AKTYWOWANY == "Aktywowany"` było `True` i
    `"Aktywowany" in tuple_of_status_flags` działało niezależnie czy elementy są
    `StatusFlag` czy bare `str` (kontrakt `UnitBlob.status_flags: tuple[str, ...]`).
    """

    AKTYWOWANY = "Aktywowany"
    WYCZERPANY = "Wyczerpany"
    PRZYSZPILONY = "Przyszpilony"
    UFORTYFIKOWANY = "Ufortyfikowany"


# Module-level aliasy dla zwięzłości w call sites (`STATUS_AKTYWOWANY` zamiast
# `StatusFlag.AKTYWOWANY` — jednorazowe imports w `phases.py`/`combat.py`/`effects.py`).
STATUS_AKTYWOWANY: StatusFlag = StatusFlag.AKTYWOWANY
STATUS_WYCZERPANY: StatusFlag = StatusFlag.WYCZERPANY
STATUS_PRZYSZPILONY: StatusFlag = StatusFlag.PRZYSZPILONY
STATUS_UFORTYFIKOWANY: StatusFlag = StatusFlag.UFORTYFIKOWANY


def add_status(blob: "UnitBlob", status: str | StatusFlag) -> "UnitBlob":
    """Idempotentne dodanie statusu do `blob.status_flags`.

    Jeśli `status` już jest w `blob.status_flags` — zwraca `blob` bez zmian (no-op,
    zachowuje identity). W przeciwnym wypadku zwraca nowy blob z appendowanym statusem.

    Akceptuje zarówno `StatusFlag` jak i bare `str` — dla `StatusFlag(str, Enum)`
    porównanie z istniejącymi stringami w tuple jest identity-safe.
    """
    if status in blob.status_flags:
        return blob
    return replace(blob, status_flags=tuple(list(blob.status_flags) + [status]))


def remove_status(blob: "UnitBlob", status: str | StatusFlag) -> "UnitBlob":
    """Idempotentne usunięcie statusu z `blob.status_flags`.

    Jeśli `status` nie ma w `blob.status_flags` — zwraca `blob` bez zmian (no-op).
    W przeciwnym wypadku zwraca nowy blob z filtrowanym tuple.
    """
    if status not in blob.status_flags:
        return blob
    return replace(
        blob, status_flags=tuple(s for s in blob.status_flags if s != status)
    )


__all__ = [
    "StatusFlag",
    "STATUS_AKTYWOWANY",
    "STATUS_WYCZERPANY",
    "STATUS_PRZYSZPILONY",
    "STATUS_UFORTYFIKOWANY",
    "add_status",
    "remove_status",
]
