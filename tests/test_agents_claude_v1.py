"""D — testy `ClaudeV1Player` (depth-1 ogólny: gradient celów + dobijanie).

Sprawdza: brak akcji → None, atak > pasywne, determinizm, marsz na cel (gradient),
**bonus dobijania** (p_full_kill×ELIM premiuje wymiatalny cel), 2. akcja move-then-shoot,
osłona tylko Ostrzał (pkt 19), oraz legalność na pełnej grze (audyt).
"""

from __future__ import annotations

from app.services.agents.claude_v1_player import ClaudeV1Player
from app.services.engine.actions import ChargeAction, ManeuverAction, ShootAction
from app.services.engine.geometry import distance
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    TerrainCircle,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_AKTYWOWANY

RIFLE = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=3)
SWORD = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=3)
STRONG = WeaponProfile(slug="cannon", name="Cannon", range_inches=24, attacks=6)


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
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        objectives=objectives,
    )


def test_returns_none_when_no_actions():
    blobs = (_blob(1, 0, 0, 0, status_flags=(STATUS_AKTYWOWANY,)),)
    assert ClaudeV1Player().choose_action(_state(blobs), perspective=0) is None


def test_prefers_attack_over_passive():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    action = ClaudeV1Player().choose_action(_state(blobs), perspective=0)
    assert isinstance(action, ShootAction) and action.target_id == 2


def test_deterministic_choice():
    blobs = (_blob(1, 0, 0, 0, ranged_weapons=(RIFLE,)), _blob(2, 1, 10, 0))
    state = _state(blobs)
    assert ClaudeV1Player().choose_action(state, 0) == ClaudeV1Player().choose_action(state, 0)


def test_marches_toward_far_objective_via_gradient():
    # Cel daleko (15″ > move 6″, poza horyzontem kontroli 3″). Gradient marszu
    # ciągnie oddział ku celowi mimo że kontrola nie zmieni się w tym ruchu.
    own = _blob(1, 0, 0, 0)  # bez broni → tylko Manewr/Obrona
    obj = Objective(id=1, position=Position(15, 0), controller=None)
    action = ClaudeV1Player().choose_action(_state((own,), (obj,)), perspective=0)
    assert isinstance(action, ManeuverAction)
    assert distance(action.target_position, obj.position) < distance(own.position, obj.position)


def test_finishing_bonus_prefers_wipeable_target():
    # Dwa 1-modelowe cele, identyczne poza wytrzymałością: T1 (wymiatalny,
    # p_full_kill≈1) vs T20 (niewymiatalny). Bonus dobijania (p_full_kill×ELIM)
    # czyni score wymiatalnego wyższym przy równych obrażeniach/pozycji.
    attacker = _blob(1, 0, 0, 0, ranged_weapons=(STRONG,))
    wipeable = _blob(2, 1, 5, 0, models_alive=1, toughness_per_model=1)
    tanky = _blob(3, 1, 5, 0, models_alive=1, toughness_per_model=20)
    c = ClaudeV1Player()
    s_wipe = c._attack_score(_state((attacker, wipeable)), 0, ShootAction(1, 2, STRONG), 0.0)
    s_tank = c._attack_score(_state((attacker, tanky)), 0, ShootAction(1, 3, STRONG), 0.0)
    assert s_wipe > s_tank


def test_continue_activation_move_then_shoot():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    enemy = _blob(2, 1, 8, 0)
    nxt = ClaudeV1Player().continue_activation(
        _state((own, enemy)), 0, 1, (ManeuverAction(1, Position(0, 0)),)
    )
    assert isinstance(nxt, ShootAction)


def test_continue_activation_none_when_nothing_beneficial():
    own = _blob(1, 0, 0, 0, ranged_weapons=(RIFLE,))
    assert ClaudeV1Player().continue_activation(
        _state((own,)), 0, 1, (ManeuverAction(1, Position(0, 0)),)
    ) is None


def test_charge_score_ignores_cover_pkt19():
    own = _blob(1, 0, 0, 0)
    enemy = _blob(2, 1, 4, 0)
    cover = (TerrainCircle(center=Position(4, 0), radius_inches=3, features=("Obronny",)),)
    c = ClaudeV1Player()

    def _score(terrain, action):
        st = BattleState(
            round=1, active_player=0, activations_remaining=(1, 1),
            blobs=(own, enemy), terrain=terrain, objectives=(),
        )
        return c._attack_score(st, 0, action, 0.0)

    charge = ChargeAction(unit_id=1, target_id=2, weapon=SWORD)
    shoot = ShootAction(unit_id=1, target_id=2, weapon=RIFLE)
    assert _score(cover, charge) == _score((), charge)   # melee: osłona ignorowana
    assert _score(cover, shoot) < _score((), shoot)       # ostrzał: osłona obniża


def test_full_game_legality_audit():
    # Claude vs Claude na realnej geometrii — gra kończy się bez IllegalActionError.
    from app.services.agents import simulate_from_rosters

    def _roster(owner: int, y: float):
        return {
            "owner_player": owner,
            "units": [
                {"id": owner * 10 + i, "position": (10.0 + i * 8, y),
                 "models": 5, "toughness": 3, "quality": 4, "defense": 5,
                 "passives": [], "weapons": [
                     {"slug": "rifle", "name": "Rifle", "range_inches": 24, "attacks": 3, "ap": 0}]}
                for i in range(2)
            ],
        }

    objectives = (
        Objective(id=1, position=Position(36, 24), controller=None),
        Objective(id=2, position=Position(24, 24), controller=None),
    )
    result = simulate_from_rosters(
        [_roster(0, 12.0), _roster(1, 36.0)],
        [ClaudeV1Player(), ClaudeV1Player()],
        seed=3, objectives=objectives,
    )
    assert result.rounds_played >= 1
    assert result.winner in (0, 1, None)
