from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services import costs
from app.services.costs.crowding import (
    crowded_melee_total,
    melee_cost_per_model,
    melee_crowding_factors,
    melee_vector_from_counts,
)


def _melee_weapon(weapon_id: int, *, ap: int = 0) -> SimpleNamespace:
    return SimpleNamespace(id=weapon_id, range="", attacks=1, ap=ap, tags="", parent=None)


def _unit(weapon_links: list[SimpleNamespace], *, default_weapon=None, default_weapon_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        quality=4,
        defense=4,
        toughness=4,
        flags="",
        weapon_links=weapon_links,
        default_weapon=default_weapon,
        default_weapon_id=default_weapon_id,
    )


def _link(weapon: SimpleNamespace, *, is_default: bool = True, default_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        weapon_id=weapon.id,
        weapon=weapon,
        is_default=is_default,
        default_count=default_count,
    )


# ---------------------------------------------------------------------------
# melee_crowding_factors / crowded_melee_total
# ---------------------------------------------------------------------------


def test_melee_crowding_factors_below_limit_all_full_cost():
    vector = [10.0, 8.0, 6.0]
    factors = melee_crowding_factors(vector, "duza")  # limits (2, 4) -> position 3 is discounted
    # duza limit1=2: only top 2 stay at 1.0, position 3 (rank 3) drops to 0.5
    assert factors == [1.0, 1.0, 0.5]


def test_melee_crowding_factors_small_unit_no_discount():
    vector = [5.0, 3.0]
    factors = melee_crowding_factors(vector, "mala")  # limits (8, 12) -- well above count
    assert factors == [1.0, 1.0]


def test_melee_crowding_factors_all_three_tiers():
    # srednia: limit1=6, limit2=8. 10 models -> ranks 1-6 full, 7-8 half, 9-10 tenth.
    vector = [float(v) for v in range(10, 0, -1)]  # 10..1, already descending
    factors = melee_crowding_factors(vector, "srednia")
    assert factors == [1.0] * 6 + [0.5] * 2 + [0.1] * 2


def test_melee_crowding_factors_preserves_input_order_not_sorted_order():
    # Non-monotonic input: rank by value, but factors align to original index.
    vector = [1.0, 10.0, 5.0]  # ranks: idx1(10)=1st, idx2(5)=2nd, idx0(1)=3rd
    factors = melee_crowding_factors(vector, "duza")  # limit1=2, limit2=4
    assert factors == [0.5, 1.0, 1.0]


def test_melee_crowding_factors_ties_broken_by_original_index():
    vector = [5.0, 5.0, 5.0, 5.0]
    factors = melee_crowding_factors(vector, "duza")  # limit1=2, limit2=4
    # Equal costs -> stable tie-break keeps earliest indices at full cost.
    assert factors == [1.0, 1.0, 0.5, 0.5]


def test_melee_crowding_factors_unknown_base_size_falls_back_to_default():
    vector = [float(v) for v in range(10, 0, -1)]
    assert melee_crowding_factors(vector, "gigantyczna") == melee_crowding_factors(vector, costs.DEFAULT_BASE_SIZE)
    assert melee_crowding_factors(vector, None) == melee_crowding_factors(vector, costs.DEFAULT_BASE_SIZE)


def test_melee_crowding_factors_empty_vector():
    assert melee_crowding_factors([], "duza") == []


def test_crowded_melee_total_applies_factors_and_rounds():
    vector = [10.0, 8.0, 6.0]
    factors = [1.0, 1.0, 0.5]
    assert crowded_melee_total(vector, factors) == 21.0  # 10 + 8 + 3


# ---------------------------------------------------------------------------
# melee_cost_per_model
# ---------------------------------------------------------------------------


def test_melee_cost_per_model_zero_count_returns_empty():
    unit = _unit([])
    assert melee_cost_per_model(unit, {"mode": "per_model", "weapons": {}}, 0, []) == []


def test_melee_cost_per_model_per_model_mode_identical_models():
    weapon = _melee_weapon(101, ap=0)
    unit = _unit([_link(weapon)])
    expected = costs.weapon_cost_components(weapon, unit.quality, [])["melee"]

    vector = melee_cost_per_model(
        unit, {"mode": "per_model", "weapons": {"101": 1}}, 5, []
    )

    assert vector == [expected] * 5


def test_melee_cost_per_model_per_model_mode_combines_multiple_weapons():
    weapon_a = _melee_weapon(101, ap=0)
    weapon_b = _melee_weapon(102, ap=2)
    unit = _unit([_link(weapon_a), _link(weapon_b)])
    cost_a = costs.weapon_cost_components(weapon_a, unit.quality, [])["melee"]
    cost_b = costs.weapon_cost_components(weapon_b, unit.quality, [])["melee"]

    vector = melee_cost_per_model(
        unit, {"mode": "per_model", "weapons": {"101": 1, "102": 1}}, 3, []
    )

    assert vector == [round(cost_a + cost_b, 2)] * 3


def test_melee_cost_per_model_no_explicit_weapons_falls_back_to_default_loadout():
    weapon = _melee_weapon(101, ap=1)
    unit = _unit([_link(weapon)], default_weapon=weapon, default_weapon_id=101)
    expected = costs.weapon_cost_components(weapon, unit.quality, [])["melee"]

    # Both modes must hit the same identical-per-model fallback.
    for mode in ("per_model", "total"):
        vector = melee_cost_per_model(unit, {"mode": mode, "weapons": {}}, 4, [])
        assert vector == [expected] * 4


def test_melee_cost_per_model_total_mode_round_robin_distribution():
    cheap = _melee_weapon(101, ap=0)
    pricey = _melee_weapon(102, ap=3)
    unit = _unit([_link(cheap), _link(pricey)])
    cheap_cost = costs.weapon_cost_components(cheap, unit.quality, [])["melee"]
    pricey_cost = costs.weapon_cost_components(pricey, unit.quality, [])["melee"]
    assert pricey_cost > cheap_cost  # sanity: ap=3 must cost more than ap=0

    # 3 copies of "cheap" + 2 copies of "pricey", spread across 3 models.
    vector = melee_cost_per_model(
        unit,
        {"mode": "total", "weapons": {"101": 3, "102": 2}},
        3,
        [],
    )

    # Reference distribution: instances sorted desc = [pricey, pricey, cheap, cheap, cheap]
    # round-robin over 3 slots -> slot0=[pricey,cheap], slot1=[pricey,cheap], slot2=[cheap]
    instances = sorted([pricey_cost, pricey_cost, cheap_cost, cheap_cost, cheap_cost], reverse=True)
    expected = [0.0, 0.0, 0.0]
    for idx, cost in enumerate(instances):
        expected[idx % 3] += cost
    assert vector == expected
    assert round(sum(vector), 2) == round(2 * pricey_cost + 3 * cheap_cost, 2)


def test_melee_cost_per_model_total_mode_unknown_weapon_id_ignored_alongside_known():
    weapon = _melee_weapon(101, ap=0)
    unit = _unit([_link(weapon)])
    expected = costs.weapon_cost_components(weapon, unit.quality, [])["melee"]
    # weapon_id 999 is not part of the unit's weapon_links -> silently skipped,
    # matching calculate_roster_unit_quote's weapon_by_id.get(...) is None guard.
    # The known id (101) still counts, so this does NOT trigger the "no
    # explicit weapons" default-loadout fallback (has_explicit_weapons=True).
    vector = melee_cost_per_model(
        unit, {"mode": "total", "weapons": {"101": 2, "999": 5}}, 2, []
    )
    assert vector == [expected, expected]


def test_melee_cost_per_model_total_mode_all_unknown_weapon_ids_falls_back_to_default():
    weapon = _melee_weapon(101, ap=0)
    unit = _unit([_link(weapon)])
    expected = costs.weapon_cost_components(weapon, unit.quality, [])["melee"]
    # When NOTHING in the loadout matches a real weapon, has_explicit_weapons
    # stays False -> same fallback-to-default behaviour as
    # calculate_roster_unit_quote (see quote.py's has_explicit_weapons guard).
    vector = melee_cost_per_model(
        unit, {"mode": "total", "weapons": {"999": 5}}, 2, []
    )
    assert vector == [expected, expected]


# ---------------------------------------------------------------------------
# melee_vector_from_counts -- lower-level, no default-weapon fallback
# ---------------------------------------------------------------------------


def test_melee_vector_from_counts_zero_model_count_returns_empty():
    assert melee_vector_from_counts({1: 2}, {1: 5.0}, 0, mode_total=False) == []


def test_melee_vector_from_counts_empty_counts_returns_zeros_not_fallback():
    # No default-weapon fallback here -- an empty/zero counts map means the
    # unit truly carries no melee cost (mirrors role_totals.py's
    # _aggregate_weapon_buckets, which has no such fallback either).
    assert melee_vector_from_counts({}, {}, 3, mode_total=False) == [0.0, 0.0, 0.0]


def test_melee_vector_from_counts_per_model_combines_multiple_weapons():
    vector = melee_vector_from_counts(
        {1: 2, 2: 1}, {1: 3.0, 2: 4.0}, 3, mode_total=False
    )
    # per-model: (2 * 3.0) + (1 * 4.0) = 10.0, identical for every model.
    assert vector == [10.0, 10.0, 10.0]


def test_melee_vector_from_counts_total_mode_round_robin():
    vector = melee_vector_from_counts(
        {1: 3, 2: 2}, {1: 10.0, 2: 5.0}, 3, mode_total=True
    )
    # instances sorted desc: [10,10,10,5,5] -> round robin over 3 slots.
    assert vector == [15.0, 15.0, 10.0]


def test_melee_vector_from_counts_unknown_weapon_id_costs_zero():
    # weapon_id present in counts but missing from the cost map -> treated
    # as 0 cost rather than raising, so a caller's partial cost map (e.g.
    # lazily built for only some weapons) degrades gracefully.
    vector = melee_vector_from_counts({1: 2}, {}, 2, mode_total=False)
    assert vector == [0.0, 0.0]
