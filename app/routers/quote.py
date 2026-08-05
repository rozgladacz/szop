"""Publiczny, bezstanowy endpoint wyceny i manifest UI OPOS."""

from fastapi import APIRouter, HTTPException

from ..config import OPOS_RULESET_VERSION
from ..services.opos_rules import (
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    load_opos_ruleset,
)


router = APIRouter(tags=["rules"])


@router.get("/ruleset")
def ruleset_manifest() -> dict[str, object]:
    ruleset = load_opos_ruleset(OPOS_RULESET_VERSION)
    return {
        "version": ruleset.version,
        "standard_stats": ruleset.standard_stats.model_dump(mode="json"),
        "stat_descriptions": ruleset.stat_descriptions,
        "ranges": {
            slug: definition.model_dump(mode="json")
            for slug, definition in ruleset.ranges.items()
        },
        "stat_icons": ruleset.stat_icons,
        "abilities": [item.model_dump(mode="json") for item in ruleset.abilities],
    }


@router.post("/quote")
def quote_unit(payload: UnitQuoteInput) -> dict[str, object]:
    try:
        quote = calculate_unit_quote(payload, ruleset_version=OPOS_RULESET_VERSION)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return quote.model_dump(mode="json")
