"""C3 — testy `scripts/lookup_rule.py` (lookup reguł po `pkt X` lub słowach).

Pokrycie: parser hierarchii (punkt/litera/rzymski + myślnik 4. poziomu doklejany
do rodzica + separator spacją + tab wewnątrz tekstu), normalizacja referencji,
resolver, wyszukiwanie (fold akcentów, ranking), tryby CLI (`--list`/`--search`/
`--json`) oraz smoke na realnym `SZOP_Rozjemca.md`. Zero DB/sieci.
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
_SCRIPT = _REPO_ROOT / "scripts" / "lookup_rule.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lookup_rule", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


lr = _load_module()


# Fixtura odzwierciedlająca rzeczywiste osobliwości SZOP_Rozjemca.md:
# - punkt N. (tab po kropce), litera \ta. , rzymski \t\ti.
# - myślnik 4. poziomu (\t\t\t-) → kontynuacja tekstu rodzica
# - separator SPACJĄ w "e. " (jak realny pkt 20.e)
# - tab WEWNĄTRZ tekstu (jak realny pkt 14.e)
_FIXTURE = (
    "5.\tCele:\n"
    "\ta.\tCele rozstawia się podczas przygotowania.\n"
    "\tf.\tWygrywa gracz z większą liczbą celów.\n"
    "\n"
    "11.\tAktywacja:\n"
    "\tb.\tZwykła aktywacja:\n"
    "\t\ti.\tRozpatrujemy przerwania.\n"
    "\t\tiv.\tWracamy do pkt i, jeżeli:\n"
    "\t\t\t-\tIstnieje akcja, którą oddział może wykonać.\n"
    "\t\t\t-\tOddział wykonał mniej niż dwie akcje.\n"
    "\n"
    "20.\tPrzegrupowanie:\n"
    "\te. Jeżeli oddział ma zdolność Nieustraszony nie wykonuje testów.\n"
    "\tf.\tW zależności od liczby porażek:\n"
    "\t\ti.\tjedna: oddział zostaje Przyszpilony.\n"
    "\n"
    "14.\tAkcje:\n"
    "\te.\tAkcje specjalne: ich opis i ograniczenia\tdefiniuje zdolność.\n"
)


@pytest.fixture
def nodes():
    return lr.parse_rules(_FIXTURE)


# --- parser -------------------------------------------------------------------


def test_parse_top_letter_roman_refs(nodes):
    assert set(nodes) >= {"5", "5.a", "5.f", "11", "11.b", "11.b.i", "11.b.iv", "20.f.i"}
    assert nodes["5"].depth == 0
    assert nodes["5.a"].depth == 1
    assert nodes["11.b.i"].depth == 2


def test_parse_parent_and_children(nodes):
    assert nodes["5.a"].parent_ref == "5"
    assert nodes["11.b.i"].parent_ref == "11.b"
    assert "5.a" in nodes["5"].children and "5.f" in nodes["5"].children
    assert nodes["11.b"].children == ["11.b.i", "11.b.iv"]


def test_dash_bullets_fold_into_parent_text(nodes):
    # Myślniki 4. poziomu nie tworzą własnych referencji — są w tekście rodzica.
    iv = nodes["11.b.iv"]
    assert "Istnieje akcja" in iv.text
    assert "mniej niż dwie akcje" in iv.text
    assert not any(ref.startswith("11.b.iv.") for ref in nodes)


def test_space_separator_after_label(nodes):
    # Realny pkt 20.e używa spacji, nie taba, po "e.".
    assert "20.e" in nodes
    assert "Nieustraszony" in nodes["20.e"].text


def test_internal_tab_collapsed(nodes):
    # Tab wewnątrz tekstu (pkt 14.e) zwijany do pojedynczej spacji.
    assert "\t" not in nodes["14.e"].text
    assert "ograniczenia definiuje zdolność" in nodes["14.e"].text


def test_document_order_preserved(nodes):
    tops = [n.ref for n in nodes.values() if n.depth == 0]
    assert tops == ["5", "11", "20", "14"]  # kolejność z fixtury, nie sort


# --- normalize + resolve ------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("14.d.iv", "14.d.iv"),
        ("pkt 5.f", "5.f"),
        ("PKT 5.F", "5.f"),
        ("  20  ", "20"),
        ("11.b.", "11.b"),
        ("11. b . i", "11.b.i"),
    ],
)
def test_normalize_ref(raw, expected):
    assert lr.normalize_ref(raw) == expected


def test_resolve_existing_and_missing(nodes):
    assert lr.resolve_ref(nodes, "pkt 11.b.iv") is nodes["11.b.iv"]
    assert lr.resolve_ref(nodes, "99.z") is None


# --- search -------------------------------------------------------------------


def test_search_accent_insensitive(nodes):
    # "przegrupowanie" bez ogonków musi trafić w punkt z "Przegrupowanie".
    results = lr.search_rules(nodes, "przegrupowanie")
    refs = [n.ref for n, _ in results]
    assert "20" in refs


def test_search_requires_all_tokens(nodes):
    results = lr.search_rules(nodes, "oddział akcje")
    assert results  # 11.b.iv zawiera oba słowa
    none = lr.search_rules(nodes, "oddział zupełniebrakujące")
    assert none == []


def test_search_ranks_by_occurrence(nodes):
    results = lr.search_rules(nodes, "oddział")
    assert results
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)
    assert all(s >= 1 for s in scores)


def test_search_limit(nodes):
    assert len(lr.search_rules(nodes, "oddział", limit=1)) == 1


def test_search_empty_query(nodes):
    assert lr.search_rules(nodes, "   ") == []


# --- JSON serializery ---------------------------------------------------------


def test_resolve_to_json_has_context(nodes):
    payload = lr.resolve_to_json(nodes, nodes["11.b.i"])
    assert payload["schema"] == lr.JSON_SCHEMA
    assert payload["ref"] == "11.b.i"
    parent_refs = [p["ref"] for p in payload["parents"]]
    assert parent_refs == ["11", "11.b"]  # od najwyższego
    assert json.loads(json.dumps(payload))  # JSON round-trip


def test_node_to_json_children(nodes):
    payload = lr.node_to_json(nodes["11.b"])
    assert payload["children"] == ["11.b.i", "11.b.iv"]


# --- CLI ----------------------------------------------------------------------


def test_cli_resolve(capsys):
    rc = lr.main(["14.d.iv"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pkt 14.d.iv" in out
    assert "kontratak" in out  # treść realnego punktu


def test_cli_resolve_json(capsys):
    rc = lr.main(["5.f", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["ref"] == "5.f"
    assert "celów" in payload["text"]


def test_cli_search(capsys):
    rc = lr.main(["--search", "osłona"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "19" in out  # pkt 19 to definicja Osłony


def test_cli_search_no_results(capsys):
    rc = lr.main(["--search", "zupełniebrakującesłowo"])
    assert rc == 1
    assert "Brak punktów" in capsys.readouterr().out


def test_cli_list(capsys):
    rc = lr.main(["--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pkt 0" in out and "pkt 27" in out


def test_cli_unknown_ref(capsys):
    rc = lr.main(["99.z"])
    assert rc == 1
    assert "Nie znaleziono" in capsys.readouterr().err


def test_cli_no_args(capsys):
    rc = lr.main([])
    assert rc == 2
    assert "Podaj referencję" in capsys.readouterr().err


def test_cli_missing_rules_file(capsys):
    rc = lr.main(["5.f", "--rules-file", str(_REPO_ROOT / "nope_missing.md")])
    assert rc == 2
    assert "Nie można odczytać" in capsys.readouterr().err


# --- smoke na realnym pliku reguł --------------------------------------------


def test_real_rules_parse_smoke():
    nodes = lr.load_rules()
    # Punkty 0–27 muszą istnieć jako najwyższy poziom.
    tops = {n.ref for n in nodes.values() if n.depth == 0}
    assert {str(i) for i in range(0, 28)} <= tops
    # Znane głębokie referencje cytowane w ADR/HANDOFF.
    assert lr.resolve_ref(nodes, "14.d.iv") is not None  # kontratak
    assert lr.resolve_ref(nodes, "5.f") is not None  # koniec gry po 4 rundach
    assert lr.resolve_ref(nodes, "11.b.iv") is not None  # do 2 akcji
