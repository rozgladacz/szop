from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.security import hash_agent_token, require_agent_scope


RAW_TOKEN = "agent-secret-token"


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _fake_request(
    token: str | None = RAW_TOKEN,
    *,
    query_params: dict[str, str] | None = None,
) -> SimpleNamespace:
    headers = {}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return SimpleNamespace(
        headers=headers,
        method="GET",
        url=SimpleNamespace(path="/agent/battles/7"),
        path_params={"battle_id": "7"},
        query_params=query_params or {},
    )


def _seed_agent_token(
    session: Session,
    *,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
    expires_in: timedelta = timedelta(days=1),
    revoked: bool = False,
    agent_role: str = models.USER_ROLE_AGENT,
) -> models.AgentToken:
    owner = models.User(username="owner", password_hash="x")
    agent = models.User(username="agent", password_hash="x", role=agent_role)
    now = datetime.now(UTC).replace(tzinfo=None)
    token = models.AgentToken(
        agent_user=agent,
        owner_user=owner,
        token_hash=hash_agent_token(raw_token),
        scope_json=json.dumps(scopes or {"battle:read": True}),
        expires_at=now + expires_in,
        revoked_at=now if revoked else None,
    )
    session.add_all([owner, agent, token])
    session.commit()
    session.refresh(token)
    return token


def test_hash_agent_token_is_stable_and_does_not_store_raw_secret() -> None:
    hashed = hash_agent_token(RAW_TOKEN)

    assert hashed == hash_agent_token(RAW_TOKEN)
    assert hashed.startswith("sha256:")
    assert RAW_TOKEN not in hashed


def test_require_agent_scope_accepts_valid_bearer_token_and_audits_request() -> None:
    session = _build_session()
    token = _seed_agent_token(session)
    dependency = require_agent_scope("battle:read")

    principal = dependency(
        request=_fake_request(
            query_params={"token": "leaked", "q": "public", "api_key": "hidden"}
        ),
        db=session,
    )

    assert principal.agent_user_id == token.agent_user_id
    assert principal.owner_user_id == token.owner_user_id
    assert principal.token_id == token.id
    assert principal.scopes == frozenset({"battle:read"})

    session.refresh(token)
    assert token.last_used_at is not None

    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == token.owner_user_id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/agent/battles/7"
    payload = json.loads(audit.params_json)
    assert payload["scope"] == "battle:read"
    assert payload["path_params"] == {"battle_id": "7"}
    assert payload["query_params"] == {
        "token": "[REDACTED]",
        "q": "public",
        "api_key": "[REDACTED]",
    }
    assert RAW_TOKEN not in audit.params_json


def test_require_agent_scope_accepts_wildcard_scope() -> None:
    session = _build_session()
    token = _seed_agent_token(session, scopes={"*": True})

    principal = require_agent_scope("battle:write")(
        request=_fake_request(),
        db=session,
    )

    assert principal.token_id == token.id
    assert principal.scopes == frozenset({"*"})


def test_require_agent_scope_rejects_missing_bearer_token() -> None:
    session = _build_session()
    _seed_agent_token(session)

    with pytest.raises(HTTPException) as exc_info:
        require_agent_scope("battle:read")(request=_fake_request(token=None), db=session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_require_agent_scope_rejects_missing_scope_without_audit() -> None:
    session = _build_session()
    token = _seed_agent_token(session, scopes={"battle:read": True})

    with pytest.raises(HTTPException) as exc_info:
        require_agent_scope("battle:write")(request=_fake_request(), db=session)

    assert exc_info.value.status_code == 403
    session.refresh(token)
    assert token.last_used_at is None
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


@pytest.mark.parametrize(
    ("expires_in", "revoked"),
    [
        (timedelta(seconds=-1), False),
        (timedelta(days=1), True),
    ],
)
def test_require_agent_scope_rejects_expired_or_revoked_tokens(
    expires_in: timedelta, revoked: bool
) -> None:
    session = _build_session()
    token = _seed_agent_token(session, expires_in=expires_in, revoked=revoked)

    with pytest.raises(HTTPException) as exc_info:
        require_agent_scope("battle:read")(request=_fake_request(), db=session)

    assert exc_info.value.status_code == 401
    session.refresh(token)
    assert token.last_used_at is None
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_require_agent_scope_rejects_token_for_non_agent_user() -> None:
    session = _build_session()
    _seed_agent_token(session, agent_role=models.USER_ROLE_USER)

    with pytest.raises(HTTPException) as exc_info:
        require_agent_scope("battle:read")(request=_fake_request(), db=session)

    assert exc_info.value.status_code == 401
