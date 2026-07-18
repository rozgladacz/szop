import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .db import get_db, utcnow

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)

# Dozwolone znaki nazwy użytkownika: litery (w tym Unicode/polskie), cyfry,
# podkreślenie, spacja, kropka i myślnik. Whitelist celowo NIE dopuszcza
# cudzysłowów, nawiasów ostrokątnych, ampersanda ani innych znaków, które
# mogłyby wyłamać się z kontekstu HTML/JS przy renderowaniu nazwy.
USERNAME_MAX_LENGTH = 64
_USERNAME_RE = re.compile(r"^[\w][\w .\-]{0,%d}$" % (USERNAME_MAX_LENGTH - 1), re.UNICODE)
_AGENT_TOKEN_HASH_PREFIX = "sha256:"
_SECRET_PARAM_PARTS = (
    "authorization",
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
)


@dataclass(frozen=True)
class AgentPrincipal:
    """Authenticated agent identity returned by agent-token dependencies."""

    agent_user_id: int
    owner_user_id: int
    token_id: int
    scopes: frozenset[str]


def is_valid_username(username: str) -> bool:
    """Czy nazwa użytkownika zawiera wyłącznie bezpieczne znaki."""
    return bool(_USERNAME_RE.fullmatch(username))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def hash_agent_token(token: str) -> str:
    """Return the stable hash persisted for bearer agent tokens."""
    return _AGENT_TOKEN_HASH_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_bcrypt_hash(hashed_password: str) -> bool:
    return hashed_password.startswith(("$2a$", "$2b$", "$2y$", "$2$"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if _is_bcrypt_hash(hashed_password):
        # Legacy bcrypt hashes are limited to 72 bytes; truncate to avoid backend errors.
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8"),
        )
    return pwd_context.verify(plain_password, hashed_password)


def get_current_user(optional: bool = False, *, close_session: bool = False):
    def dependency(
        request: Request, db: Session = Depends(get_db)
    ) -> Optional[models.User]:
        user_id = request.session.get("user_id")
        if not user_id:
            if optional:
                return None
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        user = db.get(models.User, user_id)
        if user is None:
            request.session.pop("user_id", None)
            if optional:
                return None
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        if close_session:
            db.expunge(user)
            db.close()

        return user

    return dependency


def _unauthorized_agent() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authorization_header(request: Request) -> str | None:
    headers = getattr(request, "headers", {})
    value = headers.get("authorization")
    if value is None:
        value = headers.get("Authorization")
    return value


def _extract_bearer_token(request: Request) -> str:
    authorization = _authorization_header(request)
    if not authorization:
        raise _unauthorized_agent()

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise _unauthorized_agent()
    return token.strip()


def _parse_agent_scopes(scope_json: str) -> frozenset[str]:
    try:
        payload = json.loads(scope_json or "{}")
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(key for key, value in payload.items() if value is True)


def _scope_allows(scopes: frozenset[str], scope_name: str) -> bool:
    return "*" in scopes or scope_name in scopes


def _redacted_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        normalized_key = str(key).lower()
        if any(part in normalized_key for part in _SECRET_PARAM_PARTS):
            redacted[str(key)] = "[REDACTED]"
        else:
            redacted[str(key)] = value
    return redacted


def _agent_audit_payload(
    request: Request,
    scope_names: tuple[str, ...],
    *,
    include_query_params: bool = True,
) -> str:
    path_params = getattr(request, "path_params", {}) or {}
    query_params = (
        (getattr(request, "query_params", {}) or {})
        if include_query_params
        else {}
    )
    payload = {
        "method": getattr(request, "method", ""),
        "path_params": _redacted_mapping(dict(path_params)),
        "query_params": _redacted_mapping(dict(query_params)),
        "status": "authorized",
    }
    if len(scope_names) == 1:
        payload["scope"] = scope_names[0]
    else:
        payload["scopes"] = list(scope_names)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _request_path(request: Request) -> str:
    url = getattr(request, "url", None)
    path = getattr(url, "path", None)
    if path:
        return path
    scope = getattr(request, "scope", {}) or {}
    return str(scope.get("path", ""))


def _authenticate_agent(
    request: Request,
    db: Session,
    scope_names: tuple[str, ...],
    *,
    audit_query_params: bool = True,
    update_last_used_at: bool = True,
) -> AgentPrincipal:
    token_hash = hash_agent_token(_extract_bearer_token(request))
    token = db.execute(
        select(models.AgentToken).where(models.AgentToken.token_hash == token_hash)
    ).scalar_one_or_none()
    now = utcnow()
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise _unauthorized_agent()

    agent_user = token.agent_user
    if agent_user is None or agent_user.role != models.USER_ROLE_AGENT:
        raise _unauthorized_agent()

    scopes = _parse_agent_scopes(token.scope_json)
    if not all(_scope_allows(scopes, scope_name) for scope_name in scope_names):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    principal = AgentPrincipal(
        agent_user_id=token.agent_user_id,
        owner_user_id=token.owner_user_id,
        token_id=token.id,
        scopes=scopes,
    )
    if update_last_used_at:
        token.last_used_at = now
    db.add(
        models.AgentAuditLog(
            user_id=token.owner_user_id,
            agent_user_id=token.agent_user_id,
            route=_request_path(request),
            params_json=_agent_audit_payload(
                request,
                scope_names,
                include_query_params=audit_query_params,
            ),
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return principal


def require_agent_scope(
    scope_name: str,
    *,
    audit_query_params: bool = True,
    update_last_used_at: bool = True,
):
    """FastAPI dependency factory for scoped bearer-token agent access."""

    return require_agent_scopes(
        scope_name,
        audit_query_params=audit_query_params,
        update_last_used_at=update_last_used_at,
    )


def require_agent_scopes(
    *scope_names: str,
    audit_query_params: bool = True,
    update_last_used_at: bool = True,
):
    """FastAPI dependency requiring every named scope on one bearer token."""
    required = tuple(scope_names)
    if not required:
        raise ValueError("at least one agent scope is required")

    def dependency(
        request: Request, db: Session = Depends(get_db)
    ) -> AgentPrincipal:
        return _authenticate_agent(
            request,
            db,
            required,
            audit_query_params=audit_query_params,
            update_last_used_at=update_last_used_at,
        )

    return dependency
