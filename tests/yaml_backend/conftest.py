"""Conftest dla `tests/yaml/` — wymusza `OPR_RULES_BACKEND=yaml` dla każdego testu.

Strumień A, Faza A3.2. Te testy weryfikują że **YAML backend działa jako
samodzielny silnik** (nie tylko parity asercja przez `both_assert`).

Każdy test poniżej wywołuje `calculate_roster_unit_quote` pod yaml backendem
i sprawdza że wynik:
1. Ma shape zgodny z kontraktem (`cost_engine_version`, role totals, components,
   item_costs).
2. Jest **numerycznie identyczny** z proceduralnym (zaokrąglenia ≤ 1e-2) —
   referencja przeliczana przed switchem backendu w fixture `make_quote`.
3. Nie podnosi wyjątku przy żadnym z trybów loadout (per_model/total).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config
from app.services.costs import quote as quote_module


@pytest.fixture(autouse=True)
def _yaml_backend(monkeypatch: pytest.MonkeyPatch):
    """Wymusza `OPR_RULES_BACKEND=yaml` dla wszystkich testów w tym pakiecie."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_YAML)


@pytest.fixture
def make_quote(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[dict, dict]]:
    """Returns helper `make_quote(unit, loadout, count) → (proc, yaml)`.

    Wewnątrz: switch na procedural, oblicz, switch z powrotem na yaml, oblicz.
    Pozwala każdemu testowi mieć łatwy dostęp do referencji procedural bez
    duplikowania monkeypatch.
    """

    def _impl(unit, loadout=None, count: int = 1) -> tuple[dict, dict]:
        loadout = loadout if loadout is not None else {}
        monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_PROCEDURAL)
        proc = quote_module.calculate_roster_unit_quote(unit, loadout, count=count)
        monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_YAML)
        yaml = quote_module.calculate_roster_unit_quote(unit, loadout, count=count)
        return proc, yaml

    return _impl


@pytest.fixture
def assert_quote_parity() -> Callable[[dict, dict], None]:
    """Helper porównujący dwa quote'y z tolerancją 1e-2 (zaokrąglenia round-2)."""

    def _impl(proc: dict, yaml: dict, *, tol: float = 1e-2) -> None:
        assert proc["selected_role"] == yaml["selected_role"]
        assert proc["warrior_total"] == pytest.approx(yaml["warrior_total"], abs=tol)
        assert proc["shooter_total"] == pytest.approx(yaml["shooter_total"], abs=tol)
        assert proc["selected_total"] == pytest.approx(yaml["selected_total"], abs=tol)
        for key in ("base", "weapon", "active", "aura", "passive"):
            assert proc["components"][key] == pytest.approx(
                yaml["components"][key], abs=tol
            ), f"components.{key}: proc={proc['components'][key]}, yaml={yaml['components'][key]}"

    return _impl


# ---------------------------------------------------------------------------
# Wspólne fabryki jednostek/broni (mirror test_ruleset_parity.py).
# ---------------------------------------------------------------------------


@pytest.fixture
def make_weapon() -> Callable[..., Any]:
    def _impl(
        weapon_id: int = 101,
        *,
        range_: str = '18"',
        attacks: float = 1.0,
        ap: int = 1,
        tags: str = "",
    ):
        return SimpleNamespace(
            id=weapon_id,
            range=range_,
            attacks=attacks,
            ap=ap,
            tags=tags,
            parent=None,
            effective_range=range_,
            effective_attacks=attacks,
            effective_ap=ap,
            effective_tags=tags,
            effective_cached_cost=None,
        )

    return _impl


@pytest.fixture
def make_unit(make_weapon) -> Callable[..., Any]:
    def _impl(
        *,
        quality: int = 4,
        defense: int = 4,
        toughness: int = 1,
        flags: str = "",
        weapon_kwargs: dict | None = None,
        abilities: list | None = None,
    ):
        base_weapon = make_weapon(**(weapon_kwargs or {}))
        return SimpleNamespace(
            quality=quality,
            defense=defense,
            toughness=toughness,
            flags=flags,
            army=None,
            abilities=abilities or [],
            weapon_links=[
                SimpleNamespace(
                    weapon_id=101,
                    weapon=base_weapon,
                    is_default=True,
                    default_count=1,
                )
            ],
            default_weapon=base_weapon,
            default_weapon_id=101,
        )

    return _impl
