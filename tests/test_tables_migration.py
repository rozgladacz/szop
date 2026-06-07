"""Faza A1 — exact match: tabele YAML vs stałe `_engine.py`.

Zabezpiecza, że `app/rulesets/v1/tables.yaml` jest wierną kopią stałych
z `app/services/costs/_engine.py:23-79`. Bez tego YAML backend (A2)
liczyłby na innych liczbach niż procedural i `both_assert` miałby
deltę != 0.

Procedural pozostaje oracle — modyfikujemy tylko YAML, nigdy odwrotnie.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.costs import _engine
from app.services.rulesets import load_ruleset


@pytest.fixture(scope="module")
def ruleset():
    return load_ruleset("v1")


@pytest.fixture(scope="module")
def tables(ruleset):
    return ruleset.tables


def test_version_is_one(ruleset) -> None:
    assert ruleset.version == 1


def test_morale_ability_multipliers(tables) -> None:
    assert tables.morale_ability_multipliers == _engine.MORALE_ABILITY_MULTIPLIERS


def test_defense_base_values(tables) -> None:
    assert tables.defense_base_values == _engine.DEFENSE_BASE_VALUES


def test_defense_ability_modifiers(tables) -> None:
    assert tables.defense_ability_modifiers == _engine.DEFENSE_ABILITY_MODIFIERS


def test_toughness_special(tables) -> None:
    assert tables.toughness_special == _engine.TOUGHNESS_SPECIAL


def test_range_table(tables) -> None:
    assert tables.range_table == _engine.RANGE_TABLE


def test_artillery_range_bonus(tables) -> None:
    assert tables.artillery_range_bonus == _engine.ARTILLERY_RANGE_BONUS


def test_unwieldy_range_penalty(tables) -> None:
    assert tables.unwieldy_range_penalty == _engine.UNWIELDY_RANGE_PENALTY


def test_cautious_hit_bonus(tables) -> None:
    assert tables.cautious_hit_bonus == _engine.CAUTIOUS_HIT_BONUS


def test_ap_base(tables) -> None:
    assert tables.ap_base == _engine.AP_BASE


def test_ap_lance(tables) -> None:
    assert tables.ap_lance == _engine.AP_LANCE


def test_penetrating_multiplier(tables) -> None:
    assert tables.penetrating_multiplier == _engine.PENETRATING_MULTIPLIER


def test_waagh_ap_modifier(tables) -> None:
    assert tables.waagh_ap_modifier == _engine.WAAGH_AP_MODIFIER


def test_blast_multiplier(tables) -> None:
    assert tables.blast_multiplier == _engine.BLAST_MULTIPLIER


def test_deadly_multiplier(tables) -> None:
    assert tables.deadly_multiplier == _engine.DEADLY_MULTIPLIER


def test_brutalny_ap_cost(tables) -> None:
    assert tables.brutalny_ap_cost == _engine.BRUTALNY_AP_COST


def test_transport_multipliers_match_procedural_pairs(tables) -> None:
    yaml_pairs = [(tm.traits_set, tm.multiplier) for tm in tables.transport_multipliers]
    expected_pairs = [(frozenset(traits), multiplier) for traits, multiplier in _engine.TRANSPORT_MULTIPLIERS]
    assert yaml_pairs == expected_pairs


def test_overcharge_multiplier(tables) -> None:
    assert tables.overcharge_multiplier == _engine.OVERCHARGE_MULTIPLIER


def test_base_cost_factor(tables) -> None:
    # Procedural `_apply_ruleset_overrides()` mógł nadpisać BASE_COST_FACTOR z
    # `app/rulesets/default.json` (uznany za nieaktualny w A1). YAML v1 trzyma
    # surową wartość 5.0; weryfikujemy zgodność z modułową stałą *po* override.
    assert tables.base_cost_factor == _engine.BASE_COST_FACTOR


def test_loader_returns_same_instance_on_second_call() -> None:
    """LRU cache → ten sam frozen manifest, zero alokacji na hot path."""
    a = load_ruleset("v1")
    b = load_ruleset("v1")
    assert a is b


def test_unknown_version_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown ruleset version"):
        load_ruleset("v999")
