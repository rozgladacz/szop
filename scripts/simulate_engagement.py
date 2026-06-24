"""C3 — `simulate_engagement`: rozgrywa N gier head-to-head między DWIEMA
KONKRETNYMI rozpiskami z bazy (po id) i raportuje wynik (win-rate A/B/remis +
śr. rundy + koszt punktowy).

Uruchom:
    python scripts/simulate_engagement.py --list                 # rozpiski w bazie
    python scripts/simulate_engagement.py 1 2                     # roster 1 vs roster 2
    python scripts/simulate_engagement.py 1 2 -n 20 --bot priority --seed 3 --map lustrzana_a

Deliverable Strumienia C3 (`simulate_engagement(roster_a, roster_b, n)` — roadmap
„Narzędzia MCP") w formie **skryptu-liścia** (ADR-0013), równolegle do
`exploit_hunt.py`/`battle_replay.py`/`leaderboard.py`. Pełna forma MCP-tool/HTTP
czeka na serwer C1/B4. Opiera się na `LocalClient.simulate_roster_ids` (B5
DB-backed, `szop_client/local.py`) — zbudowanym **jawnie jako enabler C3** — więc
ćwiczy seam `GameClient` end-to-end zamiast obchodzić go bezpośrednim runnerem.

Różni się od istniejących narzędzi:
- `balance_simulate` gra rostery z fixtur YAML (engine-dict), nie z bazy;
- `exploit_hunt` generuje EFEMERYCZNE losowe rozpiski z puli jednostek;
- `leaderboard`/`balance_report` rankingują BOTY, nie rozpiski.
Tu: dwie istniejące rozpiski usera z DB, ten sam bot po obu stronach (porównanie
ROZPISEK, nie botów), naprzemienna inicjatywa + rozłączne seedy graczy (jak D2).

Skrypt-liść: zero zmian w rdzeniu silnika/agentów/szop_client; DB tylko do odczytu.
Tryb `user_id=None` (narzędzie balansu) — bez scopingu własności (czyta każdą rozpiskę).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Sequence

# UTF-8 stdout (nazwy rozpisek/armii PL na Windows cp1250 — jak exploit_hunt.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.services.agents import roster_points  # noqa: E402
from szop_client.local import LocalClient, RosterNotFoundError  # noqa: E402
from szop_client.protocol import SimulationSummary  # noqa: E402


def _load_balance_simulate():
    """Ładuje sąsiedni `balance_simulate.py` jako moduł (scripts/ nie jest pakietem).

    Reuse `make_player`/`build_map`/`initiative_for_game`/`PLAYER_SEED_OFFSET` (SSOT
    budowy graczy + map + rozłącznego seedowania). Wzorzec jak `exploit_hunt.py`.
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

# Plansza pkt 3.b (6′×4′ = 72″×48″); strefy wg pkt 3.a + 24.a, spójnie
# z exploit_hunt.DEPLOY_ZONES. Importujemy DeploymentZone z pakietu agentów.
from app.services.agents import DeploymentZone  # noqa: E402

BOARD_W, BOARD_H = 72.0, 48.0
ZONE_DEPTH = 12.0
DEPLOY_ZONES = (
    DeploymentZone(0.0, 0.0, BOARD_W, ZONE_DEPTH),
    DeploymentZone(0.0, BOARD_H - ZONE_DEPTH, BOARD_W, BOARD_H),
)
DEFAULT_MAP = "lustrzana_a"  # lustro y=24 → równe dla stref bottom/top (jak exploit_hunt)


# ---------------------------------------------------------------------------
# Info o rozpisce (do raportu + --list)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterInfo:
    """Lekki opis rozpiski do raportu (bez trzymania obiektu ORM po zamknięciu sesji)."""

    id: int
    name: str
    army: str
    points: float
    composition: str


def _composition_summary(roster) -> str:
    parts = []
    for ru in getattr(roster, "roster_units", []) or []:
        unit = getattr(ru, "unit", None)
        name = getattr(unit, "name", "?") or "?"
        parts.append(f"{int(ru.count)}×{name}")
    return ", ".join(parts)


def roster_info(roster) -> RosterInfo:
    """Buduje `RosterInfo` z obiektu ORM `Roster` (czyta relacje — sesja musi być otwarta)."""
    army = getattr(getattr(roster, "army", None), "name", "?") or "?"
    return RosterInfo(
        id=int(roster.id),
        name=getattr(roster, "name", "?") or "?",
        army=army,
        points=round(roster_points(roster), 2),
        composition=_composition_summary(roster),
    )


def list_rosters(session) -> list[RosterInfo]:
    """Wszystkie rozpiski w bazie jako `RosterInfo` (read-only), posortowane po id."""
    from app import models

    rosters = session.query(models.Roster).order_by(models.Roster.id).all()
    return [roster_info(r) for r in rosters]


# ---------------------------------------------------------------------------
# Symulacja
# ---------------------------------------------------------------------------


def _player_factory(bot: str, base_seed: int):
    """Fabryka graczy dla `simulate`: gra `i` → 2 gracze tego samego bota z
    rozłącznymi seedami (p1 przesunięty o `PLAYER_SEED_OFFSET`, jak D2/exploit_hunt).

    Ten SAM bot po obu stronach — porównujemy ROZPISKI, nie boty (czynnik bot
    znosi się, różnica wyniku = różnica rozpisek). `random` różnicuje seedami;
    `priority`/`greedy` deterministyczne (seed ignorowany, ale plansza symetryczna
    + naprzemienna inicjatywa usuwają bias).
    """

    def factory(i: int):
        return [
            bsim.make_player(bot, base_seed + i),
            bsim.make_player(bot, base_seed + i + bsim.PLAYER_SEED_OFFSET),
        ]

    return factory


def simulate_engagement(
    session,
    roster_id_a: int,
    roster_id_b: int,
    *,
    bot: str = "priority",
    n: int = 10,
    seed: int = 0,
    map_name: str = DEFAULT_MAP,
) -> tuple[SimulationSummary, RosterInfo, RosterInfo]:
    """Rozgrywa N gier rozpiska A (owner 0) vs B (owner 1); zwraca (summary, info_a, info_b).

    Deleguje do `LocalClient.simulate_roster_ids` (most ORM→engine + agregacja pkt 5.f).
    Mapa (teren + cele) z `balance_simulate.build_map`; rozstawienie w strefach
    (`DEPLOY_ZONES`, pkt 13.a) przez boty (D5). Inicjatywa naprzemienna (domyślnie
    w `simulate`) usuwa bias pierwszego gracza.

    Raises `RosterNotFoundError` gdy któraś rozpiska nie istnieje.
    """
    from app import models

    roster_a = session.get(models.Roster, roster_id_a)
    if roster_a is None:
        raise RosterNotFoundError(f"Roster id={roster_id_a} nie istnieje")
    roster_b = session.get(models.Roster, roster_id_b)
    if roster_b is None:
        raise RosterNotFoundError(f"Roster id={roster_id_b} nie istnieje")
    info_a = roster_info(roster_a)
    info_b = roster_info(roster_b)

    map_fixture = bsim.build_map(map_name, seed)
    client = LocalClient(session=session, user_id=None)  # tryb narzędzia balansu
    summary = client.simulate_roster_ids(
        roster_id_a,
        roster_id_b,
        _player_factory(bot, seed),
        n=n,
        seed=seed,
        terrain=map_fixture.terrain,
        objectives=map_fixture.objectives,
        deployment_zones=DEPLOY_ZONES,
    )
    return summary, info_a, info_b


# ---------------------------------------------------------------------------
# Output (czyste funkcje — testowalne bez DB)
# ---------------------------------------------------------------------------


def format_roster_list(infos: Sequence[RosterInfo]) -> str:
    if not infos:
        return "Brak rozpisek w bazie."
    lines = [
        "Rozpiski w bazie (id → nazwa / armia / koszt):",
        "=" * 72,
        f"{'id':>4}  {'pkt':>7}  {'nazwa':<24}  armia / skład",
        "-" * 72,
    ]
    for info in infos:
        lines.append(
            f"{info.id:>4}  {info.points:>7.0f}  {info.name[:24]:<24}  "
            f"{info.army} — {info.composition}"
        )
    return "\n".join(lines)


def _bar(rate: float, width: int = 24) -> str:
    filled = int(round(rate * width))
    return "█" * filled + "░" * (width - filled)


def _games_label(n: int) -> str:
    if n == 1:
        return "1 gra"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} gry"
    return f"{n} gier"


def format_engagement_report(
    summary: SimulationSummary,
    info_a: RosterInfo,
    info_b: RosterInfo,
    *,
    bot: str,
    map_name: str,
) -> str:
    """Raport tekstowy head-to-head (win-rate A/B/remis + śr. rundy + koszt)."""
    lines = [
        f"Symulacja: rozpiska A vs B — {_games_label(summary.n_games)} "
        f"(bot={bot}, mapa={map_name}, naprzemienna inicjatywa)",
        "=" * 72,
        f"  A [{info_a.id}] {info_a.name} ({info_a.army}) — {info_a.points:.0f} pkt: {info_a.composition}",
        f"  B [{info_b.id}] {info_b.name} ({info_b.army}) — {info_b.points:.0f} pkt: {info_b.composition}",
        "-" * 72,
        f"  A wygrane : {summary.wins_p0:>4}  {summary.win_rate_p0:>6.1%}  {_bar(summary.win_rate_p0)}",
        f"  B wygrane : {summary.wins_p1:>4}  {summary.win_rate_p1:>6.1%}  {_bar(summary.win_rate_p1)}",
        f"  remisy    : {summary.draws:>4}  {summary.draw_rate:>6.1%}  {_bar(summary.draw_rate)}",
        "-" * 72,
        f"  śr. rund/grę: {summary.avg_rounds:.2f}",
    ]
    # Interpretacja koszt↔wynik (sygnał jak w exploit_hunt — tańsza wygrywa = niedoszacowanie).
    if info_a.points > 0 and info_b.points > 0:
        mean = (info_a.points + info_b.points) / 2.0
        pct = abs(info_a.points - info_b.points) / mean * 100.0 if mean > 0 else 0.0
        lines += [
            "-" * 72,
            f"  Δkoszt: {abs(info_a.points - info_b.points):.0f} pkt ({pct:.1f}% od średniej)",
        ]
        if info_a.points == info_b.points:
            lines.append("  Koszt równy — interpretuj wynik bez korekty kosztowej.")
        else:
            cheaper, cheaper_wr = (
                ("A", summary.win_rate_p0)
                if info_a.points < info_b.points
                else ("B", summary.win_rate_p1)
            )
            lines.append(f"  Tańsza = {cheaper} (win {cheaper_wr:.0%})")
            if pct >= 5.0 and cheaper_wr > 0.5:
                lines.append(
                    "  Sygnał: TAŃSZA rozpiska wygrywa >50% mimo niższego kosztu "
                    "(możliwe niedoszacowanie składu — patrz exploit_hunt)."
                )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C3 simulate_engagement — head-to-head dwóch rozpisek z DB.",
    )
    parser.add_argument("roster_a", type=int, nargs="?", help="id rozpiski A (owner 0).")
    parser.add_argument("roster_b", type=int, nargs="?", help="id rozpiski B (owner 1).")
    parser.add_argument("-n", "--games", type=int, default=10, help="liczba gier (≥1).")
    parser.add_argument(
        "--bot", type=str, default="priority",
        help="bot po OBU stronach (porównanie rozpisek, nie botów; domyślnie 'priority').",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed determinizmu.")
    parser.add_argument("--map", type=str, default=DEFAULT_MAP, help="mapa (teren+cele) z balance_simulate.")
    parser.add_argument("--list", action="store_true", help="wypisz rozpiski w bazie i zakończ.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    from app.db import SessionLocal

    with SessionLocal() as session:
        if args.list:
            print(format_roster_list(list_rosters(session)))
            return 0

        if args.roster_a is None or args.roster_b is None:
            print(
                "Podaj dwa id rozpisek (np. `simulate_engagement.py 1 2`) lub `--list`.",
                file=sys.stderr,
            )
            return 2
        if args.games < 1:
            print(f"--games musi być ≥1, jest {args.games}.", file=sys.stderr)
            return 2

        try:
            summary, info_a, info_b = simulate_engagement(
                session,
                args.roster_a,
                args.roster_b,
                bot=args.bot,
                n=args.games,
                seed=args.seed,
                map_name=args.map,
            )
        except RosterNotFoundError as exc:
            print(f"Nie znaleziono rozpiski: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    print(format_engagement_report(summary, info_a, info_b, bot=args.bot, map_name=args.map))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
