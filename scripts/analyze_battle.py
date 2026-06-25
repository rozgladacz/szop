"""Telemetria (ADR-0017, slice) — analityczny raport pojedynczej bitwy z event-logu.

Uruchom:
    python scripts/analyze_battle.py                                  # demo fixtura, priority vs random
    python scripts/analyze_battle.py --map symetryczna_a --map-seed 3 --players priority3,priority --seed 7
    python scripts/analyze_battle.py --from-db 12                     # analiza zapisanej bitwy z DB (persistence)
    python scripts/analyze_battle.py --out reports/analyze/battle.md  # zapis raportu markdown do pliku
    python scripts/analyze_battle.py --json data/battle_metrics/1.jsonl  # + maszynowe metryki JSON (telemetria)

Co robi (roadmap "Cross-cutting: telemetria od dnia 1", ADR-0017):
Z event-logu jednej bitwy liczy analitykę — komplementarną do `battle_replay.py`
(narracja per-event). Tu nie narracja, lecz **agregacja**:
1. Wynik gry (zwycięzca pkt 5.f, finalna kontrola celów) + timeline kontroli
   celów per runda (pkt 5.d/5.f, sprawdzane w fazie końca rundy pkt 8.c.ii).
2. Statystyki ataku/obrony per oddział i per strona: obrażenia zadane/otrzymane,
   trafienia, straty modeli (w tym ELIMINOWANY pkt 26.d).
3. Rozkład akcji (Manewr/Związanie/ruch Szarży/Ostrzał/Szarża) + rozkład typów
   eventów.
4. Szczęście kości Przegrupowania (rozkład rzutów 1–6 + średnia, pkt 20) — to
   jedyne surowe rzuty obecne w event-logu.

Źródła event-logu (jak `battle_replay.py`):
- `--fixture`/`--map` — świeża symulacja (`simulate_from_rosters`, reuse fixtur/
  graczy z `balance_simulate.py` SSOT). Mapowanie oddział→strona z `final_state`.
- `--from-db <id>` — persystencja (`engine.persistence.load_events`, read-only).
  Persystencja nie trzyma `initial_state`, więc mapowanie oddział→strona jest
  niedostępne → raport degraduje się łagodnie (per-oddział bez rollupu per strona).

Rdzeń = czyste funkcje (`analyze_battle_log`, `render_analysis`,
`analysis_to_dict`/`aggregate_to_dict`) — bez I/O, w pełni testowalne. Headless-
first (ADR-0013). **Skrypt-liść — zero zmian w rdzeniu silnika/agentów.**

`--json PATH` zapisuje maszynowe metryki (jedna linia JSON = rekord jsonl,
schema `szop.battle_metrics/v1`) — tylko pola ODZYSKIWALNE z event-logu (rozkład
akcji/eventów, kości Przegrupowania, staty per oddział/strona, kontrola celów).
Pola czasowe pełnego ADR-0017 (`time_per_action_ms`, `decision_time_ms`) +
structlog live-emission w resolver/persistence wymagają zmian w hot-path silnika
→ świadomie odłożone.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
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
from app.services.engine.events import (  # noqa: E402
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
)


def _load_balance_simulate():
    """Ładuje sąsiedni `balance_simulate.py` jako moduł (scripts/ nie jest pakietem).

    Rejestracja w `sys.modules` PRZED exec — `dataclass(slots=True)` rozwiązuje
    `cls.__module__` przez `sys.modules.get(...)` (jak w `scripts/battle_replay.py`).
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
# Rdzeń analityki — czyste funkcje (bez I/O)
# ---------------------------------------------------------------------------

#: Czytelne etykiety typów ruchu (zsynchronizowane z battle_replay._MOVE_LABEL).
_MOVE_LABEL = {
    "manever": "Manewr",
    "binding": "Związanie",
    "charge_move": "ruch Szarży",
    "deploy": "rozstawienie",
}


@dataclass(slots=True)
class UnitStats:
    """Agregat statystyk pojedynczego oddziału z event-logu bitwy."""

    unit_id: int
    owner: int | None = None  # 0/1 jeśli znany (sim path); None gdy nieznany (DB)
    shots_fired: int = 0
    melees_fought: int = 0
    hits_dealt: int = 0
    wounds_dealt: int = 0  # suma wounds_dealt + precise + eliminating (jako atakujący)
    kills_inflicted: int = 0  # modele pokonane przez ten oddział (by_attacker_id)
    wounds_received: int = 0  # rany otrzymane (jako obrońca)
    models_lost: int = 0
    eliminated_lost: int = 0  # podzbiór models_lost pokonanych Zgubą (pkt 26.d)
    moves: int = 0
    morale_tests: int = 0
    morale_failures: int = 0


@dataclass(slots=True)
class SideStats:
    """Rollup statystyk jednej strony (gracza 0/1)."""

    player: int
    units: int = 0
    shots_fired: int = 0
    melees_fought: int = 0
    wounds_dealt: int = 0
    wounds_received: int = 0
    kills_inflicted: int = 0
    models_lost: int = 0
    eliminated_lost: int = 0
    moves: int = 0
    morale_failures: int = 0


@dataclass(slots=True)
class BattleAnalysis:
    """Pełna analityka bitwy — wynik `analyze_battle_log`."""

    events_total: int = 0
    event_type_counts: dict[str, int] = field(default_factory=dict)
    rounds_played: int = 0
    winner: int | None = None
    final_objectives: tuple[int, int] | None = None
    objective_timeline: list[tuple[int, tuple[int, int]]] = field(default_factory=list)
    objective_changes: int = 0
    action_counts: dict[str, int] = field(default_factory=dict)
    morale_dice: dict[int, int] = field(default_factory=dict)  # face (1..6) → count
    unit_stats: dict[int, UnitStats] = field(default_factory=dict)
    side_stats: dict[int, SideStats] | None = None  # None gdy owner_map nieznany


def _unit(stats: dict[int, UnitStats], uid: int, owner_map) -> UnitStats:
    """Pobiera (lub tworzy) `UnitStats` dla `uid`, przypisując `owner` jeśli znany."""
    u = stats.get(uid)
    if u is None:
        owner = None if owner_map is None else owner_map.get(uid)
        u = UnitStats(unit_id=uid, owner=owner)
        stats[uid] = u
    return u


def analyze_battle_log(events, *, owner_map=None, winner=None) -> BattleAnalysis:
    """Agreguje event-log bitwy w `BattleAnalysis`.

    Args:
        events: sekwencja engine eventów (`events.BattleEvent`).
        owner_map: opcjonalne `{unit_id: owner_player}` (z `final_state`) —
            włącza rollup per strona. None (np. `--from-db`) → tylko per-oddział.
        winner: opcjonalny zwycięzca (∈ {0,1,None}); gdy None i są `RoundEnded`,
            wnioskowany z ostatniego `objectives_held` (pkt 5.f).
    """
    events = list(events)
    analysis = BattleAnalysis(events_total=len(events))

    type_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    morale_dice: Counter[int] = Counter()
    unit_stats: dict[int, UnitStats] = {}

    for e in events:
        type_counts[type(e).__name__] += 1

        if isinstance(e, MoveExecuted):
            action_counts[_MOVE_LABEL.get(e.move_type, e.move_type)] += 1
            _unit(unit_stats, e.unit_id, owner_map).moves += 1

        elif isinstance(e, (ShotResolved, MeleeResolved)):
            is_shot = isinstance(e, ShotResolved)
            action_counts["Ostrzał" if is_shot else "Szarża/Kontratak"] += 1
            wounds = e.wounds_dealt + e.wounds_precise + e.wounds_eliminating
            atk = _unit(unit_stats, e.attacker_id, owner_map)
            if is_shot:
                atk.shots_fired += 1
            else:
                atk.melees_fought += 1
            atk.hits_dealt += e.hits
            atk.wounds_dealt += wounds
            _unit(unit_stats, e.defender_id, owner_map).wounds_received += wounds

        elif isinstance(e, ModelKilled):
            victim = _unit(unit_stats, e.unit_id, owner_map)
            victim.models_lost += 1
            if e.eliminated:
                victim.eliminated_lost += 1
            if e.by_attacker_id is not None:
                _unit(unit_stats, e.by_attacker_id, owner_map).kills_inflicted += 1

        elif isinstance(e, MoraleTestPassed):
            u = _unit(unit_stats, e.unit_id, owner_map)
            u.morale_tests += 1
            u.morale_failures += e.failures
            for r in e.rolls:
                morale_dice[r] += 1

        elif isinstance(e, ObjectiveControlChanged):
            analysis.objective_changes += 1

        elif isinstance(e, RoundEnded):
            analysis.objective_timeline.append((e.round_number, e.objectives_held))

    analysis.event_type_counts = dict(type_counts)
    analysis.action_counts = dict(action_counts)
    analysis.morale_dice = {face: morale_dice.get(face, 0) for face in range(1, 7)}
    analysis.unit_stats = unit_stats

    if analysis.objective_timeline:
        analysis.rounds_played = analysis.objective_timeline[-1][0]
        analysis.final_objectives = analysis.objective_timeline[-1][1]

    if winner is None and analysis.final_objectives is not None:
        p0, p1 = analysis.final_objectives
        winner = 0 if p0 > p1 else 1 if p1 > p0 else None
    analysis.winner = winner

    # Rollup per strona — tylko gdy znamy przynależność oddziałów.
    if owner_map is not None:
        sides: dict[int, SideStats] = {0: SideStats(0), 1: SideStats(1)}
        for u in unit_stats.values():
            if u.owner not in (0, 1):
                continue
            s = sides[u.owner]
            s.units += 1
            s.shots_fired += u.shots_fired
            s.melees_fought += u.melees_fought
            s.wounds_dealt += u.wounds_dealt
            s.wounds_received += u.wounds_received
            s.kills_inflicted += u.kills_inflicted
            s.models_lost += u.models_lost
            s.eliminated_lost += u.eliminated_lost
            s.moves += u.moves
            s.morale_failures += u.morale_failures
        analysis.side_stats = sides

    return analysis


# ---------------------------------------------------------------------------
# Render markdown — czyste funkcje (bez I/O)
# ---------------------------------------------------------------------------

_BAR_WIDTH = 20


def _bar(fraction: float, width: int = _BAR_WIDTH) -> str:
    """Tekstowy słupek `█`/`░` proporcjonalny do `fraction` (0..1). Jak balance_common."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _winner_label(winner: int | None) -> str:
    return "REMIS" if winner is None else f"Zwycięzca: P{winner}"


def _render_dice(morale_dice: dict[int, int]) -> list[str]:
    """Sekcja rozkładu rzutów Przegrupowania (1–6) + średnia."""
    total = sum(morale_dice.values())
    lines = ["## Szczęście kości (Przegrupowanie, pkt 20)"]
    if total == 0:
        lines.append("")
        lines.append("_(brak testów Przegrupowania w tej bitwie)_")
        return lines
    peak = max(morale_dice.values()) or 1
    mean = sum(face * n for face, n in morale_dice.items()) / total
    lines.append("")
    lines.append(f"Rzutów łącznie: **{total}**, średnia: **{mean:.2f}** (oczekiwana 3.5)")
    lines.append("")
    for face in range(1, 7):
        n = morale_dice[face]
        lines.append(f"- `{face}` {_bar(n / peak)} {n}")
    return lines


def render_analysis(analysis: BattleAnalysis, *, header: str | None = None) -> str:
    """Renderuje `BattleAnalysis` jako raport markdown (tabele + tekstowe słupki)."""
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
        lines.append("")

    # Wynik.
    lines.append("## Wynik")
    lines.append("")
    lines.append(f"- **{_winner_label(analysis.winner)}**")
    if analysis.final_objectives is not None:
        p0, p1 = analysis.final_objectives
        lines.append(f"- Cele końcowe (pkt 5.f): P0={p0} | P1={p1}")
    lines.append(f"- Rund rozegranych: {analysis.rounds_played}")
    lines.append(f"- Eventów: {analysis.events_total}")
    lines.append(f"- Zmian kontroli celów (pkt 5.d): {analysis.objective_changes}")

    # Timeline kontroli celów.
    if analysis.objective_timeline:
        lines.append("")
        lines.append("## Kontrola celów wg rund (pkt 5.d/8.c.ii)")
        lines.append("")
        lines.append("| Runda | P0 | P1 |")
        lines.append("|---|---|---|")
        for round_no, (p0, p1) in analysis.objective_timeline:
            lines.append(f"| {round_no} | {p0} | {p1} |")

    # Statystyki per strona.
    if analysis.side_stats is not None:
        lines.append("")
        lines.append("## Statystyki per strona")
        lines.append("")
        lines.append(
            "| Strona | Oddz. | Ostrzał | Walka | Rany zad. | Rany otrz. "
            "| Zabite | Straty | ELIM | Ruchy | Por. Przegr. |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for p in (0, 1):
            s = analysis.side_stats[p]
            lines.append(
                f"| P{p} | {s.units} | {s.shots_fired} | {s.melees_fought} "
                f"| {s.wounds_dealt} | {s.wounds_received} | {s.kills_inflicted} "
                f"| {s.models_lost} | {s.eliminated_lost} | {s.moves} | {s.morale_failures} |"
            )

    # Statystyki per oddział.
    if analysis.unit_stats:
        lines.append("")
        lines.append("## Statystyki per oddział")
        lines.append("")
        lines.append(
            "| Oddz. | Strona | Ostrzał | Walka | Traf. | Rany zad. | Zabite "
            "| Rany otrz. | Straty | ELIM | Ruchy | Test/Por. |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for uid in sorted(analysis.unit_stats):
            u = analysis.unit_stats[uid]
            owner = "—" if u.owner is None else f"P{u.owner}"
            lines.append(
                f"| {uid} | {owner} | {u.shots_fired} | {u.melees_fought} "
                f"| {u.hits_dealt} | {u.wounds_dealt} | {u.kills_inflicted} "
                f"| {u.wounds_received} | {u.models_lost} | {u.eliminated_lost} "
                f"| {u.moves} | {u.morale_tests}/{u.morale_failures} |"
            )

    # Rozkład akcji.
    if analysis.action_counts:
        lines.append("")
        lines.append("## Rozkład akcji")
        lines.append("")
        peak = max(analysis.action_counts.values()) or 1
        for name, n in sorted(analysis.action_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {name:18s} {_bar(n / peak)} {n}")

    # Szczęście kości.
    lines.append("")
    lines.extend(_render_dice(analysis.morale_dice))

    # Rozkład typów eventów.
    if analysis.event_type_counts:
        lines.append("")
        lines.append("## Rozkład typów eventów")
        lines.append("")
        for et, n in sorted(analysis.event_type_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {et:26s} {n}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agregacja wielu gier — czyste funkcje (bez I/O)
# ---------------------------------------------------------------------------

#: Pola `SideStats` agregowane jako średnie per gra (bez `player`/`units`).
_SIDE_MEAN_FIELDS = (
    "shots_fired",
    "melees_fought",
    "wounds_dealt",
    "wounds_received",
    "kills_inflicted",
    "models_lost",
    "eliminated_lost",
    "moves",
    "morale_failures",
)


@dataclass(slots=True)
class AggregateAnalysis:
    """Agregat telemetrii z próby N gier (ten sam matchup, naprzemienna inicjatywa)."""

    games: int = 0
    win_p0: int = 0
    win_p1: int = 0
    draws: int = 0
    mean_rounds: float = 0.0
    side_means: dict[int, dict[str, float]] = field(default_factory=dict)
    action_means: dict[str, float] = field(default_factory=dict)
    morale_dice_total: dict[int, int] = field(default_factory=dict)


def aggregate_analyses(analyses) -> AggregateAnalysis:
    """Agreguje listę `BattleAnalysis` (po jednej na grę) w `AggregateAnalysis`.

    Wymaga, by każda gra miała `side_stats` (sim path z `owner_map`). Średnie
    liczone per gra (dzielone przez liczbę gier, nie przez liczbę oddziałów).
    """
    analyses = list(analyses)
    agg = AggregateAnalysis(games=len(analyses))
    if not analyses:
        agg.morale_dice_total = {face: 0 for face in range(1, 7)}
        return agg

    total_rounds = 0
    side_sums: dict[int, dict[str, int]] = {
        0: {f: 0 for f in _SIDE_MEAN_FIELDS},
        1: {f: 0 for f in _SIDE_MEAN_FIELDS},
    }
    action_sums: Counter[str] = Counter()
    dice_sums: Counter[int] = Counter()

    for a in analyses:
        if a.winner == 0:
            agg.win_p0 += 1
        elif a.winner == 1:
            agg.win_p1 += 1
        else:
            agg.draws += 1
        total_rounds += a.rounds_played
        if a.side_stats is not None:
            for p in (0, 1):
                s = a.side_stats[p]
                for f in _SIDE_MEAN_FIELDS:
                    side_sums[p][f] += getattr(s, f)
        for name, n in a.action_counts.items():
            action_sums[name] += n
        for face, n in a.morale_dice.items():
            dice_sums[face] += n

    n = len(analyses)
    agg.mean_rounds = total_rounds / n
    agg.side_means = {
        p: {f: side_sums[p][f] / n for f in _SIDE_MEAN_FIELDS} for p in (0, 1)
    }
    agg.action_means = {name: total / n for name, total in action_sums.items()}
    agg.morale_dice_total = {face: dice_sums.get(face, 0) for face in range(1, 7)}
    return agg


def render_aggregate(agg: AggregateAnalysis, *, header: str | None = None) -> str:
    """Renderuje `AggregateAnalysis` jako raport markdown."""
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
        lines.append("")

    lines.append("## Rozkład wyników")
    lines.append("")
    lines.append(f"- Gier: **{agg.games}**, śr. rund: **{agg.mean_rounds:.2f}**")
    if agg.games:
        wr0 = agg.win_p0 / agg.games
        wr1 = agg.win_p1 / agg.games
        wrd = agg.draws / agg.games
        lines.append(f"- P0 wygrane: {agg.win_p0} {_bar(wr0)} {wr0:.0%}")
        lines.append(f"- P1 wygrane: {agg.win_p1} {_bar(wr1)} {wr1:.0%}")
        lines.append(f"- Remisy:     {agg.draws} {_bar(wrd)} {wrd:.0%}")

    if agg.side_means:
        lines.append("")
        lines.append("## Średnie per strona (na grę)")
        lines.append("")
        lines.append(
            "| Strona | Ostrzał | Walka | Rany zad. | Rany otrz. | Zabite "
            "| Straty | ELIM | Ruchy | Por. Przegr. |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in (0, 1):
            m = agg.side_means[p]
            lines.append(
                f"| P{p} | {m['shots_fired']:.1f} | {m['melees_fought']:.1f} "
                f"| {m['wounds_dealt']:.1f} | {m['wounds_received']:.1f} "
                f"| {m['kills_inflicted']:.1f} | {m['models_lost']:.1f} "
                f"| {m['eliminated_lost']:.1f} | {m['moves']:.1f} "
                f"| {m['morale_failures']:.1f} |"
            )

    if agg.action_means:
        lines.append("")
        lines.append("## Średni miks akcji (na grę)")
        lines.append("")
        peak = max(agg.action_means.values()) or 1.0
        for name, mean in sorted(agg.action_means.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {name:18s} {_bar(mean / peak)} {mean:.1f}")

    lines.append("")
    lines.extend(_render_dice(agg.morale_dice_total))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serializacja JSON — telemetria maszynowa (ADR-0017, czyste funkcje)
# ---------------------------------------------------------------------------

#: Wersjonowana etykieta schematu metryk (downstream tooling rozpoznaje format).
_METRICS_SCHEMA = "szop.battle_metrics/v1"


def analysis_to_dict(analysis: BattleAnalysis) -> dict:
    """Serializuje `BattleAnalysis` do JSON-owalnego dict (telemetria, ADR-0017).

    Tylko metryki ODZYSKIWALNE z event-logu (rozkład akcji/typów eventów, kości
    Przegrupowania, staty per oddział/strona, kontrola celów). Pola czasowe
    ADR-0017 (`time_per_action_ms`, `decision_time_ms`) wymagają live-
    instrumentacji hot-path silnika → świadomie poza tym slice'em. Klucze
    słowników kości/stron jako `str` (wymóg JSON object keys).
    """
    return {
        "schema": _METRICS_SCHEMA,
        "kind": "battle",
        "events_total": analysis.events_total,
        "rounds_played": analysis.rounds_played,
        "winner": analysis.winner,
        "final_objectives": (
            list(analysis.final_objectives)
            if analysis.final_objectives is not None
            else None
        ),
        "objective_changes": analysis.objective_changes,
        "objective_timeline": [
            [round_no, list(held)] for round_no, held in analysis.objective_timeline
        ],
        "event_type_counts": dict(analysis.event_type_counts),
        "action_counts": dict(analysis.action_counts),
        "morale_dice": {str(face): analysis.morale_dice.get(face, 0) for face in range(1, 7)},
        "unit_stats": [asdict(analysis.unit_stats[uid]) for uid in sorted(analysis.unit_stats)],
        "side_stats": (
            {str(p): asdict(analysis.side_stats[p]) for p in (0, 1)}
            if analysis.side_stats is not None
            else None
        ),
    }


def aggregate_to_dict(agg: AggregateAnalysis) -> dict:
    """Serializuje `AggregateAnalysis` (próba N gier) do JSON-owalnego dict."""
    return {
        "schema": _METRICS_SCHEMA,
        "kind": "aggregate",
        "games": agg.games,
        "win_p0": agg.win_p0,
        "win_p1": agg.win_p1,
        "draws": agg.draws,
        "mean_rounds": agg.mean_rounds,
        "side_means": {str(p): dict(means) for p, means in agg.side_means.items()},
        "action_means": dict(agg.action_means),
        "morale_dice_total": {
            str(face): agg.morale_dice_total.get(face, 0) for face in range(1, 7)
        },
    }


# ---------------------------------------------------------------------------
# Źródła event-logu
# ---------------------------------------------------------------------------


def _simulate_one(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int,
    initiative_player: int,
) -> BattleAnalysis:
    """Symuluje jedną grę i zwraca jej `BattleAnalysis`. Reuse `balance_simulate` SSOT.

    Gracze z rozłącznych seedów (P1 += `PLAYER_SEED_OFFSET`) — jak `balance_simulate`,
    usuwa bias mirror-matchu (finding F2). `owner_map` z `final_state` → per strona.
    """
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
    owner_map = {b.id: b.owner_player for b in result.final_state.blobs}
    return analyze_battle_log(result.events, owner_map=owner_map, winner=result.winner)


def _fixture_analysis(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int = 0,
    initiative_player: int = 0,
) -> tuple[BattleAnalysis, str]:
    """Symuluje jedną grę z fixtury → `(BattleAnalysis, header)`. Compute bez renderu."""
    analysis = _simulate_one(
        fixture, player_kinds=player_kinds, seed=seed, initiative_player=initiative_player
    )
    header = (
        f"Analiza: {fixture.name}  —  P0={player_kinds[0]} vs P1={player_kinds[1]}  "
        f"(seed={seed}, rund={analysis.rounds_played})"
    )
    return analysis, header


def analyze_from_fixture(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int = 0,
    initiative_player: int = 0,
) -> str:
    """Symuluje jedną grę z fixtury i renderuje raport per-battle."""
    analysis, header = _fixture_analysis(
        fixture, player_kinds=player_kinds, seed=seed, initiative_player=initiative_player
    )
    return render_analysis(analysis, header=header)


def _fixture_aggregate(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int = 0,
    games: int,
) -> tuple[AggregateAnalysis, str]:
    """Symuluje N gier (naprzemienna inicjatywa) → `(AggregateAnalysis, header)`.

    Metodyka próby = `balance_simulate`: seed kości = `seed + i`, inicjatywa
    = `i % 2`. `owner_player` stały (roster[0]→P0) → staty per strona porównywalne.
    """
    analyses = [
        _simulate_one(
            fixture,
            player_kinds=player_kinds,
            seed=seed + i,
            initiative_player=bsim.initiative_for_game(i),
        )
        for i in range(games)
    ]
    agg = aggregate_analyses(analyses)
    header = (
        f"Agregat ({games} gier): {fixture.name}  —  "
        f"P0={player_kinds[0]} vs P1={player_kinds[1]}  (seed={seed})"
    )
    return agg, header


def analyze_aggregate_from_fixture(
    fixture,
    *,
    player_kinds: tuple[str, str],
    seed: int = 0,
    games: int,
) -> str:
    """Symuluje N gier (naprzemienna inicjatywa) i renderuje raport agregatu."""
    agg, header = _fixture_aggregate(
        fixture, player_kinds=player_kinds, seed=seed, games=games
    )
    return render_aggregate(agg, header=header)


def _db_analysis(battle_id: int) -> tuple[BattleAnalysis, str]:
    """Ładuje eventy zapisanej bitwy z persystencji → `(BattleAnalysis, header)` (read-only).

    Persystencja nie trzyma `initial_state` ⇒ `owner_map=None` ⇒ analiza bez
    rollupu per strona (degradacja łagodna, jak `battle_replay.replay_from_db`).
    """
    from app.db import Base, SessionLocal, engine
    from app.services.engine.persistence import load_events

    # Tabele event-store (ADR-0050) powstają przez `create_all` przy bootstrapie;
    # standalone analiza może trafić na bazę bez nich — `create_all` jest
    # idempotentne i addytywne, więc brak bitew degraduje się do "(brak eventów)".
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        events = load_events(session, battle_id)
    return analyze_battle_log(events), f"Analiza z DB: battle_id={battle_id}"


def analyze_from_db(battle_id: int) -> str:
    """Ładuje eventy zapisanej bitwy z persystencji i renderuje raport (read-only)."""
    analysis, header = _db_analysis(battle_id)
    return render_analysis(analysis, header=header)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Telemetria (ADR-0017): analityczny raport bitwy z event-logu.",
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
        help="Analiza zapisanej bitwy z DB (persistence.load_events) zamiast symulacji.",
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
        default=None,
        help="Gracz z inicjatywą w rundzie 1 (domyślnie 0; ignorowane dla --games>1).",
    )
    parser.add_argument(
        "--games",
        type=int,
        default=1,
        metavar="N",
        help="N>1 → raport agregatu z N gier (naprzemienna inicjatywa) zamiast per-battle.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Zapisz raport markdown do pliku (domyślnie wypis na stdout).",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Dodatkowo zapisz metryki jako JSON (jedna linia = rekord jsonl; "
            "telemetria ADR-0017, np. data/battle_metrics/<id>.jsonl). "
            "Additive — markdown nadal trafia na stdout/--out."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.games < 1:
        print(
            f"--games musi być ≥ 1 (1 = per-battle, >1 = agregat); podano {args.games}",
            file=sys.stderr,
        )
        return 2

    if args.from_db is not None:
        if args.games > 1:
            print(
                "--games>1 dotyczy tylko symulacji (--fixture/--map), nie --from-db",
                file=sys.stderr,
            )
            return 2
        obj, header = _db_analysis(args.from_db)
        report = render_analysis(obj, header=header)
        payload = analysis_to_dict(obj)
    else:
        if args.map:
            fixture = bsim.build_map(args.map, args.map_seed)
        else:
            path = args.fixture or str(bsim.DEFAULT_FIXTURE)
            fixture = bsim.load_battle_fixture(path)
        if args.games > 1:
            if args.initiative is not None:
                print(
                    "--initiative jest ignorowane dla --games>1 "
                    "(agregat używa naprzemiennej inicjatywy)",
                    file=sys.stderr,
                )
            obj, header = _fixture_aggregate(
                fixture,
                player_kinds=args.players,
                seed=args.seed,
                games=args.games,
            )
            report = render_aggregate(obj, header=header)
            payload = aggregate_to_dict(obj)
        else:
            obj, header = _fixture_analysis(
                fixture,
                player_kinds=args.players,
                seed=args.seed,
                initiative_player=args.initiative if args.initiative is not None else 0,
            )
            report = render_analysis(obj, header=header)
            payload = analysis_to_dict(obj)

    if args.out:
        p = pathlib.Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report, encoding="utf-8")
        print(f"Zapisano raport: {args.out}")
    else:
        print(report)

    if args.json:
        jp = pathlib.Path(args.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Zapisano metryki JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
