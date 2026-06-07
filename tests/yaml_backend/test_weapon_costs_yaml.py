"""A3.2 — weapon costs pod `OPR_RULES_BACKEND=yaml`.

Mirror `tests/test_weapon_costs.py` ale przez `calculate_roster_unit_quote`.
Pokrycie weapon trait combinations + role interactions (Wojownik redukuje
ranged, Strzelec redukuje melee).
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "range_,attacks,ap,tags,unit_flags",
    [
        ('18"', 1.0, 1, "", ""),
        ('24"', 1.0, 1, "", ""),
        ("Melee", 2.0, 1, "", ""),
        ('30"', 1.0, 2, "Przebijajaca", ""),
        ('36"', 1.0, 2, "Artyleria", ""),
        ('24"', 1.0, 1, "Rozprysk(3)", ""),
        ('24"', 1.0, 1, "Zabojczy(2)", ""),
        ('24"', 1.0, 1, "Szturmowy", ""),
        ('24"', 1.0, 1, "Lanca", ""),
        ('24"', 1.0, 1, "Niezawodny", ""),
        ('24"', 1.0, 1, "Namierzanie", ""),
        ('24"', 1.0, 1, "Brutalny, Przebijajaca", ""),
        ('24"', 1.0, 1, "Finezja", ""),
        ('24"', 1.0, 1, "Podkrecenie", ""),
        # Role x weapon
        ('24"', 1.0, 1, "", "Wojownik"),
        ('24"', 1.0, 1, "", "Strzelec"),
        ("Melee", 2.0, 1, "", "Wojownik"),
        ("Melee", 2.0, 1, "", "Strzelec"),
    ],
)
def test_weapon_cost_parity(
    make_unit, make_quote, assert_quote_parity, range_, attacks, ap, tags, unit_flags
) -> None:
    unit = make_unit(
        flags=unit_flags,
        weapon_kwargs={"range_": range_, "attacks": attacks, "ap": ap, "tags": tags},
    )
    proc, yaml = make_quote(unit, {}, count=3)
    assert_quote_parity(proc, yaml)


@pytest.mark.parametrize(
    "unit_flags,range_,ap,tags",
    [
        ("Niestrudzony", '24"', 1, ""),
        ("Niestrudzony,Przygotowanie", '24"', 1, ""),
        ("Straznik", '24"', 1, ""),  # ranged ×1.7
        ("Bastion", "Melee", 1, ""),  # melee ×1.2
        ("Szpica", '24"', 1, ""),
        ("Ostrozny", '24"', 1, ""),
        ("Zle_strzela", '24"', 1, ""),  # q→5
        ("Dobrze_strzela", '24"', 1, ""),  # q→4
        ("Zemsta", '24"', 1, ""),
        ("Rezerwa", '24"', 1, ""),
        ("Zasadzka", '24"', 1, ""),
        ("Odwody", '24"', 1, ""),  # ×0.75 gdy brak rezerwa/zwiadowca/zasadzka
    ],
)
def test_weapon_unit_trait_interactions(
    make_unit, make_quote, assert_quote_parity, unit_flags, range_, ap, tags
) -> None:
    unit = make_unit(
        flags=unit_flags,
        weapon_kwargs={"range_": range_, "ap": ap, "tags": tags},
    )
    proc, yaml = make_quote(unit, {}, count=3)
    assert_quote_parity(proc, yaml)


def test_waagh_penalty_on_high_ap(
    make_unit, make_quote, assert_quote_parity
) -> None:
    """Waagh: ap_mod redukowane przez waagh_ap_modifier lookup."""
    unit = make_unit(
        flags="Waagh",
        toughness=3,
        weapon_kwargs={"range_": '24"', "ap": 4, "tags": ""},
    )
    proc, yaml = make_quote(unit, {}, count=5)
    assert_quote_parity(proc, yaml)


def test_loadout_per_model_weapons(
    make_unit, make_quote, assert_quote_parity
) -> None:
    """Mode per_model: weapon count × model_count."""
    unit = make_unit(flags="Wojownik")
    proc, yaml = make_quote(unit, {"mode": "per_model", "weapons": {"101": 1}}, count=4)
    assert_quote_parity(proc, yaml)


def test_loadout_total_weapons(make_unit, make_quote, assert_quote_parity) -> None:
    """Mode total: weapon count stosowana raz (nie × model_count)."""
    unit = make_unit(flags="Wojownik")
    proc, yaml = make_quote(unit, {"mode": "total", "weapons": {"101": 3}}, count=4)
    assert_quote_parity(proc, yaml)
