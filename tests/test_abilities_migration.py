"""Faza A1 — exact match: abilities YAML vs `ABILITY_DEFINITIONS`.

Zabezpiecza, że `app/rulesets/v1/abilities.yaml` jest wierną kopią
87 definicji z `app/data/abilities.py`. Każde rozejście zatrzymuje
test i wskazuje slug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.data.abilities import ABILITY_DEFINITIONS, AbilityDefinition
from app.services.rulesets import load_ruleset


@pytest.fixture(scope="module")
def ruleset():
    return load_ruleset("v1")


@pytest.fixture(scope="module")
def abilities_by_slug(ruleset) -> dict:
    return {entry.slug: entry for entry in ruleset.abilities}


def test_count_matches_procedural(ruleset) -> None:
    assert len(ruleset.abilities) == len(ABILITY_DEFINITIONS)


def test_no_duplicate_slugs(ruleset) -> None:
    slugs = [entry.slug for entry in ruleset.abilities]
    assert len(slugs) == len(set(slugs)), "Duplicate slug in abilities.yaml"


def test_order_matches_procedural(ruleset) -> None:
    yaml_slugs = [entry.slug for entry in ruleset.abilities]
    proc_slugs = [d.slug for d in ABILITY_DEFINITIONS]
    assert yaml_slugs == proc_slugs


@pytest.mark.parametrize("ability_def", ABILITY_DEFINITIONS, ids=lambda d: d.slug)
def test_per_ability_exact_match(ability_def: AbilityDefinition, abilities_by_slug) -> None:
    """Pełna parametryzacja: jeden test per ability → łatwa identyfikacja regresji."""
    yaml_entry = abilities_by_slug.get(ability_def.slug)
    assert yaml_entry is not None, f"Brak slug {ability_def.slug!r} w abilities.yaml"

    assert yaml_entry.name == ability_def.name, ability_def.slug
    assert yaml_entry.type == ability_def.type, ability_def.slug
    assert yaml_entry.description == ability_def.description, ability_def.slug
    assert yaml_entry.value_label == ability_def.value_label, ability_def.slug
    assert yaml_entry.value_type == ability_def.value_type, ability_def.slug
    expected_choices = (
        tuple(ability_def.value_choices) if ability_def.value_choices is not None else None
    )
    assert yaml_entry.value_choices == expected_choices, ability_def.slug
