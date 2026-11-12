"""Safe, versioned JSON codec for immutable engine battle state.

The codec is deliberately whitelist-based: payload type names are resolved only
through the local registries below.  Deserialization never imports modules,
evaluates expressions, or calls arbitrary payload-selected code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import is_dataclass
from enum import Enum
from functools import lru_cache
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from app.battle_protocol import (
    ACTIVATION_PROTOCOL_VERSION_V1,
    ACTIVATION_PROTOCOL_VERSION_V2,
    ACTIVATION_PROTOCOL_VERSION_V3,
    ACTIVATION_PROTOCOL_VERSIONS,
)
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    AttackAbilityOverride,
    AttackState,
    BattleState,
    ChargeAttackIntent,
    InterruptWindowState,
    Lokalizacja,
    Objective,
    Position,
    ShootAttackIntent,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import StatusFlag
from app.services.engine.terrain_complex import TerrainPolygon

STATE_CHECKPOINT_SCHEMA = "szop.battle_state"
STATE_CHECKPOINT_VERSION = ACTIVATION_PROTOCOL_VERSION_V1
STATE_CHECKPOINT_VERSION_V2 = ACTIVATION_PROTOCOL_VERSION_V2
STATE_CHECKPOINT_VERSION_V3 = ACTIVATION_PROTOCOL_VERSION_V3
_MAX_JSON_DEPTH = 64

_V1_BATTLE_STATE_FIELDS = (
    "round",
    "active_player",
    "activations_remaining",
    "blobs",
    "terrain",
    "objectives",
    "pending_effects",
    "pending_interrupts",
    "score",
    "is_game_over",
    "initial_toughness_snapshot",
    "used_interrupts_this_round",
)
_V2_BATTLE_STATE_FIELDS = (
    "round",
    "active_player",
    "activations_remaining",
    "blobs",
    "terrain",
    "objectives",
    "pending_effects",
    "score",
    "is_game_over",
    "initial_toughness_snapshot",
    "used_interrupts_this_round",
    "initiative_player",
    "activation",
)
_V3_BATTLE_STATE_FIELDS = _V2_BATTLE_STATE_FIELDS
_UNIT_BLOB_FIELDS = (
    "id",
    "owner_player",
    "position",
    "radius_inches",
    "models_alive",
    "toughness_per_model",
    "quality",
    "defense",
    "is_hero_unit",
    "passives",
    "ability_overrides",
    "status_flags",
    "wounds_received",
    "wounds_pending",
    "wounds_pending_precise",
    "wounds_eliminating",
    "damage_balance",
    "melee_weapons",
    "ranged_weapons",
    "location",
)
_COMMON_DATACLASS_FIELDS = {
    UnitBlob: _UNIT_BLOB_FIELDS,
    Position: ("x", "y"),
    TerrainCircle: ("center", "radius_inches", "features"),
    TerrainLine: ("start", "end", "features"),
    TerrainPolygon: ("vertices", "features"),
    Objective: ("id", "position", "controller"),
    WeaponProfile: (
        "slug",
        "name",
        "range_inches",
        "attacks",
        "ap",
        "attack_quality_override",
        "weapon_abilities",
    ),
}
_V1_DATACLASS_FIELDS = {
    BattleState: _V1_BATTLE_STATE_FIELDS,
    **_COMMON_DATACLASS_FIELDS,
}
_V2_ACTIVATION_STATE_FIELDS = (
    "activation_id",
    "version",
    "selected_unit_id",
    "controlling_player",
    "initiative_player",
    "action_count",
    "action_types",
    "phase",
    "window",
)
_INTERRUPT_WINDOW_STATE_FIELDS = (
    "ordinal",
    "version",
    "priority_player",
    "passed_players",
    "interrupt_count",
)
_V2_DATACLASS_FIELDS = {
    BattleState: _V2_BATTLE_STATE_FIELDS,
    **_COMMON_DATACLASS_FIELDS,
    ActivationState: _V2_ACTIVATION_STATE_FIELDS,
    InterruptWindowState: _INTERRUPT_WINDOW_STATE_FIELDS,
}
_V3_DATACLASS_FIELDS = {
    BattleState: _V3_BATTLE_STATE_FIELDS,
    **_COMMON_DATACLASS_FIELDS,
    ActivationState: _V2_ACTIVATION_STATE_FIELDS + ("attack",),
    InterruptWindowState: _INTERRUPT_WINDOW_STATE_FIELDS,
    ShootAttackIntent: (
        "attacker_unit_id",
        "target_unit_id",
        "weapon_slug",
    ),
    ChargeAttackIntent: (
        "attacker_unit_id",
        "target_unit_id",
        "weapon_slug",
        "counter_attack_declared",
    ),
    AttackAbilityOverride: ("source_unit_id", "ability_slug"),
    AttackState: (
        "attack_id",
        "version",
        "ordinal",
        "intent",
        "window",
        "ability_overrides",
    ),
}
_DATACLASS_FIELDS_BY_VERSION = {
    STATE_CHECKPOINT_VERSION: _V1_DATACLASS_FIELDS,
    STATE_CHECKPOINT_VERSION_V2: _V2_DATACLASS_FIELDS,
    STATE_CHECKPOINT_VERSION_V3: _V3_DATACLASS_FIELDS,
}
_V2_ACTIVATION_PHASES = frozenset(
    (
        ActivationPhase.BEFORE_ACTION,
        ActivationPhase.ACTION_READY,
        ActivationPhase.AWAITING_CONTINUATION,
        ActivationPhase.AWAITING_FINALIZATION,
    )
)
_ENUM_VALUES_BY_VERSION = {
    STATE_CHECKPOINT_VERSION: {
        Lokalizacja: frozenset(Lokalizacja),
        StatusFlag: frozenset(StatusFlag),
    },
    STATE_CHECKPOINT_VERSION_V2: {
        Lokalizacja: frozenset(Lokalizacja),
        StatusFlag: frozenset(StatusFlag),
        ActivationPhase: _V2_ACTIVATION_PHASES,
    },
    STATE_CHECKPOINT_VERSION_V3: {
        Lokalizacja: frozenset(Lokalizacja),
        StatusFlag: frozenset(StatusFlag),
        ActivationPhase: frozenset(ActivationPhase),
    },
}


class BattleStateCodecError(ValueError):
    """Serialized battle state is malformed or uses an unsupported version."""


def _checkpoint_version(
    value: object,
    *,
    allowed_versions: tuple[int, ...],
) -> int:
    if type(value) is not int or value not in allowed_versions:
        raise BattleStateCodecError(
            "unsupported battle state checkpoint version"
        )
    return value


def battle_state_to_json(
    state: BattleState,
    *,
    version: int = STATE_CHECKPOINT_VERSION,
) -> dict[str, Any]:
    """Return a public-runtime versioned JSON representation of ``state``."""
    return _battle_state_to_json(
        state,
        version=version,
        allowed_versions=ACTIVATION_PROTOCOL_VERSIONS,
    )


def _battle_state_to_json_v3(state: BattleState) -> dict[str, Any]:
    """Return the private protocol-v3 checkpoint representation of ``state``."""
    return _battle_state_to_json(
        state,
        version=STATE_CHECKPOINT_VERSION_V3,
        allowed_versions=(STATE_CHECKPOINT_VERSION_V3,),
    )


def _battle_state_to_json(
    state: BattleState,
    *,
    version: int,
    allowed_versions: tuple[int, ...],
) -> dict[str, Any]:
    if not isinstance(state, BattleState):
        raise TypeError("state must be a BattleState")
    version = _checkpoint_version(version, allowed_versions=allowed_versions)
    if version == STATE_CHECKPOINT_VERSION:
        if state.initiative_player is not None or state.activation is not None:
            raise BattleStateCodecError(
                "v1 checkpoint cannot contain initiative or activation state"
            )
    else:
        if type(state.initiative_player) is not int or state.initiative_player not in (
            0,
            1,
        ):
            raise BattleStateCodecError(
                f"v{version} checkpoint requires initiative_player"
            )
        if state.pending_interrupts != ():
            raise BattleStateCodecError(
                f"v{version} checkpoint cannot contain legacy pending_interrupts"
            )
        if (
            version == STATE_CHECKPOINT_VERSION_V2
            and state.activation is not None
            and state.activation.attack is not None
        ):
            raise BattleStateCodecError("v2 checkpoint cannot contain attack state")
    return {
        "schema": STATE_CHECKPOINT_SCHEMA,
        "version": version,
        "state": _encode_value(state, version=version),
    }


def battle_state_from_json(payload: Mapping[str, Any]) -> BattleState:
    """Restore a public-runtime versioned ``BattleState`` checkpoint."""
    return _battle_state_from_json(
        payload,
        allowed_versions=ACTIVATION_PROTOCOL_VERSIONS,
    )


def _battle_state_from_json_v3(payload: Mapping[str, Any]) -> BattleState:
    """Restore a private protocol-v3 ``BattleState`` checkpoint."""
    return _battle_state_from_json(
        payload,
        allowed_versions=(STATE_CHECKPOINT_VERSION_V3,),
    )


def _battle_state_from_json(
    payload: Mapping[str, Any],
    *,
    allowed_versions: tuple[int, ...],
) -> BattleState:
    if not isinstance(payload, Mapping):
        raise BattleStateCodecError("battle state checkpoint must be an object")
    if payload.get("schema") != STATE_CHECKPOINT_SCHEMA:
        raise BattleStateCodecError("unsupported battle state checkpoint schema")
    version = _checkpoint_version(
        payload.get("version"),
        allowed_versions=allowed_versions,
    )
    if set(payload) != {"schema", "version", "state"}:
        raise BattleStateCodecError("battle state checkpoint has unexpected fields")
    state = _decode_value(payload["state"], version=version)
    if not isinstance(state, BattleState):
        raise BattleStateCodecError("checkpoint root is not a BattleState")
    return state


def _encode_value(value: Any, *, version: int, depth: int = 0) -> Any:
    _require_depth(version, depth)
    dataclass_registry, enum_registry = _registries(version)
    if isinstance(value, Enum):
        enum_name = type(value).__name__
        if (
            enum_name not in enum_registry
            or type(value) is not enum_registry[enum_name]
        ):
            raise TypeError(f"unsupported enum type: {type(value).__name__}")
        if value not in _ENUM_VALUES_BY_VERSION[version][type(value)]:
            raise TypeError(
                f"unsupported {type(value).__name__} value for checkpoint v{version}"
            )
        return {"$enum": enum_name, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        class_name = type(value).__name__
        if (
            class_name not in dataclass_registry
            or type(value) is not dataclass_registry[class_name]
        ):
            raise TypeError(f"unsupported dataclass type: {type(value).__name__}")
        field_names = _dataclass_field_names(type(value), version=version)
        if version in (
            STATE_CHECKPOINT_VERSION_V2,
            STATE_CHECKPOINT_VERSION_V3,
        ):
            type_hints = _type_hints(type(value))
            for field_name in field_names:
                _validate_type(
                    getattr(value, field_name),
                    type_hints[field_name],
                    f"{class_name}.{field_name}",
                )
        return {
            "$dataclass": class_name,
            "fields": {
                field_name: _encode_value(
                    getattr(value, field_name),
                    version=version,
                    depth=depth + 1,
                )
                for field_name in field_names
            },
        }
    if isinstance(value, tuple):
        return {
            "$tuple": [
                _encode_value(item, version=version, depth=depth + 1)
                for item in value
            ]
        }
    if isinstance(value, frozenset):
        encoded = [
            _encode_value(item, version=version, depth=depth + 1)
            for item in value
        ]
        encoded.sort(key=_canonical_sort_key)
        return {"$frozenset": encoded}
    if isinstance(value, dict):
        return {
            "$dict": [
                [
                    _encode_value(key, version=version, depth=depth + 1),
                    _encode_value(item, version=version, depth=depth + 1),
                ]
                for key, item in value.items()
            ]
        }
    if isinstance(value, Mapping):
        return {
            "$mapping": [
                [
                    _encode_value(key, version=version, depth=depth + 1),
                    _encode_value(item, version=version, depth=depth + 1),
                ]
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


def _decode_value(value: Any, *, version: int, depth: int = 0) -> Any:
    _require_depth(version, depth)
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not math.isfinite(value):
            raise BattleStateCodecError("battle state contains a non-finite float")
        return value
    if not isinstance(value, dict):
        raise BattleStateCodecError("battle state contains an untagged collection")

    if set(value) == {"$tuple"}:
        return tuple(
            _decode_sequence(
                value["$tuple"],
                "$tuple",
                version=version,
                depth=depth + 1,
            )
        )
    if set(value) == {"$frozenset"}:
        return frozenset(
            _decode_sequence(
                value["$frozenset"],
                "$frozenset",
                version=version,
                depth=depth + 1,
            )
        )
    if set(value) == {"$dict"}:
        return _decode_mapping(
            value["$dict"],
            "$dict",
            version=version,
            depth=depth + 1,
        )
    if set(value) == {"$mapping"}:
        return _decode_mapping(
            value["$mapping"],
            "$mapping",
            version=version,
            depth=depth + 1,
        )
    if set(value) == {"$enum", "value"}:
        if type(value["$enum"]) is not str:
            raise BattleStateCodecError("invalid battle state enum type")
        _, enum_registry = _registries(version)
        enum_cls = enum_registry.get(value["$enum"])
        if enum_cls is None:
            raise BattleStateCodecError("unknown battle state enum type")
        try:
            enum_value = enum_cls(value["value"])
        except (TypeError, ValueError) as exc:
            raise BattleStateCodecError("invalid battle state enum value") from exc
        if enum_value not in _ENUM_VALUES_BY_VERSION[version][enum_cls]:
            raise BattleStateCodecError(
                "battle state enum value is unsupported by this checkpoint version"
            )
        return enum_value
    if set(value) == {"$dataclass", "fields"}:
        return _decode_dataclass(
            value["$dataclass"],
            value["fields"],
            version=version,
            depth=depth + 1,
        )
    raise BattleStateCodecError("battle state contains an invalid type tag")


def _decode_sequence(
    value: Any,
    label: str,
    *,
    version: int,
    depth: int,
) -> list[Any]:
    if not isinstance(value, list):
        raise BattleStateCodecError(f"{label} payload must be a list")
    return [
        _decode_value(item, version=version, depth=depth)
        for item in value
    ]


def _decode_pairs(
    value: Any,
    label: str,
    *,
    version: int,
    depth: int,
) -> list[tuple[Any, Any]]:
    if not isinstance(value, list):
        raise BattleStateCodecError(f"{label} payload must be a list")
    pairs: list[tuple[Any, Any]] = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise BattleStateCodecError(f"{label} entries must be key/value pairs")
        pairs.append(
            (
                _decode_value(pair[0], version=version, depth=depth),
                _decode_value(pair[1], version=version, depth=depth),
            )
        )
    return pairs


def _decode_mapping(
    value: Any,
    label: str,
    *,
    version: int,
    depth: int,
) -> dict[Any, Any]:
    try:
        return dict(
            _decode_pairs(
                value,
                label,
                version=version,
                depth=depth,
            )
        )
    except TypeError as exc:
        raise BattleStateCodecError(f"{label} contains an invalid key") from exc


def _decode_dataclass(
    class_name: Any,
    raw_fields: Any,
    *,
    version: int,
    depth: int,
) -> Any:
    if not isinstance(class_name, str) or not isinstance(raw_fields, dict):
        raise BattleStateCodecError("invalid battle state dataclass payload")
    dataclass_registry, _ = _registries(version)
    cls = dataclass_registry.get(class_name)
    if cls is None:
        raise BattleStateCodecError("unknown battle state dataclass type")
    expected_fields = set(_dataclass_field_names(cls, version=version))
    if set(raw_fields) != expected_fields:
        raise BattleStateCodecError(
            f"{class_name} fields do not match checkpoint schema"
        )
    decoded_fields = {
        field_name: _decode_value(
            field_value,
            version=version,
            depth=depth,
        )
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


@lru_cache(maxsize=None)
def _registries(version: int) -> tuple[dict[str, type], dict[str, type[Enum]]]:
    dataclass_types = _DATACLASS_FIELDS_BY_VERSION[version]
    enum_types = _ENUM_VALUES_BY_VERSION[version]
    return (
        {cls.__name__: cls for cls in dataclass_types},
        {cls.__name__: cls for cls in enum_types},
    )


def _dataclass_field_names(cls: type, *, version: int) -> tuple[str, ...]:
    try:
        return _DATACLASS_FIELDS_BY_VERSION[version][cls]
    except KeyError as exc:
        raise TypeError(
            f"unsupported dataclass type for checkpoint v{version}: {cls.__name__}"
        ) from exc


def _require_depth(version: int, depth: int) -> None:
    if version == STATE_CHECKPOINT_VERSION_V3 and depth > _MAX_JSON_DEPTH:
        raise BattleStateCodecError("battle state checkpoint is nested too deeply")


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
