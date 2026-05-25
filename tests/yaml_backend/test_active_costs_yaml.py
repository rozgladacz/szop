"""A3.2 — active/aura/spell ability costs pod `OPR_RULES_BACKEND=yaml`.

Mirror `tests/test_active_costs.py` ale przez `calculate_roster_unit_quote`.
Pokrywa fixed_by_slug, fixed_by_desc i handlery (mag/aura/order_like).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _ability(name: str, ability_type: str = "active", cost_hint=None, config_json=None):
    return SimpleNamespace(
        id=hash(name) & 0xFFFF,
        name=name,
        type=ability_type,
        description="",
        cost_hint=cost_hint,
        config_json=config_json,
    )


def _ability_link(ability, params_json=None):
    return SimpleNamespace(ability=ability, params_json=params_json, unit=None)


@pytest.mark.parametrize(
    "flags,count",
    [
        # Fixed by slug: latanie=20, mobilizacja=30, przepowiednia=45,
        # presja=45, usprawnienie=45, ociezalosc=20, meczennik=5
        ("Latanie", 1),
        ("Mobilizacja", 1),
        ("Ociezalosc", 1),
        ("Meczennik", 2),
        # Fixed by desc: przekaznik=4, koordynacja=45, radio=3, spaczenie=30
        ("Przekaznik", 1),
        ("Koordynacja", 1),
    ],
)
def test_active_fixed_costs_parity(
    make_unit, make_quote, assert_quote_parity, flags, count
) -> None:
    unit = make_unit(flags=flags)
    proc, yaml = make_quote(unit, {}, count=count)
    assert_quote_parity(proc, yaml)


@pytest.mark.parametrize(
    "aura_flag,toughness",
    [
        ("Aura(6): Bastion", 3),
        ("Aura(12): Bastion", 3),
        ("Aura(6): Niestrudzony", 4),
        ("Aura(12): Niestrudzony", 4),
        ("Aura(6): Furia", 3),
        ("Aura(6): Niewrazliwy", 4),
        ("Aura(6): Dywersant", 4),
        ("Aura(6): Przygotowanie", 4),
        ("Aura(6): Ostrozny", 3),
    ],
)
def test_aura_handler_parity(
    make_unit, make_quote, assert_quote_parity, aura_flag, toughness
) -> None:
    unit = make_unit(flags=aura_flag, toughness=toughness)
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


@pytest.mark.parametrize("mag_flag", ["Mag(1)", "Mag(2)", "Mag(3)"])
def test_mag_handler_parity(
    make_unit, make_quote, assert_quote_parity, mag_flag
) -> None:
    """Mag(N) handler: base_multiplier × N = 8.0 × N."""
    unit = make_unit(flags=mag_flag)
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


def test_order_like_ability_with_target_passive(
    make_unit, make_quote, assert_quote_parity
) -> None:
    """Rozkaz/Klątwa/Oznaczenie handler — target = passive ability slug."""
    unit = make_unit(flags="Rozkaz: Wolny")
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


def test_order_like_klatwa_with_target_passive(
    make_unit, make_quote, assert_quote_parity
) -> None:
    unit = make_unit(flags="Klatwa: Nieruchomy")
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)


def test_order_like_oznaczenie_with_target_passive(
    make_unit, make_quote, assert_quote_parity
) -> None:
    unit = make_unit(flags="Oznaczenie: Delikatny", toughness=3, defense=3)
    proc, yaml = make_quote(unit, {}, count=1)
    assert_quote_parity(proc, yaml)
