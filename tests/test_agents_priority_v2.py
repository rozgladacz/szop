"""D — testy `PriorityV2Player` (selekcja wielokryterialna + target + przechwyt)."""

from __future__ import annotations

from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.geometry import distance
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
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=blobs, terrain=(), objectives=objectives,
    )


# --- selekcja aktywacji ---


def test_selection_prefers_healthy_own_unit():
    pinned = _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,))
    healthy = _blob(2, 0, 0, 2)
    enemy = _blob(3, 1, 30, 0)
    action = PriorityV2Player().choose_action(_state((pinned, healthy, enemy)), 0)
    assert action is not None and action.unit_id == 2  # zdrowy wybrany mimo zbliższego pinned


def test_selection_prefers_unit_closest_to_non_activated_enemy():
    own1 = _blob(1, 0, 0, 0)
    own2 = _blob(2, 0, 20, 0)
    enemy_active = _blob(3, 1, 25, 0, status_flags=(STATUS_AKTYWOWANY,))  # blisko own2, ale aktywowany
    enemy_fresh = _blob(4, 1, 5, 0)  # blisko own1, nieaktywowany
    action = PriorityV2Player().choose_action(_state((own1, own2, enemy_active, enemy_fresh)), 0)
    assert action is not None and action.unit_id == 1  # bliżej nieaktywowanego wroga


# --- wybór celu ataku ---


def test_target_prefers_healthy_enemy():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    exhausted = _blob(2, 1, 8, 0, status_flags=(STATUS_WYCZERPANY,))  # bliżej, ale Wyczerpany
    healthy = _blob(3, 1, 10, 0)
    action = PriorityV2Player().choose_action(_state((own, exhausted, healthy)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 3


def test_target_prefers_non_activated_enemy():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    activated = _blob(2, 1, 8, 0, status_flags=(STATUS_AKTYWOWANY,))  # bliżej, aktywowany
    fresh = _blob(3, 1, 10, 0)
    action = PriorityV2Player().choose_action(_state((own, activated, fresh)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 3


def test_target_tie_breaks_by_nearest():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    near = _blob(2, 1, 8, 0)
    far = _blob(3, 1, 14, 0)  # identyczne staty → decyduje dystans
    action = PriorityV2Player().choose_action(_state((own, near, far)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 2


# --- priorytet akcji ---


def test_priority1_discard_exhausted_before_shoot():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,), status_flags=(STATUS_WYCZERPANY,))
    enemy = _blob(2, 1, 8, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, SpecialAction) and action.ability_slug == "discard_exhausted"


def test_priority3_charge_when_no_shoot():
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))
    enemy = _blob(2, 1, 3, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ChargeAction) and action.target_id == 2


def test_priority5_moves_to_uncontrolled_objective_it_is_closest_to():
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(10, 0), controller=None)
    enemy = _blob(2, 1, 60, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy), (obj,)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, obj.position) < distance(own.position, obj.position)


def test_priority6_intercept_enemy_threatening_held_objective():
    # Cel O zajęty przez nas; wróg bliżej O niż my (i nie na O) → ruch przechwytujący.
    own = _blob(1, 0, 20, 0)
    obj = Objective(id=1, position=Position(10, 0), controller=0)  # nasz
    enemy = _blob(2, 1, 15, 0)  # bliżej O (5<10), edge 4>3 (nie zajmuje), brak broni → nie strzelamy
    state = _state((own, enemy), (obj,))
    action = PriorityV2Player().choose_action(state, 0)
    assert isinstance(action, ManeuverAction)
    # Rusza ku wrogowi (maleje dystans do wroga).
    assert distance(action.target_position, enemy.position) < distance(own.position, enemy.position)


def test_priority8_moves_to_nearest_enemy_when_no_objective():
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 30, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, enemy.position) < distance(own.position, enemy.position)


# --- continue_activation ---


def test_continue_activation_after_shoot_moves():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    obj = Objective(id=1, position=Position(20, 0), controller=None)
    taken = (ShootAction(1, 2, RIFLE),)
    nxt = PriorityV2Player().continue_activation(_state((own, enemy), (obj,)), 0, 1, taken)
    assert isinstance(nxt, ManeuverAction)  # po strzale schodzi do celu, nie marnuje


def test_deterministic_choice():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    assert PriorityV2Player().choose_action(state, 0) == PriorityV2Player().choose_action(state, 0)
