"""Exercise comparison and publication against the real D5.3b and D6.1 snapshots."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import deployment_experiment as experiment
from scripts import experiment_archive as archive
from scripts import experiment_comparison as comparison
from scripts import experiment_quality as quality


ROOT = Path(__file__).resolve().parents[1]
D5 = ROOT / "docs/experiments/d5_3b"


@pytest.fixture(scope="module")
def real_archives(tmp_path_factory):
    root = tmp_path_factory.mktemp("comparison_archives")
    deployment, _ = archive.import_history(root, archive.DEPLOYMENT_TYPE, D5)
    audit, _ = archive.import_history(root, archive.BOTS_AUDIT_TYPE, ROOT / "docs/experiments/d6_1",
                                      report=ROOT / "docs/boty-audit.md")
    return root, deployment["package_id"], audit["package_id"]


def modified_archive(tmp_path, mutate):
    source = tmp_path / "source"
    source.mkdir()
    manifest = archive._read_json(D5 / "manifest.json")
    results = archive._read_json(D5 / "results.json")
    mutate(manifest, results)
    results["summary"] = experiment.summarize(results["records"])
    raw = archive._canonical(manifest) + b"\n"
    results["metadata"]["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    (source / "manifest.json").write_bytes(raw)
    (source / "results.json").write_bytes(archive._canonical(results))
    for name in ("README.md", "results.md"):
        (source / name).write_bytes((D5 / name).read_bytes())
    root = tmp_path / "archive"
    descriptor, _ = archive.import_history(root, archive.DEPLOYMENT_TYPE, source)
    return root, descriptor["package_id"]


def test_real_deployment_totals_come_from_complete_blocks(real_archives):
    root, package_id, _ = real_archives
    report = quality.evaluate(root, package_id, compare=True)
    assert report["status"] == "passed"
    assert report["coverage"] == dict(blocks_planned=30, blocks_included=30, blocks_excluded=0,
                                     cases_recorded=480, cases_planned=480, cases_included=480,
                                     cases_excluded=0, cases_missing=0, blocks_by_exclusion={})
    assert all(len(block["case_ids"]) == 16 and block["included"] for block in report["blocks"])
    assert report["totals"] == {
        "controls": {"grid": {"player_0": 58, "player_1": 8, "draw": 54},
                     "objectives": {"player_0": 42, "player_1": 66, "draw": 12}},
        "mixed": {"grid": 30, "objectives": 174, "draw": 36},
        "mixed_by_objectives_side": {"player_0": {"grid": 18, "objectives": 74, "draw": 28},
                                     "player_1": {"grid": 12, "objectives": 100, "draw": 8}},
    }
    assert report["side_effect"]["control_delta_p0_minus_p1"] == {"grid": 50, "objectives": -24}
    assert report["side_effect"]["threshold"] is None
    breakdown = report["breakdown"]
    assert len(breakdown) == 20 and {row["initiative"] for row in breakdown} == {0, 1}
    assert {row["policy"] for row in breakdown} == {"priority", "priority3"}
    assert len({row["fixture"] for row in breakdown}) == 5
    assert {row["cases_included"] for row in breakdown} == {24}
    assert sum(row["mixed"]["objectives"] for row in breakdown) == 174


@pytest.mark.parametrize(("change", "reason", "missing"), [
    (lambda rows: rows.pop(0), "missing_case", 1),
    (lambda rows: rows[0]["result"].update(replay_equal=False), "technical:replay_error", 0),
    (lambda rows: rows[0]["result"].pop("input_digest"), "missing_input_digest", 0),
    (lambda rows: rows[0]["result"].update(input_digest="a" * 64), "initial_state_mismatch", 0),
    (lambda rows: rows[0]["result"].update(input_digest=rows[4]["result"]["input_digest"]),
     "aliased_swap_or_initiative", 0),
])
def test_incomplete_or_unverified_leg_excludes_entire_block(tmp_path, change, reason, missing):
    root, package_id = modified_archive(tmp_path, lambda _, results: change(results["records"]))
    report = quality.evaluate(root, package_id, compare=True)
    assert report["status"] == "review"
    assert report["coverage"]["blocks_by_exclusion"][reason] == 1
    assert report["coverage"]["blocks_excluded"] == 1
    assert report["coverage"]["cases_missing"] == missing
    assert report["coverage"]["cases_excluded"] == 16 - missing
    assert report["coverage"]["cases_included"] == 464
    block, = (block for block in report["blocks"] if not block["included"])
    assert set(block["exclusions"][reason]) <= set(block["case_ids"])
    assert len(block["case_ids"]) == 16
    assert sum(report["totals"]["mixed"].values()) == 232


def test_relabelling_case_identity_without_matching_deployment_is_not_a_pair(tmp_path):
    def relabel(_, results):
        first, second = results["records"][1:3]
        first["case"], second["case"] = second["case"], first["case"]

    root, package_id = modified_archive(tmp_path, relabel)
    assert quality.evaluate(root, package_id)["status"] == "passed"
    report = quality.evaluate(root, package_id, compare=True)
    assert report["coverage"]["blocks_by_exclusion"] == {"armies_or_strategies_unverified": 1}
    assert report["coverage"]["blocks_included"] == 29


def test_side_relabelling_inverts_side_wins_and_preserves_strategy_wins(tmp_path, real_archives):
    original = quality.evaluate(real_archives[0], real_archives[1], compare=True)

    def swap_labels(_, results):
        for row in results["records"]:
            case, match = row["case"], row["result"]
            case.pop("id")
            case.update(swap=not case["swap"], initiative=1 - case["initiative"],
                        strategies=case["strategies"][::-1])
            case["id"] = experiment.digest(case)[:20]
            if match["winner"] is not None:
                match["winner"] = 1 - match["winner"]
            for placement in match["placements"]:
                placement["owner"] = 1 - placement["owner"]

    root, package_id = modified_archive(tmp_path, swap_labels)
    report = quality.evaluate(root, package_id, compare=True)
    assert report["status"] == "passed" and report["coverage"] == original["coverage"]
    previous, relabelled = original["totals"], report["totals"]
    assert previous["mixed"] == relabelled["mixed"]
    assert previous["mixed_by_objectives_side"]["player_0"] == relabelled["mixed_by_objectives_side"]["player_1"]
    for strategy, control in previous["controls"].items():
        assert relabelled["controls"][strategy] == dict(player_0=control["player_1"],
                                                       player_1=control["player_0"], draw=control["draw"])


@pytest.mark.parametrize("change", ["revision", "mechanism", "design"])
def test_incompatible_provenance_excludes_technically_valid_matches(tmp_path, change):
    def alter(manifest, results):
        if change == "revision":
            manifest["base_commit"] = results["metadata"]["base_commit"] = "b" * 40
        elif change == "mechanism":
            results["metadata"]["sources"]["scripts/deployment_experiment.py"] = "a" * 64
        else:
            manifest["max_activations"] -= 1

    root, package_id = modified_archive(tmp_path, alter)
    report = quality.evaluate(root, package_id, compare=True)
    assert report["status"] == "review"
    assert f"incompatible_{change}" in report["source_reasons"]
    assert report["coverage"]["blocks_by_exclusion"][f"incompatible_{change}"] == 30
    assert report["coverage"]["cases_recorded"] == report["coverage"]["cases_excluded"] == 480
    assert report["coverage"]["cases_included"] == 0


def test_d6_1_retains_technical_coverage_without_deployment_comparisons(real_archives):
    root, _, package_id = real_archives
    report = quality.evaluate(root, package_id, compare=True)
    assert report["status"] == "review" and report["source_reasons"] == ["outside_experiment_design"]
    assert report["coverage"]["blocks_planned"] is None
    assert report["coverage"]["cases_planned"] is None
    assert report["coverage"]["cases_recorded"] == report["coverage"]["cases_excluded"] == 239
    assert report["quality"]["coverage"]["categories"]["passed"] == 167
    assert report["blocks"] == [] and report["coverage"]["cases_included"] == 0
    assert report["side_effect"]["control_delta_p0_minus_p1"] == {"grid": None, "objectives": None}


def test_publication_is_isolated_versioned_and_idempotent(real_archives, tmp_path):
    root, package_id, _ = real_archives
    output = tmp_path / "quality"

    def cli(*args, output_root=output):
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(ROOT / "scripts/experiment_quality.py"),
             "--archive-root", str(root), "--package-id", package_id, "--output-root", str(output_root), *args],
            capture_output=True, encoding="utf-8", timeout=45,
        )

    def publish(*args, code=0):
        result = cli(*args)
        assert result.returncode == code, result.stderr
        return json.loads(result.stdout)

    snapshot = root / "packages" / package_id
    original = {file: file.read_bytes() for file in snapshot.rglob("*") if file.is_file()}
    base = Path(publish()["path"])
    technical = base.read_bytes()
    args = ("--comparison", "d5_3b")
    summary = publish(*args)
    assert summary["created"] and summary["quality"]["report_sha256"] == hashlib.sha256(technical).hexdigest()
    profile_digest = hashlib.sha256(archive._canonical(comparison.PROFILE)).hexdigest()
    report_key = hashlib.sha256(archive._canonical(dict(profile_digest=profile_digest,
                                                         policy_digest=base.parent.name))).hexdigest()
    assert summary["profile_digest"] == profile_digest and summary["report_key"] == report_key
    path = Path(summary["path"])
    assert path == output / package_id / "comparison" / report_key / "comparison.json"
    assert json.loads(path.read_bytes()) == quality.evaluate(root, package_id, compare=True)
    report = path.read_bytes()
    assert not publish(*args)["created"] and path.read_bytes() == report
    stricter = publish(*args, "--min-repeats", "3", code=2)
    assert stricter["coverage"]["blocks_by_exclusion"] == {"technical:missing_repeat_evidence": 30}
    assert stricter["path"] != str(path) and base.read_bytes() == technical
    assert cli(*args, output_root=root / "compare").returncode == 3
    path.write_bytes(b"conflict")
    assert cli(*args).returncode == 3 and path.read_bytes() == b"conflict"
    assert all(file.read_bytes() == raw for file, raw in original.items())
