"""B3.5 — Passive ability registry (modifier hooks per kategoria).

Architektura per-hook registry. Każda passive ability może rejestrować się w
jednej lub wielu kategoriach modifiers:

- **defense_modifier** (`+/-` do testu obrony per pkt 17.b) — Cierpliwy, Tarcza,
  Okopany, Parowanie, etc.
- **attack_modifier** (`+/-` do testu trafienia per pkt 17.a) — Ostrożny,
  Przygotowanie, etc.
- **morale_modifier** (`+/-` do liczby testów Przegrupowania per pkt 20.d) —
  Nieustraszony, Stracency, etc.
- **weapon_modifier** (`WeaponProfile → WeaponProfile`) — Niezawodny, Dobrze
  strzela, Mistrzostwo, etc.

Engine (B3.6 phases, B3.7 resolver) wywołuje `aggregate_*(blob, context)` żeby
zebrać sumę modifiers z passive abilities bloba. Każda funkcja jest pure: bierze
`EffectContext` (read-only state proxy) → zwraca scalar/profile.

MVP scope: 3 representative abilities (Cierpliwy, Tarcza, Nieustraszony).
Reszta passive abilities (44 entries z `abilities.yaml` typ=passive) dodawana
w przyszłych iteracjach — każda nowa zdolność = nowa funkcja + entry w registry,
zero zmian w aggregator code.

Aktywne abilities (typ=active w abilities.yaml: 12 entries) **nie są** w tym
module — żyją w `interrupts.py` (pkt 12 przerwania: Rozkaz/Klątwa/Oznaczenie/
Usprawnienie/Koordynacja/Przekaźnik) lub w `phases.py` jako akcja specjalna
(pkt 14.e: Łatanie/Mag/Męczennik/Mobilizacja/Presja/Przepowiednia).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from app.services.engine.state import BattleState, UnitBlob, WeaponProfile
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_UFORTYFIKOWANY,
    STATUS_WYCZERPANY,
    remove_status,
)

if TYPE_CHECKING:
    from app.services.engine.events import BattleEvent

# STATUS_* re-exported jako symbole modułu dla wstecznej kompatybilności call
# sites trzymających `from app.services.engine.effects import STATUS_AKTYWOWANY`.
# Kanoniczne źródło: `app.services.engine.status`.


@dataclass(frozen=True, slots=True)
class EffectContext:
    """Read-only context dla passive ability evaluation.

    `blob` = oddział którego modifier liczymy. `state` (opcjonalny) = pełen
    BattleState dla zdolności wymagających queries (np. Maskowanie "gdy >3"
    od wrogów"). `weapon` (opcjonalny) = profil broni dla weapon-level modifiers.
    `is_charging` / `is_being_charged` = flagi szarży (Furia, Impet, Kontra).
    """

    blob: UnitBlob
    state: BattleState | None = None
    weapon: WeaponProfile | None = None
    is_charging: bool = False
    is_being_charged: bool = False


# Hook function types
DefenseModifierFn = Callable[[EffectContext], int]
AttackModifierFn = Callable[[EffectContext], int]
MoraleModifierFn = Callable[[EffectContext], int]
WeaponModifierFn = Callable[[WeaponProfile, UnitBlob], WeaponProfile]

# Per-hook registries (slug → fn)
_DEFENSE_MODIFIERS: dict[str, DefenseModifierFn] = {}
_ATTACK_MODIFIERS: dict[str, AttackModifierFn] = {}
_MORALE_MODIFIERS: dict[str, MoraleModifierFn] = {}
_WEAPON_MODIFIERS: dict[str, WeaponModifierFn] = {}


# ---------------------------------------------------------------------------
# Registration decorators
# ---------------------------------------------------------------------------


def register_defense_modifier(slug: str) -> Callable[[DefenseModifierFn], DefenseModifierFn]:
    def decorator(fn: DefenseModifierFn) -> DefenseModifierFn:
        if slug in _DEFENSE_MODIFIERS:
            raise RuntimeError(f"defense_modifier for {slug!r} already registered")
        _DEFENSE_MODIFIERS[slug] = fn
        return fn

    return decorator


def register_attack_modifier(slug: str) -> Callable[[AttackModifierFn], AttackModifierFn]:
    def decorator(fn: AttackModifierFn) -> AttackModifierFn:
        if slug in _ATTACK_MODIFIERS:
            raise RuntimeError(f"attack_modifier for {slug!r} already registered")
        _ATTACK_MODIFIERS[slug] = fn
        return fn

    return decorator


def register_morale_modifier(slug: str) -> Callable[[MoraleModifierFn], MoraleModifierFn]:
    def decorator(fn: MoraleModifierFn) -> MoraleModifierFn:
        if slug in _MORALE_MODIFIERS:
            raise RuntimeError(f"morale_modifier for {slug!r} already registered")
        _MORALE_MODIFIERS[slug] = fn
        return fn

    return decorator


def register_weapon_modifier(slug: str) -> Callable[[WeaponModifierFn], WeaponModifierFn]:
    def decorator(fn: WeaponModifierFn) -> WeaponModifierFn:
        if slug in _WEAPON_MODIFIERS:
            raise RuntimeError(f"weapon_modifier for {slug!r} already registered")
        _WEAPON_MODIFIERS[slug] = fn
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Aggregators — sum modifiers from blob's passive abilities
# ---------------------------------------------------------------------------


def aggregate_defense_modifier(context: EffectContext) -> int:
    """Sum defense modifiers z wszystkich passive abilities w `context.blob`.

    Zwraca delta do `modifier` argumentu `dice.roll_with_threshold(threshold=
    blob.defense, modifier=...)`. Wartość dodatnia ⇒ łatwiej obronić.
    """
    total = 0
    for slug in context.blob.passives:
        fn = _DEFENSE_MODIFIERS.get(slug)
        if fn is not None:
            total += fn(context)
    return total


def aggregate_attack_modifier(context: EffectContext) -> int:
    """Sum attack modifiers — analogicznie do defense."""
    total = 0
    for slug in context.blob.passives:
        fn = _ATTACK_MODIFIERS.get(slug)
        if fn is not None:
            total += fn(context)
    return total


def aggregate_morale_modifier(context: EffectContext) -> int:
    """Sum morale modifiers (`+/-` do liczby testów Przegrupowania pkt 20.d).

    Wartość ujemna = mniej testów (lepiej dla oddziału, np. Nieustraszony -1).
    """
    total = 0
    for slug in context.blob.passives:
        fn = _MORALE_MODIFIERS.get(slug)
        if fn is not None:
            total += fn(context)
    return total


def apply_weapon_modifiers(weapon: WeaponProfile, blob: UnitBlob) -> WeaponProfile:
    """Pipe weapon przez wszystkie weapon modifiers z passive abilities bloba.

    Kolejność: każdy modifier w kolejności rejestracji `blob.passives` tuple.
    """
    current = weapon
    for slug in blob.passives:
        fn = _WEAPON_MODIFIERS.get(slug)
        if fn is not None:
            current = fn(current, blob)
    return current


# ---------------------------------------------------------------------------
# Concrete passive abilities (MVP — 3 representative)
# ---------------------------------------------------------------------------


@register_defense_modifier("cierpliwy")
def _cierpliwy_defense(context: EffectContext) -> int:
    """Cierpliwy (id 3): +1 do testów obrony jeśli oddział nie rozpoczął
    aktywacji w tej rundzie.

    Proxy: nie ma stanu Aktywowany. (Pkt 22.d.ii: Aktywowany odrzucany na
    końcu rundy — czyli oddział "rozpoczął aktywację" gdy ma Aktywowany.)
    """
    if STATUS_AKTYWOWANY in context.blob.status_flags:
        return 0
    return 1


@register_defense_modifier("tarcza")
def _tarcza_defense(context: EffectContext) -> int:
    """Tarcza (id 34): +1 do testów obrony gdy nie Przyszpilony."""
    if STATUS_PRZYSZPILONY in context.blob.status_flags:
        return 0
    return 1


@register_morale_modifier("nieustraszony")
def _nieustraszony_morale(context: EffectContext) -> int:
    """Nieustraszony (id 16): wykonuje jeden test Przegrupowania mniej (pkt 20.d)."""
    return -1


# ---------------------------------------------------------------------------
# B3.9.e (ADR-0047) — ACTIVE_ABILITY_REGISTRY (Akcja Specjalna pkt 14.e)
# ---------------------------------------------------------------------------
#
# Aktywne zdolności (typ=active w `abilities.yaml`) były pre-B3.9.e hardcoded w
# `phases._apply_special` przez `if slug == "discard_exhausted"` — nie skalowało
# się na ~6 aktywnych z B3.0.1 audit (Łatanie/Mag/Mobilizacja/Presja/
# Przepowiednia/Męczennik) ani na przyszłe zdolności. Dziura E z post-B3 code
# review.
#
# Registry pattern (`_ACTIVE_ABILITY_REGISTRY: dict[slug → handler]`) wzorowany
# na `_DEFENSE_MODIFIERS` etc. Handler signature: `(state, actor_blob, payload)
# → (new_state, events, next_seq)`. `phases._apply_special` lookup po slug,
# delegate do handlera.


ActiveAbilityHandler = Callable[
    [BattleState, UnitBlob, dict[str, Any], int],
    tuple[BattleState, "tuple[BattleEvent, ...]", int],
]


_ACTIVE_ABILITY_REGISTRY: dict[str, ActiveAbilityHandler] = {}


def register_active_ability(
    slug: str,
) -> Callable[[ActiveAbilityHandler], ActiveAbilityHandler]:
    """Dekorator rejestrujący handler aktywnej zdolności (pkt 14.e Akcja
    Specjalna). Slug ≈ entry w `app/rulesets/v1/abilities.yaml` (type=active)
    lub uniwersalny ("discard_exhausted" pkt 22.a.ii).

    Handler kontrakt: `(state, actor_blob, payload, sequence) → (new_state,
    events, next_sequence)`. Pure function — bez DB / mutacji.
    """

    def decorator(fn: ActiveAbilityHandler) -> ActiveAbilityHandler:
        if slug in _ACTIVE_ABILITY_REGISTRY:
            raise RuntimeError(f"active_ability for {slug!r} already registered")
        _ACTIVE_ABILITY_REGISTRY[slug] = fn
        return fn

    return decorator


def get_active_ability(slug: str) -> ActiveAbilityHandler | None:
    """Lookup handlera. `None` gdy slug nie jest zarejestrowany."""
    return _ACTIVE_ABILITY_REGISTRY.get(slug)


# ---------------------------------------------------------------------------
# Built-in active abilities — discard_exhausted + 6 MVP stubs
# ---------------------------------------------------------------------------


@register_active_ability("discard_exhausted")
def _ability_discard_exhausted(
    state: BattleState,
    actor: UnitBlob,
    payload: dict[str, Any],
    sequence: int,
) -> tuple[BattleState, "tuple[BattleEvent, ...]", int]:
    """Pkt 22.a.ii — Odrzuć status Wyczerpany jako Akcja Specjalna.

    Uniwersalna zdolność dostępna dla każdego oddziału (nie wymaga konkretnej
    aktywnej zdolności w `passives`). Emit `EffectApplied(slug="discard_exhausted")`
    + `StatusRemoved(Wyczerpany)` gdy faktycznie obecny (B3.9.d / ADR-0046).
    """
    from dataclasses import replace as _replace

    from app.services.engine.events import EffectApplied, StatusRemoved

    had_wyczerpany = STATUS_WYCZERPANY in actor.status_flags
    if not had_wyczerpany:
        # No-op gdy oddział nie był Wyczerpany — emit annotation z
        # `applied: False` żeby caller widział że akcja nie miała efektu
        # (zgodnie z CR-fix C discriminator pattern).
        ev = EffectApplied(
            sequence=sequence,
            slug="discard_exhausted",
            target_unit_id=actor.id,
            source_unit_id=actor.id,
            payload={"applied": False, "note": "no-op — oddział nie był Wyczerpany"},
        )
        return state, (ev,), sequence + 1

    # CR-fix (reuse): `remove_status` helper zamiast inline tuple filter.
    new_actor = remove_status(actor, STATUS_WYCZERPANY)
    new_state = _replace(
        state,
        blobs=tuple(new_actor if b.id == actor.id else b for b in state.blobs),
    )
    events = (
        EffectApplied(
            sequence=sequence,
            slug="discard_exhausted",
            target_unit_id=actor.id,
            source_unit_id=actor.id,
            payload={"applied": True, "status_removed": STATUS_WYCZERPANY},
        ),
        StatusRemoved(
            sequence=sequence + 1,
            target_id=actor.id,
            status=STATUS_WYCZERPANY,
        ),
    )
    return new_state, events, sequence + 2


def _stub_active_ability(
    slug: str, note: str
) -> Callable[
    [BattleState, UnitBlob, dict[str, Any], int],
    tuple[BattleState, "tuple[BattleEvent, ...]", int],
]:
    """Factory dla MVP stubów — emit `EffectApplied` z note, brak state mutation.

    Konkretna implementacja każdej zdolności w przyszłych iteracjach (Łatanie =
    heal target, Mag = ranged psychic attack, Mobilizacja = remove Aktywowany
    z innego oddziału, Presja = +2 melee_balance na target przeciwnika,
    Przepowiednia = peek dice queue, Męczennik = self-sacrifice).
    """

    def handler(
        state: BattleState,
        actor: UnitBlob,
        payload: dict[str, Any],
        sequence: int,
    ) -> tuple[BattleState, "tuple[BattleEvent, ...]", int]:
        from app.services.engine.events import EffectApplied

        # CR-fix D: payload.get("target_unit_id", actor.id) zwraca None gdy
        # klucz JEST z wartością None (default fires only when key missing).
        # int(None) raises TypeError → crash _apply_special → activation_phase
        # zostaje w stanie mid-action. Guard explicitly.
        tid = payload.get("target_unit_id")
        target_unit_id = int(tid) if tid is not None else actor.id
        # CR-fix C: `applied: False` discriminator + INCOMPLETE_ABILITIES set
        # pozwala konsumentom rozróżnić stub od pełnej implementacji bez
        # parsowania freeform `note` string-a.
        ev = EffectApplied(
            sequence=sequence,
            slug=slug,
            target_unit_id=target_unit_id,
            source_unit_id=actor.id,
            payload={"applied": False, "note": note, **payload},
        )
        return state, (ev,), sequence + 1

    handler.__name__ = f"_ability_{slug}_stub"
    return handler


# 6 aktywnych zdolności per B3.0.1 audit. MVP stubs — pełne implementacje w
# kolejnych iteracjach, ale registry pattern pozwala je dodawać przyrostowo
# bez zmian w `phases._apply_special` dispatcher.
#
# CR-fix C: `INCOMPLETE_ABILITIES` to **publiczny discriminator** dla
# konsumentów (resolver validation, UI feedback, agent decision logging).
# Stuby emit `EffectApplied(payload={'applied': False, ...})` zamiast
# pretending success — caller może filtrować po `applied` lub sprawdzać slug
# przeciw `INCOMPLETE_ABILITIES`. Pełne implementacje (po B3.9.f+) dodadzą
# `applied: True` i usuną slug z tego setu.
INCOMPLETE_ABILITIES: frozenset[str] = frozenset(
    {"latanie", "mag", "mobilizacja", "presja", "przepowiednia", "meczennik"}
)

_ACTIVE_ABILITY_REGISTRY["latanie"] = _stub_active_ability(
    "latanie", "MVP stub — heal target +1 wounds_received decrement (B3.9.f+)"
)
_ACTIVE_ABILITY_REGISTRY["mag"] = _stub_active_ability(
    "mag", "MVP stub — psychic ranged attack on target (B3.9.f+)"
)
_ACTIVE_ABILITY_REGISTRY["mobilizacja"] = _stub_active_ability(
    "mobilizacja", "MVP stub — remove Aktywowany na sojuszniku (B3.9.f+)"
)
_ACTIVE_ABILITY_REGISTRY["presja"] = _stub_active_ability(
    "presja", "MVP stub — +2 do melee_balance przeciwnika (B3.9.f+)"
)
_ACTIVE_ABILITY_REGISTRY["przepowiednia"] = _stub_active_ability(
    "przepowiednia", "MVP stub — peek/reroll dice queue (B3.9.f+)"
)
_ACTIVE_ABILITY_REGISTRY["meczennik"] = _stub_active_ability(
    "meczennik", "MVP stub — self-sacrifice transfer wounds to target (B3.9.f+)"
)
