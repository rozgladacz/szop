"""D — testy `PriorityPlayer` (selekcja po koszcie + priorytet akcji 1–7)."""

from __future__ import annotations

from app.services.agents.priority_player import PriorityPlayer
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


# --- selekcja oddziału ---


def test_selects_most_expensive_unit_with_objective_in_range():
    # Oba mają cel w zasięgu; droższy (więcej HP) zostaje wybrany.
    cheap = _blob(1, 0, 0, 0, models_alive=2)          # HP 6
    pricey = _blob(2, 0, 0, 4, models_alive=8)         # HP 24
    obj = Objective(id=1, position=Position(2, 2))     # ~w zasięgu obu
    action = PriorityPlayer().choose_action(_state((cheap, pricey), (obj,)), 0)
    assert action is not None and action.unit_id == 2


def test_selection_fallback_when_no_objective_in_range():
    # Cel daleko poza zasięgiem ruchu → fallback: najdroższy aktywny i tak działa.
    u1 = _blob(1, 0, 0, 0, models_alive=3)
    u2 = _blob(2, 0, 0, 4, models_alive=7)
    obj = Objective(id=1, position=Position(60, 60))
    action = PriorityPlayer().choose_action(_state((u1, u2), (obj,)), 0)
    assert action is not None and action.unit_id == 2  # droższy


def test_cost_tie_breaks_by_lowest_id():
    a = _blob(3, 0, 0, 0)
    b = _blob(7, 0, 0, 4)
    obj = Objective(id=1, position=Position(2, 2))
    action = PriorityPlayer().choose_action(_state((a, b), (obj,)), 0)
    assert action is not None and action.unit_id == 3


# --- priorytet akcji ---


def test_priority1_shoot_nearest():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    near = _blob(2, 1, 8, 0)
    far = _blob(3, 1, 16, 0)
    action = PriorityPlayer().choose_action(_state((own, near, far)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_priority2_charge_when_no_shoot():
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))  # brak broni dystansowej
    enemy = _blob(2, 1, 3, 0)                          # w zasięgu Związania
    action = PriorityPlayer().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ChargeAction) and action.target_id == 2


def test_priority3_discard_exhausted():
    # Brak wrogów → bez strzału/szarży; Wyczerpany → Odrzuć Wyczerpany.
    own = _blob(1, 0, 0, 0, status_flags=(STATUS_WYCZERPANY,))
    action = PriorityPlayer().choose_action(_state((own,)), 0)
    assert isinstance(action, SpecialAction) and action.ability_slug == "discard_exhausted"


def test_priority4_defend_when_pinned():
    # Przyszpilony (nie Wyczerpany), brak wrogów → Obrona (odrzuca Przyszpilony pkt 22.b.v).
    own = _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,))
    action = PriorityPlayer().choose_action(_state((own,)), 0)
    assert isinstance(action, DefendAction)


def test_priority6_move_to_objective_when_not_on_it():
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(10, 0))  # gap 9 > 3 → nie na celu
    action = PriorityPlayer().choose_action(_state((own,), (obj,)), 0)
    assert isinstance(action, ManeuverAction)
    assert action.target_position != own.position  # ruch ku celowi


def test_holds_objective_when_already_on_it():
    # Na celu + brak wrogów → krok 6 nie odpala → Obrona (trzyma cel).
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(1, 0))  # gap 0 ≤ 3 → na celu
    action = PriorityPlayer().choose_action(_state((own,), (obj,)), 0)
    assert isinstance(action, DefendAction)


def test_priority5_aggressive_unit_seeks_enemy_objective_when_behind():
    # Mag na własnym celu, ale przeciwnik kontroluje 2 > 1 → rusza na nie-swój cel
    # (zamiast Obrony z kroku 7). Bez wrogów w zasięgu walki.
    mag = _blob(1, 0, 0, 0, passives=("mag",))
    obj_mine = Objective(id=1, position=Position(1, 0))      # mag na nim → own=1
    e1 = _blob(2, 1, 30, 0)
    e2 = _blob(3, 1, 30, 6)
    obj_e1 = Objective(id=2, position=Position(30, 0))       # enemy
    obj_e2 = Objective(id=3, position=Position(30, 6))       # enemy → enemy=2
    state = _state((mag, e1, e2), (obj_mine, obj_e1, obj_e2))
    action = PriorityPlayer().choose_action(state, 0)
    assert isinstance(action, ManeuverAction)
    assert action.target_position != mag.position  # opuszcza swój cel ku wrogiemu


def test_plain_unit_on_objective_does_not_seek_enemy_objective():
    # Bez mag/bohater krok 5 nie odpala → na własnym celu Obrona (trzyma), mimo deficytu.
    plain = _blob(1, 0, 0, 0)
    obj_mine = Objective(id=1, position=Position(1, 0))
    e1 = _blob(2, 1, 30, 0)
    e2 = _blob(3, 1, 30, 6)
    obj_e1 = Objective(id=2, position=Position(30, 0))
    obj_e2 = Objective(id=3, position=Position(30, 6))
    state = _state((plain, e1, e2), (obj_mine, obj_e1, obj_e2))
    action = PriorityPlayer().choose_action(state, 0)
    assert isinstance(action, DefendAction)


def test_deterministic_choice():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    a1 = PriorityPlayer().choose_action(state, 0)
    a2 = PriorityPlayer().choose_action(state, 0)
    assert a1 == a2


# --- continue_activation (2. akcja, pkt 11.b.iv) ---


def test_continue_activation_shoots_after_maneuver():
    # Po Manewrze (akcja 1) wróg w zasięgu → priorytet 1 = Ostrzał najbliższego.
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    taken = (ManeuverAction(1, Position(0, 0)),)
    nxt = PriorityPlayer().continue_activation(state, 0, 1, taken)
    assert isinstance(nxt, ShootAction) and nxt.target_id == 2


def test_continue_activation_none_when_shoot_used_and_no_melee():
    # Ostrzał już wykonany (pkt 14.c.v) + brak broni wręcz → brak kontynuacji.
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    taken = (ShootAction(1, 2, RIFLE),)
    assert PriorityPlayer().continue_activation(state, 0, 1, taken) is None
