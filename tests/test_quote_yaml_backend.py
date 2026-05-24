"""A2.5 — end-to-end test YAML backendu (`OPR_RULES_BACKEND=yaml`).

Asercja parytetu z proceduralnym SSOT na reprezentatywnych jednostkach:
piechota, transport, jednostka z passive aurą, jednostka z bronią-traitami,
loadout per_model i total, count=0 (edge case), unit=None (legacy zero-shape).

Strategia:
1. Buduj `SimpleNamespace`-jednostki (jak w `test_roster_unit_quote.py`) —
   `calculate_roster_unit_quote` przyjmuje duck-typed `unit`.
2. Każdy scenariusz odpalany pod trzema backendami: `procedural`, `yaml`,
   `both_assert`. `both_assert` jest najmocniejszą asercją (porównuje shape +
   numerykę ≤ 1e-3 wewnętrznie, RulesetParityError ⇒ test fail).
3. Sprawdzaj `shape` (klucze top-level + `components` + `item_costs`) plus
   identyczne `warrior_total/shooter_total/components` z tolerancją 1e-2
   (zaokrąglenia do 2 miejsc).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config
from app.services.costs import quote as quote_module
from app.services.costs.errors import RulesetParityError

QUOTE_TOP_KEYS = {
    "cost_engine_version",
    "selected_role",
    "warrior_total",
    "shooter_total",
    "selected_total",
    "components",
    "item_costs",
    "loadout",
}
COMPONENT_KEYS = {"base", "weapon", "active", "aura", "passive"}
ITEM_COST_KEYS = {"weapons", "active", "aura", "passive_deltas"}


# ---------------------------------------------------------------------------
# Helpers — minimalne fixtures jednostek (mirror test_roster_unit_quote).
# ---------------------------------------------------------------------------


def _weapon(weapon_id: int, *, range_: str = '18"', attacks: float = 1.0, ap: int = 1, tags: str = ""):
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


def _simple_unit(
    *,
    quality: int = 4,
    defense: int = 4,
    toughness: int = 1,
    flags: str = "Wojownik",
    weapon_id: int = 101,
    weapon_kwargs: dict | None = None,
    abilities: list | None = None,
):
    weapon_kwargs = weapon_kwargs or {}
    base_weapon = _weapon(weapon_id, **weapon_kwargs)
    return SimpleNamespace(
        quality=quality,
        defense=defense,
        toughness=toughness,
        flags=flags,
        army=None,
        abilities=abilities or [],
        weapon_links=[
            SimpleNamespace(
                weapon_id=weapon_id,
                weapon=base_weapon,
                is_default=True,
                default_count=1,
            )
        ],
        default_weapon=base_weapon,
        default_weapon_id=weapon_id,
    )


# ---------------------------------------------------------------------------
# 1. Shape parity — yaml musi zwracać dokładnie te same klucze co procedural.
# ---------------------------------------------------------------------------


def _assert_quote_shape(quote: dict) -> None:
    assert set(quote) == QUOTE_TOP_KEYS, (
        f"Unexpected top-level keys: {set(quote) ^ QUOTE_TOP_KEYS}"
    )
    assert set(quote["components"]) == COMPONENT_KEYS
    assert set(quote["item_costs"]) == ITEM_COST_KEYS
    assert quote["selected_role"] in {"wojownik", "strzelec", None}


@pytest.mark.parametrize("backend", ["procedural", "yaml", "both_assert"])
def test_quote_shape_consistent_across_backends_none_unit(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    result = quote_module.calculate_roster_unit_quote(None)
    _assert_quote_shape(result)
    assert result["selected_role"] is None
    assert result["selected_total"] == 0.0


@pytest.mark.parametrize("backend", ["procedural", "yaml", "both_assert"])
def test_quote_shape_consistent_across_backends_simple_unit(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    result = quote_module.calculate_roster_unit_quote(_simple_unit(), {}, count=3)
    _assert_quote_shape(result)
    assert result["selected_role"] in {"wojownik", "strzelec"}


# ---------------------------------------------------------------------------
# 2. Numeric parity — yaml ≡ procedural ≤ 1e-2 (po round-2).
# ---------------------------------------------------------------------------


def _quote_with_backend(monkeypatch: pytest.MonkeyPatch, backend: str, *args, **kwargs):
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    return quote_module.calculate_roster_unit_quote(*args, **kwargs)


def _assert_quotes_equal(proc: dict, yaml: dict, *, tol: float = 1e-2) -> None:
    """Porównanie dwóch quote dictów z tolerancją na zaokrąglenia."""
    assert proc["selected_role"] == yaml["selected_role"]
    assert proc["warrior_total"] == pytest.approx(yaml["warrior_total"], abs=tol)
    assert proc["shooter_total"] == pytest.approx(yaml["shooter_total"], abs=tol)
    assert proc["selected_total"] == pytest.approx(yaml["selected_total"], abs=tol)
    for key in COMPONENT_KEYS:
        assert proc["components"][key] == pytest.approx(
            yaml["components"][key], abs=tol
        ), f"components.{key} mismatch: proc={proc['components'][key]}, yaml={yaml['components'][key]}"


_SCENARIOS = {
    "infantry_basic": dict(unit_kwargs=dict(flags="Wojownik"), loadout={}, count=3),
    "infantry_strzelec": dict(
        unit_kwargs=dict(flags="Strzelec", weapon_kwargs={"range_": '24"'}),
        loadout={},
        count=5,
    ),
    "infantry_count_one": dict(unit_kwargs=dict(flags="Wojownik"), loadout={}, count=1),
    "infantry_with_passive": dict(
        unit_kwargs=dict(
            flags="Nieustraszony,Zwiadowca",
            toughness=2,
        ),
        loadout={},
        count=4,
    ),
    "infantry_aura": dict(
        unit_kwargs=dict(
            flags="Aura(6): Bastion",
            toughness=3,
        ),
        loadout={},
        count=1,
    ),
    "transport_units": dict(
        unit_kwargs=dict(
            flags="Transport(6),Latajacy",
            toughness=8,
            quality=4,
            defense=3,
        ),
        loadout={},
        count=1,
    ),
    "open_transport": dict(
        unit_kwargs=dict(
            flags="Otwarty Transport(8),Szybki",
            toughness=6,
        ),
        loadout={},
        count=1,
    ),
    "weapon_with_traits": dict(
        unit_kwargs=dict(
            flags="Wojownik",
            weapon_kwargs={
                "range_": '24"',
                "tags": "Rozprysk(3), Przebijajaca",
                "ap": 2,
            },
        ),
        loadout={},
        count=3,
    ),
    "loadout_per_model_weapons": dict(
        unit_kwargs=dict(flags="Wojownik"),
        loadout={"mode": "per_model", "weapons": {"101": 1}},
        count=2,
    ),
    "masywny_unit": dict(
        unit_kwargs=dict(flags="Wojownik,Masywny", toughness=6),
        loadout={},
        count=2,
    ),
}


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_yaml_matches_procedural_numerically(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    spec = _SCENARIOS[name]
    unit_proc = _simple_unit(**spec["unit_kwargs"])
    unit_yaml = _simple_unit(**spec["unit_kwargs"])

    proc = _quote_with_backend(
        monkeypatch, "procedural", unit_proc, spec["loadout"], count=spec["count"]
    )
    yaml = _quote_with_backend(
        monkeypatch, "yaml", unit_yaml, spec["loadout"], count=spec["count"]
    )
    _assert_quotes_equal(proc, yaml)


# ---------------------------------------------------------------------------
# 3. both_assert — wewnętrzna asercja parytetu (RulesetParityError ⇒ fail).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_both_assert_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    spec = _SCENARIOS[name]
    unit = _simple_unit(**spec["unit_kwargs"])
    # `_both_assert_quote` zwraca proceduralny wynik po passe parity-check.
    # Brak RulesetParityError ⇒ yaml ≡ procedural ≤ 1e-3 na pełnym shape.
    try:
        result = _quote_with_backend(
            monkeypatch, "both_assert", unit, spec["loadout"], count=spec["count"]
        )
    except RulesetParityError as e:  # pragma: no cover - diagnostic only
        pytest.fail(
            f"RulesetParityError in scenario {name!r}: path={e.path}, "
            f"delta={e.delta}, proc={e.proc_value}, yaml={e.yaml_value}"
        )
    _assert_quote_shape(result)


# ---------------------------------------------------------------------------
# 4. Edge cases — count=0, mode=total, include_item_costs=False.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["procedural", "yaml", "both_assert"])
def test_count_zero_returns_zero_quote(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    result = quote_module.calculate_roster_unit_quote(_simple_unit(), {}, count=0)
    _assert_quote_shape(result)
    assert result["selected_role"] is None
    assert result["selected_total"] == 0.0
    assert result["warrior_total"] == 0.0
    assert result["shooter_total"] == 0.0


@pytest.mark.parametrize("backend", ["yaml", "both_assert"])
def test_include_item_costs_false_skips_passive_deltas(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    """Optymalizacja: gdy `include_item_costs=False` pomijamy O(N²) pętlę.

    YAML backend musi szanować ten flag tak samo jak procedural — kontrakt
    z `docs/PERFORMANCE.md`.
    """
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    unit = _simple_unit(flags="Nieustraszony", toughness=2)
    result = quote_module.calculate_roster_unit_quote(
        unit, {}, count=3, include_item_costs=False
    )
    _assert_quote_shape(result)
    # passive_deltas powinno być puste — fast path nie liczy delt.
    assert result["item_costs"]["passive_deltas"] == {}


def test_yaml_quote_returns_cost_engine_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check — wszystkie backendy nazywają się tą samą wersją silnika
    (procedural pozostaje SSOT; yaml jest jego repliką, nie nowym engine).
    """
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_YAML)
    result = quote_module.calculate_roster_unit_quote(_simple_unit(), {}, count=1)
    from app.services.costs import COST_ENGINE_VERSION

    assert result["cost_engine_version"] == COST_ENGINE_VERSION


# ---------------------------------------------------------------------------
# 5. Loadout normalization — yaml musi normalizować tak samo jak procedural.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["procedural", "yaml"])
def test_loadout_normalized_consistently(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    raw_loadout = {
        "mode": "TOTAL",  # uppercase → 'total'
        "weapons": {"101": 2, "999": 5, "bad": 3},  # 999 + 'bad' dropped
        "active": {},
        "aura": {},
        "passive": {"wojownik": 1, "unknown_passive": 1},
    }
    result = quote_module.calculate_roster_unit_quote(
        _simple_unit(), raw_loadout, count=2
    )
    normalized = result["loadout"]
    assert normalized["mode"] == "total"
    assert normalized["weapons"] == {"101": 2}
    assert normalized["passive"] == {"wojownik": 1}


# ---------------------------------------------------------------------------
# 6. Item costs — `item_costs.weapons` keys i wartości muszą być spójne
# między backendami.
# ---------------------------------------------------------------------------


def test_item_costs_keys_match_between_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """`item_costs.weapons` jest słownikiem `{weapon_id_str: cost}`. Yaml musi
    raportować te same klucze i wartości co procedural (z tolerancją round-2).
    """
    unit_proc = _simple_unit(
        flags="Wojownik",
        weapon_kwargs={"range_": '24"', "tags": "Przebijajaca", "ap": 2},
    )
    unit_yaml = _simple_unit(
        flags="Wojownik",
        weapon_kwargs={"range_": '24"', "tags": "Przebijajaca", "ap": 2},
    )

    proc = _quote_with_backend(monkeypatch, "procedural", unit_proc, {}, count=2)
    yaml = _quote_with_backend(monkeypatch, "yaml", unit_yaml, {}, count=2)

    assert set(proc["item_costs"]["weapons"]) == set(yaml["item_costs"]["weapons"])
    for weapon_id, proc_cost in proc["item_costs"]["weapons"].items():
        yaml_cost = yaml["item_costs"]["weapons"][weapon_id]
        assert proc_cost == pytest.approx(yaml_cost, abs=1e-2)
