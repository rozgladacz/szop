"""Schema and corpus-coverage gate for the canonical C2.1 evaluation set."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from mcp_server.indexer import CANONICAL_SOURCES, CorpusChunk, build_corpus

EVALUATION_PATH = Path(__file__).with_name("rag_evaluation.jsonl")
EXPECTED_EVALUATION_COUNT = 30
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
        if not any(
            chunk.source == case.expected.source
            and case.expected.ref in chunk.refs
            and case.expected.anchor in chunk.text
            for chunk in selected_chunks
        ):
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
    parser.parse_args(argv)
    report = validate_evaluation()
    print(
        f"Corpus coverage: {report.covered}/{report.total} anchors across "
        f"{len(report.sources)} canonical sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
