"""HTTP client slices for the B4 battle API.

The full `GameClient` HTTP implementation is still waiting for the remaining
B4 endpoints. This module implements the shipped slices: read-only metadata
fetch (`get_battle_metadata`) and event polling (`get_events`), plus the
sandbox write slice `create_battle` backed by `POST /battles`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.engine.events import BattleEvent, json_to_event


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
    """Minimal HTTP client for battle metadata, event polling and sandbox create."""

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
        if since < 0:
            raise ValueError("since must be >= 0")
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
        return tuple(_event_from_public_payload(item) for item in events)

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
    ) -> Any:
        body = None if json_body is None else json.dumps(json_body).encode("utf-8")
        response = self._transport(
            HttpRequest(
                method=method,
                url=self._url(path, query),
                headers=self._headers(with_json_body=json_body is not None),
                body=body,
                timeout=self._timeout,
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
    if not isinstance(value, int):
        raise TypeError(key)
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, int):
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
        return json_to_event(item["payload"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError("Battle event payload cannot be decoded") from exc


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
