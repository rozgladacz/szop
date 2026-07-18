"""Coverage and shared retrieval gates for the canonical C2.1 evaluation set."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from mcp_server import search as rag_search
from mcp_server import vector_store
from mcp_server.indexer import CANONICAL_SOURCES, CorpusChunk, build_corpus

EVALUATION_PATH = Path(__file__).with_name("rag_evaluation.jsonl")
EXPECTED_EVALUATION_COUNT = 30
RETRIEVAL_LIMIT = 5
MIN_RECALL_AT_5 = 0.70
MIN_HYBRID_RECALL_AT_5 = 0.80
_EVALUATION_ID_RE = re.compile(r"^eval-(?:rules|abilities)-[0-9]{3}$")
_ALLOWED_SOURCES = {source.filename for source in CANONICAL_SOURCES}


class EvaluationError(ValueError):
    """The evaluation set is malformed or not covered by the corpus."""


@dataclass(frozen=True)
class ExpectedAnchor:
    source: str
    ref: str
    anchor: str


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    expected: ExpectedAnchor


@dataclass(frozen=True)
class CoverageReport:
    total: int
    covered: int
    sources: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalCaseResult:
    case_id: str
    hit: bool
    rank: int | None
    chunk_id: str | None


@dataclass(frozen=True)
class RetrievalReport:
    total: int
    hits: int
    recall_at_5: float
    cases: tuple[RetrievalCaseResult, ...]
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class RetrievalBenchmarkReport:
    total: int
    bm25: RetrievalReport
    dense: RetrievalReport
    hybrid: RetrievalReport
    hybrid_improved_case_ids: tuple[str, ...]
    hybrid_degraded_case_ids: tuple[str, ...]

    @property
    def methods(self) -> tuple[RetrievalReport, ...]:
        return (self.bm25, self.dense, self.hybrid)


def parse_evaluation_jsonl(data: bytes) -> tuple[EvaluationCase, ...]:
    """Parse strict UTF-8 JSONL content; this API accepts content, not a path."""
    if not isinstance(data, bytes):
        raise EvaluationError("evaluation data must be bytes")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvaluationError("evaluation set is not valid UTF-8") from exc

    cases: list[EvaluationCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise EvaluationError(f"blank line at evaluation line {line_number}")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"invalid JSON at evaluation line {line_number}") from exc
        cases.append(_parse_case(raw, line_number))
    return tuple(cases)


def load_evaluation_cases() -> tuple[EvaluationCase, ...]:
    """Read the one fixed, repository-owned evaluation artifact."""
    expected_parent = Path(__file__).resolve().parent
    path = EVALUATION_PATH.resolve(strict=True)
    if path.parent != expected_parent:
        raise EvaluationError("evaluation artifact escapes mcp_server")
    return parse_evaluation_jsonl(path.read_bytes())


def validate_evaluation(
    cases: Sequence[EvaluationCase] | None = None,
    chunks: Sequence[CorpusChunk] | None = None,
) -> CoverageReport:
    """Validate schema-level invariants and exact source/ref/anchor coverage."""
    selected_cases = tuple(cases) if cases is not None else load_evaluation_cases()
    selected_chunks = tuple(chunks) if chunks is not None else build_corpus()

    if len(selected_cases) != EXPECTED_EVALUATION_COUNT:
        raise EvaluationError(
            f"evaluation set must contain exactly {EXPECTED_EVALUATION_COUNT} records"
        )
    ids = [case.case_id for case in selected_cases]
    if len(ids) != len(set(ids)):
        raise EvaluationError("evaluation ids must be unique")
    sources = tuple(dict.fromkeys(case.expected.source for case in selected_cases))
    if set(sources) != _ALLOWED_SOURCES:
        raise EvaluationError("evaluation set must cover both canonical sources")

    missing: list[str] = []
    for case in selected_cases:
        if not any(_matches_expected(chunk, case.expected) for chunk in selected_chunks):
            missing.append(case.case_id)
    if missing:
        raise EvaluationError(
            "evaluation anchors missing from corpus: " + ", ".join(missing)
        )
    return CoverageReport(
        total=len(selected_cases),
        covered=len(selected_cases),
        sources=sources,
    )


def benchmark_retrieval(
    cases: Sequence[EvaluationCase] | None = None,
) -> RetrievalReport:
    """Measure BM25 recall@5 against the fixed source/ref/anchor gold set."""
    selected_cases = tuple(cases) if cases is not None else load_evaluation_cases()
    chunks = build_corpus()
    validate_evaluation(cases=selected_cases, chunks=chunks)
    return _benchmark_method(rag_search.search, selected_cases, chunks)


def benchmark_all_retrieval(
    cases: Sequence[EvaluationCase] | None = None,
) -> RetrievalBenchmarkReport:
    """Benchmark BM25, dense, and hybrid with one exact gold matcher."""
    selected_cases = tuple(cases) if cases is not None else load_evaluation_cases()
    chunks = build_corpus()
    validate_evaluation(cases=selected_cases, chunks=chunks)

    status = vector_store.check_index()
    if not status.compatible:
        raise vector_store.StaleIndexError(
            "vector index is missing or stale: " + "; ".join(status.issues)
        )

    bm25 = _benchmark_method(rag_search.search, selected_cases, chunks)
    dense = _benchmark_method(vector_store.dense_search, selected_cases, chunks)
    hybrid = _benchmark_method(rag_search.hybrid_search, selected_cases, chunks)
    improved = tuple(
        bm25_case.case_id
        for bm25_case, hybrid_case in zip(bm25.cases, hybrid.cases, strict=True)
        if not bm25_case.hit and hybrid_case.hit
    )
    degraded = tuple(
        bm25_case.case_id
        for bm25_case, hybrid_case in zip(bm25.cases, hybrid.cases, strict=True)
        if bm25_case.hit and not hybrid_case.hit
    )
    return RetrievalBenchmarkReport(
        total=len(selected_cases),
        bm25=bm25,
        dense=dense,
        hybrid=hybrid,
        hybrid_improved_case_ids=improved,
        hybrid_degraded_case_ids=degraded,
    )


def _benchmark_method(
    retrieve: Callable[[str, int], list[dict[str, object]]],
    cases: Sequence[EvaluationCase],
    chunks: Sequence[CorpusChunk],
) -> RetrievalReport:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    started = time.perf_counter()

    case_results: list[RetrievalCaseResult] = []
    for case in cases:
        matched_rank: int | None = None
        matched_chunk_id: str | None = None
        for rank, result in enumerate(
            retrieve(case.query, RETRIEVAL_LIMIT),
            start=1,
        ):
            chunk_id = result.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
                raise EvaluationError(
                    f"retrieval returned unknown chunk_id for {case.case_id}"
                )
            chunk = chunks_by_id[chunk_id]
            if _matches_expected(chunk, case.expected):
                matched_rank = rank
                matched_chunk_id = chunk.chunk_id
                break
        case_results.append(
            RetrievalCaseResult(
                case_id=case.case_id,
                hit=matched_rank is not None,
                rank=matched_rank,
                chunk_id=matched_chunk_id,
            )
        )

    hits = sum(result.hit for result in case_results)
    total = len(case_results)
    elapsed_seconds = time.perf_counter() - started
    return RetrievalReport(
        total=total,
        hits=hits,
        recall_at_5=hits / total,
        cases=tuple(case_results),
        elapsed_seconds=elapsed_seconds,
    )


def _matches_expected(chunk: CorpusChunk, expected: ExpectedAnchor) -> bool:
    return (
        chunk.source == expected.source
        and expected.ref in chunk.refs
        and expected.anchor in chunk.text
    )


def _parse_case(raw: object, line_number: int) -> EvaluationCase:
    if not isinstance(raw, dict) or set(raw) != {"id", "query", "expected"}:
        raise EvaluationError(f"invalid record schema at evaluation line {line_number}")
    case_id = _nonempty_string(raw["id"], "id", line_number)
    query = _nonempty_string(raw["query"], "query", line_number)
    if _EVALUATION_ID_RE.fullmatch(case_id) is None:
        raise EvaluationError(f"invalid id at evaluation line {line_number}")

    expected = raw["expected"]
    if not isinstance(expected, dict) or set(expected) != {"source", "ref", "anchor"}:
        raise EvaluationError(f"invalid expected schema at evaluation line {line_number}")
    source = _nonempty_string(expected["source"], "expected.source", line_number)
    ref = _nonempty_string(expected["ref"], "expected.ref", line_number)
    anchor = _nonempty_string(expected["anchor"], "expected.anchor", line_number)
    if source not in _ALLOWED_SOURCES:
        raise EvaluationError(f"unknown expected source at evaluation line {line_number}")
    return EvaluationCase(case_id, query, ExpectedAnchor(source, ref, anchor))


def _nonempty_string(value: object, field: str, line_number: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{field} must be a non-empty string at line {line_number}")
    if value != value.strip():
        raise EvaluationError(f"{field} must not have edge whitespace at line {line_number}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the fixed 30-question evaluation set against the C2.1 corpus.",
    )
    retrieval_modes = parser.add_mutually_exclusive_group()
    retrieval_modes.add_argument(
        "--retrieval",
        action="store_true",
        help="also run the fixed 30-question BM25 recall@5 benchmark",
    )
    retrieval_modes.add_argument(
        "--hybrid",
        action="store_true",
        help="benchmark BM25, dense, and hybrid on the same 30 questions",
    )
    args = parser.parse_args(argv)
    report = validate_evaluation()
    print(
        f"Corpus coverage: {report.covered}/{report.total} anchors across "
        f"{len(report.sources)} canonical sources"
    )
    if args.retrieval:
        retrieval = benchmark_retrieval()
        print(
            f"BM25 retrieval: {retrieval.hits}/{retrieval.total} hits; "
            f"recall@5={retrieval.recall_at_5:.3f}"
        )
        if retrieval.recall_at_5 < MIN_RECALL_AT_5:
            return 1
    elif args.hybrid:
        try:
            benchmark = benchmark_all_retrieval()
        except vector_store.VectorStoreError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for bm25_case, dense_case, hybrid_case in zip(
            benchmark.bm25.cases,
            benchmark.dense.cases,
            benchmark.hybrid.cases,
            strict=True,
        ):
            print(
                f"{bm25_case.case_id}: "
                f"bm25={_format_case_result(bm25_case)}; "
                f"dense={_format_case_result(dense_case)}; "
                f"hybrid={_format_case_result(hybrid_case)}"
            )
        for name, method in (
            ("BM25", benchmark.bm25),
            ("dense", benchmark.dense),
            ("hybrid", benchmark.hybrid),
        ):
            print(
                f"{name} retrieval: {method.hits}/{method.total} hits; "
                f"recall@5={method.recall_at_5:.3f}; "
                f"elapsed={method.elapsed_seconds:.3f}s"
            )
        print(
            "Hybrid vs BM25 improved: "
            + (", ".join(benchmark.hybrid_improved_case_ids) or "none")
        )
        print(
            "Hybrid vs BM25 degraded: "
            + (", ".join(benchmark.hybrid_degraded_case_ids) or "none")
        )
        if benchmark.hybrid.recall_at_5 < MIN_HYBRID_RECALL_AT_5:
            return 1
    return 0


def _format_case_result(result: RetrievalCaseResult) -> str:
    if not result.hit:
        return "miss"
    return f"hit@{result.rank}/{result.chunk_id}"


if __name__ == "__main__":
    raise SystemExit(main())
