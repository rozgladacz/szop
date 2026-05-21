"""Role-based cost classification and totals.

Extracted from ``_engine.py`` Section 9 (ROLE CLASSIFICATION & TOTALS).

``roster_unit_role_totals`` computes per-model cost for a roster unit under
both role variants (wojownik / strzelec) and returns both values so the caller
can pick the one that produces the cheaper (or more appropriate) total.

Design notes
------------
- The function contains several tightly-coupled inner helpers (closures) that
  share local state (passive_state, model counts, precomputed maps).  They are
  intentionally left as closures rather than extracted further to avoid
  threading ~15 arguments through a call chain.
- Two inner caches (``_passive_entries_cache``, ``_ability_cost_map_cache``)
  are keyed by a sorted-tuple of trait strings so the warrior/strzelec
  invocations share computed results when the only difference between their
  trait lists is the role slug itself.
- ``_roster_unit_classification`` (a tiny pure helper) stays in ``_engine.py``
  because ``calculate_roster_unit_quote`` (Section 8, still in ``_engine.py``)
  calls it directly, and moving it here would create an import of a tiny
  two-line function — not worth the churn until Section 8 is extracted.

Monkeypatching note: tests that patch ``costs._engine.compute_passive_state``
or ``costs._engine.ability_cost_from_name`` will NOT affect calls inside this
module (those resolve via this module's globals).  After this extraction,
patch ``costs.role_totals.compute_passive_state`` etc. if you need to intercept
calls from inside ``roster_unit_role_totals``.  Calls originating from
``calculate_roster_unit_quote`` (still in ``_engine.py``) are unaffected.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ... import models
from ..utils import ARMY_RULE_OFF_PREFIX
from ._engine import ROLE_SLUGS, PassiveState
from .abilities import ability_cost_components_from_name, base_model_cost
from .passive_state import (
    _active_traits_from_payload,
    _ensure_extra_data,
    _passive_flag_maps,
    compute_passive_state,
    normalize_roster_unit_count,
)
from .primitives import (
    _strip_role_traits,
    _with_role_trait,
    ability_identifier,
    extract_number,
    normalize_name,
)
from .unit_helpers import _ability_link_is_default, ability_cost, unit_default_weapons
from .weapons import weapon_cost_components


def roster_unit_role_totals(
    roster_unit: models.RosterUnit,
    payload: dict[str, dict[str, int]] | None = None,
    *,
    _passive_state: PassiveState | None = None,
) -> dict[str, float]:
    """Return totals for both role variants for one roster unit.

    ``roster_unit.count`` is normalized through :func:`normalize_roster_unit_count`.
    Values less than or equal to zero (or unparsable values) return
    zero totals for both roles.

    ``_passive_state`` — optional pre-computed result of ``compute_passive_state``.
    When provided, avoids the redundant second call to ``compute_passive_state``
    (e.g. when the caller already computed it).
    """
    unit = getattr(roster_unit, "unit", None)
    if unit is None:
        return {"wojownik": 0.0, "strzelec": 0.0}

    extra_data = (
        payload
        if isinstance(payload, dict)
        else _ensure_extra_data(getattr(roster_unit, "extra_weapons_json", None))
    ) or {}
    raw_data: dict[str, Any] = extra_data if isinstance(extra_data, dict) else {}

    mode_value = raw_data.get("mode")
    loadout_mode: str | None = mode_value if isinstance(mode_value, str) else None

    passive_state = _passive_state if _passive_state is not None else compute_passive_state(unit, raw_data)
    base_traits = _strip_role_traits(passive_state.traits)
    default_traits_full = _active_traits_from_payload(passive_state.payload, {})
    default_base_traits = _strip_role_traits(default_traits_full)
    default_weapons = unit_default_weapons(unit)
    has_massive_trait = any(
        ability_identifier(trait) == "masywny" for trait in base_traits
    )

    def _parse_counts(section: str) -> dict[int, int]:
        raw_section = raw_data.get(section)
        result: dict[int, int] = {}
        if isinstance(raw_section, dict):
            items = raw_section.items()
        elif isinstance(raw_section, list):
            temp: list[tuple[Any, Any]] = []
            for entry in raw_section:
                if not isinstance(entry, dict):
                    continue
                entry_id = (
                    entry.get("loadout_key")
                    or entry.get("key")
                    or entry.get("id")
                    or entry.get("weapon_id")
                    or entry.get("ability_id")
                )
                if entry_id is None:
                    continue
                temp.append((entry_id, entry.get("per_model") or entry.get("count") or 0))
            items = temp
        else:
            items = []
        for raw_id, raw_value in items:
            raw_id_str = str(raw_id)
            base_id = raw_id_str.split(":", 1)[0]
            try:
                parsed_id = int(base_id)
            except (TypeError, ValueError):
                try:
                    parsed_id = int(float(base_id))
                except (TypeError, ValueError):
                    continue
            try:
                parsed_value = int(raw_value)
            except (TypeError, ValueError):
                try:
                    parsed_value = int(float(raw_value))
                except (TypeError, ValueError):
                    parsed_value = 0
            if parsed_value < 0:
                parsed_value = 0
            result[parsed_id] = parsed_value
        return result

    weapons_counts = _parse_counts("weapons")
    active_counts = _parse_counts("active")
    aura_counts = _parse_counts("aura")
    passive_counts = passive_state.counts

    total_mode = loadout_mode == "total"
    model_multiplier = normalize_roster_unit_count(
        getattr(roster_unit, "count", 0), default=0
    )
    if model_multiplier <= 0:
        return {"wojownik": 0.0, "strzelec": 0.0}
    model_count = model_multiplier

    ability_multiplier = (
        0 if model_multiplier == 0 else 1 if has_massive_trait else model_count
    )

    def _to_total(value: int, *, ability: bool = False) -> int:
        safe_value = max(int(value), 0)
        if total_mode:
            return safe_value
        multiplier = ability_multiplier if ability else model_count
        return safe_value * multiplier

    def _weapon_components_map(current_traits: Sequence[str]) -> dict[int, dict[str, float]]:
        results: dict[int, dict[str, float]] = {}
        links = getattr(unit, "weapon_links", None) or []
        for link in links:
            weapon = link.weapon
            if not weapon or link.weapon_id is None:
                continue
            if link.weapon_id in results:
                continue
            results[link.weapon_id] = weapon_cost_components(
                weapon,
                unit.quality,
                current_traits,
            )
        if unit.default_weapon and unit.default_weapon_id is not None:
            weapon_id = unit.default_weapon_id
            if weapon_id not in results:
                results[weapon_id] = weapon_cost_components(
                    unit.default_weapon,
                    unit.quality,
                    current_traits,
                )
        return results

    def _aggregate_weapon_buckets(
        components_map: Mapping[int, Mapping[str, float]],
    ) -> dict[str, float]:
        melee_total = 0.0
        ranged_total = 0.0
        for weapon_id, stored_count in weapons_counts.items():
            components = components_map.get(weapon_id)
            if components is None:
                continue
            selected_count = _to_total(stored_count)
            if selected_count <= 0:
                continue
            melee_total += float(components.get("melee") or 0.0) * selected_count
            ranged_total += float(components.get("ranged") or 0.0) * selected_count
        return {
            "melee": round(melee_total, 2),
            "ranged": round(ranged_total, 2),
        }

    # Memoize per (sorted traits) — _passive_entries does an expensive
    # ability_cost_components_from_name call per passive (~0.5-2ms each).
    # warrior/strzelec usually differ by exactly one trait, so the inputs to
    # most ability cost computations are identical → cache hit on the second
    # role.  Cleared at end of roster_unit_role_totals via local closure.
    _passive_entries_cache: dict[tuple[str, ...], list[dict[str, Any]]] = {}

    def _passive_entries(current_traits: Sequence[str]) -> list[dict[str, Any]]:
        key = tuple(sorted(str(t) for t in current_traits))
        cached = _passive_entries_cache.get(key)
        if cached is not None:
            return cached
        entries: list[dict[str, Any]] = []
        for entry in passive_state.payload:
            slug = str(entry.get("slug") or "").strip()
            if not slug or slug in ROLE_SLUGS or slug.startswith(ARMY_RULE_OFF_PREFIX):
                continue
            label = entry.get("label") or slug
            value = entry.get("value")
            default_count = int(entry.get("default_count") or 0)
            components = ability_cost_components_from_name(
                label or slug,
                value,
                current_traits,
                toughness=unit.toughness,
                quality=unit.quality,
                defense=unit.defense,
                weapons=default_weapons,
            )
            entries.append(
                {
                    "slug": slug,
                    "default_count": default_count,
                    "cost": float(components.base),
                }
            )
        _passive_entries_cache[key] = entries
        return entries

    passive_defaults, _ = _passive_flag_maps(passive_state)

    def _passive_default_flag(name: str | None) -> int | None:
        for key in (ability_identifier(name), normalize_name(name)):
            if key and key in passive_defaults:
                return passive_defaults[key]
        return None

    # Pre-sort and pre-filter ability links ONCE — used by every
    # _ability_cost_map invocation and several role-independent loops below.
    _sorted_ability_links: list[models.UnitAbility] = [
        link for link in getattr(unit, "abilities", []) if link.ability
    ]
    _sorted_ability_links.sort(
        key=lambda link: (
            getattr(link, "position", 0),
            getattr(link, "id", 0) or 0,
        )
    )

    # Role-independent precompute (was previously rebuilt twice — once per
    # warrior/strzelec invocation of _compute_total — with an O(N²) inner
    # `next(...)` lookup per ability that hammered profiles on units with
    # many abilities).  Replaces `ability_id_to_ident` + the `next(...)` link
    # lookup loop inside _compute_total.
    _ability_id_to_ident: dict[int, str] = {}
    _link_by_ability_id: dict[int, models.UnitAbility] = {}
    _base_active_set_precomputed: set[str] = set()
    for _link in _sorted_ability_links:
        _ability = _link.ability
        _ability_id_raw = getattr(_ability, "id", None)
        if _ability_id_raw is None:
            continue
        _ability_id_int = int(_ability_id_raw)
        _link_by_ability_id[_ability_id_int] = _link
        _ident = ability_identifier(getattr(_ability, "slug", None) or _ability.name)
        if not _ident:
            continue
        _ability_id_to_ident[_ability_id_int] = _ident
        if _ability_link_is_default(_link):
            _base_active_set_precomputed.add(_ident)

    # Memoized like _passive_entries — same trait-fingerprint key.
    _ability_cost_map_cache: dict[
        tuple[str, ...], tuple[dict[int, float], float, float]
    ] = {}

    def _ability_cost_map(
        current_traits: Sequence[str],
    ) -> tuple[dict[int, float], float, float]:
        key = tuple(sorted(str(t) for t in current_traits))
        cached = _ability_cost_map_cache.get(key)
        if cached is not None:
            return cached
        ability_map: dict[int, float] = {}
        passive_total = 0.0
        active_total = 0.0
        for link in _sorted_ability_links:
            ability = link.ability
            cost_value = ability_cost(
                link,
                current_traits,
                toughness=unit.toughness,
            )
            if ability.type == "passive":
                default_flag = _passive_default_flag(ability.name)
                if default_flag is None or default_flag > 0:
                    passive_total += cost_value
            else:
                ability_map[ability.id] = cost_value
                active_total += cost_value
        result = (ability_map, passive_total, active_total)
        _ability_cost_map_cache[key] = result
        return result

    # Pre-compute weapon components once (role-independent: role slug is stripped)
    _shared_weapon_components = _weapon_components_map(base_traits)

    # Selected_active_set is also role-independent (depends only on
    # active_counts/aura_counts which are part of the loadout, not the role).
    _selected_active_set_precomputed: set[str] = set()
    for _aid, _ident in _ability_id_to_ident.items():
        if active_counts.get(_aid, 0) > 0 or aura_counts.get(_aid, 0) > 0:
            _selected_active_set_precomputed.add(_ident)

    def _compute_total(current_traits: Sequence[str], selected_role: str) -> float:
        ability_map, passive_total, _ = _ability_cost_map(current_traits)
        default_traits_with_role = _with_role_trait(default_base_traits, selected_role)
        base_value = base_model_cost(
            unit.quality,
            unit.defense,
            unit.toughness,
            default_traits_with_role,
        )
        base_per_model = base_value
        passive_entries = _passive_entries(current_traits)
        weapon_buckets = _aggregate_weapon_buckets(_shared_weapon_components)

        total = base_per_model * model_count
        if passive_total:
            total += passive_total * (1 if total_mode else ability_multiplier)
        weapon_total = weapon_buckets["melee"] + weapon_buckets["ranged"]
        if selected_role == "wojownik":
            weapon_total -= weapon_buckets["ranged"] * 0.5
        elif selected_role == "strzelec":
            weapon_total -= weapon_buckets["melee"] * 0.5
        total += weapon_total
        for ability_id, stored_count in {**active_counts, **aura_counts}.items():
            cost_value = ability_map.get(ability_id)
            if cost_value is None:
                continue
            total += cost_value * _to_total(stored_count, ability=True)

        # Reuse role-independent precomputes (was: rebuilt every call with
        # an O(N²) next(...) lookup over unit.abilities).
        base_active_set = _base_active_set_precomputed
        selected_active_set = _selected_active_set_precomputed

        def _is_odwody_blocked(active_set: set[str]) -> bool:
            return bool({"rezerwa", "zwiadowca", "zasadzka"} & active_set)

        def _transport_multiplier(active_set: set[str]) -> float:
            if "samolot" in active_set:
                return 3.5
            if "zasadzka" in active_set or "zwiadowca" in active_set:
                return 2.5
            if "latajacy" in active_set:
                return 1.5
            if "szybki" in active_set or "zwinny" in active_set:
                return 1.25
            return 1.0

        def _effective_passive_cost(entry: dict[str, Any], active_set: set[str], cost_value: float) -> float:
            slug = str(entry.get("slug") or "")
            ident = ability_identifier(slug)
            if not ident:
                return cost_value
            if ident == "odwody" and _is_odwody_blocked(active_set):
                return 0.0

            is_transport = ident == "transport"
            is_open_transport = ident in {"otwarty_transport", "platforma_strzelecka", "otwarty transport", "platforma strzelecka"}
            if is_transport or is_open_transport:
                capacity = extract_number(
                    str(
                        entry.get("value")
                        or entry.get("label")
                        or entry.get("slug")
                        or ""
                    )
                )
                if capacity > 0:
                    multiplier = _transport_multiplier(active_set)
                    if is_open_transport:
                        multiplier += 0.25
                    return capacity * multiplier
            return cost_value

        passive_diff = 0.0
        for entry in passive_entries:
            slug = entry.get("slug")
            if not slug:
                continue
            default_value = 1 if entry.get("default_count") else 0
            selected_value = passive_counts.get(str(slug), default_value)
            selected_flag = 1 if selected_value else 0
            diff = selected_flag - default_value
            if diff == 0:
                continue
            cost_value = float(entry.get("cost") or 0.0)
            # Compute identifier ONCE per entry — was previously called twice
            # (lines `ident = ...` and `passive_ident = ...`) which doubled
            # ability_identifier hits in the inner loop.
            ident = ability_identifier(str(slug))
            is_dynamic_transport = ident in {
                "transport",
                "otwarty_transport",
                "platforma_strzelecka",
                "otwarty transport",
                "platforma strzelecka",
            }
            if cost_value == 0.0 and not is_dynamic_transport:
                continue
            default_cost = (
                _effective_passive_cost(entry, base_active_set, cost_value)
                if default_value
                else 0.0
            )
            selected_cost = (
                _effective_passive_cost(entry, selected_active_set, cost_value)
                if selected_flag
                else 0.0
            )
            passive_entry_diff = selected_cost - default_cost
            if passive_entry_diff == 0:
                continue
            passive_multiplier = model_count
            passive_diff += passive_entry_diff * passive_multiplier
        if passive_diff:
            total += passive_diff

        return round(total, 2)

    warrior_traits = _with_role_trait(base_traits, "wojownik")
    shooter_traits = _with_role_trait(base_traits, "strzelec")
    warrior_total = _compute_total(warrior_traits, "wojownik")
    shooter_total = _compute_total(shooter_traits, "strzelec")
    return {"wojownik": warrior_total, "strzelec": shooter_total}


__all__ = [
    "roster_unit_role_totals",
]
