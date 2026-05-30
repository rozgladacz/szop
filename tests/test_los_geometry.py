"""B3.2 — testy `app/services/engine/los.py` (≥30 scenariuszy, ADR-0043).

Pokrywa: 3-state classification (WIDZI/NIE_WIDZI/OSLONA), Blokujący vs
Zasłaniający (pkt 4.c.ii/iii), Zasłaniający exception (atakujący/cel wewnątrz),
edge cases (empty terrain, same position, n_samples), geometry helpers
(_distance, _point_in_circle, _segment_intersects_circle, _segments_intersect).
"""

from __future__ import annotations

import math

import pytest

from app.services.engine.los import (
    DEFAULT_N_SAMPLES,
    FEATURE_BLOKUJACY,
    FEATURE_ZASLANIAJACY,
    LoSState,
    _blob_inside_terrain,
    _distance,
    _point_in_circle,
    _segment_intersects_circle,
    _segments_intersect,
    check_los,
)
from app.services.engine.state import (
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)


# ---------------------------------------------------------------------------
# Helpers do tworzenia blobów / terrain
# ---------------------------------------------------------------------------


def make_blob(
    blob_id: int = 1,
    x: float = 0.0,
    y: float = 0.0,
    radius: float = 1.0,
    owner: int = 0,
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(x, y),
        radius_inches=radius,
        models_alive=5,
        toughness_per_model=3,
    )


# ---------------------------------------------------------------------------
# Geometry primitives — _distance
# ---------------------------------------------------------------------------


def test_distance_zero():
    assert _distance(Position(0, 0), Position(0, 0)) == 0


def test_distance_pythagorean():
    assert math.isclose(_distance(Position(0, 0), Position(3, 4)), 5.0)


def test_distance_symmetric():
    p1 = Position(1, 2)
    p2 = Position(5, 7)
    assert _distance(p1, p2) == _distance(p2, p1)


# ---------------------------------------------------------------------------
# _point_in_circle
# ---------------------------------------------------------------------------


def test_point_in_circle_center():
    assert _point_in_circle(Position(0, 0), Position(0, 0), 5)


def test_point_in_circle_edge():
    """Point on edge (distance == radius) — inclusive."""
    assert _point_in_circle(Position(5, 0), Position(0, 0), 5)


def test_point_in_circle_outside():
    assert not _point_in_circle(Position(10, 0), Position(0, 0), 5)


# ---------------------------------------------------------------------------
# _segment_intersects_circle
# ---------------------------------------------------------------------------


def test_segment_endpoint_inside_circle():
    """Segment z endpoint wewnątrz koła → intersects."""
    assert _segment_intersects_circle(
        Position(0, 0), Position(10, 10), Position(0, 0), 1
    )


def test_segment_crosses_circle_center():
    """Segment przechodzący przez centrum koła → intersects."""
    assert _segment_intersects_circle(
        Position(-5, 0), Position(5, 0), Position(0, 0), 2
    )


def test_segment_tangent_to_circle():
    """Segment styczny do koła (closest point dokładnie na obwodzie) → intersects."""
    # Segment od (-5, 2) do (5, 2), koło (0,0) r=2 — styczny w (0,2)
    assert _segment_intersects_circle(
        Position(-5, 2), Position(5, 2), Position(0, 0), 2
    )


def test_segment_far_from_circle():
    assert not _segment_intersects_circle(
        Position(-5, 10), Position(5, 10), Position(0, 0), 2
    )


def test_segment_perpendicular_to_circle_above():
    """Segment powyżej koła, nie dotyka."""
    assert not _segment_intersects_circle(
        Position(0, 5), Position(0, 10), Position(0, 0), 2
    )


# ---------------------------------------------------------------------------
# _segments_intersect
# ---------------------------------------------------------------------------


def test_segments_crossing():
    """Segmenty krzyżujące się w środku."""
    assert _segments_intersect(
        Position(-5, 0), Position(5, 0), Position(0, -5), Position(0, 5)
    )


def test_segments_parallel():
    """Segmenty równoległe → nie przecinają."""
    assert not _segments_intersect(
        Position(0, 0), Position(5, 0), Position(0, 1), Position(5, 1)
    )


def test_segments_apart():
    """Segmenty rozdzielone → nie przecinają."""
    assert not _segments_intersect(
        Position(0, 0), Position(1, 0), Position(5, 5), Position(6, 6)
    )


def test_segments_collinear_overlap():
    """Segmenty kolinearne, nakładające się → intersect."""
    assert _segments_intersect(
        Position(0, 0), Position(5, 0), Position(3, 0), Position(7, 0)
    )


# ---------------------------------------------------------------------------
# _blob_inside_terrain
# ---------------------------------------------------------------------------


def test_blob_inside_terrain_circle_yes():
    blob = make_blob(x=0, y=0, radius=1)
    terrain = TerrainCircle(
        center=Position(0, 0), radius_inches=5, features=(FEATURE_ZASLANIAJACY,)
    )
    assert _blob_inside_terrain(blob, terrain) is True


def test_blob_inside_terrain_circle_no():
    blob = make_blob(x=100, y=100, radius=1)
    terrain = TerrainCircle(
        center=Position(0, 0), radius_inches=5, features=(FEATURE_ZASLANIAJACY,)
    )
    assert _blob_inside_terrain(blob, terrain) is False


def test_blob_inside_terrain_line_always_false():
    """TerrainLine nie ma 'wnętrza'."""
    blob = make_blob(x=0, y=0)
    terrain = TerrainLine(
        start=Position(-5, 0), end=Position(5, 0), features=(FEATURE_ZASLANIAJACY,)
    )
    assert _blob_inside_terrain(blob, terrain) is False


# ---------------------------------------------------------------------------
# check_los — basic (no terrain)
# ---------------------------------------------------------------------------


def test_los_no_terrain_clear():
    """Brak terenu → WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0)
    target = make_blob(blob_id=2, x=20, y=0)
    assert check_los(attacker, target, terrain=()) == LoSState.WIDZI


def test_los_empty_terrain_iterable():
    attacker = make_blob(blob_id=1, x=0, y=0)
    target = make_blob(blob_id=2, x=10, y=0)
    assert check_los(attacker, target, terrain=[]) == LoSState.WIDZI


def test_los_degenerate_same_position():
    """Identyczna pozycja attacker == target → WIDZI (degenerate guard)."""
    attacker = make_blob(blob_id=1, x=5, y=5)
    target = make_blob(blob_id=2, x=5, y=5)
    assert check_los(attacker, target, terrain=()) == LoSState.WIDZI


# ---------------------------------------------------------------------------
# check_los — Blokujący terrain (pkt 4.c.ii)
# ---------------------------------------------------------------------------


def test_los_full_block_circle_blokujacy():
    """Duże koło Blokujący między attackerem a celem → NIE_WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_BLOKUJACY,)
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.NIE_WIDZI


def test_los_full_block_line_blokujacy():
    """Linia Blokujący spanning całe pole celu → NIE_WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=1)
    blocker = TerrainLine(
        start=Position(15, -50), end=Position(15, 50), features=(FEATURE_BLOKUJACY,)
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.NIE_WIDZI


def test_los_partial_block_oslona():
    """Małe koło częściowo zasłaniające → OSLONA."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=5)
    # Mały blocker dokładnie na środku linii — zasłania część punktów celu
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=1, features=(FEATURE_BLOKUJACY,)
    )
    result = check_los(attacker, target, terrain=[blocker])
    assert result == LoSState.OSLONA


def test_los_terrain_far_away_no_effect():
    """Teren daleko od linii LoS → WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0)
    target = make_blob(blob_id=2, x=20, y=0)
    far_terrain = TerrainCircle(
        center=Position(50, 50), radius_inches=5, features=(FEATURE_BLOKUJACY,)
    )
    assert check_los(attacker, target, terrain=[far_terrain]) == LoSState.WIDZI


# ---------------------------------------------------------------------------
# check_los — Zasłaniający terrain (pkt 4.c.iii)
# ---------------------------------------------------------------------------


def test_los_zaslaniajacy_neither_inside_blocks():
    """Zasłaniający między, neither attacker/target inside → blokuje jak Blokujący."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_ZASLANIAJACY,)
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.NIE_WIDZI


def test_los_zaslaniajacy_attacker_inside_does_not_block():
    """Attacker wewnątrz Zasłaniającego — exception pkt 4.c.iii."""
    attacker = make_blob(blob_id=1, x=15, y=0, radius=1)  # wewnątrz blockera
    target = make_blob(blob_id=2, x=50, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_ZASLANIAJACY,)
    )
    # Attacker wewnątrz → ten teren nie blokuje LoS dla tej pary
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.WIDZI


def test_los_zaslaniajacy_target_inside_does_not_block():
    """Target wewnątrz Zasłaniającego — exception pkt 4.c.iii."""
    attacker = make_blob(blob_id=1, x=-30, y=0, radius=1)
    target = make_blob(blob_id=2, x=15, y=0, radius=1)  # wewnątrz blockera
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_ZASLANIAJACY,)
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.WIDZI


def test_los_zaslaniajacy_both_inside_does_not_block():
    """Oba wewnątrz Zasłaniającego — oba korzystają z wyjątku."""
    attacker = make_blob(blob_id=1, x=12, y=0, radius=1)
    target = make_blob(blob_id=2, x=18, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_ZASLANIAJACY,)
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.WIDZI


def test_los_blokujacy_attacker_inside_still_blocks():
    """Blokujący NIE ma wyjątku — attacker inside też blokuje (przeciwnie do Zasłaniający)."""
    attacker = make_blob(blob_id=1, x=15, y=0, radius=1)  # wewnątrz blockera
    target = make_blob(blob_id=2, x=50, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_BLOKUJACY,)
    )
    # Per pkt 4.c.ii Blokujący jest bezwarunkowy → attacker w środku też blokuje
    # ale tylko jeśli segment od edge attackera do targetu przechodzi przez teren.
    # Edge attackera może być wewnątrz blockera; targety na obwodzie celu są poza
    # → segmenty przechodzą przez krawędź blockera → blokowane → NIE_WIDZI.
    result = check_los(attacker, target, terrain=[blocker])
    # Nie sprawdzamy konkretnego stanu — kluczowe: nie WIDZI (Blokujący jest aktywny).
    assert result != LoSState.WIDZI


# ---------------------------------------------------------------------------
# check_los — multiple terrain
# ---------------------------------------------------------------------------


def test_los_one_zaslaniajacy_with_attacker_inside_other_blokujacy_blocks():
    """Attacker inside Zaslaniajacy → ten teren nie blokuje. Ale drugi Blokujący nadal blokuje."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=50, y=0, radius=1)
    zaslaniajacy = TerrainCircle(
        center=Position(0, 0), radius_inches=5, features=(FEATURE_ZASLANIAJACY,)
    )
    blokujacy = TerrainCircle(
        center=Position(25, 0), radius_inches=10, features=(FEATURE_BLOKUJACY,)
    )
    result = check_los(attacker, target, terrain=[zaslaniajacy, blokujacy])
    assert result == LoSState.NIE_WIDZI  # blokujacy nadal blokuje


def test_los_two_blokujacy_layered():
    """Dwa blokery jeden za drugim — i tak NIE_WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=50, y=0, radius=1)
    b1 = TerrainCircle(
        center=Position(15, 0), radius_inches=8, features=(FEATURE_BLOKUJACY,)
    )
    b2 = TerrainCircle(
        center=Position(35, 0), radius_inches=8, features=(FEATURE_BLOKUJACY,)
    )
    assert check_los(attacker, target, terrain=[b1, b2]) == LoSState.NIE_WIDZI


# ---------------------------------------------------------------------------
# check_los — non-blocking features ignored
# ---------------------------------------------------------------------------


def test_los_terrain_trudny_no_effect():
    """Teren z cechą Trudny (ale nie Blokujący/Zasłaniający) → ignorowany."""
    attacker = make_blob(blob_id=1, x=0, y=0)
    target = make_blob(blob_id=2, x=30, y=0)
    trudny_terrain = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=("Trudny",)
    )
    assert check_los(attacker, target, terrain=[trudny_terrain]) == LoSState.WIDZI


def test_los_terrain_obronny_no_effect():
    """Obronny też nie blokuje LoS (daje +1 do obrony, nie LoS)."""
    attacker = make_blob(blob_id=1, x=0, y=0)
    target = make_blob(blob_id=2, x=30, y=0)
    obronny = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=("Obronny",)
    )
    assert check_los(attacker, target, terrain=[obronny]) == LoSState.WIDZI


def test_los_terrain_blokujacy_plus_trudny():
    """Teren z multiple cechami (Blokujący + Trudny) — Blokujący decyduje o LoS."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0),
        radius_inches=10,
        features=(FEATURE_BLOKUJACY, "Trudny"),
    )
    assert check_los(attacker, target, terrain=[blocker]) == LoSState.NIE_WIDZI


# ---------------------------------------------------------------------------
# check_los — edge cases
# ---------------------------------------------------------------------------


def test_los_n_samples_zero_raises():
    attacker = make_blob(blob_id=1)
    target = make_blob(blob_id=2, x=10, y=0)
    with pytest.raises(ValueError):
        check_los(attacker, target, n_samples=0)


def test_los_n_samples_negative_raises():
    attacker = make_blob(blob_id=1)
    target = make_blob(blob_id=2, x=10, y=0)
    with pytest.raises(ValueError):
        check_los(attacker, target, n_samples=-5)


def test_los_default_n_samples_is_16():
    """Default N=16 per ADR-0043."""
    assert DEFAULT_N_SAMPLES == 16


def test_los_n_samples_1_no_oslona():
    """Z n_samples=1 nigdy nie ma OSLONA (tylko binary WIDZI/NIE_WIDZI)."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=30, y=0, radius=1)
    result = check_los(attacker, target, terrain=(), n_samples=1)
    assert result in (LoSState.WIDZI, LoSState.NIE_WIDZI)


# ---------------------------------------------------------------------------
# LoSState enum
# ---------------------------------------------------------------------------


def test_los_state_enum_values():
    assert LoSState.WIDZI.value == "widzi"
    assert LoSState.NIE_WIDZI.value == "nie_widzi"
    assert LoSState.OSLONA.value == "oslona"


def test_los_state_three_distinct_members():
    members = {m for m in LoSState}
    assert len(members) == 3
    assert LoSState.WIDZI != LoSState.NIE_WIDZI
    assert LoSState.WIDZI != LoSState.OSLONA
    assert LoSState.NIE_WIDZI != LoSState.OSLONA


# ---------------------------------------------------------------------------
# Realistic battle scenarios
# ---------------------------------------------------------------------------


def test_los_scenario_close_targets_thin_blocker():
    """Atakujący 0,0; cel 10,0 (r=2). Cienki słup w środku — częściowe zasłonięcie."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=10, y=0, radius=2)
    pillar = TerrainCircle(
        center=Position(5, 0), radius_inches=0.5, features=(FEATURE_BLOKUJACY,)
    )
    # Cienki słup zasłania mały fragment celu (większość punktów widoczna).
    result = check_los(attacker, target, terrain=[pillar])
    # Realistycznie powinno być OSLONA — sample punktów na "tyle" celu zablokowane.
    assert result in (LoSState.OSLONA, LoSState.WIDZI)


def test_los_scenario_target_behind_wall():
    """Cel za murem (TerrainLine) → NIE_WIDZI."""
    attacker = make_blob(blob_id=1, x=0, y=0, radius=1)
    target = make_blob(blob_id=2, x=20, y=0, radius=1)
    wall = TerrainLine(
        start=Position(10, -20), end=Position(10, 20), features=(FEATURE_BLOKUJACY,)
    )
    assert check_los(attacker, target, terrain=[wall]) == LoSState.NIE_WIDZI
