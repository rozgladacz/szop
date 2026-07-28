"""B2 event-store — testy persystencji (ADR-0050).

Weryfikuje, że `persistence.save_events`/`load_events` round-trip'ują pełen
strumień eventów przez prawdziwą bazę bez utraty informacji, oraz że replay z
bazy jest bit-perfect (inwariant ADR-0010/0046, ale źródłem eventów jest DB).

Bateria bitwy reużywa scenariusz ze `scripts/engine_smoke_replay.py` (2v2,
2 rundy) — gęsty strumień obejmujący Move/Shot/Charge/Defend/Status/Round/
Objective/Initiative/MoraleTest/MeleeBalanceReset eventy.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models  # noqa: E402
from app.db import Base  # noqa: E402
from app.services.engine.actions import (  # noqa: E402
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
)
from app.services.engine.combat import WeaponProfile  # noqa: E402
from app.services.engine.dice import DeterministicDice  # noqa: E402
from app.services.engine.events import (  # noqa: E402
    MoveExecuted,
    StatusAdded,
)
from app.services.engine.persistence import (  # noqa: E402
    BattleCheckpointSequenceConflict,
    BattleEventSequenceConflict,
    latest_event_sequence,
    load_latest_checkpoint,
    load_events,
    save_checkpoint,
    save_events,
)
from app.services.engine.phases import (  # noqa: E402
    deployment_round,
    round_end_phase,
    setup_phase,
)
from app.services.engine.resolver import (  # noqa: E402
    apply,
    is_battle_over,
    should_end_round,
)
from app.services.engine.state import (  # noqa: E402
    Objective,
    Position,
    apply_events,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _new_battle(session: Session, *, seed: int = 2026) -> models.Battle:
    battle = models.Battle(rng_seed=seed, status="active")
    session.add(battle)
    session.commit()
    session.refresh(battle)
    return battle


def _make_unit(uid: int, x: float, y: float) -> dict:
    return {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
    }


def _play_smoke_battle():
    """Rozgrywa deterministyczną bitwę 2v2 (2 rundy). Zwraca
    (initial_for_replay, all_events, final_state) — mirror smoke replay."""
    rosters = [
        {"owner_player": 0, "units": [_make_unit(1, 0, 0), _make_unit(2, 0, 6)]},
        {"owner_player": 1, "units": [_make_unit(3, 36, 0), _make_unit(4, 36, 6)]},
    ]
    objectives = [Objective(id=1, position=Position(18, 3))]
    state = setup_phase(rosters, objectives=objectives, initiative_player=0)

    deployment = [
        DeploymentAction(unit_id=1, position=Position(6, 0)),
        DeploymentAction(unit_id=2, position=Position(6, 6)),
        DeploymentAction(unit_id=3, position=Position(30, 0)),
        DeploymentAction(unit_id=4, position=Position(30, 6)),
    ]
    state, deploy_events = deployment_round(state, deployment)
    initial_for_replay = state  # round 0->1 nie jest event-sourced (smoke konwencja)

    dice = DeterministicDice(seed=2026)
    rifle = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1, ap=0)
    sword = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2, ap=0)

    all_events: list = []
    seq = len(deploy_events) + 1

    while not is_battle_over(state) and state.round <= 2:
        actions = [
            # Manewr w budżecie 6″ (unit 1 @ (6,0) → (12,0)); >6″ jest teraz
            # nielegalny (resolver._validate_action, pkt 15.a) — wcześniej 15″
            # przechodziło tylko bo silnik nie walidował dystansu.
            (0, ManeuverAction(unit_id=1, target_position=Position(12, 0))),
            (1, ShootAction(unit_id=3, target_id=1, weapon=rifle)),
            (0, ChargeAction(unit_id=2, target_id=4, weapon=sword)),
            (1, DefendAction(unit_id=4)),
        ]
        for expected_player, action in actions:
            if should_end_round(state):
                break
            blob = next((b for b in state.blobs if b.id == action.unit_id), None)
            if blob is None or blob.models_alive == 0:
                continue
            if state.active_player != expected_player:
                continue
            try:
                result = apply(state, action, dice, sequence=seq)
            except Exception:
                continue
            state = result.state
            seq = result.next_sequence
            all_events.extend(result.events)

        state, end_events = round_end_phase(state, sequence=seq)
        seq += len(end_events)
        all_events.extend(end_events)

    return initial_for_replay, all_events, state


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip_equal_events() -> None:
    """save → load zwraca eventy identyczne (dataclass equality) i w kolejności."""
    session = _build_session()
    battle = _new_battle(session)
    _, all_events, _ = _play_smoke_battle()
    assert len(all_events) > 10  # gęsty strumień

    written = save_events(session, battle.id, all_events)
    session.commit()
    assert written == len(all_events)

    loaded = load_events(session, battle.id)
    assert loaded == all_events  # frozen dataclasses → equality po wartości


def test_roundtrip_covers_many_event_types() -> None:
    """Strumień testowy pokrywa wiele typów (sanity dla serializera w DB)."""
    session = _build_session()
    battle = _new_battle(session)
    _, all_events, _ = _play_smoke_battle()
    save_events(session, battle.id, all_events)
    session.commit()

    loaded = load_events(session, battle.id)
    types = {type(e).__name__ for e in loaded}
    # Minimalny zestaw, który ta bitwa zawsze produkuje.
    assert {"MoveExecuted", "StatusAdded", "RoundEnded"}.issubset(types)
    assert len(types) >= 5


def test_checkpoint_survives_session_reopen_with_state_and_rng(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'checkpoint.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    _, events, state = _play_smoke_battle()
    dice = DeterministicDice(seed=314159)
    dice.roll_d6(23)

    with Session(bind=engine) as writer:
        battle = models.Battle(rng_seed=dice.seed, status="active")
        writer.add(battle)
        writer.flush()
        save_events(writer, battle.id, events)
        sequence_at = latest_event_sequence(writer, battle.id)
        save_checkpoint(writer, battle.id, sequence_at, state, dice)
        battle_id = battle.id
        writer.commit()

    expected_rolls = dice.roll_d6(50)
    with Session(bind=engine) as reader:
        loaded = load_latest_checkpoint(reader, battle_id)

    assert loaded is not None
    assert loaded.battle_id == battle_id
    assert loaded.sequence_at == max(event.sequence for event in events)
    assert loaded.state == state
    assert loaded.dice.roll_d6(50) == expected_rolls


def test_checkpoint_default_remains_exact_v1() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()

    save_checkpoint(
        session,
        battle.id,
        0,
        state,
        DeterministicDice(seed=battle.rng_seed),
    )

    row = session.query(models.BattleCheckpoint).one()
    payload = json.loads(row.state_json)
    loaded = load_latest_checkpoint(session, battle.id)
    assert payload["schema"] == "szop.battle_state"
    assert payload["version"] == 1
    assert loaded is not None
    assert loaded.state == state
    assert loaded.state.initiative_player is None


def test_checkpoint_explicit_v2_preserves_durable_initiative() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()
    state = replace(state, initiative_player=state.active_player)

    save_checkpoint(
        session,
        battle.id,
        0,
        state,
        DeterministicDice(seed=battle.rng_seed),
        state_version=2,
    )

    row = session.query(models.BattleCheckpoint).one()
    payload = json.loads(row.state_json)
    loaded = load_latest_checkpoint(session, battle.id)
    assert payload["schema"] == "szop.battle_state"
    assert payload["version"] == 2
    assert loaded is not None
    assert loaded.state == state
    assert loaded.state.initiative_player == state.active_player


@pytest.mark.parametrize("state_version", [None, True, 0, 3, 1.0, "2"])
def test_checkpoint_rejects_invalid_state_version_before_insert(state_version) -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()

    with pytest.raises(ValueError, match="unsupported battle state checkpoint version"):
        save_checkpoint(
            session,
            battle.id,
            0,
            state,
            DeterministicDice(seed=battle.rng_seed),
            state_version=state_version,
        )

    assert session.query(models.BattleCheckpoint).count() == 0


def test_checkpoint_rejects_state_version_mismatch_before_insert() -> None:
    session = _build_session()
    battle = _new_battle(session)
    v1_state, _, _ = _play_smoke_battle()
    v2_state = replace(v1_state, initiative_player=v1_state.active_player)

    mismatches = ((v1_state, 2), (v2_state, 1))
    for state, state_version in mismatches:
        with pytest.raises(ValueError):
            save_checkpoint(
                session,
                battle.id,
                0,
                state,
                DeterministicDice(seed=battle.rng_seed),
                state_version=state_version,
            )
        assert session.query(models.BattleCheckpoint).count() == 0


def test_checkpoint_requires_current_event_sequence() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()

    with pytest.raises(BattleCheckpointSequenceConflict) as exc_info:
        save_checkpoint(
            session,
            battle.id,
            1,
            state,
            DeterministicDice(seed=battle.rng_seed),
        )

    assert exc_info.value.latest_sequence == 0
    assert session.query(models.BattleCheckpoint).count() == 0


def test_checkpoint_rejects_boolean_sequence() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()

    with pytest.raises(ValueError, match="sequence_at"):
        save_checkpoint(
            session,
            battle.id,
            True,
            state,
            DeterministicDice(seed=battle.rng_seed),
        )


def test_latest_checkpoint_hides_stale_rng_position() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()
    dice = DeterministicDice(seed=battle.rng_seed)
    save_checkpoint(session, battle.id, 0, state, dice)
    save_events(
        session,
        battle.id,
        [MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))],
    )

    assert load_latest_checkpoint(session, battle.id) is None


def test_save_checkpoint_is_transactionally_neutral() -> None:
    session = _build_session()
    battle = _new_battle(session)
    state, _, _ = _play_smoke_battle()
    save_checkpoint(
        session,
        battle.id,
        0,
        state,
        DeterministicDice(seed=battle.rng_seed),
    )

    session.rollback()

    assert session.query(models.BattleCheckpoint).count() == 0


def test_event_type_column_matches_payload() -> None:
    """Kolumna `event_type` jest spójna z payloadem (discriminator)."""
    session = _build_session()
    battle = _new_battle(session)
    _, all_events, _ = _play_smoke_battle()
    save_events(session, battle.id, all_events)
    session.commit()

    rows = (
        session.query(models.BattleEvent)
        .filter_by(battle_id=battle.id)
        .order_by(models.BattleEvent.sequence)
        .all()
    )
    loaded = load_events(session, battle.id)
    for row, event in zip(rows, loaded):
        assert row.event_type == type(event).__name__


# ---------------------------------------------------------------------------
# Replay-from-DB invariant (GATE — ADR-0010 / ADR-0046 / ADR-0050)
# ---------------------------------------------------------------------------


def test_replay_from_db_invariant() -> None:
    """apply_events(initial, load_events(...)) == live final state (bit-perfect).

    Źródłem eventów jest BAZA, nie in-memory lista — dowód, że persystencja nie
    gubi informacji potrzebnej do pełnego replayu (ADR-0010 proof-of-completeness
    rozszerzony o warstwę DB)."""
    session = _build_session()
    battle = _new_battle(session)
    initial, all_events, live = _play_smoke_battle()
    save_events(session, battle.id, all_events)
    session.commit()

    loaded = load_events(session, battle.id)
    replayed = apply_events(initial, loaded)

    blob_fields = (
        "position",
        "models_alive",
        "wounds_received",
        "wounds_pending",
        "wounds_pending_precise",
        "wounds_eliminating",
        "is_hero_unit",
        "status_flags",
        "damage_balance",
        "location",
        "ability_overrides",
    )
    live_by_id = {b.id: b for b in live.blobs}
    rep_by_id = {b.id: b for b in replayed.blobs}
    assert set(live_by_id) == set(rep_by_id)
    for uid, lb in live_by_id.items():
        rb = rep_by_id[uid]
        for field in blob_fields:
            assert getattr(lb, field) == getattr(rb, field), (
                f"blob {uid}.{field}: live={getattr(lb, field)!r} "
                f"replayed={getattr(rb, field)!r}"
            )

    assert tuple((o.id, o.controller) for o in live.objectives) == tuple(
        (o.id, o.controller) for o in replayed.objectives
    )
    assert live.active_player == replayed.active_player


# ---------------------------------------------------------------------------
# UniqueConstraint + filtry
# ---------------------------------------------------------------------------


def test_unique_constraint_on_battle_sequence() -> None:
    """Dwa eventy z tym samym (battle_id, sequence) → IntegrityError."""
    session = _build_session()
    battle = _new_battle(session)
    ev = MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))
    dup = StatusAdded(sequence=1, target_id=1, status="Aktywowany")

    save_events(session, battle.id, [ev])
    session.commit()
    with pytest.raises(IntegrityError):
        save_events(session, battle.id, [dup])  # flush=True wymusza INSERT
    session.rollback()


def test_same_sequence_different_battles_ok() -> None:
    """Ten sam `sequence` w różnych bitwach jest dozwolony (constraint per-battle)."""
    session = _build_session()
    b1 = _new_battle(session, seed=1)
    b2 = _new_battle(session, seed=2)
    ev = MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))

    save_events(session, b1.id, [ev])
    save_events(session, b2.id, [ev])
    session.commit()

    assert load_events(session, b1.id) == [ev]
    assert load_events(session, b2.id) == [ev]


def test_latest_event_sequence_returns_max_or_zero() -> None:
    session = _build_session()
    empty = _new_battle(session, seed=1)
    filled = _new_battle(session, seed=2)
    events = [
        MoveExecuted(sequence=s, unit_id=1, from_pos=(0, 0), to_pos=(s, s))
        for s in (1, 2, 3)
    ]
    save_events(session, filled.id, events)
    session.commit()

    assert latest_event_sequence(session, empty.id) == 0
    assert latest_event_sequence(session, filled.id) == 3


def test_save_events_with_expected_latest_sequence_appends_contiguous_tail() -> None:
    session = _build_session()
    battle = _new_battle(session)
    first = MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))
    tail = [
        StatusAdded(sequence=2, target_id=1, status="Aktywowany"),
        MoveExecuted(sequence=3, unit_id=1, from_pos=(1, 1), to_pos=(2, 2)),
    ]
    save_events(session, battle.id, [first])
    session.commit()

    assert (
        save_events(
            session,
            battle.id,
            tail,
            expected_latest_sequence=1,
        )
        == 2
    )
    session.commit()

    assert load_events(session, battle.id) == [first, *tail]


def test_save_events_with_stale_expected_latest_sequence_raises_without_append() -> None:
    session = _build_session()
    battle = _new_battle(session)
    first = MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))
    stale_tail = [StatusAdded(sequence=1, target_id=1, status="Aktywowany")]
    save_events(session, battle.id, [first])
    session.commit()

    with pytest.raises(BattleEventSequenceConflict) as exc_info:
        save_events(
            session,
            battle.id,
            stale_tail,
            expected_latest_sequence=0,
        )

    assert exc_info.value.battle_id == battle.id
    assert exc_info.value.expected_latest_sequence == 0
    assert exc_info.value.actual_latest_sequence == 1
    assert load_events(session, battle.id) == [first]


def test_save_events_with_expected_latest_sequence_allows_empty_noop() -> None:
    session = _build_session()
    battle = _new_battle(session)

    assert save_events(session, battle.id, [], expected_latest_sequence=0) == 0
    assert latest_event_sequence(session, battle.id) == 0


def test_save_events_with_expected_latest_sequence_requires_contiguous_tail() -> None:
    session = _build_session()
    battle = _new_battle(session)
    gap = [MoveExecuted(sequence=2, unit_id=1, from_pos=(0, 0), to_pos=(2, 2))]

    with pytest.raises(ValueError, match="contiguous event sequences"):
        save_events(session, battle.id, gap, expected_latest_sequence=0)

    assert load_events(session, battle.id) == []


def test_save_events_rejects_negative_expected_latest_sequence() -> None:
    session = _build_session()
    battle = _new_battle(session)
    event = MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1))

    with pytest.raises(ValueError, match="must be >= 0"):
        save_events(session, battle.id, [event], expected_latest_sequence=-1)


def test_load_since_filter() -> None:
    """`since=N` zwraca tylko eventy z sequence > N, w kolejności."""
    session = _build_session()
    battle = _new_battle(session)
    events = [
        MoveExecuted(sequence=s, unit_id=1, from_pos=(0, 0), to_pos=(s, s))
        for s in (1, 2, 3, 4, 5)
    ]
    save_events(session, battle.id, events)
    session.commit()

    tail = load_events(session, battle.id, since=3)
    assert [e.sequence for e in tail] == [4, 5]


def test_load_events_optional_limit_returns_bounded_ordered_prefix() -> None:
    session = _build_session()
    battle = _new_battle(session)
    events = [
        StatusAdded(sequence=i, target_id=i, status="Aktywowany")
        for i in range(1, 6)
    ]
    save_events(session, battle.id, events)
    session.commit()

    assert load_events(session, battle.id, limit=2) == events[:2]
    assert load_events(session, battle.id, since=2, limit=2) == events[2:4]
    assert load_events(session, battle.id) == events


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_load_events_rejects_invalid_limit(limit) -> None:
    session = _build_session()
    battle = _new_battle(session)

    with pytest.raises(ValueError, match="limit must be a positive integer"):
        load_events(session, battle.id, limit=limit)


def test_load_empty_battle_returns_empty() -> None:
    session = _build_session()
    battle = _new_battle(session)
    assert load_events(session, battle.id) == []


def test_save_empty_events_is_noop() -> None:
    session = _build_session()
    battle = _new_battle(session)
    assert save_events(session, battle.id, []) == 0
    assert load_events(session, battle.id) == []


def test_battle_events_cascade_delete() -> None:
    """Usunięcie bitwy kasuje jej eventy (cascade all, delete-orphan)."""
    session = _build_session()
    battle = _new_battle(session)
    _, all_events, _ = _play_smoke_battle()
    save_events(session, battle.id, all_events)
    session.commit()

    session.delete(battle)
    session.commit()
    assert (
        session.query(models.BattleEvent).filter_by(battle_id=battle.id).count() == 0
    )
