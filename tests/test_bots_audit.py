"""Diagnostic invariants and explicit reproductions for the D6.1 audit."""
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from app.services.agents.factory import make_player
from app.services.agents.registry import ALL_KINDS
from app.services.engine.actions import ShootAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.resolver import apply, IllegalActionError
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


def test_contact_shoot_is_resolver_accepted_but_not_a_rule_conformity_proof():
    # Deliberate reproduction of current limitation, not endorsement of it:
    # canonical Rozjemca 14.c.iv forbids this visible close-enemy Shoot.
    state = audit.scenario("contact")
    action = make_player("priority", 19).choose_action(state, 0)
    assert isinstance(action, ShootAction)
    assert apply(state, action, DeterministicDice(19)).events


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
