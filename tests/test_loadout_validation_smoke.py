from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.routers import loadout_validation as router_module
from app.security import hash_agent_token
from app.services import loadout_validation as service
from mcp_server.config import McpConfig
from mcp_server.server import create_server
from szop_client import HttpClient, HttpRequest, HttpResponse


async def _call_validate_loadout_tool(server, arguments):
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as mcp_session:
        return await mcp_session.call_tool("validate_loadout", arguments)


def _table_counts(session: Session) -> dict[str, int]:
    classes = {
        "units": models.Unit,
        "unit_weapons": models.UnitWeapon,
        "unit_abilities": models.UnitAbility,
        "rosters": models.Roster,
        "roster_units": models.RosterUnit,
    }
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in classes.items()
    }


def test_real_seeded_service_endpoint_http_client_and_mcp_smoke() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    raw_token = "real-loadout-smoke-token"

    with sessions() as session:
        owner = models.User(username="smoke-owner", password_hash="x")
        agent = models.User(
            username="smoke-agent",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name="Smoke rules")
        armory = models.Armory(name="Smoke armory", owner=owner)
        session.add_all([owner, agent, ruleset, armory])
        session.flush()
        army = models.Army(
            name="Smoke army",
            owner=owner,
            ruleset=ruleset,
            armory=armory,
        )
        rifle = models.Weapon(
            armory=armory,
            name="Karabin",
            range="24",
            attacks=1,
            ap=0,
        )
        active = models.Ability(name="Furia", type="active", description="")
        session.add_all([army, rifle, active])
        session.flush()
        unit = models.Unit(
            army=army,
            name="Strzelcy smoke",
            quality=4,
            defense=5,
            toughness=3,
            typical_models=5,
            position=0,
            default_weapon=rifle,
        )
        session.add(unit)
        session.flush()
        session.add_all(
            [
                models.UnitWeapon(
                    unit=unit,
                    weapon=rifle,
                    is_default=True,
                    default_count=1,
                    is_primary=True,
                    position=0,
                ),
                models.UnitAbility(unit=unit, ability=active, position=0),
                models.AgentToken(
                    agent_user=agent,
                    owner_user=owner,
                    token_hash=hash_agent_token(raw_token),
                    scope_json=json.dumps(
                        {router_module.LOADOUT_VALIDATE_SCOPE: True}
                    ),
                    expires_at=datetime.now(UTC).replace(tzinfo=None)
                    + timedelta(days=1),
                ),
            ]
        )
        session.commit()
        unit_id = unit.id
        weapon_id = rifle.id
        active_id = active.id
        before_counts = _table_counts(session)

    loadout = {
        "mode": "invalid-mode",
        "weapons": {str(weapon_id): -2, "999999": 1},
        "active": {str(active_id): 1},
        "passive": {"unknown-passive": 1},
    }
    with sessions() as session:
        direct_payload = service.diff_to_dict(
            service.validate_loadout_by_id(session, unit_id, loadout, count=3)
        )

    test_app = FastAPI()
    test_app.include_router(router_module.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as api_client:
        authorization = {"Authorization": f"Bearer {raw_token}"}
        endpoint_response = api_client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=authorization,
            json={"loadout": loadout, "count": 3},
        )
        assert endpoint_response.status_code == 200

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
        client_payload = http_client.validate_loadout(unit_id, loadout, count=3)
        tool_result = asyncio.run(
            _call_validate_loadout_tool(
                create_server(
                    McpConfig("http://testserver", raw_token),
                    client=http_client,
                ),
                {"unit_id": unit_id, "loadout": loadout, "count": 3},
            )
        )

    assert endpoint_response.json() == direct_payload
    assert client_payload == direct_payload
    assert tool_result.structuredContent == direct_payload
    assert direct_payload["sections"][0]["accepted"]
    assert direct_payload["sections"][0]["rejected"]
    assert direct_payload["sections"][0]["clamped"]
    json.dumps(direct_payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

    with sessions() as session:
        assert _table_counts(session) == before_counts
        audits = session.scalars(
            select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
        ).all()
    assert len(audits) == 3
    for audit in audits:
        observed = audit.params_json
        assert raw_token not in observed
        assert "999999" not in observed
        assert "unknown-passive" not in observed
        assert "selected_total" not in observed
