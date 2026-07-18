"""Scoped read-only API for validating a global catalog unit loadout."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import AgentPrincipal, require_agent_scope
from ..services import loadout_validation as loadout_validation_service
from ..services.costs.errors import RulesetParityError

router = APIRouter(prefix="/units", tags=["units"])

LOADOUT_VALIDATE_SCOPE = "loadout:validate"
_INVALID_REQUEST_DETAIL = "Invalid loadout validation request"
_VALIDATION_FAILED_DETAIL = "Loadout validation failed"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class LoadoutValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    loadout: dict[str, Any]
    count: int = Field(1, strict=True, ge=1, le=100)


class ModePublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    raw: Any
    normalized: Literal["per_model", "total"]
    clamped: bool


class RejectedSelectionPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    reason: Literal["niedozwolone dla tej jednostki", "niepoprawne id"]


class ClampedSelectionPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    raw: Any
    normalized: NonNegativeInt


class SectionDiffPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section: Literal["weapons", "active", "aura"]
    accepted: dict[str, NonNegativeInt]
    rejected: list[RejectedSelectionPublic]
    clamped: list[ClampedSelectionPublic]


class PassiveDiffPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    accepted: dict[str, NonNegativeInt]
    rejected: list[str]


class CostComponentsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    active: float = Field(..., strict=True, allow_inf_nan=False)
    aura: float = Field(..., strict=True, allow_inf_nan=False)
    base: float = Field(..., strict=True, allow_inf_nan=False)
    passive: float = Field(..., strict=True, allow_inf_nan=False)
    weapon: float = Field(..., strict=True, allow_inf_nan=False)


class LoadoutCostPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_role: Literal["wojownik", "strzelec"] | None
    selected_total: float = Field(..., strict=True, ge=0.0, allow_inf_nan=False)
    components: CostComponentsPublic


class LoadoutValidationPublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", strict=True)

    payload_schema: Literal[
        loadout_validation_service.LOADOUT_VALIDATION_SCHEMA
    ] = Field(alias="schema")
    version: Literal[loadout_validation_service.LOADOUT_VALIDATION_VERSION]
    unit_id: int = Field(..., strict=True, ge=1)
    unit_name: str = Field(..., min_length=1, max_length=120)
    count: int = Field(..., strict=True, ge=1, le=100)
    mode: ModePublic
    sections: list[SectionDiffPublic] = Field(..., min_length=3, max_length=3)
    passive: PassiveDiffPublic
    cost: LoadoutCostPublic
    has_issues: bool

    @model_validator(mode="after")
    def validate_section_order(self) -> LoadoutValidationPublic:
        if [section.section for section in self.sections] != [
            "weapons",
            "active",
            "aura",
        ]:
            raise ValueError("loadout sections must have canonical order")
        return self


_REQUEST_OPENAPI = LoadoutValidationRequest.model_json_schema()


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


async def _request_payload(request: Request) -> LoadoutValidationRequest:
    try:
        raw_payload = json.loads(
            (await request.body()).decode("utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
        )
        return LoadoutValidationRequest.model_validate(raw_payload)
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


@router.post(
    "/{unit_id}/validate-loadout",
    response_model=LoadoutValidationPublic,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _REQUEST_OPENAPI}},
        }
    },
)
async def validate_loadout(
    request: Request,
    unit_id: Annotated[int, Path(ge=1)],
    _principal: AgentPrincipal = Depends(
        require_agent_scope(LOADOUT_VALIDATE_SCOPE)
    ),
    db: Session = Depends(get_db),
) -> LoadoutValidationPublic:
    """Validate and quote one loadout without persisting catalog or roster data."""
    payload = await _request_payload(request)
    try:
        diff = loadout_validation_service.validate_loadout_by_id(
            db,
            unit_id,
            payload.loadout,
            payload.count,
        )
        serialized = loadout_validation_service.diff_to_dict(diff)
        public = LoadoutValidationPublic.model_validate(serialized)
        strict_json = json.dumps(
            public.model_dump(by_alias=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
        return LoadoutValidationPublic.model_validate_json(strict_json)
    except loadout_validation_service.UnitNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found",
        ) from None
    except (
        loadout_validation_service.LoadoutSerializationError,
        RulesetParityError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        ValidationError,
        RecursionError,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_VALIDATION_FAILED_DETAIL,
        ) from None
