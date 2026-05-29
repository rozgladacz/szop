"""A4.3 — testy `scripts/rules_classify_geometry.py`.

Pokrycie:
- `_normalize_for_match` — Polish chars → ASCII, lowercase.
- `classify_ability` — keyword matching per kategoria, multi-category.
- Sanity na real `abilities.yaml`: zwrot → facing, niebezpośredni → los_simple,
  Artyleria → range_special, Latający → movement_special.
- `excluded_in_b_mvp` flag honors category settings.
- Report rendering: 5 sekcji (Exclusion list + 7 categories + Uncategorized).
- CLI: missing input → exit 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.rulesets.models import RulesetAbility  # noqa: E402
from scripts.rules_classify_geometry import (  # noqa: E402
    CATEGORIES,
    classify_abilities,
    classify_ability,
    load_abilities,
    main,
    render_report,
    _normalize_for_match,
)


REAL_YAML = ROOT_DIR / "app" / "rulesets" / "v1" / "abilities.yaml"


# --- Normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("zwrot przód tył lewo prawo", "zwrot przod tyl lewo prawo"),
        ("Łatwy ŚCIĘŻAJ", "latwy sciezaj"),
        ("Ostrożny", "ostrozny"),
        # NFKD: ż → z, ł → l (via pre-replace), ąć → ac
        ("Niewrażliwy", "niewrazliwy"),
        ("Mistrzostwo(X)", "mistrzostwo(x)"),
    ],
)
def test_normalize_for_match(raw: str, expected: str) -> None:
    assert _normalize_for_match(raw) == expected


# --- Classification on synthetic abilities ---------------------------------


def _ability(slug: str, description: str, type_: str = "passive") -> RulesetAbility:
    return RulesetAbility(slug=slug, name=slug.title(), type=type_, description=description)


def test_classify_facing_keyword_zwrot() -> None:
    """Reference do `Zwrot` w opisie innej zdolności → facing category."""
    ab = _ability("test", "Otrzymuje zdolność Zwrot na czas aktywacji.")
    result = classify_ability(ab)
    assert "facing" in result.categories
    assert result.excluded_in_b_mvp is True


def test_classify_facing_keyword_directional() -> None:
    """Strefy kierunkowe (przód/tył/lewo/prawo) → facing."""
    ab = _ability("zwrot", "Wyznacza 4 strefy: przód, tył, lewo, prawo.")
    result = classify_ability(ab)
    assert "facing" in result.categories
    assert result.excluded_in_b_mvp is True


def test_classify_facing_keyword_strefy() -> None:
    """`strefy` → facing (zones)."""
    ab = _ability("test", "Atakujący w tylnej strefie ma -1.")
    result = classify_ability(ab)
    assert "facing" in result.categories
    assert result.excluded_in_b_mvp is True


def test_classify_per_model_rozdziela() -> None:
    ab = _ability("precyzyjny", "Atakujący rozdziela rany.", type_="weapon")
    result = classify_ability(ab)
    assert "per_model" in result.categories
    assert result.excluded_in_b_mvp is True


def test_classify_los_simple_wysoki() -> None:
    ab = _ability("wysoki", "Sprawdza linię wzroku jakby był na podwyższeniu.")
    result = classify_ability(ab)
    assert "los_simple" in result.categories
    assert result.excluded_in_b_mvp is False


def test_classify_los_simple_niebezposredni() -> None:
    ab = _ability("niebezposredni", "Nie wymaga linii wzroku.", type_="weapon")
    result = classify_ability(ab)
    assert "los_simple" in result.categories
    assert result.excluded_in_b_mvp is False


def test_classify_range_special_artyleria() -> None:
    ab = _ability("artyleria", "Każdy oddział w zasięgu 12 od sojuszniczego oddziału jest w zasięgu.", type_="weapon")
    result = classify_ability(ab)
    assert "range_special" in result.categories


def test_classify_movement_special_latajacy() -> None:
    ab = _ability("latajacy", "Ignoruje teren i jednostki podczas ruchu.")
    result = classify_ability(ab)
    assert "movement_special" in result.categories


def test_classify_movement_special_samolot_linia() -> None:
    ab = _ability("samolot", "Musi wykonać ruch i przemieścić się w jednej linii.")
    result = classify_ability(ab)
    assert "movement_special" in result.categories


def test_classify_placement_zasadzka() -> None:
    ab = _ability("zasadzka", "Nie rozstawia się przed grą.")
    result = classify_ability(ab)
    assert "placement_special" in result.categories
    assert result.excluded_in_b_mvp is False


def test_classify_uncategorized() -> None:
    """Ability bez geometric keywords → empty categories, no excluded."""
    ab = _ability("nieustraszony", "Wykonuje jeden test przegrupowania mniej.")
    result = classify_ability(ab)
    assert result.categories == ()
    assert result.matched_keywords == {}
    assert result.excluded_in_b_mvp is False


def test_classify_multi_category() -> None:
    """Ability może trafić w wiele kategorii — wszystkie raportowane."""
    ab = _ability(
        "multi",
        "Wybiera strefę przód i rozdziela rany.",
    )
    result = classify_ability(ab)
    assert "facing" in result.categories
    assert "per_model" in result.categories
    assert result.excluded_in_b_mvp is True


# --- Real YAML sanity -------------------------------------------------------


@pytest.fixture(scope="module")
def real_abilities() -> list[RulesetAbility]:
    return load_abilities(REAL_YAML)


@pytest.fixture(scope="module")
def real_classified(real_abilities) -> list:
    return classify_abilities(real_abilities)


def test_real_zwrot_classified_as_facing(real_classified) -> None:
    """`zwrot` w real YAML musi trafić w facing + B MVP excluded (sanity z HANDOFF)."""
    by_slug = {c.slug: c for c in real_classified}
    assert "zwrot" in by_slug
    assert "facing" in by_slug["zwrot"].categories
    assert by_slug["zwrot"].excluded_in_b_mvp is True


def test_real_precyzyjny_excluded(real_classified) -> None:
    by_slug = {c.slug: c for c in real_classified}
    assert "precyzyjny" in by_slug
    assert by_slug["precyzyjny"].excluded_in_b_mvp is True


def test_real_artyleria_range_special(real_classified) -> None:
    by_slug = {c.slug: c for c in real_classified}
    assert "artyleria" in by_slug
    assert "range_special" in by_slug["artyleria"].categories


def test_real_latajacy_movement(real_classified) -> None:
    by_slug = {c.slug: c for c in real_classified}
    assert "latajacy" in by_slug
    assert "movement_special" in by_slug["latajacy"].categories


def test_real_excluded_count_reasonable(real_classified) -> None:
    """SZOP nie jest gemoetrycznie ciężki — excluded list powinien być mały (<10)."""
    excluded = [c for c in real_classified if c.excluded_in_b_mvp]
    assert 1 <= len(excluded) <= 10, f"Expected 1-10 excluded, got {len(excluded)}: {[c.slug for c in excluded]}"


def test_real_uncategorized_majority(real_classified) -> None:
    """Większość abilities nie ma geometric concerns (oczekiwane ~70% uncategorized)."""
    uncategorized = [c for c in real_classified if not c.categories]
    assert len(uncategorized) >= len(real_classified) * 0.5


# --- Report rendering ------------------------------------------------------


def test_render_report_contains_all_sections(real_classified) -> None:
    rendered = render_report(real_classified, Path("test.yaml"))
    assert "# Geometric Classification" in rendered
    assert "## B MVP Exclusion List" in rendered
    assert "## Per-category breakdown" in rendered
    assert "## Uncategorized" in rendered
    for cat in CATEGORIES:
        assert f"`{cat.name}`" in rendered


def test_render_report_has_zwrot_in_exclusion_table(real_classified) -> None:
    rendered = render_report(real_classified, Path("test.yaml"))
    # Exclusion table should reference zwrot
    assert "zwrot" in rendered.lower()


# --- CLI -------------------------------------------------------------------


def test_cli_clean_run(tmp_path: Path) -> None:
    """CLI run on real YAML → exit 0 + file created."""
    output = tmp_path / "classification.md"
    rc = main(["--input", str(REAL_YAML), "--output", str(output)])
    assert rc == 0
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "# Geometric Classification" in content


def test_cli_missing_input_exit_1(tmp_path: Path) -> None:
    output = tmp_path / "out.md"
    rc = main(["--input", str(tmp_path / "missing.yaml"), "--output", str(output)])
    assert rc == 1


def test_cli_with_minimal_yaml(tmp_path: Path) -> None:
    """Custom YAML z 1 ability → classifier działa na arbitrary input."""
    input_path = tmp_path / "abilities.yaml"
    input_path.write_text(
        yaml.safe_dump({
            "version": 1,
            "abilities": [
                {"slug": "test", "name": "Test", "type": "passive", "description": "Wybiera w którą stronę jest zwrócony."},
            ],
        }, allow_unicode=True),
        encoding="utf-8",
    )
    output = tmp_path / "out.md"
    rc = main(["--input", str(input_path), "--output", str(output)])
    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "test" in content.lower()
