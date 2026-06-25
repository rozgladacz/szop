"""Telemetria decyzji bota (ADR-0017, slice `data/agent_metrics`) — per agent.

Uruchom:
    python scripts/analyze_agents.py                                     # demo fixtura, priority vs random
    python scripts/analyze_agents.py --players priority,claude_v3 -n 8 --seed 7
    python scripts/analyze_agents.py --map symetryczna_a --map-seed 3 --players priority3,priority
    python scripts/analyze_agents.py --players priority,random -n 6 --json data/agent_metrics/run.jsonl
    python scripts/analyze_agents.py --out reports/agents/run.md          # raport markdown do pliku

Co robi (roadmap "Cross-cutting: telemetria od dnia 1", ADR-0017 →
`data/agent_metrics/{agent}.jsonl`):
Mierzy KOSZT i JAKOŚĆ decyzji botów **per bot** (nie per bitwa — to robi
`analyze_battle.py`). Z N gier zbiera per aktywację:
1. **`decision_time_ms`** — wall-clock głównej decyzji `Player.choose_action`.
2. **`decision_quality_score`** — samoocena bota: Δ `evaluate_state` (SSOT
   `policy_eval`, ADR-0031/0044) z perspektywy decydenta między stanem przed
   a po aktywacji. Dodatnia = bot poprawił własną pozycję wg swojej funkcji oceny.

Agregat per bot: liczba decyzji, średni/mediana/max czas, średnia jakość, odsetek
decyzji "poprawiających" (quality > 0), miks typów akcji. Diagnostyka uzupełnia
wniosek D4 (priority/priority3 najlepszy stosunek siła/koszt) twardymi liczbami
per-decyzja zamiast tylko win-rate.

Źródło decyzji: świeża symulacja (`simulate_from_rosters` z hookiem `on_decision`,
reuse fixtur/graczy z `balance_simulate.py` SSOT). Inicjatywa naprzemienna per
grę (metodyka `balance_simulate`). Rdzeń = czyste funkcje
(`quality_from_states`, `aggregate_records`, `render_report`, `metrics_to_dict`)
— bez I/O, testowalne. Headless-first (ADR-0013). **Skrypt-liść — jedyna zmiana
poza skryptem to additive `on_decision` hook w `match.run_match` (default None →
zero zmian zachowania).**

`--json PATH` zapisuje maszynowe metryki (jedna linia JSON = jeden agent, schema
`szop.agent_metrics/v1`). `decision_quality_score` jest deterministyczna (czysta
funkcja stanów); `decision_time_ms` zależy od maszyny (wall-clock) — nie używać
do golden/regresji. Konta agentów (`agent_user_id` jako ID DB) + leaderboard
międzykontowy odłożone do B2 auth (ADR-0030 część 2) — tu `agent` = nazwa bota.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import statistics
import sys
from dataclasses import dataclass, field
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

from app.services.agents.policy_eval import evaluate_state  # noqa: E402
from app.services.engine.state import BattleState  # noqa: E402


def _load_balance_simulate():
    """Ładuje sąsiedni `balance_simulate.py` jako moduł (scripts/ nie jest pakietem).

    Rejestracja w `sys.modules` PRZED exec — `dataclass(slots=True)` rozwiązuje
    `cls.__module__` przez `sys.modules.get(...)` (jak w `scripts/analyze_battle.py`).
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

#: Czytelne etykiety typów akcji (klasa `actions.*Action` → PL).
_ACTION_LABEL = {
    "ManeuverAction": "Manewr",
    "DefendAction": "Obrona",
    "ShootAction": "Ostrzał",
    "ChargeAction": "Szarża",
    "SpecialAction": "Specjalna",
}


# ---------------------------------------------------------------------------
# Rdzeń telemetrii — czyste funkcje (bez I/O)
# ---------------------------------------------------------------------------


def quality_from_states(
    state_before: BattleState, state_after: BattleState, perspective: int
) -> float:
    """Δ `evaluate_state` z perspektywy decydenta (samoocena jakości decyzji).

    Reużywa SSOT `policy_eval.evaluate_state` (bilans HP + kontrola/bliskość celów
    pkt 5, ADR-0031). Dodatnia wartość = aktywacja poprawiła pozycję bota wg jego
    własnej funkcji oceny. Czysta i deterministyczna (funkcja stanów, zero RNG).

    Uwaga (ograniczenie): `evaluate_state` czyta `obj.controller` jak jest
    (aktualizowany w `round_end_phase`, pkt 8.c.ii), więc przejęcie celu *w obrębie*
    aktywacji widać głównie jako proximity, nie pełną kontrolę — pełne potwierdzenie
    przychodzi na końcu rundy. To metryka "ruchu w dobrą stronę" wg bota, nie wyrocznia.
    """
    return evaluate_state(state_after, perspective) - evaluate_state(
        state_before, perspective
    )


@dataclass(slots=True)
class DecisionRecord:
    """Pojedyncza decyzja (aktywacja) bota."""

    kind: str
    perspective: int
    unit_id: int
    action_type: str  # etykieta PL (_ACTION_LABEL)
    decision_time_ms: float
    quality: float


@dataclass(slots=True)
class AgentMetrics:
    """Agregat metryk decyzji jednego bota (po nazwie `kind`)."""

    kind: str
    games: int = 0
    decisions: int = 0
    times_ms: list[float] = field(default_factory=list)
    sum_quality: float = 0.0
    positive_decisions: int = 0  # quality > 0
    action_counts: dict[str, int] = field(default_factory=dict)

    def add(self, rec: DecisionRecord) -> None:
        self.decisions += 1
        self.times_ms.append(rec.decision_time_ms)
        self.sum_quality += rec.quality
        if rec.quality > 0:
            self.positive_decisions += 1
        self.action_counts[rec.action_type] = (
            self.action_counts.get(rec.action_type, 0) + 1
        )

    @property
    def mean_quality(self) -> float:
        return self.sum_quality / self.decisions if self.decisions else 0.0

    @property
    def positive_rate(self) -> float:
        return self.positive_decisions / self.decisions if self.decisions else 0.0

    @property
    def mean_time_ms(self) -> float:
        return statistics.fmean(self.times_ms) if self.times_ms else 0.0

    @property
    def median_time_ms(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0.0

    @property
    def max_time_ms(self) -> float:
        return max(self.times_ms) if self.times_ms else 0.0


def aggregate_records(
    records: Sequence[DecisionRecord], *, games_by_kind: dict[str, int] | None = None
) -> dict[str, AgentMetrics]:
    """Grupuje `DecisionRecord`-y w `AgentMetrics` per `kind`.

    `games_by_kind` (opcjonalne) ustawia liczbę gier per bot (z drivera — liczba
    decyzji jej nie zna). Kolejność kluczy = pierwsze wystąpienie bota.
    """
    metrics: dict[str, AgentMetrics] = {}
    for rec in records:
        m = metrics.get(rec.kind)
        if m is None:
            m = AgentMetrics(kind=rec.kind)
            metrics[rec.kind] = m
        m.add(rec)
    if games_by_kind:
        for kind, games in games_by_kind.items():
            if kind in metrics:
                metrics[kind].games = games
    return metrics


# ---------------------------------------------------------------------------
# Driver — re-symulacja z hookiem on_decision
# ---------------------------------------------------------------------------


def collect_decisions(
    fixture,
    *,
    n: int,
    player_kinds: tuple[str, str],
    base_seed: int = 0,
) -> tuple[list[DecisionRecord], dict[str, int]]:
    """Rozgrywa N gier, zbiera decyzje obu botów przez `on_decision`.

    Metodyka identyczna z `balance_simulate.simulate_balance`: seed kości
    `base_seed+i`, inicjatywa `i % 2`, gracze z rozłącznych seedów (P0/P1).
    Zwraca płaską listę rekordów + `{kind: liczba_gier}`.
    """
    if n <= 0:
        raise ValueError(f"n musi być > 0, jest {n}")
    records: list[DecisionRecord] = []
    # owner_player→kind jest niezmienne między grami (inicjatywa zmienia tylko
    # kolejność, nie własność) → kolektor budowany raz.
    kind_by_player = {0: player_kinds[0], 1: player_kinds[1]}
    games_by_kind: dict[str, int] = {}
    for kind in player_kinds:  # set-like, zachowuje kolejność, dedup self-play
        games_by_kind.setdefault(kind, 0)

    def collect(perspective, unit_id, action, state_before, state_after, elapsed_ms):
        records.append(
            DecisionRecord(
                kind=kind_by_player[perspective],
                perspective=perspective,
                unit_id=unit_id,
                action_type=_ACTION_LABEL.get(
                    type(action).__name__, type(action).__name__
                ),
                decision_time_ms=elapsed_ms,
                quality=quality_from_states(state_before, state_after, perspective),
            )
        )

    for i in range(n):
        seed = base_seed + i
        players = [
            bsim.make_player(player_kinds[0], seed),
            bsim.make_player(player_kinds[1], seed + bsim.PLAYER_SEED_OFFSET),
        ]
        bsim.simulate_from_rosters(
            fixture.rosters,
            players,
            seed=seed,
            terrain=fixture.terrain,
            objectives=fixture.objectives,
            initiative_player=bsim.initiative_for_game(i),
            on_decision=collect,
        )
        for kind in games_by_kind:
            games_by_kind[kind] += 1
    return records, games_by_kind


# ---------------------------------------------------------------------------
# Serializacja maszynowa (JSON, schema szop.agent_metrics/v1)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "szop.agent_metrics/v1"


def metrics_to_dict(m: AgentMetrics) -> dict:
    """`AgentMetrics` → JSON-owalny dict (jeden rekord jsonl, schema v1).

    `decision_quality_score` deterministyczna; `decision_time_ms` zależy od
    maszyny (wall-clock) — pola czasowe NIE są stabilne między uruchomieniami.
    """
    return {
        "schema": SCHEMA_VERSION,
        "agent": m.kind,
        "games": m.games,
        "decisions": m.decisions,
        "decision_time_ms": {
            "mean": round(m.mean_time_ms, 4),
            "median": round(m.median_time_ms, 4),
            "max": round(m.max_time_ms, 4),
        },
        "decision_quality_score": {
            "mean": round(m.mean_quality, 4),
            "positive_rate": round(m.positive_rate, 4),
            "total": round(m.sum_quality, 4),
        },
        "action_mix": dict(sorted(m.action_counts.items())),
    }


def write_json(metrics: dict[str, AgentMetrics], path: str | os.PathLike) -> None:
    """Zapisuje metryki jako jsonl — jedna linia = jeden agent."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for m in metrics.values():
            fh.write(json.dumps(metrics_to_dict(m), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Raport markdown
# ---------------------------------------------------------------------------


def render_report(
    metrics: dict[str, AgentMetrics],
    *,
    fixture_name: str,
    player_kinds: tuple[str, str],
    n_games: int,
) -> str:
    """Czytelny raport markdown z metrykami per agent."""
    lines: list[str] = []
    lines.append(f"# Telemetria decyzji bota — {fixture_name}")
    lines.append("")
    lines.append(
        f"Matchup: `{player_kinds[0]}` vs `{player_kinds[1]}` · gier: {n_games} · "
        f"źródło: re-symulacja (ADR-0017)."
    )
    lines.append("")
    lines.append(
        "| Agent | Decyzje | Śr. jakość | % poprawia | Śr. czas [ms] | Mediana | Max |"
    )
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for m in metrics.values():
        lines.append(
            f"| `{m.kind}` | {m.decisions} | {m.mean_quality:+.2f} | "
            f"{m.positive_rate * 100:.0f}% | {m.mean_time_ms:.3f} | "
            f"{m.median_time_ms:.3f} | {m.max_time_ms:.3f} |"
        )
    lines.append("")
    lines.append("## Miks typów akcji (per agent)")
    lines.append("")
    for m in metrics.values():
        mix = ", ".join(f"{a}={c}" for a, c in sorted(m.action_counts.items()))
        lines.append(f"- `{m.kind}`: {mix or '—'}")
    lines.append("")
    lines.append(
        "> `decision_quality_score` = Δ `evaluate_state` (samoocena bota, SSOT "
        "policy_eval) — deterministyczna. `decision_time_ms` = wall-clock "
        "`choose_action` — zależy od maszyny, nie do regresji."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Telemetria decyzji bota per agent (ADR-0017).",
    )
    parser.add_argument(
        "--fixture",
        default=str(bsim.DEFAULT_FIXTURE),
        help="Ścieżka do fixtury roster-pair YAML (domyślnie demo_skirmish).",
    )
    parser.add_argument(
        "--map",
        default=None,
        help=f"Generowana mapa zamiast --fixture: {', '.join(sorted(bsim.MAP_BUILDERS))}.",
    )
    parser.add_argument(
        "--map-seed", type=int, default=0, help="Seed mapy generowanej (--map)."
    )
    parser.add_argument(
        "--players",
        default="priority,random",
        help="Para botów 'kind0,kind1' (np. priority,claude_v3).",
    )
    parser.add_argument(
        "-n", "--games", type=int, default=6, help="Liczba gier (domyślnie 6)."
    )
    parser.add_argument("--seed", type=int, default=0, help="Bazowy seed kości.")
    parser.add_argument(
        "--out", default=None, help="Zapis raportu markdown do pliku."
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="Zapis maszynowych metryk jsonl (data/agent_metrics/...).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        player_kinds = bsim._parse_players(args.players)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    try:
        fixture = (
            bsim.build_map(args.map, args.map_seed)
            if args.map
            else bsim.load_battle_fixture(args.fixture)
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    records, games_by_kind = collect_decisions(
        fixture, n=args.games, player_kinds=player_kinds, base_seed=args.seed
    )
    metrics = aggregate_records(records, games_by_kind=games_by_kind)

    report = render_report(
        metrics,
        fixture_name=fixture.name,
        player_kinds=player_kinds,
        n_games=args.games,
    )
    print(report)

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"\n[zapisano raport: {out}]")

    if args.json_path:
        write_json(metrics, args.json_path)
        print(f"[zapisano metryki jsonl: {args.json_path}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
