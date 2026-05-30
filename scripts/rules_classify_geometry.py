"""Classify abilities by geometric mechanics required.

Trzeci skrypt pipeline'u A4 (ADR-0006 — drift-only nie auto-gen). Czyta
`app/rulesets/v1/abilities.yaml`, dopasowuje keywords w `description`, grupuje
zdolności wg kategorii geometrycznej. Wynik: `build/geometry_classification.md`.

Cel: **lista exclusions dla Strumienia B MVP** (Pareto: oddział = koło, brak
orientacji per-model, brak facing). Hard prereq dla B0 (`docs/roadmap.md`).

Kategorie:
- **facing** — orientacja/strefy (przód/tył/lewo/prawo); WYKLUCZONE w B MVP
- **per_model** — wybór konkretnego modelu (rozdzielanie ran); WYKLUCZONE
- **los_complex** — łuki/stożki/sektory LoS; WYKLUCZONE
- **los_simple** — proste modyfikatory LoS (Wysoki, niebezpośredni); OK
- **range_special** — zasięg od trzeciego oddziału (Artyleria); OK
- **placement_special** — niestandardowe rozstawianie; OK (one-time setup)
- **movement_special** — niestandardowy ruch (linia, ignore terrain); REVIEW
- **none** — brak geometric concerns

Heurystyka jest **konserwatywna** (false-positives akceptowalne, false-negatives
problematyczne) — klasyfikator emituje raport do **ręcznego przeglądu**, nie
auto-decyzję. B MVP architekt decyduje per exclusion.

Użycie:
    python scripts/rules_classify_geometry.py
    python scripts/rules_classify_geometry.py --input app/rulesets/v1/abilities.yaml \\
                                                --output build/geometry_classification.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.rulesets.models import RulesetAbility  # noqa: E402

DEFAULT_INPUT = Path("app/rulesets/v1/abilities.yaml")
DEFAULT_OUTPUT = Path("build/geometry_classification.md")


# --- Categories -------------------------------------------------------------

@dataclass(frozen=True)
class Category:
    """Definicja kategorii geometrycznej."""

    name: str
    label: str
    excluded_in_b_mvp: bool
    rationale: str
    # Słowa kluczowe (regex-ready). Dopasowanie case-insensitive po normalizacji
    # do ASCII (NFKD + drop combining) — Polish letters traktujemy jako ASCII
    # equivalents żeby wzorzec "tyl" łapał "tył", "tylu", "tylnej".
    keywords: tuple[str, ...] = field(default_factory=tuple)


CATEGORIES: tuple[Category, ...] = (
    Category(
        name="facing",
        label="Orientacja / strefy (front/tył/flank)",
        excluded_in_b_mvp=True,
        rationale="B MVP Pareto: oddział = koło, brak facing. Wymaga `BattleUnit.facing_deg` field (ADR-0042).",
        # Wszystkie keyword patterns OPERUJĄ NA TEKŚCIE PO `_normalize_for_match`
        # (ASCII-fold + lowercase). Patterny muszą być w ASCII — Polish chars
        # tylko w fallback test cases, nie w live patterns.
        keywords=(
            r"\bzwrot\b",
            r"\bprzod\b", r"\btyl\b", r"\blewo\b", r"\bprawo\b",
            r"\bstrefa\b", r"\bstrefie\b", r"\bstrefy\b",
            r"\busytuowanie\b",
            r"\bflank\w*",
            r"\bobrot\w*",  # obrót, obrotów, obrotowy, obrotowa (po NFKD ó→o)
        ),
    ),
    Category(
        name="per_model",
        label="Wybór konkretnego modelu (allocation/target selection)",
        excluded_in_b_mvp=True,
        rationale="B MVP: oddział = jeden blob, brak per-model granularity. Per-model wymaga rozszerzenia E1 (post-stable).",
        keywords=(
            r"\brozdziela\w*",  # rozdziela rany
            r"\bnajwyzsz\w+ wytrzymalosc\w*",
            r"\bnajnizsz\w+ wytrzymalosc\w*",
            r"\bwybrane?go modelu\b",
            r"\bwybierz model\w*",
            r"\bdoceloweg?o? modelu\b",
        ),
    ),
    Category(
        name="los_complex",
        label="LoS — łuki / stożki / sektory",
        excluded_in_b_mvp=True,
        rationale="B MVP LoS: 3-state (Widzi/Nie widzi/Osłona) via sampling N=16 (ADR-0043). Łuki/stożki wymagają analitycznej geometrii.",
        # Note: '°' (U+00B0) jest stripowane przez ASCII normalize — NIE używać
        # w live patterns. Polish nazewnictwo ('stopni', 'stopnie') jako primary;
        # angle keywords ('kat\w*' łapie kąt/kąta/kątem) jako fallback.
        keywords=(
            r"\bluk\b", r"\bluku\b",
            r"\bstozek\b", r"\bstozka\b",
            r"\bsektor\w*",
            r"\bkat\w*",  # kąt (po NFKD ą→a)
            r"\d+\s*stopni\w*",  # 180 stopni, 90 stopni, ... — Polish notation
        ),
    ),
    Category(
        name="los_simple",
        label="LoS — proste modyfikatory (Wysoki, niebezpośredni, etc.)",
        excluded_in_b_mvp=False,
        rationale="B MVP może obsłużyć: ignore LoS check (niebezpośredni), elevation modifier (Wysoki), simple cover.",
        keywords=(
            r"\blinia\s+wzroku\b", r"\bli?nii?\s+wzroku\b",
            r"\bpole\s+widzenia\b", r"\bpolu\s+widzenia\b",
            r"\bpodwyz?szeniu?\b", r"\bpodniesionym?\b",
            r"\bnie\s+wymaga\s+lini\w*",
        ),
    ),
    Category(
        name="range_special",
        label="Specjalny zasięg (od sojuszniczego, od krawędzi, od cel'u)",
        excluded_in_b_mvp=False,
        rationale="B MVP obsłuży: zasięg od trzeciego elementu (sojuszniczy oddział, krawędź stołu). Wymaga wielokrotnego center-of-mass lookup.",
        keywords=(
            r"\bod\s+sojuszniczego\b", r"\bod\s+dowolnego\b",
            r"\bod\s+krawedzi\b",
            r"\bod\s+celu\b",
            r"\bod\s+twoj?ej?\s+strefy\s+rozstawienia\b",
        ),
    ),
    Category(
        name="placement_special",
        label="Specjalne rozstawienie / deployment",
        excluded_in_b_mvp=False,
        rationale="B MVP: deployment phase obsługuje special placement (Zasadzka, Zwiadowca, Rezerwa) jako pre-game setup, nie runtime geometry.",
        keywords=(
            r"\bnie\s+rozstawia\s+sie\s+przed\b",
            r"\bdowolnym\s+dozwolonym\s+miejscu\b",
            r"\brozstawia\s+sie\s+po\b",
            r"\bprzed\s+rozstawieniem\b",
            r"\b12\W+od\s+twoj?ej?\s+krawedzi\b",
            r"\brozstawia\s+sie\b",
        ),
    ),
    Category(
        name="movement_special",
        label="Specjalny ruch (linia, ignorowanie terenu, jet)",
        excluded_in_b_mvp=False,
        rationale="B MVP może obsłużyć: ignore terrain (Latający, Zwinny), linear move (Samolot 30-36\"). Wymaga branchu w move resolver — manageable.",
        keywords=(
            r"\bignoruje\s+teren\b", r"\bignoruje\s+jednostki\b",
            r"\bw\s+jednej\s+linii\b", r"\bw\s+linii\s+prostej\b",
            r"\bprzemiesc\w+\s+\d+\W+\d+\W+w\s+jednej\b",  # 30-36" w jednej
            r"\bpunkt\s+koncowy\b",
        ),
    ),
)


# --- Text normalization -----------------------------------------------------

_POLISH_NONDECOMP = {"ł": "l", "Ł": "L"}


def _normalize_for_match(text: str) -> str:
    """ASCII-fold + lowercase dla keyword matching. Patrz make_slug() w rules_extract.

    Polish chars (`ą/ć/ę/ł/ń/ó/ś/ź/ż`) → ASCII equivalents, żeby keyword "tyl"
    łapał "tył", "tylu", "tylnej".
    """
    for orig, repl in _POLISH_NONDECOMP.items():
        text = text.replace(orig, repl)
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


# --- Classification ---------------------------------------------------------

@dataclass(frozen=True)
class ClassifiedAbility:
    slug: str
    name: str
    type: str
    categories: tuple[str, ...]  # nazwy kategorii (mogą być >1)
    matched_keywords: dict[str, tuple[str, ...]]  # category → matched patterns
    excluded_in_b_mvp: bool


def classify_ability(ability: RulesetAbility) -> ClassifiedAbility:
    """Dopasuj keywords per kategoria; wynik to lista kategorii + flagi."""
    normalized = _normalize_for_match(ability.description)
    matched: dict[str, tuple[str, ...]] = {}
    categories: list[str] = []
    excluded = False

    for cat in CATEGORIES:
        hits: list[str] = []
        for pattern in cat.keywords:
            if re.search(pattern, normalized):
                hits.append(pattern)
        if hits:
            categories.append(cat.name)
            matched[cat.name] = tuple(hits)
            if cat.excluded_in_b_mvp:
                excluded = True

    return ClassifiedAbility(
        slug=ability.slug,
        name=ability.name,
        type=ability.type,
        categories=tuple(categories),
        matched_keywords=matched,
        excluded_in_b_mvp=excluded,
    )


def classify_abilities(abilities: list[RulesetAbility]) -> list[ClassifiedAbility]:
    return [classify_ability(a) for a in abilities]


# --- Loader -----------------------------------------------------------------

def load_abilities(path: Path) -> list[RulesetAbility]:
    if not path.exists():
        raise FileNotFoundError(f"Abilities YAML not found: {path}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [RulesetAbility.model_validate(entry) for entry in data.get("abilities", [])]


# --- Rendering --------------------------------------------------------------

def render_report(classified: list[ClassifiedAbility], input_path: Path) -> str:
    today = _dt.date.today().isoformat()
    by_category: dict[str, list[ClassifiedAbility]] = {cat.name: [] for cat in CATEGORIES}
    uncategorized: list[ClassifiedAbility] = []
    excluded: list[ClassifiedAbility] = []

    for c in classified:
        if not c.categories:
            uncategorized.append(c)
        else:
            for cat_name in c.categories:
                by_category[cat_name].append(c)
        if c.excluded_in_b_mvp:
            excluded.append(c)

    lines: list[str] = [
        f"# Geometric Classification — {today}",
        "",
        f"- **Source:** `{input_path}` — {len(classified)} abilities scanned",
        f"- **Excluded in B MVP:** {len(excluded)} abilities",
        f"- **Uncategorized (no geometric keywords):** {len(uncategorized)}",
        "",
        "## B MVP Exclusion List (hard input dla Strumień B0)",
        "",
        "Te zdolności wymagają geometrii nieobsługiwanej w Pareto MVP "
        "(oddział = koło, brak facing). Engine raise `UnsupportedAbilityError` "
        "gdy roster zawiera je. Roadmap: ADR-0008 (Pareto MVP), ADR-0042 "
        "(facing introduction w E3).",
        "",
        "| slug | name | type | reason |",
        "|---|---|---|---|",
    ]
    for c in sorted(excluded, key=lambda x: x.slug):
        reasons = ", ".join(c.categories)
        lines.append(f"| `{c.slug}` | {c.name} | {c.type} | {reasons} |")
    if not excluded:
        lines.append("| _(none)_ | | | |")
    lines.append("")

    lines.append("## Per-category breakdown")
    lines.append("")

    for cat in CATEGORIES:
        members = sorted(by_category[cat.name], key=lambda x: x.slug)
        excl_marker = " ⛔ (B MVP excluded)" if cat.excluded_in_b_mvp else ""
        lines.append(f"### `{cat.name}` — {cat.label}{excl_marker}")
        lines.append("")
        lines.append(f"_{cat.rationale}_")
        lines.append("")
        if members:
            lines.append("| slug | name | type | matched keywords |")
            lines.append("|---|---|---|---|")
            for c in members:
                hits = "; ".join(c.matched_keywords.get(cat.name, ()))
                lines.append(f"| `{c.slug}` | {c.name} | {c.type} | `{hits}` |")
        else:
            lines.append("_(none matched)_")
        lines.append("")

    lines.append("## Uncategorized (no geometric concerns)")
    lines.append("")
    lines.append(
        "Zdolności bez matched keywords w żadnej kategorii. Większość to passive "
        "abilities operujące na statystykach (test'y, modifier'y), bronie z prostymi "
        "efektami (AP, Rozprysk), itp."
    )
    lines.append("")
    if uncategorized:
        lines.append(f"({len(uncategorized)} abilities)")
        lines.append("")
        slugs = sorted(u.slug for u in uncategorized)
        # Wrap into rows of 6
        for i in range(0, len(slugs), 6):
            chunk = slugs[i:i + 6]
            lines.append(", ".join(f"`{s}`" for s in chunk))
            lines.append("")
    else:
        lines.append("_(none — all abilities matched at least one category)_")
        lines.append("")

    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify abilities by geometric mechanics → B MVP exclusion list.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        abilities = load_abilities(args.input)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    classified = classify_abilities(abilities)
    rendered = render_report(classified, args.input)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(rendered)

    excluded_count = sum(1 for c in classified if c.excluded_in_b_mvp)
    print(
        f"Classified {len(classified)} abilities, {excluded_count} excluded in B MVP "
        f"→ {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
