from __future__ import annotations

import copy
import json

import pytest

from app.services.engine.action_codec import (
    ACTION_WIRE_SCHEMA,
    ActionCodecError,
    action_from_json,
    action_to_json,
)
from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.state import Position, WeaponProfile


WEAPON = WeaponProfile(
    slug="rifle",
    name="Karabin",
    range_inches=24,
    attacks=2,
    ap=-1,
    attack_quality_override=3,
    weapon_abilities=("precyzyjny",),
)


@pytest.mark.parametrize(
    "action",
    [
        ManeuverAction(unit_id=1, target_position=Position(3.5, 4)),
        DefendAction(unit_id=2),
        ShootAction(unit_id=3, target_id=4, weapon=WEAPON),
        ChargeAction(
            unit_id=5,
            target_id=6,
            weapon=WEAPON,
            counter_attack_declared=False,
        ),
        SpecialAction(
            unit_id=7,
            ability_slug="mag",
            payload={"target_id": 8, "choices": ["a", None, True, 1.5]},
        ),
    ],
)
def test_action_wire_round_trip_for_closed_union(action) -> None:
    payload = action_to_json(action)

    assert payload["schema"] == ACTION_WIRE_SCHEMA
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert action_from_json(payload) == action


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="other"),
        lambda payload: payload.update(version=2),
        lambda payload: payload.update(version=True),
        lambda payload: payload.update(action_type="deployment"),
        lambda payload: payload.update(extra="field"),
        lambda payload: payload["payload"].update(extra="field"),
        lambda payload: payload["payload"].update(unit_id=True),
    ],
)
def test_action_wire_rejects_unknown_schema_version_type_fields_and_bool(mutation) -> None:
    payload = action_to_json(DefendAction(unit_id=1))
    mutation(payload)

    with pytest.raises(ActionCodecError):
        action_from_json(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_action_wire_rejects_non_finite_position(value: float) -> None:
    payload = action_to_json(ManeuverAction(1, Position(1, 2)))
    payload["payload"]["target_position"]["x"] = value

    with pytest.raises(ActionCodecError):
        action_from_json(payload)


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"tuple": (1, 2)},
        {"set": {1, 2}},
        {1: "non-string key"},
        {"nan": float("nan")},
        {"infinity": float("inf")},
        {"object": object()},
    ],
)
def test_action_wire_rejects_non_json_safe_special_payload(bad_payload) -> None:
    with pytest.raises(ActionCodecError):
        action_to_json(SpecialAction(1, "mag", bad_payload))


def test_action_wire_rejects_cyclic_special_payload() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ActionCodecError, match="cycle"):
        action_to_json(SpecialAction(1, "mag", cyclic))


def test_action_wire_decoder_copies_mutable_special_payload() -> None:
    wire = action_to_json(SpecialAction(1, "mag", {"choices": [1, 2]}))
    decoded = action_from_json(copy.deepcopy(wire))

    wire["payload"]["payload"]["choices"].append(3)

    assert decoded.payload == {"choices": [1, 2]}
