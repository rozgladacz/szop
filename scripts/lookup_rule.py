"""C3 — `lookup_rule`: strukturalny lookup reguł gry po referencji `pkt X` lub słowach.

Uruchom:
    python scripts/lookup_rule.py 14.d.iv            # dokładny punkt + kontekst
    python scripts/lookup_rule.py "pkt 5.f"          # prefiks `pkt ` jest tolerowany
    python scripts/lookup_rule.py 20                  # cały punkt 20 z podpunktami
    python scripts/lookup_rule.py --search osłona     # wyszukiwanie słów kluczowych
    python scripts/lookup_rule.py --list              # spis punktów najwyższego poziomu
    python scripts/lookup_rule.py 14.d.iv --json      # maszynowo

Deliverable Strumienia C3 (`lookup_rule(query)` — roadmap „Narzędzia MCP",
`docs/roadmap.md`) w formie **skryptu-liścia** (ADR-0013), równolegle do
`explain_ability.py`/`validate_loadout.py`/`simulate_engagement.py`/`score_list.py`/
`find_exploit_candidates.py`. Pełna forma MCP-tool/HTTP czeka na serwer C1/B4.

**Zakres MVP (strukturalny, bezzależnościowy):** parser hierarchicznej numeracji
`SZOP_Rozjemca.md` (punkty 0–27, poziomy `N.` → `a.` → `i.`; myślnikowe
podpunkty 4. poziomu doklejane do tekstu rodzica) → (1) resolver referencji
`pkt X` zwracający dokładny tekst punktu wraz z kontekstem rodzica i podpunktami,
(2) wyszukiwanie słów kluczowych (fold akcentów) zwracające ranking pasujących
`pkt`. Bezpośrednio wspiera workflow agentów (AGENTS [REQUIRED] #8 — każde
stwierdzenie o regułach cytuje konkretny `pkt X` odczytany ze źródła).

Źródłem jest `app/static/docs/SZOP_Rozjemca.md` — SSOT reguł przebiegu gry dla
silnika (decyzja strategiczna w `docs/roadmap.md`). Zdolności mają osobne
narzędzie strukturalne (`explain_ability.py`), więc tutaj NIE indeksujemy
`SZOP_Zdolnosci.md`. **Pełna wersja RAG** (semantyczne wyszukiwanie nad DOCX +
embeddingi, sqlite-vec) to Strumień C2 — świadomie odłożona (osobne zależności).

Skrypt-liść: zero zmian w rdzeniu silnika/agentów; brak DB/HTTP/sieci.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

# UTF-8 stdout (tekst reguł PL na Windows cp1250 — jak explain_ability.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

#: Domyślny plik źródłowy reguł przebiegu gry (SSOT silnika).
DEFAULT_RULES_PATH = _repo_root / "app" / "static" / "docs" / "SZOP_Rozjemca.md"

#: Schemat maszynowego wyjścia (`--json`).
JSON_SCHEMA = "szop.lookup_rule/v1"

#: Etykieta poziomu po liczbie kropek w referencji (do czytelnego renderu).
_LEVEL_LABELS = ("punkt", "podpunkt", "podpunkt")

# Linia punktu: po zdjęciu wiodących tabów — etykieta (cyfry albo litery, w tym
# rzymskie zapisane małymi literami) + kropka + separator (tab lub spacja) + treść.
_POINT_RE = re.compile(r"^([0-9]+|[a-z]+)\.[\t ]+(\S.*)$")


@dataclass
class RuleNode:
    """Pojedynczy punkt reguł z kanoniczną referencją (np. ``14.d.iv``)."""

    ref: str
    label: str  # ostatni człon referencji (np. ``iv``)
    text: str
    parent_ref: str | None
    depth: int  # 0 = punkt, 1 = podpunkt litera, 2 = podpunkt rzymski
    children: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser (czysta funkcja — testowalna bez I/O)
# ---------------------------------------------------------------------------


def parse_rules(text: str) -> dict[str, RuleNode]:
    """Parsuje markdown reguł na słownik ``ref -> RuleNode`` w kolejności dokumentu.

    Wcięcie (liczba wiodących tabów) wyznacza poziom: 0 = punkt ``N.``,
    1 = podpunkt ``a.``, 2 = podpunkt rzymski ``i.``. Linie głębsze (myślnikowe
    podpunkty 4. poziomu) oraz wszystko, co nie zaczyna się od poprawnej etykiety,
    traktujemy jako kontynuację tekstu bieżącego (najgłębszego) punktu — dzięki
    czemu zwracany punkt jest kompletną jednostką logiczną. Słownik zachowuje
    kolejność wstawiania (Python 3.7+) = kolejność dokumentu.
    """
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

        # Linia bez poprawnej etykiety albo głębsza niż poziom rzymski (np.
        # myślnik 11.b.iv) = kontynuacja tekstu bieżącego punktu.
        if match is None or depth > 2:
            if current_ref is not None:
                node = nodes[current_ref]
                cont = _clean_text(stripped)
                node.text = f"{node.text}\n{cont}" if cont else node.text
            continue

        label, body = match.group(1), _clean_text(match.group(2))

        if depth == 0:
            ref = label
            parent_ref = None
            last_top = ref
            last_letter_ref = None
        elif depth == 1:
            if last_top is None:
                continue  # podpunkt bez punktu nadrzędnego — pomijamy defensywnie
            ref = f"{last_top}.{label}"
            parent_ref = last_top
            last_letter_ref = ref
        else:  # depth == 2
            if last_letter_ref is None:
                continue  # podpunkt rzymski bez litery nadrzędnej — pomijamy
            ref = f"{last_letter_ref}.{label}"
            parent_ref = last_letter_ref

        nodes[ref] = RuleNode(
            ref=ref, label=label, text=body, parent_ref=parent_ref, depth=depth
        )
        if parent_ref is not None and parent_ref in nodes:
            nodes[parent_ref].children.append(ref)
        current_ref = ref

    return nodes


def _clean_text(value: str) -> str:
    """Normalizuje białe znaki w obrębie linii (taby wewnętrzne → spacja)."""
    return re.sub(r"\s+", " ", value.replace("\t", " ")).strip()


# ---------------------------------------------------------------------------
# Resolver + wyszukiwanie (czyste funkcje)
# ---------------------------------------------------------------------------


def normalize_ref(query: str) -> str:
    """Sprowadza wejście do kanonicznej referencji: ``pkt 14.D.IV`` → ``14.d.iv``."""
    text = query.strip().casefold()
    text = re.sub(r"^pkt\.?\s*", "", text)  # opcjonalny prefiks „pkt"
    text = text.strip().strip(".")  # końcowa kropka, otaczające spacje
    text = re.sub(r"\s+", "", text)  # „14. d . iv" → „14.d.iv" (defensywnie)
    return text


def resolve_ref(nodes: dict[str, RuleNode], query: str) -> RuleNode | None:
    """Zwraca punkt o danej referencji (``14.d.iv``) albo ``None``."""
    return nodes.get(normalize_ref(query))


def _fold(value: str) -> str:
    """Fold akcentów + casefold (NFKD, usuwa znaki łączące) do wyszukiwania."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold()


def search_rules(
    nodes: dict[str, RuleNode], query: str, *, limit: int = 10
) -> list[tuple[RuleNode, int]]:
    """Wyszukuje punkty zawierające WSZYSTKIE słowa zapytania (fold akcentów).

    Wynik: lista ``(node, score)`` posortowana malejąco po liczbie wystąpień słów,
    remisy rozstrzyga kolejność dokumentu. ``score`` = suma wystąpień wszystkich
    tokenów zapytania w tekście punktu.
    """
    tokens = [_fold(t) for t in query.split() if t.strip()]
    if not tokens:
        return []

    ordered = list(nodes.values())  # kolejność dokumentu
    matches: list[tuple[int, int, RuleNode]] = []  # (−score, idx, node) do sortu
    for idx, node in enumerate(ordered):
        folded = _fold(node.text)
        if not all(tok in folded for tok in tokens):
            continue
        score = sum(folded.count(tok) for tok in tokens)
        matches.append((-score, idx, node))

    matches.sort()
    return [(node, -neg_score) for neg_score, _idx, node in matches[:limit]]


# ---------------------------------------------------------------------------
# Render (czyste funkcje — testowalne bez I/O)
# ---------------------------------------------------------------------------


def _snippet(text: str, *, width: int = 160) -> str:
    """Jednoliniowy skrót tekstu punktu do podglądu w liście/wyszukiwaniu."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "…"


def node_to_json(node: RuleNode) -> dict:
    """Maszynowy rekord pojedynczego punktu (bez kontekstu)."""
    return {"ref": node.ref, "text": node.text, "children": list(node.children)}


def resolve_to_json(nodes: dict[str, RuleNode], node: RuleNode) -> dict:
    """Maszynowy rekord punktu z kontekstem (rodzice + podpunkty)."""
    parents = []
    parent_ref = node.parent_ref
    while parent_ref is not None and parent_ref in nodes:
        parent = nodes[parent_ref]
        parents.append({"ref": parent.ref, "text": parent.text})
        parent_ref = parent.parent_ref
    parents.reverse()
    children = [node_to_json(nodes[ref]) for ref in node.children if ref in nodes]
    return {
        "schema": JSON_SCHEMA,
        "ref": node.ref,
        "text": node.text,
        "parents": parents,
        "children": children,
    }


def format_resolved(nodes: dict[str, RuleNode], node: RuleNode) -> str:
    """Czytelny render punktu: kontekst rodzica → punkt → podpunkty."""
    level = _LEVEL_LABELS[min(node.depth, len(_LEVEL_LABELS) - 1)]
    lines = [f"pkt {node.ref} ({level})", "=" * 60]

    # Kontekst rodziców (od najwyższego), wcięty.
    chain: list[RuleNode] = []
    parent_ref = node.parent_ref
    while parent_ref is not None and parent_ref in nodes:
        chain.append(nodes[parent_ref])
        parent_ref = nodes[parent_ref].parent_ref
    chain.reverse()
    for parent in chain:
        lines.append(f"  [{parent.ref}] {_snippet(parent.text)}")
    if chain:
        lines.append("")

    # Treść samego punktu.
    for i, part in enumerate(node.text.split("\n")):
        lines.append(f"pkt {node.ref}: {part}" if i == 0 else f"    {part}")

    # Podpunkty.
    if node.children:
        lines.append("")
        lines.append("Podpunkty:")
        for ref in node.children:
            child = nodes.get(ref)
            if child is not None:
                lines.append(f"  [{child.ref}] {_snippet(child.text)}")
    return "\n".join(lines)


def format_search(results: Sequence[tuple[RuleNode, int]], query: str) -> str:
    """Czytelny render wyników wyszukiwania (ranking + skróty)."""
    if not results:
        return f"Brak punktów pasujących do: {query!r}."
    lines = [f"Wyniki dla {query!r}: {len(results)}", "=" * 60]
    for node, score in results:
        lines.append(f"[{node.ref}] (trafień: {score})")
        lines.append(f"    {_snippet(node.text)}")
    return "\n".join(lines)


def format_list(nodes: dict[str, RuleNode]) -> str:
    """Spis punktów najwyższego poziomu (ref + skrót nagłówka)."""
    tops = [n for n in nodes.values() if n.depth == 0]
    lines = [f"Punkty reguł (najwyższy poziom): {len(tops)}", "=" * 60]
    for node in tops:
        suffix = f" ({len(node.children)} podpunktów)" if node.children else ""
        lines.append(f"  pkt {node.ref:<3} {_snippet(node.text, width=80)}{suffix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_rules(path: pathlib.Path = DEFAULT_RULES_PATH) -> dict[str, RuleNode]:
    """Wczytuje i parsuje plik reguł (UTF-8)."""
    return parse_rules(path.read_text(encoding="utf-8"))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C3 lookup_rule — strukturalny lookup reguł po `pkt X` lub słowach.",
    )
    parser.add_argument(
        "ref", type=str, nargs="?",
        help="referencja punktu (np. 14.d.iv, „pkt 5.f”, 20).",
    )
    parser.add_argument(
        "--search", type=str, default=None, metavar="QUERY",
        help="wyszukaj punkty zawierające wszystkie podane słowa (fold akcentów).",
    )
    parser.add_argument(
        "--limit", type=int, default=10,
        help="maks. liczba wyników wyszukiwania (domyślnie 10).",
    )
    parser.add_argument("--list", action="store_true", help="wypisz punkty najwyższego poziomu.")
    parser.add_argument("--json", action="store_true", help="wynik maszynowy (JSON).")
    parser.add_argument(
        "--rules-file", type=str, default=None,
        help="alternatywny plik reguł (domyślnie SZOP_Rozjemca.md).",
    )
    return parser.parse_args(argv)


def _print_json(payload: dict) -> None:
    """Wspólny dump JSON (UTF-8, wcięcie 2) dla wszystkich trybów `--json`."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    path = pathlib.Path(args.rules_file) if args.rules_file else DEFAULT_RULES_PATH
    try:
        nodes = load_rules(path)
    except OSError as exc:
        print(f"Nie można odczytać pliku reguł: {exc}", file=sys.stderr)
        return 2

    if args.list:
        if args.json:
            _print_json({
                "schema": JSON_SCHEMA,
                "points": [node_to_json(n) for n in nodes.values() if n.depth == 0],
            })
        else:
            print(format_list(nodes))
        return 0

    if args.search is not None:
        results = search_rules(nodes, args.search, limit=args.limit)
        if args.json:
            _print_json({
                "schema": JSON_SCHEMA,
                "query": args.search,
                "results": [{**node_to_json(n), "score": s} for n, s in results],
            })
        else:
            print(format_search(results, args.search))
        return 0 if results else 1

    if not args.ref:
        print(
            "Podaj referencję punktu (np. `lookup_rule.py 14.d.iv`), "
            "`--search SŁOWA` albo `--list`.",
            file=sys.stderr,
        )
        return 2

    node = resolve_ref(nodes, args.ref)
    if node is None:
        print(
            f"Nie znaleziono punktu: {args.ref!r} (znormalizowano do "
            f"{normalize_ref(args.ref)!r}). Użyj `--list` albo `--search`.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        _print_json(resolve_to_json(nodes, node))
    else:
        print(format_resolved(nodes, node))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
