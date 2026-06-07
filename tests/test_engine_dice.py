"""B3.1 — testy `app/services/engine/dice.py`.

Pokrywa: reproducibility (same seed → same sequence), distribution
(chi-square 10k rolls), threshold clamp do 2+ (pkt 1.d), natural 1/6 rules
(pkt 1.b/c), modifier addytywny, edge cases (count=0, negative).
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.services.engine.dice import DeterministicDice, RollResult


# ---------------------------------------------------------------------------
# Reproducibility — same seed → same sequence
# ---------------------------------------------------------------------------


def test_same_seed_same_sequence():
    d1 = DeterministicDice(seed=42)
    d2 = DeterministicDice(seed=42)
    for _ in range(10):
        assert d1.roll_d6(5) == d2.roll_d6(5)


def test_different_seeds_different_sequence():
    d1 = DeterministicDice(seed=42)
    d2 = DeterministicDice(seed=43)
    # Extremely unlikely (1 in 6^20) że pierwsze 20 będą identyczne.
    assert d1.roll_d6(20) != d2.roll_d6(20)


def test_seed_property_preserved():
    dice = DeterministicDice(seed=123)
    assert dice.seed == 123
    dice.roll_d6(5)
    assert dice.seed == 123  # seed nie zmienia się po rzutach


# ---------------------------------------------------------------------------
# Distribution — chi-square dla 10k rolls
# ---------------------------------------------------------------------------


def test_distribution_uniform_on_10k_rolls():
    """Chi-square test dla d6 — każda wartość 1-6 ma prawdopodobieństwo 1/6.

    Próg p > 0.001 (bardzo luźny, żeby false-positives były rzadkie).
    Dla 10000 rolls i 6 bucketów, expected = 1666.67 per bucket.
    Chi-square statistic = sum((observed - expected)^2 / expected).
    Critical value for df=5 at p=0.001 ≈ 20.515.
    """
    dice = DeterministicDice(seed=2026)
    rolls = dice.roll_d6(10000)
    counts = Counter(rolls)
    expected = 10000 / 6
    chi_square = sum((counts[i] - expected) ** 2 / expected for i in range(1, 7))
    assert chi_square < 20.515, f"Chi-square {chi_square} > 20.515 (df=5, p=0.001)"


# ---------------------------------------------------------------------------
# roll_d6 — basic
# ---------------------------------------------------------------------------


def test_roll_d6_zero_count():
    dice = DeterministicDice(seed=1)
    assert dice.roll_d6(0) == ()


def test_roll_d6_negative_raises():
    dice = DeterministicDice(seed=1)
    with pytest.raises(ValueError):
        dice.roll_d6(-1)


def test_roll_d6_results_in_range_1_6():
    dice = DeterministicDice(seed=2026)
    rolls = dice.roll_d6(1000)
    assert all(1 <= r <= 6 for r in rolls)


def test_roll_d6_count_matches_request():
    dice = DeterministicDice(seed=1)
    rolls = dice.roll_d6(7)
    assert len(rolls) == 7


# ---------------------------------------------------------------------------
# roll_with_threshold — basic semantics (SZOP_Rozjemca pkt 1)
# ---------------------------------------------------------------------------


def test_threshold_basic_4_plus():
    """Threshold 4+ bez modifiera: 4/5/6 = sukces, 1/2/3 = porażka."""
    dice = DeterministicDice(seed=42)
    # Rzuć dużo razy, porównaj z expected ratio.
    result = dice.roll_with_threshold(count=10000, threshold=4)
    # 1=fail (1/6), 2=fail (1/6), 3=fail (1/6), 4=success (1/6), 5=success (1/6), 6=auto-success (1/6)
    # = 3/6 = 0.5 success rate
    success_rate = result.successes / 10000
    assert 0.47 < success_rate < 0.53, f"Success rate {success_rate} far from 0.5"


def test_natural_1_always_fails():
    """Pkt 1.c — naturalna 1 zawsze porażka, nawet z modifierem +5."""
    # Wymusimy że co najmniej kilka 1-tek wyjdzie — duży count.
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=1000, threshold=2, modifier=10)
    # Effective threshold = max(2, 2-10) = 2; bez 1.c wszystko (2+) by było sukcesem.
    # Z 1.c: ~1/6 rolls = 1 = fail. Spodziewamy się ~833 sukcesów (~5/6).
    success_rate = result.successes / 1000
    assert 0.80 < success_rate < 0.87, (
        f"Success rate {success_rate} suggests 1.c is broken"
    )


def test_natural_6_auto_success_default():
    """Pkt 1.b — naturalna 6 zawsze sukces, nawet przy threshold 7+ (cap=6)."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=600, threshold=10)
    # Bez modifiera, effective threshold = max(2, 10-0) = 10; nikt by nie trafił.
    # Z 1.b: ~1/6 rolls = 6 = auto-sukces.
    success_rate = result.successes / 600
    assert 0.12 < success_rate < 0.21, (
        f"Success rate {success_rate} suggests 1.b is broken"
    )


def test_natural_6_no_auto_success_brutalny_case():
    """Brutalny (broń, pkt id 57) wyłącza natural 6 auto-success w testach obrony."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(
        count=600, threshold=10, natural_6_auto_success=False
    )
    # Effective threshold = 10; żadna kostka 1-6 nie spełnia. Wszystko fail.
    assert result.successes == 0


def test_natural_6_no_auto_success_delikatny_case():
    """Delikatny (passive, id 4) wyłącza natural 6 auto-success w testach obrony."""
    dice = DeterministicDice(seed=42)
    # Threshold 4+ z Delikatny: 4/5 = sukces (naturalnie), 6 = porażka? Nie — 6 ≥ 4
    # więc 6 nadal jest sukcesem przez normalną zasadę, ale NIE jako auto.
    # Test: threshold 7+ z Delikatny: 6 nie jest już auto-sukcesem, więc 0 sukcesów.
    result = dice.roll_with_threshold(
        count=600, threshold=7, natural_6_auto_success=False
    )
    assert result.successes == 0


def test_natural_6_normal_success_when_meets_threshold():
    """Z natural_6_auto_success=False, 6 nadal jest sukcesem gdy 6 ≥ effective_threshold."""
    dice = DeterministicDice(seed=42)
    # Threshold 4+ z Delikatny: 4/5/6 = sukces, 1/2/3 = fail.
    # Powinno być ~0.5 success rate (3/6 = 0.5, ale 1 to auto-fail bo 1.c).
    result = dice.roll_with_threshold(
        count=10000, threshold=4, natural_6_auto_success=False
    )
    success_rate = result.successes / 10000
    # 4,5,6 = success → 3/6 (1 jest excluded przez 1.c), faktycznie 3/6 = 0.5
    assert 0.47 < success_rate < 0.53


# ---------------------------------------------------------------------------
# roll_with_threshold — modifier (pkt 1.d)
# ---------------------------------------------------------------------------


def test_modifier_positive_lowers_effective_threshold():
    """Modifier +1 obniża effective threshold o 1."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=1, threshold=4, modifier=1)
    assert result.effective_threshold == 3


def test_modifier_negative_raises_effective_threshold():
    """Modifier −1 podnosi effective threshold o 1."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=1, threshold=4, modifier=-1)
    assert result.effective_threshold == 5


def test_modifier_clamped_to_minimum_2():
    """Pkt 1.d — effective threshold clamped do ≥ 2."""
    dice = DeterministicDice(seed=42)
    # threshold 3, modifier +5 → effective by było -2, clamp do 2.
    result = dice.roll_with_threshold(count=1, threshold=3, modifier=5)
    assert result.effective_threshold == 2


def test_modifier_zero_default():
    """Default modifier=0."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=1, threshold=4)
    assert result.modifier == 0
    assert result.effective_threshold == 4


# ---------------------------------------------------------------------------
# roll_with_threshold — edge cases & RollResult
# ---------------------------------------------------------------------------


def test_threshold_zero_count_returns_zero_successes():
    dice = DeterministicDice(seed=1)
    result = dice.roll_with_threshold(count=0, threshold=4)
    assert result.successes == 0
    assert result.rolls == ()


def test_threshold_negative_count_raises():
    dice = DeterministicDice(seed=1)
    with pytest.raises(ValueError):
        dice.roll_with_threshold(count=-1, threshold=4)


def test_roll_result_is_frozen():
    """RollResult jest frozen dataclass."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=3, threshold=4)
    with pytest.raises(Exception):  # FrozenInstanceError
        result.successes = 99  # type: ignore[misc]


def test_roll_result_preserves_natural_rolls():
    """`rolls` w RollResult ma natural values (bez modifiera, bez interpretacji)."""
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=5, threshold=4, modifier=2)
    assert len(result.rolls) == 5
    assert all(1 <= r <= 6 for r in result.rolls)


def test_roll_result_base_threshold_preserved():
    dice = DeterministicDice(seed=42)
    result = dice.roll_with_threshold(count=1, threshold=4, modifier=2)
    assert result.base_threshold == 4
    assert result.modifier == 2
    assert result.effective_threshold == 2  # 4 - 2


# ---------------------------------------------------------------------------
# Reproducibility — replay determinism (ADR-0010 + ADR-0012)
# ---------------------------------------------------------------------------


def test_replay_with_same_seed_gives_same_result():
    """Two DeterministicDice z tym samym seedem dają identyczny sequence rzutów."""
    seed = 12345
    d1 = DeterministicDice(seed=seed)
    d2 = DeterministicDice(seed=seed)
    r1 = d1.roll_with_threshold(count=10, threshold=4, modifier=1)
    r2 = d2.roll_with_threshold(count=10, threshold=4, modifier=1)
    assert r1 == r2
