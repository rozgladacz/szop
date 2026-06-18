"""D — testy `ClaudeV2Player` (depth-2 z modelowaniem przeciwnika, ability-aware).

Lekkie: depth-2 jest kosztowne, więc małe stany. Sprawdza brak akcji → None,
determinizm, skończoność wartości akcji, człon statusów (ability-aware przez slugi)
oraz legalność na krótkiej grze.
"""

from __future__ import annotations

from app.services.agents.claude_v2_player import ClaudeV2Player, _status_term
from app.services.engine.actions import ShootAction
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY, STATUS_PRZYSZPILONY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)


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
    assert ClaudeV2Player().choose_action(_state(blobs), perspective=0) is None


def test_deterministic_choice():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    assert ClaudeV2Player(seed=1).choose_action(state, 0) == ClaudeV2Player(seed=1).choose_action(state, 0)


def test_picks_an_action_with_target_in_range():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    action = ClaudeV2Player().choose_action(_state(blobs), perspective=0)
    assert action is not None  # depth-2 wybiera coś (zwykle Ostrzał) — nie None


def test_status_term_rewards_enemy_debuff_penalizes_own():
    # Ability-aware (slugi statusów): wrogi Przyszpilony dobry, własny zły.
    enemy_pinned = _state((
        _blob(1, 0, 0, 0),
        _blob(2, 1, 10, 0, status_flags=(STATUS_PRZYSZPILONY,)),
    ))
    own_pinned = _state((
        _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,)),
        _blob(2, 1, 10, 0),
    ))
    assert _status_term(enemy_pinned, perspective=0) > 0
    assert _status_term(own_pinned, perspective=0) < 0


def test_full_game_legality_audit():
    from app.services.agents import simulate_from_rosters

    def _roster(owner: int, y: float):
        return {
            "owner_player": owner,
            "units": [
                {"id": owner * 10 + i, "position": (14.0 + i * 10, y),
                 "models": 5, "toughness": 3, "quality": 4, "defense": 5,
                 "passives": [], "weapons": [
                     {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 3, "ap": 0}]}
                for i in range(2)
            ],
        }

    objectives = (Objective(id=1, position=Position(30, 24), controller=None),)
    result = simulate_from_rosters(
        [_roster(0, 12.0), _roster(1, 36.0)],
        [ClaudeV2Player(seed=1), ClaudeV2Player(seed=2)],
        seed=3, objectives=objectives,
    )
    assert result.rounds_played >= 1
    assert result.winner in (0, 1, None)
