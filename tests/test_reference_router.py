from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as main_app
from app.routers import reference
from app.services.rule_lookup import MAX_RULE_RESULTS


@pytest.fixture
def client() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(reference.router)
    return TestClient(test_app)


def test_main_app_registers_public_reference_routes() -> None:
    methods_by_path = {
        route.path: getattr(route, "methods", set())
        for route in main_app.routes
    }

    assert "GET" in methods_by_path["/rules/lookup"]
    assert "GET" in methods_by_path["/abilities/explain"]


def test_lookup_rule_returns_exact_canonical_point_with_context(
    client: TestClient,
) -> None:
    response = client.get("/rules/lookup", params={"query": "pkt 14.d.iv"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "szop.lookup_rule/v1"
    assert payload["version"] == 1
    assert payload["source"] == "SZOP_Rozjemca.md"
    assert payload["query"] == "pkt 14.d.iv"
    assert payload["normalized_query"] == "14.d.iv"
    assert payload["mode"] == "reference"
    assert len(payload["matches"]) == 1
    match = payload["matches"][0]
    assert match["ref"] == "14.d.iv"
    assert "kontratak" in match["text"]
    assert [parent["ref"] for parent in match["parents"]] == ["14", "14.d"]
    assert match["score"] is None


def test_lookup_rule_search_folds_polish_characters_and_honors_limit(
    client: TestClient,
) -> None:
    response = client.get(
        "/rules/lookup",
        params={"query": "oslona", "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "search"
    assert payload["normalized_query"] == "oslona"
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["ref"] == "19"
    assert payload["matches"][0]["score"] >= 1


def test_lookup_rule_returns_empty_matches_for_unknown_reference_and_search(
    client: TestClient,
) -> None:
    missing_ref = client.get("/rules/lookup", params={"query": "pkt 99.z"})
    missing_text = client.get(
        "/rules/lookup",
        params={"query": "zupelniebrakujaceslowo"},
    )

    assert missing_ref.status_code == 200
    assert missing_ref.json()["mode"] == "reference"
    assert missing_ref.json()["matches"] == []
    assert missing_text.status_code == 200
    assert missing_text.json()["mode"] == "search"
    assert missing_text.json()["matches"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"query": "   "},
        {"query": "x" * 201},
        {"query": "osłona", "limit": 0},
        {"query": "osłona", "limit": MAX_RULE_RESULTS + 1},
    ],
)
def test_lookup_rule_rejects_invalid_input(
    client: TestClient,
    params: dict[str, str | int],
) -> None:
    assert client.get("/rules/lookup", params=params).status_code == 422


def test_lookup_rule_ignores_arbitrary_file_parameter_and_never_leaks_path(
    client: TestClient,
    tmp_path: Path,
) -> None:
    attacker_file = tmp_path / "rules.md"
    attacker_file.write_text("14.\tFAŁSZYWA REGUŁA", encoding="utf-8")

    response = client.get(
        "/rules/lookup",
        params={
            "query": "14.d.iv",
            "rules_file": str(attacker_file),
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "kontratak" in body
    assert "FAŁSZYWA REGUŁA" not in body
    assert str(tmp_path) not in body
    assert len(json.dumps(response.json(), ensure_ascii=False)) < 20_000


def test_lookup_rule_redacts_canonical_source_read_error(
    client: TestClient,
) -> None:
    leaked_path = r"C:\private\deployment\SZOP_Rozjemca.md"
    with patch(
        "app.routers.reference.lookup_rule_payload",
        side_effect=OSError(leaked_path),
    ):
        response = client.get("/rules/lookup", params={"query": "14.d.iv"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Rules source unavailable"}
    assert leaked_path not in response.text


def test_explain_ability_resolves_slug_and_normalized_display_name(
    client: TestClient,
) -> None:
    slug_response = client.get("/abilities/explain", params={"query": "furia"})
    name_response = client.get(
        "/abilities/explain",
        params={"query": "Podwojny"},
    )

    assert slug_response.status_code == 200
    slug_payload = slug_response.json()
    assert slug_payload["schema"] == "szop.explain_ability/v1"
    assert slug_payload["version"] == 1
    assert slug_payload["source"] == "app.data.abilities"
    assert slug_payload["ability"]["slug"] == "furia"
    assert "szarży" in slug_payload["ability"]["description"]

    assert name_response.status_code == 200
    name_payload = name_response.json()
    assert name_payload["ability"]["slug"] == "rozrywajacy"
    assert name_payload["ability"]["display_name"] == "Podwójny"


def test_explain_ability_rejects_invalid_or_unknown_query(
    client: TestClient,
) -> None:
    assert client.get("/abilities/explain", params={"query": "   "}).status_code == 422
    assert (
        client.get("/abilities/explain", params={"query": "x" * 101}).status_code
        == 422
    )
    response = client.get(
        "/abilities/explain",
        params={"query": "nieistniejaca_zdolnosc"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Ability not found"}


def test_openapi_exposes_only_controlled_reference_parameters(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    rule_parameters = {
        parameter["name"]
        for parameter in paths["/rules/lookup"]["get"]["parameters"]
    }
    ability_parameters = {
        parameter["name"]
        for parameter in paths["/abilities/explain"]["get"]["parameters"]
    }

    assert rule_parameters == {"query", "limit"}
    assert ability_parameters == {"query"}
