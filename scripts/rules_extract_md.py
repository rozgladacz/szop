"""Extract ability definitions from SZOP_Zdolnosci.md into a YAML drift snapshot.

Equiwalent `rules_extract.py` ale dla strukturalnej Markdown-version reguł
(`app/static/docs/SZOP_Zdolnosci.md`). MD jest **formalną, ręcznie utrzymywaną**
wersją zdolności z `SZOP.docx` (cytat opisu 1:1, plus dodatkowe metadane:
`efekty`, `koszt`, `aura_tak`, `rozkaz_tak`, `zakres`, `mistrzostwo_tak`).

Schema wynikowy: `RulesetAbility` z `app/services/rulesets/models.py` (reuse,
to samo co DOCX extract). Drift pipeline (`rules_drift.py`) konsumuje oba
strumienie identycznie.

MD jest dużo prostsze parserowane niż DOCX:
- Sekcje wyznaczone explicit `## Pasywne` / `## Aktywne` / `## Aury` / `## Broni`.
- Zdolności wyznaczone `### N. Name` (numbered, stable id).
- `typ: <pasywna|aktywna|aura|broni>` (Polski → English mapping w SECTION_MAP).
- `opis: "..."` (quoted), w tym multi-line quoted strings.

Użycie:
    python scripts/rules_extract_md.py
    python scripts/rules_extract_md.py --input app/static/docs/SZOP_Zdolnosci.md \\
                                        --output build/rules_md.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.rulesets.models import AbilityType, RulesetAbility  # noqa: E402
from scripts.rules_extract import make_slug, validate_uniqueness  # noqa: E402


class MdExtract(BaseModel):
    """Korzeń `build/rules_md.yaml` — wersja + ścieżka źródła + lista."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=1, ge=1)
    source: str
    abilities: tuple[RulesetAbility, ...]


# Sekcje MD (Polish → schema AbilityType).
SECTION_MAP: dict[str, AbilityType] = {
    "Pasywne": "passive",
    "Aktywne": "active",
    "Aury": "aura",
    "Broni": "weapon",
}

# `typ:` field (Polski → schema).
TYPE_MAP: dict[str, AbilityType] = {
    "pasywna": "passive",
    "aktywna": "active",
    "aura": "aura",
    "broni": "weapon",
}

# Section header — `## <pierwsze słowo + opcjonalne dodatkowe>`. Lookup w
# SECTION_MAP idzie po **pierwszym słowie** (split by whitespace).
# Pozwala na future MD edits typu "## Pasywne Specjalne" bez breakage —
# pierwsze słowo nadal mapuje na sekcję, reszta jest pomijana.
SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$")
ABILITY_HEADER = re.compile(r"^###\s+\d+\.\s+(.+?)\s*$")  # `### 1. Bastion`
TYPE_FIELD = re.compile(r"^\s*-\s*typ:\s*(\w+)\s*$")
OPIS_FIELD = re.compile(r"^\s*-\s*opis:\s*(.+?)\s*$")


def _unquote(text: str) -> str:
    """Strip wrapping double-quotes from `opis:` value, if present."""
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def extract_abilities_md(md_path: Path) -> list[RulesetAbility]:
    """Walk Markdown sections + ability headers, return list of RulesetAbility.

    Multi-line quoted `opis:` jest scalany przez kontynuację linii — póki linia
    następna nie zaczyna nowego pola (`- klucz:`), nowego ability (`### N.`) lub
    nowej sekcji (`## `), traktujemy ją jako kontynuację opisu.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown not found: {md_path}")

    with open(md_path, encoding="utf-8") as fh:
        lines = fh.readlines()

    abilities: list[RulesetAbility] = []
    current_section: AbilityType | None = None
    pending_name: str | None = None
    pending_type: AbilityType | None = None
    pending_opis_parts: list[str] = []
    inside_opis = False

    def flush() -> None:
        nonlocal pending_name, pending_type, pending_opis_parts, inside_opis
        if pending_name is not None and pending_type is not None and pending_opis_parts:
            description = " ".join(p.strip() for p in pending_opis_parts).strip()
            if description:
                abilities.append(
                    RulesetAbility(
                        slug=make_slug(pending_name),
                        name=pending_name,
                        type=pending_type,
                        description=description,
                    )
                )
        pending_name = None
        pending_type = None
        pending_opis_parts = []
        inside_opis = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        # Sekcja: `## Pasywne` / `## Aktywne` / etc. (ignore `## Konwencje`).
        # Multi-word headers (e.g., `## Pasywne Specjalne`) — lookup po pierwszym
        # słowie. Niezmapowane sekcje (Konwencje, Wstęp, etc.) → current_section=None.
        section_match = SECTION_HEADER.match(line)
        if section_match:
            flush()
            header_text = section_match.group(1).strip()
            first_word = header_text.split(maxsplit=1)[0] if header_text else ""
            current_section = SECTION_MAP.get(first_word)
            continue

        # Nowa ability: `### N. Name`.
        ability_match = ABILITY_HEADER.match(line)
        if ability_match:
            flush()
            if current_section is None:
                # Headers przed pierwszą valid section (np. `## Konwencje > ### Tagi`) — skip.
                continue
            pending_name = ability_match.group(1).strip()
            # Domyślny type z sekcji; może być nadpisany przez `- typ:` field.
            pending_type = current_section
            continue

        # `- typ: <value>` field.
        type_match = TYPE_FIELD.match(line)
        if type_match and pending_name is not None:
            inside_opis = False
            polish_type = type_match.group(1).strip()
            mapped = TYPE_MAP.get(polish_type)
            if mapped is not None:
                pending_type = mapped
            else:
                # Unknown typ value (np. typo 'pasywne' zamiast 'pasywna') —
                # zachowaj section fallback ale ostrzeż usera. Bez tej diagnostyki
                # MD typo prowadziłoby do silent miscategorization → drift R4.
                print(
                    f"WARNING: unknown `typ: {polish_type!r}` for ability "
                    f"{pending_name!r} — falling back to section type "
                    f"{pending_type!r}",
                    file=sys.stderr,
                )
            continue

        # `- opis: "<text>"` field (potencjalnie multi-line).
        opis_match = OPIS_FIELD.match(line)
        if opis_match and pending_name is not None:
            pending_opis_parts = [_unquote(opis_match.group(1))]
            inside_opis = True
            continue

        # Wewnątrz opisu: kontynuacja póki nie nowy field (`- klucz:`), nie
        # nowa lista (`-  `), nie pusta linia. Konserwatywnie: pusta linia
        # lub nowy `- ` to koniec opisu.
        if inside_opis and pending_name is not None:
            if not stripped:
                inside_opis = False
                continue
            if stripped.startswith("- ") or stripped.startswith("-\t"):
                inside_opis = False
                continue
            # Continuation line — append.
            pending_opis_parts.append(stripped)

    flush()
    return abilities


def write_yaml(extract: MdExtract, output_path: Path) -> None:
    """Serialize do YAML zgodnie z konwencją `abilities.yaml`."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": extract.version,
        "source": extract.source,
        "abilities": [
            {
                "slug": ab.slug,
                "name": ab.name,
                "type": ab.type,
                "description": ab.description,
            }
            for ab in extract.abilities
        ],
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            payload,
            fh,
            allow_unicode=True,
            sort_keys=False,
            width=10000,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract ability definitions from SZOP_Zdolnosci.md → build/rules_md.yaml",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("app/static/docs/SZOP_Zdolnosci.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/rules_md.yaml"),
    )
    args = parser.parse_args(argv)

    try:
        abilities = extract_abilities_md(args.input)
    except FileNotFoundError as exc:
        print(f"ERROR: Markdown not found: {exc.filename or args.input}", file=sys.stderr)
        return 1

    try:
        validate_uniqueness(abilities)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    extract = MdExtract(
        version=1,
        source=str(args.input).replace("\\", "/"),
        abilities=tuple(abilities),
    )

    write_yaml(extract, args.output)
    print(
        f"Extracted {len(abilities)} abilities from {args.input} → {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
