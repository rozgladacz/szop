"""Assess native snapshots, real historical records and re-signed corrupt inputs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import campaign_v1 as campaign
from scripts import experiment_archive as archive
from scripts import experiment_quality as quality


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/experiments/d7_1/manifest.json"
DIGEST = "b" * 64


def make_campaign(tmp_path, *, limit=32, change=None):
    source = tmp_path / "source"
    source.mkdir()
    with campaign.locked(source):
        header = campaign.initialize(source, MANIFEST)
        manifest = campaign.load_manifest(MANIFEST)
        previous = header["campaign_id"]
        rows = []
        for index, case in enumerate(campaign.experiment.iter_cases(manifest)):
            if index >= limit:
                break
            result = dict(status="complete", winner=None, replay_equal=True, final_digest=DIGEST,
                          event_digest=DIGEST)
            row = dict(case=case, result=result, reproducible=True,
                       timings=[{"deployment_ms": 1.0, "total_ms": 2.0}] * 2)
            if index == 0 and change:
                change(row)
            rows.append(row)
            previous, _ = campaign.append_record(source, row, index, previous)
        campaign.rebuild(source, header, manifest, rows)
    root = tmp_path / "archive"
    descriptor, _ = archive.import_campaign(root, source)
    return root, descriptor


def cli(root, package_id, output, *args):
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(ROOT / "scripts/experiment_quality.py"),
         "--archive-root", str(root), "--package-id", package_id, "--output-root", str(output), *args],
        capture_output=True, encoding="utf-8", timeout=45,
    )


def files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def resign(root, descriptor, *, update_checksums=True):
    package = root / "packages" / descriptor["package_id"]
    snapshot = package / "snapshot"
    if descriptor["type"] == archive.PACKAGE_TYPE:
        if update_checksums:
            checksums = {name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
                         for name in descriptor["files"] if name != "checksums.json"}
            (snapshot / "checksums.json").write_bytes(archive._canonical(checksums))
        current = archive._describe(snapshot, descriptor["committed_cases"], descriptor["planned_cases"])
    else:
        current = archive._describe_history(snapshot, descriptor["type"])
    (package / "package.json").write_bytes(archive._canonical(current))
    package.rename(package.with_name(current["package_id"]))
    assert archive.verify_package(root, current["package_id"]) == current
    return current["package_id"]


def test_offline_reading_matches_native_frozen_plan_and_statuses():
    manifest = campaign.load_manifest(MANIFEST)
    assert quality._deployment_plan(manifest, campaign=True) == list(campaign.experiment.iter_cases(manifest))
    assert quality.CAMPAIGN_FAILURES == campaign.FAILURES
    assert quality.CAMPAIGN_STATUSES == campaign.RESULT_STATUSES
    assert quality.RECORD_SCHEMA == campaign.RECORD_SCHEMA


@pytest.mark.parametrize(("limit", "completeness", "status"), [
    (32, "complete", "passed"), (8, "partial", "review"), (0, "partial", "review"),
])
def test_clean_campaign_counts_prefix_as_planned_cases(tmp_path, limit, completeness, status):
    root, descriptor = make_campaign(tmp_path, limit=limit)
    report = quality.evaluate(root, descriptor["package_id"])
    assert report["campaign_id"] == descriptor["campaign_id"]
    assert report["integrity"] == "verified" and report["completeness"] == completeness
    assert report["status"] == status
    assert report["coverage"] == dict(planned=32, recorded=limit, missing=32 - limit,
                                      categories={"passed": limit} if limit else {},
                                      reasons={}, outcomes={"draw": limit} if limit else {})
    if limit:
        assert report["cases"][0]["evidence"] == {"file": "journal.jsonl", "line": 1, "pointer": "/row"}
        assert report["cases"][0]["repeat_samples"] == 2


@pytest.mark.parametrize("status", ["deployment_error", "match_error", "activation_cap"])
def test_complete_domain_failure_is_recorded_but_not_a_draw(tmp_path, status):
    def change(row):
        row["result"] = dict(status=status, error="experiment failure")

    root, descriptor = make_campaign(tmp_path, change=change)
    report = quality.evaluate(root, descriptor["package_id"])
    assert report["status"] == "review" and report["completeness"] == "complete"
    assert report["coverage"]["recorded"] == 32
    assert report["coverage"]["categories"] == {status: 1, "passed": 31}
    assert report["coverage"]["outcomes"] == {"draw": 31}
    assert report["cases"][0]["reasons"] == [status, "missing_replay_evidence"]
    assert report["cases"][0]["outcome"] is None


@pytest.mark.parametrize(("changes", "result", "reasons"), [
    ({}, {"replay_equal": None}, ["missing_replay_evidence"]),
    ({}, {"final_digest": None}, ["missing_replay_evidence"]),
    ({}, {"replay_equal": False}, ["replay_error"]),
    ({}, {"status": "replay_error", "replay_equal": None}, ["replay_error"]),
    ({"timings": []}, {}, ["missing_repeat_evidence"]),
    ({"reproducible": False}, {}, ["non_reproducible"]),
    ({"reproducible": False, "timings": []}, {"replay_equal": False},
     ["non_reproducible", "replay_error", "missing_repeat_evidence"]),
])
def test_repeat_failure_replay_failure_and_absence_are_distinct(tmp_path, changes, result, reasons):
    def change(row):
        row.update(changes)
        row["result"].update(result)

    root, descriptor = make_campaign(tmp_path, limit=1, change=change)
    report = quality.evaluate(root, descriptor["package_id"])
    case = report["cases"][0]
    assert case["reasons"] == reasons
    assert report["coverage"]["categories"] == {reasons[0]: 1}
    assert report["coverage"]["reasons"] == dict.fromkeys(reasons, 1)
    assert case["outcome"] is None


@pytest.mark.parametrize("damage", ["hash", "chain", "duplicate", "schema", "summary", "checksums", "descriptor"])
def test_cannot_pass_with_corrupt_rehashed_snapshot(tmp_path, damage):
    root, descriptor = make_campaign(tmp_path, limit=2)
    package_id = descriptor["package_id"]
    snapshot = root / "packages" / package_id / "snapshot"
    journal = snapshot / "journal.jsonl"
    if damage in ("chain", "duplicate", "schema"):
        lines = journal.read_bytes().splitlines()
        first, record = map(archive._json_object, lines)
        if damage == "chain":
            record["previous"] = DIGEST
        elif damage == "duplicate":
            record["row"]["case"] = first["row"]["case"]
        else:
            record["schema"] = "szop.campaign.record/v2"
        record.pop("sha256")
        record["sha256"] = campaign.sha(campaign.canonical(record))
        journal.write_bytes(lines[0] + b"\n" + archive._canonical(record) + b"\n")
    elif damage == "summary":
        report = snapshot / "report.md"
        report.write_bytes(report.read_bytes().replace(b'"cases": 2', b'"cases": 3'))
    elif damage == "checksums":
        (snapshot / "checksums.json").write_bytes(b"{}")
    elif damage == "descriptor":
        descriptor["committed_cases"] = 3
    else:
        journal.write_bytes(journal.read_bytes() + b"corrupt")
    if damage != "hash":
        package_id = resign(root, descriptor, update_checksums=damage != "checksums")

    output = tmp_path / "quality"
    invocation = cli(root, package_id, output)
    assert invocation.returncode == 1, invocation.stderr
    assert json.loads(invocation.stderr)["status"] == "integrity_error"
    assert not output.exists() and not invocation.stdout


def test_reports_are_bound_to_verified_package_and_policy_and_never_overwritten(tmp_path):
    root, descriptor = make_campaign(tmp_path)
    package_id = descriptor["package_id"]
    original_archive = files(root)
    output = tmp_path / "quality"
    first = cli(root, package_id, output)
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    path = Path(summary["path"])
    original = path.read_bytes()
    report = json.loads(original)
    assert report["schema"] == quality.SCHEMA and report["package_id"] == package_id
    assert report["policy_digest"] == hashlib.sha256(archive._canonical(report["policy"])).hexdigest()
    assert path == output / package_id / report["policy_digest"] / "quality.json"

    repeat = cli(root, package_id, output)
    assert repeat.returncode == 0 and not json.loads(repeat.stdout)["created"]
    assert path.read_bytes() == original
    stricter = cli(root, package_id, output, "--min-repeats", "3")
    assert stricter.returncode == 2, stricter.stderr
    updated = json.loads(stricter.stdout)
    assert updated["coverage"]["categories"] == {"missing_repeat_evidence": 32}
    assert updated["package_id"] == package_id and updated["policy_digest"] != report["policy_digest"]
    assert Path(updated["path"]).is_file() and path.read_bytes() == original

    path.write_bytes(b"changed")
    conflict = cli(root, package_id, output)
    assert conflict.returncode == 3 and path.read_bytes() == b"changed"
    assert cli(root, package_id, root / "quality").returncode == 3
    assert files(root) == original_archive


@pytest.fixture(scope="module")
def historical_archives(tmp_path_factory):
    root = tmp_path_factory.mktemp("quality_history")
    descriptors = {}
    for kind, folder, report in [(archive.DEPLOYMENT_TYPE, "d5_3b", None),
                                 (archive.BOTS_AUDIT_TYPE, "d6_1", ROOT / "docs/boty-audit.md")]:
        descriptors[kind], _ = archive.import_history(root, kind, ROOT / "docs/experiments" / folder, report=report)
    return root, descriptors


def test_real_d5_3b_complete_pairs_are_recorded_without_counting_repeats(historical_archives):
    root, descriptors = historical_archives
    report = quality.evaluate(root, descriptors[archive.DEPLOYMENT_TYPE]["package_id"])
    assert report["status"] == "passed"
    assert report["coverage"]["recorded"] == report["coverage"]["planned"] == 480
    assert report["coverage"]["categories"] == {"passed": 480}
    assert report["cases"][0]["evidence"] == {"file": "results.json", "pointer": "/records/0"}
    assert report["cases"][0]["replay"] == {"scope": "match", "status": "passed"}


def test_real_d6_1_distinguishes_probe_scopes_and_keeps_unknown_plan(historical_archives):
    root, descriptors = historical_archives
    report = quality.evaluate(root, descriptors[archive.BOTS_AUDIT_TYPE]["package_id"])
    assert report["status"] == "review" and report["completeness"] == "unknown"
    coverage = report["coverage"]
    assert coverage["recorded"] == 239 and coverage["planned"] is None and coverage["missing"] is None
    assert coverage["categories"] == {"passed": 167, "decision_rejected": 14, "missing_replay_evidence": 58}
    assert coverage["reasons"]["missing_replay_evidence"] == 72
    assert {group: count["planned"] for group, count in report["groups"].items()} == {
        "decision": 162, "deployment": 54, "ending": 9, "fixture": None,
    }
    assert report["groups"]["deployment"]["categories"] == {"missing_replay_evidence": 54}
    assert report["groups"]["ending"]["outcomes"] == {}
    first = report["cases"][0]
    assert first["recorded_status"] == "resolver_accepted" and first["category"] == "passed"
    assert first["replay"] == {"scope": "activation", "status": "passed"}
    assert first["outcome"] is None


@pytest.mark.parametrize(("kind", "summary_key"), [
    (archive.DEPLOYMENT_TYPE, "complete_mixed"),
    (archive.BOTS_AUDIT_TYPE, "non_reproducible"),
])
def test_historical_aggregate_disagreement_survives_archive_verify(historical_archives, tmp_path, kind, summary_key):
    root, descriptors = historical_archives
    descriptor = deepcopy(descriptors[kind])
    source = root / "packages" / descriptor["package_id"]
    package = tmp_path / "packages" / descriptor["package_id"]
    for relative, contents in files(source).items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    path = package / "snapshot" / "results.json"
    results = archive._read_json(path)
    results["summary"][summary_key] += 1
    path.write_bytes(archive._canonical(results))
    package_id = resign(tmp_path, descriptor)
    with pytest.raises(quality.IntegrityError, match="aggregate disagrees"):
        quality.evaluate(tmp_path, package_id)
