from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.services import battle_creation
from app.services.agents.roster_adapter import AdaptResult
from app.services.engine.persistence import load_latest_checkpoint


_DEFAULT_PROTOCOL_VERSION = object()


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _fake_adapter(_roster, *, owner_player: int) -> AdaptResult:
    return AdaptResult(
        units={
            "owner_player": owner_player,
            "units": [
                {
                    "id": owner_player + 1,
                    "position": (owner_player * 12.0, 0.0),
                    "models": 1,
                    "toughness": 3,
                    "quality": 4,
                    "defense": 5,
                    "passives": [],
                }
            ],
        }
    )


def _stage(
    session: Session,
    *,
    activation_protocol_version: object = _DEFAULT_PROTOCOL_VERSION,
):
    kwargs = {}
    if activation_protocol_version is not _DEFAULT_PROTOCOL_VERSION:
        kwargs["activation_protocol_version"] = activation_protocol_version
    return battle_creation.stage_battle_creation(
        session,
        p1_user_id=1,
        p2_user_id=2,
        p1_roster=SimpleNamespace(id=11),
        p2_roster=SimpleNamespace(id=12),
        rng_seed=77,
        initiative_player=1,
        **kwargs,
    )


def test_stage_battle_creation_defaults_to_coherent_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(battle_creation, "roster_to_engine_roster", _fake_adapter)
    session = _session()

    staged = _stage(session)

    checkpoint = load_latest_checkpoint(session, staged.battle.id)
    row = session.query(models.BattleCheckpoint).one()
    assert staged.battle.activation_protocol_version == 1
    assert json.loads(row.state_json)["version"] == 1
    assert checkpoint is not None
    assert checkpoint.state.initiative_player is None
    assert checkpoint.state.activation is None


def test_stage_battle_creation_explicit_v2_is_coherent_and_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(battle_creation, "roster_to_engine_roster", _fake_adapter)
    session = _session()

    staged = _stage(session, activation_protocol_version=2)

    checkpoint = load_latest_checkpoint(session, staged.battle.id)
    row = session.query(models.BattleCheckpoint).one()
    assert staged.battle.activation_protocol_version == 2
    assert json.loads(row.state_json)["version"] == 2
    assert checkpoint is not None
    assert checkpoint.state.initiative_player == 1
    assert checkpoint.state.activation is None


@pytest.mark.parametrize("version", [None, True, 0, 4, 1.0, "2"])
def test_stage_battle_creation_rejects_invalid_version_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    version,
) -> None:
    def unexpected_adapter(*_args, **_kwargs):
        raise AssertionError("invalid version must fail before roster adaptation")

    monkeypatch.setattr(
        battle_creation,
        "roster_to_engine_roster",
        unexpected_adapter,
    )
    session = _session()

    with pytest.raises(ValueError, match="activation_protocol_version"):
        _stage(session, activation_protocol_version=version)

    assert session.query(models.Battle).count() == 0
    assert session.query(models.BattleCheckpoint).count() == 0
