"""Extract ability definitions from SZOP.docx into build/rules_extracted.yaml.

A4.1 — pierwsze ogniwo pipeline'u drift (ADR-0006). Czyta paragraphy z DOCX,
emituje schema `{slug, name, type, description}` per zdolność.

Schema mirror: `app/rulesets/v1/abilities.yaml` (version 1).

Parser strategy (decyzja z A4.1.1 spike, patrz docs/handoffs/HANDOFF_faza-a-4-extract.md):
- Brak Headingów w DOCX (wszystko Normal/List Paragraph) → content-based state machine.
- Sekcje delimitowane paragrafami końca dwukropkiem: `Pasywne:`/`Aktywne:`/`Aury:`/`Broni:`.
- Start parsingu: pierwszy `^Pasywne:$` (skip game rules paragrafy 0-30).
- Stop parsingu: paragraf zaczynający się `Koszt oddziału jest sumą`.
- Zdolność: `^<Name>: <description>$` (regex). Multi-paragraph descriptions: następne
  paragrafy nie pasujące do regex/section-header dołączane do bieżącego opisu.
- Table 2 (passive ability prices) świadomie pominięta — to dane do `ability_costs.yaml`.
- Type derywowany z section header.

Użycie:
    python scripts/rules_extract.py
    python scripts/rules_extract.py --input app/static/docs/SZOP.docx --output build/rules_extracted.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from docx import Document
from pydantic import BaseModel, ConfigDict, Field

# --- Schema -----------------------------------------------------------------

AbilityType = Literal["passive", "active", "aura", "weapon", "unknown"]


class ExtractedAbility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    name: str
    type: AbilityType
    description: str


class RulesExtract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    source: str = Field(description="Względna ścieżka do DOCX")
    abilities: list[ExtractedAbility]


# --- Parser constants -------------------------------------------------------

SECTION_MAP: dict[str, AbilityType] = {
    "Pasywne": "passive",
    "Aktywne": "active",
    "Aury": "aura",
    "Broni": "weapon",
}

# Pattern: <Name> (no colon inside) : <description>
# Name: 2-60 chars, no colon, no period (unlikely in ability names)
NAME_DESC = re.compile(r"^([^:.]{2,60}?):\s+(.+)$")

START_MARKER = "Pasywne:"
STOP_MARKER = "Koszt oddziału jest sumą"

# Some single-line section headers don't introduce abilities themselves, just context
IGNORED_HEADERS = {
    "Dodatkowe zdolności:",
    "Zasady Armii: (zdolności pasywne wycenianie przy założeniu, że ma je prawie każdy oddział w rozpisce)",
}


# --- Slug generation --------------------------------------------------------

# NFKD doesn't decompose Ł/ł (separate Latin chars in Unicode). Pre-replace.
_POLISH_NONDECOMP = {"ł": "l", "Ł": "L"}


def make_slug(name: str) -> str:
    """Deterministic slug: NFKD-decompose → strip accents → lowercase → spaces→underscore.

    Special chars (parens, slashes, X param) stripped — slug must be a stable identifier.

    Examples:
        "Bohater" → "bohater"
        "Szybki/Wolny" → "szybki_wolny"
        "Mag(X)" → "mag"
        "Mistrzostwo(X)" → "mistrzostwo"
        "Dobrze/źle strzela" → "dobrze_zle_strzela"
        "Łatanie" → "latanie"
        "Ociężałość" → "ociezalosc"
    """
    # Drop "(X)" parameter notation
    cleaned = re.sub(r"\(\w+\)", "", name).strip()
    # Pre-replace Polish chars that don't decompose under NFKD
    for orig, repl in _POLISH_NONDECOMP.items():
        cleaned = cleaned.replace(orig, repl)
    # NFKD decompose remaining Polish chars to ASCII + combining marks
    decomposed = unicodedata.normalize("NFKD", cleaned)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    # Lowercase, normalize whitespace/separators
    lowered = ascii_only.lower()
    # Replace slashes and whitespace with underscore
    underscored = re.sub(r"[/\s]+", "_", lowered)
    # Strip remaining non-alphanum-underscore
    return re.sub(r"[^a-z0-9_]", "", underscored).strip("_")


# --- Extractor --------------------------------------------------------------

def extract_abilities(docx_path: Path) -> list[ExtractedAbility]:
    """Walk paragraphs in SZOP.docx, return list of extracted abilities."""

    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX not found: {docx_path}")

    try:
        document = Document(str(docx_path))
    except Exception as exc:  # python-docx raises various exceptions
        raise RuntimeError(f"Failed to open DOCX (not a valid .docx?): {exc}") from exc

    started = False
    current_section: AbilityType | None = None
    abilities: list[ExtractedAbility] = []
    pending: ExtractedAbility | None = None
    description_parts: list[str] = []

    def flush_pending() -> None:
        """Append pending ability with accumulated description to results."""
        nonlocal pending, description_parts
        if pending is not None:
            full_desc = " ".join(description_parts).strip()
            # Pydantic frozen → rebuild
            abilities.append(
                ExtractedAbility(
                    slug=pending.slug,
                    name=pending.name,
                    type=pending.type,
                    description=full_desc,
                )
            )
        pending = None
        description_parts = []

    for paragraph in document.paragraphs:
        # Word soft line breaks (Shift+Enter) come through as `\n` inside paragraph.text.
        # Multiple abilities can share a paragraph this way (e.g., Porażenie/Zguba/Dezintegracja).
        # Split and process each line as a logical paragraph.
        for raw_line in paragraph.text.split("\n"):
            text = raw_line.strip()
            if not text:
                continue

            # Start gate: skip game rules until first "Pasywne:" header
            if not started:
                if text == START_MARKER:
                    started = True
                    current_section = SECTION_MAP["Pasywne"]
                continue

            # Stop gate: cost formulas section
            if text.startswith(STOP_MARKER):
                flush_pending()
                return abilities

            # Section header check: single word + colon
            section_match = re.match(r"^(\w+):$", text)
            if section_match:
                header = section_match.group(1)
                if header in SECTION_MAP:
                    flush_pending()
                    current_section = SECTION_MAP[header]
                    continue

            # Multi-word headers (e.g., "Dodatkowe zdolności:")
            if text in IGNORED_HEADERS:
                flush_pending()
                continue

            # Try to match "<Name>: <description>"
            match = NAME_DESC.match(text)
            if match and current_section is not None:
                # New ability starts → flush previous
                flush_pending()
                name = match.group(1).strip()
                description = match.group(2).strip()
                pending = ExtractedAbility(
                    slug=make_slug(name),
                    name=name,
                    type=current_section,
                    description=description,
                )
                description_parts = [description]
            else:
                # Continuation of previous ability's description
                if pending is not None:
                    description_parts.append(text)
                # else: orphan paragraph (e.g., instruction outside ability) — ignore

    # End of doc — flush last pending
    flush_pending()
    return abilities


# --- Validation -------------------------------------------------------------

def validate_uniqueness(abilities: list[ExtractedAbility]) -> None:
    """Raise if duplicate slugs."""
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for ab in abilities:
        if ab.slug in seen:
            duplicates.append((ab.slug, seen[ab.slug], ab.name))
        else:
            seen[ab.slug] = ab.name
    if duplicates:
        lines = ["Duplicate slugs detected:"]
        for slug, name1, name2 in duplicates:
            lines.append(f"  {slug}: '{name1}' vs '{name2}'")
        raise ValueError("\n".join(lines))


# --- YAML serializer --------------------------------------------------------

def write_yaml(extract: RulesExtract, output_path: Path) -> None:
    """Serialize RulesExtract to YAML with conventions matching abilities.yaml."""
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


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract ability definitions from SZOP.docx → build/rules_extracted.yaml",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("app/static/docs/SZOP.docx"),
        help="Path to SZOP.docx (default: app/static/docs/SZOP.docx)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/rules_extracted.yaml"),
        help="Output YAML path (default: build/rules_extracted.yaml)",
    )
    args = parser.parse_args(argv)

    try:
        abilities = extract_abilities(args.input)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        validate_uniqueness(abilities)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    extract = RulesExtract(
        version=1,
        source=str(args.input).replace("\\", "/"),
        abilities=abilities,
    )

    write_yaml(extract, args.output)
    print(
        f"Extracted {len(abilities)} abilities from {args.input} → {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
