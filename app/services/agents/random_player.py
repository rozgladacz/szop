"""D1 — RandomPlayer: losuje uniform z legalnych akcji (baseline bot).

Deterministyczny per seed (`random.Random`) — replay-safe, jak `DeterministicDice`
(ADR-0012). Służy jako baseline w balansie (D2) i jako sanity-opponent dla
GreedyPlayer.
"""

from __future__ import annotations

import random

from app.services.agents.base import (
    Player,
    legal_actions,
    legal_followup_actions,
)
from app.services.engine.actions import Action
from app.services.engine.state import BattleState


class RandomPlayer(Player):
    """Bot wybierający losowo spośród `legal_actions`.

    `seed` zapewnia determinizm: ten sam seed + ta sama sekwencja stanów →
    te same akcje. Brak legalnych akcji → None.
    """

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        return self._rng.choice(candidates)

    def continue_activation(
        self, state, perspective, unit_id, actions_taken
    ) -> Action | None:
        """2. akcja (pkt 11.b.iv): losowo spośród legalnych kontynuacji lub stop
        (None w puli) — zachowuje losowy charakter baseline'u."""
        followups = legal_followup_actions(state, perspective, unit_id, actions_taken)
        return self._rng.choice([*followups, None])
