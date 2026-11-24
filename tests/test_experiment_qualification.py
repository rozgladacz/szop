"""Qualification depends on validated observations, never on an applied action alone."""

from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree

import pytest

from scripts import bots_audit, campaign_v1, experiment_archive as archive
from scripts import experiment_qualification as qualification
from scripts import experiment_quality as quality
from scripts import export_decisions as export


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/experiments/d6_1"


@pytest.fixture(scope="module")
def campaign_package(tmp_path_factory):
    root = tmp_path_factory.mktemp("qualification")
    manifest = json.loads((ROOT / "docs/experiments/d7_1/manifest.json").read_bytes())
    manifest.update(battle_seeds=[11], initiatives=[0], strategy_pairs=[["grid", "objectives"]])
    source = root / "manifest.json"
    source.write_bytes(archive._canonical(manifest))
    directory = root / "campaign"
    directory.mkdir()
    with campaign_v1.locked(directory):
        campaign_v1.initialize(directory, source, decision_trace="qualification-test")
        assert campaign_v1.run(directory, 2)[0] == 0
    archived = root / "archive"
    descriptor, _ = archive.import_campaign(archived, directory)
    return archived, descriptor["package_id"], root / "reports"


def test_qualified_campaign_replay_groups_repeats_and_side_swaps(campaign_package):
    root, package_id, output = campaign_package
    result = quality.evaluate_qualification(root, [package_id, package_id])
    assert result["coverage"]["cases"] == {"qualified": 2}
    assert result["coverage"]["observations"]["qualified"] == 32
    assert result["coverage"]["observation_exclusions"]["outside_verified_scope"] > 0
    assert result["coverage"]["observation_exclusions"]["automatic_transition"] > 0
    assert result["partition"]["unique_samples"] < 32
    assert result["partition"]["shared_groups"] == result["partition"]["shared_samples"] == 0
    assert len({case["partition_group"] for case in result["cases"]}) == 1
    assert len({case["split"] for case in result["cases"]}) == 1
    for case in result["cases"]:
        assert [e["repeat"] for e in case["executions"]] == [1, 2]
        for evidence in case["executions"]:
            assert evidence["replay"] == "verified"
            accepted = [obs for obs in evidence["observations"] if obs["eligibility"] == "qualified"]
            assert all(obs["kind"] == "choose_deployment" and obs["rules_status"] == "confirmed"
                       and obs["evidence_range"] for obs in accepted)
    report, created = quality._publish(output, root, result)
    assert created
    again = quality.evaluate_qualification(root, [package_id])
    assert quality._publish(output, root, again) == (report, False)
    assert report.read_bytes() == archive._canonical(result) + b"\n"
    with pytest.raises(archive.ArchiveError, match="separate directory trees"):
        quality._publish(root / "reports", root, result)


def test_case_with_replay_failure_in_one_repeat_cannot_supply_a_sample(campaign_package, monkeypatch):
    root, package_id, _ = campaign_package
    original = export.verify_package

    def fail_second_repeat(directory, *, expand=False):
        if directory.name == "2":
            raise export.ExportError("false recorded state reference")
        return original(directory, expand=expand)

    monkeypatch.setattr(export, "verify_package", fail_second_repeat)
    report = quality.evaluate_qualification(root, [package_id])
    assert report["status"] == "review"
    assert report["coverage"]["case_exclusions"] == {"trace_replay_failed": 2}
    assert report["partition"]["unique_samples"] == 0
    assert all(not e["observations"] for case in report["cases"] for e in case["executions"])


def test_replay_is_bound_to_archived_descriptor_and_committed_input(campaign_package):
    root, package_id, _ = campaign_package
    technical, _, _, _, _, journal = quality._evaluate(root, package_id, min_repeats=2)
    assessed = technical["cases"][0]
    snapshot = root / "packages" / package_id / archive.SNAPSHOT
    variants = qualification._source_variants()
    entry = assessed["decision_trace"][0]
    result = journal[0]["result"]
    for candidate, candidate_result in ((dict(entry, descriptor_sha256="0" * 64), result),
                                        (entry, dict(result, input_digest="0" * 64))):
        verified = qualification._execution(export, snapshot, candidate_result, candidate, variants)
        assert verified["replay"] == "failed"
        assert verified["observations"] == []


@pytest.mark.parametrize("outcome,reason", [("none", "no_choice"), ("rejected", "decision_rejected"),
                                            ("error", "decision_error")])
def test_unperformed_decisions_have_explicit_exclusions(outcome, reason):
    row = dict(index=1, kind="continue_activation", outcome=outcome, choice=None, reason="fixture")
    assessed = qualification._observation({"observation": row}, True)
    assert assessed["eligibility"] == "excluded"
    assert assessed["rules_status"] == "unverified"
    assert assessed["reason"] == reason and assessed["observation_reason"] == "fixture"


def test_unsupported_context_and_placement_without_effect():
    row = dict(index=1, kind="choose_deployment", outcome="accepted", choice=[1, 2], events=None)
    item = {"observation": row, "events": []}
    assert qualification._observation(item, True)["reason"] == "placement_not_executed"
    item = {"observation": dict(row, events=[0, 1]), "events": [{}]}
    assert qualification._observation(item, False)["reason"] == "unsupported_deployment_context"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_archive_observations_bind_audited_rule_violations(tmp_path, newline):
    audit = tmp_path / "source"
    copytree(AUDIT, audit)
    results = audit / "results.json"
    raw = results.read_text(encoding="utf-8")
    results.write_text(raw, encoding="utf-8", newline=newline)
    archive_root = tmp_path / "audit"
    descriptor, _ = archive.import_history(archive_root, archive.BOTS_AUDIT_TYPE, audit,
                                           report=ROOT / "docs/boty-audit.md")
    report = quality.evaluate_qualification(archive_root, [descriptor["package_id"]])
    assert report["status"] == "review"
    assert report["coverage"]["cases"] == {"excluded": 239}
    assert report["coverage"]["rules_status"] == {"unverified": 236, "violation": 3}
    extras = {row["evidence"]["pointer"]: row for row in report["cases"] if row["rules_status"] == "violation"}
    audited = json.loads(raw)["decisions"]
    expected_types = {"14.c.iv": "shoot", "22.a.i": "shoot", "22.b.i": "maneuver"}
    for pointer, assessed in extras.items():
        row = audited[int(pointer.rsplit("/", 1)[1])]
        reproduced = bots_audit.deterministic(bots_audit.decision_once(row["kind"], row["seed"], row["scenario"]))
        assert reproduced["first"] == row["result"]["first"]
        assert reproduced["first"]["action_type"] == expected_types[assessed["rule"]]
        assert reproduced["resolver_accepted"] and reproduced["replay_equal"]
        assert reproduced["first"] in reproduced["applied"]
        assert assessed["eligibility"] == "excluded"


def test_partition_merges_families_with_matching_inputs_transitively():
    def qualified(family, *inputs):
        return dict(map_family=["fixture", family], eligibility="qualified",
                    executions=[{"observations": [
                        dict(input_sha256=value, sample_sha256=f"{value}-label", eligibility="qualified")
                        for value in inputs]}])

    candidates = [qualified("a", "shared-ab"), qualified("b", "shared-ab", "shared-bc"),
                  qualified("c", "shared-bc"), qualified("d", "unique")]
    reversed_cases = deepcopy(candidates[::-1])
    assigned = qualification._partition(candidates)
    assert len({case["partition_group"] for case in candidates[:3]}) == 1
    assert candidates[3]["partition_group"] != candidates[0]["partition_group"]
    assert qualification._partition(reversed_cases) == assigned
    assert assigned["unique_samples"] == 3
    assert assigned["shared_groups"] == assigned["shared_samples"] == 0
