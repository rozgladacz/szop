from decimal import Decimal

import pytest

from app.services.opos_rules import load_opos_ruleset


def test_ruleset_is_cached_and_complete() -> None:
    first = load_opos_ruleset()
    second = load_opos_ruleset()

    assert first is second
    assert first.version == "1.1.0"
    assert set(first.ranges) == {"melee", "short", "long"}
    assert {item.slug for item in first.abilities_of("passive")} == {
        "hero", "ambush", "scout", "agile", "fast", "immobile", "jump",
        "dodge", "parry", "steadfast", "patient",
        "breakthrough", "guardian", "counterattack", "airplane",
    }
    assert {item.slug for item in first.abilities_of("special")} == {
        "patching", "aura", "order", "transport",
    }
    assert {item.slug for item in first.abilities_of("weapon")} == {
        "area", "deadly", "double", "reload", "artillery", "charge",
        "prepared",
    }
    assert all(item.icon and item.description for item in first.abilities)


def test_current_rule_changes_are_in_yaml() -> None:
    abilities = load_opos_ruleset().abilities_by_slug

    assert abilities["airplane"].effects.ability_cost_delta == Decimal("-1")
    assert abilities["airplane"].aura_eligible is False
    assert abilities["deadly"].effects.weapon_multiplier == Decimal("4")
    assert "6 lub mniej" in abilities["deadly"].description
    assert abilities["transport"].effects.ability_cost_delta == Decimal("2")
    assert abilities["double"].description == "Każdy sukces liczy się również jako remis."
    assert abilities["double"].effects.weapon_multiplier == Decimal("1.5")
    assert abilities["charge"].category == "weapon"
    assert abilities["charge"].allowed_ranges == ("melee",)
    assert abilities["charge"].effects.weapon_multiplier == Decimal("1.4")
    assert abilities["prepared"].category == "weapon"
    assert abilities["prepared"].allowed_ranges == ("short", "long")
    assert abilities["prepared"].effects.weapon_multiplier == Decimal("1.4")


def test_aura_target_list_is_exact() -> None:
    assert {item.slug for item in load_opos_ruleset().aura_targets} == {
        "agile", "fast", "jump", "dodge", "parry", "steadfast", "patient",
        "breakthrough", "guardian", "counterattack", "area", "deadly",
        "double", "reload", "artillery", "charge", "prepared",
    }


def test_unknown_ruleset_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        load_opos_ruleset("v999")
