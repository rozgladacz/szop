"""Ability & passive cost computation.

Extracted from ``_engine.py``:
- Section 5 (ABILITY COST COMPUTATION): ``passive_cost``,
  ``_parse_aura_value``, ``ability_cost_components_from_name``
- Section 6 shims: ``ability_cost_from_name``, ``base_model_cost``
  (logically belong here because both call Section 5 helpers).

Dependency order (bottom-up):
  primitives → weapons → abilities → (rest of engine)

``ability_cost_components_from_name`` is the hot-path entry point — called
via ``ability_cost_from_name`` inside ``roster_unit_role_totals``.  See
``docs/PERFORMANCE.md`` before touching this chain.

Monkeypatching note: ``ability_cost_from_name`` is re-imported into
``_engine``'s globals (via the Section 5 stub).  Tests patching
``costs._engine.ability_cost_from_name`` will therefore override the binding
seen by ``roster_unit_role_totals`` (also in ``_engine``).  This is the
correct patch target for those tests — do not change it.
"""

from __future__ import annotations

import re
from typing import Sequence

from ... import models
from ...data import abilities as ability_catalog
from ._engine import (
    DEFENSE_ABILITY_SLUGS,
    BASE_COST_FACTOR,
    MORALE_ABILITY_MULTIPLIERS,
    TRANSPORT_MULTIPLIERS,
    AbilityCostComponents,
)
from .primitives import (
    ability_identifier,
    defense_modifier,
    extract_number,
    morale_modifier,
    normalize_name,
    normalize_range_value,
    split_traits,
    toughness_modifier,
)
from .weapons import _weapon_cost, weapon_cost


def passive_cost(
    ability_name: str,
    tou: float = 1.0,
    aura: bool = False,
    abilities: Sequence[str] | None = None,
) -> float:
    slug = ability_identifier(ability_name)
    norm = normalize_name(ability_name)
    key = slug or norm
    if not key:
        return 0.0

    tou = float(tou)

    if slug == "zasadzka":
        return 4.0 * tou
    if slug == "zwiadowca":
        return 2.0 * tou
    if slug == "odwody":
        return 0
    if slug == "szybki":
        return 1.0 * tou
    if slug == "wolny":
        return -1.0 * tou
    if slug == "harcownik":
        return 1.5 * tou
    if slug == "instynkt":
        return (-1.0 if not aura else 1.0) * tou
    if slug == "nieruchomy":
        return -2.5 * tou
    if slug == "zwinny":
        return 0.5 * tou
    if slug == "niezgrabny":
        return -0.5 * tou
    if slug == "latajacy":
        return 1.0 * tou
    if slug == "samolot":
        return 3.0 * tou
    if slug == "kontra":
        return 2.0 * tou
    if slug == "maskowanie":
        return 2.0 * tou
    if slug == "okopany":
        return 1.0 * tou
    if slug == "tarcza":
        return 1.25 * tou
    if slug == "regeneracja":
        return 4.0 * tou
    if slug == "dywersant":
        return 1.25 * (tou if aura else 1.0)
    if slug == "zdobywca":
        return 3.0 * tou
    if slug == "straznik":
        return 9.0 * tou
    if slug == "cierpliwy":
        return 1.0 * tou
    if slug == "roj":
        return 0.25 * tou
    if slug == "zwrot":
        return -1.0 * tou

    if aura:
        if slug == "bastion":
            return 3.0
        if slug == "niestrudzony":
            return 8.0
        if slug in {"nieustraszony", "ucieczka", "stracency"}:
            return 1.5 * tou
        if slug == "delikatny":
            return 0.5 * tou
        if slug == "niewrazliwy":
            return 1.5 * tou
        if slug == "furia":
            return 3.0 * tou
        if slug == "przygotowanie":
            return 3.5 * tou
        if slug == "ostrozny":
            return 4.25 * tou

    return 0.0


def _parse_aura_value(name: str, value: str | None) -> tuple[str, float]:
    aura_range = 6.0
    ability_ref = ""
    if value:
        parts = value.split("|", 1)
        if len(parts) == 2:
            ability_ref = parts[0].strip()
            aura_range = extract_number(parts[1]) or 6.0
        else:
            ability_ref = value.strip()
    if not ability_ref:
        desc = normalize_name(name)
        if desc.startswith("aura("):
            match = re.match(r"aura\(([^)]+)\)\s*[:\-–]?\s*(.*)", desc)
            if match:
                aura_range = extract_number(match.group(1)) or 6.0
                raw_ref = match.group(2)
                ability_ref = raw_ref.lstrip(": -–").strip().rstrip(") ")
                ability_ref = ability_ref.strip()
        elif desc.startswith("aura:"):
            ability_ref = desc.split(":", 1)[1].strip()
        else:
            ability_ref = desc[4:].lstrip(": -–").strip()
    slug = ability_catalog.slug_for_name(ability_ref) or ability_identifier(ability_ref)
    return slug, aura_range


def _mistrzostwo_aura_cost(weapon_slug: str) -> float:
    q = 4
    delta1 = abs(
        _weapon_cost(q, 24, 1, 2, [weapon_slug], []) - _weapon_cost(q, 24, 1, 2, [], [])
    )
    delta2 = abs(
        _weapon_cost(q, 0, 2, 2, [weapon_slug], []) - _weapon_cost(q, 0, 2, 2, [], [])
    )
    return max(delta1, delta2)


def _mistrzostwo_weapon_cost(
    weapon_slug: str,
    weapons: Sequence[models.Weapon],
    quality: int,
    unit_traits: Sequence[str],
) -> float:
    total = 0.0
    for wpn in weapons:
        range_v = normalize_range_value(
            getattr(wpn, "effective_range", None) or getattr(wpn, "range", "")
        )
        existing = list(split_traits(
            getattr(wpn, "effective_tags", None) or getattr(wpn, "tags", "")
        ))
        attacks = float(
            getattr(wpn, "effective_attacks", None)
            if getattr(wpn, "effective_attacks", None) is not None
            else getattr(wpn, "attacks", 1.0)
        )
        ap = int(
            getattr(wpn, "effective_ap", None)
            if getattr(wpn, "effective_ap", None) is not None
            else getattr(wpn, "ap", 0)
        )
        if weapon_slug in {normalize_name(t) for t in existing}:
            continue
        cost_without = _weapon_cost(quality, range_v, attacks, ap, existing, list(unit_traits))
        cost_with = _weapon_cost(quality, range_v, attacks, ap, existing + [weapon_slug], list(unit_traits))
        total += abs(cost_with - cost_without)
    return total


def base_model_cost(
    quality: int,
    defense: int,
    toughness: int,
    abilities: Sequence[str] | None,
) -> float:
    ability_list = list(abilities or [])

    morale_multiplier = 1.0
    applied_morale_modifiers: set[str] = set()
    defense_abilities: list[str] = []
    passive_total = 0.0

    for ability in ability_list:
        slug = ability_identifier(ability)
        norm = slug or normalize_name(ability)
        if not norm:
            continue
        if slug in MORALE_ABILITY_MULTIPLIERS and slug not in applied_morale_modifiers:
            morale_multiplier *= MORALE_ABILITY_MULTIPLIERS[slug]
            applied_morale_modifiers.add(slug)
            continue
        if slug in DEFENSE_ABILITY_SLUGS:
            defense_abilities.append(slug)
            continue
        passive_total += passive_cost(ability, float(toughness), abilities=ability_list)

    morale_value = morale_modifier(int(quality), morale_multiplier)
    defense_value = defense_modifier(int(defense), defense_abilities)
    toughness_value = toughness_modifier(int(toughness))

    cost = BASE_COST_FACTOR * morale_value * defense_value * toughness_value
    cost += passive_total
    return cost


def ability_cost_components_from_name(
    name: str,
    value: str | None = None,
    unit_abilities: Sequence[str] | None = None,
    *,
    toughness: int | float | None = None,
    quality: int | None = None,
    defense: int | None = None,
    weapons: Sequence[models.Weapon] | None = None,
) -> AbilityCostComponents:
    desc = normalize_name(name)
    if not desc:
        return AbilityCostComponents(base=0.0, weapon_delta=0.0)

    abilities: list[str] = list(unit_abilities or [])
    slug = ability_identifier(name)

    def _contains_slug(items: Sequence[str], needle: str | None) -> bool:
        if not needle:
            return False
        for element in items:
            if ability_identifier(element) == needle:
                return True
        return False

    if slug and not _contains_slug(abilities, slug):
        if value is not None and str(value).strip():
            abilities.append(f"{slug}({value})")
        else:
            abilities.append(slug)

    abilities_without: list[str]
    if slug:
        abilities_without = []
        removed = False
        for item in abilities:
            if not removed and ability_identifier(item) == slug:
                removed = True
                continue
            abilities_without.append(item)
    else:
        abilities_without = list(abilities)

    ability_set: set[str] = set()
    for item in abilities:
        identifier = ability_identifier(item)
        if identifier:
            ability_set.add(identifier)

    row_delta: float | None = None
    if (
        slug
        and quality is not None
        and defense is not None
        and toughness is not None
        and abilities_without != abilities
        and (slug in MORALE_ABILITY_MULTIPLIERS or slug in DEFENSE_ABILITY_SLUGS)

    ):
        row_delta = base_model_cost(
            int(quality),
            int(defense),
            int(float(toughness)),
            abilities,
        ) - base_model_cost(
            int(quality),
            int(defense),
            int(float(toughness)),
            abilities_without,
        )

    weapon_delta = 0.0
    if (
        weapons
        and slug
        and quality is not None
        and abilities_without != abilities
    ):
        traits_with = abilities
        traits_without = abilities_without
        total_with = 0.0
        total_without = 0.0
        for wpn in weapons:
            total_with += weapon_cost(wpn, int(quality), traits_with)
            total_without += weapon_cost(wpn, int(quality), traits_without)
        weapon_delta = total_with - total_without

    if desc.startswith("transport"):
        capacity = extract_number(value or name)
        multiplier = 1.0
        for options, value in TRANSPORT_MULTIPLIERS:
            if ability_set & options:
                multiplier = value
        base_result = capacity * multiplier
    if desc.startswith("otwarty transport") or desc.startswith("platforma strzelecka"):
        capacity = extract_number(value or name)
        multiplier = 1.0
        for options, value in TRANSPORT_MULTIPLIERS:
            if ability_set & options:
                multiplier = value
        base_result = capacity * (multiplier + 0.25)
    elif desc.startswith("aura"):
        if value and value.startswith("mistrzostwo:"):
            parts = value.split("|", 1)
            w_slug = parts[0][len("mistrzostwo:"):].strip()
            aura_range_val = extract_number(parts[1]) if len(parts) == 2 else 6.0
            cost = _mistrzostwo_aura_cost(w_slug) * 8.0
            if abs(aura_range_val - 12.0) < 1e-6:
                cost *= 2.0
            base_result = cost
        else:
            ability_slug, aura_range = _parse_aura_value(name, value)
            cost = passive_cost(ability_slug, 8.0, True)
            if abs(aura_range - 12.0) < 1e-6:
                cost *= 2.0
            base_result = cost
    elif desc.startswith("mag"):
        base_result = 8.0 * extract_number(value or name)
    elif desc == "przekaznik":
        base_result = 4.0
    elif desc == "koordynacja":
        base_result = 45.0
    elif slug == "latanie":
        base_result = 20.0
    elif slug == "mobilizacja":
        base_result = 30.0
    elif slug == "przepowiednia":
        base_result = 45.0
    elif slug == "presja":
        base_result = 45.0
    elif slug == "usprawnienie":
        base_result = 45.0
    elif desc.startswith("rozkaz") or desc.startswith("klatwa") or desc.startswith("oznaczenie"):
        ability_ref = value or (desc.split(":", 1)[1].strip() if ":" in desc else "")
        if ability_ref.startswith("mistrzostwo:"):
            w_slug = ability_ref[len("mistrzostwo:"):].strip()
            base_result = _mistrzostwo_aura_cost(w_slug) * 10.0
        else:
            ability_slug = ability_catalog.slug_for_name(ability_ref) or ability_identifier(ability_ref)
            base_result = passive_cost(ability_slug, 10.0, True)
    elif desc == "radio":
        base_result = 3.0
    elif slug == "ociezalosc":
        base_result = 20.0
    elif desc == "spaczenie":
        base_result = 30.0
    elif slug == "meczennik":
        base_result = 5.0
    elif slug == "mistrzostwo":
        weapon_slug = ability_identifier(value or "")
        if weapons and weapon_slug and quality is not None:
            base_result = _mistrzostwo_weapon_cost(
                weapon_slug, weapons, int(quality), list(unit_abilities or [])
            )
        else:
            base_result = 0.0
    else:
        tou_value = float(toughness) if toughness is not None else 1.0
        definition = ability_catalog.find_definition(slug) if slug else None
        if slug == "przygotowanie":
            base_result = 0.0
        elif definition and definition.type == "passive":
            base_result = passive_cost(name, tou_value, abilities=abilities)
        elif slug and not definition:
            base_result = passive_cost(name, tou_value, abilities=abilities)
        else:
            base_result = 0.0

    if row_delta is not None:
        base_result = row_delta

    return AbilityCostComponents(base=float(base_result), weapon_delta=float(weapon_delta))


def ability_cost_from_name(
    name: str,
    value: str | None = None,
    unit_abilities: Sequence[str] | None = None,
    *,
    toughness: int | float | None = None,
    quality: int | None = None,
    defense: int | None = None,
    weapons: Sequence[models.Weapon] | None = None,
) -> float:
    components = ability_cost_components_from_name(
        name,
        value,
        unit_abilities,
        toughness=toughness,
        quality=quality,
        defense=defense,
        weapons=weapons,
    )
    return components.total


__all__ = [
    "_parse_aura_value",
    "ability_cost_components_from_name",
    "ability_cost_from_name",
    "base_model_cost",
    "passive_cost",
]
