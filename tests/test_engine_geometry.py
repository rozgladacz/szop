"""B3.9.b — testy `app/services/engine/geometry.py`.

Pokrywa:
- `distance` — Euclidean, math.hypot-based, symetria + zero degeneracja
- `point_in_circle` — inclusive boundary, center/edge/outside
- `circle_edge_distance` — positive/zero/negative (overlap)
- `segment_intersects_circle` — endpoint inside, midpoint crossing, clamped projection
- `segments_intersect` — strict crossing, T-junction (colinear endpoint on segment), parallel non-intersecting
- `UNIT_CIRCLE_16` — 16 elements, unit length, equally spaced angles
"""

from __future__ import annotations

import math

import pytest

from app.services.engine.geometry import (
    UNIT_CIRCLE_16,
    circle_edge_distance,
    distance,
    point_in_circle,
    segment_intersects_circle,
    segments_intersect,
)
from app.services.engine.state import Position


# ---------------------------------------------------------------------------
# distance
# ---------------------------------------------------------------------------


def test_distance_zero_for_same_point():
    p = Position(x=3.0, y=4.0)
    assert distance(p, p) == 0.0


def test_distance_horizontal():
    p1 = Position(x=0.0, y=5.0)
    p2 = Position(x=4.0, y=5.0)
    assert distance(p1, p2) == 4.0


def test_distance_pythagorean_345():
    """Klasyczny trójkąt 3-4-5."""
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=3.0, y=4.0)
    assert distance(p1, p2) == pytest.approx(5.0)


def test_distance_symmetric():
    p1 = Position(x=1.5, y=-2.0)
    p2 = Position(x=-3.0, y=7.5)
    assert distance(p1, p2) == pytest.approx(distance(p2, p1))


# ---------------------------------------------------------------------------
# point_in_circle
# ---------------------------------------------------------------------------


def test_point_in_circle_center_inside():
    center = Position(x=0.0, y=0.0)
    assert point_in_circle(center, center, radius=2.0) is True


def test_point_in_circle_on_boundary_inclusive():
    """Punkt dokładnie na obwodzie liczy się jako wewnątrz (≤ radius)."""
    center = Position(x=0.0, y=0.0)
    edge = Position(x=2.0, y=0.0)
    assert point_in_circle(edge, center, radius=2.0) is True


def test_point_in_circle_outside():
    center = Position(x=0.0, y=0.0)
    outside = Position(x=3.0, y=0.0)
    assert point_in_circle(outside, center, radius=2.0) is False


def test_point_in_circle_off_axis():
    center = Position(x=1.0, y=1.0)
    point = Position(x=2.0, y=2.0)  # distance = sqrt(2) ≈ 1.41
    assert point_in_circle(point, center, radius=1.5) is True
    assert point_in_circle(point, center, radius=1.0) is False


# ---------------------------------------------------------------------------
# circle_edge_distance (fix #4)
# ---------------------------------------------------------------------------


def test_circle_edge_distance_disjoint_positive():
    """Dwa rozłączne koła — gap między obwodami dodatni."""
    c1 = Position(x=0.0, y=0.0)
    c2 = Position(x=10.0, y=0.0)
    # centers 10 apart, radii 2 + 3 = 5, edge gap = 10 - 5 = 5
    assert circle_edge_distance(c1, 2.0, c2, 3.0) == pytest.approx(5.0)


def test_circle_edge_distance_touching_zero():
    """Koła stykające się zewnętrznie — gap = 0."""
    c1 = Position(x=0.0, y=0.0)
    c2 = Position(x=5.0, y=0.0)
    assert circle_edge_distance(c1, 2.0, c2, 3.0) == pytest.approx(0.0)


def test_circle_edge_distance_overlapping_negative():
    """Koła nakładające się — gap ujemny (penetration depth)."""
    c1 = Position(x=0.0, y=0.0)
    c2 = Position(x=3.0, y=0.0)
    # centers 3 apart, radii 2 + 2 = 4, edge gap = 3 - 4 = -1
    assert circle_edge_distance(c1, 2.0, c2, 2.0) == pytest.approx(-1.0)


def test_circle_edge_distance_symmetric():
    c1 = Position(x=1.0, y=2.0)
    c2 = Position(x=5.0, y=8.0)
    assert circle_edge_distance(c1, 1.5, c2, 2.5) == pytest.approx(
        circle_edge_distance(c2, 2.5, c1, 1.5)
    )


def test_circle_edge_distance_used_for_charge_min_gap():
    """Bug #4 regression: w `resolve_charge_attack` `min_gap` musi liczyć
    obie radii. Sanity: dla charger.r=1.5, defender.r=2.0, target gap=1″,
    minimalna distance(centers) = 1.5 + 2.0 + 1.0 = 4.5″ (= edge_gap=1.0)."""
    charger_pos = Position(x=0.0, y=0.0)
    defender_pos = Position(x=4.5, y=0.0)
    edge_gap = circle_edge_distance(charger_pos, 1.5, defender_pos, 2.0)
    assert edge_gap == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# segment_intersects_circle
# ---------------------------------------------------------------------------


def test_segment_intersects_circle_endpoint_inside():
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=10.0, y=0.0)
    center = Position(x=1.0, y=0.0)
    assert segment_intersects_circle(p1, p2, center, radius=2.0) is True


def test_segment_intersects_circle_both_endpoints_outside_midpoint_crosses():
    """Odcinek przechodzi przez koło — endpoints poza, środek wewnątrz."""
    p1 = Position(x=-10.0, y=0.0)
    p2 = Position(x=10.0, y=0.0)
    center = Position(x=0.0, y=0.0)
    assert segment_intersects_circle(p1, p2, center, radius=2.0) is True


def test_segment_intersects_circle_passes_far_away():
    p1 = Position(x=-10.0, y=10.0)
    p2 = Position(x=10.0, y=10.0)
    center = Position(x=0.0, y=0.0)
    assert segment_intersects_circle(p1, p2, center, radius=2.0) is False


def test_segment_intersects_circle_clamped_projection_outside_segment():
    """Najbliższy punkt projekcji jest poza segmentem (clamping na endpoint)."""
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=1.0, y=0.0)
    center = Position(x=10.0, y=0.0)  # daleko za p2
    assert segment_intersects_circle(p1, p2, center, radius=2.0) is False


def test_segment_intersects_circle_degenerate_point():
    """p1 == p2 i poza kołem — False; w środku kola — True."""
    p_outside = Position(x=10.0, y=0.0)
    p_inside = Position(x=1.0, y=1.0)
    center = Position(x=0.0, y=0.0)
    assert segment_intersects_circle(p_outside, p_outside, center, 2.0) is False
    assert segment_intersects_circle(p_inside, p_inside, center, 2.0) is True


# ---------------------------------------------------------------------------
# segments_intersect
# ---------------------------------------------------------------------------


def test_segments_intersect_cross_in_middle():
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=10.0, y=10.0)
    p3 = Position(x=0.0, y=10.0)
    p4 = Position(x=10.0, y=0.0)
    assert segments_intersect(p1, p2, p3, p4) is True


def test_segments_intersect_parallel_no_overlap():
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=10.0, y=0.0)
    p3 = Position(x=0.0, y=5.0)
    p4 = Position(x=10.0, y=5.0)
    assert segments_intersect(p1, p2, p3, p4) is False


def test_segments_intersect_t_junction_colinear_endpoint():
    """Endpoint jednego segmentu leży na drugim (T-junction)."""
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=10.0, y=0.0)
    p3 = Position(x=5.0, y=0.0)  # leży na p1-p2
    p4 = Position(x=5.0, y=10.0)
    assert segments_intersect(p1, p2, p3, p4) is True


def test_segments_intersect_disjoint_no_cross():
    p1 = Position(x=0.0, y=0.0)
    p2 = Position(x=1.0, y=1.0)
    p3 = Position(x=10.0, y=10.0)
    p4 = Position(x=20.0, y=20.0)
    assert segments_intersect(p1, p2, p3, p4) is False


# ---------------------------------------------------------------------------
# UNIT_CIRCLE_16
# ---------------------------------------------------------------------------


def test_unit_circle_16_has_exactly_16_points():
    assert len(UNIT_CIRCLE_16) == 16


def test_unit_circle_16_points_on_unit_circle():
    """Każdy `(cos θ, sin θ)` jest na okręgu jednostkowym (|v| == 1)."""
    for cos_a, sin_a in UNIT_CIRCLE_16:
        magnitude = math.hypot(cos_a, sin_a)
        assert magnitude == pytest.approx(1.0)


def test_unit_circle_16_first_point_is_angle_zero():
    """Index 0 = kąt 0 = (1, 0)."""
    cos_0, sin_0 = UNIT_CIRCLE_16[0]
    assert cos_0 == pytest.approx(1.0)
    assert sin_0 == pytest.approx(0.0, abs=1e-12)


def test_unit_circle_16_quarter_point_is_pi_over_2():
    """Index 4 = kąt π/2 = (0, 1)."""
    cos_q, sin_q = UNIT_CIRCLE_16[4]
    assert cos_q == pytest.approx(0.0, abs=1e-12)
    assert sin_q == pytest.approx(1.0)


def test_unit_circle_16_evenly_spaced():
    """Sąsiednie punkty różnią się o stały kąt 2π/16."""
    expected_step = 2.0 * math.pi / 16
    for i in range(16):
        cos_a, sin_a = UNIT_CIRCLE_16[i]
        cos_b, sin_b = UNIT_CIRCLE_16[(i + 1) % 16]
        # cos różnicy kątów = dot product wektorów jednostkowych
        dot = cos_a * cos_b + sin_a * sin_b
        assert dot == pytest.approx(math.cos(expected_step))
