"""B3.6 — testy `app/services/engine/phases.py`.

Pokrywa: setup_phase, deployment_round, activation_phase (każda akcja),
Przegrupowanie pkt 20 (z passive Nieustraszony), round_end_phase (reset
Aktywowany + objective control + game over po round 4).
"""

from __future__ import annotations

import pytest

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.combat import STATUS_WYCZERPANY, WeaponProfile
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    EffectApplied,
    MoraleTestPassed,
    MoveExecuted,
    RoundEnded,
)
from app.services.engine.phases import (
    MAX_ROUND,
    OBJECTIVE_CONTROL_RANGE,
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_UFORTYFIKOWANY,
    ActivationContext,
    _regroup_test,
    activation_phase,
    deployment_round,
    round_end_phase,
    setup_phase,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    UnitBlob,
)


def make_roster(owner: int, units: list[dict]) -> dict:
    return {"owner_player": owner, "units": units}


def make_unit(
    unit_id: int,
    x: float = 0.0,
    y: float = 0.0,
    models: int = 5,
    toughness: int = 3,
    quality: int = 4,
    defense: int = 5,
    passives: tuple[str, ...] = (),
) -> dict:
    return {
        "id": unit_id,
        "position": (x, y),
        "models": models,
        "toughness": toughness,
        "quality": quality,
        "defense": defense,
        "passives": list(passives),
    }


# ---------------------------------------------------------------------------
# setup_phase
# ---------------------------------------------------------------------------


def test_setup_phase_builds_state():
    rosters = [
        make_roster(0, [make_unit(1)]),
        make_roster(1, [make_unit(2)]),
    ]
    state = setup_phase(rosters)
    assert state.round == 0
    assert state.active_player == 0  # default initiative
    assert len(state.blobs) == 2


def test_setup_phase_initiative_player():
    rosters = [
        make_roster(0, [make_unit(1)]),
        make_roster(1, [make_unit(2)]),
    ]
    state = setup_phase(rosters, initiative_player=1)
    assert state.active_player == 1


def test_setup_phase_with_objectives():
    rosters = [make_roster(0, [make_unit(1)]), make_roster(1, [make_unit(2)])]
    objectives = [Objective(id=1, position=Position(20, 20))]
    state = setup_phase(rosters, objectives=objectives)
    assert len(state.objectives) == 1
    assert state.objectives[0].id == 1


# ---------------------------------------------------------------------------
# deployment_round
# ---------------------------------------------------------------------------


def test_deployment_round_moves_units():
    rosters = [make_roster(0, [make_unit(1, x=0, y=0)]), make_roster(1, [make_unit(2)])]
    state = setup_phase(rosters)
    actions = [DeploymentAction(unit_id=1, position=Position(10, 10))]
    new_state, events = deployment_round(state, actions)
    assert any(isinstance(e, MoveExecuted) and e.move_type == "deploy" for e in events)
    blob1 = next(b for b in new_state.blobs if b.id == 1)
    assert blob1.position.x == 10
    assert blob1.position.y == 10


def test_deployment_round_increments_round_to_1():
    rosters = [make_roster(0, [make_unit(1)]), make_roster(1, [make_unit(2)])]
    state = setup_phase(rosters)
    assert state.round == 0
    new_state, _ = deployment_round(state, [])
    assert new_state.round == 1


def test_deployment_round_resets_activated_status():
    """Po deployment status Aktywowany jest zerowany przed pierwszą rundą."""
    rosters = [make_roster(0, [make_unit(1)]), make_roster(1, [make_unit(2)])]
    state = setup_phase(rosters)
    new_state, _ = deployment_round(state, [])
    for b in new_state.blobs:
        assert STATUS_AKTYWOWANY not in b.status_flags


# ---------------------------------------------------------------------------
# activation_phase — actions
# ---------------------------------------------------------------------------


def _basic_state(extra: tuple[str, ...] = ()) -> BattleState:
    rosters = [
        make_roster(0, [make_unit(1, x=0, y=0, passives=extra)]),
        make_roster(1, [make_unit(2, x=20, y=0)]),
    ]
    state = setup_phase(rosters)
    state, _ = deployment_round(state, [])
    return state


def test_activation_maneuver_updates_position_and_status():
    state = _basic_state()
    action = ManeuverAction(unit_id=1, target_position=Position(5, 0))
    new_state, events = activation_phase(state, action, DeterministicDice(42))
    blob = next(b for b in new_state.blobs if b.id == 1)
    assert blob.position.x == 5
    assert STATUS_AKTYWOWANY in blob.status_flags
    assert any(isinstance(e, MoveExecuted) for e in events)


def test_activation_defend_adds_ufortyfikowany():
    state = _basic_state()
    action = DefendAction(unit_id=1)
    new_state, events = activation_phase(state, action, DeterministicDice(42))
    blob = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_UFORTYFIKOWANY in blob.status_flags
    assert STATUS_AKTYWOWANY in blob.status_flags


def test_activation_defend_removes_pinned_status():
    """Pkt 22.b.v — Przyszpilony zostaje odrzucony gdy oddział staje się Ufortyfikowany."""
    rosters = [
        make_roster(0, [make_unit(1)]),
        make_roster(1, [make_unit(2, x=20)]),
    ]
    state = setup_phase(rosters)
    state, _ = deployment_round(state, [])
    # Manualnie ustaw status Przyszpilony
    pinned_blob = next(b for b in state.blobs if b.id == 1)
    from dataclasses import replace
    pinned_blob = replace(pinned_blob, status_flags=(STATUS_PRZYSZPILONY,))
    state = replace(
        state,
        blobs=tuple(pinned_blob if b.id == 1 else b for b in state.blobs),
    )
    new_state, _ = activation_phase(state, DefendAction(unit_id=1), DeterministicDice(42))
    blob = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_PRZYSZPILONY not in blob.status_flags
    assert STATUS_UFORTYFIKOWANY in blob.status_flags


def test_activation_shoot_emits_shot_resolved():
    from app.services.engine.events import ShotResolved

    state = _basic_state()
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    action = ShootAction(unit_id=1, target_id=2, weapon=weapon)
    new_state, events = activation_phase(state, action, DeterministicDice(42))
    assert any(isinstance(e, ShotResolved) for e in events)
    # Attacker dostaje Aktywowany
    attacker = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_AKTYWOWANY in attacker.status_flags


def test_activation_charge_emits_melee_events():
    from app.services.engine.events import MeleeResolved

    state = _basic_state()
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    action = ChargeAction(unit_id=1, target_id=2, weapon=weapon)
    new_state, events = activation_phase(state, action, DeterministicDice(42))
    assert any(isinstance(e, MeleeResolved) for e in events)


def test_activation_special_discard_exhausted():
    """SpecialAction(discard_exhausted) usuwa status Wyczerpany."""
    rosters = [make_roster(0, [make_unit(1)]), make_roster(1, [make_unit(2)])]
    state = setup_phase(rosters)
    state, _ = deployment_round(state, [])
    from dataclasses import replace
    blob = next(b for b in state.blobs if b.id == 1)
    blob = replace(blob, status_flags=(STATUS_WYCZERPANY,))
    state = replace(state, blobs=tuple(blob if b.id == 1 else b for b in state.blobs))
    new_state, events = activation_phase(
        state, SpecialAction(unit_id=1, ability_slug="discard_exhausted"),
        DeterministicDice(42),
    )
    blob = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_WYCZERPANY not in blob.status_flags
    assert any(isinstance(e, EffectApplied) for e in events)


def test_activation_unknown_action_raises():
    state = _basic_state()

    class FakeAction:
        unit_id = 1

    with pytest.raises(TypeError, match="Unknown action type"):
        activation_phase(state, FakeAction(), DeterministicDice(42))


# ---------------------------------------------------------------------------
# Przegrupowanie pkt 20
# ---------------------------------------------------------------------------


def test_regroup_skipped_when_no_wounds():
    """Pkt 20.a — bez ran nie ma testu Przegrupowania."""
    state = _basic_state()
    action = ManeuverAction(unit_id=1, target_position=Position(5, 0))
    _, events = activation_phase(state, action, DeterministicDice(42))
    assert not any(isinstance(e, MoraleTestPassed) for e in events)


def test_regroup_after_taking_wounds():
    """Pkt 20.a — oddział który otrzymał rany **w tej aktywacji** robi test.

    Post-B3.9.c (ADR-0045): trigger jest delta, nie cumulative. Test wywołuje
    `_regroup_test` bezpośrednio z `ActivationContext` zawierającym deltę,
    zamiast pre-stage `wounds_received` na blobie (co odpowiadałoby buggy
    pre-B3.9.c semantyce gdzie cumulative wounds z poprzednich aktywacji
    triggerowały test).
    """
    state = _basic_state()
    from dataclasses import replace
    # Symulacja: oddział OTRZYMAŁ 2 rany w tej aktywacji (np. po Ostrzale).
    # ActivationContext przekazuje deltę.
    blob = next(b for b in state.blobs if b.id == 1)
    state = replace(
        state,
        blobs=tuple(replace(b, wounds_received=2) if b.id == 1 else b for b in state.blobs),
    )
    context = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 2),),
        melee_combatants=frozenset(),
    )
    _, events, _ = _regroup_test(state, 1, context, DeterministicDice(42), sequence=1)
    assert any(isinstance(e, MoraleTestPassed) for e in events)


def test_regroup_skipped_for_cumulative_wounds_without_delta():
    """B3.9.c fix #1 regression: cumulative `wounds_received` z poprzednich
    aktywacji NIE triggeruje testu pkt 20.a — tylko delta tej aktywacji."""
    state = _basic_state()
    from dataclasses import replace
    state = replace(
        state,
        blobs=tuple(replace(b, wounds_received=2) if b.id == 1 else b for b in state.blobs),
    )
    # Maneuver — żadnych nowych ran w tej aktywacji.
    action = ManeuverAction(unit_id=1, target_position=Position(5, 0))
    _, events = activation_phase(state, action, DeterministicDice(42))
    assert not any(isinstance(e, MoraleTestPassed) for e in events)


def test_regroup_nieustraszony_reduces_test_count():
    """Nieustraszony (id 16) — -1 test Przegrupowania.

    Post-B3.9.c: test używa `_regroup_test` + `ActivationContext` z deltą
    zamiast pre-stage cumulative wounds + ManeuverAction (buggy proxy).
    """
    state_no = _basic_state()
    state_n = _basic_state(extra=("nieustraszony",))
    from dataclasses import replace
    state_no = replace(
        state_no,
        blobs=tuple(replace(b, wounds_received=2) if b.id == 1 else b for b in state_no.blobs),
    )
    state_n = replace(
        state_n,
        blobs=tuple(replace(b, wounds_received=2) if b.id == 1 else b for b in state_n.blobs),
    )
    context = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 2),),
        melee_combatants=frozenset(),
    )
    _, events_no, _ = _regroup_test(state_no, 1, context, DeterministicDice(42), sequence=1)
    _, events_n, _ = _regroup_test(state_n, 1, context, DeterministicDice(42), sequence=1)
    morale_no = next(e for e in events_no if isinstance(e, MoraleTestPassed))
    morale_n_list = [e for e in events_n if isinstance(e, MoraleTestPassed)]
    if morale_n_list:
        assert len(morale_n_list[0].rolls) < len(morale_no.rolls)
    else:
        # Zero testów — nieustraszony zmniejszył do 0
        assert True


# ---------------------------------------------------------------------------
# round_end_phase
# ---------------------------------------------------------------------------


def test_round_end_resets_activated_status():
    """Pkt 8.c.i — wszystkie znaczniki Aktywowany usuwane."""
    state = _basic_state()
    from dataclasses import replace
    # Wymuś że niektóre bloby mają Aktywowany
    new_blobs = tuple(
        replace(b, status_flags=(STATUS_AKTYWOWANY,)) for b in state.blobs
    )
    state = replace(state, blobs=new_blobs)
    new_state, _ = round_end_phase(state)
    for b in new_state.blobs:
        assert STATUS_AKTYWOWANY not in b.status_flags


def test_round_end_increments_round():
    state = _basic_state()  # round=1 po deployment
    new_state, _ = round_end_phase(state)
    assert new_state.round == 2


def test_round_end_emits_round_ended_event():
    state = _basic_state()
    _, events = round_end_phase(state)
    assert any(isinstance(e, RoundEnded) for e in events)


def test_round_end_game_over_after_round_4():
    """Pkt 5.f — gra kończy się po rundzie 4."""
    state = _basic_state()
    from dataclasses import replace
    state = replace(state, round=MAX_ROUND)  # round=4
    new_state, _ = round_end_phase(state)
    assert new_state.is_game_over is True


def test_round_end_no_game_over_round_3():
    state = _basic_state()
    from dataclasses import replace
    state = replace(state, round=3)
    new_state, _ = round_end_phase(state)
    assert new_state.is_game_over is False
    assert new_state.round == 4


# ---------------------------------------------------------------------------
# Objective control pkt 5.d
# ---------------------------------------------------------------------------


def test_objective_unclaimed_when_no_units_nearby():
    obj = Objective(id=1, position=Position(50, 50))
    rosters = [make_roster(0, [make_unit(1, x=0, y=0)]), make_roster(1, [make_unit(2, x=10, y=0)])]
    state = setup_phase(rosters, objectives=[obj])
    state, _ = deployment_round(state, [])
    new_state, _ = round_end_phase(state)
    obj_after = new_state.objectives[0]
    assert obj_after.controller is None


def test_objective_claimed_by_only_player_nearby():
    """Pkt 5.d — gdy tylko 1 gracz w 3″ od celu, ten gracz kontroluje."""
    obj = Objective(id=1, position=Position(0, 0))
    rosters = [
        make_roster(0, [make_unit(1, x=0, y=0, models=1)]),  # przy celu
        make_roster(1, [make_unit(2, x=50, y=50)]),  # daleko
    ]
    state = setup_phase(rosters, objectives=[obj])
    state, _ = deployment_round(state, [])
    new_state, _ = round_end_phase(state)
    obj_after = new_state.objectives[0]
    assert obj_after.controller == 0
    assert new_state.score == (1, 0)


def test_objective_disputed_keeps_previous_controller():
    """Pkt 5.d — gdy obaj gracze w 3″, cel pozostaje zajęty (poprzedni kontroler)."""
    obj = Objective(id=1, position=Position(0, 0), controller=0)
    rosters = [
        make_roster(0, [make_unit(1, x=0, y=0, models=1)]),  # przy celu
        make_roster(1, [make_unit(2, x=1, y=0, models=1)]),  # też przy celu
    ]
    state = setup_phase(rosters, objectives=[obj])
    state, _ = deployment_round(state, [])
    new_state, _ = round_end_phase(state)
    obj_after = new_state.objectives[0]
    # Disputed → pozostaje 0 (previous controller)
    assert obj_after.controller == 0


def test_objective_pinned_unit_does_not_control():
    """Pkt 22.b.ii — Przyszpilony oddział nie kontroluje celów."""
    obj = Objective(id=1, position=Position(0, 0))
    rosters = [
        make_roster(0, [make_unit(1, x=0, y=0, models=1)]),
    ]
    state = setup_phase(rosters, objectives=[obj])
    state, _ = deployment_round(state, [])
    from dataclasses import replace
    blob = next(b for b in state.blobs if b.id == 1)
    blob = replace(blob, status_flags=(STATUS_PRZYSZPILONY,))
    state = replace(state, blobs=(blob,))
    new_state, _ = round_end_phase(state)
    assert new_state.objectives[0].controller is None
