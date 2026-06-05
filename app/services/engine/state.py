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
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from app.services.rulesets.loader import load_b_mvp_exclusions, load_ruleset
from app.services.rulesets.models import BMvpConfig

if TYPE_CHECKING:  # avoid circular import; events.py is "leaf" relative to state.py
    from app.services.engine.events import BattleEvent


class Lokalizacja(str, Enum):
    """Lokalizacja oddziału na planszy (pkt 26 SZOP_Rozjemca.md, R5.a 2026-06).

    ZAPLECZE — rezerwy przed rozstawieniem (Zasadzka/Rezerwa).
    FRONT    — aktywny oddział na planszy (default po rozstawieniu).
    WYCOFANY — wszyscy modele pokonani (models_alive == 0); może Odzyskać.
    ELIMINOWANY — pokonany bronią Zguba; nie może Odzyskać (pkt 27.c).
    """

    ZAPLECZE = "zaplecze"
    FRONT = "front"
    WYCOFANY = "wycofany"
    ELIMINOWANY = "eliminowany"


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
class WeaponProfile:
    """Profil broni używany w combat resolution.

    Przed B3.9.e ten dataclass żył w `combat.py`. Migracja do `state.py` (B3.9.e
    / ADR-0047) była konieczna żeby `UnitBlob.melee_weapons`/`ranged_weapons`
    mogły go używać bez import cycle (`combat.py` importuje z `state.py`).
    `combat.py` re-eksportuje dla wstecznej kompatybilności call sites.

    `slug` ≈ entry w `app/rulesets/v1/abilities.yaml` (type=weapon).
    `range_inches=0` = melee. `attacks` = liczba ataków per model.
    `attack_quality_override` = `None` (użyj `attacker.quality`) lub stała
    wartość (np. Niezawodny id 63 → 2).
    `ap` = pole główne (AP modifier; weapon_abilities tuple jest dla dalszych).
    `weapon_abilities` = lista sluggów ze zdolnościami broni (Brutalny,
    Precyzyjny etc. dla MVP; przyszłe Furia/Impet/Podwójny).
    """

    slug: str
    name: str
    range_inches: int
    attacks: int
    ap: int = 0
    attack_quality_override: int | None = None
    weapon_abilities: tuple[str, ...] = ()


# CR-fix E (post-B3.9.f code review): sentinel weapon dla units bez melee
# inventory. Pre-fix `combat.resolve_charge_attack` fallowal do broni
# atakującego — silently reintroducing bug #7. Teraz fallback używa UNARMED
# (1 atak, AP 0, brak abilities) — explicit "unarmed defender" semantyka
# zamiast cichego użycia broni przeciwnika.
UNARMED_WEAPON: "WeaponProfile" = WeaponProfile(
    slug="unarmed",
    name="Unarmed",
    range_inches=0,
    attacks=1,
    ap=0,
    weapon_abilities=(),
)


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

    `melee_weapons` / `ranged_weapons` (B3.9.e / ADR-0047) — inventory broni
    oddziału. Partycja po `range_inches`: > 0 ranged, == 0 melee. Pre-B3.9.e
    `resolve_charge_attack` używał broni atakującego do kontrataku defendera —
    bug #7. Po B3.9.e defender używa `defender.melee_weapons[0]` (z fallback
    do attacker.weapon gdy inventory pusty — backward compat dla test fixtures
    konstruujących UnitBlob bez weapons).
    """

    id: int
    owner_player: int  # 0 lub 1
    position: Position
    radius_inches: float
    models_alive: int
    toughness_per_model: int
    quality: int = 4  # jakość modelu (threshold for hit per pkt 17.a); default Q4
    defense: int = 5  # obrona modelu (threshold for defense per pkt 17.b); default D5
    is_hero_unit: bool = False  # czy w oddziale jest model z zdolnością Bohater (id 2)
    passives: tuple[str, ...] = ()
    status_flags: tuple[str, ...] = ()
    wounds_received: int = 0
    wounds_pending: int = 0
    wounds_pending_precise: int = 0
    melee_balance: int = 0
    melee_weapons: tuple[WeaponProfile, ...] = ()  # B3.9.e / ADR-0047
    ranged_weapons: tuple[WeaponProfile, ...] = ()  # B3.9.e / ADR-0047
    location: Lokalizacja = Lokalizacja.FRONT  # R5.a 2026-06 (pkt 26)


@dataclass(frozen=True, slots=True)
class Objective:
    """Cel misji (pkt 5).

    `controller` ∈ {None, 0, 1}: None = niezajęty; 0/1 = owner_player kontrolujący.
    Per pkt 5.d: zajęty gdy w 3″ od celu tylko oddziały tego gracza. Pozostaje
    zajęty między rundami (pkt 5.d ostatnie zdanie).
    """

    id: int
    position: Position
    controller: int | None = None


@dataclass(frozen=True, slots=True)
class BattleState:
    """Immutable snapshot stanu bitwy.

    Rekonstrukcja przez `apply_events(initial, events)` per ADR-0010.
    `round=0` to runda rozstawienia (pkt 9), 1-4 to rundy walki (pkt 5.f).

    `initial_toughness_snapshot` (ADR-0045 / B3.9.c) — frozen mapa
    `unit_id → initial_toughness_total` ustalona w `build_initial_state` raz
    i NIGDY nie modyfikowana w trakcie rozgrywki. Używana przez `_regroup_test`
    dla pkt 20.b (test gdy current toughness ≤ ½ INITIAL toughness). Przed
    B3.9.c regroup używał `models_alive * toughness + wounds_received` jako
    proxy — bug #3 (proxy traci dokładność przy modelach pokonanych w
    poprzednich aktywacjach: `wounds_received` jest resetowany przy
    pokonaniu modelu, więc proxy underestymuje initial).

    Reprezentacja jako `tuple[tuple[int, int], ...]` (a nie `dict`) zachowuje
    frozen-dataclass purity — żaden kod nie może zmutować dict-a przez
    referencję. Lookup przez `initial_toughness_for(state, unit_id)` helper.
    """

    round: int
    active_player: int  # 0 lub 1
    activations_remaining: tuple[int, int]  # per player
    blobs: tuple[UnitBlob, ...]
    terrain: tuple[TerrainCircle | TerrainLine, ...]
    objectives: tuple[Objective, ...] = ()  # 5 celów per pkt 5.a
    pending_effects: tuple[str, ...] = ()  # placeholder dla B3.5
    pending_interrupts: tuple[str, ...] = ()  # placeholder dla B3.5
    score: tuple[int, int] = (0, 0)  # zajęte cele per player (pkt 5.f)
    is_game_over: bool = False  # True po round_end_phase rundy 4 (pkt 5.f)
    initial_toughness_snapshot: tuple[tuple[int, int], ...] = ()  # ADR-0045


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

            # B3.9.e (ADR-0047) — partition `unit["weapons"]` po `range_inches`.
            # `weapons` może być listą `WeaponProfile` lub listą dict-ów
            # (`{"slug","name","range_inches","attacks","ap","weapon_abilities"}`).
            # Backward compat: gdy brak `weapons`, oba tuples zostają puste.
            melee_weapons: list[WeaponProfile] = []
            ranged_weapons: list[WeaponProfile] = []
            for w in unit.get("weapons", ()):
                if isinstance(w, WeaponProfile):
                    weapon = w
                else:
                    weapon = WeaponProfile(
                        slug=str(w["slug"]),
                        name=str(w.get("name", w["slug"])),
                        range_inches=int(w["range_inches"]),
                        attacks=int(w.get("attacks", 1)),
                        ap=int(w.get("ap", 0)),
                        attack_quality_override=w.get("attack_quality_override"),
                        weapon_abilities=tuple(w.get("weapon_abilities", ())),
                    )
                if weapon.range_inches > 0:
                    ranged_weapons.append(weapon)
                else:
                    melee_weapons.append(weapon)

            # R5.a (2026-06): ZAPLECZE dla Zasadzka/Rezerwa (pkt 26 — off-board reserves).
            initial_location = (
                Lokalizacja.ZAPLECZE
                if ("zasadzka" in unit_slugs or "rezerwa" in unit_slugs)
                else Lokalizacja.FRONT
            )
            blobs.append(
                UnitBlob(
                    id=int(unit["id"]),
                    owner_player=owner,
                    position=Position(float(pos_raw[0]), float(pos_raw[1])),
                    radius_inches=radius,
                    models_alive=models,
                    toughness_per_model=tou,
                    quality=int(unit.get("quality", 4)),
                    defense=int(unit.get("defense", 5)),
                    is_hero_unit=is_hero,
                    passives=unit_slugs,
                    melee_weapons=tuple(melee_weapons),
                    ranged_weapons=tuple(ranged_weapons),
                    location=initial_location,
                )
            )

    # B3.9.c (ADR-0045): frozen mapa initial toughness per unit_id. Liczone z
    # `models_alive * toughness_per_model` (= sum_models * toughness w MVP, bez
    # halving Bohatera — to dotyczy radius area, nie toughness pool per
    # `SZOP_Rozjemca.md pkt 17.d–18`).
    snapshot = tuple(
        (b.id, b.models_alive * b.toughness_per_model) for b in blobs
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
        initial_toughness_snapshot=snapshot,
    )


def initial_toughness_for(state: BattleState, unit_id: int) -> int:
    """Zwraca initial_toughness_total dla `unit_id` z `state.initial_toughness_snapshot`.

    Zwraca 0 gdy `unit_id` brak w snapshot (state zbudowany pomijając
    `build_initial_state` — np. test fixtures). Caller (`_regroup_test`)
    używa fallback gdy 0.
    """
    for uid, tough in state.initial_toughness_snapshot:
        if uid == unit_id:
            return tough
    return 0


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
