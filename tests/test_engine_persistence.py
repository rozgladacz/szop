"""B2 event-store — testy persystencji (ADR-0050).

Weryfikuje, że `persistence.save_events`/`load_events` round-trip'ują pełen
strumień eventów przez prawdziwą bazę bez utraty informacji, oraz że replay z
bazy jest bit-perfect (inwariant ADR-0010/0046, ale źródłem eventów jest DB).

Bateria bitwy reużywa scenariusz ze `scripts/engine_smoke_replay.py` (2v2,
2 rundy) — gęsty strumień obejmujący Move/Shot/Charge/Defend/Status/Round/
Objective/Initiative/MoraleTest/MeleeBalanceReset eventy.
"""

from __future__ import annotations

import sys
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
from app.services.engine.persistence import load_events, save_events  # noqa: E402
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
            (0, ManeuverAction(unit_id=1, target_position=Position(15, 0))),
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
        "melee_balance",
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
