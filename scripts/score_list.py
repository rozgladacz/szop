"""C3 — `score_list`: ocenia JEDNĄ rozpiskę z bazy (po id) przez **agregację
wyników symulacji** przeciw POLU pozostałych rozpisek z DB (win-rate przeciw
każdemu przeciwnikowi + zagregowany wynik całości).

Uruchom:
    python scripts/score_list.py --list                  # rozpiski w bazie
    python scripts/score_list.py 1                        # roster 1 vs całe pole
    python scripts/score_list.py 1 -n 20 --bot priority --seed 3 --map lustrzana_a
    python scripts/score_list.py 1 --vs 2,5,8             # tylko wybrani przeciwnicy
    python scripts/score_list.py 1 --army "Testowa"       # pole z jednej armii

Deliverable Strumienia C3 (`score_list(roster_id)` — roadmap „Narzędzia MCP") w
formie **skryptu-liścia** (ADR-0013), zgodnie z decyzją usera 2026-06-26: pierwsza
wersja ocenia rozpiskę przez AGREGACJĘ wyników symulacji bitwy (później wynik ma
być interpretowany przez dedykowanego agenta — poza zakresem tego slice). Pełna
forma MCP-tool/HTTP czeka na serwer C1/B4.

Reuse SSOT przez sibling `scripts/simulate_engagement.py` (jeden pairing = jedna
`SimulationSummary` z `LocalClient.simulate_roster_ids`, B5 DB-backed) — ten slice
agreguje N takich pairingów (rozpiska oceniana zawsze jako `owner 0`) w jeden
wynik. Czynnik bota znosi się (ten sam bot po obu stronach jak w `simulate_engagement`);
różnica wyników = różnica rozpisek.

Różni się od istniejących narzędzi:
- `simulate_engagement` ocenia JEDNĄ parę (A vs B), nie pole;
- `exploit_hunt` generuje EFEMERYCZNE losowe rozpiski, nie ocenia istniejącej;
- `balance_report`/`leaderboard` rankingują BOTY, nie rozpiski usera.
Tu: jedna istniejąca rozpiska usera vs wszystkie pozostałe z DB → jej „siła" w polu.

Skrypt-liść: zero zmian w rdzeniu silnika/agentów/szop_client; DB tylko do odczytu.
Tryb `user_id=None` (narzędzie balansu) — bez scopingu własności.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Sequence

# UTF-8 stdout (nazwy rozpisek/armii PL na Windows cp1250 — jak simulate_engagement.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.db_bootstrap import initialized_session  # noqa: E402

# Reuse pairingu + opisu rozpiski z siblinga (SSOT — nie replikujemy mostu
# ORM→engine ani budowy graczy/map). Import wywołuje setup modułu (bsim, stdout).
from scripts.simulate_engagement import (  # noqa: E402
    DEFAULT_MAP,
    RosterInfo,
    _bar,
    _games_label,
    format_roster_list,
    list_rosters,
    roster_info,
    simulate_engagement,
)

from szop_client.local import RosterNotFoundError  # noqa: E402
from szop_client.protocol import SimulationSummary  # noqa: E402


# ---------------------------------------------------------------------------
# Agregacja (czyste funkcje — testowalne bez DB)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpponentResult:
    """Wynik oceny ocenianej rozpiski (owner 0) przeciw JEDNEMU przeciwnikowi."""

    opponent: RosterInfo
    summary: SimulationSummary

    @property
    def win_rate(self) -> float:
        # Oceniana rozpiska gra zawsze jako owner 0 → jej wygrane = wins_p0.
        return self.summary.win_rate_p0


@dataclass(frozen=True)
class ScoreSummary:
    """Zagregowany wynik ocenianej rozpiski przeciw całemu polu."""

    n_opponents: int
    n_games_total: int
    wins: int
    losses: int
    draws: int
    total_rounds: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.n_games_total if self.n_games_total else 0.0

    @property
    def loss_rate(self) -> float:
        return self.losses / self.n_games_total if self.n_games_total else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.n_games_total if self.n_games_total else 0.0

    @property
    def avg_rounds(self) -> float:
        return self.total_rounds / self.n_games_total if self.n_games_total else 0.0


def aggregate_score(results: Sequence[OpponentResult]) -> ScoreSummary:
    """Sumuje pairingi w jeden wynik (oceniana rozpiska = owner 0 w każdym)."""
    wins = sum(r.summary.wins_p0 for r in results)
    losses = sum(r.summary.wins_p1 for r in results)
    draws = sum(r.summary.draws for r in results)
    games = sum(r.summary.n_games for r in results)
    rounds = sum(r.summary.total_rounds for r in results)
    return ScoreSummary(
        n_opponents=len(results),
        n_games_total=games,
        wins=wins,
        losses=losses,
        draws=draws,
        total_rounds=rounds,
    )


# ---------------------------------------------------------------------------
# Symulacja (ścieżka DB)
# ---------------------------------------------------------------------------


def _select_opponents(
    session, roster_id: int, *, vs_ids: Sequence[int] | None, army: str | None
) -> list[RosterInfo]:
    """Pole przeciwników: wszystkie rozpiski poza ocenianą, opcjonalnie zawężone.

    `vs_ids` — jawna lista id przeciwników (pomija pozostałe filtry poza self).
    `army` — tylko rozpiski z armii o tej nazwie (case-insensitive).
    """
    field = [info for info in list_rosters(session) if info.id != roster_id]
    if vs_ids is not None:
        wanted = set(vs_ids)
        field = [info for info in field if info.id in wanted]
    elif army is not None:
        needle = army.casefold()
        field = [info for info in field if info.army.casefold() == needle]
    return field


def score_list(
    session,
    roster_id: int,
    *,
    bot: str = "priority",
    n: int = 10,
    seed: int = 0,
    map_name: str = DEFAULT_MAP,
    vs_ids: Sequence[int] | None = None,
    army: str | None = None,
) -> tuple[RosterInfo, list[OpponentResult]]:
    """Ocenia rozpiskę `roster_id` przez N gier przeciw każdemu przeciwnikowi w polu.

    Zwraca (info ocenianej rozpiski, lista `OpponentResult` posortowana po id
    przeciwnika). Deleguje każdy pairing do `simulate_engagement` (SSOT — most
    ORM→engine + agregacja pkt 5.f). Wszystkie pairingi używają tej samej mapy
    (ten sam `seed`) → spójne, deterministyczne tło oceny.

    Raises `RosterNotFoundError` gdy oceniana rozpiska nie istnieje.
    """
    from app import models

    target = session.get(models.Roster, roster_id)
    if target is None:
        raise RosterNotFoundError(f"Roster id={roster_id} nie istnieje")
    target_info = roster_info(target)

    opponents = _select_opponents(session, roster_id, vs_ids=vs_ids, army=army)
    results: list[OpponentResult] = []
    for opp in opponents:
        summary, _info_target, info_opp = simulate_engagement(
            session,
            roster_id,
            opp.id,
            bot=bot,
            n=n,
            seed=seed,
            map_name=map_name,
        )
        results.append(OpponentResult(opponent=info_opp, summary=summary))
    return target_info, results


# ---------------------------------------------------------------------------
# Output (czyste funkcje — testowalne bez DB)
# ---------------------------------------------------------------------------


def format_score_report(
    target: RosterInfo,
    results: Sequence[OpponentResult],
    aggregate: ScoreSummary,
    *,
    bot: str,
    map_name: str,
) -> str:
    """Raport tekstowy: nagłówek ocenianej rozpiski + per-przeciwnik win-rate +
    zagregowany wynik (siła w polu) + sygnał koszt↔wynik."""
    lines = [
        f"Ocena rozpiski [{target.id}] {target.name} ({target.army}) — {target.points:.0f} pkt",
        f"  skład: {target.composition}",
        f"  (bot={bot}, mapa={map_name}, naprzemienna inicjatywa, "
        f"{_games_label(aggregate.n_games_total // aggregate.n_opponents) if aggregate.n_opponents else '0 gier'}/przeciwnika)",
        "=" * 72,
    ]
    if not results:
        lines.append("Brak przeciwników w polu (potrzeba ≥1 innej rozpiski w bazie).")
        return "\n".join(lines)

    lines.append(f"{'id':>4}  {'win':>6}  {'pkt':>6}  {'Δpkt':>6}  przeciwnik / skład")
    lines.append("-" * 72)
    for r in sorted(results, key=lambda r: r.opponent.id):
        opp = r.opponent
        d_pts = opp.points - target.points
        lines.append(
            f"{opp.id:>4}  {r.win_rate:>6.1%}  {opp.points:>6.0f}  {d_pts:>+6.0f}  "
            f"{opp.name[:20]} ({opp.army}) — {opp.composition}"
        )
    lines += [
        "-" * 72,
        f"  SIŁA W POLU: {aggregate.win_rate:.1%}  {_bar(aggregate.win_rate)}",
        f"  wygrane {aggregate.wins} / przegrane {aggregate.losses} / "
        f"remisy {aggregate.draws}  ({_games_label(aggregate.n_games_total)} vs "
        f"{aggregate.n_opponents} przeciwnik(ów))",
        f"  śr. rund/grę: {aggregate.avg_rounds:.2f}",
    ]

    # Sygnał koszt↔wynik: czy rozpiska wygrywa ponad/poniżej swojego kosztu.
    cheaper = [r for r in results if r.opponent.points < target.points]
    pricier = [r for r in results if r.opponent.points > target.points]
    if cheaper:
        wr_vs_cheaper = sum(r.summary.wins_p0 for r in cheaper) / sum(
            r.summary.n_games for r in cheaper
        )
        lines.append(
            f"  vs tańsi ({len(cheaper)}): {wr_vs_cheaper:.0%} — "
            f"{'oczekiwane (droższa wygrywa)' if wr_vs_cheaper >= 0.5 else 'SYGNAŁ: przegrywa z tańszymi (możliwe przeszacowanie)'}"
        )
    if pricier:
        wr_vs_pricier = sum(r.summary.wins_p0 for r in pricier) / sum(
            r.summary.n_games for r in pricier
        )
        lines.append(
            f"  vs drożsi ({len(pricier)}): {wr_vs_pricier:.0%} — "
            f"{'SYGNAŁ: wygrywa z droższymi (możliwe niedoszacowanie)' if wr_vs_pricier > 0.5 else 'oczekiwane (droższa wygrywa)'}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_vs(raw: str | None) -> list[int] | None:
    """Parsuje `--vs "2,5,8"` na listę id (None gdy nie podano)."""
    if raw is None:
        return None
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part))  # ValueError → czysty błąd CLI w main()
    return ids


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C3 score_list — ocena rozpiski przez agregację symulacji vs pole.",
    )
    parser.add_argument("roster", type=int, nargs="?", help="id ocenianej rozpiski (owner 0).")
    parser.add_argument("-n", "--games", type=int, default=10, help="gier na przeciwnika (≥1).")
    parser.add_argument(
        "--bot", type=str, default="priority",
        help="bot po OBU stronach (porównanie rozpisek, nie botów; domyślnie 'priority').",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed determinizmu.")
    parser.add_argument("--map", type=str, default=DEFAULT_MAP, help="mapa (teren+cele) z balance_simulate.")
    parser.add_argument(
        "--vs", type=str, default=None,
        help="ogranicz pole do tych id przeciwników (CSV, np. '2,5,8').",
    )
    parser.add_argument(
        "--army", type=str, default=None,
        help="ogranicz pole do rozpisek z tej armii (ignorowane gdy podano --vs).",
    )
    parser.add_argument("--list", action="store_true", help="wypisz rozpiski w bazie i zakończ.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    with initialized_session() as session:
        if args.list:
            print(format_roster_list(list_rosters(session)))
            return 0

        if args.roster is None:
            print(
                "Podaj id ocenianej rozpiski (np. `score_list.py 1`) lub `--list`.",
                file=sys.stderr,
            )
            return 2
        if args.games < 1:
            print(f"--games musi być ≥1, jest {args.games}.", file=sys.stderr)
            return 2
        try:
            vs_ids = _parse_vs(args.vs)
        except ValueError:
            print(f"--vs musi być listą id rozdzielonych przecinkiem, jest {args.vs!r}.", file=sys.stderr)
            return 2

        try:
            target, results = score_list(
                session,
                args.roster,
                bot=args.bot,
                n=args.games,
                seed=args.seed,
                map_name=args.map,
                vs_ids=vs_ids,
                army=args.army,
            )
        except RosterNotFoundError as exc:
            print(f"Nie znaleziono rozpiski: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        aggregate = aggregate_score(results)

    print(format_score_report(target, results, aggregate, bot=args.bot, map_name=args.map))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
