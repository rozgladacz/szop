from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, StreamingResponse

from .. import models
from ..battle_protocol import (
    ACTIVATION_PROTOCOL_VERSION_V1,
    ACTIVATION_PROTOCOL_VERSION_V2,
    validate_activation_protocol_version,
)
from ..db import get_db
from ..security import get_current_user, require_agent_scope
from ..services import battle_activations as battle_activation_service
from ..services import battle_invites as battle_invite_service
from ..services import battle_replay as battle_replay_service
from ..services.agents.maps import DEFAULT_DEPLOYMENT_ZONES, build_map
from ..services.agents.roster_adapter import AdaptResult
from ..services.battle_creation import stage_battle_creation
from ..services.battle_event_stream import (
    session_factory_from_session,
    stream_battle_events,
)
from ..services.battle_actions import (
    BattleActionForbidden,
    BattleActionInvalid,
    BattleActionNotFound,
    BattleActionSequenceConflict,
    BattleActionUnavailable,
    get_participant_battle,
    stage_battle_action,
)
from ..services.engine.activation_protocol import ActivationProtocolErrorReason
from ..services.engine.events import BattleEvent as EngineBattleEvent
from ..services.engine.events import event_to_json
from ..services.engine.persistence import (
    BattleCheckpointSequenceConflict,
    BattleEventSequenceConflict,
    latest_event_sequence,
    load_events,
    load_latest_checkpoint,
)
from ..services.engine.state_codec import battle_state_to_json
from ..services.roster_simulation import (
    BATTLE_SIMULATION_BOTS,
    MAX_PUBLIC_SIMULATION_GAMES,
    simulate_roster_pair,
    simulation_players,
)


def _protocol_validation_error_code(
    *,
    path: str,
    body: Any,
    errors: list[dict[str, Any]],
) -> str | None:
    if path.endswith("/activations"):
        return "invalid_selection"
    if path.endswith("/interrupts"):
        return "illegal_interrupt"
    if path.endswith("/activations/{activation_id}/transitions"):
        if isinstance(body, dict) and body.get("operation") == "finalize":
            if any("recovery" in error.get("loc", ()) for error in errors):
                return "illegal_recovery"
        return "invalid_phase"
    if not path.endswith("/actions") or not isinstance(body, dict):
        return None

    guard_fields = {"activation_id", "expected_activation_version"}
    present_guards = guard_fields & set(body)
    if not present_guards:
        return None
    if present_guards != guard_fields or any(
        guard_fields & set(error.get("loc", ())) for error in errors
    ):
        return "activation_guard_required"
    return "illegal_action"


class BattleProtocolRoute(APIRoute):
    """Keep v2 auth/recovery errors closed without changing legacy v1 errors."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def protocol_route_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                code = _protocol_validation_error_code(
                    path=self.path,
                    body=exc.body,
                    errors=exc.errors(),
                )
                if code is not None:
                    return JSONResponse(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        content={"detail": {"code": code}},
                    )
                raise
            except HTTPException as exc:
                if exc.status_code not in {
                    status.HTTP_401_UNAUTHORIZED,
                    status.HTTP_403_FORBIDDEN,
                }:
                    raise
                is_protocol_request = (
                    self.path.endswith("/activations")
                    or self.path.endswith("/interrupts")
                    or self.path.endswith(
                        "/activations/{activation_id}/transitions"
                    )
                )
                if self.path.endswith("/actions"):
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    is_protocol_request = isinstance(body, dict) and bool(
                        {"activation_id", "expected_activation_version"} & set(body)
                    )
                if not is_protocol_request:
                    raise
                code = (
                    "unauthorized"
                    if exc.status_code == status.HTTP_401_UNAUTHORIZED
                    else "forbidden"
                )
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": {"code": code}},
                    headers=exc.headers,
                )

        return protocol_route_handler


router = APIRouter(
    prefix="/battles",
    tags=["battles"],
    route_class=BattleProtocolRoute,
)

BATTLE_CREATE_SCOPE = "battle:create"
BATTLE_INVITE_SCOPE = "battle:invite"
BATTLE_ACCEPT_SCOPE = "battle:accept"
BATTLE_READ_SCOPE = "battle:read"
BATTLE_ACT_SCOPE = "battle:act"
BATTLE_INTERRUPT_SCOPE = "battle:interrupt"
BATTLE_SIMULATE_SCOPE = "battle:simulate"
MAX_SIMULATION_GAMES = MAX_PUBLIC_SIMULATION_GAMES
_MAX_EVENT_CURSOR = (1 << 63) - 1
_MAX_INVITE_ACCEPT_ATTEMPTS = 3
_INVITE_ACCEPT_CONFLICT_DETAIL = "Battle invite could not be accepted"


@dataclass(frozen=True)
class BattleCreator:
    user_id: int


@dataclass(frozen=True)
class BattleInviter:
    user_id: int


@dataclass(frozen=True)
class BattleAcceptor:
    user_id: int
    session_user_is_agent: bool = False


@dataclass(frozen=True)
class BattleReader:
    user_id: int


@dataclass(frozen=True)
class BattleActor:
    user_id: int


@dataclass(frozen=True)
class BattleInterrupter:
    user_id: int


@dataclass(frozen=True)
class BattleSimulator:
    user_id: int


class BattleCreate(BaseModel):
    p1_roster_id: int = Field(..., ge=1)
    p2_roster_id: int = Field(..., ge=1)
    rng_seed: int = 0
    initiative_player: int = Field(0, ge=0, le=1)
    activation_protocol_version: int = Field(
        ACTIVATION_PROTOCOL_VERSION_V1,
        strict=True,
    )

    @field_validator("activation_protocol_version")
    @classmethod
    def validate_protocol_version(cls, value: object) -> int:
        return validate_activation_protocol_version(value)


class BattleInviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    to_user_id: int | None = Field(None, strict=True, ge=1)
    roster_id: int = Field(..., strict=True, ge=1)
    scenario: str = Field(
        "lustrzana_a",
        strict=True,
        min_length=1,
        max_length=100,
    )
    expires_in_hours: int = Field(24, strict=True, ge=1, le=168)
    activation_protocol_version: int = Field(
        ACTIVATION_PROTOCOL_VERSION_V1,
        strict=True,
    )

    @field_validator("scenario", mode="before")
    @classmethod
    def canonicalize_scenario(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("activation_protocol_version")
    @classmethod
    def validate_protocol_version(cls, value: object) -> int:
        return validate_activation_protocol_version(value)


class BattleInvitePublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(..., strict=True, ge=1)
    from_user_id: int = Field(..., strict=True, ge=1)
    to_user_id: int | None = Field(None, strict=True, ge=1)
    roster_id: int = Field(..., strict=True, ge=1)
    scenario: str = Field(..., min_length=1, max_length=100)
    status: Literal["pending"]
    activation_protocol_version: int = Field(..., strict=True)
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class BattleInviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    roster_id: int = Field(..., strict=True, ge=1)


class BattleSimulate(BaseModel):
    p1_roster_id: int = Field(..., ge=1)
    p2_roster_id: int = Field(..., ge=1)
    games: int = Field(10, ge=1, le=MAX_SIMULATION_GAMES)
    bot: str = "priority"
    seed: int = 0
    map_name: str = "lustrzana_a"


class BattleEventPublic(BaseModel):
    sequence: int = Field(..., ge=1)
    event_type: str
    payload: dict[str, Any]


class BattleEventsPublic(BaseModel):
    battle_id: int
    events: list[BattleEventPublic]


class BattleStatePublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    checkpoint_schema: str = Field(..., alias="schema")
    version: int = Field(..., ge=1)
    battle_id: int
    sequence_at: int = Field(..., ge=0)
    state: dict[str, Any]


class BattleStateWirePublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    checkpoint_schema: str = Field(..., alias="schema")
    version: int = Field(..., ge=1)
    state: dict[str, Any]


class BattleReplayPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    battle_id: int = Field(..., strict=True, ge=1)
    base_sequence: int = Field(..., strict=True, ge=0)
    replayed_through_sequence: int = Field(..., strict=True, ge=0)
    event_count: int = Field(
        ...,
        strict=True,
        ge=0,
        le=battle_replay_service.MAX_REPLAY_EVENTS,
    )
    verified_against_checkpoint: Literal[True]
    state: BattleStateWirePublic


class BattleActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_sequence: int = Field(..., ge=0, strict=True)
    activation_id: int | None = Field(None, ge=1, strict=True)
    expected_activation_version: int | None = Field(None, ge=1, strict=True)
    action: dict[str, Any]


class BattleActivationStartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_sequence: int = Field(..., ge=0, strict=True)
    selected_unit_id: int = Field(..., ge=0, strict=True)


class BattleActivationInterruptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["interrupt"]
    expected_sequence: int = Field(..., ge=0, strict=True)
    activation_id: int = Field(..., ge=1, strict=True)
    expected_activation_version: int = Field(..., ge=1, strict=True)
    expected_window_version: int = Field(..., ge=1, strict=True)
    source_unit_id: int = Field(..., ge=0, strict=True)
    ability_slug: str = Field(..., min_length=1, strict=True)
    payload: dict[str, Any]


class BattleActivationPassCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["pass"]
    expected_sequence: int = Field(..., ge=0, strict=True)
    activation_id: int = Field(..., ge=1, strict=True)
    expected_activation_version: int = Field(..., ge=1, strict=True)
    expected_window_version: int = Field(..., ge=1, strict=True)


BattleActivationInterruptOperation = Annotated[
    BattleActivationInterruptCreate | BattleActivationPassCreate,
    Field(discriminator="operation"),
]


class BattleActivationRecoveryUse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_unit_id: int = Field(..., ge=0, strict=True)
    ability_slug: str = Field(..., min_length=1, strict=True)
    payload: dict[str, Any]


class BattleActivationRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    uses: list[BattleActivationRecoveryUse]


class BattleActivationContinueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["continue"]
    expected_sequence: int = Field(..., ge=0, strict=True)
    expected_activation_version: int = Field(..., ge=1, strict=True)


class BattleActivationFinalizeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["finalize"]
    expected_sequence: int = Field(..., ge=0, strict=True)
    expected_activation_version: int = Field(..., ge=1, strict=True)
    recovery: BattleActivationRecovery


BattleActivationTransitionCreate = Annotated[
    BattleActivationContinueCreate | BattleActivationFinalizeCreate,
    Field(discriminator="operation"),
]


class BattleActionPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    battle_id: int
    previous_sequence: int = Field(..., ge=0)
    new_sequence: int = Field(..., ge=0)
    state: BattleStateWirePublic
    events: list[BattleEventPublic]


class RosterAdaptationPublic(BaseModel):
    dropped_excluded: list[str] = Field(default_factory=list)
    inert_incomplete: list[str] = Field(default_factory=list)
    deferred_attached_heroes: list[int] = Field(default_factory=list)


class BattleAdaptationPublic(BaseModel):
    p1: RosterAdaptationPublic
    p2: RosterAdaptationPublic


class BattlePublic(BaseModel):
    battle_id: int
    p1_user_id: int | None
    p2_user_id: int | None
    p1_roster_id: int | None
    p2_roster_id: int | None
    winner_user_id: int | None
    current_round: int = Field(..., ge=0)
    rng_seed: int
    status: str
    activation_protocol_version: int = Field(..., strict=True)
    latest_sequence: int = Field(..., ge=0)
    adaptation_report: BattleAdaptationPublic | None = None


class BattleSimulationPublic(BaseModel):
    p1_roster_id: int
    p2_roster_id: int
    bot: str
    map_name: str
    n_games: int = Field(..., ge=1)
    wins_p0: int = Field(..., ge=0)
    wins_p1: int = Field(..., ge=0)
    draws: int = Field(..., ge=0)
    total_rounds: int = Field(..., ge=0)
    win_rate_p0: float
    win_rate_p1: float
    draw_rate: float
    avg_rounds: float


def _authorization_header(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if value is None:
        value = request.headers.get("Authorization")
    return value


def _has_authorization_header(request: Request) -> bool:
    value = _authorization_header(request)
    return bool(value and value.strip())


def _authorized_owner_user_id(
    *,
    request: Request,
    db: Session,
    current_user: models.User | None,
    agent_scope: str,
) -> int:
    if _has_authorization_header(request):
        principal = require_agent_scope(agent_scope)(request=request, db=db)
        return principal.owner_user_id

    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return current_user.id


def _battle_creator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleCreator:
    return BattleCreator(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_CREATE_SCOPE,
        )
    )


def _battle_inviter(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleInviter:
    return BattleInviter(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_INVITE_SCOPE,
        )
    )


def _battle_acceptor(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleAcceptor:
    if _has_authorization_header(request):
        principal = require_agent_scope(BATTLE_ACCEPT_SCOPE)(request=request, db=db)
        return BattleAcceptor(user_id=principal.owner_user_id)
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return BattleAcceptor(
        user_id=current_user.id,
        session_user_is_agent=current_user.role == models.USER_ROLE_AGENT,
    )


def _battle_reader(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleReader:
    return BattleReader(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_READ_SCOPE,
        )
    )


def _battle_actor(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleActor:
    return BattleActor(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_ACT_SCOPE,
        )
    )


def _battle_interrupter(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleInterrupter:
    return BattleInterrupter(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_INTERRUPT_SCOPE,
        )
    )


def _battle_simulator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleSimulator:
    return BattleSimulator(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_SIMULATE_SCOPE,
        )
    )


def _get_accessible_battle(
    db: Session, *, battle_id: int, reader: BattleReader | BattleActor
) -> models.Battle:
    try:
        return get_participant_battle(
            db,
            battle_id=battle_id,
            user_id=reader.user_id,
        )
    except BattleActionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _get_owned_roster(
    db: Session, *, roster_id: int, owner_user_id: int
) -> models.Roster:
    roster = db.execute(
        select(models.Roster).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == owner_user_id,
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return roster


def _public_event(event: EngineBattleEvent) -> BattleEventPublic:
    payload = event_to_json(event)
    return BattleEventPublic(
        sequence=int(payload["sequence"]),
        event_type=str(payload["event_type"]),
        payload=payload,
    )


def _public_event_payload(event: EngineBattleEvent) -> dict[str, Any]:
    return _public_event(event).model_dump()


_ACTIVATION_NOT_FOUND_ERRORS = (
    battle_activation_service.BattleActivationStartNotFound,
    battle_activation_service.BattleActivationPassNotFound,
    battle_activation_service.BattleActivationInterruptNotFound,
    battle_activation_service.BattleActivationActionNotFound,
    battle_activation_service.BattleActivationContinueNotFound,
    battle_activation_service.BattleActivationFinalizeNotFound,
)
_ACTIVATION_UPGRADE_ERRORS = (
    battle_activation_service.BattleActivationStartUpgradeRequired,
    battle_activation_service.BattleActivationPassUpgradeRequired,
    battle_activation_service.BattleActivationInterruptUpgradeRequired,
    battle_activation_service.BattleActivationActionUpgradeRequired,
    battle_activation_service.BattleActivationContinueUpgradeRequired,
    battle_activation_service.BattleActivationFinalizeUpgradeRequired,
)
_ACTIVATION_SEQUENCE_ERRORS = (
    battle_activation_service.BattleActivationStartSequenceConflict,
    battle_activation_service.BattleActivationPassSequenceConflict,
    battle_activation_service.BattleActivationInterruptSequenceConflict,
    battle_activation_service.BattleActivationActionSequenceConflict,
    battle_activation_service.BattleActivationContinueSequenceConflict,
    battle_activation_service.BattleActivationFinalizeSequenceConflict,
)
_ACTIVATION_FORBIDDEN_ERRORS = (
    battle_activation_service.BattleActivationStartForbidden,
    battle_activation_service.BattleActivationInterruptForbidden,
    battle_activation_service.BattleActivationActionForbidden,
    battle_activation_service.BattleActivationContinueForbidden,
    battle_activation_service.BattleActivationFinalizeForbidden,
)
_ACTIVATION_UNAVAILABLE_ERRORS = (
    battle_activation_service.BattleActivationStartUnavailable,
    battle_activation_service.BattleActivationPassUnavailable,
    battle_activation_service.BattleActivationInterruptUnavailable,
    battle_activation_service.BattleActivationActionUnavailable,
    battle_activation_service.BattleActivationContinueUnavailable,
    battle_activation_service.BattleActivationFinalizeUnavailable,
)
_ACTIVATION_WRITE_ERRORS = (
    battle_activation_service.BattleActivationStartWriteConflict,
    battle_activation_service.BattleActivationPassWriteConflict,
    battle_activation_service.BattleActivationInterruptWriteConflict,
    battle_activation_service.BattleActivationActionWriteConflict,
    battle_activation_service.BattleActivationContinueWriteConflict,
    battle_activation_service.BattleActivationFinalizeWriteConflict,
    BattleEventSequenceConflict,
    BattleCheckpointSequenceConflict,
    IntegrityError,
    OperationalError,
)
_ACTIVATION_INVALID_ERRORS = (
    battle_activation_service.BattleActivationStartInvalid,
    battle_activation_service.BattleActivationPassInvalid,
    battle_activation_service.BattleActivationInterruptInvalid,
    battle_activation_service.BattleActivationActionInvalid,
    battle_activation_service.BattleActivationContinueInvalid,
    battle_activation_service.BattleActivationFinalizeInvalid,
)


def _activation_protocol_http_error(
    exc: Exception,
    *,
    operation: str,
) -> HTTPException | None:
    if isinstance(exc, _ACTIVATION_NOT_FOUND_ERRORS):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "battle_not_found"},
        )
    if isinstance(exc, _ACTIVATION_UPGRADE_ERRORS):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "battle_protocol_upgrade_required"},
        )
    if isinstance(exc, _ACTIVATION_SEQUENCE_ERRORS):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stale_sequence"},
        )
    if isinstance(exc, _ACTIVATION_FORBIDDEN_ERRORS):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden"},
        )
    if isinstance(exc, (*_ACTIVATION_UNAVAILABLE_ERRORS, *_ACTIVATION_WRITE_ERRORS)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "write_conflict"},
        )
    if not isinstance(exc, _ACTIVATION_INVALID_ERRORS):
        return None

    if isinstance(
        exc,
        battle_activation_service.BattleActivationInterruptUnsupported,
    ):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unsupported_interrupt"},
        )
    reason = exc.reason
    if reason is ActivationProtocolErrorReason.STALE_ACTIVATION:
        code, status_code = "stale_activation", status.HTTP_409_CONFLICT
    elif reason is ActivationProtocolErrorReason.STALE_WINDOW:
        code, status_code = "stale_window", status.HTTP_409_CONFLICT
    elif reason is ActivationProtocolErrorReason.INVALID_PHASE:
        code, status_code = "invalid_phase", status.HTTP_409_CONFLICT
    elif reason is ActivationProtocolErrorReason.INVALID_CALLER:
        code, status_code = (
            ("not_current_priority", status.HTTP_409_CONFLICT)
            if operation in {"pass", "interrupt"}
            else ("forbidden", status.HTTP_403_FORBIDDEN)
        )
    elif reason is ActivationProtocolErrorReason.INVALID_SELECTION:
        code, status_code = "invalid_selection", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif reason is ActivationProtocolErrorReason.ILLEGAL_ACTION:
        code, status_code = "illegal_action", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT:
        code, status_code = "illegal_interrupt", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif reason is ActivationProtocolErrorReason.INTERRUPT_LIMIT_REACHED:
        code, status_code = (
            "interrupt_limit_reached",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    elif reason is ActivationProtocolErrorReason.ILLEGAL_RECOVERY:
        code, status_code = "illegal_recovery", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif reason is ActivationProtocolErrorReason.ILLEGAL_CONTINUE:
        code, status_code = "invalid_phase", status.HTTP_409_CONFLICT
    else:
        fallback_codes = {
            "start": "invalid_selection",
            "pass": "invalid_phase",
            "interrupt": "illegal_interrupt",
            "action": "illegal_action",
            "continue": "invalid_phase",
            "finalize": "illegal_recovery",
        }
        code = fallback_codes[operation]
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=status_code, detail={"code": code})


def _stage_activation_mutation(
    db: Session,
    *,
    operation: str,
    stage: Callable[[], Any],
    success_status: int | Callable[[Any], int],
) -> JSONResponse:
    try:
        prepared = stage()
        status_code = (
            success_status(prepared)
            if callable(success_status)
            else success_status
        )
        response = _activation_json_response(
            prepared,
            status_code=status_code,
        )
        db.commit()
        return response
    except Exception as exc:
        db.rollback()
        mapped = _activation_protocol_http_error(exc, operation=operation)
        if mapped is None:
            raise
        raise mapped from exc


def _public_activation_mutation(prepared: Any) -> BattleActionPublic:
    serialized_state = battle_state_to_json(
        prepared.state,
        version=ACTIVATION_PROTOCOL_VERSION_V2,
    )
    return BattleActionPublic(
        battle_id=prepared.battle_id,
        previous_sequence=prepared.previous_sequence,
        new_sequence=prepared.new_sequence,
        state=BattleStateWirePublic(
            checkpoint_schema=str(serialized_state["schema"]),
            version=int(serialized_state["version"]),
            state=serialized_state["state"],
        ),
        events=[_public_event(event) for event in prepared.events],
    )


def _activation_json_response(
    prepared: Any,
    *,
    status_code: int,
) -> JSONResponse:
    public = _public_activation_mutation(prepared)
    return JSONResponse(
        status_code=status_code,
        content=public.model_dump(mode="json", by_alias=True),
    )


def _accepts_event_stream(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return any(
        item.split(";", 1)[0].strip().lower() == "text/event-stream"
        for item in accept.split(",")
    )


def _event_stream_cursor(
    *,
    since: int | None,
    last_event_id: str | None,
) -> int:
    if last_event_id is None:
        cursor = since if since is not None else 0
        if cursor > _MAX_EVENT_CURSOR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="since cursor is outside the event sequence range",
            )
        return cursor
    if re.fullmatch(r"[0-9]+", last_event_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be a non-negative decimal sequence",
        )
    try:
        header_cursor = int(last_event_id)
    except ValueError:
        header_cursor = _MAX_EVENT_CURSOR + 1
    if header_cursor > _MAX_EVENT_CURSOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be a non-negative decimal sequence",
        )
    if since is not None and since != header_cursor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since and Last-Event-ID cursors must match",
        )
    return header_cursor


def _public_adaptation(result: AdaptResult) -> RosterAdaptationPublic:
    return RosterAdaptationPublic(
        dropped_excluded=list(result.dropped_excluded),
        inert_incomplete=list(result.inert_incomplete),
        deferred_attached_heroes=list(result.deferred_attached_heroes),
    )


def _public_battle(
    db: Session,
    battle: models.Battle,
    *,
    adaptation_report: BattleAdaptationPublic | None = None,
) -> BattlePublic:
    return BattlePublic(
        battle_id=battle.id,
        p1_user_id=battle.p1_user_id,
        p2_user_id=battle.p2_user_id,
        p1_roster_id=battle.p1_roster_id,
        p2_roster_id=battle.p2_roster_id,
        winner_user_id=battle.winner_user_id,
        current_round=battle.current_round,
        rng_seed=battle.rng_seed,
        status=battle.status,
        activation_protocol_version=battle.activation_protocol_version,
        latest_sequence=latest_event_sequence(db, battle.id),
        adaptation_report=adaptation_report,
    )


def _public_battle_invite(invite: models.BattleInvite) -> BattleInvitePublic:
    return BattleInvitePublic(
        id=invite.id,
        from_user_id=invite.from_user_id,
        to_user_id=invite.to_user_id,
        roster_id=invite.roster_id,
        scenario=invite.scenario,
        status=invite.status,
        activation_protocol_version=invite.activation_protocol_version,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
    )


def _public_invite_acceptance(
    db: Session,
    result: battle_invite_service.BattleInviteAccepted,
) -> BattlePublic:
    adaptation_report = None
    if result.created:
        if result.adapted_p1 is None or result.adapted_p2 is None:
            raise RuntimeError("new invite acceptance is missing adaptation results")
        adaptation_report = BattleAdaptationPublic(
            p1=_public_adaptation(result.adapted_p1),
            p2=_public_adaptation(result.adapted_p2),
        )
    return _public_battle(
        db,
        result.battle,
        adaptation_report=adaptation_report,
    )


def _is_sqlite_lock_error(db: Session, exc: OperationalError) -> bool:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return False
    message = str(exc.orig).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
    )


def _read_invite_acceptance_after_rollback(
    db: Session,
    *,
    invite_id: int,
    acceptor: BattleAcceptor,
    roster_id: int,
) -> battle_invite_service.BattleInviteAccepted | None:
    try:
        return battle_invite_service.read_battle_invite_acceptance(
            db,
            invite_id=invite_id,
            acceptor_user_id=acceptor.user_id,
            accepted_roster_id=roster_id,
            session_acceptor_is_agent=acceptor.session_user_is_agent,
        )
    except battle_invite_service.BattleInviteAcceptPending:
        return None
    except battle_invite_service.BattleInviteAcceptNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except battle_invite_service.BattleInviteAcceptConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_INVITE_ACCEPT_CONFLICT_DETAIL,
        ) from exc


def _simulation_players(bot: str, base_seed: int, game_index: int):
    return simulation_players(bot, base_seed, game_index)


@router.post("", response_model=BattlePublic, status_code=status.HTTP_201_CREATED)
def create_battle(
    payload: BattleCreate,
    db: Session = Depends(get_db),
    creator: BattleCreator = Depends(_battle_creator),
) -> BattlePublic:
    roster_p0 = _get_owned_roster(
        db, roster_id=payload.p1_roster_id, owner_user_id=creator.user_id
    )
    roster_p1 = _get_owned_roster(
        db, roster_id=payload.p2_roster_id, owner_user_id=creator.user_id
    )
    staged = stage_battle_creation(
        db,
        p1_user_id=creator.user_id,
        p2_user_id=creator.user_id,
        p1_roster=roster_p0,
        p2_roster=roster_p1,
        rng_seed=payload.rng_seed,
        initiative_player=payload.initiative_player,
        activation_protocol_version=payload.activation_protocol_version,
    )
    db.commit()
    db.refresh(staged.battle)
    return _public_battle(
        db,
        staged.battle,
        adaptation_report=BattleAdaptationPublic(
            p1=_public_adaptation(staged.adapted_p1),
            p2=_public_adaptation(staged.adapted_p2),
        ),
    )


@router.post("/simulate", response_model=BattleSimulationPublic)
def simulate_battle(
    payload: BattleSimulate,
    db: Session = Depends(get_db),
    simulator: BattleSimulator = Depends(_battle_simulator),
) -> BattleSimulationPublic:
    roster_p0 = _get_owned_roster(
        db, roster_id=payload.p1_roster_id, owner_user_id=simulator.user_id
    )
    roster_p1 = _get_owned_roster(
        db, roster_id=payload.p2_roster_id, owner_user_id=simulator.user_id
    )
    bot = payload.bot.lower()
    try:
        summary = simulate_roster_pair(
            roster_p0,
            roster_p1,
            bot=bot,
            games=payload.games,
            seed=payload.seed,
            map_name=payload.map_name,
            allowed_bots=BATTLE_SIMULATION_BOTS,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    n_games = summary.n_games
    return BattleSimulationPublic(
        p1_roster_id=roster_p0.id,
        p2_roster_id=roster_p1.id,
        bot=bot,
        map_name=payload.map_name.lower(),
        n_games=n_games,
        wins_p0=summary.wins_p0,
        wins_p1=summary.wins_p1,
        draws=summary.draws,
        total_rounds=summary.total_rounds,
        win_rate_p0=summary.win_rate_p0,
        win_rate_p1=summary.win_rate_p1,
        draw_rate=summary.draw_rate,
        avg_rounds=summary.avg_rounds,
    )


@router.post(
    "/invite",
    response_model=BattleInvitePublic,
    status_code=status.HTTP_201_CREATED,
)
def create_battle_invite(
    payload: BattleInviteCreate,
    db: Session = Depends(get_db),
    inviter: BattleInviter = Depends(_battle_inviter),
) -> BattleInvitePublic:
    try:
        invite = battle_invite_service.create_battle_invite(
            db,
            from_user_id=inviter.user_id,
            to_user_id=payload.to_user_id,
            roster_id=payload.roster_id,
            scenario=payload.scenario,
            expires_in_hours=payload.expires_in_hours,
            activation_protocol_version=payload.activation_protocol_version,
        )
        public = _public_battle_invite(invite)
        db.commit()
    except (
        battle_invite_service.BattleInviteRosterNotFound,
        battle_invite_service.BattleInviteTargetNotFound,
    ) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except battle_invite_service.BattleInviteScenarioInvalid as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown battle invite scenario",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle invite could not be created",
        ) from exc
    return public


@router.post("/invite/{invite_id}/accept", response_model=BattlePublic)
def accept_battle_invite(
    invite_id: int,
    payload: BattleInviteAccept,
    db: Session = Depends(get_db),
    acceptor: BattleAcceptor = Depends(_battle_acceptor),
) -> BattlePublic:
    for attempt in range(_MAX_INVITE_ACCEPT_ATTEMPTS):
        try:
            result = battle_invite_service.stage_battle_invite_acceptance(
                db,
                invite_id=invite_id,
                acceptor_user_id=acceptor.user_id,
                accepted_roster_id=payload.roster_id,
                session_acceptor_is_agent=acceptor.session_user_is_agent,
            )
            if isinstance(
                result,
                battle_invite_service.BattleInviteExpiredStaged,
            ):
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_INVITE_ACCEPT_CONFLICT_DETAIL,
                )
            db.commit()
            db.refresh(result.battle)
            return _public_invite_acceptance(db, result)
        except battle_invite_service.BattleInviteAcceptNotFound as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except battle_invite_service.BattleInviteAcceptConflict as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_INVITE_ACCEPT_CONFLICT_DETAIL,
            ) from exc
        except battle_invite_service.BattleInviteAcceptRace:
            db.rollback()
            durable = _read_invite_acceptance_after_rollback(
                db,
                invite_id=invite_id,
                acceptor=acceptor,
                roster_id=payload.roster_id,
            )
            if durable is not None:
                return _public_invite_acceptance(db, durable)
            if attempt + 1 == _MAX_INVITE_ACCEPT_ATTEMPTS:
                break
            db.rollback()
        except IntegrityError:
            db.rollback()
            durable = _read_invite_acceptance_after_rollback(
                db,
                invite_id=invite_id,
                acceptor=acceptor,
                roster_id=payload.roster_id,
            )
            if durable is not None:
                return _public_invite_acceptance(db, durable)
            break
        except OperationalError as exc:
            is_sqlite_lock = _is_sqlite_lock_error(db, exc)
            db.rollback()
            if not is_sqlite_lock:
                raise
            durable = _read_invite_acceptance_after_rollback(
                db,
                invite_id=invite_id,
                acceptor=acceptor,
                roster_id=payload.roster_id,
            )
            if durable is not None:
                return _public_invite_acceptance(db, durable)
            if attempt + 1 == _MAX_INVITE_ACCEPT_ATTEMPTS:
                break
            db.rollback()
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_INVITE_ACCEPT_CONFLICT_DETAIL,
    )


@router.post(
    "/{battle_id}/activations",
    response_model=BattleActionPublic,
    status_code=status.HTTP_201_CREATED,
)
def start_battle_activation(
    battle_id: int,
    payload: BattleActivationStartCreate,
    db: Session = Depends(get_db),
    actor: BattleActor = Depends(_battle_actor),
) -> JSONResponse:
    return _stage_activation_mutation(
        db,
        operation="start",
        stage=lambda: battle_activation_service.stage_battle_activation_start(
            db,
            battle_id=battle_id,
            caller_user_id=actor.user_id,
            selected_unit_id=payload.selected_unit_id,
            expected_sequence=payload.expected_sequence,
        ),
        success_status=status.HTTP_201_CREATED,
    )


@router.post(
    "/{battle_id}/interrupts",
    response_model=BattleActionPublic,
    responses={status.HTTP_202_ACCEPTED: {"model": BattleActionPublic}},
)
def mutate_battle_activation_interrupt(
    battle_id: int,
    payload: BattleActivationInterruptOperation,
    db: Session = Depends(get_db),
    interrupter: BattleInterrupter = Depends(_battle_interrupter),
) -> BattleActionPublic | JSONResponse:
    if isinstance(payload, BattleActivationPassCreate):
        return _stage_activation_mutation(
            db,
            operation="pass",
            stage=lambda: battle_activation_service.stage_battle_activation_pass(
                db,
                battle_id=battle_id,
                caller_user_id=interrupter.user_id,
                expected_sequence=payload.expected_sequence,
                activation_id=payload.activation_id,
                expected_activation_version=payload.expected_activation_version,
                expected_window_version=payload.expected_window_version,
            ),
            success_status=lambda prepared: (
                status.HTTP_202_ACCEPTED
                if prepared.state.activation is not None
                and prepared.state.activation.window is not None
                else status.HTTP_200_OK
            ),
        )
    return _stage_activation_mutation(
        db,
        operation="interrupt",
        stage=lambda: battle_activation_service.stage_battle_activation_interrupt(
            db,
            battle_id=battle_id,
            caller_user_id=interrupter.user_id,
            expected_sequence=payload.expected_sequence,
            activation_id=payload.activation_id,
            expected_activation_version=payload.expected_activation_version,
            expected_window_version=payload.expected_window_version,
            source_unit_id=payload.source_unit_id,
            ability_slug=payload.ability_slug,
            payload=payload.payload,
        ),
        success_status=status.HTTP_200_OK,
    )


@router.post(
    "/{battle_id}/activations/{activation_id}/transitions",
    response_model=BattleActionPublic,
    responses={status.HTTP_202_ACCEPTED: {"model": BattleActionPublic}},
)
def transition_battle_activation(
    battle_id: int,
    activation_id: int,
    payload: BattleActivationTransitionCreate,
    db: Session = Depends(get_db),
    actor: BattleActor = Depends(_battle_actor),
) -> BattleActionPublic | JSONResponse:
    if isinstance(payload, BattleActivationContinueCreate):
        return _stage_activation_mutation(
            db,
            operation="continue",
            stage=lambda: battle_activation_service.stage_battle_activation_continue(
                db,
                battle_id=battle_id,
                caller_user_id=actor.user_id,
                expected_sequence=payload.expected_sequence,
                activation_id=activation_id,
                expected_activation_version=payload.expected_activation_version,
            ),
            success_status=status.HTTP_202_ACCEPTED,
        )
    return _stage_activation_mutation(
        db,
        operation="finalize",
        stage=lambda: battle_activation_service.stage_battle_activation_finalize(
            db,
            battle_id=battle_id,
            caller_user_id=actor.user_id,
            expected_sequence=payload.expected_sequence,
            activation_id=activation_id,
            expected_activation_version=payload.expected_activation_version,
            recovery_uses=tuple(payload.recovery.uses),
        ),
        success_status=status.HTTP_200_OK,
    )


def _take_v1_battle_action(
    db: Session,
    *,
    battle: models.Battle,
    actor_user_id: int,
    payload: BattleActionCreate,
) -> BattleActionPublic:
    try:
        prepared = stage_battle_action(
            db,
            battle=battle,
            actor_user_id=actor_user_id,
            expected_sequence=payload.expected_sequence,
            action_payload=payload.action,
        )
        db.commit()
    except BattleActionInvalid as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
    except BattleActionForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except (
        BattleActionUnavailable,
        BattleActionSequenceConflict,
        BattleEventSequenceConflict,
        BattleCheckpointSequenceConflict,
        IntegrityError,
    ) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle event sequence conflict",
        ) from exc

    serialized_state = battle_state_to_json(prepared.state)
    return BattleActionPublic(
        battle_id=battle.id,
        previous_sequence=prepared.previous_sequence,
        new_sequence=prepared.new_sequence,
        state=BattleStateWirePublic(
            checkpoint_schema=str(serialized_state["schema"]),
            version=int(serialized_state["version"]),
            state=serialized_state["state"],
        ),
        events=[_public_event(event) for event in prepared.events],
    )


@router.post(
    "/{battle_id}/actions",
    response_model=BattleActionPublic,
    responses={status.HTTP_202_ACCEPTED: {"model": BattleActionPublic}},
)
def take_battle_action(
    battle_id: int,
    payload: BattleActionCreate,
    db: Session = Depends(get_db),
    actor: BattleActor = Depends(_battle_actor),
) -> BattleActionPublic | JSONResponse:
    has_activation_id = payload.activation_id is not None
    has_activation_version = payload.expected_activation_version is not None
    if has_activation_id and has_activation_version:
        return _stage_activation_mutation(
            db,
            operation="action",
            stage=lambda: battle_activation_service.stage_battle_activation_action(
                db,
                battle_id=battle_id,
                caller_user_id=actor.user_id,
                expected_sequence=payload.expected_sequence,
                activation_id=payload.activation_id,
                expected_activation_version=payload.expected_activation_version,
                action_payload=payload.action,
            ),
            success_status=status.HTTP_202_ACCEPTED,
        )

    battle = _get_accessible_battle(db, battle_id=battle_id, reader=actor)
    if (
        battle.activation_protocol_version == ACTIVATION_PROTOCOL_VERSION_V2
        or has_activation_id
        or has_activation_version
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "activation_guard_required"},
        )
    return _take_v1_battle_action(
        db,
        battle=battle,
        actor_user_id=actor.user_id,
        payload=payload,
    )


@router.get("/{battle_id}", response_model=BattlePublic)
def get_battle(
    battle_id: int,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattlePublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    return _public_battle(db, battle)


@router.get(
    "/{battle_id}/events",
    response_model=BattleEventsPublic,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def get_battle_events(
    battle_id: int,
    request: Request,
    since: Annotated[int | None, Query(ge=0)] = None,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleEventsPublic | StreamingResponse:
    wants_event_stream = _accepts_event_stream(request)
    cursor = (
        _event_stream_cursor(
            since=since,
            last_event_id=request.headers.get("last-event-id"),
        )
        if wants_event_stream
        else (since if since is not None else 0)
    )
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    if wants_event_stream:
        stream_session_factory = session_factory_from_session(db)
        return StreamingResponse(
            stream_battle_events(
                request,
                session_factory=stream_session_factory,
                battle_id=battle.id,
                cursor=cursor,
                project_event=_public_event_payload,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    events = load_events(db, battle.id, since=cursor)
    return BattleEventsPublic(
        battle_id=battle.id,
        events=[_public_event(event) for event in events],
    )


@router.get("/{battle_id}/state", response_model=BattleStatePublic)
def get_battle_state(
    battle_id: int,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleStatePublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    checkpoint = load_latest_checkpoint(db, battle.id)
    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Current battle checkpoint is unavailable",
        )
    serialized = battle_state_to_json(
        checkpoint.state,
        version=battle.activation_protocol_version,
    )
    return BattleStatePublic(
        checkpoint_schema=str(serialized["schema"]),
        version=int(serialized["version"]),
        battle_id=battle.id,
        sequence_at=checkpoint.sequence_at,
        state=serialized["state"],
    )


@router.post("/{battle_id}/replay", response_model=BattleReplayPublic)
def replay_battle(
    battle_id: int,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleReplayPublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    try:
        replayed = battle_replay_service.replay_battle_state(
            db,
            battle_id=battle.id,
        )
    except battle_replay_service.BattleReplayLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Battle replay exceeds event limit",
        ) from exc
    except battle_replay_service.BattleReplayConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle replay could not be verified",
        ) from exc

    serialized = battle_state_to_json(
        replayed.state,
        version=battle.activation_protocol_version,
    )
    return BattleReplayPublic(
        battle_id=replayed.battle_id,
        base_sequence=replayed.base_sequence,
        replayed_through_sequence=replayed.replayed_through_sequence,
        event_count=replayed.event_count,
        verified_against_checkpoint=True,
        state=BattleStateWirePublic(
            checkpoint_schema=str(serialized["schema"]),
            version=int(serialized["version"]),
            state=serialized["state"],
        ),
    )
