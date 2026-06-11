"""faza-b-regroup-choice — pkt 20.f.i: kontrolujący wybiera Wyczerpany/Przyszpilony
przy JEDNEJ porażce Przegrupowania. Routing callbacku + replay (result_status)."""

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
    # Oddział 5×T3 (powyżej połowy → 1 test bazowy), z ranami z tej aktywacji.
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
        if _morale_status(ev) == "exhausted":  # default = 1 porażka → Wyczerpany
            return seed
    pytest.skip("nie znaleziono seeda z dokładnie 1 porażką")


def test_default_one_fail_is_exhausted():
    # Bez callbacku (np. `apply`/testy) → wsteczna kompat: Wyczerpany.
    seed = _find_one_fail_seed()
    new_state, ev, _ = _regroup_test(_state(), 1, _ctx(), DeterministicDice(seed), 1)
    assert _morale_status(ev) == "exhausted"
    blob = new_state.blobs[0]
    assert STATUS_WYCZERPANY in blob.status_flags
    assert STATUS_PRZYSZPILONY not in blob.status_flags


def test_choice_pinned_applies_przyszpilony():
    # Pkt 20.f.i: wybór "pinned" → Przyszpilony (nie Wyczerpany).
    seed = _find_one_fail_seed()
    new_state, ev, _ = _regroup_test(
        _state(), 1, _ctx(), DeterministicDice(seed), 1, lambda st, b: "pinned"
    )
    assert _morale_status(ev) == "pinned"
    blob = new_state.blobs[0]
    assert STATUS_PRZYSZPILONY in blob.status_flags
    assert STATUS_WYCZERPANY not in blob.status_flags


def test_pinned_choice_replays_bit_perfect():
    # Replay: event niesie result_status="pinned" → reducer odtwarza Przyszpilony.
    seed = _find_one_fail_seed()
    initial = _state()
    new_state, ev, _ = _regroup_test(
        initial, 1, _ctx(), DeterministicDice(seed), 1, lambda st, b: "pinned"
    )
    replayed = apply_events(initial, ev)
    live, rep = new_state.blobs[0], replayed.blobs[0]
    assert live.status_flags == rep.status_flags
    assert STATUS_PRZYSZPILONY in rep.status_flags


def test_callback_receives_controlling_unit():
    # Callback dostaje (state, blob) kontrolowanego oddziału.
    seed = _find_one_fail_seed()
    seen = []
    _regroup_test(_state(), 1, _ctx(), DeterministicDice(seed), 1,
                  lambda st, b: seen.append(b.id) or "pinned")
    assert seen == [1]
