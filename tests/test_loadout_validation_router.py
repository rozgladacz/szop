from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.main import app as main_app
from app.routers import loadout_validation as router_module
from app.security import hash_agent_token
from app.services import loadout_validation as service

RAW_TOKEN = "loadout-validation-secret"
PRIVATE_LOADOUT_VALUE = "private-loadout-marker"


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(router_module.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as client:
        yield client, sessions, engine


def _seed_catalog_and_token(
    sessions: sessionmaker[Session],
    *,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
    expires_in: timedelta = timedelta(days=1),
    revoked: bool = False,
) -> tuple[int, dict[str, int]]:
    with sessions() as session:
        owner = models.User(username=f"owner-{raw_token}", password_hash="x")
        agent = models.User(
            username=f"agent-{raw_token}",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name=f"Rules-{raw_token}")
        armory = models.Armory(name=f"Armory-{raw_token}", owner=owner)
        session.add_all([owner, agent, ruleset, armory])
        session.flush()
        army = models.Army(
            name=f"Army-{raw_token}",
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
        aura = models.Ability(name="Dowodzenie", type="aura", description="")
        session.add_all([army, rifle, active, aura])
        session.flush()
        unit = models.Unit(
            army=army,
            name="Strzelcy",
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
                models.UnitAbility(unit=unit, ability=aura, position=1),
            ]
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            models.AgentToken(
                agent_user=agent,
                owner_user=owner,
                token_hash=hash_agent_token(raw_token),
                scope_json=json.dumps(
                    scopes
                    if scopes is not None
                    else {router_module.LOADOUT_VALIDATE_SCOPE: True}
                ),
                expires_at=now + expires_in,
                revoked_at=now if revoked else None,
            )
        )
        session.commit()
        return unit.id, {"weapon": rifle.id, "active": active.id, "aura": aura.id}


def _authorization(raw_token: str = RAW_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def _mixed_loadout(ids: dict[str, int]) -> dict[str, object]:
    return {
        "mode": "invalid-mode",
        "weapons": {str(ids["weapon"]): -2, "99999": 1},
        "active": {str(ids["active"]): 1},
        "aura": {str(ids["aura"]): 1},
        "passive": {"unknown-passive": 1},
    }


def test_main_app_registers_agent_only_loadout_validation_post() -> None:
    methods_by_path = {
        route.path: getattr(route, "methods", set()) for route in main_app.routes
    }
    path = "/units/{unit_id}/validate-loadout"
    assert "POST" in methods_by_path[path]
    assert "GET" not in methods_by_path[path]


def test_endpoint_delegates_once_returns_strict_payload_and_safe_audit(api) -> None:
    client, sessions, _engine = api
    unit_id, ids = _seed_catalog_and_token(sessions)
    with patch.object(
        service,
        "validate_loadout_by_id",
        wraps=service.validate_loadout_by_id,
    ) as validate_by_id:
        response = client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=_authorization(),
            json={"loadout": _mixed_loadout(ids), "count": 3},
        )

    assert response.status_code == 200
    validate_by_id.assert_called_once()
    payload = response.json()
    assert payload["schema"] == "szop.validate_loadout/v1"
    assert payload["version"] == 1
    assert payload["unit_id"] == unit_id
    assert payload["count"] == 3
    assert [section["section"] for section in payload["sections"]] == [
        "weapons",
        "active",
        "aura",
    ]
    assert payload["sections"][0]["rejected"]
    assert payload["sections"][0]["clamped"]
    assert payload["passive"]["rejected"] == ["unknown-passive"]
    assert payload["mode"]["clamped"] is True
    json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

    with sessions() as session:
        audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    params = json.loads(audit.params_json)
    assert audit.route == f"/units/{unit_id}/validate-loadout"
    assert params == {
        "method": "POST",
        "path_params": {"unit_id": str(unit_id)},
        "query_params": {},
        "scope": router_module.LOADOUT_VALIDATE_SCOPE,
        "status": "authorized",
    }
    observed = audit.params_json
    assert RAW_TOKEN not in observed
    assert "unknown-passive" not in observed
    assert "selected_total" not in observed
    assert "99999" not in observed


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"loadout": []},
        {"loadout": {}, "count": True},
        {"loadout": {}, "count": 0},
        {"loadout": {}, "count": 101},
        {"loadout": {}, "extra": PRIVATE_LOADOUT_VALUE},
    ],
)
def test_invalid_body_returns_constant_safe_422_without_service_call(api, body) -> None:
    client, sessions, _engine = api
    unit_id, _ids = _seed_catalog_and_token(sessions)
    with patch.object(service, "validate_loadout_by_id") as validate_by_id:
        response = client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=_authorization(),
            json=body,
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid loadout validation request"}
    assert PRIVATE_LOADOUT_VALUE not in response.text
    validate_by_id.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        f'{{"loadout":{{"private":"{PRIVATE_LOADOUT_VALUE}"}}',
        '{"loadout":{"mode":NaN}}',
    ],
)
def test_malformed_or_nonfinite_json_returns_constant_safe_422(api, content) -> None:
    client, sessions, _engine = api
    unit_id, _ids = _seed_catalog_and_token(sessions)
    response = client.post(
        f"/units/{unit_id}/validate-loadout",
        headers={**_authorization(), "Content-Type": "application/json"},
        content=content,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid loadout validation request"}
    assert PRIVATE_LOADOUT_VALUE not in response.text


def test_excessively_nested_json_returns_constant_safe_422(api) -> None:
    client, sessions, _engine = api
    unit_id, _ids = _seed_catalog_and_token(sessions)
    content = '{"loadout":' + "[" * 1100 + "0" + "]" * 1100 + "}"
    response = client.post(
        f"/units/{unit_id}/validate-loadout",
        headers={**_authorization(), "Content-Type": "application/json"},
        content=content,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid loadout validation request"}


def test_missing_unit_returns_constant_404_without_oracle(api) -> None:
    client, sessions, _engine = api
    _unit_id, _ids = _seed_catalog_and_token(sessions)
    response = client.post(
        "/units/99999/validate-loadout",
        headers=_authorization(),
        json={"loadout": {}, "count": 1},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Unit not found"}


@pytest.mark.parametrize(
    ("authorization", "seed_kwargs", "expected_status"),
    [
        (None, None, 401),
        ("Bearer invalid", None, 401),
        (
            "Bearer expired",
            {"raw_token": "expired", "expires_in": timedelta(seconds=-1)},
            401,
        ),
        (
            "Bearer revoked",
            {"raw_token": "revoked", "revoked": True},
            401,
        ),
        (
            "Bearer wrong-scope",
            {"raw_token": "wrong-scope", "scopes": {"battle:read": True}},
            403,
        ),
    ],
)
def test_endpoint_uses_agent_scope_without_session_fallback(
    api,
    authorization,
    seed_kwargs,
    expected_status,
) -> None:
    client, sessions, _engine = api
    unit_id = 1
    if seed_kwargs is not None:
        unit_id, _ids = _seed_catalog_and_token(sessions, **seed_kwargs)
    headers = {"Authorization": authorization} if authorization else {}
    with patch.object(service, "validate_loadout_by_id") as validate_by_id:
        response = client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=headers,
            json={"loadout": {}, "count": 1},
        )
    assert response.status_code == expected_status
    validate_by_id.assert_not_called()
    with sessions() as session:
        assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_controlled_service_failure_is_constant_and_redacted(api) -> None:
    client, sessions, _engine = api
    unit_id, _ids = _seed_catalog_and_token(sessions)
    with patch.object(
        service,
        "validate_loadout_by_id",
        side_effect=ValueError(
            f"{PRIVATE_LOADOUT_VALUE} C:\\private\\loadout.json selected_total=99"
        ),
    ):
        response = client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=_authorization(),
            json={"loadout": {"private": PRIVATE_LOADOUT_VALUE}},
        )
    assert response.status_code == 500
    assert response.json() == {"detail": "Loadout validation failed"}
    assert PRIVATE_LOADOUT_VALUE not in response.text
    assert "C:\\private" not in response.text


def _statement_count(client, engine, unit_id, loadout) -> int:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.post(
            f"/units/{unit_id}/validate-loadout",
            headers=_authorization(),
            json={"loadout": loadout, "count": 5},
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    return len(statements)


def test_sql_statement_count_is_constant_for_small_and_large_legal_payload(api) -> None:
    client, sessions, engine = api
    unit_id, ids = _seed_catalog_and_token(sessions)
    small = {"weapons": {str(ids["weapon"]): 1}}
    large = {
        "weapons": {
            f"{ids['weapon']}:variant-{index:03d}": 1 for index in range(100)
        },
        "active": {f"{ids['active']}:variant-{index:03d}": 1 for index in range(100)},
        "aura": {f"{ids['aura']}:variant-{index:03d}": 1 for index in range(100)},
    }

    small_count = _statement_count(client, engine, unit_id, small)
    large_count = _statement_count(client, engine, unit_id, large)

    assert small_count == 11
    assert large_count == 11


def test_openapi_exposes_only_body_and_unit_path_parameter(api) -> None:
    client, _sessions, _engine = api
    operation = client.get("/openapi.json").json()["paths"][
        "/units/{unit_id}/validate-loadout"
    ]["post"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "unit_id"
    ]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["loadout"]
    assert set(schema["properties"]) == {"loadout", "count"}
