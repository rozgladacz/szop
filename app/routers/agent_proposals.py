from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import (
    AgentPrincipal,
    get_current_user,
    require_agent_scope,
    require_agent_scopes,
)
from ..services.battle_actions import (
    BattleActionForbidden,
    BattleActionInvalid,
    BattleActionNotFound,
    BattleActionProposalProtocolConflict,
    BattleActionSequenceConflict,
    BattleActionUnavailable,
    get_participant_battle,
    prepare_battle_action,
    stage_battle_action,
)
from ..services.engine.persistence import (
    BattleCheckpointSequenceConflict,
    BattleEventSequenceConflict,
    latest_event_sequence,
)

router = APIRouter(prefix="/agent_proposals", tags=["agent_proposals"])

CREATE_PROPOSAL_SCOPE = "agent_proposals:create"
BATTLE_READ_SCOPE = "battle:read"
BATTLE_ACTION_PROPOSAL = "battle:action"
_MAX_ACTION_LENGTH = 120
_MAX_SUMMARY_LENGTH = 500
_MAX_PAYLOAD_JSON_CHARS = 20_000
_ACTION_RE = re.compile(rf"^[a-z][a-z0-9_.:-]{{0,{_MAX_ACTION_LENGTH - 1}}}$")


class AgentProposalCreate(BaseModel):
    action: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_ACTION_LENGTH,
        pattern=_ACTION_RE.pattern,
    )
    summary: str = Field(..., min_length=1, max_length=_MAX_SUMMARY_LENGTH)
    payload: dict[str, Any] = Field(default_factory=dict)


class BattleActionProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    battle_id: int = Field(..., ge=1, strict=True)
    expected_sequence: int = Field(..., ge=0, strict=True)
    action: dict[str, Any]
    summary: str = Field(..., min_length=1, max_length=_MAX_SUMMARY_LENGTH)


class AgentProposalPublic(BaseModel):
    id: int
    owner_user_id: int
    agent_user_id: int
    token_id: int | None
    action: str
    summary: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    status: str
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    decided_by_user_id: int | None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _summary_text(summary: str) -> str:
    text = summary.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent proposal summary cannot be blank.",
        )
    return text


def _payload_json(payload: dict[str, Any]) -> str:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent proposal payload must be JSON-serializable.",
        ) from exc
    if len(text) > _MAX_PAYLOAD_JSON_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Agent proposal payload is limited to "
                f"{_MAX_PAYLOAD_JSON_CHARS} JSON characters."
            ),
        )
    return text


def _payload_from_json(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _result_json(result: dict[str, Any]) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    )


def _result_from_json(result_json: str | None) -> dict[str, Any] | None:
    if result_json is None:
        return None
    return _payload_from_json(result_json)


def _audit_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    action: str,
    route: str = "/agent_proposals",
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "action": action,
        "proposal_id": proposal.id,
        "proposal_action": proposal.action,
        "token_id": proposal.token_id,
    }
    if details:
        payload.update(details)
    db.add(
        models.AgentAuditLog(
            user_id=proposal.owner_user_id,
            agent_user_id=proposal.agent_user_id,
            route=route,
            params_json=json.dumps(payload, sort_keys=True),
        )
    )


def _public_proposal(proposal: models.AgentProposal) -> AgentProposalPublic:
    return AgentProposalPublic(
        id=proposal.id,
        owner_user_id=proposal.owner_user_id,
        agent_user_id=proposal.agent_user_id,
        token_id=proposal.token_id,
        action=proposal.action,
        summary=proposal.summary,
        payload=_payload_from_json(proposal.payload_json),
        result=_result_from_json(proposal.result_json),
        status=proposal.status,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        decided_at=proposal.decided_at,
        decided_by_user_id=proposal.decided_by_user_id,
    )


def _get_owned_proposal(
    db: Session,
    *,
    proposal_id: int,
    owner_user_id: int,
) -> models.AgentProposal:
    proposal = db.execute(
        select(models.AgentProposal).where(
            models.AgentProposal.id == proposal_id,
            models.AgentProposal.owner_user_id == owner_user_id,
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return proposal


def _decide_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    current_user: models.User,
    target_status: str,
    audit_action: str,
    conflict_action: str,
) -> AgentProposalPublic:
    if proposal.status == target_status:
        return _public_proposal(proposal)
    if proposal.status != models.AGENT_PROPOSAL_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only pending agent proposals can be {conflict_action}.",
        )

    proposal.status = target_status
    proposal.decided_at = _now()
    proposal.decided_by_user_id = current_user.id
    _audit_proposal(
        db,
        proposal=proposal,
        action=audit_action,
        route=f"/agent_proposals/{proposal.id}/{audit_action}",
        details={
            **_battle_action_audit_details(proposal),
            "decided_by_user_id": current_user.id,
        },
    )
    db.commit()
    db.refresh(proposal)
    return _public_proposal(proposal)


def _battle_action_fields(
    proposal: models.AgentProposal,
) -> tuple[int, int, dict[str, Any]]:
    payload = _payload_from_json(proposal.payload_json)
    if set(payload) != {"battle_id", "expected_sequence", "action"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle action proposal payload is unavailable.",
        )
    battle_id = payload["battle_id"]
    expected_sequence = payload["expected_sequence"]
    action_payload = payload["action"]
    if (
        type(battle_id) is not int
        or battle_id < 1
        or type(expected_sequence) is not int
        or expected_sequence < 0
        or type(action_payload) is not dict
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle action proposal payload is unavailable.",
        )
    return battle_id, expected_sequence, action_payload


def _battle_action_audit_details(
    proposal: models.AgentProposal,
) -> dict[str, Any]:
    if proposal.action != BATTLE_ACTION_PROPOSAL:
        return {}
    battle_id, expected_sequence, _ = _battle_action_fields(proposal)
    return {
        "battle_id": battle_id,
        "expected_sequence": expected_sequence,
    }


def _claim_battle_action_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    current_user: models.User,
) -> bool:
    now = _now()
    result = db.execute(
        update(models.AgentProposal)
        .where(
            models.AgentProposal.id == proposal.id,
            models.AgentProposal.owner_user_id == current_user.id,
            models.AgentProposal.status == models.AGENT_PROPOSAL_STATUS_PENDING,
        )
        .values(
            status=models.AGENT_PROPOSAL_STATUS_EXECUTED,
            decided_at=now,
            decided_by_user_id=current_user.id,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.expire(proposal)
    db.refresh(proposal)
    return True


def _proposal_after_claim_conflict(
    db: Session,
    *,
    proposal_id: int,
    owner_user_id: int,
) -> AgentProposalPublic:
    proposal = _get_owned_proposal(
        db,
        proposal_id=proposal_id,
        owner_user_id=owner_user_id,
    )
    if proposal.status in {
        models.AGENT_PROPOSAL_STATUS_EXECUTED,
        models.AGENT_PROPOSAL_STATUS_STALE,
    }:
        return _public_proposal(proposal)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Only pending battle action proposals can be executed.",
    )


def _mark_battle_action_stale(
    db: Session,
    *,
    proposal_id: int,
    current_user: models.User,
    battle_id: int,
    expected_sequence: int,
    actual_sequence: int,
) -> AgentProposalPublic:
    now = _now()
    stale_result = {
        "battle_id": battle_id,
        "expected_sequence": expected_sequence,
        "actual_sequence": actual_sequence,
    }
    updated = db.execute(
        update(models.AgentProposal)
        .where(
            models.AgentProposal.id == proposal_id,
            models.AgentProposal.owner_user_id == current_user.id,
            models.AgentProposal.status == models.AGENT_PROPOSAL_STATUS_PENDING,
        )
        .values(
            status=models.AGENT_PROPOSAL_STATUS_STALE,
            result_json=_result_json(stale_result),
            decided_at=now,
            decided_by_user_id=current_user.id,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        db.rollback()
        return _proposal_after_claim_conflict(
            db,
            proposal_id=proposal_id,
            owner_user_id=current_user.id,
        )
    proposal = _get_owned_proposal(
        db,
        proposal_id=proposal_id,
        owner_user_id=current_user.id,
    )
    db.refresh(proposal)
    _audit_proposal(
        db,
        proposal=proposal,
        action="stale",
        route=f"/agent_proposals/{proposal.id}/approve",
        details={
            **stale_result,
            "decided_by_user_id": current_user.id,
        },
    )
    db.commit()
    db.refresh(proposal)
    return _public_proposal(proposal)


def _execute_battle_action_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    current_user: models.User,
) -> AgentProposalPublic:
    if proposal.status in {
        models.AGENT_PROPOSAL_STATUS_EXECUTED,
        models.AGENT_PROPOSAL_STATUS_STALE,
    }:
        return _public_proposal(proposal)
    if proposal.status != models.AGENT_PROPOSAL_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending battle action proposals can be executed.",
        )

    battle_id, expected_sequence, action_payload = _battle_action_fields(proposal)
    if not _claim_battle_action_proposal(
        db,
        proposal=proposal,
        current_user=current_user,
    ):
        return _proposal_after_claim_conflict(
            db,
            proposal_id=proposal.id,
            owner_user_id=current_user.id,
        )

    try:
        battle = get_participant_battle(
            db,
            battle_id=battle_id,
            user_id=current_user.id,
        )
        prepared = stage_battle_action(
            db,
            battle=battle,
            actor_user_id=current_user.id,
            expected_sequence=expected_sequence,
            action_payload=action_payload,
            require_v1_protocol=True,
        )
        execution_result = {
            "battle_id": battle_id,
            "previous_sequence": prepared.previous_sequence,
            "new_sequence": prepared.new_sequence,
            "event_count": len(prepared.events),
        }
        proposal.result_json = _result_json(execution_result)
        _audit_proposal(
            db,
            proposal=proposal,
            action="execute",
            route=f"/agent_proposals/{proposal.id}/approve",
            details={
                **execution_result,
                "expected_sequence": expected_sequence,
                "decided_by_user_id": current_user.id,
            },
        )
        db.commit()
    except BattleActionNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except BattleActionForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except BattleActionInvalid as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
    except BattleActionProposalProtocolConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (BattleActionUnavailable, BattleActionSequenceConflict) as exc:
        db.rollback()
        return _mark_battle_action_stale(
            db,
            proposal_id=proposal.id,
            current_user=current_user,
            battle_id=battle_id,
            expected_sequence=expected_sequence,
            actual_sequence=exc.actual_sequence,
        )
    except (
        BattleEventSequenceConflict,
        BattleCheckpointSequenceConflict,
        IntegrityError,
    ):
        db.rollback()
        return _mark_battle_action_stale(
            db,
            proposal_id=proposal.id,
            current_user=current_user,
            battle_id=battle_id,
            expected_sequence=expected_sequence,
            actual_sequence=latest_event_sequence(db, battle_id),
        )

    db.refresh(proposal)
    return _public_proposal(proposal)


@router.post("", response_model=AgentProposalPublic, status_code=status.HTTP_201_CREATED)
def create_agent_proposal(
    payload: AgentProposalCreate,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(require_agent_scope(CREATE_PROPOSAL_SCOPE)),
) -> AgentProposalPublic:
    if payload.action == BATTLE_ACTION_PROPOSAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Battle actions must use "
                "POST /agent_proposals/battle-actions."
            ),
        )
    proposal = models.AgentProposal(
        owner_user_id=principal.owner_user_id,
        agent_user_id=principal.agent_user_id,
        token_id=principal.token_id,
        action=payload.action,
        summary=_summary_text(payload.summary),
        payload_json=_payload_json(payload.payload),
    )
    db.add(proposal)
    db.flush()
    _audit_proposal(db, proposal=proposal, action="create")
    db.commit()
    db.refresh(proposal)
    return _public_proposal(proposal)


@router.post(
    "/battle-actions",
    response_model=AgentProposalPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_battle_action_proposal(
    payload: BattleActionProposalCreate,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(
        require_agent_scopes(BATTLE_READ_SCOPE, CREATE_PROPOSAL_SCOPE)
    ),
) -> AgentProposalPublic:
    summary = _summary_text(payload.summary)
    try:
        battle = get_participant_battle(
            db,
            battle_id=payload.battle_id,
            user_id=principal.owner_user_id,
        )
        prepared = prepare_battle_action(
            db,
            battle=battle,
            actor_user_id=principal.owner_user_id,
            expected_sequence=payload.expected_sequence,
            action_payload=payload.action,
            require_v1_protocol=True,
        )
    except BattleActionNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except BattleActionForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except BattleActionInvalid as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
    except (
        BattleActionProposalProtocolConflict,
        BattleActionUnavailable,
        BattleActionSequenceConflict,
    ) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    proposal_payload = {
        "battle_id": battle.id,
        "expected_sequence": prepared.previous_sequence,
        "action": prepared.action_wire,
    }
    proposal = models.AgentProposal(
        owner_user_id=principal.owner_user_id,
        agent_user_id=principal.agent_user_id,
        token_id=principal.token_id,
        action=BATTLE_ACTION_PROPOSAL,
        summary=summary,
        payload_json=_payload_json(proposal_payload),
    )
    db.add(proposal)
    db.flush()
    _audit_proposal(
        db,
        proposal=proposal,
        action="create",
        route="/agent_proposals/battle-actions",
        details={
            "battle_id": battle.id,
            "expected_sequence": prepared.previous_sequence,
        },
    )
    db.commit()
    db.refresh(proposal)
    return _public_proposal(proposal)


@router.get("", response_model=list[AgentProposalPublic])
def list_agent_proposals(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> list[AgentProposalPublic]:
    proposals = (
        db.execute(
            select(models.AgentProposal)
            .where(models.AgentProposal.owner_user_id == current_user.id)
            .order_by(
                models.AgentProposal.created_at.desc(),
                models.AgentProposal.id.desc(),
            )
        )
        .scalars()
        .all()
    )
    return [_public_proposal(proposal) for proposal in proposals]


@router.get("/{proposal_id}", response_model=AgentProposalPublic)
def get_agent_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> AgentProposalPublic:
    proposal = _get_owned_proposal(
        db,
        proposal_id=proposal_id,
        owner_user_id=current_user.id,
    )
    return _public_proposal(proposal)


@router.post("/{proposal_id}/approve", response_model=AgentProposalPublic)
def approve_agent_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> AgentProposalPublic:
    proposal = _get_owned_proposal(
        db,
        proposal_id=proposal_id,
        owner_user_id=current_user.id,
    )
    if proposal.action == BATTLE_ACTION_PROPOSAL:
        return _execute_battle_action_proposal(
            db,
            proposal=proposal,
            current_user=current_user,
        )
    return _decide_proposal(
        db,
        proposal=proposal,
        current_user=current_user,
        target_status=models.AGENT_PROPOSAL_STATUS_APPROVED,
        audit_action="approve",
        conflict_action="approved",
    )


@router.post("/{proposal_id}/reject", response_model=AgentProposalPublic)
def reject_agent_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> AgentProposalPublic:
    proposal = _get_owned_proposal(
        db,
        proposal_id=proposal_id,
        owner_user_id=current_user.id,
    )
    return _decide_proposal(
        db,
        proposal=proposal,
        current_user=current_user,
        target_status=models.AGENT_PROPOSAL_STATUS_REJECTED,
        audit_action="reject",
        conflict_action="rejected",
    )
