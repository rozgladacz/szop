"""C3 — `score_list`: ocenia JEDNĄ rozpiskę z bazy (po id) przez **agregację
wyników symulacji** przeciw POLU pozostałych rozpisek z DB (win-rate przeciw
każdemu przeciwnikowi + zagregowany wynik całości).

Uruchom:
    python scripts/score_list.py --list                  # rozpiski w bazie
    python scripts/score_list.py 1                        # roster 1 vs całe pole
    python scripts/score_list.py 1 -n 20 --bot priority --seed 3 --map lustrzana_a
    python scripts/score_list.py 1 --vs 2,5,8             # tylko wybrani przeciwnicy
    python scripts/score_list.py 1 --army "Testowa"       # pole z jednej armii

Leaf-CLI (ADR-0013) zachowuje historyczny raport i filtry. Produkcyjny SSOT
`app.services.roster_scoring` obsługuje również owner-scoped API, `HttpClient` i
MCP; wspólny pairing deleguje do `app.services.roster_simulation`. Rozpiska
oceniana jest zawsze jako gracz 0. Interpretacja wyniku przez dedykowanego agenta
pozostaje poza zakresem.

Różni się od istniejących narzędzi:
- `simulate_engagement` ocenia JEDNĄ parę (A vs B), nie pole;
- `exploit_hunt` generuje EFEMERYCZNE losowe rozpiski, nie ocenia istniejącej;
- `balance_report`/`leaderboard` rankingują BOTY, nie rozpiski usera.
Tu: jedna istniejąca rozpiska usera vs wszystkie pozostałe z DB → jej „siła" w polu.

Skrypt-liść nie zapisuje wyników ani nie zmienia mechaniki silnika; DB tylko do odczytu.
Tryb `user_id=None` (narzędzie balansu) — bez scopingu własności.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
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

# Zachowaj historyczne eksporty formatowania i pairingu dla call sites leaf-CLI.
from scripts.simulate_engagement import (  # noqa: E402
    DEFAULT_MAP,
    _bar,
    _games_label,
    format_roster_list,
    simulate_engagement,
)

from app.services.roster_scoring import (  # noqa: E402
    OpponentResult,
    RosterInfo,
    RosterNotFoundError,
    ScoreSummary,
    _select_opponents,
    aggregate_score,
    list_rosters,
    score_list,
)


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
