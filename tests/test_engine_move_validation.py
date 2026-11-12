"""Maneuver budgets and route validation through the resolver (ADR-0057)."""

from __future__ import annotations

import pytest

from app.services.engine.actions import ManeuverAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoveExecuted
from app.services.engine.resolver import IllegalActionError, ResolverResult, apply
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Position,
    TerrainCircle,
    UnitBlob,
    effective_move_inches,
)


def _blob(**kw) -> UnitBlob:
    defaults = dict(
        id=1,
        owner_player=0,
        position=Position(0.0, 0.0),
        radius_inches=1.0,
        models_alive=5,
        toughness_per_model=3,
    )
    defaults.update(kw)
    return UnitBlob(**defaults)


def _state(blob: UnitBlob, terrain: tuple = ()) -> BattleState:
    return BattleState(
        round=1,
        active_player=blob.owner_player,
        activations_remaining=(1, 1),
        blobs=(blob,),
        terrain=terrain,
    )


def _maneuver(target: Position, blob: UnitBlob | None = None):
    blob = blob if blob is not None else _blob()
    return apply(_state(blob), ManeuverAction(unit_id=blob.id, target_position=target),
                 DeterministicDice(42))


# ---------------------------------------------------------------------------
# effective_move_inches — jednostkowo
# ---------------------------------------------------------------------------


def test_effective_move_base_is_six():
    assert effective_move_inches(_blob()) == 6.0


def test_effective_move_szybki_adds_two():
    assert effective_move_inches(_blob(passives=("szybki",))) == 8.0


def test_effective_move_wolny_subtracts_two():
    assert effective_move_inches(_blob(passives=("wolny",))) == 4.0


def test_effective_move_szybki_and_wolny_cancel():
    assert effective_move_inches(_blob(passives=("szybki", "wolny"))) == 6.0


def test_effective_move_honors_ability_override_grant():
    # Rozkaz/Klątwa nadające Szybki do końca aktywacji (pkt 11.b.i/12).
    blob = _blob(ability_overrides=(("szybki", True),))
    assert effective_move_inches(blob) == 8.0


# ---------------------------------------------------------------------------
# Walidacja przez resolver.apply
# ---------------------------------------------------------------------------


def test_legal_move_within_budget_accepted():
    result = _maneuver(Position(5.0, 0.0))
    assert isinstance(result, ResolverResult)
    assert any(isinstance(e, MoveExecuted) for e in result.events)


def test_exact_boundary_six_inches_accepted():
    result = _maneuver(Position(6.0, 0.0))
    assert any(isinstance(e, MoveExecuted) for e in result.events)


def test_move_over_budget_raises():
    with pytest.raises(IllegalActionError, match="exceeds move budget"):
        _maneuver(Position(7.0, 0.0))


def test_diagonal_distance_uses_euclidean():
    # (3,4) = 5″ ≤ 6 legalny; (5,4) = ~6.40″ > 6 nielegalny.
    assert any(isinstance(e, MoveExecuted) for e in _maneuver(Position(3.0, 4.0)).events)
    with pytest.raises(IllegalActionError):
        _maneuver(Position(5.0, 4.0))


def test_szybki_extends_budget_to_eight():
    blob = _blob(passives=("szybki",))
    assert any(isinstance(e, MoveExecuted) for e in _maneuver(Position(7.5, 0.0), blob).events)


def test_szybki_still_rejects_beyond_eight():
    blob = _blob(passives=("szybki",))
    with pytest.raises(IllegalActionError):
        _maneuver(Position(8.5, 0.0), blob)


def test_wolny_shrinks_budget_to_four():
    blob = _blob(passives=("wolny",))
    # 5″ > 4″ budżet → nielegalny (przy bazowym 6″ byłby legalny).
    with pytest.raises(IllegalActionError):
        _maneuver(Position(5.0, 0.0), blob)
    # 3.5″ ≤ 4″ → legalny.
    assert any(isinstance(e, MoveExecuted) for e in _maneuver(Position(3.5, 0.0), blob).events)


def test_override_grant_szybki_allows_seven():
    blob = _blob(ability_overrides=(("szybki", True),))
    assert any(isinstance(e, MoveExecuted) for e in _maneuver(Position(7.0, 0.0), blob).events)


def test_trudny_terrain_on_path_halves_budget_even_with_clear_endpoint():
    # Start and finish are outside the terrain. Crossing it still halves the
    # budget for the entire move (pkt 4.c.iv), with no slack for a detour here.
    trudny = TerrainCircle(center=Position(3.0, 0.0), radius_inches=0.5, features=("Trudny",))
    blob = _blob()
    with pytest.raises(IllegalActionError, match="no legal maneuver route"):
        apply(
            _state(blob, terrain=(trudny,)),
            ManeuverAction(unit_id=blob.id, target_position=Position(6.0, 0.0)),
            DeterministicDice(42),
        )


def test_maneuver_ending_in_another_unit_raises():
    actor = _blob()
    blocker = _blob(id=2, owner_player=1, position=Position(6.0, 0.0))
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(actor, blocker),
        terrain=(),
    )
    with pytest.raises(IllegalActionError, match="no legal maneuver route"):
        apply(
            state,
            ManeuverAction(unit_id=1, target_position=Position(4.1, 0.0)),
            DeterministicDice(42),
        )


@pytest.mark.parametrize("x", [3.0, 3.5, 4.0])
def test_maneuver_can_finish_close_to_or_touching_another_unit(x):
    actor = _blob()
    blocker = _blob(id=2, owner_player=1, position=Position(6.0, 0.0))
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(actor, blocker),
        terrain=(),
    )
    result = apply(
        state,
        ManeuverAction(unit_id=1, target_position=Position(x, 0.0)),
        DeterministicDice(42),
    )
    assert any(isinstance(e, MoveExecuted) for e in result.events)


def test_maneuver_ignores_defeated_and_non_front_units_for_clearance():
    actor = _blob()
    defeated = _blob(id=2, owner_player=1, position=Position(3.5, 0.0), models_alive=0)
    reserve = _blob(
        id=3,
        owner_player=1,
        position=Position(3.5, 0.0),
        location=Lokalizacja.ZAPLECZE,
    )
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(actor, defeated, reserve),
        terrain=(),
    )
    result = apply(
        state,
        ManeuverAction(unit_id=1, target_position=Position(3.0, 0.0)),
        DeterministicDice(42),
    )
    assert any(isinstance(e, MoveExecuted) for e in result.events)
