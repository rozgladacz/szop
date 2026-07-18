from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.main import app as main_app
from app.routers import reference
from app.security import hash_agent_token
from mcp_server.embeddings import EmbeddingError
from mcp_server.search import SearchError
from mcp_server.vector_store import StaleIndexError, VectorStoreError


RAW_TOKEN = "rules-search-secret"
PRIVATE_QUERY = "  Jak działa osłona semantycznie?  "
PRIVATE_RESULT_TEXT = "Treść wyniku nie może trafić do audytu."


def _hybrid_result() -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "chunk_id": "szop-rozjemca-0019",
            "source": "SZOP_Rozjemca.md",
            "headings": ["19. Osłona"],
            "refs": ["19"],
            "text": PRIVATE_RESULT_TEXT,
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
    ]


@pytest.fixture
def api() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(reference.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as client:
        yield client, sessions


def _seed_token(
    sessions: sessionmaker[Session],
    *,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
    expires_in: timedelta = timedelta(days=1),
    revoked: bool = False,
) -> None:
    with sessions() as session:
        owner = models.User(username=f"owner-{raw_token}", password_hash="x")
        agent = models.User(
            username=f"agent-{raw_token}",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        token = models.AgentToken(
            agent_user=agent,
            owner_user=owner,
            token_hash=hash_agent_token(raw_token),
            scope_json=json.dumps(
                scopes if scopes is not None else {reference.RULES_SEARCH_SCOPE: True}
            ),
            expires_at=now + expires_in,
            revoked_at=now if revoked else None,
        )
        session.add_all([owner, agent, token])
        session.commit()


def _authorization(raw_token: str = RAW_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def test_main_app_registers_scoped_post_rules_search() -> None:
    methods_by_path = {
        route.path: getattr(route, "methods", set())
        for route in main_app.routes
    }

    assert "POST" in methods_by_path["/rules/search"]
    assert "GET" not in methods_by_path["/rules/search"]


def test_rules_search_trims_body_delegates_once_and_audits_without_body(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sessions = api
    _seed_token(sessions)
    calls: list[tuple[str, int]] = []

    def fake_hybrid_search(query: str, limit: int):
        calls.append((query, limit))
        return _hybrid_result()

    monkeypatch.setattr(reference, "hybrid_search", fake_hybrid_search)
    response = client.post(
        "/rules/search",
        headers=_authorization(),
        json={"query": PRIVATE_QUERY, "limit": 3},
    )

    assert response.status_code == 200
    assert calls == [(PRIVATE_QUERY.strip(), 3)]
    assert response.json() == {
        "schema": "szop.search_rules/v1",
        "version": 1,
        "query": PRIVATE_QUERY.strip(),
        "strategy": "hybrid_weighted_rrf",
        "count": 1,
        "results": _hybrid_result(),
    }
    json.dumps(response.json(), ensure_ascii=False, allow_nan=False)

    with sessions() as session:
        audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    params = json.loads(audit.params_json)
    assert audit.route == "/rules/search"
    assert params == {
        "method": "POST",
        "path_params": {},
        "query_params": {},
        "scope": reference.RULES_SEARCH_SCOPE,
        "status": "authorized",
    }
    assert PRIVATE_QUERY.strip() not in audit.params_json
    assert PRIVATE_RESULT_TEXT not in audit.params_json
    assert RAW_TOKEN not in audit.params_json


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": "   "},
        {"query": "x" * 201},
        {"query": "osłona", "limit": True},
        {"query": "osłona", "limit": 0},
        {"query": "osłona", "limit": 11},
        {"query": "osłona", "extra": "forbidden"},
    ],
)
def test_rules_search_rejects_invalid_body_before_hybrid(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    client, sessions = api
    _seed_token(sessions)

    def fail_hybrid_search(_query: str, _limit: int):
        raise AssertionError("hybrid_search must not be called")

    monkeypatch.setattr(reference, "hybrid_search", fail_hybrid_search)
    response = client.post(
        "/rules/search",
        headers=_authorization(),
        json=body,
    )

    assert response.status_code == 422
    query = body.get("query")
    if isinstance(query, str) and query:
        assert query not in response.text


def test_rules_search_openapi_exposes_only_the_body_schema(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api

    operation = client.get("/openapi.json").json()["paths"]["/rules/search"][
        "post"
    ]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert operation.get("parameters", []) == []
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "limit"}


def test_rules_search_malformed_json_does_not_echo_body(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sessions = api
    _seed_token(sessions)
    private_query = "sekretna treść malformed JSON"
    monkeypatch.setattr(
        reference,
        "hybrid_search",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("hybrid_search must not be called")
        ),
    )

    response = client.post(
        "/rules/search",
        headers={**_authorization(), "Content-Type": "application/json"},
        content=f'{{"query":"{private_query}"',
    )

    assert response.status_code == 422
    assert private_query not in response.text


@pytest.mark.parametrize(
    "error",
    [
        ImportError(r"missing module at C:\\private\\site-packages"),
        EmbeddingError(r"offline model missing at C:\\private\\models"),
        StaleIndexError(r"stale C:\\private\\rag_vectors.sqlite"),
        VectorStoreError(r"cannot open C:\\private\\rag_vectors.sqlite"),
        SearchError(f"bad generated score for {PRIVATE_QUERY.strip()}"),
        OSError(r"cannot read C:\\private\\SZOP_Rozjemca.md"),
        sqlite3.OperationalError(r"database C:\\private\\index is locked"),
    ],
)
def test_rules_search_maps_controlled_readiness_errors_to_redacted_503(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    client, sessions = api
    _seed_token(sessions)
    monkeypatch.setattr(reference, "hybrid_search", lambda *_args: (_ for _ in ()).throw(error))

    response = client.post(
        "/rules/search",
        headers=_authorization(),
        json={"query": PRIVATE_QUERY, "limit": 5},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Rules search unavailable"}
    assert PRIVATE_QUERY.strip() not in response.text
    assert "C:\\private" not in response.text


def test_rules_search_rejects_nonfinite_service_payload_as_503(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sessions = api
    _seed_token(sessions)
    results = _hybrid_result()
    results[0]["score"] = float("nan")
    monkeypatch.setattr(reference, "hybrid_search", lambda *_args: results)

    response = client.post(
        "/rules/search",
        headers=_authorization(),
        json={"query": "osłona"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Rules search unavailable"}


@pytest.mark.parametrize(
    ("authorization", "seed_kwargs", "expected_status"),
    [
        (None, None, 401),
        ("Bearer invalid", None, 401),
        (
            "Bearer expired",
            {"raw_token": "expired", "expires_in": timedelta(seconds=-1)},
            401,
        ),
        (
            "Bearer revoked",
            {"raw_token": "revoked", "revoked": True},
            401,
        ),
        (
            "Bearer wrong-scope",
            {"raw_token": "wrong-scope", "scopes": {"battle:read": True}},
            403,
        ),
    ],
)
def test_rules_search_uses_agent_scope_without_session_fallback(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
    seed_kwargs: dict[str, object] | None,
    expected_status: int,
) -> None:
    client, sessions = api
    if seed_kwargs is not None:
        _seed_token(sessions, **seed_kwargs)
    monkeypatch.setattr(
        reference,
        "hybrid_search",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("hybrid_search must not be called")
        ),
    )
    headers = {"Authorization": authorization} if authorization else {}

    response = client.post(
        "/rules/search",
        headers=headers,
        json={"query": "osłona"},
    )

    assert response.status_code == expected_status
    with sessions() as session:
        assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_base_app_and_mcp_imports_do_not_load_heavy_rag_modules() -> None:
    code = (
        "import sys; import app.main; import mcp_server.server; "
        "forbidden = {'torch', 'transformers', 'sentence_transformers', 'sqlite_vec'}; "
        "loaded = sorted(forbidden.intersection(sys.modules)); "
        "print(','.join(loaded)); raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
