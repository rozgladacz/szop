"""Swept circle tests for Maneuver routes (ADR-0057)."""

from __future__ import annotations

from app.services.engine.geometry import distance, point_segment_distance, segment_segment_distance
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Position,
    Terrain,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)


MOVE_EPSILON = 1e-6
_IMPASSABLE = "Niedostepny"
_DIFFICULT = "Trudny"

Bounds = tuple[float, float, float, float]


def _segment_bounds(start: Position, end: Position, radius: float = 0.0) -> Bounds:
    return (
        min(start.x, end.x) - radius, min(start.y, end.y) - radius,
        max(start.x, end.x) + radius, max(start.y, end.y) + radius,
    )


def _bounds_intersect(a: Bounds, b: Bounds) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _terrain_bounds(terrain: Terrain) -> Bounds:
    if isinstance(terrain, TerrainCircle):
        return _segment_bounds(terrain.center, terrain.center, terrain.radius_inches)
    if isinstance(terrain, TerrainLine):
        return _segment_bounds(terrain.start, terrain.end)
    return terrain.bounds


def _sweeps_terrain(start: Position, end: Position, radius: float, terrain: Terrain) -> bool:
    if isinstance(terrain, TerrainCircle):
        return point_segment_distance(terrain.center, start, end) <= radius + terrain.radius_inches
    if isinstance(terrain, TerrainLine):
        return segment_segment_distance(start, end, terrain.start, terrain.end) <= radius
    return terrain.contains_point(start) or any(
        segment_segment_distance(start, end, a, b) <= radius for a, b in terrain.edges
    )


class ManeuverSpace:
    """Obstacles in reach of one unit, prepared once per route search."""

    def __init__(self, state: BattleState, actor: UnitBlob, budget: float):
        origin = actor.position
        self._radius = actor.radius_inches
        self._units: list[tuple[Position, float]] = []
        self.starts_overlapping = False
        for other in state.blobs:
            if (
                other.id == actor.id
                or other.models_alive <= 0
                or other.location is not Lokalizacja.FRONT
            ):
                continue
            clearance = self._radius + other.radius_inches
            start_distance = distance(origin, other.position)
            if start_distance <= budget + clearance + MOVE_EPSILON:
                self._units.append((other.position, clearance))
                self.starts_overlapping |= start_distance < clearance - MOVE_EPSILON

        reachable_bounds = _segment_bounds(origin, origin, budget + self._radius + MOVE_EPSILON)
        self._terrain: list[tuple[Terrain, Bounds, bool]] = []
        for terrain in state.terrain:
            impassable = _IMPASSABLE in terrain.features
            if impassable or _DIFFICULT in terrain.features:
                bounds = _terrain_bounds(terrain)
                if _bounds_intersect(bounds, reachable_bounds):
                    self._terrain.append((terrain, bounds, impassable))

    def segment(self, start: Position, end: Position) -> bool | None:
        """Return True for difficult terrain, False for clear, None for blocked."""
        can_escape = self.starts_overlapping and start != end
        for center, clearance in self._units:
            if can_escape:
                # A legacy overlap can be left by moving away from its center.
                clearance = min(clearance, distance(start, center))
            if point_segment_distance(center, start, end) < clearance - MOVE_EPSILON:
                return None

        difficult = False
        if self._terrain:
            swept_bounds = _segment_bounds(start, end, self._radius)
            for terrain, bounds, impassable in self._terrain:
                if (impassable or not difficult) and _bounds_intersect(bounds, swept_bounds):
                    if _sweeps_terrain(start, end, self._radius, terrain):
                        if impassable:
                            return None
                        difficult = True
        return difficult

    def can_stop(self, position: Position) -> bool:
        return self.segment(position, position) is not None
