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
from app.main import app
from app.routers import battles
from app.security import hash_agent_token, hash_password
from app.services.engine.events import MoveExecuted, StatusAdded
from app.services.engine.persistence import save_events

RAW_TOKEN = "battle-read-secret"


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_user(session: Session, username: str) -> models.User:
    user = models.User(username=username, password_hash=hash_password("haslo"))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_battle(
    session: Session,
    *,
    p1: models.User | None,
    p2: models.User | None,
) -> models.Battle:
    battle = models.Battle(
        p1_user_id=p1.id if p1 is not None else None,
        p2_user_id=p2.id if p2 is not None else None,
        rng_seed=2026,
        status="active",
    )
    session.add(battle)
    session.commit()
    session.refresh(battle)
    return battle


def _seed_events(session: Session, battle: models.Battle) -> None:
    save_events(
        session,
        battle.id,
        [
            MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1)),
            StatusAdded(sequence=2, target_id=1, status="Aktywowany"),
        ],
    )
    session.commit()


def _seed_agent_token(
    session: Session,
    *,
    owner: models.User,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
) -> models.AgentToken:
    agent = models.User(
        username=f"agent-{owner.id}",
        password_hash=hash_password("sekret"),
        role=models.USER_ROLE_AGENT,
    )
    token = models.AgentToken(
        agent_user=agent,
        owner_user=owner,
        token_hash=hash_agent_token(raw_token),
        scope_json=json.dumps(scopes or {battles.BATTLE_READ_SCOPE: True}),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    )
    session.add_all([agent, token])
    session.commit()
    session.refresh(token)
    return token


def _fake_request(
    token: str | None = RAW_TOKEN,
    *,
    battle_id: int = 7,
    query_params: dict[str, str] | None = None,
) -> SimpleNamespace:
    headers = {}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return SimpleNamespace(
        headers=headers,
        method="GET",
        url=SimpleNamespace(path=f"/battles/{battle_id}/events"),
        path_params={"battle_id": str(battle_id)},
        query_params=query_params or {},
    )


def test_battles_router_is_registered_in_app() -> None:
    route_paths = {getattr(route, "path", "") for route in app.routes}
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods_by_path.setdefault(path, set()).update(getattr(route, "methods", set()))

    assert "/battles/{battle_id}/events" in route_paths
    assert "GET" in methods_by_path["/battles/{battle_id}/events"]


def test_get_battle_events_returns_owner_scoped_event_log_with_since_filter() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    battle = _seed_battle(session, p1=owner, p2=opponent)
    _seed_events(session, battle)

    response = battles.get_battle_events(
        battle.id,
        since=1,
        db=session,
        reader=battles.BattleReader(user_id=owner.id),
    )

    assert response.battle_id == battle.id
    assert [event.sequence for event in response.events] == [2]
    assert response.events[0].event_type == "StatusAdded"
    assert response.events[0].payload["status"] == "Aktywowany"


def test_get_battle_events_rejects_non_participant_and_missing_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    stranger = _seed_user(session, "stranger")
    battle = _seed_battle(session, p1=owner, p2=opponent)

    with pytest.raises(HTTPException) as stranger_info:
        battles.get_battle_events(
            battle.id,
            db=session,
            reader=battles.BattleReader(user_id=stranger.id),
        )
    assert stranger_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.get_battle_events(
            battle.id + 999,
            db=session,
            reader=battles.BattleReader(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404


def test_battle_reader_accepts_session_user_without_agent_audit() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    reader = battles._battle_reader(
        request=_fake_request(token=None),
        db=session,
        current_user=owner,
    )

    assert reader == battles.BattleReader(user_id=owner.id)
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_battle_reader_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    token = _seed_agent_token(session, owner=owner)

    reader = battles._battle_reader(
        request=_fake_request(query_params={"since": "1", "token": "leaked"}),
        db=session,
        current_user=None,
    )

    assert reader == battles.BattleReader(user_id=owner.id)

    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/battles/7/events"
    payload = json.loads(audit.params_json)
    assert payload["scope"] == battles.BATTLE_READ_SCOPE
    assert payload["path_params"] == {"battle_id": "7"}
    assert payload["query_params"] == {"since": "1", "token": "[REDACTED]"}
    assert RAW_TOKEN not in audit.params_json


def test_battle_reader_rejects_missing_auth_and_missing_scope() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    with pytest.raises(HTTPException) as missing_info:
        battles._battle_reader(
            request=_fake_request(token=None),
            db=session,
            current_user=None,
        )
    assert missing_info.value.status_code == 401

    _seed_agent_token(
        session,
        owner=owner,
        scopes={"battle:write": True},
    )
    with pytest.raises(HTTPException) as scope_info:
        battles._battle_reader(
            request=_fake_request(),
            db=session,
            current_user=None,
        )
    assert scope_info.value.status_code == 403
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_agent_reader_cannot_read_battle_owned_by_other_user() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    other = _seed_user(session, "other")
    opponent = _seed_user(session, "opponent")
    _seed_agent_token(session, owner=owner)
    battle = _seed_battle(session, p1=other, p2=opponent)
    _seed_events(session, battle)

    reader = battles._battle_reader(
        request=_fake_request(battle_id=battle.id),
        db=session,
        current_user=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        battles.get_battle_events(battle.id, db=session, reader=reader)

    assert exc_info.value.status_code == 404
