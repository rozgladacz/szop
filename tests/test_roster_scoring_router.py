from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.main import app as main_app
from app.routers import roster_scoring as router_module
from app.security import hash_agent_token
from app.services import roster_scoring as scoring_service
from szop_client.types import SimulationSummary

RAW_TOKEN = "roster-score-secret"


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


def _seed_score_field(
    sessions: sessionmaker[Session],
    *,
    owned_count: int = 3,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
    expires_in: timedelta = timedelta(days=1),
    revoked: bool = False,
) -> tuple[int, list[int], int]:
    with sessions() as session:
        owner = models.User(username=f"owner-{raw_token}", password_hash="x")
        outsider = models.User(username=f"outsider-{raw_token}", password_hash="x")
        agent = models.User(
            username=f"agent-{raw_token}",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name=f"Rules-{raw_token}")
        armory = models.Armory(name=f"Armory-{raw_token}", owner=owner)
        session.add_all([owner, outsider, agent, ruleset, armory])
        session.flush()
        army = models.Army(
            name="Score Army",
            owner=owner,
            ruleset=ruleset,
            armory=armory,
        )
        blade = models.Weapon(
            armory=armory,
            name="Score Blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
        )
        session.add_all([army, blade])
        session.flush()
        unit = models.Unit(
            army=army,
            name="Score Unit",
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
        owned: list[models.Roster] = []
        for index in range(owned_count):
            roster = models.Roster(
                name=f"Owned {index + 1}",
                army=army,
                owner=owner,
            )
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
            owned.append(roster)
        foreign = models.Roster(name="Foreign private", army=army, owner=outsider)
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
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            models.AgentToken(
                agent_user=agent,
                owner_user=owner,
                token_hash=hash_agent_token(raw_token),
                scope_json=json.dumps(
                    scopes
                    if scopes is not None
                    else {router_module.ROSTER_SCORE_SCOPE: True}
                ),
                expires_at=now + expires_in,
                revoked_at=now if revoked else None,
            )
        )
        session.commit()
        return owner.id, [roster.id for roster in owned], foreign.id


def _authorization(raw_token: str = RAW_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def _post_score(
    client: TestClient,
    roster_id: int,
    body: dict,
    *,
    raw_token: str = RAW_TOKEN,
):
    return client.post(
        f"/rosters/{roster_id}/score",
        headers=_authorization(raw_token),
        json=body,
    )


def test_main_app_registers_agent_only_roster_score_post() -> None:
    methods_by_path = {
        getattr(route, "path_format", route.path): getattr(route, "methods", set())
        for route in main_app.routes
    }
    path = "/rosters/{roster_id}/score"
    assert "POST" in methods_by_path[path]
    assert "GET" not in methods_by_path[path]


def test_endpoint_delegates_once_returns_strict_payload_and_safe_audit(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions)
    target_id, opponent_ids = owned_ids[0], [owned_ids[2], owned_ids[1]]

    with patch.object(
        scoring_service,
        "score_list",
        wraps=scoring_service.score_list,
    ) as score_list:
        response = _post_score(
            client,
            target_id,
            {
                "games_per_opponent": 1,
                "bot": "RANDOM",
                "seed": 7,
                "map_name": "LUSTRZANA_A",
                "opponent_roster_ids": opponent_ids,
            },
        )

    assert response.status_code == 200, response.text
    score_list.assert_called_once()
    payload = response.json()
    assert payload["schema"] == "szop.score_list/v1"
    assert payload["version"] == 1
    assert payload["target"]["id"] == target_id
    assert payload["parameters"] == {
        "games_per_opponent": 1,
        "bot": "random",
        "seed": 7,
        "map_name": "lustrzana_a",
        "opponent_roster_ids": sorted(opponent_ids),
    }
    assert [item["opponent"]["id"] for item in payload["results"]] == sorted(
        opponent_ids
    )
    assert payload["aggregate"]["n_opponents"] == 2
    assert payload["aggregate"]["n_games"] == 2
    json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

    with sessions() as session:
        audit = session.scalar(select(models.AgentAuditLog))
        battles = session.scalar(select(func.count()).select_from(models.Battle))
    assert battles == 0
    assert audit is not None
    assert audit.route == f"/rosters/{target_id}/score"
    audit_payload = json.loads(audit.params_json)
    assert audit_payload == {
        "method": "POST",
        "path_params": {"roster_id": target_id},
        "query_params": {},
        "scope": router_module.ROSTER_SCORE_SCOPE,
        "status": "authorized",
    }
    observed = audit.params_json
    assert RAW_TOKEN not in observed
    assert str(owned_ids[1]) not in observed
    assert "Owned" not in observed
    assert "Score Army" not in observed
    assert "wins" not in observed
    assert "random" not in observed
    assert "lustrzana_a" not in observed


def test_query_injection_is_constant_422_and_never_reaches_audit(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions)
    target_id = owned_ids[0]
    injected = "private-opponent-880088"

    response = client.post(
        f"/rosters/{target_id}/score"
        f"?opponent_roster_ids=880088&bot=random&seed=7&name={injected}",
        headers=_authorization(),
        json={},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid roster score request"}
    with sessions() as session:
        audit = session.scalar(select(models.AgentAuditLog))
    assert audit is not None
    payload = json.loads(audit.params_json)
    assert payload["query_params"] == {}
    assert "880088" not in audit.params_json
    assert injected not in audit.params_json
    assert "random" not in audit.params_json


def test_non_integer_roster_path_is_not_matched_or_audited(api) -> None:
    client, sessions, _engine = api
    sentinel = "private-name-880088"

    response = client.post(
        f"/rosters/{sentinel}/score",
        headers=_authorization(),
        json={},
    )

    assert response.status_code == 404
    assert sentinel not in response.text
    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(models.AgentAuditLog)
        ) == 0


def test_unexpected_scoring_error_is_constant_safe_500(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions)
    leaked = "private roster 990099 result"

    with patch.object(scoring_service, "score_list", side_effect=RuntimeError(leaked)):
        response = _post_score(client, owned_ids[0], {})

    assert response.status_code == 500
    assert response.json() == {"detail": "Roster scoring failed"}
    assert leaked not in response.text
    assert "traceback" not in response.text.lower()


def test_oversized_body_is_bounded_constant_422_without_echo(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions)
    sentinel = "private-body-770077"

    response = _post_score(
        client,
        owned_ids[0],
        {"extra": sentinel + ("x" * router_module.MAX_SCORE_REQUEST_BYTES)},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid roster score request"}
    assert sentinel not in response.text
    with sessions() as session:
        audit = session.scalar(select(models.AgentAuditLog))
    assert audit is not None
    assert sentinel not in audit.params_json


def test_missing_foreign_target_and_explicit_opponent_share_safe_404(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, foreign_id = _seed_score_field(sessions)
    target_id = owned_ids[0]
    responses = [
        _post_score(client, foreign_id, {"opponent_roster_ids": []}),
        _post_score(client, 999999, {"opponent_roster_ids": []}),
        _post_score(client, 2**100, {"opponent_roster_ids": []}),
        _post_score(client, target_id, {"opponent_roster_ids": [foreign_id]}),
        _post_score(client, target_id, {"opponent_roster_ids": [999999]}),
        _post_score(client, target_id, {"opponent_roster_ids": [2**100]}),
    ]

    assert [response.status_code for response in responses] == [404] * 6
    assert {response.text for response in responses} == {
        '{"detail":"Roster not found"}'
    }
    assert all("Foreign private" not in response.text for response in responses)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"games_per_opponent": True},
        {"games_per_opponent": 0},
        {"games_per_opponent": 11},
        {"seed": True},
        {"seed": 2**31},
        {"bot": "minimax"},
        {"map_name": "private-map"},
        {"opponent_roster_ids": [2, 2]},
        {"opponent_roster_ids": [True]},
        {"extra": "private-value"},
    ],
)
def test_invalid_request_shapes_are_constant_safe_422(api, body) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions)
    target_id = owned_ids[0]
    if body == {}:
        body = {"opponent_roster_ids": [target_id]}
    response = _post_score(client, target_id, body)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid roster score request"}
    assert "private-value" not in response.text


def test_workload_caps_reject_without_silent_truncation_and_empty_is_valid(api) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions, owned_count=12)
    target_id = owned_ids[0]

    default_too_large = _post_score(client, target_id, {})
    total_too_large = _post_score(
        client,
        target_id,
        {
            "games_per_opponent": 10,
            "opponent_roster_ids": owned_ids[1:7],
        },
    )
    empty = _post_score(client, target_id, {"opponent_roster_ids": []})

    assert default_too_large.status_code == 422
    assert total_too_large.status_code == 422
    assert default_too_large.json() == total_too_large.json() == {
        "detail": (
            "Roster score workload exceeds limits; provide an explicit opponent subset"
        )
    }
    assert empty.status_code == 200
    assert empty.json()["results"] == []
    assert empty.json()["aggregate"]["n_games"] == 0


@pytest.mark.parametrize(
    ("token_kwargs", "provided_token", "expected_status"),
    [
        ({}, None, 401),
        ({}, "invalid-token", 401),
        ({"scopes": {"battle:read": True}}, RAW_TOKEN, 403),
        ({"expires_in": timedelta(seconds=-1)}, RAW_TOKEN, 401),
        ({"revoked": True}, RAW_TOKEN, 401),
    ],
)
def test_auth_failures_use_existing_agent_scope_ssot(
    api,
    token_kwargs,
    provided_token,
    expected_status,
) -> None:
    client, sessions, _engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(
        sessions,
        **token_kwargs,
    )
    headers = _authorization(provided_token) if provided_token else {}
    response = client.post(
        f"/rosters/{owned_ids[0]}/score",
        headers=headers,
        json={"opponent_roster_ids": []},
    )
    assert response.status_code == expected_status
    with sessions() as session:
        assert session.scalar(select(models.AgentAuditLog)) is None


def _statement_count(
    client: TestClient,
    engine,
    roster_id: int,
    body: dict,
) -> int:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = _post_score(client, roster_id, body)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    return len(statements)


def _add_deep_weapon_chains(
    sessions: sessionmaker[Session],
    roster_ids: list[int],
) -> None:
    with sessions() as session:
        army = session.scalar(select(models.Army).where(models.Army.name == "Score Army"))
        armory = session.scalar(
            select(models.Armory).where(models.Armory.name.like("Armory-%"))
        )
        assert army is not None
        assert armory is not None
        for index, roster_id in enumerate(roster_ids):
            root = models.Weapon(
                armory=armory,
                name=f"Deep root {index}",
                range="Walka wręcz",
                attacks=1,
                ap=0,
            )
            parent_1 = models.Weapon(armory=armory, parent=root)
            parent_2 = models.Weapon(armory=armory, parent=parent_1)
            leaf = models.Weapon(armory=armory, parent=parent_2)
            unit = models.Unit(
                army=army,
                name=f"Deep unit {index}",
                quality=4,
                defense=5,
                toughness=3,
                typical_models=1,
                position=index + 1,
                default_weapon=leaf,
            )
            session.add_all([root, parent_1, parent_2, leaf, unit])
            session.flush()
            session.add_all(
                [
                    models.UnitWeapon(
                        unit=unit,
                        weapon=leaf,
                        is_default=True,
                        default_count=1,
                        is_primary=True,
                        position=0,
                    ),
                    models.RosterUnit(
                        roster_id=roster_id,
                        unit=unit,
                        count=1,
                        position=1,
                    ),
                ]
            )
        session.commit()


def _domain_counts(session: Session) -> dict[str, int]:
    domain = {
        "rosters": models.Roster,
        "roster_units": models.RosterUnit,
        "battles": models.Battle,
        "battle_events": models.BattleEvent,
        "units": models.Unit,
        "weapons": models.Weapon,
    }
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in domain.items()
    }


def test_sql_statement_count_is_game_invariant_and_field_batch_is_constant(api) -> None:
    client, sessions, engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions, owned_count=4)
    target_id = owned_ids[0]
    with sessions() as session:
        before = _domain_counts(session)

    one_game = _statement_count(
        client,
        engine,
        target_id,
        {"games_per_opponent": 1, "opponent_roster_ids": [owned_ids[1]]},
    )
    max_games = _statement_count(
        client,
        engine,
        target_id,
        {"games_per_opponent": 10, "opponent_roster_ids": [owned_ids[1]]},
    )
    one_opponent = _statement_count(
        client,
        engine,
        target_id,
        {"games_per_opponent": 1, "opponent_roster_ids": [owned_ids[1]]},
    )
    three_opponents = _statement_count(
        client,
        engine,
        target_id,
        {"games_per_opponent": 1, "opponent_roster_ids": owned_ids[1:4]},
    )
    default_field = _statement_count(
        client,
        engine,
        target_id,
        {"games_per_opponent": 1},
    )

    assert one_game == max_games
    assert one_opponent == three_opponents
    assert one_game == one_opponent == 13
    assert default_field == 15
    with sessions() as session:
        assert _domain_counts(session) == before
        assert session.scalar(select(func.count()).select_from(models.AgentAuditLog)) == 5


def test_sql_count_is_constant_for_multiple_deep_weapon_parent_chains(api) -> None:
    client, sessions, engine = api
    _owner_id, owned_ids, _foreign_id = _seed_score_field(sessions, owned_count=4)
    _add_deep_weapon_chains(sessions, owned_ids)
    summary = SimulationSummary(
        n_games=1,
        wins_p0=1,
        wins_p1=0,
        draws=0,
        total_rounds=1,
    )

    with patch.object(
        scoring_service,
        "simulate_roster_pair",
        return_value=summary,
    ):
        one_opponent = _statement_count(
            client,
            engine,
            owned_ids[0],
            {"games_per_opponent": 1, "opponent_roster_ids": [owned_ids[1]]},
        )
        three_opponents = _statement_count(
            client,
            engine,
            owned_ids[0],
            {"games_per_opponent": 1, "opponent_roster_ids": owned_ids[1:4]},
        )

    assert one_opponent == three_opponents == 13


def test_openapi_exposes_only_body_and_roster_path_parameter(api) -> None:
    client, _sessions, _engine = api
    operation = client.get("/openapi.json").json()["paths"][
        "/rosters/{roster_id}/score"
    ]["post"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "roster_id"
    ]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "games_per_opponent",
        "bot",
        "seed",
        "map_name",
        "opponent_roster_ids",
    }
