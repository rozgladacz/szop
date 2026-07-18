"""Deterministic offline BM25 and hybrid retrieval over the C2.1 corpus."""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from functools import lru_cache
from typing import Sequence

from rank_bm25 import BM25Okapi

from mcp_server import vector_store
from mcp_server.indexer import CorpusChunk, build_corpus

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 10
MAX_RESULT_TEXT_LENGTH = 1200
DEFAULT_LIMIT = 5
METADATA_TOKEN_WEIGHT = 2

# Fixed after the bounded C2.4 grid: depth {5, 10}, k {20, 60}, weights
# BM25:dense {1:1, 2:1}. See ADR-0026 and mcp_server.evaluation.
HYBRID_CANDIDATE_LIMIT = 5
RRF_K = 60
BM25_RRF_WEIGHT = 2.0
DENSE_RRF_WEIGHT = 1.0

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


def hybrid_search(query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, object]]:
    """Fuse the fixed BM25 and dense branches with deterministic weighted RRF."""
    normalized_query = _validate_query(query)
    selected_limit = _validate_limit(limit)

    bm25_results = search(normalized_query, HYBRID_CANDIDATE_LIMIT)
    dense_results = vector_store.dense_search(
        normalized_query,
        HYBRID_CANDIDATE_LIMIT,
    )
    return _fuse_ranked_results(
        bm25_results,
        dense_results,
        limit=selected_limit,
        chunks=build_corpus(),
    )


def _fuse_ranked_results(
    bm25_results: Sequence[dict[str, object]],
    dense_results: Sequence[dict[str, object]],
    *,
    limit: int,
    chunks: Sequence[CorpusChunk],
    candidate_limit: int = HYBRID_CANDIDATE_LIMIT,
    rrf_k: int = RRF_K,
    bm25_weight: float = BM25_RRF_WEIGHT,
    dense_weight: float = DENSE_RRF_WEIGHT,
) -> list[dict[str, object]]:
    """Fuse injected ranked lists; kept pure for tuning and model-free tests."""
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    corpus_order = {
        chunk.chunk_id: index
        for index, chunk in enumerate(chunks)
    }
    bm25_ranks = _candidate_ranks(
        bm25_results,
        candidate_limit=candidate_limit,
        chunks_by_id=chunks_by_id,
        branch="BM25",
    )
    dense_ranks = _candidate_ranks(
        dense_results,
        candidate_limit=candidate_limit,
        chunks_by_id=chunks_by_id,
        branch="dense",
    )

    candidates: list[tuple[float, int, str]] = []
    for chunk_id in bm25_ranks.keys() | dense_ranks.keys():
        score = _rrf_contribution(bm25_ranks.get(chunk_id), bm25_weight, rrf_k)
        score += _rrf_contribution(dense_ranks.get(chunk_id), dense_weight, rrf_k)
        if not math.isfinite(score):
            raise SearchError(f"non-finite hybrid score for {chunk_id}")
        candidates.append((score, corpus_order[chunk_id], chunk_id))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    results: list[dict[str, object]] = []
    for rank, (score, _, chunk_id) in enumerate(candidates[:limit], start=1):
        chunk = chunks_by_id[chunk_id]
        results.append(
            {
                "rank": rank,
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "headings": list(chunk.headings),
                "refs": list(chunk.refs),
                "text": _bounded_text(chunk.text),
                "score": _json_float(score),
                "components": {
                    "bm25": _rrf_component(
                        bm25_ranks.get(chunk_id),
                        bm25_weight,
                        rrf_k,
                    ),
                    "dense": _rrf_component(
                        dense_ranks.get(chunk_id),
                        dense_weight,
                        rrf_k,
                    ),
                },
            }
        )
    return results


def _candidate_ranks(
    results: Sequence[dict[str, object]],
    *,
    candidate_limit: int,
    chunks_by_id: dict[str, CorpusChunk],
    branch: str,
) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for rank, result in enumerate(results[:candidate_limit], start=1):
        if not isinstance(result, dict):
            raise SearchError(f"{branch} result at rank {rank} must be an object")
        chunk_id = result.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
            raise SearchError(f"{branch} returned unknown chunk_id at rank {rank}")
        ranks.setdefault(chunk_id, rank)
    return ranks


def _rrf_contribution(rank: int | None, weight: float, rrf_k: int) -> float:
    if rank is None:
        return 0.0
    return weight / (rrf_k + rank)


def _rrf_component(
    rank: int | None,
    weight: float,
    rrf_k: int,
) -> dict[str, object] | None:
    if rank is None:
        return None
    return {
        "rank": rank,
        "weight": weight,
        "contribution": _json_float(_rrf_contribution(rank, weight, rrf_k)),
    }


def _json_float(value: float) -> float:
    if not math.isfinite(value):
        raise SearchError("retrieval score must be finite")
    rounded = round(value, 12)
    return 0.0 if rounded == 0 else rounded


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
        description="Search the fixed canonical SZOP corpus in an offline mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("bm25", "dense", "hybrid"),
        default="bm25",
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    try:
        if args.mode == "bm25":
            results = search(args.query, args.limit)
        elif args.mode == "dense":
            results = vector_store.dense_search(args.query, args.limit)
        else:
            results = hybrid_search(args.query, args.limit)
    except (SearchError, TypeError, vector_store.VectorStoreError) as exc:
        parser.error(str(exc))
    print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
