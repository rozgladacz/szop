"""HTTP client for the public B4 battle API.

The client keeps no mutable battle-state or sequence cache. Mutating one action
first reads the current checkpoint sequence, then sends it as an explicit
optimistic precondition and consumes the returned state/event delta.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.engine.action_codec import (
    ActionCodecError,
    action_from_json,
    action_to_json,
)
from app.services.engine.actions import Action
from app.services.engine.events import BattleEvent, json_to_event
from app.services.engine.state import BattleState
from app.services.engine.state_codec import battle_state_from_json
from szop_client.types import (
    BattleActionProposal,
    BattleStateCheckpoint,
    SimulationSummary,
)
from szop_client.wire import validate_event_delta

if TYPE_CHECKING:
    from szop_client.protocol import ContinuationFn

RULE_LOOKUP_SCHEMA = "szop.lookup_rule/v1"
ABILITY_EXPLANATION_SCHEMA = "szop.explain_ability/v1"
RULES_SEARCH_SCHEMA = "szop.search_rules/v1"
LOADOUT_VALIDATION_SCHEMA = "szop.validate_loadout/v1"
REFERENCE_API_VERSION = 1
LOADOUT_VALIDATION_VERSION = 1
RULES_SEARCH_STRATEGY = "hybrid_weighted_rrf"
RULE_SOURCE = "SZOP_Rozjemca.md"
ABILITY_SOURCE = "app.data.abilities"
RULE_SEARCH_SOURCES = frozenset({"SZOP_Rozjemca.md", "SZOP_Zdolnosci.md"})
MAX_RULE_QUERY_LENGTH = 200
MAX_RULE_RESULTS = 10
MAX_RULE_TEXT_LENGTH = 4000
MAX_RULE_CHILDREN = 20
MAX_ABILITY_QUERY_LENGTH = 100
MAX_RULE_SEARCH_TEXT_LENGTH = 1200
MAX_LOADOUT_COUNT = 100
RAG_SEARCH_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Transport-neutral request passed to injectable transports."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    timeout: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Transport-neutral HTTP response returned by injectable transports."""

    status_code: int
    body: bytes


@dataclass(frozen=True, slots=True)
class BattleMetadata:
    """Participant-scoped metadata returned by `GET /battles/{id}`."""

    battle_id: int
    p1_user_id: int | None
    p2_user_id: int | None
    p1_roster_id: int | None
    p2_roster_id: int | None
    winner_user_id: int | None
    current_round: int
    rng_seed: int
    status: str
    latest_sequence: int


Transport = Callable[[HttpRequest], HttpResponse]


class HttpClientError(RuntimeError):
    """HTTP API returned an error status or malformed payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpClientTransportError(HttpClientError):
    """HTTP transport failed before a valid API response was received."""


class HttpClient:
    """HTTP client for checkpointed single-action play and sandbox operations."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        self._base_url = normalized
        self._token = token
        self._timeout = timeout
        self._transport = transport or _urlopen_transport

    def create_battle(
        self,
        *,
        p1_roster_id: int,
        p2_roster_id: int,
        rng_seed: int = 0,
        initiative_player: int = 0,
    ) -> BattleMetadata:
        """Create a sandbox battle via `POST /battles` and return its metadata."""
        error_label = "POST create battle"
        payload = self._request_json(
            "POST",
            "/battles",
            {},
            json_body={
                "p1_roster_id": p1_roster_id,
                "p2_roster_id": p2_roster_id,
                "rng_seed": rng_seed,
                "initiative_player": initiative_player,
            },
            error_label=error_label,
        )
        return _metadata_from_payload(payload, error_label=error_label)

    def simulate_roster_ids(
        self,
        *,
        p1_roster_id: int,
        p2_roster_id: int,
        bot: str = "priority",
        n: int = 10,
        seed: int = 0,
        map_name: str = "lustrzana_a",
    ) -> SimulationSummary:
        """Run sandbox simulation via `POST /battles/simulate`."""
        if n <= 0:
            raise ValueError(f"n musi byc > 0, jest {n}")
        error_label = "POST battle simulation"
        payload = self._request_json(
            "POST",
            "/battles/simulate",
            {},
            json_body={
                "p1_roster_id": p1_roster_id,
                "p2_roster_id": p2_roster_id,
                "games": n,
                "bot": bot,
                "seed": seed,
                "map_name": map_name,
            },
            error_label=error_label,
        )
        return _simulation_summary_from_payload(payload, error_label=error_label)

    def get_battle_metadata(self, battle_id: int) -> BattleMetadata:
        """Return participant-scoped battle metadata from the B4 API."""
        error_label = "GET battle metadata"
        payload = self._get_json(
            f"/battles/{battle_id}",
            {},
            error_label=error_label,
        )
        return _metadata_from_payload(
            payload,
            error_label=error_label,
            expected_battle_id=battle_id,
        )

    def get_events(self, battle_id: int, since: int = 0) -> tuple[BattleEvent, ...]:
        """Return battle events with `sequence > since` from the B4 polling API."""
        if type(since) is not int or since < 0:
            raise ValueError("since must be an int >= 0")
        error_label = "GET battle events"
        payload = self._get_json(
            f"/battles/{battle_id}/events",
            {"since": since},
            error_label=error_label,
        )
        if not isinstance(payload, dict):
            raise HttpClientError(f"{error_label} returned malformed payload")
        _ensure_expected_battle_id(
            payload,
            battle_id,
            error_label=error_label,
        )
        events = payload.get("events")
        if not isinstance(events, list):
            raise HttpClientError("GET battle events returned malformed payload")
        try:
            return validate_event_delta(
                (_event_from_public_payload(item) for item in events),
                since=since,
            )
        except ValueError as exc:
            raise HttpClientError(
                "GET battle events returned malformed payload"
            ) from exc

    def get_state_checkpoint(self, battle_id: int) -> BattleStateCheckpoint:
        """Return state and sequence from the same versioned ``GET /state``."""
        error_label = "GET battle state"
        payload = self._get_json(
            f"/battles/{battle_id}/state",
            {},
            error_label=error_label,
        )
        if not isinstance(payload, dict):
            raise HttpClientError(f"{error_label} returned malformed payload")
        _ensure_expected_battle_id(payload, battle_id, error_label=error_label)
        try:
            sequence_at = _required_int(payload, "sequence_at")
            if sequence_at < 0:
                raise TypeError("sequence_at")
            schema = _required_str(payload, "schema")
            version = _required_int(payload, "version")
            state = battle_state_from_json(
                {
                    "schema": schema,
                    "version": version,
                    "state": payload["state"],
                }
            )
            return BattleStateCheckpoint(
                battle_id=battle_id,
                sequence_at=sequence_at,
                schema=schema,
                version=version,
                state=state,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpClientError(
                f"{error_label} returned malformed payload"
            ) from exc

    def get_state(self, battle_id: int) -> BattleState:
        """Return the participant-scoped current domain state of a battle."""
        return self.get_state_checkpoint(battle_id).state

    def lookup_rule(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        """Look up canonical rule points through the public read-only API."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        if type(limit) is not int or not 1 <= limit <= MAX_RULE_RESULTS:
            raise ValueError(
                f"limit must be an int between 1 and {MAX_RULE_RESULTS}"
            )
        error_label = "GET rule lookup"
        payload = self._get_json(
            "/rules/lookup",
            {"query": normalized_query, "limit": limit},
            error_label=error_label,
        )
        return _rule_lookup_from_payload(
            payload,
            expected_query=normalized_query,
            requested_limit=limit,
            error_label=error_label,
        )

    def search_rules(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        """Search canonical rules semantically through the scoped hybrid API."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        if type(limit) is not int or not 1 <= limit <= MAX_RULE_RESULTS:
            raise ValueError(
                f"limit must be an int between 1 and {MAX_RULE_RESULTS}"
            )
        error_label = "POST rules search"
        payload = self._request_json(
            "POST",
            "/rules/search",
            {},
            json_body={"query": normalized_query, "limit": limit},
            error_label=error_label,
            timeout=max(self._timeout, RAG_SEARCH_TIMEOUT),
        )
        return _rules_search_from_payload(
            payload,
            expected_query=normalized_query,
            requested_limit=limit,
            error_label=error_label,
        )

    def validate_loadout(
        self,
        unit_id: int,
        loadout: dict[str, Any],
        count: int = 1,
    ) -> dict[str, Any]:
        """Validate and quote one global catalog unit without persisting it."""
        if type(unit_id) is not int or unit_id < 1:
            raise ValueError("unit_id must be an int >= 1")
        if type(count) is not int or not 1 <= count <= MAX_LOADOUT_COUNT:
            raise ValueError(
                f"count must be an int between 1 and {MAX_LOADOUT_COUNT}"
            )
        canonical_loadout = _canonical_json_object(loadout, label="loadout")
        error_label = "POST loadout validation"
        payload = self._request_json(
            "POST",
            f"/units/{unit_id}/validate-loadout",
            {},
            json_body={"loadout": canonical_loadout, "count": count},
            error_label=error_label,
        )
        return _loadout_validation_from_payload(
            payload,
            expected_unit_id=unit_id,
            expected_count=count,
            error_label=error_label,
        )

    def explain_ability(self, query: str) -> dict[str, Any]:
        """Explain one canonical ability by slug or normalized display name."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_ABILITY_QUERY_LENGTH,
        )
        error_label = "GET ability explanation"
        payload = self._get_json(
            "/abilities/explain",
            {"query": normalized_query},
            error_label=error_label,
        )
        return _ability_explanation_from_payload(
            payload,
            expected_query=normalized_query,
            error_label=error_label,
        )

    def propose_battle_action(
        self,
        battle_id: int,
        *,
        expected_sequence: int,
        action: Mapping[str, Any],
        summary: str,
    ) -> BattleActionProposal:
        """Create a validated consent request without mutating the battle."""
        if type(battle_id) is not int or battle_id < 1:
            raise ValueError("battle_id must be an int >= 1")
        if type(expected_sequence) is not int or expected_sequence < 0:
            raise ValueError("expected_sequence must be an int >= 0")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        try:
            canonical_action = action_to_json(action_from_json(action))
        except (ActionCodecError, TypeError, ValueError) as exc:
            raise ValueError("action must be a valid szop.action/v1 payload") from exc

        normalized_summary = summary.strip()
        error_label = "POST battle action proposal"
        payload = self._request_json(
            "POST",
            "/agent_proposals/battle-actions",
            {},
            json_body={
                "battle_id": battle_id,
                "expected_sequence": expected_sequence,
                "action": canonical_action,
                "summary": normalized_summary,
            },
            error_label=error_label,
        )
        return _battle_action_proposal_from_payload(
            payload,
            expected_battle_id=battle_id,
            expected_sequence=expected_sequence,
            expected_action=canonical_action,
            expected_summary=normalized_summary,
            error_label=error_label,
        )

    def take_action(
        self,
        battle_id: int,
        action: Action,
        *,
        continuation: "ContinuationFn | None" = None,
    ) -> tuple[BattleState, tuple[BattleEvent, ...]]:
        """Persist one action with a freshly read optimistic sequence guard.

        Callback continuations are process-local behavior and cannot cross the
        HTTP boundary in this single-action API slice.
        """
        if continuation is not None:
            raise ValueError(
                "HttpClient.take_action does not support continuation callbacks"
            )
        wire_action = action_to_json(action)
        expected_sequence = self.get_state_checkpoint(battle_id).sequence_at
        error_label = "POST battle action"
        payload = self._request_json(
            "POST",
            f"/battles/{battle_id}/actions",
            {},
            json_body={
                "expected_sequence": expected_sequence,
                "action": wire_action,
            },
            error_label=error_label,
        )
        return _action_result_from_payload(
            payload,
            expected_battle_id=battle_id,
            expected_previous_sequence=expected_sequence,
            error_label=error_label,
        )

    def _get_json(
        self,
        path: str,
        query: dict[str, Any],
        *,
        error_label: str,
    ) -> Any:
        return self._request_json(
            "GET", path, query, json_body=None, error_label=error_label
        )

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any],
        *,
        json_body: dict[str, Any] | None,
        error_label: str,
        timeout: float | None = None,
    ) -> Any:
        body = (
            None
            if json_body is None
            else json.dumps(
                json_body,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        response = self._transport(
            HttpRequest(
                method=method,
                url=self._url(path, query),
                headers=self._headers(with_json_body=json_body is not None),
                body=body,
                timeout=self._timeout if timeout is None else timeout,
            )
        )
        if not 200 <= response.status_code < 300:
            raise HttpClientError(
                f"{error_label} failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return _decode_json(response.body)

    def _headers(self, *, with_json_body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if with_json_body:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str, query: dict[str, Any]) -> str:
        if not query:
            return f"{self._base_url}{path}"
        return f"{self._base_url}{path}?{urlencode(query)}"


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpClientError("HTTP response body is not valid JSON") from exc


def _normalize_reference_query(query: str, *, max_length: int) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"query must contain at most {max_length} characters")
    return normalized


def _is_strict_json_value(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_strict_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            type(key) is str and _is_strict_json_value(item)
            for key, item in value.items()
        )
    return False


def _canonical_json_object(value: Any, *, label: str) -> dict[str, Any]:
    try:
        if type(value) is not dict or not _is_strict_json_value(value):
            raise TypeError(label)
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(f"{label} must be a finite JSON object") from exc


def _rule_lookup_from_payload(
    payload: Any,
    *,
    expected_query: str,
    requested_limit: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        source = _required_str(payload, "source")
        query = _required_str(payload, "query")
        normalized_query = _bounded_required_str(
            payload,
            "normalized_query",
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        mode = _required_str(payload, "mode")
        raw_matches = payload["matches"]
        if (
            schema != RULE_LOOKUP_SCHEMA
            or version != REFERENCE_API_VERSION
            or source != RULE_SOURCE
            or query != expected_query
            or mode not in {"reference", "search"}
            or not isinstance(raw_matches, list)
            or len(raw_matches) > requested_limit
        ):
            raise TypeError("rule lookup envelope")
        matches = [
            _rule_match_from_payload(item, mode=mode)
            for item in raw_matches
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "source": source,
        "query": query,
        "normalized_query": normalized_query,
        "mode": mode,
        "matches": matches,
    }


def _rules_search_from_payload(
    payload: Any,
    *,
    expected_query: str,
    requested_limit: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {"schema", "version", "query", "strategy", "count", "results"},
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        query = _bounded_required_str(
            payload,
            "query",
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        strategy = _required_str(payload, "strategy")
        count = _required_int(payload, "count")
        raw_results = payload["results"]
        if (
            schema != RULES_SEARCH_SCHEMA
            or version != REFERENCE_API_VERSION
            or query != expected_query
            or strategy != RULES_SEARCH_STRATEGY
            or count < 0
            or count > requested_limit
            or not isinstance(raw_results, list)
            or len(raw_results) != count
        ):
            raise TypeError("rules search envelope")
        results = [
            _rules_search_result_from_payload(item, expected_rank=rank)
            for rank, item in enumerate(raw_results, start=1)
        ]
        if len({result["chunk_id"] for result in results}) != count:
            raise TypeError("rules search chunk IDs")
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "query": query,
        "strategy": strategy,
        "count": count,
        "results": results,
    }


def _loadout_validation_from_payload(
    payload: Any,
    *,
    expected_unit_id: int,
    expected_count: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {
                "schema",
                "version",
                "unit_id",
                "unit_name",
                "count",
                "mode",
                "sections",
                "passive",
                "cost",
                "has_issues",
            },
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        unit_id = _required_int(payload, "unit_id")
        unit_name = _bounded_required_str(payload, "unit_name", max_length=120)
        count = _required_int(payload, "count")
        mode = _loadout_mode_from_payload(payload["mode"])
        sections = _loadout_sections_from_payload(payload["sections"])
        passive = _loadout_passive_from_payload(payload["passive"])
        cost = _loadout_cost_from_payload(payload["cost"])
        has_issues = payload["has_issues"]
        expected_issues = bool(
            mode["clamped"]
            or passive["rejected"]
            or any(section["rejected"] or section["clamped"] for section in sections)
        )
        if (
            schema != LOADOUT_VALIDATION_SCHEMA
            or version != LOADOUT_VALIDATION_VERSION
            or unit_id != expected_unit_id
            or count != expected_count
            or not 1 <= count <= MAX_LOADOUT_COUNT
            or type(has_issues) is not bool
            or has_issues is not expected_issues
        ):
            raise TypeError("loadout validation envelope")
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "unit_id": unit_id,
        "unit_name": unit_name,
        "count": count,
        "mode": mode,
        "sections": sections,
        "passive": passive,
        "cost": cost,
        "has_issues": has_issues,
    }


def _loadout_mode_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout mode")
    _require_exact_keys(payload, {"raw", "normalized", "clamped"})
    raw = payload["raw"]
    normalized = _required_str(payload, "normalized")
    clamped = payload["clamped"]
    if (
        not _is_strict_json_value(raw)
        or normalized not in {"per_model", "total"}
        or type(clamped) is not bool
    ):
        raise TypeError("loadout mode")
    return {"raw": raw, "normalized": normalized, "clamped": clamped}


def _loadout_sections_from_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) != 3:
        raise TypeError("loadout sections")
    sections = [
        _loadout_section_from_payload(section, expected_name=expected_name)
        for section, expected_name in zip(
            payload,
            ("weapons", "active", "aura"),
            strict=True,
        )
    ]
    return sections


def _loadout_section_from_payload(
    payload: Any,
    *,
    expected_name: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout section")
    _require_exact_keys(payload, {"section", "accepted", "rejected", "clamped"})
    section = _required_str(payload, "section")
    if section != expected_name:
        raise TypeError("loadout section order")
    return {
        "section": section,
        "accepted": _loadout_count_mapping(payload["accepted"]),
        "rejected": _rejected_loadout_items(payload["rejected"]),
        "clamped": _clamped_loadout_items(payload["clamped"]),
    }


def _loadout_count_mapping(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise TypeError("loadout count mapping")
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if type(key) is not str or not key or type(value) is not int or value < 0:
            raise TypeError("loadout count mapping")
        counts[key] = value
    return counts


def _rejected_loadout_items(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        raise TypeError("rejected loadout items")
    items: list[dict[str, str]] = []
    allowed_reasons = {"niedozwolone dla tej jednostki", "niepoprawne id"}
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("rejected loadout item")
        _require_exact_keys(item, {"id", "reason"})
        item_id = _required_str(item, "id")
        reason = _required_str(item, "reason")
        if not item_id or reason not in allowed_reasons:
            raise TypeError("rejected loadout item")
        items.append({"id": item_id, "reason": reason})
    return items


def _clamped_loadout_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise TypeError("clamped loadout items")
    items: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("clamped loadout item")
        _require_exact_keys(item, {"id", "raw", "normalized"})
        item_id = _required_str(item, "id")
        raw = item["raw"]
        normalized = _required_int(item, "normalized")
        if not item_id or not _is_strict_json_value(raw) or normalized < 0:
            raise TypeError("clamped loadout item")
        items.append({"id": item_id, "raw": raw, "normalized": normalized})
    return items


def _loadout_passive_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout passive")
    _require_exact_keys(payload, {"accepted", "rejected"})
    rejected = payload["rejected"]
    if not isinstance(rejected, list) or any(
        type(slug) is not str or not slug for slug in rejected
    ):
        raise TypeError("loadout passive")
    return {
        "accepted": _loadout_count_mapping(payload["accepted"]),
        "rejected": list(rejected),
    }


def _loadout_cost_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout cost")
    _require_exact_keys(payload, {"selected_role", "selected_total", "components"})
    selected_role = payload["selected_role"]
    selected_total = _required_finite_float(payload, "selected_total")
    components = payload["components"]
    if (
        selected_role not in {None, "wojownik", "strzelec"}
        or selected_total < 0.0
        or not isinstance(components, dict)
    ):
        raise TypeError("loadout cost")
    component_names = {"active", "aura", "base", "passive", "weapon"}
    _require_exact_keys(components, component_names)
    return {
        "selected_role": selected_role,
        "selected_total": selected_total,
        "components": {
            name: _required_finite_float(components, name)
            for name in sorted(component_names)
        },
    }


def _rules_search_result_from_payload(
    payload: Any,
    *,
    expected_rank: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("rules search result")
    _require_exact_keys(
        payload,
        {
            "rank",
            "chunk_id",
            "source",
            "headings",
            "refs",
            "text",
            "score",
            "components",
        },
    )
    rank = _required_int(payload, "rank")
    source = _required_str(payload, "source")
    if rank != expected_rank or source not in RULE_SEARCH_SOURCES:
        raise TypeError("rules search rank or source")
    components = _rules_search_components_from_payload(payload["components"])
    score = _required_finite_float(payload, "score", positive=True)
    contribution_sum = sum(
        component["contribution"]
        for component in components.values()
        if component is not None
    )
    if not math.isclose(score, contribution_sum, rel_tol=0.0, abs_tol=2e-12):
        raise TypeError("rules search score")
    return {
        "rank": rank,
        "chunk_id": _bounded_required_str(payload, "chunk_id", max_length=128),
        "source": source,
        "headings": _bounded_string_list(
            payload["headings"],
            max_items=12,
            max_length=300,
        ),
        "refs": _bounded_string_list(
            payload["refs"],
            max_items=64,
            max_length=64,
        ),
        "text": _bounded_required_str(
            payload,
            "text",
            max_length=MAX_RULE_SEARCH_TEXT_LENGTH,
        ),
        "score": score,
        "components": components,
    }


def _rules_search_components_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("rules search components")
    _require_exact_keys(payload, {"bm25", "dense"})
    bm25 = _rrf_component_from_payload(payload["bm25"], expected_weight=2.0)
    dense = _rrf_component_from_payload(payload["dense"], expected_weight=1.0)
    if bm25 is None and dense is None:
        raise TypeError("rules search components")
    return {"bm25": bm25, "dense": dense}


def _rrf_component_from_payload(
    payload: Any,
    *,
    expected_weight: float,
) -> dict[str, int | float] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError("RRF component")
    _require_exact_keys(payload, {"rank", "weight", "contribution"})
    rank = _required_int(payload, "rank")
    weight = _required_finite_float(payload, "weight", positive=True)
    contribution = _required_finite_float(
        payload,
        "contribution",
        positive=True,
    )
    if not 1 <= rank <= 5 or weight != expected_weight:
        raise TypeError("RRF component")
    return {
        "rank": rank,
        "weight": weight,
        "contribution": contribution,
    }


def _bounded_string_list(
    value: Any,
    *,
    max_items: int,
    max_length: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > max_items
        or any(
            not isinstance(item, str) or not item or len(item) > max_length
            for item in value
        )
    ):
        raise TypeError("bounded string list")
    return list(value)


def _require_exact_keys(payload: dict[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise TypeError("unexpected object keys")


def _required_finite_float(
    payload: dict[str, Any],
    key: str,
    *,
    positive: bool = False,
) -> float:
    value = payload[key]
    if type(value) is not float or not math.isfinite(value):
        raise TypeError(key)
    if positive and value <= 0.0:
        raise TypeError(key)
    return value


def _rule_match_from_payload(item: Any, *, mode: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TypeError("rule match")
    ref = _bounded_required_str(item, "ref", max_length=32)
    text = _bounded_required_str(
        item,
        "text",
        max_length=MAX_RULE_TEXT_LENGTH,
        allow_empty=True,
    )
    parents = _rule_context_list(item["parents"], max_items=2)
    children = _rule_context_list(
        item["children"],
        max_items=MAX_RULE_CHILDREN,
    )
    score = item["score"]
    if mode == "reference":
        if score is not None:
            raise TypeError("reference score")
    elif type(score) is not int or score < 1:
        raise TypeError("search score")
    return {
        "ref": ref,
        "text": text,
        "parents": parents,
        "children": children,
        "score": score,
    }


def _rule_context_list(value: Any, *, max_items: int) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > max_items:
        raise TypeError("rule context")
    contexts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError("rule context")
        contexts.append(
            {
                "ref": _bounded_required_str(item, "ref", max_length=32),
                "text": _bounded_required_str(
                    item,
                    "text",
                    max_length=MAX_RULE_TEXT_LENGTH,
                    allow_empty=True,
                ),
            }
        )
    return contexts


def _ability_explanation_from_payload(
    payload: Any,
    *,
    expected_query: str,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        source = _required_str(payload, "source")
        query = _required_str(payload, "query")
        if (
            schema != ABILITY_EXPLANATION_SCHEMA
            or version != REFERENCE_API_VERSION
            or source != ABILITY_SOURCE
            or query != expected_query
        ):
            raise TypeError("ability explanation envelope")
        ability = _ability_from_payload(payload["ability"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "source": source,
        "query": query,
        "ability": ability,
    }


def _ability_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("ability")
    value_label = _optional_bounded_str(payload, "value_label", max_length=100)
    value_type = _optional_bounded_str(payload, "value_type", max_length=50)
    requires_value = payload["requires_value"]
    blocked = payload["blocked"]
    raw_choices = payload["value_choices"]
    if (
        type(requires_value) is not bool
        or type(blocked) is not bool
        or not isinstance(raw_choices, list)
        or len(raw_choices) > 50
        or any(
            not isinstance(choice, str) or len(choice) > 100
            for choice in raw_choices
        )
    ):
        raise TypeError("ability fields")
    return {
        "slug": _bounded_required_str(payload, "slug", max_length=100),
        "name": _bounded_required_str(payload, "name", max_length=200),
        "display_name": _bounded_required_str(
            payload,
            "display_name",
            max_length=250,
        ),
        "type": _bounded_required_str(payload, "type", max_length=50),
        "description": _bounded_required_str(
            payload,
            "description",
            max_length=10_000,
            allow_empty=True,
        ),
        "value_label": value_label,
        "value_type": value_type,
        "requires_value": requires_value,
        "value_choices": list(raw_choices),
        "blocked": blocked,
    }


def _bounded_required_str(
    payload: dict[str, Any],
    key: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    value = _required_str(payload, key)
    if len(value) > max_length or (not allow_empty and not value):
        raise TypeError(key)
    return value


def _optional_bounded_str(
    payload: dict[str, Any],
    key: str,
    *,
    max_length: int,
) -> str | None:
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise TypeError(key)
    return value


def _metadata_from_payload(
    payload: Any,
    *,
    error_label: str,
    expected_battle_id: int | None = None,
) -> BattleMetadata:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    if expected_battle_id is not None:
        _ensure_expected_battle_id(
            payload,
            expected_battle_id,
            error_label=error_label,
        )
    try:
        return BattleMetadata(
            battle_id=_required_int(payload, "battle_id"),
            p1_user_id=_optional_int(payload, "p1_user_id"),
            p2_user_id=_optional_int(payload, "p2_user_id"),
            p1_roster_id=_optional_int(payload, "p1_roster_id"),
            p2_roster_id=_optional_int(payload, "p2_roster_id"),
            winner_user_id=_optional_int(payload, "winner_user_id"),
            current_round=_required_int(payload, "current_round"),
            rng_seed=_required_int(payload, "rng_seed"),
            status=_required_str(payload, "status"),
            latest_sequence=_required_int(payload, "latest_sequence"),
        )
    except (KeyError, TypeError) as exc:
        raise HttpClientError(error_message) from exc


def _simulation_summary_from_payload(
    payload: Any,
    *,
    error_label: str,
) -> SimulationSummary:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        summary = SimulationSummary(
            n_games=_required_int(payload, "n_games"),
            wins_p0=_required_int(payload, "wins_p0"),
            wins_p1=_required_int(payload, "wins_p1"),
            draws=_required_int(payload, "draws"),
            total_rounds=_required_int(payload, "total_rounds"),
        )
    except (KeyError, TypeError) as exc:
        raise HttpClientError(error_message) from exc
    if (
        summary.n_games <= 0
        or summary.wins_p0 < 0
        or summary.wins_p1 < 0
        or summary.draws < 0
        or summary.total_rounds < 0
        or summary.wins_p0 + summary.wins_p1 + summary.draws != summary.n_games
    ):
        raise HttpClientError(error_message)
    return summary


def _action_result_from_payload(
    payload: Any,
    *,
    expected_battle_id: int,
    expected_previous_sequence: int,
    error_label: str,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    _ensure_expected_battle_id(
        payload,
        expected_battle_id,
        error_label=error_label,
    )
    try:
        previous_sequence = _required_int(payload, "previous_sequence")
        new_sequence = _required_int(payload, "new_sequence")
        if (
            previous_sequence != expected_previous_sequence
            or new_sequence < previous_sequence
        ):
            raise TypeError("action sequence")
        state_payload = payload["state"]
        if not isinstance(state_payload, dict):
            raise TypeError("state")
        state = battle_state_from_json(state_payload)
        raw_events = payload["events"]
        if not isinstance(raw_events, list):
            raise TypeError("events")
        events = tuple(_event_from_public_payload(item) for item in raw_events)
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc

    expected_sequences = tuple(range(previous_sequence + 1, new_sequence + 1))
    if tuple(event.sequence for event in events) != expected_sequences:
        raise HttpClientError(error_message)
    return state, events


def _battle_action_proposal_from_payload(
    payload: Any,
    *,
    expected_battle_id: int,
    expected_sequence: int,
    expected_action: dict[str, Any],
    expected_summary: str,
    error_label: str,
) -> BattleActionProposal:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        if _required_str(payload, "action") != "battle:action":
            raise TypeError("action")
        if _required_str(payload, "status") != "pending":
            raise TypeError("status")
        if _required_str(payload, "summary") != expected_summary:
            raise TypeError("summary")
        proposal_payload = payload["payload"]
        if (
            not isinstance(proposal_payload, dict)
            or set(proposal_payload)
            != {"battle_id", "expected_sequence", "action"}
        ):
            raise TypeError("payload")
        battle_id = _required_int(proposal_payload, "battle_id")
        sequence = _required_int(proposal_payload, "expected_sequence")
        action = proposal_payload["action"]
        if (
            battle_id != expected_battle_id
            or sequence != expected_sequence
            or action != expected_action
        ):
            raise TypeError("proposal payload")
        return BattleActionProposal(
            proposal_id=_required_int(payload, "id"),
            owner_user_id=_required_int(payload, "owner_user_id"),
            agent_user_id=_required_int(payload, "agent_user_id"),
            token_id=_optional_int(payload, "token_id"),
            battle_id=battle_id,
            expected_sequence=sequence,
            action=action,
            summary=expected_summary,
            status="pending",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc


def _ensure_expected_battle_id(
    payload: dict[str, Any],
    expected_battle_id: int,
    *,
    error_label: str,
) -> None:
    try:
        battle_id = _required_int(payload, "battle_id")
    except (KeyError, TypeError) as exc:
        raise HttpClientError(f"{error_label} returned malformed payload") from exc
    if battle_id != expected_battle_id:
        raise HttpClientError(
            f"{error_label} returned battle_id {battle_id}, "
            f"expected {expected_battle_id}"
        )


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise TypeError(key)
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload[key]
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(key)
    return value


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _event_from_public_payload(item: Any) -> BattleEvent:
    if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
        raise HttpClientError("Battle event payload is malformed")
    try:
        sequence = _required_int(item, "sequence")
        event_type = _required_str(item, "event_type")
        event = json_to_event(item["payload"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError("Battle event payload cannot be decoded") from exc
    if event.sequence != sequence or type(event).__name__ != event_type:
        raise HttpClientError("Battle event envelope does not match its payload")
    return event


def _urlopen_transport(request: HttpRequest) -> HttpResponse:
    urllib_request = Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        with urlopen(urllib_request, timeout=request.timeout) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            return HttpResponse(status_code=status_code, body=response.read())
    except HTTPError as exc:
        body = exc.read()
        return HttpResponse(status_code=exc.code, body=body)
    except URLError as exc:
        raise HttpClientTransportError(f"HTTP transport failed: {exc.reason}") from exc
