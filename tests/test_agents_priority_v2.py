"""D — testy `PriorityV2Player` (selekcja wielokryterialna + target + przechwyt)."""

from __future__ import annotations

from app.services.agents.priority_v2_player import PriorityV2Player
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
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_WYCZERPANY,
)

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
SWORD = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)


def _blob(uid: int, owner: int, x: float, y: float, **kw) -> UnitBlob:
    defaults: dict = {
        "id": uid,
        "owner_player": owner,
        "position": Position(x, y),
        "radius_inches": 1.0,
        "models_alive": 5,
        "toughness_per_model": 3,
    }
    defaults.update(kw)
    return UnitBlob(**defaults)


def _state(blobs: tuple[UnitBlob, ...], objectives: tuple = ()) -> BattleState:
    return BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=blobs, terrain=(), objectives=objectives,
    )


# --- selekcja aktywacji ---


def test_selection_prefers_healthy_own_unit():
    pinned = _blob(1, 0, 0, 0, status_flags=(STATUS_PRZYSZPILONY,))
    healthy = _blob(2, 0, 0, 2)
    enemy = _blob(3, 1, 30, 0)
    action = PriorityV2Player().choose_action(_state((pinned, healthy, enemy)), 0)
    assert action is not None and action.unit_id == 2  # zdrowy wybrany mimo zbliższego pinned


def test_selection_prefers_unit_closest_to_non_activated_enemy():
    own1 = _blob(1, 0, 0, 0)
    own2 = _blob(2, 0, 20, 0)
    enemy_active = _blob(3, 1, 25, 0, status_flags=(STATUS_AKTYWOWANY,))  # blisko own2, ale aktywowany
    enemy_fresh = _blob(4, 1, 5, 0)  # blisko own1, nieaktywowany
    action = PriorityV2Player().choose_action(_state((own1, own2, enemy_active, enemy_fresh)), 0)
    assert action is not None and action.unit_id == 1  # bliżej nieaktywowanego wroga


# --- wybór celu ataku ---


def test_target_prefers_healthy_enemy():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    exhausted = _blob(2, 1, 8, 0, status_flags=(STATUS_WYCZERPANY,))  # bliżej, ale Wyczerpany
    healthy = _blob(3, 1, 10, 0)
    action = PriorityV2Player().choose_action(_state((own, exhausted, healthy)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 3


def test_target_prefers_non_activated_enemy():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    activated = _blob(2, 1, 8, 0, status_flags=(STATUS_AKTYWOWANY,))  # bliżej, aktywowany
    fresh = _blob(3, 1, 10, 0)
    action = PriorityV2Player().choose_action(_state((own, activated, fresh)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 3


def test_target_tie_breaks_by_nearest():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    near = _blob(2, 1, 8, 0)
    far = _blob(3, 1, 14, 0)  # identyczne staty → decyduje dystans
    action = PriorityV2Player().choose_action(_state((own, near, far)), 0)
    assert isinstance(action, ShootAction) and action.target_id == 2


# --- priorytet akcji ---


def test_priority1_discard_exhausted_before_shoot():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,), status_flags=(STATUS_WYCZERPANY,))
    enemy = _blob(2, 1, 8, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, SpecialAction) and action.ability_slug == "discard_exhausted"


def test_priority3_charge_when_no_shoot():
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))
    enemy = _blob(2, 1, 3, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ChargeAction) and action.target_id == 2


def test_charge_target_ignores_cover_pkt19():
    """Szarża (melee) nie uwzględnia osłony (pkt 19 = Ostrzał): silnik melee nie
    liczy `compute_cover`. Cel za zasłoną Obronną i identyczny bez zasłony,
    w równym dystansie, mają równą wagę → tie-break po id (covered = niższe id).
    Przed fixem osłona zaniżała `mean` covered-celu → wybierany byłby uncovered."""
    own = _blob(1, 0, 0, 0, melee_weapons=(SWORD,))  # tylko melee → krok 3 Szarża
    covered = _blob(2, 1, 4, 0)  # niższe id, w terenie Obronnym (osłona)
    uncovered = _blob(3, 1, 0, 4)  # równy dystans (4), bez osłony
    terrain = (TerrainCircle(center=Position(4, 0), radius_inches=3, features=("Obronny",)),)
    state = BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=(own, covered, uncovered), terrain=terrain, objectives=(),
    )
    action = PriorityV2Player().choose_action(state, 0)
    assert isinstance(action, ChargeAction)
    assert action.target_id == 2  # osłona ignorowana → tie-break id → covered (id 2)


def test_priority5_moves_to_uncontrolled_objective_it_is_closest_to():
    own = _blob(1, 0, 0, 0)
    obj = Objective(id=1, position=Position(10, 0), controller=None)
    enemy = _blob(2, 1, 60, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy), (obj,)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, obj.position) < distance(own.position, obj.position)


def test_priority6_intercept_enemy_threatening_held_objective():
    # Cel O zajęty przez nas; wróg bliżej O niż my (i nie na O) → ruch przechwytujący.
    own = _blob(1, 0, 25, 0)
    obj = Objective(id=1, position=Position(10, 0), controller=0)  # nasz
    enemy = _blob(2, 1, 15, 0)  # bliżej O (5<15), edge 4>3 (nie zajmuje), brak broni → nie strzelamy
    state = _state((own, enemy), (obj,))
    action = PriorityV2Player().choose_action(state, 0)
    assert isinstance(action, ManeuverAction)
    # Rusza ku wrogowi (maleje dystans do wroga).
    assert distance(action.target_position, enemy.position) < distance(own.position, enemy.position)


def test_priority8_moves_to_nearest_enemy_when_no_objective():
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 30, 0)
    action = PriorityV2Player().choose_action(_state((own, enemy)), 0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, enemy.position) < distance(own.position, enemy.position)


# --- continue_activation ---


def test_continue_activation_after_shoot_moves():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 30, 0)
    obj = Objective(id=1, position=Position(20, 0), controller=None)
    taken = (ShootAction(1, 2, RIFLE),)
    nxt = PriorityV2Player().continue_activation(_state((own, enemy), (obj,)), 0, 1, taken)
    assert isinstance(nxt, ManeuverAction)  # po strzale schodzi do celu, nie marnuje


def test_deterministic_choice():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    state = _state((own, enemy))
    assert PriorityV2Player().choose_action(state, 0) == PriorityV2Player().choose_action(state, 0)


# --- audyt legalności w pełnych grach (brak niedozwolonych celów / pomijania /
#     marnowania akcji) ---


def _audit_rosters() -> list[dict]:
    """2v2 z bronią dystansową+wręcz, by uruchomić Ostrzał/Szarżę/ruch/cele."""
    def u(uid, x, y, weapons):
        return {"id": uid, "position": (x, y), "models": 5, "toughness": 3,
                "quality": 4, "defense": 5, "passives": [], "weapons": weapons}
    rifle = {"slug": "rifle", "name": "R", "range_inches": 24, "attacks": 2}
    sword = {"slug": "sword", "name": "S", "range_inches": 0, "attacks": 2}
    return [
        {"owner_player": 0, "units": [u(1, 18, 12, [rifle]), u(2, 30, 12, [sword])]},
        {"owner_player": 1, "units": [u(3, 18, 36, [rifle]), u(4, 30, 36, [sword])]},
    ]


class _AuditingV2(PriorityV2Player):
    """Wrapper rejestrujący naruszenia: niedozwolony cel, pominięta aktywacja,
    zmarnowana/niedozwolona kontynuacja."""

    def __init__(self):
        self.violations: list[str] = []

    def _check_action(self, state, perspective, action, *, is_cont, taken=()):
        from app.services.agents.base import _can_charge, _can_shoot, _move_inches
        from app.services.engine.resolver import _can_take_followup
        from app.services.engine.status import STATUS_AKTYWOWANY

        if action is None:
            return
        actor = next((b for b in state.blobs if b.id == action.unit_id), None)
        if actor is None or actor.owner_player != perspective or actor.models_alive == 0:
            self.violations.append(f"bad actor {action}")
            return
        if STATUS_AKTYWOWANY in actor.status_flags:
            self.violations.append(f"actor already activated {action}")
        if isinstance(action, ShootAction):
            t = next((b for b in state.blobs if b.id == action.target_id), None)
            if t is None or t.owner_player == perspective or not _can_shoot(actor, t, action.weapon, state.terrain):
                self.violations.append(f"illegal shoot target {action}")
        if isinstance(action, ChargeAction):
            t = next((b for b in state.blobs if b.id == action.target_id), None)
            if t is None or t.owner_player == perspective or not _can_charge(actor, t, _move_inches()):
                self.violations.append(f"illegal charge target {action}")
        if is_cont and not _can_take_followup(action, taken):
            self.violations.append(f"illegal followup {action}")

    def choose_action(self, state, perspective):
        from app.services.agents.base import own_active_units

        action = super().choose_action(state, perspective)
        if own_active_units(state, perspective) and action is None:
            self.violations.append("skipped activation with units available")
        self._check_action(state, perspective, action, is_cont=False)
        return action

    def continue_activation(self, state, perspective, unit_id, actions_taken):
        nxt = super().continue_activation(state, perspective, unit_id, actions_taken)
        if nxt is not None and nxt.unit_id != unit_id:
            self.violations.append("followup for wrong unit")
        if nxt is None:
            actor = next((b for b in state.blobs if b.id == unit_id), None)
            if actor is not None and actor.models_alive > 0:
                self.violations.append("wasted continuation (None with unit alive)")
        self._check_action(state, perspective, nxt, is_cont=True, taken=actions_taken)
        return nxt


def test_v2_no_illegal_targets_or_wasted_actions_in_matches():
    from app.services.agents.match import simulate_from_rosters
    from app.services.agents.priority_player import PriorityPlayer
    from app.services.agents.random_player import RandomPlayer
    from app.services.engine.state import Objective as _Obj, Position as _Pos

    objs = [
        _Obj(id=1, position=_Pos(18, 8)), _Obj(id=2, position=_Pos(54, 8)),
        _Obj(id=3, position=_Pos(36, 24)), _Obj(id=4, position=_Pos(18, 40)),
        _Obj(id=5, position=_Pos(54, 40)),
    ]
    # Różni przeciwnicy → różnorodne stany (ranni/Przyszpileni/Wyczerpani wrogowie,
    # rozproszenie) stresują wybór celu i kontynuacje.
    opponents = [RandomPlayer(7), PriorityV2Player(), PriorityPlayer()]
    for seed in range(6):
        for opp in opponents:
            auditor = _AuditingV2()
            simulate_from_rosters(_audit_rosters(), [auditor, opp], seed=seed, objectives=objs)
            assert auditor.violations == [], f"seed={seed} opp={type(opp).__name__}: {auditor.violations[:5]}"
