"""Regression tests for the backup sidecar's independent startup."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _scheduler_env(data_dir: Path, db_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "DB_URL": f"sqlite:///{db_path.as_posix()}",
    }


def test_scheduler_starts_in_fresh_interpreter(tmp_path: Path) -> None:
    script = (
        "import runpy, time; "
        "time.sleep = lambda _: (_ for _ in ()).throw(SystemExit(0)); "
        "runpy.run_module('app.scripts.backup_loop', run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=_scheduler_env(tmp_path, tmp_path / "szop.db"),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Backup scheduler started" in result.stderr
    assert "Następny backup" in result.stderr


def test_scheduler_creates_consistent_sqlite_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "szop.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample VALUES ('from WAL')")
        conn.commit()

        result = subprocess.run(
            [sys.executable, "-c", "from app.scripts.backup_loop import _run_once; _run_once()"],
            cwd=PROJECT_ROOT,
            env=_scheduler_env(tmp_path, db_path),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr

        backups = list((tmp_path / "backups").glob("szop-backup-*.db"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as snapshot:
            assert snapshot.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert snapshot.execute("SELECT value FROM sample").fetchone() == ("from WAL",)


def test_compose_uses_scheduler_healthcheck() -> None:
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    check = compose["services"]["szop-backup"]["healthcheck"]["test"]

    assert check[0] == "CMD-SHELL"
    assert "app.scripts.backup_loop" in check[1]
    assert "/proc/1/cmdline" in check[1]
    assert "auth/login" not in check[1]
