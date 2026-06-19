"""D4 — testy leaderboardu botów (`scripts/leaderboard.py`).

Pokrywa: pary distinct (mirror wykluczony), round-robin shape, agregacja
standings (suma gier, symetria wins↔losses między botami, ranking malejący +
tiebreak, pomijanie mirror/obcych botów), render markdown (tabela + cytat
pkt 5.f + wykresy), helper `_bar`, ścieżka domyślna, zapis, determinizm, CLI
smoke, walidacja CLI. Skrypt-liść nad `balance_simulate.py` — testy nie dotykają
DB ani kosztów. Liczba gier trzymana mała (szybkość).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "leaderboard.py"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"


def _load_module():
    """Ładuje skrypt jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("leaderboard", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


lb = _load_module()


def _config(**overrides):
    base = dict(
        n_games=2,
        base_seed=0,
        fixtures=(str(_FIXTURE),),
        player_kinds=("random", "greedy", "priority"),
        generated_at="2026-06-19",
    )
    base.update(overrides)
    return lb.LeaderboardConfig(**base)


def _result(p0, p1, *, n=10, w0=0, w1=0, draws=0, fixture="fx"):
    """Buduje syntetyczny `BalanceResult` (bez rozgrywania gier)."""
    return lb.bsim.BalanceResult(
        fixture_name=fixture,
        player_kinds=(p0, p1),
        n_games=n,
        wins_p0=w0,
        wins_p1=w1,
        draws=draws,
        total_rounds=n * 4,
    )


# --- pary / round-robin -------------------------------------------------------


def test_player_matchups_distinct_no_mirror():
    pairs = lb.player_matchups(("random", "greedy", "priority"))
    # C(3,2) = 3 pary, bez mirrorów A-A, jeden kierunek
    assert len(pairs) == 3
    assert ("random", "random") not in pairs
    assert ("random", "greedy") in pairs
    assert ("greedy", "random") not in pairs


def test_run_leaderboard_shape():
    cfg = _config(player_kinds=("random", "greedy", "priority"))
    results = lb.run_leaderboard(cfg)
    # 1 fixtura × 3 pary distinct = 3 wyniki
    assert len(results) == 3
    for r in results:
        assert r.n_games == 2
        assert r.wins_p0 + r.wins_p1 + r.draws == 2


def test_run_leaderboard_two_fixtures():
    cfg = _config(fixtures=(str(_FIXTURE), str(_FIXTURE)))
    results = lb.run_leaderboard(cfg)
    assert len(results) == 3 * 2  # 2 fixtury × 3 pary


# --- standings ----------------------------------------------------------------


def test_compute_standings_totals_games():
    kinds = ("a", "b", "c")
    results = [
        _result("a", "b", n=10, w0=6, w1=4),
        _result("a", "c", n=10, w0=3, w1=7),
        _result("b", "c", n=10, w0=5, w1=5),
    ]
    standings = lb.compute_standings(results, kinds)
    by = {s.kind: s for s in standings}
    # każdy bot gra w 2 parach × 10 = 20 gier
    assert by["a"].games == 20 and by["b"].games == 20 and by["c"].games == 20


def test_compute_standings_wins_losses_symmetry():
    kinds = ("a", "b")
    # a wygrywa 7, przegrywa 3 vs b
    results = [_result("a", "b", n=10, w0=7, w1=3)]
    standings = lb.compute_standings(results, kinds)
    by = {s.kind: s for s in standings}
    assert by["a"].wins == 7 and by["a"].losses == 3
    # b lustrzanie: jego porażki = wygrane a, wygrane = porażki a
    assert by["b"].wins == 3 and by["b"].losses == 7
    # suma wins wszystkich botów == suma rozstrzygniętych gier
    assert by["a"].wins + by["b"].wins == 7 + 3


def test_compute_standings_draws_counted_for_both():
    kinds = ("a", "b")
    results = [_result("a", "b", n=10, w0=4, w1=2, draws=4)]
    standings = lb.compute_standings(results, kinds)
    by = {s.kind: s for s in standings}
    assert by["a"].draws == 4 and by["b"].draws == 4


def test_compute_standings_ranking_descending_by_win_rate():
    kinds = ("weak", "mid", "strong")
    results = [
        _result("strong", "mid", n=10, w0=8, w1=2),
        _result("strong", "weak", n=10, w0=9, w1=1),
        _result("mid", "weak", n=10, w0=7, w1=3),
    ]
    standings = lb.compute_standings(results, kinds)
    assert [s.kind for s in standings] == ["strong", "mid", "weak"]
    assert standings[0].win_rate >= standings[1].win_rate >= standings[2].win_rate


def test_compute_standings_tiebreak_by_wins_then_name():
    kinds = ("alpha", "beta")
    # identyczny win-rate (0.5), identyczne wins/losses → tiebreak po nazwie
    results = [_result("alpha", "beta", n=10, w0=5, w1=5)]
    standings = lb.compute_standings(results, kinds)
    assert [s.kind for s in standings] == ["alpha", "beta"]


def test_compute_standings_skips_mirror_and_foreign():
    kinds = ("a", "b")
    results = [
        _result("a", "a", n=10, w0=5, w1=5),  # mirror — pomijany
        _result("a", "x", n=10, w0=8, w1=2),  # x spoza zestawu — pomijany
        _result("a", "b", n=10, w0=6, w1=4),
    ]
    standings = lb.compute_standings(results, kinds)
    by = {s.kind: s for s in standings}
    # tylko a-b liczone: a 10 gier, b 10 gier
    assert by["a"].games == 10 and by["b"].games == 10
    assert by["a"].wins == 6 and by["b"].wins == 4


def test_standing_rates_zero_games_safe():
    s = lb.BotStanding(kind="x", games=0, wins=0, losses=0, draws=0)
    assert s.win_rate == 0.0 and s.loss_rate == 0.0 and s.draw_rate == 0.0


# --- render -------------------------------------------------------------------


def test_bar_proportional():
    assert lb._bar(0.0) == "░" * lb._BAR_WIDTH
    assert lb._bar(1.0) == "█" * lb._BAR_WIDTH
    half = lb._bar(0.5)
    assert half.count("█") == lb._BAR_WIDTH // 2


def test_format_leaderboard_has_table_and_rules_citation():
    kinds = ("a", "b")
    results = [_result("a", "b", n=10, w0=7, w1=3, fixture="demo")]
    standings = lb.compute_standings(results, kinds)
    text = lb.format_leaderboard(standings, _config(player_kinds=kinds), results)
    assert "# Leaderboard botów" in text
    assert "pkt 5.f" in text  # cytat reguły zwycięstwa
    assert "| # | Bot |" in text
    assert "Win-rate" in text
    # lider (a) wymieniony przed b w tabeli
    assert text.index("| 1 | a |") < text.index("| 2 | b |")
    assert "```" in text  # blok wykresu


def test_format_leaderboard_ends_with_newline():
    standings = [lb.BotStanding("a", 10, 7, 3, 0)]
    text = lb.format_leaderboard(standings, _config(), None)
    assert text.endswith("\n")


# --- output -------------------------------------------------------------------


def test_default_report_path():
    p = lb.default_report_path()
    assert p.name == "leaderboard.md"
    assert p.parent.name == "reports"


def test_write_report_creates_dirs(tmp_path):
    out = tmp_path / "nested" / "leaderboard.md"
    lb.write_report("# x\n", out)
    assert out.read_text(encoding="utf-8") == "# x\n"


# --- determinizm + CLI --------------------------------------------------------


def test_run_leaderboard_deterministic():
    cfg = _config()
    r1 = lb.run_leaderboard(cfg)
    r2 = lb.run_leaderboard(cfg)
    assert [(r.player_kinds, r.wins_p0, r.wins_p1, r.draws) for r in r1] == [
        (r.player_kinds, r.wins_p0, r.wins_p1, r.draws) for r in r2
    ]


def test_main_writes_file(tmp_path):
    out = tmp_path / "lb.md"
    rc = lb.main(
        [
            "--fixtures",
            str(_FIXTURE),
            "-n",
            "2",
            "--players",
            "random,greedy",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "# Leaderboard botów" in text
    assert "random" in text and "greedy" in text


def test_cli_rejects_unknown_player():
    with pytest.raises(SystemExit):
        lb.main(["--players", "random,nieistniejacy_bot", "-n", "1"])


def test_cli_rejects_single_player():
    with pytest.raises(SystemExit):
        lb.main(["--players", "random", "-n", "1"])


def test_cli_rejects_nonpositive_games(tmp_path):
    with pytest.raises(SystemExit):
        lb.main(["--players", "random,greedy", "-n", "0", "--out", str(tmp_path / "x.md")])
