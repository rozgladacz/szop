"""B3.5 — Interrupt manager (`SZOP_Rozjemca.md pkt 11.b.i + pkt 12` + ADR-0015).

**Punkt przerwania = przed akcją (pkt 11.b.i).** Aktualne reguły (pkt 11.b)
rozpatrują przerwania w JEDNYM miejscu — kroku "Rozpatrujemy przerwania" (pkt
11.b.i), który pętla aktywacji (pkt 11.b.iv → i) odwiedza na początku każdej
iteracji. Ponieważ oddział wykonuje do dwóch akcji, daje to **do dwóch okien
przed-akcyjnych** na aktywację (przed akcją #1 i przed akcją #2).

- `BEFORE_ACTION` — przed akcją oddziału (pkt 11.b.i). Strażnik (id 31), Rozkaz/
  Klątwa/Oznaczenie wyzwalają się tutaj.

> **Korekta drift 2026-06-09 (user, rules author):** ADR-0015 (2026-05-30)
> modelował 4 punkty (ACTIVATION_START/AFTER_ACTION/BEFORE_REGROUP/AFTER_REGROUP)
> wyprowadzone z *przejść* sekwencji pkt 11.b. Aktualny tekst pkt 11/12 umiejscawia
> przerwania TYLKO przed akcją — pozostałe 3 punkty nie miały oparcia w regułach.
> Zredukowano do `BEFORE_ACTION`. Patrz ADR-0015 (sekcja Korekta).

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

from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from typing import Any, Callable

from app.services.engine.events import (
    AbilityOverrideApplied,
    BattleEvent,
    InterruptTriggered,
)
from app.services.engine.geometry import circle_edge_distance
from app.services.engine.state import BattleState, UnitBlob, effective_passives


class InterruptPoint(Enum):
    """Punkt przerwania per pkt 11.b.i (przed akcją).

    Jeden zamknięty punkt — `BEFORE_ACTION`. Pętla aktywacji (pkt 11.b.iv → i)
    odwiedza go przed każdą z ≤2 akcji, stąd do dwóch okien przed-akcyjnych na
    aktywację. (Korekta 2026-06-09 — zob. docstring modułu + ADR-0015.)
    """

    BEFORE_ACTION = "before_action"


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
        for slug in effective_passives(blob):
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


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "straznik")
def _straznik_handler(
    context: InterruptContext,
    payload: dict[str, Any],
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Strażnik (id 31): "Możesz przerwać w aktywacji przeciwnika, aby wykonać
    Ostrzał. Następnie twój oddział zostaje wyczerpany."

    Wyzwalany w `BEFORE_ACTION` (pkt 11.b.i) — przed akcją aktywowanego wroga.

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


# ---------------------------------------------------------------------------
# Rozkaz(X) / Klątwa(X) / Oznaczenie(X) (id 50/45/49) — faza-b-order-interrupts
# ---------------------------------------------------------------------------
#
# Policy (user, autor reguł, 2026-06-09): wyzwalane w `BEFORE_ACTION` (pkt 11.b.i),
# raz na rundę, efekt do końca aktywacji, X = pasywka z `rozkaz_tak: true`.
# - Rozkaz(X) — sojuszniczy oddział w 12″ (nie)ma X (pkt 50).
# - Klątwa(X) — wrogi oddział w 12″ (nie)ma X (pkt 45).
# - Oznaczenie(X) — sojuszniczy oddział atakujący cel w 12″ od nosiciela (pkt 49).
#
# Mechanika: emit `AbilityOverrideApplied(target, X, granted)` → substrat
# `UnitBlob.ability_overrides` (Faza 1) → `effective_passives` aplikuje X do
# końca aktywacji (`activation_phase` emituje `AbilityOverridesCleared`).
# `granted` (payload, default True) rozróżnia wariant pozytywny (nadaj X) od
# negatywnego (odbierz X) — „(nie)miał zdolność X" (pkt 12).

ORDER_RANGE_INCHES = 12.0
# Sluggi przerwań z limitem „raz na rundę" (pkt 12). Strażnik NIE jest tu —
# nie ma per-rundowego limitu w regułach.
ONCE_PER_ROUND_INTERRUPTS = frozenset({"rozkaz", "klatwa", "oznaczenie"})


class InvalidInterruptError(ValueError):
    """Niedozwolone wywołanie przerwania (zasięg / cel ally-enemy / X bez
    `rozkaz_tak` / limit raz-na-rundę)."""


@lru_cache(maxsize=4)
def _rozkaz_capable_slugs(ruleset_version: str = "v1") -> frozenset[str]:
    """Zbiór slugów pasywek z `rozkaz_tak: true` (dozwolone jako X). lru_cache —
    ruleset jest immutable per wersja."""
    from app.services.rulesets.loader import load_ruleset

    ruleset = load_ruleset(ruleset_version)
    return frozenset(a.slug for a in ruleset.abilities if a.rozkaz_tak)


def _apply_order_like(
    context: InterruptContext,
    payload: dict[str, Any],
    *,
    slug: str,
    require_enemy: bool,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Wspólna logika Rozkaz/Klątwa/Oznaczenie (pkt 12 + 45/49/50).

    Payload: `target_id` (oddział-cel), `ability` (X — pasywka `rozkaz_tak:true`),
    `granted` (bool, default True — nadaj/odbierz), `sequence`.

    Walidacja (raise `InvalidInterruptError`): limit raz-na-rundę, istnienie celu,
    `rozkaz_tak`, ally/enemy, zasięg 12″ (krawędź-krawędź). Emit `InterruptTriggered`
    + `AbilityOverrideApplied`; mutacja live state (override na celu + zapis limitu).
    """
    state = context.state
    source_id = context.source_unit_id
    source = next((b for b in state.blobs if b.id == source_id), None)
    if source is None:
        raise InvalidInterruptError(f"{slug}: source unit {source_id} not found")

    if "target_id" not in payload or "ability" not in payload:
        raise InvalidInterruptError(
            f"{slug}: payload requires 'target_id' and 'ability'"
        )
    target_id = int(payload["target_id"])
    ability = str(payload["ability"])
    granted = bool(payload.get("granted", True))
    seq = int(payload.get("sequence", 0))

    if (source_id, slug) in state.used_interrupts_this_round:
        raise InvalidInterruptError(
            f"{slug}: already used by unit {source_id} this round (raz na rundę)"
        )

    target = next((b for b in state.blobs if b.id == target_id), None)
    if target is None or target.models_alive == 0:
        raise InvalidInterruptError(
            f"{slug}: target {target_id} not found or defeated"
        )

    if ability not in _rozkaz_capable_slugs():
        raise InvalidInterruptError(
            f"{slug}: ability {ability!r} is not rozkaz_tak-capable (pkt 12 — X "
            f"musi mieć rozkaz_tak: true)"
        )

    is_enemy = target.owner_player != source.owner_player
    if require_enemy and not is_enemy:
        raise InvalidInterruptError(f"{slug}: target {target_id} must be enemy")
    if not require_enemy and is_enemy:
        raise InvalidInterruptError(f"{slug}: target {target_id} must be ally")

    gap = circle_edge_distance(
        source.position, source.radius_inches, target.position, target.radius_inches
    )
    if gap > ORDER_RANGE_INCHES:
        raise InvalidInterruptError(
            f"{slug}: target {target_id} out of {ORDER_RANGE_INCHES}\" range "
            f"(edge gap={gap:.2f})"
        )

    events: tuple[BattleEvent, ...] = (
        InterruptTriggered(
            sequence=seq,
            interrupt_point=context.point.value,
            slug=slug,
            source_unit_id=source_id,
            target_unit_id=target_id,
            payload={"ability": ability, "granted": granted},
        ),
        AbilityOverrideApplied(
            sequence=seq + 1,
            target_id=target_id,
            ability=ability,
            granted=granted,
            source_id=source_id,
        ),
    )
    # Mutacja live state (mirror reducerów: AbilityOverrideApplied + InterruptTriggered).
    new_target = replace(
        target, ability_overrides=target.ability_overrides + ((ability, granted),)
    )
    new_blobs = tuple(new_target if b.id == target_id else b for b in state.blobs)
    new_state = replace(
        state,
        blobs=new_blobs,
        used_interrupts_this_round=state.used_interrupts_this_round
        + ((source_id, slug),),
    )
    return new_state, events


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "rozkaz")
def _rozkaz_handler(
    context: InterruptContext, payload: dict[str, Any]
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Rozkaz(X) (id 50): sojuszniczy oddział w 12″ (nie)ma X do końca aktywacji."""
    return _apply_order_like(context, payload, slug="rozkaz", require_enemy=False)


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "klatwa")
def _klatwa_handler(
    context: InterruptContext, payload: dict[str, Any]
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Klątwa(X) (id 45): wrogi oddział w 12″ (nie)ma X do końca aktywacji."""
    return _apply_order_like(context, payload, slug="klatwa", require_enemy=True)


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "oznaczenie")
def _oznaczenie_handler(
    context: InterruptContext, payload: dict[str, Any]
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Oznaczenie(X) (id 49): sojuszniczy oddział (nie)ma X do końca aktywacji.

    **Uproszczenie MVP (H-note):** reguła pkt 49 celuje w sojusznika, który
    *atakuje cel w 12″ od nosiciela* — tj. zasięg mierzony do ofiary ataku, a
    wyzwalany przy deklaracji ataku sojusznika. Pełny trigger wymaga kontekstu
    ataku (orkiestracja przerwań, H2/B4). MVP: traktujemy jak „sojusznik w 12″
    od nosiciela ma X" (mechanicznie jak Rozkaz, osobny slug + limit). Precyzyjny
    trigger ataku — follow-up po wpięciu deklaracji przerwań w pętlę aktywacji.
    """
    return _apply_order_like(context, payload, slug="oznaczenie", require_enemy=False)
