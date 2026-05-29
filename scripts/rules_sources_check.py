"""Verify SHA256 checksums of canonical SZOP source files.

Czwarty skrypt pipeline'u A4 (ADR-0006 drift-only). Wykrywa **silent edit**
plików źródłowych (`SZOP.docx`, `SZOP.pdf`, `SZOP_Zdolnosci.md`,
`SZOP_Rozjemca.md`) — typowa klasa bugów gdy ktoś podmienia PDF bez
aktualizacji DOCX, lub edytuje MD bez zmiany YAML mirror.

Centralna lokalizacja hashes: `app/rulesets/v1/source_hashes.yaml` (decyzja
A4.4 — alternatywa odrzucona: per-file `*.sha256` z exception w `.gitignore`,
bo `app/static/docs/` jest cały gitignored).

Tryby:
- **check (default):** porównuje hashes z bieżącymi plikami → exit 0/1/2.
- **--update:** liczy bieżące hashes i nadpisuje `source_hashes.yaml`.
  Używane po świadomej zmianie source files (np. nowa edycja DOCX/MD).

Exit codes:
- `0` — wszystkie hashes zgadzają się (clean).
- `1` — co najmniej jeden mismatch (silent edit detected — wymaga review).
- `2` — co najmniej jeden source file missing (nie istnieje).

Użycie:
    python scripts/rules_sources_check.py
    python scripts/rules_sources_check.py --update
    python scripts/rules_sources_check.py --hashes app/rulesets/v1/source_hashes.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_HASHES = Path("app/rulesets/v1/source_hashes.yaml")
HASH_VERSION = 1


# --- Schema -----------------------------------------------------------------

class CheckStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"


@dataclass(frozen=True)
class SourceEntry:
    """Jeden rekord z `source_hashes.yaml`."""

    path: str  # relatywna ścieżka od project root, slash-normalized
    sha256: str
    role: str  # opis przeznaczenia pliku (do report'u)


@dataclass(frozen=True)
class CheckResult:
    entry: SourceEntry
    status: CheckStatus
    actual_sha256: str | None  # None gdy plik brakuje


# --- Hash computation -------------------------------------------------------

_CHUNK = 65536


def compute_sha256(path: Path) -> str:
    """SHA256 hex digest. Streamuje 64KB chunks dla dużych plików."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Loader -----------------------------------------------------------------

def load_hashes(path: Path) -> list[SourceEntry]:
    """Załaduj `source_hashes.yaml`. Brak pliku → empty list (do --update)."""
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    entries = []
    for raw in data.get("sources", []):
        entries.append(
            SourceEntry(
                path=raw["path"],
                sha256=raw["sha256"],
                role=raw.get("role", "(no role)"),
            )
        )
    return entries


def save_hashes(path: Path, entries: list[SourceEntry]) -> None:
    """Persist `source_hashes.yaml` (przez `--update`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": HASH_VERSION,
        "sources": [
            {"path": e.path, "sha256": e.sha256, "role": e.role}
            for e in entries
        ],
    }
    header = (
        "# SHA256 checksums of canonical SZOP source files.\n"
        "# Regenerated via: python scripts/rules_sources_check.py --update\n"
        "# Verified via:   python scripts/rules_sources_check.py\n\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False, width=10000)


# --- Check -----------------------------------------------------------------

def check_entries(entries: list[SourceEntry], project_root: Path) -> list[CheckResult]:
    """Porównaj zapisane hashes z bieżącymi plikami."""
    results = []
    for entry in entries:
        # Path w YAML jest slash-normalized od project root.
        full_path = project_root / entry.path
        if not full_path.exists():
            results.append(CheckResult(entry=entry, status=CheckStatus.MISSING, actual_sha256=None))
            continue

        actual = compute_sha256(full_path)
        if actual == entry.sha256:
            status = CheckStatus.MATCH
        else:
            status = CheckStatus.MISMATCH
        results.append(CheckResult(entry=entry, status=status, actual_sha256=actual))
    return results


def exit_code_from_results(results: list[CheckResult]) -> int:
    """0=clean, 1=mismatch, 2=missing (missing wygrywa nad mismatch)."""
    has_missing = any(r.status == CheckStatus.MISSING for r in results)
    has_mismatch = any(r.status == CheckStatus.MISMATCH for r in results)
    if has_missing:
        return 2
    if has_mismatch:
        return 1
    return 0


# --- Update mode -----------------------------------------------------------

# Domyślne źródła do trackowania (sequence wzbogacany przez --update gdy plik
# istnieje; brakujące pomijane z warning).
DEFAULT_SOURCES: tuple[tuple[str, str], ...] = (
    ("app/static/docs/SZOP.docx", "Word document — primary author source"),
    ("app/static/docs/SZOP.pdf", "PDF export — should track DOCX changes"),
    ("app/static/docs/SZOP_Zdolnosci.md", "Curated MD version of abilities — 1:1 quotes from SZOP"),
    ("app/static/docs/SZOP_Rozjemca.md", "Game rules narrative (referee version)"),
)


def compute_current_entries(
    project_root: Path,
    existing: list[SourceEntry] | None = None,
) -> list[SourceEntry]:
    """Wygeneruj fresh hashes dla `DEFAULT_SOURCES` + zachowaj `role` z `existing` jeśli był."""
    role_by_path: dict[str, str] = {}
    if existing is not None:
        for e in existing:
            role_by_path[e.path] = e.role

    entries = []
    for path_str, default_role in DEFAULT_SOURCES:
        full_path = project_root / path_str
        if not full_path.exists():
            print(f"WARNING: source missing, skipped: {path_str}", file=sys.stderr)
            continue
        sha = compute_sha256(full_path)
        role = role_by_path.get(path_str, default_role)
        entries.append(SourceEntry(path=path_str, sha256=sha, role=role))
    return entries


# --- CLI -------------------------------------------------------------------

def _print_results(results: list[CheckResult]) -> None:
    """Krótki summary do stderr (per linia: STATUS path)."""
    for r in results:
        if r.status == CheckStatus.MATCH:
            print(f"  OK       {r.entry.path}", file=sys.stderr)
        elif r.status == CheckStatus.MISMATCH:
            print(
                f"  MISMATCH {r.entry.path}\n"
                f"    expected: {r.entry.sha256}\n"
                f"    actual:   {r.actual_sha256}",
                file=sys.stderr,
            )
        elif r.status == CheckStatus.MISSING:
            print(f"  MISSING  {r.entry.path} — file not found", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify SHA256 checksums of canonical SZOP source files (ADR-0006).",
    )
    parser.add_argument(
        "--hashes",
        type=Path,
        default=DEFAULT_HASHES,
        help="Path to source_hashes.yaml (default: app/rulesets/v1/source_hashes.yaml)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate hashes from current source files (overrides stored hashes).",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="Project root (for resolving relative source paths). Default: script's parent dir.",
    )
    args = parser.parse_args(argv)

    if args.update:
        existing = load_hashes(args.hashes)
        fresh = compute_current_entries(args.project_root, existing=existing)
        save_hashes(args.hashes, fresh)
        print(f"Updated {len(fresh)} hashes → {args.hashes}", file=sys.stderr)
        return 0

    entries = load_hashes(args.hashes)
    if not entries:
        print(
            f"ERROR: no hashes loaded from {args.hashes}. "
            f"Run with --update to generate initial hashes.",
            file=sys.stderr,
        )
        return 2

    results = check_entries(entries, args.project_root)
    _print_results(results)

    code = exit_code_from_results(results)
    summary = {0: "CLEAN", 1: "MISMATCH", 2: "MISSING"}[code]
    print(
        f"Source check: {len(results)} files, {summary} (exit {code})",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
