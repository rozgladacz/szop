"""D — ClaudeV3Player: szkielet `PriorityPlayer` + wybór celu „dobij/koncentruj".

Diagnoza (benchmark 2026-06-17): rodzina value-max (greedy/claude_v1/claude_v2, też
depth-2 minimax) przegrywa z `priority`/`priority3`, bo SIŁA priorytetowców leży w
STRUKTURZE POLITYKI (najpierw walcz: Ostrzał→Szarża, potem zajmij cele), nie w
głębokości lookaheadu. Zamiast walczyć z tą polityką, ClaudeV3 ją DZIEDZICZY i naprawia
udokumentowaną słabość WYBORU CELU:

- `PriorityPlayer` strzela **najbliższego** wroga — rozprasza ogień, nie dobija rannych.
- `PriorityV3Player` waży cel `x(4-x)` — symetryczne wokół x=2, **nie premiuje dobijania**.

ClaudeV3 zostawia CAŁY szkielet `PriorityPlayer` (selekcja oddziału, kolejność 1–7, ruch
na cele, anty-klastrowanie) i nadpisuje TYLKO `_act`, zmieniając krok 2/3 z „najbliższy"
na **koncentrację ognia, by DOBIĆ** (usuń aktywację wroga, pkt 5.f): cel = max
`mean + p_full_kill + expected_kills`. Wycena przez `prediction.expected_damage` →
automatycznie świadoma zdolności (AP/Brutalny/Precyzyjny/Cierpliwy/…). Depth-1, koszt
rzędu `priority` (~2×; kilka `expected_damage` na aktywację).

**Wynik (3 fixtury, 120 gier/matchup):** bije priority2 (68%), greedy (88%), claude_v1;
~remis z claude_v2. **Nie bije priority (~42%) ani priority3 (~33%)** — udokumentowany
sufit: „strzel najbliższego" to mocne lokalne optimum (proximity-anchoring i odcięcie
od celów sprawdzone, nie pomogły). Najtańszy z botów Claude i najbliżej priority.
"""

from __future__ import annotations

from app.services.agents.base import _can_charge, _can_shoot, enemy_units
from app.services.agents.priority_player import PriorityPlayer
from app.services.engine.actions import (
    Action,
    ChargeAction,
    DefendAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.prediction import expected_damage
from app.services.engine.state import BattleState, UnitBlob, effective_move_inches
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY

#: Waga oczekiwanych ran (HP fine-grained) — skuteczność strzału.
MEAN_W: float = 8.0
#: Waga DOBIJANIA: p(pełne wymiecenie) — usuwa aktywację + kontestera (pkt 5.f).
FINISH_W: float = 30.0
#: Waga oczekiwanych pokonanych modeli — koncentracja na rannych/słabych.
KILL_W: float = 14.0


class ClaudeV3Player(PriorityPlayer):
    """`PriorityPlayer` z wyborem celu „dobij/koncentruj" (ability-aware), depth-1."""

    def _target_value(self, attacker: UnitBlob, target: UnitBlob, weapon, terrain: tuple) -> float:
        """Wartość ataku: obrażenia + dobijanie + koncentracja na rannych.

        `expected_damage` reużywa `combat.py` → uwzględnia zdolności broni/obrony bez
        hardkodowania slugów. Dobijanie (`p_full_kill`) + `expected_models_killed`
        kierują ogień na cele najbliższe wymiecenia (usunięcie aktywacji wroga).
        """
        d = expected_damage(attacker, target, weapon, terrain)
        return (
            d.mean * MEAN_W
            + d.p_full_kill() * FINISH_W
            + d.expected_models_killed() * KILL_W
        )

    def _best_shoot(self, unit: UnitBlob, enemies: list[UnitBlob], terrain: tuple) -> ShootAction | None:
        best: ShootAction | None = None
        best_val = float("-inf")
        for enemy in enemies:
            for weapon in unit.ranged_weapons:
                if _can_shoot(unit, enemy, weapon, terrain):
                    val = self._target_value(unit, enemy, weapon, terrain)
                    if val > best_val:  # strict > → stabilny tie-break (kolejność enemies/weapons)
                        best_val = val
                        best = ShootAction(unit_id=unit.id, target_id=enemy.id, weapon=weapon)
        return best

    def _best_charge(self, unit: UnitBlob, enemies: list[UnitBlob], move: float) -> ChargeAction | None:
        if not unit.melee_weapons:
            return None
        weapon = unit.melee_weapons[0]
        best: ChargeAction | None = None
        best_val = float("-inf")
        # Osłona (pkt 19) tylko Ostrzał — Szarża wyceniana z pustym terenem (spójnie z silnikiem melee).
        for enemy in enemies:
            if _can_charge(unit, enemy, move):
                val = self._target_value(unit, enemy, weapon, ())
                if val > best_val:
                    best_val = val
                    best = ChargeAction(unit_id=unit.id, target_id=enemy.id, weapon=weapon)
        return best

    def _act(
        self,
        state: BattleState,
        perspective: int,
        unit: UnitBlob,
        actions_taken: tuple[Action, ...] = (),
    ) -> Action:
        """Priorytet `PriorityPlayer` 1–7, ale krok 2/3 = cel „dobij/koncentruj".

        Kroki 1 (Wyczerpany), 4 (Przyszpilony) jak rodzic; 5–7 (ruch na cele/wroga)
        delegowane do `PriorityPlayer._act` (reuse, zero duplikacji) po oznaczeniu
        Ostrzału/Szarży jako wykorzystanych.
        """
        move = effective_move_inches(unit)  # pkt 15.a ± Szybki/Wolny (zdolność 33)
        enemies = enemy_units(state, perspective)
        shoot_used = any(isinstance(a, ShootAction) for a in actions_taken)
        charge_used = any(isinstance(a, ChargeAction) for a in actions_taken)

        if STATUS_WYCZERPANY in unit.status_flags:  # 1.
            return SpecialAction(unit_id=unit.id, ability_slug="discard_exhausted")
        if not shoot_used:  # 2. Ostrzał — najlepszy cel (dobij), nie najbliższy.
            shoot = self._best_shoot(unit, enemies, state.terrain)
            if shoot is not None:
                return shoot
        if not charge_used:  # 3. Szarża — najlepszy cel wręcz.
            charge = self._best_charge(unit, enemies, move)
            if charge is not None:
                return charge
        if STATUS_PRZYSZPILONY in unit.status_flags:  # 4.
            return DefendAction(unit_id=unit.id)
        # 5–7 + bezpiecznik: identyczne z PriorityPlayer (ruch na cele/wroga/Obrona).
        return super()._act(
            state, perspective, unit,
            actions_taken + (ShootAction(unit.id, -1, None), ChargeAction(unit.id, -1, None)),
        )
