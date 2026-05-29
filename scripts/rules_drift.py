"""Detect drift between DOCX-extracted abilities and the YAML ruleset.

Drugi etap pipeline'u drift-only (ADR-0006). Porównuje `build/rules_extracted.yaml`
(A4.1, parsed `SZOP.docx`) z `app/rulesets/v1/abilities.yaml` (deklaratywny
ruleset) i emituje `build/drift_report.md`. **Nie modyfikuje YAML automatycznie.**

Cztery typy raportów (decyzje A4.2, patrz HANDOFF_faza-a-4-drift.md):

| ID | Sytuacja                                | Severity | Exit code |
|----|-----------------------------------------|----------|-----------|
| R1 | slug w DOCX, brak w YAML                | ERROR    | 1         |
| R2 | slug w YAML, brak w DOCX                | WARN     | 2         |
| R3 | ten sam slug, różny `description`       | WARN     | 2         |
| R4 | ten sam slug, różny `type`              | ERROR    | 1         |

R2 jest filtrowany przez allowlist (`app/rulesets/v1/drift_allowlist.yaml`):
wpisy zawarte w `allowed_yaml_only` są raportowane jako "WHITELISTED" ale
**nie kontrybuują do exit code**.

Description comparison: po `unicodedata.normalize("NFKC", s).strip()` +
collapse whitespace (`re.sub(r"\\s+", " ", s)`). Łapie typografię Unicode
i artefakty DOCX export, zachowuje case + merytoryczne różnice.

Exit codes:
- `0` — clean (zero ERROR/WARN, lub wyłącznie whitelisted R2)
- `1` — co najmniej jeden R1 lub R4 (severity ERROR)
- `2` — tylko WARN (non-whitelisted R2 lub R3), brak ERROR

Użycie:
    python scripts/rules_drift.py
    python scripts/rules_drift.py --extracted build/rules_extracted.yaml \\
                                   --yaml app/rulesets/v1/abilities.yaml \\
                                   --whitelist app/rulesets/v1/drift_allowlist.yaml \\
                                   --report build/drift_report.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.rulesets.models import RulesetAbility  # noqa: E402

DEFAULT_EXTRACTED = Path("build/rules_extracted.yaml")
DEFAULT_YAML = Path("app/rulesets/v1/abilities.yaml")
DEFAULT_WHITELIST = Path("app/rulesets/v1/drift_allowlist.yaml")
DEFAULT_REPORT = Path("build/drift_report.md")


# --- Normalization ----------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")


def normalize_description(text: str) -> str:
    """NFKC + strip + collapse whitespace. Patrz HANDOFF A4.2 Q2."""
    normalized = unicodedata.normalize("NFKC", text).strip()
    return _WHITESPACE.sub(" ", normalized)


# --- Whitelist --------------------------------------------------------------

@dataclass(frozen=True)
class WhitelistEntry:
    slug: str
    reason: str
    until_date: str | None = None


@dataclass(frozen=True)
class Allowlist:
    """Whitelist dwukierunkowy: filtruje R2 (YAML-only) i R1 (DOCX-only)."""

    yaml_only: dict[str, WhitelistEntry]
    docx_only: dict[str, WhitelistEntry]


def _parse_entries(raw_list: list) -> dict[str, WhitelistEntry]:
    out: dict[str, WhitelistEntry] = {}
    for raw in raw_list:
        slug = raw["slug"]
        out[slug] = WhitelistEntry(
            slug=slug,
            reason=raw.get("reason", "(no reason given)"),
            until_date=raw.get("until_date"),
        )
    return out


def load_whitelist(path: Path | None) -> Allowlist:
    """Załaduj `drift_allowlist.yaml`. Brak pliku = pusty allowlist (OK).

    Schema:
        allowed_yaml_only:  # filtruje R2 (YAML-only)
          - slug: aura
            reason: "..."
            until_date: ~  # null = permanent
        allowed_docx_only:  # filtruje R1 (DOCX-only) — symetria
          - slug: szybki_wolny
            reason: "..."
            until_date: ~
    """
    if path is None or not path.exists():
        return Allowlist(yaml_only={}, docx_only={})

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    return Allowlist(
        yaml_only=_parse_entries(data.get("allowed_yaml_only", [])),
        docx_only=_parse_entries(data.get("allowed_docx_only", [])),
    )


# --- Abilities loader -------------------------------------------------------

def load_abilities(path: Path) -> list[RulesetAbility]:
    """Załaduj `abilities` z YAML (zarówno `rules_extracted.yaml` jak `abilities.yaml`)."""
    if not path.exists():
        raise FileNotFoundError(f"Abilities YAML not found: {path}")

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_abilities = data.get("abilities", [])
    return [RulesetAbility.model_validate(entry) for entry in raw_abilities]


# --- Diff computation -------------------------------------------------------

@dataclass(frozen=True)
class DriftReport:
    r1_missing_in_yaml: list[RulesetAbility]
    r1_whitelisted: list[tuple[RulesetAbility, WhitelistEntry]]
    r2_missing_in_docx: list[RulesetAbility]
    r2_whitelisted: list[tuple[RulesetAbility, WhitelistEntry]]
    r3_description_mismatch: list[tuple[RulesetAbility, RulesetAbility]]  # (docx, yaml)
    r4_type_mismatch: list[tuple[RulesetAbility, RulesetAbility]]  # (docx, yaml)

    @property
    def has_errors(self) -> bool:
        return bool(self.r1_missing_in_yaml or self.r4_type_mismatch)

    @property
    def has_warnings(self) -> bool:
        return bool(self.r2_missing_in_docx or self.r3_description_mismatch)

    @property
    def exit_code(self) -> int:
        if self.has_errors:
            return 1
        if self.has_warnings:
            return 2
        return 0


def compute_drift(
    docx_abilities: list[RulesetAbility],
    yaml_abilities: list[RulesetAbility],
    whitelist: Allowlist | dict[str, WhitelistEntry] | None = None,
) -> DriftReport:
    """Porównaj listy ability po slug — wygeneruj 5 bucketów raportu.

    `whitelist` accepts: Allowlist (preferred), dict (legacy — treated as yaml_only),
    or None (empty allowlist).
    """
    if whitelist is None:
        whitelist = Allowlist(yaml_only={}, docx_only={})
    elif isinstance(whitelist, dict):
        whitelist = Allowlist(yaml_only=whitelist, docx_only={})

    docx_by_slug = {a.slug: a for a in docx_abilities}
    yaml_by_slug = {a.slug: a for a in yaml_abilities}

    docx_slugs = set(docx_by_slug)
    yaml_slugs = set(yaml_by_slug)

    r1_all = sorted(
        (docx_by_slug[s] for s in docx_slugs - yaml_slugs),
        key=lambda a: a.slug,
    )
    r1_missing: list[RulesetAbility] = []
    r1_whitelisted: list[tuple[RulesetAbility, WhitelistEntry]] = []
    for ab in r1_all:
        entry = whitelist.docx_only.get(ab.slug)
        if entry is None:
            r1_missing.append(ab)
        else:
            r1_whitelisted.append((ab, entry))

    r2_all = sorted(
        (yaml_by_slug[s] for s in yaml_slugs - docx_slugs),
        key=lambda a: a.slug,
    )
    r2_missing: list[RulesetAbility] = []
    r2_whitelisted: list[tuple[RulesetAbility, WhitelistEntry]] = []
    for ab in r2_all:
        entry = whitelist.yaml_only.get(ab.slug)
        if entry is None:
            r2_missing.append(ab)
        else:
            r2_whitelisted.append((ab, entry))

    r3: list[tuple[RulesetAbility, RulesetAbility]] = []
    r4: list[tuple[RulesetAbility, RulesetAbility]] = []
    for slug in sorted(docx_slugs & yaml_slugs):
        d = docx_by_slug[slug]
        y = yaml_by_slug[slug]
        if d.type != y.type:
            r4.append((d, y))
        # R3 niezależnie od R4 — type mismatch nie wyklucza description drift
        if normalize_description(d.description) != normalize_description(y.description):
            r3.append((d, y))

    return DriftReport(
        r1_missing_in_yaml=r1_missing,
        r1_whitelisted=r1_whitelisted,
        r2_missing_in_docx=r2_missing,
        r2_whitelisted=r2_whitelisted,
        r3_description_mismatch=r3,
        r4_type_mismatch=r4,
    )


# --- Report rendering -------------------------------------------------------

def _section_header(title: str, count: int, severity: str) -> str:
    return f"## {title} — {count} ({severity})\n"


def render_report(
    report: DriftReport,
    extracted_path: Path,
    yaml_path: Path,
    whitelist_path: Path | None,
    docx_count: int,
    yaml_count: int,
) -> str:
    """Wygeneruj `build/drift_report.md` jako pełen markdown."""
    today = _dt.date.today().isoformat()
    whitelist_total = len(report.r1_whitelisted) + len(report.r2_whitelisted)
    whitelist_info = (
        f"`{whitelist_path}` ({whitelist_total} matched)"
        if whitelist_path is not None and whitelist_path.exists()
        else "(none)"
    )

    lines = [
        f"# Drift Report — {today}",
        "",
        f"- **Extracted (DOCX):** `{extracted_path}` — {docx_count} abilities",
        f"- **YAML (ruleset):** `{yaml_path}` — {yaml_count} abilities",
        f"- **Whitelist:** {whitelist_info}",
        f"- **Exit code:** {report.exit_code} "
        f"({'ERROR' if report.has_errors else ('WARN' if report.has_warnings else 'CLEAN')})",
        "",
        "## Summary",
        "",
        "| Type | Description | Count | Severity | Exit contribution |",
        "|---|---|---|---|---|",
        f"| R1 | Missing in YAML (non-whitelisted) | {len(report.r1_missing_in_yaml)} | ERROR | "
        f"{'1' if report.r1_missing_in_yaml else '—'} |",
        f"| R1w | Missing in YAML (whitelisted) | {len(report.r1_whitelisted)} | INFO | — |",
        f"| R2 | Missing in DOCX (non-whitelisted) | {len(report.r2_missing_in_docx)} | WARN | "
        f"{'2' if report.r2_missing_in_docx else '—'} |",
        f"| R2w | Missing in DOCX (whitelisted) | {len(report.r2_whitelisted)} | INFO | — |",
        f"| R3 | Description mismatch | {len(report.r3_description_mismatch)} | WARN | "
        f"{'2' if report.r3_description_mismatch else '—'} |",
        f"| R4 | Type mismatch | {len(report.r4_type_mismatch)} | ERROR | "
        f"{'1' if report.r4_type_mismatch else '—'} |",
        "",
    ]

    # R1 — Missing in YAML (ERROR)
    lines.append(_section_header("R1 — Missing in YAML", len(report.r1_missing_in_yaml), "ERROR"))
    if report.r1_missing_in_yaml:
        for ab in report.r1_missing_in_yaml:
            lines.append(f"### `{ab.slug}` ({ab.name}) — `{ab.type}`")
            lines.append("")
            lines.append(f"**DOCX description:** {ab.description}")
            lines.append("")
            lines.append("**Action:** dodaj do `app/rulesets/v1/abilities.yaml` lub zarejestruj świadomy skip.")
            lines.append("")
    else:
        lines.append("_(none)_\n")

    # R1 whitelisted (INFO) — symetria do R2w
    lines.append(_section_header("R1 (whitelisted) — Missing in YAML, świadomie dozwolone", len(report.r1_whitelisted), "INFO"))
    if report.r1_whitelisted:
        for ab, entry in report.r1_whitelisted:
            until = f" (until {entry.until_date})" if entry.until_date else " (permanent)"
            lines.append(f"### `{ab.slug}` ({ab.name}) — `{ab.type}`{until}")
            lines.append("")
            lines.append(f"**Reason:** {entry.reason}")
            lines.append("")
    else:
        lines.append("_(none)_\n")

    # R2 — Missing in DOCX (WARN, non-whitelisted)
    lines.append(_section_header("R2 — Missing in DOCX", len(report.r2_missing_in_docx), "WARN"))
    if report.r2_missing_in_docx:
        for ab in report.r2_missing_in_docx:
            lines.append(f"### `{ab.slug}` ({ab.name}) — `{ab.type}`")
            lines.append("")
            lines.append(f"**YAML description:** {ab.description}")
            lines.append("")
            lines.append(
                "**Action:** dodaj wpis do `app/rulesets/v1/drift_allowlist.yaml` z uzasadnieniem "
                "(świadomy YAML-only) lub usuń z YAML."
            )
            lines.append("")
    else:
        lines.append("_(none)_\n")

    # R2 whitelisted (INFO)
    lines.append(_section_header("R2 (whitelisted) — Missing in DOCX, świadomie dozwolone", len(report.r2_whitelisted), "INFO"))
    if report.r2_whitelisted:
        for ab, entry in report.r2_whitelisted:
            until = f" (until {entry.until_date})" if entry.until_date else " (permanent)"
            lines.append(f"### `{ab.slug}` ({ab.name}) — `{ab.type}`{until}")
            lines.append("")
            lines.append(f"**Reason:** {entry.reason}")
            lines.append("")
    else:
        lines.append("_(none)_\n")

    # R3 — Description mismatch (WARN)
    lines.append(_section_header("R3 — Description mismatch", len(report.r3_description_mismatch), "WARN"))
    if report.r3_description_mismatch:
        for d, y in report.r3_description_mismatch:
            lines.append(f"### `{d.slug}` ({d.name}) — `{d.type}`")
            lines.append("")
            lines.append("**DOCX normalized:**")
            lines.append("")
            lines.append(f"> {normalize_description(d.description)}")
            lines.append("")
            lines.append("**YAML normalized:**")
            lines.append("")
            lines.append(f"> {normalize_description(y.description)}")
            lines.append("")
    else:
        lines.append("_(none)_\n")

    # R4 — Type mismatch (ERROR)
    lines.append(_section_header("R4 — Type mismatch", len(report.r4_type_mismatch), "ERROR"))
    if report.r4_type_mismatch:
        for d, y in report.r4_type_mismatch:
            lines.append(f"### `{d.slug}` ({d.name})")
            lines.append("")
            lines.append(f"- DOCX type: `{d.type}`")
            lines.append(f"- YAML type: `{y.type}`")
            lines.append("")
            lines.append("**Action:** rozstrzygnij źródło prawdy. Type mismatch zwykle sygnalizuje bug kosztu.")
            lines.append("")
    else:
        lines.append("_(none)_\n")

    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect drift between DOCX-extracted abilities and YAML ruleset (ADR-0006).",
    )
    parser.add_argument("--extracted", type=Path, default=DEFAULT_EXTRACTED)
    parser.add_argument("--yaml", type=Path, default=DEFAULT_YAML, dest="yaml_path")
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=DEFAULT_WHITELIST,
        help="Path to drift_allowlist.yaml (optional — brak pliku = pusty allowlist)",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    try:
        docx_abilities = load_abilities(args.extracted)
        yaml_abilities = load_abilities(args.yaml_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to load abilities YAML: {exc}", file=sys.stderr)
        return 1

    whitelist = load_whitelist(args.whitelist)

    report = compute_drift(docx_abilities, yaml_abilities, whitelist)

    rendered = render_report(
        report,
        extracted_path=args.extracted,
        yaml_path=args.yaml_path,
        whitelist_path=args.whitelist,
        docx_count=len(docx_abilities),
        yaml_count=len(yaml_abilities),
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(rendered)

    severity = "ERROR" if report.has_errors else ("WARN" if report.has_warnings else "CLEAN")
    print(
        f"Drift: R1={len(report.r1_missing_in_yaml)} "
        f"R1w={len(report.r1_whitelisted)} "
        f"R2={len(report.r2_missing_in_docx)} "
        f"R2w={len(report.r2_whitelisted)} "
        f"R3={len(report.r3_description_mismatch)} "
        f"R4={len(report.r4_type_mismatch)} "
        f"→ {severity} (exit {report.exit_code}) → {args.report}",
        file=sys.stderr,
    )
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
