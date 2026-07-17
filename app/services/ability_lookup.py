"""Stable read-only projection of the canonical ability catalog."""

from __future__ import annotations

from app.data import abilities as ability_catalog
from app.data.abilities import AbilityDefinition

ABILITY_EXPLANATION_SCHEMA = "szop.explain_ability/v1"
ABILITY_EXPLANATION_VERSION = 1
ABILITY_SOURCE = "app.data.abilities"
MAX_ABILITY_QUERY_LENGTH = 100


def resolve_ability(query: str) -> AbilityDefinition | None:
    """Resolve a canonical ability by slug or normalized Polish name."""
    slug = ability_catalog.slug_for_name(query)
    if slug is None:
        return None
    return ability_catalog.find_definition(slug)


def ability_to_json(definition: AbilityDefinition) -> dict:
    """Project one SSOT definition without duplicating catalog data."""
    return {
        **ability_catalog.to_dict(definition),
        "blocked": definition.blocked,
    }


def explain_ability_payload(query: str) -> dict | None:
    """Build the stable public response or return ``None`` for an unknown ability."""
    normalized_query = _validate_query(query)
    definition = resolve_ability(normalized_query)
    if definition is None:
        return None
    return {
        "schema": ABILITY_EXPLANATION_SCHEMA,
        "version": ABILITY_EXPLANATION_VERSION,
        "source": ABILITY_SOURCE,
        "query": normalized_query,
        "ability": ability_to_json(definition),
    }


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > MAX_ABILITY_QUERY_LENGTH:
        raise ValueError(
            f"query must contain at most {MAX_ABILITY_QUERY_LENGTH} characters"
        )
    return normalized
