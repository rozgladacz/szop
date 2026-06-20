"""D2 — generator raportu balansu: round-robin turniej botów → reports/balance/YYYY-MM-DD.md.

Uruchom:
    python scripts/balance_report.py                                   # wszystkie fixtury + boty
    python scripts/balance_report.py -n 50 --players random,greedy,priority
    python scripts/balance_report.py --fixtures tests/fixtures/battles/demo_skirmish.yaml --out reports/balance/custom.md

Co robi (roadmap D2, `docs/roadmap.md#d2-balance-simulation`):
1. Dla każdej fixtury × każdej pary typów botów (round-robin — kombinacje
   z powtórzeniem; mirror P0↔P1 nesie `win_rate_p0`/`win_rate_p1`) rozgrywa
   N gier przez `simulate_balance` (SSOT — `balance_simulate.py`, ADR-0032).
2. Renderuje markdown: metadane przebiegu + per-fixtura tabela win-rate +
   tekstowe (unicode) wykresy słupkowe.
3. Zapisuje do `reports/balance/YYYY-MM-DD.md` (lub `--out`).

Zwycięzca = **pkt 5.f** SZOP_Rozjemca („Gra kończy się po 4 rundach. Wygrywa
gracz, który na koniec gry zajmuje więcej celów") — dziedziczone z
`simulate_balance`.

Skrypt-liść: zero zmian w rdzeniu silnika/agentach. Wykresy są **tekstowe**
(bez matplotlib) — dependency-free (patrz `HANDOFF_faza-d-balance-report.md`,
sekcja Decyzje). Headless/deterministyczny per `--seed` (ADR-0010/0012/0013).
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Sequence


def _load_balance_common():
    """Ładuje sąsiedni `balance_common.py` (wspólna infrastruktura skryptów balansu).

    scripts/ nie jest pakietem — spec/exec z cache w `sys.modules` (idempotentne).
    """
    name = "balance_common"
    if name in sys.modules:
        return sys.modules[name]
    script = pathlib.Path(__file__).resolve().parent / "balance_common.py"
    spec = importlib.util.spec_from_file_location(name, script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bc = _load_balance_common()
bsim = bc.bsim

# Re-eksport wspólnych helperów jako atrybuty modułu (API testów + użycie lokalne).
DEFAULT_FIXTURES = bc.DEFAULT_FIXTURES
DEFAULT_PLAYERS = bc.DEFAULT_PLAYERS  # = registry.USEFUL_KINDS (SSOT)
resolve_fixtures = bc.resolve_fixtures
_fixture_names_in_order = bc._fixture_names_in_order
_bar = bc._bar
_BAR_WIDTH = bc._BAR_WIDTH
_today = bc._today
write_report = bc.write_report
_parse_fixtures = bc._parse_fixtures
_parse_map_list = bc._parse_map_list
_parse_player_list = bc._parse_player_list


# ---------------------------------------------------------------------------
# Round-robin
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportConfig:
    """Konfiguracja przebiegu raportu."""

    n_games: int
    base_seed: int
    fixtures: tuple[str, ...]
    player_kinds: tuple[str, ...]
    generated_at: str  # ISO date (YYYY-MM-DD)
    maps: tuple[str, ...] = ()  # generowane mapy (MAP_BUILDERS), dodatkowo do fixtur
    map_seed: int = 0


def player_matchups(player_kinds: Sequence[str]) -> list[tuple[str, str]]:
    """Pary (P0, P1) round-robin — kombinacje z powtórzeniem.

    Mirror (P1 vs P0) jest zbędny: `BalanceResult` nesie zarówno `win_rate_p0`
    jak i `win_rate_p1`, a inicjatywa jest naprzemienna w `simulate_balance`.
    """
    return list(combinations_with_replacement(player_kinds, 2))


def run_round_robin(config: ReportConfig) -> list:
    """Rozgrywa round-robin: bitwa (fixtura/mapa) × para botów → lista `BalanceResult`.

    Kolejność wynikowa: bitwy (fixtury → mapy) × pary (round-robin).
    """
    results = []
    for fixture in resolve_fixtures(config):
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
# Render markdown
# ---------------------------------------------------------------------------


def format_markdown_report(results: Sequence, config: ReportConfig) -> str:
    """Buduje pełny raport markdown (metadane + per-fixtura tabela + wykresy)."""
    out: list[str] = [
        f"# Raport balansu — {config.generated_at}",
        "",
        f"- Gier na parę: **{config.n_games}**",
        f"- Bazowy seed: `{config.base_seed}`",
        "- Inicjatywa: naprzemienna (`i % 2`) — usuwa bias pierwszego gracza",
        "- Zwycięzca: **pkt 5.f** (gra kończy się po 4 rundach; wygrywa gracz "
        "zajmujący więcej celów)",
        f"- Boty: {', '.join(f'`{p}`' for p in config.player_kinds)}",
    ]
    if config.maps:
        out.append(f"- Mapy generowane (seed `{config.map_seed}`): "
                   f"{', '.join(f'`{m}`' for m in config.maps)}")
    out.append("")
    for fx in _fixture_names_in_order(results):
        fx_results = [r for r in results if r.fixture_name == fx]
        out.append(f"## Fixtura: {fx}")
        out.append("")
        out.append("| P0 | P1 | Gier | P0 % | P1 % | Remis % | Śr. rund |")
        out.append("|----|----|-----:|-----:|-----:|--------:|---------:|")
        for r in fx_results:
            out.append(
                f"| {r.player_kinds[0]} | {r.player_kinds[1]} | {r.n_games} "
                f"| {r.win_rate_p0:.1%} | {r.win_rate_p1:.1%} | {r.draw_rate:.1%} "
                f"| {r.avg_rounds:.2f} |"
            )
        out.append("")
        out.append("### Wykresy win-rate")
        out.append("")
        out.append("```")
        for r in fx_results:
            out.append(f"{r.player_kinds[0]} vs {r.player_kinds[1]}")
            out.append(f"  P0    {_bar(r.win_rate_p0)} {r.win_rate_p0:6.1%}")
            out.append(f"  P1    {_bar(r.win_rate_p1)} {r.win_rate_p1:6.1%}")
            out.append(f"  remis {_bar(r.draw_rate)} {r.draw_rate:6.1%}")
            out.append("")
        out.append("```")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def default_report_path(generated_at: str | None = None) -> pathlib.Path:
    """Domyślna ścieżka raportu: `reports/balance/YYYY-MM-DD.md` (repo root)."""
    return bc._repo_root / "reports" / "balance" / f"{generated_at or _today()}.md"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D2 — generator raportu balansu (round-robin botów → markdown).",
    )
    parser.add_argument(
        "--fixtures",
        type=_parse_fixtures,
        default=None,
        help="Lista fixtur 'a.yaml,b.yaml' (domyślnie: demo_skirmish, objective_clash, "
        "unit_profiles — pomijane gdy podano tylko --map).",
    )
    parser.add_argument(
        "--map",
        dest="maps",
        type=_parse_map_list,
        default=(),
        help=f"Mapy generowane (dodatkowo do fixtur): {', '.join(sorted(bsim.MAP_BUILDERS))}.",
    )
    parser.add_argument(
        "--map-seed",
        type=int,
        default=0,
        help="Seed dla generowanych map (domyślnie 0).",
    )
    parser.add_argument(
        "-n",
        "--games",
        type=int,
        default=50,
        help="Liczba gier na parę botów (domyślnie 50).",
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
        help=(
            f"Boty do round-robin: nazwy, TAGI (useful/fast/reference/…) lub 'all'. "
            f"Domyślnie 'useful' = {', '.join(DEFAULT_PLAYERS)}."
        ),
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Ścieżka raportu (domyślnie reports/balance/YYYY-MM-DD.md).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    # --fixtures jawne → użyj; inaczej default fixtury, chyba że podano tylko --map.
    if args.fixtures is not None:
        fixtures = tuple(args.fixtures)
    elif args.maps:
        fixtures = ()
    else:
        fixtures = DEFAULT_FIXTURES
    if not fixtures and not args.maps:
        raise SystemExit("Brak źródła bitew: podaj --fixtures lub --map.")
    config = ReportConfig(
        n_games=args.games,
        base_seed=args.seed,
        fixtures=fixtures,
        player_kinds=tuple(args.players),
        generated_at=_today(),
        maps=tuple(args.maps),
        map_seed=args.map_seed,
    )
    if config.n_games <= 0:
        raise SystemExit(f"-n musi być > 0, jest {config.n_games}")
    results = run_round_robin(config)
    text = format_markdown_report(results, config)
    out_path = pathlib.Path(args.out) if args.out else default_report_path(config.generated_at)
    write_report(text, out_path)
    n_pairs = len(player_matchups(config.player_kinds))
    n_battles = len(config.fixtures) + len(config.maps)
    print(f"Raport zapisany: {out_path}")
    print(
        f"  bitwy: {n_battles}  pary botów: {n_pairs}  "
        f"gier/para: {config.n_games}  (łącznie {len(results) * config.n_games} gier)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
