"""Deterministic offline BM25 retrieval over the canonical C2.1 corpus."""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from functools import lru_cache

from rank_bm25 import BM25Okapi

from mcp_server.indexer import CorpusChunk, build_corpus

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 10
MAX_RESULT_TEXT_LENGTH = 1200
DEFAULT_LIMIT = 5
METADATA_TOKEN_WEIGHT = 2

_POLISH_TRANSLATION = str.maketrans({"ł": "l", "Ł": "L"})


class SearchError(ValueError):
    """The retrieval request or generated score is invalid."""


def tokenize(text: str) -> list[str]:
    """Return deterministic Unicode tokens with case and diacritics folded."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    decomposed = unicodedata.normalize("NFKD", text.translate(_POLISH_TRANSLATION))
    folded = "".join(
        character.casefold() if character.isalnum() else " "
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return folded.split()


def search(query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, object]]:
    """Return bounded, JSON-safe BM25 results in deterministic rank order."""
    normalized_query = _validate_query(query)
    selected_limit = _validate_limit(limit)
    query_tokens = tokenize(normalized_query)
    if not query_tokens:
        raise SearchError("query must contain at least one letter or digit")

    chunks, bm25 = _load_index()
    raw_scores = bm25.get_scores(query_tokens)
    ordered_indexes = sorted(
        range(len(chunks)),
        key=lambda index: (-float(raw_scores[index]), index),
    )[:selected_limit]

    results: list[dict[str, object]] = []
    for rank, index in enumerate(ordered_indexes, start=1):
        chunk = chunks[index]
        results.append(_result_record(rank, chunk, float(raw_scores[index])))
    return results


@lru_cache(maxsize=1)
def _load_index() -> tuple[tuple[CorpusChunk, ...], BM25Okapi]:
    chunks = build_corpus()
    tokenized_corpus = [_chunk_tokens(chunk) for chunk in chunks]
    return chunks, BM25Okapi(tokenized_corpus)


def _chunk_tokens(chunk: CorpusChunk) -> list[str]:
    metadata = " ".join((chunk.source, *chunk.headings, *chunk.refs))
    metadata_tokens = tokenize(metadata)
    return metadata_tokens * METADATA_TOKEN_WEIGHT + tokenize(chunk.text)


def _validate_query(query: object) -> str:
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise SearchError("query must not be empty")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise SearchError(f"query must not exceed {MAX_QUERY_LENGTH} characters")
    return normalized


def _validate_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= MAX_RESULTS:
        raise SearchError(f"limit must be between 1 and {MAX_RESULTS}")
    return limit


def _result_record(rank: int, chunk: CorpusChunk, score: float) -> dict[str, object]:
    if not math.isfinite(score):
        raise SearchError(f"non-finite BM25 score for {chunk.chunk_id}")
    json_score = round(score, 12)
    if json_score == 0:
        json_score = 0.0
    return {
        "rank": rank,
        "chunk_id": chunk.chunk_id,
        "source": chunk.source,
        "headings": list(chunk.headings),
        "refs": list(chunk.refs),
        "text": _bounded_text(chunk.text),
        "score": json_score,
    }


def _bounded_text(text: str) -> str:
    if len(text) <= MAX_RESULT_TEXT_LENGTH:
        return text
    return text[: MAX_RESULT_TEXT_LENGTH - 1].rstrip() + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search the fixed canonical SZOP corpus with offline BM25.",
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    try:
        results = search(args.query, args.limit)
    except (SearchError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
