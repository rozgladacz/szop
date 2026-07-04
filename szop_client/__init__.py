"""`szop_client` — klient gry Strumienia B (B5, ADR-0016).

Stabilny seam między konsumentami (C3 `simulate_engagement`, D-stream, UI) a
wewnętrznym silnikiem. Public API:

- `GameClient` — Protocol (pełny kontrakt klienta; `LocalClient` go spełnia,
  `HttpClient` rośnie slice'ami wraz z B4 API).
- `LocalClient` — implementacja in-process (headless). Ścieżka engine-dict +
  ścieżka DB (`LocalClient(session, user_id)` + metody `*_roster_ids`,
  most ORM→engine przez `roster_adapter`).
- `HttpClient` — HTTP metadata + polling + sandbox `create_battle` nad B4 battle API.
- `SimulationSummary` — wynik batcha `simulate`.

Pełny `HttpClient` zgodny z całym `GameClient` oraz pakowanie `pip install -e`
— odłożone do kolejnych endpointów B4. Patrz `docs/handoffs/HANDOFF_faza-b-5-client.md`.
"""

from szop_client.http import (
    BattleMetadata,
    HttpClient,
    HttpClientError,
    HttpClientTransportError,
    HttpRequest,
    HttpResponse,
)
from szop_client.local import (
    LocalClient,
    RosterNotFoundError,
    UnknownBattleError,
)
from szop_client.protocol import (
    ContinuationFn,
    GameClient,
    PlayerFactory,
    SimulationSummary,
    Terrain,
)

__all__ = [
    "GameClient",
    "BattleMetadata",
    "HttpClient",
    "HttpClientError",
    "HttpClientTransportError",
    "HttpRequest",
    "HttpResponse",
    "LocalClient",
    "UnknownBattleError",
    "RosterNotFoundError",
    "SimulationSummary",
    "PlayerFactory",
    "ContinuationFn",
    "Terrain",
]
