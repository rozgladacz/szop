"""B3.5 — testy `app/services/engine/effects.py`.

Pokrywa: EffectContext frozen, register/aggregate framework, 2 concrete defense
passives (Cierpliwy/Tarcza). Nieustraszony jest binarny (pkt 20.e — skip testów
Przegrupowania w `phases._regroup_test`), nie addytywny modifier.
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
    _WEAPON_MODIFIERS,
    aggregate_attack_modifier,
    aggregate_defense_modifier,
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
# Nieustraszony (id 16) — pkt 20.e binarny skip (NIE addytywny morale modifier)
# ---------------------------------------------------------------------------


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
    blob = make_blob(passives=("nieustraszony",))  # nie rejestruje modyfikatora ataku
    ctx = EffectContext(blob=blob)
    assert aggregate_attack_modifier(ctx) == 0


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


def test_nieustraszony_not_in_additive_registries():
    """Pkt 20.e (drift 2026-06): Nieustraszony jest binarny (skip w
    `phases._regroup_test`), NIE addytywny modyfikator — nie ma wpisu w żadnym
    z registrów effects (defense/attack/weapon)."""
    assert "nieustraszony" not in _DEFENSE_MODIFIERS
    assert "nieustraszony" not in _ATTACK_MODIFIERS
    assert "nieustraszony" not in _WEAPON_MODIFIERS


def test_no_weapon_modifiers_yet_in_mvp():
    """MVP nie ma weapon modifiers (Niezawodny/Dobrze strzela/Mistrzostwo → B3.5+)."""
    # Registry istnieje ale jest pusty
    assert isinstance(_WEAPON_MODIFIERS, dict)


# C2d3: poz. 23, full-board ranged context and edge-distance boundary.
@pytest.mark.parametrize("radii", [(0.5, 1.0), (1.0, 2.0), (3.0, 0.5)])
@pytest.mark.parametrize("gap,bonus", [(11.999, 0), (12.0, 0), (12.001, 1)])
def test_ostrozny_scans_enemy_edge_boundary(radii, gap, bonus):
    from dataclasses import replace
    from app.services.engine.state import BattleState

    actor = replace(make_blob(passives=("ostrozny",)), radius_inches=radii[0])
    enemy = replace(make_blob(2), owner_player=1, radius_inches=radii[1],
                    position=Position(sum(radii) + gap, 0))
    state = BattleState(1, 0, (1, 1), (actor, enemy), ())
    assert aggregate_attack_modifier(EffectContext(
        actor, state=state, is_ranged_attack=True,
    )) == bonus


@pytest.mark.parametrize("owner,alive,location,flags,bonus", [
    (1, 1, "front", (), 0),
    (1, 1, "front", ("Wyczerpany", "Przyszpilony"), 0),
    (0, 1, "front", (), 1),
    (1, 0, "front", (), 1),
    (1, 1, "zaplecze", (), 1),
    (1, 0, "wycofany", (), 1),
    (1, 0, "eliminowany", (), 1),
])
def test_ostrozny_enemy_population_not_just_selected_target(owner, alive, location, flags, bonus):
    from dataclasses import replace
    from app.services.engine.state import BattleState, Lokalizacja, TerrainCircle

    actor = make_blob(passives=("ostrozny",))
    target = replace(make_blob(2), owner_player=1, position=Position(30, 0))
    other = replace(make_blob(3), owner_player=owner, models_alive=alive,
                    location=Lokalizacja(location), status_flags=flags)
    wall = TerrainCircle(Position(4, 0), 1, ("Blokujacy",))
    state = BattleState(1, 0, (1, 1), (actor, target, other), (wall,))
    assert aggregate_attack_modifier(EffectContext(
        actor, state=state, is_ranged_attack=True,
    )) == bonus


@pytest.mark.parametrize("ranged,full_state,granted,expected", [
    (True, True, True, 1), (False, True, True, 0),
    (True, False, True, 0), (True, True, False, 0),
])
def test_ostrozny_explicit_context_and_deduplicated_rozkaz(ranged, full_state, granted, expected):
    from dataclasses import replace
    from app.services.engine.state import BattleState

    actor = replace(make_blob(passives=("ostrozny",)),
                    ability_overrides=(("ostrozny", granted),))
    state = BattleState(1, 0, (1, 1), (actor,), ())
    assert aggregate_attack_modifier(EffectContext(
        actor, state=state if full_state else None, is_ranged_attack=ranged,
    )) == expected
