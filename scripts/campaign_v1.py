"""Durable, sequential v1 campaigns over the unchanged D5.3b adapter."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from time import perf_counter
import uuid

ROOT = Path(__file__).resolve().parent.parent
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import deployment_experiment as experiment  # noqa: E402

SCHEMA = "szop.campaign/v1"
RECORD_SCHEMA = "szop.campaign.record/v1"
FAILURES = {"non_reproducible", "replay_error", "invariant_error", "harness_error"}
RESULT_STATUSES = {"complete", "deployment_error", "match_error", "activation_cap",
                   "replay_error", "invariant_error", "harness_error"}
BASE_FILES = {"manifest.json", "header.json", "journal.jsonl"}
DERIVED_FILES = {"report.md", "checksums.json"}


class CampaignError(ValueError):
    """Invalid or incompatible campaign; no silent repair/retry."""


# === SECTION: canonical serialization, safe paths and process locking ===
def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_read(path: Path):
    def reject_constant(value):
        raise CampaignError("nonfinite JSON")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def plain_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise CampaignError("expected a regular file: " + str(path))
    return path


def contained_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise CampaignError("invalid relative path")
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise CampaignError("path outside allowed input directory")
    if not path.resolve().is_relative_to(root.resolve()):
        raise CampaignError("path outside allowed input directory")
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise CampaignError("symlinks are not campaign inputs")
    return plain_file(path)


@contextmanager
def locked(directory: Path):
    if directory.is_symlink() or not directory.is_dir():
        raise CampaignError("campaign directory must be a real directory")
    path = directory / ".lock"
    if path.is_symlink():
        raise CampaignError("invalid lock path")
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CampaignError("campaign busy: another process holds the lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def sync_directory(path: Path) -> None:
    # Windows has no portable stdlib directory fsync. File fsync is still used.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


# === SECTION: manifest, frozen inputs and semantic source compatibility ===
def load_manifest(path: Path) -> dict:
    manifest = experiment.load_manifest(plain_file(path))
    for fixture in manifest["fixtures"]:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str):
            raise CampaignError("invalid fixture")
        if "path" in fixture:
            if set(fixture) != {"id", "path"}:
                raise CampaignError("invalid file fixture")
            path = contained_file(ROOT, fixture["path"])
            if not path.resolve().is_relative_to((ROOT / "tests/fixtures/battles").resolve()):
                raise CampaignError("fixture must belong to tests/fixtures/battles")
            if path.suffix != ".yaml":
                raise CampaignError("fixture must be YAML")
        elif (set(fixture) != {"id", "map", "map_seed"}
              or fixture["map"] not in experiment.bsim.MAP_BUILDERS
              or type(fixture["map_seed"]) is not int or fixture["map_seed"] < 0):
            raise CampaignError("invalid map fixture")
    return manifest


def environment() -> dict:
    return dict(python=platform.python_version(), platform=platform.platform())


def compatibility(manifest: dict) -> dict:
    paths = {Path(__file__).resolve(), ROOT / "scripts/deployment_experiment.py",
             ROOT / "scripts/balance_common.py", ROOT / "scripts/balance_simulate.py"}
    for folder in ("app/services/engine", "app/services/agents", "app/services/rulesets", "app/data"):
        paths.update((ROOT / folder).rglob("*.py"))
    paths.update((ROOT / "app/rulesets/v1").rglob("*.yaml"))
    paths.update(ROOT / f["path"] for f in manifest["fixtures"] if "path" in f)
    sources = {p.relative_to(ROOT).as_posix(): sha(plain_file(p).read_text(encoding="utf-8").encode())
               for p in sorted(paths)}
    return dict(manifest_digest=sha(canonical(manifest)), sources=sources,
                python_family=list(sys.version_info[:2]),
                dependencies={name: version(name) for name in ("pydantic", "pydantic_core", "PyYAML")})


def initialize(directory: Path, manifest_path: Path) -> dict:
    if any(p.name != ".lock" for p in directory.iterdir()):
        raise CampaignError("start requires an empty campaign directory")
    manifest = load_manifest(manifest_path)
    identity = compatibility(manifest)
    inputs = {}
    for fixture in manifest["fixtures"]:
        if "path" in fixture:
            relative = "inputs/" + fixture["path"]
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = contained_file(ROOT, fixture["path"]).read_text(encoding="utf-8").encode()
            atomic_write(target, data)
            inputs[relative] = sha(data)
    atomic_write(directory / "manifest.json", canonical(manifest) + b"\n")
    atomic_write(directory / "journal.jsonl", b"")
    header = dict(schema=SCHEMA, campaign_id=sha(canonical(identity)), identity=identity,
                  inputs=inputs, environment=environment(),
                  base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    atomic_write(directory / "header.json", canonical(dict(header, sha256=sha(canonical(header)))) + b"\n")
    return header


def inspect(directory: Path, *, allow_tail=False):
    header = json_read(plain_file(directory / "header.json"))
    checksum = header.pop("sha256")
    if header["schema"] != SCHEMA or sha(canonical(header)) != checksum:
        raise CampaignError("header integrity mismatch")
    manifest = load_manifest(directory / "manifest.json")
    if sha(canonical(manifest)) != header["identity"]["manifest_digest"]:
        raise CampaignError("manifest integrity mismatch")
    if sha(canonical(header["identity"])) != header["campaign_id"]:
        raise CampaignError("campaign identity mismatch")
    for relative, digest in header["inputs"].items():
        if sha(contained_file(directory, relative).read_bytes()) != digest:
            raise CampaignError("frozen input integrity mismatch")
    allowed = BASE_FILES | DERIVED_FILES | set(header["inputs"]) | {".lock"}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        derived_temporary = re.fullmatch(r"\.(report\.md|checksums\.json)\.[0-9a-f]{32}\.tmp", relative)
        if path.is_symlink() or (path.is_file() and relative not in allowed and not derived_temporary):
            raise CampaignError("unexpected campaign file; inspect before recovery")
    if compatibility(manifest) != header["identity"]:
        raise CampaignError("source/dependency compatibility conflict; start a new campaign")
    cases = list(experiment.iter_cases(manifest))
    rows, previous, valid_bytes = [], header["campaign_id"], 0
    with plain_file(directory / "journal.jsonl").open("rb") as handle:
        for line in handle:
            if not line.endswith(b"\n"):
                if allow_tail:
                    return header, manifest, rows, previous, valid_bytes, True
                raise CampaignError("incomplete journal tail; use repair-tail explicitly")
            try:
                envelope = json.loads(line)
                digest = envelope.pop("sha256")
                row = envelope["row"]
                if (envelope["schema"] != RECORD_SCHEMA or type(envelope["index"]) is not int
                        or envelope["index"] != len(rows)
                        or envelope["previous"] != previous or sha(canonical(envelope)) != digest
                        or len(rows) >= len(cases) or canonical(row["case"]) != canonical(cases[len(rows)])
                        or type(row["reproducible"]) is not bool
                        or row["result"]["status"] not in RESULT_STATUSES
                        or not isinstance(row["timings"], list)):
                    raise CampaignError("journal chain, case or result mismatch")
            except (ValueError, KeyError, TypeError) as exc:
                raise CampaignError("corrupt committed journal record") from exc
            rows.append(row)
            previous = digest
            valid_bytes += len(line)
    return header, manifest, rows, previous, valid_bytes, False


# === SECTION: durable case commits, derived reports and snapshot archives ===
def append_record(directory: Path, row: dict, index: int, previous: str) -> tuple[str, float]:
    start = perf_counter()
    envelope = dict(schema=RECORD_SCHEMA, index=index, previous=previous, row=row,
                    environment=environment())
    digest = sha(canonical(envelope))
    with plain_file(directory / "journal.jsonl").open("ab") as handle:
        handle.write(canonical(dict(envelope, sha256=digest)) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return digest, (perf_counter() - start) * 1000


def outcome(row: dict) -> str:
    return row["result"]["status"] if row["reproducible"] else "non_reproducible"


def rebuild(directory: Path, header: dict, manifest: dict, rows: list) -> dict:
    # Unstable results stay in the denominator, without contributing wins/draws.
    report_rows = [dict(row, result=dict(row["result"], status=outcome(row))) for row in rows]
    summary = experiment.summarize(report_rows)
    summary.update(planned=len(list(experiment.iter_cases(manifest))),
                   campaign_id=header["campaign_id"],
                   campaign_failures=sum(outcome(row) in FAILURES for row in rows))
    report = ("# D7.1 — trwała kampania v1\n\n```json\n"
              + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n\n"
              "Dane implementacji MVP; znane ograniczenia D6.1 obowiązują. "
              "Błędy nie są remisami; powtórzenia sprawdzają determinizm.\n\n"
              + experiment.render_report(report_rows))
    atomic_write(directory / "report.md", report.encode("utf-8"))
    names = BASE_FILES | {"report.md"} | set(header["inputs"])
    checksums = {name: sha(contained_file(directory, name).read_bytes()) for name in sorted(names)}
    atomic_write(directory / "checksums.json", canonical(checksums) + b"\n")
    return summary


def run(directory: Path, max_cases: int) -> tuple[int, dict]:
    start = perf_counter()
    if type(max_cases) is not int or not 1 <= max_cases <= 2048:
        raise CampaignError("max-cases must be in 1..2048")
    header, manifest, rows, previous, _, _ = inspect(directory)
    startup_ms = (perf_counter() - start) * 1000
    cases = list(experiment.iter_cases(manifest))
    committed, persistence_ms = 0, []
    if any(outcome(row) in FAILURES for row in rows):
        return 1, dict(status="failed", committed=0, total=len(rows))
    for case in cases[len(rows):len(rows) + max_cases]:
        try:
            row = experiment.run_case(case, manifest)
        except Exception as exc:
            status = ("replay_error" if isinstance(exc, AssertionError) and "replay" in str(exc)
                      else "invariant_error" if isinstance(exc, AssertionError) else "harness_error")
            row = dict(case=case, result=dict(status=status, error_type=type(exc).__name__),
                       reproducible=True, timings=[])
        previous, elapsed = append_record(directory, row, len(rows), previous)
        rows.append(row)
        committed += 1
        persistence_ms.append(elapsed)
        print(f"committed {len(rows)} {case['id']} {outcome(row)}", file=sys.stderr, flush=True)
        if outcome(row) in FAILURES:
            break
    # A completed resume is a true no-op, including the derived files.
    if committed:
        rebuild(directory, header, manifest, rows)
    failed = any(outcome(row) in FAILURES for row in rows)
    complete = len(rows) == len(cases)
    return (1 if failed else 0 if complete else 2), dict(
        status="failed" if failed else "complete" if complete else "stopped",
        campaign_id=header["campaign_id"], committed=committed, total=len(rows), planned=len(cases),
        startup_ms=startup_ms, persistence_ms=persistence_ms)


def repair_tail(directory: Path) -> dict:
    _, _, rows, _, length, partial = inspect(directory, allow_tail=True)
    if not partial:
        return dict(repaired=False, total=len(rows))
    path = directory / "journal.jsonl"
    # Keep the discarded bytes as an explicit external recovery artifact.
    backup = directory.with_name(directory.name + ".tail-" + uuid.uuid4().hex + ".bin")
    with path.open("rb") as handle:
        handle.seek(length)
        data = handle.read()
    with backup.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    with path.open("r+b") as handle:
        handle.truncate(length)
        handle.flush()
        os.fsync(handle.fileno())
    return dict(repaired=True, total=len(rows), discarded_bytes=len(data), backup=str(backup))


def verify_derived(directory: Path, header: dict) -> None:
    checksums = json_read(plain_file(directory / "checksums.json"))
    expected = BASE_FILES | {"report.md"} | set(header["inputs"])
    if (not isinstance(checksums, dict) or set(checksums) != expected
            or any(sha(contained_file(directory, name).read_bytes()) != digest
                   for name, digest in checksums.items())):
        raise CampaignError("derived artifacts are stale or corrupt; run report to rebuild")


def archive(directory: Path, destination: Path) -> dict:
    header, manifest, rows, _, _, _ = inspect(directory)
    if destination.exists() or destination.is_symlink():
        raise CampaignError("archive destination must not exist")
    if destination.resolve().is_relative_to(directory.resolve()):
        raise CampaignError("archive cannot be inside its campaign")
    rebuild(directory, header, manifest, rows)
    checksums = json_read(directory / "checksums.json")
    destination.mkdir(parents=False)
    with locked(destination):
        for name in (*checksums, "checksums.json"):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(contained_file(directory, name).read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
        for name, digest in checksums.items():
            if sha(contained_file(destination, name).read_bytes()) != digest:
                raise CampaignError("archive copy checksum mismatch")
        sync_directory(destination)
    return dict(archived=str(destination), campaign_id=header["campaign_id"], total=len(rows))


# === SECTION: local CLI; no background scheduling or automatic retries ===
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "resume", "verify", "report", "repair-tail", "archive"):
        child = commands.add_parser(command)
        child.add_argument("--directory", type=Path, required=True)
        if command == "start":
            child.add_argument("--manifest", type=Path, required=True)
        if command in {"start", "resume"}:
            child.add_argument("--max-cases", type=int, required=True)
        if command == "archive":
            child.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            args.directory.mkdir(parents=True, exist_ok=False)
        with locked(args.directory):
            if args.command == "start":
                initialize(args.directory, args.manifest)
            if args.command in {"start", "resume"}:
                code, result = run(args.directory, args.max_cases)
            elif args.command == "repair-tail":
                code, result = 0, repair_tail(args.directory)
            elif args.command == "archive":
                code, result = 0, archive(args.directory, args.destination)
            else:
                header, manifest, rows, _, _, _ = inspect(args.directory)
                if args.command == "verify":
                    verify_derived(args.directory, header)
                result = (rebuild(args.directory, header, manifest, rows) if args.command == "report"
                          else dict(verified=True, campaign_id=header["campaign_id"], total=len(rows)))
                code = 0
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return code
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status="error", error_type=type(exc).__name__, error=str(exc)), ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
