"""B3.1 — Deterministic dice (ADR-0012).

`DeterministicDice` wrapuje `random.Random(seed)` — pełna reproducibility dla
event-sourced replay. Każda bitwa ma `rng_seed` (przyszła ORM, B2), z którego
inicjalizujemy `DeterministicDice` przed pierwszym rzutem.

Wszystkie testy z `SZOP_Rozjemca.md pkt 1` (Test(X), naturalne 1/6, modyfikatory):
- `roll_d6(count)` — niskopoziomowy RNG bez interpretacji
- `roll_with_threshold(count, threshold, modifier=0, ...)` — pełna reguła testu:
  - Effective threshold = clamp(threshold − modifier, ≥ 2) (pkt 1.d)
  - Natural 1 → fail (pkt 1.c, niezbywalne)
  - Natural 6 → success (pkt 1.b, znoszone przez `natural_6_auto_success=False` dla Brutalny/Delikatny)
  - Pozostałe: success iff natural ≥ effective_threshold

Logika konkretnych zdolności (Niewrazliwy id 17 — natural 5 = sukces, Furia id 7
— natural 6 → extra trafienie) **żyje w `combat.py`**, nie tu. `dice.py`
zwraca pełen `RollResult` z natural rolls, combat.py inspekcjonuje per kostkę.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RollResult:
    """Wynik rzutu z pełną widocznością na każdą kostkę.

    `rolls` to natural values (1-6) — bez modifierów, bez interpretacji
    natural_1/6. Pozwala combat.py inspekcjonować per kostkę dla Furia/Podwójny
    (natural 6 → extra trafienie) lub Niewrazliwy (natural 5 → sukces).

    `successes` to wynik podstawowej reguły z pkt 1; combat.py może dodać/odjąć
    sukcesy w post-processing (np. dla zdolności modyfikujących reguły kostki).
    """

    rolls: tuple[int, ...]
    successes: int
    effective_threshold: int
    base_threshold: int
    modifier: int


class DeterministicDice:
    """Reproducible RNG wrapper (ADR-0012).

    Inicjalizowany seedem; każdy `roll_*` jest deterministyczny dla danego
    seedu + sekwencji wywołań. Stan RNG zmienia się między rzutami (nie thread-safe;
    pojedynczy battle resolver żyje na jednym threadzie).

    Examples:
        >>> dice = DeterministicDice(seed=42)
        >>> dice.roll_d6(3)
        (..., ..., ...)  # deterministic per seed
    """

    def __init__(self, seed: int) -> None:
        self._seed = int(seed)
        self._rng = random.Random(self._seed)

    @property
    def seed(self) -> int:
        return self._seed

    def roll_d6(self, count: int = 1) -> tuple[int, ...]:
        """Roll `count` k6. Returns natural values (1-6) jako tuple."""
        if count < 0:
            raise ValueError(f"Cannot roll negative count: {count}")
        return tuple(self._rng.randint(1, 6) for _ in range(count))

    def roll_with_threshold(
        self,
        count: int,
        threshold: int,
        *,
        modifier: int = 0,
        natural_6_auto_success: bool = True,
        natural_1_auto_failure: bool = True,
    ) -> RollResult:
        """Rzut `count` k6 vs `threshold` per `SZOP_Rozjemca.md pkt 1`.

        Args:
            count: liczba kostek do rzucenia (≥ 0).
            threshold: bazowa wartość X w `Test(X)` (np. jakość modelu = 4).
            modifier: addytywny modyfikator obniżający trudność (+1 = łatwiej,
                -1 = trudniej). Effective threshold = max(2, threshold − modifier).
            natural_6_auto_success: czy natural 6 jest auto-sukcesem (pkt 1.b).
                False dla broni `Brutalny` (w testach obrony) i dla `Delikatny`
                w testach obrony.
            natural_1_auto_failure: czy natural 1 jest auto-porażką (pkt 1.c).
                Default True; pkt 1.c jest niezbywalne, ale flag istnieje dla
                hipotetycznych przyszłych zdolności.

        Returns:
            RollResult z natural rolls i liczbą sukcesów po regule podstawowej.
        """
        if count < 0:
            raise ValueError(f"Cannot roll negative count: {count}")

        # Effective threshold: clamp do ≥ 2 (pkt 1.d).
        effective_threshold = max(2, threshold - modifier)

        rolls = self.roll_d6(count)
        successes = 0
        for r in rolls:
            if r == 1 and natural_1_auto_failure:
                continue  # auto-fail (pkt 1.c)
            if r == 6 and natural_6_auto_success:
                successes += 1  # auto-success (pkt 1.b)
                continue
            if r >= effective_threshold:
                successes += 1

        return RollResult(
            rolls=rolls,
            successes=successes,
            effective_threshold=effective_threshold,
            base_threshold=threshold,
            modifier=modifier,
        )
