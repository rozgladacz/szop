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

from app.services.engine.geometry import (
    UNIT_CIRCLE_16,
    distance,
    point_in_circle,
    segment_intersects_circle,
    segments_intersect,
)
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
# Local helpers (geometry primitives → app.services.engine.geometry)
# ---------------------------------------------------------------------------


def _blob_inside_terrain(
    blob: UnitBlob, terrain: TerrainCircle | TerrainLine
) -> bool:
    """Czy blob (centrum) jest "wewnątrz" terenu.

    Per `SZOP_Rozjemca.md pkt 4.a`: oddział wewnątrz gdy większość modeli w
    większości znajduje się w obrębie. W Pareto MVP (oddział = koło): proxy
    przez centrum blob. Dla `TerrainLine` zwraca False (line nie ma "wnętrza").
    """
    if isinstance(terrain, TerrainCircle):
        return point_in_circle(blob.position, terrain.center, terrain.radius_inches)
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
    dist_centers = distance(attacker.position, target.position)
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

    # Sample N punktów równomiernie na obwodzie celu. N=16 (default) używa
    # precomputed `UNIT_CIRCLE_16` z `geometry.py` (perf — bez 16× math.cos/sin).
    target_points: list[Position] = []
    if n_samples == DEFAULT_N_SAMPLES:
        for cos_a, sin_a in UNIT_CIRCLE_16:
            target_points.append(
                Position(
                    target.position.x + target.radius_inches * cos_a,
                    target.position.y + target.radius_inches * sin_a,
                )
            )
    else:
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
                if segment_intersects_circle(
                    attacker_edge, tp, t.center, t.radius_inches
                ):
                    blocked = True
                    break
            elif isinstance(t, TerrainLine):
                if segments_intersect(attacker_edge, tp, t.start, t.end):
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
