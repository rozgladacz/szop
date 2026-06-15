"""D5 — strefa rozstawienia + proste strategie pozycjonowania botów.

Strumień D5 (roadmap `docs/roadmap.md#strumień-d`). Dziś `simulate_from_rosters`
woła `deployment_round` z pustą listą — oddziały startują na pozycjach z roster.
D5 daje botom (`Player.choose_deployment`) wpływ na pozycje startowe.

`DeploymentZone` modeluje **strefę rozstawienia** (`SZOP_Rozjemca.md pkt 24`:
prostokąt wzdłuż dłuższej krawędzi, domyślnie 12″ od środka — pkt 24.a). Trzymana
jako parametr runnera (NIE pole `BattleState`) — spójnie z wzorcem terrain/
objectives/deployment przekazywanych do `simulate_from_rosters`. Zero zmian w
rdzeniu silnika (`engine/*`), warstwa-liść agentów.

**Legalność (pkt 13.a, uproszczenie MVP):** całe koło oddziału (`position ± radius`)
mieści się w prostokącie strefy. Świadomie pominięte na tym etapie: cecha
Niedostępny (pkt 4.c.i) oraz reguła >1″ od modeli innych oddziałów (pkt 13.a) —
należą do E4 (kolizje jednostka–jednostka, roadmap).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from app.services.engine.state import Position


@dataclass(frozen=True, slots=True)
class DeploymentZone:
    """Prostokątna strefa rozstawienia gracza (pkt 24, axis-aligned).

    Współrzędne w calach, origin = lewy-dolny róg pola (jak `Position`).
    Niezmienne: `x_min <= x_max`, `y_min <= y_max`.
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains_circle(self, position: Position, radius: float) -> bool:
        """Czy całe koło (`position`, `radius`) mieści się w strefie (pkt 13.a MVP).

        Każdy punkt obwodu koła musi leżeć w prostokącie → środek odsunięty od
        każdej krawędzi o co najmniej `radius`. Tolerancja `1e-9` na błąd float.
        """
        eps = 1e-9
        return (
            position.x - radius >= self.x_min - eps
            and position.x + radius <= self.x_max + eps
            and position.y - radius >= self.y_min - eps
            and position.y + radius <= self.y_max + eps
        )


def _usable_bounds(
    zone: DeploymentZone, radius: float
) -> tuple[float, float, float, float]:
    """Prostokąt środków, dla których koło `radius` mieści się w strefie.

    Gdy strefa jest węższa niż `2*radius` w którejś osi (koło się nie mieści),
    zwęża się do środka tej osi (lo == hi) — strategie degradują do umieszczenia
    w środku zamiast rzucać wyjątkiem (walidację robi `DeploymentZone.contains_circle`).
    """

    def axis(lo: float, hi: float) -> tuple[float, float]:
        u_lo, u_hi = lo + radius, hi - radius
        if u_lo > u_hi:
            mid = (lo + hi) / 2.0
            return mid, mid
        return u_lo, u_hi

    x_lo, x_hi = axis(zone.x_min, zone.x_max)
    y_lo, y_hi = axis(zone.y_min, zone.y_max)
    return x_lo, y_lo, x_hi, y_hi


def _linspace(lo: float, hi: float, n: int) -> list[float]:
    """`n` równo rozłożonych wartości w [lo, hi]. n==1 → środek."""
    if n <= 1:
        return [(lo + hi) / 2.0]
    step = (hi - lo) / (n - 1)
    return [lo + i * step for i in range(n)]


def grid_positions(
    zone: DeploymentZone, count: int, radius: float
) -> list[Position]:
    """Deterministyczny równomierny grid `count` pozycji w strefie.

    Każde koło (`radius`) mieści się w strefie (`_usable_bounds`). Układ
    row-major: `cols = ceil(sqrt(count))`, `rows = ceil(count/cols)`; zwraca
    pierwsze `count` punktów. Pusty wynik dla `count <= 0`.
    """
    if count <= 0:
        return []

    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    x_lo, y_lo, x_hi, y_hi = _usable_bounds(zone, radius)
    xs = _linspace(x_lo, x_hi, cols)
    ys = _linspace(y_lo, y_hi, rows)

    positions: list[Position] = []
    for r in range(rows):
        for c in range(cols):
            if len(positions) >= count:
                break
            positions.append(Position(xs[c], ys[r]))
    return positions


def random_position_in_zone(
    rng: random.Random, zone: DeploymentZone, radius: float
) -> Position:
    """Losowa legalna pozycja środka w strefie (koło `radius` w środku).

    Deterministyczna per `rng` (replay-safe jak `DeterministicDice`, ADR-0012).
    """
    x_lo, y_lo, x_hi, y_hi = _usable_bounds(zone, radius)
    # uniform(a, a) == a — degenerat (koło szersze niż strefa) zwraca środek.
    return Position(rng.uniform(x_lo, x_hi), rng.uniform(y_lo, y_hi))
