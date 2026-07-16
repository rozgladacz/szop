"""Public, lazily loaded API for the SZOP game clients.

Keeping imports lazy lets HTTP-only consumers use ``HttpClient`` without
loading the in-process engine, cost modules, ORM, or database configuration.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BattleActionProposal": ("szop_client.types", "BattleActionProposal"),
    "BattleMetadata": ("szop_client.http", "BattleMetadata"),
    "BattleStateCheckpoint": ("szop_client.types", "BattleStateCheckpoint"),
    "HttpClient": ("szop_client.http", "HttpClient"),
    "HttpClientError": ("szop_client.http", "HttpClientError"),
    "HttpClientTransportError": ("szop_client.http", "HttpClientTransportError"),
    "HttpRequest": ("szop_client.http", "HttpRequest"),
    "HttpResponse": ("szop_client.http", "HttpResponse"),
    "LocalClient": ("szop_client.local", "LocalClient"),
    "UnknownBattleError": ("szop_client.local", "UnknownBattleError"),
    "RosterNotFoundError": ("szop_client.local", "RosterNotFoundError"),
    "SimulationSummary": ("szop_client.types", "SimulationSummary"),
    "battle_events_to_wire": ("szop_client.wire", "battle_events_to_wire"),
    "battle_state_checkpoint_to_wire": (
        "szop_client.wire",
        "battle_state_checkpoint_to_wire",
    ),
    "ensure_json_safe": ("szop_client.wire", "ensure_json_safe"),
    "validate_event_delta": ("szop_client.wire", "validate_event_delta"),
    "GameClient": ("szop_client.protocol", "GameClient"),
    "PlayerFactory": ("szop_client.protocol", "PlayerFactory"),
    "ContinuationFn": ("szop_client.protocol", "ContinuationFn"),
    "Terrain": ("szop_client.protocol", "Terrain"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
