"""B3.9.e — testy `UnitBlob` weapons inventory + `_ACTIVE_ABILITY_REGISTRY`
(ADR-0047).

Pokrywa:
- `WeaponProfile` re-export (state.py canonical, combat.py backward-compat).
- `UnitBlob.melee_weapons`/`ranged_weapons` default + immutability.
- `build_initial_state` parsuje `unit["weapons"]` (dict + WeaponProfile),
  partycja po `range_inches`.
- **Fix #7**: `resolve_charge_attack` counter używa `defender.melee_weapons[0]`
  zamiast attacker.weapon; fallback gdy inventory pusty.
- `_ACTIVE_ABILITY_REGISTRY` — `register_active_ability` decorator + duplicate
  detection + `get_active_ability` lookup + handler dispatch przez
  `phases._apply_special`.
- Built-in `discard_exhausted` (full impl) + 6 stubów (Łatanie/Mag/...).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from app.services.engine.actions import ChargeAction, SpecialAction
from app.services.engine.combat import WeaponProfile as WeaponProfileFromCombat
from app.services.engine.combat import resolve_charge_attack
from app.services.engine.dice import DeterministicDice
from app.services.engine.effects import (
    _ACTIVE_ABILITY_REGISTRY,
    get_active_ability,
    register_active_ability,
)
from app.services.engine.events import EffectApplied, StatusRemoved
from app.services.engine.phases import _apply_special
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    WeaponProfile,
    build_initial_state,
)


# ---------------------------------------------------------------------------
# WeaponProfile re-export — backward compat
# ---------------------------------------------------------------------------


def test_weapon_profile_canonical_in_state_module():
    """`state.WeaponProfile` jest kanonicznym źródłem. `combat.WeaponProfile`
    re-eksportuje ten sam obiekt."""
    assert WeaponProfileFromCombat is WeaponProfile


# ---------------------------------------------------------------------------
# UnitBlob weapons fields — default + immutability
# ---------------------------------------------------------------------------


def _make_blob(uid: int = 1, **kwargs) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": 0,
        "position": Position(x=0.0, y=0.0),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kwargs)
    return UnitBlob(**defaults)


def test_unit_blob_default_weapons_empty():
    blob = _make_blob()
    assert blob.melee_weapons == ()
    assert blob.ranged_weapons == ()


def test_unit_blob_weapons_immutability():
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=2)
    blob = _make_blob(melee_weapons=(weapon,))
    with pytest.raises(FrozenInstanceError):
        blob.melee_weapons = ()  # type: ignore[misc]


def test_unit_blob_weapons_via_replace():
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=2)
    blob = _make_blob()
    blob2 = replace(blob, melee_weapons=(weapon,))
    assert blob2.melee_weapons == (weapon,)
    assert blob.melee_weapons == ()  # original unchanged


# ---------------------------------------------------------------------------
# build_initial_state — parses unit["weapons"]
# ---------------------------------------------------------------------------


def _roster_with_weapons(weapons: list) -> list[dict]:
    return [
        {
            "owner_player": 0,
            "units": [
                {
                    "id": 1,
                    "position": (0.0, 0.0),
                    "models": 5,
                    "toughness": 3,
                    "weapons": weapons,
                }
            ],
        },
        {
            "owner_player": 1,
            "units": [
                {
                    "id": 2,
                    "position": (10.0, 0.0),
                    "models": 5,
                    "toughness": 3,
                }
            ],
        },
    ]


def test_build_initial_state_partitions_weapons_by_range():
    """`range_inches > 0` → ranged_weapons; `== 0` → melee_weapons."""
    rifle = {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 1}
    sword = {"slug": "sword", "name": "Sword", "range_inches": 0, "attacks": 2}
    state = build_initial_state(_roster_with_weapons([rifle, sword]))
    blob1 = next(b for b in state.blobs if b.id == 1)
    assert len(blob1.melee_weapons) == 1
    assert blob1.melee_weapons[0].slug == "sword"
    assert len(blob1.ranged_weapons) == 1
    assert blob1.ranged_weapons[0].slug == "rifle"


def test_build_initial_state_accepts_weapon_profile_instances():
    """`unit["weapons"]` może zawierać gotowe `WeaponProfile` (nie tylko dicty)."""
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=2)
    state = build_initial_state(_roster_with_weapons([weapon]))
    blob1 = next(b for b in state.blobs if b.id == 1)
    assert blob1.melee_weapons == (weapon,)


def test_build_initial_state_missing_weapons_empty_inventory():
    """Brak `unit["weapons"]` → oba tuples puste (backward compat)."""
    state = build_initial_state(_roster_with_weapons([]))
    blob1 = next(b for b in state.blobs if b.id == 1)
    assert blob1.melee_weapons == ()
    assert blob1.ranged_weapons == ()


def test_build_initial_state_weapon_ap_and_abilities_propagated():
    """AP + weapon_abilities z dict-a poprawnie mapowane na `WeaponProfile`."""
    weapon = {
        "slug": "rifle",
        "name": "Rifle",
        "range_inches": 24,
        "attacks": 1,
        "ap": 2,
        "weapon_abilities": ["brutalny", "precyzyjny"],
    }
    state = build_initial_state(_roster_with_weapons([weapon]))
    blob1 = next(b for b in state.blobs if b.id == 1)
    assert blob1.ranged_weapons[0].ap == 2
    assert blob1.ranged_weapons[0].weapon_abilities == ("brutalny", "precyzyjny")


# ---------------------------------------------------------------------------
# Fix #7 — counter-attack uses defender.melee_weapons[0]
# ---------------------------------------------------------------------------


def _basic_state(charger: UnitBlob, defender: UnitBlob) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(charger, defender),
        terrain=(),
    )


def test_fix7_counter_uses_defender_melee_weapon():
    """B3.9.e fix #7: counter-attack używa `defender.melee_weapons[0]` zamiast
    charger.weapon. Test: defender ma weapon ze slug "defender_sword" — counter
    eventów MeleeResolved ma `weapon_slug == "defender_sword"`."""
    charger_weapon = WeaponProfile(
        slug="charger_sword", name="Charger Sword", range_inches=0, attacks=2
    )
    defender_weapon = WeaponProfile(
        slug="defender_sword", name="Defender Sword", range_inches=0, attacks=3
    )
    charger = _make_blob(uid=1, position=Position(8, 0), quality=3)
    defender = _make_blob(
        uid=2,
        owner_player=1,
        position=Position(12, 0),
        defense=4,
        melee_weapons=(defender_weapon,),
    )
    state = _basic_state(charger, defender)
    result = resolve_charge_attack(
        state, charger, defender, charger_weapon, DeterministicDice(42), sequence=1
    )
    # Sekwencja eventów Szarży: MoveExecuted + counter MeleeResolved (defender→charger)
    # + (opcjonalnie ModelKilled) + StatusAdded(Wyczerpany) + charger MeleeResolved.
    # Counter event to PIERWSZY MeleeResolved (defender jest tam attackerem).
    melee_events = [
        e for e in result.events if type(e).__name__ == "MeleeResolved"
    ]
    assert len(melee_events) >= 1
    counter = next(e for e in melee_events if e.attacker_id == 2)
    assert counter.weapon_slug == "defender_sword", (
        f"Counter musi używać defender weapon, dostałem {counter.weapon_slug!r}"
    )


def test_fix7_fallback_when_defender_melee_empty():
    """CR-fix E: defender bez `melee_weapons` → fallback do `UNARMED_WEAPON`
    (1 atak, AP 0) zamiast charger.weapon. Pre-fix fallback wracał do broni
    atakującego — silently reintroducing bug #7 dla ranged-only units."""
    charger_weapon = WeaponProfile(
        slug="charger_sword", name="Charger Sword", range_inches=0, attacks=2
    )
    charger = _make_blob(uid=1, position=Position(8, 0), quality=3)
    defender = _make_blob(
        uid=2, owner_player=1, position=Position(12, 0), defense=4
    )  # melee_weapons = () default
    state = _basic_state(charger, defender)
    result = resolve_charge_attack(
        state, charger, defender, charger_weapon, DeterministicDice(42), sequence=1
    )
    melee_events = [e for e in result.events if type(e).__name__ == "MeleeResolved"]
    counter = next((e for e in melee_events if e.attacker_id == 2), None)
    if counter is not None:
        # Fallback → UNARMED_WEAPON, NIE charger weapon
        assert counter.weapon_slug == "unarmed"
        assert counter.weapon_slug != "charger_sword"


# ---------------------------------------------------------------------------
# ACTIVE_ABILITY_REGISTRY — register / lookup / duplicate detection
# ---------------------------------------------------------------------------


def test_registry_built_in_discard_exhausted_present():
    assert get_active_ability("discard_exhausted") is not None


def test_registry_built_in_six_stubs_present():
    for slug in ("latanie", "mag", "mobilizacja", "presja", "przepowiednia", "meczennik"):
        assert get_active_ability(slug) is not None, f"missing stub: {slug}"


def test_registry_lookup_unknown_returns_none():
    assert get_active_ability("nonexistent_xyz_99") is None


def test_register_active_ability_decorator_duplicate_raises():
    """Re-registracja tego samego slug → RuntimeError."""
    # Czyścimy globalny rejestr na czas testu (przywracamy po) — używamy
    # syntetycznego slugu żeby nie zepsuć innych testów.
    slug = "test_ability_unique_xyz_001"
    assert slug not in _ACTIVE_ABILITY_REGISTRY

    @register_active_ability(slug)
    def _handler(state, actor, payload, sequence):  # noqa: ANN001
        return state, (), sequence

    try:
        with pytest.raises(RuntimeError, match=slug):

            @register_active_ability(slug)
            def _handler2(state, actor, payload, sequence):  # noqa: ANN001
                return state, (), sequence
    finally:
        del _ACTIVE_ABILITY_REGISTRY[slug]


# ---------------------------------------------------------------------------
# _apply_special — delegacja do registry
# ---------------------------------------------------------------------------


def test_apply_special_discard_exhausted_full_impl():
    """`discard_exhausted` przez registry: EffectApplied + StatusRemoved gdy
    Wyczerpany faktycznie był."""
    blob = _make_blob(uid=1, status_flags=("Wyczerpany",))
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 0),
        blobs=(blob,),
        terrain=(),
    )
    action = SpecialAction(unit_id=1, ability_slug="discard_exhausted")
    new_state, events, next_seq = _apply_special(state, action, sequence=10)
    assert next_seq == 12  # EffectApplied + StatusRemoved
    types = [type(e).__name__ for e in events]
    assert "EffectApplied" in types
    assert "StatusRemoved" in types
    new_blob = next(b for b in new_state.blobs if b.id == 1)
    assert "Wyczerpany" not in new_blob.status_flags


def test_apply_special_discard_exhausted_noop_when_not_wyczerpany():
    """`discard_exhausted` gdy oddział nie był Wyczerpany → tylko EffectApplied
    annotation, brak StatusRemoved (replay invariant: StatusRemoved tylko gdy
    faktyczna zmiana)."""
    blob = _make_blob(uid=1, status_flags=())
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 0),
        blobs=(blob,),
        terrain=(),
    )
    action = SpecialAction(unit_id=1, ability_slug="discard_exhausted")
    _, events, next_seq = _apply_special(state, action, sequence=5)
    assert next_seq == 6  # tylko EffectApplied
    types = [type(e).__name__ for e in events]
    assert types == ["EffectApplied"]


def test_apply_special_stub_latanie_emits_annotation():
    """Stub `latanie` → EffectApplied annotation z note opisującym docelową
    semantykę, brak state mutation."""
    blob = _make_blob(uid=1)
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 0),
        blobs=(blob,),
        terrain=(),
    )
    action = SpecialAction(
        unit_id=1, ability_slug="latanie", payload={"target_unit_id": 1}
    )
    new_state, events, _ = _apply_special(state, action, sequence=1)
    assert new_state is state  # no state mutation in stub
    assert len(events) == 1
    assert isinstance(events[0], EffectApplied)
    assert events[0].slug == "latanie"
    assert "note" in events[0].payload


def test_apply_special_unknown_slug_no_op_annotation():
    """Slug spoza registry → no-op `EffectApplied` z note (poprzednia semantyka)."""
    blob = _make_blob(uid=1)
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 0),
        blobs=(blob,),
        terrain=(),
    )
    action = SpecialAction(unit_id=1, ability_slug="nonexistent_xyz_99")
    new_state, events, _ = _apply_special(state, action, sequence=1)
    assert new_state is state
    assert len(events) == 1
    assert isinstance(events[0], EffectApplied)
    assert events[0].slug == "nonexistent_xyz_99"
    assert "not registered" in events[0].payload["note"]
