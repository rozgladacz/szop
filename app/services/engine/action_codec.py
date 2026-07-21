"""Safe, versioned JSON wire codec for the public engine ``Action`` union.

The codec is deliberately closed and registry-based. Payload discriminators
select only locally registered action classes; decoding never imports modules,
evaluates expressions, or executes payload-provided data.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from app.services.engine.actions import (
    ACTION_TYPE_BY_CLASS,
    Action,
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.state import Position, WeaponProfile

ACTION_WIRE_SCHEMA = "szop.action"
ACTION_WIRE_VERSION = 1
_MAX_JSON_DEPTH = 64


class ActionCodecError(ValueError):
    """An action wire payload is malformed or uses an unsupported version."""


Encoder = Callable[[Any], dict[str, Any]]
Decoder = Callable[[dict[str, Any]], Action]


def _encode_maneuver(action: ManeuverAction) -> dict[str, Any]:
    return {
        "unit_id": _strict_int(action.unit_id, "ManeuverAction.unit_id"),
        "target_position": _position_to_json(action.target_position),
    }


def _decode_maneuver(payload: dict[str, Any]) -> ManeuverAction:
    _require_fields(payload, {"unit_id", "target_position"}, "maneuver payload")
    return ManeuverAction(
        unit_id=_strict_int(payload["unit_id"], "maneuver.unit_id"),
        target_position=_position_from_json(payload["target_position"]),
    )


def _encode_defend(action: DefendAction) -> dict[str, Any]:
    return {"unit_id": _strict_int(action.unit_id, "DefendAction.unit_id")}


def _decode_defend(payload: dict[str, Any]) -> DefendAction:
    _require_fields(payload, {"unit_id"}, "defend payload")
    return DefendAction(unit_id=_strict_int(payload["unit_id"], "defend.unit_id"))


def _encode_shoot(action: ShootAction) -> dict[str, Any]:
    return {
        "unit_id": _strict_int(action.unit_id, "ShootAction.unit_id"),
        "target_id": _strict_int(action.target_id, "ShootAction.target_id"),
        "weapon": _weapon_to_json(action.weapon),
    }


def _decode_shoot(payload: dict[str, Any]) -> ShootAction:
    _require_fields(payload, {"unit_id", "target_id", "weapon"}, "shoot payload")
    return ShootAction(
        unit_id=_strict_int(payload["unit_id"], "shoot.unit_id"),
        target_id=_strict_int(payload["target_id"], "shoot.target_id"),
        weapon=_weapon_from_json(payload["weapon"]),
    )


def _encode_charge(action: ChargeAction) -> dict[str, Any]:
    if type(action.counter_attack_declared) is not bool:
        raise ActionCodecError("ChargeAction.counter_attack_declared must be a boolean")
    return {
        "unit_id": _strict_int(action.unit_id, "ChargeAction.unit_id"),
        "target_id": _strict_int(action.target_id, "ChargeAction.target_id"),
        "weapon": _weapon_to_json(action.weapon),
        "counter_attack_declared": action.counter_attack_declared,
    }


def _decode_charge(payload: dict[str, Any]) -> ChargeAction:
    _require_fields(
        payload,
        {"unit_id", "target_id", "weapon", "counter_attack_declared"},
        "charge payload",
    )
    counter_attack_declared = payload["counter_attack_declared"]
    if type(counter_attack_declared) is not bool:
        raise ActionCodecError("charge.counter_attack_declared must be a boolean")
    return ChargeAction(
        unit_id=_strict_int(payload["unit_id"], "charge.unit_id"),
        target_id=_strict_int(payload["target_id"], "charge.target_id"),
        weapon=_weapon_from_json(payload["weapon"]),
        counter_attack_declared=counter_attack_declared,
    )


def _encode_special(action: SpecialAction) -> dict[str, Any]:
    if type(action.ability_slug) is not str:
        raise ActionCodecError("SpecialAction.ability_slug must be a string")
    if type(action.payload) is not dict:
        raise ActionCodecError("SpecialAction.payload must be a JSON object")
    return {
        "unit_id": _strict_int(action.unit_id, "SpecialAction.unit_id"),
        "ability_slug": action.ability_slug,
        "payload": _copy_json_value(action.payload),
    }


def _decode_special(payload: dict[str, Any]) -> SpecialAction:
    _require_fields(
        payload,
        {"unit_id", "ability_slug", "payload"},
        "special payload",
    )
    ability_slug = payload["ability_slug"]
    if type(ability_slug) is not str:
        raise ActionCodecError("special.ability_slug must be a string")
    special_payload = payload["payload"]
    if type(special_payload) is not dict:
        raise ActionCodecError("special.payload must be a JSON object")
    return SpecialAction(
        unit_id=_strict_int(payload["unit_id"], "special.unit_id"),
        ability_slug=ability_slug,
        payload=_copy_json_value(special_payload),
    )


_ACTION_ENCODERS: dict[type, tuple[str, Encoder]] = {
    ManeuverAction: (ACTION_TYPE_BY_CLASS[ManeuverAction], _encode_maneuver),
    DefendAction: (ACTION_TYPE_BY_CLASS[DefendAction], _encode_defend),
    ShootAction: (ACTION_TYPE_BY_CLASS[ShootAction], _encode_shoot),
    ChargeAction: (ACTION_TYPE_BY_CLASS[ChargeAction], _encode_charge),
    SpecialAction: (ACTION_TYPE_BY_CLASS[SpecialAction], _encode_special),
}
_ACTION_DECODERS: dict[str, Decoder] = {
    ACTION_TYPE_BY_CLASS[ManeuverAction]: _decode_maneuver,
    ACTION_TYPE_BY_CLASS[DefendAction]: _decode_defend,
    ACTION_TYPE_BY_CLASS[ShootAction]: _decode_shoot,
    ACTION_TYPE_BY_CLASS[ChargeAction]: _decode_charge,
    ACTION_TYPE_BY_CLASS[SpecialAction]: _decode_special,
}


def action_to_json(action: Action) -> dict[str, Any]:
    """Return a strict JSON-safe, versioned representation of ``action``."""
    registered = _ACTION_ENCODERS.get(type(action))
    if registered is None:
        raise TypeError(f"unsupported action type: {type(action).__name__}")
    discriminator, encoder = registered
    return {
        "schema": ACTION_WIRE_SCHEMA,
        "version": ACTION_WIRE_VERSION,
        "action_type": discriminator,
        "payload": encoder(action),
    }


def action_from_json(payload: Mapping[str, Any]) -> Action:
    """Decode one of the five registered public actions from wire JSON."""
    if not isinstance(payload, Mapping):
        raise ActionCodecError("action wire payload must be an object")
    if set(payload) != {"schema", "version", "action_type", "payload"}:
        raise ActionCodecError("action wire payload has unexpected fields")
    if payload["schema"] != ACTION_WIRE_SCHEMA:
        raise ActionCodecError("unsupported action wire schema")
    if type(payload["version"]) is not int or payload["version"] != ACTION_WIRE_VERSION:
        raise ActionCodecError("unsupported action wire version")
    action_type = payload["action_type"]
    if type(action_type) is not str:
        raise ActionCodecError("action_type must be a string")
    decoder = _ACTION_DECODERS.get(action_type)
    if decoder is None:
        raise ActionCodecError("unknown action wire type")
    raw_action = payload["payload"]
    if type(raw_action) is not dict:
        raise ActionCodecError("action payload must be an object")
    return decoder(raw_action)


def _position_to_json(position: Position) -> dict[str, int | float]:
    if type(position) is not Position:
        raise ActionCodecError("action position must be a Position")
    return {
        "x": _finite_number(position.x, "Position.x"),
        "y": _finite_number(position.y, "Position.y"),
    }


def _position_from_json(payload: Any) -> Position:
    raw = _require_object(payload, {"x", "y"}, "position")
    return Position(
        x=_finite_number(raw["x"], "position.x"),
        y=_finite_number(raw["y"], "position.y"),
    )


def _weapon_to_json(weapon: WeaponProfile) -> dict[str, Any]:
    if type(weapon) is not WeaponProfile:
        raise ActionCodecError("action weapon must be a WeaponProfile")
    if type(weapon.slug) is not str or type(weapon.name) is not str:
        raise ActionCodecError("WeaponProfile slug and name must be strings")
    if type(weapon.weapon_abilities) is not tuple or any(
        type(item) is not str for item in weapon.weapon_abilities
    ):
        raise ActionCodecError("WeaponProfile.weapon_abilities must be strings")
    quality = weapon.attack_quality_override
    if quality is not None:
        quality = _strict_int(quality, "WeaponProfile.attack_quality_override")
    return {
        "slug": weapon.slug,
        "name": weapon.name,
        "range_inches": _strict_int(weapon.range_inches, "WeaponProfile.range_inches"),
        "attacks": _strict_int(weapon.attacks, "WeaponProfile.attacks"),
        "ap": _strict_int(weapon.ap, "WeaponProfile.ap"),
        "attack_quality_override": quality,
        "weapon_abilities": list(weapon.weapon_abilities),
    }


def _weapon_from_json(payload: Any) -> WeaponProfile:
    expected = {
        "slug",
        "name",
        "range_inches",
        "attacks",
        "ap",
        "attack_quality_override",
        "weapon_abilities",
    }
    raw = _require_object(payload, expected, "weapon")
    if type(raw["slug"]) is not str or type(raw["name"]) is not str:
        raise ActionCodecError("weapon slug and name must be strings")
    quality = raw["attack_quality_override"]
    if quality is not None:
        quality = _strict_int(quality, "weapon.attack_quality_override")
    abilities = raw["weapon_abilities"]
    if type(abilities) is not list or any(type(item) is not str for item in abilities):
        raise ActionCodecError("weapon.weapon_abilities must be a list of strings")
    return WeaponProfile(
        slug=raw["slug"],
        name=raw["name"],
        range_inches=_strict_int(raw["range_inches"], "weapon.range_inches"),
        attacks=_strict_int(raw["attacks"], "weapon.attacks"),
        ap=_strict_int(raw["ap"], "weapon.ap"),
        attack_quality_override=quality,
        weapon_abilities=tuple(abilities),
    )


def _strict_int(value: Any, path: str) -> int:
    if type(value) is not int:
        raise ActionCodecError(f"{path} must be an integer")
    return value


def _finite_number(value: Any, path: str) -> int | float:
    if type(value) not in (int, float):
        raise ActionCodecError(f"{path} must be a number")
    if type(value) is float and not math.isfinite(value):
        raise ActionCodecError(f"{path} must be finite")
    return value


def _require_object(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ActionCodecError(f"{label} must be an object")
    _require_fields(value, expected, label)
    return value


def _require_fields(payload: dict[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ActionCodecError(f"{label} has unexpected fields")


def _copy_json_value(
    value: Any,
    *,
    depth: int = 0,
    ancestors: frozenset[int] = frozenset(),
) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise ActionCodecError("special action payload is nested too deeply")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ActionCodecError("special action payload contains a non-finite float")
        return value
    if type(value) in (list, dict):
        identity = id(value)
        if identity in ancestors:
            raise ActionCodecError("special action payload contains a cycle")
        ancestors = ancestors | {identity}
    if type(value) is list:
        return [
            _copy_json_value(item, depth=depth + 1, ancestors=ancestors)
            for item in value
        ]
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ActionCodecError("special action payload keys must be strings")
            copied[key] = _copy_json_value(
                item, depth=depth + 1, ancestors=ancestors
            )
        return copied
    raise ActionCodecError(
        f"special action payload contains unsupported {type(value).__name__}"
    )
