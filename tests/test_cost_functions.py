"""A2.5 — unit tests dla DSL prymitywów z `app/services/rulesets/cost_functions.py`.

Asercja zerowej delty względem oracle SSOT (`app/services/costs/{primitives,
weapons,abilities}.py`) na reprezentatywnych przypadkach. Każda z 13 funkcji
+ wrappery (`weapon_cost_components_yaml`, `weapon_cost_yaml`) ma odpowiadający
test parity.

Inwarianty:
- YAML i oracle czytają te same tabele (`tables.yaml` był wygenerowany 1:1 z
  `_engine.py`), więc każda delta sygnalizuje regression w DSL, nie w danych.
- Funkcje są pure — nie monkeypatchujemy stanu globalnego.
- `RulesetManifest.tables` jest frozen (Pydantic v2), więc ten sam załadowany
  manifest wykorzystywany w session-fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.data import abilities as ability_catalog
from app.services.costs import abilities as oracle_abilities
from app.services.costs import primitives as oracle_primitives
from app.services.costs import weapons as oracle_weapons
from app.services.rulesets import RulesetTables, load_ruleset
from app.services.rulesets import cost_functions as cf


@pytest.fixture(scope="module")
def manifest():
    return load_ruleset()


@pytest.fixture(scope="module")
def tables(manifest) -> RulesetTables:
    return manifest.tables


# ---------------------------------------------------------------------------
# 1) range_multiplier — lookup_with_nearest nad tables.range_table.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("range_value", [0, 6, 9, 12, 18, 24, 36, 48, 5, 7, 13, 100])
def test_range_multiplier_parity(tables: RulesetTables, range_value: int) -> None:
    assert cf.range_multiplier(tables, range_value) == oracle_primitives.range_multiplier(
        range_value
    )


# ---------------------------------------------------------------------------
# 2) ap_modifier — lookup nad tables.ap_base.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ap", [0, 1, 2, 3, 4, 5, 6, 10])
def test_ap_modifier_parity(tables: RulesetTables, ap: int) -> None:
    assert cf.ap_modifier(tables, ap) == oracle_primitives.lookup_with_nearest(
        oracle_weapons.AP_BASE, ap
    )


# ---------------------------------------------------------------------------
# 3) blast_cost — mnożnik z tables.blast_multiplier (1.0 gdy brak).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [2, 3, 4, 6, 9, 11, 999])
def test_blast_cost_falls_back_to_one_when_missing(
    tables: RulesetTables, value: int
) -> None:
    expected = tables.blast_multiplier.get(value, 1.0)
    assert cf.blast_cost(tables, value) == pytest.approx(expected)


def test_blast_cost_matches_engine_table(tables: RulesetTables) -> None:
    from app.services.costs._engine import BLAST_MULTIPLIER

    for k, v in BLAST_MULTIPLIER.items():
        assert cf.blast_cost(tables, k) == pytest.approx(v)


# ---------------------------------------------------------------------------
# 4) deadly_cost — analogicznie dla deadly_multiplier.
# ---------------------------------------------------------------------------


def test_deadly_cost_matches_engine_table(tables: RulesetTables) -> None:
    from app.services.costs._engine import DEADLY_MULTIPLIER

    for k, v in DEADLY_MULTIPLIER.items():
        assert cf.deadly_cost(tables, k) == pytest.approx(v)


def test_deadly_cost_missing_returns_one(tables: RulesetTables) -> None:
    assert cf.deadly_cost(tables, 999) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5) morale_modifier — czysta formuła quality-based.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("q", [1, 2, 3, 4, 5, 6, 7])  # 1 i 7 testują clamp
@pytest.mark.parametrize("penalty", [1.0, 0.5, 2.0, 0.0, -1.0])
def test_morale_modifier_parity(q: int, penalty: float) -> None:
    assert cf.morale_modifier(q, penalty) == pytest.approx(
        oracle_primitives.morale_modifier(q, penalty)
    )


# ---------------------------------------------------------------------------
# 6) defense_modifier — bazowa wartość plus delty per ability slug.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defense", [1, 2, 3, 4, 5, 6, 7])  # 1 i 7 testują clamp
@pytest.mark.parametrize(
    "slugs",
    [
        None,
        [],
        ["bastion"],
        ["delikatny"],
        ["niewrazliwy"],
        ["bastion", "niewrazliwy"],
        ["unknown_slug"],
    ],
)
def test_defense_modifier_parity(
    tables: RulesetTables, defense: int, slugs
) -> None:
    assert cf.defense_modifier(tables, defense, slugs) == pytest.approx(
        oracle_primitives.defense_modifier(defense, slugs)
    )


# ---------------------------------------------------------------------------
# 7) toughness_modifier — tables.toughness_special dla {1..4}, inaczej formuła.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tou", [1, 2, 3, 4, 5, 6, 8, 10, 12, 15])
def test_toughness_modifier_parity(tables: RulesetTables, tou: int) -> None:
    assert cf.toughness_modifier(tables, tou) == pytest.approx(
        oracle_primitives.toughness_modifier(tou)
    )


# ---------------------------------------------------------------------------
# 8) transport_multiplier — priority-first (oracle uzywa for-loop bez breaku,
# YAML ma `break` po fix parity-bug w A2.4c). Asercja: identyczny wynik dla
# wszystkich kombinacji z _engine.TRANSPORT_MULTIPLIERS.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ability_set",
    [
        frozenset(),
        frozenset({"szybki"}),
        frozenset({"zwiadowca"}),
        frozenset({"zasadzka"}),
        frozenset({"latajacy"}),
        frozenset({"samolot"}),
        frozenset({"zwinny"}),
        frozenset({"latajacy", "samolot"}),  # priority — samolot wygrywa
        frozenset({"szybki", "zwinny"}),  # priority — zwinny wygrywa?
        frozenset({"unknown"}),  # brak match → 1.0
    ],
)
def test_transport_multiplier_priority_matches_yaml_order(
    tables: RulesetTables, ability_set: frozenset[str]
) -> None:
    """YAML używa `break` po pierwszym matchu — testujemy bezpośrednio na YAML.

    Oracle używa last-match-wins (bez breaku); A2.4c udowodnił że to bug —
    YAML priority-first jest poprawnym wynikiem. Te asercje pilnują że
    `transport_multiplier()` honoruje kolejność z `tables.yaml`.
    """
    expected = 1.0
    for rule in tables.transport_multipliers:
        if ability_set & rule.traits_set:
            expected = rule.multiplier
            break
    assert cf.transport_multiplier(tables, ability_set) == pytest.approx(expected)


def test_transport_multiplier_ignores_empty_string_in_set(
    tables: RulesetTables,
) -> None:
    """Sygnatura `ability_set: Iterable[str]` — pusty string jest pomijany."""
    assert cf.transport_multiplier(tables, ["", None]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 9) scale_by_tou — passive cost scaling. 5 flag (base/scale/aura_required/
# aura_alt_base/aura_scale).
# ---------------------------------------------------------------------------


def test_scale_by_tou_simple_multiplication() -> None:
    """zasadzka: base=4.0, scale=True (default), aura=False/True bez zmiany."""
    assert cf.scale_by_tou(3.0, 4.0) == pytest.approx(12.0)
    assert cf.scale_by_tou(3.0, 4.0, aura=True) == pytest.approx(12.0)


def test_scale_by_tou_aura_required_returns_zero_outside_aura() -> None:
    """bastion: aura_required=True → 0 gdy aura=False."""
    assert cf.scale_by_tou(3.0, 3.0, aura=False, aura_required=True) == pytest.approx(
        0.0
    )
    # w aurze: scale=True (default) → base * tou
    assert cf.scale_by_tou(3.0, 3.0, aura=True, aura_required=True) == pytest.approx(
        9.0
    )


def test_scale_by_tou_no_scale() -> None:
    """odwody: scale=False → base bez mnożenia."""
    assert cf.scale_by_tou(5.0, 0.0, scale=False) == pytest.approx(0.0)
    assert cf.scale_by_tou(5.0, 3.0, scale=False) == pytest.approx(3.0)


def test_scale_by_tou_aura_alt_base() -> None:
    """instynkt: base=-1.0, aura_alt_base=+1.0 — sign flip w aurze."""
    assert cf.scale_by_tou(3.0, -1.0, aura=False, aura_alt_base=1.0) == pytest.approx(
        -3.0
    )
    assert cf.scale_by_tou(3.0, -1.0, aura=True, aura_alt_base=1.0) == pytest.approx(
        3.0
    )


def test_scale_by_tou_aura_scale_overrides_scale_in_aura() -> None:
    """dywersant: base=1.25, scale=False, aura_scale=True →
    aura=False: 1.25, aura=True: 1.25*tou."""
    assert cf.scale_by_tou(
        3.0, 1.25, scale=False, aura_scale=True, aura=False
    ) == pytest.approx(1.25)
    assert cf.scale_by_tou(
        3.0, 1.25, scale=False, aura_scale=True, aura=True
    ) == pytest.approx(3.75)


@pytest.mark.parametrize(
    "ability_name,tou,aura",
    [
        ("zasadzka", 3.0, False),
        ("zasadzka", 3.0, True),
        ("zwiadowca", 4.0, False),
        ("odwody", 5.0, False),
        ("szybki", 2.0, False),
        ("wolny", 2.0, False),
        ("harcownik", 3.0, False),
        ("instynkt", 4.0, False),
        ("instynkt", 4.0, True),
        ("nieruchomy", 3.0, False),
        ("zwinny", 5.0, False),
        ("niezgrabny", 3.0, False),
        ("latajacy", 4.0, False),
        ("samolot", 6.0, False),
        ("kontra", 3.0, False),
        ("maskowanie", 3.0, False),
        ("okopany", 2.0, False),
        ("tarcza", 4.0, False),
        ("regeneracja", 3.0, False),
        ("dywersant", 4.0, False),
        ("dywersant", 4.0, True),
        ("zdobywca", 3.0, False),
        ("straznik", 4.0, False),
        ("cierpliwy", 3.0, False),
        ("roj", 5.0, False),
        ("zwrot", 3.0, False),
        ("bastion", 4.0, False),
        ("bastion", 4.0, True),
        ("niestrudzony", 4.0, True),
        ("nieustraszony", 5.0, True),
        ("delikatny", 3.0, True),
        ("niewrazliwy", 4.0, True),
        ("furia", 3.0, True),
        ("przygotowanie", 4.0, True),
        ("ostrozny", 5.0, True),
    ],
)
def test_passive_cost_dsl_matches_oracle(
    manifest, tables: RulesetTables, ability_name: str, tou: float, aura: bool
) -> None:
    """passive_cost_dsl (z YAML recipes) musi zwracać identyczny wynik co
    oracle `abilities.passive_cost`. Test cartesian na wszystkich 33 passive
    slugach × {aura ON/OFF gdzie istotne}."""
    from app.services.rulesets.dispatcher import passive_cost_dsl
    from app.services.rulesets.handlers import _build_passive_recipes

    recipes = _build_passive_recipes(manifest.ability_costs)
    dsl = passive_cost_dsl(tables, recipes, ability_name, tou=tou, aura=aura)
    oracle = oracle_abilities.passive_cost(ability_name, tou, aura)
    assert dsl == pytest.approx(oracle), (
        f"passive mismatch for {ability_name!r}: dsl={dsl}, oracle={oracle}"
    )


def test_passive_cost_dsl_unknown_slug_returns_zero(manifest, tables) -> None:
    from app.services.rulesets.dispatcher import passive_cost_dsl
    from app.services.rulesets.handlers import _build_passive_recipes

    recipes = _build_passive_recipes(manifest.ability_costs)
    assert passive_cost_dsl(tables, recipes, "nieistniejacy_slug", tou=3.0) == 0.0


def test_passive_cost_dsl_empty_name_returns_zero(manifest, tables) -> None:
    from app.services.rulesets.dispatcher import passive_cost_dsl
    from app.services.rulesets.handlers import _build_passive_recipes

    recipes = _build_passive_recipes(manifest.ability_costs)
    assert passive_cost_dsl(tables, recipes, "", tou=3.0) == 0.0
    assert passive_cost_dsl(tables, recipes, None, tou=3.0) == 0.0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 10) base_model_cost — pełna replika oracle z wstrzykniętym passive_cost_fn.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quality,defense,toughness,abilities",
    [
        (4, 4, 1, None),
        (4, 4, 1, []),
        (4, 3, 6, ["Nieustraszony"]),
        (3, 4, 4, ["Bastion"]),
        (4, 4, 4, ["Zasadzka", "Zwinny"]),
        (5, 5, 2, ["Delikatny"]),
        (4, 4, 3, ["Wojownik"]),  # role slug — nie morale/defense
        (4, 4, 8, ["Samolot", "Latajacy"]),
        (4, 4, 1, ["Niewrazliwy", "Bastion"]),
        (4, 2, 6, ["Maskowanie", "Okopany"]),
    ],
)
def test_base_model_cost_parity(
    manifest, tables, quality, defense, toughness, abilities
) -> None:
    from app.services.rulesets.dispatcher import passive_cost_dsl
    from app.services.rulesets.handlers import _build_passive_recipes

    recipes = _build_passive_recipes(manifest.ability_costs)

    def _passive_fn(name, tou, aura, abs_):
        return passive_cost_dsl(tables, recipes, name, tou=tou, aura=aura, abilities=abs_)

    dsl = cf.base_model_cost(
        tables, quality, defense, toughness, abilities, passive_cost_fn=_passive_fn
    )
    oracle = oracle_abilities.base_model_cost(quality, defense, toughness, abilities)
    assert dsl == pytest.approx(oracle, abs=1e-9), (
        f"base_model_cost mismatch: dsl={dsl}, oracle={oracle}"
    )


# ---------------------------------------------------------------------------
# 11) parse_aura_value — parsing aura definicji.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("Aura", "Bastion"),
        ("Aura(12)", "Bastion"),
        ("Aura", "Bastion|12"),
        ("Aura: Bastion", None),
        ("Aura(6): Niewrazliwy", None),
        ("Aura(12): Niestrudzony", None),
        ("aura", "  furia  "),
    ],
)
def test_parse_aura_value_parity(name: str, value: str | None) -> None:
    dsl = cf.parse_aura_value(name, value, slug_for_name=ability_catalog.slug_for_name)
    oracle = oracle_abilities._parse_aura_value(name, value)
    assert dsl == oracle


# ---------------------------------------------------------------------------
# 12) _weapon_cost_yaml — pełna replika weapons._weapon_cost.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quality,range_v,attacks,ap,wt,ut",
    [
        # Plain ranged
        (4, 24, 1, 0, [], []),
        (4, 18, 2, 1, [], []),
        # Plain melee
        (4, 0, 2, 1, [], []),
        # Wojownik reduces ranged
        (4, 24, 1, 0, [], ["wojownik"]),
        # Strzelec reduces melee
        (4, 0, 2, 1, [], ["strzelec"]),
        # Weapon trait — assault (recursion: melee + ranged)
        (4, 18, 2, 1, ["szturmowy"], []),
        # Weapon trait — blast(3) lookup
        (4, 24, 1, 1, ["rozprysk(3)"], []),
        # Weapon trait — deadly(2) lookup
        (4, 24, 1, 1, ["zabojczy(2)"], []),
        # Unit trait — niestrudzony × przygotowanie
        (4, 24, 1, 1, [], ["niestrudzony", "przygotowanie"]),
        # Unit trait — straznik (×1.7 ranged)
        (4, 24, 1, 1, [], ["straznik"]),
        # Unit trait — bastion melee (×1.2)
        (4, 0, 2, 1, [], ["bastion"]),
        # Combined weapon traits — penetrating + brutal
        (4, 18, 2, 2, ["przebijajaca", "brutalny"], []),
        # finezja (chance bonus)
        (3, 24, 1, 1, ["finezja"], []),
        # overcharge ranged (×OVERCHARGE_MULTIPLIER)
        (4, 24, 1, 1, ["podkrecenie"], []),
        # niezawodny → q=2
        (5, 24, 1, 1, ["niezawodny"], []),
        # waagh penalty
        (4, 24, 1, 3, [], ["waagh"]),
    ],
)
def test_weapon_cost_yaml_inner_parity(
    tables, quality, range_v, attacks, ap, wt, ut
) -> None:
    dsl = cf._weapon_cost_yaml(tables, quality, range_v, attacks, ap, wt, ut)
    oracle = oracle_weapons._weapon_cost(quality, range_v, attacks, ap, wt, ut)
    assert dsl == pytest.approx(oracle), (
        f"weapon mismatch: quality={quality}, range={range_v}, attacks={attacks}, "
        f"ap={ap}, wt={wt}, ut={ut}: dsl={dsl}, oracle={oracle}"
    )


# ---------------------------------------------------------------------------
# 13) _mistrzostwo_aura_cost — fixed q=4, dwa probe shots.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "weapon_slug",
    ["przebijajaca", "rozrywajacy", "lanca", "namierzanie", "brutalny", "finezja"],
)
def test_mistrzostwo_aura_cost_parity(tables, weapon_slug: str) -> None:
    dsl = cf._mistrzostwo_aura_cost(tables, weapon_slug)
    oracle = oracle_abilities._mistrzostwo_aura_cost(weapon_slug)
    assert dsl == pytest.approx(oracle)


# ---------------------------------------------------------------------------
# 14) _mistrzostwo_weapon_cost — sumowane delty po broniach jednostki.
# ---------------------------------------------------------------------------


def _make_weapon(range_v: str, attacks: float, ap: int, tags: str = ""):
    return SimpleNamespace(
        effective_range=range_v,
        effective_attacks=attacks,
        effective_ap=ap,
        effective_tags=tags,
        effective_cached_cost=None,
    )


def test_mistrzostwo_weapon_cost_parity_empty(tables) -> None:
    """Brak broni → 0 w obu wersjach."""
    assert cf._mistrzostwo_weapon_cost(tables, "przebijajaca", [], 4, []) == 0.0
    assert (
        oracle_abilities._mistrzostwo_weapon_cost("przebijajaca", [], 4, []) == 0.0
    )


def test_mistrzostwo_weapon_cost_parity_single_weapon(tables) -> None:
    weapons = [_make_weapon('24"', 1.0, 1)]
    dsl = cf._mistrzostwo_weapon_cost(tables, "przebijajaca", weapons, 4, [])
    oracle = oracle_abilities._mistrzostwo_weapon_cost(
        "przebijajaca", weapons, 4, []
    )
    assert dsl == pytest.approx(oracle)


def test_mistrzostwo_weapon_cost_skips_weapon_with_trait_already(tables) -> None:
    """Broń, która już ma trait, jest pomijana (oracle linia 194: `if weapon_slug in
    {normalize_name(t) for t in existing}: continue`)."""
    weapons = [
        _make_weapon('24"', 1.0, 1, tags="przebijajaca"),  # already has trait
        _make_weapon("Melee", 2.0, 1),  # added trait will count
    ]
    dsl = cf._mistrzostwo_weapon_cost(tables, "przebijajaca", weapons, 4, [])
    oracle = oracle_abilities._mistrzostwo_weapon_cost(
        "przebijajaca", weapons, 4, []
    )
    assert dsl == pytest.approx(oracle)


# ---------------------------------------------------------------------------
# 15) weapon_cost_components_yaml — wrapper z melee+ranged buckets.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "range_str,attacks,ap,tags,unit_traits",
    [
        ('24"', 1.0, 1, "", []),
        ("Melee", 2.0, 1, "", []),
        ('18"', 2.0, 1, "szturmowy", []),  # assault → melee + ranged
        ('24"', 1.0, 0, "rozprysk(3)", []),
        ('24"', 1.0, 1, "", ["Wojownik"]),
        ("Melee", 2.0, 1, "", ["Strzelec"]),
        ('30"', 1.0, 2, "przebijajaca", ["Niestrudzony"]),
    ],
)
def test_weapon_cost_components_yaml_parity(
    tables, range_str, attacks, ap, tags, unit_traits
) -> None:
    weapon = _make_weapon(range_str, attacks, ap, tags=tags)
    dsl = cf.weapon_cost_components_yaml(tables, weapon, 4, unit_traits)
    oracle = oracle_weapons.weapon_cost_components(weapon, 4, unit_traits)
    assert dsl == oracle


# ---------------------------------------------------------------------------
# 16) weapon_cost_yaml — wrapper zwracający rounded total.
# ---------------------------------------------------------------------------


def test_weapon_cost_yaml_returns_rounded_nonneg(tables) -> None:
    weapon = _make_weapon('24"', 1.0, 1)
    dsl = cf.weapon_cost_yaml(tables, weapon, 4, [])
    assert isinstance(dsl, float)
    assert dsl >= 0.0


def test_weapon_cost_yaml_ignores_cache_attr(tables) -> None:
    """Cache (`effective_cached_cost`) jest świadomie pomijany w YAML wrapperze
    (komentarz w cost_functions.py: parity nie zalezy od pre-warmu)."""
    weapon = _make_weapon('24"', 1.0, 1)
    weapon.effective_cached_cost = 999.0  # gdyby cache zadziałał, dostalibyśmy 999
    dsl = cf.weapon_cost_yaml(tables, weapon, 4, [])
    assert dsl < 100.0  # rozsądny zakres dla broni 24"/1/1


@pytest.mark.parametrize(
    "range_str,attacks,ap,tags,unit_traits",
    [
        ('24"', 1.0, 1, "", []),
        ("Melee", 2.0, 1, "", []),
        ('24"', 1.0, 1, "", ["Wojownik"]),
        ('30"', 1.0, 2, "przebijajaca, namierzanie", []),
    ],
)
def test_weapon_cost_yaml_matches_oracle_when_no_cache(
    tables, range_str, attacks, ap, tags, unit_traits
) -> None:
    """Bezpośrednie porównanie z `weapons.weapon_cost(use_cached=False)` —
    YAML wrapper również ignoruje cache."""
    weapon = _make_weapon(range_str, attacks, ap, tags=tags)
    dsl = cf.weapon_cost_yaml(tables, weapon, 4, unit_traits)
    oracle = oracle_weapons.weapon_cost(weapon, 4, unit_traits, use_cached=False)
    assert dsl == pytest.approx(oracle)
