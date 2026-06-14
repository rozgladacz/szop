"""`szop_client` — klient gry Strumienia B (B5, ADR-0016).

Stabilny seam między konsumentami (C3 `simulate_engagement`, D-stream, UI) a
wewnętrznym silnikiem. Public API:

- `GameClient` — Protocol (kontrakt klienta; `LocalClient`/`HttpClient` wymienne).
- `LocalClient` — implementacja in-process (headless, bez DB/HTTP).
- `SimulationSummary` — wynik batcha `simulate`.

`HttpClient` (po B4 API), DB-backed ładowanie rosterów (po `faza-d-roster-adapter`)
oraz pakowanie `pip install -e` (standalone z HttpClient) — odłożone. Patrz
`docs/handoffs/HANDOFF_faza-b-5-client.md`.
"""

from szop_client.local import LocalClient, UnknownBattleError
from szop_client.protocol import (
    ContinuationFn,
    GameClient,
    PlayerFactory,
    SimulationSummary,
    Terrain,
)

__all__ = [
    "GameClient",
    "LocalClient",
    "UnknownBattleError",
    "SimulationSummary",
    "PlayerFactory",
    "ContinuationFn",
    "Terrain",
]
