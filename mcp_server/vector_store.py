"""Persistent, atomically rebuilt sqlite-vec store for the C2.3 corpus."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sqlite3
import struct
import sys
import tempfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_server import indexer
from mcp_server.embeddings import (
    EMBEDDING_DIMENSION,
    MODEL_ID,
    MODEL_REVISION,
    EmbeddingError,
    Embedder,
    get_default_embedder,
    normalize_and_validate_embeddings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_PATH = PROJECT_ROOT / "build" / "rag_vectors.sqlite"

INDEX_SCHEMA = "szop.rag_vectors/v1"
INDEX_SCHEMA_VERSION = 1
MAX_QUERY_LENGTH = 200
MAX_RESULTS = 10
MAX_RESULT_TEXT_LENGTH = 1200
_TEMP_PREFIX = ".rag_vectors-"
_TEMP_SUFFIX = ".sqlite.tmp"


# === SECTION: Public store contract and offline APIs ===


class VectorStoreError(RuntimeError):
    """Base error for vector store availability, input, or integrity failures."""


class StaleIndexError(VectorStoreError):
    """The persistent index does not match the current corpus/model contract."""


@dataclass(frozen=True)
class IndexStatus:
    compatible: bool
    corpus_hash: str
    chunk_count: int
    vector_count: int
    sqlite_vec_version: str | None
    issues: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "schema": INDEX_SCHEMA,
            "version": INDEX_SCHEMA_VERSION,
            "path": "build/rag_vectors.sqlite",
            "compatible": self.compatible,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "corpus_hash": self.corpus_hash,
            "chunk_count": self.chunk_count,
            "vector_count": self.vector_count,
            "sqlite_vec_version": self.sqlite_vec_version,
            "issues": list(self.issues),
        }


def rebuild_index(*, embedder: Embedder | None = None) -> IndexStatus:
    """Build and atomically replace only the fixed project vector index."""
    chunks = indexer.build_corpus()
    provider = embedder if embedder is not None else get_default_embedder()
    _validate_embedder_metadata(provider)
    raw_vectors = provider.embed(tuple(_embedding_text(chunk) for chunk in chunks))
    vectors = normalize_and_validate_embeddings(
        raw_vectors,
        expected_count=len(chunks),
    )

    output = _fixed_index_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=_TEMP_PREFIX,
        suffix=_TEMP_SUFFIX,
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _build_database(temporary, chunks, vectors)
        _fsync_file(temporary)
        status = _validate_built_index(temporary, chunks)
        if not status.compatible:
            raise VectorStoreError(
                "temporary vector index failed validation: " + "; ".join(status.issues)
            )
        os.replace(temporary, output)
        _fsync_directory_best_effort(output.parent)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return check_index()


def check_index() -> IndexStatus:
    """Check the fixed store against the current corpus and model metadata."""
    chunks = indexer.build_corpus()
    return _inspect_index(_fixed_index_path(), chunks)


def dense_search(
    query: str,
    limit: int = 5,
    *,
    embedder: Embedder | None = None,
) -> list[dict[str, object]]:
    """Return deterministic JSON-safe dense top-k from the fixed offline store."""
    clean_query = _validate_query(query)
    clean_limit = _validate_limit(limit)
    status = check_index()
    if not status.compatible:
        raise StaleIndexError("vector index is missing or stale: " + "; ".join(status.issues))

    provider = embedder if embedder is not None else get_default_embedder()
    _validate_embedder_metadata(provider)
    raw_query_vector = provider.embed((clean_query,))
    query_vector = normalize_and_validate_embeddings(
        raw_query_vector,
        expected_count=1,
    )[0]

    path = _fixed_index_path()
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT
                chunks.chunk_id,
                chunks.source,
                chunks.headings_json,
                chunks.refs_json,
                chunks.text,
                rag_vectors.distance
            FROM rag_vectors
            JOIN chunks ON chunks.internal_id = rag_vectors.chunk_rowid
            WHERE rag_vectors.embedding MATCH ? AND k = ?
            """,
            (_serialize_vector(query_vector), status.vector_count),
        ).fetchall()

    ranked: list[tuple[float, str, sqlite3.Row]] = []
    for row in rows:
        distance = float(row["distance"])
        if not math.isfinite(distance):
            raise VectorStoreError("sqlite-vec returned a non-finite distance")
        ranked.append((distance, str(row["chunk_id"]), row))
    ranked.sort(key=lambda item: (item[0], item[1]))

    results: list[dict[str, object]] = []
    for rank, (distance, chunk_id, row) in enumerate(ranked[:clean_limit], start=1):
        score = 1.0 - distance
        if not math.isfinite(score):
            raise VectorStoreError("dense similarity score is not finite")
        results.append(
            {
                "rank": rank,
                "chunk_id": chunk_id,
                "source": str(row["source"]),
                "headings": json.loads(row["headings_json"]),
                "refs": json.loads(row["refs_json"]),
                "text": _bounded_text(str(row["text"])),
                "distance": distance,
                "score": score,
            }
        )
    return results


# === SECTION: Fixed boundaries and sqlite-vec binding ===


def _embedding_text(chunk: indexer.CorpusChunk) -> str:
    metadata = "\n".join((chunk.source, *chunk.headings, *chunk.refs))
    return f"{metadata}\n\n{chunk.text}" if metadata else chunk.text


def _validate_embedder_metadata(embedder: Embedder) -> None:
    if getattr(embedder, "model_id", None) != MODEL_ID:
        raise VectorStoreError("embedder must use the fixed C2.3 model id")
    if getattr(embedder, "model_revision", None) != MODEL_REVISION:
        raise VectorStoreError("embedder must use the fixed C2.3 model revision")
    if getattr(embedder, "dimension", None) != EMBEDDING_DIMENSION:
        raise VectorStoreError("embedder must use the fixed C2.3 dimension")


def _fixed_index_path() -> Path:
    project_root = PROJECT_ROOT.resolve(strict=True)
    expected = (project_root / "build" / "rag_vectors.sqlite").resolve(strict=False)
    configured = DEFAULT_INDEX_PATH.resolve(strict=False)
    if configured != expected:
        raise VectorStoreError("vector index must be the fixed project build artifact")
    return configured


def _connect(path: Path) -> sqlite3.Connection:
    try:
        sqlite_vec = importlib.import_module("sqlite_vec")
    except ImportError as exc:
        raise VectorStoreError(
            "sqlite-vec is missing; install requirements-rag.txt"
        ) from exc
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)
    except Exception as exc:
        connection.close()
        raise VectorStoreError("cannot initialize sqlite-vec binding") from exc
    return connection


def _serialize_vector(vector: Sequence[float]) -> bytes:
    sqlite_vec = importlib.import_module("sqlite_vec")
    return sqlite_vec.serialize_float32(vector)


# === SECTION: Schema creation and deterministic metadata ===


def _build_database(
    path: Path,
    chunks: Sequence[indexer.CorpusChunk],
    vectors: Sequence[Sequence[float]],
) -> None:
    with closing(_connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            f"""
            CREATE TABLE index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) STRICT;

            CREATE TABLE chunks (
                internal_id INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                source_key TEXT NOT NULL,
                source TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                headings_json TEXT NOT NULL CHECK(json_valid(headings_json)),
                refs_json TEXT NOT NULL CHECK(json_valid(refs_json)),
                text TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                content_hash TEXT NOT NULL
            ) STRICT;

            CREATE VIRTUAL TABLE rag_vectors USING vec0(
                chunk_rowid INTEGER PRIMARY KEY,
                embedding float[{EMBEDDING_DIMENSION}] distance_metric=cosine
            );
            """
        )
        sqlite_vec_version = _sqlite_vec_version(connection)
        metadata = _expected_metadata(chunks, sqlite_vec_version)
        connection.executemany(
            "INSERT INTO index_metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        connection.executemany(
            """
            INSERT INTO chunks(
                internal_id, chunk_id, source_key, source, ordinal,
                headings_json, refs_json, text, word_count, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [_chunk_row(internal_id, chunk) for internal_id, chunk in enumerate(chunks, 1)],
        )
        connection.executemany(
            "INSERT INTO rag_vectors(chunk_rowid, embedding) VALUES (?, ?)",
            [
                (internal_id, _serialize_vector(vector))
                for internal_id, vector in enumerate(vectors, 1)
            ],
        )
        connection.commit()


def _expected_metadata(
    chunks: Sequence[indexer.CorpusChunk],
    sqlite_vec_version: str,
) -> dict[str, str]:
    return {
        "index_schema": INDEX_SCHEMA,
        "schema_version": str(INDEX_SCHEMA_VERSION),
        "corpus_schema": indexer.CORPUS_SCHEMA,
        "corpus_version": str(indexer.CORPUS_VERSION),
        "corpus_hash": _corpus_hash(chunks),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "embedding_dimension": str(EMBEDDING_DIMENSION),
        "normalization": "l2",
        "distance_metric": "cosine",
        "chunk_count": str(len(chunks)),
        "sqlite_vec_version": sqlite_vec_version,
    }


def _corpus_hash(chunks: Sequence[indexer.CorpusChunk]) -> str:
    return hashlib.sha256(indexer.render_manifest(chunks)).hexdigest()


def _chunk_row(
    internal_id: int,
    chunk: indexer.CorpusChunk,
) -> tuple[object, ...]:
    return (
        internal_id,
        chunk.chunk_id,
        chunk.source_key,
        chunk.source,
        chunk.ordinal,
        _stable_json(chunk.headings),
        _stable_json(chunk.refs),
        chunk.text,
        chunk.word_count,
        chunk.content_hash,
    )


def _stable_json(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _validate_built_index(
    path: Path,
    chunks: Sequence[indexer.CorpusChunk],
) -> IndexStatus:
    return _inspect_index(path, chunks)


# === SECTION: Integrity and stale-index validation ===


def _inspect_index(
    path: Path,
    chunks: Sequence[indexer.CorpusChunk],
) -> IndexStatus:
    corpus_hash = _corpus_hash(chunks)
    if not path.is_file():
        return IndexStatus(False, corpus_hash, 0, 0, None, ("index file is missing",))

    try:
        with closing(_connect(path)) as connection:
            sqlite_vec_version = _sqlite_vec_version(connection)
            issues, chunk_count, vector_count = _validate_connection(
                connection,
                chunks,
                sqlite_vec_version,
            )
    except (OSError, sqlite3.Error, VectorStoreError) as exc:
        return IndexStatus(
            False,
            corpus_hash,
            0,
            0,
            None,
            (f"cannot open or validate index: {type(exc).__name__}",),
        )
    return IndexStatus(
        not issues,
        corpus_hash,
        chunk_count,
        vector_count,
        sqlite_vec_version,
        tuple(issues),
    )


def _validate_connection(
    connection: sqlite3.Connection,
    chunks: Sequence[indexer.CorpusChunk],
    sqlite_vec_version: str,
) -> tuple[list[str], int, int]:
    issues: list[str] = []
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        issues.append("sqlite integrity check failed")

    stored_metadata = {
        str(row["key"]): str(row["value"])
        for row in connection.execute("SELECT key, value FROM index_metadata")
    }
    expected_metadata = _expected_metadata(chunks, sqlite_vec_version)
    for key, expected in expected_metadata.items():
        if stored_metadata.get(key) != expected:
            issues.append(f"metadata mismatch: {key}")
    if set(stored_metadata) != set(expected_metadata):
        issues.append("metadata keys mismatch")

    stored_chunks = [
        tuple(row)
        for row in connection.execute(
            """
            SELECT internal_id, chunk_id, source_key, source, ordinal,
                   headings_json, refs_json, text, word_count, content_hash
            FROM chunks ORDER BY internal_id
            """
        )
    ]
    expected_chunks = [
        _chunk_row(internal_id, chunk)
        for internal_id, chunk in enumerate(chunks, 1)
    ]
    chunk_count = len(stored_chunks)
    if stored_chunks != expected_chunks:
        issues.append("stored chunk metadata does not match current corpus")

    vector_rows = connection.execute(
        "SELECT chunk_rowid, embedding FROM rag_vectors ORDER BY chunk_rowid"
    ).fetchall()
    vector_count = len(vector_rows)
    if [int(row["chunk_rowid"]) for row in vector_rows] != list(
        range(1, len(chunks) + 1)
    ):
        issues.append("vector ids do not match chunk ids")
    for row in vector_rows:
        blob = bytes(row["embedding"])
        if len(blob) != EMBEDDING_DIMENSION * 4:
            issues.append("stored vector has invalid byte length")
            break
        values = struct.unpack(f"<{EMBEDDING_DIMENSION}f", blob)
        if not all(math.isfinite(value) for value in values):
            issues.append("stored vector contains non-finite values")
            break
    if chunk_count != len(chunks):
        issues.append("chunk count mismatch")
    if vector_count != len(chunks):
        issues.append("vector count mismatch")
    return issues, chunk_count, vector_count


def _sqlite_vec_version(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT vec_version()").fetchone()
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise VectorStoreError("sqlite-vec did not report a valid version")
    return row[0]


# === SECTION: Atomic durability and CLI input validation ===


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory_best_effort(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    clean = query.strip()
    if not clean:
        raise VectorStoreError("query must not be blank")
    if len(query) > MAX_QUERY_LENGTH:
        raise VectorStoreError(f"query must not exceed {MAX_QUERY_LENGTH} characters")
    return clean


def _validate_limit(limit: int) -> int:
    if type(limit) is not int:
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= MAX_RESULTS:
        raise VectorStoreError(f"limit must be between 1 and {MAX_RESULTS}")
    return limit


def _bounded_text(text: str) -> str:
    if len(text) <= MAX_RESULT_TEXT_LENGTH:
        return text
    return text[: MAX_RESULT_TEXT_LENGTH - 1].rstrip() + "…"


# === SECTION: Offline CLI ===


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage the fixed offline C2.3 sqlite-vec rules index.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("rebuild", help="atomically rebuild the fixed index")
    subparsers.add_parser("check", help="check the fixed index against the corpus")
    query_parser = subparsers.add_parser("query", help="run an offline dense query")
    query_parser.add_argument("--query", required=True)
    query_parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        if args.command == "rebuild":
            payload: Any = rebuild_index().to_record()
            exit_code = 0
        elif args.command == "check":
            status = check_index()
            payload = status.to_record()
            exit_code = 0 if status.compatible else 1
        else:
            payload = dense_search(args.query, args.limit)
            exit_code = 0
    except (EmbeddingError, VectorStoreError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
