"""D4 — leaderboard botów: round-robin wszystkich typów → kanoniczny ranking ogólny.

Uruchom:
    python scripts/leaderboard.py                                   # wszystkie fixtury + boty
    python scripts/leaderboard.py -n 20 --players random,greedy,priority
    python scripts/leaderboard.py --out reports/leaderboard.md

Co robi (roadmap D4, `docs/roadmap.md#d4-adversarial-play`):
1. Dla każdej fixtury × każdej **nieuporządkowanej pary różnych** botów rozgrywa
   N gier przez `simulate_balance` (SSOT — `balance_simulate.py`, ADR-0032).
2. Agreguje wynik **ponad parami** w jeden standing per bot (gry / wygrane /
   porażki / remisy / win-rate) — różni się od `balance_report.py`, który daje
   macierz pairwise. Mirror self-play (A vs A) wykluczony: deterministyczny
   remis, nieinformatywny dla rankingu (np. greedy/greedy 100% remisów).
3. Renderuje markdown: metadane + tabela rankingowa + tekstowe (unicode) słupki
   win-rate. Zapisuje do `reports/leaderboard.md` (lub `--out`).

Zwycięzca pojedynczej gry = **pkt 5.f** SZOP_Rozjemca („Gra kończy się po 4
rundach. Wygrywa gracz, który na koniec gry zajmuje więcej celów") —
dziedziczone z `simulate_balance`.

Skrypt-liść: zero zmian w rdzeniu silnika/agentach. Wykresy **tekstowe** (bez
matplotlib) — dependency-free, jak `balance_report.py`. Headless/deterministyczny
per `--seed` (ADR-0010/0012/0013). Ranking botów teraz; osobne konta agentów
(`agent_kind`) + leaderboard międzykontowy odłożone do B2 auth (ADR-0030).
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import os
import pathlib
import sys
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

# UTF-8 stdout (nazwy botów/fixtur PL na Windows cp1250 — jak balance_simulate.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _load_balance_simulate():
    """Ładuje sąsiedni `balance_simulate.py` jako moduł (scripts/ nie jest pakietem).

    Rejestracja w `sys.modules` PRZED exec — `dataclass(slots=True)` rozwiązuje
    `cls.__module__` przez `sys.modules.get(...)` (jak w `balance_report.py`).
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

#: Domyślne fixtury gdy `--fixtures` nie podane (wszystkie z tests/fixtures/battles/).
DEFAULT_FIXTURES: tuple[str, ...] = tuple(
    str(_repo_root / "tests" / "fixtures" / "battles" / f"{stem}.yaml")
    for stem in ("demo_skirmish", "objective_clash", "unit_profiles")
)

#: Domyślny zestaw botów do rankingu.
DEFAULT_PLAYERS: tuple[str, ...] = tuple(bsim.PLAYER_KINDS)

_BAR_WIDTH = 24


# ---------------------------------------------------------------------------
# Konfiguracja + round-robin
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeaderboardConfig:
    """Konfiguracja przebiegu leaderboardu."""

    n_games: int
    base_seed: int
    fixtures: tuple[str, ...]
    player_kinds: tuple[str, ...]
    generated_at: str  # ISO date (YYYY-MM-DD)


def player_matchups(player_kinds: Sequence[str]) -> list[tuple[str, str]]:
    """Pary (P0, P1) — **nieuporządkowane, różne** boty (mirror wykluczony).

    `simulate_balance` zwraca zarówno `win_rate_p0` jak `win_rate_p1` (inicjatywa
    naprzemienna), więc jeden kierunek pary wystarcza. Mirror (A vs A) pomijamy:
    deterministyczny remis dla botów deterministycznych — nie wnosi sygnału do
    rankingu ogólnego.
    """
    return list(combinations(player_kinds, 2))


def run_leaderboard(config: LeaderboardConfig) -> list:
    """Rozgrywa round-robin: fixtura × para różnych botów → lista `BalanceResult`."""
    results = []
    for fx_path in config.fixtures:
        fixture = bsim.load_battle_fixture(fx_path)
        for kinds in player_matchups(config.player_kinds):
            results.append(
                bsim.simulate_balance(
                    fixture,
                    n=config.n_games,
                    player_kinds=kinds,
                    base_seed=config.base_seed,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Standings (agregacja ponad parami)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BotStanding:
    """Standing ogólny jednego bota zagregowany ze wszystkich par/fixtur."""

    kind: str
    games: int
    wins: int
    losses: int
    draws: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def loss_rate(self) -> float:
        return self.losses / self.games if self.games else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.games if self.games else 0.0


def compute_standings(
    results: Sequence, player_kinds: Sequence[str]
) -> list[BotStanding]:
    """Agreguje `BalanceResult` ponad parami w ranking per bot.

    Dla każdej pary (A=P0, B=P1): A zalicza `wins_p0` wygranych, `wins_p1`
    porażek, `draws` remisów; B symetrycznie. Sumowane po wszystkich fixturach.
    Ranking malejący po win-rate; tiebreak: więcej wygranych → mniej porażek →
    nazwa (deterministyczny).
    """
    games = {k: 0 for k in player_kinds}
    wins = {k: 0 for k in player_kinds}
    losses = {k: 0 for k in player_kinds}
    draws = {k: 0 for k in player_kinds}
    for r in results:
        p0, p1 = r.player_kinds
        if p0 == p1 or p0 not in games or p1 not in games:
            continue  # mirror lub bot spoza zestawu — pomiń
        games[p0] += r.n_games
        games[p1] += r.n_games
        wins[p0] += r.wins_p0
        wins[p1] += r.wins_p1
        losses[p0] += r.wins_p1
        losses[p1] += r.wins_p0
        draws[p0] += r.draws
        draws[p1] += r.draws
    standings = [
        BotStanding(
            kind=k,
            games=games[k],
            wins=wins[k],
            losses=losses[k],
            draws=draws[k],
        )
        for k in player_kinds
    ]
    standings.sort(key=lambda s: (-s.win_rate, -s.wins, s.losses, s.kind))
    return standings


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------


def _bar(fraction: float, width: int = _BAR_WIDTH) -> str:
    """Tekstowy słupek `█`/`░` o długości `width` proporcjonalny do `fraction` (0..1)."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _fixture_names_in_order(results: Sequence) -> list[str]:
    """Unikalne nazwy fixtur zachowując kolejność wystąpienia."""
    seen: list[str] = []
    for r in results:
        if r.fixture_name not in seen:
            seen.append(r.fixture_name)
    return seen


def format_leaderboard(
    standings: Sequence[BotStanding],
    config: LeaderboardConfig,
    results: Sequence | None = None,
) -> str:
    """Buduje pełny leaderboard markdown (metadane + tabela rankingowa + wykresy)."""
    fixtures = _fixture_names_in_order(results) if results else []
    out: list[str] = [
        f"# Leaderboard botów — {config.generated_at}",
        "",
        f"- Gier na parę: **{config.n_games}**",
        f"- Bazowy seed: `{config.base_seed}`",
        "- Pary: round-robin **różnych** botów (mirror self-play wykluczony)",
        "- Inicjatywa: naprzemienna (`i % 2`) — usuwa bias pierwszego gracza",
        "- Zwycięzca gry: **pkt 5.f** (gra kończy się po 4 rundach; wygrywa gracz "
        "zajmujący więcej celów)",
        f"- Boty: {', '.join(f'`{p}`' for p in config.player_kinds)}",
    ]
    if fixtures:
        out.append(f"- Fixtury: {', '.join(f'`{f}`' for f in fixtures)}")
    out.append("")
    out.append("## Ranking")
    out.append("")
    out.append("| # | Bot | Gier | Wygrane | Porażki | Remisy | Win-rate |")
    out.append("|--:|-----|-----:|--------:|--------:|-------:|---------:|")
    for rank, s in enumerate(standings, start=1):
        out.append(
            f"| {rank} | {s.kind} | {s.games} | {s.wins} | {s.losses} "
            f"| {s.draws} | {s.win_rate:.1%} |"
        )
    out.append("")
    out.append("### Wykres win-rate")
    out.append("")
    out.append("```")
    name_width = max((len(s.kind) for s in standings), default=0)
    for s in standings:
        out.append(f"{s.kind:<{name_width}}  {_bar(s.win_rate)} {s.win_rate:6.1%}")
    out.append("```")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.date.today().isoformat()


def default_report_path() -> pathlib.Path:
    """Domyślna ścieżka leaderboardu: `reports/leaderboard.md` (repo root)."""
    return _repo_root / "reports" / "leaderboard.md"


def write_report(text: str, path: str | os.PathLike) -> None:
    """Zapisuje raport (tworzy katalogi nadrzędne jeśli trzeba)."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_fixtures(spec: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in spec.split(",") if p.strip())
    if not parts:
        raise argparse.ArgumentTypeError("--fixtures: oczekiwano ≥1 ścieżki")
    return parts


def _parse_player_list(spec: str) -> tuple[str, ...]:
    parts = [p.strip().lower() for p in spec.split(",") if p.strip()]
    for p in parts:
        if p not in bsim.PLAYER_KINDS:
            raise argparse.ArgumentTypeError(
                f"Nieznany gracz {p!r}; dozwolone: {', '.join(bsim.PLAYER_KINDS)}"
            )
    # Dedup zachowując kolejność.
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
    if len(out) < 2:
        raise argparse.ArgumentTypeError(
            "--players: oczekiwano ≥2 różnych typów do round-robin"
        )
    return tuple(out)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D4 — leaderboard botów (round-robin → ranking ogólny → markdown).",
    )
    parser.add_argument(
        "--fixtures",
        type=_parse_fixtures,
        default=DEFAULT_FIXTURES,
        help="Lista fixtur 'a.yaml,b.yaml' (domyślnie: demo_skirmish, objective_clash, unit_profiles).",
    )
    parser.add_argument(
        "-n",
        "--games",
        type=int,
        default=30,
        help="Liczba gier na parę botów (domyślnie 30).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Bazowy seed; gra i używa seedu base+i (domyślnie 0).",
    )
    parser.add_argument(
        "--players",
        type=_parse_player_list,
        default=DEFAULT_PLAYERS,
        help=f"Boty do round-robin (domyślnie wszystkie: {', '.join(DEFAULT_PLAYERS)}).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Ścieżka raportu (domyślnie reports/leaderboard.md).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = LeaderboardConfig(
        n_games=args.games,
        base_seed=args.seed,
        fixtures=tuple(args.fixtures),
        player_kinds=tuple(args.players),
        generated_at=_today(),
    )
    if config.n_games <= 0:
        raise SystemExit(f"-n musi być > 0, jest {config.n_games}")
    results = run_leaderboard(config)
    standings = compute_standings(results, config.player_kinds)
    text = format_leaderboard(standings, config, results)
    out_path = pathlib.Path(args.out) if args.out else default_report_path()
    write_report(text, out_path)
    n_pairs = len(player_matchups(config.player_kinds))
    print(f"Leaderboard zapisany: {out_path}")
    print(
        f"  fixtury: {len(config.fixtures)}  pary botów: {n_pairs}  "
        f"gier/para: {config.n_games}  (łącznie {len(results) * config.n_games} gier)"
    )
    if standings:
        top = standings[0]
        print(f"  lider: {top.kind} ({top.win_rate:.1%} win-rate, {top.games} gier)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
