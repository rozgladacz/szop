"""B6 read-only HTML shell and executed Canvas/checkpoint compatibility gates."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.config import SECRET_KEY
from app.db import Base, get_db
from app.main import app
from app.services.engine.activation_protocol import start_activation
from app.services.engine.dice import DeterministicDice
from app.services.engine.persistence import save_checkpoint
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)
from app.services.engine.state_codec import battle_state_to_json
from app.services.engine.status import StatusFlag
from app.services.engine.terrain_complex import TerrainPolygon
from tests.node_runtime import resolve_node_binary

ROOT = Path(__file__).resolve().parents[1]


# === SECTION: Real codec fixtures — independent of presentation and production DB ===
def preview_state() -> BattleState:
    unit = UnitBlob(
        id=1, owner_player=0, position=Position(-4, 8), radius_inches=2,
        models_alive=3, toughness_per_model=2,
        status_flags=(StatusFlag.AKTYWOWANY, "Wyczerpany"),
        passives=("<img src=x onerror=alert(1)>",),
    )
    return BattleState(
        round=2, active_player=1, activations_remaining=(1, 1),
        blobs=(unit, replace(unit, id=2, owner_player=1, position=Position(14, 10)),
               replace(unit, id=3, location=Lokalizacja.ZAPLECZE, position=Position(999, 999)),
               replace(unit, id=4, models_alive=0, location=Lokalizacja.WYCOFANY),
               replace(unit, id=5, models_alive=0),
               replace(unit, id=6, location=Lokalizacja.ELIMINOWANY, models_alive=0)),
        terrain=(TerrainCircle(Position(3, 3), 3, ("Trudny",)),
                 TerrainLine(Position(0, 12), Position(16, 12), ("Obronny",)),
                 TerrainPolygon(
                     (Position(18, 12), Position(21, 12), Position(21, 19),
                      Position(19, 17), Position(18, 19)),
                     ("Blokujacy",),
                 )),
        objectives=(Objective(1, Position(7, 7), 1), Objective(2, Position(12, 5))),
        score=(1, 2),
    )


def public_payload(version: int, battle_id: int = 7, *, active: bool = False) -> dict:
    state = preview_state()
    if version > 1:
        state = replace(state, initiative_player=1)
    if active:
        state = replace(state, blobs=tuple(
            replace(unit, status_flags=()) if unit.id == 2 else unit
            for unit in state.blobs
        ))
        state = start_activation(state, selected_unit_id=2).state
    return {
        **battle_state_to_json(state, version=version),
        "battle_id": battle_id, "sequence_at": 0,
    }


@pytest.fixture
def preview_world():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = models.User(username="preview-owner", password_hash="unused")
        outsider = models.User(username="preview-outsider", password_hash="unused")
        db.add_all([owner, outsider])
        db.flush()
        battles = []
        for version in (1, 2, 3):
            battle = models.Battle(
                p1_user_id=owner.id, p2_user_id=owner.id,
                rng_seed=2026, status="active", activation_protocol_version=version,
            )
            db.add(battle)
            db.flush()
            state = preview_state()
            if version > 1:
                state = replace(state, initiative_player=1)
            save_checkpoint(db, battle.id, 0, state, DeterministicDice(2026), state_version=version)
            battles.append(battle.id)
        unavailable = models.Battle(p1_user_id=owner.id, rng_seed=1, status="active")
        db.add(unavailable)
        db.commit()
        owner_id, outsider_id, unavailable_id = owner.id, outsider.id, unavailable.id

    def database():
        with Session(engine) as db:
            yield db

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    # No lifespan: tests must not initialize or migrate the configured production DB.
    client = TestClient(app)
    try:
        yield client, engine, owner_id, outsider_id, battles, unavailable_id
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def login_cookie(client: TestClient, user_id: int) -> None:
    from base64 import b64encode

    session = b64encode(json.dumps({"user_id": user_id}).encode())
    client.cookies.clear()
    client.cookies.set("session", TimestampSigner(SECRET_KEY).sign(session).decode())


# === SECTION: Shell auth, no oracle and zero domain writes through real HTTP ===
def test_shell_requires_session_and_does_not_lookup_battle(preview_world):
    client, engine, owner, _, ids, _ = preview_world
    response = client.get("/battle-preview?battle_id=1", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"
    login_cookie(client, owner)
    found = client.get(f"/battle-preview?battle_id={ids[0]}")
    missing = client.get("/battle-preview?battle_id=999999")
    assert found.status_code == missing.status_code == 200
    assert found.content == missing.content
    assert "Podgląd bitwy 2D" in found.text
    assert "/js/modules/battle_canvas.js" in found.text
    assert 'method="post"' not in found.text.lower()
    assert "battle_canvas.js" not in client.get("/auth/login").text
    assert client.post("/battle-preview").status_code == 405
    with Session(engine) as db:
        assert len(db.scalars(select(models.Battle)).all()) == 4


@pytest.mark.parametrize("version", [1, 2, 3])
def test_existing_checkpoint_api_keeps_codec_and_domain_unchanged(preview_world, version):
    client, engine, owner, outsider, ids, unavailable = preview_world
    login_cookie(client, owner)
    with Session(engine) as db:
        before = [(row.id, row.state_json, row.rng_json) for row in db.scalars(select(models.BattleCheckpoint))]
    response = client.get(f"/battles/{ids[version - 1]}/state")
    assert response.status_code == 200
    assert response.json() == public_payload(version, ids[version - 1])
    assert "rng" not in response.json()
    assert client.get(f"/battles/{unavailable}/state").status_code == 409
    login_cookie(client, outsider)
    foreign = client.get(f"/battles/{ids[version - 1]}/state")
    missing = client.get("/battles/999999/state")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content
    client.cookies.clear()
    assert client.get(f"/battles/{ids[version - 1]}/state").status_code == 401
    with Session(engine) as db:
        assert [(row.id, row.state_json, row.rng_json) for row in db.scalars(select(models.BattleCheckpoint))] == before
        assert db.scalars(select(models.BattleEvent)).all() == []


# === SECTION: Executed Node renderer/controller/DOM smoke with real wire fixtures ===
def test_canvas_renderer_and_request_controller():
    result = subprocess.run(
        [resolve_node_binary(), str(ROOT / "tests/js/battle_canvas.test.js")],
        input=json.dumps(
            [public_payload(v) for v in (1, 2, 3)]
            + [public_payload(v, active=True) for v in (2, 3)]
        ),
        capture_output=True, text=True, encoding="utf-8", check=True, cwd=ROOT,
    )
    assert json.loads(result.stdout)["passed"] is True
