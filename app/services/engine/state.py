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


class ActivationPhase(str, Enum):
    """Durable structural phase of an activation protocol v2 checkpoint."""

    BEFORE_ACTION = "BEFORE_ACTION"
    ACTION_READY = "ACTION_READY"
    AWAITING_CONTINUATION = "AWAITING_CONTINUATION"
    AWAITING_FINALIZATION = "AWAITING_FINALIZATION"


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
    - `damage_balance` — bilans obrażeń (zadane − otrzymane); akumuluje wręcz
      (pkt 20.c), nazwa uogólniona pod przyszłe zdolności (H3, 2026-06-14)

    `wounds_eliminating` (R4.Zguba / H5 RESOLVED 2026-06-07) — DODATKOWY licznik
    (NIE trzecia pula alokacji per pkt 17.d). Broń ze zdolnością `Zguba` (pkt 26.d/
    27.a) zadaje rany normalnie do precise/regular ORAZ zwiększa ten licznik o tę
    samą liczbę. Alokacja precise/regular zmniejsza licznik (o `toughness` per
    pokonany model, floor 0). Model pokonany gdy licznik wciąż dodatni →
    ELIMINOWANY (`location`, nie wraca przez Leczenie); inaczej WYCOFANY.
    Invariant: `0 <= wounds_eliminating <= wounds_received` w stabilnym stanie;
    wipe (`models_alive == 0`) zeruje oba.

    `passives` zawiera sluggi z `app/rulesets/v1/abilities.yaml`. `status_flags`
    z pkt 22 (Aktywowany, Wyczerpany, Przyszpilony, Przygotowany).

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
    # Czasowe override'y pasywów (Rozkaz/Klątwa/Oznaczenie id 50/45/49, pkt 12 +
    # 11.b.i) — krotka `(slug, granted)`: granted=True nadaje X, granted=False
    # odbiera/tłumi X. Aktywne **do końca aktywacji** (czyszczone w pkt 11.b.vi).
    # Efektywny zbiór pasywów liczy `effective_passives(blob)`; agregatory
    # `effects.py` + `interrupts`/`combat` czytają effective, nie surowe `passives`.
    ability_overrides: tuple[tuple[str, bool], ...] = ()
    status_flags: tuple[str, ...] = ()
    wounds_received: int = 0
    wounds_pending: int = 0
    wounds_pending_precise: int = 0
    wounds_eliminating: int = 0  # R4.Zguba (pkt 26.d/27.a): licznik ran broni Zguba
    damage_balance: int = 0  # bilans obrażeń zadane−otrzymane (pkt 20.c; H3 rename z melee_balance)
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


def _require_strict_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_player(value: object, field_name: str) -> int:
    player = _require_strict_int(value, field_name)
    if player not in (0, 1):
        raise ValueError(f"{field_name} must be 0 or 1")
    return player


@dataclass(frozen=True, slots=True)
class InterruptWindowState:
    """Durable, open interrupt window in activation protocol v2."""

    ordinal: int
    version: int
    priority_player: int
    passed_players: tuple[int, ...]
    interrupt_count: int

    def __post_init__(self) -> None:
        ordinal = _require_strict_int(self.ordinal, "ordinal")
        if ordinal not in (1, 2):
            raise ValueError("ordinal must be 1 or 2")
        version = _require_strict_int(self.version, "version")
        if version < 1:
            raise ValueError("window version must be >= 1")
        priority = _require_player(self.priority_player, "priority_player")
        if type(self.passed_players) is not tuple:
            raise TypeError("passed_players must be a tuple")
        passed: list[int] = []
        for player in self.passed_players:
            passed.append(_require_player(player, "passed_players item"))
        if len(passed) != len(set(passed)):
            raise ValueError("passed_players must not contain duplicates")
        # A second pass closes the window atomically, so an open checkpoint can
        # contain at most the first pass.
        if len(passed) > 1:
            raise ValueError("an open window can contain at most one pass")
        if passed and priority == passed[0]:
            raise ValueError("priority must move after the first pass")
        interrupt_count = _require_strict_int(
            self.interrupt_count,
            "interrupt_count",
        )
        if not 0 <= interrupt_count <= 64:
            raise ValueError("interrupt_count must be between 0 and 64")
        if version != 1 + interrupt_count + len(passed):
            raise ValueError(
                "window version must equal open + accepted interrupts/passes"
            )


@dataclass(frozen=True, slots=True)
class ActivationState:
    """Durable activation head for activation protocol v2."""

    activation_id: int
    version: int
    selected_unit_id: int
    controlling_player: int
    initiative_player: int
    action_count: int
    action_types: tuple[str, ...]
    phase: ActivationPhase
    window: InterruptWindowState | None

    def __post_init__(self) -> None:
        for field_name in ("activation_id", "version", "selected_unit_id"):
            value = _require_strict_int(getattr(self, field_name), field_name)
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        _require_player(self.controlling_player, "controlling_player")
        initiative_player = _require_player(
            self.initiative_player,
            "initiative_player",
        )
        action_count = _require_strict_int(self.action_count, "action_count")
        if not 0 <= action_count <= 2:
            raise ValueError("action_count must be between 0 and 2")
        if type(self.action_types) is not tuple or any(
            type(action_type) is not str for action_type in self.action_types
        ):
            raise TypeError("action_types must be a tuple of strings")
        if len(self.action_types) != action_count:
            raise ValueError("action_count must match action_types length")
        # Local import avoids the state -> actions -> state import cycle while
        # still reusing the canonical public Action codec vocabulary.
        from app.services.engine.actions import ACTION_TYPE_DISCRIMINATORS

        if any(
            action_type not in ACTION_TYPE_DISCRIMINATORS
            for action_type in self.action_types
        ):
            raise ValueError("action_types contains an unknown Action discriminator")
        if type(self.phase) is not ActivationPhase:
            raise TypeError("phase must be an ActivationPhase")
        if self.window is not None and type(self.window) is not InterruptWindowState:
            raise TypeError("window must be an InterruptWindowState or None")

        if self.phase is ActivationPhase.BEFORE_ACTION:
            if self.window is None:
                raise ValueError("BEFORE_ACTION requires an open window")
            if self.window.ordinal != action_count + 1:
                raise ValueError(
                    "BEFORE_ACTION ordinal must follow the committed action count"
                )
            expected_passes = (
                ()
                if self.window.priority_player == initiative_player
                else (initiative_player,)
            )
            if self.window.passed_players != expected_passes:
                raise ValueError(
                    "window priority/passes must start from activation initiative"
                )
            if self.window.ordinal == 1 and self.version != self.window.version:
                raise ValueError(
                    "first-window activation and window versions must match"
                )
            if (
                self.window.ordinal == 2
                and self.version < self.window.version + 4
            ):
                raise ValueError("second-window activation version is unreachable")
            return

        if self.window is not None:
            raise ValueError("only BEFORE_ACTION can contain a window")
        if self.phase is ActivationPhase.ACTION_READY:
            minimum_version = 3 if action_count == 0 else 7
            if action_count not in (0, 1) or self.version < minimum_version:
                raise ValueError("ACTION_READY checkpoint is unreachable")
        elif self.phase is ActivationPhase.AWAITING_CONTINUATION:
            if action_count != 1 or self.version < 4:
                raise ValueError("AWAITING_CONTINUATION checkpoint is unreachable")
        elif self.phase is ActivationPhase.AWAITING_FINALIZATION:
            if action_count != 2 or self.version < 8:
                raise ValueError("AWAITING_FINALIZATION checkpoint is unreachable")


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
    # Limit „raz na rundę" przerwań Rozkaz/Klątwa/Oznaczenie (pkt 12) — krotka
    # `(source_unit_id, slug)` użytych w tej rundzie. Reset w round_end_phase +
    # RoundEnded reducer. faza-b-order-interrupts 2026-06-09.
    used_interrupts_this_round: tuple[tuple[int, str], ...] = ()
    # ``None`` means a legacy v1 checkpoint has no durable initiative proof.
    # It must never be inferred from ``active_player``.
    initiative_player: int | None = None
    activation: ActivationState | None = None

    def __post_init__(self) -> None:
        if self.initiative_player is not None:
            _require_player(self.initiative_player, "initiative_player")
        if self.activation is not None:
            if type(self.activation) is not ActivationState:
                raise TypeError("activation must be an ActivationState or None")
            if self.initiative_player is None:
                raise ValueError("activation requires a durable initiative_player")
            if self.activation.initiative_player != self.initiative_player:
                raise ValueError("activation initiative must match BattleState")
            if self.activation.controlling_player != self.active_player:
                raise ValueError("activation controller must match active_player")


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


def effective_passives(blob: UnitBlob) -> tuple[str, ...]:
    """Efektywny zbiór pasywów oddziału z uwzględnieniem czasowych override'ów.

    Rozkaz(X)/Klątwa(X)/Oznaczenie(X) (id 50/45/49) nadają (`granted=True`) lub
    odbierają (`granted=False`) pasywkę X do końca aktywacji. `effective_passives`
    łączy bazowe `blob.passives` z override'ami, **zachowując kolejność**
    rejestracji (agregatory `effects.py` iterują w kolejności — determinizm
    replay): najpierw bazowe pasywy (z usunięciem suppressed), potem nadane
    nieobecne w bazie.

    Override'y aplikowane w kolejności (ostatni wygrywa): grant dodaje X (jeśli
    nieobecny), suppress usuwa X (jeśli obecny). Fast-path: brak override'ów →
    zwraca `blob.passives` (identity, zero alokacji).
    """
    if not blob.ability_overrides:
        return blob.passives
    result = list(blob.passives)
    for slug, granted in blob.ability_overrides:
        if granted:
            if slug not in result:
                result.append(slug)
        elif slug in result:
            result.remove(slug)
    return tuple(result)


def effective_move_inches(blob: UnitBlob, ruleset_version: str = "v1") -> float:
    """Maksymalny dystans Ruchu oddziału w calach (pkt 15.a + zdolność 33).

    Budżet bazowy = `tables.b_mvp.move_inches` (pkt 15.a „każdy model porusza się
    o maksymalnie 6″"; ADR-0008). Modyfikatory zdolności 33 Szybki/Wolny
    (`SZOP_Zdolnosci.md`: „maksymalny dystans ruchu modyfikowany o +2″ (Szybki)
    lub −2″ (Wolny)"; B0 decyzja #3 — stosowane w runtime): `szybki` +2″,
    `wolny` −2″. Czytane z `effective_passives(blob)` → honoruje czasowe
    override'y Rozkaz/Klątwa/Oznaczenie (pkt 11.b.i/12). Clamp ≥ 0.

    **POZA zakresem (E4, roadmap „Ruch nie egzekwuje Trudny/Niedostępny"):**
    pkt 4.c.iv Trudny (½ ruchu przez teren) — budżet NIE zależy od terenu na
    trasie (brak parametru `terrain`); pkt 4.c.i Niedostępny — brak path-blocking.
    """
    config = load_ruleset(ruleset_version).tables.b_mvp
    if config is None:
        raise RuntimeError("b_mvp config missing in tables.yaml; cannot compute move")
    move = float(config.move_inches)
    passives = effective_passives(blob)
    if "szybki" in passives:
        move += 2.0
    if "wolny" in passives:
        move -= 2.0
    return max(0.0, move)


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
