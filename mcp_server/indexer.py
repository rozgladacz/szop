"""Deterministic, offline corpus builder for the canonical SZOP sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DOCS_DIR = PROJECT_ROOT / "app" / "static" / "docs"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "build" / "rag_corpus.jsonl"

CORPUS_SCHEMA = "szop.rag_corpus/v1"
CORPUS_VERSION = 1
TARGET_WORDS = 300
OVERLAP_WORDS = 50
MIN_CHUNK_WORDS = 180
MAX_CHUNK_WORDS = 450
MAX_SEMANTIC_BLOCK_WORDS = 400
_NEW_CONTENT_TARGET = TARGET_WORDS - OVERLAP_WORDS
_MIN_NEW_CONTENT_WORDS = MIN_CHUNK_WORDS - OVERLAP_WORDS

SourceKind = Literal["numbered_rules", "markdown_sections"]


class CorpusError(ValueError):
    """Base error for invalid corpus inputs or invariants."""


class CorpusEncodingError(CorpusError):
    """A canonical source is not valid UTF-8."""


@dataclass(frozen=True)
class CanonicalSource:
    key: str
    filename: str
    kind: SourceKind


CANONICAL_SOURCES: tuple[CanonicalSource, ...] = (
    CanonicalSource("rules", "SZOP_Rozjemca.md", "numbered_rules"),
    CanonicalSource("abilities", "SZOP_Zdolnosci.md", "markdown_sections"),
)
_SOURCES_BY_KEY = {source.key: source for source in CANONICAL_SOURCES}


@dataclass(frozen=True)
class SemanticBlock:
    headings: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    source_key: str
    source: str
    ordinal: int
    headings: tuple[str, ...]
    refs: tuple[str, ...]
    text: str
    word_count: int
    new_word_count: int
    overlap_words: int
    content_hash: str

    def to_record(self) -> dict[str, object]:
        return {
            "schema": CORPUS_SCHEMA,
            "version": CORPUS_VERSION,
            "id": self.chunk_id,
            "source_key": self.source_key,
            "source": self.source,
            "ordinal": self.ordinal,
            "headings": list(self.headings),
            "refs": list(self.refs),
            "word_count": self.word_count,
            "new_word_count": self.new_word_count,
            "overlap_words": self.overlap_words,
            "content_hash": self.content_hash,
            "text": self.text,
        }


_WORD_RE = re.compile(r"\S+")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_TOP_RULE_RE = re.compile(r"^([0-9]+)\.[\t ]+(\S.*)$")
_RULE_LABEL_RE = re.compile(r"^([0-9]+|[a-z]+)\.[\t ]+(\S.*)$")
_INLINE_POINT_RE = re.compile(
    r"\bpkt\.?\s*([0-9]+(?:\s*\.\s*[a-z]+){0,2})",
    re.IGNORECASE,
)
_ABILITY_HEADING_RE = re.compile(r"^([0-9]+)\.\s+")


def count_words(text: str) -> int:
    """Count whitespace-delimited tokens used by the documented tolerances."""
    return len(_WORD_RE.findall(text))


def decode_source_bytes(source_key: str, data: bytes) -> str:
    """Strictly decode bytes for an allowlisted source key."""
    source = _require_source(source_key)
    if not isinstance(data, bytes):
        raise CorpusError("source data must be bytes")
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CorpusEncodingError(
            f"canonical source {source.filename} is not valid UTF-8"
        ) from exc


def load_canonical_source(source_key: str) -> str:
    """Read one fixed source; callers can select a key, never a filesystem path."""
    source = _require_source(source_key)
    path = _canonical_source_path(source)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CorpusError(f"cannot read canonical source {source.filename}") from exc
    return decode_source_bytes(source.key, data)


def build_corpus() -> tuple[CorpusChunk, ...]:
    """Build the complete corpus in fixed source and chunk order."""
    chunks: list[CorpusChunk] = []
    for source in CANONICAL_SOURCES:
        text = load_canonical_source(source.key)
        chunks.extend(_chunk_source(source, text))
    _validate_chunks(chunks)
    return tuple(chunks)


def render_manifest(chunks: Sequence[CorpusChunk] | None = None) -> bytes:
    """Render canonical JSONL bytes with stable keys, separators, and LF endings."""
    selected = tuple(chunks) if chunks is not None else build_corpus()
    _validate_chunks(selected)
    lines = [
        json.dumps(
            chunk.to_record(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for chunk in selected
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_manifest(chunks: Sequence[CorpusChunk] | None = None) -> Path:
    """Write only the fixed gitignored build artifact; no output path is accepted."""
    output = _fixed_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_manifest(chunks))
    return output


def _require_source(source_key: str) -> CanonicalSource:
    if not isinstance(source_key, str) or source_key not in _SOURCES_BY_KEY:
        allowed = ", ".join(source.key for source in CANONICAL_SOURCES)
        raise CorpusError(f"source must be one of: {allowed}")
    return _SOURCES_BY_KEY[source_key]


def _canonical_source_path(source: CanonicalSource) -> Path:
    docs_dir = CANONICAL_DOCS_DIR.resolve(strict=True)
    path = (docs_dir / source.filename).resolve(strict=True)
    if path.parent != docs_dir:
        raise CorpusError(f"canonical source escapes allowlisted directory: {source.filename}")
    return path


def _fixed_output_path() -> Path:
    project_root = PROJECT_ROOT.resolve(strict=True)
    expected_parent = (project_root / "build").resolve(strict=False)
    actual_parent = DEFAULT_MANIFEST_PATH.parent.resolve(strict=False)
    if not expected_parent.is_relative_to(project_root):
        raise CorpusError("manifest build directory escapes the project root")
    if actual_parent != expected_parent:
        raise CorpusError("manifest output must remain the fixed project build directory")
    return actual_parent / "rag_corpus.jsonl"


def _chunk_source(source: CanonicalSource, text: str) -> list[CorpusChunk]:
    if not isinstance(text, str) or not text.strip():
        raise CorpusError(f"canonical source {source.filename} is empty")
    if source.kind == "numbered_rules":
        blocks = _numbered_rule_blocks(text)
    else:
        blocks = _markdown_blocks(text)
    groups = _pack_semantic_blocks(blocks)
    return _render_chunks(source, groups)


def _numbered_rule_blocks(text: str) -> list[SemanticBlock]:
    blocks: list[SemanticBlock] = []
    current: list[str] = []
    heading = ""

    def flush() -> None:
        if current:
            block_text = "\n".join(current).strip()
            if block_text:
                blocks.append(SemanticBlock((heading,), block_text))

    for line in text.splitlines():
        match = _TOP_RULE_RE.match(line)
        if match:
            flush()
            current = [line]
            heading = f"pkt {match.group(1)} — {match.group(2).strip()}"
        elif current:
            current.append(line)
        elif line.strip():
            raise CorpusError("numbered rules contain text before the first top-level point")
    flush()
    if not blocks:
        raise CorpusError("numbered rules contain no top-level points")
    return blocks


def _markdown_blocks(text: str) -> list[SemanticBlock]:
    blocks: list[SemanticBlock] = []
    current: list[str] = []
    heading_path: dict[int, str] = {}

    def flush() -> None:
        if current:
            block_text = "\n".join(current).strip()
            if block_text:
                headings = tuple(
                    heading_path[level]
                    for level in sorted(heading_path)
                )
                blocks.append(SemanticBlock(headings, block_text))

    for line in text.splitlines():
        match = _MARKDOWN_HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            for stale_level in [item for item in heading_path if item >= level]:
                del heading_path[stale_level]
            heading_path[level] = match.group(2).strip()
            current = [line]
        else:
            current.append(line)
    flush()
    if not blocks:
        raise CorpusError("markdown source contains no semantic blocks")
    return blocks


def _split_oversized_block(block: SemanticBlock) -> list[SemanticBlock]:
    """Use paragraph boundaries first; split words only for an oversized paragraph."""
    if count_words(block.text) <= MAX_SEMANTIC_BLOCK_WORDS:
        return [block]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", block.text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        words = _WORD_RE.findall(paragraph)
        if len(words) <= MAX_SEMANTIC_BLOCK_WORDS:
            units.append(paragraph)
            continue
        for offset in range(0, len(words), MAX_SEMANTIC_BLOCK_WORDS):
            units.append(" ".join(words[offset : offset + MAX_SEMANTIC_BLOCK_WORDS]))

    split_blocks: list[SemanticBlock] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        unit_words = count_words(unit)
        if current and current_words + unit_words > MAX_SEMANTIC_BLOCK_WORDS:
            split_blocks.append(SemanticBlock(block.headings, "\n\n".join(current)))
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
    if current:
        split_blocks.append(SemanticBlock(block.headings, "\n\n".join(current)))
    return split_blocks


def _pack_semantic_blocks(blocks: Sequence[SemanticBlock]) -> list[list[SemanticBlock]]:
    expanded = [part for block in blocks for part in _split_oversized_block(block)]
    groups: list[list[SemanticBlock]] = []
    current: list[SemanticBlock] = []
    current_words = 0

    for block in expanded:
        block_words = count_words(block.text)
        should_flush = bool(current) and (
            current_words >= _NEW_CONTENT_TARGET
            or current_words + block_words > MAX_SEMANTIC_BLOCK_WORDS
        )
        if should_flush:
            groups.append(current)
            current = []
            current_words = 0
        current.append(block)
        current_words += block_words
    if current:
        groups.append(current)

    _rebalance_short_groups(groups)
    return groups


def _rebalance_short_groups(groups: list[list[SemanticBlock]]) -> None:
    """Merge undersized new-content groups without splitting semantic blocks."""
    index = 1
    while index < len(groups):
        current_words = _group_word_count(groups[index])
        if current_words >= _MIN_NEW_CONTENT_WORDS:
            index += 1
            continue

        if index + 1 < len(groups):
            next_words = _group_word_count(groups[index + 1])
            if current_words + next_words <= MAX_SEMANTIC_BLOCK_WORDS:
                groups[index].extend(groups[index + 1])
                groups.pop(index + 1)
                continue

        previous = groups[index - 1]
        while len(previous) > 1 and current_words < _MIN_NEW_CONTENT_WORDS:
            candidate = previous[-1]
            candidate_words = count_words(candidate.text)
            remaining_words = _group_word_count(previous[:-1])
            if current_words + candidate_words > MAX_SEMANTIC_BLOCK_WORDS:
                break
            if remaining_words < _MIN_NEW_CONTENT_WORDS:
                break
            previous.pop()
            groups[index].insert(0, candidate)
            current_words += candidate_words
        if current_words >= _MIN_NEW_CONTENT_WORDS:
            index += 1
            continue

        previous_words = _group_word_count(previous)
        if previous_words + current_words <= MAX_SEMANTIC_BLOCK_WORDS:
            previous.extend(groups[index])
            groups.pop(index)
            continue
        index += 1


def _group_word_count(group: Sequence[SemanticBlock]) -> int:
    return sum(count_words(block.text) for block in group)


def _render_chunks(
    source: CanonicalSource,
    groups: Sequence[Sequence[SemanticBlock]],
) -> list[CorpusChunk]:
    chunks: list[CorpusChunk] = []
    previous_new_text = ""
    for ordinal, group in enumerate(groups, start=1):
        new_text = "\n\n".join(block.text for block in group).strip()
        overlap = ""
        overlap_count = 0
        if previous_new_text:
            previous_words = _WORD_RE.findall(previous_new_text)
            overlap_words = previous_words[-OVERLAP_WORDS:]
            overlap = " ".join(overlap_words)
            overlap_count = len(overlap_words)
        text = f"{overlap}\n\n{new_text}" if overlap else new_text
        headings = _unique_in_order(
            heading
            for block in group
            for heading in block.headings
        )
        refs = _extract_refs(source, new_text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks.append(
            CorpusChunk(
                chunk_id=f"c2.1-{source.key}-{ordinal:04d}",
                source_key=source.key,
                source=source.filename,
                ordinal=ordinal,
                headings=headings,
                refs=refs,
                text=text,
                word_count=count_words(text),
                new_word_count=count_words(new_text),
                overlap_words=overlap_count,
                content_hash=content_hash,
            )
        )
        previous_new_text = new_text
    return chunks


def _extract_refs(source: CanonicalSource, text: str) -> tuple[str, ...]:
    refs: list[str] = []
    if source.kind == "numbered_rules":
        top_ref: str | None = None
        letter_ref: str | None = None
        for line in text.splitlines():
            stripped = line.lstrip("\t")
            depth = len(line) - len(stripped)
            match = _RULE_LABEL_RE.match(stripped)
            if match is None:
                continue
            label = match.group(1).casefold()
            if depth == 0 and label.isdigit():
                top_ref = label
                letter_ref = None
                refs.append(f"pkt {top_ref}")
            elif depth == 1 and top_ref is not None:
                letter_ref = f"{top_ref}.{label}"
                refs.append(f"pkt {letter_ref}")
            elif depth == 2 and letter_ref is not None:
                refs.append(f"pkt {letter_ref}.{label}")
        for match in _INLINE_POINT_RE.finditer(text):
            normalized = re.sub(r"\s+", "", match.group(1)).casefold()
            refs.append(f"pkt {normalized}")
    else:
        for line in text.splitlines():
            heading_match = _MARKDOWN_HEADING_RE.match(line)
            if heading_match is None or len(heading_match.group(1)) != 3:
                continue
            ability_match = _ABILITY_HEADING_RE.match(heading_match.group(2))
            if ability_match:
                refs.append(f"ability:{ability_match.group(1)}")
    return _unique_in_order(refs)


def _unique_in_order(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _validate_chunks(chunks: Sequence[CorpusChunk]) -> None:
    if not chunks:
        raise CorpusError("corpus must contain at least one chunk")
    ids = [chunk.chunk_id for chunk in chunks]
    hashes = [chunk.content_hash for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise CorpusError("chunk ids must be unique")
    if len(hashes) != len(set(hashes)):
        raise CorpusError("chunk content hashes must be unique")
    for chunk in chunks:
        expected_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        if chunk.content_hash != expected_hash:
            raise CorpusError(f"invalid content hash for {chunk.chunk_id}")
        if not MIN_CHUNK_WORDS <= chunk.word_count <= MAX_CHUNK_WORDS:
            raise CorpusError(
                f"chunk {chunk.chunk_id} has {chunk.word_count} words; "
                f"expected {MIN_CHUNK_WORDS}-{MAX_CHUNK_WORDS}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic C2.1 corpus from fixed canonical SZOP sources.",
    )
    parser.parse_args(argv)
    chunks = build_corpus()
    output = write_manifest(chunks)
    print(
        f"Wrote {len(chunks)} deterministic chunks from "
        f"{len(CANONICAL_SOURCES)} sources to {output.relative_to(PROJECT_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
