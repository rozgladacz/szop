"""D1 — testy `RandomPlayer` (determinizm per seed, None gdy brak akcji)."""

from __future__ import annotations

from app.services.agents.base import legal_actions
from app.services.agents.random_player import RandomPlayer
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)


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


def _state(blobs: tuple[UnitBlob, ...]) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
    )


def test_returns_none_when_no_legal_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert RandomPlayer(seed=1).choose_action(_state(blobs), perspective=0) is None


def test_chosen_action_is_legal():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    action = RandomPlayer(seed=7).choose_action(state, perspective=0)
    assert action in legal_actions(state, perspective=0)


def test_same_seed_is_deterministic():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    a1 = RandomPlayer(seed=42).choose_action(state, perspective=0)
    a2 = RandomPlayer(seed=42).choose_action(state, perspective=0)
    assert a1 == a2


def test_different_seeds_can_diverge():
    # Wiele kandydatów → przynajmniej jedna para seedów daje różny wybór.
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    choices = {
        repr(RandomPlayer(seed=s).choose_action(state, perspective=0))
        for s in range(20)
    }
    assert len(choices) > 1
