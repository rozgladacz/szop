"""C2.3 sqlite-vec persistence, atomicity, and offline API boundaries."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest

from mcp_server import embeddings, indexer, search as rag_search, vector_store


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


def test_importing_mcp_modules_does_not_import_heavy_ml_stack() -> None:
    script = """
import sys
import mcp_server.server
import mcp_server.search
import mcp_server.vector_store
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


def test_default_dense_and_hybrid_calls_reuse_one_embedder_without_ranking_drift(
    isolated_index,
    monkeypatch,
) -> None:
    injected = FakeEmbedder()
    vector_store.rebuild_index(embedder=injected)
    query = "dowolne pytanie"
    expected_dense = vector_store.dense_search(query, 5, embedder=injected)
    expected_hybrid = rag_search._fuse_ranked_results(
        rag_search.search(query, rag_search.HYBRID_CANDIDATE_LIMIT),
        expected_dense,
        limit=5,
        chunks=indexer.build_corpus(),
    )
    constructions = 0

    class DefaultFakeEmbedder(FakeEmbedder):
        def __init__(self) -> None:
            nonlocal constructions
            constructions += 1
            super().__init__()

    monkeypatch.setattr(embeddings, "_default_embedder", None)
    monkeypatch.setattr(
        embeddings,
        "SentenceTransformerEmbedder",
        DefaultFakeEmbedder,
    )

    assert vector_store.dense_search(query, 5) == expected_dense
    assert vector_store.dense_search(query, 5) == expected_dense
    assert rag_search.hybrid_search(query, 5) == expected_hybrid
    assert rag_search.hybrid_search(query, 5) == expected_hybrid
    assert constructions == 1


def test_explicit_embedder_injection_bypasses_default_singleton(
    isolated_index,
    monkeypatch,
) -> None:
    def unexpected_default():
        raise AssertionError("default singleton must not be used")

    monkeypatch.setattr(vector_store, "get_default_embedder", unexpected_default)
    embedder = FakeEmbedder()
    vector_store.rebuild_index(embedder=embedder)
    assert vector_store.dense_search("osłona", embedder=embedder)


def test_concurrent_first_use_loads_model_once_and_serializes_encode(
    tmp_path,
    monkeypatch,
) -> None:
    constructor_calls = 0
    active_encodes = 0
    max_active_encodes = 0
    counter_lock = threading.Lock()
    constructor_kwargs: dict[str, object] = {}

    class FakeModel:
        def get_embedding_dimension(self) -> int:
            return embeddings.EMBEDDING_DIMENSION

        def encode(self, texts, **kwargs):
            nonlocal active_encodes, max_active_encodes
            with counter_lock:
                active_encodes += 1
                max_active_encodes = max(max_active_encodes, active_encodes)
            try:
                time.sleep(0.01)
                vector = (1.0,) + (0.0,) * (embeddings.EMBEDDING_DIMENSION - 1)
                return tuple(vector for _ in texts)
            finally:
                with counter_lock:
                    active_encodes -= 1

    def construct_model(model_id, **kwargs):
        nonlocal constructor_calls
        with counter_lock:
            constructor_calls += 1
            constructor_kwargs.update(kwargs)
        time.sleep(0.02)
        assert model_id == embeddings.MODEL_ID
        return FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=construct_model),
    )
    monkeypatch.setattr(embeddings, "_fixed_model_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(embeddings, "_default_embedder", None)
    barrier = threading.Barrier(6)

    def embed_once(number: int):
        barrier.wait()
        return embeddings.get_default_embedder().embed((f"query {number}",))

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(embed_once, range(6)))

    assert len(results) == 6
    assert constructor_calls == 1
    assert max_active_encodes == 1
    assert constructor_kwargs == {
        "revision": embeddings.MODEL_REVISION,
        "cache_folder": str(tmp_path),
        "local_files_only": True,
        "device": "cpu",
        "trust_remote_code": False,
        "token": False,
        "backend": "torch",
    }


def test_failed_model_load_can_retry_without_poisoning_default_cache(
    tmp_path,
    monkeypatch,
) -> None:
    attempts = 0

    class FakeModel:
        def get_embedding_dimension(self) -> int:
            return embeddings.EMBEDDING_DIMENSION

        def encode(self, texts, **kwargs):
            vector = (1.0,) + (0.0,) * (embeddings.EMBEDDING_DIMENSION - 1)
            return tuple(vector for _ in texts)

    def construct_model(model_id, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("controlled first-load failure")
        return FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=construct_model),
    )
    monkeypatch.setattr(embeddings, "_fixed_model_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(embeddings, "_default_embedder", None)
    provider = embeddings.get_default_embedder()

    with pytest.raises(embeddings.EmbeddingError, match="offline mode"):
        provider.embed(("first",))
    assert provider._model is None
    assert provider.embed(("second",))
    assert embeddings.get_default_embedder() is provider
    assert attempts == 2


def test_download_path_is_separate_from_offline_singleton(tmp_path, monkeypatch) -> None:
    instances = []

    class RecordingEmbedder(FakeEmbedder):
        def __init__(self, *, allow_download: bool = False) -> None:
            super().__init__()
            self.allow_download = allow_download
            instances.append(self)

    monkeypatch.setattr(embeddings, "_default_embedder", None)
    monkeypatch.setattr(embeddings, "SentenceTransformerEmbedder", RecordingEmbedder)
    monkeypatch.setattr(embeddings, "_fixed_model_cache_dir", lambda: tmp_path)

    offline = embeddings.get_default_embedder()
    assert embeddings.download_model() == tmp_path
    assert embeddings.get_default_embedder() is offline
    assert [instance.allow_download for instance in instances] == [False, True]
    assert instances[0] is not instances[1]
