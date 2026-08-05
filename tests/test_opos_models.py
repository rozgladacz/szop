from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app import models
from app.db import Base, assert_not_legacy_szop_database, ensure_roster_mode_columns


def test_fresh_schema_contains_only_opos_domain_tables() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)

    assert set(inspect(test_engine).get_table_names()) == {
        "users", "armies", "unit_templates", "rosters", "roster_units",
    }


def test_roster_cost_uses_rounded_unit_cost_times_copies() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = models.User(username="test", password_hash="hash")
        roster = models.Roster(name="Test", owner=user)
        roster.roster_units = [
            models.RosterUnit(
                name="Straż",
                models_per_unit=3,
                unit_copies=4,
                defense=Decimal("4"),
                toughness=Decimal("2"),
                profiles_json="{}",
                unit_cost=37,
                position=0,
            )
        ]
        session.add(roster)
        session.flush()

        assert roster.roster_units[0].entry_cost == 148
        assert roster.total_cost == 148


def test_required_foreign_key_and_position_indexes_exist() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    inspector = inspect(test_engine)

    assert "ix_armies_owner_id" in {item["name"] for item in inspector.get_indexes("armies")}
    assert "ix_rosters_owner_id" in {item["name"] for item in inspector.get_indexes("rosters")}
    assert "ix_rosters_army_id" in {item["name"] for item in inspector.get_indexes("rosters")}
    assert "ix_unit_templates_army_position" in {
        item["name"] for item in inspector.get_indexes("unit_templates")
    }
    assert "ix_roster_units_roster_position" in {
        item["name"] for item in inspector.get_indexes("roster_units")
    }


def test_legacy_szop_database_is_rejected_before_opos_bootstrap() -> None:
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE armories (id INTEGER PRIMARY KEY)")

    try:
        assert_not_legacy_szop_database(legacy_engine)
    except RuntimeError as exc:
        assert "świeżej bazy data/opos.db" in str(exc)
        assert "armories" in str(exc)
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("Stara baza SZOP powinna zostać odrzucona")


def test_existing_opos_database_passes_legacy_guard() -> None:
    opos_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(opos_engine)

    assert_not_legacy_szop_database(opos_engine)


def test_existing_opos_database_gets_missing_roster_mode_columns() -> None:
    old_engine = create_engine("sqlite:///:memory:")
    with old_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE rosters (id INTEGER PRIMARY KEY, name VARCHAR(120))"
        )

    ensure_roster_mode_columns(old_engine)

    columns = {item["name"] for item in inspect(old_engine).get_columns("rosters")}
    assert {
        "simple_points_enabled",
        "collapse_descriptions",
        "small_battle_enabled",
    } <= columns
