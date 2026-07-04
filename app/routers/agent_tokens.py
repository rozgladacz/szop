from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db, utcnow
from ..security import get_current_user, hash_agent_token, hash_password

router = APIRouter(prefix="/agent_tokens", tags=["agent_tokens"])

_DEFAULT_EXPIRY_DAYS = 30
_MAX_EXPIRY_DAYS = 365
_MAX_ACTIVE_TOKENS_PER_OWNER = 20
_MAX_SCOPES = 20
_SCOPE_RE = re.compile(r"^(?:\*|[a-z][a-z0-9_.:-]{0,63})$")


class AgentTokenCreate(BaseModel):
    scopes: list[str] = Field(..., min_length=1, max_length=_MAX_SCOPES)
    expires_in_days: int = Field(_DEFAULT_EXPIRY_DAYS, ge=1, le=_MAX_EXPIRY_DAYS)


class AgentTokenPublic(BaseModel):
    id: int
    agent_user_id: int
    agent_username: str
    owner_user_id: int
    scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class AgentTokenCreated(AgentTokenPublic):
    token: str


def _validate_scopes(scopes: list[str]) -> list[str]:
    if len(scopes) > _MAX_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {_MAX_SCOPES} agent token scopes are allowed.",
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for value in scopes:
        scope = str(value).strip()
        if not _SCOPE_RE.fullmatch(scope):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid agent token scope: {scope!r}",
            )
        if scope not in seen:
            normalized.append(scope)
            seen.add(scope)

    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one agent token scope is required.",
        )
    if "*" in seen and len(normalized) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wildcard scope cannot be combined with specific scopes.",
        )
    return normalized


def _scope_json(scopes: list[str]) -> str:
    return json.dumps({scope: True for scope in scopes}, sort_keys=True)


def _scopes_from_json(scope_json: str) -> list[str]:
    try:
        payload = json.loads(scope_json or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return sorted(key for key, value in payload.items() if value is True)


def _enforce_active_token_quota(db: Session, owner_user_id: int, now: datetime) -> None:
    count = db.execute(
        select(func.count(models.AgentToken.id)).where(
            models.AgentToken.owner_user_id == owner_user_id,
            models.AgentToken.revoked_at.is_(None),
            models.AgentToken.expires_at > now,
        )
    ).scalar_one()
    if int(count or 0) < _MAX_ACTIVE_TOKENS_PER_OWNER:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"At most {_MAX_ACTIVE_TOKENS_PER_OWNER} active agent tokens are "
            "allowed per user."
        ),
    )


def _new_agent_username(db: Session, owner_user_id: int) -> str:
    for _ in range(16):
        suffix = secrets.token_urlsafe(6).replace("-", "_")[:8]
        username = f"agent-{owner_user_id}-{suffix}"
        exists = db.execute(
            select(models.User.id).where(models.User.username == username)
        ).first()
        if not exists:
            return username
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not allocate an agent username.",
    )


def _audit_token_management(
    db: Session,
    *,
    owner_user_id: int,
    agent_user_id: int,
    action: str,
    token_id: int,
    scopes: list[str],
) -> None:
    db.add(
        models.AgentAuditLog(
            user_id=owner_user_id,
            agent_user_id=agent_user_id,
            route="/agent_tokens",
            params_json=json.dumps(
                {
                    "action": action,
                    "token_id": token_id,
                    "scopes": scopes,
                },
                sort_keys=True,
            ),
        )
    )


def _public_token(token: models.AgentToken) -> AgentTokenPublic:
    agent_username = ""
    if token.agent_user is not None:
        agent_username = token.agent_user.username
    return AgentTokenPublic(
        id=token.id,
        agent_user_id=token.agent_user_id,
        agent_username=agent_username,
        owner_user_id=token.owner_user_id,
        scopes=_scopes_from_json(token.scope_json),
        expires_at=token.expires_at,
        revoked_at=token.revoked_at,
        last_used_at=token.last_used_at,
        created_at=token.created_at,
    )


@router.post("", response_model=AgentTokenCreated, status_code=status.HTTP_201_CREATED)
def create_agent_token(
    payload: AgentTokenCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> AgentTokenCreated:
    scopes = _validate_scopes(payload.scopes)
    now = utcnow()
    _enforce_active_token_quota(db, current_user.id, now)
    raw_token = secrets.token_urlsafe(32)
    agent_user = models.User(
        username=_new_agent_username(db, current_user.id),
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_admin=False,
        role=models.USER_ROLE_AGENT,
    )
    agent_token = models.AgentToken(
        agent_user=agent_user,
        owner_user_id=current_user.id,
        token_hash=hash_agent_token(raw_token),
        scope_json=_scope_json(scopes),
        expires_at=now + timedelta(days=payload.expires_in_days),
    )
    db.add_all([agent_user, agent_token])
    db.flush()
    _audit_token_management(
        db,
        owner_user_id=current_user.id,
        agent_user_id=agent_user.id,
        action="create",
        token_id=agent_token.id,
        scopes=scopes,
    )
    db.commit()
    db.refresh(agent_token)
    public = _public_token(agent_token)
    return AgentTokenCreated(**public.model_dump(), token=raw_token)


@router.get("", response_model=list[AgentTokenPublic])
def list_agent_tokens(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> list[AgentTokenPublic]:
    tokens = (
        db.execute(
            select(models.AgentToken)
            .where(models.AgentToken.owner_user_id == current_user.id)
            .order_by(models.AgentToken.created_at.desc(), models.AgentToken.id.desc())
        )
        .scalars()
        .all()
    )
    return [_public_token(token) for token in tokens]


@router.delete("/{token_id}", response_model=AgentTokenPublic)
def revoke_agent_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
) -> AgentTokenPublic:
    token = db.execute(
        select(models.AgentToken).where(
            models.AgentToken.id == token_id,
            models.AgentToken.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if token.revoked_at is None:
        token.revoked_at = utcnow()
        _audit_token_management(
            db,
            owner_user_id=current_user.id,
            agent_user_id=token.agent_user_id,
            action="revoke",
            token_id=token.id,
            scopes=_scopes_from_json(token.scope_json),
        )
        db.commit()
        db.refresh(token)

    return _public_token(token)
