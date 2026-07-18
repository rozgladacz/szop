"""Public read-only endpoints for canonical rules and abilities."""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from mcp_server.embeddings import EmbeddingError
from mcp_server.search import (
    MAX_QUERY_LENGTH as MAX_RULE_SEARCH_QUERY_LENGTH,
    MAX_RESULTS as MAX_RULE_SEARCH_RESULTS,
    MAX_RESULT_TEXT_LENGTH,
    SearchError,
    hybrid_search,
)
from mcp_server.vector_store import VectorStoreError

from ..security import AgentPrincipal, require_agent_scope
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

RULES_SEARCH_SCOPE = "rules:search"
RULES_SEARCH_SCHEMA = "szop.search_rules/v1"
RULES_SEARCH_VERSION = 1
RULES_SEARCH_STRATEGY = "hybrid_weighted_rrf"

RuleSearchQuery = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_RULE_SEARCH_QUERY_LENGTH,
    ),
]
BoundedHeading = Annotated[str, StringConstraints(min_length=1, max_length=300)]
BoundedRef = Annotated[str, StringConstraints(min_length=1, max_length=64)]


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


class RulesSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: RuleSearchQuery
    limit: int = Field(5, strict=True, ge=1, le=MAX_RULE_SEARCH_RESULTS)


class RrfComponentPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(..., strict=True, ge=1, le=5)
    weight: float = Field(..., strict=True, gt=0.0, allow_inf_nan=False)
    contribution: float = Field(..., strict=True, gt=0.0, allow_inf_nan=False)


class RrfComponentsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bm25: RrfComponentPublic | None
    dense: RrfComponentPublic | None

    @model_validator(mode="after")
    def validate_fixed_weights(self) -> RrfComponentsPublic:
        if self.bm25 is None and self.dense is None:
            raise ValueError("at least one RRF component is required")
        if self.bm25 is not None and self.bm25.weight != 2.0:
            raise ValueError("BM25 RRF weight must match the fixed strategy")
        if self.dense is not None and self.dense.weight != 1.0:
            raise ValueError("dense RRF weight must match the fixed strategy")
        return self


class RulesSearchResultPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(..., strict=True, ge=1, le=MAX_RULE_SEARCH_RESULTS)
    chunk_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    source: Literal["SZOP_Rozjemca.md", "SZOP_Zdolnosci.md"]
    headings: list[BoundedHeading] = Field(..., max_length=12)
    refs: list[BoundedRef] = Field(..., max_length=64)
    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_RESULT_TEXT_LENGTH),
    ]
    score: float = Field(..., strict=True, gt=0.0, allow_inf_nan=False)
    components: RrfComponentsPublic


class RulesSearchPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    payload_schema: Literal[RULES_SEARCH_SCHEMA] = Field(alias="schema")
    version: Literal[RULES_SEARCH_VERSION]
    query: RuleSearchQuery
    strategy: Literal[RULES_SEARCH_STRATEGY]
    count: int = Field(..., strict=True, ge=0, le=MAX_RULE_SEARCH_RESULTS)
    results: list[RulesSearchResultPublic] = Field(
        ...,
        max_length=MAX_RULE_SEARCH_RESULTS,
    )

    @model_validator(mode="after")
    def validate_result_envelope(self) -> RulesSearchPublic:
        if self.count != len(self.results):
            raise ValueError("count must match results")
        if [result.rank for result in self.results] != list(
            range(1, self.count + 1)
        ):
            raise ValueError("result ranks must be contiguous")
        if len({result.chunk_id for result in self.results}) != self.count:
            raise ValueError("result chunk IDs must be unique")
        return self


_RULES_SEARCH_REQUEST_OPENAPI = RulesSearchRequest.model_json_schema()


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


@router.post(
    "/rules/search",
    response_model=RulesSearchPublic,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": _RULES_SEARCH_REQUEST_OPENAPI}
            },
        }
    },
)
def search_rules(
    raw_payload: Annotated[Any, Body()],
    _principal: AgentPrincipal = Depends(require_agent_scope(RULES_SEARCH_SCOPE)),
) -> RulesSearchPublic:
    """Run the fixed hybrid rules retrieval through the agent-only API."""
    try:
        payload = RulesSearchRequest.model_validate(raw_payload)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid rules search request",
        ) from None
    try:
        results = hybrid_search(payload.query, payload.limit)
        strict_json = json.dumps(
            {
                "schema": RULES_SEARCH_SCHEMA,
                "version": RULES_SEARCH_VERSION,
                "query": payload.query,
                "strategy": RULES_SEARCH_STRATEGY,
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
        return RulesSearchPublic.model_validate_json(strict_json)
    except (
        ImportError,
        OSError,
        sqlite3.Error,
        EmbeddingError,
        VectorStoreError,
        SearchError,
        ValidationError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rules search unavailable",
        ) from None
