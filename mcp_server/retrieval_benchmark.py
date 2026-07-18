"""Fixed one-process warm-latency benchmark for C2.5 offline retrieval."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time

from mcp_server import evaluation, search as rag_search, vector_store

BENCHMARK_SCHEMA = "szop.rag_retrieval_latency/v1"
LATENCY_CASE_IDS = tuple(f"eval-rules-{number:03d}" for number in range(1, 7))


def benchmark_warm_latency() -> dict[str, object]:
    """Measure six fixed hybrid calls after one compatible-index check."""
    status = vector_store.check_index()
    if not status.compatible:
        raise vector_store.StaleIndexError(
            "vector index is missing or stale: " + "; ".join(status.issues)
        )

    cases_by_id = {
        case.case_id: case for case in evaluation.load_evaluation_cases()
    }
    try:
        cases = tuple(cases_by_id[case_id] for case_id in LATENCY_CASE_IDS)
    except KeyError as exc:
        raise RuntimeError("fixed latency case is missing from the gold set") from exc

    durations: list[float] = []
    rankings: dict[str, list[str]] = {}
    total_started = time.perf_counter()
    for case in cases:
        call_started = time.perf_counter()
        results = rag_search.hybrid_search(case.query, evaluation.RETRIEVAL_LIMIT)
        durations.append(_json_seconds(time.perf_counter() - call_started))
        rankings[case.case_id] = [str(result["chunk_id"]) for result in results]
    total_seconds = _json_seconds(time.perf_counter() - total_started)

    warm = durations[1:]
    return {
        "schema": BENCHMARK_SCHEMA,
        "mode": "hybrid",
        "index": status.to_record(),
        "case_ids": list(LATENCY_CASE_IDS),
        "query_count": len(durations),
        "cold_first_call_seconds": durations[0],
        "warm_call_count": len(warm),
        "warm_p50_seconds": _json_seconds(statistics.median(warm)),
        "warm_p95_seconds": _json_seconds(_percentile(warm, 0.95)),
        "total_seconds": total_seconds,
        "top_chunk_ids_by_case": rankings,
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _json_seconds(value: float) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0.0:
        raise RuntimeError("retrieval benchmark produced an invalid duration")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the fixed C2.5 hybrid warm-latency query set.",
    )
    parser.parse_args(argv)
    try:
        payload = benchmark_warm_latency()
    except vector_store.VectorStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
