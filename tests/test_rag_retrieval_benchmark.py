"""Model-free contract tests for the fixed C2.5 warm-latency benchmark."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mcp_server import retrieval_benchmark


def test_benchmark_checks_index_and_reports_json_safe_fixed_latency_set(
    monkeypatch,
) -> None:
    check_calls = 0

    class CompatibleStatus:
        compatible = True
        issues = ()

        def to_record(self):
            return {"compatible": True, "issues": []}

    def check_index():
        nonlocal check_calls
        check_calls += 1
        return CompatibleStatus()

    calls: list[tuple[str, int]] = []

    def retrieve(query: str, limit: int):
        calls.append((query, limit))
        return [{"chunk_id": f"chunk-{len(calls)}"}]

    clock = iter((0.0, 0.0, 10.0, 10.0, 11.0, 11.0, 13.0,
                  13.0, 16.0, 16.0, 20.0, 20.0, 25.0, 25.0))
    monkeypatch.setattr(retrieval_benchmark.vector_store, "check_index", check_index)
    monkeypatch.setattr(retrieval_benchmark.rag_search, "hybrid_search", retrieve)
    monkeypatch.setattr(retrieval_benchmark.time, "perf_counter", lambda: next(clock))

    report = retrieval_benchmark.benchmark_warm_latency()

    assert check_calls == 1
    assert report["schema"] == retrieval_benchmark.BENCHMARK_SCHEMA
    assert report["mode"] == "hybrid"
    assert report["case_ids"] == list(retrieval_benchmark.LATENCY_CASE_IDS)
    assert report["query_count"] == len(calls) == 6
    assert report["cold_first_call_seconds"] == 10.0
    assert report["warm_p50_seconds"] == 3.0
    assert report["warm_p95_seconds"] == pytest.approx(4.8)
    assert report["total_seconds"] == 25.0
    json.dumps(report, ensure_ascii=False, allow_nan=False)


def test_benchmark_rejects_stale_index_before_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval_benchmark.vector_store,
        "check_index",
        lambda: SimpleNamespace(compatible=False, issues=("metadata mismatch",)),
    )
    with pytest.raises(retrieval_benchmark.vector_store.StaleIndexError):
        retrieval_benchmark.benchmark_warm_latency()


def test_benchmark_cli_accepts_no_queries_models_or_paths(monkeypatch, capsys) -> None:
    payload = {"schema": retrieval_benchmark.BENCHMARK_SCHEMA, "value": 1.0}
    monkeypatch.setattr(
        retrieval_benchmark,
        "benchmark_warm_latency",
        lambda: payload,
    )
    assert retrieval_benchmark.main([]) == 0
    assert json.loads(capsys.readouterr().out) == payload

    with pytest.raises(SystemExit):
        retrieval_benchmark.main(["--query", "arbitrary"])
    with pytest.raises(SystemExit):
        retrieval_benchmark.main(["--model-id", "arbitrary/model"])
    with pytest.raises(SystemExit):
        retrieval_benchmark.main(["--path", "outside.sqlite"])
