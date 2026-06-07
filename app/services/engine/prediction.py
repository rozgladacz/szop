"""B3.3 — Analytic prediction module (`SZOP_Rozjemca.md pkt 17 + 19`, ADR-0044).

Public API:
- `expected_damage(attacker, defender, weapon, terrain=())` → `DamageDistribution`
  — analityczny equivalent `combat.resolve_ranged_attack`, bez RNG.
- `would_see(attacker_pos, target, terrain)` → `LoSState` — hipotetyczny LoS
  (dla heuristic players w Strumieniu D).
- `_success_probability(threshold, modifier, ...)` — primitive: prob. sukcesu
  na kostce k6 per pkt 1.

Konsumenci:
- `app/services/agents/` (Strumień D) — `greedy_player` wybiera target z
  najwyższym `expected_damage.mean`.
- `mcp_server/tools/simulate_engagement` (Strumień C) — szybki estymator bez
  100× Monte Carlo per evaluation.

Inwariant ADR-0044: `expected_damage.mean` musi być **w zakresie ±3σ** średniej
z `combat.resolve_ranged_attack` Monte Carlo (N=500 iteracji, p > 0.01 chi-square
dla pmf w typowych scenariuszach). Naruszenie inwariantu = bug w prediction lub
combat (test `test_prediction_vs_simulation.py`).

MVP scope (zgodny z combat.py B3.4):
- Hit + defense + AP + Brutalny + Precyzyjny + Osłona pkt 19.
- Bez Furia/Impet/Podwójny/Przebijająca/Zabójczy/Niewrazliwy/Delikatny (
  dorzucane wraz z B3.5+ effects.py integration).
- Single ranged attack — bez melee (analogiczna formuła, dodamy gdy potrzeba).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from app.services.engine.combat import (
    ABILITY_BRUTALNY,
    ABILITY_PODWOJNY,
    ABILITY_PRECYZYJNY,
    WeaponProfile,
    compute_attack_modifiers,
    compute_cover,
    compute_defense_modifier,
    effective_attack_quality,
)
from app.services.engine.los import LoSState, check_los
from app.services.engine.state import (
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)


# ---------------------------------------------------------------------------
# DamageDistribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DamageDistribution:
    """Distribution liczby ran z pojedynczego ataku.

    `pmf[k]` = prawdopodobieństwo dokładnie k ran zadanych do defendera.
    `mean` = oczekiwana liczba ran (`Σ k * pmf[k]`). `models_at_risk` =
    liczba modeli, których pokonanie jest analityką sprawdzane (typowo
    `defender.models_alive`); `toughness_per_model` z defendera.
    """

    pmf: dict[int, float]
    mean: float
    models_at_risk: int
    toughness_per_model: int

    def p_at_least(self, n: int) -> float:
        """P(wounds ≥ n)."""
        return sum(p for k, p in self.pmf.items() if k >= n)

    def p_kill(self) -> float:
        """P(co najmniej 1 model pokonany) = P(wounds ≥ toughness_per_model)."""
        return self.p_at_least(self.toughness_per_model)

    def p_full_kill(self) -> float:
        """P(cały oddział pokonany) = P(wounds ≥ toughness × models)."""
        return self.p_at_least(self.toughness_per_model * self.models_at_risk)

    def expected_models_killed(self) -> float:
        """E[liczba pokonanych modeli] = Σ floor(wounds / toughness) capped at models_at_risk."""
        total = 0.0
        for k, p in self.pmf.items():
            killed = min(k // self.toughness_per_model, self.models_at_risk)
            total += killed * p
        return total


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _success_probability(
    threshold: int,
    modifier: int = 0,
    *,
    natural_6_auto_success: bool = True,
    natural_1_auto_failure: bool = True,
) -> float:
    """Prawdopodobieństwo sukcesu pojedynczego rzutu k6 per `SZOP_Rozjemca.md pkt 1`.

    Effective threshold = `max(2, threshold - modifier)` (pkt 1.d clamp).

    Reguły:
    - Natural 1 (1/6) → fail (pkt 1.c) jeśli `natural_1_auto_failure=True`
    - Natural 6 (1/6) → success (pkt 1.b) jeśli `natural_6_auto_success=True`
    - Pozostałe (2-5, 4/6): success iff value ≥ effective_threshold
    """
    eff = max(2, threshold - modifier)
    p = 0.0
    for roll in range(1, 7):
        if roll == 1 and natural_1_auto_failure:
            continue
        if roll == 6 and natural_6_auto_success:
            p += 1 / 6
            continue
        if roll >= eff:
            p += 1 / 6
    return p


def _binomial_pmf(n: int, p: float) -> dict[int, float]:
    """PMF dla X ~ Binomial(n, p): `P(X=k) = C(n,k) p^k (1-p)^(n-k)`.

    Returns `{k: P(X=k)}` for k=0..n; pomijamy entries z prob ~ 0 (≤ 1e-15)
    żeby pmf był spartan.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    if not 0 <= p <= 1:
        raise ValueError(f"p must be in [0, 1], got {p}")
    if n == 0:
        return {0: 1.0}
    pmf: dict[int, float] = {}
    q = 1.0 - p
    for k in range(n + 1):
        coeff = math.comb(n, k)
        prob = coeff * (p**k) * (q ** (n - k))
        if prob > 1e-15:
            pmf[k] = prob
    return pmf


# ---------------------------------------------------------------------------
# Public API: expected_damage, would_see
# ---------------------------------------------------------------------------


def expected_damage(
    attacker: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
) -> DamageDistribution:
    """Analityczna estymacja ran zadawanych przez Ostrzał (pkt 17 + 19).

    Equivalent `combat.resolve_ranged_attack` bez RNG. Liczy:
    1. `n_attacks = attacker.models_alive * weapon.attacks`.
    2. `p_hit` = `_success_probability(attacker.quality, attack_modifier)` z
       uwzględnieniem Osłony (pkt 19) — `compute_attack_modifiers`.
    3. `p_failed_defense` = `1 - _success_probability(defender.defense, defense_modifier,
       natural_6_auto_success=not Brutalny)` z AP + bonus osłony.
    4. `p_wound = p_hit * p_failed_defense`.
    5. Wounds ~ Binomial(n_attacks, p_wound). PMF + mean liczone analitycznie.

    Args:
        attacker, defender: bloby.
        weapon: profil broni atakującego.
        terrain: dla Osłony pkt 19 (LoS check, Obronny).

    Returns:
        `DamageDistribution(pmf, mean, models_at_risk, toughness_per_model)`.

    MVP scope: AP / Brutalny / Precyzyjny — zgodne z combat.py. Pozostałe
    weapon abilities (Furia/Impet/etc.) ignorowane (dorzucane w przyszłych
    iteracjach wraz z combat.py rozszerzeniem).
    """
    from app.services.engine.effects import (
        EffectContext,
        aggregate_attack_modifier,
        aggregate_defense_modifier,
    )

    terrain_list = list(terrain)
    has_cover = compute_cover(attacker, defender, terrain_list)
    attack_quality = effective_attack_quality(weapon, attacker)
    attack_modifier, extra_defense_bonus = compute_attack_modifiers(
        attacker_quality=attack_quality, has_cover=has_cover
    )
    defense_modifier = compute_defense_modifier(
        weapon_ap=weapon.ap, extra_defense_bonus=extra_defense_bonus
    )

    # Passive modifiers — consistency z combat.py
    attack_modifier += aggregate_attack_modifier(EffectContext(blob=attacker, weapon=weapon))
    defense_modifier += aggregate_defense_modifier(EffectContext(blob=defender, weapon=weapon))

    is_brutalny = ABILITY_BRUTALNY in weapon.weapon_abilities

    p_hit = _success_probability(
        threshold=attack_quality, modifier=attack_modifier
    )
    # Podwójny (id 66): natural 6 trafienia dodaje +1 hit (E[extra hits per die] = 1/6).
    # Mean approximation — pmf shape jest multinomial, ale mean parity ±3σ OK.
    extra_hit_rate = 1 / 6 if ABILITY_PODWOJNY in weapon.weapon_abilities else 0
    effective_p_hit = min(1.0, p_hit + extra_hit_rate)
    p_save = _success_probability(
        threshold=defender.defense,
        modifier=defense_modifier,
        natural_6_auto_success=not is_brutalny,
    )
    p_wound_per_attack = effective_p_hit * (1.0 - p_save)

    n_attacks = attacker.models_alive * weapon.attacks
    if n_attacks == 0 or p_wound_per_attack == 0:
        return DamageDistribution(
            pmf={0: 1.0},
            mean=0.0,
            models_at_risk=defender.models_alive,
            toughness_per_model=defender.toughness_per_model,
        )

    pmf = _binomial_pmf(n_attacks, p_wound_per_attack)
    mean = sum(k * p for k, p in pmf.items())
    return DamageDistribution(
        pmf=pmf,
        mean=mean,
        models_at_risk=defender.models_alive,
        toughness_per_model=defender.toughness_per_model,
    )


def would_see(
    attacker_position: Position,
    attacker_radius: float,
    target: UnitBlob,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
) -> LoSState:
    """Hipotetyczny `check_los` dla `attacker_position` (bez modyfikacji state).

    Używany przez heuristic players (Strumień D) i prediction-time queries: "co
    by widział oddział, gdyby przesunął się do X?". Bez generowania faktycznego
    `MoveExecuted` event.

    Implementacja: tworzymy ephemeral `UnitBlob` z attacker_position + radius
    (pozostałe pola placeholder) i delegujemy do `los.check_los`.
    """
    ephemeral = UnitBlob(
        id=-1,
        owner_player=0,
        position=attacker_position,
        radius_inches=attacker_radius,
        models_alive=1,
        toughness_per_model=1,
    )
    return check_los(ephemeral, target, terrain)
