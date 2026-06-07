"""A3.1 — pełny parity test YAML vs procedural pod `OPR_RULES_BACKEND=both_assert`.

Strategia:
- 100 cartesian: kombinacje (quality, defense, toughness, abilities-set,
  weapon-config). Sample → ~100 unique scenariuszy.
- 50 manual: edge-case'y (transport × traits, aura × mistrzostwo,
  morale-stack, defense-stack, weapon-trait stack, masywny + role).

Każdy test odpala `calculate_roster_unit_quote` pod `both_assert` — wewnętrzny
`_assert_quote_parity` raise `RulesetParityError` jeśli delta > 1e-3 na
**dowolnym** polu output dict (selected/warrior/shooter totals, components
base/weapon/active/aura/passive, item_costs.weapons/active/aura/passive_deltas).

To jest CI gate (Faza A3). Aby przerwać CI: dodać nowy scenariusz i podpiąć
do `both_assert`. Aby zdebuggować: `RulesetParityError.path` wskazuje
ścieżkę w dict, `delta` wartość różnicy.
"""

from __future__ import annotations

import itertools
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


@pytest.fixture(autouse=True)
def _both_assert_backend(monkeypatch: pytest.MonkeyPatch):
    """Wszystkie testy w tym module działają pod `both_assert`."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_BOTH_ASSERT)


# ---------------------------------------------------------------------------
# Helpers — minimalne fixtures jednostek.
# ---------------------------------------------------------------------------


def _weapon(
    weapon_id: int,
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


def _unit(
    *,
    quality: int = 4,
    defense: int = 4,
    toughness: int = 1,
    flags: str = "",
    weapon_kwargs: dict | None = None,
    abilities: list | None = None,
):
    weapon_kwargs = weapon_kwargs or {}
    base_weapon = _weapon(101, **weapon_kwargs)
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


def _assert_parity(unit, loadout=None, count: int = 1) -> dict:
    """Wywołaj quote pod `both_assert`. Brak RulesetParityError ⇒ ok.

    Zwraca wynik proceduralny (z def. `_both_assert_quote`) dla dodatkowych
    asercji caller-side.
    """
    try:
        return quote_module.calculate_roster_unit_quote(unit, loadout or {}, count=count)
    except RulesetParityError as e:  # pragma: no cover - diagnostic only
        pytest.fail(
            f"RulesetParityError: path={e.path}, delta={e.delta}, "
            f"proc={e.proc_value!r}, yaml={e.yaml_value!r}"
        )


# ---------------------------------------------------------------------------
# 100 cartesian — quality × defense × toughness × abilities × weapon-config.
# ---------------------------------------------------------------------------


# 4 × 4 × 4 × 4 × 2 = 512 raw. Sample na unique ~100 dający dobre pokrycie.
_QUALITY_VALUES = [3, 4, 5, 6]
_DEFENSE_VALUES = [2, 3, 4, 5]
_TOUGHNESS_VALUES = [1, 3, 6, 9]
# Flag sets dobrane tak, żeby pokryć cztery rodzaje gałęzi dispatchera:
# - czysty role/no-flag (sanity),
# - passive scaling (Zwiadowca + morale Nieustraszony),
# - aura handler (`Aura(...): X`),
# - transport handler (priority traits).
# Bez tego pokrycia cartesian dotyka tylko 33 passive recipes z YAML,
# zostawiając handlery na manual case'ach.
_FLAG_SETS = [
    "Wojownik",
    "Strzelec",
    "Nieustraszony,Zwiadowca",
    "Aura(6): Bastion",
    "Transport(6),Latajacy",
    "Mag(2)",
    "Mistrzostwo(przebijajaca)",
]
_WEAPON_CONFIGS = [
    {"range_": '18"', "attacks": 1.0, "ap": 1, "tags": ""},
    {"range_": '24"', "attacks": 1.0, "ap": 2, "tags": "Przebijajaca"},
    {"range_": "Melee", "attacks": 2.0, "ap": 1, "tags": ""},
    {"range_": '24"', "attacks": 1.0, "ap": 1, "tags": "Szturmowy"},
]


def _cartesian_ids():
    """Generator dla cartesian — sample 100 z pełnej kartezjany 4×4×4×4×4=1024.

    Wcześniej brane pierwsze 100 z `itertools.product` co dawało tylko
    pierwsze (q,d,t) cykle dla pierwszego flag/weapon. Teraz `random.sample`
    z seed=0 daje deterministyczne ALE zrównoważone pokrycie wszystkich
    pięciu wymiarów. Failure diagnostics przez `ids=` lambda — czytelne
    `q4_d3_t6_flags-Strzelec_w-Przebijajaca` zamiast indeksu listy.
    """
    import random

    all_combos = list(
        itertools.product(
            _QUALITY_VALUES, _DEFENSE_VALUES, _TOUGHNESS_VALUES,
            _FLAG_SETS, _WEAPON_CONFIGS,
        )
    )
    rng = random.Random(0)
    return rng.sample(all_combos, k=min(100, len(all_combos)))


def _cartesian_id(params: tuple) -> str:
    q, d, t, flags, w = params
    flags_short = flags.replace(",", "+") if flags else "none"
    tags = w.get("tags") or "plain"
    return f"q{q}_d{d}_t{t}_f-{flags_short}_w-{tags[:20]}"


_CARTESIAN_PARAMS = _cartesian_ids()


@pytest.mark.parametrize(
    "q,d,t,flags,weapon_cfg",
    _CARTESIAN_PARAMS,
    ids=[_cartesian_id(p) for p in _CARTESIAN_PARAMS],
)
def test_cartesian_parity(q, d, t, flags, weapon_cfg) -> None:
    unit = _unit(
        quality=q, defense=d, toughness=t, flags=flags, weapon_kwargs=weapon_cfg
    )
    _assert_parity(unit, {}, count=3)


# ---------------------------------------------------------------------------
# 50 manual edge cases — pokrywają DSL handlery i kombinacje, które
# cartesian może pominąć.
# ---------------------------------------------------------------------------


_MANUAL_CASES: dict[str, dict] = {
    # --- 1) Wszystkie role bez abilities ---
    "wojownik_only": dict(unit_kwargs=dict(flags="Wojownik"), count=1),
    "strzelec_only": dict(unit_kwargs=dict(flags="Strzelec"), count=1),
    "no_role_default": dict(unit_kwargs=dict(flags=""), count=1),
    # --- 2) Passive scaling (10 wybranych z 33) ---
    "passive_zasadzka": dict(unit_kwargs=dict(flags="Zasadzka", toughness=4), count=3),
    "passive_zwiadowca": dict(
        unit_kwargs=dict(flags="Zwiadowca", toughness=4), count=3
    ),
    "passive_szybki_zwinny": dict(
        unit_kwargs=dict(flags="Szybki,Zwinny", toughness=3), count=2
    ),
    "passive_latajacy": dict(
        unit_kwargs=dict(flags="Latajacy", toughness=4), count=1
    ),
    "passive_samolot": dict(
        unit_kwargs=dict(flags="Samolot", toughness=9), count=1
    ),
    "passive_regeneracja": dict(
        unit_kwargs=dict(flags="Regeneracja", toughness=6), count=2
    ),
    "passive_tarcza": dict(unit_kwargs=dict(flags="Tarcza", toughness=4), count=4),
    "passive_kontra": dict(unit_kwargs=dict(flags="Kontra", toughness=3), count=5),
    "passive_maskowanie_okopany": dict(
        unit_kwargs=dict(flags="Maskowanie,Okopany", toughness=2), count=10
    ),
    "passive_instynkt": dict(
        unit_kwargs=dict(flags="Instynkt", toughness=2), count=5
    ),
    # --- 3) Morale-multipliers (defensive stack) ---
    "morale_nieustraszony": dict(
        unit_kwargs=dict(flags="Nieustraszony", toughness=2), count=5
    ),
    "morale_ucieczka": dict(
        unit_kwargs=dict(flags="Ucieczka", toughness=2), count=3
    ),
    "morale_stracency": dict(
        unit_kwargs=dict(flags="Stracency", toughness=2), count=3
    ),
    # --- 4) Defense-modifiers ---
    "defense_delikatny": dict(
        unit_kwargs=dict(flags="Delikatny", toughness=2, defense=3), count=3
    ),
    "defense_niewrazliwy": dict(
        unit_kwargs=dict(flags="Niewrazliwy", toughness=4, defense=5), count=2
    ),
    "defense_furia": dict(
        unit_kwargs=dict(flags="Furia", toughness=3, defense=4), count=4
    ),
    # --- 5) Aura — szeroka gama wewnętrznych abilities ---
    "aura_bastion_6": dict(
        unit_kwargs=dict(flags="Aura(6): Bastion", toughness=3), count=1
    ),
    "aura_niestrudzony_6": dict(
        unit_kwargs=dict(flags="Aura(6): Niestrudzony", toughness=4), count=1
    ),
    "aura_nieustraszony_12": dict(
        unit_kwargs=dict(flags="Aura(12): Nieustraszony", toughness=4), count=1
    ),
    "aura_delikatny": dict(
        unit_kwargs=dict(flags="Aura(6): Delikatny", toughness=3, defense=3), count=1
    ),
    "aura_furia_6": dict(
        unit_kwargs=dict(flags="Aura(6): Furia", toughness=4), count=1
    ),
    "aura_dywersant_6": dict(
        unit_kwargs=dict(flags="Aura(6): Dywersant", toughness=4), count=1
    ),
    # --- 6) Transport — różne kombinacje traitów priorytetowych ---
    "transport_basic": dict(
        unit_kwargs=dict(flags="Transport(6)", toughness=8), count=1
    ),
    "transport_szybki": dict(
        unit_kwargs=dict(flags="Transport(6),Szybki", toughness=8), count=1
    ),
    "transport_zwiadowca": dict(
        unit_kwargs=dict(flags="Transport(8),Zwiadowca", toughness=9), count=1
    ),
    "transport_latajacy": dict(
        unit_kwargs=dict(flags="Transport(10),Latajacy", toughness=9), count=1
    ),
    "transport_samolot_szybki": dict(
        unit_kwargs=dict(flags="Transport(8),Samolot,Szybki", toughness=9), count=1
    ),
    "transport_zwinny": dict(
        unit_kwargs=dict(flags="Transport(6),Zwinny", toughness=8), count=1
    ),
    # --- 7) Open transport / platforma strzelecka ---
    "open_transport_basic": dict(
        unit_kwargs=dict(flags="Otwarty Transport(8)", toughness=8), count=1
    ),
    "open_transport_latajacy": dict(
        unit_kwargs=dict(flags="Otwarty Transport(6),Latajacy", toughness=8), count=1
    ),
    "platforma_strzelecka": dict(
        unit_kwargs=dict(flags="Platforma Strzelecka(4),Szybki", toughness=6), count=1
    ),
    # --- 8) Weapon-trait stack (szturmowy + przebijajaca + brutalny) ---
    "weapon_stacked": dict(
        unit_kwargs=dict(
            flags="Wojownik",
            weapon_kwargs={
                "range_": '24"',
                "ap": 2,
                "tags": "Szturmowy, Przebijajaca, Brutalny",
            },
        ),
        count=3,
    ),
    "weapon_overcharge": dict(
        unit_kwargs=dict(
            flags="Strzelec",
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": "Podkrecenie"},
        ),
        count=2,
    ),
    "weapon_finezja_low_q": dict(
        unit_kwargs=dict(
            flags="",
            quality=3,
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": "Finezja"},
        ),
        count=2,
    ),
    "weapon_blast_3": dict(
        unit_kwargs=dict(
            flags="Wojownik",
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": "Rozprysk(3)"},
        ),
        count=3,
    ),
    "weapon_deadly_2": dict(
        unit_kwargs=dict(
            flags="Wojownik",
            weapon_kwargs={"range_": '24"', "ap": 2, "tags": "Zabojczy(2)"},
        ),
        count=3,
    ),
    "weapon_artillery": dict(
        unit_kwargs=dict(
            flags="",
            weapon_kwargs={"range_": '36"', "ap": 2, "tags": "Artyleria"},
        ),
        count=1,
    ),
    "weapon_niezawodny": dict(
        unit_kwargs=dict(
            flags="",
            quality=5,
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": "Niezawodny"},
        ),
        count=2,
    ),
    "weapon_namierzanie": dict(
        unit_kwargs=dict(
            flags="",
            weapon_kwargs={"range_": '36"', "ap": 1, "tags": "Namierzanie"},
        ),
        count=1,
    ),
    # --- 9) Unit-trait + weapon trait interakcje ---
    "waagh_unit": dict(
        unit_kwargs=dict(
            flags="Waagh",
            toughness=3,
            weapon_kwargs={"range_": '12"', "ap": 3, "tags": ""},
        ),
        count=5,
    ),
    "niestrudzony_przygotowanie": dict(
        unit_kwargs=dict(
            flags="Niestrudzony,Przygotowanie",
            toughness=3,
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": ""},
        ),
        count=3,
    ),
    "straznik_unit_ranged": dict(
        unit_kwargs=dict(
            flags="Straznik",
            toughness=3,
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": ""},
        ),
        count=3,
    ),
    "bastion_melee": dict(
        unit_kwargs=dict(
            flags="Bastion",
            toughness=3,
            weapon_kwargs={"range_": "Melee", "attacks": 2.0, "ap": 1, "tags": ""},
        ),
        count=3,
    ),
    "ostrozny_range_bonus": dict(
        unit_kwargs=dict(
            flags="Ostrozny",
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": ""},
        ),
        count=2,
    ),
    "odwody_unit": dict(
        unit_kwargs=dict(
            flags="Odwody",
            toughness=2,
            weapon_kwargs={"range_": '24"', "ap": 1, "tags": ""},
        ),
        count=4,
    ),
    # --- 10) Masywny — wpływa na multiplier abilities ---
    "masywny_alone": dict(
        unit_kwargs=dict(flags="Masywny", toughness=6, defense=3), count=2
    ),
    "masywny_with_passive": dict(
        unit_kwargs=dict(
            flags="Masywny,Nieustraszony", toughness=6, defense=3
        ),
        count=2,
    ),
    # --- 11) Loadout modes ---
    "loadout_per_model": dict(
        unit_kwargs=dict(flags="Wojownik"),
        loadout={"mode": "per_model", "weapons": {"101": 1}},
        count=3,
    ),
    "loadout_total": dict(
        unit_kwargs=dict(flags="Wojownik"),
        loadout={"mode": "total", "weapons": {"101": 3}},
        count=3,
    ),
    # --- 12) Edge counts ---
    "count_zero_proceduralna_path": dict(
        unit_kwargs=dict(flags="Wojownik"), count=0
    ),
    "count_one": dict(unit_kwargs=dict(flags="Wojownik"), count=1),
    "count_large": dict(unit_kwargs=dict(flags="Strzelec"), count=20),
}


@pytest.mark.parametrize("name", sorted(_MANUAL_CASES))
def test_manual_parity(name: str) -> None:
    spec = _MANUAL_CASES[name]
    unit = _unit(**spec["unit_kwargs"])
    _assert_parity(unit, spec.get("loadout", {}), count=spec["count"])


def test_unit_none_parity() -> None:
    """Edge case — `calculate_roster_unit_quote(None)` musi przejść parity."""
    _assert_parity(None, count=1)
