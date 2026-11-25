from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import models
from .config import DEBUG, SECRET_KEY, SESSION_HTTPS_ONLY, TRUSTED_HOSTS
from .db import get_db, init_db
from .middleware_public import PublicAccessMiddleware
from .i18n import (
    LanguageMiddleware,
    javascript_catalog,
    language_for,
    safe_next,
    set_language_cookie,
    translate,
)
from .paths import STATIC_DIR, TEMPLATES_DIR
from .routers import (
    admin,
    armies,
    armories,
    auth,
    collections,
    export,
    export_xlsx,
    rosters,
    users,
)
from .security import get_current_user
from .services import costs
from .templating import Jinja2Templates

logger = logging.getLogger(__name__)

app = FastAPI(debug=DEBUG)

# Trusted-host guard — zapobiega atakom Host-header injection gdy za reverse proxy.
# Domyślnie "*" (wszystkie hosty dozwolone) — zawężamy przez TRUSTED_HOSTS w .env.
if TRUSTED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    # https_only=True aktywować gdy SESSION_HTTPS_ONLY=true (np. za Tailscale serve TLS)
    https_only=SESSION_HTTPS_ONLY,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


app.add_middleware(LanguageMiddleware)
app.add_middleware(PublicAccessMiddleware)


@app.get('/i18n/{language}.js', include_in_schema=False)
def translation_script(request: Request, language: str):
    if language not in ('pl', 'en'):
        raise HTTPException(404)
    request.state.language = language
    return Response(javascript_catalog(language), media_type='text/javascript',
                    headers={'Cache-Control': 'public, max-age=31536000, immutable'})


@app.exception_handler(StarletteHTTPException)
async def localized_http_error(request: Request, exc):
    detail = translate(exc.detail, language_for(request)) if isinstance(exc.detail, str) else exc.detail
    return JSONResponse({'detail': detail}, status_code=exc.status_code, headers=exc.headers)


@app.post('/language')
def change_language(
    request: Request,
    language: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User | None, Depends(get_current_user(optional=True))],
    next: Annotated[str, Form()] = '/',
):
    if language not in ('pl', 'en'):
        raise HTTPException(400, detail='Nieobsługiwany język')
    if current_user:
        current_user.preferred_language = language
        db.commit()
    request.state.language = language
    return set_language_cookie(RedirectResponse(safe_next(next), status_code=303), language, secure=SESSION_HTTPS_ONLY)


@app.get('/downloads', response_class=HTMLResponse)
def downloads(request: Request, current_user: Annotated[models.User | None, Depends(get_current_user(optional=True))]):
    folder = STATIC_DIR / 'docs'
    files = sorted((p.name for p in folder.iterdir() if p.suffix.lower() == '.pdf' and p.is_file() and not p.is_symlink()), key=str.casefold) if folder.exists() else []
    return templates.TemplateResponse('downloads.html', {'request': request, 'user': current_user, 'files': files})


@app.on_event("startup")
def startup_event() -> None:
    init_db()
    logger.info("Application started")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    army_query = select(models.Army).order_by(models.Army.created_at.desc()).limit(5)
    if not current_user.is_admin:
        army_query = army_query.where(
            or_(
                models.Army.owner_id == current_user.id,
                models.Army.owner_id.is_(None),
            )
        )
    armies = db.execute(army_query).scalars().all()
    roster_query = (
        select(models.Roster)
        .options(
            selectinload(models.Roster.roster_units),
            selectinload(models.Roster.army),
        )
        .order_by(models.Roster.created_at.desc())
        .limit(5)
    )
    if not current_user.is_admin:
        roster_query = roster_query.where(
            or_(
                models.Roster.owner_id == current_user.id,
                models.Roster.owner_id.is_(None),
            )
        )
    rosters_list = db.execute(roster_query).scalars().all()
    for roster in rosters_list:
        costs.ensure_cached_costs(roster.roster_units)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": current_user,
            "armies": armies,
            "rosters": rosters_list,
        },
    )


app.include_router(auth.router)
app.include_router(armories.router)
app.include_router(armies.router)
app.include_router(rosters.router)
app.include_router(collections.router)
app.include_router(export.router)
app.include_router(export_xlsx.router)
app.include_router(users.router)
app.include_router(admin.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg")
