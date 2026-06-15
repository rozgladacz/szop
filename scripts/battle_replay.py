"""B6 — CLI replay: renderuje event-log bitwy jako czytelny tekst w terminalu.

Uruchom:
    python scripts/battle_replay.py                                  # demo fixtura, priority vs random
    python scripts/battle_replay.py --fixture tests/fixtures/battles/objective_clash.yaml --players priority,greedy --seed 7
    python scripts/battle_replay.py --map symetryczna_a --map-seed 3 --players priority3,random
    python scripts/battle_replay.py --from-db 12                     # replay zapisanej bitwy z DB (persistence)

Co robi (roadmap B6, `docs/roadmap.md#b6-prezentacja`):
1. Pozyskuje strumień eventów bitwy — albo ze świeżej symulacji
   (`simulate_from_rosters`, reuse fixtur/graczy z `balance_simulate.py` SSOT),
   albo z persystencji (`engine.persistence.load_events`, tryb `--from-db`).
2. Renderuje log: narracja jednolinijkowa per event, pogrupowana w rundy
   (delimiter `RoundEnded`), z bieżącym wynikiem celów (pkt 5.d/5.f) i
   podsumowaniem (rozkład typów eventów + zwycięzca).

Rdzeń = czyste funkcje formatujące (`format_event`, `render_battle_log`) — bez
I/O, w pełni testowalne. Renderujemy **z samego event-logu** (bez rekonstrukcji
pełnego stanu), więc tryb sim i `--from-db` działają jednolicie (persystencja
nie trzyma initial_state). Headless-first (ADR-0013): UI opcjonalne, silnik
nie zależy od prezentacji. **Skrypt-liść — zero zmian w rdzeniu silnika/agentów.**
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys
from typing import Sequence

# UTF-8 stdout (nazwy broni/rosterów PL na Windows cp1250 — jak balance_simulate.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.services.agents import simulate_from_rosters  # noqa: E402
from app.services.engine.events import RoundEnded  # noqa: E402


def _load_balance_simulate():
    """Ładuje sąsiedni `balance_simulate.py` jako moduł (scripts/ nie jest pakietem).

    Rejestracja w `sys.modules` PRZED exec — `dataclass(slots=True)` rozwiązuje
    `cls.__module__` przez `sys.modules.get(...)` (jak w `scripts/balance_report.py`).
    """
    name = "balance_simulate"
    if name in sys.modules:
        return sys.modules[name]
    script = pathlib.Path(__file__).resolve().parent / "balance_simulate.py"
    spec = importlib.util.spec_from_file_location(name, script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bsim = _load_balance_simulate()


# ---------------------------------------------------------------------------
# Rdzeń renderujący — czyste funkcje (bez I/O)
# ---------------------------------------------------------------------------


def _pos(p: tuple[float, float]) -> str:
    """Pozycja `(x, y)` jako `(12.0, 6.0)` z 1 miejscem po przecinku."""
    return f"({p[0]:.1f}, {p[1]:.1f})"


def _status_str(s) -> str:
    """Czytelna nazwa statusu. `StatusFlag` (str-Enum) → wartość, nie repr enuma."""
    return getattr(s, "value", s)


_MOVE_LABEL = {
    "manever": "Manewr",
    "binding": "Związanie",
    "charge_move": "ruch Szarży",
    "deploy": "rozstawienie",
}


def _fmt_move(e) -> str:
    label = _MOVE_LABEL.get(e.move_type, e.move_type)
    return f"oddział {e.unit_id}: {label} {_pos(e.from_pos)} → {_pos(e.to_pos)}"


def _wounds_suffix(e) -> str:
    """Dopisek o ranach precyzyjnych/eliminujących, jeśli niezerowe."""
    extra = []
    if e.wounds_precise:
        extra.append(f"{e.wounds_precise} precyz.")
    if e.wounds_eliminating:
        extra.append(f"{e.wounds_eliminating} Zguba")
    return f" [{', '.join(extra)}]" if extra else ""


def _fmt_attack(label: str, e) -> str:
    """Wspólny szkielet narracji ataku (Ostrzał/Szarża/Kontratak)."""
    return (
        f"{label}: oddział {e.attacker_id} → {e.defender_id} "
        f"({e.weapon_slug}): {e.hits} traf., {e.wounds_dealt} ran"
        f"{_wounds_suffix(e)}"
    )


def _fmt_shot(e) -> str:
    return _fmt_attack("Ostrzał", e)


def _fmt_melee(e) -> str:
    return _fmt_attack("Szarża" if e.charger_id else "Kontratak", e)


def _fmt_model_killed(e) -> str:
    who = "Bohater" if e.is_hero else f"model #{e.model_index}"
    fate = "ELIMINOWANY (Zguba)" if e.eliminated else "Wycofany"
    src = f" (przez oddz. {e.by_attacker_id})" if e.by_attacker_id is not None else ""
    return f"Strata: oddział {e.unit_id} traci {who} — {fate}{src}"


_MORALE_LABEL = {
    "pass": "zdany",
    "exhausted": "Wyczerpany",
    "pinned": "Przyszpilony",
    "exhausted_pinned": "Wyczerpany+Przyszpilony",
    "broken": "rozbity",
}


def _fmt_morale(e) -> str:
    label = _MORALE_LABEL.get(e.result_status, e.result_status)
    rolls = ", ".join(str(r) for r in e.rolls) if e.rolls else "—"
    return (
        f"Przegrupowanie: oddział {e.unit_id}: rzuty [{rolls}], "
        f"{e.failures} porażek → {label}"
    )


def _fmt_effect(e) -> str:
    src = f" od oddz. {e.source_unit_id}" if e.source_unit_id is not None else ""
    payload = f" {dict(e.payload)}" if e.payload else ""
    return f"Efekt '{e.slug}' na oddziale {e.target_unit_id}{src}{payload}"


def _fmt_interrupt(e) -> str:
    tgt = f" → oddz. {e.target_unit_id}" if e.target_unit_id is not None else ""
    limit = " [zużywa limit/rundę]" if e.consumes_round_limit else ""
    return (
        f"Przerwanie ({e.interrupt_point}) '{e.slug}': "
        f"oddz. {e.source_unit_id}{tgt}{limit}"
    )


def _fmt_round_ended(e) -> str:
    p0, p1 = e.objectives_held
    return f"— KONIEC RUNDY {e.round_number} — cele: P0={p0} | P1={p1}"


def _fmt_status_added(e) -> str:
    return f"Status +{_status_str(e.status)}: oddział {e.target_id}"


def _fmt_status_removed(e) -> str:
    return f"Status −{_status_str(e.status)}: oddział {e.target_id}"


def _fmt_objective_control(e) -> str:
    def _ctrl(c):
        return "nikt" if c is None else f"P{c}"

    return (
        f"Cel {e.objective_id}: kontrola {_ctrl(e.previous_controller)} "
        f"→ {_ctrl(e.new_controller)}"
    )


def _fmt_initiative(e) -> str:
    return f"Inicjatywa: P{e.previous_active_player} → P{e.new_active_player}"


def _fmt_balance_reset(e) -> str:
    return f"Reset bilansu wręcz: oddział {e.target_id}"


def _fmt_mutex(e) -> str:
    dropped = ", ".join(_status_str(s) for s in e.dropped_statuses) if e.dropped_statuses else "—"
    return f"Kolizja statusów: oddział {e.target_id} odrzuca [{dropped}]"


def _fmt_override_applied(e) -> str:
    verb = "nadaje" if e.granted else "odbiera"
    src = f" (od oddz. {e.source_id})" if e.source_id is not None else ""
    return f"Override: oddział {e.target_id} {verb} '{e.ability}'{src}"


def _fmt_overrides_cleared(e) -> str:
    return f"Override wygasa: oddział {e.target_id}"


#: Dispatch nazwa-klasy → formatter ciała narracji (bez prefiksu sekwencji).
_FORMATTERS = {
    "MoveExecuted": _fmt_move,
    "ShotResolved": _fmt_shot,
    "MeleeResolved": _fmt_melee,
    "ModelKilled": _fmt_model_killed,
    "MoraleTestPassed": _fmt_morale,
    "EffectApplied": _fmt_effect,
    "InterruptTriggered": _fmt_interrupt,
    "RoundEnded": _fmt_round_ended,
    "StatusAdded": _fmt_status_added,
    "StatusRemoved": _fmt_status_removed,
    "ObjectiveControlChanged": _fmt_objective_control,
    "InitiativePassed": _fmt_initiative,
    "MeleeBalanceReset": _fmt_balance_reset,
    "MutexCollision": _fmt_mutex,
    "AbilityOverrideApplied": _fmt_override_applied,
    "AbilityOverridesCleared": _fmt_overrides_cleared,
}


def format_event(event) -> str:
    """Jednolinijkowa narracja PL dla pojedynczego eventu (bez numeru sekwencji).

    Fallback dla nieznanego typu: `repr` pól (nie crashuje na nowym evencie).
    """
    fmt = _FORMATTERS.get(type(event).__name__)
    if fmt is None:
        return f"{type(event).__name__}: {event!r}"
    return fmt(event)


def _winner_label(winner: int | None) -> str:
    if winner is None:
        return "REMIS"
    return f"Zwycięzca: P{winner}"


def render_battle_log(events, *, header: str | None = None, winner: int | None = None) -> str:
    """Renderuje pełny log bitwy jako wielolinijkowy tekst.

    Eventy grupowane w rundy (delimiter `RoundEnded`). Każdy event poprzedzony
    numerem sekwencji. Sekcja podsumowania: liczba eventów, rozkład typów,
    finalny wynik celów (z ostatniego `RoundEnded`) i zwycięzca.

    Args:
        events: sekwencja engine eventów (`events.BattleEvent`).
        header: opcjonalny nagłówek (fixtura/gracze/seed lub id bitwy z DB).
        winner: opcjonalny zwycięzca (∈ {0,1,None}); gdy None i są `RoundEnded`,
            wnioskowany z ostatniego `objectives_held` (pkt 5.f).
    """
    events = list(events)
    lines: list[str] = []
    if header:
        lines.append(header)
        lines.append("=" * 60)

    if not events:
        lines.append("(brak eventów)")
        return "\n".join(lines)

    round_no = 1
    lines.append(f"--- RUNDA {round_no} ---")
    for e in events:
        lines.append(f"  [{e.sequence:>4}] {format_event(e)}")
        if isinstance(e, RoundEnded):
            round_no += 1
            # Nagłówek kolejnej rundy tylko jeśli będą dalsze eventy.
            if e is not events[-1]:
                lines.append(f"--- RUNDA {round_no} ---")

    # Podsumowanie.
    last_round_ended = next(
        (e for e in reversed(events) if isinstance(e, RoundEnded)), None
    )
    if winner is None and last_round_ended is not None:
        p0, p1 = last_round_ended.objectives_held
        winner = 0 if p0 > p1 else 1 if p1 > p0 else None

    counts: dict[str, int] = {}
    for e in events:
        counts[type(e).__name__] = counts.get(type(e).__name__, 0) + 1

    lines.append("=" * 60)
    lines.append(f"PODSUMOWANIE — {len(events)} eventów")
    if last_round_ended is not None:
        p0, p1 = last_round_ended.objectives_held
        lines.append(f"  Cele końcowe: P0={p0} | P1={p1}")
    lines.append(f"  {_winner_label(winner)}")
    lines.append("  Rozkład typów eventów:")
    for et, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"    {et:25s} {n}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Źródła eventów
# ---------------------------------------------------------------------------


def replay_from_fixture(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int = 0,
    initiative_player: int = 0,
) -> str:
    """Symuluje jedną grę z fixtury i renderuje log. Reuse `balance_simulate` SSOT."""
    players = [
        bsim.make_player(player_kinds[0], seed),
        bsim.make_player(player_kinds[1], seed + bsim.PLAYER_SEED_OFFSET),
    ]
    result = simulate_from_rosters(
        fixture.rosters,
        players,
        seed=seed,
        terrain=fixture.terrain,
        objectives=fixture.objectives,
        initiative_player=initiative_player,
    )
    header = (
        f"REPLAY: {fixture.name}  |  P0={player_kinds[0]} vs P1={player_kinds[1]}  "
        f"|  seed={seed}  |  rund={result.rounds_played}"
    )
    return render_battle_log(result.events, header=header, winner=result.winner)


def replay_from_db(battle_id: int) -> str:
    """Ładuje eventy zapisanej bitwy z persystencji i renderuje log (read-only)."""
    # `app.models` PRZED `app.db`: `app.db` importuje `app.services` zanim
    # zdefiniuje `Base`, więc zaimportowanie `app.db` jako pierwszego z pary
    # db/models wpada w cykl (Base jeszcze nie istnieje). Normalny bootstrap
    # aplikacji importuje `app.models` pierwszy — odtwarzamy tę kolejność.
    import app.models  # noqa: F401
    from app.db import Base, SessionLocal, engine
    from app.services.engine.persistence import load_events

    # Tabele event-store (B2/ADR-0050) powstają przez `create_all` przy bootstrapie
    # aplikacji. Standalone replay może trafić na bazę bez nich — `create_all` jest
    # idempotentne i **addytywne** (tworzy tylko brakujące tabele, nie rusza danych),
    # więc brak bitew degraduje się łagodnie do "(brak eventów)".
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        events = load_events(session, battle_id)
    header = f"REPLAY z DB: battle_id={battle_id}  |  {len(events)} eventów"
    return render_battle_log(events, header=header)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="B6 — CLI replay: renderuje event-log bitwy jako czytelny tekst.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Ścieżka do fixtury roster-pair YAML (domyślnie demo_skirmish).",
    )
    src.add_argument(
        "--map",
        type=str,
        default=None,
        help=f"Generowana mapa zamiast --fixture: {', '.join(sorted(bsim.MAP_BUILDERS))}.",
    )
    src.add_argument(
        "--from-db",
        type=int,
        default=None,
        metavar="BATTLE_ID",
        help="Replay zapisanej bitwy z DB (persistence.load_events) zamiast symulacji.",
    )
    parser.add_argument(
        "--map-seed",
        type=int,
        default=0,
        help="Seed generatora mapy (Lustrzana_A/Symetryczna_A; domyślnie 0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed kości symulacji (domyślnie 0).",
    )
    parser.add_argument(
        "--players",
        type=bsim._parse_players,
        default=("priority", "random"),
        help=f"Para graczy 'p0,p1' z {{{', '.join(bsim.PLAYER_KINDS)}}} (domyślnie priority,random).",
    )
    parser.add_argument(
        "--initiative",
        type=int,
        choices=(0, 1),
        default=0,
        help="Gracz z inicjatywą w rundzie 1 (domyślnie 0).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.from_db is not None:
        print(replay_from_db(args.from_db))
        return 0

    if args.map:
        fixture = bsim.build_map(args.map, args.map_seed)
    else:
        path = args.fixture or str(bsim.DEFAULT_FIXTURE)
        fixture = bsim.load_battle_fixture(path)

    print(
        replay_from_fixture(
            fixture,
            player_kinds=args.players,
            seed=args.seed,
            initiative_player=args.initiative,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
