"""C2.3 sqlite-vec persistence, atomicity, and offline API boundaries."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import subprocess
import sys
from contextlib import closing

import pytest

from mcp_server import embeddings, indexer, vector_store


class FakeEmbedder:
    model_id = embeddings.MODEL_ID
    model_revision = embeddings.MODEL_REVISION
    dimension = embeddings.EMBEDDING_DIMENSION

    def __init__(self, salt: str = "fake") -> None:
        self.salt = salt

    def embed(self, texts):
        vectors = []
        for text in texts:
            values: list[float] = []
            counter = 0
            while len(values) < self.dimension:
                digest = hashlib.sha256(
                    f"{self.salt}:{counter}:{text}".encode("utf-8")
                ).digest()
                values.extend((byte - 127.5) / 127.5 for byte in digest)
                counter += 1
            vectors.append(tuple(values[: self.dimension]))
        return tuple(vectors)


class ConstantEmbedder(FakeEmbedder):
    def embed(self, texts):
        vector = (1.0,) + (0.0,) * (self.dimension - 1)
        return tuple(vector for _ in texts)


@pytest.fixture
def isolated_index(tmp_path, monkeypatch):
    pytest.importorskip("sqlite_vec", reason="optional requirements-rag.txt profile")
    index_path = tmp_path / "build" / "rag_vectors.sqlite"
    monkeypatch.setattr(vector_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(vector_store, "DEFAULT_INDEX_PATH", index_path)
    return index_path


def test_embedding_validation_enforces_count_dimension_finite_and_normalization() -> None:
    vector = [3.0, 4.0] + [0.0] * (embeddings.EMBEDDING_DIMENSION - 2)
    result = embeddings.normalize_and_validate_embeddings([vector], expected_count=1)
    assert math.isclose(math.sqrt(sum(value * value for value in result[0])), 1.0)

    with pytest.raises(embeddings.EmbeddingError, match="dimension"):
        embeddings.normalize_and_validate_embeddings([[1.0]], expected_count=1)
    with pytest.raises(embeddings.EmbeddingError, match="non-finite"):
        embeddings.normalize_and_validate_embeddings(
            [[math.nan] + [1.0] * (embeddings.EMBEDDING_DIMENSION - 1)],
            expected_count=1,
        )
    with pytest.raises(embeddings.EmbeddingError, match="zero"):
        embeddings.normalize_and_validate_embeddings(
            [[0.0] * embeddings.EMBEDDING_DIMENSION],
            expected_count=1,
        )


def test_rebuild_persists_schema_metadata_and_36_finite_vectors(isolated_index) -> None:
    status = vector_store.rebuild_index(embedder=FakeEmbedder())
    assert status.compatible
    assert status.chunk_count == status.vector_count == len(indexer.build_corpus()) == 36
    assert status.sqlite_vec_version == "v0.1.9"

    with closing(vector_store._connect(isolated_index)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
        assert metadata["index_schema"] == vector_store.INDEX_SCHEMA
        assert metadata["schema_version"] == str(vector_store.INDEX_SCHEMA_VERSION)
        assert metadata["model_id"] == embeddings.MODEL_ID
        assert metadata["model_revision"] == embeddings.MODEL_REVISION
        assert metadata["embedding_dimension"] == str(embeddings.EMBEDDING_DIMENSION)
        assert len(metadata["corpus_hash"]) == 64
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'rag_vectors'"
        ).fetchone()[0]
        assert "vec0" in sql
        rows = connection.execute("SELECT embedding FROM rag_vectors").fetchall()
        assert len(rows) == 36
        assert all(len(bytes(row[0])) == embeddings.EMBEDDING_DIMENSION * 4 for row in rows)


def test_successful_rebuild_atomically_replaces_index(isolated_index) -> None:
    vector_store.rebuild_index(embedder=FakeEmbedder("old"))
    old_bytes = isolated_index.read_bytes()
    vector_store.rebuild_index(embedder=FakeEmbedder("new"))
    assert isolated_index.read_bytes() != old_bytes
    assert not list(isolated_index.parent.glob(".rag_vectors-*.sqlite.tmp"))
    assert vector_store.check_index().compatible


def test_controlled_validation_failure_preserves_previous_index(
    isolated_index,
    monkeypatch,
) -> None:
    vector_store.rebuild_index(embedder=FakeEmbedder("old"))
    old_bytes = isolated_index.read_bytes()

    def fail_validation(path, chunks):
        raise vector_store.VectorStoreError("controlled validation failure")

    monkeypatch.setattr(vector_store, "_validate_built_index", fail_validation)
    with pytest.raises(vector_store.VectorStoreError, match="controlled"):
        vector_store.rebuild_index(embedder=FakeEmbedder("new"))
    assert isolated_index.read_bytes() == old_bytes
    assert not list(isolated_index.parent.glob(".rag_vectors-*.sqlite.tmp"))


@pytest.mark.parametrize("key", ["corpus_hash", "model_id", "model_revision"])
def test_check_detects_stale_corpus_and_model_metadata(isolated_index, key) -> None:
    vector_store.rebuild_index(embedder=FakeEmbedder())
    with closing(vector_store._connect(isolated_index)) as connection:
        connection.execute(
            "UPDATE index_metadata SET value = 'stale' WHERE key = ?",
            (key,),
        )
        connection.commit()
    status = vector_store.check_index()
    assert not status.compatible
    assert f"metadata mismatch: {key}" in status.issues


def test_dense_search_has_stable_ties_and_json_safe_contract(isolated_index) -> None:
    embedder = ConstantEmbedder()
    vector_store.rebuild_index(embedder=embedder)
    results = vector_store.dense_search("dowolne pytanie", 5, embedder=embedder)
    expected_ids = sorted(chunk.chunk_id for chunk in indexer.build_corpus())[:5]
    assert [result["chunk_id"] for result in results] == expected_ids
    assert [result["rank"] for result in results] == [1, 2, 3, 4, 5]
    assert all(result["distance"] == 0.0 for result in results)
    assert all(result["score"] == 1.0 for result in results)
    assert all(isinstance(result["headings"], list) for result in results)
    assert all(isinstance(result["refs"], list) for result in results)
    json.dumps(results, ensure_ascii=False, allow_nan=False)


def test_dense_search_rejects_missing_or_stale_index(isolated_index) -> None:
    with pytest.raises(vector_store.StaleIndexError, match="missing or stale"):
        vector_store.dense_search("osłona", embedder=FakeEmbedder())


def test_public_apis_and_clis_accept_no_paths_extensions_or_model_ids() -> None:
    assert list(inspect.signature(vector_store.rebuild_index).parameters) == ["embedder"]
    assert list(inspect.signature(vector_store.check_index).parameters) == []
    assert list(inspect.signature(vector_store.dense_search).parameters) == [
        "query",
        "limit",
        "embedder",
    ]
    assert list(inspect.signature(embeddings.download_model).parameters) == []
    with pytest.raises(SystemExit):
        vector_store.main(["rebuild", "--path", "outside.sqlite"])
    with pytest.raises(SystemExit):
        vector_store.main(["check", "--extension", "outside.dll"])
    with pytest.raises(SystemExit):
        embeddings.main(["--model-id", "other/model"])
    source = inspect.getsource(vector_store._connect)
    assert "sqlite_vec.load(connection)" in source
    assert "connection.load_extension" not in source


def test_clis_contain_optional_dependency_errors(monkeypatch, capsys) -> None:
    def fail_model():
        raise embeddings.EmbeddingError("model unavailable")

    monkeypatch.setattr(embeddings, "download_model", fail_model)
    assert embeddings.main([]) == 1
    assert capsys.readouterr().err.strip() == "model unavailable"

    def fail_rebuild(*, embedder=None):
        raise embeddings.EmbeddingError("offline cache unavailable")

    monkeypatch.setattr(vector_store, "rebuild_index", fail_rebuild)
    assert vector_store.main(["rebuild"]) == 1
    assert capsys.readouterr().err.strip() == "offline cache unavailable"


def test_fixed_paths_reject_monkeypatched_escape(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(vector_store, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        vector_store,
        "DEFAULT_INDEX_PATH",
        tmp_path / "outside" / "rag_vectors.sqlite",
    )
    with pytest.raises(vector_store.VectorStoreError, match="fixed project"):
        vector_store.check_index()

    monkeypatch.setattr(embeddings, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        embeddings,
        "MODEL_CACHE_DIR",
        tmp_path / "outside" / "models",
    )
    with pytest.raises(embeddings.EmbeddingError, match="fixed project"):
        embeddings._fixed_model_cache_dir()


def test_importing_mcp_server_does_not_import_heavy_ml_stack() -> None:
    script = """
import sys
import mcp_server.server
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
