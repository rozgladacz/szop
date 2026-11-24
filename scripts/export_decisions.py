"""Export and replay one observed execution of a v1 campaign case offline."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from math import isfinite, prod
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import campaign_v1 as campaign  # noqa: E402
from scripts.experiment_archive import (  # noqa: E402
    DECISION_EXPORT_SCHEMA as SCHEMA, EXPORT_DATA_FILES as FILES, TRACE_LABEL as LABEL,
)
from app.services.agents.deployment import DeploymentZone, is_deployment_position_legal  # noqa: E402
from app.services.agents.match import DeploymentDecision  # noqa: E402
from app.services.engine.action_codec import (  # noqa: E402
    ACTION_WIRE_SCHEMA, ACTION_WIRE_VERSION, action_from_json, action_to_json,
)
from app.services.engine.actions import DeploymentAction  # noqa: E402
from app.services.engine.events import (  # noqa: E402
    SCHEMA_VERSION, InitiativePassed, MoveExecuted, RoundEnded, StatusAdded, event_to_json, json_to_event,
)
from app.services.engine.geometry import Position  # noqa: E402
from app.services.engine.observation import ActionDecision, AutomaticTransition  # noqa: E402
from app.services.engine.phases import deployment_round  # noqa: E402
from app.services.engine.state import Lokalizacja, apply_events  # noqa: E402
from app.services.engine.state_codec import (  # noqa: E402
    STATE_CHECKPOINT_SCHEMA, STATE_CHECKPOINT_VERSION, battle_state_from_json, battle_state_to_json,
)
from app.services.engine.status import StatusFlag  # noqa: E402

experiment = campaign.experiment
CODECS = {
    "action": {"schema": ACTION_WIRE_SCHEMA, "version": ACTION_WIRE_VERSION},
    "state": {"schema": STATE_CHECKPOINT_SCHEMA, "version": STATE_CHECKPOINT_VERSION},
    "event": {"version": SCHEMA_VERSION},
}
DEPLOYMENT_STEPS = {"deployment_moved", "deployment_finished"}
BATTLE_STEPS = {
    "activation_started", "activation_stopped", "activation_finished",
    "initiative_passed", "round_ended",
}
ACTION_KINDS = {"choose_action", "continue_activation"}
MATCH_STATUSES = {"complete", "deployment_error", "match_error", "activation_cap", "adapter_exception"}
MANIFEST_FIELDS = {
    "schema", "fixtures", "policies", "battle_seeds", "swaps", "initiatives", "strategy_pairs",
    "deployment_zones", "repeats", "max_activations", "ruleset_version",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
REVISION = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class ExportError(ValueError):
    """The package or requested execution does not satisfy the format."""


def _require(condition, message):
    if not condition:
        raise ExportError(message)


def _keys(value, *keys):
    _require(type(value) is dict and value.keys() == set(keys), "unexpected object fields")
    return value


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _hash(value):
    return campaign.sha(campaign.canonical(value))


def _state_hash(state):
    return _hash(battle_state_to_json(state))


def _position(position):
    return None if position is None else [position.x, position.y]


def _decode_position(payload):
    _require(
        type(payload) is list and len(payload) == 2
        and all(type(n) in (int, float) and isfinite(n) for n in payload),
        "invalid deployment coordinates",
    )
    return Position(*payload)


def _record_state(record):
    return record.before if isinstance(record, AutomaticTransition) else record.seen_state


class _Trace:
    """Project in-process observations onto offsets into the two event tails."""

    def __init__(self, records):
        self.records = records
        self.rows = []
        self.deployment = []
        self.battle = []
        self.initial = _record_state(records[0]) if records else None
        self.deployed = None
        self.deployment_moves = sum(r.kind == "deployment_moved"
                                    for r in records if isinstance(r, AutomaticTransition))
        self.placement_choices = 0
        self.activation_start = 0
        self.state_digests = {}

    def project(self):
        for index, record in enumerate(self.records, 1):
            try:
                if isinstance(record, DeploymentDecision):
                    row = self._placement(record)
                elif isinstance(record, ActionDecision):
                    row = self._action(record)
                else:
                    row = self._transition(record)
            except (TypeError, ValueError) as exc:
                raise ExportError(f"cannot encode observation {index}: {exc}") from exc
            self.rows.append(dict(index=index, **row))

    def _ref(self, state, offset):
        if state is None:
            return None
        key = id(state)
        if key not in self.state_digests:
            self.state_digests[key] = _state_hash(state)
        return {"offset": offset, "sha256": self.state_digests[key]}

    @staticmethod
    def _add_events(tail, events):
        start = len(tail)
        tail.extend(event_to_json(event) for event in events)
        return [start, len(tail)] if events else None

    def _placement(self, record):
        offset = self.placement_choices
        seen = self._ref(record.seen_state, offset)
        if offset > self.deployment_moves:
            seen = {"snapshot": battle_state_to_json(record.seen_state), "sha256": seen["sha256"]}
        if record.outcome == "accepted":
            self.placement_choices += 1
        index = record.placement_index
        return dict(
            kind="choose_deployment", player=record.perspective, unit_id=record.unit_id,
            strategy=record.strategy, target_id=record.target_id, placement_index=index,
            zone=[record.zone.x_min, record.zone.y_min, record.zone.x_max, record.zone.y_max],
            occupied=[blob.id for blob in record.occupied],
            assignments=[list(pair) for pair in record.assignments],
            seen=seen, choice=_position(record.position), outcome=record.outcome,
            reason=record.reason, events=[index - 1, index] if index and index <= self.deployment_moves else None,
        )

    def _action(self, record):
        offset = len(self.battle)
        before_activation = record.kind == "choose_action" and record.before is not None
        return dict(
            kind=record.kind, player=record.perspective, unit_id=record.unit_id,
            prior_actions=[action_to_json(action) for action in record.prior_actions],
            choice=action_to_json(record.action) if record.action is not None else None,
            outcome=record.outcome, reason=record.reason,
            seen=self._ref(record.seen_state, self.activation_start if before_activation else offset),
            before=self._ref(record.before, offset),
            events=self._add_events(self.battle, record.events),
            after=self._ref(record.after, len(self.battle)),
        )

    def _transition(self, record):
        tail = self.deployment if record.kind in DEPLOYMENT_STEPS else self.battle
        start = len(tail)
        events = self._add_events(tail, record.events)
        if record.kind == "activation_started":
            self.activation_start = start
        if record.kind == "deployment_finished":
            self.deployed = record.after
        return dict(
            kind=record.kind, unit_id=record.unit_id, reason=record.reason, events=events,
            before=self._ref(record.before, start), after=self._ref(record.after, len(tail)),
        )


def _case(manifest, case_id):
    for case in experiment.iter_cases(manifest):
        if case["id"] == case_id:
            return case
    raise ExportError("case ID is absent from the manifest")


def _seeds(case):
    # Mirrors the adapter's assignment by original army under a physical side swap.
    seed = case["seed"]
    decision = [seed, seed + experiment.PLAYER_SEED_OFFSET]
    return {"battle": seed, "policy_by_player": decision[::-1] if case["swap"] else decision,
            "map": case["fixture"].get("map_seed")}


def _run_id(campaign_id, label):
    return _hash({"schema": SCHEMA, "campaign_id": campaign_id, "label": label})


def _observed_result(result, trace):
    status = result["status"]
    if status == "complete":
        _require(result["replay_equal"], "adapter did not verify full replay")
        _require(_hash(trace.battle) == result["event_digest"], "observer differs from runner battle log")
        return {k: result[k] for k in ("final_digest", "event_digest", "score", "winner", "rounds")}
    return None


def export_case(manifest_path: Path, case_id: str, repeat: int, label: str, directory: Path):
    """Re-simulate one explicit case/repeat and publish its immutable evidence."""
    manifest = campaign.load_manifest(manifest_path)
    _verify_manifest_fields(manifest)
    case = _case(manifest, case_id)
    _require(_int(repeat, 1) and repeat <= manifest["repeats"], "repeat is outside the manifest")
    _require(type(label) is str and LABEL.fullmatch(label), "invalid execution label")
    _require(not directory.exists() and not directory.is_symlink(), "export destination already exists")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source = source_provenance(campaign.compatibility(manifest), revision)
    result, records, _ = capture_execution(case, manifest)
    return publish_execution(case, manifest, repeat, label, directory, source, result, records)


def source_provenance(identity: dict, revision: str) -> dict:
    exporter_digest = campaign.sha(Path(__file__).read_text(encoding="utf-8").encode("utf-8"))
    return dict(identity, source_commit=revision, exporter_sha256=exporter_digest)


def capture_execution(case: dict, manifest: dict):
    """Run the adapter once while retaining the original result and any available trace."""
    records = []
    try:
        result = experiment.run_once(case, manifest, on_observation=records.append)
    except Exception as exc:
        # Retain the available prefix without exposing exception messages or paths.
        return {"status": "adapter_exception", "error_type": type(exc).__name__}, records, exc
    return result, records, None


def publish_execution(case, manifest, repeat, label, directory, source, result, records, *,
                      origin="manifest_resimulation"):
    """Project, verify and publish the observations from the supplied execution."""
    identity = {key: source[key] for key in ("manifest_digest", "sources", "python_family", "dependencies")}
    campaign_id = _hash(identity)
    trace = _Trace(records)
    trace.project()
    initial = battle_state_to_json(trace.initial) if trace.initial is not None else None
    if initial is not None and "input_digest" in result:
        _require(_hash(initial) == result["input_digest"], "observer differs from runner start state")
    states = {
        "initial": initial,
        "deployed": battle_state_to_json(trace.deployed) if trace.deployed is not None else None,
    }
    runner_status = result["status"]
    status = "complete" if runner_status == "complete" else "incomplete"
    meta = dict(
        schema=SCHEMA, codecs=CODECS, campaign_id=campaign_id,
        run_id=_run_id(campaign_id, label), run_label=label,
        origin={"kind": origin, "manifest_base_commit": manifest.get("base_commit")},
        case=case, repeat=repeat, seeds=_seeds(case), source=source,
        status=status, runner_status=runner_status, error_type=result.get("error_type"),
        result=_observed_result(result, trace),
        replay={"status": "verified" if status == "complete" else "prefix_only"},
        counts={"observations": len(trace.rows), "decisions": sum("choice" in r for r in trace.rows),
                "deployment_events": len(trace.deployment), "battle_events": len(trace.battle)},
    )
    payload = {
        "manifest.json": _line(manifest),
        "states.json": _line(states),
        "deployment.jsonl": b"".join(map(_line, trace.deployment)),
        "battle.jsonl": b"".join(map(_line, trace.battle)),
        "decisions.jsonl": b"".join(map(_line, trace.rows)),
    }
    meta["files"] = {name: campaign.sha(data) for name, data in payload.items()}
    _verify_payload(meta, _decode_payload(payload))
    directory.mkdir(parents=True)
    for name, data in payload.items():
        campaign.atomic_write(directory / name, data)
    campaign.atomic_write(directory / "export.json", _line(meta))
    return meta


def _line(value):
    return campaign.canonical(value) + b"\n"


def _parse_line(raw):
    value = json.loads(raw.decode("utf-8"))
    _require(raw == _line(value), "noncanonical JSON")
    return value


def _read_file(directory, name, digest):
    data = campaign.plain_file(directory / name).read_bytes()
    _require(campaign.sha(data) == digest, f"hash mismatch: {name}")
    return data


def _decode_payload(files):
    return {
        name: [_parse_line(line) for line in data.splitlines(keepends=True)]
        if name.endswith(".jsonl") else _parse_line(data)
        for name, data in files.items()
    }


def _decode_events(rows):
    events = []
    for index, row in enumerate(rows, 1):
        _require(type(row) is dict and _int(row.get("sequence"), 1) and row["sequence"] == index,
                 "event sequence is not continuous")
        _require(type(row.get("version")) is int and row["version"] == SCHEMA_VERSION,
                 "unsupported event wire version")
        event = json_to_event(row)
        _require(campaign.canonical(event_to_json(event)) == campaign.canonical(row), "unexpected event payload")
        if isinstance(event, StatusAdded):
            # The headless runner adds StatusFlag values. JSON writes them as strings,
            # but the state codec distinguishes enum values from bare strings.
            event = replace(event, status=StatusFlag(event.status))
        events.append(event)
    return events


def _verify_manifest_fields(manifest):
    _require(type(manifest) is dict
             and MANIFEST_FIELDS <= manifest.keys() <= MANIFEST_FIELDS | {"base_commit"},
             "unsupported manifest fields")
    revision = manifest.get("base_commit")
    _require(revision is None or (type(revision) is str and REVISION.fullmatch(revision)),
             "invalid manifest base revision")
    _require(manifest["schema"] == "szop.deployment_experiment/v1" and manifest["ruleset_version"] == "v1",
             "unsupported manifest")
    _require(_int(manifest["repeats"], 2) and manifest["repeats"] <= 5, "invalid manifest repeat count")
    dimensions = [manifest[key] for key in (
        "fixtures", "policies", "battle_seeds", "swaps", "initiatives", "strategy_pairs",
    )]
    _require(all(type(values) is list and values for values in dimensions)
             and prod(map(len, dimensions)) * manifest["repeats"] <= 2048, "invalid manifest dimensions")
    zones = manifest["deployment_zones"]
    _require(type(zones) is list and len(zones) == 2 and all(
        type(z) is list and len(z) == 4 and all(type(n) in (int, float) and isfinite(n) for n in z)
        and z[0] <= z[2] and z[1] <= z[3] for z in zones
    ), "invalid manifest deployment zones")
    _require(_int(manifest["max_activations"], 1) and manifest["max_activations"] <= 2000,
             "invalid manifest activation cap")


def _verify_provenance(meta, manifest):
    _keys(meta, "schema", "codecs", "campaign_id", "run_id", "run_label", "origin", "case", "repeat",
          "seeds", "source", "status", "runner_status", "error_type", "result", "replay", "counts", "files")
    _require(meta["schema"] == SCHEMA and _line(meta["codecs"]) == _line(CODECS), "unsupported export format")
    _verify_manifest_fields(manifest)
    case = _case(manifest, meta["case"]["id"])
    _require(_line(case) == _line(meta["case"]), "case differs from manifest")
    _require(_int(meta["repeat"], 1) and meta["repeat"] <= manifest["repeats"], "invalid repeat ordinal")
    _require(_line(meta["seeds"]) == _line(_seeds(case)), "seed assignment mismatch")
    source = _keys(meta["source"], "source_commit", "exporter_sha256", "manifest_digest",
                   "sources", "python_family", "dependencies")
    _require(type(source["source_commit"]) is str and REVISION.fullmatch(source["source_commit"]),
             "invalid source revision")
    _require(type(source["sources"]) is dict and source["sources"]
             and all(type(d) is str and SHA256.fullmatch(d)
                     for d in (*source["sources"].values(), source["exporter_sha256"])),
             "invalid source fingerprints")
    family = source["python_family"]
    dependencies = _keys(source["dependencies"], "pydantic", "pydantic_core", "PyYAML")
    _require(type(family) is list and len(family) == 2 and all(_int(part) for part in family)
             and all(type(version) is str and version for version in dependencies.values()),
             "invalid source environment")
    _require(source["manifest_digest"] == _hash(manifest), "manifest digest mismatch")
    identity = {key: source[key] for key in ("manifest_digest", "sources", "python_family", "dependencies")}
    _require(meta["campaign_id"] == _hash(identity), "campaign identity mismatch")
    _require(type(meta["run_label"]) is str and LABEL.fullmatch(meta["run_label"])
             and meta["run_id"] == _run_id(meta["campaign_id"], meta["run_label"]), "export identity mismatch")
    origin = _keys(meta["origin"], "kind", "manifest_base_commit")
    _require(origin["kind"] in ("manifest_resimulation", "campaign_execution")
             and origin["manifest_base_commit"] == manifest.get("base_commit"), "manifest origin mismatch")
    _require(meta["runner_status"] in MATCH_STATUSES, "unknown runner status")
    complete = meta["runner_status"] == "complete"
    _require(meta["status"] == ("complete" if complete else "incomplete"), "export status mismatch")
    _require(meta["replay"] == {"status": "verified" if complete else "prefix_only"}, "replay status mismatch")
    _require(meta["error_type"] is None or (not complete and type(meta["error_type"]) is str),
             "invalid adapter error marker")
    _require(complete or meta["result"] is None, "incomplete export cannot contain a complete result")
    return complete


def _decode_state(payload):
    if payload is None:
        return None
    _require(type(payload) is dict and payload.get("version") == STATE_CHECKPOINT_VERSION, "expected v1 state")
    state = battle_state_from_json(payload)
    _require(_line(payload) == _line(battle_state_to_json(state)), "noncanonical state")
    return state


def _verify_ref(ref, digest, offset):
    _keys(ref, "offset", "sha256")
    _require(_int(ref["offset"]) and ref["offset"] == offset and ref["sha256"] == digest,
             "state reference does not match replay")


def _scope(row, start, count):
    span = row["events"]
    _require(span is None or (type(span) is list and len(span) == 2 and all(_int(i) for i in span)
             and span[0] == start < span[1] <= count), "invalid event range")
    return start if span is None else span[1]


def _same_position(event, choice):
    return event.to_pos == (choice.x, choice.y)


def _verify_deployment(rows, events, initial, deployed, manifest, case):
    if initial is None:
        _require(not rows and not events and deployed is None, "deployment without initial state")
        return {}
    _require(initial.round == 0 and initial.active_player == case["initiative"], "invalid initial deployment state")
    first_transition = next((i for i, row in enumerate(rows) if row["kind"] != "choose_deployment"), len(rows))
    choices, transitions = rows[:first_transition], rows[first_transition:]
    eligible = [u for u in initial.blobs if u.models_alive > 0 and u.location == Lokalizacja.FRONT]
    _require(len(choices) <= len(eligible), "too many deployment choices")

    moves = [e for e in events if isinstance(e, MoveExecuted) and e.move_type == "deploy"]
    _require(len(moves) <= len(choices), "deployment move without a choice")
    actions = []
    expanded = {}
    working = initial
    occupied = []
    assignments = ({}, {})
    for offset, row in enumerate(choices):
        _keys(row, "index", "kind", "player", "unit_id", "strategy", "target_id", "placement_index",
              "zone", "occupied", "assignments", "seen", "choice", "outcome", "reason", "events")
        player = row["player"]
        unit = eligible[offset]
        _require(type(player) is int and player in (0, 1) and _int(row["unit_id"])
                 and unit.id == row["unit_id"] and unit.owner_player == player, "invalid deployment actor")
        _require(row["strategy"] == case["strategies"][player]
                 and _line(row["zone"]) == _line(manifest["deployment_zones"][player]), "deployment context mismatch")
        _require(_line(row["occupied"]) == _line([u.id for u in occupied])
                 and _line(row["assignments"]) == _line([list(item) for item in assignments[player].items()]),
                 "deployment occupancy or assignment mismatch")
        if offset <= len(moves):
            _verify_ref(row["seen"], _state_hash(working), offset)
        else:
            seen = _keys(row["seen"], "snapshot", "sha256")
            _require(_decode_state(seen["snapshot"]) == working and seen["sha256"] == _state_hash(working),
                     "deployment snapshot differs from prior choices")
        expanded[row["index"]] = (working, None, None)
        choice = _decode_position(row["choice"]) if row["choice"] is not None else None
        target = row["target_id"]
        _require(target is None or (_int(target) and row["strategy"] == "objectives"
                 and any(o.id == target for o in working.objectives)), "invalid deployment target")
        if row["outcome"] != "accepted":
            _require(row["outcome"] in ("rejected", "error") and type(row["reason"]) is str
                     and row["placement_index"] is None and row["events"] is None
                     and offset == len(choices) - 1 and not moves and deployed is None,
                     "invalid unexecuted deployment decision")
            continue
        _require(choice is not None and _int(row["placement_index"], 1)
                 and row["placement_index"] == offset + 1 and row["reason"] is None
                 and is_deployment_position_legal(
                     unit, choice, DeploymentZone(*row["zone"]), occupied=occupied, terrain=initial.terrain,
                 ), "invalid accepted deployment")
        if offset < len(moves):
            event = moves[offset]
            _require(_scope(row, offset, len(events)) == offset + 1 and event.unit_id == unit.id
                     and _same_position(event, choice), "deployment choice does not own the recorded move")
            actions.append(DeploymentAction(unit.id, choice))
        else:
            _require(row["events"] is None, "unapplied placement claims a move")
        if target is not None:
            assignments[player][target] = assignments[player].get(target, 0) + 1
        placed = replace(unit, position=choice)
        occupied.append(placed)
        working = replace(working, blobs=tuple(placed if u.id == unit.id else u for u in working.blobs))

    if deployed is not None:
        _require(len(actions) == len(choices) == len(eligible), "deployment completed with missing placements")
    expected = []
    end, tail = deployment_round(initial, actions, on_observation=expected.append)
    if deployed is None:
        expected = expected[:len(actions)]
        tail = tail[:len(actions)]
    else:
        _require(_state_hash(end) == _state_hash(deployed), "post-deployment state differs from replay")
    _require(_line([event_to_json(e) for e in events]) == _line([event_to_json(e) for e in tail]),
             "deployment tail differs from replay")
    _require(len(expected) == len(transitions), "missing deployment execution transition")
    offset, digest = 0, _state_hash(initial)
    for row, transition in zip(transitions, expected, strict=True):
        _keys(row, "index", "kind", "unit_id", "reason", "events", "before", "after")
        _require(row["kind"] == transition.kind and _line(row["unit_id"]) == _line(transition.unit_id)
                 and row["reason"] is None,
                 "deployment transition differs from replay")
        _verify_ref(row["before"], digest, offset)
        stop = _scope(row, offset, len(events))
        _require(stop - offset == len(transition.events), "wrong deployment transition range")
        digest = _state_hash(transition.after)
        _verify_ref(row["after"], digest, stop)
        if transition.kind == "deployment_moved":
            index = choices[offset]["index"]
            expanded[index] = (expanded[index][0], transition.before, transition.after)
        expanded[row["index"]] = (None, transition.before, transition.after)
        offset = stop
    return expanded


class _BattleReplay:
    """Check decision order and consume each recorded battle event once."""

    def __init__(self, initial, events):
        self.state = initial
        self.digest = _state_hash(initial) if initial is not None else None
        self.events = events
        self.offset = 0
        self.activation = None
        self.applied = []
        self.stopped = False

    def verify(self, row):
        kind = row["kind"]
        start = self.offset
        before = self.state
        _require(not before.is_game_over, "observation follows the end of the battle")
        end = _scope(row, start, len(self.events))
        events = self.events[start:end]
        if kind in ACTION_KINDS:
            seen = self._action(row, events)
        else:
            _require(kind in BATTLE_STEPS, "unknown battle observation")
            seen = None
            self._transition(row, events)
        self.state = apply_events(before, events)
        if self.state is not before:
            self.digest = _state_hash(self.state)
        self.offset = end
        if row["after"] is not None:
            _verify_ref(row["after"], self.digest, end)
        return seen, before if row["before"] is not None else None, self.state if row["after"] is not None else None

    def _action(self, row, events):
        _keys(row, "index", "kind", "player", "unit_id", "prior_actions", "choice", "outcome", "reason",
              "seen", "before", "events", "after")
        outcome = row["outcome"]
        choice = action_from_json(row["choice"]) if row["choice"] is not None else None
        _require(row["unit_id"] is None or _int(row["unit_id"]), "invalid action unit")
        _require(outcome in ("applied", "rejected", "none", "error"), "unknown action outcome")
        _require((outcome != "none" or choice is None) and (outcome not in ("applied", "rejected") or choice is not None),
                 "choice differs from outcome")
        _require((type(row["reason"]) is str and bool(row["reason"]))
                 if outcome in ("rejected", "error") else row["reason"] is None, "invalid action reason")
        executed, has_before = outcome == "applied", row["before"] is not None
        execution_error = outcome == "error" and choice is not None
        _require((row["after"] is not None) == executed and (executed or not events)
                 and has_before == (executed or execution_error),
                 "action outcome has wrong state references or effects")
        _require(all(not isinstance(e, (RoundEnded, InitiativePassed)) for e in events),
                 "action claims a system event")
        seen, offset, digest = self.state, self.offset, self.digest
        if row["kind"] == "choose_action":
            _require(row["prior_actions"] == [] and row["unit_id"] == (None if choice is None else choice.unit_id),
                     "invalid first action context")
            if has_before:
                _require(self.activation is not None and not self.applied and not self.stopped,
                         "first action has no activation start")
                unit, seen, offset, digest = self.activation
                _require(unit == row["unit_id"], "first decision has wrong actor")
            else:
                _require(self.activation is None, "unexpected first decision in activation")
        else:
            _require(self.activation is not None and self.applied and not self.stopped
                     and row["unit_id"] == self.activation[0]
                     and _line(row["prior_actions"]) == _line(self.applied), "invalid continuation context")
            _require(not executed or choice.unit_id == row["unit_id"], "applied continuation changes unit")
        _require(type(row["player"]) is int and row["player"] == seen.active_player, "invalid decision player")
        _verify_ref(row["seen"], digest, offset)
        if has_before:
            _verify_ref(row["before"], self.digest, self.offset)
        if executed:
            self.applied.append(row["choice"])
        elif self.activation is not None:
            self.stopped = True
        return seen

    def _transition(self, row, events):
        _keys(row, "index", "kind", "unit_id", "reason", "events", "before", "after")
        _require(row["after"] is not None, "missing transition post-state")
        _verify_ref(row["before"], self.digest, self.offset)
        kind, unit = row["kind"], row["unit_id"]
        _require(unit is None or _int(unit), "invalid transition unit")
        _require(row["reason"] is None or type(row["reason"]) is str, "invalid transition reason")
        if kind == "activation_started":
            _require(self.activation is None and _int(unit) and row["reason"] is None
                     and any(blob.id == unit and blob.owner_player == self.state.active_player
                             for blob in self.state.blobs), "invalid activation start")
            self.activation = (unit, self.state, self.offset, self.digest)
        elif kind in ("activation_stopped", "activation_finished"):
            _require(self.activation is not None and unit == self.activation[0] and self.applied,
                     "transition without matching activation")
            if kind == "activation_stopped":
                _require(not self.stopped and not events and type(row["reason"]) is str, "invalid automatic stop")
                self.stopped = True
            else:
                _require(self.stopped and row["reason"] is None, "invalid activation finalization")
                self.activation, self.applied, self.stopped = None, [], False
        else:
            _require(self.activation is None and events, "invalid round or initiative transition")
            if kind == "round_ended":
                _require(unit is None, "round transition has an activation unit")
            else:
                expected_reason = "choose_action_none" if unit is None else "activation_finished"
                _require(row["reason"] == expected_reason, "initiative transition has the wrong origin")
        passed = [e for e in events if isinstance(e, InitiativePassed)]
        ended = [e for e in events if isinstance(e, RoundEnded)]
        _require((len(passed) == len(events) == 1 if kind == "initiative_passed" else not passed)
                 and (len(ended) == 1 and events[-1] is ended[0] if kind == "round_ended" else not ended),
                 "system event has the wrong transition")


def _verify(meta, manifest, states, deployment, battle, rows, *, expand=False):
    complete = _verify_provenance(meta, manifest)
    _keys(states, "initial", "deployed")
    initial, deployed = _decode_state(states["initial"]), _decode_state(states["deployed"])
    for index, row in enumerate(rows, 1):
        _require(type(row) is dict and _int(row.get("index"), 1) and row["index"] == index
                 and type(row.get("kind")) is str, "invalid observation identity")
    counts = {"observations": len(rows), "decisions": sum("choice" in r for r in rows),
              "deployment_events": len(deployment), "battle_events": len(battle)}
    _require(_line(meta["counts"]) == _line(counts), "observation or event count mismatch")
    first_battle = next((i for i, row in enumerate(rows)
                         if row["kind"] not in DEPLOYMENT_STEPS | {"choose_deployment"}), len(rows))
    deployments, decisions = rows[:first_battle], rows[first_battle:]
    expansion = _verify_deployment(deployments, deployment, initial, deployed, manifest, meta["case"])
    _require(deployed is not None or (not battle and not decisions and not complete), "battle without deployment")
    if meta["runner_status"] == "deployment_error":
        _require(deployed is None, "deployment error has a completed deployment")
    if meta["runner_status"] in ("match_error", "activation_cap"):
        _require(deployed is not None, "battle error has no completed deployment")
    replay = _BattleReplay(deployed, battle)
    for row in decisions:
        try:
            states_at_decision = replay.verify(row)
        except ExportError as exc:
            raise ExportError(f"observation {row['index']}: {exc}") from exc
        if expand:
            expansion[row["index"]] = states_at_decision
    _require(replay.offset == len(battle), "unclaimed battle events")
    if complete:
        result = _keys(meta["result"], "final_digest", "event_digest", "score", "winner", "rounds")
        end = replay.state
        _require(end.is_game_over and replay.activation is None and result["final_digest"] == replay.digest,
                 "final battle state differs from replay")
        expected = dict(final_digest=replay.digest, event_digest=_hash([event_to_json(e) for e in battle]),
                        score=list(end.score), winner=experiment.match._winner(end), rounds=end.round)
        _require(_line(result) == _line(expected), "result or event digest differs from replay")
    if expand:
        return [_expand(meta, row, expansion[row["index"]], deployment, battle) for row in rows]
    return None


def _expand(meta, row, states, deployment, battle):
    span = row["events"]
    events = deployment if row["kind"] in DEPLOYMENT_STEPS | {"choose_deployment"} else battle
    return dict(
        campaign_id=meta["campaign_id"], run_id=meta["run_id"], case_id=meta["case"]["id"],
        repeat=meta["repeat"], observation=row,
        states={key: battle_state_to_json(state) if state is not None else None
                for key, state in zip(("seen", "before", "after"), states, strict=True)},
        events=[event_to_json(e) for e in events[span[0]:span[1]]] if span is not None else [],
    )


def _verify_payload(meta, payload, *, expand=False):
    return _verify(
        meta, payload["manifest.json"], payload["states.json"],
        _decode_events(payload["deployment.jsonl"]), _decode_events(payload["battle.jsonl"]),
        payload["decisions.jsonl"], expand=expand,
    )


def verify_package(directory: Path, *, expand=False):
    """Verify one package and optionally reconstruct each ordered observation."""
    _require(directory.is_dir() and not directory.is_symlink(), "expected a real export directory")
    try:
        _require({p.name for p in directory.iterdir()} == {*FILES, "export.json"}, "unexpected package files")
        meta = _parse_line(campaign.plain_file(directory / "export.json").read_bytes())
        files = _keys(meta["files"], *FILES)
        payload = _decode_payload({name: _read_file(directory, name, files[name]) for name in FILES})
        observations = _verify_payload(meta, payload, expand=expand)
        return (meta, observations) if expand else meta
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError, NotImplementedError) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError(f"invalid decision package: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True, dest="command")
    export = commands.add_parser("export", help="re-simulate one case and write its observation package")
    export.add_argument("--manifest", type=Path, required=True)
    export.add_argument("--case", required=True)
    export.add_argument("--repeat", type=int, required=True)
    export.add_argument("--run-label", required=True)
    export.add_argument("directory", type=Path)
    for command in ("verify", "expand"):
        commands.add_parser(command).add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            meta = export_case(args.manifest, args.case, args.repeat, args.run_label, args.directory)
        elif args.command == "verify":
            meta = verify_package(args.directory)
        else:
            meta, observations = verify_package(args.directory, expand=True)
            for row in observations:
                print(campaign.canonical(row).decode("ascii"))
        if args.command != "expand":
            print(campaign.canonical(meta).decode("ascii"))
        return 0 if meta["status"] == "complete" else 2
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"decision export: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
