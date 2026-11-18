"""D5 — strefa rozstawienia + proste strategie pozycjonowania botów.

Strumień D5 (roadmap `docs/roadmap.md#strumień-d`). `deployment_zones` pozwala
botom (`Player.choose_deployment`) wybrać pozycje startowe; bez tej opcji
oddziały startują na pozycjach z roster.

`DeploymentZone` modeluje **strefę rozstawienia** (`SZOP_Rozjemca.md pkt 24`:
prostokąt wzdłuż dłuższej krawędzi, domyślnie 12″ od środka — pkt 24.a). Trzymana
jako parametr runnera (NIE pole `BattleState`) — spójnie z wzorcem terrain/
objectives/deployment przekazywanych do `simulate_from_rosters`.

**Legalność D5.1 (pkt 13.a):** całe koło oddziału mieści się w strefie,
poza Niedostępnym (pkt 4.c.i) i innymi oddziałami (pkt 2.d). Styk oddziałów
jest dozwolony (pkt 15.c). Runner i strategie reużywają walidator D5.1;
oczekujące pozycje z rosteru nie są zajętymi miejscami.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import chain

from app.services.engine.movement import can_place_unit
from app.services.engine.pathfinding import is_finite_position
from app.services.engine.resolver import IllegalActionError
from app.services.engine.state import BattleState, Lokalizacja, Position, Terrain, UnitBlob


# Private callback context, never part of BattleState/checkpoints. Binding it to
# the exact working state prevents unrelated/nested selections from using it.
_SELECTION: ContextVar[tuple[BattleState, tuple[UnitBlob, ...]] | None] = ContextVar(
    "deployment_selection", default=None,
)
DEPLOYMENT_GRID_AXIS_POINTS = 33  # at most 1089 fallback positions
DEPLOYMENT_RANDOM_ATTEMPTS = 64


@contextmanager
def _deployment_selection(
    state: BattleState, occupied: Iterable[UnitBlob],
) -> Iterator[None]:
    """Supply explicit occupied positions during an unchanged Player callback."""
    token = _SELECTION.set((state, tuple(occupied)))
    try:
        yield
    finally:
        _SELECTION.reset(token)


def _deployment_occupied(state: BattleState) -> tuple[UnitBlob, ...]:
    # Direct calls outside the runner represent no prior placements, not all
    # FRONT placeholders in state. Multi-unit orchestration must bind occupancy.
    selection = _SELECTION.get()
    return selection[1] if selection is not None and selection[0] is state else ()


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


def is_deployment_position_legal(
    unit: UnitBlob,
    position: Position,
    zone: DeploymentZone | None,
    *,
    occupied: Iterable[UnitBlob],
    terrain: Iterable[Terrain],
) -> bool:
    """Validate one proposed placement without changing state (pkt 13.a).

    `occupied` contains only units already placed, from either player. Waiting
    placeholders must be excluded by the caller. Dead/off-board units and self
    are ignored, as in Maneuver. No zone is inferred when `zone` is None.
    """
    def finite(value: float) -> bool:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False

    if (
        zone is None or unit.models_alive <= 0 or unit.location is not Lokalizacja.FRONT
        or not is_finite_position(position)
        or not finite(unit.radius_inches) or unit.radius_inches <= 0
    ):
        return False
    if (
        not all(finite(value) for value in (zone.x_min, zone.y_min, zone.x_max, zone.y_max))
        or zone.x_min > zone.x_max or zone.y_min > zone.y_max
        or not zone.contains_circle(position, unit.radius_inches)
    ):
        return False
    blockers = tuple(
        other for other in occupied
        if other.id != unit.id and other.models_alive > 0
        and other.location is Lokalizacja.FRONT
    )
    if any(
        not is_finite_position(other.position)
        or not finite(other.radius_inches) or other.radius_inches <= 0
        for other in blockers
    ):
        return False
    return can_place_unit(unit, position, occupied=blockers, terrain=terrain)


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


def grid_deployment_position(
    state: BattleState, unit_id: int, zone: DeploymentZone
) -> Position:
    """Pozycja oddziału `unit_id` w **deterministycznym gridzie** własnej strefy.

    Strategia dla botów deterministycznych: wszystkie własne oddziały na Froncie
    (sort po `id`) dostają sloty z `grid_positions`. Grid liczony dla największego
    promienia własnych oddziałów (`max radius`) → każde (mniejsze) koło też mieści
    się w strefie, jeśli pozwala na to jej rozmiar. Slot per oddział = jego indeks.
    Nielegalny slot zastępuje pierwszy legalny punkt ograniczonej siatki próbek.
    """
    unit = next(b for b in state.blobs if b.id == unit_id)
    own = sorted(
        (
            b
            for b in state.blobs
            if b.owner_player == unit.owner_player
            and b.models_alive > 0
            and b.location == Lokalizacja.FRONT
        ),
        key=lambda b: b.id,
    )
    max_radius = max(b.radius_inches for b in own)
    positions = grid_positions(zone, len(own), max_radius)
    idx = next(i for i, b in enumerate(own) if b.id == unit_id)
    return _first_legal_position(
        state, unit, zone,
        chain((positions[idx],), _fallback_positions(zone, unit.radius_inches)),
    )


def _fallback_positions(zone: DeploymentZone, radius: float) -> Iterator[Position]:
    """Bounded row-major sampling; exhaustion is not proof of no free space."""
    x_lo, y_lo, x_hi, y_hi = _usable_bounds(zone, radius)
    for y in _linspace(y_lo, y_hi, DEPLOYMENT_GRID_AXIS_POINTS):
        for x in _linspace(x_lo, x_hi, DEPLOYMENT_GRID_AXIS_POINTS):
            yield Position(x, y)


def _first_legal_position(
    state: BattleState, unit: UnitBlob, zone: DeploymentZone,
    candidates: Iterable[Position],
) -> Position:
    occupied = _deployment_occupied(state)
    for position in candidates:
        if is_deployment_position_legal(
            unit, position, zone, occupied=occupied, terrain=state.terrain,
        ):
            return position
    raise IllegalActionError(
        f"Rozstawienie oddziału {unit.id}: brak legalnego kandydata "
        "w ograniczonym przeszukanym zbiorze (pkt 13.a)"
    )


def random_deployment_position(
    rng: random.Random, state: BattleState, unit_id: int, zone: DeploymentZone,
) -> Position:
    """Try bounded seeded samples, then the same deterministic fallback as Grid."""
    unit = next(b for b in state.blobs if b.id == unit_id)

    def candidates():
        for _ in range(DEPLOYMENT_RANDOM_ATTEMPTS):
            yield random_position_in_zone(rng, zone, unit.radius_inches)
        yield from _fallback_positions(zone, unit.radius_inches)

    return _first_legal_position(state, unit, zone, candidates())


class GridDeploymentMixin:
    """Mixin dla botów deterministycznych: rozstawienie na gridzie w strefie (D5).

    Domieszany przed `Player` (`class Bot(GridDeploymentMixin, Player)`) nadpisuje
    `Player.choose_deployment` deterministycznym gridem (`grid_deployment_position`).
    `RandomPlayer` świadomie NIE używa — losuje pozycję w strefie.
    """

    def choose_deployment(
        self, state: BattleState, unit_id: int, zone: DeploymentZone
    ) -> Position:
        return grid_deployment_position(state, unit_id, zone)


def random_position_in_zone(
    rng: random.Random, zone: DeploymentZone, radius: float
) -> Position:
    """Losowa legalna pozycja środka w strefie (koło `radius` w środku).

    Deterministyczna per `rng` (replay-safe jak `DeterministicDice`, ADR-0012).
    """
    x_lo, y_lo, x_hi, y_hi = _usable_bounds(zone, radius)
    # uniform(a, a) == a — degenerat (koło szersze niż strefa) zwraca środek.
    return Position(rng.uniform(x_lo, x_hi), rng.uniform(y_lo, y_hi))
