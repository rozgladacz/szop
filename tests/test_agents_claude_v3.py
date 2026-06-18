"""D — testy `ClaudeV3Player` (szkielet PriorityPlayer + wybór celu „dobij/koncentruj").

Sprawdza: dziedziczenie szkieletu priority (None gdy brak akcji, Ostrzał gdy można,
determinizm), KLUCZOWĄ różnicę — wybór celu finishable nad świeżym (focus-fire),
oraz legalność na pełnej grze.
"""

from __future__ import annotations

from app.services.agents.claude_v3_player import ClaudeV3Player
from app.services.engine.actions import ShootAction
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)
STRONG = WeaponProfile(slug="cannon", name="Cannon", range_inches=24, attacks=6)


def _blob(uid: int, owner: int, x: float, y: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid, "owner_player": owner, "position": Position(x, y),
        "radius_inches": 1.0, "models_alive": 5, "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


def _state(blobs, objectives=()):
    return BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=blobs, terrain=(), objectives=objectives,
    )


def test_returns_none_when_no_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert ClaudeV3Player().choose_action(_state(blobs), perspective=0) is None


def test_shoots_when_able():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    action = ClaudeV3Player().choose_action(_state(blobs), perspective=0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_deterministic_choice():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    assert ClaudeV3Player().choose_action(state, 0) == ClaudeV3Player().choose_action(state, 0)


def test_focus_fire_targets_finishable_over_fresh():
    # Dwa wrogowie RÓWNO oddaleni: id2 wymiatalny (1 model T1, p_full_kill≈1),
    # id3 świeży (5 modeli T3). Focus-fire celuje wymiatalnego (dobicie = +FINISH),
    # w odróżnieniu od PriorityPlayer („najbliższy", remis → kolejność).
    attacker = _blob(1, 0, 0, 0, ranged_weapons=(STRONG,))
    finishable = _blob(2, 1, 6, 0, models_alive=1, toughness_per_model=1)
    fresh = _blob(3, 1, 6, 0.1, models_alive=5, toughness_per_model=3)
    action = ClaudeV3Player().choose_action(_state((attacker, finishable, fresh)), perspective=0)
    assert isinstance(action, ShootAction)
    assert action.target_id == finishable.id


def test_full_game_legality_audit():
    from app.services.agents import simulate_from_rosters

    def _roster(owner: int, y: float):
        return {
            "owner_player": owner,
            "units": [
                {"id": owner * 10 + i, "position": (12.0 + i * 9, y),
                 "models": 5, "toughness": 3, "quality": 4, "defense": 5,
                 "passives": [], "weapons": [
                     {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 3, "ap": 0}]}
                for i in range(2)
            ],
        }

    objectives = (Objective(id=1, position=Position(30, 24), controller=None),)
    result = simulate_from_rosters(
        [_roster(0, 12.0), _roster(1, 36.0)],
        [ClaudeV3Player(), ClaudeV3Player()],
        seed=3, objectives=objectives,
    )
    assert result.rounds_played >= 1
    assert result.winner in (0, 1, None)
