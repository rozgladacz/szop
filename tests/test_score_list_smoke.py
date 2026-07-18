from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.routers import roster_scoring as router_module
from app.security import hash_agent_token
from app.services import roster_scoring as scoring_service
from mcp_server.config import McpConfig
from mcp_server.server import create_server
from szop_client import HttpClient, HttpRequest, HttpResponse


async def _call_score_list_tool(server, arguments):
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as mcp_session:
        return await mcp_session.call_tool("score_list", arguments)


def _model_rows(session: Session, model) -> tuple[tuple, ...]:
    columns = tuple(model.__table__.columns)
    rows = session.scalars(select(model).order_by(model.id)).all()
    return tuple(
        tuple(getattr(row, column.name) for column in columns)
        for row in rows
    )


def _domain_snapshot(session: Session) -> dict[str, tuple[tuple, ...]]:
    return {
        "rosters": _model_rows(session, models.Roster),
        "roster_units": _model_rows(session, models.RosterUnit),
        "battles": _model_rows(session, models.Battle),
        "battle_events": _model_rows(session, models.BattleEvent),
        "units": _model_rows(session, models.Unit),
        "unit_weapons": _model_rows(session, models.UnitWeapon),
        "weapons": _model_rows(session, models.Weapon),
        "abilities": _model_rows(session, models.Ability),
        "agent_tokens": _model_rows(session, models.AgentToken),
    }


def test_real_seeded_service_endpoint_http_client_and_mcp_score_list_smoke() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    raw_token = "real-score-list-smoke-token"

    with sessions() as session:
        owner = models.User(username="score-smoke-owner", password_hash="x")
        outsider = models.User(username="score-smoke-outsider", password_hash="x")
        agent = models.User(
            username="score-smoke-agent",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name="Score smoke rules")
        armory = models.Armory(name="Score smoke armory", owner=owner)
        session.add_all([owner, outsider, agent, ruleset, armory])
        session.flush()
        army = models.Army(
            name="Score smoke army",
            owner=owner,
            ruleset=ruleset,
            armory=armory,
        )
        blade = models.Weapon(
            armory=armory,
            name="Score smoke blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
        )
        session.add_all([army, blade])
        session.flush()
        unit = models.Unit(
            army=army,
            name="Score smoke unit",
            quality=4,
            defense=5,
            toughness=3,
            typical_models=1,
            position=0,
            default_weapon=blade,
        )
        session.add(unit)
        session.flush()
        session.add(
            models.UnitWeapon(
                unit=unit,
                weapon=blade,
                is_default=True,
                default_count=1,
                is_primary=True,
                position=0,
            )
        )

        rosters: list[models.Roster] = []
        for name in ("Target", "Opponent A", "Opponent B"):
            roster = models.Roster(name=name, army=army, owner=owner)
            session.add(roster)
            session.flush()
            session.add(
                models.RosterUnit(
                    roster=roster,
                    unit=unit,
                    count=1,
                    position=0,
                )
            )
            rosters.append(roster)
        foreign = models.Roster(name="Foreign roster", army=army, owner=outsider)
        session.add(foreign)
        session.flush()
        session.add(
            models.RosterUnit(
                roster=foreign,
                unit=unit,
                count=1,
                position=0,
            )
        )
        session.add(
            models.AgentToken(
                agent_user=agent,
                owner_user=owner,
                token_hash=hash_agent_token(raw_token),
                scope_json=json.dumps({router_module.ROSTER_SCORE_SCOPE: True}),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(days=1),
            )
        )
        session.commit()
        owner_id = owner.id
        target_id = rosters[0].id
        opponent_ids = [rosters[1].id, rosters[2].id]
        foreign_id = foreign.id
        before = _domain_snapshot(session)

    with sessions() as session:
        target, results = scoring_service.score_list(
            session,
            target_id,
            bot="random",
            n=1,
            seed=5,
            map_name="lustrzana_a",
            owner_user_id=owner_id,
            allowed_bots=("random",),
            max_opponents=scoring_service.MAX_SCORE_OPPONENTS,
            max_total_games=scoring_service.MAX_SCORE_TOTAL_GAMES,
        )
        direct_payload = scoring_service.score_list_to_dict(
            target,
            results,
            games_per_opponent=1,
            bot="random",
            seed=5,
            map_name="lustrzana_a",
        )
    assert direct_payload["parameters"]["opponent_roster_ids"] == opponent_ids
    assert foreign_id not in direct_payload["parameters"]["opponent_roster_ids"]

    test_app = FastAPI()
    test_app.include_router(router_module.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    body = {
        "games_per_opponent": 1,
        "bot": "random",
        "seed": 5,
        "map_name": "lustrzana_a",
    }
    with TestClient(test_app) as api_client:
        authorization = {"Authorization": f"Bearer {raw_token}"}
        endpoint_response = api_client.post(
            f"/rosters/{target_id}/score",
            headers=authorization,
            json=body,
        )
        assert endpoint_response.status_code == 200, endpoint_response.text

        def transport(request: HttpRequest) -> HttpResponse:
            parsed = urlsplit(request.url)
            response = api_client.request(
                request.method,
                parsed.path + (f"?{parsed.query}" if parsed.query else ""),
                headers=request.headers,
                content=request.body,
            )
            return HttpResponse(status_code=response.status_code, body=response.content)

        http_client = HttpClient(
            "http://testserver",
            token=raw_token,
            transport=transport,
        )
        client_payload = http_client.score_list(
            target_id,
            games_per_opponent=1,
            bot="random",
            seed=5,
            map_name="lustrzana_a",
        )
        tool_result = asyncio.run(
            _call_score_list_tool(
                create_server(
                    McpConfig("http://testserver", raw_token),
                    client=http_client,
                ),
                {
                    "roster_id": target_id,
                    "games_per_opponent": 1,
                    "bot": "random",
                    "seed": 5,
                    "map_name": "lustrzana_a",
                },
            )
        )
        foreign_response = api_client.post(
            f"/rosters/{target_id}/score",
            headers=authorization,
            json={**body, "opponent_roster_ids": [foreign_id]},
        )

    assert endpoint_response.json() == direct_payload
    assert client_payload == direct_payload
    assert tool_result.structuredContent == direct_payload
    assert foreign_response.status_code == 404
    assert foreign_response.json() == {"detail": "Roster not found"}
    json.dumps(direct_payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

    with sessions() as session:
        after = _domain_snapshot(session)
        audits = session.scalars(
            select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
        ).all()
    assert after == before
    assert len(audits) == 4
    for audit in audits:
        observed = audit.params_json
        assert raw_token not in observed
        assert str(foreign_id) not in observed
        assert "Opponent A" not in observed
        assert "Opponent B" not in observed
        assert "Foreign roster" not in observed
        assert "points" not in observed
        assert "wins" not in observed
        assert "random" not in observed
        assert "lustrzana_a" not in observed
