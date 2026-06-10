"""D2 — agregator balansu: rozgrywa N headless gier i raportuje win-rate.

Uruchom:
    python scripts/balance_simulate.py                          # demo fixtura
    python scripts/balance_simulate.py -n 200 --players greedy,random
    python scripts/balance_simulate.py --fixture tests/fixtures/battles/demo_skirmish.yaml --out build/balance.csv

Co robi (roadmap D2, `docs/roadmap.md#d2-balance-simulation`):
1. Ładuje parę rosterów + teren + cele z fixtury YAML (format engine-dict,
   patrz `tests/fixtures/battles/demo_skirmish.yaml`).
2. Rozgrywa N pełnych gier przez `app.services.agents.simulate_from_rosters`
   (headless match runner, ADR-0032). Seed kości = `base_seed + i`,
   **inicjatywa naprzemienna** (`i % 2`) — usuwa bias pierwszego gracza
   z metryki balansu.
3. Agreguje zwycięzców (pkt 5.f: „Gra kończy się po 4 rundach; wygrywa gracz,
   który na koniec gry zajmuje więcej celów") → win-rate / draw-rate per
   roster (owner_player 0/1) + średnia liczba rund.
4. Wypisuje podsumowanie na stdout; opcjonalnie zapisuje CSV (`--out`).

Headless / deterministyczny (ADR-0010/0012/0013): zero DB/HTTP, wynik
reprodukowalny per `--seed`. To konsument zalążka B5 `LocalClient.simulate`.
**Zero zmian w rdzeniu silnika ani warstwie agentów** — skrypt-liść.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Sequence

import yaml

# UTF-8 stdout niezależnie od kodeka konsoli (nazwy broni/rosterów PL na Windows
# cp1250 crashują mid-run — jak w `scripts/profile_quote.py`).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# `import app.*` działa niezależnie od katalogu wywołania.
_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.services.agents import (  # noqa: E402
    GreedyPlayer,
    Player,
    RandomPlayer,
    simulate_from_rosters,
)
from app.services.engine.state import (  # noqa: E402
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
)

#: Domyślna fixtura gdy `--fixture` nie podane.
DEFAULT_FIXTURE = _repo_root / "tests" / "fixtures" / "battles" / "demo_skirmish.yaml"

PLAYER_KINDS = ("random", "greedy")


# ---------------------------------------------------------------------------
# Fixtura
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BattleFixture:
    """Para rosterów + teren + cele wczytane z YAML."""

    name: str
    rosters: tuple[dict, ...]
    terrain: tuple[TerrainCircle | TerrainLine, ...]
    objectives: tuple[Objective, ...]


def _parse_terrain(raw: Sequence[dict]) -> tuple[TerrainCircle | TerrainLine, ...]:
    out: list[TerrainCircle | TerrainLine] = []
    for t in raw or ():
        shape = str(t.get("shape", "circle")).lower()
        features = tuple(t.get("features", ()))
        if shape == "circle":
            cx, cy = t["center"]
            out.append(
                TerrainCircle(
                    center=Position(float(cx), float(cy)),
                    radius_inches=float(t["radius"]),
                    features=features,
                )
            )
        elif shape == "line":
            sx, sy = t["start"]
            ex, ey = t["end"]
            out.append(
                TerrainLine(
                    start=Position(float(sx), float(sy)),
                    end=Position(float(ex), float(ey)),
                    features=features,
                )
            )
        else:
            raise ValueError(f"Nieznany kształt terenu: {shape!r} (oczekiwano circle/line)")
    return tuple(out)


def _parse_objectives(raw: Sequence[dict]) -> tuple[Objective, ...]:
    out: list[Objective] = []
    for o in raw or ():
        ox, oy = o["position"]
        out.append(Objective(id=int(o["id"]), position=Position(float(ox), float(oy))))
    return tuple(out)


def load_battle_fixture(path: str | os.PathLike) -> BattleFixture:
    """Parsuje fixturę roster-pair YAML → `BattleFixture`.

    Rostery przekazywane jako surowe dict-y (engine-dict 1:1 z
    `build_initial_state`); teren/cele konwertowane na dataclassy silnika.
    """
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rosters = data.get("rosters")
    if not isinstance(rosters, list) or len(rosters) != 2:
        raise ValueError(f"Fixtura {path}: oczekiwano dokładnie 2 rosterów, jest {rosters!r}")
    return BattleFixture(
        name=str(data.get("name", pathlib.Path(path).stem)),
        rosters=tuple(rosters),
        terrain=_parse_terrain(data.get("terrain", ())),
        objectives=_parse_objectives(data.get("objectives", ())),
    )


# ---------------------------------------------------------------------------
# Gracze
# ---------------------------------------------------------------------------


def make_player(kind: str, seed: int) -> Player:
    """Buduje gracza D1 z nazwy. `greedy` ignoruje seed (deterministyczny)."""
    kind = kind.lower()
    if kind == "random":
        return RandomPlayer(seed=seed)
    if kind == "greedy":
        return GreedyPlayer()
    raise ValueError(f"Nieznany typ gracza: {kind!r} (oczekiwano {PLAYER_KINDS})")


# ---------------------------------------------------------------------------
# Agregacja
# ---------------------------------------------------------------------------


def initiative_for_game(i: int) -> int:
    """Naprzemienna inicjatywa per grę (usuwa bias pierwszego gracza)."""
    return i % 2


@dataclass(frozen=True, slots=True)
class BalanceResult:
    """Zagregowany wynik N gier. `wins_p*` per owner_player (nie per inicjatywa)."""

    fixture_name: str
    player_kinds: tuple[str, str]
    n_games: int
    wins_p0: int
    wins_p1: int
    draws: int
    total_rounds: int

    @property
    def win_rate_p0(self) -> float:
        return self.wins_p0 / self.n_games if self.n_games else 0.0

    @property
    def win_rate_p1(self) -> float:
        return self.wins_p1 / self.n_games if self.n_games else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.n_games if self.n_games else 0.0

    @property
    def avg_rounds(self) -> float:
        return self.total_rounds / self.n_games if self.n_games else 0.0

    def csv_header(self) -> list[str]:
        return [
            "fixture",
            "player0",
            "player1",
            "n_games",
            "wins_p0",
            "wins_p1",
            "draws",
            "win_rate_p0",
            "win_rate_p1",
            "draw_rate",
            "avg_rounds",
        ]

    def csv_row(self) -> list[str]:
        return [
            self.fixture_name,
            self.player_kinds[0],
            self.player_kinds[1],
            str(self.n_games),
            str(self.wins_p0),
            str(self.wins_p1),
            str(self.draws),
            f"{self.win_rate_p0:.4f}",
            f"{self.win_rate_p1:.4f}",
            f"{self.draw_rate:.4f}",
            f"{self.avg_rounds:.2f}",
        ]


def simulate_balance(
    fixture: BattleFixture,
    *,
    n: int,
    player_kinds: tuple[str, str],
    base_seed: int = 0,
) -> BalanceResult:
    """Rozgrywa N gier i agreguje zwycięzców per owner_player.

    Każda gra: seed kości = `base_seed + i`, inicjatywa = `i % 2`. Gracze
    budowani świeżo per grę z seedem pochodnym (`base_seed + i`) — dla
    `RandomPlayer` daje wariację decyzji niezależnie od kości; `GreedyPlayer`
    seed ignoruje. Zwycięzca z `MatchResult.winner ∈ {0,1,None}` (pkt 5.f).
    """
    if n <= 0:
        raise ValueError(f"n musi być > 0, jest {n}")
    wins = [0, 0]
    draws = 0
    total_rounds = 0
    for i in range(n):
        seed = base_seed + i
        players = [make_player(player_kinds[0], seed), make_player(player_kinds[1], seed)]
        result = simulate_from_rosters(
            fixture.rosters,
            players,
            seed=seed,
            terrain=fixture.terrain,
            objectives=fixture.objectives,
            initiative_player=initiative_for_game(i),
        )
        if result.winner is None:
            draws += 1
        else:
            wins[result.winner] += 1
        total_rounds += result.rounds_played
    return BalanceResult(
        fixture_name=fixture.name,
        player_kinds=player_kinds,
        n_games=n,
        wins_p0=wins[0],
        wins_p1=wins[1],
        draws=draws,
        total_rounds=total_rounds,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def format_summary(result: BalanceResult) -> str:
    """Czytelne podsumowanie na stdout."""
    lines = [
        f"Fixtura : {result.fixture_name}",
        f"Gracze  : P0={result.player_kinds[0]}  vs  P1={result.player_kinds[1]}",
        f"Gier    : {result.n_games}  (inicjatywa naprzemienna)",
        "-" * 48,
        f"  P0 wygrane : {result.wins_p0:>5}  ({result.win_rate_p0:6.1%})",
        f"  P1 wygrane : {result.wins_p1:>5}  ({result.win_rate_p1:6.1%})",
        f"  Remisy     : {result.draws:>5}  ({result.draw_rate:6.1%})",
        "-" * 48,
        f"  Śr. rund   : {result.avg_rounds:.2f}",
    ]
    return "\n".join(lines)


def result_to_csv_string(result: BalanceResult) -> str:
    """CSV (header + 1 wiersz) jako string."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(result.csv_header())
    writer.writerow(result.csv_row())
    return buf.getvalue()


def write_csv(result: BalanceResult, path: str | os.PathLike) -> None:
    """Zapisuje wynik jako CSV (tworzy katalog nadrzędny jeśli trzeba)."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""` — `csv` sam zarządza line-terminatorem (\r\n), bez translacji.
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(result_to_csv_string(result))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_players(spec: str) -> tuple[str, str]:
    parts = [p.strip().lower() for p in spec.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"--players oczekuje 'p0,p1' (2 wartości), dostało {spec!r}"
        )
    for p in parts:
        if p not in PLAYER_KINDS:
            raise argparse.ArgumentTypeError(
                f"Nieznany gracz {p!r}; dozwolone: {', '.join(PLAYER_KINDS)}"
            )
    return (parts[0], parts[1])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D2 — agreguje N headless gier → win-rate balansu (CSV + podsumowanie).",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=str(DEFAULT_FIXTURE),
        help="Ścieżka do fixtury roster-pair YAML (domyślnie demo_skirmish).",
    )
    parser.add_argument(
        "-n",
        "--games",
        type=int,
        default=100,
        help="Liczba gier do rozegrania (domyślnie 100).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Bazowy seed; gra i używa seedu base+i (domyślnie 0).",
    )
    parser.add_argument(
        "--players",
        type=_parse_players,
        default=("random", "random"),
        help="Para graczy 'p0,p1' z {random, greedy} (domyślnie random,random).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Ścieżka pliku CSV (domyślnie: tylko podsumowanie na stdout).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    fixture = load_battle_fixture(args.fixture)
    result = simulate_balance(
        fixture,
        n=args.games,
        player_kinds=args.players,
        base_seed=args.seed,
    )
    print(format_summary(result))
    if args.out:
        write_csv(result, args.out)
        print(f"\nCSV zapisany: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
