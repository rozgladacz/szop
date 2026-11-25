from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..db import get_db
from ..i18n import language_for, set_language_cookie
from ..paths import TEMPLATES_DIR
from ..security import (
    get_current_user,
    hash_password,
    is_valid_username,
    pwd_context,
    verify_password,
)
from ..services import public_access
from ..services.settings import get_registration_open
from ..templating import Jinja2Templates

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _logged_in(request: Request, user: models.User, token: str | None = None):
    request.state.language = user.preferred_language
    request.session.clear()
    if token is None:
        request.session["user_id"] = user.id
    else:
        request.session[public_access.SESSION_KEY] = token
    return set_language_cookie(RedirectResponse(url="/", status_code=303), user.preferred_language, secure=config.SESSION_HTTPS_ONLY)


def _login_response(request: Request, error: str | None = None, status_code: int = 200, headers=None):
    return templates.TemplateResponse(
        "auth_login.html", {"request": request, "error": error}, status_code=status_code, headers=headers,
    )


def _registration_response(request: Request, registration_open: bool, error=None, status_code=200, headers=None):
    protected = bool(config.PUBLIC_ORIGIN and registration_open)
    return templates.TemplateResponse(
        "auth_register.html",
        {
            "request": request, "error": error, "registration_open": registration_open,
            "form_token": public_access.issue_form(request) if protected else None,
            "requires_code": protected and bool(public_access.REGISTRATION_CODE),
            "password_min": public_access.PLAYER_PASSWORD_MIN if protected else None,
            "password_max": public_access.PASSWORD_MAX if protected else None,
            "password_requirements": public_access.password_requirements(public_access.PLAYER_PASSWORD_MIN),
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    current_user: Annotated[models.User | None, Depends(get_current_user(optional=True))],
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return _login_response(request)


@router.post("/login")
def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
):
    if config.PUBLIC_ORIGIN:
        retry = public_access.attempts.retry_after("login", request, username)
        if retry is not None:
            return _login_response(request, public_access.ATTEMPT_ERROR, 429, {"Retry-After": str(retry)})
    user = db.execute(select(models.User).where(models.User.username == username)).scalar_one_or_none()
    if config.PUBLIC_ORIGIN and user is None:
        pwd_context.dummy_verify()
    if not user or not verify_password(password, user.password_hash):
        return _login_response(request, public_access.LOGIN_ERROR, 400)
    updated_language = user.preferred_language not in ("pl", "en")
    if updated_language:
        user.preferred_language = language_for(request)
    token = public_access.add_session(db, user) if config.PUBLIC_ORIGIN else None
    if token is not None or updated_language:
        db.commit()
    return _logged_in(request, user, token)


@router.get("/register", response_class=HTMLResponse)
def register_form(
    request: Request,
    current_user: Annotated[models.User | None, Depends(get_current_user(optional=True))],
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return _registration_response(request, get_registration_open())


@router.post("/register")
def register(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    form_token: Annotated[str, Form()] = "",
    website: Annotated[str, Form()] = "",
    access_code: Annotated[str, Form()] = "",
):
    if not get_registration_open():
        return _registration_response(request, False, status_code=403)
    if config.PUBLIC_ORIGIN:
        retry = public_access.attempts.retry_after("register", request)
        if retry is not None:
            return _registration_response(request, True, public_access.ATTEMPT_ERROR, 429, {"Retry-After": str(retry)})
        if not public_access.valid_form(request, form_token, website, access_code):
            return _registration_response(request, True, public_access.FORM_ERROR, 400)
        if not public_access.valid_password(password, minimum=public_access.PLAYER_PASSWORD_MIN):
            return _registration_response(request, True, public_access.password_requirements(public_access.PLAYER_PASSWORD_MIN), 400)
    username = username.strip()
    if not is_valid_username(username):
        return _registration_response(
            request, True, "Nazwa użytkownika może zawierać tylko litery, cyfry, spację oraz znaki . _ -", 400,
        )
    language = language_for(request)
    if config.PUBLIC_ORIGIN:
        try:
            user, token = public_access.register_account(db, username, hash_password(password), language)
        except HTTPException as exc:
            return _registration_response(request, True, exc.detail, exc.status_code, exc.headers)
        return _logged_in(request, user, token)

    existing = db.execute(select(models.User).where(models.User.username == username)).scalar_one_or_none()
    if existing:
        return _registration_response(request, True, "Użytkownik o takiej nazwie już istnieje", 400)
    user = models.User(username=username, password_hash=hash_password(password), preferred_language=language)
    db.add(user)
    db.commit()
    return _logged_in(request, user)


@router.post("/logout")
def logout(request: Request, db: Annotated[Session, Depends(get_db)]):
    token = request.session.get(public_access.SESSION_KEY)
    if config.PUBLIC_ORIGIN and isinstance(token, str):
        public_access.revoke_session(db, token)
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
