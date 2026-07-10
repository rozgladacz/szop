"""Strumień D — gracze heurystyczni (boty) nad publicznym API silnika (B3.9).

Public API:
- `Player` — bazowy ABC (`choose_action(state, perspective) -> Action | None`).
- `legal_actions(state, perspective)` — enumerator kandydatów na akcję.
- `RandomPlayer(seed)` — baseline, losuje uniform.
- `GreedyPlayer()` — depth-1 maksymalizacja wartości akcji.
- `ClaudeV1Player()` — depth-1 ogólny (value-maximizer): gradient marszu ku celom
  (anty-miopia) + dobijanie (`p_full_kill`) + świadomość zdolności przez `expected_damage`.
  Bije `GreedyPlayer`, ale słabszy od `PriorityPlayer`/v3 (luka strukturalna depth-1, nie wag).
- `ClaudeV2Player(seed, samples)` — depth-2 z modelowaniem przeciwnika (riposta = jedna
  akcja `priority3`, nie maximin) + expectimax-lite + ocena ability-aware (slugi statusów).
  35%/28% vs priority/priority3 (znacznie lepiej niż v1/minimax ~4–8%), wciąż nie bije ich;
  ~100–130× koszt priority. Patrz roadmap D4.
- `ClaudeV3Player()` — dziedziczy szkielet `PriorityPlayer`, nadpisuje TYLKO wybór celu:
  „dobij/koncentruj" (`p_full_kill`+`expected_kills`, ability-aware) zamiast „najbliższy".
  Najlepszy z botów Claude vs priority (~42%/33%) przy ~2× koszcie priority; bije
  priority2/greedy/v1/v2. Wciąż nie bije priority/priority3 (sufit heurystyki). Roadmap D4.
- `PriorityPlayer()` — pół-deterministyczny (prosty): selekcja „najbliżej wroga" + priorytet 1–7.
- `PriorityV2Player()` — rozbudowany: selekcja po stanie wroga + ruch przechwytujący + wybór celu przez prediction.
- `MinimaxPlayer(seed)` — D4: lookahead depth-2 (maximin nad `evaluate_state`).
- `evaluate_state(state, perspective)` — skalarna ocena stanu.
- `run_match(state, players, dice)` / `simulate_from_rosters(...)` — headless
  pętla bitwy (orkiestrator pełnej gry) → `MatchResult`.
- `DeploymentZone` + `grid_positions` / `random_position_in_zone` — D5: strefa
  rozstawienia (pkt 24) + proste strategie pozycjonowania botów (`Player.choose_deployment`).
- `make_player(kind, seed)` + `PLAYER_KINDS` / `PLAYER_SEED_OFFSET` — SSOT
  konstrukcji botów z nazwy dla skryptów, przyszłych routerów B4 i UI.

Konsumenci (roadmap): D2 balance_simulate, D3 exploit_hunt, D4 adversarial UI.
`run_match` to zalążek B5 LocalClient.simulate (pełen B5 z HttpClient poza zakresem).
"""

from app.services.agents.base import Player, legal_actions
from app.services.agents.claude_v1_player import ClaudeV1Player
from app.services.agents.claude_v2_player import ClaudeV2Player
from app.services.agents.claude_v3_player import ClaudeV3Player
from app.services.agents.deployment import (
    DeploymentZone,
    GridDeploymentMixin,
    grid_deployment_position,
    grid_positions,
    random_position_in_zone,
)
from app.services.agents.factory import (
    PLAYER_KINDS,
    PLAYER_SEED_OFFSET,
    make_player,
)
from app.services.agents.greedy_player import GreedyPlayer
from app.services.agents.match import (
    MatchResult,
    run_match,
    simulate_from_rosters,
)
from app.services.agents.minimax_player import MinimaxPlayer
from app.services.agents.policy_eval import evaluate_state
from app.services.agents.registry import (
    BOT_SPECS,
    BotSpec,
    REFERENCE_KINDS,
    USEFUL_KINDS,
    bot_kinds,
    has_tag,
)
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.agents.random_player import RandomPlayer
from app.services.agents.roster_adapter import (
    AdaptResult,
    roster_points,
    roster_to_engine_roster,
)

__all__ = [
    "Player",
    "legal_actions",
    "RandomPlayer",
    "GreedyPlayer",
    "ClaudeV1Player",
    "ClaudeV2Player",
    "ClaudeV3Player",
    "PriorityPlayer",
    "PriorityV2Player",
    "PriorityV3Player",
    "MinimaxPlayer",
    "evaluate_state",
    "MatchResult",
    "run_match",
    "simulate_from_rosters",
    "DeploymentZone",
    "GridDeploymentMixin",
    "grid_positions",
    "grid_deployment_position",
    "random_position_in_zone",
    "AdaptResult",
    "roster_to_engine_roster",
    "roster_points",
    "make_player",
    "PLAYER_KINDS",
    "PLAYER_SEED_OFFSET",
    "BotSpec",
    "BOT_SPECS",
    "USEFUL_KINDS",
    "REFERENCE_KINDS",
    "bot_kinds",
    "has_tag",
]
