"""D1 — GreedyPlayer: maksymalizuje natychmiastową wartość 1 akcji (depth-1).

Ocena per akcja (wszystko w jednej skali "spodziewany zysk"):
- **Ostrzał / Szarża** — `expected_damage(...).mean × WOUND_VALUE` (oczekiwane
  rany, ADR-0044) **+** Δ wartości celów (`objective_balance_with_control`) na
  hipotetycznym stanie z wymiecionymi modelami defendera. Drugi człon premiuje
  atak czyszczący wroga z celu (pkt 5.d kontrola → 5.f wygrana); pierwszy zostaje
  fine-grained dla obrażeń sub-kill. Szarża (wręcz) używa formuły `expected_damage`
  jako przybliżenia (melee-specyficzne efekty pominięte, ADR-0031).
- **Manewr** — Δ`objective_balance_with_control` (przejęcie/utrata celu, pkt 5.d;
  ruch nie zmienia HP, więc to czysto wartość celów). Z przeliczeniem kontroli
  ruch na cel jest wart `OBJECTIVE_WEIGHT`, nie tylko proximity.
- **Obrona** — stała `DEFEND_VALUE` (lepsza niż nic, poniżej skutecznego ataku).
- **Odrzuć Wyczerpany** — stała `DISCARD_VALUE` (zdjęcie Wyczerpany, pkt 22.a).

Argmax z deterministycznym tie-break (pierwszy w stabilnej kolejności
`legal_actions` wygrywa). Czysta funkcja decyzji (RNG tylko w combat przy
faktycznym `apply`, nie tutaj).

Wspólna waluta celów (`objective_balance_with_control`, pkt 5.d/5.f) jest
kluczowa: bez niej atak (skala obrażeń) deklasował manewr na cel (skala proximity)
i bot przegrywał mimo zadawania ran — wygrywa kontrola celów, nie obrażenia.
"""

from __future__ import annotations

import math
from dataclasses import replace

from app.services.agents.base import Player, legal_actions
from app.services.agents.policy_eval import objective_balance_with_control
from app.services.engine.actions import (
    Action,
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.prediction import expected_damage
from app.services.engine.state import BattleState, UnitBlob

#: Wartość 1 oczekiwanej rany w punktach oceny (skaluje atak vs pozycję).
WOUND_VALUE: float = 8.0
#: Wartość akcji Obrony (Ufortyfikowany) — niska, defensywny fallback.
DEFEND_VALUE: float = 1.0
#: Wartość zdjęcia stanu Wyczerpany (Odrzuć Wyczerpany, pkt 22.a).
DISCARD_VALUE: float = 3.0


def _blob_by_id(state: BattleState, unit_id: int) -> UnitBlob | None:
    return next((b for b in state.blobs if b.id == unit_id), None)


def _replace_blob(state: BattleState, blob_id: int, **updates) -> BattleState:
    """Hipotetyczny stan z jednym blobem podmienionym (`dataclasses.replace`)."""
    new_blobs = tuple(
        replace(b, **updates) if b.id == blob_id else b for b in state.blobs
    )
    return replace(state, blobs=new_blobs)


def _apply_expected_kills(
    state: BattleState, defender_id: int, kills: int
) -> BattleState:
    """Hipotetyczny stan po ataku: defender traci `kills` modeli (clamp ≥0).

    Tylko `models_alive` (kontrola celu pkt 5.d zależy od models_alive>0 +
    pozycji); pozostałe pola ran nietknięte — to przybliżenie do oceny, nie
    rozliczenie combat. `kills <= 0` → stan bez zmian (brak realokacji).
    """
    if kills <= 0:
        return state
    defender = _blob_by_id(state, defender_id)
    if defender is None:
        return state
    return _replace_blob(
        state, defender_id, models_alive=max(0, defender.models_alive - kills)
    )


class GreedyPlayer(Player):
    """Bot maksymalizujący wartość pojedynczej akcji (depth-1, bez lookahead)."""

    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        # Bazowa wartość celów (kontrola przeliczona z pozycji, pkt 5.d) — wspólny
        # punkt odniesienia dla Δ atak/manewr.
        base_objective = objective_balance_with_control(state, perspective)
        best_action: Action | None = None
        best_score = -math.inf
        for action in candidates:
            score = self._score(state, perspective, action, base_objective)
            if score > best_score:  # strict > → stabilny tie-break (pierwszy wygrywa)
                best_score = score
                best_action = action
        return best_action

    def _score(
        self,
        state: BattleState,
        perspective: int,
        action: Action,
        base_objective: float,
    ) -> float:
        if isinstance(action, (ShootAction, ChargeAction)):
            return self._attack_score(state, perspective, action, base_objective)
        if isinstance(action, ManeuverAction):
            return self._maneuver_score(state, perspective, action, base_objective)
        if isinstance(action, DefendAction):
            return DEFEND_VALUE
        if isinstance(action, SpecialAction):
            return DISCARD_VALUE
        return 0.0

    def _attack_score(
        self,
        state: BattleState,
        perspective: int,
        action: ShootAction | ChargeAction,
        base_objective: float,
    ) -> float:
        attacker = _blob_by_id(state, action.unit_id)
        defender = _blob_by_id(state, action.target_id)
        if attacker is None or defender is None:
            return 0.0
        dist = expected_damage(attacker, defender, action.weapon, state.terrain)
        # Człon HP (fine-grained, sub-kill) + zmiana wartości celów gdy atak
        # praktycznie wymiata defendera z 3″ celu (pkt 5.d). Bez double-count:
        # obrażenia = HP, objective_balance = tylko cele.
        expected_kills = round(dist.expected_models_killed())
        hypothetical = _apply_expected_kills(state, defender.id, expected_kills)
        objective_delta = (
            objective_balance_with_control(hypothetical, perspective) - base_objective
        )
        return dist.mean * WOUND_VALUE + objective_delta

    def _maneuver_score(
        self,
        state: BattleState,
        perspective: int,
        action: ManeuverAction,
        base_objective: float,
    ) -> float:
        hypothetical = _replace_blob(
            state, action.unit_id, position=action.target_position
        )
        # Ruch nie zmienia HP → Δ to czysto wartość celów (z przeliczoną kontrolą).
        return (
            objective_balance_with_control(hypothetical, perspective) - base_objective
        )
