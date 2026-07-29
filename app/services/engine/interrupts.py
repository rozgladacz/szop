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

Per-rundowe limity ("Raz na rundę", pkt 12 — Rozkaz/Klątwa/Oznaczenie) SĄ
enforce'owane (ADR-0049): `BattleState.used_interrupts_this_round:
tuple[tuple[int, str], ...]` trzyma pary `(source_id, slug)` zużyte w tej rundzie;
`_apply_order_like` odrzuca ponowne wywołanie (`InvalidInterruptError`),
`phases.round_end_phase` resetuje pole do `()`, a reducer `InterruptTriggered`
(gdy `consumes_round_limit`) odtwarza je przy replay. Strażnik (id 31) NIE ma
limitu raz-na-rundę (brak w regułach).

Zawartość:
- `InterruptPoint` enum (1 wartość — `BEFORE_ACTION`, pkt 11.b.i; korekta
  2026-06-09 z 4 punktów, zob. niżej + ADR-0015)
- `register_interrupt_handler(point, slug)` decorator
- `get_eligible_interrupts(state, point)` — lista (blob, slug) which CAN trigger
- `trigger_interrupt(...)` — wywołuje konkretny handler
- Handlery registry: kompatybilny stub Strażnika, source-correct Rozkaz/Klątwa
  (id 50/45) oraz historyczne uproszczenie Oznaczenia (id 49). Publiczny adapter
  activation-v2 wywołuje bezpośrednio prywatny outcome C1b pełnego Ostrzału
  + Wyczerpany, z pominięciem legacy stubu.

Auto-orkiestracja przerwań w pętli aktywacji (`phases.activation_phase` woła
handlery sama) wciąż czeka na integrację (H2/B4); dziś handlery wywoływane jawnie.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Callable

from app.services.engine.combat import (
    ABILITY_NAMIERZANIE,
    _RangedProfileDeclaration,
    _resolve_ranged_volley,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    AbilityOverrideApplied,
    BattleEvent,
    InterruptTriggered,
    StatusAdded,
)
from app.services.engine.geometry import circle_edge_distance
from app.services.engine.los import LoSState, check_los
from app.services.engine.state import (
    ActivationPhase,
    BattleState,
    Lokalizacja,
    UnitBlob,
    WeaponProfile,
    apply_events,
    effective_passives,
)
from app.services.engine.status import STATUS_WYCZERPANY


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

    `state` = aktualny BattleState (read-only). `point` = punkt przerwania
    (`BEFORE_ACTION` — jedyny w MVP). `active_unit_id` = oddział obecnie
    aktywowany (jeśli applicable; None dla między-rundowych). `source_unit_id` =
    oddział wywołujący interrupt (with eligible passive ability). `sequence`
    jest wyłącznie wewnętrznym początkiem outcome, nie polem payloadu klienta.
    """

    state: BattleState
    point: InterruptPoint
    source_unit_id: int
    active_unit_id: int | None = None
    sequence: int = 0


# Handler signature: (context, **kwargs) → (new_state, events)
InterruptHandlerFn = Callable[
    [InterruptContext, dict[str, Any]],
    tuple[BattleState, tuple[BattleEvent, ...]],
]

# Registry: (point, slug) → handler
_INTERRUPT_HANDLERS: dict[tuple[InterruptPoint, str], InterruptHandlerFn] = {}

# Public readiness is deliberately narrower than the internal registry.
READY_INTERRUPT_HANDLERS = frozenset({"rozkaz", "klatwa", "straznik"})


def register_interrupt_handler(
    point: InterruptPoint, slug: str
) -> Callable[[InterruptHandlerFn], InterruptHandlerFn]:
    """Decorator — rejestruje handler dla (point, slug).

    Użycie::

        @register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "straznik")
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
    To eligibility (KTO ma zdolność), nie dozwolenie: per-rundowy limit ("Raz na
    rundę", pkt 12), zasięg 12″ i ally/enemy waliduje dopiero handler
    (`_apply_order_like` przez `state.used_interrupts_this_round`).
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

    Kompatybilny legacy stub: emituje tylko `InterruptTriggered`. Publiczny
    adapter C1c omija ten historyczny call site i wywołuje bezpośrednio prywatny,
    source-correct activation-v2 outcome C1b.
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
# B4.4d.C1b — private, source-correct Strażnik activation-v2 outcome
# ---------------------------------------------------------------------------


_STRAZNIK_PAYLOAD_FIELDS = frozenset({"assignments"})
_STRAZNIK_ASSIGNMENT_FIELDS = frozenset({"weapon_slug", "target_id"})
_STRAZNIK_SUPPORTED_WEAPON_ABILITIES = frozenset(
    {
        "ap",
        "artyleria",
        "brutalny",
        "namierzanie",
        "niebezposredni",
        "nieporeczny",
        "niezawodny",
        "podwojny",
        "precyzyjny",
        "rozrywajacy",
        "szturmowa",
        "zguba",
    }
)
_STRAZNIK_UNSUPPORTED_SOURCE_PASSIVES = frozenset(
    {
        "dobrze_strzela",
        "dywersant",
        "instynkt",
        "mistrzostwo",
        "ostrozny",
        "planowanie",
        "szpica",
        "zle_strzela",
        "zwrot",
    }
)
_STRAZNIK_UNSUPPORTED_TARGET_PASSIVES = frozenset(
    {
        "maskowanie",
        "okopany",
        "zemsta",
        "zwrot",
    }
)
_STRAZNIK_MAX_OUTCOME_EVENTS = 64
_STRAZNIK_MAX_ASSIGNMENTS = 64
_STRAZNIK_MAX_ATTACK_DICE = 10_000
_STRAZNIK_ARTILLERY_RANGE_INCHES = 12.0


@dataclass(frozen=True, slots=True)
class _StraznikProfileAssignment:
    weapon: WeaponProfile
    weapon_count: int
    target_id: int


@dataclass(frozen=True, slots=True)
class _StraznikShootPlan:
    assignments: tuple[_StraznikProfileAssignment, ...]
    target_ids: tuple[int, ...]


def _canonical_straznik_inventory(
    source: UnitBlob,
) -> dict[str, tuple[WeaponProfile, int]]:
    if type(source.ranged_weapons) is not tuple:
        raise InvalidInterruptError(
            "straznik: canonical ranged inventory must be a tuple"
        )
    grouped: dict[str, list[WeaponProfile]] = {}
    for weapon in source.ranged_weapons:
        if (
            type(weapon) is not WeaponProfile
            or type(weapon.slug) is not str
            or not weapon.slug
            or type(weapon.name) is not str
            or type(weapon.range_inches) is not int
            or weapon.range_inches <= 0
            or type(weapon.attacks) is not int
            or weapon.attacks <= 0
            or type(weapon.ap) is not int
            or (
                weapon.attack_quality_override is not None
                and (
                    type(weapon.attack_quality_override) is not int
                    or weapon.attack_quality_override < 2
                )
            )
            or type(weapon.weapon_abilities) is not tuple
            or any(
                type(ability) is not str or not ability
                for ability in weapon.weapon_abilities
            )
            or len(weapon.weapon_abilities) != len(set(weapon.weapon_abilities))
        ):
            raise InvalidInterruptError(
                "straznik: canonical ranged inventory is malformed"
            )
        unsupported = (
            frozenset(weapon.weapon_abilities)
            - _STRAZNIK_SUPPORTED_WEAPON_ABILITIES
        )
        if unsupported:
            raise InvalidInterruptError(
                "straznik: canonical inventory has unsupported weapon abilities"
            )
        grouped.setdefault(weapon.slug, []).append(weapon)

    inventory: dict[str, tuple[WeaponProfile, int]] = {}
    for slug, profiles in grouped.items():
        canonical = profiles[0]
        if any(profile != canonical for profile in profiles[1:]):
            raise InvalidInterruptError(
                f"straznik: canonical profile {slug!r} is ambiguous"
            )
        inventory[slug] = (canonical, len(profiles))
    return inventory


def _validated_straznik_plan(
    source: UnitBlob,
    payload: Mapping[str, Any],
) -> _StraznikShootPlan:
    raw_assignments, target_ids = _validated_straznik_request_payload(payload)
    if len(raw_assignments) > len(source.ranged_weapons):
        raise InvalidInterruptError(
            "straznik: assignments list has an invalid size"
        )

    inventory = _canonical_straznik_inventory(source)
    assignments: list[_StraznikProfileAssignment] = []
    for weapon_slug, target_id in raw_assignments:
        canonical = inventory.get(weapon_slug)
        if canonical is None:
            raise InvalidInterruptError(
                f"straznik: profile {weapon_slug!r} is not in source inventory"
            )
        assignments.append(
            _StraznikProfileAssignment(
                weapon=canonical[0],
                weapon_count=canonical[1],
                target_id=target_id,
            )
        )

    return _StraznikShootPlan(
        assignments=tuple(assignments),
        target_ids=target_ids,
    )


def _validated_straznik_request_payload(
    payload: Mapping[str, Any],
) -> tuple[tuple[tuple[str, int], ...], tuple[int, ...]]:
    """Decode the source-independent strict public Strażnik plan."""

    if type(payload) is not dict or frozenset(payload) != _STRAZNIK_PAYLOAD_FIELDS:
        raise InvalidInterruptError(
            "straznik: payload requires exactly assignments"
        )
    raw_assignments = payload["assignments"]
    if (
        type(raw_assignments) is not list
        or not raw_assignments
        or len(raw_assignments) > _STRAZNIK_MAX_ASSIGNMENTS
    ):
        raise InvalidInterruptError(
            "straznik: assignments list has an invalid size"
        )

    assignments: list[tuple[str, int]] = []
    assigned_slugs: set[str] = set()
    target_ids: list[int] = []
    for raw_assignment in raw_assignments:
        if (
            type(raw_assignment) is not dict
            or frozenset(raw_assignment) != _STRAZNIK_ASSIGNMENT_FIELDS
        ):
            raise InvalidInterruptError(
                "straznik: each assignment requires weapon_slug and target_id"
            )
        weapon_slug = raw_assignment["weapon_slug"]
        target_id = raw_assignment["target_id"]
        if (
            type(weapon_slug) is not str
            or not weapon_slug
            or type(target_id) is not int
            or target_id < 0
        ):
            raise InvalidInterruptError(
                "straznik: assignment types are invalid"
            )
        if weapon_slug in assigned_slugs:
            raise InvalidInterruptError(
                "straznik: one profile cannot be assigned more than once"
            )
        assigned_slugs.add(weapon_slug)
        if target_id not in target_ids:
            target_ids.append(target_id)
        assignments.append((weapon_slug, target_id))

    if not 1 <= len(target_ids) <= 2:
        raise InvalidInterruptError(
            "straznik: Ostrzal requires one or two distinct targets"
        )
    return tuple(assignments), tuple(target_ids)


def _unique_blob(state: BattleState, unit_id: int, label: str) -> UnitBlob:
    matches = tuple(blob for blob in state.blobs if blob.id == unit_id)
    if len(matches) != 1:
        raise InvalidInterruptError(
            f"straznik: {label} {unit_id} is missing or ambiguous"
        )
    return matches[0]


def _straznik_has_artillery_range(
    state: BattleState,
    source: UnitBlob,
    target: UnitBlob,
) -> bool:
    return any(
        ally.owner_player == source.owner_player
        and ally.models_alive > 0
        and ally.location is Lokalizacja.FRONT
        and circle_edge_distance(
            ally.position,
            ally.radius_inches,
            target.position,
            target.radius_inches,
        )
        <= _STRAZNIK_ARTILLERY_RANGE_INCHES
        for ally in state.blobs
    )


def _validate_straznik_assignment(
    state: BattleState,
    source: UnitBlob,
    target: UnitBlob,
    assignment: _StraznikProfileAssignment,
) -> None:
    weapon = assignment.weapon
    abilities = frozenset(weapon.weapon_abilities)
    source_passives = frozenset(effective_passives(source))
    target_passives = frozenset(effective_passives(target))
    gap = circle_edge_distance(
        source.position,
        source.radius_inches,
        target.position,
        target.radius_inches,
    )

    if "nieporeczny" in abilities and gap <= 12.0:
        raise InvalidInterruptError(
            "straznik: Nieporeczny profile cannot attack within 12 inches"
        )
    if "niebezposredni" in abilities and "samolot" in target_passives:
        raise InvalidInterruptError(
            "straznik: Niebezposredni profile cannot target Samolot"
        )

    effective_range = weapon.range_inches
    if (
        "samolot" in target_passives
        and ABILITY_NAMIERZANIE not in abilities
    ):
        effective_range -= 12
    nominal_range_ok = effective_range >= 0 and gap <= effective_range
    artillery_range_ok = (
        "artyleria" in abilities
        and _straznik_has_artillery_range(state, source, target)
    )
    if (
        "artyleria" in abilities
        and "samolot" in target_passives
        and ABILITY_NAMIERZANIE not in abilities
    ):
        raise InvalidInterruptError(
            "straznik: Artyleria versus Samolot is unsupported without Namierzanie"
        )
    if not nominal_range_ok and not artillery_range_ok:
        raise InvalidInterruptError(
            f"straznik: profile {weapon.slug!r} is out of range"
        )

    if "niebezposredni" not in abilities:
        if state.terrain and (
            "wysoki" in source_passives
            or "wysoki" in target_passives
            or "samolot" in source_passives
            or "samolot" in target_passives
        ):
            raise InvalidInterruptError(
                "straznik: elevated line of sight is not representable"
            )
        if check_los(source, target, state.terrain) is LoSState.NIE_WIDZI:
            raise InvalidInterruptError(
                f"straznik: target {target.id} is outside line of sight"
            )


def _validate_straznik_lock(
    state: BattleState,
    source: UnitBlob,
) -> None:
    source_passives = frozenset(effective_passives(source))
    for enemy in state.blobs:
        if (
            enemy.owner_player == source.owner_player
            or enemy.models_alive <= 0
            or enemy.location is not Lokalizacja.FRONT
        ):
            continue
        gap = circle_edge_distance(
            source.position,
            source.radius_inches,
            enemy.position,
            enemy.radius_inches,
        )
        if gap > 2.0:
            continue
        enemy_passives = frozenset(effective_passives(enemy))
        if state.terrain and (
            "wysoki" in source_passives
            or "wysoki" in enemy_passives
            or "samolot" in source_passives
            or "samolot" in enemy_passives
        ):
            raise InvalidInterruptError(
                "straznik: elevated 2-inch lock line of sight is not representable"
            )
        if check_los(source, enemy, state.terrain) is not LoSState.NIE_WIDZI:
            raise InvalidInterruptError(
                "straznik: Ostrzal is locked by a visible enemy within 2 inches"
            )


def _execute_straznik_activation_interrupt_outcomes(
    *,
    state: BattleState,
    source: UnitBlob,
    ability_slug: str,
    payload: Mapping[str, Any],
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Private activation-v2 leaf for one complete Strażnik Ostrzał."""

    if (
        type(state) is not BattleState
        or type(source) is not UnitBlob
        or ability_slug != "straznik"
        or type(dice) is not DeterministicDice
        or type(sequence) is not int
        or sequence < 1
    ):
        raise InvalidInterruptError("straznik: outcome input is malformed")
    activation = state.activation
    if (
        activation is None
        or activation.phase is not ActivationPhase.BEFORE_ACTION
        or activation.window is None
    ):
        raise InvalidInterruptError(
            "straznik: durable BEFORE_ACTION window is required"
        )

    current_source = _unique_blob(state, source.id, "source")
    active_unit = _unique_blob(
        state,
        activation.selected_unit_id,
        "active unit",
    )
    source_passives = frozenset(effective_passives(current_source))
    if (
        current_source != source
        or current_source.owner_player != activation.window.priority_player
        or type(current_source.models_alive) is not int
        or current_source.models_alive <= 0
        or current_source.location is not Lokalizacja.FRONT
        or "straznik" not in source_passives
        or STATUS_WYCZERPANY in current_source.status_flags
        or type(active_unit.owner_player) is not int
        or active_unit.owner_player not in (0, 1)
        or type(active_unit.models_alive) is not int
        or active_unit.models_alive <= 0
        or active_unit.location is not Lokalizacja.FRONT
        or active_unit.owner_player != activation.controlling_player
        or active_unit.owner_player == current_source.owner_player
    ):
        raise InvalidInterruptError(
            "straznik: source or enemy activation is invalid"
        )
    if source_passives & _STRAZNIK_UNSUPPORTED_SOURCE_PASSIVES:
        raise InvalidInterruptError(
            "straznik: source has an unsupported ranged combat passive"
        )

    plan = _validated_straznik_plan(current_source, payload)
    targets: dict[int, UnitBlob] = {}
    for target_id in plan.target_ids:
        target = _unique_blob(state, target_id, "target")
        target_passives = frozenset(effective_passives(target))
        if (
            type(target.owner_player) is not int
            or target.owner_player not in (0, 1)
            or type(target.models_alive) is not int
            or target.models_alive <= 0
            or target.location is not Lokalizacja.FRONT
            or target.owner_player == current_source.owner_player
            or target_passives & _STRAZNIK_UNSUPPORTED_TARGET_PASSIVES
        ):
            raise InvalidInterruptError(
                f"straznik: target {target_id} is not a supported live enemy"
            )
        targets[target_id] = target

    _validate_straznik_lock(state, current_source)
    for assignment in plan.assignments:
        _validate_straznik_assignment(
            state,
            current_source,
            targets[assignment.target_id],
            assignment,
        )

    max_outcome_events = (
        2
        + len(plan.assignments)
        + sum(targets[target_id].models_alive for target_id in plan.target_ids)
    )
    if max_outcome_events > _STRAZNIK_MAX_OUTCOME_EVENTS:
        raise InvalidInterruptError("straznik: outcome would exceed event bound")
    attack_dice = sum(
        current_source.models_alive
        * assignment.weapon.attacks
        * assignment.weapon_count
        for assignment in plan.assignments
    )
    if attack_dice > _STRAZNIK_MAX_ATTACK_DICE:
        raise InvalidInterruptError("straznik: attack dice bound exceeded")

    marker = InterruptTriggered(
        sequence=sequence,
        interrupt_point=InterruptPoint.BEFORE_ACTION.value,
        slug="straznik",
        source_unit_id=current_source.id,
        target_unit_id=active_unit.id,
        payload={
            "assignments": [
                {
                    "weapon_slug": assignment.weapon.slug,
                    "target_id": assignment.target_id,
                }
                for assignment in plan.assignments
            ]
        },
    )
    declarations = tuple(
        _RangedProfileDeclaration(
            defender=targets[assignment.target_id],
            weapon=assignment.weapon,
            weapon_count=assignment.weapon_count,
        )
        for assignment in plan.assignments
    )
    volley = _resolve_ranged_volley(
        state,
        current_source,
        declarations,
        dice,
        sequence + 1,
        state.terrain,
        source_correct=True,
    )
    replayed_volley_state = apply_events(state, volley.events)
    if any(
        _unique_blob(replayed_volley_state, defender.id, "replayed target")
        != defender
        for defender in volley.new_defenders
    ):
        raise InvalidInterruptError(
            "straznik: live combat outcome does not match event replay"
        )
    status_event = StatusAdded(
        sequence=sequence + 1 + len(volley.events),
        target_id=current_source.id,
        status=STATUS_WYCZERPANY,
    )
    outcome_events: tuple[BattleEvent, ...] = (
        marker,
        *volley.events,
        status_event,
    )
    replay_state = apply_events(state, outcome_events)
    return replay_state, outcome_events


# ---------------------------------------------------------------------------
# Rozkaz(X) / Klątwa(X) / Oznaczenie(X) (id 50/45/49) — faza-b-order-interrupts
# ---------------------------------------------------------------------------
#
# Policy (user, autor reguł, 2026-06-09): wyzwalane w `BEFORE_ACTION` (pkt 11.b.i),
# raz na rundę i efekt do końca aktywacji.
# - Rozkaz(X) — sojuszniczy oddział w 12″ (nie)ma X (pkt 50).
#   X = pasywka z `rozkaz_tak: true` i kanonicznym `rozkaz_kierunek`.
# - Klątwa(X) — wrogi oddział w 12″ (nie)ma X (pkt 45);
#   X = pasywka z jawnym `klatwa_tak: true`.
# - Oznaczenie(X) — sojuszniczy oddział atakujący cel w 12″ od nosiciela (pkt 49).
#
# Mechanika: emit `AbilityOverrideApplied(target, X, granted)` → substrat
# `UnitBlob.ability_overrides` (Faza 1) → `effective_passives` aplikuje X do
# końca aktywacji (`activation_phase` emituje `AbilityOverridesCleared`).
# Dla source-correct Rozkazu `granted` jest wymaganym strict bool i musi zgadzać
# się z `rozkaz_kierunek`; source-correct Klątwa dopuszcza oba kierunki
# deklarowane przez gracza. Historyczne Oznaczenie zachowuje coercion do czasu
# własnego source-correct slice'a.

ORDER_RANGE_INCHES = 12.0
# Sluggi przerwań z limitem „raz na rundę" (pkt 12). Strażnik NIE jest tu —
# nie ma per-rundowego limitu w regułach.
ONCE_PER_ROUND_INTERRUPTS = frozenset({"rozkaz", "klatwa", "oznaczenie"})


class InvalidInterruptError(ValueError):
    """Niedozwolone wywołanie przerwania (zasięg / cel ally-enemy / X bez
    source-correct tagu / limit raz-na-rundę)."""


_ROZKAZ_PAYLOAD_FIELDS = frozenset({"target_id", "ability", "granted"})
_KLATWA_PAYLOAD_FIELDS = frozenset({"target_id", "ability", "granted"})


def _validated_rozkaz_payload(
    payload: Mapping[str, Any],
) -> tuple[int, str, bool]:
    try:
        payload_fields = frozenset(payload)
    except Exception as exc:
        raise InvalidInterruptError("rozkaz: malformed payload") from exc
    if payload_fields != _ROZKAZ_PAYLOAD_FIELDS:
        raise InvalidInterruptError(
            "rozkaz: payload requires exactly target_id, ability and granted"
        )
    target_id = payload["target_id"]
    ability = payload["ability"]
    granted = payload["granted"]
    if (
        type(target_id) is not int
        or target_id < 0
        or type(ability) is not str
        or not ability
        or type(granted) is not bool
    ):
        raise InvalidInterruptError("rozkaz: payload types are invalid")

    required_granted = _rozkaz_capable_directions().get(ability)
    if required_granted is None:
        raise InvalidInterruptError(
            f"rozkaz: ability {ability!r} lacks canonical rozkaz tags"
        )
    if granted is not required_granted:
        raise InvalidInterruptError(
            f"rozkaz: granted does not match rozkaz_kierunek for {ability!r}"
        )
    return target_id, ability, granted


def _validated_klatwa_payload(
    payload: Mapping[str, Any],
) -> tuple[int, str, bool]:
    try:
        payload_fields = frozenset(payload)
    except Exception as exc:
        raise InvalidInterruptError("klatwa: malformed payload") from exc
    if payload_fields != _KLATWA_PAYLOAD_FIELDS:
        raise InvalidInterruptError(
            "klatwa: payload requires exactly target_id, ability and granted"
        )
    target_id = payload["target_id"]
    ability = payload["ability"]
    granted = payload["granted"]
    if (
        type(target_id) is not int
        or target_id < 0
        or type(ability) is not str
        or not ability
        or type(granted) is not bool
    ):
        raise InvalidInterruptError("klatwa: payload types are invalid")
    if ability not in _klatwa_capable_slugs():
        raise InvalidInterruptError(
            f"klatwa: ability {ability!r} lacks canonical klatwa_tak tag"
        )
    return target_id, ability, granted


def validate_ready_activation_interrupt_request(
    *,
    ability_slug: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and copy the source-independent public-ready request shape."""

    if (
        type(ability_slug) is not str
        or ability_slug not in READY_INTERRUPT_HANDLERS
    ):
        raise InvalidInterruptError(f"interrupt {ability_slug!r} is not ready")
    if not isinstance(payload, Mapping):
        raise InvalidInterruptError("ready interrupt payload is malformed")
    try:
        dispatch_payload = dict(payload)
    except Exception as exc:
        raise InvalidInterruptError("ready interrupt payload is malformed") from exc
    if ability_slug == "rozkaz":
        _validated_rozkaz_payload(dispatch_payload)
    elif ability_slug == "klatwa":
        _validated_klatwa_payload(dispatch_payload)
    elif ability_slug == "straznik":
        assignments, _target_ids = _validated_straznik_request_payload(
            dispatch_payload
        )
        return {
            "assignments": [
                {"weapon_slug": weapon_slug, "target_id": target_id}
                for weapon_slug, target_id in assignments
            ]
        }
    return dispatch_payload


@lru_cache(maxsize=4)
def _rozkaz_capable_slugs(ruleset_version: str = "v1") -> frozenset[str]:
    """Zbiór slugów pasywek z `rozkaz_tak: true` (dozwolone jako X). lru_cache —
    ruleset jest immutable per wersja."""
    from app.services.rulesets.loader import load_ruleset

    ruleset = load_ruleset(ruleset_version)
    return frozenset(a.slug for a in ruleset.abilities if a.rozkaz_tak)


@lru_cache(maxsize=4)
def _klatwa_capable_slugs(ruleset_version: str = "v1") -> frozenset[str]:
    """Immutable source-correct Klątwa catalog from explicit ruleset tags."""
    from app.services.rulesets.loader import load_ruleset

    ruleset = load_ruleset(ruleset_version)
    return frozenset(
        ability.slug
        for ability in ruleset.abilities
        if ability.type == "passive" and ability.klatwa_tak is True
    )


@lru_cache(maxsize=4)
def _rozkaz_capable_directions(
    ruleset_version: str = "v1",
) -> Mapping[str, bool]:
    """Immutable source-correct Rozkaz catalog: slug -> required `granted`."""
    from app.services.rulesets.loader import load_ruleset

    directions = {"+": True, "−": False}
    ruleset = load_ruleset(ruleset_version)
    return MappingProxyType(
        {
            ability.slug: directions[ability.rozkaz_kierunek]
            for ability in ruleset.abilities
            if ability.type == "passive"
            and ability.rozkaz_tak is True
            and ability.rozkaz_kierunek in directions
        }
    )


def _order_like_participants(
    context: InterruptContext,
    *,
    slug: str,
    target_id: int,
    require_enemy: bool,
    require_front: bool = False,
    require_source_slug: bool = False,
) -> tuple[UnitBlob, UnitBlob]:
    state = context.state
    source_id = context.source_unit_id
    source = next((blob for blob in state.blobs if blob.id == source_id), None)
    if (
        source is None
        or source.models_alive <= 0
        or (require_front and source.location is not Lokalizacja.FRONT)
        or (require_source_slug and slug not in effective_passives(source))
    ):
        raise InvalidInterruptError(
            f"{slug}: source unit {source_id} is not a live Front source with {slug}"
        )
    if (source_id, slug) in state.used_interrupts_this_round:
        raise InvalidInterruptError(
            f"{slug}: already used by unit {source_id} this round (raz na rundę)"
        )

    target = next((blob for blob in state.blobs if blob.id == target_id), None)
    if (
        target is None
        or target.models_alive <= 0
        or (require_front and target.location is not Lokalizacja.FRONT)
    ):
        raise InvalidInterruptError(
            f"{slug}: target {target_id} is not a live Front unit"
        )

    is_enemy = target.owner_player != source.owner_player
    if is_enemy != require_enemy:
        raise InvalidInterruptError(
            f"{slug}: target {target_id} must be "
            f"{'enemy' if require_enemy else 'ally'}"
        )

    gap = circle_edge_distance(
        source.position, source.radius_inches, target.position, target.radius_inches
    )
    if gap > ORDER_RANGE_INCHES:
        raise InvalidInterruptError(
            f"{slug}: target {target_id} out of {ORDER_RANGE_INCHES}\" range "
            f"(edge gap={gap:.2f})"
        )
    return source, target


def _apply_order_like_outcome(
    context: InterruptContext,
    *,
    source: UnitBlob,
    target: UnitBlob,
    slug: str,
    ability: str,
    granted: bool,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    events: tuple[BattleEvent, ...] = (
        InterruptTriggered(
            sequence=sequence,
            interrupt_point=context.point.value,
            slug=slug,
            source_unit_id=source.id,
            target_unit_id=target.id,
            payload={"ability": ability, "granted": granted},
            consumes_round_limit=slug in ONCE_PER_ROUND_INTERRUPTS,
        ),
        AbilityOverrideApplied(
            sequence=sequence + 1,
            target_id=target.id,
            ability=ability,
            granted=granted,
            source_id=source.id,
        ),
    )
    new_target = replace(
        target, ability_overrides=target.ability_overrides + ((ability, granted),)
    )
    new_blobs = tuple(
        new_target if blob.id == target.id else blob for blob in context.state.blobs
    )
    new_state = replace(
        context.state,
        blobs=new_blobs,
        used_interrupts_this_round=context.state.used_interrupts_this_round
        + ((source.id, slug),),
    )
    return new_state, events


def _apply_order_like(
    context: InterruptContext,
    payload: dict[str, Any],
    *,
    slug: str,
    require_enemy: bool,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Historyczna wspólna logika niegotowego Oznaczenia.

    Payload: `target_id` (oddział-cel), `ability` (X — pasywka `rozkaz_tak:true`),
    `granted` (bool, default True — nadaj/odbierz), `sequence`.

    Walidacja (raise `InvalidInterruptError`): limit raz-na-rundę, istnienie celu,
    `rozkaz_tak`, ally/enemy, zasięg 12″ (krawędź-krawędź). Emit `InterruptTriggered`
    + `AbilityOverrideApplied`; mutacja live state (override na celu + zapis limitu).
    """
    if "target_id" not in payload or "ability" not in payload:
        raise InvalidInterruptError(
            f"{slug}: payload requires 'target_id' and 'ability'"
        )
    target_id = int(payload["target_id"])
    ability = str(payload["ability"])
    granted = bool(payload.get("granted", True))
    seq = int(payload.get("sequence", 0))
    source, target = _order_like_participants(
        context,
        slug=slug,
        target_id=target_id,
        require_enemy=require_enemy,
    )

    if ability not in _rozkaz_capable_slugs():
        raise InvalidInterruptError(
            f"{slug}: ability {ability!r} is not rozkaz_tak-capable (pkt 12 — X "
            f"musi mieć rozkaz_tak: true)"
        )

    return _apply_order_like_outcome(
        context,
        source=source,
        target=target,
        slug=slug,
        ability=ability,
        granted=granted,
        sequence=seq,
    )


def _apply_rozkaz(
    context: InterruptContext,
    payload: Mapping[str, Any],
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Strict source-correct Rozkaz(X) outcome from canonical ruleset metadata."""
    target_id, ability, granted = _validated_rozkaz_payload(payload)
    if type(context.sequence) is not int or context.sequence < 0:
        raise InvalidInterruptError("rozkaz: context sequence is invalid")

    source, target = _order_like_participants(
        context,
        slug="rozkaz",
        target_id=target_id,
        require_enemy=False,
        require_front=True,
        require_source_slug=True,
    )
    return _apply_order_like_outcome(
        context,
        source=source,
        target=target,
        slug="rozkaz",
        ability=ability,
        granted=granted,
        sequence=context.sequence,
    )


def _apply_klatwa(
    context: InterruptContext,
    payload: Mapping[str, Any],
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Strict source-correct Klątwa(X) outcome from canonical ruleset metadata."""
    target_id, ability, granted = _validated_klatwa_payload(payload)
    if type(context.sequence) is not int or context.sequence < 0:
        raise InvalidInterruptError("klatwa: context sequence is invalid")

    source, target = _order_like_participants(
        context,
        slug="klatwa",
        target_id=target_id,
        require_enemy=True,
        require_front=True,
        require_source_slug=True,
    )
    return _apply_order_like_outcome(
        context,
        source=source,
        target=target,
        slug="klatwa",
        ability=ability,
        granted=granted,
        sequence=context.sequence,
    )


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "rozkaz")
def _rozkaz_handler(
    context: InterruptContext, payload: dict[str, Any]
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Rozkaz(X) (id 50): sojuszniczy oddział w 12″ (nie)ma X do końca aktywacji."""
    return _apply_rozkaz(context, payload)


@register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "klatwa")
def _klatwa_handler(
    context: InterruptContext, payload: dict[str, Any]
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Klątwa(X) (id 45): wrogi oddział w 12″ (nie)ma X do końca aktywacji."""
    return _apply_klatwa(context, payload)


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


def execute_ready_activation_interrupt_outcomes(
    *,
    state: BattleState,
    source: UnitBlob,
    ability_slug: str,
    payload: Mapping[str, Any],
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Built-in leaf for public-ready durable activation interrupts."""
    if (
        type(state) is not BattleState
        or type(source) is not UnitBlob
        or type(dice) is not DeterministicDice
        or type(sequence) is not int
        or sequence < 1
    ):
        raise InvalidInterruptError("ready interrupt adapter input is malformed")
    dispatch_payload = validate_ready_activation_interrupt_request(
        ability_slug=ability_slug,
        payload=payload,
    )

    activation = state.activation
    if (
        activation is None
        or activation.phase is not ActivationPhase.BEFORE_ACTION
        or activation.window is None
    ):
        raise InvalidInterruptError("ready interrupt requires a durable open window")
    current_source = next(
        (blob for blob in state.blobs if blob.id == source.id),
        None,
    )
    active_unit = next(
        (blob for blob in state.blobs if blob.id == activation.selected_unit_id),
        None,
    )
    if (
        current_source is None
        or current_source != source
        or current_source.owner_player != activation.window.priority_player
        or current_source.models_alive <= 0
        or current_source.location is not Lokalizacja.FRONT
        or ability_slug not in effective_passives(current_source)
        or active_unit is None
        or active_unit.models_alive <= 0
        or active_unit.location is not Lokalizacja.FRONT
    ):
        raise InvalidInterruptError("ready interrupt source or active unit is invalid")

    if ability_slug == "straznik":
        return _execute_straznik_activation_interrupt_outcomes(
            state=state,
            source=current_source,
            ability_slug=ability_slug,
            payload=dispatch_payload,
            dice=dice,
            sequence=sequence,
        )
    context = InterruptContext(
        state=state,
        point=InterruptPoint.BEFORE_ACTION,
        source_unit_id=current_source.id,
        active_unit_id=active_unit.id,
        sequence=sequence,
    )
    return trigger_interrupt(
        context,
        ability_slug,
        dispatch_payload,
    )


__all__ = [
    "InterruptContext",
    "InterruptPoint",
    "InvalidInterruptError",
    "READY_INTERRUPT_HANDLERS",
    "execute_ready_activation_interrupt_outcomes",
    "get_eligible_interrupts",
    "register_interrupt_handler",
    "trigger_interrupt",
    "validate_ready_activation_interrupt_request",
]
