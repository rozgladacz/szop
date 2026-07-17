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
`find_exploit_candidates.py`. Publiczne API, `HttpClient` i MCP korzystają z
tej samej implementacji parsera w `app.services.rule_lookup`.

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

from app.services.rule_lookup import (  # noqa: E402
    DEFAULT_RULES_PATH,
    RULE_LOOKUP_SCHEMA as JSON_SCHEMA,
    RuleNode,
    load_rules,
    node_to_json,
    normalize_ref,
    parse_rules,
    resolve_ref,
    resolve_to_json,
    search_rules,
)

#: Etykieta poziomu po liczbie kropek w referencji (do czytelnego renderu).
_LEVEL_LABELS = ("punkt", "podpunkt", "podpunkt")

# ---------------------------------------------------------------------------
# Render (czyste funkcje — testowalne bez I/O)
# ---------------------------------------------------------------------------


def _snippet(text: str, *, width: int = 160) -> str:
    """Jednoliniowy skrót tekstu punktu do podglądu w liście/wyszukiwaniu."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "…"


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
