from __future__ import annotations

import json

import pytest

from app.services.engine.events import MoveExecuted, StatusAdded, event_to_json
from app.services.engine.state_codec import battle_state_to_json
from szop_client import (
    BattleMetadata,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
    LocalClient,
    SimulationSummary,
)


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        body=json.dumps(payload).encode("utf-8"),
    )


def _battle_public_payload(battle_id: int) -> dict:
    return {
        "battle_id": battle_id,
        "p1_user_id": 10,
        "p2_user_id": 10,
        "p1_roster_id": 100,
        "p2_roster_id": 200,
        "winner_user_id": None,
        "current_round": 1,
        "rng_seed": 5,
        "status": "active",
        "latest_sequence": 4,
    }


def test_create_battle_posts_rosters_and_returns_metadata() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return HttpResponse(
            status_code=201,
            body=json.dumps(_battle_public_payload(77)).encode("utf-8"),
        )

    client = HttpClient("https://szop.example/api/", token="raw-token", transport=transport)

    metadata = client.create_battle(
        p1_roster_id=100,
        p2_roster_id=200,
        rng_seed=5,
        initiative_player=1,
    )

    assert metadata == BattleMetadata(
        battle_id=77,
        p1_user_id=10,
        p2_user_id=10,
        p1_roster_id=100,
        p2_roster_id=200,
        winner_user_id=None,
        current_round=1,
        rng_seed=5,
        status="active",
        latest_sequence=4,
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert json.loads(request.body.decode("utf-8")) == {
        "p1_roster_id": 100,
        "p2_roster_id": 200,
        "rng_seed": 5,
        "initiative_player": 1,
    }


def test_create_battle_raises_for_http_error_status() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=404, body=b'{"detail":"missing"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).create_battle(
            p1_roster_id=1, p2_roster_id=2
        )

    assert exc_info.value.status_code == 404


def test_create_battle_raises_create_label_for_malformed_payload() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response({"battle_id": 1, "latest_sequence": "bad"})

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).create_battle(
            p1_roster_id=1, p2_roster_id=2
        )

    assert "POST create battle returned malformed payload" in str(exc_info.value)
    assert "GET battle metadata" not in str(exc_info.value)


def test_create_battle_ignores_additive_adaptation_report() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        payload = _battle_public_payload(77)
        payload["adaptation_report"] = {
            "p1": {
                "dropped_excluded": [],
                "inert_incomplete": [],
                "deferred_attached_heroes": [123],
            },
            "p2": {
                "dropped_excluded": [],
                "inert_incomplete": [],
                "deferred_attached_heroes": [],
            },
        }
        return HttpResponse(
            status_code=201,
            body=json.dumps(payload).encode("utf-8"),
        )

    metadata = HttpClient("http://localhost", transport=transport).create_battle(
        p1_roster_id=100,
        p2_roster_id=200,
    )

    assert metadata.battle_id == 77
    assert metadata.latest_sequence == 4


def test_simulate_roster_ids_posts_payload_and_returns_summary() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(
            {
                "p1_roster_id": 100,
                "p2_roster_id": 200,
                "bot": "random",
                "map_name": "lustrzana_a",
                "n_games": 3,
                "wins_p0": 1,
                "wins_p1": 1,
                "draws": 1,
                "total_rounds": 12,
                "win_rate_p0": 1 / 3,
                "win_rate_p1": 1 / 3,
                "draw_rate": 1 / 3,
                "avg_rounds": 4.0,
            }
        )

    client = HttpClient("https://szop.example/api/", token="raw-token", transport=transport)

    summary = client.simulate_roster_ids(
        p1_roster_id=100,
        p2_roster_id=200,
        bot="random",
        n=3,
        seed=5,
        map_name="lustrzana_a",
    )

    assert summary == SimulationSummary(
        n_games=3,
        wins_p0=1,
        wins_p1=1,
        draws=1,
        total_rounds=12,
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles/simulate"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert json.loads(request.body.decode("utf-8")) == {
        "p1_roster_id": 100,
        "p2_roster_id": 200,
        "games": 3,
        "bot": "random",
        "seed": 5,
        "map_name": "lustrzana_a",
    }


def test_simulate_roster_ids_raises_for_http_error_status() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=400, body=b'{"detail":"bad bot"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).simulate_roster_ids(
            p1_roster_id=1, p2_roster_id=2
        )

    assert exc_info.value.status_code == 400


def test_simulate_roster_ids_raises_for_malformed_payload() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response({"n_games": 1, "wins_p0": "bad"})

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).simulate_roster_ids(
            p1_roster_id=1, p2_roster_id=2
        )

    assert "POST battle simulation returned malformed payload" in str(exc_info.value)


def test_simulate_roster_ids_rejects_bool_integer_fields() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(
            {
                "n_games": 1,
                "wins_p0": True,
                "wins_p1": 0,
                "draws": 0,
                "total_rounds": 4,
            }
        )

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).simulate_roster_ids(
            p1_roster_id=1, p2_roster_id=2
        )

    assert "POST battle simulation returned malformed payload" in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "n_games": 2,
            "wins_p0": 1,
            "wins_p1": 0,
            "draws": 0,
            "total_rounds": 4,
        },
        {
            "n_games": 1,
            "wins_p0": 1,
            "wins_p1": 0,
            "draws": 0,
            "total_rounds": -1,
        },
    ],
)
def test_simulate_roster_ids_rejects_inconsistent_summary_payload(
    payload: dict[str, int],
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).simulate_roster_ids(
            p1_roster_id=1, p2_roster_id=2
        )

    assert "POST battle simulation returned malformed payload" in str(exc_info.value)


@pytest.mark.parametrize("n", [0, -1])
def test_simulate_roster_ids_rejects_nonpositive_n_before_transport(n: int) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError, match="n musi byc > 0"):
        HttpClient("http://localhost", transport=transport).simulate_roster_ids(
            p1_roster_id=1, p2_roster_id=2, n=n
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


def test_get_battle_metadata_rejects_bool_optional_integer_fields() -> None:
    payload = _battle_public_payload(42)
    payload["p2_roster_id"] = True

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_battle_metadata(42)

    assert "GET battle metadata returned malformed payload" in str(exc_info.value)


def test_get_battle_metadata_rejects_mismatched_battle_id() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(_battle_public_payload(43))

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_battle_metadata(42)

    assert "GET battle metadata returned battle_id 43, expected 42" in str(
        exc_info.value
    )


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


def test_get_events_rejects_mismatched_battle_id() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response({"battle_id": 99, "events": []})

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_events(42)

    assert "GET battle events returned battle_id 99, expected 42" in str(
        exc_info.value
    )


def _equivalent_local_state():
    local = LocalClient()
    battle_id = local.create_battle(
        [
            {
                "owner_player": 0,
                "units": [
                    {"id": 1, "position": (0, 0), "models": 2, "toughness": 3}
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {"id": 2, "position": (12, 0), "models": 2, "toughness": 3}
                ],
            },
        ],
        seed=77,
        initiative_player=1,
    )
    return local.get_state(battle_id)


def test_get_state_returns_domain_state_with_local_client_parity() -> None:
    seen: list[HttpRequest] = []
    local_state = _equivalent_local_state()
    serialized = battle_state_to_json(local_state)

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(
            {
                **serialized,
                "battle_id": 42,
                "sequence_at": 2,
            }
        )

    state = HttpClient(
        "https://szop.example/api/", token="raw-token", transport=transport
    ).get_state(42)

    assert state == local_state
    assert seen[0].method == "GET"
    assert seen[0].url == "https://szop.example/api/battles/42/state"
    assert seen[0].headers["Authorization"] == "Bearer raw-token"
    assert seen[0].body is None


def test_get_state_raises_for_http_error_status() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=404, body=b'{"detail":"missing"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).get_state(999)

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("sequence_at"),
        lambda payload: payload.update(sequence_at=True),
        lambda payload: payload.update(version=999),
        lambda payload: payload.update(battle_id=43),
        lambda payload: payload["state"].update({"$dataclass": "__import__"}),
        lambda payload: payload["state"]["fields"].update(round="bad"),
    ],
)
def test_get_state_rejects_malformed_payload(mutation) -> None:
    payload = {
        **battle_state_to_json(_equivalent_local_state()),
        "battle_id": 42,
        "sequence_at": 2,
    }
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(HttpClientError):
        HttpClient("http://localhost", transport=transport).get_state(42)
