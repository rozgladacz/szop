"""Public read-only endpoints for canonical rules and abilities."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from ..services.ability_lookup import (
    ABILITY_EXPLANATION_SCHEMA,
    ABILITY_EXPLANATION_VERSION,
    MAX_ABILITY_QUERY_LENGTH,
    explain_ability_payload,
)
from ..services.rule_lookup import (
    MAX_RULE_QUERY_LENGTH,
    MAX_RULE_RESULTS,
    RULE_LOOKUP_SCHEMA,
    RULE_LOOKUP_VERSION,
    lookup_rule_payload,
)

router = APIRouter(tags=["reference"])


class RuleContextPublic(BaseModel):
    ref: str
    text: str


class RuleMatchPublic(BaseModel):
    ref: str
    text: str
    parents: list[RuleContextPublic]
    children: list[RuleContextPublic]
    score: int | None


class RuleLookupPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payload_schema: Literal[RULE_LOOKUP_SCHEMA] = Field(alias="schema")
    version: Literal[RULE_LOOKUP_VERSION]
    source: str
    query: str
    normalized_query: str
    mode: Literal["reference", "search"]
    matches: list[RuleMatchPublic]


class AbilityPublic(BaseModel):
    slug: str
    name: str
    display_name: str
    type: str
    description: str
    value_label: str | None
    value_type: str | None
    requires_value: bool
    value_choices: list[str]
    blocked: bool


class AbilityExplanationPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payload_schema: Literal[ABILITY_EXPLANATION_SCHEMA] = Field(alias="schema")
    version: Literal[ABILITY_EXPLANATION_VERSION]
    source: str
    query: str
    ability: AbilityPublic


@router.get("/rules/lookup", response_model=RuleLookupPublic)
def lookup_rule(
    query: Annotated[
        str,
        Query(min_length=1, max_length=MAX_RULE_QUERY_LENGTH),
    ],
    limit: Annotated[int, Query(ge=1, le=MAX_RULE_RESULTS)] = 5,
) -> RuleLookupPublic:
    try:
        payload = lookup_rule_payload(query, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rules source unavailable",
        ) from None
    return RuleLookupPublic.model_validate(payload)


@router.get("/abilities/explain", response_model=AbilityExplanationPublic)
def explain_ability(
    query: Annotated[
        str,
        Query(min_length=1, max_length=MAX_ABILITY_QUERY_LENGTH),
    ],
) -> AbilityExplanationPublic:
    try:
        payload = explain_ability_payload(query)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ability not found",
        )
    return AbilityExplanationPublic.model_validate(payload)
