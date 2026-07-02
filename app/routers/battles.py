from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import get_current_user, require_agent_scope
from ..services.engine.events import BattleEvent as EngineBattleEvent
from ..services.engine.events import event_to_json
from ..services.engine.persistence import load_events

router = APIRouter(prefix="/battles", tags=["battles"])

BATTLE_READ_SCOPE = "battle:read"


@dataclass(frozen=True)
class BattleReader:
    user_id: int


class BattleEventPublic(BaseModel):
    sequence: int = Field(..., ge=1)
    event_type: str
    payload: dict[str, Any]


class BattleEventsPublic(BaseModel):
    battle_id: int
    events: list[BattleEventPublic]


def _authorization_header(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if value is None:
        value = request.headers.get("Authorization")
    return value


def _has_authorization_header(request: Request) -> bool:
    value = _authorization_header(request)
    return bool(value and value.strip())


def _battle_reader(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleReader:
    if _has_authorization_header(request):
        principal = require_agent_scope(BATTLE_READ_SCOPE)(request=request, db=db)
        return BattleReader(user_id=principal.owner_user_id)

    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return BattleReader(user_id=current_user.id)


def _get_accessible_battle(
    db: Session, *, battle_id: int, reader: BattleReader
) -> models.Battle:
    battle = db.execute(
        select(models.Battle).where(
            models.Battle.id == battle_id,
            or_(
                models.Battle.p1_user_id == reader.user_id,
                models.Battle.p2_user_id == reader.user_id,
            ),
        )
    ).scalar_one_or_none()
    if battle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return battle


def _public_event(event: EngineBattleEvent) -> BattleEventPublic:
    payload = event_to_json(event)
    return BattleEventPublic(
        sequence=int(payload["sequence"]),
        event_type=str(payload["event_type"]),
        payload=payload,
    )


@router.get("/{battle_id}/events", response_model=BattleEventsPublic)
def get_battle_events(
    battle_id: int,
    since: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleEventsPublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    events = load_events(db, battle.id, since=since)
    return BattleEventsPublic(
        battle_id=battle.id,
        events=[_public_event(event) for event in events],
    )
