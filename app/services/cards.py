"""View-model kart OPOS współdzielony przez HTML i PDF."""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal

from app import models
from app.services.opos_rules import load_opos_ruleset, normalize_snapshot_abilities


PRIMARY_ABILITY_LIMIT = 6
CONTINUATION_ABILITY_LIMIT = 8


def display_number(value: object) -> str:
    number = Decimal(str(value))
    normalized = number.normalize()
    return format(normalized, "f")


def build_ability_payloads(
    unit: models.RosterUnit, *, ruleset_version: str
) -> list[dict[str, str]]:
    ruleset = load_opos_ruleset(ruleset_version)
    by_slug = ruleset.abilities_by_slug
    result: list[dict[str, str]] = []
    passives, _, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )
    for slug in passives:
        definition = by_slug[slug]
        result.append(
            {
                "slug": slug,
                "name": definition.name,
                "description": definition.description,
                "icon": definition.icon,
            }
        )
    for selection in json.loads(unit.special_abilities_json):
        definition = by_slug[selection["slug"]]
        name = definition.name
        if selection.get("target_slug"):
            target = by_slug[selection["target_slug"]]
            name = f"{name} ({target.name})"
        result.append(
            {
                "slug": selection["slug"],
                "name": name,
                "description": definition.description,
                "icon": definition.icon,
            }
        )
    return result


def build_profile_payloads(
    unit: models.RosterUnit, *, ruleset_version: str
) -> list[dict[str, object]]:
    ruleset = load_opos_ruleset(ruleset_version)
    by_slug = ruleset.abilities_by_slug
    _, profiles, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )
    result: list[dict[str, object]] = []
    for range_slug in ("melee", "short", "long"):
        profile = profiles[range_slug]
        result.append(
            {
                "range": range_slug,
                "name": ruleset.ranges[range_slug].name,
                "icon": ruleset.ranges[range_slug].icon,
                "active": int(profile["dice"]) > 0,
                "dice": int(profile["dice"]),
                "strength": display_number(profile["strength"]),
                "abilities": [
                    {
                        "name": by_slug[slug].name,
                        "icon": by_slug[slug].icon,
                    }
                    for slug in profile.get("abilities", [])
                ],
            }
        )
    return result


def build_unit_cards(
    unit: models.RosterUnit,
    *,
    ruleset_version: str,
    collapse_descriptions: bool = False,
) -> list[dict[str, object]]:
    abilities = build_ability_payloads(
        unit, ruleset_version=ruleset_version
    )
    primary_limit = PRIMARY_ABILITY_LIMIT
    continuation_limit = CONTINUATION_ABILITY_LIMIT
    cards: list[dict[str, object]] = [
        {
            "kind": "profile",
            "name": unit.name,
            "unit_cost": unit.unit_cost,
            "defense": display_number(unit.defense),
            "toughness": display_number(unit.toughness),
            "abilities": abilities[:primary_limit],
            "profiles": build_profile_payloads(
                unit, ruleset_version=ruleset_version
            ),
        }
    ]
    remaining = abilities[primary_limit:]
    for start in range(0, len(remaining), continuation_limit):
        cards.append(
            {
                "kind": "continuation",
                "name": unit.name,
                "unit_cost": unit.unit_cost,
                "abilities": remaining[start : start + continuation_limit],
                "continuation_number": len(cards),
            }
        )
    return cards


def build_card_pages(
    units: Iterable[models.RosterUnit],
    *,
    ruleset_version: str,
    collapse_descriptions: bool = False,
) -> list[list[dict[str, object] | None]]:
    cards = [
        card
        for unit in units
        for card in build_unit_cards(
            unit,
            ruleset_version=ruleset_version,
            collapse_descriptions=collapse_descriptions,
        )
    ]
    pages: list[list[dict[str, object] | None]] = []
    for start in range(0, len(cards), 4):
        page: list[dict[str, object] | None] = cards[start : start + 4]
        page.extend([None] * (4 - len(page)))
        pages.append(page)
    return pages
