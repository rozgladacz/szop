"""Closed terrain polygon and pure geometry for LoS and movement (ADR-0041)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.services.engine.geometry import Position, point_on_segment, segments_intersect


MAX_POLYGON_VERTICES = 256


@dataclass(frozen=True, slots=True)
class TerrainPolygon:
    """Simple perimeter in either winding, without repeating the first vertex."""

    vertices: tuple[Position, ...]
    features: tuple[str, ...] = ()
    edges: tuple[tuple[Position, Position], ...] = field(
        init=False, repr=False, compare=False
    )
    bounds: tuple[float, float, float, float] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        vertices = self.vertices
        if not isinstance(vertices, tuple) or not 3 <= len(vertices) <= MAX_POLYGON_VERTICES:
            raise ValueError(f"terrain polygon needs 3 to {MAX_POLYGON_VERTICES} vertices")
        if not isinstance(self.features, tuple) or any(
            not isinstance(f, str) for f in self.features
        ):
            raise ValueError("terrain polygon features must be a tuple of strings")
        try:
            if any(
                not isinstance(p, Position)
                or not all(type(n) in (int, float) and math.isfinite(n) for n in (p.x, p.y))
                for p in vertices
            ):
                raise ValueError("terrain polygon vertices must be finite positions")
        except OverflowError as exc:
            raise ValueError("terrain polygon vertices must be finite positions") from exc
        if len(set(vertices)) != len(vertices):
            raise ValueError("terrain polygon vertices must be distinct")

        min_x, max_x = min(p.x for p in vertices), max(p.x for p in vertices)
        min_y, max_y = min(p.y for p in vertices), max(p.y for p in vertices)
        span_x, span_y = float(max_x) - float(min_x), float(max_y) - float(min_y)
        if not math.isfinite(2 * span_x * span_y):
            raise ValueError("terrain polygon coordinate span is too large")

        # Translate before computing signed area to avoid cancellation from a
        # large coordinate origin.
        origin = vertices[0]
        offsets = [(p.x - origin.x, p.y - origin.y) for p in vertices[1:]]
        try:
            area_twice = math.fsum(
                ax * by - ay * bx
                for (ax, ay), (bx, by) in zip(offsets, offsets[1:])
            )
        except (OverflowError, ValueError) as exc:
            raise ValueError("terrain polygon area cannot be represented") from exc
        if area_twice == 0:
            raise ValueError("terrain polygon must enclose a nonzero area")

        edges = tuple(zip(vertices, vertices[1:] + vertices[:1]))
        for i, (start, end) in enumerate(edges):
            previous = vertices[i - 1]
            if point_on_segment(end, previous, start) or point_on_segment(previous, start, end):
                raise ValueError("terrain polygon edges must not overlap")
            for j in range(i + 2, len(edges)):
                if i == 0 and j == len(edges) - 1:
                    continue  # The closing edge shares the first vertex.
                if segments_intersect(start, end, *edges[j]):
                    raise ValueError("terrain polygon edges must not intersect")

        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "bounds", (min_x, min_y, max_x, max_y))

    def contains_point(self, point: Position) -> bool:
        """Even-odd ray casting, with the perimeter included."""
        min_x, min_y, max_x, max_y = self.bounds
        if not (min_x <= point.x <= max_x and min_y <= point.y <= max_y):
            return False
        inside = False
        for start, end in self.edges:
            if point_on_segment(point, start, end):
                return True
            # The half-open test counts a ray through a vertex only once per crossing.
            if (start.y > point.y) != (end.y > point.y):
                fraction = (point.y - start.y) / (end.y - start.y)
                if point.x < start.x + fraction * (end.x - start.x):
                    inside = not inside
        return inside

    def intersects_segment(self, start: Position, end: Position) -> bool:
        """Whether the segment touches or crosses the filled polygon."""
        min_x, min_y, max_x, max_y = self.bounds
        if (
            max(start.x, end.x) < min_x or min(start.x, end.x) > max_x
            or max(start.y, end.y) < min_y or min(start.y, end.y) > max_y
        ):
            return False
        return (
            any(segments_intersect(start, end, a, b) for a, b in self.edges)
            or self.contains_point(start)
        )
