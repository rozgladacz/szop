from __future__ import annotations

import json
from typing import Any, get_args
from unittest.mock import patch

import pytest

from app.services.engine.action_codec import action_from_json, action_to_json
from app.services.engine.actions import DefendAction
from app.services.engine.events import (
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    BattleEvent,
    EffectApplied,
    InitiativePassed,
    InterruptTriggered,
    MeleeBalanceReset,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    MutexCollision,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
    event_to_json,
)
from app.services.engine.state_codec import battle_state_to_json
from szop_client import (
    BattleMetadata,
    BattleStateCheckpoint,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
    LocalClient,
    SimulationSummary,
    battle_events_to_wire,
    battle_state_checkpoint_to_wire,
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
        MoveExecuted(sequence=8, unit_id=10, from_pos=(0.0, 0.0), to_pos=(1.0, 2.0)),
        StatusAdded(sequence=9, target_id=10, status="Aktywowany"),
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


@pytest.mark.parametrize("since", [-1, True])
def test_get_events_rejects_invalid_since_before_transport(since) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).get_events(1, since=since)


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


@pytest.mark.parametrize("sequences", [(7,), (9, 8), (8, 8)])
def test_get_events_rejects_events_not_strictly_ordered_after_since(
    sequences: tuple[int, ...],
) -> None:
    events = [
        StatusAdded(sequence=sequence, target_id=10, status="Aktywowany")
        for sequence in sequences
    ]

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(
            {
                "battle_id": 42,
                "events": [
                    {
                        "sequence": event.sequence,
                        "event_type": type(event).__name__,
                        "payload": event_to_json(event),
                    }
                    for event in events
                ],
            }
        )

    with pytest.raises(HttpClientError, match="malformed payload"):
        HttpClient("http://localhost", transport=transport).get_events(42, since=7)


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


def test_get_state_checkpoint_exposes_one_coherent_public_snapshot() -> None:
    local_state = _equivalent_local_state()

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(
            {
                **battle_state_to_json(local_state),
                "battle_id": 42,
                "sequence_at": 17,
            }
        )

    checkpoint = HttpClient(
        "http://localhost", transport=transport
    ).get_state_checkpoint(42)

    assert checkpoint == BattleStateCheckpoint(
        battle_id=42,
        sequence_at=17,
        schema="szop.battle_state",
        version=1,
        state=local_state,
    )
    projected = battle_state_checkpoint_to_wire(checkpoint)
    assert projected["battle_id"] == 42
    assert projected["sequence_at"] == 17
    assert "rng" not in projected
    json.dumps(projected, allow_nan=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("battle_id", True),
        ("battle_id", 0),
        ("sequence_at", True),
        ("sequence_at", -1),
        ("schema", ""),
        ("version", True),
    ],
)
def test_battle_state_checkpoint_rejects_invalid_public_metadata(
    field: str,
    value: Any,
) -> None:
    values = {
        "battle_id": 42,
        "sequence_at": 17,
        "schema": "szop.battle_state",
        "version": 1,
        "state": _equivalent_local_state(),
    }
    values[field] = value

    with pytest.raises(ValueError):
        BattleStateCheckpoint(**values)


def test_get_state_delegates_to_public_checkpoint_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _equivalent_local_state()
    checkpoint = BattleStateCheckpoint(
        battle_id=42,
        sequence_at=2,
        schema="szop.battle_state",
        version=1,
        state=state,
    )
    client = HttpClient(
        "http://localhost",
        transport=lambda _request: (_ for _ in ()).throw(
            AssertionError("transport should not be called")
        ),
    )
    seen: list[int] = []

    def get_checkpoint(battle_id: int) -> BattleStateCheckpoint:
        seen.append(battle_id)
        return checkpoint

    monkeypatch.setattr(client, "get_state_checkpoint", get_checkpoint)

    assert client.get_state(42) is state
    assert seen == [42]


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


def test_take_action_fetches_fresh_sequence_posts_wire_and_matches_local_client() -> None:
    seen: list[HttpRequest] = []
    local = LocalClient()
    local_battle_id = local.create_battle(
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
    )
    initial_events = local.get_events(local_battle_id)
    initial_sequence = initial_events[-1].sequence
    local_result: list[tuple] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        if request.method == "GET":
            serialized = battle_state_to_json(local.get_state(local_battle_id))
            return _json_response(
                {
                    **serialized,
                    "battle_id": 42,
                    "sequence_at": initial_sequence,
                }
            )
        body = json.loads(request.body.decode("utf-8"))
        assert body["expected_sequence"] == initial_sequence
        decoded_action = action_from_json(body["action"])
        state, events = local.take_action(
            local_battle_id,
            decoded_action,
            continuation=None,
        )
        local_result.append((state, events))
        return _json_response(
            {
                "battle_id": 42,
                "previous_sequence": initial_sequence,
                "new_sequence": events[-1].sequence,
                "state": battle_state_to_json(state),
                "events": [
                    {
                        "sequence": event.sequence,
                        "event_type": type(event).__name__,
                        "payload": event_to_json(event),
                    }
                    for event in events
                ],
            }
        )

    client = HttpClient(
        "https://szop.example/api",
        token="raw-token",
        transport=transport,
    )
    with patch.object(
        client,
        "get_state_checkpoint",
        wraps=client.get_state_checkpoint,
    ) as get_checkpoint:
        result = client.take_action(42, DefendAction(unit_id=1), continuation=None)

    assert result == local_result[0]
    get_checkpoint.assert_called_once_with(42)
    assert [request.method for request in seen] == ["GET", "POST"]
    assert seen[1].url == "https://szop.example/api/battles/42/actions"
    assert seen[1].headers["Content-Type"] == "application/json"
    assert seen[1].headers["Authorization"] == "Bearer raw-token"
    posted = json.loads(seen[1].body.decode("utf-8"))
    assert action_from_json(posted["action"]) == DefendAction(unit_id=1)


def test_take_action_rejects_continuation_before_transport() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    client = HttpClient("http://localhost", transport=transport)

    with pytest.raises(ValueError, match="does not support continuation"):
        client.take_action(
            1,
            DefendAction(unit_id=1),
            continuation=lambda *_args: None,
        )


def test_take_action_surfaces_sequence_conflict() -> None:
    state = _equivalent_local_state()

    def transport(request: HttpRequest) -> HttpResponse:
        if request.method == "GET":
            return _json_response(
                {
                    **battle_state_to_json(state),
                    "battle_id": 42,
                    "sequence_at": 2,
                }
            )
        return HttpResponse(status_code=409, body=b'{"detail":"conflict"}')

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).take_action(
            42,
            DefendAction(unit_id=1),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(battle_id=99),
        lambda payload: payload.update(previous_sequence=True),
        lambda payload: payload.update(previous_sequence=1),
        lambda payload: payload.update(new_sequence=True),
        lambda payload: payload["events"][0].update(sequence=99),
        lambda payload: payload["events"][0].update(event_type="WrongEvent"),
        lambda payload: payload["state"].update(version=999),
    ],
)
def test_take_action_rejects_malformed_or_inconsistent_response(mutation) -> None:
    state = _equivalent_local_state()
    event = StatusAdded(sequence=3, target_id=1, status="Aktywowany")
    response_payload = {
        "battle_id": 42,
        "previous_sequence": 2,
        "new_sequence": 3,
        "state": battle_state_to_json(state),
        "events": [
            {
                "sequence": event.sequence,
                "event_type": type(event).__name__,
                "payload": event_to_json(event),
            }
        ],
    }
    mutation(response_payload)

    def transport(request: HttpRequest) -> HttpResponse:
        if request.method == "GET":
            return _json_response(
                {
                    **battle_state_to_json(state),
                    "battle_id": 42,
                    "sequence_at": 2,
                }
            )
        return _json_response(response_payload)

    with pytest.raises(HttpClientError):
        HttpClient("http://localhost", transport=transport).take_action(
            42,
            DefendAction(unit_id=1),
        )


def test_propose_battle_action_posts_frozen_wire_without_state_read() -> None:
    seen: list[HttpRequest] = []
    wire_action = action_to_json(DefendAction(unit_id=1))

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        body = json.loads(request.body.decode("utf-8"))
        return _json_response(
            {
                "id": 17,
                "owner_user_id": 10,
                "agent_user_id": 11,
                "token_id": 12,
                "action": "battle:action",
                "summary": body["summary"],
                "payload": {
                    "battle_id": body["battle_id"],
                    "expected_sequence": body["expected_sequence"],
                    "action": body["action"],
                },
                "result": None,
                "status": "pending",
                "created_at": "2026-07-16T10:00:00",
                "updated_at": "2026-07-16T10:00:00",
                "decided_at": None,
                "decided_by_user_id": None,
            }
        )

    proposal = HttpClient(
        "https://szop.example/api",
        token="proposal-token",
        transport=transport,
    ).propose_battle_action(
        42,
        expected_sequence=9,
        action=wire_action,
        summary="  Oddział 1: obrona  ",
    )

    assert proposal.proposal_id == 17
    assert proposal.battle_id == 42
    assert proposal.expected_sequence == 9
    assert proposal.action == wire_action
    assert proposal.summary == "Oddział 1: obrona"
    assert proposal.status == "pending"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/agent_proposals/battle-actions"
    assert request.headers["Authorization"] == "Bearer proposal-token"
    assert json.loads(request.body.decode("utf-8")) == {
        "battle_id": 42,
        "expected_sequence": 9,
        "action": wire_action,
        "summary": "Oddział 1: obrona",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"battle_id": True, "expected_sequence": 0, "action": {}, "summary": "x"},
        {"battle_id": 1, "expected_sequence": True, "action": {}, "summary": "x"},
        {"battle_id": 1, "expected_sequence": 0, "action": {}, "summary": "x"},
        {
            "battle_id": 1,
            "expected_sequence": 0,
            "action": action_to_json(DefendAction(unit_id=1)),
            "summary": " ",
        },
    ],
)
def test_propose_battle_action_rejects_invalid_input_before_transport(
    arguments,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).propose_battle_action(
            **arguments
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(id=True),
        lambda payload: payload.update(action="other"),
        lambda payload: payload.update(status="executed"),
        lambda payload: payload.update(summary="other"),
        lambda payload: payload["payload"].update(battle_id=99),
        lambda payload: payload["payload"].update(expected_sequence=True),
        lambda payload: payload["payload"].update(action={}),
    ],
)
def test_propose_battle_action_rejects_malformed_response(mutation) -> None:
    wire_action = action_to_json(DefendAction(unit_id=1))
    response_payload = {
        "id": 17,
        "owner_user_id": 10,
        "agent_user_id": 11,
        "token_id": 12,
        "action": "battle:action",
        "summary": "Oddział 1: obrona",
        "payload": {
            "battle_id": 42,
            "expected_sequence": 9,
            "action": wire_action,
        },
        "result": None,
        "status": "pending",
        "created_at": "2026-07-16T10:00:00",
        "updated_at": "2026-07-16T10:00:00",
        "decided_at": None,
        "decided_by_user_id": None,
    }
    mutation(response_payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(response_payload)

    with pytest.raises(HttpClientError):
        HttpClient("http://localhost", transport=transport).propose_battle_action(
            42,
            expected_sequence=9,
            action=wire_action,
            summary="Oddział 1: obrona",
        )


def test_all_current_battle_events_have_json_safe_public_projections() -> None:
    events: tuple[BattleEvent, ...] = (
        MoveExecuted(1, 1, (0.0, 0.0), (1.0, 2.0)),
        ShotResolved(2, 1, 2, "karabin", 3, 2, 1, 0),
        MeleeResolved(3, 1, 2, "miecz", 2, 1, 0, 0, 1),
        ModelKilled(4, 2, 0, True, False, 1),
        MoraleTestPassed(5, 2, (1, 6), 1, "pinned"),
        EffectApplied(6, "leczenie", 1, 2, {"amount": 1}),
        InterruptTriggered(7, "before_action", "rozkaz", 1, 2, {"x": 3}, True),
        RoundEnded(8, 2, (2, 1)),
        StatusAdded(9, 1, "Aktywowany"),
        StatusRemoved(10, 1, "Przyszpilony"),
        MeleeBalanceReset(11, 1),
        MutexCollision(12, 1, ("Przyszpilony", "Przygotowany")),
        ObjectiveControlChanged(13, 5, None, 0),
        InitiativePassed(14, 0, 1),
        AbilityOverrideApplied(15, 1, "furia", True, 2),
        AbilityOverridesCleared(16, 1),
    )

    assert {type(event) for event in events} == set(get_args(BattleEvent))
    projected, last_sequence = battle_events_to_wire(events, since=0)

    assert [item["sequence"] for item in projected] == list(range(1, 17))
    assert [item["type"] for item in projected] == [
        type(event).__name__ for event in events
    ]
    assert last_sequence == 16
    json.dumps(projected, allow_nan=False)


def test_event_projection_rejects_non_finite_payloads() -> None:
    event = EffectApplied(
        sequence=1,
        slug="bad",
        target_unit_id=1,
        payload={"value": float("nan")},
    )

    with pytest.raises(ValueError, match="not JSON-safe"):
        battle_events_to_wire((event,), since=0)
