"""Owner-scoped, agent-only API for read-only roster field scoring."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import AgentPrincipal, require_agent_scope
from ..services import roster_scoring as scoring_service
from ..services.agents.maps import MAP_BUILDERS
from ..services.roster_simulation import BATTLE_SIMULATION_BOTS

router = APIRouter(prefix="/rosters", tags=["rosters"])

ROSTER_SCORE_SCOPE = "roster:score"
MIN_SAFE_SEED = -(2**31)
MAX_SAFE_SEED = 2**31 - 1
MAX_SCORE_REQUEST_BYTES = 16 * 1024
_INVALID_REQUEST_DETAIL = "Invalid roster score request"
_WORKLOAD_DETAIL = (
    "Roster score workload exceeds limits; provide an explicit opponent subset"
)
_NOT_FOUND_DETAIL = "Roster not found"
_SCORING_FAILED_DETAIL = "Roster scoring failed"

PositiveRosterId = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
FiniteRate = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]


class ScoreListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    games_per_opponent: int = Field(
        3,
        strict=True,
        ge=1,
        le=scoring_service.MAX_SCORE_GAMES_PER_OPPONENT,
    )
    bot: str = Field("priority", min_length=1, max_length=40)
    seed: int = Field(0, strict=True, ge=MIN_SAFE_SEED, le=MAX_SAFE_SEED)
    map_name: str = Field("lustrzana_a", min_length=1, max_length=40)
    opponent_roster_ids: list[PositiveRosterId] | None = Field(
        default=None,
        max_length=scoring_service.MAX_SCORE_OPPONENTS,
    )

    @model_validator(mode="after")
    def validate_unique_opponents(self) -> ScoreListRequest:
        if self.opponent_roster_ids is not None and len(
            set(self.opponent_roster_ids)
        ) != len(self.opponent_roster_ids):
            raise ValueError("opponent_roster_ids must be unique")
        return self


class RosterInfoPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(..., strict=True, ge=1)
    name: str = Field(..., min_length=1, max_length=120)
    army: str = Field(..., min_length=1, max_length=120)
    points: float = Field(..., strict=True, ge=0.0, allow_inf_nan=False)
    composition: str = Field(
        ...,
        max_length=scoring_service.MAX_ROSTER_COMPOSITION_LENGTH,
    )


class ScoreParametersPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    games_per_opponent: int = Field(
        ...,
        strict=True,
        ge=1,
        le=scoring_service.MAX_SCORE_GAMES_PER_OPPONENT,
    )
    bot: str = Field(..., min_length=1, max_length=40)
    seed: int = Field(
        ...,
        strict=True,
        ge=MIN_SAFE_SEED,
        le=MAX_SAFE_SEED,
    )
    map_name: str = Field(..., min_length=1, max_length=40)
    opponent_roster_ids: list[PositiveRosterId] = Field(
        ...,
        max_length=scoring_service.MAX_SCORE_OPPONENTS,
    )


class OpponentScorePublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    opponent: RosterInfoPublic
    n: int = Field(
        ...,
        strict=True,
        ge=1,
        le=scoring_service.MAX_SCORE_GAMES_PER_OPPONENT,
    )
    wins: NonNegativeInt
    losses: NonNegativeInt
    draws: NonNegativeInt
    rounds: NonNegativeInt
    win_rate: FiniteRate
    loss_rate: FiniteRate
    draw_rate: FiniteRate
    avg_rounds: float = Field(..., strict=True, ge=0.0, allow_inf_nan=False)


class ScoreSummaryPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    n_opponents: int = Field(
        ...,
        strict=True,
        ge=0,
        le=scoring_service.MAX_SCORE_OPPONENTS,
    )
    n_games: int = Field(
        ...,
        strict=True,
        ge=0,
        le=scoring_service.MAX_SCORE_TOTAL_GAMES,
    )
    wins: NonNegativeInt
    losses: NonNegativeInt
    draws: NonNegativeInt
    rounds: NonNegativeInt
    win_rate: FiniteRate
    loss_rate: FiniteRate
    draw_rate: FiniteRate
    avg_rounds: float = Field(..., strict=True, ge=0.0, allow_inf_nan=False)


class CostSignalsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    vs_cheaper: ScoreSummaryPublic
    vs_pricier: ScoreSummaryPublic


class ScoreListPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", strict=True)

    payload_schema: Literal[scoring_service.SCORE_LIST_SCHEMA] = Field(alias="schema")
    version: Literal[scoring_service.SCORE_LIST_VERSION]
    target: RosterInfoPublic
    parameters: ScoreParametersPublic
    results: list[OpponentScorePublic] = Field(
        ...,
        max_length=scoring_service.MAX_SCORE_OPPONENTS,
    )
    aggregate: ScoreSummaryPublic
    cost_signals: CostSignalsPublic

    @model_validator(mode="after")
    def validate_result_envelope(self) -> ScoreListPublic:
        result_ids = [result.opponent.id for result in self.results]
        if result_ids != sorted(result_ids) or len(set(result_ids)) != len(result_ids):
            raise ValueError("score results must have unique ascending opponent IDs")
        if self.target.id in result_ids:
            raise ValueError("score results cannot include the target")
        if result_ids != self.parameters.opponent_roster_ids:
            raise ValueError("score parameters and result IDs differ")
        if self.aggregate.n_opponents != len(self.results):
            raise ValueError("score aggregate opponent count differs")
        return self


_REQUEST_OPENAPI = ScoreListRequest.model_json_schema()


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


async def _request_payload(request: Request) -> ScoreListRequest:
    try:
        raw_body = bytearray()
        async for chunk in request.stream():
            if len(raw_body) + len(chunk) > MAX_SCORE_REQUEST_BYTES:
                raise ValueError("score request body is too large")
            raw_body.extend(chunk)
        raw_payload = json.loads(
            bytes(raw_body).decode("utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
        )
        return ScoreListRequest.model_validate(raw_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        RecursionError,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INVALID_REQUEST_DETAIL,
        ) from None


def _validate_public_request(payload: ScoreListRequest, roster_id: int) -> None:
    opponent_ids = payload.opponent_roster_ids
    if opponent_ids is not None:
        if roster_id in opponent_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_INVALID_REQUEST_DETAIL,
            )
        if payload.games_per_opponent * len(opponent_ids) > (
            scoring_service.MAX_SCORE_TOTAL_GAMES
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_WORKLOAD_DETAIL,
            )
    if payload.bot.lower() not in BATTLE_SIMULATION_BOTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INVALID_REQUEST_DETAIL,
        )
    if payload.map_name.lower() not in MAP_BUILDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INVALID_REQUEST_DETAIL,
        )


@router.post(
    "/{roster_id:int}/score",
    response_model=ScoreListPublic,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _REQUEST_OPENAPI}},
        }
    },
)
async def score_roster(
    request: Request,
    roster_id: Annotated[int, Path(ge=1)],
    principal: AgentPrincipal = Depends(
        require_agent_scope(
            ROSTER_SCORE_SCOPE,
            audit_query_params=False,
            update_last_used_at=False,
        )
    ),
    db: Session = Depends(get_db),
) -> ScoreListPublic:
    """Score one owned roster against an owned, explicitly bounded field."""
    if request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INVALID_REQUEST_DETAIL,
        )
    payload = await _request_payload(request)
    _validate_public_request(payload, roster_id)
    try:
        target, results = scoring_service.score_list(
            db,
            roster_id,
            bot=payload.bot.lower(),
            n=payload.games_per_opponent,
            seed=payload.seed,
            map_name=payload.map_name.lower(),
            vs_ids=payload.opponent_roster_ids,
            owner_user_id=principal.owner_user_id,
            allowed_bots=BATTLE_SIMULATION_BOTS,
            max_opponents=scoring_service.MAX_SCORE_OPPONENTS,
            max_total_games=scoring_service.MAX_SCORE_TOTAL_GAMES,
        )
        projected = scoring_service.score_list_to_dict(
            target,
            results,
            games_per_opponent=payload.games_per_opponent,
            bot=payload.bot.lower(),
            seed=payload.seed,
            map_name=payload.map_name.lower(),
        )
        public = ScoreListPublic.model_validate(projected)
        strict_json = json.dumps(
            public.model_dump(by_alias=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
        return ScoreListPublic.model_validate_json(strict_json)
    except scoring_service.RosterNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        ) from None
    except scoring_service.ScoreWorkloadError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_WORKLOAD_DETAIL,
        ) from None
    except scoring_service.ScoreRequestError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_INVALID_REQUEST_DETAIL,
        ) from None
    except (
        scoring_service.ScoreSerializationError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        ValidationError,
        RecursionError,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_SCORING_FAILED_DETAIL,
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_SCORING_FAILED_DETAIL,
        ) from None
