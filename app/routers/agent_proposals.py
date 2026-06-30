from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import AgentPrincipal, get_current_user, require_agent_scope

router = APIRouter(prefix="/agent_proposals", tags=["agent_proposals"])

CREATE_PROPOSAL_SCOPE = "agent_proposals:create"
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


class AgentProposalPublic(BaseModel):
    id: int
    owner_user_id: int
    agent_user_id: int
    token_id: int | None
    action: str
    summary: str
    payload: dict[str, Any]
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
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
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


def _audit_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    action: str,
) -> None:
    db.add(
        models.AgentAuditLog(
            user_id=proposal.owner_user_id,
            agent_user_id=proposal.agent_user_id,
            route="/agent_proposals",
            params_json=json.dumps(
                {
                    "action": action,
                    "proposal_id": proposal.id,
                    "proposal_action": proposal.action,
                    "token_id": proposal.token_id,
                },
                sort_keys=True,
            ),
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
    _audit_proposal(db, proposal=proposal, action=audit_action)
    db.commit()
    db.refresh(proposal)
    return _public_proposal(proposal)


@router.post("", response_model=AgentProposalPublic, status_code=status.HTTP_201_CREATED)
def create_agent_proposal(
    payload: AgentProposalCreate,
    db: Session = Depends(get_db),
    principal: AgentPrincipal = Depends(require_agent_scope(CREATE_PROPOSAL_SCOPE)),
) -> AgentProposalPublic:
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
