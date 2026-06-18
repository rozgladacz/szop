"""D4 — testy `MinimaxPlayer` (lookahead depth-2 maximin).

Pokrywa: brak akcji → None, determinizm per seed, legalność wyboru, zdobycie
niezajętego celu (pkt 5.d), **kluczowy różnik depth-2** — wycena uwzględnia
najlepszą odpowiedź wroga (`_opponent_best_value` < ocena bez odpowiedzi gdy wróg
może poprawić swoją pozycję), kontynuacja aktywacji (pkt 11.b.iv) oraz integracja
z pełną grą (`simulate_from_rosters`, determinizm).
"""

from __future__ import annotations

from app.services.agents.match import simulate_from_rosters
from app.services.agents.minimax_player import MinimaxPlayer
from app.services.agents.base import legal_actions
from app.services.engine.actions import ManeuverAction
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)


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


def _state(
    blobs: tuple[UnitBlob, ...],
    objectives: tuple = (),
    active_player: int = 0,
) -> BattleState:
    return BattleState(
        round=1,
        active_player=active_player,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


# --- engine-dict rostery dla testów integracyjnych -------------------------

_RIFLE_D = {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 2}
_SWORD_D = {"slug": "sword", "name": "Sword", "range_inches": 0, "attacks": 2}


def _unit_d(uid: int, x: float, y: float, weapons: list) -> dict:
    return {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
        "weapons": weapons,
    }


def _rosters() -> list[dict]:
    return [
        {"owner_player": 0, "units": [_unit_d(1, 6, 0, [_RIFLE_D]), _unit_d(2, 6, 6, [_SWORD_D])]},
        {"owner_player": 1, "units": [_unit_d(3, 30, 0, [_RIFLE_D]), _unit_d(4, 30, 6, [_SWORD_D])]},
    ]


def _objectives() -> list[Objective]:
    return [Objective(id=1, position=Position(18, 3))]


# --- testy jednostkowe -----------------------------------------------------


def test_returns_none_when_no_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert MinimaxPlayer().choose_action(_state(blobs), perspective=0) is None


def test_deterministic_choice():
    # Ten sam seed + ten sam stan → ta sama akcja (rollout deterministyczny).
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    a1 = MinimaxPlayer(seed=7).choose_action(state, perspective=0)
    a2 = MinimaxPlayer(seed=7).choose_action(state, perspective=0)
    assert a1 == a2


def test_returned_action_is_legal():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    action = MinimaxPlayer(seed=1).choose_action(state, perspective=0)
    assert action in legal_actions(state, perspective=0)


def test_captures_uncontrolled_objective():
    # Bez wrogów, niezajęty cel w zasięgu ruchu → marsz na cel zdobywa kontrolę
    # (pkt 5.d), co maksymalizuje ocenę → minimax wybiera Manewr ku celowi.
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(5, 0), controller=None)
    action = MinimaxPlayer(seed=1).choose_action(_state((own,), (obj,)), perspective=0)
    assert isinstance(action, ManeuverAction)
    assert action.target_position != own.position  # zbliża do celu, nie "stój"


def test_opponent_lookahead_penalizes_value():
    """Różnik depth-2: wycena uwzględnia najlepszą odpowiedź wroga.

    Tura wroga (active_player=1); wrogi oddział może wejść na niezajęty cel i go
    przejąć (pkt 5.d). `_opponent_best_value` z mojej (0) perspektywy MUSI być
    niższa niż ocena tego stanu BEZ odpowiedzi wroga — bo wróg poprawia pozycję.
    """
    enemy = _blob(1, 1, 0, 0)  # wróg przy celu (active_player=1)
    mine = _blob(2, 0, 50, 50)  # mój oddział daleko (nie kontroluje)
    obj = Objective(id=1, position=Position(5, 0), controller=None)
    state = _state((enemy, mine), (obj,), active_player=1)
    bot = MinimaxPlayer(seed=1)
    no_reply = bot._evaluate(state, perspective=0)
    with_reply = bot._opponent_best_value(state, perspective=0)
    assert with_reply < no_reply


def test_continue_activation_none_when_no_followups():
    # Oddział już Aktywowany (lub brak kandydatów) → brak kontynuacji.
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    state = _state(blobs)
    result = MinimaxPlayer().continue_activation(
        state, perspective=0, unit_id=1, actions_taken=()
    )
    assert result is None


# --- testy integracyjne ----------------------------------------------------


def test_full_game_runs_and_is_deterministic():
    args = dict(seed=2026, objectives=_objectives())
    r1 = simulate_from_rosters(_rosters(), [MinimaxPlayer(0), MinimaxPlayer(0)], **args)
    r2 = simulate_from_rosters(_rosters(), [MinimaxPlayer(0), MinimaxPlayer(0)], **args)
    assert r1.final_state == r2.final_state
    assert r1.winner == r2.winner
    assert r1.winner in (0, 1, None)
    assert len(r1.events) > 0


def test_minimax_beats_greedy_sanity():
    # Sanity: lookahead depth-2 bije depth-1 greedy na lustrzanej geometrii
    # (zero dzielonego biasu — różne seedy graczy via simulate_from_rosters).
    from app.services.agents.greedy_player import GreedyPlayer

    wins = 0
    for i in range(4):
        res = simulate_from_rosters(
            _rosters(),
            [MinimaxPlayer(0), GreedyPlayer()],
            seed=100 + i,
            objectives=_objectives(),
        )
        if res.winner == 0:
            wins += 1
    assert wins >= 2  # minimax wygrywa większość
