"""Qualify observed deployment placements from verified campaign traces."""

from collections import Counter, defaultdict
import hashlib
from pathlib import Path

if __package__:
    from . import experiment_archive as archive
else:
    import experiment_archive as archive


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "szop.experiment.qualification/v1"
PROFILE_ID = "deployment-position-mvp-v1"
RULES = "app/static/docs/SZOP_Rozjemca.md"
EXPORTER = "scripts/export_decisions.py"
PHASES = "app/services/engine/phases.py"

# ADR-0059 compared the deployment and setup code on the two exact revisions.
_BASELINE_PHASES_CRLF_SHA256 = "fb49eb2dd6d06945b498af2ddbf125e7fae8e80c73fbcfc44312764c7d785afa"
_P6_PHASES_LF_SHA256 = "0ba67bafb68a08d926189942c751765f76c0b9ee7196fdc29cd8413b7adb3cf3"
_P6_PHASES_CRLF_SHA256 = "8d6b6447934cdb915fde5e784e6d19c01412baeab31ffa69fb7ebff135e80836"
_P6_PHASES_DIGESTS = {_P6_PHASES_LF_SHA256, _P6_PHASES_CRLF_SHA256}

# Independently reproduced first decisions in the exact results of D6.1.
# These bindings do not treat arbitrary scenario labels as rule evidence.
AUDIT_EVIDENCE = {
    "results_sha256": {
        "lf": "8c002c73363540072b5a51f2eb258292369d14b466afdd5c9743068dff592d59",
        "crlf": "b1e1385be8e20fa51fd81bc131c1da23db5bea96cd95f09bc4f4a26d18122945",
    },
    "findings": {
        "/decisions/10": ("14.c.iv", "visible_enemy_within_2in"),
        "/decisions/57": ("22.b.i", "maneuver_while_pinned"),
        "/decisions/65": ("22.a.i", "attack_while_exhausted"),
    },
}

PROFILE = {
    "id": PROFILE_ID,
    "schema": "szop.experiment.qualification_profile/v1",
    "task": "imitate_observed_standard_deployment_position",
    "rules": dict(file=RULES, sha256="173d2efce1e9a605424f71b0cd4542a77495e0c2b91c8ee0d7565b5f4282a2cd",
                  points=["2.d", "4.c.i", "13.a", "13.b", "15.c", "24"]),
    "geometry": "d5_1_circular_footprint_in_explicit_rectangle",
    "requires": ["campaign_execution", "technical_case_passed", "full_replay_of_each_repeat",
                 "observed_accepted_position_with_move", "no_ability_dependent_placement_context"],
    "diagnostic_audit": AUDIT_EVIDENCE,
    "sources_lf_sha256": {
        EXPORTER: "087b022eff787047d535faaa1b143d14ec0f4bd620f83782734193f78aa37297",
        "scripts/deployment_experiment.py": "ad781e4164bd8b2d722ccd6b7dbeb26001096bb4eb5118180faa17be44cc0728",
        "app/services/agents/deployment.py": "4aedf46fddad3404b9e305560b74ce0d2e6524d2ced9a32cdf1633d82c196ed3",
        PHASES: "eef7b6365132df0b2dea9a5c8224960c2bc278092018745a62dbcffcf4537a6c",
        "app/services/engine/geometry.py": "21f587e36da4cd9e1ad16eb966c561f049896e7b1147a486c044664c9a46a30b",
        "app/services/engine/movement.py": "346e86291c4a6cb2b5ff8ed329c4975c8ad9815e78663a9658650fd1fa360f41",
        "app/services/engine/terrain_complex.py": "56d43f45f380abf6907bbf89ec77637f6d3922107762020dc750bba4ccd6a01a",
        "app/services/engine/state.py": "b7513f18814e9007e15605dba1c9af43f09e92b43d7b6698b5358a180042c528",
        "app/services/engine/state_codec.py": "8a5133266ff7e154a3836b3d13c05093925ab2645a0736b3733dfc84811a8a27",
        "app/services/engine/events.py": "8a8499d0ccd89989f62d1ebf15679a5f36a49d391267862e28d442ba838581e0",
    },
    "partition": dict(unit="map_family_or_shared_observation_input", assignment="sha256_bucket_mod_10",
                      train=list(range(8)), validation=[8], test=[9]),
}
SPLITS = ("train", "validation", "test")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value) -> str:
    return _sha(archive._canonical(value))


def _source_variants() -> dict[str, set[str]]:
    variants = {}
    expected = {**PROFILE["sources_lf_sha256"], RULES: PROFILE["rules"]["sha256"]}
    for name, digest in expected.items():
        content = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        actual = _sha(content)
        if name == PHASES and actual in (digest, _P6_PHASES_LF_SHA256):
            variants[name] = {digest, _BASELINE_PHASES_CRLF_SHA256, *_P6_PHASES_DIGESTS}
        elif actual == digest:
            variants[name] = {digest, _sha(content.replace(b"\n", b"\r\n"))}
        else:
            raise ValueError(f"qualification profile requires its pinned source: {name}")
    return variants


def _profile_sources(meta: dict, variants: dict[str, set[str]]) -> bool:
    source = meta["source"]
    recorded = {**source["sources"], EXPORTER: source["exporter_sha256"]}
    return all(recorded.get(name) in permitted for name, permitted in variants.items() if name != RULES)


def _plain_deployment(state) -> bool:
    return (not state.pending_interrupts and not state.pending_effects
            and all(not (unit.passives or unit.ability_overrides or unit.status_flags)
                    and not any(weapon.weapon_abilities for weapon in (*unit.ranged_weapons, *unit.melee_weapons))
                    for unit in state.blobs))


def _observation(item: dict, profile_supported: bool) -> dict:
    row = item["observation"]
    record = dict(index=row["index"], kind=row["kind"], outcome=row.get("outcome"),
                  eligibility="excluded")
    if "choice" not in row:
        reason = "automatic_transition"
    elif row["outcome"] in {"none", "rejected", "error"}:
        reason = {"none": "no_choice", "rejected": "decision_rejected", "error": "decision_error"}[row["outcome"]]
        record["observation_reason"] = row.get("reason")
    elif row["kind"] != "choose_deployment":
        reason = "outside_verified_scope"
    elif not row["events"] or len(item["events"]) != 1:
        reason = "placement_not_executed"
    elif not profile_supported:
        reason = "unsupported_deployment_context"
    else:
        # The export verifier binds this exact observed state, actor, placement and move,
        # reusing is_deployment_position_legal on the recorded occupancy and terrain.
        inputs = dict(seen=row["seen"]["sha256"], player=row["player"], unit=row["unit_id"],
                      zone=row["zone"], occupied=row["occupied"])
        record.update(eligibility="qualified", rules_status="confirmed", evidence_range=row["events"],
                      input_sha256=_digest(inputs), sample_sha256=_digest([inputs, row["choice"]]))
        return record
    record.update(rules_status="unverified", reason=reason)
    return record


def _execution(export, snapshot: Path, result: dict, entry: dict, variants: dict) -> dict:
    evidence = entry["evidence"]
    analysis = dict(repeat=entry["repeat"], evidence=evidence, descriptor_sha256=entry["descriptor_sha256"])
    if not archive.TRACE_FILE_PATH.fullmatch(evidence) or Path(evidence).name != "export.json":
        raise ValueError("unexpected execution evidence path")
    try:
        directory = archive._directory(snapshot / Path(evidence).parent)
        meta, observations = export.verify_package(directory, expand=True)
        if (_sha(archive._canonical(meta) + b"\n") != entry["descriptor_sha256"]
                or meta["replay"]["status"] != "verified"):
            raise ValueError("execution changed after technical assessment")
        first = next((item for item in observations if item["observation"]["kind"] == "choose_deployment"), None)
        if first is not None and first["observation"]["seen"]["sha256"] != result["input_digest"]:
            raise ValueError("initial observation differs from the committed input")
    except (OSError, ValueError, KeyError, RecursionError):
        return dict(analysis, replay="failed", observations=[])
    supported = (first is not None and _profile_sources(meta, variants)
                 and _plain_deployment(export.battle_state_from_json(first["states"]["seen"])))
    if supported and meta["source"]["sources"].get(PHASES) in _P6_PHASES_DIGESTS:
        analysis["compatible_phase_sha256"] = _P6_PHASES_LF_SHA256
    return dict(analysis, replay="verified", observations=[_observation(item, supported) for item in observations])


def _case(export, snapshot: Path, technical: dict, result: dict | None, findings: dict, variants: dict) -> dict:
    case = technical["case"]
    output = {key: technical[key] for key in ("case_id", "group", "evidence")}
    output.update(technical_category=technical["category"], rules_status="unverified",
                  eligibility="excluded", executions=[])
    finding = findings.get(technical["evidence"]["pointer"])
    if finding is not None:
        return dict(output, rules_status="violation", rule=finding[0], reason=finding[1])
    if technical["category"] != "passed":
        return dict(output, reason=technical["category"])
    if not technical.get("decision_trace"):
        return dict(output, reason="no_decision_trace")
    for entry in technical["decision_trace"]:
        execution = _execution(export, snapshot, result, entry, variants)
        output["executions"].append(execution)
    if any(execution["replay"] != "verified" for execution in output["executions"]):
        for execution in output["executions"]:
            execution["observations"] = []
        return dict(output, reason="trace_replay_failed")
    if any(row["eligibility"] == "qualified" for e in output["executions"] for row in e["observations"]):
        fixture = case["fixture"]
        family = ["fixture", fixture["path"]] if "path" in fixture else ["generated_map", fixture["map"]]
        return dict(output, eligibility="qualified", rules_status="confirmed", map_family=family)
    return dict(output, reason="no_qualified_observation")


def _partition(cases: list[dict]) -> dict:
    # Join map families that share an identical observation input before assigning a split.
    # Per-family partitioning also groups side swaps, repeat executions and seed variants.
    families, inputs = {}, {}
    for case in cases:
        if case["eligibility"] != "qualified":
            continue
        family = tuple(case["map_family"])
        neighbors = families.setdefault(family, set())
        for execution in case["executions"]:
            for row in execution["observations"]:
                if row["eligibility"] == "qualified":
                    other = inputs.setdefault(row["input_sha256"], family)
                    if other != family:
                        neighbors.add(other)
                        families[other].add(family)

    groups, by_family = {}, {}
    for family in sorted(families):
        if family in by_family:
            continue
        group_id = _digest(family)
        bucket = int(group_id, 16) % 10
        split = next(name for name in SPLITS if bucket in PROFILE["partition"][name])
        component, queue = {family}, [family]
        while queue:
            for neighbor in families[queue.pop()] - component:
                component.add(neighbor)
                queue.append(neighbor)
        by_family.update({item: (group_id, split) for item in component})
        groups[group_id] = dict(split=split, map_families=sorted(component))

    group_splits, sample_splits = defaultdict(set), defaultdict(set)
    counts = Counter()
    for case in cases:
        if case["eligibility"] != "qualified":
            continue
        group_id, split = by_family[tuple(case["map_family"])]
        case.update(partition_group=group_id, split=split)
        group_splits[group_id].add(split)
        for execution in case["executions"]:
            for row in execution["observations"]:
                if row["eligibility"] == "qualified":
                    sample_splits[row["sample_sha256"]].add(split)
                    counts[split] += 1
    shared_groups = sum(len(assigned) > 1 for assigned in group_splits.values())
    shared_samples = sum(len(assigned) > 1 for assigned in sample_splits.values())
    if shared_groups or shared_samples:
        raise ValueError("groups or identical samples cross qualification splits")
    return dict(groups=groups, observations={split: counts[split] for split in SPLITS},
                unique_samples=len(sample_splits), shared_groups=shared_groups, shared_samples=shared_samples)


def qualify(root: Path, assessments: list[tuple[dict, dict, list[dict]]]) -> dict:
    """Use technical assessment and replay each eligible trace with the repository codecs."""
    if __package__:
        from . import export_decisions as export
    else:
        import export_decisions as export

    variants = _source_variants()
    sources, cases = [], []
    for technical, descriptor, journal in assessments:
        package_id = technical["package_id"]
        snapshot = root / "packages" / package_id / archive.SNAPSHOT
        audit = (descriptor["type"] == archive.BOTS_AUDIT_TYPE and
                 descriptor["files"]["results.json"]["sha256"] in AUDIT_EVIDENCE["results_sha256"].values())
        findings = AUDIT_EVIDENCE["findings"] if audit else {}
        sources.append(dict(package_id=package_id, package_type=technical["package_type"],
                            completeness=technical["completeness"], policy_digest=technical["policy_digest"],
                            quality_report_sha256=_sha(archive._canonical(technical) + b"\n"),
                            coverage=technical["coverage"]))
        results = {row["case"]["id"]: row["result"] for row in journal}
        cases.extend(dict(package_id=package_id, **_case(export, snapshot, assessed,
                          results.get(assessed["case_id"]), findings, variants))
                     for assessed in technical["cases"])

    partition = _partition(cases)
    executions = [execution for case in cases for execution in case["executions"]]
    observations = [row for execution in executions for row in execution["observations"]]
    coverage = dict(cases=dict(Counter(case["eligibility"] for case in cases)),
                    rules_status=dict(Counter(case["rules_status"] for case in cases)),
                    case_exclusions=dict(Counter(case["reason"] for case in cases if "reason" in case)),
                    observations=dict(Counter(row["eligibility"] for row in observations)),
                    observation_exclusions=dict(Counter(row["reason"] for row in observations if "reason" in row)))
    profile = PROFILE
    if any("compatible_phase_sha256" in execution for execution in executions):
        profile = {**PROFILE, "compatible_sources_lf_sha256": {PHASES: _P6_PHASES_LF_SHA256}}
    profile_digest = _digest(profile)
    return dict(schema=SCHEMA, profile=profile, profile_digest=profile_digest,
                report_key=_digest([profile_digest, sources]), sources=sources,
                status="passed" if partition["unique_samples"] else "review",
                coverage=coverage, partition=partition, cases=cases)
