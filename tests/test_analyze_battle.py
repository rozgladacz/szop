"""Telemetria (ADR-0017) — testy `scripts/analyze_battle.py`.

Pokrywa: agregację event-logu w `BattleAnalysis` (per oddział + per strona),
wnioskowanie zwycięzcy (pkt 5.f), timeline kontroli celów, rozkład akcji,
rozkład rzutów Przegrupowania, degradację bez `owner_map` (ścieżka --from-db),
render markdown, oraz integrację end-to-end na fixturze (`simulate_from_rosters`).
Skrypt jest izolowanym liściem nad publicznym API silnika/agentów — testy nie
dotykają DB.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from app.services.engine.events import (
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "analyze_battle.py"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"


def _load_module():
    """Ładuje skrypt jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("analyze_battle", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _synthetic_events():
    """Mały, deterministyczny event-log: P0={u1}, P1={u3} (u2 nie działa)."""
    return [
        MoveExecuted(sequence=1, unit_id=1, from_pos=(0.0, 0.0), to_pos=(1.0, 0.0)),
        MoveExecuted(
            sequence=2, unit_id=3, from_pos=(9.0, 0.0), to_pos=(5.0, 0.0),
            move_type="charge_move",
        ),
        ShotResolved(
            sequence=3, attacker_id=1, defender_id=3, weapon_slug="rifle",
            hits=3, wounds_dealt=2, wounds_precise=1,
        ),
        MeleeResolved(
            sequence=4, attacker_id=3, defender_id=1, weapon_slug="blade",
            hits=1, wounds_dealt=1, wounds_eliminating=1, charger_id=3,
        ),
        ModelKilled(sequence=5, unit_id=3, model_index=0, by_attacker_id=1),
        ModelKilled(
            sequence=6, unit_id=1, model_index=0, eliminated=True, by_attacker_id=3,
        ),
        MoraleTestPassed(
            sequence=7, unit_id=3, rolls=(2, 5), failures=1, result_status="exhausted",
        ),
        ObjectiveControlChanged(
            sequence=8, objective_id=0, previous_controller=None, new_controller=0,
        ),
        ObjectiveControlChanged(
            sequence=9, objective_id=1, previous_controller=None, new_controller=1,
        ),
        RoundEnded(sequence=10, round_number=1, objectives_held=(1, 0)),
        RoundEnded(sequence=11, round_number=2, objectives_held=(1, 2)),
    ]


# ---------------------------------------------------------------------------
# Rdzeń analityki
# ---------------------------------------------------------------------------


def test_per_unit_aggregation(mod):
    a = mod.analyze_battle_log(_synthetic_events(), owner_map={1: 0, 2: 0, 3: 1})

    u1 = a.unit_stats[1]
    assert u1.owner == 0
    assert u1.shots_fired == 1 and u1.melees_fought == 0
    assert u1.hits_dealt == 3
    assert u1.wounds_dealt == 3  # 2 + 1 precise
    assert u1.kills_inflicted == 1  # zabił model u3
    assert u1.wounds_received == 2  # 1 + 1 eliminating z melee
    assert u1.models_lost == 1 and u1.eliminated_lost == 1
    assert u1.moves == 1 and u1.morale_tests == 0

    u3 = a.unit_stats[3]
    assert u3.owner == 1
    assert u3.melees_fought == 1 and u3.shots_fired == 0
    assert u3.wounds_dealt == 2  # 1 + 1 eliminating
    assert u3.kills_inflicted == 1
    assert u3.wounds_received == 3  # z ostrzału (2 + 1 precise)
    assert u3.models_lost == 1 and u3.eliminated_lost == 0
    assert u3.moves == 1
    assert u3.morale_tests == 1 and u3.morale_failures == 1

    assert 2 not in a.unit_stats  # u2 nie wystąpił w żadnym evencie


def test_per_side_rollup(mod):
    a = mod.analyze_battle_log(_synthetic_events(), owner_map={1: 0, 3: 1})
    assert a.side_stats is not None
    s0, s1 = a.side_stats[0], a.side_stats[1]
    assert s0.units == 1 and s0.shots_fired == 1 and s0.melees_fought == 0
    assert s0.wounds_dealt == 3 and s0.wounds_received == 2
    assert s0.kills_inflicted == 1 and s0.models_lost == 1 and s0.eliminated_lost == 1
    assert s0.morale_failures == 0
    assert s1.units == 1 and s1.melees_fought == 1
    assert s1.wounds_dealt == 2 and s1.wounds_received == 3
    assert s1.morale_failures == 1


def test_actions_dice_and_objectives(mod):
    a = mod.analyze_battle_log(_synthetic_events(), owner_map={1: 0, 3: 1})
    assert a.action_counts == {
        "Manewr": 1,
        "ruch Szarży": 1,
        "Ostrzał": 1,
        "Szarża/Kontratak": 1,
    }
    assert a.morale_dice == {1: 0, 2: 1, 3: 0, 4: 0, 5: 1, 6: 0}
    assert a.objective_timeline == [(1, (1, 0)), (2, (1, 2))]
    assert a.objective_changes == 2
    assert a.rounds_played == 2
    assert a.final_objectives == (1, 2)


def test_winner_inferred_from_final_objectives(mod):
    a = mod.analyze_battle_log(_synthetic_events(), owner_map={1: 0, 3: 1})
    assert a.winner == 1  # P1 zajmuje więcej celów (pkt 5.f)


def test_winner_explicit_override(mod):
    a = mod.analyze_battle_log(
        _synthetic_events(), owner_map={1: 0, 3: 1}, winner=0
    )
    assert a.winner == 0  # jawny zwycięzca ma pierwszeństwo nad wnioskowaniem


def test_draw_when_objectives_equal(mod):
    events = [RoundEnded(sequence=1, round_number=4, objectives_held=(2, 2))]
    a = mod.analyze_battle_log(events)
    assert a.winner is None


def test_no_owner_map_degrades_gracefully(mod):
    """Ścieżka --from-db: brak owner_map ⇒ brak rollupu per strona, owner=None."""
    a = mod.analyze_battle_log(_synthetic_events())
    assert a.side_stats is None
    assert all(u.owner is None for u in a.unit_stats.values())
    # Per-oddział nadal liczone w pełni.
    assert a.unit_stats[1].wounds_dealt == 3


def test_empty_log(mod):
    a = mod.analyze_battle_log([])
    assert a.events_total == 0
    assert a.winner is None
    assert a.unit_stats == {}
    assert a.morale_dice == {f: 0 for f in range(1, 7)}


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------


def test_render_contains_sections(mod):
    a = mod.analyze_battle_log(_synthetic_events(), owner_map={1: 0, 3: 1})
    text = mod.render_analysis(a, header="Test")
    assert "# Test" in text
    assert "## Wynik" in text
    assert "## Kontrola celów" in text
    assert "## Statystyki per strona" in text
    assert "## Statystyki per oddział" in text
    assert "## Rozkład akcji" in text
    assert "## Szczęście kości" in text
    assert "## Rozkład typów eventów" in text
    assert "Zwycięzca: P1" in text


def test_render_without_side_stats_skips_section(mod):
    a = mod.analyze_battle_log(_synthetic_events())  # brak owner_map
    text = mod.render_analysis(a)
    assert "## Statystyki per strona" not in text
    assert "## Statystyki per oddział" in text  # per-oddział nadal jest


def test_render_empty_no_crash(mod):
    text = mod.render_analysis(mod.analyze_battle_log([]))
    assert "REMIS" in text
    assert "brak testów Przegrupowania" in text


# ---------------------------------------------------------------------------
# Integracja end-to-end (symulacja na fixturze)
# ---------------------------------------------------------------------------


def test_analyze_from_fixture_end_to_end(mod):
    fixture = mod.bsim.load_battle_fixture(str(_FIXTURE))
    report = mod.analyze_from_fixture(
        fixture, player_kinds=("priority", "random"), seed=3
    )
    assert "## Wynik" in report
    assert "## Statystyki per strona" in report
    assert ("Zwycięzca: P" in report) or ("REMIS" in report)


def test_analyze_from_fixture_deterministic(mod):
    fixture = mod.bsim.load_battle_fixture(str(_FIXTURE))
    r1 = mod.analyze_from_fixture(fixture, player_kinds=("priority", "random"), seed=7)
    r2 = mod.analyze_from_fixture(fixture, player_kinds=("priority", "random"), seed=7)
    assert r1 == r2  # ten sam seed ⇒ identyczny raport (determinizm ADR-0010/0012)


def test_cli_main_smoke(mod, capsys):
    rc = mod.main(["--players", "priority,random", "--seed", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Wynik" in out
