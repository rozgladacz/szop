"""A3.2 — passive ability costs pod `OPR_RULES_BACKEND=yaml`.

Mirror scenariuszy z `tests/test_passive_costs.py`, ale exerciszuje
**YAML backend** przez `calculate_roster_unit_quote`. Asercja:
- yaml działa jako samodzielny silnik (nie raise),
- yaml ≡ procedural (delta ≤ 1e-2) na każdym z passive scenariuszy.

`OPR_RULES_BACKEND=yaml` jest ustawiane przez `tests/yaml/conftest.py:_yaml_backend`.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "flags,toughness,count",
    [
        ("Nieustraszony", 2, 5),  # morale-multiplier
        ("Nieustraszony,Zwiadowca", 4, 3),  # morale + passive scale
        ("Zasadzka", 4, 3),
        ("Zwiadowca", 3, 5),
        ("Szybki", 2, 2),
        ("Wolny", 3, 4),
        ("Latajacy", 4, 1),
        ("Samolot", 9, 1),
        ("Harcownik", 3, 3),
        ("Tarcza", 4, 4),
        ("Regeneracja", 6, 2),
        ("Kontra,Maskowanie", 3, 5),
        ("Okopany", 2, 10),
        ("Instynkt", 2, 5),
        ("Roj", 1, 20),
        ("Zwrot", 3, 3),
        ("Cierpliwy", 3, 4),
        ("Zdobywca", 4, 1),
        ("Niezgrabny", 3, 4),
        ("Nieruchomy", 4, 3),
    ],
)
def test_passive_yaml_matches_procedural(
    make_unit, make_quote, assert_quote_parity, flags, toughness, count
) -> None:
    unit = make_unit(flags=flags, toughness=toughness)
    proc, yaml = make_quote(unit, {}, count=count)
    assert_quote_parity(proc, yaml)


def test_passive_morale_stack(make_unit, make_quote, assert_quote_parity) -> None:
    """Stack 3 morale-multipliers — yaml liczy `morale_multiplier *=` ten sam
    sposób co oracle (raz per slug, w pętli abilities)."""
    unit = make_unit(flags="Nieustraszony,Ucieczka,Stracency", toughness=3)
    proc, yaml = make_quote(unit, {}, count=2)
    assert_quote_parity(proc, yaml)


def test_passive_defense_stack(make_unit, make_quote, assert_quote_parity) -> None:
    """Defense-stack: `delikatny` + `niewrazliwy` — yaml dodaje delty per slug."""
    unit = make_unit(flags="Delikatny,Niewrazliwy", toughness=3, defense=4)
    proc, yaml = make_quote(unit, {}, count=3)
    assert_quote_parity(proc, yaml)


def test_passive_aura_returns_zero_when_aura_required(
    make_unit, make_quote, assert_quote_parity
) -> None:
    """`bastion` bez aury → 0 (aura_required=True). Yaml: scale_by_tou flagą."""
    unit = make_unit(flags="Bastion", toughness=4)
    proc, yaml = make_quote(unit, {}, count=2)
    assert_quote_parity(proc, yaml)


def test_passive_dywersant_aura_scale_flag(
    make_unit, make_quote, assert_quote_parity
) -> None:
    """`dywersant`: aura_scale=True — base bez mnożenia gdy aura=False (1.25),
    z mnożeniem gdy aura=True (1.25*tou). Tutaj testujemy passive standalone."""
    unit = make_unit(flags="Dywersant", toughness=5)
    proc, yaml = make_quote(unit, {}, count=2)
    assert_quote_parity(proc, yaml)
