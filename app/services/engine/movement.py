"""Shared movement legality helpers for the engine and heuristic agents."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.engine.geometry import circle_edge_distance
from app.services.engine.state import BattleState, Lokalizacja, Position, UnitBlob

MIN_MANEUVER_UNIT_GAP = 1.0
MANEUVER_CLEARANCE_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class ManeuverBlocker:
    """The first unit blocking a Maneuver destination."""

    unit_id: int
    gap_inches: float


def maneuver_destination_blocker(
    state: BattleState,
    actor: UnitBlob,
    target_position: Position,
    *,
    min_gap_inches: float = MIN_MANEUVER_UNIT_GAP,
    epsilon: float = MANEUVER_CLEARANCE_EPSILON,
) -> ManeuverBlocker | None:
    """Return the first live Front unit too close to a Maneuver destination.

    Pareto MVP represents a unit as one circle, so pkt 15.b.iii is checked as an
    edge-to-edge gap between the moving unit circle at `target_position` and each
    other live unit circle. `ChargeAction` has its own binding movement rules and
    is intentionally not covered by this helper.
    """
    for other in state.blobs:
        if other.id == actor.id:
            continue
        if other.models_alive <= 0 or other.location != Lokalizacja.FRONT:
            continue
        gap = circle_edge_distance(
            target_position,
            actor.radius_inches,
            other.position,
            other.radius_inches,
        )
        if gap <= min_gap_inches + epsilon:
            return ManeuverBlocker(unit_id=other.id, gap_inches=gap)
    return None


def maneuver_destination_is_clear(
    state: BattleState,
    actor: UnitBlob,
    target_position: Position,
    *,
    min_gap_inches: float = MIN_MANEUVER_UNIT_GAP,
    epsilon: float = MANEUVER_CLEARANCE_EPSILON,
) -> bool:
    """True when a Maneuver destination keeps the required gap from other units."""
    return (
        maneuver_destination_blocker(
            state,
            actor,
            target_position,
            min_gap_inches=min_gap_inches,
            epsilon=epsilon,
        )
        is None
    )
