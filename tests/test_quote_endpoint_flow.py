from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config, main, models
from app.db import Base, get_db
from app.routers import rosters
from app.security import hash_password
from app.services import costs
from app.services.costs.budget import MAX_UNIT_EQUIPMENT, MAX_UNIT_MODELS, UnitBudgetExceeded


SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "quote_snapshots"


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _json_response_payload(response) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _request_with_json_accept() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"accept", b"application/json")],
        }
    )


def _build_roster_fixture(session):
    user = models.User(username="owner", password_hash="secret")
    ruleset = models.RuleSet(name="Core")
    armory = models.Armory(name="Armory", owner=user)
    session.add_all([user, ruleset, armory])
    session.flush()

    rifle = models.Weapon(armory=armory, name="Rifle", range='18"', attacks=2, ap=1)
    blade = models.Weapon(armory=armory, name="Blade", range="Melee", attacks=1, ap=1)
    session.add_all([rifle, blade])
    session.flush()

    active_scout = models.Ability(name="Zasadzka", type="active", description="")
    active_fly = models.Ability(name="Samolot", type="active", description="")
    aura_heavy = models.Ability(name="Ociężałość", type="aura", description="")
    session.add_all([active_scout, active_fly, aura_heavy])
    session.flush()

    army = models.Army(name="Alpha", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()

    unit = models.Unit(
        army=army,
        owner=user,
        name="Veterans",
        quality=4,
        defense=4,
        toughness=3,
        typical_models=1,
        flags="Wojownik, Strzelec, Masywny, Otwarty Transport(2), Odwody",
        default_weapon=rifle,
        position=0,
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
            models.UnitWeapon(
                unit=unit,
                weapon=blade,
                is_default=False,
                default_count=0,
                position=1,
            ),
            models.UnitAbility(unit=unit, ability=active_scout, position=0),
            models.UnitAbility(unit=unit, ability=active_fly, position=1),
            models.UnitAbility(unit=unit, ability=aura_heavy, position=2),
        ]
    )

    support = models.Unit(
        army=army,
        owner=user,
        name="Support",
        quality=5,
        defense=5,
        toughness=1,
        typical_models=1,
        flags="Wojownik",
        default_weapon=blade,
        position=1,
    )
    session.add(support)
    session.flush()

    session.add(
        models.UnitWeapon(
            unit=support,
            weapon=blade,
            is_default=True,
            default_count=1,
            is_primary=True,
            position=0,
        )
    )

    roster = models.Roster(name="List", army=army, owner=user)
    session.add(roster)
    session.flush()

    unit_a = models.RosterUnit(roster=roster, unit=unit, count=3, position=0)
    unit_b = models.RosterUnit(roster=roster, unit=support, count=2, position=1)
    session.add_all([unit_a, unit_b])
    session.flush()

    session.refresh(unit_a)
    session.refresh(unit_b)
    return {
        "user": user,
        "roster": roster,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "ids": {
            "blade": blade.id,
            "scout": active_scout.id,
            "fly": active_fly.id,
            "heavy": aura_heavy.id,
        },
    }


def _assert_snapshot(snapshot_name: str, payload: dict[str, object]) -> None:
    snapshot_path = SNAPSHOT_DIR / f"{snapshot_name}.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload == expected


def test_unit_budget_is_enforced_before_quote_and_save(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'unit-budget.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, autoflush=False)
    with sessions() as session:
        fixture = _build_roster_fixture(session)
        fixture["user"].password_hash = hash_password("tester password")
        roster_id = fixture["roster"].id
        army_id = fixture["roster"].army_id
        roster_unit_id = fixture["unit_a"].id
        unit_id = fixture["unit_a"].unit_id
        rifle_id = str(fixture["unit_a"].unit.default_weapon_id)
        scout_id = str(fixture["ids"]["scout"])
        session.commit()

    def override_db():
        with sessions() as session:
            yield session

    monkeypatch.setattr(config, "PUBLIC_ORIGIN", "")
    monkeypatch.setitem(main.app.dependency_overrides, get_db, override_db)
    client = TestClient(main.app, follow_redirects=False)
    assert client.post("/auth/login", data={"username": "owner", "password": "tester password"},
                       headers={"accept-language": "en"}).status_code == 303
    target = f"/rosters/{roster_id}/units/{roster_unit_id}"
    oversized = {"mode": "total", "weapons": {rifle_id: MAX_UNIT_EQUIPMENT}, "active": {scout_id: 1}}
    boundary = {"mode": "total", "weapons": {rifle_id: MAX_UNIT_EQUIPMENT}}

    assert client.post(f"{target}/quote", json={"count": MAX_UNIT_MODELS, "loadout": boundary,
                                              "include_item_costs": False}).status_code == 200
    too_many_models = client.post(f"{target}/quote", json={"count": MAX_UNIT_MODELS + 1})
    assert too_many_models.status_code == 422
    assert too_many_models.json()["detail"] == f"A unit can have at most {MAX_UNIT_MODELS} models."
    assert client.post(f"{target}/quote", json={"count": 2, "loadout": oversized}).status_code == 422
    assert client.post(f"{target}/quote", json={"count": MAX_UNIT_MODELS, "loadout": {
        "mode": "per_model", "weapons": {rifle_id: MAX_UNIT_EQUIPMENT // MAX_UNIT_MODELS + 1},
    }}).status_code == 422

    for data in (
        {"count": MAX_UNIT_MODELS + 1},
        {"count": 2, "loadout_json": json.dumps(oversized)},
        {"count": 1, "composed_models_json": json.dumps([{"id": None, "qty": MAX_UNIT_MODELS + 1}])},
        {"count": 1, "composed_models_json": json.dumps([{
            "id": None, "qty": 2, "weapons": {rifle_id: MAX_UNIT_EQUIPMENT // 2 + 1},
        }])},
    ):
        assert client.post(f"{target}/update", data=data).status_code == 422

    assert client.post(f"/rosters/{roster_id}/units/add", data={
        "unit_id": unit_id, "count": MAX_UNIT_MODELS + 1,
    }).status_code == 422
    assert client.post(f"/armies/{army_id}/units/new", data={
        "name": "Too much equipment", "quality": 4, "defense": 4, "toughness": 1,
        "typical_models": MAX_UNIT_MODELS, "weapons": json.dumps([
            {"weapon_id": rifle_id, "count": MAX_UNIT_EQUIPMENT // MAX_UNIT_MODELS + 1},
        ]),
    }).status_code == 422
    assert client.post(f"/collections/units/{unit_id}/models/add", data={
        f"weapon_{rifle_id}": MAX_UNIT_EQUIPMENT + 1,
    }).status_code == 422

    with sessions() as session:
        stored = session.get(models.RosterUnit, roster_unit_id)
        assert (stored.count, stored.extra_weapons_json, stored.composed_models_json) == (3, None, None)
        assert session.scalar(select(func.count()).select_from(models.RosterUnit)) == 2
        assert session.scalar(select(func.count()).select_from(models.Unit)) == 2
        assert session.scalar(select(func.count()).select_from(models.CollectionModel)) == 0
    assert client.post(f"{target}/update", data={"count": MAX_UNIT_MODELS,
                                                 "loadout_json": json.dumps(boundary)}).status_code == 303
    client.close()
    engine.dispose()


def test_oversized_existing_weapon_default_stops_before_expansion():
    with _session() as session:
        unit = _build_roster_fixture(session)["unit_a"].unit
        unit.weapon_links[0].default_count = MAX_UNIT_EQUIPMENT + 1
        with pytest.raises(UnitBudgetExceeded, match=str(MAX_UNIT_EQUIPMENT)):
            costs.unit_default_weapons(unit)


def test_quote_endpoint_handles_modes_dynamic_passives_and_classification() -> None:
    session = _session()
    try:
        fixture = _build_roster_fixture(session)
        roster = fixture["roster"]
        roster_unit = fixture["unit_a"]
        ids = fixture["ids"]

        base_response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={
                "count": 3,
                "loadout": {
                    "mode": "per_model",
                    "passive": {"wojownik": 1, "odwody": 1, "otwarty_transport(2)": 1},
                },
            },
            db=session,
            current_user=fixture["user"],
        )
        base_payload = _json_response_payload(base_response)

        blocked_odwody_response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={
                "count": 3,
                "loadout": {
                    "mode": "per_model",
                    "active": {str(ids["scout"]): 1},
                    "passive": {"wojownik": 1, "odwody": 1, "otwarty_transport(2)": 1},
                },
            },
            db=session,
            current_user=fixture["user"],
        )
        blocked_payload = _json_response_payload(blocked_odwody_response)

        transport_with_fly_response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={
                "count": 3,
                "loadout": {
                    "mode": "per_model",
                    "active": {str(ids["fly"]): 1},
                    "aura": {str(ids["heavy"]): 1},
                    "passive": {"strzelec": 1, "otwarty_transport(2)": 1},
                    "weapons": {str(ids["blade"]): 1},
                },
            },
            db=session,
            current_user=fixture["user"],
        )
        transport_payload = _json_response_payload(transport_with_fly_response)

        assert base_payload["count"] == 3
        assert base_payload["roster_unit_id"] == roster_unit.id
        assert base_payload["unit_id"] == roster_unit.id
        assert base_payload["selected_total"] >= base_payload["warrior_total"]
        assert base_payload["selected_total"] >= base_payload["shooter_total"]
        assert blocked_payload["selected_total"] != base_payload["selected_total"]
        assert transport_payload["loadout"]["mode"] == "per_model"
        assert isinstance(transport_payload["loadout"]["passive"], dict)
    finally:
        session.close()


def test_quote_endpoint_and_update_flow_persists_cached_cost_and_roster_total() -> None:
    session = _session()
    try:
        fixture = _build_roster_fixture(session)
        roster = fixture["roster"]
        roster_unit = fixture["unit_a"]
        other_unit = fixture["unit_b"]
        ids = fixture["ids"]

        loadout_payload = {
            "mode": "per_model",
            "weapons": {str(ids["blade"]): 1},
            "active": {str(ids["fly"]): 1},
            "aura": {str(ids["heavy"]): 1},
            "passive": {"strzelec": 1, "otwarty_transport(2)": 1},
        }

        quote_response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={"count": 4, "loadout": loadout_payload},
            db=session,
            current_user=fixture["user"],
        )
        quote_payload = _json_response_payload(quote_response)

        update_response = rosters.update_roster_unit(
            roster.id,
            roster_unit.id,
            request=_request_with_json_accept(),
            count=4,
            loadout_json=json.dumps(loadout_payload, ensure_ascii=False),
            custom_name="Veterans Prime",
            db=session,
            current_user=fixture["user"],
        )
        update_payload = _json_response_payload(update_response)

        refreshed_primary = session.get(models.RosterUnit, roster_unit.id)
        refreshed_secondary = session.get(models.RosterUnit, other_unit.id)
        assert refreshed_primary is not None
        assert refreshed_secondary is not None

        total_from_units = float(refreshed_primary.cached_cost or 0.0) + float(
            refreshed_secondary.cached_cost or 0.0
        )
        persisted_loadout = json.loads(update_payload["unit"]["loadout_json"])
        persisted_quote = _json_response_payload(
            rosters.quote_roster_unit(
                roster.id,
                roster_unit.id,
                payload={"count": 4, "loadout": persisted_loadout},
                db=session,
                current_user=fixture["user"],
            )
        )

        assert update_payload["unit"]["id"] == roster_unit.id
        assert update_payload["unit"]["custom_name"] == "Veterans Prime"
        assert quote_payload["roster_unit_id"] == roster_unit.id
        assert quote_payload["unit_id"] == roster_unit.id
        assert quote_payload["selected_total"] > 0
        assert update_payload["unit"]["cached_cost"] == persisted_quote["selected_total"]
        assert update_payload["total_cost"] == total_from_units
    finally:
        session.close()
def test_quote_endpoint_returns_zero_totals_for_zero_negative_and_unparsable_count() -> None:
    session = _session()
    try:
        fixture = _build_roster_fixture(session)
        roster = fixture["roster"]
        roster_unit = fixture["unit_a"]

        quoted_zero = _json_response_payload(
            rosters.quote_roster_unit(
                roster.id,
                roster_unit.id,
                payload={"count": 0, "loadout": {"mode": "per_model"}},
                db=session,
                current_user=fixture["user"],
            )
        )
        quoted_negative = _json_response_payload(
            rosters.quote_roster_unit(
                roster.id,
                roster_unit.id,
                payload={"count": -3, "loadout": {"mode": "per_model"}},
                db=session,
                current_user=fixture["user"],
            )
        )
        quoted_unparsable = _json_response_payload(
            rosters.quote_roster_unit(
                roster.id,
                roster_unit.id,
                payload={"count": "oops", "loadout": {"mode": "per_model"}},
                db=session,
                current_user=fixture["user"],
            )
        )

        assert quoted_zero["count"] == 0
        assert quoted_negative["count"] == 0
        assert quoted_unparsable["count"] == 0
        assert quoted_zero["roster_unit_id"] == roster_unit.id
        assert quoted_negative["roster_unit_id"] == roster_unit.id
        assert quoted_unparsable["roster_unit_id"] == roster_unit.id
        assert quoted_zero["unit_id"] == roster_unit.id
        assert quoted_negative["unit_id"] == roster_unit.id
        assert quoted_unparsable["unit_id"] == roster_unit.id
        assert quoted_zero["selected_total"] == 0.0
        assert quoted_negative["selected_total"] == 0.0
        assert quoted_unparsable["selected_total"] == 0.0
    finally:
        session.close()


def test_quote_endpoint_returns_item_costs_and_selected_role() -> None:
    session = _session()
    try:
        fixture = _build_roster_fixture(session)
        roster = fixture["roster"]
        roster_unit = fixture["unit_a"]
        ids = fixture["ids"]

        response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={
                "count": 2,
                "loadout": {
                    "mode": "per_model",
                    "weapons": {str(ids["blade"]): 1},
                    "active": {str(ids["scout"]): 1},
                    "aura": {str(ids["heavy"]): 1},
                    "passive": {"otwarty_transport(2)": 1},
                },
            },
            db=session,
            current_user=fixture["user"],
        )
        payload = _json_response_payload(response)

        # selected_role is present and valid
        assert payload["selected_role"] in {"wojownik", "strzelec"}

        # item_costs structure is present
        assert "item_costs" in payload
        item_costs = payload["item_costs"]
        assert "weapons" in item_costs
        assert "active" in item_costs
        assert "aura" in item_costs
        assert "passive_deltas" in item_costs

        # weapons: blade is in loadout so should have a cost
        assert str(ids["blade"]) in item_costs["weapons"]
        assert item_costs["weapons"][str(ids["blade"])] >= 0.0

        # active: scout should have a cost
        assert str(ids["scout"]) in item_costs["active"]

        # aura: heavy should have a cost
        assert str(ids["heavy"]) in item_costs["aura"]

        # passive_deltas: otwarty_transport should have an entry
        assert "otwarty_transport" in item_costs["passive_deltas"]
        # delta for a transport should be non-zero when enabled
        assert item_costs["passive_deltas"]["otwarty_transport"] != 0.0

        # zero-count: item_costs is empty dicts
        zero_response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={"count": 0, "loadout": {}},
            db=session,
            current_user=fixture["user"],
        )
        zero_payload = _json_response_payload(zero_response)
        assert zero_payload["item_costs"] == {
            "weapons": {},
            "active": {},
            "aura": {},
            "passive_deltas": {},
        }
    finally:
        session.close()


def test_quote_item_costs_weapons_match_weapon_cost_per_model() -> None:
    session = _session()
    try:
        fixture = _build_roster_fixture(session)
        roster = fixture["roster"]
        roster_unit = fixture["unit_a"]
        ids = fixture["ids"]

        response = rosters.quote_roster_unit(
            roster.id,
            roster_unit.id,
            payload={
                "count": 3,
                "loadout": {
                    "mode": "per_model",
                    "weapons": {str(ids["blade"]): 1},
                },
            },
            db=session,
            current_user=fixture["user"],
        )
        payload = _json_response_payload(response)

        # item_costs.weapons[blade] should equal weapon_cost per 1 model with role traits
        blade_item_cost = payload["item_costs"]["weapons"][str(ids["blade"])]
        # weapon_component = item_cost * count (per_model * 1 weapon * 3 models)
        assert payload["components"]["weapon"] == pytest.approx(
            blade_item_cost * 3, abs=0.05
        )
    finally:
        session.close()
