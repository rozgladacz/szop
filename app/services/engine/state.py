"""B3.0 — Battle state runtime substrate (ADR-0008 / 0010 / 0014).

Pure functional core:
- `Position`, `TerrainCircle`, `TerrainLine` — geometryczne podstawki.
- `UnitBlob` — oddział reprezentowany jako koło (Pareto MVP); 4 kategorie ran
  per ADR-0014.
- `BattleState` — immutable snapshot stanu bitwy.
- `compute_radius_inches(toughness_sum, config)` — wzór ADR-0008.
- `build_initial_state(rosters, terrain, ruleset_version)` — fabryka; raise
  `UnsupportedAbilityError` gdy roster zawiera zdolność z `b_mvp_exclusions.yaml`.
- `apply_events(initial, events)` — pure rebuilder (replay); reducers
  rejestrowane przez `@register_reducer(event_type_name)` w B3.1+.

Brak I/O / DB / mutacji. Wszystkie dataclasses są `frozen=True` + `slots=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from app.services.rulesets.loader import load_b_mvp_exclusions, load_ruleset
from app.services.rulesets.models import BMvpConfig

if TYPE_CHECKING:  # avoid circular import; events.py is "leaf" relative to state.py
    from app.services.engine.events import BattleEvent


class UnsupportedAbilityError(Exception):
    """Raised gdy roster ma zdolność wykluczoną w B MVP (per ADR-0008).

    `b_mvp_exclusions.yaml` definiuje 6 wykluczeń. `build_initial_state()`
    walidauje każdy oddział i raise przy pierwszym napotkaniu.
    """

    def __init__(self, slug: str, reason: str) -> None:
        self.slug = slug
        self.reason = reason
        super().__init__(f"Ability '{slug}' is excluded in B MVP: {reason}")


@dataclass(frozen=True, slots=True)
class Position:
    """2D pozycja w calach. Origin = lewy-dolny róg pola bitwy."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class TerrainCircle:
    """Element terenu jako koło. `features` per `SZOP_Rozjemca.md pkt 4.c`."""

    center: Position
    radius_inches: float
    features: tuple[str, ...]  # ∈ {Niedostepny, Blokujacy, Zaslaniajacy, Trudny, Niebezpieczny, Obronny}


@dataclass(frozen=True, slots=True)
class TerrainLine:
    """Element terenu jako odcinek (np. mur)."""

    start: Position
    end: Position
    features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnitBlob:
    """Oddział = koło (Pareto MVP, ADR-0008).

    Cztery kategorie ran per ADR-0014 (`SZOP_Rozjemca.md pkt 17.d–20.c`):
    - `wounds_received` — znaczniki ran na oddziale (pkt 18.c)
    - `wounds_pending` — pula nadchodzących, obrońca alokuje (pkt 17.d.ii)
    - `wounds_pending_precise` — pula od `Precyzyjny`, atakujący alokuje (pkt 17.d.i + 68)
    - `melee_balance` — bilans wręcz (zadane − otrzymane, pkt 20.c)

    `passives` zawiera sluggi z `app/rulesets/v1/abilities.yaml`. `status_flags`
    z pkt 22 (Aktywowany, Wyczerpany, Przyszpilony, Ufortyfikowany).
    """

    id: int
    owner_player: int  # 0 lub 1
    position: Position
    radius_inches: float
    models_alive: int
    toughness_per_model: int
    is_hero_unit: bool = False  # czy w oddziale jest model z zdolnością Bohater (id 2)
    passives: tuple[str, ...] = ()
    status_flags: tuple[str, ...] = ()
    wounds_received: int = 0
    wounds_pending: int = 0
    wounds_pending_precise: int = 0
    melee_balance: int = 0


@dataclass(frozen=True, slots=True)
class BattleState:
    """Immutable snapshot stanu bitwy.

    Rekonstrukcja przez `apply_events(initial, events)` per ADR-0010.
    `round=0` to runda rozstawienia (pkt 9), 1-4 to rundy walki (pkt 5.f).
    """

    round: int
    active_player: int  # 0 lub 1
    activations_remaining: tuple[int, int]  # per player
    blobs: tuple[UnitBlob, ...]
    terrain: tuple[TerrainCircle | TerrainLine, ...]
    pending_effects: tuple[str, ...] = ()  # placeholder dla B3.5
    pending_interrupts: tuple[str, ...] = ()  # placeholder dla B3.5
    score: tuple[int, int] = (0, 0)  # zajęte cele per player (pkt 5.f)


def compute_radius_inches(
    toughness_sum: float,
    config: BMvpConfig | None = None,
) -> float:
    """Pareto MVP radius (ADR-0008): r = sqrt(area / pi).

    `toughness_sum` to suma toughness wszystkich modeli oddziału (z Bohaterem
    liczonym jako `toughness/2`). Default config: z `load_ruleset().tables.b_mvp`.
    """
    if config is None:
        ruleset = load_ruleset()
        config = ruleset.tables.b_mvp
        if config is None:
            raise RuntimeError(
                "b_mvp config missing in tables.yaml; cannot compute radius"
            )
    area = toughness_sum * config.base_area_inches_sq_per_toughness
    return (area / config.pi_approx) ** 0.5


def build_initial_state(
    rosters: Iterable[Mapping[str, Any]],
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
    ruleset_version: str = "v1",
) -> BattleState:
    """Buduje `BattleState` z 2 rosterów; raise dla wykluczeń (ADR-0008).

    `rosters`: iterable z 2 mapping-ów per gracz:
      ``{"owner_player": int, "units": [{"id", "position": (x,y), "models", "toughness", "passives": [...]}, ...]}``

    Walidacja per ADR-0008: dla każdej zdolności w `unit["passives"]` sprawdza
    czy jest na liście `b_mvp_exclusions.yaml`; raise `UnsupportedAbilityError`
    przy pierwszym napotkaniu.

    Bohater (slug `bohater`) w `passives` skutkuje `is_hero_unit=True` i
    `radius` liczonym z `toughness_sum = models * toughness / 2` (per pkt id 2).
    """
    exclusions = load_b_mvp_exclusions(ruleset_version)
    excluded_slugs = exclusions.slugs()
    config = load_ruleset(ruleset_version).tables.b_mvp
    if config is None:
        raise RuntimeError("b_mvp config missing in tables.yaml")

    blobs: list[UnitBlob] = []
    for roster in rosters:
        owner = int(roster["owner_player"])
        for unit in roster.get("units", []):
            unit_slugs = tuple(unit.get("passives", ()))
            for slug in unit_slugs:
                if slug in excluded_slugs:
                    reason = next(
                        (
                            e.reason
                            for e in exclusions.excluded_abilities
                            if e.slug == slug
                        ),
                        "(no reason)",
                    )
                    raise UnsupportedAbilityError(slug, reason)
            models = int(unit["models"])
            tou = int(unit["toughness"])
            is_hero = "bohater" in unit_slugs
            tou_sum = models * tou / (2 if is_hero else 1)
            radius = compute_radius_inches(tou_sum, config)
            pos_raw = unit["position"]
            blobs.append(
                UnitBlob(
                    id=int(unit["id"]),
                    owner_player=owner,
                    position=Position(float(pos_raw[0]), float(pos_raw[1])),
                    radius_inches=radius,
                    models_alive=models,
                    toughness_per_model=tou,
                    is_hero_unit=is_hero,
                    passives=unit_slugs,
                )
            )

    return BattleState(
        round=0,
        active_player=0,
        activations_remaining=(
            sum(1 for b in blobs if b.owner_player == 0),
            sum(1 for b in blobs if b.owner_player == 1),
        ),
        blobs=tuple(blobs),
        terrain=tuple(terrain),
    )


# ---------------------------------------------------------------------------
# Event reducer dispatch (apply_events)
# ---------------------------------------------------------------------------
# Reducers (B3.1+) rejestrują się przez `@register_reducer("MoveExecuted")`.
# Każdy reducer: `(BattleState, BattleEvent) → BattleState` (pure).

ReducerFn = Callable[["BattleState", "BattleEvent"], "BattleState"]

_EVENT_REDUCERS: dict[str, ReducerFn] = {}


def register_reducer(event_type_name: str) -> Callable[[ReducerFn], ReducerFn]:
    """Decorator — rejestruje reducer dla danego typu eventu.

    Użycie::

        @register_reducer("MoveExecuted")
        def _reduce_move(state: BattleState, event: MoveExecuted) -> BattleState:
            ...
    """

    def decorator(fn: ReducerFn) -> ReducerFn:
        if event_type_name in _EVENT_REDUCERS:
            raise RuntimeError(
                f"Reducer for {event_type_name!r} already registered"
            )
        _EVENT_REDUCERS[event_type_name] = fn
        return fn

    return decorator


def apply_events(
    initial: BattleState,
    events: Iterable["BattleEvent"],
) -> BattleState:
    """Pure rebuilder — replay eventów na initial state (ADR-0010).

    Brak reducera dla event type → `NotImplementedError` (defensywne; każdy
    event type ma reducer po B3.7).
    """
    state = initial
    for event in events:
        event_type = type(event).__name__
        reducer = _EVENT_REDUCERS.get(event_type)
        if reducer is None:
            raise NotImplementedError(
                f"No reducer for event type {event_type!r}; "
                f"register via @register_reducer"
            )
        state = reducer(state, event)
    return state
