"""B3.5 — Interrupt manager (`SZOP_Rozjemca.md pkt 12` + ADR-0015).

4 zamknięte punkty przerwań per ADR-0015:
- `ACTIVATION_START` — przed pierwszą akcją oddziału aktywowanego (Strażnik id 31
  najczęściej tu)
- `AFTER_ACTION` — po wykonaniu akcji (pkt 14)
- `BEFORE_REGROUP` — przed testem Przegrupowania (pkt 20)
- `AFTER_REGROUP` — po Przegrupowaniu, przed Odzyskiwaniem ran (pkt 21)

Rozróżnienie z reactive window (ADR-0015a):
- **Reactive window** żyje wewnątrz Ataku (combat.py) — kontratak w Szarży.
- **Interrupt** żyje na granicy fazach gry (`InterruptPoint`) — Rozkaz, Klątwa,
  Oznaczenie, Usprawnienie, Strażnik, Koordynacja, Przekaźnik, Mag (gdy czar
  jest przerwaniem), Łatanie/Mobilizacja/Presja (gdy używane w cudzej aktywacji).

Constraint per ADR-0015: **interrupt nie generuje nowego punktu przerwania**.
Wewnątrz handler-a interrupta nie wywołujemy `trigger_at_point` rekurencyjnie —
inaczej pętle nieskończone.

Per-rundowe limity (np. "Raz na rundę" w Rozkaz) tracked przez engine higher-level
(np. `BattleState.used_interrupts_this_round: tuple[int, ...]` — TODO B3.6). MVP:
limit nie jest enforce'owany w manager — handler sprawdza sam (jeśli ma per-round
state, użyje payload `InterruptEvent`).

MVP scope:
- `InterruptPoint` enum (4 wartości)
- `register_interrupt_handler(point, slug)` decorator
- `get_eligible_interrupts(state, point)` — lista (blob, slug) which CAN trigger
- `trigger_interrupt(...)` — wywołuje konkretny handler
- 1 example handler: Strażnik (id 31) stub — emit `InterruptTriggered` event tylko
  (faktyczny Ostrzał wywoła się przez `resolve_ranged_attack` w B3.6 phases)

Konkretne interrupt handlers (z faktycznym engine-impact) idą do B3.6+ wraz z
integracją w `phases.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from app.services.engine.events import BattleEvent, InterruptTriggered
from app.services.engine.state import BattleState, UnitBlob


class InterruptPoint(Enum):
    """4 zamknięte punkty przerwań per ADR-0015."""

    ACTIVATION_START = "activation_start"
    AFTER_ACTION = "after_action"
    BEFORE_REGROUP = "before_regroup"
    AFTER_REGROUP = "after_regroup"


@dataclass(frozen=True, slots=True)
class InterruptContext:
    """Context dla interrupt handler.

    `state` = aktualny BattleState (read-only). `point` = w którym z 4 punktów.
    `active_unit_id` = oddział obecnie aktywowany (jeśli applicable; None dla
    między-rundowych). `source_unit_id` = oddział wywołujący interrupt (with
    eligible passive ability).
    """

    state: BattleState
    point: InterruptPoint
    source_unit_id: int
    active_unit_id: int | None = None


# Handler signature: (context, **kwargs) → (new_state, events)
InterruptHandlerFn = Callable[
    [InterruptContext, dict[str, Any]],
    tuple[BattleState, tuple[BattleEvent, ...]],
]

# Registry: (point, slug) → handler
_INTERRUPT_HANDLERS: dict[tuple[InterruptPoint, str], InterruptHandlerFn] = {}


def register_interrupt_handler(
    point: InterruptPoint, slug: str
) -> Callable[[InterruptHandlerFn], InterruptHandlerFn]:
    """Decorator — rejestruje handler dla (point, slug).

    Użycie::

        @register_interrupt_handler(InterruptPoint.ACTIVATION_START, "straznik")
        def _straznik_handler(context, payload):
            ...
    """

    def decorator(fn: InterruptHandlerFn) -> InterruptHandlerFn:
        key = (point, slug)
        if key in _INTERRUPT_HANDLERS:
            raise RuntimeError(
                f"Interrupt handler for {point.value}/{slug!r} already registered"
            )
        _INTERRUPT_HANDLERS[key] = fn
        return fn

    return decorator


def get_eligible_interrupts(
    state: BattleState,
    point: InterruptPoint,
) -> list[tuple[UnitBlob, str]]:
    """Zwraca listę (blob, slug) — oddziały z aktywnymi interrupt abilities w tym punkcie.

    Filtr: tylko `models_alive > 0` (pokonane oddziały nie mogą wywoływać interruptów).
    Per-rundowe limity (np. "Raz na rundę") sprawdzane wewnątrz handler-ów (MVP)
    lub przez engine higher-level (B3.6 phases poprzez `used_interrupts_this_round`).
    """
    eligible: list[tuple[UnitBlob, str]] = []
    for blob in state.blobs:
        if blob.models_alive == 0:
            continue
        for slug in blob.passives:
            if (point, slug) in _INTERRUPT_HANDLERS:
                eligible.append((blob, slug))
    return eligible


def trigger_interrupt(
    context: InterruptContext,
    slug: str,
    payload: dict[str, Any] | None = None,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Wywołuje handler dla `(context.point, slug)`.

    Args:
        context: InterruptContext zawierający state, point, source_unit_id.
        slug: zdolność interrupt-owa do wywołania.
        payload: dane specyficzne dla zdolności (np. weapon, target, value).

    Returns:
        (new_state, events) — pure transformation per ADR-0010 event-sourced.

    Raises:
        ValueError: gdy nie ma handler dla (point, slug).
    """
    handler = _INTERRUPT_HANDLERS.get((context.point, slug))
    if handler is None:
        raise ValueError(
            f"No interrupt handler for ({context.point.value}, {slug!r}); "
            f"register via @register_interrupt_handler"
        )
    return handler(context, payload or {})


# ---------------------------------------------------------------------------
# MVP example handler: Strażnik (id 31) — stub
# ---------------------------------------------------------------------------


@register_interrupt_handler(InterruptPoint.ACTIVATION_START, "straznik")
def _straznik_handler(
    context: InterruptContext,
    payload: dict[str, Any],
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Strażnik (id 31): "Możesz przerwać w aktywacji przeciwnika, aby wykonać
    Ostrzał. Następnie twój oddział zostaje wyczerpany."

    **MVP stub**: emit `InterruptTriggered` event tylko (faktyczny Ostrzał +
    set status Wyczerpany w B3.6 phases gdy integrate z full activation).

    Full implementation (B3.6+):
    1. Call `resolve_ranged_attack(state, source_blob, active_blob, weapon, dice, ...)`
    2. Apply Wyczerpany status do source_blob
    3. Return (new_state, all_events)
    """
    event = InterruptTriggered(
        sequence=payload.get("sequence", 0),
        interrupt_point=context.point.value,
        slug="straznik",
        source_unit_id=context.source_unit_id,
        target_unit_id=context.active_unit_id,
        payload={"note": "stub — full Ostrzał + Wyczerpany w B3.6"},
    )
    # MVP: state nie ulega zmianie (stub). B3.6 zaktualizuje state.
    return context.state, (event,)
