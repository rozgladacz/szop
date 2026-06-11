"""Strumień D — gracze heurystyczni (boty) nad publicznym API silnika (B3.9).

Public API:
- `Player` — bazowy ABC (`choose_action(state, perspective) -> Action | None`).
- `legal_actions(state, perspective)` — enumerator kandydatów na akcję.
- `RandomPlayer(seed)` — baseline, losuje uniform.
- `GreedyPlayer()` — depth-1 maksymalizacja wartości akcji.
- `PriorityPlayer()` — pół-deterministyczny (prosty): selekcja „najbliżej wroga" + priorytet 1–7.
- `PriorityV2Player()` — rozbudowany: selekcja po stanie wroga + ruch przechwytujący + wybór celu przez prediction.
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
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.agents.random_player import RandomPlayer

__all__ = [
    "Player",
    "legal_actions",
    "RandomPlayer",
    "GreedyPlayer",
    "PriorityPlayer",
    "PriorityV2Player",
    "PriorityV3Player",
    "evaluate_state",
    "MatchResult",
    "run_match",
    "simulate_from_rosters",
]
