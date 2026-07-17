"""C3 — `explain_ability`: strukturalny lookup zdolności po slug lub nazwie PL.

Uruchom:
    python scripts/explain_ability.py --list                  # wszystkie zdolności
    python scripts/explain_ability.py --type weapon           # tylko broni
    python scripts/explain_ability.py furia                   # po slug
    python scripts/explain_ability.py Podwojny                # po nazwie (fuzzy, bez ogonkow)
    python scripts/explain_ability.py transport --json        # maszynowo

Deliverable Strumienia C3 (`explain_ability(slug)` — roadmap „Narzędzia MCP",
`docs/roadmap.md`) w formie **skryptu-liścia** (ADR-0013), równolegle do
`simulate_engagement.py`/`exploit_hunt.py`/`battle_replay.py`. Publiczne API,
`HttpClient` i MCP korzystają z tej samej warstwy
`app.services.ability_lookup`.

Źródło = katalog SSOT `app.data.abilities` (ten sam, którego używają warstwa
kosztów i UI) — `find_definition`/`slug_for_name`/`definitions_by_type`/`to_dict`.
NIE re-parsuje `app/rulesets/v1/abilities.yaml` (to target driftu A4, nie API):
reuse katalogu zamiast replikacji (AGENTS [CRITICAL] #3). Rozpoznaje wejście po
slug (`furia`) ORAZ po nazwie PL z normalizacją (wielkość liter / ogonki /
spacje), bo `slug_for_name` mapuje też wyświetlaną nazwę (np. `Podwójny` →
slug `rozrywajacy`).

Skrypt-liść: zero zmian w rdzeniu silnika/agentów/katalogu; brak DB/HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Sequence

# UTF-8 stdout (nazwy/opisy zdolności PL na Windows cp1250 — jak balance_simulate.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.data import abilities as ability_catalog  # noqa: E402
from app.data.abilities import AbilityDefinition  # noqa: E402
from app.services.ability_lookup import (  # noqa: E402
    ability_to_json,
    resolve_ability,
)

#: Czytelne etykiety PL typów zdolności (klucz = `AbilityDefinition.type`).
TYPE_LABELS = {
    "passive": "pasywna",
    "active": "aktywna",
    "aura": "aura",
    "weapon": "broni",
}

#: Kolejność typów w `--list` (deterministyczna, grupami).
TYPE_ORDER = ("passive", "active", "aura", "weapon")


def _type_label(ability_type: str) -> str:
    return TYPE_LABELS.get(ability_type, ability_type)


# ---------------------------------------------------------------------------
# Render (czyste funkcje — testowalne bez I/O)
# ---------------------------------------------------------------------------


def format_ability(definition: AbilityDefinition) -> str:
    """Czytelny opis pojedynczej zdolności."""
    status = "ZABLOKOWANA (poza zakresem MVP)" if definition.blocked else "aktywna"
    lines = [
        f"Zdolność: {definition.display_name()} [{definition.slug}]",
        f"Typ: {definition.type} ({_type_label(definition.type)})",
        f"Status: {status}",
    ]
    if definition.value_label:
        param = f"Parametr: {definition.value_label} (typ: {definition.value_type or '?'}"
        if definition.value_choices:
            param += f", dozwolone: {', '.join(definition.value_choices)}"
        param += ")"
        lines.append(param)
    lines.append("Opis:")
    lines.append(f"  {definition.description}")
    return "\n".join(lines)


def format_list(definitions: Sequence[AbilityDefinition]) -> str:
    """Lista zdolności pogrupowana po typie (slug → wyświetlana nazwa)."""
    by_type: dict[str, list[AbilityDefinition]] = {}
    for d in definitions:
        by_type.setdefault(d.type, []).append(d)

    lines = [f"Zdolności w katalogu: {len(definitions)}", "=" * 60]
    # Najpierw typy w ustalonej kolejności, potem ewentualne nieznane (alfabetycznie).
    ordered_types = [t for t in TYPE_ORDER if t in by_type]
    ordered_types += sorted(t for t in by_type if t not in TYPE_ORDER)
    for ability_type in ordered_types:
        entries = sorted(by_type[ability_type], key=lambda d: d.slug)
        lines.append(f"\n{ability_type} ({_type_label(ability_type)}) — {len(entries)}:")
        for d in entries:
            mark = " [blocked]" if d.blocked else ""
            lines.append(f"  {d.slug:<22} {d.display_name()}{mark}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_definitions(definitions: Sequence[AbilityDefinition], *, as_json: bool) -> None:
    """Wypisuje listę zdolności jako JSON (tablica) albo czytelną listę (wspólne dla --list/--type)."""
    if as_json:
        print(json.dumps([ability_to_json(d) for d in definitions], ensure_ascii=False, indent=2))
    else:
        print(format_list(definitions))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C3 explain_ability — strukturalny lookup zdolności po slug/nazwie.",
    )
    parser.add_argument(
        "ability", type=str, nargs="?",
        help="slug (np. furia) lub nazwa PL (np. Furia / Podwójny).",
    )
    parser.add_argument(
        "--type", type=str, default=None, dest="ability_type",
        help=f"wypisz wszystkie zdolności danego typu: {', '.join(TYPE_ORDER)}.",
    )
    parser.add_argument("--list", action="store_true", help="wypisz wszystkie zdolności i zakończ.")
    parser.add_argument("--json", action="store_true", help="wynik maszynowy (JSON).")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.ability_type is not None:
        defs = ability_catalog.definitions_by_type(args.ability_type)
        if not defs:
            valid = ", ".join(TYPE_ORDER)
            print(
                f"Nieznany typ zdolności: {args.ability_type!r} (dozwolone: {valid}).",
                file=sys.stderr,
            )
            return 2
        _print_definitions(defs, as_json=args.json)
        return 0

    if args.list:
        _print_definitions(list(ability_catalog.all_definitions()), as_json=args.json)
        return 0

    if not args.ability:
        print(
            "Podaj slug/nazwę zdolności (np. `explain_ability.py furia`) "
            "albo `--list` / `--type TYPE`.",
            file=sys.stderr,
        )
        return 2

    definition = resolve_ability(args.ability)
    if definition is None:
        print(
            f"Nie znaleziono zdolności: {args.ability!r}. Użyj `--list` by zobaczyć dostępne.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(ability_to_json(definition), ensure_ascii=False, indent=2))
    else:
        print(format_ability(definition))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
