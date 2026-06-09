"""D1 — testy `GreedyPlayer` (depth-1 argmax: atak > obrona, marsz na cel)."""

from __future__ import annotations

from app.services.agents.greedy_player import GreedyPlayer
from app.services.engine.actions import ManeuverAction, ShootAction
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)


def _blob(uid: int, owner: int, x: float, y: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": owner,
        "position": Position(x, y),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


def _state(blobs: tuple[UnitBlob, ...], objectives: tuple = ()) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


def test_returns_none_when_no_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert GreedyPlayer().choose_action(_state(blobs), perspective=0) is None


def test_prefers_attack_over_passive_actions():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    action = GreedyPlayer().choose_action(_state(blobs), perspective=0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_prefers_maneuver_toward_objective_when_no_attack():
    # Bez broni → brak ataków; bliski niezajęty cel czyni marsz najlepszą akcją.
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(6, 0), controller=None)
    action = GreedyPlayer().choose_action(_state((own,), (obj,)), perspective=0)
    assert isinstance(action, ManeuverAction)
    # Ruch zbliża do celu (nie "stój").
    assert action.target_position != own.position


def test_deterministic_choice():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    a1 = GreedyPlayer().choose_action(state, perspective=0)
    a2 = GreedyPlayer().choose_action(state, perspective=0)
    assert a1 == a2
