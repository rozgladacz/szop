"""Determinism, input boundaries, and recall for the C2.2 BM25 slice."""

from __future__ import annotations

import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server import evaluation, indexer, search as rag_search


def test_tokenizer_folds_polish_case_diacritics_punctuation_and_refs() -> None:
    assert rag_search.tokenize("ŻÓŁĆ, Łódź; pkt 14.D.I — AP(X)") == [
        "zolc",
        "lodz",
        "pkt",
        "14",
        "d",
        "i",
        "ap",
        "x",
    ]


@pytest.mark.parametrize("query", ["", "   ", "...!!!"])
def test_search_rejects_empty_or_tokenless_query(query: str) -> None:
    with pytest.raises(rag_search.SearchError):
        rag_search.search(query, 5)


@pytest.mark.parametrize("query", [None, True, 123])
def test_search_rejects_non_string_query(query: object) -> None:
    with pytest.raises(TypeError):
        rag_search.search(query, 5)  # type: ignore[arg-type]


def test_search_rejects_overlong_query() -> None:
    with pytest.raises(rag_search.SearchError, match="200"):
        rag_search.search("a" * (rag_search.MAX_QUERY_LENGTH + 1), 5)


@pytest.mark.parametrize("limit", [0, -1, rag_search.MAX_RESULTS + 1])
def test_search_rejects_out_of_range_limit(limit: int) -> None:
    with pytest.raises(rag_search.SearchError):
        rag_search.search("osłona", limit)


@pytest.mark.parametrize("limit", [True, False, 1.5, "5", None])
def test_search_rejects_bool_and_non_integer_limit(limit: object) -> None:
    with pytest.raises(TypeError):
        rag_search.search("osłona", limit)  # type: ignore[arg-type]


def test_search_is_deterministic_and_breaks_zero_score_ties_by_corpus_order() -> None:
    assert rag_search.search("przegrupowanie oddział", 5) == rag_search.search(
        "przegrupowanie oddział",
        5,
    )
    tied = rag_search.search("qzxvnotincorpus", 3)
    assert [result["chunk_id"] for result in tied] == [
        chunk.chunk_id for chunk in indexer.build_corpus()[:3]
    ]
    assert [result["score"] for result in tied] == [0.0, 0.0, 0.0]


def test_search_indexes_source_headings_and_exact_references() -> None:
    by_ref = rag_search.search("pkt 14.d.i", 5)
    assert any(
        result["source"] == "SZOP_Rozjemca.md" and "pkt 14.d.i" in result["refs"]
        for result in by_ref
    )
    by_source = rag_search.search("SZOP Zdolnosci", 5)
    assert all(result["source"] == "SZOP_Zdolnosci.md" for result in by_source)


def test_results_are_ranked_bounded_and_json_safe() -> None:
    results = rag_search.search("oddział atak obrona", 5)
    assert [result["rank"] for result in results] == [1, 2, 3, 4, 5]
    assert all(
        len(result["text"]) <= rag_search.MAX_RESULT_TEXT_LENGTH
        for result in results
    )
    assert any(result["text"].endswith("…") for result in results)
    assert all(isinstance(result["score"], float) for result in results)
    assert all(math.isfinite(result["score"]) for result in results)
    json.dumps(results, ensure_ascii=False, allow_nan=False)


def test_public_search_and_cli_accept_no_arbitrary_paths() -> None:
    assert list(inspect.signature(rag_search.search).parameters) == ["query", "limit"]
    with pytest.raises(SystemExit):
        rag_search.main(["--query", "osłona", "--input", "outside.md"])


def test_search_and_evaluation_have_no_runtime_db_http_or_orm_imports() -> None:
    for module in (rag_search, evaluation):
        source = Path(module.__file__).read_text(encoding="utf-8").casefold()
        for forbidden in (
            "sqlalchemy",
            "app.models",
            "app.database",
            "sessionlocal",
            "httpx",
            "requests",
        ):
            assert forbidden not in source


def test_search_module_cli_smoke() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "mcp_server.search",
            "--query",
            "osłona",
            "--limit",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)
    assert len(payload) == 2
    assert payload[0]["rank"] == 1


def test_benchmark_runs_exactly_30_cases_and_meets_recall_gate() -> None:
    report = evaluation.benchmark_retrieval()
    assert report.total == len(report.cases) == evaluation.EXPECTED_EVALUATION_COUNT == 30
    assert report.hits == sum(case.hit for case in report.cases)
    assert report.recall_at_5 == report.hits / report.total
    assert report.recall_at_5 >= evaluation.MIN_RECALL_AT_5
