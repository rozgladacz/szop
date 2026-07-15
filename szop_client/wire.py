"""Public JSON-safe projections for HTTP client domain values."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.services.engine.events import BattleEvent, event_to_json
from app.services.engine.state_codec import battle_state_to_json
from szop_client.types import BattleStateCheckpoint


def ensure_json_safe(value: Any) -> Any:
    """Normalize native JSON data and reject unsupported or non-finite values."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("value is not JSON-safe") from None
    return json.loads(encoded)


def battle_state_checkpoint_to_wire(
    checkpoint: BattleStateCheckpoint,
) -> dict[str, Any]:
    """Project a coherent checkpoint without exposing internal RNG state."""
    serialized = battle_state_to_json(checkpoint.state)
    if (
        checkpoint.schema != serialized["schema"]
        or checkpoint.version != serialized["version"]
    ):
        raise ValueError("battle state checkpoint schema does not match its state")
    return ensure_json_safe(
        {
            "battle_id": checkpoint.battle_id,
            "sequence_at": checkpoint.sequence_at,
            "schema": checkpoint.schema,
            "version": checkpoint.version,
            "state": serialized["state"],
        }
    )


def validate_event_delta(
    events: Iterable[BattleEvent],
    *,
    since: int,
) -> tuple[BattleEvent, ...]:
    """Return a strictly ordered ``sequence > since`` event delta."""
    if type(since) is not int or since < 0:
        raise ValueError("since must be an int >= 0")
    validated: list[BattleEvent] = []
    last_sequence = since
    for event in events:
        try:
            sequence = event.sequence
        except AttributeError:
            raise ValueError("battle event delta contains a non-event") from None
        if type(sequence) is not int or sequence <= last_sequence:
            raise ValueError("battle event delta is not strictly ordered after since")
        validated.append(event)
        last_sequence = sequence
    return tuple(validated)


def battle_events_to_wire(
    events: Iterable[BattleEvent],
    *,
    since: int,
) -> tuple[list[dict[str, Any]], int]:
    """Project an event delta and return its stable last sequence."""
    validated = validate_event_delta(events, since=since)
    projected = [
        ensure_json_safe(
            {
                "sequence": event.sequence,
                "type": type(event).__name__,
                "payload": event_to_json(event),
            }
        )
        for event in validated
    ]
    last_sequence = validated[-1].sequence if validated else since
    return projected, last_sequence
