
from __future__ import annotations

import json

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.services import ability_registry, costs, utils

if not hasattr(utils, "HIDDEN_TRAIT_SLUGS"):
    utils.HIDDEN_TRAIT_SLUGS = set()

from app.routers import rosters


class DummySession:
    def __init__(self, abilities: list[models.Ability] | None = None):
        self._abilities = list(abilities) if abilities else []

    def execute(self, _statement):  # pragma: nocover - simple stub
        return self

    def scalars(self):  # pragma: nocover - simple stub
        return self

    def all(self) -> list[models.Ability]:  # pragma: nocover - simple stub
        return list(self._abilities)

    def add(self, ability: models.Ability) -> None:  # pragma: nocover - simple stub
        self._abilities.append(ability)

    def flush(self) -> None:  # pragma: nocover - simple stub
        return None



def _make_unit() -> models.Unit:
    unit = models.Unit(
        name="Test",
        quality=4,
        defense=3,
        toughness=4,
        army_id=1,
    )
    unit.abilities = []
    unit.weapon_links = []
    return unit



def test_unit_ability_payload_includes_custom_name():
    unit = _make_unit()
    ability = models.Ability(
        id=7,
        name="Mag(2)",
        type="active",
        description="",
    )
    ability.config_json = json.dumps({"slug": "mag"})
    link = models.UnitAbility(
        position=0,
        ability=ability,
        params_json=json.dumps({"value": "2", "custom_name": "Psyker"}),
    )
    unit.abilities = [link]

    payload = ability_registry.unit_ability_payload(unit, "active")

    assert payload
    entry = payload[0]
    assert entry["custom_name"] == "Psyker"
    assert entry["label"] == "Mag(2)"
    assert entry["base_label"] == "Mag(2)"


def test_build_unit_abilities_stores_trimmed_custom_name():
    ability = models.Ability(id=5, name="Aura", type="aura", description="")
    ability.config_json = json.dumps({"slug": "aura"})
    session = DummySession([ability])

    entries = ability_registry.build_unit_abilities(
        session,
        [
            {
                "ability_id": ability.id,
                "value": "",  # optional
                "custom_name": "  Medyk  ",
            }
        ],
        "aura",
    )

    assert entries
    params = json.loads(entries[0].params_json)
    assert params["custom_name"] == "Medyk"
    assert "value" not in params


def test_selected_ability_entries_use_unit_custom_names():
    loadout = {"active": {"7": 1}}
    ability_items = [
        {
            "ability_id": 7,
            "label": "Aura: Regeneracja",
            "custom_name": "Medyk",
            "description": "",
        }
    ]


    selected = rosters._selected_ability_entries(loadout, ability_items, "active")

    assert selected and selected[0]["custom_name"] == "Medyk"
    assert selected[0]["label"] == "Aura: Regeneracja"



def test_ability_label_with_count_uses_custom_name():
    entry = {"label": "Aura: Regeneracja", "count": 1, "custom_name": "Medyk"}

    assert rosters._ability_label_with_count(entry) == "Medyk [Aura: Regeneracja]"

    entry_with_count = {"label": "Mag", "count": 2, "custom_name": "Psyker"}

    assert rosters._ability_label_with_count(entry_with_count) == "Psyker [Mag] ×2"


def test_definition_payload_excludes_disallowed_aura_and_order_choices():
    aura_disallowed = {
        "zasadzka",
        "zwiadowca",
        "nieruchomy",
        "samolot",
        "dobrze_strzela",
        "zle_strzela",
        "roj",
        "zwrot",
        "bohater",
        "ochroniarz",
        "transport",
        "sekcje",
        "rezerwa",
        "odwody",
    }
    order_disallowed = {
        "zasadzka",
        "zwiadowca",
        "samolot",
        "dobrze_strzela",
        "zle_strzela",
        "roj",
        "zwrot",
        "bohater",
        "ochroniarz",
        "transport",
        "sekcje",
        "rezerwa",
        "odwody",
        "zdobywca",
    }

    session = DummySession()

    aura_payload = ability_registry.definition_payload(session, "aura")
    aura_entry = next(item for item in aura_payload if item["slug"] == "aura")
    assert aura_entry["value_choices"]
    for choice in aura_entry["value_choices"]:
        value = str(choice["value"])
        ability_slug = value.split("|", 1)[0]
        assert ability_slug not in aura_disallowed

    active_payload = ability_registry.definition_payload(session, "active")
    order_entry = next(item for item in active_payload if item["slug"] == "rozkaz")
    assert order_entry["value_choices"]
    for choice in order_entry["value_choices"]:
        assert str(choice["value"]) not in order_disallowed


def test_definition_payload_has_separate_long_range_aura_entry():
    session = DummySession()

    aura_payload = ability_registry.definition_payload(session, "aura")
    aura_entry = next(item for item in aura_payload if item["slug"] == "aura")
    aura_12_entry = next(item for item in aura_payload if item["slug"] == "aura_12")

    assert aura_entry["value_choices"]
    assert aura_12_entry["value_choices"]
    assert all(str(choice["value"]).endswith("|6") for choice in aura_entry["value_choices"])
    assert all(str(choice["value"]).endswith("|12") for choice in aura_12_entry["value_choices"])
    assert [choice["label"] for choice in aura_entry["value_choices"]] == [
        choice["label"] for choice in aura_12_entry["value_choices"]
    ]


def test_meczennik_aura_has_fixed_cost():
    assert costs.ability_cost_from_name("Męczennik") == 5.0


def test_passive_mistrzostwo_has_weapon_dropdown():
    """passive_definitions_for_army must expose mistrzostwo with value_choices for the JS picker."""
    from app.routers.armies import passive_definitions_for_army

    defs = passive_definitions_for_army(None)
    mistrzostwo = next((d for d in defs if d.get("slug") == "mistrzostwo"), None)

    assert mistrzostwo is not None, "mistrzostwo missing from passive_definitions"
    assert mistrzostwo.get("requires_value") is True, "requires_value must be True"
    choices = mistrzostwo.get("value_choices", [])
    assert len(choices) > 0, "value_choices must be non-empty for JS picker to show dropdown"
    # Each choice must have value and label for the JS picker to build <option> elements
    for choice in choices:
        assert "value" in choice and choice["value"], f"choice missing value: {choice}"
        assert "label" in choice and choice["label"], f"choice missing label: {choice}"
    # Excluded weapon slugs must not appear in choices
    excluded = ability_registry.EXCLUDED_MISTRZOSTWO_WEAPON_SLUGS
    for choice in choices:
        assert choice["value"] not in excluded, (
            f"excluded weapon slug {choice['value']!r} found in mistrzostwo value_choices"
        )

