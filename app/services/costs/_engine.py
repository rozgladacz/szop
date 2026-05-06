# ============================================================
# SECTION: IMPORTS & COST TABLES
# RANGE_TABLE, AP_BASE, DEFENSE_BASE_VALUES, itp.
# Stałe używane wyłącznie przez backend — nie duplikować w JS.
# ============================================================
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from ... import models
from ...data import abilities as ability_catalog
from ..utils import ARMY_RULE_OFF_PREFIX, passive_flags_to_payload


MORALE_ABILITY_MULTIPLIERS = {
    "nieustraszony": 0.5,
    "ucieczka": 0.5,
    "stracency": 0.5,
}

DEFENSE_BASE_VALUES = {2: 2.3, 3: 1.65, 4: 1.25, 5: 1.0, 6: 0.9}
DEFENSE_ABILITY_MODIFIERS = {
    "delikatny": {2: -0.05, 3: -0.05, 4: -0.05, 5: -0.05, 6: -0.1},
    "niewrazliwy": {2: 0.05, 3: 0.1, 4: 0.2, 5: 0.3, 6: 0.25},
    "szpica": {2: 0.15, 3: 0.12, 4: 0.1, 5: 0.08, 6: 0.06},
    "waagh": {2: -0.03, 3: -0.03, 4: -0.03, 5: -0.02, 6: -0.01},
    "odrodzenie": {2: 0.9, 3: 0.65, 4: 0.5, 5: 0.4, 6: 0.35},
}

TOUGHNESS_SPECIAL = {1: 1.0, 2: 2.15, 3: 3.5, 4: 5}

DEFENSE_ABILITY_SLUGS = set(DEFENSE_ABILITY_MODIFIERS)

RANGE_TABLE = {0: 0.6, 12: 0.65, 18: 1.0, 24: 1.25, 30: 1.45, 36: 1.55}
ARTILLERY_RANGE_BONUS = {
    0: 0.0,
    12: 0.85,
    18: 0.55,
    24: 0.35,
    30: 0.2,
    36: 0.15,
}
UNWIELDY_RANGE_PENALTY = {
    0: 0.0,
    12: 0.6,
    18: 0.4,
    24: 0.4,
    30: 0.3,
    36: 0.15,
}

CAUTIOUS_HIT_BONUS = {0: 0.0, 12: 0.0, 18: 0.6, 24: 0.7, 30: 0.8, 36: 0.9}

AP_BASE = {-1: 0.75, 0: 1.0, 1: 1.4, 2: 1.8, 3: 2.1, 4: 2.3, 5: 2.4}
AP_LANCE = {-1: 0.15, 0: 0.35, 1: 0.3, 2: 0.25, 3: 0.15, 4: 0.1, 5: 0.05}
PENETRATING_MULTIPLIER = {-1: 1.5, 0: 2.0, 1: 2.5, 2: 2.7, 3: 2.8, 4: 2.9, 5: 3.0}
WAAGH_AP_MODIFIER = {-1: 0.01, 0: 0.02, 1: 0.05, 2: 0.04, 3: 0.04, 4: 0.03, 5: 0.02}

BLAST_MULTIPLIER = {2: 1.9, 3: 2.7, 6: 4.3}
DEADLY_MULTIPLIER = {2: 1.8, 3: 2.5, 6: 3.8}
OVERCHARGE_MULTIPLIER = 1.05
BRUTALNY_AP_COST = {-1: 0.0, 0: 0.01, 1: 0.02, 2: 0.1, 3: 0.2, 4: 0.3, 5: 0.4}

TRANSPORT_MULTIPLIERS = [
    ({"samolot"}, 3.5),
    ({"zasadzka", "zwiadowca"}, 2.5),
    ({"latajacy"}, 1.5),
    ({"szybki", "zwinny"}, 1.25),
]

BASE_COST_FACTOR = 5.0

# Path is anchored on the ``app/`` package (two levels above this file:
# app/services/costs/_engine.py → app/).  When this module was a flat
# app/services/costs.py the original ``parent.parent`` reached app/ — after
# the package split we need one more ``parent`` to land in the same place.
_RULESET_FALLBACK_PATH = (
    Path(__file__).resolve().parent.parent.parent / "rulesets" / "default.json"
)

ORDER_LIKE_ACTIVE_SLUGS = {"rozkaz", "klatwa", "oznaczenie"}
COST_ENGINE_VERSION = "quote-v1"


# ============================================================
# SECTION: CONFIG, RULESET & DATACLASSES
# default_ruleset_config, _apply_ruleset_overrides,
# PassiveState, AbilityCostComponents
# ============================================================
@lru_cache()
def default_ruleset_config() -> dict[str, Any]:
    try:
        with _RULESET_FALLBACK_PATH.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_ruleset_overrides() -> None:
    config = default_ruleset_config()
    range_modifiers = config.get("range_modifiers")
    if isinstance(range_modifiers, dict):
        for key, value in range_modifiers.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            key_text = str(key).strip().casefold()
            if key_text in {"melee", "m"}:
                RANGE_TABLE[0] = numeric
            else:
                try:
                    RANGE_TABLE[int(key)] = numeric
                except (TypeError, ValueError):
                    continue
    base_factor = config.get("base_cost_factor")
    if isinstance(base_factor, (int, float)) and base_factor > 0:
        global BASE_COST_FACTOR
        BASE_COST_FACTOR = float(base_factor)


_apply_ruleset_overrides()


ROLE_SLUGS = {"wojownik", "strzelec"}


def _roster_unit_classification(
    melee_total: float,
    ranged_total: float,
    *,
    fallback: str = "wojownik",
) -> str:
    melee_value = max(float(melee_total or 0.0), 0.0)
    ranged_value = max(float(ranged_total or 0.0), 0.0)
    if melee_value > ranged_value:
        return "wojownik"
    if ranged_value > melee_value:
        return "strzelec"
    return "wojownik" if fallback == "wojownik" else "strzelec"


@dataclass
class PassiveState:
    payload: list[dict[str, Any]]
    counts: dict[str, int]
    traits: list[str]


@dataclass
class AbilityCostComponents:
    base: float
    weapon_delta: float = 0.0

    @property
    def total(self) -> float:
        return self.base + self.weapon_delta


# ============================================================
# SECTION: ARMY / UNIT HELPERS & PASSIVE STATE  (extracted to passive_state.py)
# Functions in this section live in ``app/services/costs/passive_state.py``.
# Re-imported here so call sites in Sections 7, 8, 9 (still in _engine) and
# in roster.py keep resolving these names via _engine globals.
# ============================================================
from .passive_state import (  # noqa: E402, F401
    _active_traits_from_payload,
    _apply_army_rule_overrides,
    _canonicalize_passive_counts,
    _ensure_extra_data,
    _passive_flag_maps,
    _passive_payload,
    _passive_payload_with_army,
    _parse_passive_counts,
    army_rules,
    compute_passive_state,
    normalize_roster_unit_count,
)

# ============================================================
# SECTION: TRAIT & ABILITY PARSING UTILS  (extracted to primitives.py)
# Functions in this section live in ``app/services/costs/primitives.py``.
# We re-import them here so existing call sites in this module (e.g.
# ``flags_to_ability_list``, ``ability_identifier`` referenced unqualified
# below) keep resolving via _engine's globals.
# ============================================================
from .primitives import (  # noqa: E402, F401
    _ascii_letters,
    _strip_role_traits,
    _with_role_trait,
    ability_choices,
    ability_identifier,
    clamp_defense,
    clamp_quality,
    defense_modifier,
    extract_number,
    flags_to_ability_list,
    lookup_with_nearest,
    morale_modifier,
    normalize_name,
    normalize_range_value,
    range_multiplier,
    split_traits,
    toughness_modifier,
    unit_trait_variants,
)


# ============================================================
# SECTION: ABILITY COST COMPUTATION  (extracted to abilities.py)
# Functions in this section live in ``app/services/costs/abilities.py``.
# Re-imported here so existing unqualified call sites in _engine (e.g.
# ``ability_cost_from_name`` in Section 7) keep resolving via _engine globals.
# ============================================================
from .abilities import (  # noqa: E402, F401
    _parse_aura_value,
    ability_cost_components_from_name,
    ability_cost_from_name,
    base_model_cost,
    passive_cost,
)

# ============================================================
# SECTION: WEAPON & BASE MODEL COST  (extracted to weapons.py)
# Functions in this section live in ``app/services/costs/weapons.py``.
# Re-imported here so existing unqualified call sites in _engine keep resolving
# via _engine globals.
# Performance: ``_weapon_cost`` / ``weapon_cost_components`` are hot — see
# docs/PERFORMANCE.md before touching this chain.
# Monkeypatching: tests must patch ``costs._weapons._weapon_cost``, not
# ``costs._engine._weapon_cost``, because ``weapon_cost_components`` resolves
# the name via ``weapons`` module globals after extraction.
# ============================================================
from .weapons import (  # noqa: E402, F401
    _weapon_cost,
    weapon_cost,
    weapon_cost_components,
)

# ============================================================
# SECTION: UNIT-LEVEL COST AGGREGATION  (extracted to unit_helpers.py)
# Functions in this section live in ``app/services/costs/unit_helpers.py``.
# Re-imported here so call sites inside quote.py (Section 8) and
# role_totals.py (Section 9) keep resolving these names via _engine globals.
# ============================================================
from .unit_helpers import (  # noqa: E402, F401
    _ability_link_is_default,
    _normalize_loadout_section_ids,
    ability_cost,
    ability_uses_order_like_cost,
    normalize_roster_unit_loadout,
    unit_default_weapons,
    unit_total_cost,
    unit_typical_total_cost,
)

# ============================================================
# SECTION: QUOTE API — SSOT CORE  (extracted to quote.py)
# Functions in this section live in app/services/costs/quote.py.
# Re-imported here so existing call sites (routers, services, roster.py)
# keep resolving calculate_roster_unit_quote via _engine globals.
# ============================================================
from .quote import (  # noqa: E402, F401
    calculate_roster_unit_quote,
)

# ============================================================
# SECTION: ROLE CLASSIFICATION & TOTALS  (extracted to role_totals.py)
# Functions in this section live in ``app/services/costs/role_totals.py``.
# Re-imported here so ``calculate_roster_unit_quote`` (extracted to quote.py)
# and any other callers keep resolving the name via _engine globals.
# ============================================================
from .role_totals import (  # noqa: E402, F401
    roster_unit_role_totals,
)

# ============================================================
# SECTION: ROSTER-LEVEL AGGREGATION  (extracted to roster.py)
# Functions in this section live in ``app/services/costs/roster.py``.
# Re-imported here so consumers (routers, services) keep resolving these
# names via the ``costs`` package public API without changes.
# ============================================================
from .roster import (  # noqa: E402, F401
    ensure_cached_costs,
    recalculate_roster_costs,
    roster_total,
    roster_unit_cost,
    update_cached_costs,
)
