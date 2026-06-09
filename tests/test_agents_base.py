"""D1 — testy enumeratora `legal_actions` + selektorów (`app/services/agents/base.py`).

Pokrywa: filtr własnych aktywowalnych oddziałów (Aktywowany/pokonany/Zaplecze),
Obrona zawsze, Odrzuć Wyczerpany warunkowo, Manewr (dyskretyzacja + clamp),
Ostrzał (zasięg + LoS), Szarża (zasięg Związania).
"""

from __future__ import annotations

import pytest

from app.services.agents.base import (
    enemy_units,
    legal_actions,
    own_active_units,
)
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
    Lokalizacja,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY, STATUS_WYCZERPANY

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


def _state(blobs: tuple[UnitBlob, ...], **kw) -> BattleState:
    defaults: dict = {
        "round": 1,
        "active_player": 0,
        "activations_remaining": (1, 1),
        "blobs": blobs,
        "terrain": (),
    }
    defaults.update(kw)
    return BattleState(**defaults)


def test_own_active_units_filters_activated_dead_zaplecze():
    blobs = (
        _blob(1, 0, 0, 0),  # active
        _blob(2, 0, 1, 0, status_flags=(STATUS_AKTYWOWANY,)),  # Aktywowany
        _blob(3, 0, 2, 0, models_alive=0),  # pokonany
        _blob(4, 0, 3, 0, location=Lokalizacja.ZAPLECZE),  # rezerwa
        _blob(5, 1, 4, 0),  # wróg
    )
    state = _state(blobs)
    active = own_active_units(state, perspective=0)
    assert [b.id for b in active] == [1]


def test_enemy_units_are_opponents_only():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 10, 0), _blob(3, 1, 12, 0, models_alive=0))
    state = _state(blobs)
    enemies = enemy_units(state, perspective=0)
    assert [b.id for b in enemies] == [2]  # id=3 pokonany odfiltrowany


def test_legal_actions_empty_when_no_active_units():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert legal_actions(_state(blobs), perspective=0) == []


def test_defend_always_present():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 30, 0))
    actions = legal_actions(_state(blobs), perspective=0)
    assert any(isinstance(a, DefendAction) and a.unit_id == 1 for a in actions)


def test_maneuver_targets_clamped_to_move():
    # Wróg daleko (40″) — Manewr ku niemu clampowany do move_inches (6).
    own = _blob(1, 0, 0, 0)
    blobs = (own, _blob(2, 1, 40, 0))
    actions = legal_actions(_state(blobs), perspective=0)
    maneuvers = [a for a in actions if isinstance(a, ManeuverAction)]
    assert maneuvers, "spodziewamy się przynajmniej Manewru ku wrogowi"
    for m in maneuvers:
        moved = distance(own.position, m.target_position)
        assert moved <= 6.0 + 1e-9


def test_shoot_when_in_range_and_clear_los():
    blobs = (
        _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)),
        _blob(2, 1, 10, 0),
    )
    actions = legal_actions(_state(blobs), perspective=0)
    shoots = [a for a in actions if isinstance(a, ShootAction)]
    assert len(shoots) == 1
    assert shoots[0].target_id == 2 and shoots[0].weapon is RIFLE


def test_no_shoot_when_out_of_range():
    blobs = (
        _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)),
        _blob(2, 1, 50, 0),  # gap ~48 > 24
    )
    actions = legal_actions(_state(blobs), perspective=0)
    assert not any(isinstance(a, ShootAction) for a in actions)


def test_charge_when_within_reach():
    blobs = (
        _blob(1, 0, 0, 0, melee_weapons=(SWORD,)),
        _blob(2, 1, 5, 0),  # gap = 5 - 1 - 1 = 3 ≤ move 6
    )
    actions = legal_actions(_state(blobs), perspective=0)
    charges = [a for a in actions if isinstance(a, ChargeAction)]
    assert len(charges) == 1 and charges[0].target_id == 2


def test_no_charge_when_too_far():
    blobs = (
        _blob(1, 0, 0, 0, melee_weapons=(SWORD,)),
        _blob(2, 1, 20, 0),  # gap = 18 > move 6
    )
    actions = legal_actions(_state(blobs), perspective=0)
    assert not any(isinstance(a, ChargeAction) for a in actions)


def test_discard_exhausted_only_when_wyczerpany():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_WYCZERPANY,)), _blob(2, 1, 30, 0))
    actions = legal_actions(_state(blobs), perspective=0)
    specials = [a for a in actions if isinstance(a, SpecialAction)]
    assert len(specials) == 1 and specials[0].ability_slug == "discard_exhausted"


def test_no_discard_when_not_wyczerpany():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 30, 0))
    actions = legal_actions(_state(blobs), perspective=0)
    assert not any(isinstance(a, SpecialAction) for a in actions)


def test_perspective_enumerates_correct_player():
    blobs = (_blob(1, 0, 0, 0), _blob(2, 1, 30, 0))
    p1_actions = legal_actions(_state(blobs), perspective=1)
    assert all(a.unit_id == 2 for a in p1_actions)
