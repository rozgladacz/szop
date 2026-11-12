"""E4: continuous segment clearance, reachable endpoints, and resolver parity."""

from dataclasses import replace

import pytest

from app.services.agents.base import legal_actions
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.engine.actions import ManeuverAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoveExecuted
from app.services.engine.pathfinding import ManeuverPlanner, find_reachable_positions
from app.services.engine.resolver import IllegalActionError, apply, apply_activation
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    apply_events,
    effective_move_inches,
)
from app.services.engine.terrain_complex import TerrainPolygon


_WALL = ("Niedostepny",)
_DIFFICULT = ("Trudny",)


def _actor(position=Position(0, 0), radius=0.4, passives=()):
    return UnitBlob(
        id=1, owner_player=0, position=position, radius_inches=radius,
        models_alive=1, toughness_per_model=1, passives=passives,
    )


def _state(actor=None, *, other_units=(), terrain=(), objectives=()):
    return BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=(actor or _actor(), *other_units), terrain=terrain, objectives=objectives,
    )


def _planner(state):
    actor = state.blobs[0]
    return ManeuverPlanner(state, actor, effective_move_inches(actor))


def test_thin_wall_cannot_be_crossed_between_legal_endpoints():
    state = _state(terrain=(TerrainLine(Position(2, -20), Position(2, 20), _WALL),))
    assert not _planner(state).can_reach(Position(4.2, 0))
    reachable = find_reachable_positions(state, state.blobs[0], 6)
    assert Position(1, 0) in reachable
    assert all(point.x < 1.6 for point in reachable)


@pytest.mark.parametrize("terrain", [
    TerrainCircle(Position(2, 0.55), 0.2, _WALL),
    TerrainLine(Position(2, 0.3), Position(2, 1.7), _WALL),
    TerrainPolygon((
        Position(2, 0.2), Position(3, 0.2), Position(3, 0.4),
        Position(2.5, 0.4), Position(2.5, 2), Position(2, 2),
    ), _WALL),
])
def test_swept_footprint_hits_terrain_even_if_center_segment_misses(terrain):
    start, finish = Position(0, 0), Position(6, 0)
    assert not terrain.intersects_segment(start, finish)
    assert not _planner(_state(terrain=(terrain,))).can_reach(finish)


def test_concave_terrain_notch_remains_open():
    polygon = TerrainPolygon((
        Position(1, -1), Position(3, -1), Position(3, 0),
        Position(2, 0), Position(2, 2), Position(1, 2),
    ), _WALL)
    state = _state(_actor(Position(4, 0.6)), terrain=(polygon,))
    assert _planner(state).can_reach(Position(2.6, 0.6))


def test_unit_blocks_swept_route_even_when_endpoint_is_clear():
    blocker = replace(_actor(Position(3, 0), radius=1), id=2, owner_player=1)
    state = _state(other_units=(blocker,))
    assert not _planner(state).can_reach(Position(6, 0))
    assert _planner(state).can_reach(Position(3, 1.4))  # legal tangency


def test_legacy_overlapping_units_can_only_end_at_clear_positions():
    actor = _actor(radius=1)
    blocker = replace(actor, id=2, position=Position(1, 0), owner_player=1)
    planner = _planner(_state(actor, other_units=(blocker,)))
    assert not planner.can_reach(actor.position)
    assert not planner.can_reach(Position(-0.5, 0))
    assert planner.can_reach(Position(-1, 0))
    assert not planner.can_reach(Position(5.99, 0))  # no time to go around


@pytest.mark.parametrize(("passives", "maximum"), [((), 3), (("szybki",), 4), (("wolny",), 2)])
def test_difficult_terrain_halves_the_effective_budget_for_the_whole_route(passives, maximum):
    difficult = TerrainLine(Position(1, -20), Position(1, 20), _DIFFICULT)
    planner = _planner(_state(_actor(passives=passives), terrain=(difficult,)))
    assert planner.can_reach(Position(maximum, 0))
    assert not planner.can_reach(Position(maximum + 0.05, 0))


def test_clean_detour_can_use_full_budget():
    difficult = TerrainLine(Position(1.5, -0.25), Position(1.5, 0.25), _DIFFICULT)
    target = Position(4.8, 0.15)
    assert difficult.intersects_segment(Position(0, 0), target)
    assert _planner(_state(terrain=(difficult,))).can_reach(target)


def test_off_grid_endpoint_around_wall_is_legal_and_replays():
    wall = TerrainLine(Position(2, -0.5), Position(2, 0.5), _WALL)
    state = _state(terrain=(wall,))
    target = Position(4.25, 0.15)
    assert wall.intersects_segment(state.blobs[0].position, target)
    result = apply(state, ManeuverAction(1, target), DeterministicDice(42))
    assert result.state.blobs[0].position == target
    assert apply_events(state, result.events) == result.state


def test_replaying_a_legacy_movement_does_not_revalidate_its_route():
    state = _state(terrain=(TerrainLine(Position(2, -20), Position(2, 20), _WALL),))
    recorded = MoveExecuted(1, 1, (0, 0), (4, 0), "manever")
    assert apply_events(state, (recorded,)).blobs[0].position == Position(4, 0)


def test_reachable_positions_are_unique_deterministic_and_validatable():
    wall = TerrainLine(Position(2, -0.5), Position(2, 0.5), _WALL)
    state = _state(terrain=(wall,))
    actor = state.blobs[0]
    reachable = find_reachable_positions(state, actor, 6)
    assert reachable == find_reachable_positions(state, actor, 6)
    assert len(reachable) == len(set(reachable))
    assert Position(4, 0) in reachable
    planner = _planner(state)
    assert all(planner.can_reach(point) for point in reachable)


@pytest.mark.parametrize("x", [float("nan"), float("inf"), 10**500])
def test_nonfinite_or_unrepresentable_destination_is_rejected(x):
    with pytest.raises(IllegalActionError, match="must be finite"):
        apply(_state(), ManeuverAction(1, Position(x, 0)), DeterministicDice(42))


def test_second_maneuver_is_validated_from_the_updated_position():
    state = _state()
    first = ManeuverAction(1, Position(5, 0))
    for target, expected in ((Position(10, 0), Position(10, 0)), (Position(-2, 0), first.target_position)):
        result = apply_activation(
            state, first, DeterministicDice(42),
            continuation=lambda _state, _uid, _taken: ManeuverAction(1, target),
        )
        assert result.state.blobs[0].position == expected
        assert apply_events(state, result.events) == result.state


def test_second_maneuver_cannot_cross_impassable_terrain():
    state = _state(terrain=(TerrainLine(Position(3, -20), Position(3, 20), _WALL),))
    first = ManeuverAction(1, Position(2, 0))
    result = apply_activation(
        state, first, DeterministicDice(42),
        continuation=lambda _state, _uid, _taken: ManeuverAction(1, Position(4, 0)),
    )
    moves = [event for event in result.events if isinstance(event, MoveExecuted)]
    assert [event.to_pos for event in moves] == [(2, 0)]


@pytest.mark.parametrize("bot", [None, PriorityPlayer, PriorityV2Player, PriorityV3Player])
def test_bots_choose_a_reachable_endpoint_beyond_a_short_wall(bot):
    wall = TerrainLine(Position(2, -0.5), Position(2, 0.5), _WALL)
    target = Position(4.25, 0.15)
    state = _state(terrain=(wall,), objectives=(Objective(1, target),))
    candidates = legal_actions(state, 0) if bot is None else [bot().choose_action(state, 0)]
    moves = [action for action in candidates if isinstance(action, ManeuverAction)]
    assert any(action.target_position == target for action in moves)
    for action in moves:
        apply(state, action, DeterministicDice(42))
