"""Publish and inspect verified D7.1 snapshots in a local experiment archive."""
from __future__ import annotations

import argparse
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

    def unique_object(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ArchiveError("duplicate JSON key")
        return result

    def reject_constant(_value):
        raise ArchiveError("nonfinite JSON number")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                       parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ArchiveError(f"expected a JSON object: {path}")
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


def _validate_file_entries(files) -> None:
    if not isinstance(files, dict) or not CAMPAIGN_FILES <= files.keys():
        raise ArchiveError("missing required snapshot files in descriptor")
    for name, entry in files.items():
        if name not in CAMPAIGN_FILES and not (
            name.startswith("inputs/") and _is_fixture_path(name.removeprefix("inputs/"))
        ):
            raise ArchiveError("invalid snapshot path in descriptor")
        if (
            not isinstance(entry, dict)
            or set(entry) != {"size_bytes", "sha256"}
            or type(entry["size_bytes"]) is not int
            or entry["size_bytes"] < 0
            or not _matches(DIGEST, entry["sha256"])
        ):
            raise ArchiveError("invalid snapshot file entry")


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
    return dict(description, package_id=hashlib.sha256(_canonical(description)).hexdigest())


def _read_descriptor(package: Path, package_id: str) -> dict:
    if not stat.S_ISDIR(_stat(package).st_mode):
        raise ArchiveError(f"expected a package directory: {package}")
    descriptor = _read_json(package / DESCRIPTOR)
    identity = dict(descriptor)
    actual_id = identity.pop("package_id", None)
    if actual_id != package_id or hashlib.sha256(_canonical(identity)).hexdigest() != package_id:
        raise ArchiveError("package descriptor does not match its ID")
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
    _validate_file_entries(descriptor["files"])
    return descriptor


def _verify_package(package: Path, package_id: str) -> dict:
    descriptor = _read_descriptor(package, package_id)
    if {child.name for child in package.iterdir()} != {DESCRIPTOR, SNAPSHOT}:
        raise ArchiveError("unexpected file set in package directory")
    snapshot = _directory(package / SNAPSHOT)
    # Only actual files within the package are opened. Descriptor keys are never paths.
    if _describe(snapshot, descriptor["committed_cases"], descriptor["planned_cases"]) != descriptor:
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


# === SECTION: native campaign import and atomic publication ===
def import_campaign(root: Path, source: Path) -> tuple[dict, bool]:
    from scripts import campaign_v1 as campaign

    source = _directory(source)
    root = Path(os.path.abspath(root))
    # Reject overlap before creating the archive or taking either lock.
    if root.is_relative_to(source) or source.is_relative_to(root):
        raise ArchiveError("campaign and archive must occupy separate directory trees")
    root = _directory(root, create=True)
    for directory in (root, source):
        lock_path = directory / ".lock"
        if os.path.lexists(lock_path) and not stat.S_ISREG(_stat(lock_path).st_mode):
            raise ArchiveError(f"expected a regular lock file: {lock_path}")

    with campaign.locked(root):
        packages = _directory(root / "packages", create=True)
        with TemporaryDirectory(dir=packages, prefix=".import-") as work:
            staging = Path(work) / "package"
            staging.mkdir()
            snapshot = staging / SNAPSHOT
            with campaign.locked(source):
                _inventory(source)
                header = _read_json(source / "header.json")
                manifest = _read_json(source / "manifest.json")
                if not isinstance(header.get("inputs"), dict) or set(header["inputs"]) != _fixture_files(manifest):
                    raise ArchiveError("unexpected frozen input list")
                # Native archive rebuilds the derived report, checks source compatibility
                # and the journal chain, and copies under both campaign locks.
                campaign.archive(source, snapshot)
            with campaign.locked(snapshot):
                copied_header, copied_manifest, rows, *_ = campaign.inspect(snapshot)
                campaign.verify_derived(snapshot, copied_header)
            (snapshot / ".lock").unlink()
            planned = sum(1 for _ in campaign.experiment.iter_cases(copied_manifest))
            descriptor = _describe(snapshot, len(rows), planned)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "list", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--archive-root", type=Path, required=True)
        if name == "import":
            command.add_argument("--campaign", type=Path, required=True)
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
