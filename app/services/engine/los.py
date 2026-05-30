"""B3.2 — Line of Sight (3-state) per `SZOP_Rozjemca.md pkt 6` (ADR-0043).

3-state LoS:
- **WIDZI** — każdy z N=16 punktów na obwodzie celu osiągalny (pkt 6.a.i)
- **NIE_WIDZI** — żaden punkt nie jest osiągalny
- **OSŁONA** — przynajmniej 1 osiągalny + przynajmniej 1 zablokowany (pkt 6.a.ii: "Jeżeli jest punkt podstawki do którego nie można poprowadzić takiej linii cel ma osłonę")

Blokady (pkt 6.b):
- Teren z cechą `Blokujacy` (pkt 4.c.ii) — zawsze blokuje
- Teren z cechą `Zaslaniajacy` (pkt 4.c.iii) — blokuje **z wyjątkiem** gdy atakujący lub cel jest wewnątrz tego terenu

Modele jako blokady (pkt 2.d): NIE obsługiwane w MVP (TODO future iteration);
modele tego samego oddziału nie blokują (pkt 6.c) — to też nieaktywne, bo
oddział = blob.

Algorithm:
1. Wyznacz `attacker_edge_point` na obwodzie atakującego, w kierunku celu.
2. Sample N=16 punktów równomiernie na obwodzie celu (kąty 2π·i/N).
3. Filtruj teren który blokuje LoS (uwzględniając Zasłaniający exception).
4. Dla każdego z N target points: sprawdź czy odcinek `attacker_edge → target_point` przecina jakikolwiek blokujący teren.
5. Klasyfikacja: all visible → WIDZI; none → NIE_WIDZI; mixed → OSŁONA.

Komentarz do `n_samples` (ADR-0043): N=16 to Pareto trade-off między
dokładnością a kosztem (16 segment-vs-circle tests per terrain per LoS call).
Plan B: N=32 lub analytic tangent jeśli >5% false-positive rate w empirycznym
test bed (B7).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Iterable

from app.services.engine.state import (
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)


class LoSState(Enum):
    """3-state Line of Sight per pkt 6 + ADR-0043."""

    WIDZI = "widzi"
    NIE_WIDZI = "nie_widzi"
    OSLONA = "oslona"


DEFAULT_N_SAMPLES = 16

# Sentinel features (Polish, ASCII-fold per slug convention z A4)
FEATURE_BLOKUJACY = "Blokujacy"
FEATURE_ZASLANIAJACY = "Zaslaniajacy"


# ---------------------------------------------------------------------------
# Geometry primitives — pure functions
# ---------------------------------------------------------------------------


def _distance(p1: Position, p2: Position) -> float:
    """Euclidean distance między dwoma punktami."""
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    return math.sqrt(dx * dx + dy * dy)


def _point_in_circle(point: Position, center: Position, radius: float) -> bool:
    """True jeśli `point` jest wewnątrz koła (≤ radius od center)."""
    return _distance(point, center) <= radius


def _segment_intersects_circle(
    p1: Position, p2: Position, center: Position, radius: float
) -> bool:
    """True jeśli odcinek p1→p2 przecina koło (center, radius).

    Algorithm: project center na linię p1-p2, oblicz najbliższy punkt na
    odcinku (clamp do [0,1]), sprawdź dystans od center. Endpoints inside koło
    też się liczą (segment częściowo wewnątrz).
    """
    # Jeśli któryś koniec jest wewnątrz koła, segment przecina (lub jest wewnątrz).
    if _point_in_circle(p1, center, radius):
        return True
    if _point_in_circle(p2, center, radius):
        return True

    # Wektor segmentu
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0:
        # Degenerate: p1 == p2; sprawdzony już wyżej (oba "endpoints").
        return False

    # Parametr t na linii p1→p2, gdzie najbliższy punkt do center
    # t = ((center - p1) · (p2 - p1)) / |p2 - p1|^2
    t = ((center.x - p1.x) * dx + (center.y - p1.y) * dy) / seg_len_sq
    # Clamp do [0, 1] żeby zostać na odcinku (nie na nieskończonej linii)
    t = max(0.0, min(1.0, t))

    # Najbliższy punkt na odcinku
    closest = Position(p1.x + t * dx, p1.y + t * dy)
    return _distance(closest, center) <= radius


def _segments_intersect(
    p1: Position, p2: Position, p3: Position, p4: Position
) -> bool:
    """True jeśli odcinek p1→p2 przecina odcinek p3→p4.

    Standard CCW (Counter Clock-Wise) orientation test. Pokrywa też cases
    gdy segmenty są kolinearne i nakładają się.
    """

    def ccw(a: Position, b: Position, c: Position) -> float:
        """Cross product: dodatni gdy a→b→c jest CCW."""
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)

    # Strict crossing: orientations różne dla obu par
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True

    # Colinear cases (point lies on segment)
    def on_segment(a: Position, b: Position, c: Position) -> bool:
        return (
            min(a.x, b.x) <= c.x <= max(a.x, b.x)
            and min(a.y, b.y) <= c.y <= max(a.y, b.y)
        )

    if d1 == 0 and on_segment(p3, p4, p1):
        return True
    if d2 == 0 and on_segment(p3, p4, p2):
        return True
    if d3 == 0 and on_segment(p1, p2, p3):
        return True
    if d4 == 0 and on_segment(p1, p2, p4):
        return True

    return False


def _blob_inside_terrain(
    blob: UnitBlob, terrain: TerrainCircle | TerrainLine
) -> bool:
    """Czy blob (centrum) jest "wewnątrz" terenu.

    Per `SZOP_Rozjemca.md pkt 4.a`: oddział wewnątrz gdy większość modeli w
    większości znajduje się w obrębie. W Pareto MVP (oddział = koło): proxy
    przez centrum blob. Dla `TerrainLine` zwraca False (line nie ma "wnętrza").
    """
    if isinstance(terrain, TerrainCircle):
        return _point_in_circle(blob.position, terrain.center, terrain.radius_inches)
    return False


# ---------------------------------------------------------------------------
# Main LoS function
# ---------------------------------------------------------------------------


def check_los(
    attacker: UnitBlob,
    target: UnitBlob,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
    n_samples: int = DEFAULT_N_SAMPLES,
) -> LoSState:
    """Sprawdza LoS atakującego do celu (pkt 6 + ADR-0043).

    Returns 3-state: WIDZI / OSLONA / NIE_WIDZI. Sampling N=16 punktów na
    obwodzie celu, każdy weryfikowany przeciw `Blokujacy`/`Zaslaniajacy`
    terenom. Zasłaniający z wyjątkiem dla atakującego/celu wewnątrz (pkt
    4.c.iii).
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be ≥ 1, got {n_samples}")

    # Degenerate: sam blob lub overlap
    dist_centers = _distance(attacker.position, target.position)
    if dist_centers == 0:
        return LoSState.WIDZI  # same position; engine higher-level zwykle wyklucza

    # Filtruj teren który blokuje LoS dla tej pary (z Zasłaniający exception)
    blocking: list[TerrainCircle | TerrainLine] = []
    for t in terrain:
        features = set(t.features)
        if FEATURE_BLOKUJACY in features:
            blocking.append(t)
            continue
        if FEATURE_ZASLANIAJACY in features:
            # Pkt 4.c.iii: blokuje LoS z wyjątkiem do/od oddziałów wewnątrz.
            if _blob_inside_terrain(attacker, t) or _blob_inside_terrain(target, t):
                continue  # ten teren nie blokuje dla tej pary
            blocking.append(t)

    # Wyznacz attacker edge point (na obwodzie ku celowi).
    # Per pkt 6.a: atakujący wybiera model — w MVP używamy reprezentatywnego edge point.
    dx = target.position.x - attacker.position.x
    dy = target.position.y - attacker.position.y
    nx = dx / dist_centers
    ny = dy / dist_centers
    attacker_edge = Position(
        attacker.position.x + nx * attacker.radius_inches,
        attacker.position.y + ny * attacker.radius_inches,
    )

    # Sample N=16 punktów równomiernie na obwodzie celu
    target_points: list[Position] = []
    for i in range(n_samples):
        angle = 2.0 * math.pi * i / n_samples
        target_points.append(
            Position(
                target.position.x + target.radius_inches * math.cos(angle),
                target.position.y + target.radius_inches * math.sin(angle),
            )
        )

    # Sprawdź każdy target point przeciw blokującemu terenowi
    visible_count = 0
    for tp in target_points:
        blocked = False
        for t in blocking:
            if isinstance(t, TerrainCircle):
                if _segment_intersects_circle(
                    attacker_edge, tp, t.center, t.radius_inches
                ):
                    blocked = True
                    break
            elif isinstance(t, TerrainLine):
                if _segments_intersect(attacker_edge, tp, t.start, t.end):
                    blocked = True
                    break
        if not blocked:
            visible_count += 1

    # Klasyfikacja per pkt 6.a.i + 6.a.ii
    if visible_count == n_samples:
        return LoSState.WIDZI
    if visible_count == 0:
        return LoSState.NIE_WIDZI
    return LoSState.OSLONA
