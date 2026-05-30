"""B0 — testy `app/rulesets/v1/b_mvp_exclusions.yaml` (ADR-0008).

Weryfikuje: parsing przez Pydantic (`BMvpExclusions`), liczność i set slugów
zgodny z user decision (6 hand-curated entries), helper `is_excluded()`,
sanity link do `abilities.yaml` (każdy slug obecny).
"""

from __future__ import annotations

from app.services.rulesets.loader import load_b_mvp_exclusions, load_ruleset
from app.services.rulesets.models import BMvpExclusions

# 6 hand-curated slugów z `b_mvp_exclusions.yaml` (user decision 2026-05-30).
EXPECTED_EXCLUDED_SLUGS = frozenset(
    {"samolot", "wrak", "wysoki", "zwrot", "sterowany", "zuzywalny"}
)


def test_load_returns_bmvp_exclusions():
    """Public entry point zwraca instancję BMvpExclusions."""
    excl = load_b_mvp_exclusions()
    assert isinstance(excl, BMvpExclusions)
    assert excl.version == 1


def test_exclusion_count():
    """Lista ma dokładnie 6 wpisów (Pareto MVP scope, ADR-0008)."""
    excl = load_b_mvp_exclusions()
    assert len(excl.excluded_abilities) == 6


def test_exclusion_slugs_match_expected():
    """Set slugów == EXPECTED_EXCLUDED_SLUGS."""
    excl = load_b_mvp_exclusions()
    assert excl.slugs() == EXPECTED_EXCLUDED_SLUGS


def test_exclusion_entries_have_metadata():
    """Każdy wpis ma niepuste reason + category."""
    excl = load_b_mvp_exclusions()
    for entry in excl.excluded_abilities:
        assert entry.reason, f"{entry.slug}: missing/empty reason"
        assert entry.category, f"{entry.slug}: missing/empty category"


def test_is_excluded_helper():
    """is_excluded(slug) → True dla wykluczonych, False dla pozostałych."""
    excl = load_b_mvp_exclusions()
    assert excl.is_excluded("zwrot") is True
    assert excl.is_excluded("samolot") is True
    assert excl.is_excluded("bohater") is False  # nie wykluczony
    assert excl.is_excluded("nieustraszony") is False  # standardowy passive
    assert excl.is_excluded("xxx-nonexistent") is False


def test_cache_returns_same_instance():
    """Drugi call do load_b_mvp_exclusions() zwraca cached instance (lru_cache)."""
    first = load_b_mvp_exclusions()
    second = load_b_mvp_exclusions()
    assert first is second


def test_excluded_slugs_present_in_abilities_yaml():
    """Sanity link: każdy slug z exclusion list istnieje w abilities.yaml.

    Wykrywa orphans (np. literówka w `b_mvp_exclusions.yaml` albo rename w
    `abilities.yaml` bez update tu).
    """
    excl_slugs = load_b_mvp_exclusions().slugs()
    ruleset_slugs = {a.slug for a in load_ruleset().abilities}
    missing = excl_slugs - ruleset_slugs
    assert not missing, (
        f"Exclusion slugs not in abilities.yaml: {missing}. "
        f"Update b_mvp_exclusions.yaml or rename in abilities.yaml."
    )


def test_categories_are_known():
    """Każda kategoria jest jedną z udokumentowanych w ADR-0008."""
    known_categories = {
        "ruch_specjalny",
        "terrain_generation",
        "los_niestandardowy",
        "orientacja",
        "tokeny_na_planszy",
        "session_state",
    }
    excl = load_b_mvp_exclusions()
    for entry in excl.excluded_abilities:
        assert entry.category in known_categories, (
            f"{entry.slug}: unknown category '{entry.category}'. "
            f"Update ADR-0008 lub b_mvp_exclusions.yaml."
        )


def test_frozen_immutable():
    """BMvpExclusions jest frozen — próba mutation rzuca błąd Pydantic."""
    excl = load_b_mvp_exclusions()
    try:
        excl.version = 2  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("BMvpExclusions should be frozen")
