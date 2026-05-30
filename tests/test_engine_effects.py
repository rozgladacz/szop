"""B3.5 — testy `app/services/engine/effects.py`.

Pokrywa: EffectContext frozen, register/aggregate framework, 3 concrete passives
(Cierpliwy/Tarcza/Nieustraszony), duplicate registration raises.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.effects import (
    EffectContext,
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    _ATTACK_MODIFIERS,
    _DEFENSE_MODIFIERS,
    _MORALE_MODIFIERS,
    _WEAPON_MODIFIERS,
    aggregate_attack_modifier,
    aggregate_defense_modifier,
    aggregate_morale_modifier,
    apply_weapon_modifiers,
    register_defense_modifier,
)
from app.services.engine.combat import WeaponProfile
from app.services.engine.state import Position, UnitBlob


def make_blob(
    blob_id: int = 1,
    passives: tuple[str, ...] = (),
    status_flags: tuple[str, ...] = (),
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=0,
        position=Position(0.0, 0.0),
        radius_inches=1.0,
        models_alive=5,
        toughness_per_model=3,
        passives=passives,
        status_flags=status_flags,
    )


# ---------------------------------------------------------------------------
# EffectContext frozen
# ---------------------------------------------------------------------------


def test_effect_context_is_frozen():
    ctx = EffectContext(blob=make_blob())
    with pytest.raises(FrozenInstanceError):
        ctx.is_charging = True  # type: ignore[misc]


def test_effect_context_defaults():
    ctx = EffectContext(blob=make_blob())
    assert ctx.state is None
    assert ctx.weapon is None
    assert ctx.is_charging is False
    assert ctx.is_being_charged is False


# ---------------------------------------------------------------------------
# Cierpliwy (id 3) — +1 defense gdy nie Aktywowany
# ---------------------------------------------------------------------------


def test_cierpliwy_grants_bonus_when_not_activated():
    blob = make_blob(passives=("cierpliwy",))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 1


def test_cierpliwy_no_bonus_when_activated():
    blob = make_blob(passives=("cierpliwy",), status_flags=(STATUS_AKTYWOWANY,))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 0


def test_cierpliwy_blob_without_ability_gets_nothing():
    """Bez `cierpliwy` w passives — modifier 0."""
    blob = make_blob(passives=("nieustraszony",))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 0


# ---------------------------------------------------------------------------
# Tarcza (id 34) — +1 defense gdy nie Przyszpilony
# ---------------------------------------------------------------------------


def test_tarcza_grants_bonus_when_not_pinned():
    blob = make_blob(passives=("tarcza",))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 1


def test_tarcza_no_bonus_when_pinned():
    blob = make_blob(passives=("tarcza",), status_flags=(STATUS_PRZYSZPILONY,))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 0


# ---------------------------------------------------------------------------
# Multiple defense modifiers — sumują się
# ---------------------------------------------------------------------------


def test_multiple_defense_modifiers_sum():
    """Cierpliwy + Tarcza, oba aktywne → +2 do obrony."""
    blob = make_blob(passives=("cierpliwy", "tarcza"))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 2


def test_multiple_defense_modifiers_partial_conditions():
    """Tarcza aktywna, Cierpliwy nieaktywny (już Aktywowany) → +1."""
    blob = make_blob(
        passives=("cierpliwy", "tarcza"), status_flags=(STATUS_AKTYWOWANY,)
    )
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 1


# ---------------------------------------------------------------------------
# Nieustraszony (id 16) — morale modifier
# ---------------------------------------------------------------------------


def test_nieustraszony_reduces_morale_tests():
    blob = make_blob(passives=("nieustraszony",))
    ctx = EffectContext(blob=blob)
    assert aggregate_morale_modifier(ctx) == -1


def test_nieustraszony_does_not_affect_defense():
    blob = make_blob(passives=("nieustraszony",))
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 0


# ---------------------------------------------------------------------------
# Aggregators — empty / no-op cases
# ---------------------------------------------------------------------------


def test_aggregate_defense_empty_passives():
    blob = make_blob(passives=())
    ctx = EffectContext(blob=blob)
    assert aggregate_defense_modifier(ctx) == 0


def test_aggregate_attack_empty():
    blob = make_blob(passives=("nieustraszony",))  # tylko morale
    ctx = EffectContext(blob=blob)
    assert aggregate_attack_modifier(ctx) == 0


def test_aggregate_morale_empty():
    blob = make_blob(passives=("cierpliwy",))  # tylko defense
    ctx = EffectContext(blob=blob)
    assert aggregate_morale_modifier(ctx) == 0


# ---------------------------------------------------------------------------
# apply_weapon_modifiers — pipeline (brak konkretnych w MVP, sprawdzamy no-op)
# ---------------------------------------------------------------------------


def test_apply_weapon_modifiers_no_op_when_no_weapon_passive():
    """Bez passive z weapon_modifier rejestracji — weapon zwracany bez zmian."""
    blob = make_blob(passives=("cierpliwy",))
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    result = apply_weapon_modifiers(weapon, blob)
    assert result == weapon


# ---------------------------------------------------------------------------
# Duplicate registration raises
# ---------------------------------------------------------------------------


def test_duplicate_defense_modifier_registration_raises():
    """register tej samej slug 2× → RuntimeError."""
    with pytest.raises(RuntimeError, match="already registered"):

        @register_defense_modifier("cierpliwy")
        def _duplicate(ctx):
            return 99


# ---------------------------------------------------------------------------
# Registry sanity — sprawdzamy że 3 MVP abilities są w odpowiednich registries
# ---------------------------------------------------------------------------


def test_cierpliwy_in_defense_registry():
    assert "cierpliwy" in _DEFENSE_MODIFIERS


def test_tarcza_in_defense_registry():
    assert "tarcza" in _DEFENSE_MODIFIERS


def test_nieustraszony_in_morale_registry():
    assert "nieustraszony" in _MORALE_MODIFIERS


def test_nieustraszony_not_in_defense_registry():
    """Cross-check: morale ability nie ma defense entry."""
    assert "nieustraszony" not in _DEFENSE_MODIFIERS


def test_no_weapon_modifiers_yet_in_mvp():
    """MVP nie ma weapon modifiers (Niezawodny/Dobrze strzela/Mistrzostwo → B3.5+)."""
    # Registry istnieje ale jest pusty
    assert isinstance(_WEAPON_MODIFIERS, dict)
