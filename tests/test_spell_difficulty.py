from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app import db as dbmod
from app.db import Base
from app.routers import armies
from app.services import ability_registry, costs


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _army_fixture(session):
    user = models.User(username="owner", password_hash="secret")
    ruleset = models.RuleSet(name="Core")
    armory = models.Armory(name="Base")
    army = models.Army(name="Alpha", owner=user, ruleset=ruleset, armory=armory)
    session.add_all([user, ruleset, armory, army])
    ability_registry.sync_definitions(session)
    session.flush()
    return user, army


def _active_ability(session, slug):
    _by_id, by_slug = ability_registry._get_ability_lookup_maps(session, "active")
    return by_slug[slug]


# --- helpers --------------------------------------------------------------

def test_cast_chance_values():
    assert costs.cast_chance(4) == 0.5
    assert round(costs.cast_chance(2), 4) == 0.8333
    assert round(costs.cast_chance(6), 4) == 0.1667
    # out of range clamps
    assert costs.cast_chance(9) == costs.cast_chance(6)


def test_spell_token_cost_helpers():
    # Demoralizacja: 25 pkt; dzielnik /5 (bylo /10)
    assert costs.spell_ability_token_cost(25, 4) == 3   # ceil(25*0.5/5)
    assert costs.spell_ability_token_cost(25, 2) == 5   # ceil(25*5/6/5)
    assert costs.spell_ability_token_cost(25, 6) == 1   # ceil(25/6/5)
    # negative point cost -> 0 tokens
    assert costs.spell_ability_token_cost(-6, 4) == 0
    assert costs.spell_weapon_token_cost(70) == 14
    assert costs.spell_weapon_token_cost(0) == 0


# --- add-ability route ----------------------------------------------------

def test_add_ability_spell_stores_difficulty_and_token_cost():
    session = _session()
    try:
        user, army = _army_fixture(session)
        ability = _active_ability(session, "demoralizacja")

        armies.add_army_spell_ability(
            army.id,
            Request({"type": "http"}),
            ability_id=ability.id,
            ability_value=None,
            custom_name=None,
            cast_difficulty=6,
            db=session,
            current_user=user,
        )

        spells = list(army.spells)
        assert len(spells) == 1
        spell = spells[0]
        assert spell.cast_difficulty == 6
        # 25 pkt, D=6 -> ceil(25*(1/6)/10) = 1
        assert spell.cost == 1
    finally:
        session.close()


def test_add_ability_spell_clamps_difficulty():
    session = _session()
    try:
        user, army = _army_fixture(session)
        ability = _active_ability(session, "demoralizacja")
        armies.add_army_spell_ability(
            army.id,
            Request({"type": "http"}),
            ability_id=ability.id,
            ability_value=None,
            custom_name=None,
            cast_difficulty=99,
            db=session,
            current_user=user,
        )
        spell = list(army.spells)[0]
        assert spell.cast_difficulty == costs.SPELL_DIFFICULTY_MAX
    finally:
        session.close()


# --- ability cost preview endpoint ---------------------------------------

def test_ability_cost_preview_returns_point_and_tokens():
    session = _session()
    try:
        user, army = _army_fixture(session)
        ability = _active_ability(session, "demoralizacja")

        response = armies.spell_ability_cost_preview(
            army.id,
            payload={"ability_id": ability.id, "value": ""},
            db=session,
            current_user=user,
        )
        import json

        data = json.loads(bytes(response.body))
        assert data["point_cost"] == 25
        assert data["tokens"]["4"] == 3
        assert data["tokens"]["2"] == 5
        assert data["tokens"]["6"] == 1
    finally:
        session.close()


def test_ability_cost_preview_rejects_forbidden_slug():
    session = _session()
    try:
        user, army = _army_fixture(session)
        ability = _active_ability(session, "mag")
        response = armies.spell_ability_cost_preview(
            army.id,
            payload={"ability_id": ability.id, "value": "2"},
            db=session,
            current_user=user,
        )
        import json

        data = json.loads(bytes(response.body))
        assert data == {"point_cost": 0, "tokens": {}}
    finally:
        session.close()


# --- edit / update ability spell ------------------------------------------

def _add_ability(session, user, army, slug, value=None, custom="Stara", difficulty=4):
    ability = _active_ability(session, slug)
    armies.add_army_spell_ability(
        army.id,
        Request({"type": "http"}),
        ability_id=ability.id,
        ability_value=value,
        custom_name=custom,
        cast_difficulty=difficulty,
        db=session,
        current_user=user,
    )
    return list(army.spells)[-1]


def test_edit_ability_context_includes_editing_spell():
    session = _session()
    try:
        user, army = _army_fixture(session)
        spell = _add_ability(session, user, army, "demoralizacja")
        ctx = armies._spell_page_context(
            Request({"type": "http"}), army, user, session, editing_spell=spell
        )
        assert ctx["editing_spell"].id == spell.id
    finally:
        session.close()


def test_update_ability_spell_changes_difficulty_name_and_cost():
    session = _session()
    try:
        user, army = _army_fixture(session)
        spell = _add_ability(session, user, army, "demoralizacja", difficulty=4)
        sid, pos = spell.id, spell.position
        armies.update_army_spell_ability(
            army.id,
            sid,
            Request({"type": "http"}),
            ability_id=_active_ability(session, "demoralizacja").id,
            ability_value=None,
            custom_name="Nowa",
            cast_difficulty=6,
            db=session,
            current_user=user,
        )
        session.refresh(spell)
        assert spell.cast_difficulty == 6
        assert spell.normalized_custom_name == "Nowa"
        assert spell.position == pos  # kolejnosc zachowana
        assert spell.cost == 1  # 25 pkt, D6 -> ceil(25/6/5) = 1
    finally:
        session.close()


def test_update_ability_spell_can_switch_ability_and_value():
    session = _session()
    try:
        user, army = _army_fixture(session)
        spell = _add_ability(session, user, army, "demoralizacja")
        klatwa = _active_ability(session, "klatwa")
        armies.update_army_spell_ability(
            army.id,
            spell.id,
            Request({"type": "http"}),
            ability_id=klatwa.id,
            ability_value="wolny",
            custom_name="",
            cast_difficulty=4,
            db=session,
            current_user=user,
        )
        session.refresh(spell)
        assert spell.ability_id == klatwa.id
        assert spell.ability_value == "wolny"
    finally:
        session.close()


# --- weapon cost preview (regression: string abilities + quality) ---------

def test_spell_weapon_cost_accepts_string_abilities_and_varies_with_quality():
    # The cost-preview JS sends `abilities` as plain trait strings, not dicts.
    # Regression: this previously raised 500 (AttributeError: str has no .get).
    def fv(quality):
        return {
            "range": "12",
            "attacks": "2",
            "ap": "2",
            "quality": quality,
            "abilities": ["Zabójczy(3)", "Namierzanie"],
        }

    token2, point2 = armies._spell_weapon_cost(None, fv("2"))
    token6, point6 = armies._spell_weapon_cost(None, fv("6"))
    assert token2 is not None and point2 is not None
    # Lower difficulty (higher hit chance) costs more than higher difficulty.
    assert point2 > point6
    assert token2 > token6
    # Dict-shaped abilities (form-parse path) must still work.
    token_dict, _ = armies._spell_weapon_cost(
        None,
        {
            "range": "12",
            "attacks": "2",
            "ap": "2",
            "quality": "4",
            "abilities": [
                {"slug": "zabojczy", "value": "3", "label": "", "raw": "Zabójczy(3)", "description": ""}
            ],
        },
    )
    assert token_dict is not None


def test_weapon_spell_cost_ignores_armory_cache():
    # weapon_cost() returns the cached armory cost at quality 4; the spell cost
    # must compute fresh so the saved list value matches the live preview
    # (regression: 4+ showed 2 in preview but 3 in the list).
    weapon = models.Weapon(
        name="Granat", range="12", attacks=1.0, ap=2, tags="Namierzanie"
    )
    fresh = costs.weapon_cost(weapon, unit_quality=4, use_cached=False)
    weapon.cached_cost = fresh + 50.0  # bogus stale cache that must be ignored
    _, _, token = armies._weapon_spell_details(weapon, 4)
    assert token == costs.spell_weapon_token_cost(fresh)


# --- schema migration -----------------------------------------------------

def test_army_spells_cast_difficulty_migration(tmp_path, monkeypatch):
    path = tmp_path / "migrate.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    # Recreate army_spells in the legacy shape (without cast_difficulty).
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE army_spells"))
        conn.execute(
            text(
                "CREATE TABLE army_spells ("
                "id INTEGER PRIMARY KEY, army_id INTEGER NOT NULL, kind VARCHAR(20) NOT NULL, "
                "ability_id INTEGER, ability_value VARCHAR(120), weapon_id INTEGER, "
                "base_label VARCHAR(200), description TEXT, "
                "cost INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0, "
                "custom_name VARCHAR(120))"
            )
        )

    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "DB_URL", f"sqlite:///{path}")

    assert "cast_difficulty" not in {
        c["name"] for c in inspect(engine).get_columns("army_spells")
    }
    dbmod._migrate_schema()
    cols = {c["name"] for c in inspect(engine).get_columns("army_spells")}
    assert "cast_difficulty" in cols
    # Idempotent: a second run must not error.
    dbmod._migrate_schema()
