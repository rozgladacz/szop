"""D1 — Bazowy interfejs gracza heurystycznego + enumerator legalnych akcji.

Strumień D (roadmap `docs/roadmap.md#strumień-d`). Boty konsumują **publiczne
API silnika** (B3/B3.9, ADR-0011): `state` (UnitBlob/BattleState), `actions`
(polimorficzne Action), `geometry`, `los`. Bot to czysta funkcja decyzji
`choose_action(state, perspective) -> Action | None`.

Silnik celowo NIE udostępnia listy legalnych akcji — `resolver.apply` jest
jednoakcyjny (jedna akcja → ResolverResult). Dlatego `legal_actions` jest tutaj
współdzielonym rdzeniem: buduje kandydatów z `actions.Action` typów dla każdego
nie-Aktywowanego własnego oddziału. Egzekwowanie pełnej legalności (limit 2
akcji/aktywację pkt 11.b.iv, blokada Ostrzału w zwarciu pkt 14.c.iv) należy do
warstwy `phases`/`resolver`; enumerator produkuje rozsądnych kandydatów, a
nielegalne odrzuci resolver (ADR-0031, H3 w HANDOFF). Wyjątek: final-position
clearance Manewru (pkt 15.b.iii, ADR-0052) filtrujemy już tutaj, żeby boty nie
wybierały akcji, które resolver natychmiast odrzuci.

Decyzje projektowe (ADR-0031):
- **Dyskretyzacja ManeuverAction** — pozycja docelowa jest ciągła; MVP daje
  kandydatów {stój, ruch ku najbliższemu wrogowi, ruch ku najbliższemu celowi},
  clamp do `move_inches` (b_mvp=6, pkt 15.a).
- **Zasięg ruchu** = `state.effective_move_inches(blob)` — bazowy
  `tables.b_mvp.move_inches` (pkt 15.a) ± zdolność 33 Szybki/Wolny (+2/−2,
  per-oddział). Spójne z walidacją Manewru w `resolver` (ta sama funkcja).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache
from typing import TYPE_CHECKING

from app.services.engine.actions import (
    Action,
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.geometry import circle_edge_distance, distance
from app.services.engine.los import LoSState, check_los
from app.services.engine.pathfinding import ManeuverPlanner
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    Position,
    UnitBlob,
    WeaponProfile,
    effective_move_inches,
)
from app.services.engine.status import STATUS_AKTYWOWANY, STATUS_WYCZERPANY
from app.services.rulesets.loader import load_ruleset

if TYPE_CHECKING:
    from app.services.agents.deployment import DeploymentZone


@lru_cache(maxsize=4)
def _move_inches(ruleset_version: str = "v1") -> float:
    """Bazowy zasięg Ruchu z `tables.b_mvp.move_inches` (pkt 15.a; ADR-0008).

    Stała bazowa BEZ modyfikatorów Szybki/Wolny — enumeracja akcji i boty używają
    teraz per-oddziałowego `state.effective_move_inches(blob)` (pkt 15.a ± zdolność
    33). Zachowane jako referencja zasięgu bazowego (m.in. testy reachability).
    """
    config = load_ruleset(ruleset_version).tables.b_mvp
    if config is None:
        raise RuntimeError("b_mvp config missing in tables.yaml")
    return float(config.move_inches)


# ---------------------------------------------------------------------------
# Selektory stanu
# ---------------------------------------------------------------------------


def own_active_units(state: BattleState, perspective: int) -> list[UnitBlob]:
    """Własne oddziały zdolne do aktywacji w tej rundzie.

    Filtr: `owner_player == perspective`, żywe (`models_alive > 0`), nie
    Aktywowany (pkt 22.d), na Froncie (pkt 26.b — Zaplecze aktywuje się
    rozstawieniem, nie zwykłą akcją; resolver i tak odrzuci).
    """
    return [
        b
        for b in state.blobs
        if b.owner_player == perspective
        and b.models_alive > 0
        and STATUS_AKTYWOWANY not in b.status_flags
        and b.location == Lokalizacja.FRONT
    ]


def enemy_units(state: BattleState, perspective: int) -> list[UnitBlob]:
    """Żywe wrogie oddziały na Froncie (potencjalne cele)."""
    return [
        b
        for b in state.blobs
        if b.owner_player != perspective
        and b.models_alive > 0
        and b.location == Lokalizacja.FRONT
    ]


def blob_by_id(state: BattleState, unit_id: int) -> UnitBlob:
    """Oddział o danym `id`. Zakłada istnienie (KeyError-like jak `next`)."""
    return next(b for b in state.blobs if b.id == unit_id)


def _nearest(origin: Position, candidates: list[Position]) -> Position | None:
    """Najbliższy punkt z `candidates` względem `origin` (None gdy pusto)."""
    if not candidates:
        return None
    return min(candidates, key=lambda p: distance(origin, p))


def _maneuver_targets(
    state: BattleState,
    unit: UnitBlob,
    enemies: list[UnitBlob],
    objectives: tuple[Objective, ...],
    move: float,
) -> list[Position]:
    """Kandydaci na pozycję docelową Manewru (dyskretyzacja, ADR-0031 H1).

    Stój albo idź ku najbliższemu wrogowi lub celowi po legalnej trasie.
    Deduplikacja po zaokrągleniu do 0.01″ (unikamy duplikatów gdy "stój" pokrywa
    się z już-osiągniętym celem).
    """
    planner = ManeuverPlanner(state, unit, move)
    targets: list[Position] = []
    if planner.can_reach(unit.position):
        targets.append(unit.position)
    nearest_enemy = _nearest(unit.position, [e.position for e in enemies])
    nearest_obj = _nearest(unit.position, [o.position for o in objectives])
    for goal in (nearest_enemy, nearest_obj):
        if goal is not None and (target := planner.advance_toward(goal)) is not None:
            targets.append(target)

    seen: set[tuple[float, float]] = set()
    deduped: list[Position] = []
    for p in targets:
        key = (round(p.x, 2), round(p.y, 2))
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _can_shoot(
    attacker: UnitBlob,
    target: UnitBlob,
    weapon: WeaponProfile,
    terrain: tuple,
) -> bool:
    """Czy Ostrzał (pkt 14.c) jest kandydatem: zasięg broni + LoS ≠ NIE_WIDZI.

    Zasięg mierzony obwód-obwód (`circle_edge_distance`, Pareto MVP). LoS przez
    `check_los` (pkt 6): WIDZI lub OSLONA dopuszczają strzał (Osłona = kara, nie
    blokada, pkt 19); NIE_WIDZI blokuje.
    """
    gap = circle_edge_distance(
        attacker.position, attacker.radius_inches,
        target.position, target.radius_inches,
    )
    if gap > weapon.range_inches:
        return False
    return check_los(attacker, target, terrain) is not LoSState.NIE_WIDZI


def _can_charge(
    attacker: UnitBlob, target: UnitBlob, move: float
) -> bool:
    """Czy Szarża (pkt 14.d) jest kandydatem: cel w zasięgu Związania (pkt 16).

    Pareto MVP: dystans obwód-obwód ≤ `move` (Związanie to ruch do kontaktu;
    osiągalny gdy gap mieści się w zasięgu Ruchu pkt 15.a).
    """
    gap = circle_edge_distance(
        attacker.position, attacker.radius_inches,
        target.position, target.radius_inches,
    )
    return gap <= move


def legal_followup_actions(
    state: BattleState,
    perspective: int,
    unit_id: int,
    actions_taken: tuple[Action, ...],
) -> list[Action]:
    """Legalne KOLEJNE akcje oddziału `unit_id` w trakcie aktywacji (pkt 11.b.iv).

    Filtruje `legal_actions` do tego oddziału i odsiewa nielegalne kontynuacje
    (limit 2 akcji, Ostrzał/Szarża raz) reużywając `resolver._can_take_followup`
    (SSOT reguły). Lazy import unika cyklu agents↔resolver na module-load.
    """
    from app.services.engine.resolver import _can_take_followup

    return [
        a
        for a in legal_actions(state, perspective)
        if a.unit_id == unit_id and _can_take_followup(a, actions_taken)
    ]


def legal_actions(state: BattleState, perspective: int) -> list[Action]:
    """Enumeruje rozsądnych kandydatów na akcję dla gracza `perspective`.

    Per własny aktywowalny oddział (pkt 14):
    - Obrona (14.b) — zawsze.
    - Odrzuć Wyczerpany (14.e + 22.a) — jeśli oddział Wyczerpany.
    - Manewr (14.a) — dyskretyzowane pozycje docelowe (clamp do move_inches).
    - Ostrzał (14.c) — per broń dystansowa × wrogi oddział w zasięgu + LoS.
    - Szarża (14.d) — per broń wręcz × wrogi oddział w zasięgu Związania.

    Zwraca pustą listę gdy gracz nie ma aktywowalnych oddziałów (sygnał dla
    `choose_action` → None). Nie waliduje pełnej legalności (limit akcji,
    blokada Ostrzału w zwarciu) — to robi resolver. Kandydaci Manewru
    korzystają z tego samego planera tras co resolver (ADR-0057).
    """
    enemies = enemy_units(state, perspective)
    actions: list[Action] = []
    for unit in own_active_units(state, perspective):
        move = effective_move_inches(unit)  # per-oddział: pkt 15.a ± Szybki/Wolny
        actions.append(DefendAction(unit_id=unit.id))
        if STATUS_WYCZERPANY in unit.status_flags:
            actions.append(
                SpecialAction(unit_id=unit.id, ability_slug="discard_exhausted")
            )
        for target_pos in _maneuver_targets(
            state, unit, enemies, state.objectives, move
        ):
            actions.append(
                ManeuverAction(unit_id=unit.id, target_position=target_pos)
            )
        for weapon in unit.ranged_weapons:
            for enemy in enemies:
                if _can_shoot(unit, enemy, weapon, state.terrain):
                    actions.append(
                        ShootAction(
                            unit_id=unit.id, target_id=enemy.id, weapon=weapon
                        )
                    )
        for weapon in unit.melee_weapons:
            for enemy in enemies:
                if _can_charge(unit, enemy, move):
                    actions.append(
                        ChargeAction(
                            unit_id=unit.id, target_id=enemy.id, weapon=weapon
                        )
                    )
    return actions


# ---------------------------------------------------------------------------
# Player ABC
# ---------------------------------------------------------------------------


class Player(ABC):
    """Bazowy bot: wybiera jedną akcję dla swojego gracza w danym stanie.

    `choose_action` zwraca `None`, gdy gracz nie ma legalnej akcji (wszystkie
    oddziały Aktywowane / pokonane) — orkiestrator (B4/B5) interpretuje to jako
    przekazanie inicjatywy / koniec rundy (pkt 8.b).
    """

    @abstractmethod
    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        """Zwraca akcję do wykonania przez gracza `perspective`, albo None."""
        raise NotImplementedError

    def continue_activation(
        self,
        state: BattleState,
        perspective: int,
        unit_id: int,
        actions_taken: tuple[Action, ...],
    ) -> Action | None:
        """Kolejna akcja TEGO oddziału w aktywacji (pkt 11.b.iv) lub None = koniec.

        Wywoływane przez `resolver.apply_activation` po pierwszej akcji. Default:
        `None` (1 akcja/aktywację — wsteczna kompatybilność). Boty override, by
        wykorzystać 2. akcję (np. Manewr→Ostrzał). Kandydaci:
        `base.legal_followup_actions(state, perspective, unit_id, actions_taken)`.
        """
        return None

    def choose_deployment(
        self,
        state: BattleState,
        unit_id: int,
        zone: "DeploymentZone",
    ) -> Position:
        """Pozycja rozstawienia oddziału `unit_id` w strefie `zone` (D5, pkt 13).

        Wywoływane przez `simulate_from_rosters`, gdy podano `deployment_zones`.
        Default: **bieżąca pozycja oddziału** (z roster/fikstury) — wsteczna
        kompatybilność z grami bez aktywnego deploymentu. Boty override, by
        wybrać pozycję strategicznie (np. `random_player` losuje w strefie,
        `deployment.grid_positions` daje równomierny grid).

        Runner przekazuje roboczy stan z już wybranymi pozycjami, a zwrócone
        miejsce sprawdza walidatorem D5.1 (pkt 13.a). Pozycje oczekujących
        jednostek są placeholderami, nie zajętymi miejscami. Wbudowane strategie
        otrzymują jawny zbiór zajętych miejsc przez prywatny kontekst callbacku.
        """
        return blob_by_id(state, unit_id).position
