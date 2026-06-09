"""D1 — GreedyPlayer: maksymalizuje natychmiastową wartość 1 akcji (depth-1).

Ocena per akcja (wszystko w jednej skali "spodziewany zysk"):
- **Ostrzał / Szarża** — `prediction.expected_damage(...).mean × WOUND_VALUE`
  (oczekiwane rany; analityka bez RNG, ADR-0044). Szarża (wręcz) używa tej samej
  formuły jako przybliżenia — `expected_damage` jest dystansowe (pkt 17 wspólne
  dla Ostrzału i wręcz w MVP combat), melee-specyficzne efekty pominięte (ADR-0031).
- **Manewr** — Δ`evaluate_state` (poprawa pozycji: bliskość celów, pkt 5).
- **Obrona** — stała `DEFEND_VALUE` (lepsza niż nic, poniżej skutecznego ataku).
- **Odrzuć Wyczerpany** — stała `DISCARD_VALUE` (zdjęcie Wyczerpany, pkt 22.a).

Argmax z deterministycznym tie-break (pierwszy w stabilnej kolejności
`legal_actions` wygrywa). Czysta funkcja decyzji (RNG tylko w combat przy
faktycznym `apply`, nie tutaj).
"""

from __future__ import annotations

import math
from dataclasses import replace

from app.services.agents.base import Player, legal_actions
from app.services.agents.policy_eval import evaluate_state
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


class GreedyPlayer(Player):
    """Bot maksymalizujący wartość pojedynczej akcji (depth-1, bez lookahead)."""

    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        base_eval = evaluate_state(state, perspective)
        best_action: Action | None = None
        best_score = -math.inf
        for action in candidates:
            score = self._score(state, perspective, action, base_eval)
            if score > best_score:  # strict > → stabilny tie-break (pierwszy wygrywa)
                best_score = score
                best_action = action
        return best_action

    def _score(
        self,
        state: BattleState,
        perspective: int,
        action: Action,
        base_eval: float,
    ) -> float:
        if isinstance(action, (ShootAction, ChargeAction)):
            return self._attack_score(state, action)
        if isinstance(action, ManeuverAction):
            return self._maneuver_score(state, perspective, action, base_eval)
        if isinstance(action, DefendAction):
            return DEFEND_VALUE
        if isinstance(action, SpecialAction):
            return DISCARD_VALUE
        return 0.0

    def _attack_score(
        self, state: BattleState, action: ShootAction | ChargeAction
    ) -> float:
        attacker = _blob_by_id(state, action.unit_id)
        defender = _blob_by_id(state, action.target_id)
        if attacker is None or defender is None:
            return 0.0
        dist = expected_damage(attacker, defender, action.weapon, state.terrain)
        return dist.mean * WOUND_VALUE

    def _maneuver_score(
        self,
        state: BattleState,
        perspective: int,
        action: ManeuverAction,
        base_eval: float,
    ) -> float:
        moved_blobs = tuple(
            replace(b, position=action.target_position)
            if b.id == action.unit_id
            else b
            for b in state.blobs
        )
        hypothetical = replace(state, blobs=moved_blobs)
        return evaluate_state(hypothetical, perspective) - base_eval
