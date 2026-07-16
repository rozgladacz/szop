from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app import db as dbmod
from app.db import Base
from app.services import ability_registry


def _make_session(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_units_base_size_migration_backfills_from_toughness(tmp_path, monkeypatch):
    path = tmp_path / "migrate.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)

    session = _make_session(engine)
    ability_registry.sync_definitions(session)
    session.commit()

    hero_ability = session.execute(
        select(models.Ability).where(models.Ability.name == "Bohater")
    ).scalar_one()

    user = models.User(username="owner", password_hash="secret")
    ruleset = models.RuleSet(name="Core")
    armory = models.Armory(name="Base")
    session.add_all([user, ruleset, armory])
    session.flush()
    army = models.Army(name="Test", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()

    def _unit(name: str, toughness: int, *, hero: bool = False) -> models.Unit:
        unit = models.Unit(
            name=name, quality=4, defense=4, toughness=toughness, army=army, owner=user,
        )
        if hero:
            unit.abilities = [models.UnitAbility(ability=hero_ability)]
        return unit

    # Non-heroes: base_size derived directly from toughness.
    # Heroes: derived from floor(toughness / 2) through the same thresholds
    # (SZOP rules: "Jego rozmiar jest traktowany jakby mial 2 razy mniejsza
    # wytrzymalosc" -- app/data/abilities.py "Bohater" description).
    units = {
        "small_t1": _unit("small_t1", 1),
        "small_t2": _unit("small_t2", 2),
        "medium_t3": _unit("medium_t3", 3),
        "medium_t5": _unit("medium_t5", 5),
        "large_t6": _unit("large_t6", 6),
        "large_t10": _unit("large_t10", 10),
        "hero_t6": _unit("hero_t6", 6, hero=True),  # floor(6/2)=3 -> srednia
        "hero_t3": _unit("hero_t3", 3, hero=True),  # floor(3/2)=1 -> mala
        "hero_t13": _unit("hero_t13", 13, hero=True),  # floor(13/2)=6 -> duza
    }
    session.add_all(units.values())
    session.commit()
    ids = {name: u.id for name, u in units.items()}
    session.close()

    # Simulate the legacy (pre-migration) schema: drop the column that
    # Base.metadata.create_all already added from the current ORM model.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE units DROP COLUMN base_size"))

    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "DB_URL", f"sqlite:///{path}")

    assert "base_size" not in {c["name"] for c in inspect(engine).get_columns("units")}
    dbmod._migrate_schema()
    assert "base_size" in {c["name"] for c in inspect(engine).get_columns("units")}

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, base_size FROM units")).all()
    by_id = {row[0]: row[1] for row in rows}

    assert by_id[ids["small_t1"]] == "mala"
    assert by_id[ids["small_t2"]] == "mala"
    assert by_id[ids["medium_t3"]] == "srednia"
    assert by_id[ids["medium_t5"]] == "srednia"
    assert by_id[ids["large_t6"]] == "duza"
    assert by_id[ids["large_t10"]] == "duza"
    assert by_id[ids["hero_t6"]] == "srednia"
    assert by_id[ids["hero_t3"]] == "mala"
    assert by_id[ids["hero_t13"]] == "duza"

    # Idempotent: a second run must not error or disturb already-backfilled values.
    dbmod._migrate_schema()
    with engine.connect() as conn:
        rows_again = conn.execute(text("SELECT id, base_size FROM units")).all()
    assert {row[0]: row[1] for row in rows_again} == by_id
