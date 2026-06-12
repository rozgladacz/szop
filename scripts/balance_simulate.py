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
    PriorityPlayer,
    PriorityV2Player,
    PriorityV3Player,
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

PLAYER_KINDS = ("random", "greedy", "priority", "priority2", "priority3")

#: Offset seeda decyzji P1 względem P0. Bez niego oba `RandomPlayer` dostają
#: ten sam seed → na symetrycznej fixturze produkują **lustrzane** strumienie
#: decyzji, co daje systematyczny bias pozycyjny zamiast ~50/50 (finding F2,
#: REVIEW_2026-06-11). Duża liczba pierwsza: rozłączna od seeda kości kolejnych
#: gier (`base_seed + i`, i << OFFSET) i względnie pierwsza, więc strumienie
#: P0/P1 się nie pokrywają. Seed bazowy nadal w pełni determinuje przebieg.
PLAYER_SEED_OFFSET = 1_000_003


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
    """Buduje gracza z nazwy. `greedy`/`priority` ignorują seed (deterministyczne)."""
    kind = kind.lower()
    if kind == "random":
        return RandomPlayer(seed=seed)
    if kind == "greedy":
        return GreedyPlayer()
    if kind == "priority":
        return PriorityPlayer()
    if kind == "priority2":
        return PriorityV2Player()
    if kind == "priority3":
        return PriorityV3Player()
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
    budowani świeżo per grę z **rozłącznych** seedów — P0 = `base_seed + i`,
    P1 = `base_seed + i + PLAYER_SEED_OFFSET`. Rozłączność usuwa bias mirror-
    matchu: dwa `RandomPlayer` z tym samym seedem na symetrycznej fixturze
    grałyby lustrzanie (finding F2). `GreedyPlayer`/`PriorityPlayer` seed
    ignorują (deterministyczne) — offset jest dla nich nieszkodliwy. Zwycięzca
    z `MatchResult.winner ∈ {0,1,None}` (pkt 5.f).
    """
    if n <= 0:
        raise ValueError(f"n musi być > 0, jest {n}")
    wins = [0, 0]
    draws = 0
    total_rounds = 0
    for i in range(n):
        seed = base_seed + i
        players = [
            make_player(player_kinds[0], seed),
            make_player(player_kinds[1], seed + PLAYER_SEED_OFFSET),
        ]
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
# Mapy testowe (generatory) — teren + cele + strefy + armia, symetryczne
# ---------------------------------------------------------------------------

import math  # noqa: E402
import random as _random  # noqa: E402

BOARD_W, BOARD_H = 72.0, 48.0
_CENTER = (BOARD_W / 2, BOARD_H / 2)  # (36, 24)

#: 4 profile uzbrojenia (jak unit_profiles): (slug, ranged_range, ranged_atk, melee_atk).
_PROFILES = [
    ("rifle24", 24, 1, 1),    # Strzelec-24
    ("carbine18", 18, 1, 1),  # Strzelec-18
    ("pistol12", 12, 1, 2),   # Wojownik-mix
    ("greatblade", 0, 0, 3),  # Wojownik (czysty wręcz)
]

#: Cechy terenu (ASCII, jak w silniku: los/combat/phases).
F_NIEDOSTEPNY, F_BLOKUJACY = "Niedostepny", "Blokujacy"
F_OBRONNY, F_TRUDNY, F_NIEBEZPIECZNY = "Obronny", "Trudny", "Niebezpieczny"


def _pt_reflect(x: float, y: float) -> tuple[float, float]:
    """Symetria środkowa względem (36,24)."""
    return (BOARD_W - x, BOARD_H - y)


def _mirror(x: float, y: float) -> tuple[float, float]:
    """Lustro względem linii środkowej y=24."""
    return (x, BOARD_H - y)


def _unit(uid: int, x: float, y: float, profile) -> dict:
    slug, rng, ratk, matk = profile
    weapons = []
    if rng > 0:
        weapons.append({"slug": slug, "name": slug, "range_inches": rng, "attacks": ratk})
    weapons.append({"slug": f"{slug}_melee", "name": "melee", "range_inches": 0, "attacks": matk})
    return {"id": uid, "position": (float(x), float(y)), "models": 5, "toughness": 3,
            "quality": 4, "defense": 5, "passives": [], "weapons": weapons}


def _armies(reflect) -> tuple[list, list]:
    """4 profile/stronę przy granicach stref (y=12 / y=36), P1 = symetria P0."""
    xs = [18.0, 30.0, 42.0, 54.0]
    p0 = [_unit(i + 1, xs[i], 12.0, _PROFILES[i]) for i in range(4)]
    p1 = []
    for i in range(4):
        rx, ry = reflect(xs[i], 12.0)
        p1.append(_unit(i + 5, rx, ry, _PROFILES[i]))
    return (
        [{"owner_player": 0, "units": p0}, {"owner_player": 1, "units": p1}]
    )


def _circles(pos_features: dict, radius: float) -> list:
    return [TerrainCircle(center=Position(x, y), radius_inches=radius, features=tuple(sorted(f)))
            for (x, y), f in pos_features.items()]


def _lines(segments, features) -> list:
    return [TerrainLine(start=Position(*a), end=Position(*b), features=tuple(features))
            for a, b in segments]


def build_standard_a() -> BattleFixture:
    """Standard_A — deterministyczna, środkowo-symetryczna (reflekcja od (36,24))."""
    half_circ = {
        (6, 18): {F_OBRONNY}, (24, 9): {F_OBRONNY},
        (30, 36): {F_OBRONNY, F_NIEBEZPIECZNY}, (36, 24): {F_OBRONNY, F_TRUDNY},
        (12, 30): {F_TRUDNY},
    }
    half_lines = [((3, 39), (6, 39)), ((9, 12), (12, 12)), ((12, 33), (15, 33)),
                  ((15, 24), (18, 24)), ((18, 42), (21, 42)), ((12, 6), (12, 9)),
                  ((24, 27), (27, 30)), ((30, 21), (33, 18)), ((33, 12), (36, 12))]
    half_objs = [(12, 30), (24, 9), (36, 24)]

    # Reflekcja punktowa (koła: merge cech same-pos; pomiń self-map na środku).
    circ: dict = {}
    for pos, feats in half_circ.items():
        circ.setdefault(pos, set()).update(feats)
        r = _pt_reflect(*pos)
        if r != pos:
            circ.setdefault(r, set()).update(feats)
    lines = []
    for a, b in half_lines:
        lines.append((a, b))
        lines.append((_pt_reflect(*a), _pt_reflect(*b)))
    objs, seen = [], set()
    for o in half_objs:
        for p in (o, _pt_reflect(*o)):
            if p not in seen:
                seen.add(p)
                objs.append(p)

    terrain = tuple(_circles(circ, 3.0) + _lines(lines, (F_NIEDOSTEPNY, F_BLOKUJACY)))
    objectives = tuple(Objective(id=i + 1, position=Position(float(x), float(y)))
                       for i, (x, y) in enumerate(objs))
    return BattleFixture("Standard_A", tuple(_armies(_pt_reflect)), terrain, objectives)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _terrain_from(circ_list, line_list, line_feats) -> tuple:
    """circ_list: [(x,y,r,features_set)]; line_list: [((ax,ay),(bx,by))]."""
    t = [TerrainCircle(center=Position(float(x), float(y)), radius_inches=float(r),
                       features=tuple(sorted(f))) for x, y, r, f in circ_list]
    t += [TerrainLine(start=Position(*a), end=Position(*b), features=tuple(line_feats))
          for a, b in line_list]
    return tuple(t)


def _gen_objectives(rng, reflect, *, center_on_line: bool) -> list:
    """5 celów symetrycznych (pkt 5.a) wg pkt 5.c (≥12″ od siebie, ≥6″ od krawędzi)
    + pkt 5.b (≥1/strefa y∈[6,12]/[36,42] + lewo/prawo). `reflect` = _mirror lub
    _pt_reflect. `center_on_line`: środkowy losowo na linii środka (Lustrzana) vs
    dokładnie (36,24) (Symetryczna)."""
    for _ in range(3000):
        center = (rng.uniform(6, 66), 24.0) if center_on_line else _CENTER
        pair_src = []
        ok = True
        for _slot in range(2):
            placed = False
            for _t in range(300):
                cand = (rng.uniform(6, 66), rng.uniform(6, 21))
                pts = [center] + pair_src + [reflect(*p) for p in pair_src]
                if (all(_dist(cand, p) >= 12 for p in pts)
                        and _dist(cand, reflect(*cand)) >= 12):
                    pair_src.append(cand)
                    placed = True
                    break
            if not placed:
                ok = False
                break
        if not ok:
            continue
        objs = [center] + pair_src + [reflect(*p) for p in pair_src]
        # pkt 5.b: ≥1 cel w strefie rozstawienia (y∈[6,12]) + lewo/prawo (x<36, x>36).
        if not any(6 <= y <= 12 for _, y in pair_src):
            continue
        xs = [x for x, _ in objs]
        if not (any(x < 36 for x in xs) and any(x > 36 for x in xs)):
            continue
        return objs
    raise RuntimeError("nie udało się rozmieścić celów wg pkt 5.b/5.c")


def _gen_half_lines(rng, objs, n: int, y_max: float) -> list:
    """`n` odcinków w dolnej połowie (dł. 2–5), midpoint ≥6″ od siebie i ≥3″ od
    celów (proxy odległości przez środki — MVP)."""
    out, mids = [], []
    for _ in range(n):
        for _t in range(400):
            length = rng.uniform(2, 5)
            ang = rng.uniform(0, math.pi)
            mx = rng.uniform(6, BOARD_W - 6)
            my = rng.uniform(4, y_max - 4)
            if any(_dist((mx, my), m) < 6 for m in mids):
                continue
            if any(_dist((mx, my), o) < 3 for o in objs):
                continue
            hx, hy = math.cos(ang) * length / 2, math.sin(ang) * length / 2
            out.append(((mx - hx, my - hy), (mx + hx, my + hy)))
            mids.append((mx, my))
            break
    return out


def _gen_half_circles(rng, counts, y_max: float) -> list:
    """Koła ⌀3–6 (r 1.5–3) w dolnej połowie; mogą nachodzić (brak constraintu).
    `counts`: [(feature, n)]."""
    out = []
    for feat, n in counts:
        for _ in range(n):
            r = rng.uniform(1.5, 3.0)
            x = rng.uniform(r, BOARD_W - r)
            y = rng.uniform(r, y_max)
            out.append((x, y, r, {feat}))
    return out


def _armies_angled(rng) -> list:
    """Strefy rozstawienia: 2 równoległe linie 12″ od środka pod losowym kątem.
    Oddziały na liniach; P1 = symetria środkowa P0 (pozostaje na planszy)."""
    theta = rng.uniform(0, math.pi)
    nx, ny = math.cos(theta), math.sin(theta)      # normalna (kierunek od środka)
    dx, dy = -ny, nx                                # wzdłuż linii rozstawienia
    p0, p1 = [], []
    for i, off in enumerate((-15.0, -5.0, 5.0, 15.0)):
        bx = _CENTER[0] - 12 * nx + off * dx
        by = _CENTER[1] - 12 * ny + off * dy
        bx = min(max(bx, 3.0), BOARD_W - 3.0)
        by = min(max(by, 3.0), BOARD_H - 3.0)
        p0.append(_unit(i + 1, bx, by, _PROFILES[i]))
        rx, ry = _pt_reflect(bx, by)
        p1.append(_unit(i + 5, rx, ry, _PROFILES[i]))
    return [{"owner_player": 0, "units": p0}, {"owner_player": 1, "units": p1}]


def build_lustrzana_a(seed: int = 0) -> BattleFixture:
    """Lustrzana_A — losowa, symetria lustrzana względem y=24 (pkt 5.b/5.c)."""
    rng = _random.Random(seed)
    objs = _gen_objectives(rng, _mirror, center_on_line=True)
    half_lines = _gen_half_lines(rng, objs, n=9, y_max=BOARD_H / 2)
    lines = [seg for a, b in half_lines for seg in ((a, b), (_mirror(*a), _mirror(*b)))]
    half_circ = _gen_half_circles(rng, [(F_OBRONNY, 4), (F_TRUDNY, 2), (F_NIEBEZPIECZNY, 1)],
                                  y_max=BOARD_H / 2)
    circ = []
    for x, y, r, f in half_circ:
        circ.append((x, y, r, f))
        mx, my = _mirror(x, y)
        circ.append((mx, my, r, f))
    terrain = _terrain_from(circ, lines, (F_NIEDOSTEPNY, F_BLOKUJACY))
    objectives = tuple(Objective(id=i + 1, position=Position(float(x), float(y)))
                       for i, (x, y) in enumerate(objs))
    return BattleFixture(f"Lustrzana_A(seed={seed})", tuple(_armies(_mirror)), terrain, objectives)


def build_symetryczna_a(seed: int = 0) -> BattleFixture:
    """Symetryczna_A — losowa, symetria środkowa (1 cel na środku), strefy pod
    losowym kątem (2 linie 12″ od środka)."""
    rng = _random.Random(seed)
    objs = _gen_objectives(rng, _pt_reflect, center_on_line=False)
    half_lines = _gen_half_lines(rng, objs, n=9, y_max=BOARD_H / 2)
    lines = [seg for a, b in half_lines for seg in ((a, b), (_pt_reflect(*a), _pt_reflect(*b)))]
    half_circ = _gen_half_circles(rng, [(F_OBRONNY, 4), (F_TRUDNY, 2), (F_NIEBEZPIECZNY, 1)],
                                  y_max=BOARD_H / 2)
    circ = []
    for x, y, r, f in half_circ:
        circ.append((x, y, r, f))
        rx, ry = _pt_reflect(x, y)
        circ.append((rx, ry, r, f))
    terrain = _terrain_from(circ, lines, (F_NIEDOSTEPNY, F_BLOKUJACY))
    objectives = tuple(Objective(id=i + 1, position=Position(float(x), float(y)))
                       for i, (x, y) in enumerate(objs))
    return BattleFixture(f"Symetryczna_A(seed={seed})", tuple(_armies_angled(rng)), terrain, objectives)


#: Rejestr generatorów map. Standard_A ignoruje seed; pozostałe go używają.
MAP_BUILDERS = {
    "standard_a": lambda seed: build_standard_a(),
    "lustrzana_a": build_lustrzana_a,
    "symetryczna_a": build_symetryczna_a,
}


def build_map(name: str, seed: int = 0) -> BattleFixture:
    key = name.lower()
    if key not in MAP_BUILDERS:
        raise ValueError(f"Nieznana mapa {name!r}; dostępne: {', '.join(sorted(MAP_BUILDERS))}")
    return MAP_BUILDERS[key](seed)


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
        "--map",
        type=str,
        default=None,
        help=f"Generowana mapa zamiast --fixture: {', '.join(sorted(MAP_BUILDERS))}.",
    )
    parser.add_argument(
        "--map-seed",
        type=int,
        default=0,
        help="Seed generatora mapy (Lustrzana_A/Symetryczna_A; domyślnie 0).",
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
    fixture = build_map(args.map, args.map_seed) if args.map else load_battle_fixture(args.fixture)
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
