"""D — `PriorityPlayer`: bot pół-deterministyczny (spec usera 2026-06-10, rev. 2).

Selekcja oddziału: **aktywuj oddział, który ma najbliżej do wroga**
(min. dystans do dowolnego wroga; remis → najniższe id).

W ramach aktywacji — pierwsza spełniona reguła z priorytetu (pkt 11.b.iv: do 2
akcji, Ostrzał/Szarża raz — pkt 14.c.v/14.d.vi; przy 2. akcji pomijamy już
wykonany Ostrzał/Szarżę i bierzemy następną dostępną):

  1. Jeśli Wyczerpany — zdejmij (SpecialAction discard_exhausted, pkt 22.a).
  2. Jeśli możesz — Strzelaj do najbliższego widocznego wroga (pkt 14.c).
  3. Jeśli możesz — Szarżuj na najbliższego wroga (pkt 14.d).
  4. Jeśli Przyszpilony — zdejmij (Obrona → Ufortyfikowany odrzuca Przyszpilony, pkt 22.b.v).
  5. Ruch do najbliższego celu **nie zajętego przez twoją stronę** (pkt 5.d),
     **dla którego jesteś najbliższym własnym oddziałem** (anty-klastrowanie —
     rozprasza oddziały po celach).
  6. Ruch do najbliższego celu nie zajętego przez twoją stronę.
  7. Ruch do najbliższego wroga.

Zajęcie celów (pkt 5.d) liczone z aktualnych pozycji przez
`phases._check_objective_control` (SSOT). Pół-deterministyczny: zero RNG w
decyzji (RNG tylko w combat przy `apply`); remisy rozstrzygane po id. Czysta
funkcja decyzji nad publicznym API silnika (ADR-0011/0031), zero zmian w rdzeniu.

Bezpiecznik: gdy żadna z 1–7 nie ma zastosowania (degenerat: brak wrogów i
niezajętych celów) → Obrona (poza 7 priorytetami usera, zapobiega brakowi akcji).
"""

from __future__ import annotations

from app.services.agents.base import (
    Player,
    _can_charge,
    _can_shoot,
    _move_inches,
    _move_toward,
    enemy_units,
    own_active_units,
)
from app.services.engine.actions import (
    Action,
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.geometry import distance
from app.services.engine.phases import _check_objective_control
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    UnitBlob,
)
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY


def _blob_by_id(state: BattleState, unit_id: int) -> UnitBlob | None:
    return next((b for b in state.blobs if b.id == unit_id), None)


def _dist_to_nearest_enemy(unit: UnitBlob, enemies: list[UnitBlob]) -> float:
    """Dystans do najbliższego wroga (środek-środek); `inf` gdy brak wrogów."""
    if not enemies:
        return float("inf")
    return min(distance(unit.position, e.position) for e in enemies)


def _own_field_units(state: BattleState, perspective: int) -> list[UnitBlob]:
    """Wszystkie żywe własne oddziały na Froncie (także Aktywowane — wciąż
    zajmują miejsce przy celu; istotne dla testu „najbliższy oddział")."""
    return [
        b
        for b in state.blobs
        if b.owner_player == perspective
        and b.models_alive > 0
        and b.location == Lokalizacja.FRONT
    ]


def _is_closest_own_unit(
    unit: UnitBlob, obj: Objective, own_units: list[UnitBlob]
) -> bool:
    """Czy `unit` jest najbliższym własnym oddziałem do `obj` (remis → najniższe id)."""
    if not own_units:
        return False
    nearest = min(own_units, key=lambda b: (distance(b.position, obj.position), b.id))
    return nearest.id == unit.id


def _objectives_not_controlled(
    state: BattleState, perspective: int
) -> list[Objective]:
    """Cele NIE zajęte przez `perspective` (pkt 5.d, kontrola przeliczona z
    pozycji przez `_check_objective_control` — SSOT). Zwraca obiekty `Objective`
    z aktualnym `controller` (niezajęte lub wrogie)."""
    controlled, _events, _seq = _check_objective_control(state)
    return [o for o in controlled.objectives if o.controller != perspective]


def _nearest_enemy_shoot(
    unit: UnitBlob, enemies: list[UnitBlob], terrain: tuple
) -> ShootAction | None:
    """Ostrzał najbliższego widocznego wroga osiągalnego bronią dystansową."""
    for enemy in sorted(enemies, key=lambda e: distance(unit.position, e.position)):
        for weapon in unit.ranged_weapons:
            if _can_shoot(unit, enemy, weapon, terrain):
                return ShootAction(unit_id=unit.id, target_id=enemy.id, weapon=weapon)
    return None


def _nearest_enemy_charge(
    unit: UnitBlob, enemies: list[UnitBlob], move: float
) -> ChargeAction | None:
    """Szarża na najbliższego wroga w zasięgu Związania którąkolwiek bronią wręcz."""
    for enemy in sorted(enemies, key=lambda e: distance(unit.position, e.position)):
        if unit.melee_weapons and _can_charge(unit, enemy, move):
            return ChargeAction(
                unit_id=unit.id, target_id=enemy.id, weapon=unit.melee_weapons[0]
            )
    return None


def _move_to_objective(
    unit: UnitBlob, objectives: list[Objective], move: float
) -> ManeuverAction | None:
    """Manewr ku najbliższemu celowi z listy (clamp move_inches). None gdy lista
    pusta lub oddział już na pozycji (brak no-op ruchu)."""
    if not objectives:
        return None
    target = min(objectives, key=lambda o: distance(unit.position, o.position))
    dest = _move_toward(unit.position, target.position, move)
    if dest == unit.position:
        return None
    return ManeuverAction(unit_id=unit.id, target_position=dest)


class PriorityPlayer(Player):
    """Bot pół-deterministyczny: selekcja „najbliżej wroga" + priorytet akcji 1–7."""

    def choose_action(self, state: BattleState, perspective: int) -> Action | None:
        units = own_active_units(state, perspective)
        if not units:
            return None
        return self._act(state, perspective, self._select_unit(state, perspective, units))

    def continue_activation(
        self, state: BattleState, perspective: int, unit_id, actions_taken
    ) -> Action | None:
        """2. akcja (pkt 11.b.iv): kolejna akcja wg PEŁNEGO priorytetu 1–7,
        pomijając już wykorzystany Ostrzał/Szarżę. Po strzale bot schodzi do celu
        (5/6) lub idzie do wroga (7) — nie marnuje akcji. None tylko gdy oddział
        zniknął."""
        unit = _blob_by_id(state, unit_id)
        if unit is None:
            return None
        return self._act(state, perspective, unit, actions_taken)

    def _select_unit(
        self, state: BattleState, perspective: int, units: list[UnitBlob]
    ) -> UnitBlob:
        """Oddział o najmniejszym dystansie do wroga (remis → najniższe id)."""
        enemies = enemy_units(state, perspective)
        return min(units, key=lambda u: (_dist_to_nearest_enemy(u, enemies), u.id))

    def _act(
        self,
        state: BattleState,
        perspective: int,
        unit: UnitBlob,
        actions_taken: tuple[Action, ...] = (),
    ) -> Action:
        move = _move_inches()
        enemies = enemy_units(state, perspective)
        shoot_used = any(isinstance(a, ShootAction) for a in actions_taken)
        charge_used = any(isinstance(a, ChargeAction) for a in actions_taken)

        # 1. Zdejmij Wyczerpany.
        if STATUS_WYCZERPANY in unit.status_flags:
            return SpecialAction(unit_id=unit.id, ability_slug="discard_exhausted")
        # 2. Strzelaj do najbliższego widocznego (o ile Ostrzał nie wykonany, pkt 14.c.v).
        if not shoot_used:
            shoot = _nearest_enemy_shoot(unit, enemies, state.terrain)
            if shoot is not None:
                return shoot
        # 3. Szarżuj na najbliższego (o ile Szarża nie wykonana, pkt 14.d.vi).
        if not charge_used:
            charge = _nearest_enemy_charge(unit, enemies, move)
            if charge is not None:
                return charge
        # 4. Zdejmij Przyszpilony (Obrona → Ufortyfikowany odrzuca Przyszpilony, pkt 22.b.v).
        if STATUS_PRZYSZPILONY in unit.status_flags:
            return DefendAction(unit_id=unit.id)

        # 5/6. Ruch do najbliższego celu nie zajętego przez naszą stronę (pkt 5.d).
        not_mine = _objectives_not_controlled(state, perspective)
        # 5. ...dla którego jestem najbliższym własnym oddziałem (anty-klastrowanie).
        own_field = _own_field_units(state, perspective)
        my_objectives = [o for o in not_mine if _is_closest_own_unit(unit, o, own_field)]
        mv = _move_to_objective(unit, my_objectives, move)
        if mv is not None:
            return mv
        # 6. ...dowolnego niezajętego.
        mv = _move_to_objective(unit, not_mine, move)
        if mv is not None:
            return mv

        # 7. Ruch do najbliższego wroga.
        if enemies:
            target = min(
                enemies, key=lambda e: (distance(unit.position, e.position), e.id)
            )
            dest = _move_toward(unit.position, target.position, move)
            if dest != unit.position:
                return ManeuverAction(unit_id=unit.id, target_position=dest)

        # Bezpiecznik (poza specem): brak wrogów i niezajętych celów → Obrona.
        return DefendAction(unit_id=unit.id)
