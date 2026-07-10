"""B6 — testy CLI replay (`scripts/battle_replay.py`).

Pokrywa: formatowanie każdego z 16 typów eventów (smoke + kluczowe pola w tekście),
grupowanie w rundy + podsumowanie w `render_battle_log`, wnioskowanie zwycięzcy,
reuse `simulate_from_rosters` na fixturze, smoke CLI (in-process). Skrypt jest
izolowanym liściem nad publicznym API silnika/agentów — testy nie dotykają DB.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from app.services.engine.events import (
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    EffectApplied,
    InitiativePassed,
    InterruptTriggered,
    MeleeBalanceReset,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    MutexCollision,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "battle_replay.py"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"


def _load_module():
    """Ładuje skrypt jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("battle_replay", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# format_event — per typ
# ---------------------------------------------------------------------------


def _all_events():
    """Po jednym evencie każdego z 16 typów (pola reprezentatywne)."""
    return [
        MoveExecuted(sequence=1, unit_id=3, from_pos=(0.0, 0.0), to_pos=(6.0, 0.0), move_type="manever"),
        ShotResolved(sequence=2, attacker_id=3, defender_id=1, weapon_slug="rifle", hits=2, wounds_dealt=1, wounds_precise=1),
        MeleeResolved(sequence=3, attacker_id=2, defender_id=4, weapon_slug="sword", hits=3, wounds_dealt=2, wounds_eliminating=1, charger_id=2),
        ModelKilled(sequence=4, unit_id=4, model_index=0, is_hero=True, eliminated=True, by_attacker_id=2),
        MoraleTestPassed(sequence=5, unit_id=4, rolls=(2, 5), failures=1, result_status="pinned"),
        EffectApplied(sequence=6, slug="latanie", target_unit_id=1, source_unit_id=2, payload={"x": 1}),
        InterruptTriggered(sequence=7, interrupt_point="before_action", slug="rozkaz", source_unit_id=2, target_unit_id=1, consumes_round_limit=True),
        RoundEnded(sequence=8, round_number=1, objectives_held=(2, 1)),
        StatusAdded(sequence=9, target_id=1, status="Przygotowany"),
        StatusRemoved(sequence=10, target_id=1, status="Aktywowany"),
        ObjectiveControlChanged(sequence=11, objective_id=5, previous_controller=None, new_controller=0),
        InitiativePassed(sequence=12, previous_active_player=0, new_active_player=1),
        MeleeBalanceReset(sequence=13, target_id=2),
        MutexCollision(sequence=14, target_id=1, dropped_statuses=("Przyszpilony", "Przygotowany")),
        AbilityOverrideApplied(sequence=15, target_id=1, ability="cierpliwy", granted=True, source_id=2),
        AbilityOverridesCleared(sequence=16, target_id=2),
    ]


def test_format_event_covers_all_types(mod):
    """Każdy typ eventu formatuje się bez wyjątku, niepusty, bez surowego repr."""
    for e in _all_events():
        line = mod.format_event(e)
        assert isinstance(line, str) and line.strip()
        # Nie powinno spaść do fallbacku `repr` (ten zawiera nazwę klasy + '(').
        assert not line.startswith(f"{type(e).__name__}: "), f"fallback dla {type(e).__name__}"


def test_format_event_key_content(mod):
    """Wybrane eventy zawierają kluczowe dane w narracji."""
    events = {type(e).__name__: e for e in _all_events()}
    assert "Ostrzał" in mod.format_event(events["ShotResolved"])
    assert "precyz." in mod.format_event(events["ShotResolved"])
    assert "Szarża" in mod.format_event(events["MeleeResolved"])
    assert "Zguba" in mod.format_event(events["MeleeResolved"])
    assert "Bohater" in mod.format_event(events["ModelKilled"])
    assert "ELIMINOWANY" in mod.format_event(events["ModelKilled"])
    assert "Przyszpilony" in mod.format_event(events["MoraleTestPassed"])
    assert "KONIEC RUNDY 1" in mod.format_event(events["RoundEnded"])
    assert "P0=2" in mod.format_event(events["RoundEnded"])


def test_format_event_unknown_fallback(mod):
    """Nieznany typ eventu → fallback repr, bez crashu."""

    class _Weird:
        sequence = 99

    line = mod.format_event(_Weird())
    assert "_Weird" in line


def test_status_flag_enum_renders_value_not_repr(mod):
    """StatusAdded.status jako `StatusFlag` (str-Enum) → czytelna wartość, nie repr."""
    from app.services.engine.status import StatusFlag

    e = StatusAdded(sequence=1, target_id=1, status=StatusFlag.PRZYGOTOWANY)
    line = mod.format_event(e)
    assert "Przygotowany" in line
    assert "StatusFlag" not in line


def test_kontratak_label_when_no_charger(mod):
    """MeleeResolved z charger_id=0 → 'Kontratak' (nie 'Szarża')."""
    e = MeleeResolved(sequence=1, attacker_id=4, defender_id=2, weapon_slug="sword", hits=1, wounds_dealt=0, charger_id=0)
    assert "Kontratak" in mod.format_event(e)


# ---------------------------------------------------------------------------
# render_battle_log
# ---------------------------------------------------------------------------


def test_render_empty(mod):
    out = mod.render_battle_log([])
    assert "brak eventów" in out


def test_render_groups_rounds_and_summary(mod):
    events = [
        MoveExecuted(sequence=1, unit_id=1, from_pos=(0.0, 0.0), to_pos=(6.0, 0.0)),
        RoundEnded(sequence=2, round_number=1, objectives_held=(1, 0)),
        ShotResolved(sequence=3, attacker_id=1, defender_id=2, weapon_slug="rifle", hits=1, wounds_dealt=1),
        RoundEnded(sequence=4, round_number=2, objectives_held=(2, 1)),
    ]
    out = mod.render_battle_log(events, header="TEST")
    assert "TEST" in out
    assert "--- RUNDA 1 ---" in out
    assert "--- RUNDA 2 ---" in out
    assert "PODSUMOWANIE — 4 eventów" in out
    assert "Cele końcowe: P0=2 | P1=1" in out
    # Zwycięzca wnioskowany z ostatniego RoundEnded (2>1 → P0).
    assert "Zwycięzca: P0" in out
    # Numer sekwencji każdego eventu w logu.
    assert "[   1]" in out and "[   4]" in out


def test_render_no_trailing_empty_round_header(mod):
    """Gdy ostatni event to RoundEnded — nie dorzucaj pustego nagłówka kolejnej rundy."""
    events = [RoundEnded(sequence=1, round_number=1, objectives_held=(0, 0))]
    out = mod.render_battle_log(events)
    assert "--- RUNDA 2 ---" not in out


def test_render_explicit_winner_overrides_inference(mod):
    events = [RoundEnded(sequence=1, round_number=1, objectives_held=(3, 0))]
    out = mod.render_battle_log(events, winner=None)
    assert "Zwycięzca: P0" in out
    out_draw = mod.render_battle_log(events, winner=1)
    assert "Zwycięzca: P1" in out_draw


def test_render_draw_label(mod):
    events = [RoundEnded(sequence=1, round_number=1, objectives_held=(1, 1))]
    out = mod.render_battle_log(events)
    assert "REMIS" in out


# ---------------------------------------------------------------------------
# Integracja: symulacja z fixtury + CLI
# ---------------------------------------------------------------------------


def test_replay_from_fixture_nonempty(mod):
    fixture = mod.bsim.load_battle_fixture(_FIXTURE)
    out = mod.replay_from_fixture(fixture, player_kinds=("priority", "random"), seed=3)
    assert "REPLAY:" in out
    assert "--- RUNDA 1 ---" in out
    assert "PODSUMOWANIE" in out
    assert "Zwycięzca" in out or "REMIS" in out


def test_replay_from_fixture_deterministic(mod):
    fixture = mod.bsim.load_battle_fixture(_FIXTURE)
    a = mod.replay_from_fixture(fixture, player_kinds=("priority", "random"), seed=11)
    b = mod.replay_from_fixture(fixture, player_kinds=("priority", "random"), seed=11)
    assert a == b


def test_cli_main_fixture(mod, capsys):
    rc = mod.main(["--fixture", str(_FIXTURE), "--players", "priority,random", "--seed", "5"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "REPLAY:" in captured.out
    assert "PODSUMOWANIE" in captured.out


def test_cli_main_default_fixture(mod, capsys):
    rc = mod.main([])
    assert rc == 0
    assert "PODSUMOWANIE" in capsys.readouterr().out


def test_cli_map_mode(mod, capsys):
    rc = mod.main(["--map", "symetryczna_a", "--map-seed", "1", "--players", "random,random", "--seed", "2"])
    assert rc == 0
    assert "REPLAY:" in capsys.readouterr().out


def test_cli_mutually_exclusive_sources(mod):
    """--fixture i --from-db wzajemnie wykluczające → SystemExit (argparse)."""
    with pytest.raises(SystemExit):
        mod.build_arg_parser().parse_args(["--fixture", "x.yaml", "--from-db", "1"])


def test_cli_missing_fixture_clean_error(mod, capsys):
    # Nieistniejąca ścieżka --fixture: czysty błąd CLI (rc=2 + stderr),
    # nie surowy traceback FileNotFoundError.
    rc = mod.main(["--fixture", "nope_missing_fixture.yaml"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "nope_missing_fixture.yaml" in err
    assert "Traceback" not in err


def test_cli_unknown_map_clean_error(mod, capsys):
    # Nieznana nazwa --map: czysty błąd CLI (ValueError z build_map → rc=2).
    rc = mod.main(["--map", "not_a_real_map"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not_a_real_map" in err
    assert "Traceback" not in err
