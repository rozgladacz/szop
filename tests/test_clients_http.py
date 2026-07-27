from __future__ import annotations

import json
from typing import Any, get_args
from unittest.mock import patch

import pytest

from app.services.engine.action_codec import action_from_json, action_to_json
from app.services.engine.actions import DefendAction
from app.services.engine.events import (
    ActivePlayerChanged,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    BattleEvent,
    EffectApplied,
    InitiativePassed,
    InitiativeTransferred,
    InterruptPriorityPassed,
    InterruptTriggered,
    InterruptWindowClosed,
    InterruptWindowOpened,
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
    HttpClientTransportError,
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


def _rule_lookup_payload() -> dict:
    return {
        "schema": "szop.lookup_rule/v1",
        "version": 1,
        "source": "SZOP_Rozjemca.md",
        "query": "osłona",
        "normalized_query": "oslona",
        "mode": "search",
        "matches": [
            {
                "ref": "19",
                "text": "Osłona zmienia test trafienia.",
                "parents": [],
                "children": [],
                "score": 1,
            }
        ],
    }


def _ability_explanation_payload() -> dict:
    return {
        "schema": "szop.explain_ability/v1",
        "version": 1,
        "source": "app.data.abilities",
        "query": "Podwojny",
        "ability": {
            "slug": "rozrywajacy",
            "name": "Podwójny",
            "display_name": "Podwójny",
            "type": "weapon",
            "description": "Naturalne 6 dają dodatkowe trafienie.",
            "value_label": None,
            "value_type": None,
            "requires_value": False,
            "value_choices": [],
            "blocked": False,
        },
    }


def _rules_search_payload() -> dict:
    return {
        "schema": "szop.search_rules/v1",
        "version": 1,
        "query": "Jak działa osłona?",
        "strategy": "hybrid_weighted_rrf",
        "count": 1,
        "results": [
            {
                "rank": 1,
                "chunk_id": "szop-rozjemca-0019",
                "source": "SZOP_Rozjemca.md",
                "headings": ["19. Osłona"],
                "refs": ["19"],
                "text": "Osłona zmienia test trafienia.",
                "score": 0.048915917504,
                "components": {
                    "bm25": {
                        "rank": 1,
                        "weight": 2.0,
                        "contribution": 0.032786885246,
                    },
                    "dense": {
                        "rank": 2,
                        "weight": 1.0,
                        "contribution": 0.016129032258,
                    },
                },
            }
        ],
    }


def _loadout_validation_payload() -> dict:
    return {
        "schema": "szop.validate_loadout/v1",
        "version": 1,
        "unit_id": 7,
        "unit_name": "Strzelcy",
        "count": 3,
        "mode": {"raw": "bad", "normalized": "per_model", "clamped": True},
        "sections": [
            {
                "section": "weapons",
                "accepted": {"3": 0},
                "rejected": [
                    {"id": "999", "reason": "niedozwolone dla tej jednostki"}
                ],
                "clamped": [{"id": "3", "raw": -2, "normalized": 0}],
            },
            {"section": "active", "accepted": {}, "rejected": [], "clamped": []},
            {"section": "aura", "accepted": {}, "rejected": [], "clamped": []},
        ],
        "passive": {"accepted": {}, "rejected": ["unknown-passive"]},
        "cost": {
            "selected_role": "strzelec",
            "selected_total": 12.5,
            "components": {
                "active": 0.0,
                "aura": 0.0,
                "base": 10.0,
                "passive": 0.0,
                "weapon": 2.5,
            },
        },
        "has_issues": True,
    }


def _score_list_payload() -> dict:
    roster = lambda roster_id, name, points: {
        "id": roster_id,
        "name": name,
        "army": "Army",
        "points": float(points),
        "composition": "1× Unit",
    }
    return {
        "schema": "szop.score_list/v1",
        "version": 1,
        "target": roster(7, "Target", 100.0),
        "parameters": {
            "games_per_opponent": 3,
            "bot": "priority",
            "seed": 4,
            "map_name": "lustrzana_a",
            "opponent_roster_ids": [8, 9],
        },
        "results": [
            {
                "opponent": roster(8, "Cheaper", 50.0),
                "n": 3,
                "wins": 2,
                "losses": 1,
                "draws": 0,
                "rounds": 12,
                "win_rate": 2 / 3,
                "loss_rate": 1 / 3,
                "draw_rate": 0.0,
                "avg_rounds": 4.0,
            },
            {
                "opponent": roster(9, "Pricier", 150.0),
                "n": 3,
                "wins": 1,
                "losses": 1,
                "draws": 1,
                "rounds": 9,
                "win_rate": 1 / 3,
                "loss_rate": 1 / 3,
                "draw_rate": 1 / 3,
                "avg_rounds": 3.0,
            },
        ],
        "aggregate": {
            "n_opponents": 2,
            "n_games": 6,
            "wins": 3,
            "losses": 2,
            "draws": 1,
            "rounds": 21,
            "win_rate": 0.5,
            "loss_rate": 2 / 6,
            "draw_rate": 1 / 6,
            "avg_rounds": 3.5,
        },
        "cost_signals": {
            "vs_cheaper": {
                "n_opponents": 1,
                "n_games": 3,
                "wins": 2,
                "losses": 1,
                "draws": 0,
                "rounds": 12,
                "win_rate": 2 / 3,
                "loss_rate": 1 / 3,
                "draw_rate": 0.0,
                "avg_rounds": 4.0,
            },
            "vs_pricier": {
                "n_opponents": 1,
                "n_games": 3,
                "wins": 1,
                "losses": 1,
                "draws": 1,
                "rounds": 9,
                "win_rate": 1 / 3,
                "loss_rate": 1 / 3,
                "draw_rate": 1 / 3,
                "avg_rounds": 3.0,
            },
        },
    }


def _exploit_candidates_payload() -> dict:
    def candidate(
        rank,
        roster_id,
        name,
        points,
        wins,
        losses,
        draws,
        rounds,
    ):
        games = wins + losses + draws
        win_rate = wins / games
        return {
            "rank": rank,
            "roster_id": roster_id,
            "name": name,
            "army": "Army",
            "points": float(points),
            "composition": "1× Unit",
            "games": games,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "rounds": rounds,
            "win_rate": win_rate,
            "loss_rate": losses / games,
            "draw_rate": draws / games,
            "avg_rounds": rounds / games,
            "exploit_score": win_rate / points * 100.0 if points else 0.0,
        }

    return {
        "schema": "szop.find_exploit_candidates/v1",
        "version": 1,
        "army": {"id": 4, "name": "Army", "roster_count": 3},
        "parameters": {
            "games_per_pair": 2,
            "bot": "priority",
            "seed": 4,
            "map_name": "lustrzana_a",
            "roster_ids": [7, 8, 9],
        },
        "candidates": [
            candidate(1, 7, "Alpha", 100.0, 2, 1, 1, 15),
            candidate(2, 8, "Beta", 50.0, 1, 3, 0, 14),
            candidate(3, 9, "Gamma", 200.0, 2, 1, 1, 13),
        ],
        "pairs": [
            {
                "roster_a_id": 7,
                "roster_b_id": 8,
                "wins_a": 2,
                "wins_b": 0,
                "draws": 0,
                "games": 2,
                "rounds": 8,
                "win_rate_a": 1.0,
                "win_rate_b": 0.0,
                "avg_rounds": 4.0,
            },
            {
                "roster_a_id": 7,
                "roster_b_id": 9,
                "wins_a": 0,
                "wins_b": 1,
                "draws": 1,
                "games": 2,
                "rounds": 7,
                "win_rate_a": 0.0,
                "win_rate_b": 0.5,
                "avg_rounds": 3.5,
            },
            {
                "roster_a_id": 8,
                "roster_b_id": 9,
                "wins_a": 1,
                "wins_b": 1,
                "draws": 0,
                "games": 2,
                "rounds": 6,
                "win_rate_a": 0.5,
                "win_rate_b": 0.5,
                "avg_rounds": 3.0,
            },
        ],
    }


def test_score_list_posts_once_with_bearer_local_timeout_and_strict_contract() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_score_list_payload())

    payload = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        timeout=2.0,
        transport=transport,
    ).score_list(
        7,
        games_per_opponent=3,
        bot="PRIORITY",
        seed=4,
        map_name="LUSTRZANA_A",
        opponent_roster_ids=[9, 8],
    )

    assert payload == _score_list_payload()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/rosters/7/score"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert request.timeout == 120.0
    assert json.loads(request.body.decode("utf-8")) == {
        "games_per_opponent": 3,
        "bot": "priority",
        "seed": 4,
        "map_name": "lustrzana_a",
        "opponent_roster_ids": [8, 9],
    }


def test_score_list_does_not_reduce_larger_client_timeout() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_score_list_payload())

    HttpClient("http://localhost", timeout=180.0, transport=transport).score_list(
        7,
        games_per_opponent=3,
        seed=4,
        opponent_roster_ids=[8, 9],
    )
    assert seen[0].timeout == 180.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"roster_id": True},
        {"roster_id": 0},
        {"roster_id": 7, "games_per_opponent": True},
        {"roster_id": 7, "games_per_opponent": 11},
        {"roster_id": 7, "bot": "minimax"},
        {"roster_id": 7, "seed": True},
        {"roster_id": 7, "seed": 2**31},
        {"roster_id": 7, "map_name": "bad"},
        {"roster_id": 7, "opponent_roster_ids": (8,)},
        {"roster_id": 7, "opponent_roster_ids": [8, 8]},
        {"roster_id": 7, "opponent_roster_ids": [7]},
        {
            "roster_id": 7,
            "games_per_opponent": 10,
            "opponent_roster_ids": [8, 9, 10, 11, 12, 13],
        },
    ],
)
def test_score_list_rejects_invalid_arguments_before_transport(kwargs) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).score_list(**kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version=True),
        lambda payload: payload["target"].update(id=70),
        lambda payload: payload["target"].update(points=float("nan")),
        lambda payload: payload["parameters"]["opponent_roster_ids"].reverse(),
        lambda payload: payload["results"].reverse(),
        lambda payload: payload["results"][0].update(wins=3),
        lambda payload: payload["results"][0].update(win_rate=float("nan")),
        lambda payload: payload["results"][0].update(win_rate=1.0000000000005),
        lambda payload: payload["aggregate"].update(n_games=5),
        lambda payload: payload["aggregate"].update(win_rate=0.9),
        lambda payload: payload["aggregate"].update(loss_rate=-0.0000000000001),
        lambda payload: payload["cost_signals"]["vs_cheaper"].update(wins=1),
        lambda payload: payload.update(extra="forbidden"),
    ],
)
def test_score_list_rejects_malformed_or_inconsistent_response(mutation) -> None:
    payload = _score_list_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="POST roster score returned malformed payload",
    ):
        HttpClient("http://localhost", transport=transport).score_list(
            7,
            games_per_opponent=3,
            seed=4,
            opponent_roster_ids=[8, 9],
        )


def test_find_exploit_candidates_posts_once_with_bearer_timeout_and_strict_contract() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_exploit_candidates_payload())

    payload = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        timeout=2.0,
        transport=transport,
    ).find_exploit_candidates(
        4,
        games_per_pair=2,
        bot="PRIORITY",
        seed=4,
        map_name="LUSTRZANA_A",
        roster_ids=[9, 7, 8],
    )

    assert payload == _exploit_candidates_payload()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/armies/4/exploit-candidates"
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert request.timeout == 120.0
    assert json.loads(request.body.decode("utf-8")) == {
        "games_per_pair": 2,
        "bot": "priority",
        "seed": 4,
        "map_name": "lustrzana_a",
        "roster_ids": [7, 8, 9],
    }


def test_find_exploit_candidates_does_not_reduce_larger_client_timeout() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_exploit_candidates_payload())

    HttpClient(
        "http://localhost",
        timeout=180.0,
        transport=transport,
    ).find_exploit_candidates(
        4,
        games_per_pair=2,
        seed=4,
        roster_ids=[7, 8, 9],
    )
    assert seen[0].timeout == 180.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"army_id": True},
        {"army_id": 0},
        {"army_id": 2**63},
        {"army_id": 4, "games_per_pair": True},
        {"army_id": 4, "games_per_pair": 4},
        {"army_id": 4, "bot": "minimax"},
        {"army_id": 4, "seed": True},
        {"army_id": 4, "seed": 2**31},
        {"army_id": 4, "map_name": "bad"},
        {"army_id": 4, "roster_ids": (7, 8)},
        {"army_id": 4, "roster_ids": []},
        {"army_id": 4, "roster_ids": [7]},
        {"army_id": 4, "roster_ids": [7, 7]},
        {"army_id": 4, "roster_ids": [True, 8]},
        {
            "army_id": 4,
            "games_per_pair": 3,
            "roster_ids": [7, 8, 9, 10, 11, 12, 13],
        },
    ],
)
def test_find_exploit_candidates_rejects_invalid_arguments_before_transport(
    kwargs,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    with pytest.raises(ValueError):
        HttpClient("http://localhost", transport=transport).find_exploit_candidates(
            **kwargs
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version=True),
        lambda payload: payload["army"].update(id=40),
        lambda payload: payload["army"].update(roster_count=2),
        lambda payload: payload["parameters"]["roster_ids"].reverse(),
        lambda payload: payload["candidates"].reverse(),
        lambda payload: payload["candidates"][0].update(wins=3),
        lambda payload: payload["candidates"][0].update(win_rate=float("nan")),
        lambda payload: payload["candidates"][0].update(exploit_score=0.9),
        lambda payload: (
            payload["candidates"][1].update(exploit_score=0.5000000000005),
            payload["candidates"].__setitem__(
                slice(0, 2),
                [payload["candidates"][1], payload["candidates"][0]],
            ),
            [item.update(rank=rank) for rank, item in enumerate(payload["candidates"], 1)],
        ),
        lambda payload: payload["pairs"].reverse(),
        lambda payload: payload["pairs"][0].update(wins_a=1),
        lambda payload: payload["pairs"][0].update(avg_rounds=float("nan")),
        lambda payload: payload.update(extra="forbidden"),
    ],
)
def test_find_exploit_candidates_rejects_malformed_or_inconsistent_response(
    mutation,
) -> None:
    payload = _exploit_candidates_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="POST exploit candidate search returned malformed payload",
    ):
        HttpClient(
            "http://localhost",
            transport=transport,
        ).find_exploit_candidates(
            4,
            games_per_pair=2,
            seed=4,
            roster_ids=[7, 8, 9],
        )


def test_lookup_rule_gets_encoded_query_and_returns_validated_contract() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_rule_lookup_payload())

    payload = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        transport=transport,
    ).lookup_rule("  osłona  ", limit=1)

    assert payload == _rule_lookup_payload()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert (
        request.url
        == "https://szop.example/api/rules/lookup?query=os%C5%82ona&limit=1"
    )
    assert request.headers["Authorization"] == "Bearer raw-token"
    assert request.body is None


def test_explain_ability_gets_encoded_name_and_returns_validated_contract() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_ability_explanation_payload())

    payload = HttpClient(
        "https://szop.example/api",
        transport=transport,
    ).explain_ability("Podwojny")

    assert payload == _ability_explanation_payload()
    assert seen[0].method == "GET"
    assert (
        seen[0].url
        == "https://szop.example/api/abilities/explain?query=Podwojny"
    )


def test_search_rules_posts_body_with_bearer_and_rag_safe_timeout() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_rules_search_payload())

    payload = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        timeout=2.0,
        transport=transport,
    ).search_rules("  Jak działa osłona?  ", limit=1)

    assert payload == _rules_search_payload()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/rules/search"
    assert request.headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer raw-token",
    }
    assert json.loads(request.body.decode("utf-8")) == {
        "query": "Jak działa osłona?",
        "limit": 1,
    }
    assert request.timeout == 30.0


def test_search_rules_does_not_reduce_larger_client_timeout() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_rules_search_payload())

    HttpClient(
        "http://localhost",
        timeout=45.0,
        transport=transport,
    ).search_rules("Jak działa osłona?", limit=1)

    assert seen[0].timeout == 45.0


def test_search_rules_timeout_does_not_change_other_client_methods() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_rule_lookup_payload())

    client = HttpClient(
        "http://localhost",
        timeout=2.0,
        transport=transport,
    )

    client.lookup_rule("osłona", limit=1)

    assert seen[0].timeout == 2.0


def test_validate_loadout_posts_body_with_bearer_and_global_timeout() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(_loadout_validation_payload())

    loadout = {"mode": "bad", "weapons": {"3": -2, "999": 1}}
    payload = HttpClient(
        "https://szop.example/api/",
        token="raw-token",
        timeout=2.0,
        transport=transport,
    ).validate_loadout(7, loadout, count=3)

    assert payload == _loadout_validation_payload()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/units/7/validate-loadout"
    assert request.headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer raw-token",
    }
    assert json.loads(request.body.decode("utf-8")) == {
        "loadout": loadout,
        "count": 3,
    }
    assert request.timeout == 2.0


@pytest.mark.parametrize(
    ("unit_id", "loadout", "count"),
    [
        (0, {}, 1),
        (True, {}, 1),
        (1, [], 1),
        (1, {1: "bad-key"}, 1),
        (1, {"value": float("nan")}, 1),
        (1, {"value": object()}, 1),
        (1, {}, True),
        (1, {}, 0),
        (1, {}, 101),
    ],
)
def test_validate_loadout_rejects_invalid_arguments_before_transport(
    unit_id,
    loadout,
    count,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    client = HttpClient("http://localhost", transport=transport)
    with pytest.raises(ValueError):
        client.validate_loadout(unit_id, loadout, count=count)


def test_validate_loadout_rejects_cyclic_json_before_transport() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="finite JSON object"):
        HttpClient("http://localhost", transport=transport).validate_loadout(
            1,
            cyclic,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version=True),
        lambda payload: payload.update(unit_id=8),
        lambda payload: payload.update(count=2),
        lambda payload: payload.update(extra="forbidden"),
        lambda payload: payload["mode"].update(normalized="invalid"),
        lambda payload: payload["mode"].update(raw=float("nan")),
        lambda payload: payload["sections"].reverse(),
        lambda payload: payload["sections"][0]["accepted"].update({"3": True}),
        lambda payload: payload["sections"][0]["rejected"][0].update(
            reason="private reason"
        ),
        lambda payload: payload["cost"].update(selected_total=float("nan")),
        lambda payload: payload["cost"]["components"].update(base="10"),
        lambda payload: payload.update(has_issues=False),
    ],
)
def test_validate_loadout_rejects_malformed_response(mutation) -> None:
    payload = _loadout_validation_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="POST loadout validation returned malformed payload",
    ):
        HttpClient("http://localhost", transport=transport).validate_loadout(
            7,
            {},
            count=3,
        )


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs"),
    [
        ("lookup_rule", ("",), {}),
        ("lookup_rule", ("   ",), {}),
        ("lookup_rule", ("x" * 201,), {}),
        ("lookup_rule", ("osłona",), {"limit": True}),
        ("lookup_rule", ("osłona",), {"limit": 0}),
        ("lookup_rule", ("osłona",), {"limit": 11}),
        ("explain_ability", ("",), {}),
        ("explain_ability", ("x" * 101,), {}),
        ("search_rules", ("",), {}),
        ("search_rules", ("   ",), {}),
        ("search_rules", ("x" * 201,), {}),
        ("search_rules", ("osłona",), {"limit": True}),
        ("search_rules", ("osłona",), {"limit": 0}),
        ("search_rules", ("osłona",), {"limit": 11}),
    ],
)
def test_reference_methods_reject_invalid_input_before_transport(
    method_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("transport should not be called")

    client = HttpClient("http://localhost", transport=transport)
    with pytest.raises(ValueError):
        getattr(client, method_name)(*args, **kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version=True),
        lambda payload: payload.update(source=r"C:\secret\rules.md"),
        lambda payload: payload.update(query="different"),
        lambda payload: payload.update(mode="semantic"),
        lambda payload: payload.update(matches="bad"),
        lambda payload: payload["matches"][0].update(score=None),
        lambda payload: payload["matches"][0].update(text="x" * 4001),
        lambda payload: payload["matches"][0].update(parents=[{}]),
    ],
)
def test_lookup_rule_rejects_malformed_payload(mutation) -> None:
    payload = _rule_lookup_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="GET rule lookup returned malformed payload",
    ):
        HttpClient("http://localhost", transport=transport).lookup_rule(
            "osłona",
            limit=1,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version="1"),
        lambda payload: payload.update(source="/tmp/abilities.py"),
        lambda payload: payload.update(query="different"),
        lambda payload: payload.update(ability=[]),
        lambda payload: payload["ability"].update(slug=""),
        lambda payload: payload["ability"].update(requires_value=1),
        lambda payload: payload["ability"].update(value_choices=[1]),
        lambda payload: payload["ability"].pop("description"),
    ],
)
def test_explain_ability_rejects_malformed_payload(mutation) -> None:
    payload = _ability_explanation_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="GET ability explanation returned malformed payload",
    ):
        HttpClient("http://localhost", transport=transport).explain_ability(
            "Podwojny"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema="wrong"),
        lambda payload: payload.update(version=True),
        lambda payload: payload.update(query="different"),
        lambda payload: payload.update(strategy="dense"),
        lambda payload: payload.update(count=2),
        lambda payload: payload.update(results="bad"),
        lambda payload: payload.update(extra="forbidden"),
        lambda payload: payload["results"][0].update(rank=True),
        lambda payload: payload["results"][0].update(source=r"C:\secret\rules.md"),
        lambda payload: payload["results"][0].update(text="x" * 1201),
        lambda payload: payload["results"][0].update(score=float("nan")),
        lambda payload: payload["results"][0].update(extra="forbidden"),
        lambda payload: payload["results"][0]["components"]["bm25"].update(
            weight=1.0
        ),
        lambda payload: payload["results"][0]["components"]["dense"].update(
            contribution=float("inf")
        ),
    ],
)
def test_search_rules_rejects_malformed_payload(mutation) -> None:
    payload = _rules_search_payload()
    mutation(payload)

    def transport(_request: HttpRequest) -> HttpResponse:
        return _json_response(payload)

    with pytest.raises(
        HttpClientError,
        match="POST rules search returned malformed payload",
    ):
        HttpClient("http://localhost", transport=transport).search_rules(
            "Jak działa osłona?",
            limit=1,
        )


def test_search_rules_preserves_http_error_status_without_response_detail() -> None:
    private_query = "sekretna treść pytania"

    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(
            status_code=503,
            body=(
                '{"detail":"C:\\\\private\\\\models: '
                + private_query
                + '"}'
            ).encode("utf-8"),
        )

    with pytest.raises(HttpClientError) as exc_info:
        HttpClient("http://localhost", transport=transport).search_rules(
            private_query
        )

    assert exc_info.value.status_code == 503
    assert private_query not in str(exc_info.value)
    assert "C:\\private" not in str(exc_info.value)


@pytest.mark.parametrize("method_name", ["lookup_rule", "explain_ability"])
def test_reference_methods_reject_invalid_json(method_name: str) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=200, body=b"{not-json")

    client = HttpClient("http://localhost", transport=transport)
    with pytest.raises(HttpClientError, match="not valid JSON"):
        getattr(client, method_name)("osłona")


@pytest.mark.parametrize("method_name", ["lookup_rule", "explain_ability"])
def test_reference_methods_preserve_transport_error(method_name: str) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise HttpClientTransportError("HTTP transport failed: offline")

    client = HttpClient("http://localhost", transport=transport)
    with pytest.raises(HttpClientTransportError, match="offline"):
        getattr(client, method_name)("osłona")


@pytest.mark.parametrize("method_name", ["lookup_rule", "explain_ability"])
def test_reference_methods_preserve_http_error_status(method_name: str) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=404, body=b'{"detail":"missing"}')

    client = HttpClient("http://localhost", transport=transport)
    with pytest.raises(HttpClientError) as exc_info:
        getattr(client, method_name)("osłona")

    assert exc_info.value.status_code == 404


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
        ActivationStarted(17, 17, 1, 1, 0, 0),
        InterruptWindowOpened(18, 17, 1, 1, 1, 0),
        ActivationInterruptTriggered(19, 17, 2, 1, 2, 0),
        InterruptPriorityPassed(20, 17, 3, 1, 3, 0, 1),
        InterruptWindowClosed(21, 17, 4, 1, 4),
        ActivationActionCommitted(22, 17, 5, "defend"),
        ActivationContinuationChosen(23, 17, 6, False),
        ActivationFinalized(24, 17),
        InitiativeTransferred(25, 17, 0, 1),
        ActivePlayerChanged(26, 17, 0, 1),
    )

    assert {type(event) for event in events} == set(get_args(BattleEvent))
    projected, last_sequence = battle_events_to_wire(events, since=0)

    assert [item["sequence"] for item in projected] == list(range(1, 27))
    assert [item["type"] for item in projected] == [
        type(event).__name__ for event in events
    ]
    assert last_sequence == 26
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
