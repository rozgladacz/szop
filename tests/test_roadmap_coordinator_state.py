from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / ".agents"
    / "skills"
    / "roadmap-coordinator"
    / "scripts"
    / "coordinator_state.py"
)
SPEC = importlib.util.spec_from_file_location("roadmap_coordinator_state", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

START = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


def _blocker(
    *,
    key: str = "thread:worker-1",
    version: str = "updated:1",
    summary: str = "Worker oczekuje na zatwierdzenie narzędzia.",
):
    return MODULE.observation(
        "blocked",
        blocker_kind="approval_required",
        blocker_key=key,
        blocker_version=version,
        blocker_summary=summary,
    )


def _transition(state, observed, *, minutes: int = 0):
    return MODULE.transition(state, observed, now=START + timedelta(minutes=minutes))


def test_ready_running_and_ready_transitions_clear_transient_state() -> None:
    state = MODULE.initial_state(START)

    running, effects = _transition(
        state,
        MODULE.observation("running", stage_key="B4.4d.C2a2", thread_id="worker-1"),
    )
    ready, ready_effects = _transition(running, MODULE.observation("ready"), minutes=1)

    assert running["state"] == MODULE.RUNNING
    assert running["active_stage"]["stage_key"] == "B4.4d.C2a2"
    assert running["blocker"] is None
    assert effects == {
        "notify": False,
        "pause_automation": False,
        "notification_reason": None,
    }
    assert ready["state"] == MODULE.READY
    assert ready["active_stage"] is None
    assert ready["blocker"] is None
    assert ready_effects["notify"] is False


def test_running_worker_can_change_without_notification() -> None:
    initial = MODULE.initial_state(START)
    running, _ = _transition(
        initial,
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-1"),
    )

    unchanged, unchanged_effects = _transition(
        running,
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-1"),
        minutes=1,
    )
    changed, changed_effects = _transition(
        unchanged,
        MODULE.observation("running", stage_key="C2b", thread_id="worker-2"),
        minutes=2,
    )

    assert unchanged["last_transition"] == "worker_unchanged"
    assert changed["last_transition"] == "worker_changed"
    assert changed["active_stage"]["stage_key"] == "C2b"
    assert unchanged_effects["notify"] is False
    assert changed_effects["notify"] is False


def test_running_to_blocked_and_back_to_running() -> None:
    initial = MODULE.initial_state(START)
    running, _ = _transition(
        initial,
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-1"),
    )

    blocked, blocked_effects = _transition(running, _blocker(), minutes=1)
    resumed, resumed_effects = _transition(
        blocked,
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-1"),
        minutes=2,
    )

    assert blocked["state"] == MODULE.BLOCKED
    assert blocked_effects["notification_reason"] == "blocker_first_seen"
    assert resumed["state"] == MODULE.RUNNING
    assert resumed["blocker"] is None
    assert resumed_effects["notify"] is False


def test_first_blocker_notifies_and_persists_required_metadata() -> None:
    blocked, effects = _transition(MODULE.initial_state(START), _blocker())

    assert blocked["state"] == MODULE.BLOCKED
    assert blocked["blocker"]["fingerprint"].startswith("sha256:")
    assert len(blocked["blocker"]["fingerprint"]) == len("sha256:") + 64
    assert blocked["blocker"]["first_seen_at"] == "2026-08-07T08:00:00Z"
    assert blocked["blocker"]["last_notified_at"] == "2026-08-07T08:00:00Z"
    assert blocked["blocker"]["unchanged_runs"] == 0
    assert effects == {
        "notify": True,
        "pause_automation": False,
        "notification_reason": "blocker_first_seen",
    }


def test_same_blocker_is_silent_and_counts_unchanged_runs() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())

    second, effects = _transition(first, _blocker(), minutes=45)

    assert second["state"] == MODULE.BLOCKED
    assert second["blocker"]["unchanged_runs"] == 1
    assert second["blocker"]["last_seen_at"] == "2026-08-07T08:45:00Z"
    assert second["blocker"]["last_notified_at"] == "2026-08-07T08:00:00Z"
    assert effects["notify"] is False
    assert effects["pause_automation"] is False


def test_changed_blocker_resets_clock_counter_and_notifies() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=30)

    changed, effects = _transition(
        second,
        _blocker(version="updated:2", summary="Worker zadał nowe pytanie."),
        minutes=60,
    )

    assert changed["state"] == MODULE.BLOCKED
    assert changed["blocker"]["first_seen_at"] == "2026-08-07T09:00:00Z"
    assert changed["blocker"]["last_notified_at"] == "2026-08-07T09:00:00Z"
    assert changed["blocker"]["unchanged_runs"] == 0
    assert effects["notify"] is True
    assert effects["notification_reason"] == "blocker_changed"


def test_third_identical_observation_requests_pause() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)

    pending, effects = _transition(second, _blocker(), minutes=89)

    assert pending["state"] == MODULE.PAUSE_PENDING
    assert pending["blocker"]["unchanged_runs"] == 2
    assert pending["last_transition"] == "identical_blocker_threshold"
    assert effects == {
        "notify": False,
        "pause_automation": True,
        "notification_reason": None,
    }


def test_ninety_minutes_requests_pause_even_before_third_observation() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())

    pending, effects = _transition(first, _blocker(), minutes=90)

    assert pending["state"] == MODULE.PAUSE_PENDING
    assert pending["blocker"]["unchanged_runs"] == 1
    assert pending["last_transition"] == "blocked_age_threshold"
    assert effects["pause_automation"] is True
    assert effects["notify"] is False


def test_pause_pending_retries_side_effect_without_duplicate_notification() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)

    retried, effects = _transition(pending, _blocker(), minutes=91)

    assert retried["state"] == MODULE.PAUSE_PENDING
    assert retried["blocker"]["unchanged_runs"] == 2
    assert retried["last_transition"] == "pause_retry_required"
    assert effects["pause_automation"] is True
    assert effects["notify"] is False


def test_changed_blocker_cancels_unconfirmed_pause_and_starts_new_cycle() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)

    changed, effects = _transition(
        pending,
        _blocker(key="weekly-limit", version="reset:2", summary="Limit tygodniowy."),
        minutes=91,
    )

    assert changed["state"] == MODULE.BLOCKED
    assert changed["blocker"]["key"] == "weekly-limit"
    assert changed["blocker"]["unchanged_runs"] == 0
    assert effects["notification_reason"] == "blocker_changed"
    assert effects["notify"] is True
    assert effects["pause_automation"] is False


def test_cleared_blocker_cancels_unconfirmed_pause() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)

    ready, effects = _transition(pending, MODULE.observation("ready"), minutes=91)

    assert ready["state"] == MODULE.READY
    assert ready["blocker"] is None
    assert effects["notify"] is False
    assert effects["pause_automation"] is False


def test_confirm_pause_notifies_once_and_is_idempotent() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)

    paused, effects = MODULE.confirm_pause(pending, now=START + timedelta(minutes=90))
    repeated, repeated_effects = MODULE.confirm_pause(
        paused, now=START + timedelta(minutes=91)
    )

    assert paused["state"] == MODULE.PAUSED
    assert paused["blocker"]["last_notified_at"] == "2026-08-07T09:30:00Z"
    assert effects["notify"] is True
    assert effects["notification_reason"] == "automation_paused_for_blocker"
    assert repeated["state"] == MODULE.PAUSED
    assert repeated_effects["notify"] is False


def test_confirm_pause_rejects_nonpending_state() -> None:
    with pytest.raises(ValueError, match="only be confirmed from PAUSE_PENDING"):
        MODULE.confirm_pause(MODULE.initial_state(START), now=START)


def test_paused_state_ignores_observations_until_manual_resume() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)
    paused, _ = MODULE.confirm_pause(pending, now=START + timedelta(minutes=90))

    still_paused, effects = _transition(
        paused,
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-2"),
        minutes=91,
    )

    assert still_paused["state"] == MODULE.PAUSED
    assert still_paused["blocker"] == paused["blocker"]
    assert still_paused["active_stage"] == paused["active_stage"]
    assert effects["notify"] is False
    assert effects["pause_automation"] is False


def test_manual_resume_clears_blocker_and_allows_a_new_cycle() -> None:
    first, _ = _transition(MODULE.initial_state(START), _blocker())
    second, _ = _transition(first, _blocker(), minutes=45)
    pending, _ = _transition(second, _blocker(), minutes=90)
    paused, _ = MODULE.confirm_pause(pending, now=START + timedelta(minutes=90))

    resumed, effects = MODULE.resume(paused, now=START + timedelta(minutes=100))
    blocked_again, new_effects = MODULE.transition(
        resumed,
        _blocker(),
        now=START + timedelta(minutes=101),
    )

    assert resumed["state"] == MODULE.READY
    assert resumed["blocker"] is None
    assert resumed["resumed_at"] == "2026-08-07T09:40:00Z"
    assert effects["notify"] is False
    assert blocked_again["state"] == MODULE.BLOCKED
    assert blocked_again["blocker"]["unchanged_runs"] == 0
    assert new_effects["notification_reason"] == "blocker_first_seen"


def test_resume_rejects_a_running_coordinator() -> None:
    running, _ = _transition(
        MODULE.initial_state(START),
        MODULE.observation("running", stage_key="C2a2", thread_id="worker-1"),
    )

    with pytest.raises(ValueError, match="only valid for a paused coordinator"):
        MODULE.resume(running, now=START + timedelta(minutes=1))


def test_resume_is_idempotent_after_state_was_already_reset() -> None:
    ready, effects = MODULE.resume(MODULE.initial_state(START), now=START)

    assert ready["state"] == MODULE.READY
    assert ready["last_transition"] == "manual_resume_already_ready"
    assert effects["notify"] is False


def test_fingerprint_is_normalized_and_changes_with_blocker_version() -> None:
    first = MODULE.blocker_fingerprint(
        kind=" approval_required ",
        key="thread:worker-1",
        version="updated:1",
    )
    normalized = MODULE.blocker_fingerprint(
        kind="approval_required",
        key="thread:worker-1",
        version="updated:1",
    )
    changed = MODULE.blocker_fingerprint(
        kind="approval_required",
        key="thread:worker-1",
        version="updated:2",
    )
    paraphrased = MODULE.observation(
        "blocked",
        blocker_kind="approval_required",
        blocker_key="thread:worker-1",
        blocker_version="updated:1",
        blocker_summary="To samo pytanie opisane innymi słowami.",
    )

    assert first == normalized
    assert paraphrased["blocker"]["fingerprint"] == first
    assert changed != first


def test_state_file_round_trip_persists_each_transition(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    first = MODULE.record_observation(path, _blocker(), now=START)
    second = MODULE.record_observation(
        path, _blocker(), now=START + timedelta(minutes=45)
    )
    loaded = MODULE.load_state(path)

    assert first["effects"]["notify"] is True
    assert second["effects"]["notify"] is False
    assert loaded == second["state"]
    assert loaded["blocker"]["unchanged_runs"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_ready_stage_selector_accepts_only_open_explicit_markers(tmp_path: Path) -> None:
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text(
        "\n".join(
            (
                "- [ ] **A1** ordinary open stage",
                "- [x] **A2** completed [automation-ready]",
                "- [ ] **A3** explicit [automation-ready]",
            )
        ),
        encoding="utf-8",
    )

    assert MODULE.automation_ready_stages(roadmap) == ["A3"]


def test_ready_stage_selector_rejects_duplicate_stage_ids(tmp_path: Path) -> None:
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text(
        "- [ ] **A3** first [automation-ready]\n"
        "- [ ] **A3** duplicate [automation-ready]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate automation-ready stage ids"):
        MODULE.automation_ready_stages(roadmap)
