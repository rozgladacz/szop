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


# D5.2: bounded strategies and sequential explicit occupancy


def _crowded_deployment_state():
    units = tuple(
        _placement_unit(id=i + 1, owner_player=i % 2,
                        radius_inches=(0.35, 0.5, 0.65)[i % 3],
                        position=Position(1, 1))
        for i in range(6)
    )
    # Concave polygon blocks the preferred lower-left grid slot, with a free notch.
    terrain = (TerrainPolygon((
        Position(0, 0), Position(3, 0), Position(3, 0.8),
        Position(0.8, 0.8), Position(0.8, 2), Position(0, 2),
    ), ("Niedostepny",)),)
    return BattleState(0, 0, (3, 3), units, terrain, ())


def _assert_legal_deployment(state, actions, zones):
    occupied = []
    units = {b.id: b for b in state.blobs}
    for action in actions:
        unit = units[action.unit_id]
        assert is_deployment_position_legal(
            unit, action.position, zones[unit.owner_player],
            occupied=occupied, terrain=state.terrain,
        )
        occupied.append(replace(unit, position=action.position))
    return occupied


@pytest.mark.parametrize("factory", [GreedyPlayer, PriorityPlayer, PriorityV2Player, PriorityV3Player, RandomPlayer])
def test_bots_deploy_legal_mixed_radii_with_polygon_and_shared_narrow_zone(factory):
    state = _crowded_deployment_state()
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    actions = _build_deployment_from_players(state, [factory(), factory()], zones)
    _assert_legal_deployment(state, actions, zones)
    assert len(actions) == 6
    assert actions == _build_deployment_from_players(state, [factory(), factory()], zones)
    assert all(b.position == Position(1, 1) for b in state.blobs)


def test_runner_callbacks_see_previously_chosen_positions_and_preserve_input():
    from app.services.agents.deployment import _deployment_occupied

    seen = []

    class ObservingPlayer(_PassivePlayer):
        def choose_deployment(self, state, unit_id, zone):
            occupied = _deployment_occupied(state)
            seen.append((state, tuple(occupied)))
            assert len(occupied) == len(seen) - 1
            for other in occupied:
                assert next(b for b in state.blobs if b.id == other.id) == other
            return Position(2 + (unit_id - 1) * 3, 3)

    state = replace(_crowded_deployment_state(), terrain=())
    zones = (DeploymentZone(0, 0, 22, 6),) * 2
    actions = _build_deployment_from_players(state, [ObservingPlayer(), ObservingPlayer()], zones)
    _assert_legal_deployment(state, actions, zones)
    assert [action.unit_id for action in actions] == [b.id for b in state.blobs]
    assert all(b.position == Position(1, 1) for b in state.blobs)
    assert _deployment_occupied(seen[-1][0]) == ()  # context reset after callback


@pytest.mark.parametrize("bad_position", [Position(2, 2), Position(float("nan"), 2), Position(-1, 2)])
def test_runner_rejects_later_bad_choice_without_partial_input_mutation(bad_position):
    from app.services.agents.deployment import _deployment_occupied

    seen = []

    class BadSecondPlayer(_PassivePlayer):
        def choose_deployment(self, state, unit_id, zone):
            seen.append(state)
            return Position(2, 2) if len(seen) == 1 else bad_position

    state = replace(_crowded_deployment_state(), terrain=())
    before = state
    zones = (DeploymentZone(0, 0, 20, 6),) * 2
    player = BadSecondPlayer()
    with pytest.raises(IllegalActionError):
        _build_deployment_from_players(state, [player, player], zones)
    assert len(seen) == 2
    assert state == before and all(b.position == Position(1, 1) for b in state.blobs)
    assert _deployment_occupied(seen[-1]) == ()


def test_runner_rejects_custom_choice_inside_terrain_before_deployment(monkeypatch):
    import app.services.agents.match as match

    class TerrainPlayer(_PassivePlayer):
        def choose_deployment(self, state, unit_id, zone):
            return Position(6, 6)

    def forbidden_commit(*args, **kwargs):
        pytest.fail("invalid choices must not reach deployment_round")

    monkeypatch.setattr(match, "deployment_round", forbidden_commit)
    with pytest.raises(IllegalActionError):
        simulate_from_rosters(
            _rosters(), [TerrainPlayer(), TerrainPlayer()], deployment_zones=ZONES,
            terrain=(TerrainCircle(Position(6, 6), 1, ("Niedostepny",)),),
        )


def test_waiting_placeholders_reserves_and_dead_do_not_block_grid():
    state = _crowded_deployment_state()
    state = replace(state, terrain=(), blobs=tuple(
        replace(b, position=Position(6, 1), location=Lokalizacja.ZAPLECZE) if b.id == 2 else
        replace(b, position=Position(6, 1), models_alive=0) if b.id == 3 else b
        for b in state.blobs
    ))
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    actions = _build_deployment_from_players(state, [PriorityPlayer(), PriorityPlayer()], zones)
    assert [a.unit_id for a in actions] == [1, 4, 5, 6]
    _assert_legal_deployment(state, actions, zones)


def test_random_bounded_attempts_then_deterministic_fallback():
    from app.services.agents.deployment import DEPLOYMENT_RANDOM_ATTEMPTS, random_deployment_position

    class BlockedRng:
        def __init__(self):
            self.calls = 0

        def uniform(self, lo, hi):
            self.calls += 1
            return 5.0  # every random sample is inside the obstacle

    unit = _placement_unit()
    state = BattleState(0, 0, (1, 0), (unit,),
                        (TerrainCircle(Position(5, 5), 1, ("Niedostepny",)),), ())
    rng = BlockedRng()
    position = random_deployment_position(rng, state, unit.id, DeploymentZone(0, 0, 10, 10))
    assert rng.calls == 2 * DEPLOYMENT_RANDOM_ATTEMPTS
    assert is_deployment_position_legal(unit, position, DeploymentZone(0, 0, 10, 10),
                                        occupied=(), terrain=state.terrain)


@pytest.mark.parametrize("factory", [PriorityPlayer, RandomPlayer])
def test_bounded_search_reports_only_sampled_exhaustion(factory, monkeypatch):
    import app.services.agents.deployment as deployment

    unit = _placement_unit()
    state = BattleState(0, 0, (1, 0), (unit,),
                        (TerrainCircle(Position(5, 5), 100, ("Niedostepny",)),), ())
    calls = []
    validate = deployment.is_deployment_position_legal

    def count(*args, **kwargs):
        calls.append(1)
        return validate(*args, **kwargs)

    monkeypatch.setattr(deployment, "is_deployment_position_legal", count)
    with pytest.raises(IllegalActionError, match="ograniczonym przeszukanym zbiorze"):
        factory().choose_deployment(state, unit.id, DeploymentZone(0, 0, 10, 10))
    expected = deployment.DEPLOYMENT_GRID_AXIS_POINTS ** 2 + (
        deployment.DEPLOYMENT_RANDOM_ATTEMPTS if factory is RandomPlayer else 1
    )
    assert len(calls) == expected


def test_private_occupancy_context_resets_after_callback_exception_and_nested_scope():
    from app.services.agents.deployment import _deployment_occupied, _deployment_selection

    state = _crowded_deployment_state()
    foreign_state = replace(state)
    with _deployment_selection(state, state.blobs[:1]):
        assert _deployment_occupied(state) == state.blobs[:1]
        assert _deployment_occupied(foreign_state) == ()
        with pytest.raises(RuntimeError):
            with _deployment_selection(state, state.blobs[:2]):
                assert _deployment_occupied(state) == state.blobs[:2]
                raise RuntimeError("callback failed")
        assert _deployment_occupied(state) == state.blobs[:1]
    assert _deployment_occupied(state) == ()


def test_auto_deployment_matches_explicit_actions_and_complete_match_replay():
    from app.services.engine.phases import deployment_round
    from app.services.engine.state import apply_events

    state = _state()
    explicit_players = [RandomPlayer(7), RandomPlayer(19)]
    actions = _build_deployment_from_players(state, explicit_players, ZONES)
    explicit = simulate_from_rosters(
        _rosters(), explicit_players, seed=18, objectives=_objectives(), deployment=actions,
    )
    automatic = simulate_from_rosters(
        _rosters(), [RandomPlayer(7), RandomPlayer(19)], seed=18,
        objectives=_objectives(), deployment_zones=ZONES,
    )
    # The same players' deployment draws leave identical future decision RNG;
    # engine seed/outcomes and the old explicit-deployment path are unchanged.
    assert automatic == explicit
    deployed, _ = deployment_round(state, actions)
    assert apply_events(deployed, automatic.events) == automatic.final_state


@pytest.mark.parametrize("kind", ["minimax", "claude_v1", "claude_v2", "claude_v3"])
def test_other_factory_grid_bots_use_shared_placement_validator(kind):
    from app.services.agents.factory import make_player

    state = _crowded_deployment_state()
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    players = [make_player(kind, 2), make_player(kind, 8)]
    actions = _build_deployment_from_players(state, players, zones)
    assert len(actions) == 6
    _assert_legal_deployment(state, actions, zones)


# D5.3a: explicit per-side strategies and objective assignment heuristic.


def _objective_choices(state, zones, monkeypatch, strategies=("objectives", "objectives")):
    import app.services.agents.match as match

    selected = []
    choose = match.objective_deployment_choice

    def record(working, unit_id, zone, *, assignments):
        position, target = choose(working, unit_id, zone, assignments=assignments)
        unit = next(b for b in working.blobs if b.id == unit_id)
        selected.append((unit.owner_player, target, dict(assignments)))
        return position, target

    monkeypatch.setattr(match, "objective_deployment_choice", record)
    actions = match._build_deployment_from_players(
        state, [_PassivePlayer(), _PassivePlayer()], zones,
        deployment_strategies=strategies,
    )
    return actions, selected


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_objectives_assign_distinct_then_least_populated_targets(count, monkeypatch):
    units = tuple(_placement_unit(id=i + 1, position=Position(1, 1), radius_inches=0.3)
                  for i in range(count))
    targets = (Objective(11, Position(6, 6)), Objective(22, Position(40, 6)))
    state = BattleState(0, 0, (count, 0), units, (), targets)
    actions, selected = _objective_choices(state, (DeploymentZone(0, 0, 12, 12),) * 2, monkeypatch)
    assert [target for _, target, _ in selected] == [11, 22, 11, 22, 11][:count]
    _assert_legal_deployment(state, actions, (DeploymentZone(0, 0, 12, 12),) * 2)
    assert all(b.position == Position(1, 1) for b in state.blobs)


def test_objective_counts_are_per_side_and_reset_between_games(monkeypatch):
    state = replace(_crowded_deployment_state(), terrain=(), objectives=(
        Objective(1, Position(6, 1)), Objective(2, Position(30, 1)),
    ))
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    first, selected = _objective_choices(state, zones, monkeypatch)
    assert [target for _, target, _ in selected] == [1, 1, 2, 2, 1, 1]
    assert selected[0][2] == selected[1][2] == {}
    _assert_legal_deployment(state, first, zones)
    second = _build_deployment_from_players(
        state, [_PassivePlayer(), _PassivePlayer()], zones,
        deployment_strategies=("objectives", "objectives"),
    )
    assert second == first


def test_objective_candidates_reuse_legal_pool_and_deterministic_ties():
    from app.services.agents.deployment import objective_deployment_choice

    unit = _placement_unit()
    # Equal geometry, shuffled IDs: tie goes to ID, then x/y, not input order.
    targets = (Objective(22, Position(5, 5)), Objective(11, Position(5, 5)))
    state = BattleState(0, 0, (1, 0), (unit,), (), targets)
    zone = DeploymentZone(0, 0, 10, 10)
    position, target = objective_deployment_choice(state, unit.id, zone, assignments={})
    assert target == 11
    assert (position, target) == objective_deployment_choice(
        replace(state, objectives=tuple(reversed(targets))), unit.id, zone, assignments={},
    )
    assert is_deployment_position_legal(unit, position, zone, occupied=(), terrain=())


def test_objectives_handle_polygon_and_narrow_zone_with_mixed_radii():
    state = replace(_crowded_deployment_state(), objectives=(
        Objective(1, Position(2, 1)), Objective(2, Position(11, 1)),
    ))
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    actions = _build_deployment_from_players(
        state, [RandomPlayer(1), RandomPlayer(2)], zones,
        deployment_strategies=("objectives", "objectives"),
    )
    _assert_legal_deployment(state, actions, zones)
    assert len(actions) == 6


def test_objectives_without_targets_use_grid_and_ignore_waiting_offboard_dead():
    state = replace(_crowded_deployment_state(), terrain=(), blobs=tuple(
        replace(b, location=Lokalizacja.ZAPLECZE) if b.id == 2 else
        replace(b, models_alive=0) if b.id == 3 else b
        for b in _crowded_deployment_state().blobs
    ))
    zones = (DeploymentZone(0, 0, 12, 2),) * 2
    players = [PriorityPlayer(), PriorityPlayer()]
    default = _build_deployment_from_players(state, players, zones)
    assert default == _build_deployment_from_players(
        state, players, zones, deployment_strategies=("objectives", "objectives"),
    )
    assert [a.unit_id for a in default] == [1, 4, 5, 6]


def test_objective_exhaustion_is_bounded_and_does_not_mutate_input(monkeypatch):
    import app.services.agents.deployment as deployment

    state = replace(_crowded_deployment_state(), objectives=(Objective(1, Position(5, 5)),),
                    terrain=(TerrainCircle(Position(5, 5), 100, ("Niedostepny",)),))
    checked = []
    validate = deployment.is_deployment_position_legal

    def count(*args, **kwargs):
        checked.append(1)
        return validate(*args, **kwargs)

    monkeypatch.setattr(deployment, "is_deployment_position_legal", count)
    with pytest.raises(IllegalActionError, match="ograniczonym przeszukanym zbiorze"):
        _build_deployment_from_players(
            state, [_PassivePlayer(), _PassivePlayer()], (DeploymentZone(0, 0, 10, 10),) * 2,
            deployment_strategies=("objectives", "grid"),
        )
    assert len(checked) == 1 + deployment.DEPLOYMENT_GRID_AXIS_POINTS ** 2
    assert all(b.position == Position(1, 1) for b in state.blobs)


@pytest.mark.parametrize("strategies", ["objectives", (), ("grid",), ("grid",) * 3,
                                         ("invalid", None), (None, 1), ([], None), True])
def test_invalid_strategy_selection_fails_before_player_callback(strategies):
    with pytest.raises(ValueError, match="deployment_strategies"):
        _build_deployment_from_players(_state(), [], ZONES, deployment_strategies=strategies)


def test_strategy_requires_zones_and_cannot_override_explicit_deployment():
    from app.services.engine.actions import DeploymentAction

    with pytest.raises(ValueError, match="requires deployment_zones"):
        simulate_from_rosters(_rosters(), [], deployment_strategies=("grid", "grid"))
    with pytest.raises(ValueError, match="nie oba naraz"):
        simulate_from_rosters(_rosters(), [], deployment_zones=ZONES,
                              deployment_strategies=("objectives", "grid"),
                              deployment=[DeploymentAction(1, Position(6, 6))])


def test_explicit_strategies_override_only_selected_callback_and_preserve_rng():
    state = _state()
    left, right = RandomPlayer(7), RandomPlayer(19)
    right_before = right._rng.getstate()
    actions = _build_deployment_from_players(
        state, [left, right], ZONES, deployment_strategies=(None, "grid"),
    )
    reference = _build_deployment_from_players(state, [RandomPlayer(7), PriorityPlayer()], ZONES)
    assert actions == reference
    assert right._rng.getstate() == right_before


def test_objective_opt_in_matches_explicit_and_complete_replay():
    from app.services.engine.phases import deployment_round
    from app.services.engine.state import apply_events

    state = _state()
    strategies = ("objectives", "grid")
    actions = _build_deployment_from_players(
        state, [RandomPlayer(7), RandomPlayer(19)], ZONES, deployment_strategies=strategies,
    )
    explicit = simulate_from_rosters(
        _rosters(), [RandomPlayer(7), RandomPlayer(19)], seed=18,
        objectives=_objectives(), deployment=actions,
    )
    automatic = simulate_from_rosters(
        _rosters(), [RandomPlayer(7), RandomPlayer(19)], seed=18,
        objectives=_objectives(), deployment_zones=ZONES, deployment_strategies=strategies,
    )
    assert automatic == explicit
    assert automatic == simulate_from_rosters(
        _rosters(), [RandomPlayer(7), RandomPlayer(19)], seed=18,
        objectives=_objectives(), deployment_zones=ZONES, deployment_strategies=strategies,
    )
    deployed, _ = deployment_round(state, actions)
    assert apply_events(deployed, automatic.events) == automatic.final_state


def test_objective_later_exhaustion_never_commits_partial_deployment(monkeypatch):
    import app.services.agents.match as match

    rosters = _rosters()
    rosters[0]["units"][1]["models"] = 100  # circle cannot fit in this zone
    before = repr(rosters)

    def no_commit(*args, **kwargs):
        pytest.fail("partial objective deployment reached deployment_round")

    monkeypatch.setattr(match, "deployment_round", no_commit)
    with pytest.raises(IllegalActionError, match="ograniczonym przeszukanym zbiorze"):
        simulate_from_rosters(
            rosters, [_PassivePlayer(), _PassivePlayer()], objectives=_objectives(),
            deployment_zones=(DeploymentZone(0, 0, 7, 7),) * 2,
            deployment_strategies=("objectives", "objectives"),
        )
    assert repr(rosters) == before
