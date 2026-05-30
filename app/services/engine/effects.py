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
from typing import Callable

from app.services.engine.combat import WeaponProfile
from app.services.engine.state import BattleState, UnitBlob

# Status flag constants (per `SZOP_Rozjemca.md pkt 22`)
STATUS_AKTYWOWANY = "Aktywowany"
STATUS_WYCZERPANY = "Wyczerpany"
STATUS_PRZYSZPILONY = "Przyszpilony"
STATUS_UFORTYFIKOWANY = "Ufortyfikowany"


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
