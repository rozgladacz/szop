"""Strumień D — gracze heurystyczni (boty) nad publicznym API silnika (B3.9).

Public API:
- `Player` — bazowy ABC (`choose_action(state, perspective) -> Action | None`).
- `legal_actions(state, perspective)` — enumerator kandydatów na akcję.
- `RandomPlayer(seed)` — baseline, losuje uniform.
- `GreedyPlayer()` — depth-1 maksymalizacja wartości akcji.
- `evaluate_state(state, perspective)` — skalarna ocena stanu.
- `run_match(state, players, dice)` / `simulate_from_rosters(...)` — headless
  pętla bitwy (orkiestrator pełnej gry) → `MatchResult`.

Konsumenci (roadmap): D2 balance_simulate, D3 exploit_hunt, D4 adversarial UI.
`run_match` to zalążek B5 LocalClient.simulate (pełen B5 z HttpClient poza zakresem).
"""

from app.services.agents.base import Player, legal_actions
from app.services.agents.greedy_player import GreedyPlayer
from app.services.agents.match import (
    MatchResult,
    run_match,
    simulate_from_rosters,
)
from app.services.agents.policy_eval import evaluate_state
from app.services.agents.random_player import RandomPlayer

__all__ = [
    "Player",
    "legal_actions",
    "RandomPlayer",
    "GreedyPlayer",
    "evaluate_state",
    "MatchResult",
    "run_match",
    "simulate_from_rosters",
]
