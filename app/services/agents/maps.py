"""Generated battle maps shared by app-level agents, B4 API and scripts.

The generators used to live in `scripts/balance_simulate.py`. They are now in
`app` so routers and future UI code can use generated maps without importing a
script module. `balance_simulate.py` re-exports these names for backward
compatibility with existing scripts and tests.
"""

from __future__ import annotations

import math
import random as _random
from dataclasses import dataclass

from app.services.agents.deployment import DeploymentZone
from app.services.engine.state import Objective, Position, TerrainCircle, TerrainLine


@dataclass(frozen=True, slots=True)
class BattleFixture:
    """Para rosterów + teren + cele wczytane z YAML."""

    name: str
    rosters: tuple[dict, ...]
    terrain: tuple[TerrainCircle | TerrainLine, ...]
    objectives: tuple[Objective, ...]

# ---------------------------------------------------------------------------
# Mapy testowe (generatory) — teren + cele + strefy + armia, symetryczne
# ---------------------------------------------------------------------------

BOARD_W, BOARD_H = 72.0, 48.0
ZONE_DEPTH = 12.0
DEFAULT_DEPLOYMENT_ZONES = (
    DeploymentZone(0.0, 0.0, BOARD_W, ZONE_DEPTH),
    DeploymentZone(0.0, BOARD_H - ZONE_DEPTH, BOARD_W, BOARD_H),
)
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


__all__ = [
    "BattleFixture",
    "BOARD_W",
    "BOARD_H",
    "ZONE_DEPTH",
    "DEFAULT_DEPLOYMENT_ZONES",
    "MAP_BUILDERS",
    "build_map",
    "build_standard_a",
    "build_lustrzana_a",
    "build_symetryczna_a",
]
