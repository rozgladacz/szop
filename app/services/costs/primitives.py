"""Trait & ability parsing primitives — leaf-level helpers for the cost engine.

Extracted from the original ``costs.py`` Section 4 (``TRAIT & ABILITY PARSING UTILS``).
These functions are pure or near-pure (read constants from ``_engine`` /
``ability_catalog`` but never mutate state) and form the bottom of the dependency
DAG: ``primitives`` is imported *into* ``_engine``, never the other way.

Hot paths cached here:
- ``ability_identifier`` — ~18 700 calls/quote on a Leman-Russ-class unit.
- ``normalize_name``     — re-used by ``ability_identifier`` and many call sites.

Both use ``functools.lru_cache(maxsize=4096)``.  Do not remove the cache without
re-running ``make profile`` — see ``docs/PERFORMANCE.md``.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Sequence

from ...data import abilities as ability_catalog
from ..utils import ARMY_RULE_OFF_PREFIX

# Constants that primitives reference are defined in ``_engine`` (section 1+2).
# At first import, ``_engine`` finishes evaluating those constants *before* it
# pulls primitives in (see the ``from .primitives import *`` line near the top
# of ``_engine``), so this circular-looking import is resolved cleanly.
from ._engine import (
    DEFENSE_ABILITY_MODIFIERS,
    DEFENSE_BASE_VALUES,
    RANGE_TABLE,
    ROLE_SLUGS,
    TOUGHNESS_SPECIAL,
)


def _strip_role_traits(traits: Sequence[str]) -> list[str]:
    clean: list[str] = []
    for trait in traits:
        identifier = ability_identifier(trait)
        if identifier in ROLE_SLUGS:
            continue
        clean.append(trait)
    return clean


def _with_role_trait(traits: Sequence[str], slug: str | None) -> list[str]:
    base = list(traits)
    if slug and slug in ROLE_SLUGS:
        base.append(slug)
    return base


def _ascii_letters(value: str) -> str:
    result: list[str] = []
    for char in value:
        if unicodedata.combining(char):
            continue
        if ord(char) < 128:
            result.append(char)
            continue
        name = unicodedata.name(char, "")
        if "LETTER" in name:
            base = name.split("LETTER", 1)[1].strip()
            if " WITH " in base:
                base = base.split(" WITH ", 1)[0].strip()
            if " SIGN" in base:
                base = base.split(" SIGN", 1)[0].strip()
            if " DIGRAPH" in base:
                base = base.split(" DIGRAPH", 1)[0].strip()
            tokens = base.split()
            if len(tokens) > 1 and len(tokens[-1]) == 1:
                base = tokens[-1]
            else:
                base = base.replace(" ", "")
            if not base:
                continue
            if "SMALL" in name:
                result.append(base.lower())
            else:
                result.append(base.upper())
        # Ignore characters without a useful letter mapping.
    return "".join(result)


# Pure string normalization — heavily reused by ability_identifier and many
# direct call sites. Caching avoids re-running NFKD + regex passes on the
# repeating set of ability/weapon names per request.
@lru_cache(maxsize=4096)
def normalize_name(text: str | None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFKD", str(text))
    value = _ascii_letters(value)
    value = value.replace("-", " ").replace("_", " ")
    value = re.sub(r"[!?]+$", "", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def extract_number(text: str | None) -> float:
    if not text:
        return 0.0
    match = re.search(r"[0-9]+(?:[.,][0-9]+)?", str(text))
    if not match:
        return 0.0
    return float(match.group(0).replace(",", "."))


def flags_to_ability_list(flags: dict | None) -> list[str]:
    abilities: list[str] = []
    for key, value in (flags or {}).items():
        if key is None:
            continue
        raw_name = str(key).strip()
        if not raw_name:
            continue
        if raw_name.startswith(ARMY_RULE_OFF_PREFIX):
            continue
        is_optional = False
        name = raw_name
        while name.endswith(("?", "!")):
            if name.endswith("!"):
                name = name[:-1].strip()
                continue
            if name.endswith("?"):
                name = name[:-1].strip()
                is_optional = True
                continue
            break
        if not name:
            continue
        slug = ability_catalog.slug_for_name(name) or name
        if is_optional:
            # Zdolności oznaczone znakiem zapytania są dostępne do kupienia,
            # ale nie wchodzą w skład podstawowego profilu jednostki.
            # Nie powinny więc wpływać na koszt ani statystyki bazowe.
            continue
        if isinstance(value, bool):
            if value:
                abilities.append(slug)
            continue
        if value is None:
            abilities.append(slug)
            continue
        value_str = str(value).strip()
        if not value_str or value_str.casefold() in {"true", "yes"}:
            abilities.append(slug)
        else:
            abilities.append(f"{slug}({value_str})")
    return abilities


def ability_choices(ability: str | None) -> list[str]:
    identifier = ability_identifier(ability)
    if not identifier:
        return []
    normalized = identifier.replace("\\", "/")
    if "/" not in normalized:
        return [identifier]
    options: list[str] = []
    for part in normalized.split("/"):
        part = part.strip()
        if not part:
            continue
        slug = ability_catalog.slug_for_name(part)
        if slug:
            options.append(slug)
        else:
            options.append(normalize_name(part))
    return options or [identifier]


def unit_trait_variants(unit_flags: dict | None) -> list[tuple[str, ...]]:
    base_traits = flags_to_ability_list(unit_flags)
    variants: list[tuple[str, ...]] = [tuple()]
    for trait in base_traits:
        options = ability_choices(trait)
        if not options:
            continue
        next_variants: list[tuple[str, ...]] = []
        for existing in variants:
            for option in options:
                next_variants.append(existing + (option,))
        variants = next_variants if next_variants else variants
    if not variants:
        return [tuple()]
    dedup: dict[tuple[str, ...], None] = {}
    for variant in variants:
        dedup.setdefault(variant, None)
    return list(dedup.keys())


def split_traits(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,;]", text) if part.strip()]


def clamp_quality(value: int) -> int:
    return max(2, min(6, int(value)))


def clamp_defense(value: int) -> int:
    return max(2, min(6, int(value)))


def morale_modifier(quality: int, penalty_multiplier: float = 1.0) -> float:
    quality = clamp_quality(quality)
    penalty = max(float(penalty_multiplier), 0.0)
    return 1.3 - (quality - 1) / 10.0 * penalty


def defense_modifier(defense: int, ability_slugs: Iterable[str] | None = None) -> float:
    defense = clamp_defense(defense)
    value = DEFENSE_BASE_VALUES[defense]
    if ability_slugs:
        for slug in ability_slugs:
            modifier_map = DEFENSE_ABILITY_MODIFIERS.get(slug)
            if modifier_map:
                value += modifier_map.get(defense, 0.0)
    return value


def toughness_modifier(toughness: int) -> float:
    toughness = max(int(toughness), 1)
    if toughness in TOUGHNESS_SPECIAL:
        return TOUGHNESS_SPECIAL[toughness]
    return max(1.0, (5 * toughness) // 3 - 2)


def lookup_with_nearest(table: dict[int, float], key: int) -> float:
    if key in table:
        return table[key]
    nearest = min(table, key=lambda existing: abs(existing - key))
    return table[nearest]


def range_multiplier(range_value: int) -> float:
    if range_value in RANGE_TABLE:
        return RANGE_TABLE[range_value]
    nearest = min(RANGE_TABLE, key=lambda existing: abs(existing - range_value))
    return RANGE_TABLE[nearest]


def normalize_range_value(value: str | int | float | None) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if not text:
            return 0
        lowered = text.casefold()
        if lowered in {"melee", "m"}:
            return 0
        numeric = extract_number(lowered)
    if numeric <= 0:
        return 0
    return int(round(numeric))


# Pure function called ~18,700 times per quote (profiled on Leman Russ).
# Inputs are always small strings or None, output depends only on module-level
# ability_catalog constants — perfect candidate for process-wide memoization.
# Cache size 4096 covers the realistic universe of distinct ability text seen
# across all armies; LRU eviction protects memory if that assumption breaks.
@lru_cache(maxsize=4096)
def ability_identifier(text: str | None) -> str:
    if text is None:
        return ""
    raw = str(text).strip()
    if raw.startswith(ARMY_RULE_OFF_PREFIX):
        raw = raw[len(ARMY_RULE_OFF_PREFIX) :].strip()
    if not raw:
        return ""
    base = raw
    for separator in ("(", "=", ":"):
        if separator in base:
            base = base.split(separator, 1)[0].strip()
    base = base.rstrip("?!").strip()
    slug = ability_catalog.slug_for_name(base)
    if slug:
        return slug
    return normalize_name(base)


__all__ = [
    "_ascii_letters",
    "_strip_role_traits",
    "_with_role_trait",
    "ability_choices",
    "ability_identifier",
    "clamp_defense",
    "clamp_quality",
    "defense_modifier",
    "extract_number",
    "flags_to_ability_list",
    "lookup_with_nearest",
    "morale_modifier",
    "normalize_name",
    "normalize_range_value",
    "range_multiplier",
    "split_traits",
    "toughness_modifier",
    "unit_trait_variants",
]
