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
    BattleEvent,
    EffectApplied,
    InterruptTriggered,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    RoundEnded,
    ShotResolved,
    event_to_json,
    json_to_event,
)


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
