from __future__ import annotations

import json

import pytest

from app.services.engine.events import MoveExecuted, StatusAdded, event_to_json
from szop_client import (
    BattleMetadata,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
)


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        body=json.dumps(payload).encode("utf-8"),
    )


def test_get_battle_metadata_fetches_b4_metadata_endpoint() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(
            {
                "battle_id": 42,
                "p1_user_id": 10,
                "p2_user_id": 20,
                "p1_roster_id": 100,
                "p2_roster_id": None,
                "winner_user_id": None,
                "current_round": 3,
                "rng_seed": 777,
                "status": "active",
                "latest_sequence": 9,
            }
        )

    client = HttpClient("https://szop.example/api/", token="raw-token", transport=transport)

    assert client.get_battle_metadata(42) == BattleMetadata(
        battle_id=42,
        p1_user_id=10,
        p2_user_id=20,
        p1_roster_id=100,
        p2_roster_id=None,
        winner_user_id=None,
        current_round=3,
        rng_seed=777,
        status="active",
        latest_sequence=9,
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.url == "https://szop.example/api/battles/42"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert request.body is None


def test_get_battle_metadata_raises_for_http_error_status() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=404, body=b'{"detail":"missing"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_battle_metadata(999)

    assert exc_info.value.status_code == 404


def test_get_battle_metadata_raises_for_malformed_payload() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response({"battle_id": 1, "latest_sequence": "bad"})

    with pytest.raises(HttpClientError):
        HttpClient("http://localhost", transport=transport).get_battle_metadata(1)


def test_get_events_polls_b4_endpoint_and_decodes_engine_events() -> None:
    seen: list[HttpRequest] = []
    events = (
        MoveExecuted(sequence=1, unit_id=10, from_pos=(0.0, 0.0), to_pos=(1.0, 2.0)),
        StatusAdded(sequence=2, target_id=10, status="Aktywowany"),
    )

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response({
            "battle_id": 42,
            "events": [
                {
                    "sequence": event.sequence,
                    "event_type": type(event).__name__,
                    "payload": event_to_json(event),
                }
                for event in events
            ],
        })

    client = HttpClient("https://szop.example/api/", token="raw-token", transport=transport)

    assert client.get_events(42, since=7) == events
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.url == "https://szop.example/api/battles/42/events?since=7"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert request.body is None


def test_get_events_omits_authorization_header_without_token() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response({"battle_id": 1, "events": []})

    assert HttpClient("http://localhost", transport=transport).get_events(1) == ()
    assert "Authorization" not in seen[0].headers


def test_get_events_rejects_negative_since_before_transport() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).get_events(1, since=-1)


def test_get_events_raises_for_http_error_status() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=404, body=b'{"detail":"missing"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_events(999)

    assert exc_info.value.status_code == 404


def test_get_events_raises_for_malformed_payload() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response({"battle_id": 1, "events": [{"payload": {"bad": "event"}}]})

    with pytest.raises(HttpClientError):
        HttpClient("http://localhost", transport=transport).get_events(1)
