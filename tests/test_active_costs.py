from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.data import abilities as ability_catalog
from app import models
from app.services import costs


def test_latanie_cost_is_20():
    assert costs.ability_cost_from_name("Łatanie") == 20.0


def test_ociezalosc_aura_cost_is_20():
    assert costs.ability_cost_from_name("Ociężałość") == 20.0


def test_mobilizacja_cost_is_30():
    assert costs.ability_cost_from_name("Mobilizacja") == 30.0


def test_usprawnienie_cost_is_60():
    assert costs.ability_cost_from_name("Usprawnienie") == 60.0


def test_ability_identifier_ignores_diacritics():
    assert costs.ability_identifier("Łatanie") == "latanie"
    assert costs.normalize_name("Żółć") == "zolc"


def test_catalog_slug_lookup_handles_diacritics():
    assert ability_catalog.slug_for_name("Łatanie") == "latanie"


def test_order_like_abilities_ignore_cost_hint_for_dynamic_cost() -> None:
    unit = models.Unit(name="U", quality=4, defense=4, toughness=1, army_id=1)
    ability = models.Ability(
        name="Klątwa: Wolny",
        type="active",
        description="",
        cost_hint=0,
        config_json='{"slug":"klatwa"}',
    )
    link = models.UnitAbility(unit=unit, ability=ability, params_json='{"value":"wolny"}')

    assert costs.ability_cost(link, [], toughness=1) == -6.0


def test_non_order_like_ability_still_uses_cost_hint() -> None:
    unit = models.Unit(name="U", quality=4, defense=4, toughness=1, army_id=1)
    ability = models.Ability(
        name="Mobilizacja",
        type="active",
        description="",
        cost_hint=0,
        config_json='{"slug":"mobilizacja"}',
    )
    link = models.UnitAbility(unit=unit, ability=ability, params_json=None)

    assert costs.ability_cost(link, [], toughness=1) == 0.0


def test_order_like_cost_detection_normalizes_slug_from_config() -> None:
    ability = models.Ability(
        name="Klątwa: Wolny",
        type="active",
        description="",
        cost_hint=0,
        config_json='{"slug":"Klątwa"}',
    )

    assert costs.ability_uses_order_like_cost(ability) is True


def test_demoralizacja_cost_is_25():
    assert costs.ability_cost_from_name("Demoralizacja") == 25.0


def test_mag_cost_scales_with_toughness():
    # X * clamp(T, 6, 18)  (polowa poprzedniego X * clamp(2T, 12, 36))
    assert costs.ability_cost_from_name("Mag", "2", toughness=1) == 12.0
    assert costs.ability_cost_from_name("Mag", "2", toughness=8) == 16.0
    assert costs.ability_cost_from_name("Mag", "2", toughness=18) == 36.0


def test_rozkaz_sign_depends_on_kierunek():
    # T=6 -> T_eff = clamp(8, 8, 24) = 8; Furia "+" -> 10, Tarcza "-" -> 6
    assert costs.ability_cost_from_name("Rozkaz", "furia", toughness=6) == 30.0
    assert costs.ability_cost_from_name("Rozkaz", "tarcza", toughness=6) == 7.5


def test_klatwa_and_oznaczenie_use_x_for_toughness_6():
    assert costs.ability_cost_from_name("Klątwa", "wolny", toughness=1) == -6.0
    assert costs.ability_cost_from_name("Oznaczenie", "furia", toughness=6) == 18.0
