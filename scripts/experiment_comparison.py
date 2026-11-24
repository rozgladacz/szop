"""Compare matched blocks in the frozen D5.3b design using archived evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib

if __package__:
    from . import experiment_archive as archive
else:
    import experiment_archive as archive


SCHEMA = "szop.experiment.comparison/v1"
STRATEGIES = ("grid", "objectives")
OUTCOMES = ("player_0", "player_1", "draw")
PROFILE = {
    "schema": "szop.experiment.comparison_profile/v1",
    "id": "d5_3b",
    "variable": "deployment_strategy_by_side",
    "block_axes": ["fixture", "policy", "seed"],
    "variant_axes": ["swap", "initiative", "strategies"],
    "source": {
        "package_type": archive.DEPLOYMENT_TYPE,
        "base_commit": "5588fedfc021129c6a0480c8dd4b7d4609c99d39",
        "manifest_digest": "cd24887cbd140bdd0348c7c98a5529b3bb07fdd0cc6fbd48bb5c4b090d1ec6fb",
        "source_digest": "fe83b5909882ae3fb34d637b548b6bf122260f2bc3caa4b4c48ca034face1be5",
        "ruleset_version": "v1",
    },
    "original_army_units": [[1, 2, 3, 4], [5, 6, 7, 8]],
    "side_effect_threshold": None,
}


def _digest(value: object, *, published: bool = False) -> str:
    data = archive._canonical(value)
    return hashlib.sha256(data + b"\n" if published else data).hexdigest()


def _counts() -> dict:
    return dict(controls={strategy: dict.fromkeys(OUTCOMES, 0) for strategy in STRATEGIES},
                mixed=dict.fromkeys((*STRATEGIES, "draw"), 0),
                mixed_by_objectives_side={side: dict.fromkeys((*STRATEGIES, "draw"), 0)
                                          for side in OUTCOMES[:2]})


def _count(counts: dict, case: dict, outcome: str) -> None:
    strategies = case["strategies"]
    if strategies[0] == strategies[1]:
        counts["controls"][strategies[0]][outcome] += 1
    else:
        winner = "draw" if outcome == "draw" else strategies[OUTCOMES.index(outcome)]
        counts["mixed"][winner] += 1
        counts["mixed_by_objectives_side"][OUTCOMES[strategies.index("objectives")]][winner] += 1


def _strategy_evidence(case: dict, result: dict) -> bool:
    placements = result.get("placements")
    if not isinstance(placements, list):
        return False
    originals = PROFILE["original_army_units"]
    owners = originals[::-1] if case["swap"] else originals
    units = [[], []]
    for placement in placements:
        if not isinstance(placement, dict):
            return False
        owner, unit = placement.get("owner"), placement.get("unit")
        if type(owner) is not int or owner not in (0, 1) or type(unit) is not int:
            return False
        target = placement.get("assigned_target")
        if "assigned_target" not in placement or (target is not None and type(target) is not int):
            return False
        if (target is not None) != (case["strategies"][owner] == "objectives"):
            return False
        units[owner].append(unit)
    return [sorted(army) for army in units] == owners


def _block_exclusions(members: list[dict], assessed: dict, results: dict) -> dict:
    exclusions = defaultdict(list)
    variants = defaultdict(list)
    for case in members:
        case_id = case["id"]
        check = assessed.get(case_id)
        if check is None:
            exclusions["missing_case"].append(case_id)
            continue
        if check["category"] != "passed":
            exclusions["technical:" + check["category"]].append(case_id)
            continue
        if check["replay"] != {"scope": "match", "status": "passed"} or check["outcome"] not in OUTCOMES:
            exclusions["missing_match_evidence"].append(case_id)
            continue
        result = results[case_id]
        digest = result.get("input_digest")
        if not archive._matches(archive.DIGEST, digest):
            exclusions["missing_input_digest"].append(case_id)
        else:
            variants[(case["swap"], case["initiative"])].append((digest, case_id))
        if not _strategy_evidence(case, result):
            exclusions["armies_or_strategies_unverified"].append(case_id)

    digest_variants = defaultdict(set)
    for variant, entries in variants.items():
        for digest, _ in entries:
            digest_variants[digest].add(variant)
    for entries in variants.values():
        if len({digest for digest, _ in entries}) != 1:
            exclusions["initial_state_mismatch"].extend(case_id for _, case_id in entries)
        for digest, case_id in entries:
            if len(digest_variants[digest]) > 1:
                exclusions["aliased_swap_or_initiative"].append(case_id)
    return dict(exclusions)


def _provenance(technical: dict, descriptor: dict, manifest: dict, results: dict) -> tuple[dict, list[str]]:
    observed = dict(package_type=technical["package_type"], manifest_digest=_digest(manifest),
                    base_commit=descriptor.get("recorded_revision"),
                    ruleset_version=manifest.get("ruleset_version"), source_digest=None)
    expected = PROFILE["source"]
    if observed["package_type"] != expected["package_type"]:
        return observed, ["outside_experiment_design"]

    metadata = results.get("metadata", {})
    sources = metadata.get("sources")
    if archive._digest_map_recorded(sources):
        observed["source_digest"] = _digest(sources)
    reasons = []
    if (observed["base_commit"] != expected["base_commit"]
            or metadata.get("base_commit") != expected["base_commit"]):
        reasons.append("incompatible_revision")
    if (observed["source_digest"], observed["ruleset_version"]) != (
        expected["source_digest"], expected["ruleset_version"]
    ):
        reasons.append("incompatible_mechanism")
    if (observed["manifest_digest"] != expected["manifest_digest"]
            or descriptor["evidence"]["manifest_binding"] == "unknown"):
        reasons.append("incompatible_design")
    return observed, reasons


def compare(technical: dict, descriptor: dict, manifest: dict, plan: list[dict], results: dict) -> dict:
    """Use the technical result and case evidence from the same verified read."""
    provenance, source_reasons = _provenance(technical, descriptor, manifest, results)
    supported_type = provenance["package_type"] == PROFILE["source"]["package_type"]
    assessed = {item["case_id"]: item for item in technical["cases"] if item["group"] == "match"}
    records = {row["case"]["id"]: row["result"] for row in results["records"]} if supported_type else {}
    grouped = defaultdict(list)
    if supported_type:
        for case in plan:
            grouped[(case["fixture"]["id"], case["policy"], case["seed"])].append(case)

    blocks, breakdown = [], {}
    totals, reasons = _counts(), Counter()
    included_cases = included_blocks = 0
    for (fixture, policy, seed), members in sorted(grouped.items()):
        exclusions = _block_exclusions(members, assessed, records)
        member_ids = [case["id"] for case in members]
        reasons.update(exclusions.keys())
        reasons.update(source_reasons)
        included = not (exclusions or source_reasons)
        blocks.append(dict(fixture=fixture, policy=policy, seed=seed, included=included,
                           case_ids=member_ids, exclusions=exclusions))
        if included:
            included_cases += len(members)
            included_blocks += 1
        for case in members:
            key = (fixture, policy, case["initiative"])
            if key not in breakdown:
                breakdown[key] = dict(cases_planned=0, cases_recorded=0, cases_included=0, **_counts())
            counts = breakdown[key]
            counts["cases_planned"] += 1
            counts["cases_recorded"] += case["id"] in assessed
            if included:
                counts["cases_included"] += 1
                outcome = assessed[case["id"]]["outcome"]
                _count(totals, case, outcome)
                _count(counts, case, outcome)

    recorded = technical["coverage"]["recorded"]
    planned = len(plan) if supported_type else None
    profile_digest = _digest(PROFILE)
    policy_digest = technical["policy_digest"]
    report_key = _digest(dict(profile_digest=profile_digest, policy_digest=policy_digest))
    return dict(
        schema=SCHEMA, package_id=technical["package_id"], profile=deepcopy(PROFILE),
        profile_digest=profile_digest, report_key=report_key,
        quality=dict(schema=technical["schema"], policy_digest=policy_digest,
                     report_sha256=_digest(technical, published=True), coverage=technical["coverage"]),
        status="passed" if included_blocks and included_blocks == len(blocks) else "review",
        provenance=provenance, source_reasons=source_reasons,
        coverage=dict(
            blocks_planned=len(blocks) if supported_type else None, blocks_included=included_blocks,
            blocks_excluded=len(blocks) - included_blocks if supported_type else None,
            cases_planned=planned, cases_recorded=recorded, cases_included=included_cases,
            cases_excluded=recorded - included_cases, cases_missing=None if planned is None else planned - recorded,
            blocks_by_exclusion=dict(reasons),
        ),
        blocks=blocks, totals=totals,
        breakdown=[dict(fixture=fixture, policy=policy, initiative=initiative, **counts)
                   for (fixture, policy, initiative), counts in sorted(breakdown.items())],
        side_effect=dict(unit="block", interpretation="descriptive_control_imbalance",
                         threshold=PROFILE["side_effect_threshold"],
                         control_delta_p0_minus_p1={strategy: counts["player_0"] - counts["player_1"]
                                                    if included_blocks else None
                                                    for strategy, counts in totals["controls"].items()}),
    )
