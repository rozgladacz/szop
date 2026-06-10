"""D — testy `PriorityPlayer` (selekcja „najbliżej wroga" + priorytet 1–7, rev. 2)."""

from __future__ import annotations

from app.services.agents.priority_player import PriorityPlayer
from app.services.engine.geometry import distance
from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_WYCZERPANY,
)

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


def _state(blobs: tuple[UnitBlob, ...], objectives: tuple = ()) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


def test_returns_none_when_no_active_units():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert PriorityPlayer().choose_action(_state(blobs), perspective=0) is None


# --- selekcja: oddział najbliżej wroga ---


def test_selects_unit_closest_to_enemy():
    far = _blob(1, 0, 0, 0)
    near = _blob(2, 0, 20, 0)
    enemy = _blob(3, 1, 25, 0)
    action = PriorityPlayer().choose_action(_state((far, near, enemy)), 0)
    assert action is not None and action.unit_id == 2  # near


def test_selection_tie_breaks_by_lowest_id():
    a = _blob(5, 0, 0, 0)
    b = _blob(2, 0, 0, 0)  # ten sam dystans do wroga
    enemy = _blob(9, 1, 30, 0)
    action = PriorityPlayer().choose_action(_state((a, b, enemy)), 0)
    assert action is not None and action.unit_id == 2  # niższe id


# --- priorytet akcji ---


def test_priority1_discard_exhausted_before_shoot():
    # Wyczerpany (priorytet 1) ma pierwszeństwo NAWET gdy strzał możliwy (priorytet 2).
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,), status_flags=(STATUS_WYCZERPANY,))
    enemy = _blob(2, 1, 8, 0)
    action = PriorityPlayer().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, SpecialAction) and action.ability_slug == "discard_exhausted"


def test_priority2_shoot_nearest_visible():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    near = _blob(2, 1, 8, 0)
    far = _blob(3, 1, 16, 0)
    action = PriorityPlayer().choose_action(_state((own, near, far)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_priority3_charge_when_no_shoot():
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))  # brak broni dystansowej
    enemy = _blob(2, 1, 3, 0)
    action = PriorityPlayer().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ChargeAction) and action.target_id == 2


def test_priority4_defend_when_pinned():
    # Przyszpilony, brak wroga w zasięgu walki → Obrona (odrzuca Przyszpilony pkt 22.b.v).
    own = _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,))
    enemy = _blob(2, 1, 60, 0)
    action = PriorityPlayer().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, DefendAction)


# --- priorytet 5/6: ruch do niezajętego celu ---


def test_priority5_moves_to_uncontrolled_objective():
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(10, 0), controller=None)  # niezajęty, >3"
    enemy = _blob(2, 1, 60, 0)  # daleko (brak strzału/szarży)
    action = PriorityPlayer().choose_action(_state((own, enemy), (obj,)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, obj.position) < distance(own.position, obj.position)


def test_priority5_anti_clustering_each_unit_to_its_closest_objective():
    # Anty-klastrowanie: A rusza do obj1 (jest mu najbliżej), B do obj2 — nie oba na ten sam.
    a = _blob(1, 0, 0, 0)
    b = _blob(2, 0, 0, 20)
    obj1 = Objective(id=1, position=Position(8, 0), controller=None)   # bliżej A
    obj2 = Objective(id=2, position=Position(8, 20), controller=None)  # bliżej B
    state = _state((a, b), (obj1, obj2))
    bot = PriorityPlayer()
    mv_a = bot._act(state, 0, a)
    mv_b = bot._act(state, 0, b)
    assert isinstance(mv_a, ManeuverAction) and isinstance(mv_b, ManeuverAction)
    # A celuje w obj1 (maleje dystans do obj1), B w obj2.
    assert distance(mv_a.target_position, obj1.position) < distance(a.position, obj1.position)
    assert distance(mv_b.target_position, obj2.position) < distance(b.position, obj2.position)


def test_priority6_falls_back_to_nearest_uncontrolled_when_not_closest():
    # A nie jest najbliższy do żadnego niezajętego celu (B bliżej obu) → priorytet 6:
    # i tak rusza do najbliższego niezajętego (nie stoi).
    a = _blob(1, 0, 0, 0)
    b = _blob(2, 0, 7, 0)  # bliżej obu celów
    obj1 = Objective(id=1, position=Position(10, 0), controller=None)
    obj2 = Objective(id=2, position=Position(12, 0), controller=None)
    state = _state((a, b), (obj1, obj2))
    mv_a = PriorityPlayer()._act(state, 0, a)
    assert isinstance(mv_a, ManeuverAction)  # rusza (priorytet 6), nie stoi


def test_priority7_moves_to_nearest_enemy_when_no_uncontrolled_objective():
    # Brak niezajętych celów → priorytet 7: ruch do najbliższego wroga.
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 30, 0)
    action = PriorityPlayer().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, enemy.position) < distance(own.position, enemy.position)


# --- continue_activation (2. akcja, pkt 11.b.iv) ---


def test_continue_activation_shoots_after_maneuver():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    taken = (ManeuverAction(1, Position(0, 0)),)
    nxt = PriorityPlayer().continue_activation(_state((own, enemy)), 0, 1, taken)
    assert isinstance(nxt, ShootAction) and nxt.target_id == 2


def test_continue_activation_moves_to_objective_after_shoot():
    # Po Ostrzale (zużyty, pkt 14.c.v) bot schodzi do niezajętego celu — nie marnuje akcji.
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    obj = Objective(id=1, position=Position(20, 0), controller=None)
    taken = (ShootAction(1, 2, RIFLE),)
    nxt = PriorityPlayer().continue_activation(_state((own, enemy), (obj,)), 0, 1, taken)
    assert isinstance(nxt, ManeuverAction)
    assert distance(nxt.target_position, obj.position) < distance(own.position, obj.position)


def test_deterministic_choice():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    assert PriorityPlayer().choose_action(state, 0) == PriorityPlayer().choose_action(state, 0)
