from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.db import Base, get_db
from app.main import app
from app.security import hash_password


def _client_with_fixture():
    # Two owners, two private armies. `stranger` owns neither `victim`'s
    # army nor any unit in it — used to prove cross-tenant IDOR is closed.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override

    with session_local() as db:
        victim = models.User(username="victim", password_hash=hash_password("pass"))
        stranger = models.User(username="stranger", password_hash=hash_password("pass"))
        ruleset = models.RuleSet(name="Core")
        armory = models.Armory(name="Base")
        private_army = models.Army(name="Private", owner=victim, ruleset=ruleset, armory=armory)
        unit = models.Unit(
            name="Secret Unit", quality=4, defense=4, toughness=1, army=private_army
        )
        db.add_all([victim, stranger, ruleset, armory, private_army, unit])
        db.commit()
        unit_id = unit.id

    client = TestClient(app)
    return client, unit_id


def test_stranger_cannot_add_collection_model_for_foreign_private_unit():
    client, unit_id = _client_with_fixture()
    try:
        client.post("/auth/login", data={"username": "stranger", "password": "pass"})
        response = client.post(
            f"/collections/units/{unit_id}/models/add",
            data={"label": "x", "count": "1"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_stranger_cannot_view_foreign_private_unit_collection_page():
    client, unit_id = _client_with_fixture()
    try:
        client.post("/auth/login", data={"username": "stranger", "password": "pass"})
        response = client.get(f"/collections/units/{unit_id}")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_owner_can_add_collection_model_for_own_unit():
    client, unit_id = _client_with_fixture()
    try:
        client.post("/auth/login", data={"username": "victim", "password": "pass"})
        response = client.post(
            f"/collections/units/{unit_id}/models/add",
            data={"label": "x", "count": "1"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
    finally:
        app.dependency_overrides.clear()
