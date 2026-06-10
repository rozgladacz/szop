"""D — `PriorityPlayer`: bot pół-deterministyczny (spec usera 2026-06-10).

Selekcja oddziału: aktywuj **najdroższy** oddział, który **ma cel w zasięgu**.
W ramach aktywacji — pierwsza spełniona reguła z priorytetu:

  1. Strzelaj do najbliższego wroga (Ostrzał, pkt 14.c).
  2. Szarżuj na najbliższego wroga (Szarża, pkt 14.d).
  3. Zdejmij Wyczerpany (SpecialAction discard_exhausted, pkt 22.a).
  4. Zdejmij Przyszpilony (Obrona → Ufortyfikowany odrzuca Przyszpilony, pkt 22.b.v).
  5. Jeśli (Wojownik/Mag) i kontrolujesz mniej celów niż przeciwnik —
     ruch do najbliższego nie-twojego celu (pkt 5.d/5.f).
  6. Ruch do najbliższego celu, jeśli nie jesteś na celu.
  7. Obrona (pkt 14.b).

Pół-deterministyczny: zero RNG w decyzji (RNG tylko w combat przy `apply`);
remisy rozstrzygane stabilnie (najniższe id). Czysta funkcja decyzji nad
publicznym API silnika (ADR-0011/0031), zero zmian w rdzeniu.

ZAŁOŻENIA (silnik nie ma kosztu punktowego ani slugu „Wojownik"):
- **„najdroższy"** → proxy `models_alive × toughness_per_model` (HP pool).
  Remis → najniższe id. Na oddziałach o równych statystykach proxy jest uniform.
- **„cel w zasięgu" (selekcja)** → cel z `circle_edge_distance ≤ move_inches`.
  Brak → fallback: najdroższy aktywny oddział.
- **Krok 5 „Wojownik/Mag"** → pasywka ∈ {`mag`, `bohater`} (`wojownik` nie jest
  slugiem w rulesecie). Inertny na oddziałach bez zdolności.
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
from app.services.engine.geometry import circle_edge_distance, distance
from app.services.engine.phases import (
    OBJECTIVE_CONTROL_RANGE,
    _check_objective_control,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    UnitBlob,
    effective_passives,
)
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY

#: Pasywki kwalifikujące do kroku 5 (proxy „Wojownik/Mag"; `wojownik` poza regułami).
_AGGRESSIVE_OBJECTIVE_SLUGS = frozenset({"mag", "bohater"})


def _unit_cost(blob: UnitBlob) -> int:
    """Proxy kosztu oddziału (silnik nie ma punktów): HP pool = modele × wytrzymałość."""
    return blob.models_alive * blob.toughness_per_model


def _objective_edge_gap(blob: UnitBlob, obj: Objective) -> float:
    """Odległość obwodu oddziału od celu (≈ pkt 5.d mierzone 3″ od celu)."""
    return max(distance(blob.position, obj.position) - blob.radius_inches, 0.0)


def _has_objective_in_range(blob: UnitBlob, state: BattleState, move: float) -> bool:
    """Czy oddział ma cel osiągalny w tej aktywacji (gap ≤ move_inches)."""
    return any(_objective_edge_gap(blob, o) <= move for o in state.objectives)


def _is_on_objective(blob: UnitBlob, state: BattleState) -> bool:
    """Czy oddział jest na jakimś celu (w zasięgu kontroli 3″, pkt 5.d)."""
    return any(
        _objective_edge_gap(blob, o) <= OBJECTIVE_CONTROL_RANGE for o in state.objectives
    )


def _nearest_enemy_shoot(
    unit: UnitBlob, enemies: list[UnitBlob], terrain: tuple
) -> ShootAction | None:
    """Ostrzał najbliższego wroga osiągalnego którąkolwiek bronią dystansową."""
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


def _controlled_counts(state: BattleState, perspective: int) -> tuple[int, int]:
    """(własne, wroga) zajęte cele po przeliczeniu kontroli z pozycji (pkt 5.d, SSOT)."""
    controlled, _events, _seq = _check_objective_control(state)
    own = sum(1 for o in controlled.objectives if o.controller == perspective)
    enemy = sum(
        1 for o in controlled.objectives
        if o.controller is not None and o.controller != perspective
    )
    return own, enemy


def _move_to_objective(
    unit: UnitBlob, objectives: list[Objective], move: float
) -> ManeuverAction | None:
    """Manewr ku najbliższemu celowi z listy (clamp move_inches). None gdy pusto."""
    if not objectives:
        return None
    target = min(objectives, key=lambda o: distance(unit.position, o.position))
    dest = _move_toward(unit.position, target.position, move)
    if dest == unit.position:
        return None  # już na miejscu — nie generuj no-op ruchu
    return ManeuverAction(unit_id=unit.id, target_position=dest)


class PriorityPlayer(Player):
    """Bot pół-deterministyczny: selekcja po koszcie + cel-w-zasięgu, akcja po priorytecie 1–7."""

    def choose_action(self, state: BattleState, perspective: int) -> Action | None:
        units = own_active_units(state, perspective)
        if not units:
            return None
        return self._act(state, perspective, self._select_unit(state, units))

    def _select_unit(self, state: BattleState, units: list[UnitBlob]) -> UnitBlob:
        """Najdroższy oddział z celem w zasięgu; fallback: najdroższy aktywny.

        Remis kosztu → najniższe id (determinizm). Klucz sort: (-koszt, id).
        """
        move = _move_inches()
        with_objective = [u for u in units if _has_objective_in_range(u, state, move)]
        pool = with_objective or units
        return min(pool, key=lambda u: (-_unit_cost(u), u.id))

    def _act(self, state: BattleState, perspective: int, unit: UnitBlob) -> Action:
        move = _move_inches()
        enemies = enemy_units(state, perspective)

        # 1. Strzelaj do najbliższego.
        shoot = _nearest_enemy_shoot(unit, enemies, state.terrain)
        if shoot is not None:
            return shoot
        # 2. Szarżuj na najbliższego.
        charge = _nearest_enemy_charge(unit, enemies, move)
        if charge is not None:
            return charge
        # 3. Zdejmij Wyczerpany.
        if STATUS_WYCZERPANY in unit.status_flags:
            return SpecialAction(unit_id=unit.id, ability_slug="discard_exhausted")
        # 4. Zdejmij Przyszpilony (Obrona → Ufortyfikowany odrzuca Przyszpilony, pkt 22.b.v).
        if STATUS_PRZYSZPILONY in unit.status_flags:
            return DefendAction(unit_id=unit.id)
        # 5. (Wojownik/Mag) i kontrolujesz mniej celów → ruch do nie-twojego celu.
        if _AGGRESSIVE_OBJECTIVE_SLUGS.intersection(effective_passives(unit)):
            own_ctrl, enemy_ctrl = _controlled_counts(state, perspective)
            if own_ctrl < enemy_ctrl:
                not_mine = [
                    o for o in state.objectives if o.controller != perspective
                ]
                mv = _move_to_objective(unit, not_mine, move)
                if mv is not None:
                    return mv
        # 6. Ruch do najbliższego celu, jeśli nie jesteś na celu.
        if not _is_on_objective(unit, state):
            mv = _move_to_objective(unit, list(state.objectives), move)
            if mv is not None:
                return mv
        # 7. Obrona.
        return DefendAction(unit_id=unit.id)
