"""Weapon cost computation — evaluates the raw numerical cost of a single weapon.

Extracted from ``_engine.py`` Section 6 (WEAPON & BASE MODEL COST).

Dependency order (bottom-up):
  primitives → weapons → abilities → (rest of engine)

``_weapon_cost`` is the inner loop: it is called ~N_weapons × 2 per
``roster_unit_role_totals`` call (melee + ranged for every weapon).  Keep it
lean.  Do not add new lookups without re-running ``make profile`` — see
``docs/PERFORMANCE.md``.

Monkeypatching note: tests that need to stub ``_weapon_cost`` must patch
``costs._weapons._weapon_cost`` (the module where ``weapon_cost_components``
resolves the name via LEGB), NOT ``costs._engine._weapon_cost`` which no
longer has any callers after the extraction.
"""

from __future__ import annotations

import math
from typing import Sequence

from ... import models
from ._engine import (
    AP_BASE,
    AP_LANCE,
    ARTILLERY_RANGE_BONUS,
    BLAST_MULTIPLIER,
    BRUTALNY_AP_COST,
    CAUTIOUS_HIT_BONUS,
    DEADLY_MULTIPLIER,
    OVERCHARGE_MULTIPLIER,
    PENETRATING_MULTIPLIER,
    UNWIELDY_RANGE_PENALTY,
    WAAGH_AP_MODIFIER,
)
from .primitives import (
    ability_identifier,
    extract_number,
    flags_to_ability_list,
    lookup_with_nearest,
    normalize_name,
    normalize_range_value,
    range_multiplier,
    split_traits,
)


def _weapon_cost(
    quality: int,
    range_value: int,
    attacks: float,
    ap: int,
    weapon_traits: Sequence[str],
    unit_traits: Sequence[str],
    allow_assault_extra: bool = True,
) -> float:
    chance = 7.0
    attacks = float(attacks if attacks is not None else 1.0)
    attacks = max(attacks, 0.0)
    base_ap = int(ap or 0)
    range_mod = range_multiplier(range_value)
    ap_mod = lookup_with_nearest(AP_BASE, base_ap)
    mult = 1.0
    q = int(quality)
    range_bonus = 0.0
    range_penalty = 0.0

    unit_set: set[str] = set()
    for trait in unit_traits:
        identifier = ability_identifier(trait)
        if identifier:
            unit_set.add(identifier)
    melee = range_value == 0

    waagh_penalty = 0.0
    if "waagh" in unit_set:
        waagh_penalty = lookup_with_nearest(WAAGH_AP_MODIFIER, base_ap)

    if melee and "furia" in unit_set:
        chance += 0.65
    if "przygotowanie" in unit_set and "samolot" not in unit_set:
        chance += 0.2 if "niestrudzony" in unit_set else 0.65
    if "niestrudzony" in unit_set and "samolot" not in unit_set:
        mult *= 1.5
    if "straznik" in unit_set and not melee:
        mult *= 1.7
    if "bastion" in unit_set and melee:
        mult *= 1.2
    if "dywersant" in unit_set:
        mult *= 1.2
    if "szpica" in unit_set:
        chance += 0.5
    if "ostrozny" in unit_set:
        chance += lookup_with_nearest(CAUTIOUS_HIT_BONUS, range_value)
    if not melee and "wojownik" in unit_set:
        mult *= 0.5
    if melee and "strzelec" in unit_set:
        mult *= 0.5
    if not melee and "zle_strzela" in unit_set:
        q = 5
    if not melee and "dobrze_strzela" in unit_set:
        q = 4
    if "zemsta" in unit_set:
        mult *= 1.2
    if "rezerwa" in unit_set:
        mult *= 0.6
    if "zasadzka" in unit_set and not melee:
        mult *= 0.6
    if "odwody" in unit_set and not (unit_set & {"rezerwa", "zwiadowca", "zasadzka"}):
        mult *= 0.75

    assault = False
    overcharge = False
    finezja = False
    has_namierzanie = False

    for trait in weapon_traits:
        norm = normalize_name(trait)
        if not norm:
            continue

        if norm.startswith("rozprysk") or norm.startswith("blast"):
            value = int(round(extract_number(trait)))
            if value in BLAST_MULTIPLIER:
                mult *= BLAST_MULTIPLIER[value]
                continue

        if norm.startswith("zabojczy") or norm.startswith("deadly"):
            value = int(round(extract_number(trait)))
            if value in DEADLY_MULTIPLIER:
                mult *= DEADLY_MULTIPLIER[value]
                continue

        if norm in {
            "seria",
            "rozrywajacy",
            "rozrywajaca",
            "rozrwyajaca",
            "podwojny",
            "podwojna",
            "rending",
        }:
            chance += 1.0
        elif norm in {"lanca", "lance"}:
            chance += 0.65
        elif norm in {"namierzanie", "lock on"}:
            has_namierzanie = True
            mult *= 1.1
        elif norm in {"impet", "impact"}:
            chance += 0.65
            ap_mod += lookup_with_nearest(AP_LANCE, base_ap)
        elif norm in {"przebijajaca", "przebijajacy", "penetrating"}:
            mult *= lookup_with_nearest(PENETRATING_MULTIPLIER, base_ap)
        elif norm in {"finezja"}:
            finezja = True
        elif norm in {"brutalny", "brutalna", "brutal"}:
            ap_mod += lookup_with_nearest(BRUTALNY_AP_COST, base_ap)
        elif norm in {
            "zguba",
            "bez regeneracji",
            "bez regegenracji",
            "no regen",
            "no regeneration",
        }:
            mult *= 1.05
        elif norm in {"dezintegracja", "disintegration"}:
            chance += 2.9 / ap_mod - 1
        elif norm in {"niebezposredni", "indirect"}:
            mult *= 1.2
        elif norm in {"zuzywalny", "limited"}:
            mult *= 0.4
        elif norm in {"precyzyjny", "precise"}:
            mult *= 1.5
        elif norm in {"niezawodny", "niezawodna", "reliable"}:
            q = 2
        elif norm in {"szturmowy", "szturmowa", "assault"}:
            assault = True
        elif norm in {"artyleria", "artillery"}:
            range_bonus += lookup_with_nearest(ARTILLERY_RANGE_BONUS, range_value)
        elif norm in {"nieporeczny", "unwieldy"}:
            range_penalty += lookup_with_nearest(UNWIELDY_RANGE_PENALTY, range_value)
        elif norm in {"podkrecenie", "overcharge", "overclock"}:
            overcharge = True
        elif norm in {"burzaca"}:
            mult *= 1.5
        elif norm in {"unik", "przewidywalny"}:
            mult *= 1.2
        elif norm in {"sterowany"}:
            mult *= 1.5
        elif melee and norm in {"porazenie"}:
            mult *= 1.1

    if waagh_penalty:
        ap_mod = max(ap_mod - waagh_penalty, 0.0)

    if not has_namierzanie:
        chance -= 0.6 if not melee else 0.3
    range_mod = max(range_mod + range_bonus - range_penalty, 0.0)
    chance = max(chance - q, 0.9)
    if finezja:
        chance += ((7 - q) * (6 - q) ** 2) / 50.0
    cost = attacks * 2.0 * range_mod * chance * ap_mod * mult

    if overcharge and (not assault or range_value != 0):
        cost *= OVERCHARGE_MULTIPLIER

    if assault and allow_assault_extra and range_value != 0:
        melee_part_cost = _weapon_cost(
            quality,
            0,
            attacks,
            base_ap,
            weapon_traits,
            unit_traits,
            allow_assault_extra=False,
        )
        cost += melee_part_cost

    return cost


def weapon_cost_components(
    weapon: models.Weapon,
    unit_quality: int = 4,
    unit_flags: dict | Sequence[str] | None = None,
) -> dict[str, float]:
    if isinstance(unit_flags, dict):
        unit_traits = flags_to_ability_list(unit_flags)
    elif unit_flags is None:
        unit_traits = []
    else:
        unit_traits = list(unit_flags)

    range_value = normalize_range_value(
        getattr(weapon, "effective_range", None) or getattr(weapon, "range", "")
    )
    traits = split_traits(
        getattr(weapon, "effective_tags", None) or getattr(weapon, "tags", "")
    )
    attacks_value = (
        getattr(weapon, "effective_attacks", None)
        if getattr(weapon, "effective_attacks", None) is not None
        else getattr(weapon, "attacks", 1.0)
    )
    ap_value = (
        getattr(weapon, "effective_ap", None)
        if getattr(weapon, "effective_ap", None) is not None
        else getattr(weapon, "ap", 0)
    )

    ranged_cost = 0.0
    melee_cost = 0.0
    assault = any(
        normalize_name(trait) in {"szturmowy", "szturmowa", "assault"}
        for trait in traits
    )

    if range_value > 0:
        ranged_cost = _weapon_cost(
            unit_quality,
            range_value,
            attacks_value,
            ap_value,
            traits,
            unit_traits,
            allow_assault_extra=False,
        )
    if range_value == 0 or (range_value > 0 and assault):
        melee_cost = _weapon_cost(
            unit_quality,
            0,
            attacks_value,
            ap_value,
            traits,
            unit_traits,
            allow_assault_extra=False,
        )

    ranged = max(float(ranged_cost or 0.0), 0.0)
    melee = max(float(melee_cost or 0.0), 0.0)
    return {
        "melee": round(melee, 2),
        "ranged": round(ranged, 2),
        "total": round(melee + ranged, 2),
    }


def weapon_cost(
    weapon: models.Weapon,
    unit_quality: int = 4,
    unit_flags: dict | Sequence[str] | None = None,
    *,
    use_cached: bool = True,
) -> float:
    if isinstance(unit_flags, dict):
        unit_traits = flags_to_ability_list(unit_flags)
    elif unit_flags is None:
        unit_traits = []
    else:
        unit_traits = list(unit_flags)

    # Standard armory views should reuse cached weapon costs when possible.
    if use_cached and unit_quality == 4 and not unit_traits:
        cached = getattr(weapon, "effective_cached_cost", None)
        if isinstance(cached, (int, float)) and math.isfinite(cached):
            return round(max(float(cached), 0.0), 2)
    components = weapon_cost_components(
        weapon,
        unit_quality=unit_quality,
        unit_flags=unit_traits,
    )
    return round(max(float(components.get("total", 0.0)), 0.0), 2)


__all__ = [
    "_weapon_cost",
    "weapon_cost",
    "weapon_cost_components",
]
