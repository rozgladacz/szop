"""Assess the recorded technical evidence of a published experiment, offline."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import product
import math
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory

if __package__:
    from . import experiment_archive as archive
    from . import experiment_comparison as comparison
else:
    # Isolated Python omits the script directory from sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import experiment_archive as archive
    import experiment_comparison as comparison


SCHEMA = "szop.experiment.quality/v1"
POLICY_SCHEMA = "szop.experiment.quality_policy/v1"
RECORD_SCHEMA = "szop.campaign.record/v1"
# Frozen v1 wire values. Importing either runner would require the venv and current sources.
# Regression tests check these against the native v1 definitions.
CAMPAIGN_FAILURES = {"non_reproducible", "replay_error", "invariant_error", "harness_error"}
MATCH_STATUSES = {"complete", "deployment_error", "match_error", "activation_cap"}
CAMPAIGN_STATUSES = MATCH_STATUSES | (CAMPAIGN_FAILURES - {"non_reproducible"})
PRIMARY_ORDER = (
    "deployment_error", "match_error", "activation_cap", "decision_rejected", "decision_error",
    "invariant_error", "harness_error",
    "non_reproducible", "replay_error", "missing_repeat_evidence", "missing_replay_evidence",
)
DEPLOYMENT_SCHEMA = archive.HISTORY_FORMATS[archive.DEPLOYMENT_TYPE][0]
DEPLOYMENT_AXES = {
    "fixture": "fixtures", "policy": "policies", "seed": "battle_seeds", "swap": "swaps",
    "initiative": "initiatives", "strategies": "strategy_pairs",
}


class IntegrityError(ValueError):
    """The package failed structural or content verification."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def _same(actual, expected) -> bool:
    return archive._canonical(actual) == archive._canonical(expected)


def _snapshot_bytes(snapshot: Path, descriptor: dict, name: str) -> bytes:
    # Fixed, already inventoried paths. Check the same bytes the evidence parser uses.
    path = snapshot / name
    _require(stat.S_ISREG(archive._stat(path).st_mode), f"expected a regular snapshot file: {name}")
    data = path.read_bytes()
    entry = descriptor["files"][name]
    _require(len(data) == entry["size_bytes"] and _sha(data) == entry["sha256"],
             f"snapshot file changed while reading: {name}")
    return data


def _unique_list(manifest: dict, key: str, valid, *, empty=False) -> list:
    values = manifest[key]
    _require(isinstance(values, list) and (values or empty) and all(valid(v) for v in values)
             and len({archive._canonical(v) for v in values}) == len(values), f"invalid manifest {key}")
    return values


def _nonempty_text(value) -> bool:
    return isinstance(value, str) and bool(value)


def _seed(value) -> bool:
    return type(value) is int and value >= 0


def _side(value) -> bool:
    return type(value) is int and value in (0, 1)


def _fixture(value) -> bool:
    if not isinstance(value, dict) or not _nonempty_text(value.get("id")):
        return False
    return ((set(value) == {"id", "path"} and archive._is_fixture_path(value["path"]))
            or (set(value) == {"id", "map", "map_seed"} and _nonempty_text(value["map"])
                and _seed(value["map_seed"])))


def _strategy_pair(value) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and all(strategy in ("grid", "objectives") for strategy in value))


def _deployment_plan(manifest: dict, *, campaign: bool) -> list[dict]:
    # Decode the stored v1 design without loading live registry/map builders or touching fixture paths.
    _require(manifest["schema"] == DEPLOYMENT_SCHEMA and manifest["ruleset_version"] == "v1",
             "unsupported deployment manifest schema")
    validators = (_fixture, _nonempty_text, _seed, lambda v: type(v) is bool, _side, _strategy_pair)
    axes = [_unique_list(manifest, key, valid) for key, valid in zip(DEPLOYMENT_AXES.values(), validators)]
    _require(len({fixture["id"] for fixture in axes[0]}) == len(axes[0]), "duplicate fixture ID")
    repeats = manifest.get("repeats")
    _require((not campaign and repeats is None) or (type(repeats) is int and 2 <= repeats <= 5),
             "invalid deployment repeat count")
    _require(math.prod(map(len, axes)) * (repeats or 1) <= 2048, "excessive deployment case grid")
    _require(type(manifest["max_activations"]) is int and 1 <= manifest["max_activations"] <= 2000,
             "invalid activation cap in manifest")
    zones = manifest["deployment_zones"]
    _require(isinstance(zones, list) and len(zones) == 2, "invalid deployment zones in manifest")
    cases = []
    for combination in product(*axes):
        case = dict(zip(DEPLOYMENT_AXES, combination))
        cases.append(dict(id=_sha(archive._canonical(case))[:20], **case))
    _require(len({case["id"] for case in cases}) == len(cases), "duplicate deployment case ID")
    return cases


def _check_match_status(row: dict, statuses: set[str]) -> str:
    status = row["result"]["status"]
    _require(isinstance(status, str) and status in statuses, "invalid match result status")
    if status == "complete":
        winner = row["result"]["winner"]
        _require(winner is None or _side(winner), "invalid match winner")
    return status


def _deployment_summary(rows: list[dict], *, campaign: bool) -> dict:
    # The frozen source report used raw statuses for D5.3b and overrides unstable rows for D7.1.
    statuses, outcomes = Counter(), Counter()
    mixed_cases = unstable = 0
    for row in rows:
        status = _check_match_status(row, CAMPAIGN_STATUSES if campaign else MATCH_STATUSES)
        _require(type(row["reproducible"]) is bool, "invalid recorded reproducibility")
        unstable += not row["reproducible"]
        if campaign and not row["reproducible"]:
            status = "non_reproducible"
        statuses[status] += 1
        pair = row["case"]["strategies"]
        if pair[0] != pair[1]:
            mixed_cases += 1
            if status == "complete":
                winner = row["result"]["winner"]
                outcomes["draw" if winner is None else pair[winner]] += 1
    return dict(cases=len(rows), statuses=dict(statuses), mixed_cases=mixed_cases,
                complete_mixed=sum(outcomes.values()), mixed_outcomes=dict(outcomes), non_reproducible=unstable)


def _campaign_rows(snapshot: Path, descriptor: dict, manifest: dict, plan: list[dict]) -> list[dict]:
    header = archive._json_object(_snapshot_bytes(snapshot, descriptor, "header.json"))
    header_hash = header.pop("sha256")
    _require(header["schema"] == archive.CAMPAIGN_SCHEMA and _sha(archive._canonical(header)) == header_hash,
             "campaign header hash or schema mismatch")
    identity = header["identity"]
    _require(isinstance(identity["sources"], dict) and archive._digest_map_recorded(identity["sources"])
             and isinstance(identity["dependencies"], dict) and isinstance(identity["python_family"], list),
             "invalid recorded campaign source identity")
    previous = descriptor["campaign_id"]
    _require(header["campaign_id"] == previous == _sha(archive._canonical(identity))
             and identity["manifest_digest"] == _sha(archive._canonical(manifest)), "campaign identity mismatch")
    inputs = {name: descriptor["files"][name]["sha256"] for name in archive._fixture_files(manifest)}
    derived = {name: entry["sha256"] for name, entry in descriptor["files"].items() if name != "checksums.json"}
    _require(_same(header["inputs"], inputs), "frozen input digest mismatch")
    _require(_same(archive._json_object(_snapshot_bytes(snapshot, descriptor, "checksums.json")), derived),
             "campaign checksums mismatch")

    rows = []
    journal = _snapshot_bytes(snapshot, descriptor, "journal.jsonl")
    _require(not journal or journal.endswith(b"\n"), "incomplete journal record")
    for index, line in enumerate(journal.split(b"\n")[:-1]):
        envelope = archive._json_object(line)
        digest = envelope.pop("sha256")
        row = envelope["row"]
        _require(envelope["schema"] == RECORD_SCHEMA and type(envelope["index"]) is int
                 and envelope["index"] == index and envelope["previous"] == previous
                 and digest == _sha(archive._canonical(envelope)), f"journal chain mismatch at line {index + 1}")
        _require(index < len(plan) and _same(row["case"], plan[index]),
                 f"unexpected or duplicate journal case at line {index + 1}")
        previous = digest
        rows.append(row)
    _require(len(rows) == descriptor["committed_cases"] and len(plan) == descriptor["planned_cases"],
             "campaign descriptor disagrees with manifest or journal case count")
    summary = _deployment_summary(rows, campaign=True)
    summary.update(planned=len(plan), campaign_id=descriptor["campaign_id"],
                   campaign_failures=sum(summary["statuses"].get(status, 0) for status in CAMPAIGN_FAILURES))
    report = _snapshot_bytes(snapshot, descriptor, "report.md")
    aggregate = re.match(rb"[^\r\n]+\r?\n\r?\n```json\r?\n(.*?)\r?\n```", report, flags=re.DOTALL)
    _require(aggregate is not None and _same(archive._json_object(aggregate[1]), summary),
             "campaign report aggregate disagrees with journal")
    return rows


def _historical_matches(results: dict, plan: list[dict]) -> list[dict]:
    rows = results["records"]
    planned = {case["id"]: case for case in plan}
    for row in rows:
        case = row["case"]
        _require(_same(case, planned.get(case["id"])), "historical deployment case is outside the manifest")
    _require(_same(results["summary"], _deployment_summary(rows, campaign=False)),
             "historical deployment aggregate disagrees with records")
    return rows


def _audit_plan(manifest: dict, results: dict) -> dict:
    kinds = set(_unique_list(manifest, "kinds", _nonempty_text))
    seeds = set(_unique_list(manifest, "seeds", _seed))
    scenarios = set(_unique_list(manifest, "scenarios", _nonempty_text))
    fixtures = set(_unique_list(manifest, "fixtures", archive._is_fixture_path, empty=True))
    strategies = ("default", "grid", "objectives")
    # Eligibility for fixture probes was a registry property absent from the archived manifest.
    counts = dict(decision=len(kinds) * len(seeds) * len(scenarios), deployment=len(kinds) * len(strategies) * 2,
                  ending=len(kinds), fixture=None)
    summary = Counter()
    accepted = Counter()
    for group, (field, _) in archive.AUDIT_GROUPS.items():
        rows = results[field]
        for row in rows:
            _require(row["kind"] in kinds, f"audit {group} case kind is outside the manifest")
            if group == "decision":
                _require(_seed(row["seed"]) and row["seed"] in seeds and row["scenario"] in scenarios,
                         "audit decision case is outside the manifest")
                flag = row["result"]["resolver_accepted"]
                _require(type(flag) is bool, "invalid audit decision acceptance evidence")
                if flag:
                    accepted[row["kind"]] += 1
            elif group == "deployment":
                _require(row["strategy"] in strategies and type(row["narrow"]) is bool,
                         "audit deployment case is outside the manifest")
            elif group == "fixture":
                _require(row["fixture"] in fixtures, "audit fixture case is outside the manifest")
            summary["non_reproducible"] += not row["reproducible"]
        summary[group + "_cases"] = len(rows)
    _require(_same(results["summary"], dict(summary, accepted_first=dict(accepted))),
             "historical audit aggregate disagrees with records")
    return counts


def _audit_case(group: str, row: dict) -> dict:
    return {key: row[key] for key in archive.AUDIT_GROUPS[group][1]}


def _sample_count(samples, *, scalar: bool) -> int | None:
    def number(value):
        return type(value) is int and value >= 0 or type(value) is float and math.isfinite(value) and value >= 0

    if samples is None:
        return None
    _require(isinstance(samples, list), "invalid timing samples")
    for sample in samples:
        valid = number(sample) if scalar else (
            isinstance(sample, dict) and bool(sample)
            and all(key.endswith("_ms") and number(value) for key, value in sample.items())
        )
        _require(valid, "invalid timing sample")
    return len(samples)


def _replay(result: dict, scope: str) -> str:
    claim = result.get("replay_equal")
    _require(claim is None or type(claim) is bool, "invalid replay evidence flag")
    if scope == "none":
        _require(claim is None, "unexpected replay evidence for a deployment probe")
        return "missing"
    fields = ("final_digest", "event_digest") if scope == "match" else ("final_digest",)
    for key in fields:
        value = result.get(key)
        _require(value is None or archive._matches(archive.DIGEST, value), f"invalid replay digest {key}")
    if claim is False or result.get("status") == "replay_error":
        return "failed"
    return "passed" if claim is True and all(result.get(key) is not None for key in fields) else "missing"


def _observation(row: dict, group: str, *, audit: bool) -> tuple[str, str, str | None]:
    result = row["result"]
    if not audit or group == "fixture":
        statuses = (MATCH_STATUSES if audit else CAMPAIGN_STATUSES)
        status = _check_match_status(row, statuses)
        return status, "match", None if status in ("complete", "replay_error") else status
    if group == "deployment":
        status = result["status"]
        _require(status in ("legal", "bounded_exhaustion"), "invalid audit deployment status")
        return status, "none", None if status == "legal" else "deployment_error"
    if group == "ending":
        status = result["status"]
        _require(status in ("complete", "incomplete", "error"), "invalid audit ending status")
        return status, "match", {"incomplete": "invariant_error", "error": "match_error"}.get(status)
    for key in ("public_roundtrip", "input_unchanged"):
        _require(type(result[key]) is bool, f"invalid audit decision {key}")
    first, accepted = result["first"], result["resolver_accepted"]
    _require(first is None or isinstance(first, dict), "invalid audit first action")
    _require(first is not None or (not accepted and result.get("replay_equal") is None),
             "contradictory audit decision evidence")
    if not result["public_roundtrip"] or not result["input_unchanged"]:
        return "decision_error", "activation", "invariant_error"
    if first is not None and not accepted:
        return "decision_rejected", "activation", "decision_rejected"
    if result.get("error") is not None:
        return "decision_error", "activation", "decision_error"
    return ("resolver_accepted" if accepted else "no_action"), "activation", None


def _assess(row: dict, case: dict, group: str, evidence: dict, policy: dict,
            *, audit: bool, declared_repeats: int | None) -> dict:
    status, scope, domain_failure = _observation(row, group, audit=audit)
    result = row["result"]
    replay = _replay(result, scope)
    samples = _sample_count(row.get("timings_ms" if audit else "timings"), scalar=audit)
    reproducible = row["reproducible"]
    _require(type(reproducible) is bool, "invalid recorded reproducibility")
    _require(declared_repeats is None or samples is None or samples <= declared_repeats,
             "more timing samples than declared executions")
    reasons = {domain_failure} if domain_failure else set()
    if not reproducible:
        reasons.add("non_reproducible")
    if samples is None or samples < max(declared_repeats or 0, policy["min_repeats"]):
        reasons.add("missing_repeat_evidence")
    if replay != "passed":
        reasons.add("replay_error" if replay == "failed" else "missing_replay_evidence")
    ordered = [reason for reason in policy["primary_order"] if reason in reasons]
    outcome = None
    if not ordered and status == "complete" and "winner" in result:
        winner = result["winner"]
        _require(winner is None or _side(winner), "invalid winner")
        outcome = "draw" if winner is None else f"player_{winner}"
    case_id = case.get("id") or _sha(archive._canonical([group, case]))
    return dict(case_id=case_id, group=group, case=case, evidence=evidence, recorded_status=status,
                category=ordered[0] if ordered else "passed", reasons=ordered, outcome=outcome,
                repeat_samples=samples, recorded_reproducible=reproducible,
                replay=dict(scope=scope, status=replay))


def _group_summary(cases: list[dict], planned: int | None) -> dict:
    categories = Counter(case["category"] for case in cases)
    reasons = Counter(reason for case in cases for reason in case["reasons"])
    outcomes = Counter(case["outcome"] for case in cases if case["outcome"] is not None)
    return dict(planned=planned, recorded=len(cases), missing=None if planned is None else planned - len(cases),
                categories=dict(categories), reasons=dict(reasons), outcomes=dict(outcomes))


def evaluate(root: Path, package_id: str, *, min_repeats: int = 2, compare: bool = False) -> dict:
    """Assess a verified package, optionally including the frozen comparison design."""
    if type(min_repeats) is not int or min_repeats < 2:
        raise ValueError("the minimum repeat count must be at least 2")
    policy = dict(schema=POLICY_SCHEMA, version=1, min_repeats=min_repeats,
                  replay="recorded_equality_and_digests", primary_order=list(PRIMARY_ORDER))
    plan, results = [], {}
    try:
        descriptor = archive.verify_package(root, package_id)
        snapshot = root / "packages" / package_id / archive.SNAPSHOT
        manifest = archive._json_object(_snapshot_bytes(snapshot, descriptor, "manifest.json"))
        kind = descriptor["type"]
        campaign = kind == archive.PACKAGE_TYPE
        audit = kind == archive.BOTS_AUDIT_TYPE
        if audit:
            results = archive._json_object(_snapshot_bytes(snapshot, descriptor, "results.json"))
            counts = _audit_plan(manifest, results)
            cases = [
                _assess(row, _audit_case(group, row), group, dict(file="results.json", pointer=f"/{field}/{index}"),
                        policy, audit=True, declared_repeats=None)
                for group, (field, _) in archive.AUDIT_GROUPS.items() for index, row in enumerate(results[field])
            ]
        else:
            plan = _deployment_plan(manifest, campaign=campaign)
            counts = {"match": len(plan)}
            if campaign:
                rows = _campaign_rows(snapshot, descriptor, manifest, plan)
            else:
                results = archive._json_object(_snapshot_bytes(snapshot, descriptor, "results.json"))
                rows = _historical_matches(results, plan)
            cases = [
                _assess(row, row["case"], "match",
                        dict(file="journal.jsonl", line=index + 1, pointer="/row") if campaign
                        else dict(file="results.json", pointer=f"/records/{index}"),
                        policy, audit=False, declared_repeats=manifest.get("repeats"))
                for index, row in enumerate(rows)
            ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise IntegrityError(str(exc)) from exc

    groups = {group: _group_summary([case for case in cases if case["group"] == group], planned)
              for group, planned in counts.items()}
    planned = None if None in counts.values() else sum(counts.values())
    coverage = _group_summary(cases, planned)
    partial = any(group["missing"] for group in groups.values())
    completeness = "partial" if partial else ("unknown" if planned is None else "complete")
    status = "passed" if completeness == "complete" and all(case["category"] == "passed" for case in cases) else "review"
    report = dict(schema=SCHEMA, package_id=package_id, package_type=kind, source_schema=descriptor["source_schema"],
                  campaign_id=descriptor.get("campaign_id"), policy=policy,
                  policy_digest=_sha(archive._canonical(policy)), integrity="verified", completeness=completeness,
                  status=status, coverage=coverage, groups=groups, cases=cases)
    if compare:
        try:
            return comparison.compare(report, descriptor, manifest, plan, results)
        except (ValueError, OverflowError, RecursionError) as exc:
            raise IntegrityError(str(exc)) from exc
    return report


def _publish(root: Path, archive_root: Path, report: dict) -> tuple[Path, bool]:
    # The caller controls the output root. Path keys are computed or verified here.
    output = archive._separate_archive(root, archive._directory(archive_root))
    parent = output / report["package_id"]
    if report["schema"] == comparison.SCHEMA:
        parent = parent / "comparison"
        name, key = "comparison.json", report["report_key"]
    else:
        name, key = "quality.json", report["policy_digest"]
    parent = archive._directory(parent, create=True)
    destination = parent / key
    data = archive._canonical(report) + b"\n"
    with TemporaryDirectory(dir=parent, prefix=".quality-") as temporary:
        staging = Path(temporary) / "report"
        staging.mkdir()
        with (staging / name).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not os.path.lexists(destination):
            try:
                staging.rename(destination)
                return destination / name, True
            except OSError:
                if not os.path.lexists(destination):
                    raise
    result = archive._directory(destination) / name
    if (not stat.S_ISREG(archive._stat(result).st_mode) or result.read_bytes() != data):
        raise ValueError("existing evaluation differs for this package and policy")
    return result, False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--min-repeats", type=int, default=2)
    parser.add_argument("--comparison", choices=[comparison.PROFILE["id"]], help="enable the frozen comparison profile")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.archive_root, args.package_id, min_repeats=args.min_repeats,
                          compare=args.comparison is not None)
        path, created = _publish(args.output_root, args.archive_root, report)
    except IntegrityError as exc:
        print(archive._canonical(dict(status="integrity_error", error=str(exc))).decode("ascii"), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(archive._canonical(dict(status="publication_error", error=str(exc))).decode("ascii"), file=sys.stderr)
        return 3
    details = (("profile_digest", "report_key", "quality", "source_reasons") if args.comparison
               else ("policy_digest", "completeness"))
    result = {key: report[key] for key in ("package_id", "status", "coverage", *details)}
    print(archive._canonical(dict(result, path=str(path), created=created)).decode("ascii"))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
