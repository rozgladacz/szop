"""Determinism, safety, and evaluation coverage for the C2.1 corpus."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mcp_server import evaluation, indexer


@pytest.fixture(scope="module")
def corpus() -> tuple[indexer.CorpusChunk, ...]:
    return indexer.build_corpus()


def test_manifest_is_byte_deterministic_and_stably_ordered(corpus) -> None:
    second = indexer.build_corpus()
    assert corpus == second
    assert indexer.render_manifest(corpus) == indexer.render_manifest(second)
    source_order = [chunk.source_key for chunk in corpus]
    assert source_order == sorted(source_order, key=("rules", "abilities").index)
    for source_key in ("rules", "abilities"):
        ordinals = [chunk.ordinal for chunk in corpus if chunk.source_key == source_key]
        assert ordinals == list(range(1, len(ordinals) + 1))


def test_manifest_jsonl_round_trip(corpus) -> None:
    payload = indexer.render_manifest(corpus)
    assert payload.endswith(b"\n")
    records = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    assert len(records) == len(corpus)
    assert all(record["schema"] == indexer.CORPUS_SCHEMA for record in records)


def test_chunk_ids_and_content_hashes_are_unique_and_valid(corpus) -> None:
    ids = [chunk.chunk_id for chunk in corpus]
    hashes = [chunk.content_hash for chunk in corpus]
    assert len(ids) == len(set(ids))
    assert len(hashes) == len(set(hashes))
    for chunk in corpus:
        assert chunk.content_hash == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()


def test_corpus_contains_both_allowlisted_sources(corpus) -> None:
    assert {chunk.source for chunk in corpus} == {
        "SZOP_Rozjemca.md",
        "SZOP_Zdolnosci.md",
    }


def test_headers_and_detectable_references_are_preserved(corpus) -> None:
    rules = next(chunk for chunk in corpus if "Oddział wskazuje od jednego" in chunk.text)
    assert any(heading.startswith("pkt 14 —") for heading in rules.headings)
    assert "pkt 14.d.i" in rules.refs

    abilities = next(chunk for chunk in corpus if "### 1. Bastion" in chunk.text)
    assert "SZOP — Zdolności" in abilities.headings
    assert "Pasywne" in abilities.headings
    assert "1. Bastion" in abilities.headings
    assert "ability:1" in abilities.refs


def test_chunk_sizes_and_exact_overlap_follow_documented_tolerances(corpus) -> None:
    by_source: dict[str, list[indexer.CorpusChunk]] = {}
    for chunk in corpus:
        assert indexer.MIN_CHUNK_WORDS <= chunk.word_count <= indexer.MAX_CHUNK_WORDS
        by_source.setdefault(chunk.source_key, []).append(chunk)

    for chunks in by_source.values():
        assert chunks[0].overlap_words == 0
        for previous, current in zip(chunks, chunks[1:]):
            assert current.overlap_words == indexer.OVERLAP_WORDS
            previous_words = indexer._WORD_RE.findall(previous.text)
            current_words = indexer._WORD_RE.findall(current.text)
            assert previous_words[-indexer.OVERLAP_WORDS :] == current_words[: indexer.OVERLAP_WORDS]


def test_long_semantic_ability_is_not_mechanically_split(corpus) -> None:
    chunks = [chunk for chunk in corpus if "35. Transport(X)" in chunk.headings]
    assert len(chunks) == 1
    assert "### 35. Transport(X)" in chunks[0].text
    assert "bazowy: X ×" in chunks[0].text


def test_invalid_utf8_and_invalid_source_selector_are_rejected() -> None:
    with pytest.raises(indexer.CorpusEncodingError):
        indexer.decode_source_bytes("rules", b"\xff")
    with pytest.raises(indexer.CorpusError):
        indexer.load_canonical_source("../../secret.txt")
    with pytest.raises(indexer.CorpusError):
        indexer.load_canonical_source(Path("SZOP_Rozjemca.md"))  # type: ignore[arg-type]


def test_public_commands_accept_no_path_arguments() -> None:
    assert not inspect.signature(indexer.build_corpus).parameters
    assert "path" not in inspect.signature(indexer.write_manifest).parameters
    assert "path" not in inspect.signature(evaluation.load_evaluation_cases).parameters
    with pytest.raises(SystemExit):
        indexer.main(["--input", "outside.md"])
    with pytest.raises(SystemExit):
        evaluation.main(["--evaluation", "outside.jsonl"])


def test_manifest_writer_uses_only_fixed_build_location(corpus, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(indexer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        indexer,
        "DEFAULT_MANIFEST_PATH",
        tmp_path / "build" / "rag_corpus.jsonl",
    )
    output = indexer.write_manifest(corpus)
    assert output == tmp_path / "build" / "rag_corpus.jsonl"
    assert output.read_bytes() == indexer.render_manifest(corpus)


def test_manifest_writer_rejects_output_outside_project(corpus, tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(indexer, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        indexer,
        "DEFAULT_MANIFEST_PATH",
        tmp_path / "outside" / "rag_corpus.jsonl",
    )
    with pytest.raises(indexer.CorpusError, match="fixed project build directory"):
        indexer.write_manifest(corpus)


def test_modules_have_no_runtime_orm_or_db_imports() -> None:
    for module in (indexer, evaluation):
        source = Path(module.__file__).read_text(encoding="utf-8").casefold()
        assert "sqlalchemy" not in source
        assert "app.models" not in source
        assert "app.database" not in source


def test_evaluation_set_has_exact_schema_unique_ids_and_both_sources() -> None:
    cases = evaluation.load_evaluation_cases()
    assert len(cases) == evaluation.EXPECTED_EVALUATION_COUNT == 30
    assert len({case.case_id for case in cases}) == 30
    assert {case.expected.source for case in cases} == {
        "SZOP_Rozjemca.md",
        "SZOP_Zdolnosci.md",
    }
    assert all(case.query and case.expected.ref and case.expected.anchor for case in cases)


def test_all_evaluation_anchors_are_covered(corpus) -> None:
    report = evaluation.validate_evaluation(chunks=corpus)
    assert report.covered == report.total == 30


def test_evaluation_parser_rejects_encoding_schema_and_invalid_count(corpus) -> None:
    with pytest.raises(evaluation.EvaluationError, match="UTF-8"):
        evaluation.parse_evaluation_jsonl(b"\xff")
    with pytest.raises(evaluation.EvaluationError, match="record schema"):
        evaluation.parse_evaluation_jsonl(b'{"id":"x"}\n')
    cases = evaluation.load_evaluation_cases()
    with pytest.raises(evaluation.EvaluationError, match="exactly 30"):
        evaluation.validate_evaluation(cases=cases[:-1], chunks=corpus)


def test_evaluation_rejects_duplicate_ids_and_uncovered_anchor(corpus) -> None:
    cases = list(evaluation.load_evaluation_cases())
    cases[1] = replace(cases[1], case_id=cases[0].case_id)
    with pytest.raises(evaluation.EvaluationError, match="ids must be unique"):
        evaluation.validate_evaluation(cases=cases, chunks=corpus)

    cases = list(evaluation.load_evaluation_cases())
    cases[0] = replace(
        cases[0],
        expected=replace(cases[0].expected, anchor="anchor that cannot exist"),
    )
    with pytest.raises(evaluation.EvaluationError, match="eval-rules-001"):
        evaluation.validate_evaluation(cases=cases, chunks=corpus)
