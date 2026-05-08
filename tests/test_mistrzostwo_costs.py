from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services import costs
from app.services.costs.abilities import _mistrzostwo_aura_cost


def _weapon(
    range_value: str,
    attacks: float = 1.0,
    ap: int = 0,
    tags: str | None = None,
):
    return SimpleNamespace(
        effective_range=range_value,
        effective_attacks=attacks,
        effective_ap=ap,
        effective_tags=tags,
        effective_cached_cost=None,
    )


# ---------------------------------------------------------------------------
# _mistrzostwo_aura_cost – Nieporęczny only affects ranged weapons
# ---------------------------------------------------------------------------

def test_mistrzostwo_aura_cost_nieporeczny_uses_ranged_delta() -> None:
    delta_ranged = abs(
        costs._weapon_cost(4, 24, 1, 2, ["nieporeczny"], [])
        - costs._weapon_cost(4, 24, 1, 2, [], [])
    )
    delta_melee = abs(
        costs._weapon_cost(4, 0, 2, 2, ["nieporeczny"], [])
        - costs._weapon_cost(4, 0, 2, 2, [], [])
    )
    expected = max(delta_ranged, delta_melee)

    assert delta_ranged > 0, "Nieporęczny should reduce ranged weapon cost"
    assert delta_melee == pytest.approx(0.0), "Nieporęczny has no effect on melee weapons"
    assert _mistrzostwo_aura_cost("nieporeczny") == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Aura: Mistrzostwo(Nieporęczny) costs
# ---------------------------------------------------------------------------

def test_aura_mistrzostwo_nieporeczny_6inch_cost() -> None:
    base = _mistrzostwo_aura_cost("nieporeczny")
    result = costs.ability_cost_from_name("Aura", "mistrzostwo:nieporeczny|6")
    assert result == pytest.approx(base * 8.0)


def test_aura_mistrzostwo_nieporeczny_12inch_cost() -> None:
    base = _mistrzostwo_aura_cost("nieporeczny")
    result = costs.ability_cost_from_name("Aura", "mistrzostwo:nieporeczny|12")
    assert result == pytest.approx(base * 16.0)


# ---------------------------------------------------------------------------
# Rozkaz: Mistrzostwo(Nieporęczny) cost
# ---------------------------------------------------------------------------

def test_rozkaz_mistrzostwo_nieporeczny_cost() -> None:
    base = _mistrzostwo_aura_cost("nieporeczny")
    result = costs.ability_cost_from_name("Rozkaz", "mistrzostwo:nieporeczny")
    assert result == pytest.approx(base * 10.0)


# ---------------------------------------------------------------------------
# Passive Mistrzostwo(Nieporęczny) on a unit with weapons
# ---------------------------------------------------------------------------

def test_passive_mistrzostwo_nieporeczny_reduces_ranged_weapon_cost() -> None:
    ranged = _weapon('24"', attacks=2, ap=1)
    cost_with = costs.ability_cost_from_name(
        "Mistrzostwo", "nieporeczny", weapons=[ranged], quality=4
    )
    expected = abs(
        costs._weapon_cost(4, 24, 2, 1, ["nieporeczny"], [])
        - costs._weapon_cost(4, 24, 2, 1, [], [])
    )
    assert cost_with == pytest.approx(expected, abs=0.01)
    assert cost_with > 0


def test_passive_mistrzostwo_nieporeczny_no_effect_on_melee_only_unit() -> None:
    melee = _weapon("Melee", attacks=2, ap=1)
    cost = costs.ability_cost_from_name(
        "Mistrzostwo", "nieporeczny", weapons=[melee], quality=4
    )
    assert cost == pytest.approx(0.0, abs=0.01)


def test_passive_mistrzostwo_nieporeczny_sums_over_multiple_weapons() -> None:
    ranged1 = _weapon('24"', attacks=1, ap=0)
    ranged2 = _weapon('12"', attacks=2, ap=1)
    melee = _weapon("Melee", attacks=3, ap=2)

    delta1 = abs(
        costs._weapon_cost(4, 24, 1, 0, ["nieporeczny"], [])
        - costs._weapon_cost(4, 24, 1, 0, [], [])
    )
    delta2 = abs(
        costs._weapon_cost(4, 12, 2, 1, ["nieporeczny"], [])
        - costs._weapon_cost(4, 12, 2, 1, [], [])
    )
    delta3 = abs(
        costs._weapon_cost(4, 0, 3, 2, ["nieporeczny"], [])
        - costs._weapon_cost(4, 0, 3, 2, [], [])
    )
    expected = delta1 + delta2 + delta3

    result = costs.ability_cost_from_name(
        "Mistrzostwo", "nieporeczny", weapons=[ranged1, ranged2, melee], quality=4
    )
    assert result == pytest.approx(expected, abs=0.01)
