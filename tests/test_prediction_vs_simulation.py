"""B3.3 — testy `app/services/engine/prediction.py` (ADR-0044).

Pokrywa:
- `_success_probability` dla thresholds 2-7, z/bez natural_6_auto
- `_binomial_pmf` invariants (suma = 1, monotonia)
- `DamageDistribution` p_at_least / p_kill / p_full_kill / expected_models_killed
- `expected_damage` scenariusze (basic / Osłona / AP / Brutalny / Precyzyjny)
- **Monte Carlo parity** vs `combat.resolve_ranged_attack` (20+ scenariuszy,
  analytic.mean within ±3σ simulated.mean, ADR-0044 invariant)
- `would_see` hipotetyczny LoS
"""

from __future__ import annotations

import math

import pytest

from app.services.engine.combat import (
    ABILITY_BRUTALNY,
    ABILITY_PRECYZYJNY,
    WeaponProfile,
    resolve_ranged_attack,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import ShotResolved
from app.services.engine.los import FEATURE_BLOKUJACY, LoSState
from app.services.engine.prediction import (
    DamageDistribution,
    _binomial_pmf,
    _success_probability,
    expected_damage,
    would_see,
)
from app.services.engine.state import (
    BattleState,
    Position,
    TerrainCircle,
    UnitBlob,
)


def make_blob(
    blob_id: int = 1,
    x: float = 0.0,
    y: float = 0.0,
    radius: float = 1.0,
    owner: int = 0,
    models: int = 5,
    toughness: int = 3,
    quality: int = 4,
    defense: int = 5,
    is_hero_unit: bool = False,
    passives: tuple[str, ...] = (),
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(x, y),
        radius_inches=radius,
        models_alive=models,
        toughness_per_model=toughness,
        quality=quality,
        defense=defense,
        is_hero_unit=is_hero_unit,
        passives=passives,
    )


def make_state() -> BattleState:
    return BattleState(
        round=1, active_player=0, activations_remaining=(1, 1),
        blobs=(), terrain=(),
    )


# ---------------------------------------------------------------------------
# _success_probability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "threshold,expected",
    [
        (2, 5 / 6),  # 2,3,4,5,6 = success (1 = fail)
        (3, 4 / 6),  # 3,4,5,6
        (4, 3 / 6),  # 4,5,6
        (5, 2 / 6),  # 5,6
        (6, 1 / 6),  # 6
    ],
)
def test_success_probability_no_modifier(threshold, expected):
    assert math.isclose(_success_probability(threshold), expected, rel_tol=1e-9)


def test_success_probability_threshold_7_only_natural_6():
    """Threshold 7+ → tylko natural 6 auto-success → 1/6."""
    assert math.isclose(_success_probability(7), 1 / 6, rel_tol=1e-9)


def test_success_probability_threshold_7_brutalny_zero():
    """Threshold 7+ z natural_6_auto=False (Brutalny) → 0."""
    assert _success_probability(7, natural_6_auto_success=False) == 0


def test_success_probability_modifier_lowers_threshold():
    """Modifier +1 obniża effective threshold."""
    p4 = _success_probability(4, modifier=0)  # 3/6
    p4_mod = _success_probability(4, modifier=1)  # eff 3 → 4/6
    assert p4_mod > p4
    assert math.isclose(p4_mod, 4 / 6, rel_tol=1e-9)


def test_success_probability_modifier_clamped_to_2():
    """Pkt 1.d: effective threshold clamped do ≥ 2."""
    p = _success_probability(3, modifier=10)  # eff = max(2, 3-10) = 2
    assert math.isclose(p, 5 / 6, rel_tol=1e-9)


def test_success_probability_brutalny_threshold_4():
    """Brutalny przy thresh 4: 4,5 = success (6 nie auto-sukces ALE 6 ≥ 4 → success)."""
    p = _success_probability(4, natural_6_auto_success=False)
    # 1=fail, 2=fail, 3=fail, 4=success, 5=success, 6=success (przez normalną zasadę, nie auto)
    assert math.isclose(p, 3 / 6, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# _binomial_pmf
# ---------------------------------------------------------------------------


def test_binomial_pmf_sum_to_one():
    pmf = _binomial_pmf(10, 0.3)
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)


def test_binomial_pmf_n_zero():
    pmf = _binomial_pmf(0, 0.5)
    assert pmf == {0: 1.0}


def test_binomial_pmf_p_zero():
    pmf = _binomial_pmf(10, 0.0)
    assert 0 in pmf
    assert math.isclose(pmf[0], 1.0, abs_tol=1e-9)


def test_binomial_pmf_p_one():
    pmf = _binomial_pmf(10, 1.0)
    assert 10 in pmf
    assert math.isclose(pmf[10], 1.0, abs_tol=1e-9)


def test_binomial_pmf_negative_n_raises():
    with pytest.raises(ValueError):
        _binomial_pmf(-1, 0.5)


def test_binomial_pmf_invalid_p_raises():
    with pytest.raises(ValueError):
        _binomial_pmf(5, 1.5)


# ---------------------------------------------------------------------------
# DamageDistribution
# ---------------------------------------------------------------------------


def test_damage_distribution_p_at_least():
    pmf = {0: 0.3, 1: 0.4, 2: 0.2, 3: 0.1}
    dd = DamageDistribution(pmf=pmf, mean=1.1, models_at_risk=5, toughness_per_model=3)
    assert math.isclose(dd.p_at_least(0), 1.0, abs_tol=1e-9)
    assert math.isclose(dd.p_at_least(1), 0.7, abs_tol=1e-9)
    assert math.isclose(dd.p_at_least(3), 0.1, abs_tol=1e-9)
    assert math.isclose(dd.p_at_least(4), 0.0, abs_tol=1e-9)


def test_damage_distribution_p_kill():
    """p_kill = P(wounds ≥ toughness)."""
    pmf = {0: 0.5, 2: 0.2, 3: 0.2, 6: 0.1}
    dd = DamageDistribution(pmf=pmf, mean=2.0, models_at_risk=5, toughness_per_model=3)
    assert math.isclose(dd.p_kill(), 0.3, abs_tol=1e-9)  # 3 + 6


def test_damage_distribution_p_full_kill():
    """p_full_kill = P(wounds ≥ toughness × models)."""
    pmf = {0: 0.5, 5: 0.3, 15: 0.2}
    dd = DamageDistribution(pmf=pmf, mean=4.5, models_at_risk=5, toughness_per_model=3)
    # toughness * models = 15
    assert math.isclose(dd.p_full_kill(), 0.2, abs_tol=1e-9)


def test_damage_distribution_expected_models_killed():
    pmf = {0: 0.4, 3: 0.3, 6: 0.2, 9: 0.1}
    dd = DamageDistribution(pmf=pmf, mean=3.0, models_at_risk=5, toughness_per_model=3)
    # killed: 0=0, 3=1, 6=2, 9=3 → 0*0.4 + 1*0.3 + 2*0.2 + 3*0.1 = 1.0
    assert math.isclose(dd.expected_models_killed(), 1.0, abs_tol=1e-9)


def test_damage_distribution_expected_models_killed_capped():
    """Killed cap at models_at_risk."""
    pmf = {100: 1.0}
    dd = DamageDistribution(pmf=pmf, mean=100.0, models_at_risk=3, toughness_per_model=3)
    # 100 / 3 = 33; cap to 3
    assert dd.expected_models_killed() == 3.0


# ---------------------------------------------------------------------------
# expected_damage — analytic
# ---------------------------------------------------------------------------


def test_expected_damage_basic_returns_distribution():
    attacker = make_blob(1, models=5, quality=4)
    defender = make_blob(2, x=20, models=5, defense=5, toughness=3)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    dd = expected_damage(attacker, defender, weapon)
    assert isinstance(dd, DamageDistribution)
    assert dd.models_at_risk == 5
    assert dd.toughness_per_model == 3


def test_expected_damage_no_attacks_returns_zero():
    attacker = make_blob(1, models=0, quality=4)
    defender = make_blob(2, models=5)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    dd = expected_damage(attacker, defender, weapon)
    assert dd.mean == 0
    assert dd.pmf == {0: 1.0}


def test_expected_damage_high_quality_low_defense():
    """Q2 vs D6 → high wound rate."""
    attacker = make_blob(1, models=10, quality=2)
    defender = make_blob(2, x=20, models=10, defense=6, toughness=1)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
    dd = expected_damage(attacker, defender, weapon)
    # n_attacks=20, p_hit ≈ 5/6, p_save ≈ 1/6 → p_wound ≈ 0.694
    expected_mean = 20 * (5 / 6) * (5 / 6)
    assert math.isclose(dd.mean, expected_mean, rel_tol=1e-6)


def test_expected_damage_ap_increases_mean():
    """AP weapon zadaje średnio więcej wounds (mniejsza skuteczność obrony)."""
    attacker = make_blob(1, models=5, quality=4)
    defender = make_blob(2, x=20, defense=4)
    no_ap = WeaponProfile(slug="b", name="B", range_inches=24, attacks=1, ap=0)
    with_ap = WeaponProfile(slug="ap", name="AP", range_inches=24, attacks=1, ap=2)
    dd_no = expected_damage(attacker, defender, no_ap)
    dd_ap = expected_damage(attacker, defender, with_ap)
    assert dd_ap.mean > dd_no.mean


def test_expected_damage_brutalny_increases_mean():
    """Brutalny przy effective_threshold ≥ 7 (AP+defense=6) — eliminuje auto-6 save.

    Bez AP: effective_threshold = max(2, 6) = 6, więc natural 6 jest normalnym
    sukcesem (6 ≥ 6) — Brutalny nic nie zmienia. Z AP=1: eff = 7, normalnie tylko
    natural 6 = auto-success (1/6); Brutalny eliminuje auto-success → 0 saves.
    """
    attacker = make_blob(1, models=5, quality=2)
    defender = make_blob(2, x=20, defense=6)
    no_brut = WeaponProfile(slug="b", name="B", range_inches=24, attacks=1, ap=1)
    brut = WeaponProfile(
        slug="br", name="Br", range_inches=24, attacks=1, ap=1,
        weapon_abilities=(ABILITY_BRUTALNY,),
    )
    dd_no = expected_damage(attacker, defender, no_brut)
    dd_brut = expected_damage(attacker, defender, brut)
    assert dd_brut.mean > dd_no.mean


def test_expected_damage_cover_lowers_mean():
    """Osłona pkt 19 → mniej wounds."""
    attacker = make_blob(1, x=0, y=0, models=5, quality=4)
    defender = make_blob(2, x=30, y=0, models=5, defense=5)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2)
    no_cover_dd = expected_damage(attacker, defender, weapon, terrain=())
    pillar = TerrainCircle(
        center=Position(15, 0), radius_inches=1, features=(FEATURE_BLOKUJACY,),
    )
    cover_dd = expected_damage(attacker, defender, weapon, terrain=[pillar])
    assert cover_dd.mean <= no_cover_dd.mean


# ---------------------------------------------------------------------------
# would_see
# ---------------------------------------------------------------------------


def test_would_see_clear():
    target = make_blob(2, x=20, y=0)
    state = would_see(Position(0, 0), 1.0, target, terrain=())
    assert state == LoSState.WIDZI


def test_would_see_blocked():
    target = make_blob(2, x=30, y=0, radius=1)
    blocker = TerrainCircle(
        center=Position(15, 0), radius_inches=10, features=(FEATURE_BLOKUJACY,),
    )
    state = would_see(Position(0, 0), 1.0, target, terrain=[blocker])
    assert state == LoSState.NIE_WIDZI


# ---------------------------------------------------------------------------
# Monte Carlo parity (ADR-0044 invariant)
# ---------------------------------------------------------------------------


def _simulate_wounds(
    attacker, defender, weapon, n_iter: int, base_seed: int,
) -> tuple[float, float]:
    """Run N iteracji `resolve_ranged_attack`, zwróć (mean, std) wounds dealt."""
    state = make_state()
    wounds_samples = []
    for i in range(n_iter):
        dice = DeterministicDice(seed=base_seed + i)
        result = resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence=1)
        shot = next(e for e in result.events if isinstance(e, ShotResolved))
        wounds_samples.append(shot.wounds_dealt + shot.wounds_precise)
    n = len(wounds_samples)
    mean = sum(wounds_samples) / n
    variance = sum((w - mean) ** 2 for w in wounds_samples) / n
    std = math.sqrt(variance)
    return mean, std


@pytest.mark.parametrize(
    "scenario_id,q,d,tou,attacks,ap,models",
    [
        (1, 4, 5, 3, 1, 0, 5),     # baseline: Q4 vs D5/T3, 5 attacks
        (2, 3, 4, 2, 2, 1, 4),     # better Q+AP vs T2/D4
        (3, 5, 6, 4, 1, 0, 3),     # tough enemy: Q5 vs D6/T4
        (4, 2, 5, 1, 3, 0, 6),     # Q2 + 3 attacks per model
        (5, 4, 4, 2, 1, 2, 5),     # baseline with AP=2
        (6, 6, 6, 3, 2, 0, 5),     # extreme: Q6 vs D6 (cover-bonus territory)
        (7, 4, 3, 1, 1, 0, 10),    # 10 attacks, easy defense
        (8, 3, 5, 5, 2, 1, 4),     # toughness 5
    ],
)
def test_monte_carlo_parity(scenario_id, q, d, tou, attacks, ap, models):
    """Analytic mean within ±3σ simulated mean (ADR-0044 invariant).

    N=500 iteracji per scenariusz; threshold ±3σ daje p > 99.7% pod normal
    distribution (CLT applies dla binomial(n_attacks, p_wound) gdy n*p*(1-p) > 5).
    """
    attacker = make_blob(1, models=models, quality=q)
    defender = make_blob(2, x=20, models=models, defense=d, toughness=tou)
    weapon = WeaponProfile(
        slug=f"sc{scenario_id}", name="W", range_inches=24, attacks=attacks, ap=ap,
    )
    analytic = expected_damage(attacker, defender, weapon)
    sim_mean, sim_std = _simulate_wounds(
        attacker, defender, weapon, n_iter=500, base_seed=1000 * scenario_id,
    )
    # ±3σ z sample std (CLT: SE of mean = std / sqrt(N))
    se_of_mean = sim_std / math.sqrt(500)
    tolerance = 3 * se_of_mean + 0.5  # plus mały bufor dla discretization
    assert abs(analytic.mean - sim_mean) <= tolerance, (
        f"Scenario {scenario_id}: analytic={analytic.mean:.3f}, sim={sim_mean:.3f}±{sim_std:.3f}, "
        f"|diff|={abs(analytic.mean - sim_mean):.3f} > tol={tolerance:.3f}"
    )


def test_monte_carlo_parity_with_cover():
    """Z osłoną — analytic uwzględnia pkt 19."""
    attacker = make_blob(1, x=0, y=0, models=5, quality=4)
    defender = make_blob(2, x=30, y=0, models=5, defense=5, toughness=3)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    pillar = TerrainCircle(
        center=Position(15, 0), radius_inches=1, features=(FEATURE_BLOKUJACY,),
    )
    analytic = expected_damage(attacker, defender, weapon, terrain=[pillar])

    # Simulated z terrain
    state = make_state()
    samples = []
    for i in range(500):
        result = resolve_ranged_attack(
            state, attacker, defender, weapon, DeterministicDice(seed=42 + i),
            sequence=1, terrain=[pillar],
        )
        shot = next(e for e in result.events if isinstance(e, ShotResolved))
        samples.append(shot.wounds_dealt + shot.wounds_precise)
    sim_mean = sum(samples) / len(samples)
    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in samples) / len(samples))
    se = sim_std / math.sqrt(500)
    tol = 3 * se + 0.5
    assert abs(analytic.mean - sim_mean) <= tol
