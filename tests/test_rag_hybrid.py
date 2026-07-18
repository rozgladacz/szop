"""Deterministic fusion and shared evaluation tests for the C2.4 hybrid slice."""

from __future__ import annotations

import inspect
import json
import math
import subprocess
import sys
from types import SimpleNamespace

import pytest

from mcp_server import evaluation, indexer, search as rag_search, vector_store
from mcp_server.server import TOOL_NAMES


def _ranked(*chunk_ids: str) -> list[dict[str, object]]:
    return [
        {"rank": rank, "chunk_id": chunk_id}
        for rank, chunk_id in enumerate(chunk_ids, start=1)
    ]


def test_hybrid_fuses_deduplicated_candidates_and_keeps_single_branch_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = indexer.build_corpus()
    first, second, third = (chunk.chunk_id for chunk in chunks[:3])
    monkeypatch.setattr(
        rag_search,
        "search",
        lambda query, limit: _ranked(second, first, second),
    )
    monkeypatch.setattr(
        vector_store,
        "dense_search",
        lambda query, limit: _ranked(third, second),
    )

    results = rag_search.hybrid_search("pytanie", 3)

    assert [result["chunk_id"] for result in results] == [second, first, third]
    assert [result["rank"] for result in results] == [1, 2, 3]
    assert results[0]["components"]["bm25"]["rank"] == 1
    assert results[0]["components"]["dense"]["rank"] == 2
    assert results[1]["components"]["bm25"]["rank"] == 2
    assert results[1]["components"]["dense"] is None
    assert results[2]["components"]["bm25"] is None
    assert results[2]["components"]["dense"]["rank"] == 1

    expected = round(
        rag_search.BM25_RRF_WEIGHT / (rag_search.RRF_K + 1)
        + rag_search.DENSE_RRF_WEIGHT / (rag_search.RRF_K + 2),
        12,
    )
    assert results[0]["score"] == expected
    assert results[0]["source"] == chunks[1].source
    assert results[0]["refs"] == list(chunks[1].refs)


def test_hybrid_rrf_ties_follow_corpus_order() -> None:
    first, second = (chunk.chunk_id for chunk in indexer.build_corpus()[:2])
    results = rag_search._fuse_ranked_results(
        _ranked(second),
        _ranked(first),
        limit=2,
        chunks=indexer.build_corpus(),
        bm25_weight=1.0,
        dense_weight=1.0,
    )

    assert [result["chunk_id"] for result in results] == [first, second]
    assert results[0]["score"] == results[1]["score"]


def test_hybrid_constants_and_contract_are_json_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_id = indexer.build_corpus()[0].chunk_id
    monkeypatch.setattr(rag_search, "search", lambda query, limit: _ranked(chunk_id))
    monkeypatch.setattr(
        vector_store,
        "dense_search",
        lambda query, limit: _ranked(chunk_id),
    )

    results = rag_search.hybrid_search("osłona", 1)

    assert rag_search.HYBRID_CANDIDATE_LIMIT == 5
    assert rag_search.RRF_K == 60
    assert rag_search.BM25_RRF_WEIGHT == 2.0
    assert rag_search.DENSE_RRF_WEIGHT == 1.0
    assert math.isfinite(results[0]["score"])
    assert all(
        component is None or math.isfinite(component["contribution"])
        for component in results[0]["components"].values()
    )
    json.dumps(results, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("query", ["", "   ", "...!!!", "a" * 201])
def test_hybrid_reuses_bm25_query_validation(query: str) -> None:
    with pytest.raises(rag_search.SearchError):
        rag_search.hybrid_search(query, 5)


@pytest.mark.parametrize("query", [None, True, 123])
def test_hybrid_rejects_non_string_query(query: object) -> None:
    with pytest.raises(TypeError):
        rag_search.hybrid_search(query, 5)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, 11, True, 1.5, "5", None])
def test_hybrid_reuses_result_limit_validation(limit: object) -> None:
    error = TypeError if not isinstance(limit, int) or isinstance(limit, bool) else rag_search.SearchError
    with pytest.raises(error):
        rag_search.hybrid_search("osłona", limit)  # type: ignore[arg-type]


def test_hybrid_propagates_controlled_missing_or_stale_index_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_id = indexer.build_corpus()[0].chunk_id
    monkeypatch.setattr(rag_search, "search", lambda query, limit: _ranked(chunk_id))

    def stale(query: str, limit: int) -> list[dict[str, object]]:
        raise vector_store.StaleIndexError("vector index is missing or stale: missing index")

    monkeypatch.setattr(vector_store, "dense_search", stale)

    with pytest.raises(vector_store.StaleIndexError, match="missing or stale"):
        rag_search.hybrid_search("osłona", 5)


def test_search_cli_defaults_to_bm25_and_has_explicit_offline_modes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake(method: str):
        def retrieve(query: str, limit: int) -> list[dict[str, object]]:
            calls.append((method, query, limit))
            return [{"rank": 1, "chunk_id": method}]

        return retrieve

    monkeypatch.setattr(rag_search, "search", fake("bm25"))
    monkeypatch.setattr(rag_search, "hybrid_search", fake("hybrid"))
    monkeypatch.setattr(vector_store, "dense_search", fake("dense"))

    assert rag_search.main(["--query", "q", "--limit", "2"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["chunk_id"] == "bm25"
    assert rag_search.main(["--mode", "dense", "--query", "q"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["chunk_id"] == "dense"
    assert rag_search.main(["--mode", "hybrid", "--query", "q"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["chunk_id"] == "hybrid"
    assert calls == [("bm25", "q", 2), ("dense", "q", 5), ("hybrid", "q", 5)]


def test_public_hybrid_signature_accepts_no_paths_or_model_configuration() -> None:
    assert list(inspect.signature(rag_search.hybrid_search).parameters) == [
        "query",
        "limit",
    ]
    with pytest.raises(SystemExit):
        rag_search.main(["--mode", "hybrid", "--query", "q", "--index", "x"])


def test_shared_benchmark_uses_one_gold_matcher_and_reports_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = evaluation.load_evaluation_cases()
    chunks = indexer.build_corpus()
    expected_ids = {
        case.query: next(
            chunk.chunk_id
            for chunk in chunks
            if evaluation._matches_expected(chunk, case.expected)
        )
        for case in cases
    }
    wrong_id = next(
        chunk.chunk_id
        for chunk in chunks
        if chunk.chunk_id not in set(expected_ids.values())
    )

    def result_for(method: str, query: str, limit: int) -> list[dict[str, object]]:
        case_index = next(index for index, case in enumerate(cases) if case.query == query)
        hit = not (
            (method == "bm25" and case_index == 0)
            or (method == "dense" and case_index == 1)
            or (method == "hybrid" and case_index == 2)
        )
        return _ranked(expected_ids[query] if hit else wrong_id)

    monkeypatch.setattr(
        vector_store,
        "check_index",
        lambda: SimpleNamespace(compatible=True, issues=()),
    )
    monkeypatch.setattr(
        rag_search,
        "search",
        lambda query, limit: result_for("bm25", query, limit),
    )
    monkeypatch.setattr(
        vector_store,
        "dense_search",
        lambda query, limit: result_for("dense", query, limit),
    )
    monkeypatch.setattr(
        rag_search,
        "hybrid_search",
        lambda query, limit: result_for("hybrid", query, limit),
    )

    report = evaluation.benchmark_all_retrieval(cases)

    assert report.total == 30
    assert report.bm25.hits == 29
    assert report.dense.hits == 29
    assert report.hybrid.hits == 29
    assert report.hybrid_improved_case_ids == (cases[0].case_id,)
    assert report.hybrid_degraded_case_ids == (cases[2].case_id,)
    assert all(method.elapsed_seconds >= 0 for method in report.methods)


def test_shared_benchmark_rejects_stale_index_before_any_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_store,
        "check_index",
        lambda: SimpleNamespace(compatible=False, issues=("metadata mismatch",)),
    )
    called = False

    def unexpected(query: str, limit: int) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(rag_search, "search", unexpected)

    with pytest.raises(vector_store.StaleIndexError, match="metadata mismatch"):
        evaluation.benchmark_all_retrieval()
    assert called is False


def test_bm25_evaluation_entrypoint_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evaluation,
        "benchmark_retrieval",
        lambda: evaluation.RetrievalReport(30, 24, 0.8, (), 0.01),
    )

    assert evaluation.main(["--retrieval"]) == 0
    assert "BM25 retrieval: 24/30 hits; recall@5=0.800" in capsys.readouterr().out


def test_hybrid_evaluation_has_a_separate_recall_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bm25 = evaluation.RetrievalReport(30, 24, 0.8, (), 0.01)
    dense = evaluation.RetrievalReport(30, 8, 8 / 30, (), 0.02)
    hybrid = evaluation.RetrievalReport(30, 23, 23 / 30, (), 0.03)
    monkeypatch.setattr(
        evaluation,
        "benchmark_all_retrieval",
        lambda: evaluation.RetrievalBenchmarkReport(
            30,
            bm25,
            dense,
            hybrid,
            (),
            (),
        ),
    )

    assert evaluation.MIN_HYBRID_RECALL_AT_5 == 0.8
    assert evaluation.main(["--hybrid"]) == 1


def test_hybrid_is_not_imported_or_registered_by_runtime_mcp() -> None:
    assert "hybrid_search" not in TOOL_NAMES
    script = """
import sys
import mcp_server.server
assert 'mcp_server.search' not in sys.modules
assert 'mcp_server.vector_store' not in sys.modules
for prefix in ('sentence_transformers', 'torch', 'transformers'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
