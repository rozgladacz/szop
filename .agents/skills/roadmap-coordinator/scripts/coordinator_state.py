"""Durable state machine for the szop_a roadmap coordinator."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata


SCHEMA_VERSION = 1
AUTOMATION_ID = "roadmapa-koordynacja-poza-szczytem-pn-pt"
MAX_IDENTICAL_OBSERVATIONS = 3
MAX_BLOCKED_AGE = timedelta(minutes=90)

READY = "READY"
RUNNING = "RUNNING"
BLOCKED = "BLOCKED"
PAUSE_PENDING = "PAUSE_PENDING"
PAUSED = "PAUSED"
VALID_STATES = {READY, RUNNING, BLOCKED, PAUSE_PENDING, PAUSED}
AUTOMATION_READY_PATTERN = re.compile(
    r"^\s*-\s*\[\s\]\s+\*\*(?P<stage>[^*]+)\*\*.*\[automation-ready\]",
    re.MULTILINE,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
    return _as_utc(parsed)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not _normalize(value):
        raise ValueError(f"{name} must be a non-empty string")
    return _normalize(value)


def default_state_path() -> Path:
    repository_root = Path(__file__).resolve().parents[4]
    return repository_root / ".codex" / "runtime" / "roadmap-coordinator-state.json"


def default_roadmap_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "roadmap.md"


def automation_ready_stages(path: Path) -> list[str]:
    try:
        roadmap = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read roadmap: {path}") from exc
    stages = [_normalize(match.group("stage")) for match in AUTOMATION_READY_PATTERN.finditer(roadmap)]
    if len(stages) != len(set(stages)):
        raise ValueError("roadmap contains duplicate automation-ready stage ids")
    return stages


def initial_state(now: datetime | None = None) -> dict[str, Any]:
    current = _as_utc(now or _utc_now())
    return {
        "schema_version": SCHEMA_VERSION,
        "automation_id": AUTOMATION_ID,
        "state": READY,
        "active_stage": None,
        "blocker": None,
        "updated_at": _format_timestamp(current),
        "last_transition": "initialized",
        "resumed_at": None,
    }


def _validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("coordinator state must be a JSON object")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported coordinator state schema")
    if state.get("automation_id") != AUTOMATION_ID:
        raise ValueError("coordinator state belongs to another automation")
    if state.get("state") not in VALID_STATES:
        raise ValueError("invalid coordinator state")
    _parse_timestamp(state.get("updated_at"))

    blocker = state.get("blocker")
    if state["state"] in {BLOCKED, PAUSE_PENDING, PAUSED}:
        if not isinstance(blocker, dict):
            raise ValueError("blocked coordinator state requires blocker metadata")
        for field in (
            "fingerprint",
            "kind",
            "key",
            "summary",
            "first_seen_at",
            "last_seen_at",
            "last_notified_at",
        ):
            if not isinstance(blocker.get(field), str):
                raise ValueError(f"blocker.{field} must be a string")
        _parse_timestamp(blocker["first_seen_at"])
        _parse_timestamp(blocker["last_seen_at"])
        _parse_timestamp(blocker["last_notified_at"])
        unchanged_runs = blocker.get("unchanged_runs")
        if isinstance(unchanged_runs, bool) or not isinstance(unchanged_runs, int):
            raise ValueError("blocker.unchanged_runs must be an integer")
        if unchanged_runs < 0:
            raise ValueError("blocker.unchanged_runs cannot be negative")
    elif blocker is not None:
        raise ValueError("unblocked coordinator state cannot retain a blocker")
    return state


def load_state(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    if not path.exists():
        return initial_state(now)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read coordinator state: {path}") from exc
    return _validate_state(state)


def save_state(path: Path, state: dict[str, Any]) -> None:
    _validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def blocker_fingerprint(
    *,
    kind: str,
    key: str,
    version: str = "",
) -> str:
    canonical = {
        "key": _require_text("blocker key", key),
        "kind": _require_text("blocker kind", kind),
        "version": _normalize(version),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def observation(
    status: str,
    *,
    stage_key: str | None = None,
    thread_id: str | None = None,
    blocker_kind: str | None = None,
    blocker_key: str | None = None,
    blocker_version: str = "",
    blocker_summary: str | None = None,
) -> dict[str, Any]:
    if status not in {"ready", "running", "blocked"}:
        raise ValueError("observation status must be ready, running, or blocked")
    if status == "running":
        return {
            "status": status,
            "stage_key": _require_text("stage key", stage_key),
            "thread_id": _normalize(thread_id) if thread_id else None,
        }
    if status == "blocked":
        kind = _require_text("blocker kind", blocker_kind)
        key = _require_text("blocker key", blocker_key)
        summary = _require_text("blocker summary", blocker_summary)
        version = _normalize(blocker_version)
        return {
            "status": status,
            "blocker": {
                "fingerprint": blocker_fingerprint(
                    kind=kind,
                    key=key,
                    version=version,
                ),
                "kind": kind,
                "key": key,
                "version": version,
                "summary": summary,
            },
        }
    return {"status": status}


def _effects(
    *,
    notify: bool = False,
    pause_automation: bool = False,
    notification_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "notify": notify,
        "pause_automation": pause_automation,
        "notification_reason": notification_reason,
    }


def transition(
    state: dict[str, Any],
    observed: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _as_utc(now or _utc_now())
    current_text = _format_timestamp(current)
    previous = deepcopy(_validate_state(state))
    status = observed.get("status")
    if status not in {"ready", "running", "blocked"}:
        raise ValueError("invalid observation")

    if previous["state"] == PAUSED:
        previous["updated_at"] = current_text
        previous["last_transition"] = "paused_requires_manual_resume"
        return previous, _effects()

    if status == "ready":
        previous.update(
            {
                "state": READY,
                "active_stage": None,
                "blocker": None,
                "updated_at": current_text,
                "last_transition": "ready_observed",
            }
        )
        return previous, _effects()

    if status == "running":
        stage_key = _require_text("stage key", observed.get("stage_key"))
        active_stage = {
            "stage_key": stage_key,
            "thread_id": observed.get("thread_id"),
            "observed_at": current_text,
        }
        old_stage = previous.get("active_stage")
        if previous["state"] != RUNNING:
            transition_name = "worker_started"
        elif isinstance(old_stage, dict) and old_stage.get("stage_key") == stage_key:
            transition_name = "worker_unchanged"
        else:
            transition_name = "worker_changed"
        previous.update(
            {
                "state": RUNNING,
                "active_stage": active_stage,
                "blocker": None,
                "updated_at": current_text,
                "last_transition": transition_name,
            }
        )
        return previous, _effects()

    blocker_observation = observed.get("blocker")
    if not isinstance(blocker_observation, dict):
        raise ValueError("blocked observation requires blocker metadata")
    fingerprint = _require_text(
        "blocker fingerprint", blocker_observation.get("fingerprint")
    )
    old_blocker = previous.get("blocker")
    same_blocker = (
        isinstance(old_blocker, dict)
        and old_blocker.get("fingerprint") == fingerprint
    )

    if previous["state"] == PAUSE_PENDING and same_blocker:
        old_blocker["last_seen_at"] = current_text
        previous.update(
            {
                "updated_at": current_text,
                "last_transition": "pause_retry_required",
            }
        )
        return previous, _effects(pause_automation=True)

    if same_blocker and previous["state"] == BLOCKED:
        unchanged_runs = old_blocker["unchanged_runs"] + 1
        old_blocker["unchanged_runs"] = unchanged_runs
        old_blocker["last_seen_at"] = current_text
        first_seen = _parse_timestamp(old_blocker["first_seen_at"])
        elapsed = max(timedelta(0), current - first_seen)
        observations = unchanged_runs + 1
        threshold_reason: str | None = None
        if observations >= MAX_IDENTICAL_OBSERVATIONS:
            threshold_reason = "identical_blocker_threshold"
        elif elapsed >= MAX_BLOCKED_AGE:
            threshold_reason = "blocked_age_threshold"

        if threshold_reason is not None:
            previous.update(
                {
                    "state": PAUSE_PENDING,
                    "updated_at": current_text,
                    "last_transition": threshold_reason,
                }
            )
            return previous, _effects(pause_automation=True)

        previous.update(
            {
                "updated_at": current_text,
                "last_transition": "blocker_unchanged",
            }
        )
        return previous, _effects()

    notification_reason = (
        "blocker_changed" if isinstance(old_blocker, dict) else "blocker_first_seen"
    )
    previous.update(
        {
            "state": BLOCKED,
            "blocker": {
                **blocker_observation,
                "first_seen_at": current_text,
                "last_seen_at": current_text,
                "last_notified_at": current_text,
                "unchanged_runs": 0,
            },
            "updated_at": current_text,
            "last_transition": notification_reason,
        }
    )
    return previous, _effects(
        notify=True,
        notification_reason=notification_reason,
    )


def confirm_pause(
    state: dict[str, Any], *, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _as_utc(now or _utc_now())
    current_text = _format_timestamp(current)
    updated = deepcopy(_validate_state(state))
    if updated["state"] == PAUSED:
        updated["updated_at"] = current_text
        updated["last_transition"] = "pause_already_confirmed"
        return updated, _effects()
    if updated["state"] != PAUSE_PENDING:
        raise ValueError("pause can only be confirmed from PAUSE_PENDING")
    updated["state"] = PAUSED
    updated["blocker"]["last_notified_at"] = current_text
    updated["updated_at"] = current_text
    updated["last_transition"] = "automation_pause_confirmed"
    return updated, _effects(
        notify=True,
        notification_reason="automation_paused_for_blocker",
    )


def resume(
    state: dict[str, Any], *, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _as_utc(now or _utc_now())
    current_text = _format_timestamp(current)
    updated = deepcopy(_validate_state(state))
    if updated["state"] == READY:
        updated["updated_at"] = current_text
        updated["last_transition"] = "manual_resume_already_ready"
        return updated, _effects()
    if updated["state"] not in {PAUSE_PENDING, PAUSED}:
        raise ValueError("manual resume is only valid for a paused coordinator")
    updated.update(
        {
            "state": READY,
            "active_stage": None,
            "blocker": None,
            "updated_at": current_text,
            "last_transition": "manual_resume",
            "resumed_at": current_text,
        }
    )
    return updated, _effects()


def _persist_transition(
    path: Path,
    operation: Any,
    *,
    now: datetime | None = None,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_state(path, now=now)
    if observed is None:
        updated, effects = operation(state, now=now)
    else:
        updated, effects = operation(state, observed, now=now)
    save_state(path, updated)
    return {"state": updated, "effects": effects}


def record_observation(
    path: Path,
    observed: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return _persist_transition(path, transition, now=now, observed=observed)


def record_pause_confirmation(
    path: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    return _persist_transition(path, confirm_pause, now=now)


def record_resume(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    return _persist_transition(path, resume, now=now)


def _parse_cli_timestamp(value: str | None) -> datetime | None:
    return _parse_timestamp(value) if value else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", type=Path, default=default_state_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("--now")

    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--status", choices=("ready", "running", "blocked"), required=True)
    observe_parser.add_argument("--stage-key")
    observe_parser.add_argument("--thread-id")
    observe_parser.add_argument("--blocker-kind")
    observe_parser.add_argument("--blocker-key")
    observe_parser.add_argument("--blocker-version", default="")
    observe_parser.add_argument("--blocker-summary")
    observe_parser.add_argument("--now")

    confirm_parser = subparsers.add_parser("confirm-pause")
    confirm_parser.add_argument("--now")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--now")

    ready_parser = subparsers.add_parser("ready-stages")
    ready_parser.add_argument("--roadmap", type=Path, default=default_roadmap_path())
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    now = _parse_cli_timestamp(getattr(args, "now", None))
    if args.command == "ready-stages":
        result = {"automation_ready_stages": automation_ready_stages(args.roadmap)}
    elif args.command == "show":
        result: dict[str, Any] = {"state": load_state(args.state_file, now=now)}
    elif args.command == "observe":
        try:
            observed = observation(
                args.status,
                stage_key=args.stage_key,
                thread_id=args.thread_id,
                blocker_kind=args.blocker_kind,
                blocker_key=args.blocker_key,
                blocker_version=args.blocker_version,
                blocker_summary=args.blocker_summary,
            )
        except ValueError as exc:
            parser.error(str(exc))
        result = record_observation(args.state_file, observed, now=now)
    elif args.command == "confirm-pause":
        result = record_pause_confirmation(args.state_file, now=now)
    else:
        result = record_resume(args.state_file, now=now)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
