"""Testy dla `scripts/rules_extract_md.py`.

Pokrycie:
- Real `SZOP_Zdolnosci.md` sanity (count w sensownym zakresie, types, unique slugs).
- Golden test z minimalną programmatic MD fixture w `tmp_path`.
- Section detection (Pasywne/Aktywne/Aury/Broni mapowane na English types).
- Multi-line `opis:` (continuation lines).
- Edge: ignorowanie `## Konwencje` / `### Tagi dla...`.
- Edge: brak `- typ:` field → fallback na section type.
- CLI: error 1 gdy brak input.
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
from scripts.rules_extract_md import (  # noqa: E402
    extract_abilities_md,
    main,
)

SCRIPT_PATH = ROOT_DIR / "scripts" / "rules_extract_md.py"
REAL_MD = ROOT_DIR / "app" / "static" / "docs" / "SZOP_Zdolnosci.md"


# --- Real MD sanity ---------------------------------------------------------


@pytest.fixture(scope="module")
def real_md_abilities() -> list[RulesetAbility]:
    return extract_abilities_md(REAL_MD)


def test_real_md_count_in_expected_range(real_md_abilities: list) -> None:
    """Sanity: SZOP_Zdolnosci.md ma ~77 abilities (zgodne z DOCX state)."""
    n = len(real_md_abilities)
    assert 70 <= n <= 100, f"Expected 70-100 abilities, got {n} — parser regression?"


def test_real_md_all_slugs_unique(real_md_abilities: list) -> None:
    slugs = [a.slug for a in real_md_abilities]
    assert len(slugs) == len(set(slugs)), "Duplicate slugs in MD extract"


def test_real_md_all_fields_nonempty(real_md_abilities: list) -> None:
    for ab in real_md_abilities:
        assert ab.slug
        assert ab.name
        assert ab.description
        assert len(ab.description) >= 5, f"Suspiciously short desc for {ab.slug}: {ab.description!r}"


def test_real_md_types_from_valid_set(real_md_abilities: list) -> None:
    valid_types = {"passive", "active", "aura", "weapon"}
    for ab in real_md_abilities:
        assert ab.type in valid_types


def test_real_md_known_abilities_present(real_md_abilities: list) -> None:
    """Smoke: kilka stabilnych zdolności musi być w MD."""
    slugs = {a.slug for a in real_md_abilities}
    must_have = {"bastion", "bohater", "transport", "mag", "ap"}
    missing = must_have - slugs
    assert not missing, f"Missing core abilities: {missing}"


def test_real_md_type_distribution(real_md_abilities: list) -> None:
    """Passive >= 30, weapon >= 15, active + aura >= 5."""
    by_type: dict[str, int] = {}
    for ab in real_md_abilities:
        by_type[ab.type] = by_type.get(ab.type, 0) + 1
    assert by_type.get("passive", 0) >= 30
    assert by_type.get("weapon", 0) >= 15
    assert by_type.get("active", 0) + by_type.get("aura", 0) >= 5


# --- Golden programmatic fixture --------------------------------------------


@pytest.fixture
def minimal_md(tmp_path: Path) -> Path:
    """Minimal MD fixture z 4 zdolnościami (po 1 per type) + Konwencje (ignored)."""
    content = """# SZOP — Test fixture

## Konwencje

Ignored preamble section.

### Tagi dla zdolności pasywnych
Ignored.

## Pasywne

### 1. AbilityA
- typ: pasywna
- opis: "Pierwsza zdolność testowa."
- inne pola: ignored

### 2. AbilityB(X)
- typ: pasywna
- opis: "Druga z parametrem."

## Aktywne

### 3. AbilityC
- typ: aktywna
- opis: "Trzecia aktywna."

## Aury

### 4. AbilityD
- typ: aura
- opis: "Czwarta jako aura."

## Broni

### 5. AbilityE
- typ: broni
- opis: "Piąta jako broń."
"""
    path = tmp_path / "minimal.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_golden_minimal_md(minimal_md: Path) -> None:
    abilities = extract_abilities_md(minimal_md)

    assert len(abilities) == 5

    by_name = {a.name: a for a in abilities}
    assert by_name["AbilityA"].type == "passive"
    assert by_name["AbilityA"].slug == "abilitya"
    assert by_name["AbilityA"].description == "Pierwsza zdolność testowa."

    assert by_name["AbilityB(X)"].type == "passive"
    assert by_name["AbilityB(X)"].slug == "abilityb"

    assert by_name["AbilityC"].type == "active"
    assert by_name["AbilityD"].type == "aura"
    assert by_name["AbilityE"].type == "weapon"


def test_konwencje_section_ignored(tmp_path: Path) -> None:
    """`## Konwencje` z `### Tagi...` headers nie powinny tworzyć abilities."""
    content = """## Konwencje

### Tagi dla zdolności pasywnych

Some text.

### Tagi dla zdolności broni

More text.

## Pasywne

### 1. RealAbility
- typ: pasywna
- opis: "Real one."
"""
    path = tmp_path / "konwencje.md"
    path.write_text(content, encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert len(abilities) == 1
    assert abilities[0].name == "RealAbility"


def test_multiline_opis(tmp_path: Path) -> None:
    """`opis:` może mieć kontynuację w następnej linii — łączymy do końca pola."""
    content = """## Pasywne

### 1. MultiLine
- typ: pasywna
- opis: "Pierwsza linia opisu
  kontynuacja drugiej
  i trzecia linia."
- inne_pole: ignored
"""
    path = tmp_path / "multiline.md"
    path.write_text(content, encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert len(abilities) == 1
    desc = abilities[0].description
    assert "Pierwsza linia" in desc
    assert "kontynuacja drugiej" in desc
    assert "i trzecia linia" in desc


def test_typ_fallback_to_section(tmp_path: Path) -> None:
    """Brak `- typ:` field → fallback na section type."""
    content = """## Aktywne

### 1. NoTypField
- opis: "Brak typu."
"""
    path = tmp_path / "no_typ.md"
    path.write_text(content, encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert len(abilities) == 1
    assert abilities[0].type == "active"  # z section


def test_empty_opis_skipped(tmp_path: Path) -> None:
    """Ability bez `opis:` field → nie dodajemy do output (niekompletna)."""
    content = """## Pasywne

### 1. NoOpis
- typ: pasywna

### 2. HasOpis
- typ: pasywna
- opis: "Z opisem."
"""
    path = tmp_path / "no_opis.md"
    path.write_text(content, encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert len(abilities) == 1
    assert abilities[0].name == "HasOpis"


def test_polish_chars_in_name(tmp_path: Path) -> None:
    """Polish chars w name muszą produkować poprawny slug (NFKD + Ł/ł)."""
    content = """## Pasywne

### 1. Łatwy/żółty Ółówek
- typ: pasywna
- opis: "Polish."
"""
    path = tmp_path / "polish.md"
    path.write_text(content, encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert len(abilities) == 1
    assert abilities[0].slug == "latwy_zolty_olowek"


# --- CLI smoke -------------------------------------------------------------


def test_golden_cli_smoke(minimal_md: Path, tmp_path: Path) -> None:
    output = tmp_path / "out.yaml"
    rc = main(["--input", str(minimal_md), "--output", str(output)])
    assert rc == 0
    assert output.exists()

    with open(output, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["version"] == 1
    assert "source" in data
    assert len(data["abilities"]) == 5


def test_cli_missing_input_exit_1(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH),
            "--input", str(tmp_path / "missing.md"),
            "--output", str(tmp_path / "out.yaml"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "error" in result.stderr.lower()


def test_empty_md_returns_empty_list(tmp_path: Path) -> None:
    """MD bez section headers → empty list."""
    path = tmp_path / "empty.md"
    path.write_text("# Just a title\n\nNo sections.\n", encoding="utf-8")
    abilities = extract_abilities_md(path)
    assert abilities == []
