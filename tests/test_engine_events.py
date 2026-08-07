"""B3.0.5 — testy `app/services/engine/events.py`.

Pokrywa: serializacja round-trip dla 8 typów eventów (ADR-0010), schema
versioning, error handling w `json_to_event`, preserving tuple fields przez
JSON (tuple → list → tuple).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.events import (
    SCHEMA_VERSION,
    ActivePlayerChanged,
    AttackAbilityOverrideApplied,
    AttackDeclared,
    AttackInterruptPriorityPassed,
    AttackInterruptTriggered,
    AttackInterruptWindowClosed,
    AttackInterruptWindowOpened,
    AttackResolved,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    BattleEvent,
    EffectApplied,
    InterruptTriggered,
    InterruptPriorityPassed,
    InterruptWindowClosed,
    InterruptWindowOpened,
    InitiativePassed,
    InitiativeTransferred,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    RoundEnded,
    ShotResolved,
    event_to_json,
    json_to_event,
)
from app.services.engine.state import ChargeAttackIntent, ShootAttackIntent


# ---------------------------------------------------------------------------
# Frozen — 8 event types
# ---------------------------------------------------------------------------


def test_move_executed_is_frozen():
    e = MoveExecuted(sequence=1, unit_id=1, from_pos=(0.0, 0.0), to_pos=(1.0, 0.0))
    with pytest.raises(FrozenInstanceError):
        e.sequence = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# event_to_json — basic
# ---------------------------------------------------------------------------


def test_event_to_json_includes_event_type():
    e = MoveExecuted(sequence=1, unit_id=42, from_pos=(0.0, 0.0), to_pos=(6.0, 0.0))
    payload = event_to_json(e)
    assert payload["event_type"] == "MoveExecuted"
    assert payload["sequence"] == 1
    assert payload["unit_id"] == 42
    assert payload["version"] == SCHEMA_VERSION


def test_event_to_json_raises_for_non_event():
    class NotAnEvent:
        pass

    with pytest.raises(TypeError):
        event_to_json(NotAnEvent())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# json_to_event — error handling
# ---------------------------------------------------------------------------


def test_json_to_event_missing_type_raises():
    with pytest.raises(ValueError, match="event_type"):
        json_to_event({"sequence": 1, "unit_id": 1})


def test_json_to_event_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown event type"):
        json_to_event({"event_type": "FooBar", "sequence": 1})


# ---------------------------------------------------------------------------
# Round-trip — 8 typów (parametrized)
# ---------------------------------------------------------------------------


@pytest.fixture
def all_event_samples() -> list[BattleEvent]:
    """Po jednym przykładzie każdego z 8 event types — z reprezentatywnymi polami."""
    return [
        MoveExecuted(
            sequence=1,
            unit_id=10,
            from_pos=(0.0, 0.0),
            to_pos=(6.0, 0.0),
            move_type="manever",
        ),
        ShotResolved(
            sequence=2,
            attacker_id=10,
            defender_id=20,
            weapon_slug="ap_2_lance",
            hits=3,
            wounds_dealt=2,
            wounds_precise=1,
        ),
        MeleeResolved(
            sequence=3,
            attacker_id=20,
            defender_id=10,
            weapon_slug="brutalny",
            hits=4,
            wounds_dealt=3,
            charger_id=20,
        ),
        ModelKilled(
            sequence=4,
            unit_id=10,
            model_index=2,
            is_hero=False,
            by_attacker_id=20,
        ),
        MoraleTestPassed(
            sequence=5,
            unit_id=10,
            rolls=(3, 5, 2),
            failures=1,
            result_status="exhausted",
        ),
        EffectApplied(
            sequence=6,
            slug="furia",
            target_unit_id=10,
            source_unit_id=10,
            payload={"trigger": "natural_6_on_charge"},
        ),
        InterruptTriggered(
            sequence=7,
            interrupt_point="before_regroup",
            slug="straznik",
            source_unit_id=30,
            target_unit_id=10,
            payload={"weapon_used": "rifle"},
        ),
        RoundEnded(
            sequence=8,
            round_number=1,
            objectives_held=(2, 3),
        ),
    ]


def test_all_event_types_round_trip(all_event_samples):
    """event_to_json → json_to_event zwraca równy event dla wszystkich 8 typów."""
    for original in all_event_samples:
        payload = event_to_json(original)
        restored = json_to_event(payload)
        assert restored == original, (
            f"Round-trip failed for {type(original).__name__}: "
            f"original={original}, restored={restored}"
        )


def test_round_trip_through_json_string(all_event_samples):
    """Pełny cykl: event → dict → json.dumps → json.loads → event."""
    for original in all_event_samples:
        payload = event_to_json(original)
        json_str = json.dumps(payload)
        loaded = json.loads(json_str)
        restored = json_to_event(loaded)
        assert restored == original


def test_tuple_fields_preserved_through_json():
    """`rolls` jako tuple → list w JSON → tuple ponownie."""
    e = MoraleTestPassed(
        sequence=1, unit_id=1, rolls=(1, 2, 3, 4), failures=2, result_status="pinned"
    )
    payload = event_to_json(e)
    json_str = json.dumps(payload)
    loaded = json.loads(json_str)
    restored = json_to_event(loaded)
    assert isinstance(restored.rolls, tuple)
    assert restored.rolls == (1, 2, 3, 4)


def test_objectives_held_tuple_preserved():
    e = RoundEnded(sequence=1, round_number=1, objectives_held=(2, 3))
    restored = json_to_event(event_to_json(e))
    assert isinstance(restored.objectives_held, tuple)
    assert restored.objectives_held == (2, 3)


def test_mutex_collision_round_trip():
    """R5.e (resync 2026-06): MutexCollision round-trip — `dropped_statuses`
    tuple[str] przez JSON (tuple → list → tuple)."""
    from app.services.engine.events import MutexCollision

    e = MutexCollision(
        sequence=9,
        target_id=3,
        dropped_statuses=("Przyszpilony", "Przygotowany"),
    )
    payload = event_to_json(e)
    assert payload["event_type"] == "MutexCollision"
    json_str = json.dumps(payload)
    restored = json_to_event(json.loads(json_str))
    assert restored == e
    assert isinstance(restored.dropped_statuses, tuple)
    assert restored.dropped_statuses == ("Przyszpilony", "Przygotowany")


def test_event_default_version_is_schema_version():
    """Default `version` field = SCHEMA_VERSION (kompatybilność wsteczna)."""
    e = MoveExecuted(sequence=1, unit_id=1, from_pos=(0.0, 0.0), to_pos=(1.0, 0.0))
    assert e.version == SCHEMA_VERSION


def test_effect_applied_with_empty_payload():
    """Default `payload={}` survives round-trip."""
    e = EffectApplied(sequence=1, slug="nieustraszony", target_unit_id=5)
    restored = json_to_event(event_to_json(e))
    assert restored.payload == {}


def test_payload_dict_with_nested_data_preserved():
    """Złożony payload (nested dict) survives serialization."""
    e = EffectApplied(
        sequence=1,
        slug="mistrzostwo",
        target_unit_id=5,
        payload={"x": "ap_2", "metadata": {"source_weapon": "rifle"}},
    )
    payload = event_to_json(e)
    restored = json_to_event(json.loads(json.dumps(payload)))
    assert restored.payload == {"x": "ap_2", "metadata": {"source_weapon": "rifle"}}


PROTOCOL_EVENT_GOLDENS = (
    (
        ActivationStarted(101, 101, 1, 11, 0, 0),
        {
            "sequence": 101,
            "activation_id": 101,
            "activation_version": 1,
            "selected_unit_id": 11,
            "controlling_player": 0,
            "initiative_player": 0,
            "version": 1,
            "event_type": "ActivationStarted",
        },
    ),
    (
        InterruptWindowOpened(102, 101, 1, 1, 1, 0),
        {
            "sequence": 102,
            "activation_id": 101,
            "activation_version": 1,
            "window_ordinal": 1,
            "window_version": 1,
            "priority_player": 0,
            "version": 1,
            "event_type": "InterruptWindowOpened",
        },
    ),
    (
        ActivationInterruptTriggered(103, 101, 2, 1, 2, 0),
        {
            "sequence": 103,
            "activation_id": 101,
            "activation_version": 2,
            "window_ordinal": 1,
            "window_version": 2,
            "priority_player": 0,
            "version": 1,
            "event_type": "ActivationInterruptTriggered",
        },
    ),
    (
        InterruptPriorityPassed(104, 101, 3, 1, 3, 0, 1),
        {
            "sequence": 104,
            "activation_id": 101,
            "activation_version": 3,
            "window_ordinal": 1,
            "window_version": 3,
            "passed_player": 0,
            "next_priority_player": 1,
            "version": 1,
            "event_type": "InterruptPriorityPassed",
        },
    ),
    (
        InterruptWindowClosed(106, 101, 4, 1, 4),
        {
            "sequence": 106,
            "activation_id": 101,
            "activation_version": 4,
            "window_ordinal": 1,
            "window_version": 4,
            "version": 1,
            "event_type": "InterruptWindowClosed",
        },
    ),
    (
        ActivationActionCommitted(107, 101, 5, "defend"),
        {
            "sequence": 107,
            "activation_id": 101,
            "activation_version": 5,
            "action_type": "defend",
            "version": 1,
            "event_type": "ActivationActionCommitted",
        },
    ),
    (
        ActivationContinuationChosen(108, 101, 6, True),
        {
            "sequence": 108,
            "activation_id": 101,
            "activation_version": 6,
            "continue_activation": True,
            "version": 1,
            "event_type": "ActivationContinuationChosen",
        },
    ),
    (
        ActivationFinalized(109, 101),
        {
            "sequence": 109,
            "activation_id": 101,
            "version": 1,
            "event_type": "ActivationFinalized",
        },
    ),
    (
        InitiativeTransferred(110, 101, 0, 1),
        {
            "sequence": 110,
            "activation_id": 101,
            "previous_initiative_player": 0,
            "new_initiative_player": 1,
            "version": 1,
            "event_type": "InitiativeTransferred",
        },
    ),
    (
        ActivePlayerChanged(111, 101, 0, 1),
        {
            "sequence": 111,
            "activation_id": 101,
            "previous_active_player": 0,
            "new_active_player": 1,
            "version": 1,
            "event_type": "ActivePlayerChanged",
        },
    ),
)


@pytest.mark.parametrize(
    ("event", "golden"),
    PROTOCOL_EVENT_GOLDENS,
    ids=lambda value: type(value).__name__ if not isinstance(value, dict) else None,
)
def test_protocol_event_v1_golden_json_round_trip(event, golden):
    assert event_to_json(event) == golden
    restored = json_to_event(json.loads(json.dumps(golden)))
    assert restored == event
    assert type(restored) is type(event)


def test_new_event_payloads_are_strict_without_changing_legacy_decoder():
    new_payload = event_to_json(PROTOCOL_EVENT_GOLDENS[0][0])

    with pytest.raises(ValueError, match="fields do not match"):
        json_to_event(new_payload | {"unexpected": True})
    with pytest.raises(ValueError, match="fields do not match"):
        json_to_event({key: value for key, value in new_payload.items() if key != "version"})
    with pytest.raises(ValueError, match="event version"):
        json_to_event(new_payload | {"version": 2})

    legacy_payload = {
        "event_type": "InitiativePassed",
        "sequence": 7,
        "previous_active_player": 0,
        "new_active_player": 1,
        "version": 1,
        "future_annotation": "ignored-as-before",
    }
    assert json_to_event(legacy_payload) == InitiativePassed(7, 0, 1)


def test_legacy_initiative_passed_tag_and_payload_are_unchanged():
    legacy = InitiativePassed(7, 0, 1)

    assert event_to_json(legacy) == {
        "sequence": 7,
        "previous_active_player": 0,
        "new_active_player": 1,
        "version": 1,
        "event_type": "InitiativePassed",
    }


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ActivationStarted(10, 9, 1, 11, 0, 0),
        lambda: InterruptWindowOpened(11, 10, 1, 1, 2, 0),
        lambda: InterruptPriorityPassed(12, 10, 2, 1, 2, 0, 0),
        lambda: ActivationActionCommitted(13, 10, 3, "invented"),
        lambda: ActivationContinuationChosen(14, 10, 4, 1),
        lambda: ActivationFinalized(15, 10, version=2),
    ],
)
def test_protocol_events_reject_inconsistent_schema_values(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


ATTACK_PROTOCOL_EVENT_GOLDENS = (
    (
        AttackDeclared(
            sequence=201,
            activation_id=101,
            activation_version=4,
            attack_id=201,
            attack_version=1,
            attack_ordinal=1,
            intent=ShootAttackIntent(11, 21, "rifle"),
        ),
        {
            "sequence": 201,
            "activation_id": 101,
            "activation_version": 4,
            "attack_id": 201,
            "attack_version": 1,
            "attack_ordinal": 1,
            "intent": {
                "attack_type": "shoot",
                "attacker_unit_id": 11,
                "target_unit_id": 21,
                "weapon_slug": "rifle",
            },
            "version": 1,
            "event_type": "AttackDeclared",
        },
    ),
    (
        AttackDeclared(
            sequence=301,
            activation_id=101,
            activation_version=4,
            attack_id=301,
            attack_version=1,
            attack_ordinal=1,
            intent=ChargeAttackIntent(11, 21, "sword", False),
        ),
        {
            "sequence": 301,
            "activation_id": 101,
            "activation_version": 4,
            "attack_id": 301,
            "attack_version": 1,
            "attack_ordinal": 1,
            "intent": {
                "attack_type": "charge",
                "attacker_unit_id": 11,
                "target_unit_id": 21,
                "weapon_slug": "sword",
                "counter_attack_declared": False,
            },
            "version": 1,
            "event_type": "AttackDeclared",
        },
    ),
    (
        AttackInterruptWindowOpened(202, 101, 4, 201, 1, 1, 1, 0),
        {
            "sequence": 202,
            "activation_id": 101,
            "activation_version": 4,
            "attack_id": 201,
            "attack_version": 1,
            "attack_ordinal": 1,
            "window_version": 1,
            "priority_player": 0,
            "version": 1,
            "event_type": "AttackInterruptWindowOpened",
        },
    ),
    (
        AttackInterruptTriggered(203, 101, 5, 201, 2, 1, 2, 0),
        {
            "sequence": 203,
            "activation_id": 101,
            "activation_version": 5,
            "attack_id": 201,
            "attack_version": 2,
            "attack_ordinal": 1,
            "window_version": 2,
            "priority_player": 0,
            "version": 1,
            "event_type": "AttackInterruptTriggered",
        },
    ),
    (
        AttackInterruptPriorityPassed(204, 101, 6, 201, 3, 1, 3, 0, 1),
        {
            "sequence": 204,
            "activation_id": 101,
            "activation_version": 6,
            "attack_id": 201,
            "attack_version": 3,
            "attack_ordinal": 1,
            "window_version": 3,
            "passed_player": 0,
            "next_priority_player": 1,
            "version": 1,
            "event_type": "AttackInterruptPriorityPassed",
        },
    ),
    (
        AttackInterruptWindowClosed(206, 101, 7, 201, 4, 1, 4),
        {
            "sequence": 206,
            "activation_id": 101,
            "activation_version": 7,
            "attack_id": 201,
            "attack_version": 4,
            "attack_ordinal": 1,
            "window_version": 4,
            "version": 1,
            "event_type": "AttackInterruptWindowClosed",
        },
    ),
    (
        AttackAbilityOverrideApplied(204, 101, 5, 201, 2, 1, 2, 11, 12, "furia"),
        {
            "sequence": 204,
            "activation_id": 101,
            "activation_version": 5,
            "attack_id": 201,
            "attack_version": 2,
            "attack_ordinal": 1,
            "window_version": 2,
            "attacker_unit_id": 11,
            "source_unit_id": 12,
            "ability_slug": "furia",
            "version": 1,
            "event_type": "AttackAbilityOverrideApplied",
        },
    ),
    (
        AttackResolved(207, 101, 8, 201, 5, 1),
        {
            "sequence": 207,
            "activation_id": 101,
            "activation_version": 8,
            "attack_id": 201,
            "attack_version": 5,
            "attack_ordinal": 1,
            "version": 1,
            "event_type": "AttackResolved",
        },
    ),
)


@pytest.mark.parametrize(
    ("event", "golden"),
    ATTACK_PROTOCOL_EVENT_GOLDENS,
    ids=lambda value: type(value).__name__ if not isinstance(value, dict) else None,
)
def test_attack_protocol_event_v1_golden_json_round_trip(event, golden) -> None:
    assert event_to_json(event) == golden
    restored = json_to_event(json.loads(json.dumps(golden)))
    assert restored == event
    assert type(restored) is type(event)


def test_attack_declaration_intent_codec_is_closed_and_exact() -> None:
    payload = event_to_json(ATTACK_PROTOCOL_EVENT_GOLDENS[0][0])

    with pytest.raises(ValueError, match="intent fields"):
        json_to_event(
            payload
            | {"intent": payload["intent"] | {"counter_attack_declared": False}}
        )
    with pytest.raises(ValueError, match="attack intent type"):
        json_to_event(payload | {"intent": payload["intent"] | {"attack_type": "x"}})
    with pytest.raises((TypeError, ValueError)):
        json_to_event(payload | {"intent": payload["intent"] | {"attacker_unit_id": True}})


def test_attack_protocol_registry_and_reducers_are_complete() -> None:
    from app.services.engine.events import _EVENT_REGISTRY
    from app.services.engine.state import _EVENT_REDUCERS

    expected = {
        "AttackDeclared",
        "AttackInterruptWindowOpened",
        "AttackInterruptTriggered",
        "AttackInterruptPriorityPassed",
        "AttackInterruptWindowClosed",
        "AttackAbilityOverrideApplied",
        "AttackResolved",
    }

    assert expected <= _EVENT_REGISTRY.keys()
    assert expected <= _EVENT_REDUCERS.keys()
