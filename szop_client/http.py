"""Read-only HTTP client slice for B4 battle event polling.

The full `GameClient` HTTP implementation is still waiting for the remaining
B4 endpoints. This module deliberately implements only `get_events`, backed by
the existing `GET /battles/{id}/events?since=N` API.
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


Transport = Callable[[HttpRequest], HttpResponse]


class HttpClientError(RuntimeError):
    """HTTP API returned an error status or malformed payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpClientTransportError(HttpClientError):
    """HTTP transport failed before a valid API response was received."""


class HttpClient:
    """Minimal read-only HTTP client for battle event polling."""

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

    def get_events(self, battle_id: int, since: int = 0) -> tuple[BattleEvent, ...]:
        """Return battle events with `sequence > since` from the B4 polling API."""
        if since < 0:
            raise ValueError("since must be >= 0")
        response = self._transport(
            HttpRequest(
                method="GET",
                url=self._url(f"/battles/{battle_id}/events", {"since": since}),
                headers=self._headers(),
                body=None,
                timeout=self._timeout,
            )
        )
        if not 200 <= response.status_code < 300:
            raise HttpClientError(
                f"GET battle events failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = _decode_json(response.body)
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            raise HttpClientError("GET battle events returned malformed payload")
        return tuple(_event_from_public_payload(item) for item in events)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str, query: dict[str, Any]) -> str:
        return f"{self._base_url}{path}?{urlencode(query)}"


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpClientError("HTTP response body is not valid JSON") from exc


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
