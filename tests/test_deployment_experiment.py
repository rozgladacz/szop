"""Research invariants for the sequential D5.3b harness."""
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.engine.observation import AutomaticTransition
from app.services.engine.phases import deployment_round
from app.services.engine.state import Position

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("deployment_experiment", ROOT / "scripts/deployment_experiment.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)
MANIFEST = ROOT / "docs/experiments/d5_3b/manifest.json"


def manifest():
    return experiment.load_manifest(MANIFEST)


def case(**changes):
    result = next(experiment.iter_cases(manifest()))
    result.update(changes)
    return result


def test_frozen_design_is_paired_and_has_repeats():
    m = manifest()
    cases = list(experiment.iter_cases(m))
    assert len(cases) == 480
    assert len({c["id"] for c in cases}) == 480
    assert m["repeats"] == 2
    cells = {}
    for c in cases:
        key = (c["fixture"]["id"], c["policy"], c["seed"], c["swap"], c["initiative"])
        cells.setdefault(key, set()).add(tuple(c["strategies"]))
    assert all(v == {("grid", "grid"), ("grid", "objectives"),
                     ("objectives", "grid"), ("objectives", "objectives")} for v in cells.values())


@pytest.mark.parametrize("key,value", [("repeats", 1), ("max_activations", 0),
                                       ("swaps", [0]), ("battle_seeds", [True]),
                                       ("initiatives", [2]), ("policies", ["unknown"]),
                                       ("strategy_pairs", [["bad", "grid"]]),
                                       ("battle_seeds", [11, 11])])
def test_invalid_or_duplicate_design_rejected(tmp_path, key, value):
    m = manifest(); m[key] = value
    path = tmp_path / "m.json"; path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises((ValueError, KeyError)):
        experiment.load_manifest(path)


def test_swap_moves_armies_not_only_a_label():
    normal, _, _ = experiment.prepare(case(), manifest())
    swapped, _, _ = experiment.prepare(case(swap=True), manifest())
    assert {b.id: b.owner_player for b in swapped.blobs} == {
        b.id: 1 - b.owner_player for b in normal.blobs}


def test_seeds_follow_original_army_after_swap(monkeypatch):
    seeds = []
    monkeypatch.setattr(experiment, "make_player", lambda kind, seed: seeds.append(seed))
    experiment.prepare(case(seed=42, swap=False), manifest())
    experiment.prepare(case(seed=42, swap=True), manifest())
    assert seeds == [42, 42 + experiment.PLAYER_SEED_OFFSET,
                     42 + experiment.PLAYER_SEED_OFFSET, 42]


@pytest.mark.parametrize("strategies", [("grid", "grid"), ("objectives", "grid")])
def test_real_runner_parity_replay_and_instrumentation_cleanup(strategies):
    m = manifest(); c = case(strategies=list(strategies))
    original = experiment.match.objective_deployment_choice
    legal = experiment.dep.is_deployment_position_legal
    actual = experiment.run_case(c, m)
    assert actual["reproducible"]
    assert actual["result"]["status"] == "complete"
    assert actual["result"]["replay_equal"]
    assert experiment.match.objective_deployment_choice is original
    assert experiment.dep.is_deployment_position_legal is legal
    state, players, zones = experiment.prepare(c, m)
    fx = experiment.fixture_for(c)
    direct = experiment.match.simulate_from_rosters(
        fx.rosters, players, seed=c["seed"], terrain=fx.terrain, objectives=fx.objectives,
        initiative_player=c["initiative"], deployment_zones=zones, deployment_strategies=strategies)
    assert actual["result"]["event_digest"] == experiment.digest(
        [experiment.event_to_json(e) for e in direct.events])
    assert actual["result"]["final_digest"] == experiment.digest(
        experiment.battle_state_to_json(direct.final_state))
    counts = actual["result"]["candidates"]
    assert all(n > 0 for n in counts)
    if strategies[0] == "objectives":
        placed = [p for p in actual["result"]["placements"] if p["owner"] == 0]
        assert len({p["assigned_target"] for p in placed}) == len(placed)


def test_cap_is_not_counted_as_a_draw_and_cleanup_survives_failure():
    m = manifest(); m["max_activations"] = 1
    original = experiment.dep.is_deployment_position_legal
    row = experiment.run_case(case(), m)
    assert row["result"]["status"] == "activation_cap"
    assert row["reproducible"]
    assert experiment.dep.is_deployment_position_legal is original
    result = experiment.summarize([row])
    assert result["statuses"] == {"activation_cap": 1}
    assert result["complete_mixed"] == 0
    assert not result["mixed_outcomes"]


def test_deployment_failure_is_retained_without_partial_positions():
    m = manifest(); m["deployment_zones"] = [[0, 0, 0.1, 0.1], [0, 0, 0.1, 0.1]]
    original = experiment.match.objective_deployment_choice
    row = experiment.run_case(case(strategies=["objectives", "grid"]), m)
    assert row["result"]["status"] == "deployment_error"
    assert "placements" not in row["result"]
    assert row["reproducible"]
    assert experiment.match.objective_deployment_choice is original
    assert experiment.summarize([row])["mixed_outcomes"] == {}


def test_observer_records_strategy_choices_and_real_deployment_events():
    m = experiment.load_manifest(ROOT / "docs/experiments/d7_1/manifest.json")
    c = next(c for c in experiment.iter_cases(m) if c["strategies"] == ["objectives", "grid"])
    trace = []
    observed = experiment.run_once(c, m, on_observation=trace.append)
    assert observed["status"] == "complete" and observed["replay_equal"]
    assert experiment.deterministic(observed) == experiment.deterministic(experiment.run_once(c, m))

    choices = [r for r in trace if isinstance(r, experiment.match.DeploymentDecision)]
    moves = [r for r in trace if isinstance(r, AutomaticTransition) and r.kind == "deployment_moved"]
    finished, = [r for r in trace if isinstance(r, AutomaticTransition) and r.kind == "deployment_finished"]
    assert len(choices) == len(moves) == len(observed["placements"])
    assert {r.strategy for r in choices} == {"objectives", "grid"}
    for decision, move, placement in zip(choices, moves, observed["placements"], strict=True):
        event, = move.events
        assert move.before == decision.seen_state
        assert decision.outcome == "accepted"
        assert event.sequence == decision.placement_index
        assert event.unit_id == move.unit_id == decision.unit_id == placement["unit"]
        assert list(event.to_pos) == [decision.position.x, decision.position.y] == placement["position"]
        assert decision.target_id == placement["assigned_target"]
        assert len(decision.occupied) + 1 == decision.placement_index
        assert decision.zone == experiment.dep.DeploymentZone(*m["deployment_zones"][decision.perspective])
        assert experiment.apply_events(move.before, move.events) == move.after
    assert all(not r.assignments for r in choices if r.strategy == "grid")
    assert any(r.assignments for r in choices if r.strategy == "objectives")
    before_deploy, _, _ = experiment.prepare(c, m)
    actions = [experiment.match.DeploymentAction(r.unit_id, r.position) for r in choices]
    initial, deploy_events = deployment_round(before_deploy, actions)
    assert finished.before == moves[-1].after
    assert finished.after == initial
    assert (*[event for move in moves for event in move.events], *finished.events) == deploy_events


@pytest.mark.parametrize("reject", [False, True])
def test_observer_records_actual_deployment_callback_and_validation(monkeypatch, reject):
    m = manifest()
    c = case(strategies=["grid", "grid"])
    _, players, zones = experiment.prepare(c, m)
    fx = experiment.fixture_for(c)
    trace, calls = [], []
    original = players[0].choose_deployment

    def choose(state, unit_id, zone):
        position = Position(-999, -999) if reject and calls else original(state, unit_id, zone)
        calls.append((state, unit_id, zone, experiment.dep._deployment_occupied(state), position))
        return position

    def simulate():
        return experiment.match.simulate_from_rosters(
            fx.rosters, players, seed=c["seed"], terrain=fx.terrain, objectives=fx.objectives,
            deployment_zones=zones, deployment_strategies=(None, "grid"),
            on_observation=trace.append,
        )

    monkeypatch.setattr(players[0], "choose_deployment", choose)
    if reject:
        with pytest.raises(experiment.IllegalActionError) as error:
            simulate()
        accepted, decision = trace
        assert accepted.outcome == "accepted" and accepted.placement_index == 1
        assert decision.outcome == "rejected" and decision.placement_index is None
        assert decision.reason == error.value.code == "invalid_deployment_position"
    else:
        assert simulate().final_state.is_game_over
    callbacks = [r for r in trace if isinstance(r, experiment.match.DeploymentDecision) and r.strategy is None]
    assert callbacks
    assert [(r.seen_state, r.unit_id, r.zone, r.occupied, r.position) for r in callbacks] == calls


def test_adapter_observer_records_selection_exhaustion_without_fake_move():
    m = manifest()
    m["deployment_zones"] = [[0, 0, 0.1, 0.1], [0, 0, 0.1, 0.1]]
    trace = []
    row = experiment.run_once(case(strategies=["objectives", "grid"]), m, on_observation=trace.append)
    assert row["status"] == "deployment_error"
    decision, = trace
    assert (decision.outcome, decision.reason, decision.position) == ("error", "no_deployment_candidate", None)


def test_repeat_does_not_compare_wall_clock_but_detects_outcome_drift(monkeypatch):
    values = iter([{"status": "complete", "winner": 0, "total_ms": 1},
                   {"status": "complete", "winner": 0, "total_ms": 100}])
    monkeypatch.setattr(experiment, "run_once", lambda *args: next(values))
    assert experiment.run_case(case(), manifest())["reproducible"]
    values = iter([{"status": "complete", "winner": 0}, {"status": "complete", "winner": 1}])
    assert not experiment.run_case(case(), manifest())["reproducible"]


def test_report_mixed_outcome_tracks_strategy_on_winning_side():
    def row(pair, winner, status="complete"):
        return dict(case=case(strategies=pair), result=dict(status=status, winner=winner),
                    reproducible=True, timings=[dict(deployment_ms=1, total_ms=2)])
    rows = [row(["grid", "objectives"], 1), row(["objectives", "grid"], 1),
            row(["grid", "objectives"], None), row(["grid", "grid"], 0),
            row(["objectives", "grid"], None, "deployment_error")]
    summary = experiment.summarize(rows)
    assert summary["complete_mixed"] == 3
    assert summary["mixed_cases"] == 4
    assert summary["mixed_outcomes"] == {"objectives": 1, "grid": 1, "draw": 1}
    assert "3 / 4" in experiment.render_report(rows)
