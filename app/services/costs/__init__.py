"""Cost engine package.

Public API of the legacy ``app/services/costs.py`` module — preserved verbatim
so consumers like ``app.routers.rosters``, ``app.routers.armies``, and
``app.services.rules`` keep working without changes.

Internal layout (split complete — original 2400-line monolith fully decomposed):
- ``_engine.py``       — constants, cost tables (Sections 1+2), tiny helpers
                         (``_roster_unit_classification``), import stubs for all
                         extracted sections.  ~300 lines.
- ``primitives.py``    — Section 4: trait/ability parsing utils (lru_cache leaf).
- ``weapons.py``       — Section 6 core: ``_weapon_cost``, ``weapon_cost_components``,
                         ``weapon_cost``.
- ``abilities.py``     — Section 5 + Section 6 shims: ``passive_cost``,
                         ``base_model_cost``, ``ability_cost_components_from_name``,
                         ``ability_cost_from_name``.
- ``passive_state.py`` — Section 3: ``compute_passive_state``, army/passive helpers,
                         ``normalize_roster_unit_count``, ``_ensure_extra_data``.
- ``unit_helpers.py``  — Section 7: ``unit_default_weapons``, ``ability_cost``,
                         ``normalize_roster_unit_loadout``, etc.
- ``role_totals.py``   — Section 9: ``roster_unit_role_totals`` (wojownik/strzelec
                         classification with inner caches).
- ``quote.py``         — Section 8: ``calculate_roster_unit_quote`` (SSOT core,
                         the only function that may compute costs).
- ``roster.py``        — Section 10: ``roster_unit_cost``, ``recalculate_roster_costs``,
                         ``roster_total``, ``ensure_cached_costs``, ``update_cached_costs``.

When you add a new public symbol to ``_engine.py``, also re-export it from
this file (the explicit list below).  The list also serves as authoritative
documentation of what other parts of the app are allowed to consume.

Monkeypatching guide (after full split):
- ``costs.weapons._weapon_cost``                 — weapon cost formula
- ``costs.role_totals.compute_passive_state``    — passive state inside role totals
- ``costs.quote.compute_passive_state``          — passive state inside quote
- ``costs.quote.roster_unit_role_totals``        — role totals call inside quote

Performance: cost engine hot paths are documented in ``docs/PERFORMANCE.md``.
"""

# Constants & cost tables --------------------------------------------------
from ._engine import (
    AP_BASE,
    AP_LANCE,
    ARTILLERY_RANGE_BONUS,
    BASE_COST_FACTOR,
    BLAST_MULTIPLIER,
    BRUTALNY_AP_COST,
    CAUTIOUS_HIT_BONUS,
    COST_ENGINE_VERSION,
    DEADLY_MULTIPLIER,
    DEFENSE_ABILITY_MODIFIERS,
    DEFENSE_ABILITY_SLUGS,
    DEFENSE_BASE_VALUES,
    MORALE_ABILITY_MULTIPLIERS,
    ORDER_LIKE_ACTIVE_SLUGS,
    OVERCHARGE_MULTIPLIER,
    PENETRATING_MULTIPLIER,
    RANGE_TABLE,
    ROLE_SLUGS,
    TOUGHNESS_SPECIAL,
    TRANSPORT_MULTIPLIERS,
    UNWIELDY_RANGE_PENALTY,
    WAAGH_AP_MODIFIER,
)

# Dataclasses --------------------------------------------------------------
from ._engine import (
    AbilityCostComponents,
    PassiveState,
)

# Configuration ------------------------------------------------------------
from ._engine import default_ruleset_config

# Trait / ability parsing primitives ---------------------------------------
from ._engine import (
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
    # Re-exported for tests (test_roster_unit_quote.py uses these directly).
    _strip_role_traits,
    _with_role_trait,
)

# Re-exported for tests that call costs._weapon_cost directly.
# Note: monkeypatching costs._weapon_cost will NOT affect calls inside
# weapons.py (those resolve via _weapons module globals).  Tests that need
# to stub this function must patch ``costs._weapons._weapon_cost``.
from ._engine import _weapon_cost

# Submodule references — needed by tests that monkeypatch internal symbols.
# Usage:  monkeypatch.setattr(costs.weapons,       "_weapon_cost", fake)
#         monkeypatch.setattr(costs._engine,        "ability_cost_from_name", fake)
#         monkeypatch.setattr(costs._engine,        "compute_passive_state", fake)
from . import _engine, weapons, abilities, passive_state, unit_helpers, roster, role_totals, quote  # noqa: F401

# Army / unit helpers & passive state --------------------------------------
from ._engine import (
    army_rules,
    compute_passive_state,
    normalize_roster_unit_count,
)

# Ability cost computation -------------------------------------------------
from ._engine import (
    ability_cost,
    ability_cost_components_from_name,
    ability_cost_from_name,
    ability_uses_order_like_cost,
    passive_cost,
)

# Weapon & base model cost -------------------------------------------------
from ._engine import (
    base_model_cost,
    weapon_cost,
    weapon_cost_components,
)

# Unit-level aggregation ---------------------------------------------------
from ._engine import (
    ability_link_loadout_key,
    normalize_roster_unit_loadout,
    unit_default_weapons,
    unit_total_cost,
    unit_typical_total_cost,
)

# Quote API & role classification ------------------------------------------
from ._engine import (
    calculate_roster_unit_quote,
    roster_unit_role_totals,
)

# Roster-level aggregation -------------------------------------------------
from ._engine import (
    ensure_cached_costs,
    recalculate_roster_costs,
    roster_total,
    roster_unit_cost,
    update_cached_costs,
)

__all__ = [
    # constants
    "AP_BASE",
    "AP_LANCE",
    "ARTILLERY_RANGE_BONUS",
    "BASE_COST_FACTOR",
    "BLAST_MULTIPLIER",
    "BRUTALNY_AP_COST",
    "CAUTIOUS_HIT_BONUS",
    "COST_ENGINE_VERSION",
    "DEADLY_MULTIPLIER",
    "DEFENSE_ABILITY_MODIFIERS",
    "DEFENSE_ABILITY_SLUGS",
    "DEFENSE_BASE_VALUES",
    "MORALE_ABILITY_MULTIPLIERS",
    "ORDER_LIKE_ACTIVE_SLUGS",
    "OVERCHARGE_MULTIPLIER",
    "PENETRATING_MULTIPLIER",
    "RANGE_TABLE",
    "ROLE_SLUGS",
    "TOUGHNESS_SPECIAL",
    "TRANSPORT_MULTIPLIERS",
    "UNWIELDY_RANGE_PENALTY",
    "WAAGH_AP_MODIFIER",
    # dataclasses
    "AbilityCostComponents",
    "PassiveState",
    # config
    "default_ruleset_config",
    # primitives
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
    # army / passive state
    "army_rules",
    "compute_passive_state",
    "normalize_roster_unit_count",
    # ability cost
    "ability_cost",
    "ability_cost_components_from_name",
    "ability_cost_from_name",
    "ability_link_loadout_key",
    "ability_uses_order_like_cost",
    "passive_cost",
    # weapon / base
    "base_model_cost",
    "weapon_cost",
    "weapon_cost_components",
    # unit aggregation
    "normalize_roster_unit_loadout",
    "unit_default_weapons",
    "unit_total_cost",
    "unit_typical_total_cost",
    # quote / role totals
    "calculate_roster_unit_quote",
    "roster_unit_role_totals",
    # roster aggregation
    "ensure_cached_costs",
    "recalculate_roster_costs",
    "roster_total",
    "roster_unit_cost",
    "update_cached_costs",
]
