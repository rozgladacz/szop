"""Roster-level cost aggregation.

Extracted from ``_engine.py`` Section 10 (ROSTER-LEVEL AGGREGATION).

These functions are thin orchestrators: they call ``calculate_roster_unit_quote``
per roster unit, accumulate the results, and persist ``cached_cost`` back onto the
ORM entities.  No cost arithmetic lives here — see ``quote.py`` (Section 8) when
that is extracted.

Imports ``calculate_roster_unit_quote``, ``normalize_roster_unit_count``, and
``_ensure_extra_data`` from ``_engine`` (those functions are still in ``_engine``
until Section 8 and Section 3 are extracted in a follow-up session).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ... import models
from ._engine import (
    _ensure_extra_data,
    calculate_roster_unit_quote,
    normalize_roster_unit_count,
)


def roster_unit_cost(roster_unit: models.RosterUnit) -> float:
    count = normalize_roster_unit_count(getattr(roster_unit, "count", 1), default=1)
    quote = calculate_roster_unit_quote(
        getattr(roster_unit, "unit", None),
        _ensure_extra_data(getattr(roster_unit, "extra_weapons_json", None)),
        count,
        include_item_costs=False,
    )
    return float(quote.get("selected_total") or 0.0)


def recalculate_roster_costs(
    roster: models.Roster | None,
    loadout_overrides: Mapping[int, dict[str, Any] | None] | None = None,
    changed_unit_ids: set[int] | None = None,
    precomputed_costs: Mapping[int, float] | None = None,
) -> tuple[float, dict[int, float]]:
    """Recalculate ``cached_cost`` for every roster unit and return total + per-unit map.

    ``loadout_overrides`` can provide transient loadouts keyed by ``RosterUnit.id``.
    Overrides are used for cost calculation in the current call and persisted back to
    ``cached_cost`` immediately.

    ``changed_unit_ids`` — when provided, only those units are recalculated; all
    other units reuse their existing ``cached_cost`` value.  This avoids recomputing
    the entire roster on every single-unit edit.  Only pass this when you can guarantee
    that the other units' ``cached_cost`` values are up to date (i.e. after a prior full
    recalculation or save).

    ``precomputed_costs`` — when provided, units whose id appears in this mapping
    use the given cost value directly without calling ``calculate_roster_unit_quote``.
    Callers are responsible for ensuring these values are correct (e.g. derived from
    a prior ``_classification_map`` that already computed the quote).

    Architectural rule: ORM entities and SQLAlchemy ``Session`` are processed
    sequentially in-request. If CPU parallelism is introduced in the future, it must
    run only on immutable snapshots (DTO/dict) prepared before worker execution.
    """
    if roster is None:
        return 0.0, {}
    total = 0.0
    unit_costs: dict[int, float] = {}
    roster_units = getattr(roster, "roster_units", []) or []
    for roster_unit in roster_units:
        unit_id = getattr(roster_unit, "id", None)
        if changed_unit_ids is not None and unit_id not in changed_unit_ids:
            cost_value = float(getattr(roster_unit, "cached_cost", None) or 0.0)
            if unit_id is not None:
                unit_costs[unit_id] = cost_value
            total += cost_value
            continue
        if precomputed_costs and unit_id is not None and unit_id in precomputed_costs:
            cost_value = round(float(precomputed_costs[unit_id]), 2)
            if hasattr(roster_unit, "cached_cost"):
                roster_unit.cached_cost = cost_value
            unit_costs[unit_id] = cost_value
            total += cost_value
            continue
        override = None
        if loadout_overrides and unit_id is not None:
            override = loadout_overrides.get(unit_id)
        quote = calculate_roster_unit_quote(
            getattr(roster_unit, "unit", None),
            override
            if override is not None
            else _ensure_extra_data(getattr(roster_unit, "extra_weapons_json", None)),
            normalize_roster_unit_count(getattr(roster_unit, "count", 1), default=1),
            include_item_costs=False,
        )
        cost_value = float(quote.get("selected_total") or 0.0)
        if hasattr(roster_unit, "cached_cost"):
            roster_unit.cached_cost = cost_value
        if unit_id is not None:
            unit_costs[unit_id] = cost_value
        total += cost_value
    return round(total, 2), unit_costs


def roster_total(roster: models.Roster) -> float:
    total, _ = recalculate_roster_costs(roster)
    return total


def ensure_cached_costs(roster_units: Iterable[models.RosterUnit]) -> None:
    for roster_unit in roster_units:
        if getattr(roster_unit, "cached_cost", None) is None:
            roster_unit.cached_cost = roster_unit_cost(roster_unit)


def update_cached_costs(roster_units: Iterable[models.RosterUnit]) -> None:
    for ru in roster_units:
        ru.cached_cost = roster_unit_cost(ru)


__all__ = [
    "ensure_cached_costs",
    "recalculate_roster_costs",
    "roster_total",
    "roster_unit_cost",
    "update_cached_costs",
]
