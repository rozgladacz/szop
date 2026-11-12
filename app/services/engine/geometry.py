"""B3.9.b — Kanoniczne prymityki geometryczne dla engine.

Single source of truth dla wszystkich obliczeń odległości / przecięć / inclusion w
silniku. Przed B3.9 te same operacje były duplikowane w 4 miejscach (`los.py`
`_distance`/`_point_in_circle`/`_segment_intersects_circle`/`_segments_intersect`,
`phases.py` `_distance`, `combat.py` inline `(dx*dx + dy*dy) ** 0.5` × 2) co
stanowiło dziurę D z post-B3 code review oraz było przyczyną buga #4 (`charger.radius`
ignored w `resolve_charge_attack` — brak `circle_edge_distance` helpera).

Public API:
- `distance(p1, p2)` — Euclidean distance między dwoma `Position`. Implementacja
  `math.hypot` (numerycznie stabilniejsza od `sqrt(dx² + dy²)`).
- `point_in_circle(point, center, radius)` — `True` gdy `distance(point, center) <= radius`.
- `segment_intersects_circle(p1, p2, center, radius)` — `True` gdy odcinek p1→p2
  przecina lub leży wewnątrz koła (clamped projection).
- `segments_intersect(p1, p2, p3, p4)` — `True` gdy dwa odcinki się przecinają
  (CCW orientation test + colinear handling).
- `circle_edge_distance(c1_pos, c1_r, c2_pos, c2_r)` — dystans **między
  obwodami** dwóch kół. Ujemny gdy koła się nakładają. Rozwiązuje bug #4:
  `min_gap` w Szarży musi liczyć `charger.radius + defender.radius + 1.0`, nie
  samo `defender.radius + 1.0`.
- `UNIT_CIRCLE_16` — precomputed tuple 16 `(cos(angle), sin(angle))` dla
  `LoSState` samplingu (perf — unika 16× `math.cos`/`sin` per LoS call).

Konwencje:
- Wszystkie funkcje **pure** — bez state, bez side-effects.
- `Position` żyje w tym module, a `app.services.engine.state` nadal je eksportuje.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """2D pozycja w calach, od lewego dolnego rogu pola bitwy."""

    x: float
    y: float


# ---------------------------------------------------------------------------
# Distance primitives
# ---------------------------------------------------------------------------


def distance(p1: "Position", p2: "Position") -> float:
    """Euclidean distance między dwoma punktami przez `math.hypot`.

    `math.hypot(dx, dy)` jest numerycznie stabilniejszy dla bardzo małych/dużych
    wartości niż `sqrt(dx*dx + dy*dy)` (unika overflow w kwadratach).
    """
    return math.hypot(p2.x - p1.x, p2.y - p1.y)


def point_in_circle(point: "Position", center: "Position", radius: float) -> bool:
    """`True` gdy `point` jest wewnątrz koła (≤ `radius` od `center`)."""
    return distance(point, center) <= radius


def circle_edge_distance(
    c1_pos: "Position", c1_radius: float, c2_pos: "Position", c2_radius: float
) -> float:
    """Dystans między obwodami dwóch kół (`distance(centers) - r1 - r2`).

    Wartości:
    - `> 0` — koła rozłączne; minimalny gap między obwodami.
    - `== 0` — koła stykają się zewnętrznie.
    - `< 0` — koła się nakładają (penetration depth = `-result`).

    Używane w `resolve_charge_attack` dla `min_gap`: charger musi zatrzymać się
    tak, żeby jego obwód był w odległości 1″ od obwodu defendera, czyli
    `distance(centers) >= c1_r + c2_r + 1.0`. Przed B3.9.b bug #4 ignorował
    `c1_r` (charger.radius) i liczył `defender.radius + 1.0` jako min_gap.
    """
    return distance(c1_pos, c2_pos) - c1_radius - c2_radius


# ---------------------------------------------------------------------------
# Segment intersection primitives
# ---------------------------------------------------------------------------


def segment_intersects_circle(
    p1: "Position", p2: "Position", center: "Position", radius: float
) -> bool:
    """`True` gdy odcinek p1→p2 przecina koło `(center, radius)` lub jest wewnątrz.

    Algorytm: clamped projection center na linię p1-p2. Endpoints inside koło
    również się liczą (segment częściowo wewnątrz).
    """
    if point_in_circle(p1, center, radius):
        return True
    if point_in_circle(p2, center, radius):
        return True

    return point_segment_distance(center, p1, p2) <= radius


def point_segment_distance(point: Position, start: Position, end: Position) -> float:
    """Shortest Euclidean distance to a segment, including its endpoints."""
    dx = end.x - start.x
    dy = end.y - start.y
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return distance(point, start)

    projection = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_sq
    if projection <= 0:
        return distance(point, start)
    if projection >= 1:
        return distance(point, end)
    return math.hypot(
        start.x + projection * dx - point.x, start.y + projection * dy - point.y
    )


def _orientation(a: Position, b: Position, point: Position) -> float:
    return (b.x - a.x) * (point.y - a.y) - (b.y - a.y) * (point.x - a.x)


def _in_segment_bounds(point: Position, start: Position, end: Position) -> bool:
    return (
        min(start.x, end.x) <= point.x <= max(start.x, end.x)
        and min(start.y, end.y) <= point.y <= max(start.y, end.y)
    )


def point_on_segment(point: Position, start: Position, end: Position) -> bool:
    """Whether a point lies on the closed segment, including its endpoints."""
    return _in_segment_bounds(point, start, end) and _orientation(start, end, point) == 0


def segments_intersect(
    p1: "Position", p2: "Position", p3: "Position", p4: "Position"
) -> bool:
    """`True` gdy odcinek p1→p2 przecina odcinek p3→p4.

    Standardowy test orientacji CCW (Counter-Clock-Wise). Obejmuje też colinear
    cases (jeden punkt leży na drugim odcinku).
    """

    d1 = _orientation(p3, p4, p1)
    d2 = _orientation(p3, p4, p2)
    d3 = _orientation(p1, p2, p3)
    d4 = _orientation(p1, p2, p4)

    # Strict crossing: orientations różne dla obu par
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True

    return (
        (d1 == 0 and _in_segment_bounds(p1, p3, p4))
        or (d2 == 0 and _in_segment_bounds(p2, p3, p4))
        or (d3 == 0 and _in_segment_bounds(p3, p1, p2))
        or (d4 == 0 and _in_segment_bounds(p4, p1, p2))
    )


def segment_segment_distance(a: Position, b: Position, c: Position, d: Position) -> float:
    """Shortest distance between two closed 2D segments."""
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(
        point_segment_distance(a, c, d),
        point_segment_distance(b, c, d),
        point_segment_distance(c, a, b),
        point_segment_distance(d, a, b),
    )


# ---------------------------------------------------------------------------
# Precomputed unit circle samples (perf — 16-point LoS sampling per ADR-0043)
# ---------------------------------------------------------------------------

UNIT_CIRCLE_16: tuple[tuple[float, float], ...] = tuple(
    (math.cos(2.0 * math.pi * i / 16), math.sin(2.0 * math.pi * i / 16))
    for i in range(16)
)
"""16 punktów `(cos θ, sin θ)` równomiernie rozłożonych na okręgu jednostkowym.

Indeksy 0..15 odpowiadają kątom `2π·i/16`. Punkt na obwodzie koła `(cx, cy, r)`:
`(cx + r * UNIT_CIRCLE_16[i][0], cy + r * UNIT_CIRCLE_16[i][1])`. Używane przez
`check_los` (sampling N=16 per ADR-0043) zamiast 16 wywołań `math.cos`/`sin` per
LoS query.
"""


__all__ = [
    "Position",
    "distance",
    "point_in_circle",
    "circle_edge_distance",
    "point_segment_distance",
    "segment_intersects_circle",
    "segment_segment_distance",
    "point_on_segment",
    "segments_intersect",
    "UNIT_CIRCLE_16",
]
