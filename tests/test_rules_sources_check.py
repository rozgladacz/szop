"""A4.4 — testy `scripts/rules_sources_check.py`.

Pokrycie:
- `compute_sha256` — deterministic hash, identyczny dla tej samej zawartości.
- `load_hashes` / `save_hashes` — round-trip YAML.
- `check_entries` — match/mismatch/missing scenarios + status enum.
- `exit_code_from_results` — 0=clean, 1=mismatch, 2=missing (priority).
- `compute_current_entries` — uses DEFAULT_SOURCES, preserves existing roles.
- CLI: check mode, --update mode, exit codes 0/1/2.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.rules_sources_check import (  # noqa: E402
    CheckResult,
    CheckStatus,
    SourceEntry,
    check_entries,
    compute_current_entries,
    compute_sha256,
    exit_code_from_results,
    load_hashes,
    main,
    save_hashes,
)


SCRIPT_PATH = ROOT_DIR / "scripts" / "rules_sources_check.py"


# --- compute_sha256 --------------------------------------------------------


def test_compute_sha256_deterministic(tmp_path: Path) -> None:
    """Ten sam content → ten sam hash."""
    path = tmp_path / "test.bin"
    path.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert compute_sha256(path) == expected


def test_compute_sha256_handles_large_file(tmp_path: Path) -> None:
    """Streamuje >64KB chunks bez OOM."""
    path = tmp_path / "big.bin"
    payload = b"A" * (100 * 1024)  # 100KB
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert compute_sha256(path) == expected


# --- load/save round-trip --------------------------------------------------


def test_load_hashes_missing_returns_empty(tmp_path: Path) -> None:
    assert load_hashes(tmp_path / "nonexistent.yaml") == []


def test_save_load_roundtrip(tmp_path: Path) -> None:
    entries = [
        SourceEntry(path="a/b.docx", sha256="abc123", role="Test doc"),
        SourceEntry(path="c/d.pdf", sha256="def456", role="Test pdf"),
    ]
    path = tmp_path / "hashes.yaml"
    save_hashes(path, entries)

    loaded = load_hashes(path)
    assert loaded == entries


def test_save_writes_header(tmp_path: Path) -> None:
    path = tmp_path / "hashes.yaml"
    save_hashes(path, [SourceEntry(path="x", sha256="y", role="z")])
    content = path.read_text(encoding="utf-8")
    assert "Regenerated via" in content
    assert "Verified via" in content


def test_load_handles_missing_role(tmp_path: Path) -> None:
    """Wpis bez `role` → fallback '(no role)'."""
    path = tmp_path / "hashes.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "sources": [{"path": "x", "sha256": "y"}]}),
        encoding="utf-8",
    )
    loaded = load_hashes(path)
    assert loaded[0].role == "(no role)"


# --- check_entries ---------------------------------------------------------


def test_check_match(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"content")
    sha = compute_sha256(path)
    entries = [SourceEntry(path="file.bin", sha256=sha, role="test")]
    results = check_entries(entries, project_root=tmp_path)
    assert len(results) == 1
    assert results[0].status == CheckStatus.MATCH


def test_check_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"actual content")
    entries = [SourceEntry(path="file.bin", sha256="wronghash", role="test")]
    results = check_entries(entries, project_root=tmp_path)
    assert results[0].status == CheckStatus.MISMATCH
    assert results[0].actual_sha256 != "wronghash"


def test_check_missing(tmp_path: Path) -> None:
    entries = [SourceEntry(path="nonexistent.bin", sha256="x", role="test")]
    results = check_entries(entries, project_root=tmp_path)
    assert results[0].status == CheckStatus.MISSING
    assert results[0].actual_sha256 is None


def test_check_mixed(tmp_path: Path) -> None:
    """Match + mismatch + missing w jednym callu."""
    (tmp_path / "ok.bin").write_bytes(b"ok")
    (tmp_path / "bad.bin").write_bytes(b"bad")
    entries = [
        SourceEntry(path="ok.bin", sha256=compute_sha256(tmp_path / "ok.bin"), role="ok"),
        SourceEntry(path="bad.bin", sha256="wronghash", role="bad"),
        SourceEntry(path="missing.bin", sha256="x", role="miss"),
    ]
    results = check_entries(entries, project_root=tmp_path)
    statuses = {r.entry.path: r.status for r in results}
    assert statuses["ok.bin"] == CheckStatus.MATCH
    assert statuses["bad.bin"] == CheckStatus.MISMATCH
    assert statuses["missing.bin"] == CheckStatus.MISSING


# --- exit_code_from_results -----------------------------------------------


def _result(status: CheckStatus) -> CheckResult:
    return CheckResult(
        entry=SourceEntry(path="x", sha256="y", role="z"),
        status=status,
        actual_sha256="z" if status != CheckStatus.MISSING else None,
    )


def test_exit_code_all_match_is_zero() -> None:
    assert exit_code_from_results([_result(CheckStatus.MATCH)] * 3) == 0


def test_exit_code_any_mismatch_is_one() -> None:
    assert exit_code_from_results([_result(CheckStatus.MATCH), _result(CheckStatus.MISMATCH)]) == 1


def test_exit_code_any_missing_is_one() -> None:
    """MISSING jest tak samo blokujące jak MISMATCH — oba zwracają exit 1.

    Powód: workflow GHA traktuje exit 2 jako WARN-pass (przeznaczone dla
    `rules_drift.py` description differences). Missing source musi blokować CI.
    """
    assert exit_code_from_results([_result(CheckStatus.MATCH), _result(CheckStatus.MISSING)]) == 1


def test_exit_code_missing_and_mismatch_both_one() -> None:
    """Oba failure modes (MISSING + MISMATCH) zwracają exit 1.

    Status distinction widoczna w `_print_results` (per linia: MISSING/MISMATCH/OK).
    """
    results = [_result(CheckStatus.MISMATCH), _result(CheckStatus.MISSING)]
    assert exit_code_from_results(results) == 1


# --- compute_current_entries -----------------------------------------------


def test_compute_current_preserves_existing_role(tmp_path: Path, monkeypatch) -> None:
    """Gdy plik ma już `role` w existing — zachowujemy custom role zamiast default."""
    # Mock DEFAULT_SOURCES via monkeypatch
    from scripts import rules_sources_check

    fake_sources = (
        ("file.bin", "Default role text"),
    )
    monkeypatch.setattr(rules_sources_check, "DEFAULT_SOURCES", fake_sources)

    (tmp_path / "file.bin").write_bytes(b"content")
    existing = [SourceEntry(path="file.bin", sha256="oldhash", role="Custom role")]

    fresh = compute_current_entries(tmp_path, existing=existing)
    assert len(fresh) == 1
    assert fresh[0].role == "Custom role"
    assert fresh[0].sha256 != "oldhash"  # fresh hash


def test_compute_current_skips_missing(tmp_path: Path, monkeypatch) -> None:
    """Source file brak → skip with warning, nie raise."""
    from scripts import rules_sources_check

    fake_sources = (
        ("present.bin", "Present"),
        ("missing.bin", "Missing"),
    )
    monkeypatch.setattr(rules_sources_check, "DEFAULT_SOURCES", fake_sources)

    (tmp_path / "present.bin").write_bytes(b"x")

    fresh = compute_current_entries(tmp_path, existing=None)
    assert len(fresh) == 1
    assert fresh[0].path == "present.bin"


def test_compute_current_preserves_legacy_entries(tmp_path: Path, monkeypatch) -> None:
    """Entries z `existing` które nie są w DEFAULT_SOURCES — preserve + refresh SHA."""
    from scripts import rules_sources_check

    fake_sources = (("default.bin", "Default role"),)
    monkeypatch.setattr(rules_sources_check, "DEFAULT_SOURCES", fake_sources)

    (tmp_path / "default.bin").write_bytes(b"x")
    (tmp_path / "legacy.bin").write_bytes(b"legacy content")

    existing = [
        SourceEntry(path="default.bin", sha256="old_default_sha", role="Custom default"),
        SourceEntry(path="legacy.bin", sha256="old_legacy_sha", role="User-added tracking"),
    ]

    fresh = compute_current_entries(tmp_path, existing=existing)
    by_path = {e.path: e for e in fresh}
    # Default entry refreshed; role preserved.
    assert "default.bin" in by_path
    assert by_path["default.bin"].role == "Custom default"
    assert by_path["default.bin"].sha256 != "old_default_sha"
    # Legacy entry preserved with role + refreshed SHA.
    assert "legacy.bin" in by_path
    assert by_path["legacy.bin"].role == "User-added tracking"
    assert by_path["legacy.bin"].sha256 != "old_legacy_sha"


def test_compute_current_drops_missing_legacy(tmp_path: Path, monkeypatch) -> None:
    """Legacy entry whose file disappeared → dropped (with WARNING)."""
    from scripts import rules_sources_check

    fake_sources = (("default.bin", "Default"),)
    monkeypatch.setattr(rules_sources_check, "DEFAULT_SOURCES", fake_sources)

    (tmp_path / "default.bin").write_bytes(b"x")
    # No legacy.bin on disk
    existing = [
        SourceEntry(path="default.bin", sha256="x", role="ok"),
        SourceEntry(path="legacy_gone.bin", sha256="x", role="vanished"),
    ]

    fresh = compute_current_entries(tmp_path, existing=existing)
    paths = {e.path for e in fresh}
    assert "default.bin" in paths
    assert "legacy_gone.bin" not in paths


# --- CLI ------------------------------------------------------------------


def test_cli_update_then_check_clean(tmp_path: Path, monkeypatch) -> None:
    """--update generuje hashes; potem check zwraca 0."""
    from scripts import rules_sources_check

    fake_sources = (("source.bin", "Test source"),)
    monkeypatch.setattr(rules_sources_check, "DEFAULT_SOURCES", fake_sources)

    (tmp_path / "source.bin").write_bytes(b"data")
    hashes_path = tmp_path / "hashes.yaml"

    # 1) --update mode
    rc = main([
        "--hashes", str(hashes_path),
        "--update",
        "--project-root", str(tmp_path),
    ])
    assert rc == 0
    assert hashes_path.exists()

    # 2) check mode → clean
    rc = main([
        "--hashes", str(hashes_path),
        "--project-root", str(tmp_path),
    ])
    assert rc == 0


def test_cli_check_mismatch_returns_1(tmp_path: Path) -> None:
    """Zmiana pliku po --update → check zwraca 1."""
    hashes_path = tmp_path / "hashes.yaml"
    source_path = tmp_path / "src.bin"
    source_path.write_bytes(b"original")

    save_hashes(hashes_path, [
        SourceEntry(path="src.bin", sha256=compute_sha256(source_path), role="test")
    ])

    # Modify source after hashes are recorded
    source_path.write_bytes(b"modified")

    rc = main([
        "--hashes", str(hashes_path),
        "--project-root", str(tmp_path),
    ])
    assert rc == 1


def test_cli_check_missing_returns_1(tmp_path: Path) -> None:
    """Missing source file → exit 1 (blocks CI). Patrz `exit_code_from_results`."""
    hashes_path = tmp_path / "hashes.yaml"
    save_hashes(hashes_path, [
        SourceEntry(path="never_existed.bin", sha256="x", role="test")
    ])

    rc = main([
        "--hashes", str(hashes_path),
        "--project-root", str(tmp_path),
    ])
    assert rc == 1


def test_cli_no_hashes_file_returns_2(tmp_path: Path) -> None:
    """Brak `source_hashes.yaml` → exit 2 z error message."""
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH),
            "--hashes", str(tmp_path / "nonexistent.yaml"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "no hashes loaded" in result.stderr.lower() or "error" in result.stderr.lower()


# --- Real source files (integration) --------------------------------------


def test_real_source_hashes_match() -> None:
    """Smoke: bieżący `app/rulesets/v1/source_hashes.yaml` zgadza się z plikami."""
    hashes_path = ROOT_DIR / "app" / "rulesets" / "v1" / "source_hashes.yaml"
    if not hashes_path.exists():
        pytest.skip("source_hashes.yaml not generated yet — run --update first")

    entries = load_hashes(hashes_path)
    results = check_entries(entries, project_root=ROOT_DIR)
    failures = [r for r in results if r.status != CheckStatus.MATCH]
    assert not failures, f"Source drift: {[r.entry.path + ' → ' + r.status.value for r in failures]}"
