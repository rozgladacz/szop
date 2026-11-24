"""D1/D2 — testy headless match runnera (`app/services/agents/match.py`).

Pokrywa: pełna gra kończy się po MAX_ROUND (pkt 5.f), determinizm per seed,
spójność winner↔score, przekazanie inicjatywy gdy aktywny gracz nie ma akcji.
"""

from __future__ import annotations

import pytest

from app.services.agents.match import (
    MatchResult,
    _apply_activation_with_telemetry,
    run_match,
    simulate_from_rosters,
)
from app.services.agents.random_player import RandomPlayer
from app.services.agents.greedy_player import GreedyPlayer
from app.services.engine.actions import DefendAction, ManeuverAction, ShootAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import EffectApplied, InitiativePassed, StatusRemoved
from app.services.engine.observation import ActionDecision, AutomaticTransition
from app.services.engine.phases import MAX_ROUND, deployment_round, setup_phase
from app.services.engine.resolver import IllegalActionError
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
    apply_events,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 2}
SWORD = {"slug": "sword", "name": "Sword", "range_inches": 0, "attacks": 2}


def _unit(uid: int, x: float, y: float, weapons: list | None = None) -> dict:
    return {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
        "weapons": weapons or [],
    }


def _rosters() -> list[dict]:
    return [
        {"owner_player": 0, "units": [_unit(1, 6, 0, [RIFLE]), _unit(2, 6, 6, [SWORD])]},
        {"owner_player": 1, "units": [_unit(3, 30, 0, [RIFLE]), _unit(4, 30, 6, [SWORD])]},
    ]


def _objectives() -> list[Objective]:
    return [Objective(id=1, position=Position(18, 3))]


def test_match_completes_and_reaches_max_round():
    result = simulate_from_rosters(
        _rosters(),
        [RandomPlayer(seed=1), RandomPlayer(seed=2)],
        seed=2026,
        objectives=_objectives(),
    )
    assert isinstance(result, MatchResult)
    assert result.final_state.is_game_over
    assert result.rounds_played == MAX_ROUND
    assert result.winner in (0, 1, None)
    assert len(result.events) > 0


def test_deterministic_same_seed():
    args = dict(seed=99, objectives=_objectives())
    r1 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(0)], **args)
    r2 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(0)], **args)
    assert r1.final_state == r2.final_state
    assert r1.winner == r2.winner
    assert len(r1.events) == len(r2.events)


def test_winner_consistent_with_score():
    result = simulate_from_rosters(
        _rosters(),
        [GreedyPlayer(), RandomPlayer(seed=5)],
        seed=7,
        objectives=_objectives(),
    )
    p0, p1 = result.final_state.score
    if p0 > p1:
        assert result.winner == 0
    elif p1 > p0:
        assert result.winner == 1
    else:
        assert result.winner is None


def test_greedy_vs_random_completes():
    result = simulate_from_rosters(
        _rosters(),
        [GreedyPlayer(), RandomPlayer(seed=3)],
        seed=11,
        objectives=_objectives(),
    )
    assert result.final_state.is_game_over


def _blob(uid: int, owner: int, x: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": owner,
        "position": Position(x, 0.0),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


# --- telemetria per-akcja (ADR-0017, opcja A) ---

_RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)


def _telemetry_state() -> BattleState:
    blobs = (
        _blob(1, 0, 4, ranged_weapons=(_RIFLE,)),
        _blob(2, 1, 10),
    )
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=(),
    )


def test_telemetry_fires_on_decision_per_action():
    # Manewr→Ostrzał w jednej aktywacji → on_decision woła się 2× (opcja A).
    def cont(state, uid, taken):
        if len(taken) == 1:
            return ShootAction(uid, 2, _RIFLE)
        return None

    calls: list[tuple] = []

    def on_dec(perspective, unit_id, action, state_before, state_after, elapsed_ms):
        calls.append((perspective, unit_id, type(action).__name__, elapsed_ms))

    _apply_activation_with_telemetry(
        _telemetry_state(),
        ManeuverAction(1, Position(4, 0)),
        DeterministicDice(7),
        1,
        cont,
        perspective=0,
        first_action_elapsed_ms=1.5,
        on_decision=on_dec,
    )
    assert [c[2] for c in calls] == ["ManeuverAction", "ShootAction"]
    assert all(c[0] == 0 and c[1] == 1 for c in calls)  # perspektywa + unit_id
    assert calls[0][3] == 1.5  # 1. akcja: przekazany elapsed
    assert calls[1][3] >= 0.0  # 2. akcja: zmierzony czas continuation


def test_telemetry_single_action_fires_once():
    # Brak kontynuacji → dokładnie 1 wywołanie (parytet z trybem 1-akcja).
    calls: list[tuple] = []

    def on_dec(*args):
        calls.append(args)

    _apply_activation_with_telemetry(
        _telemetry_state(),
        ManeuverAction(1, Position(5, 0)),
        DeterministicDice(1),
        1,
        lambda s, uid, taken: None,
        perspective=0,
        first_action_elapsed_ms=2.0,
        on_decision=on_dec,
    )
    assert len(calls) == 1
    assert calls[0][5] == 2.0  # elapsed_ms pierwszej akcji


def test_initiative_passes_when_active_player_has_no_actions():
    # P0 (aktywny) ma jedyny oddział już Aktywowany; P1 ma świeży oddział.
    # Runner musi przekazać inicjatywę do P1 i dokończyć grę.
    blobs = (
        _blob(1, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),
        _blob(2, 1, 30),
    )
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=(),
    )
    trace = []
    result = run_match(state, [RandomPlayer(1), RandomPlayer(2)], DeterministicDice(seed=1),
                       on_observation=trace.append)
    assert result.final_state.is_game_over
    # Inicjatywa została przekazana co najmniej raz (P0 nie miał akcji w rundzie 1).
    assert any(isinstance(e, InitiativePassed) for e in result.events)
    assert trace[0] == ActionDecision("choose_action", state, None, (), None, "none")
    assert trace[1].kind == "initiative_passed"
    assert trace[1].reason == "choose_action_none"
    assert trace[1].events == result.events[:1]
    assert trace[1].before.active_player == 0 and trace[1].after.active_player == 1


def test_observation_preserves_match_rng_policy_calls_and_existing_telemetry():
    initial, _ = deployment_round(setup_phase(_rosters(), objectives=_objectives()), ())

    def play(*, observe, telemetry):
        calls, legacy, trace = [], [], []

        class RecordingPlayer(RandomPlayer):
            def choose_action(self, state, perspective):
                action = super().choose_action(state, perspective)
                calls.append(("choose_action", state, perspective, (), action))
                return action

            def continue_activation(self, state, perspective, unit_id, prior):
                action = super().continue_activation(state, perspective, unit_id, prior)
                calls.append(("continue_activation", state, perspective, prior, action))
                return action

        def collect_legacy(*args):
            legacy.append(args[:-1])

        dice = DeterministicDice(99)
        result = run_match(
            initial, [RecordingPlayer(0), RecordingPlayer(0)], dice,
            on_decision=collect_legacy if telemetry else None,
            on_observation=trace.append if observe else None,
        )
        return result, dice.roll_d6(32), calls, legacy, trace

    unobserved = play(observe=False, telemetry=False)
    legacy_only = play(observe=False, telemetry=True)
    observed = play(observe=True, telemetry=True)
    assert unobserved[:3] == legacy_only[:3] == observed[:3]
    assert legacy_only[3] == observed[3]
    result, _, calls, legacy, trace = observed
    decisions = [record for record in trace if isinstance(record, ActionDecision)]
    assert [(d.kind, d.seen_state, d.perspective, d.prior_actions, d.action) for d in decisions] == calls
    assert [(d.perspective, d.unit_id, d.action, d.before, d.after)
            for d in decisions if d.outcome == "applied"] == legacy
    assert tuple(event for record in trace for event in record.events) == result.events
    assert apply_events(initial, result.events) == result.final_state
    assert trace[0].kind == "activation_started"
    assert isinstance(trace[0].events[0], StatusRemoved)
    assert decisions[0].seen_state is initial
    assert decisions[0].before is trace[0].after and decisions[0].before != initial
    assert trace[-1].kind == "round_ended" and trace[-1].after == result.final_state
    for decision in decisions:
        if decision.outcome == "applied":
            assert apply_events(decision.before, decision.events) == decision.after


def test_observation_preserves_first_rejection_and_reason():
    class InvalidFirstAction(RandomPlayer):
        def choose_action(self, state, perspective):
            return ManeuverAction(1, Position(1000, 0))

    state = _telemetry_state()
    dice = DeterministicDice(7)
    checkpoint = dice.to_checkpoint()
    trace = []
    with pytest.raises(IllegalActionError) as error:
        run_match(state, [InvalidFirstAction(0), RandomPlayer(0)], dice, on_observation=trace.append)
    assert error.value.code == "maneuver_over_budget"
    assert trace == [ActionDecision(
        "choose_action", state, 1, (), ManeuverAction(1, Position(1000, 0)),
        "rejected", reason=error.value.code,
    )]
    assert dice.to_checkpoint() == checkpoint


@pytest.mark.parametrize(("next_action", "outcome", "reason"), [
    (None, "none", None),
    (ManeuverAction(1, Position(1000, 0)), "rejected", "maneuver_over_budget"),
    (DefendAction(2), "rejected", "different_activation_unit"),
    (ManeuverAction(1, Position(5, 0)), "applied", None),
])
def test_observation_records_followup_and_automatic_finish(next_action, outcome, reason):
    calls, trace, executed = [], [], []

    class ScriptedPlayer(RandomPlayer):
        def choose_action(self, state, perspective):
            return DefendAction(1)

        def continue_activation(self, state, perspective, unit_id, prior):
            calls.append((state, perspective, unit_id, prior))
            return next_action

    def on_decision(_player, _unit, action, *_):
        executed.append(action)

    with pytest.raises(RuntimeError, match="exceeded max_activations"):
        run_match(
            _telemetry_state(), [ScriptedPlayer(0), RandomPlayer(0)], DeterministicDice(7),
            max_activations=1, on_observation=trace.append, on_decision=on_decision,
        )
    choices = [record for record in trace if isinstance(record, ActionDecision)]
    first, followup = choices
    assert first.outcome == "applied"
    assert calls == [(first.after, 0, 1, (DefendAction(1),))]
    assert followup.kind == "continue_activation"
    assert (followup.seen_state, followup.perspective, followup.unit_id, followup.prior_actions) == calls[0]
    assert (followup.action, followup.outcome, followup.reason) == (next_action, outcome, reason)
    automatic = [record for record in trace if isinstance(record, AutomaticTransition)]
    assert [record.kind for record in automatic][-2:] == ["activation_finished", "initiative_passed"]
    if outcome == "applied":
        assert followup.before == followup.seen_state
        assert followup.events
        assert executed == [DefendAction(1), next_action]
        assert any(record.kind == "activation_stopped" and record.reason == "action_limit"
                   for record in automatic)
    else:
        assert not followup.events and followup.before is None and followup.after is None
        assert executed == [DefendAction(1)]
        assert all(record.kind != "activation_stopped" for record in automatic)


def test_observer_event_payload_is_detached_from_live_log():
    state = _telemetry_state()
    players = [RandomPlayer(0), RandomPlayer(0)]
    baseline = run_match(state, players, DeterministicDice(9))
    changed = []

    def observer(record):
        for event in record.events:
            if isinstance(event, EffectApplied):
                event.payload.clear()
                changed.append(event)

    result = run_match(state, [RandomPlayer(0), RandomPlayer(0)], DeterministicDice(9),
                       on_observation=observer)
    assert changed
    assert result == baseline
