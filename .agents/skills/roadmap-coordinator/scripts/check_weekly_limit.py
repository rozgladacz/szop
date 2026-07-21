"""Read the freshest weekly Codex rate-limit observation from local rollouts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable


WEEKLY_WINDOW_MINUTES = 7 * 24 * 60
DEFAULT_MAX_AGE_MINUTES = 12 * 60
DEFAULT_THRESHOLD_PERCENT = 10.0
MAX_CANDIDATE_FILES = 64


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weekly_window(rate_limits: object) -> tuple[float, int | None] | None:
    if not isinstance(rate_limits, dict):
        return None

    matches: list[tuple[float, int | None]] = []
    for key in ("primary", "secondary", "individual_limit"):
        window = rate_limits.get(key)
        if not isinstance(window, dict):
            continue
        if window.get("window_minutes") != WEEKLY_WINDOW_MINUTES:
            continue
        used = window.get("used_percent")
        if isinstance(used, bool) or not isinstance(used, (int, float)):
            continue
        if 0.0 <= float(used) <= 100.0:
            resets_at = window.get("resets_at")
            if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
                resets_at = None
            matches.append((float(used), int(resets_at) if resets_at is not None else None))
    return max(matches, key=lambda match: match[0]) if matches else None


def _candidate_rollouts(sessions_root: Path) -> Iterable[Path]:
    try:
        candidates = list(sessions_root.rglob("rollout-*.jsonl"))
    except OSError:
        return ()

    def modified_at(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    candidates.sort(key=modified_at, reverse=True)
    return candidates[:MAX_CANDIDATE_FILES]


def _latest_observation(sessions_root: Path) -> dict[str, Any] | None:
    for path in _candidate_rollouts(sessions_root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue

        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            weekly_window = _weekly_window(payload.get("rate_limits"))
            observed_at = _parse_timestamp(record.get("timestamp"))
            if weekly_window is None or observed_at is None:
                continue
            return {
                "observed_at": observed_at,
                "used_percent": weekly_window[0],
                "resets_at": weekly_window[1],
            }
    return None


def check_weekly_limit(
    sessions_root: Path,
    *,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 0.0 <= threshold_percent <= 100.0:
        raise ValueError("threshold_percent must be between 0 and 100")
    if max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")

    observed = _latest_observation(sessions_root)
    if observed is None:
        return {
            "status": "unavailable",
            "allow_start": False,
            "reason": "no_weekly_rate_limit_observation",
        }

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    age_minutes = max(
        0.0,
        (current - observed["observed_at"]).total_seconds() / 60.0,
    )
    if age_minutes > max_age_minutes:
        return {
            "status": "stale",
            "allow_start": False,
            "reason": "weekly_rate_limit_observation_too_old",
            "observed_at": observed["observed_at"].isoformat(),
            "age_minutes": round(age_minutes, 1),
        }

    used_percent = observed["used_percent"]
    remaining_percent = max(0.0, 100.0 - used_percent)
    allow_start = remaining_percent >= threshold_percent
    result = {
        "status": "ok",
        "allow_start": allow_start,
        "reason": "enough_weekly_limit" if allow_start else "weekly_limit_below_threshold",
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "threshold_percent": threshold_percent,
        "observed_at": observed["observed_at"].isoformat(),
        "age_minutes": round(age_minutes, 1),
    }
    if observed["resets_at"] is not None:
        result["resets_at"] = datetime.fromtimestamp(
            observed["resets_at"], tz=timezone.utc
        ).isoformat()
    return result


def _default_sessions_root() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "sessions"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-root", type=Path, default=_default_sessions_root())
    parser.add_argument("--threshold-percent", type=float, default=DEFAULT_THRESHOLD_PERCENT)
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    args = parser.parse_args()
    result = check_weekly_limit(
        args.sessions_root,
        threshold_percent=args.threshold_percent,
        max_age_minutes=args.max_age_minutes,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
