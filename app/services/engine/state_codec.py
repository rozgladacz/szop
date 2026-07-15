"""Safe, versioned JSON codec for immutable engine battle state.

The codec is deliberately whitelist-based: payload type names are resolved only
through the local registries below.  Deserialization never imports modules,
evaluates expressions, or calls arbitrary payload-selected code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import StatusFlag

STATE_CHECKPOINT_SCHEMA = "szop.battle_state"
STATE_CHECKPOINT_VERSION = 1

_DATACLASS_TYPES = (
    BattleState,
    UnitBlob,
    Position,
    TerrainCircle,
    TerrainLine,
    Objective,
    WeaponProfile,
)
_DATACLASS_REGISTRY = {cls.__name__: cls for cls in _DATACLASS_TYPES}
_ENUM_TYPES = (Lokalizacja, StatusFlag)
_ENUM_REGISTRY = {cls.__name__: cls for cls in _ENUM_TYPES}


class BattleStateCodecError(ValueError):
    """Serialized battle state is malformed or uses an unsupported version."""


def battle_state_to_json(state: BattleState) -> dict[str, Any]:
    """Return a JSON-safe, versioned representation of ``state``."""
    if not isinstance(state, BattleState):
        raise TypeError("state must be a BattleState")
    return {
        "schema": STATE_CHECKPOINT_SCHEMA,
        "version": STATE_CHECKPOINT_VERSION,
        "state": _encode_value(state),
    }


def battle_state_from_json(payload: Mapping[str, Any]) -> BattleState:
    """Restore a ``BattleState`` from a trusted-schema JSON payload."""
    if not isinstance(payload, Mapping):
        raise BattleStateCodecError("battle state checkpoint must be an object")
    if payload.get("schema") != STATE_CHECKPOINT_SCHEMA:
        raise BattleStateCodecError("unsupported battle state checkpoint schema")
    if (
        type(payload.get("version")) is not int
        or payload["version"] != STATE_CHECKPOINT_VERSION
    ):
        raise BattleStateCodecError("unsupported battle state checkpoint version")
    if set(payload) != {"schema", "version", "state"}:
        raise BattleStateCodecError("battle state checkpoint has unexpected fields")
    state = _decode_value(payload["state"])
    if not isinstance(state, BattleState):
        raise BattleStateCodecError("checkpoint root is not a BattleState")
    return state


def _encode_value(value: Any) -> Any:
    if isinstance(value, Enum):
        enum_name = type(value).__name__
        if (
            enum_name not in _ENUM_REGISTRY
            or type(value) is not _ENUM_REGISTRY[enum_name]
        ):
            raise TypeError(f"unsupported enum type: {type(value).__name__}")
        return {"$enum": enum_name, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        class_name = type(value).__name__
        if (
            class_name not in _DATACLASS_REGISTRY
            or type(value) is not _DATACLASS_REGISTRY[class_name]
        ):
            raise TypeError(f"unsupported dataclass type: {type(value).__name__}")
        return {
            "$dataclass": class_name,
            "fields": {
                field.name: _encode_value(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, tuple):
        return {"$tuple": [_encode_value(item) for item in value]}
    if isinstance(value, frozenset):
        encoded = [_encode_value(item) for item in value]
        encoded.sort(key=_canonical_sort_key)
        return {"$frozenset": encoded}
    if isinstance(value, dict):
        return {
            "$dict": [
                [_encode_value(key), _encode_value(item)]
                for key, item in value.items()
            ]
        }
    if isinstance(value, Mapping):
        return {
            "$mapping": [
                [_encode_value(key), _encode_value(item)]
                for key, item in value.items()
            ]
        }
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("battle state cannot contain non-finite floats")
        return value
    raise TypeError(f"unsupported battle state value: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not math.isfinite(value):
            raise BattleStateCodecError("battle state contains a non-finite float")
        return value
    if not isinstance(value, dict):
        raise BattleStateCodecError("battle state contains an untagged collection")

    if set(value) == {"$tuple"}:
        return tuple(_decode_sequence(value["$tuple"], "$tuple"))
    if set(value) == {"$frozenset"}:
        return frozenset(_decode_sequence(value["$frozenset"], "$frozenset"))
    if set(value) == {"$dict"}:
        return _decode_mapping(value["$dict"], "$dict")
    if set(value) == {"$mapping"}:
        return _decode_mapping(value["$mapping"], "$mapping")
    if set(value) == {"$enum", "value"}:
        enum_cls = _ENUM_REGISTRY.get(value["$enum"])
        if enum_cls is None:
            raise BattleStateCodecError("unknown battle state enum type")
        try:
            return enum_cls(value["value"])
        except (TypeError, ValueError) as exc:
            raise BattleStateCodecError("invalid battle state enum value") from exc
    if set(value) == {"$dataclass", "fields"}:
        return _decode_dataclass(value["$dataclass"], value["fields"])
    raise BattleStateCodecError("battle state contains an invalid type tag")


def _decode_sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BattleStateCodecError(f"{label} payload must be a list")
    return [_decode_value(item) for item in value]


def _decode_pairs(value: Any, label: str) -> list[tuple[Any, Any]]:
    if not isinstance(value, list):
        raise BattleStateCodecError(f"{label} payload must be a list")
    pairs: list[tuple[Any, Any]] = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise BattleStateCodecError(f"{label} entries must be key/value pairs")
        pairs.append((_decode_value(pair[0]), _decode_value(pair[1])))
    return pairs


def _decode_mapping(value: Any, label: str) -> dict[Any, Any]:
    try:
        return dict(_decode_pairs(value, label))
    except TypeError as exc:
        raise BattleStateCodecError(f"{label} contains an invalid key") from exc


def _decode_dataclass(class_name: Any, raw_fields: Any) -> Any:
    if not isinstance(class_name, str) or not isinstance(raw_fields, dict):
        raise BattleStateCodecError("invalid battle state dataclass payload")
    cls = _DATACLASS_REGISTRY.get(class_name)
    if cls is None:
        raise BattleStateCodecError("unknown battle state dataclass type")
    expected_fields = {field.name for field in fields(cls)}
    if set(raw_fields) != expected_fields:
        raise BattleStateCodecError(
            f"{class_name} fields do not match checkpoint schema"
        )
    decoded_fields = {
        field_name: _decode_value(field_value)
        for field_name, field_value in raw_fields.items()
    }
    type_hints = _type_hints(cls)
    for field_name, field_value in decoded_fields.items():
        _validate_type(
            field_value,
            type_hints[field_name],
            f"{class_name}.{field_name}",
        )
    try:
        return cls(**decoded_fields)
    except (TypeError, ValueError) as exc:
        raise BattleStateCodecError(f"invalid {class_name} payload") from exc


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=None)
def _type_hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _validate_type(value: Any, annotation: Any, path: str) -> None:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any:
        return
    if origin in (UnionType, Union):
        if any(_is_valid_type(value, option) for option in args):
            return
        raise BattleStateCodecError(f"{path} has an invalid type")
    if origin is tuple:
        if not isinstance(value, tuple):
            raise BattleStateCodecError(f"{path} must be a tuple")
        if len(args) == 2 and args[1] is Ellipsis:
            for index, item in enumerate(value):
                _validate_type(item, args[0], f"{path}[{index}]")
            return
        if len(value) != len(args):
            raise BattleStateCodecError(f"{path} has an invalid tuple length")
        for index, (item, item_type) in enumerate(zip(value, args)):
            _validate_type(item, item_type, f"{path}[{index}]")
        return
    if origin is frozenset:
        if not isinstance(value, frozenset):
            raise BattleStateCodecError(f"{path} must be a frozenset")
        for item in value:
            _validate_type(item, args[0], f"{path} item")
        return
    if origin in (dict, Mapping):
        if not isinstance(value, Mapping):
            raise BattleStateCodecError(f"{path} must be a mapping")
        key_type, value_type = args
        for key, item in value.items():
            _validate_type(key, key_type, f"{path} key")
            _validate_type(item, value_type, f"{path}[{key!r}]")
        return
    if not _is_valid_type(value, annotation):
        raise BattleStateCodecError(f"{path} has an invalid type")


def _is_valid_type(value: Any, annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in (UnionType, Union):
        return any(_is_valid_type(value, option) for option in get_args(annotation))
    if annotation is type(None):
        return value is None
    if annotation is bool:
        return type(value) is bool
    if annotation is int:
        return type(value) is int
    if annotation is float:
        return type(value) in (int, float)
    if annotation is str:
        return isinstance(value, str)
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    try:
        _validate_type(value, annotation, "value")
    except BattleStateCodecError:
        return False
    return True
