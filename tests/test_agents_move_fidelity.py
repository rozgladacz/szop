"""faza-d-bots-szybki-wolny — boty enumerują Manewr/Szarżę per-oddziałowym
budżetem `effective_move_inches` (pkt 15.a ± zdolność 33 Szybki/Wolny), nie stałą
6″.

Guard latentnego `IllegalActionError`: od commita `faza-b-move-validation` resolver
waliduje `dist ≤ effective_move_inches(actor)`. Bot z cechą **Wolny** (ruch 4″)
enumerujący Manewr clamp 6″ rozbiłby `resolver.apply`. Bot **Szybki** (ruch 8″)
pod-ruszał (clamp 6″) i pomijał legalne Szarże w paśmie 6–8″.

Pokrywa:
- enumerator `base.legal_actions` clampuje Manewr do budżetu per-oddział,
- każdy enumerowany Manewr Wolny jest akceptowany przez `resolver.apply` (regresja),
- Szybki sięga pasma 6–8″ (Manewr) i zyskuje kandydata Szarży w tym paśmie,
- oddział bez Szybki/Wolny zachowuje bazowe 6″ (zero zmian zachowania → B7 golden),
- integracyjnie: 5 botów (priority/v2/v3/claude_v3/random) na oddziale Wolny
  produkuje akcję akceptowaną przez resolver (nie crashuje).
"""

from __future__ import annotations

import pytest

from app.services.agents.base import legal_actions
from app.services.agents.claude_v3_player import ClaudeV3Player
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.agents.random_player import RandomPlayer
from app.services.engine.actions import ChargeAction, ManeuverAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.geometry import distance
from app.services.engine.resolver import ResolverResult, apply
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
)

SWORD = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)
EPS = 1e-6


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


def _maneuvers(actions, uid: int) -> list[ManeuverAction]:
    return [a for a in actions if isinstance(a, ManeuverAction) and a.unit_id == uid]


def _charges(actions, uid: int) -> list[ChargeAction]:
    return [a for a in actions if isinstance(a, ChargeAction) and a.unit_id == uid]


# ---------------------------------------------------------------------------
# Enumerator base.legal_actions — clamp budżetu per-oddział
# ---------------------------------------------------------------------------


def test_wolny_maneuvers_clamp_to_four():
    own = _blob(1, 0, 0, 0, passives=("wolny",))
    enemy = _blob(2, 1, 30, 0)
    movs = _maneuvers(legal_actions(_state((own, enemy)), perspective=0), 1)
    assert movs  # co najmniej „stój" + ruch ku wrogowi
    for m in movs:
        assert distance(own.position, m.target_position) <= 4.0 + EPS
    # ruch ku wrogowi osiąga pełny budżet 4″ (nie bazowe 6″)
    assert any(
        abs(distance(own.position, m.target_position) - 4.0) < 1e-3 for m in movs
    )


def test_wolny_maneuvers_all_accepted_by_resolver():
    # RDZEŃ REGRESJI: pre-fix ruch ku wrogowi = 6″ → resolver odrzuca → crash.
    own = _blob(1, 0, 0, 0, passives=("wolny",))
    enemy = _blob(2, 1, 30, 0)
    state = _state((own, enemy))
    for m in _maneuvers(legal_actions(state, 0), 1):
        res = apply(state, m, DeterministicDice(7))
        assert isinstance(res, ResolverResult)


def test_szybki_maneuvers_reach_extended_band():
    own = _blob(1, 0, 0, 0, passives=("szybki",))
    enemy = _blob(2, 1, 30, 0)
    movs = _maneuvers(legal_actions(_state((own, enemy)), 0), 1)
    assert any(distance(own.position, m.target_position) > 6.0 + EPS for m in movs)
    assert all(distance(own.position, m.target_position) <= 8.0 + EPS for m in movs)


def test_szybki_enables_charge_in_six_to_eight_band():
    # edge gap = 9 − 1 − 1 = 7″ ∈ (6, 8]: poza bazowym 6″, w zasięgu Szybki 8″.
    own = _blob(1, 0, 0, 0, passives=("szybki",), melee_weapons=(SWORD,))
    enemy = _blob(2, 1, 9, 0)
    assert _charges(legal_actions(_state((own, enemy)), 0), 1)


def test_base_unit_no_charge_beyond_six():
    # Kontrola: ten sam 7″ gap bez Szybki → brak kandydata Szarży (budżet 6″).
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))
    enemy = _blob(2, 1, 9, 0)
    assert not _charges(legal_actions(_state((own, enemy)), 0), 1)


def test_normal_unit_keeps_base_six():
    # Brak Szybki/Wolny → identycznie jak przed zmianą (budżet 6″) → B7 golden.
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 30, 0)
    movs = _maneuvers(legal_actions(_state((own, enemy)), 0), 1)
    assert any(
        abs(distance(own.position, m.target_position) - 6.0) < 1e-3 for m in movs
    )
    assert all(distance(own.position, m.target_position) <= 6.0 + EPS for m in movs)


# ---------------------------------------------------------------------------
# Integracja: boty na oddziale Wolny nie crashują resolvera
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "player",
    [
        PriorityPlayer(),
        PriorityV2Player(),
        PriorityV3Player(),
        ClaudeV3Player(),
        RandomPlayer(seed=3),
    ],
    ids=["priority", "priority2", "priority3", "claude_v3", "random"],
)
def test_wolny_bot_action_accepted_by_resolver(player):
    own = _blob(1, 0, 0, 0, passives=("wolny",), melee_weapons=(SWORD,))
    enemy = _blob(2, 1, 30, 0)
    obj = Objective(id=1, position=Position(30, 0))  # niezajęty → wymusza Manewr
    state = _state((own, enemy), objectives=(obj,))
    action = player.choose_action(state, perspective=0)
    assert action is not None
    res = apply(state, action, DeterministicDice(11))
    assert isinstance(res, ResolverResult)
    if isinstance(action, ManeuverAction):
        # Manewr respektuje budżet Wolny (≤4″), nie bazowe 6″.
        assert distance(own.position, action.target_position) <= 4.0 + EPS


@pytest.mark.parametrize(
    "player",
    [
        PriorityPlayer(),
        PriorityV2Player(),
        PriorityV3Player(),
        ClaudeV3Player(),
        RandomPlayer(seed=5),
    ],
    ids=["priority", "priority2", "priority3", "claude_v3", "random"],
)
def test_bot_action_accepted_when_enemy_is_too_close_for_maneuver(player):
    # Enemy is within the 6" movement budget, but ending on it would violate
    # pkt 15.b.iii (>1" from models of other units). Bots must not return that
    # illegal ManeuverAction.
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 5, 0)
    state = _state((own, enemy))
    action = player.choose_action(state, perspective=0)
    assert action is not None
    res = apply(state, action, DeterministicDice(13))
    assert isinstance(res, ResolverResult)
    if isinstance(action, ManeuverAction):
        assert action.target_position != enemy.position
