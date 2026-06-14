"""B5 — kontrakt klienta gry (`GameClient` Protocol) + typy wyników.

`GameClient` to **seam** między konsumentami (C3 `simulate_engagement`, D-stream,
przyszłe UI) a wewnętrznymi modułami silnika (`app.services.engine.*`, ADR-0011)
i runnerem (`app.services.agents.match`, ADR-0032). Konsument programuje wobec
tego Protocolu, nie wobec konkretnych modułów — dzięki temu `LocalClient`
(in-process) i przyszły `HttpClient` (po B4 API) są wymienne, a test parity
`HttpClient.simulate(...) == LocalClient.simulate(...)` ma sens (roadmap B5).

Protocol jest strukturalny (`typing.Protocol`) — implementacja nie musi po nim
dziedziczyć, wystarczy zgodność sygnatur.

Zakres B5-slice (patrz HANDOFF_faza-b-5-client): single-step play
(`create_battle`/`get_state`/`take_action`/`get_events`) + batch `simulate`.
`subscribe_events` (push/SSE z roadmap) jest realizowane jako pull
`get_events(battle_id, since)`; streaming SSE to B6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

from app.services.agents.base import Player
from app.services.engine.actions import Action, DeploymentAction
from app.services.engine.events import BattleEvent
from app.services.engine.state import (
    BattleState,
    Objective,
    TerrainCircle,
    TerrainLine,
)

#: Teren akceptowany przy tworzeniu bitwy.
Terrain = TerrainCircle | TerrainLine

#: Callback aktywacji wieloakcyjnej (pkt 11.b.iv, ADR-0051): dla danego stanu,
#: id oddziału i już-wykonanych akcji zwraca następną akcję lub `None` (koniec).
#: Zgodny z `resolver.apply_activation(continuation=...)`.
ContinuationFn = Callable[[BattleState, int, tuple[Action, ...]], Optional[Action]]

#: Fabryka graczy dla batcha `simulate`: dla indeksu gry `i` zwraca 2 graczy
#: (indeksowanych przez `owner_player` 0/1). Gracze są budowani **świeżo per
#: grę** — gracze z RNG (`RandomPlayer`) muszą dostać rozłączne seedy, inaczej
#: na symetrycznej planszy grają lustrzanie i zawyżają remisy (finding F2,
#: `HANDOFF.md` LOG 2026-06-11). To odpowiedzialność fabryki.
PlayerFactory = Callable[[int], Sequence[Player]]


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    """Zagregowany wynik N gier batcha `simulate`.

    `wins_p0`/`wins_p1` liczone per `owner_player` (0/1), nie per inicjatywa —
    inicjatywa naprzemienna usuwa bias pierwszego gracza, ale wynik zawsze
    przypisany właścicielowi (pkt 5.f). `None`-zwycięzca = remis.
    """

    n_games: int
    wins_p0: int
    wins_p1: int
    draws: int
    total_rounds: int

    @property
    def win_rate_p0(self) -> float:
        return self.wins_p0 / self.n_games if self.n_games else 0.0

    @property
    def win_rate_p1(self) -> float:
        return self.wins_p1 / self.n_games if self.n_games else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.n_games if self.n_games else 0.0

    @property
    def avg_rounds(self) -> float:
        return self.total_rounds / self.n_games if self.n_games else 0.0


@runtime_checkable
class GameClient(Protocol):
    """Wymienialny klient gry — `LocalClient` (in-process) lub `HttpClient` (B4)."""

    def create_battle(
        self,
        rosters: Sequence[dict],
        *,
        seed: int = 0,
        terrain: Sequence[Terrain] = (),
        objectives: Sequence[Objective] = (),
        initiative_player: int = 0,
        deployment: Sequence[DeploymentAction] = (),
    ) -> int:
        """Tworzy bitwę (setup + rozstawienie) i zwraca jej id. `round=1` po."""
        ...

    def get_state(self, battle_id: int) -> BattleState:
        """Aktualny `BattleState` bitwy."""
        ...

    def take_action(
        self,
        battle_id: int,
        action: Action,
        *,
        continuation: ContinuationFn | None = None,
    ) -> tuple[BattleState, tuple[BattleEvent, ...]]:
        """Aplikuje aktywację (do 2 akcji, pkt 11.b.iv). Zwraca nowy stan + delta eventów."""
        ...

    def get_events(
        self, battle_id: int, since: int = 0
    ) -> tuple[BattleEvent, ...]:
        """Eventy bitwy o `sequence > since` (pull; SSE/push → B6)."""
        ...

    def simulate(
        self,
        rosters: Sequence[dict],
        player_factory: PlayerFactory,
        *,
        n: int = 1,
        seed: int = 0,
        terrain: Sequence[Terrain] = (),
        objectives: Sequence[Objective] = (),
        alternate_initiative: bool = True,
        initiative_player: int = 0,
    ) -> SimulationSummary:
        """Rozgrywa N pełnych gier headless i agreguje wyniki (pkt 5.f)."""
        ...
