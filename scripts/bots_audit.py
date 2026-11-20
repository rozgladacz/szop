"""D6.1: bounded, in-process observations of existing bots, not a rules validator.

The manifest and results are explicit audit artifacts. Resolver acceptance is
reported separately from conformity to the canonical rule text in the report.
No DB, server checkpoint RNG, policy overrides, or external service is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.agents import deployment as dep, match  # noqa: E402
from app.services.agents.factory import make_player, PLAYER_SEED_OFFSET  # noqa: E402
from app.services.agents.registry import ALL_KINDS, spec  # noqa: E402
from app.services.engine.action_codec import action_to_json  # noqa: E402
from app.services.engine.dice import DeterministicDice  # noqa: E402
from app.services.engine.events import event_to_json  # noqa: E402
from app.services.engine.phases import _check_objective_control  # noqa: E402
from app.services.engine.resolver import apply, apply_activation, _can_take_followup, IllegalActionError  # noqa: E402
from app.services.engine.state import BattleState, Objective, Position, UnitBlob, WeaponProfile, apply_events  # noqa: E402
from app.services.engine.state_codec import battle_state_to_json, battle_state_from_json  # noqa: E402
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY  # noqa: E402
from app.services.engine.terrain_complex import TerrainPolygon  # noqa: E402


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def wire(action):
    return action_to_json(action) if action is not None else None


def scenario(name: str) -> BattleState:
    """Small diagnostic positions, not tournament armies or strength samples."""
    rifle = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
    sword = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)
    own = UnitBlob(id=1, owner_player=0, position=Position(0, 0), radius_inches=0.5,
                   models_alive=3, toughness_per_model=3,
                   ranged_weapons=(rifle,), melee_weapons=(sword,))
    enemy = replace(own, id=2, owner_player=1, position=Position(12, 0))
    state = BattleState(round=1, active_player=0, activations_remaining=(1, 1),
                        blobs=(own, enemy), terrain=(),
                        objectives=(Objective(id=1, position=Position(6, 3)),),
                        initial_toughness_snapshot=((1, 9), (2, 9)))
    if name == "ranged":
        return state
    if name == "contact":
        return replace(state, blobs=(own, replace(enemy, position=Position(2, 0))))
    if name in ("exhausted", "pinned"):
        status = STATUS_WYCZERPANY if name == "exhausted" else STATUS_PRZYSZPILONY
        return replace(state, blobs=(replace(own, status_flags=(status,)), enemy))
    if name in ("polygon_detour", "wall_blocked"):
        high = 1 if name == "polygon_detour" else 20
        polygon = TerrainPolygon(tuple(Position(x, y) for x, y in
                                       ((2, -high), (3, -high), (3, high), (2, high))),
                                 ("Niedostepny", "Blokujacy"))
        return replace(state, blobs=(replace(own, ranged_weapons=(), melee_weapons=()), enemy),
                       terrain=(polygon,), objectives=(Objective(id=1, position=Position(6, 0)),))
    if name == "objective_edge":
        return replace(state, objectives=(Objective(id=1, position=Position(2.5, 0)),))
    if name == "last_round":
        return replace(state, round=4)
    if name == "game_over":
        return replace(state, round=4, is_game_over=True)
    raise ValueError(f"unknown scenario {name!r}")


def decision_once(kind: str, seed: int, name: str) -> dict:
    original = scenario(name)
    public_wire = battle_state_to_json(original)
    state = battle_state_from_json(public_wire)
    player = make_player(kind, seed)
    start = perf_counter()
    first = player.choose_action(state, 0)
    elapsed = (perf_counter() - start) * 1000
    record = dict(first=wire(first), decision_ms=elapsed,
                  public_roundtrip=state == original, input_unchanged=True,
                  resolver_accepted=False, requested=[], applied=[])
    requests, applied = [], []

    def continuation(current, uid, taken):
        start = perf_counter()
        action = player.continue_activation(current, 0, uid, taken)
        requests.append(dict(action=wire(action), decision_ms=(perf_counter() - start) * 1000,
                             same_unit=action is None or action.unit_id == uid,
                             append_allowed=action is None or _can_take_followup(action, taken)))
        return action

    try:
        if first is not None:
            # Public v1 proposes one action; the headless runner uses the other
            # entry point for continuations. Observe both without equating them.
            apply(state, first, DeterministicDice(seed))
            record["resolver_accepted"] = True
            result = apply_activation(state, first, DeterministicDice(seed),
                                      continuation=continuation,
                                      on_action=lambda a, before, after: applied.append(wire(a)))
            record.update(replay_equal=apply_events(state, result.events) == result.state,
                          final_digest=digest(battle_state_to_json(result.state)))
    except (IllegalActionError, ValueError) as exc:
        record.update(error_type=type(exc).__name__, error=str(exc))
    record.update(requested=requests, applied=applied,
                  input_unchanged=battle_state_to_json(state) == public_wire
                  and battle_state_to_json(original) == public_wire)
    return record


def deterministic(value):
    if isinstance(value, dict):
        return {k: deterministic(v) for k, v in value.items() if not k.endswith("_ms")}
    if isinstance(value, list):
        return [deterministic(v) for v in value]
    return value


def deployment_once(kind: str, seed: int, strategy: str, narrow: bool) -> dict:
    state = scenario("ranged")
    # Two units per side make occupancy and ordering observable.
    state = replace(state, blobs=state.blobs + tuple(replace(b, id=b.id + 2) for b in state.blobs))
    zones = [dep.DeploymentZone(0, y, 6 if narrow else 12, y + (2 if narrow else 6))
             for y in (0, 12)]
    polygon = TerrainPolygon(tuple(Position(x, y) for x, y in ((0, 0), (2, 0), (2, 2), (0, 2))),
                             ("Niedostepny",))
    state = replace(state, terrain=(polygon,))
    players = [make_player(kind, seed + p * PLAYER_SEED_OFFSET) for p in (0, 1)]
    start = perf_counter()
    try:
        actions = match._build_deployment_from_players(
            state, players, zones, deployment_strategies=None if strategy == "default" else (strategy, strategy))
        occupied = []
        for action in actions:
            unit = next(b for b in state.blobs if b.id == action.unit_id)
            assert dep.is_deployment_position_legal(unit, action.position, zones[unit.owner_player],
                                                    occupied=occupied, terrain=state.terrain)
            occupied.append(replace(unit, position=action.position))
        return dict(status="legal", positions=[[b.id, b.position.x, b.position.y] for b in occupied],
                    deployment_ms=(perf_counter() - start) * 1000)
    except IllegalActionError as exc:
        return dict(status="bounded_exhaustion", error=str(exc), deployment_ms=(perf_counter() - start) * 1000)


def ending_once(kind: str, seed: int) -> dict:
    state = scenario("last_round")
    players = [make_player(kind, seed + p * PLAYER_SEED_OFFSET) for p in (0, 1)]
    start = perf_counter()
    try:
        result = match.run_match(state, players, DeterministicDice(seed), max_activations=16)
        return dict(status="complete" if result.final_state.is_game_over else "incomplete",
                    score=list(result.final_state.score), events=len(result.events),
                    replay_equal=apply_events(state, result.events) == result.final_state,
                    final_digest=digest(battle_state_to_json(result.final_state)),
                    event_digest=digest([event_to_json(e) for e in result.events]),
                    total_ms=(perf_counter() - start) * 1000)
    except (IllegalActionError, RuntimeError) as exc:
        return dict(status="error", error=str(exc), total_ms=(perf_counter() - start) * 1000)


def fixture_once(kind: str, fixture: str) -> dict:
    # Reuse the D5.3b leaf's loader/preparation and full replay observation.
    # Expensive families deliberately get only the small positions/ending.
    from scripts.deployment_experiment import run_once

    return run_once(dict(fixture=dict(path=fixture), policy=kind, seed=19, swap=False,
                         initiative=0, strategies=("grid", "grid")),
                    dict(ruleset_version="v1", max_activations=256,
                         deployment_zones=((0, 0, 72, 12), (0, 36, 72, 48))))


def symmetry_probe() -> dict:
    """Concrete tie/order and deployment reflection counterexamples, not causality."""
    state = scenario("polygon_detour")
    targets = (Objective(id=1, position=Position(0, 6)), Objective(id=2, position=Position(0, -6)))
    state = replace(state, terrain=(), objectives=targets)
    actions = [wire(make_player("priority", 19).choose_action(replace(state, objectives=order), 0))
               for order in (targets, tuple(reversed(targets)))]
    grid = dep.grid_positions(dep.DeploymentZone(0, 0, 12, 12), 4, 0.5)
    opposing = dep.grid_positions(dep.DeploymentZone(0, 36, 12, 48), 4, 0.5)
    reflected = [Position(p.x, 48 - p.y) for p in grid]
    control, _, _ = _check_objective_control(scenario("objective_edge"))
    return dict(priority_objective_order_actions=actions, objective_order_changes_action=actions[0] != actions[1],
                grid_reflection_preserves_id_slots=reflected == opposing,
                grid_lower=[[p.x, p.y] for p in grid], grid_upper=[[p.x, p.y] for p in opposing],
                objective_edge_controller=control.objectives[0].controller)


def run(manifest: dict) -> dict:
    if manifest["schema"] != "szop.bots_audit/v1":
        raise ValueError("unsupported audit schema")
    if manifest["kinds"] != list(ALL_KINDS) or manifest["seeds"] != [11, 19]:
        raise ValueError("audit is frozen on registry kinds and seeds 11,19")
    if not 1 <= len(manifest["scenarios"]) <= 16 or len(manifest["fixtures"]) > 2:
        raise ValueError("audit input exceeds the frozen small sample budget")
    for name in manifest["scenarios"]:
        scenario(name)
    decisions, deployments, endings, fixtures = [], [], [], []
    for kind in manifest["kinds"]:
        spec(kind)
        for seed in manifest["seeds"]:
            for name in manifest["scenarios"]:
                repeats = [decision_once(kind, seed, name) for _ in range(2)]
                decisions.append(dict(kind=kind, seed=seed, scenario=name, result=deterministic(repeats[0]),
                                      reproducible=deterministic(repeats[0]) == deterministic(repeats[1]),
                                      timings_ms=[r["decision_ms"] for r in repeats],
                                      followup_timings_ms=[[q["decision_ms"] for q in r["requested"]] for r in repeats]))
        for strategy in ("default", "grid", "objectives"):
            for narrow in (False, True):
                repeats = [deployment_once(kind, 19, strategy, narrow) for _ in range(2)]
                deployments.append(dict(kind=kind, strategy=strategy, narrow=narrow,
                                        result=deterministic(repeats[0]),
                                        reproducible=deterministic(repeats[0]) == deterministic(repeats[1]),
                                        timings_ms=[r["deployment_ms"] for r in repeats]))
        repeats = [ending_once(kind, 19) for _ in range(2)]
        endings.append(dict(kind=kind, result=deterministic(repeats[0]),
                            reproducible=deterministic(repeats[0]) == deterministic(repeats[1]),
                            timings_ms=[r["total_ms"] for r in repeats]))
        if spec(kind).has("fast"):
            for fixture in manifest["fixtures"]:
                repeats = [fixture_once(kind, fixture) for _ in range(2)]
                fixtures.append(dict(kind=kind, fixture=fixture, result=deterministic(repeats[0]),
                                     reproducible=deterministic(repeats[0]) == deterministic(repeats[1]),
                                     timings_ms=[r["total_ms"] for r in repeats]))
        print(f"{kind}: observed", file=sys.stderr, flush=True)
    rows = decisions + deployments + endings + fixtures
    return dict(schema="szop.bots_audit.results/v1", manifest=manifest,
                base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                python=platform.python_version(), platform=platform.platform(),
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                manifest_digest=digest(manifest),
                fixture_sha256={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                for path in manifest["fixtures"]},
                decisions=decisions, deployments=deployments, endings=endings, fixtures=fixtures, symmetry=symmetry_probe(),
                summary=dict(decision_cases=len(decisions), deployment_cases=len(deployments),
                             ending_cases=len(endings), fixture_cases=len(fixtures),
                             non_reproducible=sum(not r["reproducible"] for r in rows),
                             accepted_first=dict(Counter(r["kind"] for r in decisions if r["result"]["resolver_accepted"]))))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return 1 if result["summary"]["non_reproducible"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
