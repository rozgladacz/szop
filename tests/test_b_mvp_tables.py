"""B0 — testy sekcji `b_mvp` w `app/rulesets/v1/tables.yaml` (ADR-0008).

Weryfikuje: parsing przez Pydantic (`BMvpConfig`), wartości z `SZOP_Rozjemca.md`
(move_inches = 6 z pkt 15.a), sanity wzoru radius `sqrt(sum(toughness)/pi)`.
"""

from __future__ import annotations

import math

from app.services.rulesets.loader import load_ruleset
from app.services.rulesets.models import BMvpConfig


def test_b_mvp_section_present():
    """RulesetTables ma populated `b_mvp` po YAML load."""
    ruleset = load_ruleset()
    assert ruleset.tables.b_mvp is not None
    assert isinstance(ruleset.tables.b_mvp, BMvpConfig)


def test_b_mvp_move_inches():
    """Globalny ruch z SZOP_Rozjemca pkt 15.a = 6"."""
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    assert cfg.move_inches == 6


def test_b_mvp_base_area():
    """Podstawka modelu = 1 in² na punkt wytrzymałości (założenie Pareto MVP)."""
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    assert cfg.base_area_inches_sq_per_toughness == 1


def test_b_mvp_pi_approx():
    """pi_approx ≈ math.pi (deklaratywny, użyty w compute_radius)."""
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    assert math.isclose(cfg.pi_approx, math.pi, rel_tol=1e-9)


def test_b_mvp_radius_homogeneous_unit():
    """Oddział 5 modeli toughness 3 → radius = sqrt(15/pi) ≈ 2.1851...

    Wzór: powierzchnia = N * toughness * base_area; radius = sqrt(area/pi).
    """
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    models_count = 5
    toughness = 3
    area = models_count * toughness * cfg.base_area_inches_sq_per_toughness
    radius = math.sqrt(area / cfg.pi_approx)
    assert math.isclose(radius, math.sqrt(15 / math.pi), rel_tol=1e-9)
    assert math.isclose(radius, 2.1851, abs_tol=1e-3)


def test_b_mvp_radius_with_hero():
    """Oddział z Bohaterem (toughness/2): 1 zwykły T3 + 1 hero T6.

    Area = 3 + (6/2) = 6 → radius = sqrt(6/pi) ≈ 1.3820.
    Wynika z opisu zdolności Bohater (id 2): "rozmiar... 2 razy mniejszą wytrzymałość".
    """
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    plain_area = 3 * cfg.base_area_inches_sq_per_toughness
    hero_area = (6 / 2) * cfg.base_area_inches_sq_per_toughness
    total_area = plain_area + hero_area
    radius = math.sqrt(total_area / cfg.pi_approx)
    assert math.isclose(radius, math.sqrt(6 / math.pi), rel_tol=1e-9)
    assert math.isclose(radius, 1.3820, abs_tol=1e-3)


def test_b_mvp_frozen_immutable():
    """BMvpConfig jest frozen — próba mutation rzuca błąd Pydantic."""
    cfg = load_ruleset().tables.b_mvp
    assert cfg is not None
    try:
        cfg.move_inches = 12  # type: ignore[misc]
    except Exception:
        return  # expected — frozen
    raise AssertionError("BMvpConfig should be frozen")
