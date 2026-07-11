from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.db import Base
from app.routers import armies
from app.services import ability_registry


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _global_army_fixture(session):
    # owner=None -> "global" army: viewable by any authenticated user,
    # editable only by admins (see _army_can_edit / _ensure_army_edit_access).
    viewer = models.User(username="viewer", password_hash="secret")
    admin = models.User(username="admin", password_hash="secret", is_admin=True)
    ruleset = models.RuleSet(name="Core")
    armory = models.Armory(name="Base")
    army = models.Army(name="Global", owner=None, ruleset=ruleset, armory=armory)
    session.add_all([viewer, admin, ruleset, armory, army])
    ability_registry.sync_definitions(session)
    session.flush()
    return viewer, admin, army


def test_view_only_user_passes_the_spells_route_access_gate():
    # edit_army_spells() must gate on view access (not edit access) so a
    # view-only user reaches the template render instead of a 403.
    session = _session()
    try:
        viewer, _admin, army = _global_army_fixture(session)
        armies._ensure_army_view_access(army, viewer)  # must not raise
        with pytest.raises(HTTPException):
            armies._ensure_army_edit_access(army, viewer)
    finally:
        session.close()


def test_spell_page_context_marks_view_only_user_as_cannot_edit():
    session = _session()
    try:
        viewer, admin, army = _global_army_fixture(session)
        viewer_ctx = armies._spell_page_context(
            Request({"type": "http"}), army, viewer, session
        )
        admin_ctx = armies._spell_page_context(
            Request({"type": "http"}), army, admin, session
        )
        assert viewer_ctx["can_edit"] is False
        assert admin_ctx["can_edit"] is True
    finally:
        session.close()


def test_spell_page_context_skips_ability_catalog_for_view_only_user():
    # Efficiency regression: the add/edit-power form (and the ability_options /
    # passive_definitions it needs) is edit-only UI. A view-only user must not
    # pay for building it (ability_registry.definition_payload triggers a
    # catalog sync + full scan on every call).
    session = _session()
    try:
        viewer, admin, army = _global_army_fixture(session)
        viewer_ctx = armies._spell_page_context(
            Request({"type": "http"}), army, viewer, session
        )
        admin_ctx = armies._spell_page_context(
            Request({"type": "http"}), army, admin, session
        )
        assert viewer_ctx["ability_options"] == []
        assert viewer_ctx["passive_definitions"] == []
        assert admin_ctx["ability_options"] != []
    finally:
        session.close()


def test_view_only_user_cannot_add_spell():
    session = _session()
    try:
        viewer, _admin, army = _global_army_fixture(session)
        ability = ability_registry._get_ability_lookup_maps(session, "active")[1]["demoralizacja"]
        with pytest.raises(HTTPException) as exc_info:
            armies.add_army_spell_ability(
                army.id,
                Request({"type": "http"}),
                ability_id=ability.id,
                ability_value=None,
                custom_name=None,
                cast_difficulty=4,
                db=session,
                current_user=viewer,
            )
        assert exc_info.value.status_code == 403
    finally:
        session.close()


def test_non_viewer_still_blocked_from_owned_army_spell_list():
    session = _session()
    try:
        owner = models.User(username="owner2", password_hash="secret")
        stranger = models.User(username="stranger", password_hash="secret")
        ruleset = models.RuleSet(name="Core")
        armory = models.Armory(name="Base")
        army = models.Army(name="Owned", owner=owner, ruleset=ruleset, armory=armory)
        session.add_all([owner, stranger, ruleset, armory, army])
        session.flush()
        with pytest.raises(HTTPException) as exc_info:
            armies.edit_army_spells(
                army.id, Request({"type": "http"}), db=session, current_user=stranger
            )
        assert exc_info.value.status_code == 403
    finally:
        session.close()
