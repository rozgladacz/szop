"""Diagnostic invariants and explicit reproductions for the D6.1 audit."""
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from app.services.agents.factory import make_player
from app.services.agents.registry import ALL_KINDS
from app.services.engine.actions import ChargeAction, DefendAction, ManeuverAction, ShootAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.resolver import apply, apply_activation, IllegalActionError
from app.services.engine.state import Lokalizacja, Position, TerrainLine, apply_events
from app.services.engine.state_codec import battle_state_to_json, battle_state_from_json

_SPEC = importlib.util.spec_from_file_location("bots_audit", Path(__file__).parents[1] / "scripts/bots_audit.py")
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_audit_public_state_decision_and_continuation_replay(kind):
    first = audit.decision_once(kind, 19, "ranged")
    repeated = audit.decision_once(kind, 19, "ranged")
    assert first["public_roundtrip"] and first["input_unchanged"]
    assert first["resolver_accepted"] and first["replay_equal"]
    assert 1 <= len(first["applied"]) <= 2
    assert all(r["same_unit"] and r["append_allowed"] for r in first["requested"])
    assert audit.deterministic(first) == audit.deterministic(repeated)


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize(("scenario", "forbidden", "reason"), [
    ("contact", (ShootAction,), "visible_enemy_within_2in"),
    ("exhausted", (ShootAction, ChargeAction), "attack_while_exhausted"),
    ("pinned", (ManeuverAction,), "maneuver_while_pinned"),
])
def test_d61_reproductions_are_excluded_by_bot_and_resolver(kind, scenario, forbidden, reason):
    state = audit.scenario(scenario)
    actor, target = state.blobs
    illegal = {
        ShootAction: ShootAction(actor.id, target.id, actor.ranged_weapons[0]),
        ChargeAction: ChargeAction(actor.id, target.id, actor.melee_weapons[0]),
        ManeuverAction: ManeuverAction(actor.id, Position(2, 0)),
    }
    player = make_player(kind, 19)
    assert not isinstance(player.choose_action(state, 0), forbidden)
    assert not isinstance(player.continue_activation(state, 0, actor.id, (DefendAction(actor.id),)), forbidden)
    before = battle_state_to_json(state)
    dice = DeterministicDice(19)
    rng_before = dice.to_checkpoint()
    for action_type in forbidden:
        with pytest.raises(IllegalActionError) as exc:
            apply(state, illegal[action_type], dice)
        assert exc.value.code == reason
        assert battle_state_to_json(state) == before
        assert dice.to_checkpoint() == rng_before


@pytest.mark.parametrize(("distance", "hidden", "role", "locked"), [
    (2.999, False, "enemy", True),
    (3.0, False, "enemy", True),  # Edge to edge: 3 - 0.5 - 0.5.
    (3.001, False, "enemy", False),
    (3.0, True, "enemy", False),
    (3.0, False, "ally", False),
    (3.0, False, "reserve", False),
    (3.0, False, "defeated", False),
])
def test_shoot_lock_considers_every_visible_live_enemy_on_the_front(distance, hidden, role, locked):
    state = audit.scenario("ranged")
    attacker, target = state.blobs
    nearby = replace(target, id=3, position=Position(0, distance))
    if role == "ally":
        nearby = replace(nearby, owner_player=0)
    elif role == "reserve":
        nearby = replace(nearby, location=Lokalizacja.ZAPLECZE)
    elif role == "defeated":
        nearby = replace(nearby, models_alive=0, location=Lokalizacja.WYCOFANY)
    wall = TerrainLine(Position(-4, 1.5), Position(4, 1.5), ("Blokujacy",))
    state = replace(state, blobs=(attacker, target, nearby), terrain=(wall,) if hidden else ())
    # Niebezpośredni waives target LoS (Zdolności 62), so the close-enemy
    # restriction (Rozjemca 14.c.iv) still applies to the action.
    weapon = replace(attacker.ranged_weapons[0], weapon_abilities=("niebezposredni",))
    action = ShootAction(attacker.id, target.id, weapon)
    if locked:
        with pytest.raises(IllegalActionError) as exc:
            apply(state, action, DeterministicDice(19))
        assert exc.value.code == "visible_enemy_within_2in"
    else:
        result = apply(state, action, DeterministicDice(19))
        assert apply_events(state, result.events) == result.state


def test_illegal_followup_preserves_completed_first_action_and_its_rng():
    state = audit.scenario("exhausted")
    actor, target = state.blobs
    first = DefendAction(actor.id)
    second = ShootAction(actor.id, target.id, actor.ranged_weapons[0])
    dice = DeterministicDice(19)
    expected_dice = DeterministicDice(19)
    observations = []
    expected = apply(state, first, expected_dice)
    result = apply_activation(
        state, first, dice, continuation=lambda *_: second,
        on_observation=observations.append,
    )
    assert result == expected
    assert dice.to_checkpoint() == expected_dice.to_checkpoint()
    rejected = next(row for row in observations if row.kind == "continue_activation")
    assert rejected.outcome == "rejected"
    assert rejected.reason == "attack_while_exhausted"


def test_terminal_state_must_be_guarded_by_adapter_even_with_existing_bot():
    state = audit.scenario("game_over")
    action = make_player("priority", 19).choose_action(state, 0)
    assert action is not None
    with pytest.raises(IllegalActionError, match="Game is over"):
        apply(state, action, DeterministicDice(19))


def test_wrong_perspective_must_be_guarded_by_adapter():
    state = audit.scenario("ranged")
    action = make_player("priority", 19).choose_action(state, 1)
    with pytest.raises(IllegalActionError, match="active_player"):
        apply(state, action, DeterministicDice(19))


def test_order_and_reflection_counterexamples_do_not_claim_match_causality():
    observed = audit.symmetry_probe()
    assert observed["objective_order_changes_action"]
    assert not observed["grid_reflection_preserves_id_slots"]
    assert observed["objective_edge_controller"] == 0


@pytest.mark.parametrize("strategy", ["default", "grid", "objectives"])
def test_narrow_polygon_deployment_reuses_shared_validator(strategy):
    observed = audit.deployment_once("priority", 19, strategy, True)
    assert observed["status"] == "legal"
    assert len(observed["positions"]) == 4


def test_public_v2_codec_does_not_turn_legacy_decision_into_lifecycle():
    state = replace(audit.scenario("ranged"), initiative_player=0)
    state = battle_state_from_json(battle_state_to_json(state, version=2))
    action = make_player("priority", 19).choose_action(state, 0)
    # Legacy apply accepts it without start/pass/commit; persistence must not
    # serialize its remaining durable initiative as a v1 checkpoint.
    resolved = apply(state, action, DeterministicDice(19))
    assert resolved.state.activation is None
    with pytest.raises(ValueError, match="v1 checkpoint"):
        battle_state_to_json(resolved.state)


@pytest.mark.parametrize("name", ["contact", "exhausted", "pinned", "polygon_detour", "wall_blocked", "objective_edge", "last_round", "game_over"])
def test_audit_scenarios_are_valid_public_roundtrips(name):
    state = audit.scenario(name)
    assert battle_state_from_json(battle_state_to_json(state)) == state


def test_full_fixture_audit_replays_actual_match():
    result = audit.fixture_once("priority", "tests/fixtures/battles/demo_skirmish.yaml")
    assert result["status"] == "complete"
    assert result["replay_equal"]
