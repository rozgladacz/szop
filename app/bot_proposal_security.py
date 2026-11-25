"""Session generation and same-origin guards for owner-driven bot proposals."""

from datetime import datetime
from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from . import config, models

PRIVATE_RESPONSE = {"Cache-Control": "private, no-store"}
_GENERATION_KEY = "owner_created_at"
_OWNER_ROLES = (models.USER_ROLE_USER, models.USER_ROLE_ADMIN)
_AUTHORITY = re.compile(r"(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:.]+\])(?::[0-9]{1,5})?")


def set_owner_session(request: Request, user: models.User) -> None:
    request.session["user_id"] = user.id
    request.session[_GENERATION_KEY] = user.created_at.isoformat(timespec="microseconds")


def clear_owner_session(request: Request) -> None:
    request.session.pop("user_id", None)
    request.session.pop(_GENERATION_KEY, None)


def owner_session_claim(request: Request | None) -> tuple[int, datetime] | None:
    if request is None or "authorization" in request.headers:
        return None
    session = request.scope.get("session", {})
    user_id = session.get("user_id")
    raw = session.get(_GENERATION_KEY)
    if type(user_id) is not int or user_id <= 0 or not isinstance(raw, str):
        return None
    try:
        generation = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if generation.tzinfo is not None or raw != generation.isoformat(timespec="microseconds"):
        return None
    return user_id, generation


def matching_owner_generation(request: Request | None, user: models.User) -> datetime | None:
    if user.role in _OWNER_ROLES and owner_session_claim(request) == (user.id, user.created_at):
        return user.created_at
    return None


def _origin(value: str) -> tuple[str, str, int] | None:
    if any(char.isspace() or ord(char) < 32 or char in ",?#\\" for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.path or not _AUTHORITY.fullmatch(parsed.netloc)
        ):
            return None
        port = parsed.port
    except ValueError:
        return None
    if port == 0:
        return None
    return parsed.scheme, parsed.hostname, port or (443 if parsed.scheme == "https" else 80)


def configured_proposal_origin() -> tuple[str, str, int] | None:
    origin = _origin(config.BOT_PROPOSAL_ORIGIN)
    if origin is None:
        return None
    scheme, host, _ = origin
    if scheme == "https":
        return origin if config.SESSION_HTTPS_ONLY else None
    if host == "localhost":
        return origin
    try:
        return origin if ip_address(host).is_loopback else None
    except ValueError:
        return None


def require_proposal_origin(request: Request) -> None:
    values = request.headers.getlist("origin")
    expected = configured_proposal_origin()
    if expected is None or len(values) != 1 or _origin(values[0]) != expected:
        raise HTTPException(403, detail={"code": "origin_rejected"}, headers=PRIVATE_RESPONSE)
