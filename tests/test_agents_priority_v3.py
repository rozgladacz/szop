"""D — testy `PriorityV3Player` (drzewo decyzyjne + waga celu + audyt legalności)."""

from __future__ import annotations

from app.services.agents.priority_v3_player import (
    PriorityV3Player,
    _is_wojownik,
    _target_weight,
)
from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.geometry import distance
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    TerrainCircle,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY, STATUS_WYCZERPANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
BLADE = WeaponProfile(slug="blade", name="Blade", range_inches=0, attacks=1)
GREATBLADE = WeaponProfile(slug="gb", name="GB", range_inches=0, attacks=3)


def _blob(uid, owner, x, y, **kw) -> UnitBlob:
    d = {"id": uid, "owner_player": owner, "position": Position(x, y),
         "radius_inches": 1.0, "models_alive": 5, "toughness_per_model": 3}
    d.update(kw)
    return UnitBlob(**d)


def _state(blobs, objectives=()) -> BattleState:
    return BattleState(round=1, active_player=0, activations_remaining=(1, 1),
                       blobs=blobs, terrain=(), objectives=objectives)


# --- klasyfikacja Wojownik ---


def test_is_wojownik_classification():
    assert _is_wojownik(_blob(1, 0, 0, 0, melee_weapons=(GREATBLADE,))) is True   # 3 wręcz > 0
    assert _is_wojownik(_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,), melee_weapons=(BLADE,))) is False  # 1==1
    assert _is_wojownik(_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))) is False      # 0 < 1


# --- waga celu ---


def test_target_weight_penalizes_activated():
    a = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    fresh = _blob(2, 1, 8, 0)
    activated = _blob(3, 1, 8, 0, status_flags=(STATUS_AKTYWOWANY,))
    assert _target_weight(a, fresh, RIFLE, ()) > _target_weight(a, activated, RIFLE, ())


def test_charge_target_ignores_cover_pkt19():
    """Szarża (melee) nie uwzględnia osłony (pkt 19 = Ostrzał): silnik melee nie
    liczy `compute_cover`. Cel za zasłoną Obronną i identyczny bez zasłony,
    w równym dystansie, mają równą wagę → tie-break po id (covered = niższe id).
    Przed fixem osłona zaniżała `mean` covered-celu → wybierany byłby uncovered."""
    own = _blob(1, 0, 0, 0, melee_weapons=(GREATBLADE,))  # wojownik → gałąź Szarży
    covered = _blob(2, 1, 4, 0)  # niższe id, w terenie Obronnym (osłona)
    uncovered = _blob(3, 1, 0, 4)  # równy dystans (4), bez osłony
    terrain = (TerrainCircle(center=Position(4, 0), radius_inches=3, features=("Obronny",)),)
    state = BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=(own, covered, uncovered), terrain=terrain, objectives=(),
    )
    action = PriorityV3Player().choose_action(state, 0)
    assert isinstance(action, ChargeAction)
    assert action.target_id == 2  # osłona ignorowana → tie-break id → covered (id 2)


def test_target_weight_penalizes_massive_overkill():
    # Formuła x*(4-x) jest symetryczna wokół x=2 i karze overkill (x>4 → ujemne).
    # Masywny overkill drobnego celu (x>>2) jest GORSZY niż „prawidłowy" cel.
    big = WeaponProfile("big", "Big", 24, 6)
    a = _blob(1, 0, 0, 0, ranged_weapons=(big,))
    right_sized = _blob(2, 1, 8, 0, models_alive=5, toughness_per_model=3)  # hp 15
    tiny = _blob(3, 1, 8, 0, models_alive=1, toughness_per_model=1)          # hp 1, overkill
    assert _target_weight(a, right_sized, big, ()) > _target_weight(a, tiny, big, ())


# --- drzewo decyzyjne ---


def test_wojownik_charges_target_in_range():
    own = _blob(1, 0, 0, 0, melee_weapons=(GREATBLADE,))  # Wojownik
    enemy = _blob(2, 1, 3, 0)
    action = PriorityV3Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ChargeAction) and action.target_id == 2


def test_strzelec_shoots_target_in_range():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))  # Strzelec (0 wręcz)
    enemy = _blob(2, 1, 8, 0)
    action = PriorityV3Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_wojownik_exhausted_with_charge_target_discards():
    own = _blob(1, 0, 0, 0, melee_weapons=(GREATBLADE,), status_flags=(STATUS_WYCZERPANY,))
    enemy = _blob(2, 1, 3, 0)
    action = PriorityV3Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, SpecialAction) and action.ability_slug == "discard_exhausted"


def test_moves_to_objective_when_no_combat():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))  # Strzelec
    enemy = _blob(2, 1, 60, 0)  # poza zasięgiem
    obj = Objective(id=1, position=Position(10, 0), controller=None)
    action = PriorityV3Player().choose_action(_state((own, enemy), (obj,)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, obj.position) < distance(own.position, obj.position)


def test_deterministic_choice():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    st = _state((own, enemy))
    assert PriorityV3Player().choose_action(st, 0) == PriorityV3Player().choose_action(st, 0)


# --- audyt legalności w pełnych grach ---


def _audit_rosters() -> list[dict]:
    def u(uid, x, y, weapons):
        return {"id": uid, "position": (x, y), "models": 5, "toughness": 3,
                "quality": 4, "defense": 5, "passives": [], "weapons": weapons}
    rifle = {"slug": "rifle", "name": "R", "range_inches": 24, "attacks": 1}
    blade = {"slug": "blade", "name": "B", "range_inches": 0, "attacks": 1}
    gb = {"slug": "gb", "name": "G", "range_inches": 0, "attacks": 3}
    return [
        {"owner_player": 0, "units": [u(1, 18, 12, [rifle, blade]), u(2, 30, 12, [gb])]},
        {"owner_player": 1, "units": [u(3, 18, 36, [rifle, blade]), u(4, 30, 36, [gb])]},
    ]


class _AuditingV3(PriorityV3Player):
    def __init__(self):
        self.violations: list[str] = []

    def _check(self, state, perspective, action, *, is_cont, taken=()):
        from app.services.agents.base import _can_charge, _can_shoot, _move_inches
        from app.services.engine.resolver import _can_take_followup
        from app.services.engine.status import STATUS_AKTYWOWANY as ACT

        if action is None:
            return
        actor = next((b for b in state.blobs if b.id == action.unit_id), None)
        if actor is None or actor.owner_player != perspective or actor.models_alive == 0:
            self.violations.append(f"bad actor {action}")
            return
        if ACT in actor.status_flags:
            self.violations.append(f"already activated {action}")
        if isinstance(action, ShootAction):
            t = next((b for b in state.blobs if b.id == action.target_id), None)
            if t is None or t.owner_player == perspective or not _can_shoot(actor, t, action.weapon, state.terrain):
                self.violations.append(f"illegal shoot {action}")
        if isinstance(action, ChargeAction):
            t = next((b for b in state.blobs if b.id == action.target_id), None)
            if t is None or t.owner_player == perspective or not _can_charge(actor, t, _move_inches()):
                self.violations.append(f"illegal charge {action}")
        if is_cont and not _can_take_followup(action, taken):
            self.violations.append(f"illegal followup {action}")

    def choose_action(self, state, perspective):
        from app.services.agents.base import own_active_units
        action = super().choose_action(state, perspective)
        if own_active_units(state, perspective) and action is None:
            self.violations.append("skipped activation")
        self._check(state, perspective, action, is_cont=False)
        return action

    def continue_activation(self, state, perspective, unit_id, actions_taken):
        nxt = super().continue_activation(state, perspective, unit_id, actions_taken)
        if nxt is not None and nxt.unit_id != unit_id:
            self.violations.append("followup wrong unit")
        if nxt is None:
            actor = next((b for b in state.blobs if b.id == unit_id), None)
            if actor is not None and actor.models_alive > 0:
                self.violations.append("wasted continuation")
        self._check(state, perspective, nxt, is_cont=True, taken=actions_taken)
        return nxt


def test_v3_no_illegal_or_wasted_actions_in_matches():
    from app.services.agents.match import simulate_from_rosters
    from app.services.agents.random_player import RandomPlayer
    from app.services.engine.state import Objective as _Obj, Position as _Pos

    objs = [_Obj(id=i, position=_Pos(x, y)) for i, (x, y) in enumerate(
        [(18, 8), (54, 8), (36, 24), (18, 40), (54, 40)], start=1)]
    for seed in range(6):
        for opp in (RandomPlayer(5), PriorityV3Player()):
            auditor = _AuditingV3()
            simulate_from_rosters(_audit_rosters(), [auditor, opp], seed=seed, objectives=objs)
            assert auditor.violations == [], f"seed={seed} opp={type(opp).__name__}: {auditor.violations[:5]}"
