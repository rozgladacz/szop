"""B5 — `LocalClient`: implementacja `GameClient` in-process (ADR-0016).

Headless, bez DB/HTTP — opakowuje publiczne API silnika (ADR-0011) i runner
(`app.services.agents.match`, ADR-0032). Bitwy single-step trzymane w rejestrze
w pamięci (`_battles`); batch `simulate` deleguje do `simulate_from_rosters`.

Determinizm: `seed` → `DeterministicDice` (ADR-0010/0012). Te same argumenty +
seed = bit-perfect ten sam przebieg (replay-safe). To czyni klienta testowalnym
i odblokowuje przyszły test parity `HttpClient == LocalClient` (po B4).

Zakres slice (HANDOFF_faza-b-5-client): ścieżka **engine-dict** (rostery jako
dict 1:1 z `build_initial_state`). DB-backed konstruktor `LocalClient(db_session,
user_id)` z roadmap wymaga mostu ORM→engine-dict (`faza-d-roster-adapter`) —
odłożony.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.services.agents.match import simulate_from_rosters
from app.services.engine.actions import Action, DeploymentAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent
from app.services.engine.phases import deployment_round, setup_phase
from app.services.engine.resolver import apply_activation
from app.services.engine.state import BattleState, Objective
from szop_client.protocol import (
    ContinuationFn,
    PlayerFactory,
    SimulationSummary,
    Terrain,
)


class UnknownBattleError(KeyError):
    """Podano `battle_id` nieobecny w rejestrze `LocalClient`."""


@dataclass(slots=True)
class _BattleRecord:
    """Stan jednej bitwy single-step w rejestrze (mutowalny uchwyt na immutable state)."""

    state: BattleState
    dice: DeterministicDice
    next_sequence: int
    events: list[BattleEvent] = field(default_factory=list)


class LocalClient:
    """In-process `GameClient` (ADR-0016). Patrz `protocol.GameClient`."""

    def __init__(self) -> None:
        self._battles: dict[int, _BattleRecord] = {}
        self._next_id: int = 1

    # -- single-step play -------------------------------------------------

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
        state = setup_phase(
            rosters,
            terrain=terrain,
            objectives=objectives,
            initiative_player=initiative_player,
        )
        state, deploy_events = deployment_round(state, deployment)
        battle_id = self._next_id
        self._next_id += 1
        self._battles[battle_id] = _BattleRecord(
            state=state,
            dice=DeterministicDice(seed=seed),
            # Eventy rozstawienia mają sequence 1..k (deployment_round) → akcje
            # kontynuują monotonicznie od k+1.
            next_sequence=len(deploy_events) + 1,
            events=list(deploy_events),
        )
        return battle_id

    def get_state(self, battle_id: int) -> BattleState:
        return self._record(battle_id).state

    def take_action(
        self,
        battle_id: int,
        action: Action,
        *,
        continuation: ContinuationFn | None = None,
    ) -> tuple[BattleState, tuple[BattleEvent, ...]]:
        record = self._record(battle_id)
        result = apply_activation(
            record.state,
            action,
            record.dice,
            sequence=record.next_sequence,
            continuation=continuation,
        )
        record.state = result.state
        record.next_sequence = result.next_sequence
        record.events.extend(result.events)
        return result.state, result.events

    def get_events(
        self, battle_id: int, since: int = 0
    ) -> tuple[BattleEvent, ...]:
        record = self._record(battle_id)
        return tuple(e for e in record.events if e.sequence > since)

    # -- batch ------------------------------------------------------------

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
        if n <= 0:
            raise ValueError(f"n musi być > 0, jest {n}")
        wins = [0, 0]
        draws = 0
        total_rounds = 0
        for i in range(n):
            players = player_factory(i)
            init = (i % 2) if alternate_initiative else initiative_player
            result = simulate_from_rosters(
                rosters,
                players,
                seed=seed + i,
                terrain=terrain,
                objectives=objectives,
                initiative_player=init,
            )
            if result.winner is None:
                draws += 1
            else:
                wins[result.winner] += 1
            total_rounds += result.rounds_played
        return SimulationSummary(
            n_games=n,
            wins_p0=wins[0],
            wins_p1=wins[1],
            draws=draws,
            total_rounds=total_rounds,
        )

    # -- internal ---------------------------------------------------------

    def _record(self, battle_id: int) -> _BattleRecord:
        try:
            return self._battles[battle_id]
        except KeyError:
            raise UnknownBattleError(battle_id) from None
