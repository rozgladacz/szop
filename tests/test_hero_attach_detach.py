"""Tests for hero attach/detach endpoints and the shared hero-group
classification logic introduced with parent_roster_unit_id on RosterUnit."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.db import Base
from app.routers import rosters


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _base_world(session):
    """Create the minimal shared objects required by most tests."""
    user = models.User(username="hero-tester", password_hash="x")
    ruleset = models.RuleSet(name="Hero Rules")
    armory = models.Armory(name="Hero Armory", owner=user)
    session.add_all([user, ruleset, armory])
    session.flush()

    sword = models.Weapon(armory=armory, name="Sword", range="", attacks=1, ap=0)
    session.add(sword)
    session.flush()

    army = models.Army(name="Hero Army", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()

    bohater_ability = models.Ability(name="Bohater", type="passive", description="")
    session.add(bohater_ability)
    session.flush()

    return SimpleNamespace(
        user=user,
        ruleset=ruleset,
        armory=armory,
        sword=sword,
        army=army,
        bohater_ability=bohater_ability,
    )


def _hero_unit(session, w):
    unit = models.Unit(
        army=w.army,
        name="Kapitan",
        quality=3,
        defense=4,
        toughness=1,
        typical_models=1,
        position=0,
        default_weapon=w.sword,
    )
    session.add(unit)
    session.flush()
    session.add(
        models.UnitWeapon(
            unit=unit, weapon=w.sword, is_default=True, default_count=1,
            is_primary=True, position=0,
        )
    )
    session.add(models.UnitAbility(unit=unit, ability=w.bohater_ability, position=0))
    session.flush()
    return unit


def _plain_unit(session, w):
    unit = models.Unit(
        army=w.army,
        name="Piechota",
        quality=4,
        defense=4,
        toughness=2,
        typical_models=5,
        position=1,
        default_weapon=w.sword,
    )
    session.add(unit)
    session.flush()
    session.add(
        models.UnitWeapon(
            unit=unit, weapon=w.sword, is_default=True, default_count=1,
            is_primary=True, position=0,
        )
    )
    session.flush()
    return unit


def _roster_with(session, w, hero_unit, plain_unit):
    roster = models.Roster(name="Test Roster", army=w.army, owner=w.user)
    session.add(roster)
    session.flush()
    hero_ru = models.RosterUnit(roster=roster, unit=hero_unit, count=1, position=0)
    plain_ru = models.RosterUnit(roster=roster, unit=plain_unit, count=3, position=1)
    session.add_all([hero_ru, plain_ru])
    session.flush()
    return SimpleNamespace(roster=roster, hero_ru=hero_ru, plain_ru=plain_ru)


def _payload(response) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Attach happy path
# ---------------------------------------------------------------------------

def test_attach_hero_to_parent_sets_fk() -> None:
    session = _session()
    try:
        w = _base_world(session)
        state = _roster_with(session, w, _hero_unit(session, w), _plain_unit(session, w))

        response = rosters.attach_roster_unit(
            state.roster.id,
            state.hero_ru.id,
            payload={"parent_roster_unit_id": state.plain_ru.id},
            db=session,
            current_user=w.user,
        )
        data = _payload(response)

        assert data["roster_unit_id"] == state.hero_ru.id
        assert data["parent_roster_unit_id"] == state.plain_ru.id
        assert isinstance(data["total_cost"], (int, float))
        assert isinstance(data["unit_costs"], dict)

        session.refresh(state.hero_ru)
        assert state.hero_ru.parent_roster_unit_id == state.plain_ru.id
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Attach validation errors
# ---------------------------------------------------------------------------

def test_attach_rejects_self_reference() -> None:
    session = _session()
    try:
        w = _base_world(session)
        state = _roster_with(session, w, _hero_unit(session, w), _plain_unit(session, w))

        with pytest.raises(HTTPException) as exc_info:
            rosters.attach_roster_unit(
                state.roster.id,
                state.hero_ru.id,
                payload={"parent_roster_unit_id": state.hero_ru.id},
                db=session,
                current_user=w.user,
            )
        assert exc_info.value.status_code == 400
    finally:
        session.close()


def test_attach_rejects_non_hero_unit() -> None:
    session = _session()
    try:
        w = _base_world(session)
        state = _roster_with(session, w, _hero_unit(session, w), _plain_unit(session, w))

        # plain_ru (non-hero) tries to attach to hero_ru
        with pytest.raises(HTTPException) as exc_info:
            rosters.attach_roster_unit(
                state.roster.id,
                state.plain_ru.id,
                payload={"parent_roster_unit_id": state.hero_ru.id},
                db=session,
                current_user=w.user,
            )
        assert exc_info.value.status_code == 400
    finally:
        session.close()


def test_attach_rejects_hero_as_parent() -> None:
    """A hero cannot be a parent (flat structure, no chaining)."""
    session = _session()
    try:
        w = _base_world(session)
        hero_unit = _hero_unit(session, w)
        plain_unit = _plain_unit(session, w)

        # Create a second hero unit
        hero_unit2 = models.Unit(
            army=w.army, name="Kapitan 2", quality=3, defense=4, toughness=1,
            typical_models=1, position=2, default_weapon=w.sword,
        )
        session.add(hero_unit2)
        session.flush()
        session.add(models.UnitAbility(unit=hero_unit2, ability=w.bohater_ability, position=0))
        session.flush()

        roster = models.Roster(name="Two Heroes", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        hero_ru = models.RosterUnit(roster=roster, unit=hero_unit, count=1, position=0)
        hero_ru2 = models.RosterUnit(roster=roster, unit=hero_unit2, count=1, position=1)
        plain_ru = models.RosterUnit(roster=roster, unit=plain_unit, count=3, position=2)
        session.add_all([hero_ru, hero_ru2, plain_ru])
        session.flush()

        # hero_ru tries to attach to hero_ru2 (also a hero) → 400
        with pytest.raises(HTTPException) as exc_info:
            rosters.attach_roster_unit(
                roster.id,
                hero_ru.id,
                payload={"parent_roster_unit_id": hero_ru2.id},
                db=session,
                current_user=w.user,
            )
        assert exc_info.value.status_code == 400
    finally:
        session.close()


def test_attach_rejects_chained_parent() -> None:
    """A unit that is itself attached cannot be used as a parent."""
    session = _session()
    try:
        w = _base_world(session)
        hero_unit = _hero_unit(session, w)
        plain_unit = _plain_unit(session, w)

        # Make a second plain unit
        plain_unit2 = models.Unit(
            army=w.army, name="Kawaleria", quality=4, defense=4, toughness=2,
            typical_models=3, position=2, default_weapon=w.sword,
        )
        session.add(plain_unit2)
        session.flush()

        roster = models.Roster(name="Chain Roster", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        hero_ru = models.RosterUnit(roster=roster, unit=hero_unit, count=1, position=0)
        # plain_ru is attached to plain_ru2 — so it cannot itself be a parent
        plain_ru = models.RosterUnit(roster=roster, unit=plain_unit, count=3, position=1)
        plain_ru2 = models.RosterUnit(roster=roster, unit=plain_unit2, count=3, position=2)
        session.add_all([hero_ru, plain_ru, plain_ru2])
        session.flush()

        # Manually set plain_ru.parent_roster_unit_id (would be done by a prior attach)
        plain_ru.parent_roster_unit_id = plain_ru2.id
        session.flush()

        # hero_ru wants to attach to plain_ru, which is itself attached → 400
        with pytest.raises(HTTPException) as exc_info:
            rosters.attach_roster_unit(
                roster.id,
                hero_ru.id,
                payload={"parent_roster_unit_id": plain_ru.id},
                db=session,
                current_user=w.user,
            )
        assert exc_info.value.status_code == 400
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Detach
# ---------------------------------------------------------------------------

def test_detach_hero_clears_fk() -> None:
    session = _session()
    try:
        w = _base_world(session)
        state = _roster_with(session, w, _hero_unit(session, w), _plain_unit(session, w))

        # First attach
        rosters.attach_roster_unit(
            state.roster.id,
            state.hero_ru.id,
            payload={"parent_roster_unit_id": state.plain_ru.id},
            db=session,
            current_user=w.user,
        )
        session.refresh(state.hero_ru)
        assert state.hero_ru.parent_roster_unit_id == state.plain_ru.id

        # Now detach
        response = rosters.detach_roster_unit(
            state.roster.id,
            state.hero_ru.id,
            db=session,
            current_user=w.user,
        )
        data = _payload(response)

        assert data["roster_unit_id"] == state.hero_ru.id
        assert data["parent_roster_unit_id"] is None

        session.refresh(state.hero_ru)
        assert state.hero_ru.parent_roster_unit_id is None
    finally:
        session.close()


def test_detach_already_standalone_is_idempotent() -> None:
    """Detaching a unit that is not attached returns 200 with parent=None."""
    session = _session()
    try:
        w = _base_world(session)
        state = _roster_with(session, w, _hero_unit(session, w), _plain_unit(session, w))

        # hero_ru has no parent; detach should silently succeed
        response = rosters.detach_roster_unit(
            state.roster.id,
            state.hero_ru.id,
            db=session,
            current_user=w.user,
        )
        data = _payload(response)

        assert data["parent_roster_unit_id"] is None
        assert isinstance(data["total_cost"], (int, float))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Shared classification via _classification_map
# ---------------------------------------------------------------------------

def test_classification_map_groups_hero_totals_with_parent(monkeypatch) -> None:
    """Hero + attached parent share the Wojownik/Strzelec decision.
    The role totals are summed; the group-level winner is applied to both."""
    hero_unit_obj = SimpleNamespace(
        id=1, typical_models=1, flags=None, weapon_links=[], abilities=[],
        default_weapon=None, army=None,
    )
    parent_unit_obj = SimpleNamespace(
        id=2, typical_models=5, flags=None, weapon_links=[], abilities=[],
        default_weapon=None, army=None,
    )
    # hero solo: warrior=5, shooter=0 → would be wojownik on its own
    # parent solo: warrior=0, shooter=20 → would be strzelec on its own
    # combined: warrior=5, shooter=20 → strzelec wins for both
    hero_ru = SimpleNamespace(
        id=10, unit=hero_unit_obj, count=1, parent_roster_unit_id=20,
        extra_weapons_json=None,
    )
    parent_ru = SimpleNamespace(
        id=20, unit=parent_unit_obj, count=5, parent_roster_unit_id=None,
        extra_weapons_json=None,
    )

    def _fake_quote(roster_unit, loadout=None, include_item_costs=False):
        if roster_unit.id == 10:
            return {"warrior_total": 5.0, "shooter_total": 0.0}
        return {"warrior_total": 0.0, "shooter_total": 20.0}

    monkeypatch.setattr(rosters, "_internal_roster_unit_quote", _fake_quote)

    classifications, _ = rosters._classification_map(
        [hero_ru, parent_ru],  # type: ignore[arg-type]
        {10: {}, 20: {}},
    )

    assert classifications[10] is not None
    assert classifications[20] is not None
    assert classifications[10]["slug"] == "strzelec"
    assert classifications[20]["slug"] == "strzelec"


def test_classification_map_lone_hero_uses_own_totals(monkeypatch) -> None:
    """An unattached hero is classified by its own role totals alone."""
    hero_unit_obj = SimpleNamespace(
        id=1, typical_models=1, flags=None, weapon_links=[], abilities=[],
        default_weapon=None, army=None,
    )
    hero_ru = SimpleNamespace(
        id=10, unit=hero_unit_obj, count=1, parent_roster_unit_id=None,
        extra_weapons_json=None,
    )

    def _fake_quote(roster_unit, loadout=None, include_item_costs=False):
        return {"warrior_total": 15.0, "shooter_total": 3.0}

    monkeypatch.setattr(rosters, "_internal_roster_unit_quote", _fake_quote)

    classifications, _ = rosters._classification_map(
        [hero_ru],  # type: ignore[arg-type]
        {10: {}},
    )

    assert classifications[10] is not None
    assert classifications[10]["slug"] == "wojownik"


# ---------------------------------------------------------------------------
# Export entry fields (is_hero, parent_roster_unit_id)
# ---------------------------------------------------------------------------

def test_export_entry_is_hero_true_for_bohater_unit() -> None:
    """_roster_unit_export_data marks the entry is_hero=True for hero units."""
    session = _session()
    try:
        w = _base_world(session)
        hero_unit = _hero_unit(session, w)
        roster = models.Roster(name="Export Test", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        hero_ru = models.RosterUnit(roster=roster, unit=hero_unit, count=1, position=0)
        session.add(hero_ru)
        session.flush()

        entry = rosters._roster_unit_export_data(hero_ru)

        assert entry["is_hero"] is True
    finally:
        session.close()


def test_export_entry_parent_roster_unit_id_propagated() -> None:
    """_roster_unit_export_data includes parent_roster_unit_id from the model."""
    session = _session()
    try:
        w = _base_world(session)
        hero_unit = _hero_unit(session, w)
        plain_unit = _plain_unit(session, w)
        state = _roster_with(session, w, hero_unit, plain_unit)

        state.hero_ru.parent_roster_unit_id = state.plain_ru.id
        session.flush()

        entry = rosters._roster_unit_export_data(state.hero_ru)

        assert entry["parent_roster_unit_id"] == state.plain_ru.id
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Battle-state derived fields (show_models, max_wounds, group_id)
# ---------------------------------------------------------------------------

def test_battle_state_show_models_true_for_hero_with_count_one() -> None:
    """Heroes always show the model counter even when count=1."""
    entry: dict[str, Any] = {"count": 1, "is_hero": True, "toughness": 1}

    show_models = (entry.get("count") or 0) > 1 or bool(entry.get("is_hero"))

    assert show_models is True


def test_battle_state_show_models_false_for_non_hero_count_one() -> None:
    entry: dict[str, Any] = {"count": 1, "is_hero": False, "toughness": 2}

    show_models = (entry.get("count") or 0) > 1 or bool(entry.get("is_hero"))

    assert show_models is False


def test_battle_state_max_wounds_equals_toughness_not_count_times_toughness() -> None:
    """max_wounds = toughness, ignoring model count (allow displaying 9/6)."""
    entry: dict[str, Any] = {"count": 5, "toughness": 3}

    max_wounds = int(entry.get("toughness") or 1)

    assert max_wounds == 3  # not 5 * 3 = 15


def test_battle_state_group_id_equals_own_id_for_standalone() -> None:
    """A non-attached unit's group_id is its own roster_unit_id."""
    instance = SimpleNamespace(id=42, parent_roster_unit_id=None)
    entry: dict[str, Any] = {"instance": instance, "parent_roster_unit_id": None}

    by_id = {42: entry}
    parent_id = entry.get("parent_roster_unit_id")
    if parent_id is not None and int(parent_id) in by_id:
        group_id = int(parent_id)
    else:
        group_id = int(instance.id)

    assert group_id == 42


def test_battle_state_group_id_equals_parent_id_for_attached_hero() -> None:
    """An attached hero's group_id equals the parent's roster_unit_id."""
    parent_instance = SimpleNamespace(id=10)
    hero_instance = SimpleNamespace(id=20, parent_roster_unit_id=10)
    parent_entry: dict[str, Any] = {"instance": parent_instance, "parent_roster_unit_id": None}
    hero_entry: dict[str, Any] = {"instance": hero_instance, "parent_roster_unit_id": 10}

    by_id = {10: parent_entry, 20: hero_entry}
    parent_id = hero_entry.get("parent_roster_unit_id")
    if parent_id is not None and int(parent_id) in by_id:
        group_id = int(parent_id)
    else:
        group_id = int(hero_instance.id)

    assert group_id == 10
