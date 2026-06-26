from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, models
from app.db import Base


def _memory_engine():
    return create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_unit_base_geometry_defaults_on_fresh_schema():
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session() as session:
        user = models.User(username="base-defaults", password_hash="x")
        ruleset = models.RuleSet(name="Rules")
        armory = models.Armory(name="Armory", owner=user)
        army = models.Army(name="Army", owner=user, ruleset=ruleset, armory=armory)
        unit = models.Unit(
            army=army,
            name="Piechota",
            quality=4,
            defense=5,
            toughness=3,
        )
        session.add_all([user, ruleset, armory, army, unit])
        session.commit()
        session.refresh(unit)

        assert unit.base_size_mm == 25
        assert unit.base_shape == "round"


def test_migrate_schema_adds_unit_base_geometry_columns(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE armories (id INTEGER PRIMARY KEY, owner_id INTEGER)"))
        connection.execute(text("INSERT INTO armories (id, owner_id) VALUES (1, NULL)"))
        connection.execute(
            text(
                """
                CREATE TABLE units (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    quality INTEGER NOT NULL,
                    defense INTEGER NOT NULL,
                    toughness INTEGER NOT NULL,
                    flags TEXT,
                    default_weapon_id INTEGER,
                    parent_id INTEGER,
                    army_id INTEGER NOT NULL,
                    owner_id INTEGER,
                    position INTEGER NOT NULL DEFAULT 0,
                    typical_models INTEGER NOT NULL DEFAULT 1,
                    group_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO units (
                    id, name, quality, defense, toughness, army_id, position,
                    typical_models, group_id
                )
                VALUES (1, 'Stara piechota', 4, 5, 3, 10, 2, 6, NULL)
                """
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()

    columns = {column["name"]: column for column in inspect(engine).get_columns("units")}
    assert columns["base_size_mm"]["nullable"] is False
    assert columns["base_shape"]["nullable"] is False

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT base_size_mm, base_shape FROM units WHERE id = 1")
        ).mappings().one()

    assert row["base_size_mm"] == 25
    assert row["base_shape"] == "round"
