"""A3.2 — mistrzostwo abilities pod `OPR_RULES_BACKEND=yaml`.

Mirror `tests/test_mistrzostwo_costs.py` ale przez `calculate_roster_unit_quote`.
Pokrywa:
- Aura(N): mistrzostwo:<weapon_slug> handler (`_mistrzostwo_aura_cost × 8.0`,
  ×2.0 gdy aura_range=12)
- Rozkaz/Klatwa/Oznaczenie: mistrzostwo:<weapon_slug> handler
  (`_mistrzostwo_aura_cost × 10.0`)
- Slug `mistrzostwo` z value=<weapon_slug>: `_mistrzostwo_weapon_cost`
  (delta sum przez wszystkie bronie jednostki)
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "aura_flag",
    [
        "Aura(6): mistrzostwo:nieporeczny",
        "Aura(12): mistrzostwo:nieporeczny",
        "Aura(6): mistrzostwo:przebijajaca",
        "Aura(6): mistrzostwo:rozrywajacy",
        "Aura(6): mistrzostwo:brutalny",
        "Aura(6): mistrzostwo:lanca",
    ],
)
def test_aura_mistrzostwo_parity(
    make_unit, make_quote, assert_quote_parity, aura_flag
) -> None:
    unit = make_unit(flags=aura_flag, toughness=3)
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


@pytest.mark.parametrize(
    "order_flag",
    [
        "Rozkaz: mistrzostwo:nieporeczny",
        "Klatwa: mistrzostwo:przebijajaca",
        "Oznaczenie: mistrzostwo:brutalny",
    ],
)
def test_order_like_mistrzostwo_parity(
    make_unit, make_quote, assert_quote_parity, order_flag
) -> None:
    unit = make_unit(flags=order_flag, toughness=3)
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


@pytest.mark.parametrize(
    "weapon_slug,weapon_tags",
    [
        ("przebijajaca", ""),
        ("przebijajaca", "Brutalny"),
        ("rozrywajacy", ""),
        ("brutalny", "Przebijajaca"),
        ("lanca", ""),
        ("namierzanie", ""),
    ],
)
def test_mistrzostwo_slug_parity(
    make_unit, make_quote, assert_quote_parity, weapon_slug, weapon_tags
) -> None:
    """Slug `mistrzostwo(<weapon_slug>)` — yaml liczy delta sumę po broniach
    używając `_mistrzostwo_weapon_cost` z cost_functions."""
    unit = make_unit(
        flags=f"Mistrzostwo({weapon_slug})",
        weapon_kwargs={"range_": '24"', "ap": 1, "tags": weapon_tags},
    )
    proc, yaml = make_quote(unit, {}, count=3)
    assert_quote_parity(proc, yaml)
