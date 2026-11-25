"""D — `PriorityV3Player`: bot z drzewem decyzyjnym (spec usera 2026-06-11).

Wersje `PriorityPlayer` (prosty) i `PriorityV2Player` zachowane do porównań.

**Selekcja aktywacji** (lexykograficznie po własnych nie-Aktywowanych oddziałach):
  1. ma w zasięgu cel o najwyższej wadze ataku (patrz `_target_weight`),
  2. zdrowy (nie Przyszpilony/Wyczerpany),
  3. najbliżej wroga nieaktywowanego,
  4. najbliżej wroga zdrowego,
  5. najbliżej dowolnego wroga.  (remis → najniższe id)

**Akcja** — drzewo decyzyjne 29 węzłów (`_DECISION_TREE`), gałąź Wojownik vs
Strzelec; węzły to warunki (→true/→false) lub akcje-liście.

**Wybór celu ataku** — MAX wagi `_target_weight`:
  `-1 jeśli Aktywowany; -0.25 za każdy z {Przyszpilony, Wyczerpany,
  Przygotowany}; +x*(4-x)` gdzie `x = oczekiwane_obrażenia / pozostała_HP`.

ZAŁOŻENIA: Wojownik = `melee_attacks > ranged_attacks` (silnik bez klasyfikacji
kosztów); „Masz Przygotowanie" = pasywka slug `przygotowanie`. Konsekwencja
nieudanego Przegrupowania (drzewo usera) ODŁOŻONA — pkt 20.f.i źródła = stały
Wyczerpany (bez wyboru; wymaga zmiany reguł+silnika).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.agents.base import (
    Player,
    _can_charge,
    _can_shoot,
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
from app.services.agents.priority_v2_player import (
    _dist_to_nearest,
    _is_healthy,
    _split_objectives_by_control,
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
from app.services.engine.pathfinding import ManeuverPlanner
from app.services.engine.phases import OBJECTIVE_CONTROL_RANGE
from app.services.engine.prediction import expected_damage
from app.services.engine.state import (
    BattleState,
    Objective,
    UnitBlob,
    effective_move_inches,
)
from app.services.engine.action_constraints import (
    attack_allowed_by_status,
    maneuver_allowed_by_status,
    shooting_lock_reason,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_WYCZERPANY,
)

_NEG_INF = float("-inf")


def _is_wojownik(unit: UnitBlob) -> bool:
    """Proxy klasyfikacji (silnik bez kosztów): więcej ataków wręcz niż dystans."""
    melee = sum(w.attacks for w in unit.melee_weapons)
    ranged = sum(w.attacks for w in unit.ranged_weapons)
    return melee > ranged


def _target_weight(attacker: UnitBlob, target: UnitBlob, weapon, terrain: tuple) -> float:
    """Waga celu ataku (wyższa = lepszy). Spec usera 2026-06-11."""
    w = 0.0
    if STATUS_AKTYWOWANY in target.status_flags:
        w -= 1.0
    for s in (STATUS_PRZYSZPILONY, STATUS_WYCZERPANY, STATUS_PRZYGOTOWANY):
        if s in target.status_flags:
            w -= 0.25
    hp = target.models_alive * target.toughness_per_model
    if hp > 0:
        x = expected_damage(attacker, target, weapon, terrain).mean / hp
        w += x * (4.0 - x)
    return w


def _shoot_candidates(state: BattleState, unit: UnitBlob, enemies: list[UnitBlob]):
    """(weapon, [targets]) dla Ostrzału — pierwsza broń dystansowa (MVP)."""
    if not unit.ranged_weapons or shooting_lock_reason(state, unit) is not None:
        return None, []
    weapon = unit.ranged_weapons[0]
    return weapon, [e for e in enemies if _can_shoot(unit, e, weapon, state.terrain)]


def _charge_candidates(unit: UnitBlob, enemies: list[UnitBlob], move: float):
    """(weapon, [targets]) dla Szarży — pierwsza broń wręcz (MVP)."""
    if not unit.melee_weapons:
        return None, []
    weapon = unit.melee_weapons[0]
    return weapon, [e for e in enemies if _can_charge(unit, e, move)]


def _best_target(attacker, candidates, weapon, terrain):
    """Cel o najwyższej wadze (remis → najniższe id)."""
    if not candidates:
        return None
    return max(candidates, key=lambda t: (_target_weight(attacker, t, weapon, terrain), -t.id))


@dataclass(slots=True)
class _Ctx:
    """Kontekst decyzji (zbudowany raz per `_act`)."""

    state: BattleState
    perspective: int
    unit: UnitBlob
    actions_taken: tuple
    enemies: list
    move: float
    mine: list
    not_mine: list
    own_field: list
    shoot_weapon: object
    shoot_targets: list
    charge_weapon: object
    charge_targets: list

    @property
    def first_action(self) -> bool:
        return len(self.actions_taken) == 0

    @property
    def shoot_used(self) -> bool:
        return any(isinstance(a, ShootAction) for a in self.actions_taken)

    @property
    def charge_used(self) -> bool:
        return any(isinstance(a, ChargeAction) for a in self.actions_taken)


# --- warunki (predykaty) ---


def _c_wojownik(c: _Ctx) -> bool:
    return _is_wojownik(c.unit)


def _c_has_charge_target(c: _Ctx) -> bool:
    return bool(c.charge_targets)


def _c_has_shoot_target(c: _Ctx) -> bool:
    return bool(c.shoot_targets)


def _c_exhausted(c: _Ctx) -> bool:
    return not attack_allowed_by_status(c.unit)


def _c_pinned(c: _Ctx) -> bool:
    return not maneuver_allowed_by_status(c.unit)


def _c_przygotowanie_first_not_fortified(c: _Ctx) -> bool:
    return (
        "przygotowanie" in c.unit.passives
        and c.first_action
        and STATUS_PRZYGOTOWANY not in c.unit.status_flags
    )


def _c_can_shoot(c: _Ctx) -> bool:
    return bool(c.shoot_targets) and not c.shoot_used and not _c_exhausted(c)


def _c_can_charge(c: _Ctx) -> bool:
    return bool(c.charge_targets) and not c.charge_used and not _c_exhausted(c)


def _c_near_not_mine_objective(c: _Ctx) -> bool:
    """W 2″ (kontrola, pkt 5.d) od celu nie naszej strony."""
    return any(
        distance(c.unit.position, o.position) - c.unit.radius_inches <= OBJECTIVE_CONTROL_RANGE
        for o in c.not_mine
    )


def _c_closest_to_not_mine(c: _Ctx) -> bool:
    return any(_is_closest_own_unit(c.unit, o, c.own_field) for o in c.not_mine)


def _c_exhausted_first_action(c: _Ctx) -> bool:
    return _c_exhausted(c) and c.first_action


# --- akcje (liście) ---


def _a_discard(c: _Ctx) -> Action:
    return SpecialAction(unit_id=c.unit.id, ability_slug="discard_exhausted")


def _a_defend(c: _Ctx) -> Action:
    return DefendAction(unit_id=c.unit.id)


def _a_shoot(c: _Ctx) -> Action:
    t = _best_target(c.unit, c.shoot_targets, c.shoot_weapon, c.state.terrain)
    if t is None:
        return _a_defend(c)
    return ShootAction(unit_id=c.unit.id, target_id=t.id, weapon=c.shoot_weapon)


def _a_charge(c: _Ctx) -> Action:
    if _c_exhausted(c):
        return _a_defend(c)
    # Osłona (pkt 19) dotyczy tylko Ostrzału — silnik melee nie liczy `compute_cover`.
    # Scoring celu Szarży z pustym terenem, by prediction był spójny z combatem.
    t = _best_target(c.unit, c.charge_targets, c.charge_weapon, ())
    if t is None:
        return _a_defend(c)
    return ChargeAction(unit_id=c.unit.id, target_id=t.id, weapon=c.charge_weapon)


def _a_move_closest_friend_objective(c: _Ctx) -> Action:
    mine_closest = [o for o in c.not_mine if _is_closest_own_unit(c.unit, o, c.own_field)]
    return _move_to_objective(c.state, c.unit, mine_closest, c.move) or _a_defend(c)


def _a_move_to_enemy(c: _Ctx) -> Action:
    if not c.enemies:
        return _a_defend(c)
    target = min(c.enemies, key=lambda e: (distance(c.unit.position, e.position), e.id))
    dest = ManeuverPlanner(c.state, c.unit, c.move).advance_toward(target.position)
    if dest is None:
        return _a_defend(c)
    return ManeuverAction(unit_id=c.unit.id, target_position=dest)


def _a_move_to_not_mine_objective(c: _Ctx) -> Action:
    return _move_to_objective(c.state, c.unit, c.not_mine, c.move) or _a_defend(c)


#: Drzewo decyzyjne (spec usera 2026-06-11). Węzeł: ("cond", pred, true, false)
#: lub ("act", builder). Wejście = węzeł 1.
_DECISION_TREE: dict[int, tuple] = {
    1: ("cond", _c_wojownik, 2, 16),
    2: ("cond", _c_has_charge_target, 3, 9),
    3: ("cond", _c_exhausted, 4, 5),
    4: ("act", _a_discard),
    5: ("cond", _c_przygotowanie_first_not_fortified, 6, 7),
    6: ("act", _a_defend),
    7: ("cond", _c_can_charge, 14, 9),
    8: ("cond", _c_closest_to_not_mine, 21, 13),
    9: ("cond", _c_near_not_mine_objective, 20, 8),
    10: ("cond", _c_can_shoot, 11, 6),
    11: ("act", _a_shoot),
    12: ("act", _a_move_closest_friend_objective),
    13: ("cond", _c_has_charge_target, 10, 22),
    14: ("act", _a_charge),
    15: ("act", _a_move_to_enemy),
    16: ("cond", _c_has_shoot_target, 17, 23),
    17: ("cond", _c_exhausted, 4, 18),
    18: ("cond", _c_przygotowanie_first_not_fortified, 6, 19),
    19: ("cond", _c_can_shoot, 11, 23),
    20: ("cond", _c_pinned, 6, 10),
    21: ("cond", _c_pinned, 6, 12),
    22: ("cond", _c_pinned, 6, 15),
    23: ("cond", _c_near_not_mine_objective, 24, 27),
    24: ("cond", _c_pinned, 6, 25),
    25: ("cond", _c_has_charge_target, 26, 6),
    26: ("cond", _c_exhausted_first_action, 4, 14),
    27: ("cond", _c_closest_to_not_mine, 21, 28),
    28: ("cond", _c_pinned, 6, 29),
    29: ("act", _a_move_to_not_mine_objective),
}


class PriorityV3Player(GridDeploymentMixin, Player):
    """Bot z drzewem decyzyjnym (v3). Patrz docstring modułu."""

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

    def _build_ctx(self, state, perspective, unit, actions_taken) -> _Ctx:
        enemies = enemy_units(state, perspective)
        move = effective_move_inches(unit)  # pkt 15.a ± Szybki/Wolny (zdolność 33)
        mine, not_mine = _split_objectives_by_control(state, perspective)
        sw, st = _shoot_candidates(state, unit, enemies)
        cw, ct = _charge_candidates(unit, enemies, move)
        return _Ctx(
            state=state, perspective=perspective, unit=unit, actions_taken=tuple(actions_taken),
            enemies=enemies, move=move, mine=mine, not_mine=not_mine,
            own_field=_own_field_units(state, perspective),
            shoot_weapon=sw, shoot_targets=st, charge_weapon=cw, charge_targets=ct,
        )

    def _best_achievable_target_weight(self, ctx: _Ctx) -> float:
        """Najwyższa waga celu osiągalnego przez oddział (Ostrzał lub Szarża).

        Ostrzał honoruje osłonę (pkt 19); Szarża (melee) nie — silnik melee nie
        liczy `compute_cover`, więc scoring celów Szarży z pustym terenem."""
        best = _NEG_INF
        for w, targets, terrain in (
            (ctx.shoot_weapon, ctx.shoot_targets, ctx.state.terrain),
            (ctx.charge_weapon, ctx.charge_targets, ()),
        ):
            for t in targets:
                best = max(best, _target_weight(ctx.unit, t, w, terrain))
        return best

    def _select_unit(self, state, perspective, units):
        enemies = enemy_units(state, perspective)
        non_activated = [e for e in enemies if STATUS_AKTYWOWANY not in e.status_flags]
        healthy = [e for e in enemies if _is_healthy(e)]

        def _key(u: UnitBlob):
            ctx = self._build_ctx(state, perspective, u, ())
            return (
                -self._best_achievable_target_weight(ctx),
                0 if _is_healthy(u) else 1,
                _dist_to_nearest(u, non_activated),
                _dist_to_nearest(u, healthy),
                _dist_to_nearest(u, enemies),
                u.id,
            )

        return min(units, key=_key)

    def _act(self, state, perspective, unit, actions_taken=()) -> Action:
        ctx = self._build_ctx(state, perspective, unit, actions_taken)
        node = 1
        seen: set[int] = set()
        while node not in seen:
            seen.add(node)
            spec = _DECISION_TREE[node]
            if spec[0] == "act":
                return spec[1](ctx)
            _, pred, t_node, f_node = spec
            node = t_node if pred(ctx) else f_node
        # Bezpiecznik: cykl w drzewie (nie powinno wystąpić) → Obrona.
        return DefendAction(unit_id=unit.id)
