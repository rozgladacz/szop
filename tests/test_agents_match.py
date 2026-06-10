"""D1/D2 — testy headless match runnera (`app/services/agents/match.py`).

Pokrywa: pełna gra kończy się po MAX_ROUND (pkt 5.f), determinizm per seed,
spójność winner↔score, przekazanie inicjatywy gdy aktywny gracz nie ma akcji.
"""

from __future__ import annotations

from app.services.agents.match import (
    MatchResult,
    run_match,
    simulate_from_rosters,
)
from app.services.agents.random_player import RandomPlayer
from app.services.agents.greedy_player import GreedyPlayer
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import InitiativePassed
from app.services.engine.phases import MAX_ROUND
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 2}
SWORD = {"slug": "sword", "name": "Sword", "range_inches": 0, "attacks": 2}


def _unit(uid: int, x: float, y: float, weapons: list | None = None) -> dict:
    return {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
        "weapons": weapons or [],
    }


def _rosters() -> list[dict]:
    return [
        {"owner_player": 0, "units": [_unit(1, 6, 0, [RIFLE]), _unit(2, 6, 6, [SWORD])]},
        {"owner_player": 1, "units": [_unit(3, 30, 0, [RIFLE]), _unit(4, 30, 6, [SWORD])]},
    ]


def _objectives() -> list[Objective]:
    return [Objective(id=1, position=Position(18, 3))]


def test_match_completes_and_reaches_max_round():
    result = simulate_from_rosters(
        _rosters(),
        [RandomPlayer(seed=1), RandomPlayer(seed=2)],
        seed=2026,
        objectives=_objectives(),
    )
    assert isinstance(result, MatchResult)
    assert result.final_state.is_game_over
    assert result.rounds_played == MAX_ROUND
    assert result.winner in (0, 1, None)
    assert len(result.events) > 0


def test_deterministic_same_seed():
    args = dict(seed=99, objectives=_objectives())
    r1 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(0)], **args)
    r2 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(0)], **args)
    assert r1.final_state == r2.final_state
    assert r1.winner == r2.winner
    assert len(r1.events) == len(r2.events)


def test_winner_consistent_with_score():
    result = simulate_from_rosters(
        _rosters(),
        [GreedyPlayer(), RandomPlayer(seed=5)],
        seed=7,
        objectives=_objectives(),
    )
    p0, p1 = result.final_state.score
    if p0 > p1:
        assert result.winner == 0
    elif p1 > p0:
        assert result.winner == 1
    else:
        assert result.winner is None


def test_greedy_vs_random_completes():
    result = simulate_from_rosters(
        _rosters(),
        [GreedyPlayer(), RandomPlayer(seed=3)],
        seed=11,
        objectives=_objectives(),
    )
    assert result.final_state.is_game_over


def _blob(uid: int, owner: int, x: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": owner,
        "position": Position(x, 0.0),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


def test_initiative_passes_when_active_player_has_no_actions():
    # P0 (aktywny) ma jedyny oddział już Aktywowany; P1 ma świeży oddział.
    # Runner musi przekazać inicjatywę do P1 i dokończyć grę.
    blobs = (
        _blob(1, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),
        _blob(2, 1, 30),
    )
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=(),
    )
    result = run_match(state, [RandomPlayer(1), RandomPlayer(2)], DeterministicDice(seed=1))
    assert result.final_state.is_game_over
    # Inicjatywa została przekazana co najmniej raz (P0 nie miał akcji w rundzie 1).
    assert any(isinstance(e, InitiativePassed) for e in result.events)
