"""Deterministic Maneuver planning on a local hex lattice (ADR-0057)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from functools import cached_property
from heapq import heappop, heappush

from app.services.engine.geometry import distance
from app.services.engine.movement import MOVE_EPSILON, ManeuverSpace
from app.services.engine.state import BattleState, Position, UnitBlob


_HEX_ROW_HEIGHT = math.sqrt(3) / 2
_NEIGHBORS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))


def is_finite_position(point: Position) -> bool:
    try:
        return all(
            type(value) in (int, float) and math.isfinite(value)
            for value in (point.x, point.y)
        )
    except OverflowError:
        return False


class ManeuverPlanner:
    """Per-unit planner shared by resolver and bot candidates on the same state."""

    def __init__(self, state: BattleState, actor: UnitBlob, move_inches: float):
        self._state = state
        self._actor = actor
        self._origin = actor.position
        self._budget = move_inches
        self._half_budget = move_inches / 2

    @cached_property
    def _space(self) -> ManeuverSpace:
        return ManeuverSpace(self._state, self._actor, self._budget)

    @property
    def _valid_origin(self) -> bool:
        return (
            math.isfinite(self._budget)
            and self._budget >= 0
            and is_finite_position(self._origin)
        )

    def _fits(self, length: float, difficult: bool) -> bool:
        return length <= (self._half_budget if difficult else self._budget) + MOVE_EPSILON

    def _connector_fits(
        self, start: Position, target: Position, length: float, difficult: bool = False,
    ) -> bool:
        segment = self._space.segment(start, target)
        return segment is not None and self._fits(length, difficult or segment)

    def can_reach(self, target: Position) -> bool:
        """Whether there is a legal route to this exact, possibly off-grid point."""
        if not self._valid_origin or not is_finite_position(target):
            return False
        direct = distance(self._origin, target)
        if not self._fits(direct, False):
            return False
        if self._connector_fits(self._origin, target, direct):
            return not self._space.starts_overlapping or self._space.can_stop(target)
        if direct >= self._budget or not self._space.can_stop(target):
            return False
        return any(
            self._connector_fits(point, target, length + distance(point, target), difficult)
            for point, length, difficult in self._search(target)
            if length > 0
        )

    def _search(self, target: Position | None = None) -> Iterator[tuple[Position, float, bool]]:
        # A* for an exact destination, Dijkstra for all reachable lattice points.
        # The two labels keep clean routes even when a shorter difficult route
        # reaches the same point (pkt 4.c.iv caps its whole length).
        origin = self._origin
        positions = {(0, 0): origin}
        best = {(0, 0, False): 0.0}
        queue = [(0.0, 0.0, 0, 0, False)]
        while queue:
            _, length, q, r, difficult = heappop(queue)
            if length != best[q, r, difficult]:
                continue
            point = positions[q, r]
            yield point, length, difficult

            for dq, dr in _NEIGHBORS:
                a, b = q + dq, r + dr
                neighbor = positions.get((a, b))
                if neighbor is None:
                    neighbor = positions[a, b] = Position(
                        origin.x + a + b * 0.5, origin.y + b * _HEX_ROW_HEIGHT
                    )
                # The lattice step is 1 inch. At very large coordinate magnitudes,
                # never let float rounding turn a step into a shortcut or free edge.
                next_length = length + max(1.0, distance(point, neighbor))
                estimate = next_length + (distance(neighbor, target) if target is not None else 0)
                if not self._fits(estimate, difficult):
                    continue
                clean_length = best.get((a, b, False), math.inf)
                if clean_length <= next_length:
                    continue  # The clean label dominates both at this length.
                segment = self._space.segment(point, neighbor)
                if segment is None:
                    continue
                next_difficult = difficult or segment
                label = (a, b, next_difficult)
                if self._fits(estimate, next_difficult) and next_length < best.get(label, math.inf):
                    best[label] = next_length
                    heappush(queue, (estimate, next_length, a, b, next_difficult))

    @cached_property
    def reachable_positions(self) -> tuple[Position, ...]:
        """Legal hex lattice endpoints in deterministic search order."""
        if not self._valid_origin:
            return ()
        positions: dict[Position, None] = {}
        for point, length, _ in self._search():
            if not (length == 0 or self._space.starts_overlapping) or self._space.can_stop(point):
                positions[point] = None
        return tuple(positions)

    def advance_toward(self, target: Position) -> Position | None:
        """Choose one legal endpoint close to a bot's strategic target."""
        if not self._valid_origin or not is_finite_position(target):
            return None
        origin = self._origin
        target_distance = distance(origin, target)
        if target_distance == 0 or not math.isfinite(target_distance):
            return None
        direct = target
        if target_distance > self._budget:
            ratio = self._budget / target_distance
            direct = Position(
                origin.x + (target.x - origin.x) * ratio,
                origin.y + (target.y - origin.y) * ratio,
            )
        if direct != origin and self.can_reach(direct):
            return direct

        best = min(
            self.reachable_positions, key=lambda point: distance(point, target), default=origin
        )
        # If the legacy starting point overlaps, every legal exit is a candidate.
        if best != origin and (
            distance(best, target) < target_distance or self._space.starts_overlapping
        ):
            return best
        return None


def find_reachable_positions(state: BattleState, blob: UnitBlob, move_inches: float) -> list[Position]:
    """Legal endpoints on the 1-inch hex lattice centered at the current position."""
    return list(ManeuverPlanner(state, blob, move_inches).reachable_positions)
