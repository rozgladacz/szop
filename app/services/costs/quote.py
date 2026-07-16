"""Quote API — SSOT core.

Extracted from _engine.py Section 8 (QUOTE API — SSOT CORE).

calculate_roster_unit_quote is the single source of truth for all cost
computations.  Every route, service, and background task must call this
function — never compute costs inline.

Performance: include_item_costs=False skips the expensive passive-delta
loop (_passive_entries) and the roster_unit_role_totals call.  Use
this flag for badge-only refreshes where role totals are not displayed.
See docs/PERFORMANCE.md.

Monkeypatching note: tests patching costs._engine.compute_passive_state
or costs._engine.roster_unit_role_totals to stub behaviour inside
calculate_roster_unit_quote must now patch costs.quote.<name> after
this extraction.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Sequence

from ... import models
from ..utils import ARMY_RULE_OFF_PREFIX
from ._engine import COST_ENGINE_VERSION, ROLE_SLUGS, _roster_unit_classification
from .abilities import base_model_cost
from .crowding import crowded_melee_total, melee_crowding_factors, melee_vector_from_counts
from .passive_state import compute_passive_state, normalize_roster_unit_count
from .primitives import _strip_role_traits, _with_role_trait, ability_identifier
from .role_totals import roster_unit_role_totals
from .unit_helpers import (
    ability_cost,
    ability_link_loadout_key,
    normalize_roster_unit_loadout,
    unit_default_weapons,
)
from .weapons import weapon_cost, weapon_cost_components


__all__ = ["calculate_roster_unit_quote"]
# ============================================================
# SECTION: QUOTE API — SSOT CORE
# calculate_roster_unit_quote — jedyne źródło prawdy dla kosztów.
# Zwraca total, components, item_costs (opcjonalnie), selected_role.
# include_item_costs=False pomija pętlę passive_deltas (wydajność).
# ============================================================
def calculate_roster_unit_quote(
    unit: models.Unit | None,
    loadout: dict[str, Any] | None = None,
    count: int = 1,
    include_item_costs: bool = True,
    *,
    melee_factors_override: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Public quote interface for a single roster unit.

    ``count`` is normalized through :func:`normalize_roster_unit_count`.
    ``count <= 0`` or unparsable values produce zero totals and normalized
    loadout payload.
    ``include_item_costs`` controls whether per-item cost breakdowns and
    passive deltas are computed. Pass ``False`` for badge-only refreshes
    to skip the expensive passive-delta loop.

    ``melee_factors_override`` — optional pre-computed melee crowding
    multipliers (see costs/crowding.py), one per model, length must equal
    this call's normalized ``count``. When omitted, factors are
    self-computed from this unit's OWN melee vector and ``unit.base_size``
    (correct for a standalone unit). Callers pooling a base unit with its
    attached heroes (rosters.py's ``_classification_map``) compute a merged
    vector across the group, derive factors from the group's base_size, and
    pass each member's slice here so the group shares one crowding pool.
    """
    _empty_item_costs: dict[str, Any] = {
        "weapons": {},
        "active": {},
        "aura": {},
        "passive_deltas": {},
    }
    if unit is None:
        empty_loadout = normalize_roster_unit_loadout(unit, loadout)
        return {
            "cost_engine_version": COST_ENGINE_VERSION,
            "selected_role": None,
            "warrior_total": 0.0,
            "shooter_total": 0.0,
            "selected_total": 0.0,
            "selected_total_full": 0.0,
            "melee_per_model": [],
            "components": {
                "base": 0.0,
                "weapon": 0.0,
                "active": 0.0,
                "aura": 0.0,
                "passive": 0.0,
                "melee_crowding": 0.0,
            },
            "item_costs": _empty_item_costs,
            "loadout": empty_loadout,
        }

    raw_loadout = loadout if isinstance(loadout, dict) else {}
    normalized_loadout = normalize_roster_unit_loadout(unit, raw_loadout)
    unit_count = normalize_roster_unit_count(count, default=0)
    if unit_count <= 0:
        return {
            "cost_engine_version": COST_ENGINE_VERSION,
            "selected_role": None,
            "warrior_total": 0.0,
            "shooter_total": 0.0,
            "selected_total": 0.0,
            "selected_total_full": 0.0,
            "melee_per_model": [],
            "components": {
                "base": 0.0,
                "weapon": 0.0,
                "active": 0.0,
                "aura": 0.0,
                "passive": 0.0,
                "melee_crowding": 0.0,
            },
            "item_costs": _empty_item_costs,
            "loadout": normalized_loadout,
        }

    roster_unit = SimpleNamespace(unit=unit, count=unit_count, extra_weapons_json=None)
    _passive_state_cache = compute_passive_state(unit, normalized_loadout)
    base_traits = _strip_role_traits(_passive_state_cache.traits)
    mode_total = normalized_loadout.get("mode") == "total"
    model_count = unit_count

    weapon_by_id: dict[int, Any] = {}
    for link in getattr(unit, "weapon_links", []) or []:
        weapon_id = getattr(link, "weapon_id", None)
        weapon = getattr(link, "weapon", None)
        if weapon_id is None or weapon is None:
            continue
        weapon_by_id[int(weapon_id)] = weapon
    default_weapon_id = getattr(unit, "default_weapon_id", None)
    default_weapon = getattr(unit, "default_weapon", None)
    if default_weapon_id is not None and default_weapon is not None:
        weapon_by_id[int(default_weapon_id)] = default_weapon

    # melee_cost_by_weapon / weapon_counts feed melee_vector_from_counts below
    # (crowding discount) -- built alongside ranged_bucket in this same loop
    # so weapon_cost_components is called once per selected weapon, not
    # twice (melee_cost_per_model used to re-resolve weapon_by_id and re-cost
    # every weapon from scratch; role_totals.py already avoids this via its
    # own _shared_weapon_components reuse -- this mirrors that pattern).
    melee_cost_by_weapon: dict[int, float] = {}
    weapon_counts: dict[int, int] = {}
    ranged_bucket = 0.0
    has_explicit_weapons = False
    raw_weapons = normalized_loadout.get("weapons")
    if isinstance(raw_weapons, dict):
        for raw_key, raw_count in raw_weapons.items():
            key_str = str(raw_key).strip()
            if not key_str:
                continue
            base_id = key_str.split(":", 1)[0]
            try:
                weapon_id = int(base_id)
            except (TypeError, ValueError):
                continue
            try:
                stored_count = max(int(raw_count), 0)
            except (TypeError, ValueError):
                stored_count = 0
            if stored_count <= 0:
                continue
            selected_count = stored_count if mode_total else stored_count * model_count
            if selected_count <= 0:
                continue
            weapon = weapon_by_id.get(weapon_id)
            if weapon is None:
                continue
            has_explicit_weapons = True
            components = weapon_cost_components(weapon, unit.quality, base_traits)
            melee_cost_by_weapon[weapon_id] = float(components.get("melee") or 0.0)
            weapon_counts[weapon_id] = weapon_counts.get(weapon_id, 0) + stored_count
            ranged_bucket += float(components.get("ranged") or 0.0) * selected_count
    # Default-weapon fallback is always an identical per-model copy,
    # regardless of loadout mode -- matches melee_vector_from_counts's
    # mode_total=False contract (see crowding.py).
    melee_mode_total = mode_total
    if not has_explicit_weapons:
        melee_mode_total = False
        for default_weapon in unit_default_weapons(unit):
            components = weapon_cost_components(default_weapon, unit.quality, base_traits)
            ranged_bucket += float(components.get("ranged") or 0.0) * model_count
            default_weapon_key = getattr(default_weapon, "id", None)
            if default_weapon_key is None:
                continue
            default_weapon_key = int(default_weapon_key)
            melee_cost_by_weapon[default_weapon_key] = float(components.get("melee") or 0.0)
            weapon_counts[default_weapon_key] = weapon_counts.get(default_weapon_key, 0) + 1

    # Melee crowding discount (base_size) — applied BEFORE the Wojownik/
    # Strzelec classification below, so an oversized unit's discounted melee
    # cost (not the raw one) is what gets compared against ranged_bucket.
    # See app/services/costs/crowding.py and HANDOFF_rozmiar-podstawki.md
    # decision D6.
    melee_vector = melee_vector_from_counts(
        weapon_counts, melee_cost_by_weapon, model_count, mode_total=melee_mode_total
    )
    melee_factors = (
        melee_factors_override
        if melee_factors_override is not None
        else melee_crowding_factors(melee_vector, getattr(unit, "base_size", None))
    )
    melee_bucket_effective = crowded_melee_total(melee_vector, melee_factors)

    previous_classification_slug: str | None = None
    raw_selected_role = raw_loadout.get("selected_role")
    if isinstance(raw_selected_role, str):
        ident = ability_identifier(raw_selected_role)
        if ident in ROLE_SLUGS:
            previous_classification_slug = ident
    raw_classification = raw_loadout.get("classification")
    if previous_classification_slug is None and isinstance(raw_classification, dict):
        raw_classification_slug = raw_classification.get("slug")
        if isinstance(raw_classification_slug, str):
            ident = ability_identifier(raw_classification_slug)
            if ident in ROLE_SLUGS:
                previous_classification_slug = ident
    selected_role_slug = _roster_unit_classification(
        melee_bucket_effective,
        ranged_bucket,
        fallback=previous_classification_slug or "wojownik",
    )
    totals = roster_unit_role_totals(
        roster_unit,
        normalized_loadout,
        _passive_state=_passive_state_cache,
        melee_factors=melee_factors,
    )
    warrior_total = float(totals.get("wojownik") or 0.0)
    shooter_total = float(totals.get("strzelec") or 0.0)
    selected_total_raw = shooter_total if selected_role_slug == "strzelec" else warrior_total
    selected_total = round(selected_total_raw, 2)
    selected_traits = _with_role_trait(base_traits, selected_role_slug)

    # selected_total_full: what selected_total would be WITHOUT the melee
    # crowding discount. Derived algebraically instead of a second full
    # roster_unit_role_totals call (expensive -- re-walks every passive):
    # crowding only ever touches the melee weapon component, and role_totals
    # applies it at full weight for wojownik (melee counts 1:1) or half
    # weight for strzelec (melee is already halved by the role's own
    # weapon-role multiplier) -- see role_totals.py's _compute_total.
    melee_raw_total = round(sum(melee_vector), 2)
    role_melee_multiplier = 1.0 if selected_role_slug == "wojownik" else 0.5
    melee_crowding_amount = round(
        (melee_raw_total - melee_bucket_effective) * role_melee_multiplier, 2
    )
    selected_total_full = round(selected_total + melee_crowding_amount, 2)

    base_component = round(
        base_model_cost(
            unit.quality,
            unit.defense,
            unit.toughness,
            selected_traits,
        )
        * model_count,
        2,
    )

    # Keyed by the per-link loadout key (ability_id, or "ability_id:value" for
    # parameterized abilities) — not the bare ability id. Several links (e.g.
    # multiple "Aura: X" choices) can share one generic ability id, so a
    # bare-id-keyed dict would collapse them onto the same slot.
    ability_link_by_key: dict[str, Any] = {}
    for link in getattr(unit, "abilities", []) or []:
        ability_id = getattr(getattr(link, "ability", None), "id", None)
        if ability_id is None:
            continue
        ability_link_by_key[ability_link_loadout_key(link)] = link

    def _section_total(section: str, ability: bool = False) -> float:
        data = normalized_loadout.get(section)
        if not isinstance(data, dict):
            return 0.0
        total = 0.0
        for raw_key, raw_count in data.items():
            key_str = str(raw_key).strip()
            if not key_str:
                continue
            per_model_count = max(int(raw_count), 0)
            if per_model_count <= 0:
                continue
            multiplier = 1 if mode_total else model_count
            if ability and any(ability_identifier(trait) == "masywny" for trait in base_traits):
                multiplier = 1 if mode_total else 1
            selected_count = per_model_count if mode_total else per_model_count * multiplier
            if section == "weapons":
                base_id = key_str.split(":", 1)[0]
                try:
                    item_id = int(base_id)
                except (TypeError, ValueError):
                    continue
                weapon = weapon_by_id.get(item_id)
                if weapon is None:
                    continue
                total += weapon_cost(weapon, unit.quality, selected_traits) * selected_count
            else:
                ability_link = ability_link_by_key.get(key_str)
                if ability_link is None:
                    continue
                total += ability_cost(
                    ability_link, selected_traits, toughness=unit.toughness
                ) * selected_count
        return round(total, 2)

    weapon_component = _section_total("weapons")
    if not has_explicit_weapons:
        default_weapon_total = 0.0
        for default_weapon in unit_default_weapons(unit):
            default_weapon_total += weapon_cost(
                default_weapon, unit.quality, selected_traits
            ) * model_count
        weapon_component = round(default_weapon_total, 2)
    active_component = _section_total("active", ability=True)
    aura_component = _section_total("aura", ability=True)

    passive_component = round(
        selected_total - (base_component + weapon_component + active_component + aura_component),
        2,
    )

    # --- item_costs: per-item breakdown for frontend display ---
    # Only computed when include_item_costs=True to avoid the expensive
    # passive-delta loop (2 × roster_unit_role_totals per passive ability)
    # on badge-only refresh calls.
    if include_item_costs:
        item_weapons: dict[str, float] = {}
        for wid, weapon in weapon_by_id.items():
            item_weapons[str(wid)] = round(weapon_cost(weapon, unit.quality, selected_traits), 2)

        item_active: dict[str, float] = {}
        item_aura: dict[str, float] = {}
        for link_key, link in ability_link_by_key.items():
            ability = getattr(link, "ability", None)
            if ability is None:
                continue
            cost = round(ability_cost(link, selected_traits, toughness=unit.toughness), 2)
            ability_type = getattr(ability, "type", None)
            if ability_type == "active":
                item_active[link_key] = cost
            elif ability_type == "aura":
                item_aura[link_key] = cost

        item_passive_deltas: dict[str, float] = {}
        passive_state_for_deltas = _passive_state_cache
        current_passive = dict(normalized_loadout.get("passive") or {})
        for entry in passive_state_for_deltas.payload:
            slug = str(entry.get("slug") or "").strip()
            if not slug or slug.startswith(ARMY_RULE_OFF_PREFIX):
                continue
            identifier = ability_identifier(slug) or slug
            loadout_on = {**normalized_loadout, "passive": {**current_passive, identifier: 1}}
            loadout_off = {**normalized_loadout, "passive": {**current_passive, identifier: 0}}
            totals_on = roster_unit_role_totals(roster_unit, loadout_on)
            totals_off = roster_unit_role_totals(roster_unit, loadout_off)
            delta = totals_on.get(selected_role_slug, 0.0) - totals_off.get(selected_role_slug, 0.0)
            item_passive_deltas[identifier] = round(delta, 2)

        computed_item_costs: dict[str, Any] = {
            "weapons": item_weapons,
            "active": item_active,
            "aura": item_aura,
            "passive_deltas": item_passive_deltas,
        }
    else:
        computed_item_costs = _empty_item_costs

    return {
        "cost_engine_version": COST_ENGINE_VERSION,
        "selected_role": selected_role_slug,
        "warrior_total": round(warrior_total, 2),
        "shooter_total": round(shooter_total, 2),
        "selected_total": selected_total,
        # selected_total before the melee crowding discount (base_size) --
        # informational, for UI display of "you're saving N pkt from
        # crowding". NOT part of the base+weapon+active+aura+passive sum.
        "selected_total_full": selected_total_full,
        # Per-model melee weapon cost vector (length == model_count), pre-
        # discount. See costs/crowding.py.
        "melee_per_model": [round(v, 2) for v in melee_vector],
        "components": {
            "base": base_component,
            "weapon": weapon_component,
            "active": active_component,
            "aura": aura_component,
            "passive": passive_component,
            # Informational only (negative = savings) -- like weapon_component
            # above, NOT reconciled against passive_component's residual
            # formula, consistent with weapon_component already being an
            # approximation (full weapon cost, no role-halving) rather than
            # the true role-adjusted contribution used inside selected_total.
            "melee_crowding": -melee_crowding_amount,
        },
        "item_costs": computed_item_costs,
        "loadout": normalized_loadout,
    }

