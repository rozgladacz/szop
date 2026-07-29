from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from app.services.engine.actions import DefendAction
from app.services.engine.events import StatusAdded, event_to_json
from app.services.engine.state_codec import battle_state_to_json
from szop_client import (
    ActivationMutationResult,
    HttpClient,
    HttpClientActivationError,
    HttpClientError,
    HttpRequest,
    HttpResponse,
    LocalClient,
)


def _v2_idle_state():
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
        initiative_player=0,
    )
    return replace(
        local.get_state(battle_id),
        pending_interrupts=(),
        initiative_player=0,
        activation=None,
    )


def _mutation_payload(
    *,
    battle_id: int = 42,
    previous_sequence: int = 7,
) -> dict[str, Any]:
    event = StatusAdded(
        sequence=previous_sequence + 1,
        target_id=1,
        status="Aktywowany",
    )
    return {
        "battle_id": battle_id,
        "previous_sequence": previous_sequence,
        "new_sequence": event.sequence,
        "state": battle_state_to_json(_v2_idle_state(), version=2),
        "events": [
            {
                "sequence": event.sequence,
                "event_type": type(event).__name__,
                "payload": event_to_json(event),
            }
        ],
    }


def _response(payload: Any, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def test_activation_v2_methods_freeze_exact_single_post_wire() -> None:
    seen: list[HttpRequest] = []
    statuses = iter((201, 200, 200, 202, 202, 200))

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        body = json.loads(request.body.decode("utf-8"))
        return _response(
            _mutation_payload(previous_sequence=body["expected_sequence"]),
            status_code=next(statuses),
        )

    client = HttpClient(
        "https://szop.example/api/",
        token="v2-token",
        transport=transport,
    )
    results = (
        client.start_activation(42, expected_sequence=7, selected_unit_id=1),
        client.interrupt(
            42,
            expected_sequence=8,
            activation_id=8,
            expected_activation_version=1,
            expected_window_version=1,
            source_unit_id=2,
            ability_slug="klatwa",
            payload={
                "target_id": 2,
                "ability": "delikatny",
                "granted": True,
            },
        ),
        client.pass_interrupt_priority(
            42,
            expected_sequence=9,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=2,
        ),
        client.commit_activation_action(
            42,
            DefendAction(unit_id=1),
            expected_sequence=10,
            activation_id=8,
            expected_activation_version=3,
        ),
        client.continue_activation(
            42,
            expected_sequence=11,
            activation_id=8,
            expected_activation_version=4,
        ),
        client.finalize_activation(
            42,
            expected_sequence=12,
            activation_id=8,
            expected_activation_version=5,
            recovery_uses=(),
        ),
    )

    assert all(isinstance(result, ActivationMutationResult) for result in results)
    assert [result.previous_sequence for result in results] == list(range(7, 13))
    assert [request.method for request in seen] == ["POST"] * 6
    assert [request.url for request in seen] == [
        "https://szop.example/api/battles/42/activations",
        "https://szop.example/api/battles/42/interrupts",
        "https://szop.example/api/battles/42/interrupts",
        "https://szop.example/api/battles/42/actions",
        "https://szop.example/api/battles/42/activations/8/transitions",
        "https://szop.example/api/battles/42/activations/8/transitions",
    ]
    assert all(request.headers["Authorization"] == "Bearer v2-token" for request in seen)
    assert [json.loads(request.body.decode("utf-8")) for request in seen] == [
        {"expected_sequence": 7, "selected_unit_id": 1},
        {
            "operation": "interrupt",
            "expected_sequence": 8,
            "activation_id": 8,
            "expected_activation_version": 1,
            "expected_window_version": 1,
            "source_unit_id": 2,
            "ability_slug": "klatwa",
            "payload": {
                "target_id": 2,
                "ability": "delikatny",
                "granted": True,
            },
        },
        {
            "operation": "pass",
            "expected_sequence": 9,
            "activation_id": 8,
            "expected_activation_version": 2,
            "expected_window_version": 2,
        },
        {
            "expected_sequence": 10,
            "activation_id": 8,
            "expected_activation_version": 3,
            "action": {
                "schema": "szop.action",
                "version": 1,
                "action_type": "defend",
                "payload": {"unit_id": 1},
            },
        },
        {
            "operation": "continue",
            "expected_sequence": 11,
            "expected_activation_version": 4,
        },
        {
            "operation": "finalize",
            "expected_sequence": 12,
            "expected_activation_version": 5,
            "recovery": {"uses": []},
        },
    ]


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        (
            "start_activation",
            {"battle_id": True, "expected_sequence": 0, "selected_unit_id": 1},
        ),
        (
            "start_activation",
            {"battle_id": 1, "expected_sequence": True, "selected_unit_id": 1},
        ),
        (
            "start_activation",
            {"battle_id": 1, "expected_sequence": 0, "selected_unit_id": True},
        ),
        (
            "interrupt",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": True,
                "expected_activation_version": 1,
                "expected_window_version": 1,
                "source_unit_id": 1,
                "ability_slug": "rozkaz",
                "payload": {},
            },
        ),
        (
            "interrupt",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
                "expected_window_version": False,
                "source_unit_id": 1,
                "ability_slug": "rozkaz",
                "payload": {},
            },
        ),
        (
            "interrupt",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
                "expected_window_version": 1,
                "source_unit_id": True,
                "ability_slug": "rozkaz",
                "payload": {},
            },
        ),
        (
            "interrupt",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
                "expected_window_version": 1,
                "source_unit_id": 1,
                "ability_slug": "",
                "payload": {},
            },
        ),
        (
            "interrupt",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
                "expected_window_version": 1,
                "source_unit_id": 1,
                "ability_slug": "rozkaz",
                "payload": {"bad": float("nan")},
            },
        ),
        (
            "pass_interrupt_priority",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": True,
                "expected_window_version": 1,
            },
        ),
        (
            "commit_activation_action",
            {
                "battle_id": 1,
                "action": object(),
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
            },
        ),
        (
            "continue_activation",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": False,
            },
        ),
        (
            "finalize_activation",
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "activation_id": 1,
                "expected_activation_version": 1,
                "recovery_uses": ({"source_unit_id": 1},),
            },
        ),
    ],
)
def test_activation_v2_methods_validate_strictly_before_io(
    method_name: str,
    arguments: dict[str, Any],
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport must not be called")

    method = getattr(HttpClient("http://localhost", transport=transport), method_name)
    with pytest.raises((TypeError, ValueError)):
        method(**arguments)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(extra=True),
        lambda payload: payload.pop("events"),
        lambda payload: payload.update(battle_id=99),
        lambda payload: payload.update(previous_sequence=True),
        lambda payload: payload.update(previous_sequence=6),
        lambda payload: payload.update(new_sequence=7),
        lambda payload: payload["state"].update(version=1),
        lambda payload: payload["state"].update(extra=True),
        lambda payload: payload["events"][0].update(extra=True),
        lambda payload: payload["events"][0].update(sequence=9),
    ],
)
def test_activation_v2_success_decoder_is_fail_closed(mutation) -> None:
    payload = _mutation_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _response(payload, status_code=201)

    with pytest.raises(HttpClientError, match="malformed payload"):
        HttpClient("http://localhost", transport=transport).start_activation(
            42,
            expected_sequence=7,
            selected_unit_id=1,
        )


def test_pass_status_must_match_whether_interrupt_window_remains_open() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _response(_mutation_payload(), status_code=202)

    with pytest.raises(HttpClientError, match="status inconsistent with state"):
        HttpClient("http://localhost", transport=transport).pass_interrupt_priority(
            42,
            expected_sequence=7,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=1,
        )


def test_activation_v2_error_preserves_closed_code_without_echoing_body() -> None:
    secret = "do-not-echo"

    def transport(_request: HttpRequest) -> HttpResponse:
        return _response(
            {"detail": {"code": "stale_window"}, "secret": secret},
            status_code=409,
        )

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).pass_interrupt_priority(
            42,
            expected_sequence=7,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=1,
        )

    assert not isinstance(exc_info.value, HttpClientActivationError)
    assert exc_info.value.status_code == 409
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"detail": {"code": "unknown_code"}},
        {"detail": {"code": True}},
        {"detail": {"code": "stale_window", "extra": 1}},
        {"detail": "stale_window"},
        {},
    ],
)
def test_activation_v2_unknown_or_malformed_error_envelope_fails_closed(
    payload: Any,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _response(payload, status_code=409)

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).pass_interrupt_priority(
            42,
            expected_sequence=7,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=1,
        )

    assert not isinstance(exc_info.value, HttpClientActivationError)
    assert exc_info.value.status_code == 409


def test_activation_v2_closed_error_exposes_status_and_detail_code() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _response({"detail": {"code": "stale_window"}}, status_code=409)

    with pytest.raises(HttpClientActivationError) as exc_info:
        HttpClient("http://localhost", transport=transport).pass_interrupt_priority(
            42,
            expected_sequence=7,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=1,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail_code == "stale_window"


def test_activation_v2_error_code_with_wrong_status_fails_closed() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return _response({"detail": {"code": "stale_window"}}, status_code=422)

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).pass_interrupt_priority(
            42,
            expected_sequence=7,
            activation_id=8,
            expected_activation_version=2,
            expected_window_version=1,
        )

    assert not isinstance(exc_info.value, HttpClientActivationError)
    assert exc_info.value.status_code == 422


def test_legacy_take_action_on_v2_has_typed_upgrade_direction() -> None:
    seen: list[HttpRequest] = []
    state_payload = battle_state_to_json(_v2_idle_state(), version=2)

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        if request.method == "GET":
            return _response(
                {
                    "battle_id": 42,
                    "sequence_at": 7,
                    **state_payload,
                }
            )
        return _response(
            {"detail": {"code": "activation_guard_required"}},
            status_code=422,
        )

    with pytest.raises(HttpClientActivationError) as exc_info:
        HttpClient("http://localhost", transport=transport).take_action(
            42,
            DefendAction(unit_id=1),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail_code == "activation_guard_required"
    assert "commit_activation_action" in str(exc_info.value)
    assert [request.method for request in seen] == ["GET", "POST"]
