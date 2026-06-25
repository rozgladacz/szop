"""faza-b-multi-action — testy pętli 1–2 akcji w aktywacji (pkt 11.b.iv).

Pkt 11.b.iv (po poprawce reguł 2026-06): aktywacja to do 2 akcji (Manewr liczy
się do limitu); Ostrzał raz (pkt 14.c.v), Szarża raz (pkt 14.d.vi). Sprawdza
`resolver.apply_activation` + `_can_take_followup` + replay invariant (ADR-0010).
"""

from __future__ import annotations

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoveExecuted, ShotResolved
from app.services.engine.resolver import (
    MAX_ACTIONS_PER_ACTIVATION,
    _can_take_followup,
    apply,
    apply_activation,
)
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    WeaponProfile,
    apply_events,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
SWORD = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)


def _blob(uid: int, owner: int, x: float, y: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": owner,
        "position": Position(x, y),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


def _state() -> BattleState:
    blobs = (
        _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,), melee_weapons=(SWORD,)),
        _blob(2, 1, 10, 0),
    )
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=(),
    )


# --- _can_take_followup (pkt 11.b.iv + 14.c.v/14.d.vi) ---


def test_followup_first_extra_action_allowed():
    assert _can_take_followup(ShootAction(1, 2, RIFLE), ()) is True


def test_followup_blocked_at_two_actions():
    taken = (ManeuverAction(1, Position(1, 0)), ShootAction(1, 2, RIFLE))
    assert _can_take_followup(ManeuverAction(1, Position(2, 0)), taken) is False


def test_followup_shoot_twice_rejected():
    assert _can_take_followup(ShootAction(1, 2, RIFLE), (ShootAction(1, 2, RIFLE),)) is False


def test_followup_charge_twice_rejected():
    assert _can_take_followup(ChargeAction(1, 2, SWORD), (ChargeAction(1, 2, SWORD),)) is False


def test_followup_shoot_then_charge_allowed():
    assert _can_take_followup(ChargeAction(1, 2, SWORD), (ShootAction(1, 2, RIFLE),)) is True


def test_followup_maneuver_then_maneuver_allowed():
    # Brak reguły „różna" + Manewr liczy się tylko do limitu 2 → Manewr×2 OK.
    assert _can_take_followup(ManeuverAction(1, Position(2, 0)), (ManeuverAction(1, Position(1, 0)),)) is True


# --- pętla apply_activation ---


def _count(events, cls) -> int:
    return sum(1 for e in events if isinstance(e, cls))


def test_no_continuation_is_single_action():
    state = _state()
    res = apply_activation(state, ManeuverAction(1, Position(5, 0)), DeterministicDice(1))
    assert _count(res.events, MoveExecuted) == 1
    unit = next(b for b in res.state.blobs if b.id == 1)
    assert STATUS_AKTYWOWANY in unit.status_flags
    assert unit.position == Position(5, 0)


def test_matches_apply_when_no_continuation():
    # apply_activation bez continuation == apply (ten sam wynik).
    a = apply(_state(), ManeuverAction(1, Position(5, 0)), DeterministicDice(1))
    b = apply_activation(_state(), ManeuverAction(1, Position(5, 0)), DeterministicDice(1))
    assert a.state == b.state
    assert a.events == b.events


def test_maneuver_then_shoot_both_applied():
    # Kanoniczne combo Strzelca: dojdź (Manewr) → strzel (Ostrzał).
    def cont(state, uid, taken):
        if len(taken) == 1 and isinstance(taken[0], ManeuverAction):
            return ShootAction(uid, 2, RIFLE)
        return None

    res = apply_activation(
        _state(), ManeuverAction(1, Position(4, 0)), DeterministicDice(7), continuation=cont
    )
    assert _count(res.events, MoveExecuted) == 1
    assert _count(res.events, ShotResolved) == 1  # strzał wykonany po ruchu
    unit = next(b for b in res.state.blobs if b.id == 1)
    assert unit.position == Position(4, 0) and STATUS_AKTYWOWANY in unit.status_flags


def test_shoot_twice_blocked_only_one_shot():
    # continuation próbuje strzelić drugi raz → odrzucone (pkt 14.c.v).
    def cont(state, uid, taken):
        return ShootAction(uid, 2, RIFLE)

    res = apply_activation(
        _state(), ShootAction(1, 2, RIFLE), DeterministicDice(3), continuation=cont
    )
    assert _count(res.events, ShotResolved) == 1


def test_cap_two_actions():
    # continuation zawsze Manewr → dokładnie 2 akcje (Manewr liczy się, pkt 11.b.iv).
    def cont(state, uid, taken):
        return ManeuverAction(uid, Position(float(len(taken) + 1), 0))

    res = apply_activation(
        _state(), ManeuverAction(1, Position(1, 0)), DeterministicDice(1), continuation=cont
    )
    assert _count(res.events, MoveExecuted) == MAX_ACTIONS_PER_ACTIVATION == 2


def test_continuation_for_other_unit_rejected():
    # continuation zwraca akcję dla innego oddziału → koniec aktywacji po 1 akcji.
    def cont(state, uid, taken):
        return ManeuverAction(2, Position(11, 0))  # cudzy oddział

    res = apply_activation(
        _state(), ManeuverAction(1, Position(5, 0)), DeterministicDice(1), continuation=cont
    )
    assert _count(res.events, MoveExecuted) == 1


# --- on_action hook (telemetria per-akcja, ADR-0017) ---


def test_on_action_fires_per_applied_action():
    # Manewr→Ostrzał: hook woła się 2× ze stanami bracketującymi pojedynczą akcję.
    def cont(state, uid, taken):
        if len(taken) == 1 and isinstance(taken[0], ManeuverAction):
            return ShootAction(uid, 2, RIFLE)
        return None

    seen: list[tuple] = []

    def obs(action, state_before, state_after):
        seen.append((type(action).__name__, state_before, state_after))

    apply_activation(
        _state(),
        ManeuverAction(1, Position(4, 0)),
        DeterministicDice(7),
        continuation=cont,
        on_action=obs,
    )
    assert [s[0] for s in seen] == ["ManeuverAction", "ShootAction"]
    # after 1. akcji == before 2. akcji (stany bracketują pojedynczą akcję).
    assert seen[0][2] == seen[1][1]
    # Manewr zmienił stan (pozycja) → before != after dla 1. akcji.
    assert seen[0][1] != seen[0][2]


def test_on_action_only_fires_for_applied_actions():
    # continuation zwraca 2. Ostrzał (odrzucony pkt 14.c.v) → hook tylko 1×.
    def cont(state, uid, taken):
        return ShootAction(uid, 2, RIFLE)

    count = 0

    def obs(action, state_before, state_after):
        nonlocal count
        count += 1

    apply_activation(
        _state(),
        ShootAction(1, 2, RIFLE),
        DeterministicDice(3),
        continuation=cont,
        on_action=obs,
    )
    assert count == 1


def test_on_action_none_is_noop():
    # on_action=None bit-perfect jak bez hooka (B7 golden bez zmian).
    a = apply_activation(_state(), ManeuverAction(1, Position(5, 0)), DeterministicDice(1))
    b = apply_activation(
        _state(), ManeuverAction(1, Position(5, 0)), DeterministicDice(1), on_action=None
    )
    assert a.state == b.state and a.events == b.events


def test_replay_invariant_two_action_activation():
    state = _state()

    def cont(state_, uid, taken):
        if len(taken) == 1:
            return ShootAction(uid, 2, RIFLE)
        return None

    res = apply_activation(state, ManeuverAction(1, Position(4, 0)), DeterministicDice(7), continuation=cont)
    replayed = apply_events(state, res.events)
    # Per-blob + active_player bit-perfect (jak smoke replay).
    live = {b.id: b for b in res.state.blobs}
    rep = {b.id: b for b in replayed.blobs}
    for uid in live:
        for f in ("position", "models_alive", "wounds_received", "status_flags", "damage_balance"):
            assert getattr(live[uid], f) == getattr(rep[uid], f), f"{uid}.{f}"
    assert res.state.active_player == replayed.active_player
