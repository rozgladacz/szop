"""D1 — testy `GreedyPlayer` (depth-1 argmax: atak > obrona, marsz na cel)."""

from __future__ import annotations

from app.services.agents.greedy_player import GreedyPlayer
from app.services.engine.actions import ManeuverAction, ShootAction
from app.services.engine.geometry import distance
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)
#: Słaby (1 atak) — niskie oczekiwane obrażenia, by kontrola celu przeważyła.
WEAK = WeaponProfile(slug="pistol", name="Pistol", range_inches=24, attacks=1)
#: Mocny (6 ataków) — wymiata słaby oddział (expected_models_killed → 1).
STRONG = WeaponProfile(slug="cannon", name="Cannon", range_inches=24, attacks=6)


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


def _state(blobs: tuple[UnitBlob, ...], objectives: tuple = ()) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


def test_returns_none_when_no_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert GreedyPlayer().choose_action(_state(blobs), perspective=0) is None


def test_prefers_attack_over_passive_actions():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    action = GreedyPlayer().choose_action(_state(blobs), perspective=0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_prefers_maneuver_toward_objective_when_no_attack():
    # Bez broni → brak ataków; bliski niezajęty cel czyni marsz najlepszą akcją.
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(6, 0), controller=None)
    action = GreedyPlayer().choose_action(_state((own,), (obj,)), perspective=0)
    assert isinstance(action, ManeuverAction)
    # Ruch zbliża do celu (nie "stój").
    assert action.target_position != own.position


def test_deterministic_choice():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    a1 = GreedyPlayer().choose_action(state, perspective=0)
    a2 = GreedyPlayer().choose_action(state, perspective=0)
    assert a1 == a2


def test_prefers_taking_objective_over_weak_attack():
    # Słaby atak (1 atak vs wytrzymały wróg) daje mało obrażeń; marsz na niezajęty
    # cel przejmuje kontrolę (pkt 5.d, +OBJECTIVE_WEIGHT) → przeważa.
    own = _blob(1, 0, 0, 0, ranged_weapons=(WEAK,))
    enemy = _blob(2, 1, 10, 0, toughness_per_model=6)  # daleko od celu, wytrzymały
    obj = Objective(id=1, position=Position(5, 0), controller=None)
    action = GreedyPlayer().choose_action(_state((own, enemy), (obj,)), perspective=0)
    assert isinstance(action, ManeuverAction)
    # Ruch ląduje w 3″ od celu (zajmuje go, pkt 5.d).
    assert distance(action.target_position, obj.position) <= 3.0


def test_continue_activation_takes_beneficial_followup():
    # Po Manewrze, wróg w zasięgu → 2. akcja = Ostrzał (score > DEFEND_VALUE).
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    nxt = GreedyPlayer().continue_activation(state, 0, 1, (ManeuverAction(1, Position(0, 0)),))
    assert isinstance(nxt, ShootAction)


def test_continue_activation_none_when_nothing_beneficial():
    # Brak wrogów i celów → najlepsza kontynuacja ≤ DEFEND_VALUE → None (nie marnuje akcji).
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    state = _state((own,))
    assert GreedyPlayer().continue_activation(state, 0, 1, (ManeuverAction(1, Position(0, 0)),)) is None


def test_attack_prefers_enemy_contesting_my_objective():
    # Dwa identyczne, wymiataalne wrogie oddziały: A kontestuje mój cel, B w polu.
    # Obrażenia równe → bonus kontroli celu (wymiecenie A → przejęcie) rozstrzyga.
    own = _blob(1, 0, 0, 0, ranged_weapons=(STRONG,))
    enemy_a = _blob(2, 1, 1, 0, models_alive=1, toughness_per_model=1)  # na celu
    enemy_b = _blob(3, 1, 5, 0, models_alive=1, toughness_per_model=1)  # w polu
    obj = Objective(id=1, position=Position(0, 0), controller=None)
    action = GreedyPlayer().choose_action(
        _state((own, enemy_a, enemy_b), (obj,)), perspective=0
    )
    assert isinstance(action, ShootAction)
    assert action.target_id == enemy_a.id
