"""Run and compare the bounded D7.4c pilot and verify a separate archive copy."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/experiments/d7_1/manifest.json"
CAMPAIGN = ROOT / "scripts/campaign_v1.py"
ARCHIVE = ROOT / "scripts/experiment_archive.py"
QUALITY = ROOT / "scripts/experiment_quality.py"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def execute(script, *args, codes=(0,), isolated=False, parse=True):
    start = perf_counter()
    flags = ["-I", "-S"] if isolated else []
    completed = subprocess.run([sys.executable, *flags, "-B", "-X", "utf8", str(script), *map(str, args)],
                               cwd=script.parent.parent, capture_output=True, encoding="utf-8", timeout=180)
    if completed.returncode not in codes:
        raise RuntimeError(f"{script.name} {args[0]}: {completed.stdout}\n{completed.stderr}")
    return (json.loads(completed.stdout) if parse else completed.stdout), round((perf_counter() - start) * 1000, 2)


def checksums(directory):
    return {p.relative_to(directory).as_posix(): digest(p.read_bytes())
            for p in directory.rglob("*") if p.is_file() and p.name != ".lock"}


def case_data(directory):
    results, stable_files, sizes = [], [], []
    for line in (directory / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)["row"]
        results.append({key: row[key] for key in ("case", "result", "reproducible")})
        link = row["decision_trace"]
        for repeat, entry in enumerate(link["repeats"], 1):
            if entry["status"] != "verified":
                raise RuntimeError(f"missing verified trace for {row['case']['id']} repeat {repeat}")
            path = directory / "traces" / link["attempt"] / str(repeat)
            raw_meta = (path / "export.json").read_bytes()
            if digest(raw_meta) != entry["descriptor_sha256"]:
                raise RuntimeError("decision export descriptor changed")
            meta = json.loads(raw_meta)
            data = {name: (path / name).read_bytes() for name in meta["files"]}
            stable_files.append({name: digest(value) for name, value in data.items()})
            sizes.append(dict(bytes=len(raw_meta) + sum(map(len, data.values())), **meta["counts"]))
    return results, stable_files, sizes


def publish(root, campaign, output, *, code=0):
    imported, import_ms = execute(ARCHIVE, "import", "--archive-root", root, "--campaign", campaign)
    package = imported["package"]
    quality, quality_ms = execute(QUALITY, "--archive-root", root, "--package-id", package["package_id"],
                                  "--output-root", output, codes=(code,), isolated=True)
    return package, quality, {"import_ms": import_ms, "quality_ms": quality_ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copy", type=Path, required=True)
    parser.add_argument("--fresh-checkout", type=Path, required=True)
    args = parser.parse_args()
    out, backup, fresh = (path.resolve() for path in (args.output, args.copy, args.fresh_checkout))
    if out.exists() or backup.exists() or out == backup or out.is_relative_to(backup) or backup.is_relative_to(out):
        raise RuntimeError("choose separate, new output and backup paths")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    checkout_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fresh, text=True).strip()
    if revision != checkout_revision or fresh == ROOT:
        raise RuntimeError("a separate checkout at the pilot source revision is required")
    out.mkdir(parents=True)
    catalog, reports = out / "catalog", out / "reports"
    full, full_ms = execute(CAMPAIGN, "start", "--manifest", MANIFEST, "--directory", out / "full",
                           "--decision-trace", "d7-4c-full", "--max-cases", 32)
    stop, stop_ms = execute(CAMPAIGN, "start", "--manifest", MANIFEST, "--directory", out / "split",
                           "--decision-trace", "d7-4c-split", "--max-cases", 8, codes=(2,))
    stopped, stopped_quality, stopped_ms = publish(catalog, out / "split", reports, code=2)
    resume, resume_ms = execute(CAMPAIGN, "resume", "--directory", out / "split", "--max-cases", 24)
    before = checksums(out / "split")
    noop, noop_ms = execute(CAMPAIGN, "resume", "--directory", out / "split", "--max-cases", 32)
    if noop["committed"] or checksums(out / "split") != before:
        raise RuntimeError("completed resume changed the campaign")
    full_cases, full_traces, _ = case_data(out / "full")
    cases, stable_traces, sizes = case_data(out / "split")
    if cases != full_cases or stable_traces != full_traces or (len(cases), len(stable_traces)) != (32, 64):
        raise RuntimeError("full and resumed campaigns differ")

    package, quality, publication_ms = publish(catalog, out / "split", reports)
    key = package["package_id"]
    retried, duplicate_ms = execute(ARCHIVE, "import", "--archive-root", catalog, "--campaign", out / "split")
    if retried != {"created": False, "package": package}:
        raise RuntimeError("duplicate import changed the catalog")
    copied = backup / "packages" / key
    shutil.copytree(catalog / "packages" / key, copied)
    verification, copied_ms = execute(fresh / "scripts/experiment_archive.py", "verify", "--archive-root", backup,
                                      "--package-id", key, isolated=True)
    if verification["package"] != package:
        raise RuntimeError("archive copy differs")
    copied_quality, copied_quality_ms = execute(fresh / "scripts/experiment_quality.py", "--archive-root", backup,
                                               "--package-id", key, "--output-root", out / "copy-reports",
                                               isolated=True)
    report = Path(quality["path"]).read_bytes()
    if Path(copied_quality["path"]).read_bytes() != report:
        raise RuntimeError("fresh checkout evaluated the copy differently")
    verified_executions = list((copied / "snapshot/traces").glob("*/*/export.json"))
    if len(verified_executions) != 64:
        raise RuntimeError("archive copy has the wrong execution count")
    # Quality checks every descriptor and payload hash. Exercise the independent
    # simulator replay and expansion from the copy on a fixed case and repeat.
    first_line = (copied / "snapshot/journal.jsonl").read_bytes().splitlines()[0]
    attempt = json.loads(first_line)["row"]["decision_trace"]["attempt"]
    example = copied / "snapshot/traces" / attempt / "1"
    expanded, expand_ms = execute(fresh / "scripts/export_decisions.py", "expand", example, parse=False)
    decisions = [json.loads(line) for line in expanded.splitlines()]
    if not any(row["observation"]["kind"] in ("choose_action", "continue_activation")
               and row["states"]["seen"] and row["events"] for row in decisions):
        raise RuntimeError("decision with real state and consequences was not recovered")

    bad_manifest = out / "partial.json"
    bad = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad["max_activations"] = 1
    bad_manifest.write_text(json.dumps(bad), encoding="utf-8")
    execute(CAMPAIGN, "start", "--manifest", bad_manifest, "--directory", out / "error",
            "--decision-trace", "d7-4c-error", "--max-cases", 1, codes=(2,))
    error, error_quality, error_ms = publish(catalog, out / "error", reports, code=2)
    if error_quality["coverage"]["reasons"].get("incomplete_decision_trace") != 1:
        raise RuntimeError("failure did not retain and exclude the incomplete trace")

    trace_bytes = sum(s["bytes"] for s in sizes)
    summary = dict(
        source_revision=revision, campaign_id=resume["campaign_id"], manifest_sha256=digest(MANIFEST.read_bytes()),
        python=platform.python_version(), platform=platform.system(), cases=len(cases), executions=len(sizes),
        stable_rows_sha256=json_digest(cases), stable_file_hashes_sha256=json_digest(stable_traces),
        trace_bytes=trace_bytes, max_execution_bytes=max(s["bytes"] for s in sizes),
        budget_bytes=64 * 256 * 1024, budget_per_execution_bytes=256 * 1024,
        decisions=sum(s["decisions"] for s in sizes), observations=sum(s["observations"] for s in sizes),
        deployment_events=sum(s["deployment_events"] for s in sizes), battle_events=sum(s["battle_events"] for s in sizes),
        bytes_per_decision=round(trace_bytes / sum(s["decisions"] for s in sizes), 2),
        runs={name: dict(committed=run["committed"], wall_ms=ms) for name, run, ms in (
            ("full", full, full_ms), ("stop", stop, stop_ms), ("resume", resume, resume_ms), ("noop", noop, noop_ms))},
        full_split_equal=True, noop_byte_identical=True, duplicate_same_package=True,
        package=dict(id=key, bytes=sum(entry["size_bytes"] for entry in package["files"].values()),
                     quality_sha256=digest(report), quality=quality["coverage"], duplicate_ms=duplicate_ms,
                     **publication_ms),
        stopped=dict(id=stopped["package_id"], quality=stopped_quality["coverage"], **stopped_ms),
        copy=dict(quality_byte_identical=True, verify_ms=copied_ms, quality_ms=copied_quality_ms,
                  expanded_rows=len(decisions), expand_ms=expand_ms),
        error=dict(id=error["package_id"], quality=error_quality["coverage"], **error_ms),
    )
    (out / "results.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
