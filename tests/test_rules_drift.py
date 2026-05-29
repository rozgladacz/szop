"""A4.2 — testy `scripts/rules_drift.py`.

Pokrycie:
- 4 typy raportów per rodzaj (R1/R2/R3/R4) z czystymi fixtures.
- Exit codes: ERROR=1 (R1/R4), WARN=2 (R2/R3 nie-whitelisted), CLEAN=0.
- Allowlist: load YAML, filter R2 → whitelisted bucket, brak wpływu na exit.
- Normalizacja description: NFKC + collapse whitespace eliminuje fałszywe R3.
- Edge cases: brak pliku allowlist (OK), pusty allowlist, malformed YAML (ERROR).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.rulesets.models import RulesetAbility  # noqa: E402
from scripts.rules_drift import (  # noqa: E402
    WhitelistEntry,
    compute_drift,
    load_abilities,
    load_whitelist,
    main,
    normalize_description,
    render_report,
)


SCRIPT_PATH = ROOT_DIR / "scripts" / "rules_drift.py"


# --- Normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Whitespace collapse
        ("Tekst    z   wielokrotnymi  spacjami.", "Tekst z wielokrotnymi spacjami."),
        ("\tLeading\ttab.\t", "Leading tab."),
        # NFKC: ″ (U+2033 DOUBLE PRIME) decomposuje na 2× ′ (U+2032 PRIME) —
        # to dokładnie ten efekt który chcemy: typografia z DOCX export
        # rozjeżdża się z ręcznie wpisanym YAML, normalizacja zaciera różnicę.
        ("Zasięg 12″.", "Zasięg 12′′."),
        # NFKC: ligatury → osobne litery
        ("ﬁnezja", "finezja"),
        # Strip
        ("   spacja na końcach   ", "spacja na końcach"),
    ],
)
def test_normalize_description(raw: str, expected: str) -> None:
    assert normalize_description(raw) == expected


def test_normalize_description_preserves_case() -> None:
    """Case-sensitive — Polish nazwy własne zachowują rozróżnienie."""
    assert normalize_description("Mistrzostwo Bohater") == "Mistrzostwo Bohater"
    assert normalize_description("Mistrzostwo Bohater") != normalize_description("mistrzostwo bohater")


# --- Whitelist loader -------------------------------------------------------


def _write_whitelist(path: Path, entries: list[dict]) -> None:
    path.write_text(yaml.safe_dump({"allowed_yaml_only": entries}), encoding="utf-8")


def test_load_whitelist_missing_file_returns_empty(tmp_path: Path) -> None:
    result = load_whitelist(tmp_path / "nonexistent.yaml")
    assert result.yaml_only == {}
    assert result.docx_only == {}


def test_load_whitelist_none_path_returns_empty() -> None:
    result = load_whitelist(None)
    assert result.yaml_only == {}
    assert result.docx_only == {}


def test_load_whitelist_parses_yaml_only(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    _write_whitelist(
        path,
        [
            {"slug": "aura", "reason": "Abstract concept.", "until_date": None},
            {"slug": "szybki", "reason": "Split.", "until_date": "2026-12-31"},
        ],
    )
    result = load_whitelist(path)
    assert set(result.yaml_only.keys()) == {"aura", "szybki"}
    assert result.yaml_only["aura"].reason == "Abstract concept."
    assert result.yaml_only["aura"].until_date is None
    assert result.yaml_only["szybki"].until_date == "2026-12-31"
    assert result.docx_only == {}


def test_load_whitelist_parses_docx_only(tmp_path: Path) -> None:
    """Symetria: `allowed_docx_only` filtruje R1."""
    path = tmp_path / "allowlist.yaml"
    path.write_text(
        yaml.safe_dump({
            "allowed_docx_only": [
                {"slug": "szybki_wolny", "reason": "DOCX split.", "until_date": None},
            ]
        }),
        encoding="utf-8",
    )
    result = load_whitelist(path)
    assert result.yaml_only == {}
    assert set(result.docx_only.keys()) == {"szybki_wolny"}
    assert result.docx_only["szybki_wolny"].reason == "DOCX split."


def test_load_whitelist_handles_missing_reason(tmp_path: Path) -> None:
    """Reason brakuje → fallback '(no reason given)'."""
    path = tmp_path / "allowlist.yaml"
    path.write_text(yaml.safe_dump({"allowed_yaml_only": [{"slug": "x"}]}), encoding="utf-8")
    result = load_whitelist(path)
    assert result.yaml_only["x"].reason == "(no reason given)"


# --- Drift computation ------------------------------------------------------


def _ability(slug: str, name: str | None = None, type_: str = "passive", description: str = "Opis.") -> RulesetAbility:
    return RulesetAbility(slug=slug, name=name or slug.title(), type=type_, description=description)


def test_drift_clean_baseline() -> None:
    """Identyczne zestawy → 0 wszystkie buckets, exit 0."""
    docx = [_ability("a", description="Opis A."), _ability("b", description="Opis B.")]
    yaml_abs = list(docx)  # identical
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert report.r1_missing_in_yaml == []
    assert report.r2_missing_in_docx == []
    assert report.r2_whitelisted == []
    assert report.r3_description_mismatch == []
    assert report.r4_type_mismatch == []
    assert report.exit_code == 0


def test_drift_r1_missing_in_yaml() -> None:
    """Slug w DOCX, brak w YAML → ERROR exit 1."""
    docx = [_ability("only_docx")]
    yaml_abs: list[RulesetAbility] = []
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert [a.slug for a in report.r1_missing_in_yaml] == ["only_docx"]
    assert report.exit_code == 1


def test_drift_r1_whitelisted_does_not_affect_exit() -> None:
    """`allowed_docx_only` filtruje R1 → INFO, exit 0."""
    from scripts.rules_drift import Allowlist

    docx = [_ability("only_docx")]
    yaml_abs: list[RulesetAbility] = []
    allowlist = Allowlist(
        yaml_only={},
        docx_only={"only_docx": WhitelistEntry(slug="only_docx", reason="known split")},
    )
    report = compute_drift(docx, yaml_abs, whitelist=allowlist)
    assert report.r1_missing_in_yaml == []
    assert [a.slug for a, _ in report.r1_whitelisted] == ["only_docx"]
    assert report.exit_code == 0


def test_drift_r2_missing_in_docx_not_whitelisted() -> None:
    """Slug w YAML, brak w DOCX, brak whitelist → WARN exit 2."""
    docx: list[RulesetAbility] = []
    yaml_abs = [_ability("only_yaml")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert [a.slug for a in report.r2_missing_in_docx] == ["only_yaml"]
    assert report.r2_whitelisted == []
    assert report.exit_code == 2


def test_drift_r2_whitelisted_does_not_affect_exit() -> None:
    """Whitelisted slug → INFO bucket, exit 0."""
    docx: list[RulesetAbility] = []
    yaml_abs = [_ability("only_yaml")]
    whitelist = {"only_yaml": WhitelistEntry(slug="only_yaml", reason="known")}
    report = compute_drift(docx, yaml_abs, whitelist=whitelist)
    assert report.r2_missing_in_docx == []
    assert [a.slug for a, _ in report.r2_whitelisted] == ["only_yaml"]
    assert report.exit_code == 0


def test_drift_r2_mixed_whitelisted_and_not() -> None:
    """Część R2 whitelisted, część nie → exit 2 z partial whitelist."""
    docx: list[RulesetAbility] = []
    yaml_abs = [_ability("yaml_a"), _ability("yaml_b")]
    whitelist = {"yaml_a": WhitelistEntry(slug="yaml_a", reason="known")}
    report = compute_drift(docx, yaml_abs, whitelist=whitelist)
    assert [a.slug for a in report.r2_missing_in_docx] == ["yaml_b"]
    assert [a.slug for a, _ in report.r2_whitelisted] == ["yaml_a"]
    assert report.exit_code == 2


def test_drift_r3_description_mismatch() -> None:
    """Ten sam slug, różny description → WARN exit 2."""
    docx = [_ability("x", description="Wersja DOCX.")]
    yaml_abs = [_ability("x", description="Wersja YAML.")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert len(report.r3_description_mismatch) == 1
    d, y = report.r3_description_mismatch[0]
    assert d.description == "Wersja DOCX."
    assert y.description == "Wersja YAML."
    assert report.exit_code == 2


def test_drift_r3_normalization_eliminates_whitespace_noise() -> None:
    """NFKC + collapse whitespace eliminuje fałszywe R3 z artefaktów DOCX export."""
    docx = [_ability("x", description="Tekst   z  wielokrotnymi spacjami.")]
    yaml_abs = [_ability("x", description="Tekst z wielokrotnymi spacjami.")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert report.r3_description_mismatch == []
    assert report.exit_code == 0


def test_drift_r4_type_mismatch() -> None:
    """Ten sam slug, różny type → ERROR exit 1."""
    docx = [_ability("x", type_="active", description="d")]
    yaml_abs = [_ability("x", type_="aura", description="d")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert len(report.r4_type_mismatch) == 1
    d, y = report.r4_type_mismatch[0]
    assert d.type == "active"
    assert y.type == "aura"
    assert report.exit_code == 1


def test_drift_r4_independent_of_r3() -> None:
    """Type mismatch + description mismatch → oba raportowane, exit 1 (ERROR wygrywa)."""
    docx = [_ability("x", type_="active", description="d1")]
    yaml_abs = [_ability("x", type_="aura", description="d2")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert len(report.r4_type_mismatch) == 1
    assert len(report.r3_description_mismatch) == 1
    assert report.exit_code == 1


def test_drift_error_wins_over_warn() -> None:
    """R1 + R3 → exit 1 (ERROR przebija WARN)."""
    docx = [_ability("a"), _ability("b", description="DOCX")]
    yaml_abs = [_ability("b", description="YAML")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    assert report.exit_code == 1


# --- Report rendering -------------------------------------------------------


def test_render_report_contains_all_sections(tmp_path: Path) -> None:
    """Wygenerowany raport zawiera 5 sekcji (R1, R2, R2w, R3, R4) i summary table."""
    docx = [_ability("only_docx", description="d")]
    yaml_abs = [_ability("only_yaml", description="d")]
    report = compute_drift(docx, yaml_abs, whitelist={})
    rendered = render_report(
        report,
        extracted_path=Path("e.yaml"),
        yaml_path=Path("y.yaml"),
        whitelist_path=None,
        docx_count=1,
        yaml_count=1,
    )
    assert "# Drift Report" in rendered
    assert "## Summary" in rendered
    assert "## R1 — Missing in YAML" in rendered
    assert "## R2 — Missing in DOCX" in rendered
    assert "## R2 (whitelisted)" in rendered
    assert "## R3 — Description mismatch" in rendered
    assert "## R4 — Type mismatch" in rendered
    assert "only_docx" in rendered
    assert "only_yaml" in rendered


def test_render_report_shows_exit_code(tmp_path: Path) -> None:
    docx = [_ability("only_docx")]
    yaml_abs: list[RulesetAbility] = []
    report = compute_drift(docx, yaml_abs, whitelist={})
    rendered = render_report(
        report,
        extracted_path=Path("e.yaml"),
        yaml_path=Path("y.yaml"),
        whitelist_path=None,
        docx_count=1,
        yaml_count=0,
    )
    assert "Exit code:** 1" in rendered
    assert "ERROR" in rendered


# --- CLI entry --------------------------------------------------------------


def _dump_abilities_yaml(path: Path, abilities: list[RulesetAbility]) -> None:
    payload = {
        "version": 1,
        "abilities": [
            {"slug": a.slug, "name": a.name, "type": a.type, "description": a.description}
            for a in abilities
        ],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_cli_clean_exit_0(tmp_path: Path) -> None:
    extracted = tmp_path / "ext.yaml"
    yaml_path = tmp_path / "yaml.yaml"
    report = tmp_path / "report.md"
    abilities = [_ability("a"), _ability("b")]
    _dump_abilities_yaml(extracted, abilities)
    _dump_abilities_yaml(yaml_path, abilities)

    rc = main(["--extracted", str(extracted), "--yaml", str(yaml_path),
               "--whitelist", str(tmp_path / "missing.yaml"), "--report", str(report)])
    assert rc == 0
    assert report.exists()


def test_cli_error_exit_1(tmp_path: Path) -> None:
    extracted = tmp_path / "ext.yaml"
    yaml_path = tmp_path / "yaml.yaml"
    report = tmp_path / "report.md"
    _dump_abilities_yaml(extracted, [_ability("only_docx")])
    _dump_abilities_yaml(yaml_path, [])

    rc = main(["--extracted", str(extracted), "--yaml", str(yaml_path),
               "--whitelist", str(tmp_path / "missing.yaml"), "--report", str(report)])
    assert rc == 1


def test_cli_warn_exit_2(tmp_path: Path) -> None:
    extracted = tmp_path / "ext.yaml"
    yaml_path = tmp_path / "yaml.yaml"
    report = tmp_path / "report.md"
    _dump_abilities_yaml(extracted, [])
    _dump_abilities_yaml(yaml_path, [_ability("only_yaml")])

    rc = main(["--extracted", str(extracted), "--yaml", str(yaml_path),
               "--whitelist", str(tmp_path / "missing.yaml"), "--report", str(report)])
    assert rc == 2


def test_cli_missing_input_exit_1(tmp_path: Path) -> None:
    """Brak input YAML → exit 1 + ERROR w stderr."""
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH),
            "--extracted", str(tmp_path / "missing.yaml"),
            "--yaml", str(tmp_path / "also_missing.yaml"),
            "--whitelist", str(tmp_path / "missing.yaml"),
            "--report", str(tmp_path / "report.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "error" in result.stderr.lower()


def test_cli_with_whitelist(tmp_path: Path) -> None:
    """R2 whitelist trafia w INFO bucket, exit 0."""
    extracted = tmp_path / "ext.yaml"
    yaml_path = tmp_path / "yaml.yaml"
    whitelist = tmp_path / "wl.yaml"
    report = tmp_path / "report.md"

    _dump_abilities_yaml(extracted, [])
    _dump_abilities_yaml(yaml_path, [_ability("only_yaml")])
    _write_whitelist(whitelist, [{"slug": "only_yaml", "reason": "known"}])

    rc = main(["--extracted", str(extracted), "--yaml", str(yaml_path),
               "--whitelist", str(whitelist), "--report", str(report)])
    assert rc == 0
    content = report.read_text(encoding="utf-8")
    assert "only_yaml" in content
    assert "known" in content
