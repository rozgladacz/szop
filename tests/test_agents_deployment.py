"""D5 — testy rozstawienia jako decyzji bota (`app/services/agents/deployment.py`
+ `Player.choose_deployment` + `simulate_from_rosters(deployment_zones=)`).

Pokrywa: geometria strefy (pkt 24/13.a MVP), proste strategie (grid + losowa),
default ABC (wsteczna kompat), walidacja poza-strefą (`IllegalActionError`),
różne pozycje per gracz, integracja z runnerem + determinizm.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from app.services.agents.base import Player
from app.services.agents.deployment import (
    DeploymentZone,
    grid_deployment_position,
    grid_positions,
    is_deployment_position_legal,
    random_position_in_zone,
)
from app.services.agents.greedy_player import GreedyPlayer
from app.services.agents.match import (
    _build_deployment_from_players,
    simulate_from_rosters,
)
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.agents.random_player import RandomPlayer
from app.services.engine.phases import setup_phase
from app.services.engine.resolver import IllegalActionError
from app.services.engine.movement import ManeuverSpace
from app.services.engine.state import (
    BattleState, Lokalizacja, Objective, Position, TerrainCircle, TerrainLine, UnitBlob,
)
from app.services.engine.terrain_complex import TerrainPolygon

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
# D5.1: static legality, independent of strategy and legacy overlap escape
# --------------------------------------------------------------------------- #


def _placement_unit(**kwargs):
    return replace(UnitBlob(100, 0, Position(5, 5), 1.0, 1, 1), **kwargs)


def _legal(position=Position(5, 5), *, unit=None, occupied=(), terrain=(), zone=DeploymentZone(0, 0, 10, 10)):
    return is_deployment_position_legal(
        unit or _placement_unit(), position, zone, occupied=occupied, terrain=terrain,
    )


@pytest.mark.parametrize("radius", [0.25, 1, 3])
@pytest.mark.parametrize("axis,side", [("x", 0), ("x", 10), ("y", 0), ("y", 10)])
def test_static_placement_whole_circle_must_fit_zone(radius, axis, side):
    coordinate = radius if side == 0 else side - radius
    position = replace(Position(5, 5), **{axis: coordinate})
    unit = _placement_unit(radius_inches=radius)
    assert _legal(position, unit=unit)
    outside = replace(position, **{axis: coordinate + (-0.001 if side == 0 else 0.001)})
    assert _legal(replace(outside, **{axis: 5}), unit=unit)
    assert not _legal(outside, unit=unit)  # center is inside; edge is outside


@pytest.mark.parametrize("item", [
    TerrainCircle(Position(7, 5), 1, ("Niedostepny",)),
    TerrainLine(Position(6, 3), Position(6, 7), ("Niedostepny",)),
    TerrainPolygon((Position(6, 3), Position(8, 3), Position(8, 7), Position(6, 7)), ("Niedostepny",)),
])
def test_static_placement_terrain_boundary_and_footprint(item):
    assert not item.contains_point(Position(5, 5))
    assert not _legal(terrain=(item,))  # tangency to terrain is blocked, as E4
    assert not _legal(Position(5.01, 5), terrain=(item,))
    assert _legal(Position(4.99, 5), terrain=(item,))
    assert _legal(terrain=(replace(item, features=("Trudny", "Blokujacy")),))


def test_static_placement_uses_concave_terrain_not_its_bounding_box():
    polygon = TerrainPolygon((
        Position(2, 2), Position(8, 2), Position(8, 4),
        Position(4, 4), Position(4, 8), Position(2, 8),
    ), ("Niedostepny",))
    assert _legal(Position(5.5, 5.5), terrain=(polygon,))  # open notch
    assert not _legal(Position(3, 3), terrain=(polygon,))  # center inside
    assert not _legal(Position(4.5, 5.5), terrain=(polygon,))  # only edge inside


@pytest.mark.parametrize("owner", [0, 1])
@pytest.mark.parametrize("other_radius", [0.25, 1, 3])
def test_static_placement_units_allow_contact_but_not_penetration(owner, other_radius):
    other = _placement_unit(id=101, owner_player=owner, radius_inches=other_radius,
                            position=Position(6 + other_radius, 5))
    assert _legal(occupied=(other,))
    assert _legal(Position(4.999, 5), occupied=(other,))
    assert not _legal(Position(5.001, 5), occupied=(other,))


@pytest.mark.parametrize("other", [
    _placement_unit(),  # actor's old placeholder
    _placement_unit(id=101, location=Lokalizacja.ZAPLECZE),
    _placement_unit(id=101, models_alive=0),
    _placement_unit(id=101, models_alive=0, location=Lokalizacja.ELIMINOWANY),
    _placement_unit(id=101, models_alive=0, location=Lokalizacja.WYCOFANY),
])
def test_static_placement_ignores_self_dead_and_off_board(other):
    assert _legal(occupied=(other,))


def test_static_placement_occupancy_is_explicit_and_order_independent():
    waiting = _placement_unit(id=101)
    placed = replace(waiting, position=Position(8, 5))
    assert _legal(occupied=())  # waiting placeholder at (5,5) is not occupied
    assert not _legal(occupied=(waiting,))  # explicit occupation blocks
    assert _legal(occupied=(placed,))
    assert not _legal(occupied=iter((placed, waiting)))
    assert not _legal(occupied=iter((waiting, placed)))


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), -float("inf"), 10**500, True, "5"])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_static_placement_rejects_nonfinite_or_non_numeric_positions(coordinate, axis):
    assert not _legal(replace(Position(5, 5), **{axis: coordinate}))


@pytest.mark.parametrize("radius", [0, -1, float("nan"), float("inf"), 10**500, True])
def test_static_placement_rejects_invalid_radius(radius):
    assert not _legal(unit=_placement_unit(radius_inches=radius))


@pytest.mark.parametrize("zone", [
    None, DeploymentZone(10, 0, 0, 10), DeploymentZone(0, 10, 10, 0),
    DeploymentZone(float("nan"), 0, 10, 10), DeploymentZone(0, 0, float("inf"), 10),
    DeploymentZone(0, 0, 10**500, 10), DeploymentZone(0, 0, 1, 1),
])
def test_static_placement_requires_valid_explicit_zone(zone):
    assert not _legal(zone=zone)


@pytest.mark.parametrize("unit", [
    _placement_unit(models_alive=0),
    _placement_unit(location=Lokalizacja.ZAPLECZE),
    _placement_unit(location=Lokalizacja.ELIMINOWANY),
])
def test_static_placement_requires_live_front_actor(unit):
    assert not _legal(unit=unit)


def test_static_placement_invalid_occupied_geometry_fails_without_mutation():
    unit = _placement_unit()
    other = _placement_unit(id=101, position=Position(float("inf"), 5))
    occupied = [other]
    terrain = [TerrainCircle(Position(9, 9), 0.1, ("Niedostepny",))]
    assert not _legal(unit=unit, occupied=occupied, terrain=terrain)
    assert occupied == [other] and terrain[0].center == Position(9, 9)
    assert unit == _placement_unit()
    assert _legal(occupied=(replace(other, location=Lokalizacja.ZAPLECZE),))
    assert not _legal(occupied=(replace(other, position=Position(8, 5), radius_inches=-1),))


def test_static_placement_does_not_inherit_maneuver_overlap_escape():
    unit = _placement_unit()
    other = _placement_unit(id=101, position=Position(6, 5))
    state = BattleState(1, 0, (1, 1), (unit, other), (), ())
    space = ManeuverSpace(state, unit, 6)
    assert space.segment(unit.position, Position(4.5, 5)) is not None  # route can leave
    assert not space.can_stop(Position(4.5, 5))
    assert not _legal(Position(4.5, 5), occupied=(other,))
    assert space.can_stop(Position(4, 5))
    assert _legal(Position(4, 5), occupied=(other,))


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


# --------------------------------------------------------------------------- #
# grid_deployment_position + boty deterministyczne (D5)
# --------------------------------------------------------------------------- #


def test_grid_deployment_distinct_legal_slots():
    state = _state()
    # Oddziały gracza 0: id 1 i 2.
    p1 = grid_deployment_position(state, 1, ZONE_P0)
    p2 = grid_deployment_position(state, 2, ZONE_P0)
    assert p1 != p2  # różne sloty gridu
    for uid, pos in ((1, p1), (2, p2)):
        blob = next(b for b in state.blobs if b.id == uid)
        assert ZONE_P0.contains_circle(pos, blob.radius_inches)


def test_grid_deployment_deterministic():
    state = _state()
    assert grid_deployment_position(state, 1, ZONE_P0) == grid_deployment_position(
        state, 1, ZONE_P0
    )


@pytest.mark.parametrize(
    "factory", [GreedyPlayer, PriorityPlayer, PriorityV2Player, PriorityV3Player]
)
def test_deterministic_bots_deploy_on_grid(factory):
    state = _state()
    bot = factory()
    pos1 = bot.choose_deployment(state, 1, ZONE_P0)
    pos2 = bot.choose_deployment(state, 2, ZONE_P0)
    # Grid: różne sloty, oba legalne, zgodne z helperem.
    assert pos1 == grid_deployment_position(state, 1, ZONE_P0)
    assert pos2 == grid_deployment_position(state, 2, ZONE_P0)
    assert pos1 != pos2


def test_simulate_deterministic_bots_with_zones_completes():
    result = simulate_from_rosters(
        _rosters(),
        [GreedyPlayer(), PriorityPlayer()],
        seed=3,
        objectives=_objectives(),
        deployment_zones=ZONES,
    )
    assert result.final_state.is_game_over
    assert result.winner in (0, 1, None)
