"""Publish and inspect campaign snapshots and historical experiment evidence."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory


PACKAGE_SCHEMA = "szop.experiment.package/v1"
CAMPAIGN_SCHEMA = "szop.campaign/v1"
PACKAGE_TYPE = "campaign_v1"
DESCRIPTOR = "package.json"
SNAPSHOT = "snapshot"
CAMPAIGN_FILES = {"header.json", "manifest.json", "journal.jsonl", "report.md", "checksums.json"}
DEPLOYMENT_TYPE = "deployment_experiment_v1"
BOTS_AUDIT_TYPE = "bots_audit_v1"
BOTS_REPORT = "boty-audit.md"
HISTORY_FORMATS = {
    DEPLOYMENT_TYPE: ("szop.deployment_experiment/v1", {"manifest.json", "results.json", "README.md", "results.md"}),
    BOTS_AUDIT_TYPE: ("szop.bots_audit/v1", {"manifest.json", "results.json", "side_analysis.json",
                                           "transport_probe.json", BOTS_REPORT}),
}
AUDIT_GROUPS = {
    "decision": ("decisions", ("kind", "seed", "scenario")),
    "deployment": ("deployments", ("kind", "strategy", "narrow")),
    "ending": ("endings", ("kind",)),
    "fixture": ("fixtures", ("kind", "fixture")),
}
DIGEST = re.compile(r"[0-9a-f]{64}")
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
DEVICE_NAME = re.compile(r"(?:CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])",
                         re.IGNORECASE)


class ArchiveError(ValueError):
    """A local archive or package did not meet the publication contract."""


# === SECTION: local paths and content identity ===
def _stat(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ArchiveError(f"links and reparse points are not allowed: {path}")
    if not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
        raise ArchiveError(f"expected a directory or regular file without aliases: {path}")
    return info


def _directory(path: Path, *, create: bool = False) -> Path:
    """Check all existing components before traversing or creating a directory."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = _stat(part)
        except FileNotFoundError:
            if not create:
                raise
            part.mkdir(exist_ok=True)
            info = _stat(part)
        if not stat.S_ISDIR(info.st_mode):
            raise ArchiveError(f"expected a directory: {part}")
    return path


def _portable_part(part: str) -> bool:
    return (
        bool(part)
        and not part.endswith((".", " "))
        and not any(ord(c) < 32 or c in '<>:"\\|?*' for c in part)
        and not DEVICE_NAME.fullmatch(part.split(".")[0])
    )


def _inventory(directory: Path) -> dict[str, Path]:
    """Inventory files without following directory aliases or accepting case collisions."""
    files = {}
    pending = [directory]
    while pending:
        folder = pending.pop()
        names = set()
        for path in folder.iterdir():
            if not _portable_part(path.name) or path.name.casefold() in names:
                raise ArchiveError(f"nonportable or colliding name: {path}")
            names.add(path.name.casefold())
            if stat.S_ISDIR(_stat(path).st_mode):
                pending.append(path)
            else:
                files[path.relative_to(directory).as_posix()] = path
    return files


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _read_json(path: Path) -> dict:
    if not stat.S_ISREG(_stat(path).st_mode):
        raise ArchiveError(f"expected a JSON file: {path}")
    return _json_object(path.read_bytes(), label=str(path))


def _json_object(data: bytes, *, label: str = "input") -> dict:
    def unique_object(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ArchiveError("duplicate JSON key")
        return result

    def reject_constant(_value):
        raise ArchiveError("nonfinite JSON number")

    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                       parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ArchiveError(f"expected a JSON object: {label}")
    return value


def _is_fixture_path(relative) -> bool:
    return (
        isinstance(relative, str)
        and relative.startswith("tests/fixtures/battles/")
        and relative.endswith(".yaml")
        and all(_portable_part(part) for part in relative.split("/"))
    )


def _fixture_files(manifest: dict) -> set[str]:
    files = set()
    for fixture in manifest["fixtures"]:
        if "path" in fixture:
            relative = fixture["path"]
            if not _is_fixture_path(relative):
                raise ArchiveError("invalid campaign fixture path")
            files.add("inputs/" + relative)
    return files


def _file_entries(files: dict[str, Path]) -> dict:
    entries = {}
    for name, path in files.items():
        with path.open("rb") as handle:
            entries[name] = dict(size_bytes=os.fstat(handle.fileno()).st_size,
                                 sha256=hashlib.file_digest(handle, "sha256").hexdigest())
    return entries


def _matches(pattern: re.Pattern, value) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _validate_file_entries(files: dict) -> None:
    for entry in files.values():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"size_bytes", "sha256"}
            or type(entry["size_bytes"]) is not int
            or entry["size_bytes"] < 0
            or not _matches(DIGEST, entry["sha256"])
        ):
            raise ArchiveError("invalid snapshot file entry")


def _identified(description: dict) -> dict:
    return dict(description, package_id=hashlib.sha256(_canonical(description)).hexdigest())


# === SECTION: historical adapters (read their own formats without loading the app) ===
def _history_files(directory: Path, expected: set[str]) -> dict[str, Path]:
    files = {path.name: path for path in directory.iterdir()}
    if files.keys() != expected:
        raise ArchiveError("historical file set does not match the selected format")
    for path in files.values():
        if not stat.S_ISREG(_stat(path).st_mode):
            raise ArchiveError(f"expected a regular historical file: {path}")
    return files


def _recorded_revision(*values) -> str | None:
    revisions = [value for value in values if value is not None]
    if any(not _matches(REVISION, value) for value in revisions) or len(set(revisions)) > 1:
        raise ArchiveError("invalid or conflicting historical revisions")
    return next(iter(revisions), None)


def _digest_map_recorded(value) -> bool:
    if value is None:
        return False
    if not isinstance(value, dict) or any(not _matches(DIGEST, digest) for digest in value.values()):
        raise ArchiveError("invalid recorded source fingerprints")
    return bool(value)


def _trial_counts(rows: list, identity: Callable[[dict], object], timings_field: str) -> tuple[int, int | None]:
    if not isinstance(rows, list) or not rows:
        raise ArchiveError("historical results require rows for each case type")
    case_ids = set()
    timing_counts = []
    for row in rows:
        case_id = _canonical(identity(row))
        if case_id in case_ids or not isinstance(row["result"], dict) or type(row["reproducible"]) is not bool:
            raise ArchiveError("duplicate or malformed historical case")
        case_ids.add(case_id)
        timings = row.get(timings_field)
        if timings is not None and (not isinstance(timings, list) or not timings):
            raise ArchiveError("invalid historical timing samples")
        timing_counts.append(len(timings) if timings is not None else None)
    return len(case_ids), None if None in timing_counts else sum(timing_counts)


def _deployment_history(manifest: dict, results: dict, manifest_path: Path) -> dict:
    metadata = results.get("metadata", {})
    revision = _recorded_revision(manifest.get("base_commit"), metadata.get("base_commit"))
    repeats = manifest.get("repeats")
    if repeats is not None and (type(repeats) is not int or repeats < 1):
        raise ArchiveError("invalid historical repeats")
    binding = "unknown"
    claimed = metadata.get("manifest_sha256")
    if claimed is not None:
        raw = manifest_path.read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        for data, method in ((raw, "file_sha256"), (lf, "lf_sha256"), (lf.replace(b"\n", b"\r\n"), "crlf_sha256")):
            if hashlib.sha256(data).hexdigest() == claimed:
                binding = method
                break
        else:
            raise ArchiveError("historical manifest SHA-256 mismatch")
    counts, samples = _trial_counts(results["records"], lambda row: row["case"]["id"], "timings")
    if counts != results["summary"]["cases"]:
        raise ArchiveError("historical deployment case count mismatch")
    return dict(recorded_revision=revision, scenarios=[item["id"] for item in manifest["fixtures"]],
                case_counts={"deployment": counts}, timing_samples={"deployment": samples},
                declared_repeats=repeats, manifest_binding=binding,
                source_fingerprints=_digest_map_recorded(metadata.get("sources")))


def _bots_audit_history(manifest: dict, results: dict) -> dict:
    if results.get("schema") != "szop.bots_audit.results/v1":
        raise ArchiveError("unsupported historical audit result schema")
    bindings = []
    if results.get("manifest") is not None:
        if _canonical(results["manifest"]) != _canonical(manifest):
            raise ArchiveError("embedded historical audit manifest mismatch")
        bindings.append("embedded_manifest")
    if results.get("manifest_digest") is not None:
        if hashlib.sha256(_canonical(manifest)).hexdigest() != results["manifest_digest"]:
            raise ArchiveError("historical audit manifest digest mismatch")
        bindings.append("canonical_sha256")
    counts, samples = {}, {}
    for kind, (field, identity_fields) in AUDIT_GROUPS.items():
        counts[kind], samples[kind] = _trial_counts(
            results[field], lambda row: [row[key] for key in identity_fields], "timings_ms")
        if counts[kind] != results["summary"][kind + "_cases"]:
            raise ArchiveError(f"historical audit {kind} case count mismatch")
    return dict(recorded_revision=_recorded_revision(results.get("base_commit")), scenarios=manifest["scenarios"],
                case_counts=counts, timing_samples=samples, declared_repeats=None,
                manifest_binding="+".join(bindings) or "unknown",
                source_fingerprints=_matches(DIGEST, results.get("script_sha256"))
                and _digest_map_recorded(results.get("fixture_sha256")))


def _describe_history(snapshot: Path, kind: str) -> dict:
    schema, expected = HISTORY_FORMATS[kind]
    files = _history_files(snapshot, expected)
    manifest = _read_json(files["manifest.json"])
    results = _read_json(files["results.json"])
    if manifest.get("schema") != schema:
        raise ArchiveError("historical manifest schema does not match the selected type")
    for name in expected - {"manifest.json", "results.json"}:
        if name.endswith(".json"):
            _read_json(files[name])
    metadata = (_deployment_history(manifest, results, files["manifest.json"]) if kind == DEPLOYMENT_TYPE
                else _bots_audit_history(manifest, results))
    scenarios = metadata.pop("scenarios")
    if not isinstance(scenarios, list) or not scenarios or any(not isinstance(item, str) for item in scenarios):
        raise ArchiveError("invalid historical scenarios")
    evidence = dict(kind="historical_results", campaign_journal=False,
                    manifest_binding=metadata.pop("manifest_binding"),
                    source_fingerprints="recorded" if metadata.pop("source_fingerprints") else "unknown")
    return _identified(dict(schema=PACKAGE_SCHEMA, type=kind, source_schema=schema,
                            scenarios=sorted(set(scenarios)), evidence=evidence, files=_file_entries(files),
                            **metadata))


# === SECTION: package validation and rebuildable catalog ===
def _describe(snapshot: Path, committed: int, planned: int) -> dict:
    files = _inventory(snapshot)
    header = _read_json(snapshot / "header.json")
    manifest = _read_json(snapshot / "manifest.json")
    if set(files) != CAMPAIGN_FILES | _fixture_files(manifest):
        raise ArchiveError("snapshot file set does not match campaign format")
    description = dict(
        schema=PACKAGE_SCHEMA, type=PACKAGE_TYPE, source_schema=header["schema"],
        campaign_id=header["campaign_id"], recorded_revision=header["base_commit"],
        scenarios=sorted({entry["id"] for entry in manifest["fixtures"]}),
        committed_cases=committed, planned_cases=planned,
        completeness="complete" if committed == planned else "partial",
        files=_file_entries(files),
    )
    return _identified(description)


def _read_descriptor(package: Path, package_id: str) -> dict:
    if not stat.S_ISDIR(_stat(package).st_mode):
        raise ArchiveError(f"expected a package directory: {package}")
    descriptor = _read_json(package / DESCRIPTOR)
    identity = dict(descriptor)
    actual_id = identity.pop("package_id", None)
    if actual_id != package_id or hashlib.sha256(_canonical(identity)).hexdigest() != package_id:
        raise ArchiveError("package descriptor does not match its ID")
    kind = descriptor.get("type")
    if isinstance(kind, str) and kind in HISTORY_FORMATS:
        schema, expected = HISTORY_FORMATS[kind]
        if set(identity) != {
            "schema", "type", "source_schema", "recorded_revision", "scenarios", "case_counts",
            "timing_samples", "declared_repeats", "evidence", "files",
        } or (descriptor["schema"], descriptor["source_schema"]) != (PACKAGE_SCHEMA, schema):
            raise ArchiveError("unsupported historical package descriptor")
        files = descriptor["files"]
        if not isinstance(files, dict) or files.keys() != expected:
            raise ArchiveError("invalid historical file set in descriptor")
        scenarios = descriptor["scenarios"]
        if not isinstance(scenarios, list) or any(not isinstance(item, str) for item in scenarios):
            raise ArchiveError("invalid historical scenarios in descriptor")
        _validate_file_entries(files)
        return descriptor
    if set(identity) != {
        "schema", "type", "source_schema", "campaign_id", "recorded_revision", "scenarios",
        "committed_cases", "planned_cases", "completeness", "files",
    } or (descriptor["schema"], descriptor["type"], descriptor["source_schema"]) != (
        PACKAGE_SCHEMA, PACKAGE_TYPE, CAMPAIGN_SCHEMA,
    ):
        raise ArchiveError("unsupported package descriptor")
    committed, planned = descriptor["committed_cases"], descriptor["planned_cases"]
    scenarios = descriptor["scenarios"]
    if (
        not _matches(DIGEST, descriptor["campaign_id"])
        or not _matches(REVISION, descriptor["recorded_revision"])
        or not isinstance(scenarios, list)
        or not scenarios
        or any(not isinstance(item, str) for item in scenarios)
        or scenarios != sorted(set(scenarios))
        or type(committed) is not int
        or type(planned) is not int
        or not (0 <= committed <= planned and planned > 0)
        or descriptor["completeness"] != ("complete" if committed == planned else "partial")
    ):
        raise ArchiveError("invalid package metadata")
    files = descriptor["files"]
    if not isinstance(files, dict) or not CAMPAIGN_FILES <= files.keys():
        raise ArchiveError("missing required snapshot files in descriptor")
    for name in files:
        if name not in CAMPAIGN_FILES and not (
            name.startswith("inputs/") and _is_fixture_path(name.removeprefix("inputs/"))
        ):
            raise ArchiveError("invalid snapshot path in descriptor")
    _validate_file_entries(files)
    return descriptor


def _verify_package(package: Path, package_id: str) -> dict:
    descriptor = _read_descriptor(package, package_id)
    if {child.name for child in package.iterdir()} != {DESCRIPTOR, SNAPSHOT}:
        raise ArchiveError("unexpected file set in package directory")
    snapshot = _directory(package / SNAPSHOT)
    # Only actual files within the package are opened. Descriptor keys are never paths.
    kind = descriptor["type"]
    actual = (_describe_history(snapshot, kind) if kind in HISTORY_FORMATS
              else _describe(snapshot, descriptor["committed_cases"], descriptor["planned_cases"]))
    if actual != descriptor:
        raise ArchiveError("snapshot content or metadata does not match package descriptor")
    return descriptor


def list_packages(root: Path, *, package_id=None, kind=None, scenario=None, revision=None) -> list[dict]:
    packages = _directory(_directory(root) / "packages")
    entries = []
    for path in sorted(packages.iterdir()):
        if path.name.startswith(".import-"):
            continue
        if not _matches(DIGEST, path.name):
            raise ArchiveError(f"unexpected entry in package catalog: {path.name}")
        if package_id is not None and path.name != package_id:
            continue
        entry = _read_descriptor(path, path.name)
        if (
            (kind is None or entry["type"] == kind)
            and (scenario is None or scenario in entry["scenarios"])
            and (revision is None or entry["recorded_revision"] == revision)
        ):
            entries.append(entry)
    return entries


def verify_package(root: Path, package_id: str) -> dict:
    if not _matches(DIGEST, package_id):
        raise ArchiveError("package ID must contain 64 lowercase hex characters")
    packages = _directory(_directory(root) / "packages")
    return _verify_package(packages / package_id, package_id)


# === SECTION: atomic publication for campaign and historical packages ===
def _check_lock(directory: Path) -> None:
    path = directory / ".lock"
    if os.path.lexists(path) and not stat.S_ISREG(_stat(path).st_mode):
        raise ArchiveError(f"expected a regular lock file: {path}")


@contextmanager
def _staged_package(root: Path):
    from scripts import campaign_v1 as campaign

    root = _directory(root, create=True)
    _check_lock(root)

    with campaign.locked(root):
        packages = _directory(root / "packages", create=True)
        with TemporaryDirectory(dir=packages, prefix=".import-") as work:
            staging = Path(work) / "package"
            staging.mkdir()
            yield packages, staging


def _publish(packages: Path, staging: Path, descriptor: dict) -> tuple[dict, bool]:
    from scripts import campaign_v1 as campaign

    package_id = descriptor["package_id"]
    campaign.atomic_write(staging / DESCRIPTOR, _canonical(descriptor) + b"\n")
    _read_descriptor(staging, package_id)
    destination = packages / package_id
    if os.path.lexists(destination):
        # Check the existing bytes before reporting successful deduplication.
        return _verify_package(destination, package_id), False
    staging.rename(destination)
    campaign.sync_directory(packages)
    return descriptor, True


def _separate_archive(root: Path, source: Path) -> Path:
    root = Path(os.path.abspath(root))
    if root.is_relative_to(source) or source.is_relative_to(root):
        raise ArchiveError("source and archive must occupy separate directory trees")
    return root


def import_campaign(root: Path, source: Path) -> tuple[dict, bool]:
    from scripts import campaign_v1 as campaign

    source = _directory(source)
    root = _separate_archive(root, source)
    _check_lock(source)
    with _staged_package(root) as (packages, staging):
        snapshot = staging / SNAPSHOT
        with campaign.locked(source):
            _inventory(source)
            header = _read_json(source / "header.json")
            manifest = _read_json(source / "manifest.json")
            if not isinstance(header.get("inputs"), dict) or set(header["inputs"]) != _fixture_files(manifest):
                raise ArchiveError("unexpected frozen input list")
            # Native archive rebuilds the derived report, checks compatibility
            # and the journal chain, and copies under both campaign locks.
            campaign.archive(source, snapshot)
        with campaign.locked(snapshot):
            copied_header, copied_manifest, rows, *_ = campaign.inspect(snapshot)
            campaign.verify_derived(snapshot, copied_header)
        (snapshot / ".lock").unlink()
        planned = sum(1 for _ in campaign.experiment.iter_cases(copied_manifest))
        return _publish(packages, staging, _describe(snapshot, len(rows), planned))


def import_history(root: Path, kind: str, source: Path, *, report: Path | None = None) -> tuple[dict, bool]:
    from scripts import campaign_v1 as campaign

    if kind not in HISTORY_FORMATS:
        raise ArchiveError("unsupported historical experiment type")
    if (kind == BOTS_AUDIT_TYPE) != (report is not None):
        raise ArchiveError(f"only {BOTS_AUDIT_TYPE} requires --report")
    source = _directory(source)
    root = _separate_archive(root, source)
    _, expected = HISTORY_FORMATS[kind]
    files = _history_files(source, expected - {BOTS_REPORT})
    if report is not None:
        report = _directory(report.parent) / report.name
        if report.name != BOTS_REPORT or report.is_relative_to(root) or not stat.S_ISREG(_stat(report).st_mode):
            raise ArchiveError(f"expected a regular {BOTS_REPORT} outside the archive")
        files[BOTS_REPORT] = report

    with _staged_package(root) as (packages, staging):
        snapshot = staging / SNAPSHOT
        snapshot.mkdir()
        original = _file_entries(files)
        for name, path in files.items():
            campaign.atomic_write(snapshot / name, path.read_bytes())
        descriptor = _describe_history(snapshot, kind)
        if descriptor["files"] != original:
            raise ArchiveError("historical source changed during import")
        return _publish(packages, staging, descriptor)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "import-history", "list", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--archive-root", type=Path, required=True)
        if name == "import":
            command.add_argument("--campaign", type=Path, required=True)
        elif name == "import-history":
            command.add_argument("--type", choices=sorted(HISTORY_FORMATS), required=True)
            command.add_argument("--experiment", type=Path, required=True)
            command.add_argument("--report", type=Path)
        else:
            command.add_argument("--package-id", required=name == "verify")
        if name == "list":
            command.add_argument("--type")
            command.add_argument("--scenario")
            command.add_argument("--revision")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            descriptor, created = import_campaign(args.archive_root, args.campaign)
            result = dict(created=created, package=descriptor)
        elif args.command == "import-history":
            descriptor, created = import_history(args.archive_root, args.type, args.experiment, report=args.report)
            result = dict(created=created, package=descriptor)
        elif args.command == "verify":
            result = dict(verified=True, package=verify_package(args.archive_root, args.package_id))
        else:
            if args.package_id is not None and not _matches(DIGEST, args.package_id):
                raise ArchiveError("package ID must contain 64 lowercase hex characters")
            result = dict(packages=list_packages(args.archive_root, package_id=args.package_id,
                                                kind=args.type, scenario=args.scenario, revision=args.revision))
        print(_canonical(result).decode("ascii"))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError) as exc:
        print(_canonical(dict(status="error", error=str(exc))).decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
