"""D5.3b: sequential, reproducible deployment experiment over existing SSOTs.

Instrumentation patches are scoped to deployment and restored on every exit.
Run this leaf harness in one thread; it does not change production code.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
import hashlib
from itertools import product
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from balance_common import bsim  # noqa: E402
from app.services.agents import deployment as dep, match  # noqa: E402
from app.services.agents.factory import make_player, PLAYER_SEED_OFFSET  # noqa: E402
from app.services.agents.maps import build_map  # noqa: E402
from app.services.agents.registry import spec  # noqa: E402
from app.services.engine.dice import DeterministicDice  # noqa: E402
from app.services.engine.events import event_to_json  # noqa: E402
from app.services.engine.geometry import distance  # noqa: E402
from app.services.engine.phases import setup_phase, deployment_round  # noqa: E402
from app.services.engine.resolver import IllegalActionError  # noqa: E402
from app.services.engine.state import apply_events  # noqa: E402
from app.services.engine.state_codec import battle_state_to_json  # noqa: E402


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def load_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["schema"] != "szop.deployment_experiment/v1":
        raise ValueError("unsupported experiment schema")
    for key in ("fixtures", "policies", "battle_seeds", "swaps", "initiatives", "strategy_pairs"):
        if not isinstance(value[key], list) or not value[key]:
            raise ValueError(f"empty or invalid {key}")
    if any(type(n) is not int or n < 0 for n in value["battle_seeds"]):
        raise ValueError("battle seeds must be nonnegative integers")
    if any(type(n) is not bool for n in value["swaps"]):
        raise ValueError("swaps must be boolean")
    if any(type(n) is not int or n not in (0, 1) for n in value["initiatives"]):
        raise ValueError("invalid initiative")
    if any(len(pair) != 2 or any(s not in ("grid", "objectives") for s in pair)
           for pair in value["strategy_pairs"]):
        raise ValueError("invalid strategies")
    if type(value["repeats"]) is not int or not 2 <= value["repeats"] <= 5:
        raise ValueError("require 2..5 repeats")
    if type(value["max_activations"]) is not int or not 1 <= value["max_activations"] <= 2000:
        raise ValueError("require a bounded activation cap")
    if value["ruleset_version"] != "v1":
        raise ValueError("experiment is frozen on v1 headless runner")
    if len(value["deployment_zones"]) != 2:
        raise ValueError("two explicit deployment zones required")
    for policy in value["policies"]:
        spec(policy)  # registry SSOT, not a second allowlist
    cases = list(iter_cases(value))
    if len(cases) * value["repeats"] > 2048 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate or excessive experiment cases")
    return value


def iter_cases(manifest: dict):
    for fixture, policy, seed, swap, initiative, strategies in product(
        manifest["fixtures"], manifest["policies"], manifest["battle_seeds"],
        manifest["swaps"], manifest["initiatives"], manifest["strategy_pairs"],
    ):
        case = dict(fixture=fixture, policy=policy, seed=seed, swap=swap,
                    initiative=initiative, strategies=strategies)
        yield dict(id=digest(case)[:20], **case)


def fixture_for(case: dict):
    source = case["fixture"]
    return (build_map(source["map"], source["map_seed"]) if "map" in source
            else bsim.load_battle_fixture(ROOT / source["path"]))


def prepare(case: dict, manifest: dict):
    fixture = fixture_for(case)
    rosters = deepcopy(fixture.rosters)
    if case["swap"]:
        rosters = list(reversed(rosters))
    for owner, roster in enumerate(rosters):
        roster["owner_player"] = owner
    # Decision seeds follow original armies under a side swap, not physical P0/P1.
    origins = (1, 0) if case["swap"] else (0, 1)
    players = [make_player(case["policy"], case["seed"] + origin * PLAYER_SEED_OFFSET)
               for origin in origins]
    state = setup_phase(rosters, terrain=fixture.terrain, objectives=fixture.objectives,
                        initiative_player=case["initiative"],
                        ruleset_version=manifest["ruleset_version"])
    return state, players, [dep.DeploymentZone(*z) for z in manifest["deployment_zones"]]


def run_once(case: dict, manifest: dict) -> dict:
    """Use actual deployment runner and match; never reconstruct their policy."""
    start = perf_counter()
    state, players, zones = prepare(case, manifest)
    record = dict(status="deployment_error", input_digest=digest(battle_state_to_json(state)))
    assignments, candidates = {}, Counter()
    original_choice, original_legal = match.objective_deployment_choice, dep.is_deployment_position_legal

    def observe_choice(s, unit_id, zone, **kwargs):
        result = original_choice(s, unit_id, zone, **kwargs)
        assignments[unit_id] = result[1]
        return result

    def observe_candidate(unit, *args, **kwargs):
        candidates[unit.owner_player] += 1
        return original_legal(unit, *args, **kwargs)

    stage = "deployment"
    deploy_start = perf_counter()
    try:
        with patch.object(match, "objective_deployment_choice", observe_choice), \
                patch.object(dep, "is_deployment_position_legal", observe_candidate):
            actions = match._build_deployment_from_players(
                state, players, zones, deployment_strategies=case["strategies"],
            )
        deployment_ms = (perf_counter() - deploy_start) * 1000
        occupied, placements = [], []
        for action in actions:
            unit = next(b for b in state.blobs if b.id == action.unit_id)
            if not original_legal(unit, action.position, zones[unit.owner_player],
                                  occupied=occupied, terrain=state.terrain):
                raise AssertionError("runner returned illegal placement")
            target = assignments.get(unit.id)
            nearest = min(state.objectives, key=lambda o: (distance(action.position, o.position), o.id),
                          default=None)
            gap = lambda o: max(0.0, distance(action.position, o.position) - unit.radius_inches)
            assigned = next((o for o in state.objectives if o.id == target), None)
            placements.append(dict(unit=unit.id, owner=unit.owner_player,
                                   position=[action.position.x, action.position.y],
                                   assigned_target=target, assigned_gap=gap(assigned) if assigned else None,
                                   nearest_target=nearest.id if nearest else None,
                                   nearest_gap=gap(nearest) if nearest else None))
            occupied.append(replace(unit, position=action.position))
        initial, _ = deployment_round(state, actions)
        record.update(placements=placements, candidates=[candidates[0], candidates[1]],
                      deployment_ms=deployment_ms)
        stage = "match"
        result = match.run_match(initial, players, DeterministicDice(seed=case["seed"]),
                                 max_activations=manifest["max_activations"])
        match_end = perf_counter()
        replayed = apply_events(initial, result.events)
        if replayed != result.final_state:
            raise AssertionError("complete replay differs from live state")
        if not result.final_state.is_game_over:
            raise AssertionError("match returned before game end")
        record.update(status="complete", score=list(result.final_state.score),
                      winner=result.winner, rounds=result.rounds_played,
                      events=len(result.events), event_digest=digest([event_to_json(e) for e in result.events]),
                      final_digest=digest(battle_state_to_json(result.final_state)), replay_equal=True,
                      total_ms=(match_end - start) * 1000)
    except (IllegalActionError, RuntimeError) as exc:
        record.update(status="activation_cap" if "exceeded max_activations=" in str(exc)
                      else f"{stage}_error", error_type=type(exc).__name__, error=str(exc),
                      candidates=[candidates[0], candidates[1]], total_ms=(perf_counter() - start) * 1000)
    return record


def deterministic(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.endswith("_ms")}


def run_case(case: dict, manifest: dict) -> dict:
    repeats = [run_once(case, manifest) for _ in range(manifest["repeats"])]
    stable = all(deterministic(r) == deterministic(repeats[0]) for r in repeats[1:])
    return dict(case=case, result=deterministic(repeats[0]), reproducible=stable,
                timings=[{k: v for k, v in r.items() if k.endswith("_ms")} for r in repeats])


def summarize(records: list[dict]) -> dict:
    statuses = Counter(r["result"]["status"] for r in records)
    mixed = [r for r in records if len(set(r["case"]["strategies"])) == 2]
    complete_mixed = [r for r in mixed if r["result"]["status"] == "complete"]
    wins = Counter("draw" if r["result"]["winner"] is None else
                   r["case"]["strategies"][r["result"]["winner"]] for r in complete_mixed)
    return dict(cases=len(records), statuses=dict(statuses), mixed_cases=len(mixed),
                complete_mixed=len(complete_mixed), mixed_outcomes=dict(wins),
                non_reproducible=sum(not r["reproducible"] for r in records))


def render_report(records: list[dict]) -> str:
    summary = summarize(records)
    lines = ["# D5.3b — wyniki zamrożonego eksperymentu", "", "```json",
             json.dumps(summary, indent=2, ensure_ascii=False), "```", "",
             "Każdy przypadek liczony raz; powtórzenia służą weryfikacji determinizmu.", "",
             "| Mapa/fixture | Polityka | Mieszane zakończone / wszystkie | Cele / grid / remis |",
             "|---|---|---:|---:|"]
    groups = defaultdict(list)
    for row in records:
        groups[(row["case"]["fixture"]["id"], row["case"]["policy"])].append(row)
    for (name, policy), rows in sorted(groups.items()):
        s = summarize(rows); w = s["mixed_outcomes"]
        lines.append(f"| {name} | {policy} | {s['complete_mixed']} / {s['mixed_cases']} | "
                     f"{w.get('objectives', 0)} / {w.get('grid', 0)} / {w.get('draw', 0)} |")
    lines += ["", "| Strategia | Pozycje | Średni dystans do najbliższego celu | "
              "Najgorszy dystans | Średnia liczba różnych najbliższych celów / strona |",
              "|---|---:|---:|---:|---:|"]
    for strategy in ("grid", "objectives"):
        gaps, coverage = [], []
        for row in records:
            for owner, selected in enumerate(row["case"]["strategies"]):
                if selected == strategy and "placements" in row["result"]:
                    units = [p for p in row["result"]["placements"] if p["owner"] == owner]
                    gaps += [p["nearest_gap"] for p in units if p["nearest_gap"] is not None]
                    coverage.append(len({p["nearest_target"] for p in units if p["nearest_target"] is not None}))
        if gaps:
            lines.append(f"| {strategy} | {len(gaps)} | {mean(gaps):.3f} | {max(gaps):.3f} | {mean(coverage):.3f} |")
    lines += ["", "| Strategia | Średnia liczba faktycznych przydziałów / strona | "
              "Średni / max dystans do przydzielonego celu | Średnia liczba walidacji kandydatów / strona |",
              "|---|---:|---:|---:|"]
    for strategy in ("grid", "objectives"):
        counts, gaps, validations = [], [], []
        for row in records:
            for owner, selected in enumerate(row["case"]["strategies"]):
                if selected == strategy and "placements" in row["result"]:
                    units = [p for p in row["result"]["placements"] if p["owner"] == owner]
                    counts.append(len({p["assigned_target"] for p in units if p["assigned_target"] is not None}))
                    gaps += [p["assigned_gap"] for p in units if p["assigned_gap"] is not None]
                    validations.append(row["result"]["candidates"][owner])
        if counts:
            assigned = f"{mean(gaps):.3f} / {max(gaps):.3f}" if gaps else "brak przydziałów w Grid"
            lines.append(f"| {strategy} | {mean(counts):.3f} | {assigned} | {mean(validations):.3f} |")
    lines += ["", "| Wariant stron | Przypadki | Średni deployment ms | Średnia pełna gra ms |",
              "|---|---:|---:|---:|"]
    for pair in product(("grid", "objectives"), repeat=2):
        rows = [r for r in records if tuple(r["case"]["strategies"]) == pair and r["result"]["status"] == "complete"]
        times = [t for r in rows for t in r["timings"]]
        if times:
            lines.append(f"| {' / '.join(pair)} | {len(rows)} | {mean(t['deployment_ms'] for t in times):.3f} | "
                         f"{mean(t['total_ms'] for t in times):.3f} |")
    return "\n".join(lines) + "\n"


def provenance(manifest_path: Path) -> dict:
    paths = [Path(__file__), ROOT / "scripts/balance_simulate.py", ROOT / "scripts/balance_common.py"]
    for folder in ("app/services/engine", "app/services/agents", "tests/fixtures/battles"):
        paths += [p for p in (ROOT / folder).rglob("*") if p.suffix in (".py", ".yaml")]
    return dict(base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                python=platform.python_version(), platform=platform.platform(),
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                sources={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(paths)})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    metadata = provenance(args.manifest)
    records = []
    for case in iter_cases(manifest):
        row = run_case(case, manifest)
        records.append(row)
        print(f"{len(records)} {case['id']} {row['result']['status']} stable={row['reproducible']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(metadata=metadata, summary=summarize(records), records=records),
                                   ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    args.report.write_text(render_report(records), encoding="utf-8")
    return 0 if all(r["reproducible"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
