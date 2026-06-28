from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.main import app
from app.routers import agent_tokens
from app.security import hash_agent_token, hash_password


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_user(
    session: Session,
    *,
    username: str = "owner",
    role: str = models.USER_ROLE_USER,
    is_admin: bool = False,
) -> models.User:
    user = models.User(
        username=username,
        password_hash=hash_password("haslo"),
        role=role,
        is_admin=is_admin,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _create_token(
    session: Session,
    owner: models.User,
    *,
    scopes: list[str] | None = None,
    expires_in_days: int = 30,
) -> agent_tokens.AgentTokenCreated:
    return agent_tokens.create_agent_token(
        agent_tokens.AgentTokenCreate(
            scopes=scopes or ["battle:read"],
            expires_in_days=expires_in_days,
        ),
        db=session,
        current_user=owner,
    )


def _count_rows(session: Session, model: type[object]) -> int:
    count = session.execute(select(func.count()).select_from(model)).scalar_one()
    return int(count or 0)


def _count_agent_users(session: Session) -> int:
    count = session.execute(
        select(func.count(models.User.id)).where(
            models.User.role == models.USER_ROLE_AGENT
        )
    ).scalar_one()
    return int(count or 0)


def test_create_agent_token_returns_raw_secret_once_and_persists_only_hash() -> None:
    session = _build_session()
    owner = _seed_user(session)

    response = _create_token(session, owner, scopes=["battle:read", "battle:read"])

    assert response.token
    assert response.owner_user_id == owner.id
    assert response.scopes == ["battle:read"]
    assert response.revoked_at is None
    assert response.last_used_at is None
    assert response.expires_at > datetime.now(UTC).replace(tzinfo=None)

    stored = session.get(models.AgentToken, response.id)
    assert stored is not None
    assert stored.token_hash == hash_agent_token(response.token)
    assert response.token not in stored.token_hash
    assert json.loads(stored.scope_json) == {"battle:read": True}

    agent = session.get(models.User, response.agent_user_id)
    assert agent is not None
    assert agent.role == models.USER_ROLE_AGENT
    assert not agent.is_admin
    assert agent.username == response.agent_username

    audit = session.execute(select(models.AgentAuditLog)).scalars().all()
    assert len(audit) == 1
    assert audit[0].user_id == owner.id
    assert audit[0].agent_user_id == agent.id
    assert response.token not in audit[0].params_json
    assert json.loads(audit[0].params_json)["action"] == "create"


def test_agent_tokens_router_is_registered_in_app() -> None:
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/agent_tokens" in route_paths
    assert "/agent_tokens/{token_id}" in route_paths


def test_list_agent_tokens_filters_owner_and_never_returns_raw_secret() -> None:
    session = _build_session()
    owner = _seed_user(session, username="owner")
    other_owner = _seed_user(session, username="other")
    own_token = _create_token(session, owner, scopes=["battle:read"])
    _create_token(session, other_owner, scopes=["battle:write"])

    tokens = agent_tokens.list_agent_tokens(db=session, current_user=owner)

    assert [token.id for token in tokens] == [own_token.id]
    assert tokens[0].scopes == ["battle:read"]
    assert not hasattr(tokens[0], "token")


def test_create_agent_token_rejects_active_token_quota_without_side_effects() -> None:
    session = _build_session()
    owner = _seed_user(session)
    for _ in range(agent_tokens._MAX_ACTIVE_TOKENS_PER_OWNER):
        _create_token(session, owner)
    before_tokens = _count_rows(session, models.AgentToken)
    before_agent_users = _count_agent_users(session)
    before_audit_logs = _count_rows(session, models.AgentAuditLog)

    with pytest.raises(HTTPException) as exc_info:
        _create_token(session, owner)

    assert exc_info.value.status_code == 409
    assert "active agent tokens" in exc_info.value.detail
    assert _count_rows(session, models.AgentToken) == before_tokens
    assert _count_agent_users(session) == before_agent_users
    assert _count_rows(session, models.AgentAuditLog) == before_audit_logs


def test_create_agent_token_quota_ignores_revoked_and_expired_tokens() -> None:
    session = _build_session()
    owner = _seed_user(session)
    created = [
        _create_token(session, owner)
        for _ in range(agent_tokens._MAX_ACTIVE_TOKENS_PER_OWNER)
    ]
    revoked = session.get(models.AgentToken, created[0].id)
    expired = session.get(models.AgentToken, created[1].id)
    assert revoked is not None
    assert expired is not None
    revoked.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    expired.expires_at = datetime(2000, 1, 1)
    session.commit()

    response = _create_token(session, owner)

    assert response.id not in {token.id for token in created}
    assert response.revoked_at is None


def test_revoke_agent_token_only_for_owner_and_is_idempotent() -> None:
    session = _build_session()
    owner = _seed_user(session, username="owner")
    other_owner = _seed_user(session, username="other")
    created = _create_token(session, owner)

    with pytest.raises(HTTPException) as exc_info:
        agent_tokens.revoke_agent_token(
            created.id,
            db=session,
            current_user=other_owner,
        )
    assert exc_info.value.status_code == 404
    assert session.get(models.AgentToken, created.id).revoked_at is None

    revoked = agent_tokens.revoke_agent_token(
        created.id,
        db=session,
        current_user=owner,
    )
    assert revoked.revoked_at is not None

    revoked_again = agent_tokens.revoke_agent_token(
        created.id,
        db=session,
        current_user=owner,
    )
    assert revoked_again.revoked_at == revoked.revoked_at

    audit_actions = [
        json.loads(audit.params_json)["action"]
        for audit in session.execute(select(models.AgentAuditLog)).scalars().all()
    ]
    assert audit_actions == ["create", "revoke"]


@pytest.mark.parametrize(
    "scopes",
    [
        [],
        ["bad scope"],
        ["Battle:Read"],
        ["*"],
        ["*", "battle:read"],
        [f"battle:{index}" for index in range(21)],
    ],
)
def test_create_agent_token_scope_validation(scopes: list[str]) -> None:
    session = _build_session()
    owner = _seed_user(session)
    payload_scopes = scopes if 0 < len(scopes) <= 20 else ["battle:read"]
    payload = agent_tokens.AgentTokenCreate(scopes=payload_scopes)
    if len(scopes) == 0 or len(scopes) > 20:
        payload.scopes = scopes

    if scopes == ["*"]:
        response = agent_tokens.create_agent_token(payload, db=session, current_user=owner)
        assert response.scopes == ["*"]
        return

    with pytest.raises(HTTPException) as exc_info:
        agent_tokens.create_agent_token(payload, db=session, current_user=owner)

    assert exc_info.value.status_code == 400
    assert session.execute(select(models.AgentToken)).scalar_one_or_none() is None
    assert (
        session.execute(
            select(models.User).where(models.User.role == models.USER_ROLE_AGENT)
        ).scalar_one_or_none()
        is None
    )
