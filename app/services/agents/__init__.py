"""Strumień D — gracze heurystyczni (boty) nad publicznym API silnika (B3.9).

Public API:
- `Player` — bazowy ABC (`choose_action(state, perspective) -> Action | None`).
- `legal_actions(state, perspective)` — enumerator kandydatów na akcję.
- `RandomPlayer(seed)` — baseline, losuje uniform.
- `GreedyPlayer()` — depth-1 maksymalizacja wartości akcji.
- `evaluate_state(state, perspective)` — skalarna ocena stanu.

Konsumenci (roadmap): D2 balance_simulate, D3 exploit_hunt, D4 adversarial UI —
wszystkie wymagają jeszcze pętli bitwy (orkiestrator B4/B5 LocalClient).
"""

from app.services.agents.base import Player, legal_actions
from app.services.agents.greedy_player import GreedyPlayer
from app.services.agents.policy_eval import evaluate_state
from app.services.agents.random_player import RandomPlayer

__all__ = [
    "Player",
    "legal_actions",
    "RandomPlayer",
    "GreedyPlayer",
    "evaluate_state",
]
