"""Same-origin owner transport for durable priority/v1 attempts."""

import json
import re
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..bot_proposal_security import (
    PRIVATE_RESPONSE,
    configured_proposal_origin,
    owner_session_claim,
    require_proposal_origin,
)
from ..db import get_db
from ..services.bot_proposal_attempts import (
    BotProposalAttemptError,
    BotProposalAttemptResult,
    BotProposalCommand,
    create_bot_proposal_attempt,
    get_bot_proposal_attempt,
)
from ..services.bot_proposal_producer import prepare_bot_proposal

router = APIRouter(prefix="/battles", tags=["bot_proposals"])
_ATTEMPT_PATH = "/{battle_id}/bot-proposal-attempts/{attempt_id}"
_BATTLE_ID = re.compile(r"[1-9][0-9]{0,15}")
_JSON_MEDIA = re.compile(r'application/json(?:[ \t]*;[ \t]*charset[ \t]*=[ \t]*(?:utf-8|"utf-8"))?', re.I)
_MAX_COMMAND_BYTES = 1024
_ERROR_STATUS = {
    "owner_session_required": 401,
    "not_found": 404,
    "attempt_payload_conflict": 409,
    "attempt_expired": 410,
    "command_too_large": 413,
    "unsupported_media_type": 415,
    "invalid_command": 422,
    "attempt_temporarily_unavailable": 503,
}


def _failure(code: str) -> HTTPException:
    return HTTPException(_ERROR_STATUS[code], detail={"code": code}, headers=PRIVATE_RESPONSE)


def _owner_credentials(request: Request, db: Session) -> tuple[Engine, int, datetime]:
    engine = db.get_bind()
    if not isinstance(engine, Engine) or engine.dialect.name != "sqlite" or configured_proposal_origin() is None:
        raise _failure("not_found")
    claim = owner_session_claim(request)
    if claim is None:
        raise _failure("owner_session_required")
    return engine, *claim


def _battle_id(value: str) -> int:
    if _BATTLE_ID.fullmatch(value) is None:
        raise _failure("invalid_command")
    return int(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document = dict(pairs)
    if len(pairs) != len(document):
        raise ValueError("Duplicate command key")
    return document


async def _read_command(request: Request, battle_id: str, attempt_id: str) -> BotProposalCommand:
    media = request.headers.getlist("content-type")
    if len(media) != 1 or _JSON_MEDIA.fullmatch(media[0]) is None:
        raise _failure("unsupported_media_type")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_COMMAND_BYTES:
            raise _failure("command_too_large")
        body.extend(chunk)
    try:
        document = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
        return BotProposalCommand(battle_id=_battle_id(battle_id), attempt_id=attempt_id, **document)
    except (ValueError, TypeError, RecursionError):
        raise _failure("invalid_command") from None


def _reply(result: BotProposalAttemptResult, *, created: bool = False) -> JSONResponse:
    body = asdict(result)
    body["created_at"] = result.created_at.isoformat() + "Z"
    body["expires_at"] = result.expires_at.isoformat() + "Z"
    headers = PRIVATE_RESPONSE.copy()
    if created:
        headers["Location"] = f"/battles/{result.battle_id}/bot-proposal-attempts/{result.attempt_id}"
    return JSONResponse(body, status_code=201 if created else 200, headers=headers)


@router.post(_ATTEMPT_PATH, status_code=201)
async def register_attempt(
    battle_id: str, attempt_id: str, request: Request, db: Session = Depends(get_db),
) -> JSONResponse:
    engine, owner_id, generation = _owner_credentials(request, db)
    require_proposal_origin(request)
    command = await _read_command(request, battle_id, attempt_id)
    try:
        result, created = await run_in_threadpool(
            create_bot_proposal_attempt, engine, command,
            owner_user_id=owner_id, owner_created_at=generation, decide=prepare_bot_proposal,
        )
    except BotProposalAttemptError as exc:
        raise _failure(exc.code) from None
    except OperationalError:
        raise _failure("attempt_temporarily_unavailable") from None
    return _reply(result, created=created)


@router.get(_ATTEMPT_PATH)
def read_attempt(
    battle_id: str, attempt_id: str, request: Request, db: Session = Depends(get_db),
) -> JSONResponse:
    engine, owner_id, generation = _owner_credentials(request, db)
    try:
        result = get_bot_proposal_attempt(
            engine, battle_id=_battle_id(battle_id), attempt_id=attempt_id,
            owner_user_id=owner_id, owner_created_at=generation,
        )
    except BotProposalAttemptError as exc:
        raise _failure(exc.code) from None
    except OperationalError:
        raise _failure("attempt_temporarily_unavailable") from None
    return _reply(result)
