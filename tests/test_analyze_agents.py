"""Telemetria decyzji bota (ADR-0017, slice `data/agent_metrics`) — testy.

Pokrywa skrypt-liść `scripts/analyze_agents.py` + additive hook `on_decision`
w `match.run_match`. Czas (`decision_time_ms`) jest wall-clock → NIE asercjonowany
(zależy od maszyny); jakość (`quality`) jest czystą funkcją stanów → deterministyczna.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from app.services.agents.policy_eval import OBJECTIVE_WEIGHT, evaluate_state
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
)

_repo_root = pathlib.Path(__file__).resolve().parent.parent


def _load_module(name: str):
    """Ładuje skrypt z scripts/ jako moduł (scripts/ nie jest pakietem)."""
    if name in __import__("sys").modules:
        return __import__("sys").modules[name]
    script = _repo_root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    mod = importlib.util.module_from_spec(spec)
    __import__("sys").modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


aa = _load_module("analyze_agents")


# --- helpers do budowy stanu (wzorzec z test_agents_policy) ---


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


def _state(blobs, objectives=()) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


def _rec(kind: str, quality: float, *, action="Ostrzał", time_ms=1.0):
    return aa.DecisionRecord(
        kind=kind,
        perspective=0,
        unit_id=1,
        action_type=action,
        decision_time_ms=time_ms,
        quality=quality,
    )


# --- quality_from_states (czysta, deterministyczna) ---


def test_quality_positive_when_enemy_weaker():
    before = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0, models_alive=5)))
    after = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0, models_alive=2)))
    q = aa.quality_from_states(before, after, perspective=0)
    assert q > 0  # przeciwnik stracił modele → moja pozycja lepsza


def test_quality_zero_for_no_change():
    s = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0)))
    assert aa.quality_from_states(s, s, perspective=0) == 0.0


def test_quality_matches_evaluate_state_delta():
    before = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0)))
    after = _state(
        (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0)),
        objectives=(Objective(id=1, position=Position(50, 50), controller=0),),
    )
    q = aa.quality_from_states(before, after, perspective=0)
    assert q == evaluate_state(after, 0) - evaluate_state(before, 0)
    assert q == OBJECTIVE_WEIGHT


def test_quality_perspective_sign_flips():
    before = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0, models_alive=5)))
    after = _state((_blob(1, 0, 0, 0), _blob(2, 1, 10, 0, models_alive=2)))
    q0 = aa.quality_from_states(before, after, perspective=0)
    q1 = aa.quality_from_states(before, after, perspective=1)
    assert q0 == -q1  # symetryczna fixtura → przeciwne perspektywy


# --- aggregate_records / AgentMetrics ---


def test_aggregate_groups_per_kind():
    recs = [_rec("a", 2.0), _rec("b", -1.0), _rec("a", 4.0)]
    metrics = aa.aggregate_records(recs)
    assert set(metrics) == {"a", "b"}
    assert metrics["a"].decisions == 2
    assert metrics["a"].sum_quality == 6.0
    assert metrics["a"].mean_quality == 3.0
    assert metrics["b"].decisions == 1


def test_positive_rate_counts_strictly_positive():
    recs = [_rec("a", 1.0), _rec("a", 0.0), _rec("a", -1.0)]
    m = aa.aggregate_records(recs)["a"]
    assert m.positive_decisions == 1  # tylko > 0
    assert m.positive_rate == 1 / 3


def test_action_mix_counted():
    recs = [_rec("a", 1.0, action="Manewr"), _rec("a", 1.0, action="Ostrzał"),
            _rec("a", 1.0, action="Manewr")]
    m = aa.aggregate_records(recs)["a"]
    assert m.action_counts == {"Manewr": 2, "Ostrzał": 1}


def test_aggregate_sets_games_by_kind():
    recs = [_rec("a", 1.0), _rec("b", 1.0)]
    metrics = aa.aggregate_records(recs, games_by_kind={"a": 3, "b": 3})
    assert metrics["a"].games == 3
    assert metrics["b"].games == 3


# --- serializacja JSON (schema v1) ---


def test_metrics_to_dict_schema():
    m = aa.aggregate_records([_rec("a", 2.0), _rec("a", -1.0)], games_by_kind={"a": 2})["a"]
    d = aa.metrics_to_dict(m)
    assert d["schema"] == "szop.agent_metrics/v1"
    assert d["agent"] == "a"
    assert d["games"] == 2
    assert d["decisions"] == 2
    assert d["decision_quality_score"]["total"] == 1.0
    assert d["decision_quality_score"]["mean"] == 0.5
    assert set(d["decision_time_ms"]) == {"mean", "median", "max"}


def test_write_json_roundtrip(tmp_path):
    metrics = aa.aggregate_records(
        [_rec("a", 2.0), _rec("b", 1.0)], games_by_kind={"a": 1, "b": 1}
    )
    out = tmp_path / "agent_metrics" / "run.jsonl"
    aa.write_json(metrics, out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # jedna linia = jeden agent
    parsed = [json.loads(ln) for ln in lines]
    agents = {p["agent"] for p in parsed}
    assert agents == {"a", "b"}
    assert all(p["schema"] == "szop.agent_metrics/v1" for p in parsed)


# --- driver end-to-end (re-symulacja) ---


def test_collect_decisions_quality_deterministic():
    fixture = aa.bsim.load_battle_fixture(aa.bsim.DEFAULT_FIXTURE)
    r1, g1 = aa.collect_decisions(fixture, n=3, player_kinds=("priority", "random"), base_seed=11)
    r2, g2 = aa.collect_decisions(fixture, n=3, player_kinds=("priority", "random"), base_seed=11)
    assert g1 == g2
    # czas pomijamy (wall-clock); reszta deterministyczna
    key = lambda recs: [(x.kind, x.unit_id, x.action_type, round(x.quality, 6)) for x in recs]
    assert key(r1) == key(r2)


def test_collect_decisions_records_both_kinds():
    fixture = aa.bsim.load_battle_fixture(aa.bsim.DEFAULT_FIXTURE)
    records, games = aa.collect_decisions(
        fixture, n=2, player_kinds=("priority", "random"), base_seed=0
    )
    assert records  # niepuste
    assert {r.kind for r in records} == {"priority", "random"}
    assert games == {"priority": 2, "random": 2}


def test_collect_decisions_self_play_single_kind():
    fixture = aa.bsim.load_battle_fixture(aa.bsim.DEFAULT_FIXTURE)
    records, games = aa.collect_decisions(
        fixture, n=2, player_kinds=("priority", "priority"), base_seed=0
    )
    assert games == {"priority": 2}  # dedup self-play, gra liczona raz
    assert {r.kind for r in records} == {"priority"}


def test_collect_decisions_rejects_nonpositive_n():
    fixture = aa.bsim.load_battle_fixture(aa.bsim.DEFAULT_FIXTURE)
    try:
        aa.collect_decisions(fixture, n=0, player_kinds=("priority", "random"))
    except ValueError:
        pass
    else:
        raise AssertionError("n=0 powinno rzucić ValueError")


# --- hook backward-compat (on_decision nie zmienia gry) ---


def test_on_decision_does_not_change_match_result():
    from app.services.agents.match import simulate_from_rosters

    fixture = aa.bsim.load_battle_fixture(aa.bsim.DEFAULT_FIXTURE)
    players_a = [aa.bsim.make_player("priority", 0), aa.bsim.make_player("random", 1)]
    players_b = [aa.bsim.make_player("priority", 0), aa.bsim.make_player("random", 1)]
    base = dict(
        terrain=fixture.terrain, objectives=fixture.objectives, seed=5, initiative_player=0
    )
    without = simulate_from_rosters(fixture.rosters, players_a, **base)
    calls = []
    with_hook = simulate_from_rosters(
        fixture.rosters,
        players_b,
        on_decision=lambda *a: calls.append(a),
        **base,
    )
    assert without.winner == with_hook.winner
    assert without.rounds_played == with_hook.rounds_played
    assert len(without.events) == len(with_hook.events)
    assert calls  # hook faktycznie wołany


def test_render_report_contains_agents():
    metrics = aa.aggregate_records(
        [_rec("priority", 2.0), _rec("random", -1.0)],
        games_by_kind={"priority": 1, "random": 1},
    )
    report = aa.render_report(
        metrics, fixture_name="X", player_kinds=("priority", "random"), n_games=1
    )
    assert "priority" in report
    assert "random" in report
    assert "decision_quality_score" in report


def test_cli_rejects_bad_player_without_traceback(capsys):
    with pytest.raises(SystemExit) as exc:
        aa.main(["--players", "priority,nieistniejacy_bot", "-n", "1"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Nieznany gracz" in err
    assert "Traceback" not in err


def test_cli_rejects_unknown_map_without_traceback(capsys):
    with pytest.raises(SystemExit) as exc:
        aa.main(["--map", "nieistniejaca", "--players", "priority,random", "-n", "1"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Nieznana mapa" in err
    assert "Traceback" not in err


def test_cli_rejects_missing_fixture_without_traceback(capsys):
    with pytest.raises(SystemExit) as exc:
        aa.main(["--fixture", "tests/fixtures/battles/nie_ma.yaml", "-n", "1"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "nie_ma.yaml" in err
    assert "Traceback" not in err
