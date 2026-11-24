"""Decision evidence must survive replay independently of the collecting process."""
import json
from pathlib import Path

import pytest

from app.services.engine.actions import ManeuverAction
from app.services.engine.geometry import Position
from scripts import export_decisions as export


MANIFEST = Path("docs/experiments/d7_1/manifest.json")
CASE = "762b987db7935fad6f8e"
SWAP_CASE = "28256c014c9a157731df"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write(path, value):
    path.write_bytes(export.campaign.canonical(value) + b"\n")


def _replace_package_rows(directory, filename, rows):
    file = directory / filename
    file.write_bytes(b"".join(export.campaign.canonical(row) + b"\n" for row in rows))
    descriptor = _json(directory / "export.json")
    descriptor["files"][filename] = export.campaign.sha(file.read_bytes())
    _write(directory / "export.json", descriptor)


@pytest.fixture
def package(tmp_path):
    directory = tmp_path / "export"
    created = export.export_case(MANIFEST, CASE, 1, "unit-tests", directory)
    return directory, created


def test_real_full_case_expands_actual_choice_and_effect(package):
    directory, original = package
    meta, expanded = export.verify_package(directory, expand=True)
    assert meta == original
    assert meta["status"] == "complete"
    assert meta["replay"] == {"status": "verified"}
    assert meta["case"]["id"] == CASE and meta["repeat"] == 1
    assert meta["origin"]["kind"] == "manifest_resimulation"
    assert meta["seeds"] == {"battle": 11, "policy_by_player": [11, 1_000_014], "map": None}
    assert len(expanded) == meta["counts"]["observations"]
    assert expanded[0]["run_id"] == meta["run_id"]
    assert expanded[0]["case_id"] == CASE
    assert expanded[0]["observation"]["index"] == 1
    assert expanded[0]["events"][0]["sequence"] == 1
    assert expanded[0]["observation"]["placement_index"] == 1
    assert expanded[0]["states"]["after"] != expanded[0]["states"]["seen"]
    assert _rows(directory / "deployment.jsonl")[0]["sequence"] == 1
    assert _rows(directory / "battle.jsonl")[0]["sequence"] == 1
    assert expanded[-1]["observation"]["kind"] == "round_ended"

    start = next(i for i, row in enumerate(expanded) if row["observation"]["kind"] == "activation_started")
    first, followup, stop, finalize = expanded[start + 1:start + 5]
    assert first["observation"]["kind"] == "choose_action"
    assert followup["observation"]["kind"] == "continue_activation"
    assert first["states"]["seen"] == expanded[start]["states"]["before"]
    assert first["states"]["before"] == expanded[start]["states"]["after"]
    assert first["states"]["seen"] != first["states"]["before"]
    assert followup["states"]["seen"] == followup["states"]["before"] == first["states"]["after"]
    assert all(first["events"]) and all(followup["events"])
    assert first["events"][-1]["sequence"] + 1 == followup["events"][0]["sequence"]
    assert followup["observation"]["prior_actions"] == [first["observation"]["choice"]]
    assert stop["observation"]["kind"] == "activation_stopped" and not stop["events"]
    assert finalize["observation"]["kind"] == "activation_finished"
    original_tail = _rows(directory / "battle.jsonl")
    expanded_tail = [event for row in expanded[start:] for event in row["events"]]
    assert export.campaign.canonical(expanded_tail) == export.campaign.canonical(original_tail)
    assert export.campaign.sha(export.campaign.canonical(expanded[-1]["states"]["after"])) == meta["result"]["final_digest"]


def test_repeat_and_new_run_labels_preserve_stable_payload(tmp_path, monkeypatch):
    seen_seeds = []
    make_player = export.experiment.make_player

    def remember_seed(kind, seed):
        seen_seeds.append(seed)
        return make_player(kind, seed)

    monkeypatch.setattr(export.experiment, "make_player", remember_seed)
    directories = [tmp_path / label for label in ("first", "second", "third")]
    first, second, third = [
        export.export_case(MANIFEST, SWAP_CASE, repeat, label, path)
        for repeat, label, path in zip((1, 2, 1), ("test-a", "test-a", "test-b"), directories, strict=True)
    ]
    assert first["run_id"] == second["run_id"] != third["run_id"]
    assert first["campaign_id"] == second["campaign_id"] == third["campaign_id"]
    assert first["repeat"] == third["repeat"] == 1 and second["repeat"] == 2
    assert first["files"] == second["files"] == third["files"]
    assert first["seeds"]["policy_by_player"] == [1_000_022, 19]
    assert seen_seeds == first["seeds"]["policy_by_player"] * 3
    with pytest.raises(export.ExportError, match="already exists"):
        export.export_case(MANIFEST, SWAP_CASE, 1, "test-a", directories[0])


@pytest.mark.parametrize("outcome", ["none", "rejected"])
def test_followup_without_effect_keeps_verified_prefix(tmp_path, monkeypatch, outcome):
    manifest = _json(MANIFEST)
    manifest["max_activations"] = 1
    path = tmp_path / "manifest.json"
    _write(path, manifest)
    make_player = export.experiment.make_player

    def patched_player(kind, seed):
        player = make_player(kind, seed)
        player.continue_activation = lambda state, perspective, unit, prior: (
            ManeuverAction(unit, Position(1000, 0)) if outcome == "rejected" else None
        )
        return player

    monkeypatch.setattr(export.experiment, "make_player", patched_player)
    directory = tmp_path / "prefix"
    created = export.export_case(path, CASE, 1, "followup", directory)
    meta, records = export.verify_package(directory, expand=True)
    assert meta == created
    assert meta["result"] is None
    assert meta["replay"] == {"status": "prefix_only"}
    assert meta["runner_status"] == "activation_cap"
    followup = next(item for item in records if item["observation"]["kind"] == "continue_activation")
    assert followup["observation"]["outcome"] == outcome
    assert followup["observation"]["reason"] == ("maneuver_over_budget" if outcome == "rejected" else None)
    assert followup["observation"]["events"] is None and not followup["events"]
    assert followup["states"]["seen"] is not None
    assert followup["states"]["before"] is None and followup["states"]["after"] is None
    assert export.main(["verify", str(directory)]) == 2


def test_deployment_working_snapshots_survive_later_rejection(tmp_path, monkeypatch):
    calls = 0
    choice = export.experiment.match.objective_deployment_choice

    def fail_second(state, unit_id, zone, *, assignments):
        nonlocal calls
        calls += 1
        return (Position(1000, 0), None) if calls == 2 else choice(
            state, unit_id, zone, assignments=assignments,
        )

    monkeypatch.setattr(export.experiment.match, "objective_deployment_choice", fail_second)
    directory = tmp_path / "deployment-rejected"
    export.export_case(MANIFEST, CASE, 1, "deployment-rejected", directory)
    meta, rows = export.verify_package(directory, expand=True)
    assert meta["runner_status"] == "deployment_error"
    assert meta["counts"]["deployment_events"] == meta["counts"]["battle_events"] == 0
    assert rows[0]["observation"]["outcome"] == "accepted"
    assert not any(row["events"] for row in rows)
    assert "offset" in rows[0]["observation"]["seen"]
    assert "snapshot" in rows[-1]["observation"]["seen"]
    assert rows[-1]["observation"]["outcome"] == "rejected"
    assert rows[-1]["observation"]["reason"] == "invalid_deployment_position"


def test_rejected_first_choice_keeps_the_seen_state_without_starting_an_activation(tmp_path, monkeypatch):
    make_player = export.experiment.make_player

    def reject_movement(kind, seed):
        player = make_player(kind, seed)
        pick = player.choose_action

        def over_budget(state, perspective):
            selected = pick(state, perspective)
            return ManeuverAction(selected.unit_id, Position(1000, 0))

        player.choose_action = over_budget
        return player

    monkeypatch.setattr(export.experiment, "make_player", reject_movement)
    directory = tmp_path / "first-choice-rejected"
    export.export_case(MANIFEST, CASE, 1, "first-choice-rejected", directory)
    meta, rows = export.verify_package(directory, expand=True)
    assert meta["runner_status"] == "match_error"
    assert meta["counts"]["battle_events"] == 0
    row = rows[-1]
    assert row["observation"]["kind"] == "choose_action"
    assert row["observation"]["outcome"] == "rejected"
    assert row["observation"]["reason"] == "maneuver_over_budget"
    assert row["states"]["seen"] is not None
    assert not row["events"] and row["states"]["before"] is None
    assert all(r["observation"]["kind"] != "activation_started" for r in rows)


def test_adapter_error_before_first_observation_leaves_empty_prefix(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("unpublished private diagnostics")

    monkeypatch.setattr(export.experiment, "prepare", fail)
    directory = tmp_path / "empty-prefix"
    export.export_case(MANIFEST, CASE, 1, "empty", directory)
    meta, rows = export.verify_package(directory, expand=True)
    assert meta["runner_status"] == "adapter_exception"
    assert meta["error_type"] == "RuntimeError"
    assert rows == []
    assert b"private diagnostics" not in (directory / "export.json").read_bytes()


def test_unchecked_file_edit_fails_hash(package):
    directory, _ = package
    file = directory / "battle.jsonl"
    file.write_bytes(file.read_bytes() + b"\n")
    with pytest.raises(export.ExportError, match="hash mismatch: battle.jsonl"):
        export.verify_package(directory)


def test_battle_replay_applies_every_event_exactly_once(package, monkeypatch):
    directory, meta = package
    visited = []
    apply = export.apply_events

    def observe_apply(state, events):
        visited.extend(e.sequence for e in events)
        return apply(state, events)

    monkeypatch.setattr(export, "apply_events", observe_apply)
    export.verify_package(directory)
    assert visited == list(range(1, meta["counts"]["battle_events"] + 1))


@pytest.mark.parametrize(("mutation", "match"), [
    ("missing_event", "sequence is not continuous"),
    ("changed_event", "state reference does not match replay"),
    ("changed_without_state_effect", "result or event digest differs from replay"),
    ("false_seen_state", "state reference does not match replay"),
    ("false_span", "state reference does not match replay"),
    ("false_placement", "does not own the recorded move"),
    ("boolean_transition_unit", "deployment transition differs from replay"),
])
def test_rehashed_payload_still_fails_semantic_checks(package, mutation, match):
    directory, _ = package
    filename = "battle.jsonl" if mutation in {
        "missing_event", "changed_event", "changed_without_state_effect",
    } else "decisions.jsonl"
    rows = _rows(directory / filename)
    if mutation == "missing_event":
        del rows[2]
    elif mutation == "changed_event":
        movement = next(row for row in rows if row["event_type"] == "MoveExecuted")
        movement["to_pos"][0] += 1
    elif mutation == "changed_without_state_effect":
        movement = next(row for row in rows if row["event_type"] == "MoveExecuted")
        movement["from_pos"][0] += 1
    elif mutation == "false_seen_state":
        row = next(row for row in rows if row["kind"] == "choose_action")
        row["seen"] = row["before"]
    elif mutation == "false_span":
        row = next(row for row in rows if row["kind"] == "choose_action")
        row["events"][1] += 1
    elif mutation == "false_placement":
        rows[0]["choice"][0] += 0.01
    else:
        row = next(row for row in rows if row["kind"] == "deployment_moved" and row["unit_id"] == 1)
        row["unit_id"] = True
    _replace_package_rows(directory, filename, rows)
    with pytest.raises(export.ExportError, match=match):
        export.verify_package(directory)
