"""Wspólna infrastruktura skryptów balansu (D2 `balance_report` + D4 `leaderboard`).

Czyste funkcje współdzielone przez round-robin (`balance_report`) i ranking
ogólny (`leaderboard`): loader `balance_simulate`, domyślne fixtury,
`resolve_fixtures` (fixtury YAML + mapy generowane), render-helper `_bar`,
parsery CLI (fixtury / mapy / gracze z ekspansją tagów `registry`) oraz zapis
raportu. Oba skrypty różnią się **tylko** pairingiem (`combinations` vs
`combinations_with_replacement`) i renderem markdown (ranking vs macierz
pairwise) — te zostają lokalne.

`scripts/` nie jest pakietem importowalnym — ten moduł jest ładowany przez
spec/exec (jak `_load_balance_simulate`), żeby uniknąć dual-module hazardu z
`balance_simulate` (gdyby `scripts` stało się pakietem, `import scripts.X`
dałby inny obiekt modułu niż spec-loaded `balance_simulate`, łamiąc tożsamość
dataclass `BalanceResult`).
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import os
import pathlib
import sys
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
    `cls.__module__` przez `sys.modules.get(...)`. Idempotentne (cache w sys.modules).
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

from app.services.agents import registry  # noqa: E402  (SSOT klasyfikacji botów)

#: Domyślne fixtury gdy `--fixtures` nie podane (wszystkie z tests/fixtures/battles/).
DEFAULT_FIXTURES: tuple[str, ...] = tuple(
    str(_repo_root / "tests" / "fixtures" / "battles" / f"{stem}.yaml")
    for stem in ("demo_skirmish", "objective_clash", "unit_profiles")
)

#: Domyślny zestaw botów = boty oznaczone `useful` (rejestr SSOT). Lista zmienia
#: się przez tagi w `app/services/agents/registry.py`, nie tutaj.
DEFAULT_PLAYERS: tuple[str, ...] = registry.USEFUL_KINDS

_BAR_WIDTH = 24


# ---------------------------------------------------------------------------
# Źródła bitew (fixtury YAML + mapy generowane)
# ---------------------------------------------------------------------------


def resolve_fixtures(config) -> list:
    """Buduje listę `BattleFixture` ze źródeł: fixtury YAML + mapy generowane.

    Duck-typed na `config.fixtures` / `config.maps` / `config.map_seed` (wspólne
    dla `ReportConfig` i `LeaderboardConfig`). Mapy reużywają `bsim.build_map`
    (SSOT generatorów, `MAP_BUILDERS`). Kolejność: fixtury → mapy.
    """
    fixtures = [bsim.load_battle_fixture(p) for p in config.fixtures]
    fixtures += [bsim.build_map(m, config.map_seed) for m in config.maps]
    return fixtures


def _fixture_names_in_order(results: Sequence) -> list[str]:
    """Unikalne nazwy fixtur zachowując kolejność wystąpienia."""
    seen: list[str] = []
    for r in results:
        if r.fixture_name not in seen:
            seen.append(r.fixture_name)
    return seen


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _bar(fraction: float, width: int = _BAR_WIDTH) -> str:
    """Tekstowy słupek `█`/`░` o długości `width` proporcjonalny do `fraction` (0..1)."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.date.today().isoformat()


def write_report(text: str, path: str | os.PathLike) -> None:
    """Zapisuje raport (tworzy katalogi nadrzędne jeśli trzeba)."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsery CLI
# ---------------------------------------------------------------------------


def _parse_fixtures(spec: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in spec.split(",") if p.strip())
    if not parts:
        raise argparse.ArgumentTypeError("--fixtures: oczekiwano ≥1 ścieżki")
    return parts


def _parse_map_list(spec: str) -> tuple[str, ...]:
    parts = [p.strip().lower() for p in spec.split(",") if p.strip()]
    for p in parts:
        if p not in bsim.MAP_BUILDERS:
            raise argparse.ArgumentTypeError(
                f"Nieznana mapa {p!r}; dostępne: {', '.join(sorted(bsim.MAP_BUILDERS))}"
            )
    # Dedup zachowując kolejność.
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
    if not out:
        raise argparse.ArgumentTypeError("--map: oczekiwano ≥1 nazwy mapy")
    return tuple(out)


def _parse_player_list(spec: str) -> tuple[str, ...]:
    """Lista botów. Tokeny: konkretny bot (`priority`), TAG (`useful`/`fast`/…) który
    rozwija się do botów z tym tagiem, albo `all` (wszystkie kanoniczne). Tagi pozwalają
    `--players useful` lub `--players useful,reference` — rozszerzalne (nowe tagi działają
    automatycznie, SSOT = `registry`). Wymaga ≥2 różnych botów do round-robin/rankingu."""
    tags = registry.all_tags()
    out: list[str] = []
    for raw in spec.split(","):
        p = raw.strip().lower()
        if not p:
            continue
        if p == "all":
            expanded: tuple[str, ...] = registry.ALL_KINDS
        elif p in tags:
            expanded = registry.bot_kinds(p)
        elif p in bsim.PLAYER_KINDS:
            expanded = (p,)
        else:
            raise argparse.ArgumentTypeError(
                f"Nieznany gracz/tag {p!r}; boty: {', '.join(bsim.PLAYER_KINDS)}; "
                f"tagi: {', '.join(sorted(tags))}, all"
            )
        for kind in expanded:  # dedup zachowując kolejność
            if kind not in out:
                out.append(kind)
    if len(out) < 2:
        raise argparse.ArgumentTypeError(
            "--players: oczekiwano ≥2 różnych typów do round-robin"
        )
    return tuple(out)
