"""Shared activation-protocol version constants and strict validation."""

from __future__ import annotations


ACTIVATION_PROTOCOL_VERSION_V1 = 1
ACTIVATION_PROTOCOL_VERSION_V2 = 2
ACTIVATION_PROTOCOL_VERSIONS = (
    ACTIVATION_PROTOCOL_VERSION_V1,
    ACTIVATION_PROTOCOL_VERSION_V2,
)


def validate_activation_protocol_version(value: object) -> int:
    """Return a supported strict integer activation-protocol version."""
    if type(value) is not int or value not in ACTIVATION_PROTOCOL_VERSIONS:
        raise ValueError("activation_protocol_version must be 1 or 2")
    return value


__all__ = [
    "ACTIVATION_PROTOCOL_VERSION_V1",
    "ACTIVATION_PROTOCOL_VERSION_V2",
    "ACTIVATION_PROTOCOL_VERSIONS",
    "validate_activation_protocol_version",
]
