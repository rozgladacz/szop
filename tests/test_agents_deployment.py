"""D5 — testy rozstawienia jako decyzji bota (`app/services/agents/deployment.py`
+ `Player.choose_deployment` + `simulate_from_rosters(deployment_zones=)`).

Pokrywa: geometria strefy (pkt 24/13.a MVP), proste strategie (grid + losowa),
default ABC (wsteczna kompat), walidacja poza-strefą (`IllegalActionError`),
różne pozycje per gracz, integracja z runnerem + determinizm.
"""

from __future__ import annotations

import random

import pytest

from app.services.agents.base import Player
from app.services.agents.deployment import (
    DeploymentZone,
    grid_positions,
    random_position_in_zone,
)
from app.services.agents.match import (
    _build_deployment_from_players,
    simulate_from_rosters,
)
from app.services.agents.random_player import RandomPlayer
from app.services.engine.phases import setup_phase
from app.services.engine.resolver import IllegalActionError
from app.services.engine.state import Objective, Position

RIFLE = {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 2}
SWORD = {"slug": "sword", "name": "Sword", "range_inches": 0, "attacks": 2}

# Strefy rozstawienia (pkt 24): prostokąty przy krawędziach planszy 72×48,
# głębokie 12″, oddalone od siebie o 24″ (pkt 3.a).
ZONE_P0 = DeploymentZone(0.0, 0.0, 72.0, 12.0)
ZONE_P1 = DeploymentZone(0.0, 36.0, 72.0, 48.0)
ZONES = (ZONE_P0, ZONE_P1)


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
    # Pozycje startowe (z roster) celowo w strefach graczy.
    return [
        {"owner_player": 0, "units": [_unit(1, 6, 6, [RIFLE]), _unit(2, 30, 6, [SWORD])]},
        {"owner_player": 1, "units": [_unit(3, 6, 42, [RIFLE]), _unit(4, 30, 42, [SWORD])]},
    ]


def _objectives() -> list[Objective]:
    return [Objective(id=1, position=Position(36, 24))]


def _state():
    return setup_phase(_rosters(), objectives=_objectives())


# --------------------------------------------------------------------------- #
# DeploymentZone.contains_circle (pkt 13.a MVP)
# --------------------------------------------------------------------------- #


def test_contains_circle_inside():
    zone = DeploymentZone(0, 0, 10, 10)
    assert zone.contains_circle(Position(5, 5), 2.0)


def test_contains_circle_touching_edge_ok():
    zone = DeploymentZone(0, 0, 10, 10)
    # Koło dotyka wszystkich krawędzi — wciąż w środku (tolerancja float).
    assert zone.contains_circle(Position(5, 5), 5.0)


def test_contains_circle_crossing_edge_rejected():
    zone = DeploymentZone(0, 0, 10, 10)
    assert not zone.contains_circle(Position(1, 5), 2.0)  # x-r = -1 < 0
    assert not zone.contains_circle(Position(5, 9), 2.0)  # y+r = 11 > 10


# --------------------------------------------------------------------------- #
# Proste strategie
# --------------------------------------------------------------------------- #


def test_grid_positions_count_and_in_zone():
    zone = DeploymentZone(0, 0, 72, 12)
    positions = grid_positions(zone, 4, radius=1.0)
    assert len(positions) == 4
    assert all(zone.contains_circle(p, 1.0) for p in positions)


def test_grid_positions_deterministic():
    zone = DeploymentZone(0, 0, 72, 12)
    assert grid_positions(zone, 5, 1.0) == grid_positions(zone, 5, 1.0)


def test_grid_positions_empty_for_nonpositive():
    zone = DeploymentZone(0, 0, 72, 12)
    assert grid_positions(zone, 0, 1.0) == []
    assert grid_positions(zone, -3, 1.0) == []


def test_grid_positions_degenerate_zone_centers():
    # Koło szersze niż strefa → degraduje do środka osi (bez wyjątku).
    zone = DeploymentZone(0, 0, 2, 2)
    positions = grid_positions(zone, 3, radius=5.0)
    assert len(positions) == 3
    assert all(p == Position(1.0, 1.0) for p in positions)


def test_random_position_in_zone_is_legal():
    zone = DeploymentZone(0, 0, 72, 12)
    rng = random.Random(123)
    for _ in range(50):
        pos = random_position_in_zone(rng, zone, radius=2.0)
        assert zone.contains_circle(pos, 2.0)


def test_random_position_deterministic_per_rng():
    zone = DeploymentZone(0, 0, 72, 12)
    a = random_position_in_zone(random.Random(7), zone, 2.0)
    b = random_position_in_zone(random.Random(7), zone, 2.0)
    assert a == b


# --------------------------------------------------------------------------- #
# Player.choose_deployment
# --------------------------------------------------------------------------- #


class _PassivePlayer(Player):
    """Minimalny gracz: brak akcji, dziedziczy default `choose_deployment`."""

    def choose_action(self, state, perspective):
        return None


class _OutOfZonePlayer(Player):
    """Gracz zwracający pozycję poza planszą (test walidacji pkt 13.a)."""

    def choose_action(self, state, perspective):
        return None

    def choose_deployment(self, state, unit_id, zone):
        return Position(-100.0, -100.0)


def test_default_choose_deployment_returns_current_position():
    state = _state()
    player = _PassivePlayer()
    # Oddział 1 startuje na (6, 6) z roster → default zwraca tę pozycję.
    assert player.choose_deployment(state, 1, ZONE_P0) == Position(6.0, 6.0)


def test_random_player_choose_deployment_in_zone():
    state = _state()
    player = RandomPlayer(seed=42)
    pos = player.choose_deployment(state, 1, ZONE_P0)
    blob = next(b for b in state.blobs if b.id == 1)
    assert ZONE_P0.contains_circle(pos, blob.radius_inches)


# --------------------------------------------------------------------------- #
# _build_deployment_from_players + walidacja
# --------------------------------------------------------------------------- #


def test_build_deployment_all_in_own_zone():
    state = _state()
    players = [RandomPlayer(seed=1), RandomPlayer(seed=2)]
    actions = _build_deployment_from_players(state, players, ZONES)
    assert len(actions) == 4  # 4 oddziały na Froncie
    by_id = {a.unit_id: a for a in actions}
    for blob in state.blobs:
        zone = ZONES[blob.owner_player]
        assert zone.contains_circle(by_id[blob.id].position, blob.radius_inches)


def test_build_deployment_out_of_zone_rejected():
    state = _state()
    players = [_OutOfZonePlayer(), _OutOfZonePlayer()]
    with pytest.raises(IllegalActionError):
        _build_deployment_from_players(state, players, ZONES)


def test_players_get_different_positions():
    # Default (pozycje z roster) vs aktywny bot (losowo w strefie) — różne pozycje.
    state = _state()
    passive = [_PassivePlayer(), _PassivePlayer()]
    active = [RandomPlayer(seed=10), RandomPlayer(seed=20)]
    passive_actions = {a.unit_id: a.position for a in _build_deployment_from_players(state, passive, ZONES)}
    active_actions = {a.unit_id: a.position for a in _build_deployment_from_players(state, active, ZONES)}
    assert passive_actions != active_actions


# --------------------------------------------------------------------------- #
# Integracja z runnerem
# --------------------------------------------------------------------------- #


def test_simulate_with_deployment_zones_completes():
    result = simulate_from_rosters(
        _rosters(),
        [RandomPlayer(seed=1), RandomPlayer(seed=2)],
        seed=2026,
        objectives=_objectives(),
        deployment_zones=ZONES,
    )
    assert result.final_state.is_game_over
    assert result.winner in (0, 1, None)


def test_simulate_with_zones_deterministic():
    kwargs = dict(seed=5, objectives=_objectives(), deployment_zones=ZONES)
    r1 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(1)], **kwargs)
    r2 = simulate_from_rosters(_rosters(), [RandomPlayer(0), RandomPlayer(1)], **kwargs)
    assert r1.final_state == r2.final_state
    assert r1.winner == r2.winner


def test_simulate_zones_and_deployment_mutually_exclusive():
    from app.services.engine.actions import DeploymentAction

    with pytest.raises(ValueError):
        simulate_from_rosters(
            _rosters(),
            [RandomPlayer(0), RandomPlayer(1)],
            deployment=[DeploymentAction(unit_id=1, position=Position(6, 6))],
            deployment_zones=ZONES,
        )


def test_simulate_without_zones_backward_compat():
    # deployment_zones=None → oddziały na pozycjach z roster (zachowanie bez zmian).
    result = simulate_from_rosters(
        _rosters(),
        [RandomPlayer(seed=1), RandomPlayer(seed=2)],
        seed=2026,
        objectives=_objectives(),
    )
    assert result.final_state.is_game_over
