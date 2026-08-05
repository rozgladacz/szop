from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app import models
from app.db import Base, get_db
from app.routers import armies, export, quote, rosters
from app.security import get_csrf_token


def _profile_payload(name: str = "Straż") -> dict[str, object]:
    return {
        "name": name,
        "models_per_unit": 2,
        "unit_copies": 3,
        "defense": 4,
        "toughness": 2,
        "passive_abilities": ["steadfast"],
        "special_abilities": [],
        "profiles": {
            "melee": {"dice": 1, "strength": 1, "abilities": []},
            "short": {"dice": 0, "strength": 0, "abilities": []},
            "long": {"dice": 0, "strength": 0, "abilities": []},
        },
        "custom_stats_enabled": False,
    }


@pytest.fixture()
def api() -> Generator[tuple[TestClient, sessionmaker, dict[str, int], list[int]], None, None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    with sessions.begin() as session:
        owner = models.User(username="owner", password_hash="hash")
        stranger = models.User(username="stranger", password_hash="hash")
        session.add_all([owner, stranger])
        session.flush()
        army = models.Army(name="Moja", owner_id=owner.id)
        foreign_army = models.Army(name="Cudza", owner_id=stranger.id)
        roster = models.Roster(
            name="Test",
            owner_id=owner.id,
            army=army,
            ruleset_version="v1",
        )
        foreign_roster = models.Roster(
            name="Cudza",
            owner_id=stranger.id,
            army=foreign_army,
            ruleset_version="v1",
        )
        session.add_all([roster, foreign_roster])
        session.flush()
        ids = {
            "owner": owner.id,
            "army": army.id,
            "foreign_army": foreign_army.id,
            "roster": roster.id,
            "foreign_roster": foreign_roster.id,
        }

    current_user = models.User(
        id=ids["owner"], username="owner", password_hash="hash"
    )

    def db_override() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    def user_override() -> models.User:
        return current_user

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="test-secret")
    test_app.mount("/static", StaticFiles(directory="app/static"), name="static")
    test_app.include_router(quote.router)
    test_app.include_router(armies.router)
    test_app.include_router(rosters.router)
    test_app.include_router(export.router)
    test_app.dependency_overrides[get_db] = db_override
    test_app.dependency_overrides[armies.current_user_dep] = user_override
    test_app.dependency_overrides[rosters.current_user_dep] = user_override
    test_app.dependency_overrides[export.current_user_dep] = user_override

    @test_app.get("/_csrf")
    def csrf(request: Request) -> dict[str, str]:
        return {"token": get_csrf_token(request)}

    queries: list[int] = []

    @event.listens_for(test_engine, "before_cursor_execute")
    def count_query(*args: object, **kwargs: object) -> None:
        del args, kwargs
        queries.append(1)

    with TestClient(test_app) as client:
        yield client, sessions, ids, queries


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/_csrf").json()["token"]}


def test_quote_is_stateless_and_does_not_query_database(api) -> None:
    client, _, _, queries = api
    queries.clear()

    response = client.post("/quote", json=_profile_payload())

    assert response.status_code == 200
    assert response.json()["entry_cost"] == "234"
    assert queries == []


def test_create_roster_exposes_collapsed_extra_settings_and_scales_limit(api) -> None:
    client, sessions, _, _ = api
    token = client.get("/_csrf").json()["token"]

    form = client.get("/rosters/new")
    created = client.post(
        "/rosters",
        data={
            "name": "Mała rozpiska",
            "points_limit": "505",
            "csrf_token": token,
            "custom_stats_enabled": "true",
            "simple_points_enabled": "true",
            "collapse_descriptions": "true",
            "small_battle_enabled": "true",
        },
        follow_redirects=False,
    )

    assert form.status_code == 200
    assert '<details class="additional-settings">' in form.text
    assert '<details class="additional-settings" open>' not in form.text
    assert 'name="simple_points_enabled"' in form.text
    assert 'name="collapse_descriptions"' in form.text
    assert 'name="small_battle_enabled"' in form.text
    assert 'name="simple_points_enabled" type="checkbox" value="true" checked' in form.text
    assert 'name="small_battle_enabled" type="checkbox" value="true" checked' in form.text
    assert created.status_code == 303
    with sessions() as session:
        roster = session.query(models.Roster).filter_by(name="Mała rozpiska").one()
        assert roster.points_limit == 51
        assert roster.custom_stats_enabled is True
        assert roster.simple_points_enabled is True
        assert roster.collapse_descriptions is True
        assert roster.small_battle_enabled is True


def test_write_recalculates_price_and_rejects_client_price(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    stale = {**_profile_payload(), "unit_cost": 1}

    rejected = client.post(
        f"/rosters/{ids['roster']}/units", json=stale, headers=headers
    )
    accepted = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json()["unit_cost"] == 78
    assert accepted.json()["entry_cost"] == 234
    with sessions() as session:
        stored = session.get(models.RosterUnit, accepted.json()["id"])
        assert stored is not None and stored.unit_cost == 78


def test_mutations_require_csrf_and_hide_foreign_resources(api) -> None:
    client, _, ids, _ = api
    no_csrf = client.post(
        f"/rosters/{ids['roster']}/units", json=_profile_payload()
    )
    foreign = client.post(
        f"/rosters/{ids['foreign_roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    foreign_army = client.post(
        f"/armies/{ids['foreign_army']}/templates",
        json=_profile_payload(),
        headers=_csrf(client),
    )

    assert no_csrf.status_code == 403
    assert foreign.status_code == 404
    assert foreign_army.status_code == 404


def test_template_copy_does_not_propagate_until_explicit_update(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()
    saved = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["army"]},
        headers=headers,
    ).json()

    client.patch(
        f"/rosters/{ids['roster']}/units/{created['id']}",
        json=_profile_payload(name="Zmieniona"),
        headers=headers,
    )
    with sessions() as session:
        template = session.get(models.UnitTemplate, saved["template_id"])
        assert template is not None and template.name == "Straż"

    client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/update-template",
        headers=headers,
    )
    with sessions() as session:
        template = session.get(models.UnitTemplate, saved["template_id"])
        assert template is not None and template.name == "Zmieniona"


def test_custom_template_requires_confirmation_and_enables_roster_mode(api) -> None:
    client, sessions, ids, _ = api
    custom_profiles = _profile_payload()
    with sessions.begin() as session:
        template = models.UnitTemplate(
            army_id=ids["army"],
            owner_id=ids["owner"],
            name="Niestandardowy",
            models_per_unit=1,
            defense=3.5,
            toughness=4.5,
            passive_abilities_json="[]",
            special_abilities_json="[]",
            profiles_json=json.dumps(custom_profiles["profiles"]),
            ruleset_version="v1",
            position=0,
        )
        session.add(template)
        session.flush()
        template_id = template.id
    headers = _csrf(client)

    prompt = client.post(
        f"/rosters/{ids['roster']}/units/from-template",
        json={"template_id": template_id},
        headers=headers,
    )
    accepted = client.post(
        f"/rosters/{ids['roster']}/units/from-template",
        json={"template_id": template_id, "enable_custom_stats": True},
        headers=headers,
    )

    assert prompt.status_code == 409
    assert accepted.status_code == 200
    with sessions() as session:
        assert session.get(models.Roster, ids["roster"]).custom_stats_enabled is True


def test_cards_view_uses_two_queries_and_omits_counts(api) -> None:
    client, _, ids, queries = api
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    queries.clear()

    response = client.get(f"/rosters/{ids['roster']}/cards")

    assert response.status_code == 200
    assert len(queries) == 2
    assert response.text.count('class="unit-card unit-card-profile"') == 1
    assert "models_per_unit" not in response.text
    assert "unit_copies" not in response.text


def test_roster_detail_renders_icons_after_unit_is_saved(api) -> None:
    client, _, ids, _ = api
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )

    response = client.get(f"/rosters/{ids['roster']}")

    assert response.status_code == 200
    assert "Straż" in response.text
    assert "/static/icons/opos.svg#icon-defense" in response.text
    assert 'aria-label="Obrona 4"' in response.text
    assert 'aria-label="Obrona 4.00"' not in response.text
    assert response.text.count('data-range="') == 3
    assert "Wręcz" in response.text
    assert "Krótki" in response.text
    assert "Daleki" in response.text
    assert 'class="drag-handle"' in response.text
    assert "js-move-up" not in response.text
    assert "js-move-down" not in response.text
    assert response.text.count('class="editor-section') == 3
    assert 'class="library-tools"' in response.text
    assert 'aria-label="Zdolności oddziału"' in response.text
    assert "/static/icons/opos.svg#icon-steadfast" in response.text
    assert 'name="simple_points_enabled"' in response.text
    assert 'name="collapse_descriptions"' in response.text
    assert 'name="small_battle_enabled"' in response.text


def test_roster_and_cards_keep_two_query_budget_for_twelve_profiles(api) -> None:
    client, sessions, ids, queries = api
    profiles_json = json.dumps(_profile_payload()["profiles"])
    with sessions.begin() as session:
        session.add_all(
            [
                models.RosterUnit(
                    roster_id=ids["roster"],
                    name=f"Profil {position + 1}",
                    models_per_unit=3,
                    unit_copies=25,
                    defense=4,
                    toughness=3,
                    passive_abilities_json="[]",
                    special_abilities_json="[]",
                    profiles_json=profiles_json,
                    position=position,
                    unit_cost=100 + position,
                )
                for position in range(12)
            ]
        )

    queries.clear()
    detail = client.get(f"/rosters/{ids['roster']}")
    detail_queries = len(queries)

    queries.clear()
    cards = client.get(f"/rosters/{ids['roster']}/cards")
    card_queries = len(queries)

    assert detail.status_code == 200
    assert cards.status_code == 200
    assert detail_queries == 2
    assert card_queries == 2
    assert detail.text.count('class="unit-row"') == 12
    assert cards.text.count('class="unit-card unit-card-profile') == 12
    assert "× 25" in detail.text
    assert "× 25" not in cards.text


def test_custom_stats_cannot_be_disabled_while_custom_units_exist(api) -> None:
    client, sessions, ids, _ = api
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).custom_stats_enabled = True
    custom = _profile_payload()
    custom.update(
        defense=3.5,
        toughness=4.5,
        custom_stats_enabled=True,
    )
    custom["profiles"] = {
        "melee": {"dice": 1, "strength": 3.5, "abilities": []},
        "short": {"dice": 0, "strength": 0, "abilities": []},
        "long": {"dice": 0, "strength": 0, "abilities": []},
    }
    headers = _csrf(client)
    assert client.post(
        f"/rosters/{ids['roster']}/units", json=custom, headers=headers
    ).status_code == 200

    response = client.post(
        f"/rosters/{ids['roster']}/settings",
        data={
            "name": "Test",
            "csrf_token": headers["X-CSRF-Token"],
        },
    )

    assert response.status_code == 409
    with sessions() as session:
        assert session.get(models.Roster, ids["roster"]).custom_stats_enabled is True


def test_roster_modes_recalculate_points_and_scale_standard_toughness(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()

    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).points_limit = 500

    response = client.post(
        f"/rosters/{ids['roster']}/settings",
        data={
            "name": "Test",
            "csrf_token": headers["X-CSRF-Token"],
            "points_limit": "500",
            "simple_points_enabled": "true",
            "collapse_descriptions": "true",
            "small_battle_enabled": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with sessions() as session:
        roster = session.get(models.Roster, ids["roster"])
        unit = session.get(models.RosterUnit, created["id"])
        assert roster.simple_points_enabled is True
        assert roster.collapse_descriptions is True
        assert roster.small_battle_enabled is True
        assert roster.points_limit == 50
        assert unit.toughness == 4
        assert unit.unit_cost == 14


def test_collapsed_cards_hide_ability_descriptions(api) -> None:
    client, sessions, ids, _ = api
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).collapse_descriptions = True

    response = client.get(f"/rosters/{ids['roster']}/cards")

    assert response.status_code == 200
    assert 'unit-card-profile is-compact' not in response.text
    assert 'class="attack-primary"' in response.text
    assert 'class="attack-range"' not in response.text
    assert "Wytrwały" in response.text
    assert "+1 do obrony za każdy znacznik aktywacji." not in response.text
