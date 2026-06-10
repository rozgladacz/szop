"""D1 — testy `evaluate_state` (bilans HP + kontrola/bliskość celów)."""

from __future__ import annotations

from app.services.agents.policy_eval import (
    OBJECTIVE_WEIGHT,
    PROXIMITY_WEIGHT,
    evaluate_state,
    objective_balance_with_control,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
)
from app.services.engine.status import STATUS_PRZYSZPILONY


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


# --- objective_balance_with_control (przelicza kontrolę z pozycji, pkt 5.d) ---


def test_control_recompute_flips_uncontrolled_objective():
    # Własny oddział w 3″ niezajętego celu → kontrola gracza 0 (+OBJECTIVE_WEIGHT).
    # evaluate_state (bez przeliczenia) widzi tylko proximity; with_control widzi pełną kontrolę.
    obj = Objective(id=1, position=Position(0, 0), controller=None)
    own = _blob(1, 0, 0, 0)  # na celu (edge_dist = -1 ≤ 3)
    state = _state((own,), (obj,))
    assert objective_balance_with_control(state, 0) == OBJECTIVE_WEIGHT
    # Stała funkcja evaluate_state (controller=None) daje tylko proximity < OBJECTIVE_WEIGHT.
    assert evaluate_state(state, 0) < OBJECTIVE_WEIGHT


def test_control_recompute_contested_stays_uncontrolled():
    # Oba oddziały w 3″ → nikt nie kontroluje (pkt 5.d: tylko jeden gracz w zasięgu).
    obj = Objective(id=1, position=Position(0, 0), controller=None)
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 0, 0)
    state = _state((own, enemy), (obj,))
    # Brak kontroli → tylko proximity (oba w tym samym miejscu), < OBJECTIVE_WEIGHT.
    assert objective_balance_with_control(state, 0) < OBJECTIVE_WEIGHT


def test_control_recompute_pinned_does_not_control():
    # Przyszpilony nie kontroluje celów (pkt 22.b.ii) — kontrola nie flipuje.
    obj = Objective(id=1, position=Position(0, 0), controller=None)
    pinned = _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,))
    state = _state((pinned,), (obj,))
    # Brak kontroli (jedyny oddział Przyszpilony) → proximity tylko.
    assert objective_balance_with_control(state, 0) < OBJECTIVE_WEIGHT


def test_control_recompute_enemy_on_objective_penalizes():
    # Wrogi oddział na celu → −OBJECTIVE_WEIGHT z perspektywy gracza 0.
    obj = Objective(id=1, position=Position(0, 0), controller=None)
    enemy = _blob(2, 1, 0, 0)
    state = _state((enemy,), (obj,))
    assert objective_balance_with_control(state, 0) == -OBJECTIVE_WEIGHT
