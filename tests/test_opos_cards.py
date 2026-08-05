import json

from app import models
from app.services.cards import build_card_pages, build_unit_cards
from app.services.icon_sprite import render_card_icon


def _unit(*, passives: list[str] | None = None, copies: int = 7) -> models.RosterUnit:
    return models.RosterUnit(
        name="Gwardia",
        models_per_unit=12,
        unit_copies=copies,
        defense=4,
        toughness=2,
        passive_abilities_json=json.dumps(passives or ["steadfast"]),
        special_abilities_json="[]",
        profiles_json=json.dumps(
            {
                "melee": {"dice": 1, "strength": 1, "abilities": []},
                "short": {"dice": 2, "strength": 0, "abilities": ["double"]},
                "long": {"dice": 0, "strength": 0, "abilities": []},
            }
        ),
        position=0,
        unit_cost=83,
    )


def test_one_primary_card_is_created_independent_of_copy_count() -> None:
    cards = build_unit_cards(_unit(copies=99), ruleset_version="v1")

    assert len(cards) == 1
    assert cards[0]["kind"] == "profile"
    assert cards[0]["unit_cost"] == 83
    assert "models_per_unit" not in cards[0]
    assert "unit_copies" not in cards[0]


def test_overflow_abilities_create_continuation_without_shrinking() -> None:
    passives = [
        "hero", "ambush", "scout", "agile", "fast", "jump", "dodge",
        "parry", "steadfast", "patient", "breakthrough", "guardian",
        "counterattack",
    ]

    cards = build_unit_cards(_unit(passives=passives), ruleset_version="v1")

    assert [card["kind"] for card in cards] == ["profile", "continuation"]
    assert len(cards[0]["abilities"]) == 6
    assert len(cards[1]["abilities"]) == 7


def test_continuation_cards_never_exceed_eight_descriptions() -> None:
    passives = [
        "hero", "ambush", "scout", "agile", "fast", "immobile", "jump",
        "dodge", "parry", "steadfast", "patient", "breakthrough", "guardian",
        "counterattack", "airplane",
    ]

    cards = build_unit_cards(_unit(passives=passives), ruleset_version="v1")

    assert [len(card["abilities"]) for card in cards] == [6, 8, 1]


def test_collapsed_descriptions_do_not_change_card_capacity() -> None:
    passives = [
        "hero", "ambush", "scout", "agile", "fast", "jump", "dodge",
        "parry", "steadfast", "patient", "breakthrough", "guardian",
        "counterattack",
    ]

    cards = build_unit_cards(
        _unit(passives=passives),
        ruleset_version="v1",
        collapse_descriptions=True,
    )

    assert [len(card["abilities"]) for card in cards] == [6, 7]


def test_pages_are_padded_to_a_four_card_a4_grid() -> None:
    pages = build_card_pages([_unit(), _unit(), _unit()], ruleset_version="v1")

    assert len(pages) == 1
    assert len(pages[0]) == 4
    assert pages[0][-1] is None


def test_card_icon_expands_master_sprite_without_external_use() -> None:
    rendered = str(render_card_icon("steadfast"))

    assert 'class="card-icon"' in rendered
    assert "ns0:" not in rendered
    assert "<use" not in rendered
    assert rendered.count("<path") >= 3
