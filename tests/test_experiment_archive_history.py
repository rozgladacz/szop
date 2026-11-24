"""Historical evidence stays byte-identical and catalogable after recovery."""
import json
import os
from pathlib import Path
from shutil import copyfile, copytree
import subprocess
import sys

import pytest

from scripts import campaign_v1
from scripts import experiment_archive as archive


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "docs/experiments"
BOTS_REPORT = ROOT / "docs/boty-audit.md"


def run_cli(script, *args):
    return subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(script), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)


def test_real_history_import_deduplicates_and_rebuilds_catalog(tmp_path):
    source_root = tmp_path / "archive"
    script = ROOT / "scripts/experiment_archive.py"
    kinds = (
        (archive.DEPLOYMENT_TYPE, "d5_3b", None, {"deployment": 480}),
        (archive.BOTS_AUDIT_TYPE, "d6_1", BOTS_REPORT,
         {"decision": 162, "deployment": 54, "ending": 9, "fixture": 14}),
    )
    descriptions = {}
    for kind, folder, report, counts in kinds:
        source = EXPERIMENTS / folder
        args = ["import-history", "--archive-root", source_root, "--type", kind, "--experiment", source]
        if report:
            args += ["--report", report]
        imported = json.loads(run_cli(script, *args).stdout)
        description = imported["package"]
        descriptions[kind] = description
        assert imported["created"]
        assert description["case_counts"] == counts
        assert description["timing_samples"] == {key: 2 * count for key, count in counts.items()}
        assert description["evidence"]["kind"] == "historical_results"
        assert description["evidence"]["campaign_journal"] is False
        assert description["evidence"]["manifest_binding"] != "unknown"
        assert description["evidence"]["source_fingerprints"] == "recorded"
        assert description["declared_repeats"] == (None if report else 2)
        snapshot = source_root / "packages" / description["package_id"] / archive.SNAPSHOT
        original = list(source.iterdir()) + ([report] if report else [])
        assert set(description["files"]) == {path.name for path in original}
        assert all((snapshot / path.name).read_bytes() == path.read_bytes() for path in original)
        assert json.loads(run_cli(script, *args).stdout) == {"created": False, "package": description}

    backup = tmp_path / "new-archive"
    copytree(source_root / "packages", backup / "packages")
    # Run with the archive script alone in a different location and no app imports.
    tool = tmp_path / "experiment_archive.py"
    copyfile(script, tool)
    listed = json.loads(run_cli(tool, "list", "--archive-root", backup).stdout)
    assert {item["type"]: item for item in listed["packages"]} == descriptions
    for kind, description in descriptions.items():
        listed = json.loads(run_cli(tool, "list", "--archive-root", backup, "--type", kind,
                                    "--scenario", description["scenarios"][0],
                                    "--revision", description["recorded_revision"]).stdout)
        assert listed["packages"] == [description]
        found = json.loads(run_cli(tool, "verify", "--archive-root", backup,
                                  "--package-id", description["package_id"]).stdout)
        assert found == {"verified": True, "package": description}


def test_missing_metadata_remains_unknown_and_does_not_invent_repetitions(tmp_path):
    source = copytree(EXPERIMENTS / "d5_3b", tmp_path / "source")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.pop("base_commit")
    manifest.pop("repeats")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    results_path = source / "results.json"
    results = json.loads(results_path.read_bytes())
    results.pop("metadata")
    results["records"][0].pop("timings")
    results_path.write_text(json.dumps(results), encoding="utf-8")
    item, _ = archive.import_history(tmp_path / "archive", archive.DEPLOYMENT_TYPE, source)
    assert item["case_counts"] == {"deployment": 480}
    assert item["recorded_revision"] is item["declared_repeats"] is item["timing_samples"]["deployment"] is None
    assert item["evidence"] == {"kind": "historical_results", "campaign_journal": False,
                                "manifest_binding": "unknown", "source_fingerprints": "unknown"}


def test_manifest_checkout_line_endings_are_recognized_and_preserved(tmp_path):
    source = copytree(EXPERIMENTS / "d5_3b", tmp_path / "source")
    manifest = source / "manifest.json"
    lf = manifest.read_bytes().replace(b"\r\n", b"\n")
    manifest.write_bytes(lf)
    root = tmp_path / "archive"
    item, _ = archive.import_history(root, archive.DEPLOYMENT_TYPE, source)
    assert item["evidence"]["manifest_binding"] == "crlf_sha256"
    assert (root / "packages" / item["package_id"] / archive.SNAPSHOT / "manifest.json").read_bytes() == lf
    manifest.write_bytes(lf.replace(b'"version"', b'"other"') + b" ")
    with pytest.raises(archive.ArchiveError, match="manifest SHA-256 mismatch"):
        archive.import_history(root, archive.DEPLOYMENT_TYPE, source)


@pytest.mark.parametrize("damage", ["delete-source-file", "extra-file", "empty-directory", "duplicate-case",
                                   "incorrect-count", "hardlink"])
def test_rejects_incomplete_or_aliased_historical_sources(tmp_path, damage):
    source = copytree(EXPERIMENTS / "d6_1", tmp_path / "source")
    root = tmp_path / "archive"
    if damage == "delete-source-file":
        (source / "transport_probe.json").unlink()
    elif damage == "extra-file":
        (source / "extra.json").write_text("{}", encoding="utf-8")
    elif damage == "empty-directory":
        (source / "extra").mkdir()
    elif damage == "hardlink":
        path = source / "side_analysis.json"
        outside = copyfile(path, tmp_path / path.name)
        path.unlink()
        os.link(outside, path)
    else:
        path = source / "results.json"
        results = json.loads(path.read_bytes())
        if damage == "duplicate-case":
            results["decisions"][0] = results["decisions"][1]
        else:
            results["summary"]["deployment_cases"] = 55
        path.write_text(json.dumps(results), encoding="utf-8")
    with pytest.raises(archive.ArchiveError):
        archive.import_history(root, archive.BOTS_AUDIT_TYPE, source, report=BOTS_REPORT)
    assert not root.exists() or archive.list_packages(root) == []


def test_corrupt_history_backup_fails_verification_and_cannot_be_overwritten(tmp_path):
    root = tmp_path / "archive"
    source = EXPERIMENTS / "d5_3b"
    item, _ = archive.import_history(root, archive.DEPLOYMENT_TYPE, source)
    package_id = item["package_id"]
    changed = root / "packages" / package_id / archive.SNAPSHOT / "results.md"
    changed.write_bytes(b"corrupt")
    with pytest.raises(archive.ArchiveError, match="content or metadata"):
        archive.verify_package(root, package_id)
    with pytest.raises(archive.ArchiveError, match="content or metadata"):
        archive.import_history(root, archive.DEPLOYMENT_TYPE, source)
    assert changed.read_bytes() == b"corrupt"


def test_history_requires_supported_type_and_respects_existing_lock(tmp_path):
    source = EXPERIMENTS / "d5_3b"
    root = tmp_path / "archive"
    with pytest.raises(archive.ArchiveError, match="unsupported historical experiment type"):
        archive.import_history(root, "d7_1", EXPERIMENTS / "d7_1")
    with pytest.raises(archive.ArchiveError, match="file set"):
        archive.import_history(root, archive.DEPLOYMENT_TYPE, EXPERIMENTS / "d7_1")
    with pytest.raises(archive.ArchiveError, match="separate directory trees"):
        archive.import_history(source / "nested-archive", archive.DEPLOYMENT_TYPE, source)
    root.mkdir()
    # Use a separate process to contend for the shared publication lock.
    with campaign_v1.locked(root):
        with pytest.raises(subprocess.CalledProcessError, match="returned non-zero") as failure:
            run_cli(ROOT / "scripts/experiment_archive.py", "import-history", "--archive-root", root,
                    "--type", archive.DEPLOYMENT_TYPE, "--experiment", source)
    assert "campaign busy" in failure.value.stdout
    assert not (root / "packages").exists()
