"""Canonical, bounded structural lookup over the SZOP rules markdown."""

from __future__ import annotations

import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from app.paths import STATIC_DIR

DEFAULT_RULES_PATH = STATIC_DIR / "docs" / "SZOP_Rozjemca.md"
RULE_LOOKUP_SCHEMA = "szop.lookup_rule/v1"
RULE_LOOKUP_VERSION = 1
RULE_SOURCE = "SZOP_Rozjemca.md"
MAX_RULE_QUERY_LENGTH = 200
MAX_RULE_RESULTS = 10
MAX_RULE_TEXT_LENGTH = 4000
MAX_RULE_CHILDREN = 20

_POINT_RE = re.compile(r"^([0-9]+|[a-z]+)\.[\t ]+(\S.*)$")
_REFERENCE_QUERY_RE = re.compile(
    r"^(?:pkt\.?\s*)?[0-9]+(?:\s*\.\s*[a-z]+){0,2}\.?$",
    re.IGNORECASE,
)


@dataclass
class RuleNode:
    """One numbered rule point from the canonical document."""

    ref: str
    label: str
    text: str
    parent_ref: str | None
    depth: int
    children: list[str] = field(default_factory=list)


def parse_rules(text: str) -> dict[str, RuleNode]:
    """Parse the hierarchical numbering used by ``SZOP_Rozjemca.md``."""
    nodes: dict[str, RuleNode] = {}
    last_top: str | None = None
    last_letter_ref: str | None = None
    current_ref: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip("\t")
        depth = len(line) - len(stripped)
        match = _POINT_RE.match(stripped)

        if match is None or depth > 2:
            if current_ref is not None:
                node = nodes[current_ref]
                continuation = _clean_text(stripped)
                node.text = (
                    f"{node.text}\n{continuation}" if continuation else node.text
                )
            continue

        label, body = match.group(1), _clean_text(match.group(2))
        if depth == 0:
            ref = label
            parent_ref = None
            last_top = ref
            last_letter_ref = None
        elif depth == 1:
            if last_top is None:
                continue
            ref = f"{last_top}.{label}"
            parent_ref = last_top
            last_letter_ref = ref
        else:
            if last_letter_ref is None:
                continue
            ref = f"{last_letter_ref}.{label}"
            parent_ref = last_letter_ref

        nodes[ref] = RuleNode(
            ref=ref,
            label=label,
            text=body,
            parent_ref=parent_ref,
            depth=depth,
        )
        if parent_ref is not None and parent_ref in nodes:
            nodes[parent_ref].children.append(ref)
        current_ref = ref

    return nodes


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\t", " ")).strip()


def normalize_ref(query: str) -> str:
    """Normalize ``pkt 14.D.IV`` to ``14.d.iv``."""
    text = query.strip().casefold()
    text = re.sub(r"^pkt\.?\s*", "", text)
    text = text.strip().strip(".")
    return re.sub(r"\s+", "", text)


def resolve_ref(nodes: dict[str, RuleNode], query: str) -> RuleNode | None:
    return nodes.get(normalize_ref(query))


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value.translate(str.maketrans({"ł": "l", "Ł": "L"})),
    )
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return without_marks.casefold()


def search_rules(
    nodes: dict[str, RuleNode],
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[RuleNode, int]]:
    """Return points containing all folded query tokens, ranked by occurrences."""
    tokens = [_fold(token) for token in query.split() if token.strip()]
    if not tokens:
        return []

    matches: list[tuple[int, int, RuleNode]] = []
    for index, node in enumerate(nodes.values()):
        folded = _fold(node.text)
        if not all(token in folded for token in tokens):
            continue
        score = sum(folded.count(token) for token in tokens)
        matches.append((-score, index, node))

    matches.sort()
    return [
        (node, -negative_score)
        for negative_score, _index, node in matches[:limit]
    ]


def node_to_json(node: RuleNode) -> dict:
    return {
        "ref": node.ref,
        "text": node.text,
        "children": list(node.children),
    }


def resolve_to_json(nodes: dict[str, RuleNode], node: RuleNode) -> dict:
    """Preserve the leaf-CLI exact-result contract."""
    parents: list[dict[str, str]] = []
    parent_ref = node.parent_ref
    while parent_ref is not None and parent_ref in nodes:
        parent = nodes[parent_ref]
        parents.append({"ref": parent.ref, "text": parent.text})
        parent_ref = parent.parent_ref
    parents.reverse()
    children = [
        node_to_json(nodes[ref])
        for ref in node.children
        if ref in nodes
    ]
    return {
        "schema": RULE_LOOKUP_SCHEMA,
        "version": RULE_LOOKUP_VERSION,
        "ref": node.ref,
        "text": node.text,
        "parents": parents,
        "children": children,
    }


def load_rules(path: pathlib.Path = DEFAULT_RULES_PATH) -> dict[str, RuleNode]:
    return parse_rules(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_canonical_rules() -> dict[str, RuleNode]:
    """Load the fixed canonical source; no caller-controlled path is accepted."""
    return load_rules(DEFAULT_RULES_PATH)


def lookup_rule_payload(query: str, *, limit: int = 5) -> dict:
    """Build the stable public lookup payload from the canonical source."""
    normalized_query = _validate_query(query)
    if type(limit) is not int or not 1 <= limit <= MAX_RULE_RESULTS:
        raise ValueError(f"limit must be an int between 1 and {MAX_RULE_RESULTS}")

    nodes = load_canonical_rules()
    if _REFERENCE_QUERY_RE.fullmatch(normalized_query):
        mode = "reference"
        node = resolve_ref(nodes, normalized_query)
        matches = [] if node is None else [_public_match(nodes, node, score=None)]
        normalized = normalize_ref(normalized_query)
    else:
        mode = "search"
        results = search_rules(nodes, normalized_query, limit=limit)
        matches = [
            _public_match(nodes, node, score=score)
            for node, score in results
        ]
        normalized = _fold(normalized_query)

    return {
        "schema": RULE_LOOKUP_SCHEMA,
        "version": RULE_LOOKUP_VERSION,
        "source": RULE_SOURCE,
        "query": normalized_query,
        "normalized_query": normalized,
        "mode": mode,
        "matches": matches,
    }


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > MAX_RULE_QUERY_LENGTH:
        raise ValueError(
            f"query must contain at most {MAX_RULE_QUERY_LENGTH} characters"
        )
    return normalized


def _bounded_text(text: str) -> str:
    if len(text) <= MAX_RULE_TEXT_LENGTH:
        return text
    return text[: MAX_RULE_TEXT_LENGTH - 1].rstrip() + "…"


def _parents_to_json(
    nodes: dict[str, RuleNode],
    node: RuleNode,
) -> list[dict[str, str]]:
    parents: list[dict[str, str]] = []
    parent_ref = node.parent_ref
    while parent_ref is not None and parent_ref in nodes:
        parent = nodes[parent_ref]
        parents.append({"ref": parent.ref, "text": _bounded_text(parent.text)})
        parent_ref = parent.parent_ref
    parents.reverse()
    return parents


def _public_match(
    nodes: dict[str, RuleNode],
    node: RuleNode,
    *,
    score: int | None,
) -> dict:
    children = [
        {
            "ref": child.ref,
            "text": _bounded_text(child.text),
        }
        for ref in node.children[:MAX_RULE_CHILDREN]
        if (child := nodes.get(ref)) is not None
    ]
    return {
        "ref": node.ref,
        "text": _bounded_text(node.text),
        "parents": _parents_to_json(nodes, node),
        "children": children,
        "score": score,
    }
