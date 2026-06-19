"""D2 — testy generatora raportu balansu (`scripts/balance_report.py`).

Pokrywa: round-robin shape, render markdown (tabela + cytat pkt 5.f + wykresy),
helper `_bar`, ścieżka domyślna raportu, zapis pliku, determinizm, CLI smoke,
walidacja CLI. Skrypt-liść nad `balance_simulate.py` — testy nie dotykają DB
ani kosztów. Liczba gier trzymana mała (szybkość).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "balance_report.py"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"


def _load_module():
    """Ładuje skrypt jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("balance_report", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


br = _load_module()


def _config(**overrides):
    base = dict(
        n_games=2,
        base_seed=0,
        fixtures=(str(_FIXTURE),),
        player_kinds=("random", "greedy"),
        generated_at="2026-06-10",
    )
    base.update(overrides)
    return br.ReportConfig(**base)


# --- round-robin -------------------------------------------------------------


def test_player_matchups_combinations_with_replacement():
    pairs = br.player_matchups(("random", "greedy", "priority"))
    # n(n+1)/2 = 6 par dla 3 botów (z mirrorem w win_rate_p0/p1)
    assert len(pairs) == 6
    assert ("random", "random") in pairs
    assert ("random", "greedy") in pairs
    assert ("greedy", "random") not in pairs  # tylko jeden kierunek


def test_run_round_robin_shape():
    cfg = _config(player_kinds=("random", "greedy"))
    results = br.run_round_robin(cfg)
    # 1 fixtura × 3 pary (rr,rg,gg) = 3 wyniki
    assert len(results) == 3
    assert {r.fixture_name for r in results}  # ma nazwę
    for r in results:
        assert r.n_games == 2
        assert r.wins_p0 + r.wins_p1 + r.draws == 2


def test_run_round_robin_two_fixtures():
    cfg = _config(
        fixtures=(str(_FIXTURE), str(_FIXTURE)), player_kinds=("random", "greedy")
    )
    results = br.run_round_robin(cfg)
    assert len(results) == 6  # 2 fixtury × 3 pary


def test_run_round_robin_deterministic():
    cfg = _config()
    r1 = br.run_round_robin(cfg)
    r2 = br.run_round_robin(cfg)
    assert r1 == r2


# --- mapy generowane (--map) --------------------------------------------------


def test_resolve_fixtures_fixtures_only():
    cfg = _config()
    assert len(br.resolve_fixtures(cfg)) == 1


def test_resolve_fixtures_combines_fixtures_and_maps():
    cfg = _config(maps=("lustrzana_a",), map_seed=2)
    fixtures = br.resolve_fixtures(cfg)
    assert len(fixtures) == 2  # 1 fixtura + 1 mapa
    assert all(f.name for f in fixtures)


def test_run_round_robin_with_map():
    cfg = _config(fixtures=(), maps=("lustrzana_a",), player_kinds=("random", "greedy"))
    results = br.run_round_robin(cfg)
    assert len(results) == 3  # 1 mapa × 3 pary (rr, rg, gg — with replacement)
    for r in results:
        assert r.wins_p0 + r.wins_p1 + r.draws == 2


def test_run_round_robin_map_deterministic_per_seed():
    cfg = _config(fixtures=(), maps=("lustrzana_a",), map_seed=9)
    assert br.run_round_robin(cfg) == br.run_round_robin(cfg)


def test_format_report_lists_maps_in_metadata():
    cfg = _config(fixtures=(), maps=("symetryczna_a",), map_seed=3)
    md = br.format_markdown_report(br.run_round_robin(cfg), cfg)
    assert "Mapy generowane (seed `3`)" in md
    assert "`symetryczna_a`" in md


def test_parse_map_list_rejects_unknown():
    with pytest.raises(Exception):
        br._parse_map_list("nieistniejaca_mapa")


def test_main_map_only_skips_default_fixtures(tmp_path):
    out = tmp_path / "rep.md"
    rc = br.main(
        ["--map", "lustrzana_a", "-n", "2", "--players", "random,greedy", "--out", str(out)]
    )
    assert rc == 0
    assert "Mapy generowane" in out.read_text(encoding="utf-8")


def test_main_rejects_unknown_map():
    with pytest.raises(SystemExit):
        br.main(["--map", "nieistniejaca", "-n", "1"])


# --- _bar --------------------------------------------------------------------


def test_bar_length_and_fill():
    assert len(br._bar(0.5, width=10)) == 10
    assert br._bar(0.0, width=10) == "░" * 10
    assert br._bar(1.0, width=10) == "█" * 10
    assert br._bar(0.5, width=10) == "█████░░░░░"


def test_bar_clamps_out_of_range():
    assert br._bar(-1.0, width=8) == "░" * 8
    assert br._bar(2.0, width=8) == "█" * 8


# --- render ------------------------------------------------------------------


def test_format_markdown_report_structure():
    cfg = _config()
    results = br.run_round_robin(cfg)
    md = br.format_markdown_report(results, cfg)
    assert md.startswith("# Raport balansu — 2026-06-10")
    assert "pkt 5.f" in md  # cytat reguły zwycięzcy
    assert "## Fixtura:" in md
    assert "| P0 | P1 | Gier | P0 % | P1 % | Remis % | Śr. rund |" in md
    assert "### Wykresy win-rate" in md
    assert "vs" in md
    # wykresy używają unicode słupków
    assert "█" in md or "░" in md
    # boty wymienione w metadanych
    assert "`random`" in md and "`greedy`" in md


def test_format_markdown_groups_by_fixture():
    cfg = _config(fixtures=(str(_FIXTURE), str(_FIXTURE)))
    results = br.run_round_robin(cfg)
    md = br.format_markdown_report(results, cfg)
    # ta sama fixtura 2× → 1 nazwa (dedupe w _fixture_names_in_order)
    assert md.count("## Fixtura:") == 1


def test_fixture_names_in_order_dedup():
    class _R:
        def __init__(self, name):
            self.fixture_name = name

    rs = [_R("a"), _R("b"), _R("a"), _R("c")]
    assert br._fixture_names_in_order(rs) == ["a", "b", "c"]


# --- ścieżka / zapis ---------------------------------------------------------


def test_default_report_path_format():
    p = br.default_report_path("2026-06-10")
    assert p.name == "2026-06-10.md"
    assert p.parent.name == "balance"
    assert p.parent.parent.name == "reports"


def test_default_report_path_uses_today_when_none():
    p = br.default_report_path()
    assert p.name.endswith(".md")
    assert len(p.stem) == 10  # YYYY-MM-DD


def test_write_report_creates_file(tmp_path):
    out = tmp_path / "sub" / "report.md"
    br.write_report("# hello\n", out)
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "# hello\n"


# --- CLI ---------------------------------------------------------------------


def test_cli_smoke_writes_report(tmp_path, capsys):
    out = tmp_path / "rep.md"
    rc = br.main(["-n", "2", "--players", "random,greedy", "--fixtures", str(_FIXTURE), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "# Raport balansu" in content
    assert "pkt 5.f" in content
    printed = capsys.readouterr().out
    assert "Raport zapisany" in printed


def test_cli_rejects_bad_player():
    with pytest.raises(SystemExit):
        br.main(["-n", "2", "--players", "random,nieistniejacy_bot"])


def test_cli_rejects_single_player():
    with pytest.raises(SystemExit):
        br.main(["-n", "2", "--players", "random"])


# --- walidacja parserów ------------------------------------------------------


def test_parse_player_list_dedup():
    assert br._parse_player_list("random,greedy,random") == ("random", "greedy")


def test_parse_player_list_rejects_single():
    with pytest.raises(Exception):
        br._parse_player_list("random,random")


def test_parse_fixtures_splits():
    assert br._parse_fixtures("a.yaml, b.yaml") == ("a.yaml", "b.yaml")


def test_parse_fixtures_rejects_empty():
    with pytest.raises(Exception):
        br._parse_fixtures("  ,  ")
