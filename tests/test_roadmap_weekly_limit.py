from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / ".agents"
    / "skills"
    / "roadmap-coordinator"
    / "scripts"
    / "check_weekly_limit.py"
)
SPEC = importlib.util.spec_from_file_location("check_weekly_limit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_rollout(
    root: Path,
    *,
    timestamp: datetime,
    used_percent: float,
    window_minutes: int = 10080,
    branch: str = "primary",
) -> None:
    path = root / timestamp.strftime("%Y/%m/%d") / "rollout-test.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                branch: {
                    "used_percent": used_percent,
                    "window_minutes": window_minutes,
                    "resets_at": int((timestamp + timedelta(days=7)).timestamp()),
                }
            },
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_allows_start_at_exactly_ten_percent_remaining(tmp_path: Path) -> None:
    now = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    _write_rollout(tmp_path, timestamp=now, used_percent=90.0)

    result = MODULE.check_weekly_limit(tmp_path, now=now)

    assert result["allow_start"] is True
    assert result["remaining_percent"] == 10.0
    assert result["resets_at"].endswith("+00:00")


def test_blocks_below_ten_percent_remaining(tmp_path: Path) -> None:
    now = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    _write_rollout(tmp_path, timestamp=now, used_percent=90.1, branch="secondary")

    result = MODULE.check_weekly_limit(tmp_path, now=now)

    assert result["allow_start"] is False
    assert result["reason"] == "weekly_limit_below_threshold"


def test_uses_freshest_weekly_observation(tmp_path: Path) -> None:
    now = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    _write_rollout(tmp_path, timestamp=now - timedelta(minutes=5), used_percent=95.0)
    _write_rollout(tmp_path, timestamp=now, used_percent=12.0)
    _write_rollout(
        tmp_path,
        timestamp=now + timedelta(minutes=1),
        used_percent=100.0,
        window_minutes=300,
    )

    result = MODULE.check_weekly_limit(tmp_path, now=now)

    assert result["allow_start"] is True
    assert result["used_percent"] == 12.0


def test_blocks_when_observation_is_missing_or_stale(tmp_path: Path) -> None:
    now = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    missing = MODULE.check_weekly_limit(tmp_path, now=now)
    _write_rollout(tmp_path, timestamp=now - timedelta(hours=13), used_percent=1.0)
    stale = MODULE.check_weekly_limit(tmp_path, now=now)

    assert missing["allow_start"] is False
    assert missing["status"] == "unavailable"
    assert stale["allow_start"] is False
    assert stale["status"] == "stale"
