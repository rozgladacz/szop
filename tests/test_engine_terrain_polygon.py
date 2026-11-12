"""Terrain polygons through LoS, checkpoints and local battle creation."""

from dataclasses import replace
import json

import pytest

from app.services.engine.actions import ManeuverAction
from app.services.engine.combat import compute_cover
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import EffectApplied
from app.services.engine.los import LoSState, check_los
from app.services.engine.phases import activation_phase
from app.services.engine.state import (
    BattleState,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    apply_events,
)
from app.services.engine.state_codec import (
    BattleStateCodecError,
    battle_state_from_json,
    battle_state_to_json,
)
from app.services.engine.terrain_complex import MAX_POLYGON_VERTICES, TerrainPolygon
from scripts.balance_simulate import load_battle_fixture
from szop_client import LocalClient


def _positions(*coords: tuple[float, float]) -> tuple[Position, ...]:
    return tuple(Position(x, y) for x, y in coords)


_L_SHAPE = _positions((0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4))


def _unit(unit_id: int, x: float, y: float, radius: float = 1) -> UnitBlob:
    return UnitBlob(
        id=unit_id, owner_player=unit_id - 1, position=Position(x, y),
        radius_inches=radius, models_alive=6, toughness_per_model=1,
    )


@pytest.mark.parametrize("vertices", [_L_SHAPE, _L_SHAPE[::-1]])
def test_concavity_edges_and_winding(vertices):
    polygon = TerrainPolygon(vertices)

    assert polygon.contains_point(Position(0.5, 3))
    assert polygon.contains_point(Position(1, 1))
    assert polygon.contains_point(Position(3, 1))
    assert not polygon.contains_point(Position(2, 2))  # notch, inside the bounds
    assert polygon.intersects_segment(Position(-1, 3), Position(2, 3))
    assert polygon.intersects_segment(Position(4, -1), Position(4, 0))  # vertex
    assert polygon.intersects_segment(Position(1, 1), Position(4, 1))  # edge
    assert polygon.intersects_segment(Position(0.5, 0.5), Position(0.5, 3))
    assert not polygon.intersects_segment(Position(2, 2), Position(4, 2))
    assert not polygon.intersects_segment(Position(5, 0), Position(5, 4))


@pytest.mark.parametrize(
    "vertices",
    [
        _L_SHAPE[:2],
        _L_SHAPE * MAX_POLYGON_VERTICES,
        _L_SHAPE + _L_SHAPE[:1],
        _positions((0, 0), (2, 1), (4, 2)),  # collinear
        _positions((0, 0), (4, 2), (0, 2), (3, 0)),  # self-crossing
        _positions((0, 0), (4, 0), (2, 0), (4, 4), (0, 4)),  # backtracking edge
        _positions((0, 0), (4, 0), (0, float("inf"))),
        _positions((0, 0), (4, 0), (False, 4)),
    ],
)
def test_rejects_invalid_polygons(vertices):
    with pytest.raises(ValueError, match="terrain polygon"):
        TerrainPolygon(vertices)


def test_polygon_los_keeps_three_outcomes_and_inside_exception():
    attacker, target = _unit(1, 0, 0), _unit(2, 10, 0, radius=2)
    wide = TerrainPolygon(
        _positions((4, -3), (6, -3), (6, 3), (4, 3)), ("Blokujacy",)
    )
    narrow = TerrainPolygon(
        _positions((4, -0.1), (6, -0.1), (6, 0.1), (4, 0.1)), ("Blokujacy",)
    )
    assert check_los(attacker, target, [wide]) is LoSState.NIE_WIDZI
    assert check_los(attacker, target, [narrow]) is LoSState.OSLONA

    concealing = replace(wide, features=("Zaslaniajacy",))
    assert check_los(attacker, target, [concealing]) is LoSState.NIE_WIDZI
    inside = _unit(2, 5, 0)
    assert check_los(attacker, inside, [concealing]) is LoSState.WIDZI
    assert check_los(inside, attacker, [concealing]) is LoSState.WIDZI
    assert check_los(attacker, inside, [wide]) is LoSState.NIE_WIDZI


def test_polygon_applies_defensive_cover_only_at_centers_inside():
    terrain = TerrainPolygon(_L_SHAPE, ("Obronny",))
    attacker = _unit(1, -3, -3)
    assert compute_cover(attacker, _unit(2, 0.5, 2), [terrain])
    assert not compute_cover(attacker, _unit(2, 2, 2), [terrain])


def test_polygon_keeps_maneuver_end_position_effect_and_replay():
    state = BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=(_unit(1, -1, 0), _unit(2, 10, 0)),
        terrain=(TerrainPolygon(_L_SHAPE, ("Niebezpieczny",)),),
    )
    action = ManeuverAction(unit_id=1, target_position=Position(0.5, 2))
    result, events = activation_phase(state, action, DeterministicDice(1))
    effect = next(e for e in events if isinstance(e, EffectApplied) and e.slug == "niebezpieczny")
    assert effect.payload["wounds_inflicted"] == 2
    assert apply_events(state, events) == result


@pytest.mark.parametrize("version", [1, 2, 3])
def test_polygon_checkpoint_round_trip_and_invalid_geometry(version):
    state = BattleState(
        round=1, active_player=0, activations_remaining=(1, 1), blobs=(),
        terrain=(
            TerrainCircle(Position(6, 6), 1, ("Obronny",)),
            TerrainLine(Position(7, 7), Position(8, 8), ("Blokujacy",)),
            TerrainPolygon(_L_SHAPE, ("Zaslaniajacy",)),
        ),
        initiative_player=0 if version > 1 else None,
    )
    payload = json.loads(json.dumps(battle_state_to_json(state, version=version)))
    assert battle_state_from_json(payload) == state

    fields = payload["state"]["fields"]["terrain"]["$tuple"][2]["fields"]
    vertices = fields["vertices"]["$tuple"]
    vertices[-1] = vertices[0]  # Valid wire type, invalid ring.
    with pytest.raises(BattleStateCodecError, match="invalid TerrainPolygon"):
        battle_state_from_json(payload)


def test_polygon_fixture_reaches_local_battle_and_los(tmp_path):
    path = tmp_path / "polygon.yaml"
    path.write_text(
        """rosters:
  - owner_player: 0
    units: [{id: 1, position: [0, 0], models: 1, toughness: 1}]
  - owner_player: 1
    units: [{id: 2, position: [10, 0], models: 1, toughness: 1}]
terrain:
  - shape: polygon
    features: [Blokujacy]
    vertices: [[4, -3], [6, -3], [6, 3], [4, 3]]
""",
        encoding="utf-8",
    )
    fixture = load_battle_fixture(path)
    client = LocalClient()
    state = client.get_state(client.create_battle(fixture.rosters, terrain=fixture.terrain))
    assert isinstance(state.terrain[0], TerrainPolygon)
    assert check_los(*state.blobs, state.terrain) is LoSState.NIE_WIDZI
