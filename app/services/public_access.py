from __future__ import annotations

import hmac
import ipaddress
import math
import secrets
import time
from threading import Lock

from fastapi import HTTPException, Request
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import Float, ForeignKey, String, delete, func, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import config, models
from ..db import Base

MAX_ACCOUNTS = 100
REGISTER_INTERVAL = 60
REGISTRATION_CODE = config.PUBLIC_REGISTRATION_CODE
MIN_FORM_AGE = 2
FORM_LIFETIME = 15 * 60
SESSION_LIFETIME = 8 * 60 * 60
SESSION_KEY = "public_session"
SIGNUP_NONCE = "signup_nonce"
PLAYER_PASSWORD_MIN = 8
ADMIN_PASSWORD_MIN = 15
PASSWORD_MAX = 128
PASSWORD_REQUIREMENTS = "Hasło musi mieć od {minimum} do {maximum} znaków."
LOGIN_ERROR = "Nieprawidłowy login lub hasło"
ATTEMPT_ERROR = "Za dużo prób. Spróbuj ponownie później."
FORM_ERROR = "Sprawdź formularz rejestracji i spróbuj ponownie."


class RegistrationState(Base):
    __tablename__ = "public_registration_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_registration: Mapped[float] = mapped_column(Float)


class PublicSession(Base):
    __tablename__ = "public_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    credential: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float, index=True)


def _digest(purpose: str, value: str) -> str:
    return hmac.digest(config.SECRET_KEY.encode(), f"{purpose}:{value}".encode(), "sha256").hex()


class AttemptLimiter:
    """Bounded, process-local counters. Keys contain no raw addresses or usernames."""

    def __init__(self):
        self._lock = Lock()
        self._minute = -1
        self._counts: dict[tuple[str, str], int] = {}

    def retry_after(self, action: str, request: Request, username: str = "") -> int | None:
        host = request.client.host if request.client else ""
        try:
            address = ipaddress.ip_address(host)
            if isinstance(address, ipaddress.IPv6Address):
                host = str(address.ipv4_mapped or ipaddress.ip_network((address, 64), strict=False))
            else:
                host = str(address)
        except ValueError:
            host = "unknown"

        limits = [((action, _digest("network", host)), 10 if action == "login" else 5)]
        if action == "login":
            limits.append(((action, _digest("account", username.casefold())), 15))
        limits.append(((action, "all"), 60 if action == "login" else 30))

        with self._lock:
            minute, elapsed = divmod(int(time.monotonic()), 60)
            if minute != self._minute:
                self._counts.clear()
                self._minute = minute
            if any(self._counts.get(key, 0) >= limit for key, limit in limits):
                return 60 - elapsed
            for key, _ in limits:
                self._counts[key] = self._counts.get(key, 0) + 1
        return None


attempts = AttemptLimiter()


def valid_password(password: str, *, minimum: int) -> bool:
    return minimum <= len(password) <= PASSWORD_MAX and bool(password.strip())


def password_requirements(minimum: int) -> str:
    return PASSWORD_REQUIREMENTS.format(minimum=minimum, maximum=PASSWORD_MAX)


def _form_signer() -> URLSafeSerializer:
    return URLSafeSerializer(config.SECRET_KEY, salt="public-signup")


def issue_form(request: Request) -> str:
    nonce = request.session.get(SIGNUP_NONCE)
    if nonce is None:
        nonce = request.session[SIGNUP_NONCE] = secrets.token_urlsafe(24)
    return _form_signer().dumps([nonce, time.time()])


def valid_form(request: Request, form_token: str, website: str, access_code: str) -> bool:
    if website or not request.session.get(SIGNUP_NONCE):
        return False
    if REGISTRATION_CODE and not hmac.compare_digest(REGISTRATION_CODE.encode(), access_code.encode()):
        return False
    try:
        nonce, issued = _form_signer().loads(form_token)
        age = time.time() - issued
    except (BadData, ValueError, TypeError):
        return False
    return nonce == request.session[SIGNUP_NONCE] and MIN_FORM_AGE <= age <= FORM_LIFETIME


def add_session(db: Session, user: models.User) -> str:
    now = time.time()
    db.execute(delete(PublicSession).where(PublicSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(PublicSession(
        token=_digest("session", token),
        user_id=user.id,
        credential=_digest("credential", user.password_hash),
        expires_at=now + SESSION_LIFETIME,
    ))
    return token


def session_user(db: Session, token: str) -> models.User | None:
    row = db.execute(
        select(models.User, PublicSession.credential)
        .join(PublicSession, PublicSession.user_id == models.User.id)
        .where(PublicSession.token == _digest("session", token), PublicSession.expires_at > time.time())
    ).one_or_none()
    if row is None:
        return None
    user, credential = row
    if hmac.compare_digest(credential, _digest("credential", user.password_hash)):
        return user
    return None


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(PublicSession).where(PublicSession.token == _digest("session", token)))
    db.commit()


def register_account(db: Session, username: str, password_hash: str, language: str) -> tuple[models.User, str]:
    # Take the SQLite write lock before reading capacity or the rolling interval.
    # Hashing and form validation run before taking the lock.
    with db.begin():
        db.execute(text("BEGIN IMMEDIATE"))
        count = db.scalar(select(func.count()).select_from(models.User))
        if count >= MAX_ACCOUNTS:
            raise HTTPException(429, "Pula kont testowych jest pełna.")
        state = db.get(RegistrationState, 1)
        now = time.time()
        if state and now < state.last_registration + REGISTER_INTERVAL:
            wait = math.ceil(state.last_registration + REGISTER_INTERVAL - now)
            raise HTTPException(429, "Spróbuj ponownie za chwilę.", headers={"Retry-After": str(wait)})
        if db.scalar(select(models.User.id).where(models.User.username == username)) is not None:
            raise HTTPException(400, "Użytkownik o takiej nazwie już istnieje")

        user = models.User(username=username, password_hash=password_hash, preferred_language=language)
        db.add(user)
        db.flush()
        token = add_session(db, user)
        if state is None:
            db.add(RegistrationState(id=1, last_registration=now))
        else:
            state.last_registration = now
    return user, token
