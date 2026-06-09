"""D1 — testy `evaluate_state` (bilans HP + kontrola/bliskość celów)."""

from __future__ import annotations

from app.services.agents.policy_eval import (
    OBJECTIVE_WEIGHT,
    PROXIMITY_WEIGHT,
    evaluate_state,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
)


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


def test_hp_balance_symmetry():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0))
    state = _state(blobs)
    assert evaluate_state(state, 0) == -evaluate_state(state, 1)


def test_more_hp_is_better():
    strong = (_blob(1, 0, 0, 0, models_alive=5), _blob(2, 1, 10, 0, models_alive=2))
    weak = (_blob(1, 0, 0, 0, models_alive=2), _blob(2, 1, 10, 0, models_alive=5))
    assert evaluate_state(_state(strong), 0) > evaluate_state(_state(weak), 0)


def test_controlled_objective_adds_weight():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0))
    no_obj = evaluate_state(_state(blobs), 0)
    with_obj = evaluate_state(
        _state(blobs, objectives=(Objective(id=1, position=Position(50, 50), controller=0),)),
        0,
    )
    assert with_obj == no_obj + OBJECTIVE_WEIGHT


def test_enemy_objective_subtracts_weight():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0))
    no_obj = evaluate_state(_state(blobs), 0)
    enemy_obj = evaluate_state(
        _state(blobs, objectives=(Objective(id=1, position=Position(50, 50), controller=1),)),
        0,
    )
    assert enemy_obj == no_obj - OBJECTIVE_WEIGHT


def test_proximity_bonus_closer_is_better():
    obj = Objective(id=1, position=Position(10, 0), controller=None)
    near = (_blob(1, 0, 8, 0), _blob(2, 1, 30, 0))
    far = (_blob(1, 0, 0, 0), _blob(2, 1, 30, 0))
    s_near = evaluate_state(_state(near, (obj,)), 0)
    s_far = evaluate_state(_state(far, (obj,)), 0)
    assert s_near > s_far
    # Bonus ograniczony z góry przez PROXIMITY_WEIGHT (gap≥0 → /(1+gap) ≤ 1).
    base = evaluate_state(_state(near), 0)
    assert s_near - base <= PROXIMITY_WEIGHT + 1e-9


def test_objective_outweighs_single_wound_swing():
    # Jeden cel powinien przeważać kilka punktów ran (pkt 5.f).
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0))
    obj_state = _state(blobs, (Objective(id=1, position=Position(50, 50), controller=0),))
    # 1 model toughness 3 = 3 HP; OBJECTIVE_WEIGHT > 3.
    assert OBJECTIVE_WEIGHT > 3
