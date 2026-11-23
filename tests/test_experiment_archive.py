"""Exercise publication, crash recovery and offline verification of D7.1 packages."""
import json
import os
from pathlib import Path
from shutil import copyfile
import subprocess
import sys

import pytest

from scripts import campaign_v1 as campaign
from scripts import experiment_archive as archive


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "experiment_archive.py"


@pytest.fixture
def stopped(tmp_path):
    manifest = json.loads((ROOT / "docs/experiments/d7_1/manifest.json").read_text(encoding="utf-8"))
    manifest.update(battle_seeds=[11], initiatives=[0], strategy_pairs=[["grid", "grid"]])
    plan = tmp_path / "manifest.json"
    plan.write_text(json.dumps(manifest), encoding="utf-8")
    source = tmp_path / "campaign"
    source.mkdir()
    with campaign.locked(source):
        campaign.initialize(source, plan)
        code, result = campaign.run(source, 1)
    assert code == 2 and result["total"] == 1 and result["planned"] == 2
    return source, tmp_path / "archive"


def cli(*args, script=CLI, isolated=False):
    flags = ["-I", "-S"] if isolated else []
    return subprocess.run(
        [sys.executable, *flags, "-B", "-X", "utf8", str(script), *map(str, args)],
        cwd=script.parent, capture_output=True, encoding="utf-8", timeout=45,
    )


def published(root, description):
    return root / "packages" / description["package_id"]


# === SECTION: publication, deduplication and file-data verification ===
def test_cli_catalogs_partial_and_full_with_independent_identity(stopped):
    source, root = stopped
    invocation = ("import", "--archive-root", root, "--campaign", source)
    first = cli(*invocation)
    assert first.returncode == 0, first.stdout + first.stderr
    partial = json.loads(first.stdout)["package"]
    assert partial["completeness"] == "partial"
    assert partial["committed_cases"] == 1 and partial["planned_cases"] == 2
    assert partial["scenarios"] == ["demo_skirmish"]
    assert partial["files"]["journal.jsonl"]["size_bytes"] == (source / "journal.jsonl").stat().st_size
    repeat = cli(*invocation)
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert json.loads(repeat.stdout) == {"created": False, "package": partial}
    with campaign.locked(source):
        assert campaign.run(source, 1)[0] == 0
    full, created = archive.import_campaign(root, source)
    assert created and full["completeness"] == "complete"
    assert full["committed_cases"] == full["planned_cases"] == 2
    assert full["campaign_id"] == partial["campaign_id"]
    assert full["package_id"] != partial["package_id"]
    assert archive.verify_package(root, partial["package_id"]) == partial
    assert archive.verify_package(root, full["package_id"]) == full
    selected = cli("list", "--archive-root", root, "--package-id", full["package_id"],
                   "--type", "campaign_v1", "--scenario", "demo_skirmish",
                   "--revision", full["recorded_revision"])
    assert selected.returncode == 0, selected.stdout + selected.stderr
    assert json.loads(selected.stdout)["packages"] == [full]
    assert archive.list_packages(root, kind="other") == []
    assert archive.list_packages(root, scenario="other") == []
    assert archive.list_packages(root, revision="0" * 40) == []

    # The catalog comes from the descriptors, including after transferring the directory.
    before = archive.list_packages(root)
    moved = root.with_name("moved")
    root.rename(moved)
    assert archive.list_packages(moved) == before
    assert len(before) == 2


@pytest.mark.parametrize("damage", ["changed", "missing", "unexpected", "descriptor"])
def test_verify_and_reimport_refuse_corrupt_published_package(stopped, damage):
    source, root = stopped
    description, _ = archive.import_campaign(root, source)
    package = published(root, description)
    journal = package / "snapshot" / "journal.jsonl"
    if damage == "changed":
        data = journal.read_bytes()
        journal.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif damage == "missing":
        journal.unlink()
    elif damage == "unexpected":
        (journal.parent / "extra.txt").write_bytes(b"unexpected")
    else:
        path = package / "package.json"
        path.write_text(json.dumps(dict(description, committed_cases=2)), encoding="utf-8")
    corrupt = {path.relative_to(package): path.read_bytes()
               for path in package.rglob("*") if path.is_file()}
    result = cli("verify", "--archive-root", root, "--package-id", description["package_id"])
    assert result.returncode == 1 and json.loads(result.stdout)["status"] == "error"
    with pytest.raises(archive.ArchiveError):
        archive.import_campaign(root, source)
    assert corrupt == {path.relative_to(package): path.read_bytes()
                       for path in package.rglob("*") if path.is_file()}


def test_verify_in_isolated_copy_after_sources_change(stopped, monkeypatch, tmp_path):
    source, root = stopped
    description, _ = archive.import_campaign(root, source)
    compatibility = campaign.compatibility
    monkeypatch.setattr(campaign, "compatibility", lambda manifest: dict(
        compatibility(manifest), manifest_digest="0" * 64))
    with pytest.raises(campaign.CampaignError, match="compatibility conflict"):
        archive.import_campaign(root, source)

    tool = tmp_path / "tool-only" / "experiment_archive.py"
    tool.parent.mkdir()
    copyfile(CLI, tool)
    verify = cli("verify", "--archive-root", root, "--package-id", description["package_id"],
                 script=tool, isolated=True)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert json.loads(verify.stdout) == dict(verified=True, package=description)
    listing = cli("list", "--archive-root", root, script=tool, isolated=True)
    assert listing.returncode == 0, listing.stdout + listing.stderr
    assert json.loads(listing.stdout)["packages"] == [description]


def test_complete_counts_do_not_certify_simulation_outcome(stopped, monkeypatch):
    source, root = stopped

    def failed(case, _manifest):
        return dict(case=case, result={"status": "activation_cap"}, reproducible=True, timings=[])

    monkeypatch.setattr(campaign.experiment, "run_case", failed)
    with campaign.locked(source):
        assert campaign.run(source, 1)[0] == 0
    entry, _ = archive.import_campaign(root, source)
    assert entry["completeness"] == "complete"
    assert "quality" not in entry
    assert '"activation_cap": 1' in (published(root, entry) / "snapshot" / "report.md").read_text(
        encoding="utf-8")


# === SECTION: process interruption and filesystem boundaries ===
def test_process_interrupted_before_publication_leaves_no_visible_entry(stopped):
    source, root = stopped
    program = """
import os
from pathlib import Path
import sys
from scripts import experiment_archive

def interrupt(staging, _destination):
    assert (staging / "package.json").is_file()
    os._exit(17)

Path.rename = interrupt
experiment_archive.import_campaign(Path(sys.argv[1]), Path(sys.argv[2]))
"""
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", program, str(root), str(source)],
                            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=45)
    assert result.returncode == 17, result.stdout + result.stderr
    assert len(list((root / "packages").glob(".import-*"))) == 1
    assert archive.list_packages(root) == []
    description, created = archive.import_campaign(root, source)
    assert created and archive.list_packages(root) == [description]


def test_import_refuses_a_second_publisher(stopped):
    source, root = stopped
    root.mkdir()
    with campaign.locked(root):
        competing = cli("import", "--archive-root", root, "--campaign", source)
    assert competing.returncode == 1 and "campaign busy" in competing.stdout
    assert not (root / "packages").exists()


def test_import_rejects_unlisted_source_file_and_overlapping_trees(stopped):
    source, root = stopped
    with pytest.raises(archive.ArchiveError, match="separate directory trees"):
        archive.import_campaign(source / "nested", source)
    assert not (source / "nested").exists()
    (source / "extra.txt").write_bytes(b"unlisted")
    with pytest.raises(campaign.CampaignError, match="unexpected campaign file"):
        archive.import_campaign(root, source)
    assert archive.list_packages(root) == []


@pytest.mark.parametrize("path", ["../../outside", "inputs/tests/fixtures/battles/../outside.yaml",
                                  "inputs/tests/fixtures/battles/file.yaml:stream"])
def test_rejects_frozen_paths_not_bound_to_manifest(stopped, path):
    source, root = stopped
    header = source / "header.json"
    data = json.loads(header.read_text(encoding="utf-8"))
    data["inputs"][path] = "0" * 64
    header.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(archive.ArchiveError, match="unexpected frozen input list"):
        archive.import_campaign(root, source)
    assert archive.list_packages(root) == []


def test_verify_rejects_hardlink_and_id_path(stopped, tmp_path):
    source, root = stopped
    description, _ = archive.import_campaign(root, source)
    package = published(root, description)
    report = package / "snapshot" / "report.md"
    outside = tmp_path / "outside.md"
    copyfile(report, outside)
    report.unlink()
    os.link(outside, report)
    with pytest.raises(archive.ArchiveError, match="regular file"):
        archive.verify_package(root, description["package_id"])
    bad_id = cli("verify", "--archive-root", root, "--package-id", "../outside.md")
    assert bad_id.returncode == 1 and "64 lowercase hex" in bad_id.stdout


def test_import_rejects_directory_link(stopped, tmp_path):
    source, root = stopped
    link = tmp_path / "linked-source"
    if os.name == "nt":
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:SZOP_TEST_LINK -Target $env:SZOP_TEST_TARGET"],
            env=dict(os.environ, SZOP_TEST_LINK=str(link), SZOP_TEST_TARGET=str(source)),
            check=True, capture_output=True, timeout=15,
        )
    else:
        link.symlink_to(source, target_is_directory=True)
    with pytest.raises(archive.ArchiveError, match="links and reparse"):
        archive.import_campaign(root, link)
    assert not root.exists()
