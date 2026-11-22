"""Durable campaign invariants, including real cross-process crash/recovery."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("campaign_v1", ROOT / "scripts/campaign_v1.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


# === SECTION: small real manifests and fake storage-only outcomes ===
@pytest.fixture
def manifest_path(tmp_path):
    manifest = json.loads((ROOT / "docs/experiments/d5_3b/manifest.json").read_text(encoding="utf-8"))
    manifest.update(fixtures=[dict(id="demo", path="tests/fixtures/battles/demo_skirmish.yaml")],
                    policies=["priority"], battle_seeds=[11], swaps=[False, True],
                    initiatives=[0], strategy_pairs=[["grid", "grid"]])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def initialized(tmp_path, manifest_path, name="campaign"):
    directory = tmp_path / name
    directory.mkdir()
    with campaign.locked(directory):
        campaign.initialize(directory, manifest_path)
    return directory


def row(case, status="complete", reproducible=True):
    return dict(case=case, result=dict(status=status, winner=0, replay_equal=True),
                reproducible=reproducible, timings=[dict(total_ms=2, deployment_ms=1)])


def content(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*")
            if p.is_file() and p.name != ".lock"}


def deterministic_rows(directory):
    rows = campaign.inspect(directory)[2]
    return [{k: v for k, v in row.items() if k != "timings"} for row in rows]


def cli(*args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/campaign_v1.py"),
                           *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", timeout=30)


def test_real_full_split_resume_parity_and_noop(tmp_path, manifest_path, monkeypatch):
    full = initialized(tmp_path, manifest_path, "full")
    split = initialized(tmp_path, manifest_path, "split")
    with campaign.locked(full):
        assert campaign.run(full, 2)[0] == 0
    with campaign.locked(split):
        code, partial = campaign.run(split, 1)
        assert code == 2 and partial["total"] == 1
        assert campaign.run(split, 1)[0] == 0
    assert deterministic_rows(full) == deterministic_rows(split)
    snapshot = content(split)
    monkeypatch.setattr(campaign.experiment, "run_case", lambda *args: pytest.fail("no-op simulated"))
    with campaign.locked(split):
        code, result = campaign.run(split, 1)
    assert code == 0 and result["committed"] == 0
    assert content(split) == snapshot


def test_adapter_delegates_unchanged_case_and_manifest(tmp_path, manifest_path, monkeypatch):
    directory = initialized(tmp_path, manifest_path)
    manifest = campaign.load_manifest(manifest_path)
    expected = next(campaign.experiment.iter_cases(manifest))
    calls = []
    def invoke(case, supplied):
        calls.append((case, supplied))
        return row(case)
    monkeypatch.setattr(campaign.experiment, "run_case", invoke)
    campaign.run(directory, 1)
    assert calls == [(expected, manifest)]
    assert campaign.inspect(directory)[2][0] == row(expected)


def test_report_rebuilds_from_journal_without_simulation(tmp_path, manifest_path, monkeypatch):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 1)
    original = (directory / "report.md").read_bytes()
    (directory / "report.md").unlink()
    (directory / "checksums.json").unlink()
    monkeypatch.setattr(campaign.experiment, "run_case", lambda *args: pytest.fail("report simulated"))
    header, manifest, rows, *_ = campaign.inspect(directory)
    summary = campaign.rebuild(directory, header, manifest, rows)
    assert summary["cases"] == 1 and summary["planned"] == 2
    assert (directory / "report.md").read_bytes() == original
    for name, digest in campaign.json_read(directory / "checksums.json").items():
        assert campaign.sha((directory / name).read_bytes()) == digest


def test_derived_corruption_is_detected_and_report_repair_is_explicit(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 1)
    (directory / "report.md").write_text("corrupt report", encoding="utf-8")
    assert cli("verify", "--directory", directory).returncode == 1
    assert cli("report", "--directory", directory).returncode == 0
    assert cli("verify", "--directory", directory).returncode == 0
    assert "corrupt report" not in (directory / "report.md").read_text(encoding="utf-8")


def test_crashed_derived_temporary_is_preserved_but_not_archived(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 1)
    temporary = directory / (".report.md." + "a" * 32 + ".tmp")
    temporary.write_bytes(b"incomplete report")
    assert campaign.run(directory, 1)[0] == 0
    destination = tmp_path / "archive"
    campaign.archive(directory, destination)
    assert temporary.read_bytes() == b"incomplete report"
    assert not (destination / temporary.name).exists()
    assert cli("verify", "--directory", destination).returncode == 0


# === SECTION: corruption, compatibility and manifest boundaries ===
def test_partial_tail_requires_explicit_repair_and_retains_committed_prefix(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 1)
    journal = directory / "journal.jsonl"
    committed = journal.read_bytes()
    partial = b'{"schema":"interrupted'
    with journal.open("ab") as stream:
        stream.write(partial)
    with pytest.raises(campaign.CampaignError, match="incomplete journal tail"):
        campaign.run(directory, 1)
    assert journal.read_bytes() == committed + partial
    result = campaign.repair_tail(directory)
    assert Path(result["backup"]).read_bytes() == partial
    assert journal.read_bytes() == committed
    assert campaign.run(directory, 1)[0] == 0
    assert not campaign.repair_tail(directory)["repaired"]


def test_committed_corruption_cannot_be_repaired_as_a_tail(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 2)
    journal = directory / "journal.jsonl"
    data = journal.read_bytes().replace(b'"winner":0', b'"winner":1', 1)
    # A mutation is guaranteed even if this real fixture winner was not zero.
    if data == journal.read_bytes():
        data = data.replace(b'"index":0', b'"index":1', 1)
    journal.write_bytes(data + b"partial")
    with pytest.raises(campaign.CampaignError, match="corrupt committed"):
        campaign.repair_tail(directory)
    assert journal.read_bytes() == data + b"partial"


@pytest.mark.parametrize("mutation", ["duplicate", "index", "previous", "status"])
def test_resigned_invalid_record_is_rejected(tmp_path, manifest_path, mutation):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 2)
    journal = directory / "journal.jsonl"
    envelopes = [json.loads(line) for line in journal.read_bytes().splitlines()]
    last = envelopes[1]
    if mutation == "duplicate":last["row"]["case"] = envelopes[0]["row"]["case"]
    elif mutation == "index":last["index"] = 0
    elif mutation == "previous":last["previous"] = "wrong"
    else:last["row"]["result"]["status"] = "unknown"
    last.pop("sha256")
    last["sha256"] = campaign.sha(campaign.canonical(last))
    journal.write_bytes(b"".join(campaign.canonical(e) + b"\n" for e in envelopes))
    with pytest.raises(campaign.CampaignError, match="corrupt committed"):
        campaign.inspect(directory)


def test_manifest_and_frozen_fixture_integrity(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    path = directory / "manifest.json"
    original = path.read_bytes()
    changed = campaign.json_read(path)
    changed["battle_seeds"] = [42]
    path.write_bytes(campaign.canonical(changed))
    with pytest.raises(campaign.CampaignError, match="manifest integrity"):
        campaign.run(directory, 1)
    path.write_bytes(original)
    header = campaign.inspect(directory)[0]
    frozen = directory / next(iter(header["inputs"]))
    frozen.write_bytes(frozen.read_bytes() + b"\n")
    with pytest.raises(campaign.CampaignError, match="frozen input integrity"):
        campaign.inspect(directory)


def test_source_dependency_change_rejected_before_execution(tmp_path, manifest_path, monkeypatch):
    directory = initialized(tmp_path, manifest_path)
    original = campaign.compatibility(campaign.load_manifest(manifest_path))
    changed = deepcopy(original)
    changed["sources"]["scripts/campaign_v1.py"] = "modified"
    monkeypatch.setattr(campaign, "compatibility", lambda m: changed)
    monkeypatch.setattr(campaign.experiment, "run_case", lambda *a: pytest.fail("incompatible execution"))
    with pytest.raises(campaign.CampaignError, match="compatibility conflict"):
        campaign.run(directory, 1)
    assert (directory / "journal.jsonl").read_bytes() == b""


@pytest.mark.parametrize("field,value", [
    ("battle_seeds", [11, 11]), ("max_activations", 2001), ("repeats", 1),
    ("fixtures", [dict(id="bad", path="scripts/README.md")]),
    ("fixtures", [dict(id="bad", path="../outside.yaml")]),
    ("fixtures", [dict(id="bad", map="unknown", map_seed=1)]),
])
def test_invalid_or_outside_input_rejected(manifest_path, field, value):
    manifest = campaign.json_read(manifest_path)
    manifest[field] = value
    manifest_path.write_bytes(campaign.canonical(manifest))
    with pytest.raises((ValueError, KeyError)):
        campaign.load_manifest(manifest_path)


@pytest.mark.parametrize("limit", [0, -1, 2049, True])
def test_execution_bound_checked_before_simulation(tmp_path, manifest_path, limit):
    directory = initialized(tmp_path, manifest_path)
    with pytest.raises(campaign.CampaignError, match="max-cases"):
        campaign.run(directory, limit)
    assert not (directory / "journal.jsonl").read_bytes()


def test_start_does_not_overwrite_an_existing_directory(tmp_path, manifest_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    sentinel = directory / "sentinel"
    sentinel.write_bytes(b"preserve")
    result = cli("start", "--directory", directory, "--manifest", manifest_path, "--max-cases", 1)
    assert result.returncode == 1
    assert list(directory.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"preserve"


# === SECTION: failures remain data; archive is a movable stopped snapshot ===
@pytest.mark.parametrize("status", ["deployment_error", "match_error", "activation_cap"])
def test_domain_failure_is_not_a_draw(tmp_path, manifest_path, monkeypatch, status):
    directory = initialized(tmp_path, manifest_path)
    monkeypatch.setattr(campaign.experiment, "run_case", lambda case, m: row(case, status))
    assert campaign.run(directory, 2)[0] == 0
    report = (directory / "report.md").read_text(encoding="utf-8")
    assert status in report and '"cases": 2' in report and '"mixed_outcomes": {}' in report


@pytest.mark.parametrize("failure", ["unstable", "replay", "assertion", "unexpected"])
def test_campaign_failure_committed_once_then_fail_closed(tmp_path, manifest_path, monkeypatch, failure):
    directory = initialized(tmp_path, manifest_path)
    def invoke(case, manifest):
        if failure == "unstable":return row(case, reproducible=False)
        if failure == "replay":raise AssertionError("complete replay differs from live state")
        if failure == "assertion":raise AssertionError("runner returned illegal placement")
        raise RuntimeError("unexpected private detail")
    monkeypatch.setattr(campaign.experiment, "run_case", invoke)
    code, result = campaign.run(directory, 2)
    assert code == 1 and result["committed"] == 1
    records = campaign.inspect(directory)[2]
    assert len(records) == 1
    assert campaign.outcome(records[0]) in campaign.FAILURES
    assert '"campaign_failures": 1' in (directory / "report.md").read_text(encoding="utf-8")
    monkeypatch.setattr(campaign.experiment, "run_case", lambda *args: pytest.fail("failed campaign retried"))
    assert campaign.run(directory, 2)[0] == 1


def test_archive_moves_stopped_campaign_and_never_overwrites(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    campaign.run(directory, 1)
    destination = tmp_path / "snapshot"
    with campaign.locked(directory):
        campaign.archive(directory, destination)
    assert campaign.inspect(destination)[2] == campaign.inspect(directory)[2]
    before = content(destination)
    with pytest.raises(campaign.CampaignError, match="must not exist"):
        campaign.archive(directory, destination)
    assert content(destination) == before
    moved = tmp_path / "another-computer"
    destination.rename(moved)
    result = cli("resume", "--directory", moved, "--max-cases", 2)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(campaign.inspect(moved)[2]) == 2
    assert len(campaign.inspect(directory)[2]) == 1


def test_unknown_or_symlink_files_are_never_archived(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    (directory / "private.txt").write_text("not a campaign artifact", encoding="utf-8")
    with pytest.raises(campaign.CampaignError, match="unexpected campaign file"):
        campaign.archive(directory, tmp_path / "archive")
    assert not (tmp_path / "archive").exists()


# === SECTION: real killed writer, simultaneous writer and clean new process ===
def test_killed_process_releases_lock_and_new_process_resumes(tmp_path, manifest_path):
    directory = initialized(tmp_path, manifest_path)
    marker = tmp_path / "committed.txt"
    program = '''
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/scripts')
import campaign_v1 as c
d=Path(sys.argv[2])
with c.locked(d):
 h,m,rows,previous,_,_=c.inspect(d)
 case=next(c.experiment.iter_cases(m))
 c.append_record(d,c.experiment.run_case(case,m),0,previous)
 Path(sys.argv[3]).write_text('committed',encoding='utf-8')
 time.sleep(60)
'''
    process = subprocess.Popen([sys.executable, "-X", "utf8", "-c", program,
                                str(ROOT), str(directory), str(marker)], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = monotonic() + 15
        while not marker.exists() and process.poll() is None and monotonic() < deadline:
            sleep(0.05)
        assert marker.exists(), "child failed to commit"
        before = (directory / "journal.jsonl").read_bytes()
        blocked = cli("resume", "--directory", directory, "--max-cases", 2)
        assert blocked.returncode == 1 and "campaign busy" in blocked.stdout
        assert (directory / "journal.jsonl").read_bytes() == before
        process.kill()
        process.communicate(timeout=10)
        resumed = cli("resume", "--directory", directory, "--max-cases", 2)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert len(campaign.inspect(directory)[2]) == 2
        assert (directory / "journal.jsonl").read_bytes().startswith(before)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
