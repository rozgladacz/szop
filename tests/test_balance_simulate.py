"""D2 — testy agregatora balansu (`scripts/balance_simulate.py`).

Pokrywa: ładowanie fixtury roster-pair, determinizm per base_seed, suma
win-rate = 1, naprzemienna inicjatywa, kształt CSV, smoke CLI (in-process).
Skrypt jest izolowanym liściem nad publicznym API silnika/agentów — testy nie
dotykają DB ani kosztów.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "balance_simulate.py"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"


def _load_module():
    """Ładuje skrypt jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("balance_simulate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Rejestracja w sys.modules PRZED exec — `dataclass(slots=True)` rozwiązuje
    # `cls.__module__` przez `sys.modules.get(...)`, inaczej AttributeError.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bs = _load_module()


# --- fixtura -----------------------------------------------------------------


def test_fixture_shape_and_objects():
    fx = bs.load_battle_fixture(_FIXTURE)
    assert len(fx.rosters) == 2
    assert {r["owner_player"] for r in fx.rosters} == {0, 1}
    # 5 celów (pkt 5.a) + 1 teren-koło z fixtury
    assert len(fx.objectives) == 5
    assert {o.id for o in fx.objectives} == {1, 2, 3, 4, 5}
    assert len(fx.terrain) == 1
    assert fx.terrain[0].radius_inches == 3
    # 4 oddziały/stronę (pkt 2.a min. armii)
    assert all(len(r["units"]) == 4 for r in fx.rosters)


def test_fixture_objectives_satisfy_placement_rules():
    # pkt 5.c: cele ≥12″ od siebie, ≥6″ od krawędzi (plansza 72×48).
    fx = bs.load_battle_fixture(_FIXTURE)
    pts = [(o.position.x, o.position.y) for o in fx.objectives]
    for x, y in pts:
        assert 6 <= x <= 66 and 6 <= y <= 42  # ≥6″ od krawędzi
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            (ax, ay), (bx, by) = pts[i], pts[j]
            assert ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 >= 12.0  # ≥12″ apart


def test_fixture_rejects_non_pair(tmp_path):
    bad = tmp_path / "one.yaml"
    bad.write_text("rosters:\n  - {owner_player: 0, units: []}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        bs.load_battle_fixture(bad)


# --- gracze ------------------------------------------------------------------


def test_make_player_kinds():
    assert type(bs.make_player("random", 1)).__name__ == "RandomPlayer"
    assert type(bs.make_player("greedy", 1)).__name__ == "GreedyPlayer"
    with pytest.raises(ValueError):
        bs.make_player("minimax", 1)


# --- inicjatywa --------------------------------------------------------------


def test_alternating_initiative():
    assert [bs.initiative_for_game(i) for i in range(6)] == [0, 1, 0, 1, 0, 1]
    # n parzyste → inicjatywa rozdana 50/50
    n = 10
    assigned = [bs.initiative_for_game(i) for i in range(n)]
    assert assigned.count(0) == assigned.count(1) == n // 2


# --- agregacja ---------------------------------------------------------------


def test_simulate_balance_deterministic():
    fx = bs.load_battle_fixture(_FIXTURE)
    r1 = bs.simulate_balance(fx, n=8, player_kinds=("random", "random"), base_seed=42)
    r2 = bs.simulate_balance(fx, n=8, player_kinds=("random", "random"), base_seed=42)
    assert r1 == r2


def test_win_rates_sum_to_one():
    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=12, player_kinds=("random", "random"), base_seed=7)
    assert r.wins_p0 + r.wins_p1 + r.draws == r.n_games == 12
    assert r.win_rate_p0 + r.win_rate_p1 + r.draw_rate == pytest.approx(1.0)


def test_avg_rounds_full_game():
    # Demo bez rezerw Zaplecze → gra dochodzi do MAX_ROUND (pkt 5.f = 4 rundy).
    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=5, player_kinds=("random", "random"), base_seed=1)
    assert r.avg_rounds == pytest.approx(4.0)


def test_simulate_balance_rejects_zero_games():
    fx = bs.load_battle_fixture(_FIXTURE)
    with pytest.raises(ValueError):
        bs.simulate_balance(fx, n=0, player_kinds=("random", "random"))


# --- CSV / output ------------------------------------------------------------


def test_csv_header_row_shape():
    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=4, player_kinds=("greedy", "random"), base_seed=3)
    header = r.csv_header()
    row = r.csv_row()
    assert len(header) == len(row)
    assert header[0] == "fixture" and "win_rate_p0" in header
    # player kinds odzwierciedlone w wierszu
    assert row[header.index("player0")] == "greedy"
    assert row[header.index("player1")] == "random"


def test_result_to_csv_string_parses():
    import csv as _csv
    import io as _io

    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=4, player_kinds=("random", "random"), base_seed=9)
    rows = list(_csv.reader(_io.StringIO(bs.result_to_csv_string(r))))
    assert len(rows) == 2  # header + 1 data row
    assert rows[0] == r.csv_header()


def test_write_csv_creates_file(tmp_path):
    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=3, player_kinds=("random", "random"), base_seed=5)
    out = tmp_path / "sub" / "balance.csv"
    bs.write_csv(r, out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "win_rate_p0" in content


def test_format_summary_contains_rates():
    fx = bs.load_battle_fixture(_FIXTURE)
    r = bs.simulate_balance(fx, n=6, player_kinds=("random", "random"), base_seed=2)
    text = bs.format_summary(r)
    assert "P0 wygrane" in text and "Śr. rund" in text


# --- CLI ---------------------------------------------------------------------


def test_cli_smoke_default_fixture(capsys):
    rc = bs.main(["-n", "4"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Fixtura" in out and "wygrane" in out


def test_cli_writes_csv(tmp_path, capsys):
    out = tmp_path / "cli_balance.csv"
    rc = bs.main(["-n", "3", "--players", "greedy,random", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert "greedy" in out.read_text(encoding="utf-8")


def test_cli_rejects_bad_player():
    with pytest.raises(SystemExit):
        bs.main(["-n", "2", "--players", "random,minimax"])
