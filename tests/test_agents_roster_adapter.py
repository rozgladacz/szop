"""Testy mostu ORM `Roster` → engine-dict (`roster_adapter`).

Buduje transient obiekty ORM (bez sesji DB — atrybuty/relacje wystarczają;
`effective_*` property broni czytają własne pola gdy brak `parent`). Weryfikuje
konwersję, filtrowanie zdolności (wykluczone/inert), partycję broni, `models_mode`
oraz integrację z `build_initial_state` / `simulate_from_rosters`.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from app import models
from app.services.agents import (
    AdaptResult,
    RandomPlayer,
    roster_points,
    roster_to_engine_roster,
    simulate_from_rosters,
)
from app.services import costs
from app.services.engine.state import build_initial_state


# --- helpery konstrukcji transient ORM ---------------------------------------


def _weapon(name: str, range_str: str, attacks: float, ap: int = 0, tags: str | None = None) -> models.Weapon:
    return models.Weapon(
        name=name, range=range_str, attacks=attacks, ap=ap, tags=tags, armory_id=1
    )


def _unit(
    *,
    name: str = "Oddzial",
    quality: int = 4,
    defense: int = 5,
    toughness: int = 3,
    typical_models: int = 5,
    weapons: list[tuple[models.Weapon, bool]] | None = None,
    ability_names: list[str] | None = None,
) -> models.Unit:
    unit = models.Unit(
        name=name,
        quality=quality,
        defense=defense,
        toughness=toughness,
        typical_models=typical_models,
        army_id=1,
    )
    links: list[models.UnitWeapon] = []
    for pos, (weapon, is_primary) in enumerate(weapons or []):
        links.append(
            models.UnitWeapon(
                unit=unit,
                weapon=weapon,
                is_default=True,
                default_count=1,
                is_primary=is_primary,
                position=pos,
            )
        )
    unit.weapon_links = links
    abilities: list[models.UnitAbility] = []
    for pos, ab_name in enumerate(ability_names or []):
        ability = models.Ability(name=ab_name, type="passive", description="")
        abilities.append(models.UnitAbility(unit=unit, ability=ability, position=pos))
    unit.abilities = abilities
    return unit


def _roster(roster_units: list[models.RosterUnit]) -> models.Roster:
    roster = models.Roster(name="R", army_id=1)
    roster.roster_units = roster_units
    return roster


def _ru(unit: models.Unit, count: int = 1, *, parent_id: int | None = None, position: int = 0) -> models.RosterUnit:
    return models.RosterUnit(
        unit=unit, count=count, position=position, parent_roster_unit_id=parent_id
    )


def _simple_roster(**unit_kwargs) -> models.Roster:
    return _roster([_ru(_unit(**unit_kwargs))])


# --- testy --------------------------------------------------------------------


def test_basic_conversion_shape():
    roster = _simple_roster(quality=3, defense=4, toughness=2, typical_models=5)
    result = roster_to_engine_roster(roster, owner_player=0)

    assert isinstance(result, AdaptResult)
    assert result.units["owner_player"] == 0
    blobs = result.units["units"]
    assert len(blobs) == 1
    blob = blobs[0]
    assert blob["models"] == 5
    assert blob["toughness"] == 2
    assert blob["quality"] == 3
    assert blob["defense"] == 4
    assert "position" in blob and len(blob["position"]) == 2
    assert result.dropped_excluded == []
    assert result.inert_incomplete == []


def test_weapon_partition_melee_ranged():
    karabin = _weapon("Karabin", '24"', attacks=1, ap=0)
    miecz = _weapon("Miecz", "Walka wręcz", attacks=2, ap=1, tags="Brutalny")
    roster = _roster([_ru(_unit(weapons=[(karabin, False), (miecz, True)]))])

    result = roster_to_engine_roster(roster, owner_player=0)
    weapons = result.units["units"][0]["weapons"]
    by_name = {w["name"]: w for w in weapons}
    assert by_name["Karabin"]["range_inches"] == 24
    assert by_name["Miecz"]["range_inches"] == 0
    assert by_name["Miecz"]["attacks"] == 2
    assert by_name["Miecz"]["ap"] == 1
    assert "brutalny" in by_name["Miecz"]["weapon_abilities"]

    # build_initial_state partycjonuje po range_inches → melee/ranged inventory.
    state = build_initial_state([result.units])
    blob = state.blobs[0]
    assert {w.name for w in blob.ranged_weapons} == {"Karabin"}
    assert {w.name for w in blob.melee_weapons} == {"Miecz"}


def test_primary_weapon_ordered_first_in_category():
    zwykly = _weapon("Pistolet", '12"', attacks=1)
    glowny = _weapon("Snajperka", '30"', attacks=1)
    # primary podany jako drugi w loadout, ale ma trafić na początek kategorii.
    roster = _roster([_ru(_unit(weapons=[(zwykly, False), (glowny, True)]))])
    result = roster_to_engine_roster(roster, owner_player=0)
    ranged = [w for w in result.units["units"][0]["weapons"] if w["range_inches"] > 0]
    assert ranged[0]["name"] == "Snajperka"


def test_excluded_ability_dropped_and_reported():
    roster = _roster([_ru(_unit(ability_names=["Cierpliwy", "Samolot"]))])
    result = roster_to_engine_roster(roster, owner_player=0)

    passives = result.units["units"][0]["passives"]
    assert "cierpliwy" in passives
    assert "samolot" not in passives  # odfiltrowane (inaczej UnsupportedAbilityError)
    assert "samolot" in result.dropped_excluded

    # Dict jest buildowalny mimo że oddział "miał" wykluczoną zdolność.
    build_initial_state([result.units])


def test_incomplete_ability_is_inert_but_retained():
    roster = _roster([_ru(_unit(ability_names=["Mag"]))])
    result = roster_to_engine_roster(roster, owner_player=0)
    passives = result.units["units"][0]["passives"]
    assert "mag" in passives  # przepuszczone (engine cicho ignoruje)
    assert "mag" in result.inert_incomplete


def test_models_mode_per_copy_emits_count_blobs():
    roster = _roster([_ru(_unit(typical_models=5), count=3)])
    result = roster_to_engine_roster(roster, owner_player=0, models_mode="per_copy")
    blobs = result.units["units"]
    assert len(blobs) == 3
    assert all(b["models"] == 5 for b in blobs)
    assert len({b["id"] for b in blobs}) == 3  # unikalne id


def test_models_mode_aggregate_emits_single_blob():
    roster = _roster([_ru(_unit(typical_models=5), count=3)])
    result = roster_to_engine_roster(roster, owner_player=0, models_mode="aggregate")
    blobs = result.units["units"]
    assert len(blobs) == 1
    assert blobs[0]["models"] == 15


def test_invalid_models_mode_raises():
    roster = _simple_roster()
    with pytest.raises(ValueError):
        roster_to_engine_roster(roster, owner_player=0, models_mode="bogus")


def test_attached_hero_deferred_not_emitted():
    leader = _unit(name="Lider")
    hero = _unit(name="Bohater")
    roster = _roster([_ru(leader, position=0), _ru(hero, parent_id=99, position=1)])
    result = roster_to_engine_roster(roster, owner_player=0)
    assert len(result.units["units"]) == 1  # tylko lider
    assert result.deferred_attached_heroes  # bohater zaraportowany


def test_explicit_positions_applied():
    roster = _roster([_ru(_unit(typical_models=5), count=2)])
    positions = [(10.0, 20.0), (30.0, 40.0)]
    result = roster_to_engine_roster(roster, owner_player=0, positions=positions)
    blobs = result.units["units"]
    assert blobs[0]["position"] == (10.0, 20.0)
    assert blobs[1]["position"] == (30.0, 40.0)


def test_placeholder_positions_are_distinct():
    roster = _roster([_ru(_unit(), count=3)])
    result = roster_to_engine_roster(roster, owner_player=0)
    positions = [b["position"] for b in result.units["units"]]
    assert len(set(positions)) == 3  # brak zdegenerowanego stackowania


def test_player_id_namespaces_disjoint():
    r0 = roster_to_engine_roster(_roster([_ru(_unit(), count=2)]), owner_player=0)
    r1 = roster_to_engine_roster(_roster([_ru(_unit(), count=2)]), owner_player=1)
    ids0 = {b["id"] for b in r0.units["units"]}
    ids1 = {b["id"] for b in r1.units["units"]}
    assert ids0.isdisjoint(ids1)


def test_integration_build_initial_state_two_rosters():
    karabin = _weapon("Karabin", '24"', attacks=1)
    r0 = roster_to_engine_roster(
        _roster([_ru(_unit(name="A", weapons=[(karabin, True)]), count=2)]),
        owner_player=0,
    )
    r1 = roster_to_engine_roster(
        _roster([_ru(_unit(name="B", weapons=[(karabin, True)]), count=2)]),
        owner_player=1,
    )
    state = build_initial_state([r0.units, r1.units])
    assert len([b for b in state.blobs if b.owner_player == 0]) == 2
    assert len([b for b in state.blobs if b.owner_player == 1]) == 2


def test_integration_simulate_runs_a_full_game():
    karabin = _weapon("Karabin", '24"', attacks=2)
    miecz = _weapon("Miecz", "Walka wręcz", attacks=2)
    weapons = [(karabin, True), (miecz, False)]
    r0 = roster_to_engine_roster(
        _roster([_ru(_unit(name="A", weapons=weapons), count=2)]), owner_player=0
    )
    r1 = roster_to_engine_roster(
        _roster([_ru(_unit(name="B", weapons=weapons), count=2)]), owner_player=1
    )
    players = [RandomPlayer(seed=1), RandomPlayer(seed=2)]
    result = simulate_from_rosters([r0.units, r1.units], players, seed=7)
    assert result.rounds_played >= 1


def test_roster_points_per_copy_matches_simulated_force():
    # per_copy: `count` = liczba KOPII (jak roster_to_engine_roster), nie modeli.
    # Koszt = Σ copies × quote(typical_models) — spójny z symulowaną siłą.
    from types import SimpleNamespace

    unit = _unit(quality=3, defense=4, toughness=3, typical_models=5)
    plain = _unit(typical_models=5)
    roster = _roster([_ru(unit, count=2), _ru(plain, count=1)])

    def _cost_typical(u):
        return costs.roster_unit_cost(
            SimpleNamespace(unit=u, count=u.typical_model_count, extra_weapons_json=None)
        )

    expected = 2 * _cost_typical(unit) + 1 * _cost_typical(plain)
    assert roster_points(roster) == pytest.approx(expected)
    assert roster_points(roster) > 0.0
    # 2 kopie kosztują dokładnie 2× jedną kopię (liniowość po kopiach).
    one_copy = roster_points(_roster([_ru(unit, count=1)]))
    two_copies = roster_points(_roster([_ru(unit, count=2)]))
    assert two_copies == pytest.approx(2 * one_copy)


def test_roster_points_aggregate_scales_with_total_models():
    unit = _unit(quality=3, defense=4, toughness=3, typical_models=5)
    roster = _roster([_ru(unit, count=2)])
    from types import SimpleNamespace

    expected = costs.roster_unit_cost(
        SimpleNamespace(unit=unit, count=2 * unit.typical_model_count, extra_weapons_json=None)
    )
    assert roster_points(roster, models_mode="aggregate") == pytest.approx(expected)


def test_roster_points_rejects_bad_models_mode():
    with pytest.raises(ValueError):
        roster_points(_simple_roster(), models_mode="nope")


def test_roster_points_empty_roster_is_zero():
    assert roster_points(_roster([])) == 0.0


def test_roster_points_includes_attached_heroes():
    # Punkty = pełny koszt zaplacony (attached hero liczy sie, mimo defer engine-side).
    leader = _ru(_unit(name="Lider"), position=0)
    hero = _ru(_unit(name="Bohater"), parent_id=99, position=1)
    with_hero = roster_points(_roster([leader, hero]))
    without_hero = roster_points(_roster([_ru(_unit(name="Lider"), position=0)]))
    assert with_hero > without_hero
