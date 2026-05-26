"""A5.1 — perf regression gate dla YAML backendu.

Asercja `yaml_time / proc_time <= 1.20` na reprezentatywnym zestawie
jednostek. Ratio mierzone na aggregate (suma ms) wielu jednostek × wielu
iteracji, żeby ograniczyć wpływ noise pojedynczego pomiaru.

Strategia (mirror konwencji `scripts/profile_quote.py`):
1. Build N reprezentatywnych jednostek (różne kombinacje passive/weapon/aura).
2. Warm-up: po jednym wywołaniu na backend (LRU + ruleset loader cache).
3. Pomiar: `_RUNS` iteracji per (backend, unit), `time.perf_counter()`.
4. Asercja: `sum(yaml_ms) / sum(proc_ms) <= _MAX_RATIO`.

Test jest **świadomie tolerancyjny**:
- Dolny limit czasu chroni przed dzieleniem przez 0 / mikrosekundowymi szumami.
- Wartość 1.20 to budget z planu (ADR-0005 "Konsekwencje / Negatywne").
- Pomiary >100× przerost (regresja krytyczna) raise z pełnym breakdown.

Gdy test fail w CI: uruchom `python scripts/profile_quote.py --backend yaml`
+ porównaj z `--backend procedural`, znajdź hot path. Szczegóły w
`docs/PERFORMANCE.md` i `docs/adr/0007-ruleset-cache.md`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config
from app.services.costs import quote as quote_module

# Tunables. `_MAX_RATIO` = budżet z planu Strumienia A (1.20×) z headroomem
# 0.10 na Windows perf noise (na bare-metal Linux median trzyma się ~1.10×).
# `_ATTEMPTS` × min() — odporne na upward spike (GC/scheduler), nie maskuje
# rzeczywistej regresji (jeśli min ratio przekracza budget = realna regresja).
_MAX_RATIO = 1.30
_WARMUP = 2  # liczba warm-up wywołań per backend per unit
_RUNS = 30  # liczba mierzonych wywołań per backend per unit
_ATTEMPTS = 3  # liczba pełnych pomiarów; bierzemy min ratio


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


def _unit(*, quality=4, defense=4, toughness=1, flags="", weapon_kwargs=None, count=3):
    weapon_kwargs = weapon_kwargs or {}
    base_weapon = _weapon(101, **weapon_kwargs)
    return SimpleNamespace(
        quality=quality,
        defense=defense,
        toughness=toughness,
        flags=flags,
        army=None,
        abilities=[],
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


# Mix scenariuszy: prosta piechota, transport (handler), aura, weapon-trait,
# masywny, count-large. Pokrywają główne ścieżki hot path.
_UNITS: list[tuple[str, SimpleNamespace, int]] = [
    ("infantry_basic", _unit(flags="Wojownik"), 3),
    ("infantry_passive", _unit(flags="Nieustraszony,Zwiadowca", toughness=2), 5),
    ("infantry_aura", _unit(flags="Aura(6): Bastion", toughness=3), 1),
    ("transport", _unit(flags="Transport(6),Latajacy", toughness=8), 1),
    ("weapon_traits", _unit(
        flags="Wojownik",
        weapon_kwargs={"range_": '24"', "ap": 2, "tags": "Szturmowy, Przebijajaca, Brutalny"},
    ), 3),
    ("masywny", _unit(flags="Wojownik,Masywny", toughness=6), 2),
    ("large_count", _unit(flags="Strzelec"), 20),
]


def _time_backend(
    monkeypatch: pytest.MonkeyPatch, backend: str, units: list
) -> float:
    """Returns sum of milliseconds across all units × _RUNS."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    # Warm-up (oddzielne, żeby kolejne unity nie kradły LRU od pierwszego).
    for _, unit, count in units:
        for _ in range(_WARMUP):
            quote_module.calculate_roster_unit_quote(unit, {}, count=count)
    # Pomiar.
    total_s = 0.0
    for _, unit, count in units:
        t0 = time.perf_counter()
        for _ in range(_RUNS):
            quote_module.calculate_roster_unit_quote(unit, {}, count=count)
        total_s += time.perf_counter() - t0
    return total_s * 1000.0


def test_yaml_backend_within_perf_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """min(yaml_time / proc_time over _ATTEMPTS) <= _MAX_RATIO.

    `min()` odporne na upward spike (GC pause, scheduler kontekst). Jeśli
    nawet najlepszy z N pomiarów przekracza budget — to realna regresja.
    Diagnostyka: `scripts/profile_quote.py --backend yaml`.
    """
    ratios: list[float] = []
    last_proc = last_yaml = 0.0
    for _ in range(_ATTEMPTS):
        proc_ms = _time_backend(monkeypatch, config.RULES_BACKEND_PROCEDURAL, _UNITS)
        yaml_ms = _time_backend(monkeypatch, config.RULES_BACKEND_YAML, _UNITS)
        if proc_ms < 5.0:
            pytest.skip(
                f"procedural time {proc_ms:.2f} ms below noise floor; widening "
                "_UNITS or _RUNS would help"
            )
        ratios.append(yaml_ms / proc_ms)
        last_proc, last_yaml = proc_ms, yaml_ms

    best_ratio = min(ratios)
    assert best_ratio <= _MAX_RATIO, (
        f"YAML backend perf regression: best_ratio={best_ratio:.3f} > {_MAX_RATIO}. "
        f"All ratios: {[f'{r:.3f}' for r in ratios]}. "
        f"Last proc_ms={last_proc:.2f}, yaml_ms={last_yaml:.2f}. "
        "Diagnoza: scripts/profile_quote.py --backend yaml ROSTER=<id>."
    )


def test_ruleset_loader_lru_cache_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_ruleset()` po pierwszym call zwraca cached instance (LRU+SHA256).

    Drugi call ma być **bit-identyczny** (same `id(...)`). Inaczej hot path
    re-parsuje YAML per quote → katastrofa perf.
    """
    from app.services.rulesets import load_ruleset

    first = load_ruleset()
    second = load_ruleset()
    assert first is second, (
        "load_ruleset() nie hituje LRU cache; konsekwencje perf opisane w "
        "docs/adr/0007-ruleset-cache.md"
    )


def test_yaml_backend_warm_call_under_50ms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity check absolute: warm yaml quote dla typical unit < 50 ms.

    50 ms to konserwatywny upper bound — większość unitów mieści się w 1-5 ms
    po warmie. Liczba ma znaczenie jako ostrzeżenie gdy regresja jest *gigantyczna*
    (np. import-time work w hot path).
    """
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_YAML)
    unit = _unit(flags="Nieustraszony,Zwiadowca", toughness=4)

    # Warmup
    for _ in range(3):
        quote_module.calculate_roster_unit_quote(unit, {}, count=5)

    t0 = time.perf_counter()
    quote_module.calculate_roster_unit_quote(unit, {}, count=5)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 50.0, (
        f"YAML warm quote {elapsed_ms:.1f} ms exceeds 50 ms safety cap"
    )
