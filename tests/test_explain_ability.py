"""C3 — testy `scripts/explain_ability.py` (lookup zdolności po slug/nazwie).

Pokrycie: rozpoznanie po slug i po nazwie PL (fuzzy, przez `slug_for_name`),
nieznane wejście, tryby CLI (`--list`/`--type`/`--json`), render parametru X i
flagi `blocked`. Źródło = katalog SSOT `app.data.abilities` (zero DB/I/O).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPT = _REPO_ROOT / "scripts" / "explain_ability.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("explain_ability", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ea = _load_module()


# --- resolve ------------------------------------------------------------------


def test_resolve_by_slug():
    defn = ea.resolve_ability("furia")
    assert defn is not None
    assert defn.slug == "furia"
    assert defn.name == "Furia"


def test_resolve_by_polish_name_casefold_and_diacritics():
    # Nazwa wyświetlana 'Podwójny' = slug 'rozrywajacy' (slug_for_name mapuje display name).
    assert ea.resolve_ability("Podwójny").slug == "rozrywajacy"
    # Wielkość liter / ogonki nieistotne (normalizacja w slug_for_name).
    assert ea.resolve_ability("FURIA").slug == "furia"


def test_resolve_unknown_returns_none():
    assert ea.resolve_ability("nieistniejaca_zdolnosc") is None


# --- format -------------------------------------------------------------------


def test_format_ability_shows_value_param_and_choices():
    out = ea.format_ability(ea.resolve_ability("rozprysk"))
    assert "rozprysk" in out
    assert "Parametr: X" in out
    # value_choices ("2","3","6") wypisane.
    assert "2, 3, 6" in out


def test_format_ability_marks_blocked():
    # 'masywny' (nazwa 'Sekcje') jest blocked=True w katalogu.
    out = ea.format_ability(ea.resolve_ability("masywny"))
    assert "ZABLOKOWANA" in out


def test_format_list_groups_and_counts():
    from app.data import abilities as cat

    out = ea.format_list(list(cat.all_definitions()))
    assert "passive" in out and "weapon" in out
    assert "furia" in out


# --- json ---------------------------------------------------------------------


def test_ability_to_json_has_blocked_and_core_fields():
    rec = ea.ability_to_json(ea.resolve_ability("transport"))
    assert rec["slug"] == "transport"
    assert rec["type"] == "passive"
    assert rec["blocked"] is False
    assert rec["value_label"] == "X"


# --- CLI ----------------------------------------------------------------------


def test_main_lookup_slug(capsys):
    rc = ea.main(["furia"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Furia" in out
    assert "[furia]" in out


def test_main_lookup_polish_name(capsys):
    rc = ea.main(["Furia"])
    assert rc == 0
    assert "Furia" in capsys.readouterr().out


def test_main_unknown_exit_1(capsys):
    rc = ea.main(["zupelnie_nieznane"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Nie znaleziono" in err


def test_main_no_args_exit_2(capsys):
    rc = ea.main([])
    assert rc == 2
    assert "Podaj slug" in capsys.readouterr().err


def test_main_list(capsys):
    rc = ea.main(["--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Zdolności w katalogu" in out
    assert "furia" in out


def test_main_type_filter(capsys):
    rc = ea.main(["--type", "weapon"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "weapon" in out
    assert "rozprysk" in out  # broń istnieje w katalogu


def test_main_type_unknown_exit_2(capsys):
    rc = ea.main(["--type", "nonsense"])
    assert rc == 2
    assert "Nieznany typ" in capsys.readouterr().err


def test_main_json_single_roundtrip(capsys):
    rc = ea.main(["transport", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    rec = json.loads(out)
    assert rec["slug"] == "transport"
    assert rec["blocked"] is False
    assert rec["requires_value"] is True


def test_main_json_list_is_array(capsys):
    rc = ea.main(["--list", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert any(r["slug"] == "furia" for r in data)
