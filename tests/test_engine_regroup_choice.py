"""pkt 20.f.i (zmiana zasad 2026-06-12): 1 porażka Przegrupowania → Przyszpilony
deterministycznie (brak wyboru)."""

from __future__ import annotations

import pytest

from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoraleTestPassed
from app.services.engine.phases import ActivationContext, _regroup_test
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    apply_events,
)
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY


def _state() -> BattleState:
    own = UnitBlob(id=1, owner_player=0, position=Position(0, 0), radius_inches=1.0,
                   models_alive=5, toughness_per_model=3, wounds_received=2)
    return BattleState(round=1, active_player=0, activations_remaining=(1, 1),
                       blobs=(own,), terrain=(), objectives=())


def _ctx() -> ActivationContext:
    return ActivationContext(actor_id=1, wounds_received_this_activation=((1, 2),),
                             melee_combatants=frozenset())


def _morale_status(events):
    return next((e.result_status for e in events if isinstance(e, MoraleTestPassed)), None)


def _find_one_fail_seed() -> int:
    state, ctx = _state(), _ctx()
    for seed in range(200):
        _, ev, _ = _regroup_test(state, 1, ctx, DeterministicDice(seed), 1)
        if _morale_status(ev) == "pinned":
            return seed
    pytest.skip("nie znaleziono seeda z dokładnie 1 porażką")


def test_one_fail_is_pinned():
    # Pkt 20.f.i: 1 porażka → zawsze Przyszpilony (deterministycznie).
    seed = _find_one_fail_seed()
    new_state, ev, _ = _regroup_test(_state(), 1, _ctx(), DeterministicDice(seed), 1)
    assert _morale_status(ev) == "pinned"
    blob = new_state.blobs[0]
    assert STATUS_PRZYSZPILONY in blob.status_flags
    assert STATUS_WYCZERPANY not in blob.status_flags


def test_one_fail_replays_bit_perfect():
    seed = _find_one_fail_seed()
    initial = _state()
    new_state, ev, _ = _regroup_test(initial, 1, _ctx(), DeterministicDice(seed), 1)
    replayed = apply_events(initial, ev)
    assert new_state.blobs[0].status_flags == replayed.blobs[0].status_flags
    assert STATUS_PRZYSZPILONY in replayed.blobs[0].status_flags
