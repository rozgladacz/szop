"""Fixed, offline-first sentence embeddings for the C2.3 rules index."""

from __future__ import annotations

import argparse
import math
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_CACHE_DIR = PROJECT_ROOT / "build" / "models"

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
EMBEDDING_DIMENSION = 384
EMBEDDING_BATCH_SIZE = 16
_MODEL_PROBE = "SZOP model cache verification"


# === SECTION: Embedding contract and lazy model adapter ===


class EmbeddingError(RuntimeError):
    """The fixed embedding model or its output violates C2.3 invariants."""


class Embedder(Protocol):
    """Small injection seam used by the vector store and deterministic tests."""

    model_id: str
    model_revision: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


class SentenceTransformerEmbedder:
    """Lazy CPU wrapper around the one allowlisted sentence-transformers model.

    Model construction is protected from concurrent first use. Inference is
    serialized because SentenceTransformer does not document shared-instance
    ``encode`` calls as thread-safe. No input text or output vector is cached.
    """

    model_id = MODEL_ID
    model_revision = MODEL_REVISION
    dimension = EMBEDDING_DIMENSION

    def __init__(self, *, allow_download: bool = False) -> None:
        self._allow_download = allow_download
        self._model = None
        self._model_load_lock = threading.Lock()
        self._encode_lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        selected = _validate_texts(texts)
        if not selected:
            return ()
        model = self._load_model()
        with self._encode_lock:
            raw = model.encode(
                list(selected),
                batch_size=EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True,
                convert_to_tensor=False,
                normalize_embeddings=True,
                device="cpu",
            )
        return normalize_and_validate_embeddings(raw, expected_count=len(selected))

    def _load_model(self):
        with self._model_load_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "optional RAG dependencies are missing; install requirements-rag.txt"
                ) from exc

            cache_dir = _fixed_model_cache_dir()
            try:
                model = SentenceTransformer(
                    MODEL_ID,
                    revision=MODEL_REVISION,
                    cache_folder=str(cache_dir),
                    local_files_only=not self._allow_download,
                    device="cpu",
                    trust_remote_code=False,
                    token=False,
                    backend="torch",
                )
            except Exception as exc:
                mode = "download" if self._allow_download else "offline"
                raise EmbeddingError(
                    f"cannot load fixed MiniLM model in {mode} mode"
                ) from exc

            actual_dimension = model.get_embedding_dimension()
            if actual_dimension != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"model dimension is {actual_dimension}; "
                    f"expected {EMBEDDING_DIMENSION}"
                )
            self._model = model
            return model


_default_embedder: SentenceTransformerEmbedder | None = None
_default_embedder_lock = threading.Lock()


def get_default_embedder() -> SentenceTransformerEmbedder:
    """Return the one lazy offline embedder owned by this Python process."""
    global _default_embedder
    with _default_embedder_lock:
        if _default_embedder is None:
            _default_embedder = SentenceTransformerEmbedder()
        return _default_embedder


# === SECTION: Vector validation and fixed cache operations ===


def normalize_and_validate_embeddings(
    vectors: object,
    *,
    expected_count: int,
) -> tuple[tuple[float, ...], ...]:
    """Return finite, 384-dimensional, unit-length Python float vectors."""
    if type(expected_count) is not int or expected_count < 0:
        raise TypeError("expected_count must be a non-negative integer")
    try:
        rows = tuple(vectors)  # type: ignore[arg-type]
    except TypeError as exc:
        raise EmbeddingError("embedding output must be a sequence of vectors") from exc
    if len(rows) != expected_count:
        raise EmbeddingError(
            f"embedding count is {len(rows)}; expected {expected_count}"
        )

    normalized: list[tuple[float, ...]] = []
    for row_number, row in enumerate(rows, start=1):
        if isinstance(row, (str, bytes, bytearray)):
            raise EmbeddingError(f"embedding {row_number} is not a numeric vector")
        try:
            values = tuple(float(value) for value in row)
        except (TypeError, ValueError) as exc:
            raise EmbeddingError(
                f"embedding {row_number} is not a numeric vector"
            ) from exc
        if len(values) != EMBEDDING_DIMENSION:
            raise EmbeddingError(
                f"embedding {row_number} has dimension {len(values)}; "
                f"expected {EMBEDDING_DIMENSION}"
            )
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingError(f"embedding {row_number} contains non-finite values")
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isfinite(norm) or norm <= 0.0:
            raise EmbeddingError(f"embedding {row_number} has zero or invalid norm")
        unit = tuple(value / norm for value in values)
        if not all(math.isfinite(value) for value in unit):
            raise EmbeddingError(f"embedding {row_number} cannot be normalized")
        normalized.append(unit)
    return tuple(normalized)


def download_model() -> Path:
    """Download and validate only the fixed model into the fixed project cache."""
    embedder = SentenceTransformerEmbedder(allow_download=True)
    embedder.embed((_MODEL_PROBE,))
    return _fixed_model_cache_dir()


def _validate_texts(texts: Sequence[str]) -> tuple[str, ...]:
    if isinstance(texts, (str, bytes, bytearray)):
        raise TypeError("texts must be a sequence of strings")
    selected = tuple(texts)
    for text in selected:
        if not isinstance(text, str):
            raise TypeError("every embedding input must be a string")
        if not text.strip():
            raise EmbeddingError("embedding input must not be blank")
    return selected


def _fixed_model_cache_dir() -> Path:
    project_root = PROJECT_ROOT.resolve(strict=True)
    expected = (project_root / "build" / "models").resolve(strict=False)
    configured = MODEL_CACHE_DIR.resolve(strict=False)
    if configured != expected:
        raise EmbeddingError("model cache must be the fixed project build/models directory")
    configured.mkdir(parents=True, exist_ok=True)
    return configured


# === SECTION: Fixed model-download CLI ===


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the fixed C2.3 MiniLM model into build/models.",
    )
    parser.parse_args(argv)
    try:
        cache_dir = download_model()
    except EmbeddingError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"Downloaded and verified {MODEL_ID}@{MODEL_REVISION[:12]} "
        f"in {cache_dir.relative_to(PROJECT_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
