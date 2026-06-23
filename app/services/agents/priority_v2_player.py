"""D — `PriorityV2Player`: rozbudowany bot pół-deterministyczny (spec usera 2026-06-10).

Wersja rozszerzona wobec `PriorityPlayer` (prosta, zachowana do porównań):
dodaje wielokryterialną selekcję aktywacji wg stanu wrogów, ruch przechwytujący
(obrona własnych celów) oraz wybór celu ataku przez `prediction` (szansa
pokonania / oczekiwane obrażenia).

**Selekcja aktywacji** (lexykograficznie po własnych nie-Aktywowanych oddziałach):
  1. nie Przyszpilony/Wyczerpany (zdrowy),
  2. najbliżej wroga NIEaktywowanego,
  3. najbliżej wroga zdrowego (nie Przyszpilony/Wyczerpany),
  4. najbliżej dowolnego wroga.  (remis → najniższe id)

**Akcja** (pierwsza spełniona; pkt 11.b.iv: do 2 akcji, Ostrzał/Szarża raz):
  1. zdejmij Wyczerpany (pkt 22.a),
  2. Strzelaj (najlepszy cel, pkt 14.c),
  3. Szarżuj (najlepszy cel, pkt 14.d),
  4. zdejmij Przyszpilony (Obrona → Ufortyfikowany, pkt 22.b.v),
  5. ruch do niezajętego celu (pkt 5.d), dla którego jesteś najbliższym oddziałem,
  6. ruch przechwytujący: do najbliższego wroga, który jest bliżej niż ty celu
     ZAJĘTEGO przez nas (dla którego jesteś najbliższym obrońcą) — broń celu,
  7. ruch do dowolnego niezajętego celu,
  8. ruch do najbliższego wroga.  (bezpiecznik: Obrona)

**Wybór celu ataku** (lexykograficznie):
  1. nie Przyszpilony/Wyczerpany, 2. nie Aktywowany, 3. najwyższa szansa
  pokonania (`p_full_kill`), 4. najwyższe oczekiwane obrażenia (`mean`),
  5. najbliżej.  (remis → najniższe id)

Pół-deterministyczny: zero RNG w decyzji (RNG tylko w combat przy `apply`).
Czysta funkcja decyzji nad publicznym API silnika (ADR-0011/0031/0044).
"""

from __future__ import annotations

from app.services.agents.base import (
    Player,
    _can_charge,
    _can_shoot,
    _move_toward,
    enemy_units,
    own_active_units,
)
from app.services.agents.deployment import GridDeploymentMixin
from app.services.agents.priority_player import (
    _blob_by_id,
    _is_closest_own_unit,
    _move_to_objective,
    _own_field_units,
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
from app.services.engine.prediction import expected_damage
from app.services.engine.state import (
    BattleState,
    Objective,
    UnitBlob,
    effective_move_inches,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_WYCZERPANY,
)

_INF = float("inf")


def _is_healthy(blob: UnitBlob) -> bool:
    """Oddział nie Przyszpilony i nie Wyczerpany (pkt 22.a/b)."""
    return (
        STATUS_PRZYSZPILONY not in blob.status_flags
        and STATUS_WYCZERPANY not in blob.status_flags
    )


def _dist_to_nearest(unit: UnitBlob, others: list[UnitBlob]) -> float:
    """Najmniejszy dystans (środek-środek) do `others`; `inf` gdy pusto."""
    return min((distance(unit.position, o.position) for o in others), default=_INF)


def _split_objectives_by_control(
    state: BattleState, perspective: int
) -> tuple[list[Objective], list[Objective]]:
    """(zajęte przez nas, nie zajęte przez nas) — kontrola przeliczona z pozycji
    (pkt 5.d, `_check_objective_control` SSOT; trwała między rundami)."""
    controlled, _events, _seq = _check_objective_control(state)
    mine = [o for o in controlled.objectives if o.controller == perspective]
    not_mine = [o for o in controlled.objectives if o.controller != perspective]
    return mine, not_mine


def _best_target(
    attacker: UnitBlob,
    candidates: list[UnitBlob],
    weapon,
    terrain: tuple,
) -> UnitBlob | None:
    """Najlepszy cel ataku wg priorytetu usera (lexykograficznie):
    zdrowy > nieaktywowany > p_full_kill > oczekiwane obrażenia > najbliżej > id."""
    if not candidates:
        return None

    def _key(t: UnitBlob):
        dist = expected_damage(attacker, t, weapon, terrain)
        return (
            0 if _is_healthy(t) else 1,
            0 if STATUS_AKTYWOWANY not in t.status_flags else 1,
            -dist.p_full_kill(),
            -dist.mean,
            distance(attacker.position, t.position),
            t.id,
        )

    return min(candidates, key=_key)


class PriorityV2Player(GridDeploymentMixin, Player):
    """Rozbudowany bot priorytetowy (v2). Patrz docstring modułu."""

    def choose_action(self, state: BattleState, perspective: int) -> Action | None:
        units = own_active_units(state, perspective)
        if not units:
            return None
        return self._act(state, perspective, self._select_unit(state, perspective, units))

    def continue_activation(
        self, state: BattleState, perspective: int, unit_id, actions_taken
    ) -> Action | None:
        unit = _blob_by_id(state, unit_id)
        if unit is None:
            return None
        return self._act(state, perspective, unit, actions_taken)

    def _select_unit(
        self, state: BattleState, perspective: int, units: list[UnitBlob]
    ) -> UnitBlob:
        """Selekcja aktywacji wg 4 kryteriów (patrz docstring modułu)."""
        enemies = enemy_units(state, perspective)
        non_activated = [e for e in enemies if STATUS_AKTYWOWANY not in e.status_flags]
        healthy_enemies = [e for e in enemies if _is_healthy(e)]

        def _key(u: UnitBlob):
            return (
                0 if _is_healthy(u) else 1,
                _dist_to_nearest(u, non_activated),
                _dist_to_nearest(u, healthy_enemies),
                _dist_to_nearest(u, enemies),
                u.id,
            )

        return min(units, key=_key)

    def _act(
        self,
        state: BattleState,
        perspective: int,
        unit: UnitBlob,
        actions_taken: tuple[Action, ...] = (),
    ) -> Action:
        move = effective_move_inches(unit)  # pkt 15.a ± Szybki/Wolny (zdolność 33)
        enemies = enemy_units(state, perspective)
        shoot_used = any(isinstance(a, ShootAction) for a in actions_taken)
        charge_used = any(isinstance(a, ChargeAction) for a in actions_taken)

        # 1. Zdejmij Wyczerpany.
        if STATUS_WYCZERPANY in unit.status_flags:
            return SpecialAction(unit_id=unit.id, ability_slug="discard_exhausted")
        # 2. Strzelaj (najlepszy cel; pkt 14.c.v — raz na aktywację).
        if not shoot_used and unit.ranged_weapons:
            weapon = unit.ranged_weapons[0]
            in_range = [e for e in enemies if _can_shoot(unit, e, weapon, state.terrain)]
            target = _best_target(unit, in_range, weapon, state.terrain)
            if target is not None:
                return ShootAction(unit_id=unit.id, target_id=target.id, weapon=weapon)
        # 3. Szarżuj (najlepszy cel; pkt 14.d.vi — raz na aktywację).
        if not charge_used and unit.melee_weapons:
            weapon = unit.melee_weapons[0]
            reachable = [e for e in enemies if _can_charge(unit, e, move)]
            # Osłona (pkt 19) dotyczy tylko Ostrzału — silnik melee
            # (`resolve_melee_attack`/`resolve_charge_attack`) nie liczy `compute_cover`.
            # Scoring celu Szarży z pustym terenem, by prediction był spójny z combatem.
            target = _best_target(unit, reachable, weapon, ())
            if target is not None:
                return ChargeAction(unit_id=unit.id, target_id=target.id, weapon=weapon)
        # 4. Zdejmij Przyszpilony (Obrona → Ufortyfikowany odrzuca Przyszpilony, pkt 22.b.v).
        if STATUS_PRZYSZPILONY in unit.status_flags:
            return DefendAction(unit_id=unit.id)

        mine, not_mine = _split_objectives_by_control(state, perspective)
        own_field = _own_field_units(state, perspective)

        # 5. Ruch do niezajętego celu, dla którego jestem najbliższym oddziałem.
        my_unclaimed = [o for o in not_mine if _is_closest_own_unit(unit, o, own_field)]
        mv = _move_to_objective(unit, my_unclaimed, move)
        if mv is not None:
            return mv
        # 6. Przechwyt: ruch do najbliższego wroga, który jest bliżej niż ja celu
        #    ZAJĘTEGO przez nas, dla którego jestem najbliższym obrońcą.
        intercept = self._intercept_move(unit, enemies, mine, own_field, move)
        if intercept is not None:
            return intercept
        # 7. Ruch do dowolnego niezajętego celu.
        mv = _move_to_objective(unit, not_mine, move)
        if mv is not None:
            return mv
        # 8. Ruch do najbliższego wroga.
        if enemies:
            target = min(enemies, key=lambda e: (distance(unit.position, e.position), e.id))
            dest = _move_toward(unit.position, target.position, move)
            if dest != unit.position:
                return ManeuverAction(unit_id=unit.id, target_position=dest)

        # Bezpiecznik (poza specem): brak wrogów i niezajętych celów → Obrona.
        return DefendAction(unit_id=unit.id)

    def _intercept_move(
        self,
        unit: UnitBlob,
        enemies: list[UnitBlob],
        mine: list[Objective],
        own_field: list[UnitBlob],
        move: float,
    ) -> ManeuverAction | None:
        """Priorytet 6: broń własnego celu — rusz do najbliższego wroga, który jest
        bliżej tego celu niż ty (i jesteś jego najbliższym obrońcą)."""
        defended = [o for o in mine if _is_closest_own_unit(unit, o, own_field)]
        threats: list[UnitBlob] = []
        for obj in defended:
            my_gap = distance(unit.position, obj.position)
            threats += [e for e in enemies if distance(e.position, obj.position) < my_gap]
        if not threats:
            return None
        target = min(threats, key=lambda e: (distance(unit.position, e.position), e.id))
        dest = _move_toward(unit.position, target.position, move)
        if dest == unit.position:
            return None
        return ManeuverAction(unit_id=unit.id, target_position=dest)
