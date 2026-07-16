"""Melee crowding discount -- SSOT for base_size-driven melee cost reduction.

Rozmiar podstawki (base_size: mala/srednia/duza) okresla ile modeli oddzialu
efektywnie moze walczyc w zwarciu. Modele "nadmiarowe" (powyzej limitu) placa
mniej za bron wrecz, bo w praktyce nie dosiegaja wroga. Zniska liczona jest
PRZED klasyfikacja Wojownik/Strzelec -- patrz costs/quote.py (Faza 3).

Dependency order: ten modul siedzi na tym samym poziomie co role_totals.py
(zalezy tylko od _engine, weapons, unit_helpers) -- role_totals.py i quote.py
moga bezpiecznie importowac stad bez ryzyka cyklu.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ... import models
from ._engine import base_size_melee_limits
from .unit_helpers import unit_default_weapons
from .weapons import weapon_cost_components


def melee_vector_from_counts(
    weapons_counts: Mapping[int, int],
    melee_cost_by_weapon: Mapping[int, float],
    model_count: int,
    *,
    mode_total: bool,
) -> list[float]:
    """Per-model melee cost vector from already-parsed weapon counts.

    Lower-level building block: takes a pre-parsed ``{weapon_id: count}``
    map and a pre-computed ``{weapon_id: melee_cost}`` map instead of a raw
    unit + loadout. Deliberately has NO "no explicit weapons" fallback --
    callers that need one (e.g. ``melee_cost_per_model`` below, mirroring
    ``calculate_roster_unit_quote``'s ``has_explicit_weapons`` guard) resolve
    it themselves before calling. This keeps this function usable by callers
    whose own weapon-total logic has no such fallback (role_totals.py's
    ``_aggregate_weapon_buckets`` returns 0 for an empty weapon selection,
    it does not default to the unit's base loadout).

    ``mode_total=False`` (per_model): every model is identical -> a single
    aggregate cost repeated ``model_count`` times.
    ``mode_total=True``: counts are unit-wide, not per-model. Each count is
    expanded into individual "instances" (weight = that weapon's melee
    cost), sorted descending, and dealt round-robin across ``model_count``
    slots -- keeps expensive melee loadouts from clustering onto one vector
    position, as a best-effort approximation (no per-model identity is
    stored on RosterUnit for total-mode loadouts).
    """
    if model_count <= 0:
        return []
    if mode_total:
        instances: list[float] = []
        for weapon_id, count in weapons_counts.items():
            if count <= 0:
                continue
            cost = float(melee_cost_by_weapon.get(weapon_id) or 0.0)
            instances.extend([cost] * count)
        instances.sort(reverse=True)
        per_model = [0.0] * model_count
        for idx, cost in enumerate(instances):
            per_model[idx % model_count] += cost
        return per_model

    per_model_total = sum(
        float(melee_cost_by_weapon.get(weapon_id) or 0.0) * count
        for weapon_id, count in weapons_counts.items()
        if count > 0
    )
    return [per_model_total] * model_count


def melee_cost_per_model(
    unit: models.Unit,
    normalized_loadout: dict[str, Any],
    model_count: int,
    base_traits: Sequence[str],
) -> list[float]:
    """Per-model melee weapon cost vector (length == model_count).

    Resolves the unit's weapon selection (explicit loadout, or -- when
    nothing is explicitly selected -- the unit's default weapon loadout,
    matching calculate_roster_unit_quote's has_explicit_weapons fallback in
    quote.py) into counts + per-weapon melee costs, then delegates the
    actual per-model distribution to ``melee_vector_from_counts``.

    No explicit weapons selected (empty ``weapons`` section) -> the unit's
    default weapon loadout is used, always treated as an identical per-model
    copy regardless of loadout mode -- matching quote.py's fallback, which
    also multiplies by model_count unconditionally.
    """
    if model_count <= 0:
        return []

    weapon_by_id: dict[int, Any] = {}
    for link in getattr(unit, "weapon_links", None) or []:
        weapon_id = getattr(link, "weapon_id", None)
        weapon = getattr(link, "weapon", None)
        if weapon_id is None or weapon is None:
            continue
        weapon_by_id[int(weapon_id)] = weapon
    default_weapon_id = getattr(unit, "default_weapon_id", None)
    default_weapon_obj = getattr(unit, "default_weapon", None)
    if default_weapon_id is not None and default_weapon_obj is not None:
        weapon_by_id[int(default_weapon_id)] = default_weapon_obj

    mode_total = normalized_loadout.get("mode") == "total"
    raw_weapons = normalized_loadout.get("weapons")

    # mode_total is fixed for the whole loop (doesn't vary per item), so a
    # single counts dict suffices -- melee_vector_from_counts interprets it
    # as per-model or unit-wide based on the mode_total flag passed below.
    counts: dict[int, int] = {}
    has_explicit_weapons = False
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
            if stored_count <= 0 or weapon_id not in weapon_by_id:
                continue
            has_explicit_weapons = True
            counts[weapon_id] = counts.get(weapon_id, 0) + stored_count

    if not has_explicit_weapons:
        # counts is guaranteed empty here (nothing above adds to it without
        # also setting has_explicit_weapons=True).
        for weapon in unit_default_weapons(unit):
            weapon_id = getattr(weapon, "id", None)
            if weapon_id is None:
                continue
            weapon_id = int(weapon_id)
            weapon_by_id.setdefault(weapon_id, weapon)
            counts[weapon_id] = counts.get(weapon_id, 0) + 1
        # Default loadout is always an identical per-model copy, regardless
        # of loadout mode -- force mode_total=False so `counts` (per-model
        # semantics) is read correctly.
        mode_total = False

    # Lazy -- only cost the weapon_ids actually selected, not every option on
    # the unit (weapon_cost_components is not free; see weapons.py's "keep it
    # lean" note on the same inner-loop cost function).
    melee_cost_by_weapon = {
        weapon_id: float(weapon_cost_components(weapon_by_id[weapon_id], unit.quality, base_traits).get("melee") or 0.0)
        for weapon_id in counts
        if weapon_id in weapon_by_id
    }
    return melee_vector_from_counts(
        counts, melee_cost_by_weapon, model_count, mode_total=mode_total
    )


def melee_crowding_factors(vector: Sequence[float], base_size: str | None) -> list[float]:
    """Per-position melee cost multiplier from base_size crowding limits.

    Models are ranked by melee cost descending (ties broken by original
    index for determinism). The top ``limit1`` ranked models keep full cost
    (x1.0), the next ``limit1..limit2`` get x0.5, and the rest get x0.1.
    Returned list is aligned to the INPUT order: ``factors[i]`` applies to
    ``vector[i]``, not to the sorted rank.
    """
    limit1, limit2 = base_size_melee_limits(base_size)
    count = len(vector)
    if count == 0:
        return []
    order = sorted(range(count), key=lambda i: (-vector[i], i))
    factors = [0.0] * count
    for rank, idx in enumerate(order):
        position = rank + 1
        if position <= limit1:
            factors[idx] = 1.0
        elif position <= limit2:
            factors[idx] = 0.5
        else:
            factors[idx] = 0.1
    return factors


def crowded_melee_total(vector: Sequence[float], factors: Sequence[float]) -> float:
    return round(sum(v * f for v, f in zip(vector, factors)), 2)


__all__ = [
    "crowded_melee_total",
    "melee_cost_per_model",
    "melee_crowding_factors",
    "melee_vector_from_counts",
]
