"""B5 — `LocalClient`: implementacja `GameClient` in-process (ADR-0016).

Headless, bez DB/HTTP — opakowuje publiczne API silnika (ADR-0011) i runner
(`app.services.agents.match`, ADR-0032). Bitwy single-step trzymane w rejestrze
w pamięci (`_battles`); batch `simulate` deleguje do `simulate_from_rosters`.

Determinizm: `seed` → `DeterministicDice` (ADR-0010/0012). Te same argumenty +
seed = bit-perfect ten sam przebieg (replay-safe). To czyni klienta testowalnym
i odblokowuje przyszły test parity `HttpClient == LocalClient` (po B4).

Ścieżka **engine-dict** (rostery jako dict 1:1 z `build_initial_state`) +
**ścieżka DB** (rozpiski ORM `Roster` po id). Konstruktor `LocalClient(session,
user_id)` wiąże opcjonalną sesję SQLAlchemy (read-only); metody `*_roster_ids`
wczytują `Roster`, adaptują przez most ORM→engine-dict (`roster_adapter`,
`faza-d-roster-adapter`) i delegują do istniejących ścieżek engine-dict. Bez
sesji klient działa jak dotąd (wsteczna kompat z B5-slice).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.agents.deployment import DeploymentZone
from app.services.agents.roster_adapter import roster_to_engine_roster
from app.services.engine.actions import Action, DeploymentAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent
from app.services.engine.phases import deployment_round, setup_phase
from app.services.engine.resolver import apply_activation
from app.services.engine.state import BattleState, Objective
from app.services.roster_simulation import simulate_batch
from szop_client.protocol import (
    ContinuationFn,
    PlayerFactory,
    SimulationSummary,
    Terrain,
)
from szop_client.types import RosterNotFoundError


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

    def __init__(self, session: Any = None, user_id: int | None = None) -> None:
        """`session` — opcjonalna sesja SQLAlchemy (read-only) do ścieżki DB.

        `user_id` — gdy podane, metody `*_roster_ids` wymagają by `Roster.owner_id`
        był równy `user_id` (scoping: nie symuluj cudzych rozpisek). `None` =
        bez ograniczenia własności (np. narzędzia balansu na puli publicznej).
        Bez `session` klient działa wyłącznie na engine-dict (wsteczna kompat).
        """
        self._battles: dict[int, _BattleRecord] = {}
        self._next_id: int = 1
        self._session = session
        self._user_id = user_id

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
        deployment_zones: Sequence[DeploymentZone] | None = None,
    ) -> SimulationSummary:
        return simulate_batch(
            rosters,
            player_factory,
            n=n,
            seed=seed,
            terrain=terrain,
            objectives=objectives,
            alternate_initiative=alternate_initiative,
            initiative_player=initiative_player,
            deployment_zones=deployment_zones,
        )

    # -- DB-backed (rozpiski ORM po id) -----------------------------------

    def create_battle_from_roster_ids(
        self,
        roster_id_p0: int,
        roster_id_p1: int,
        *,
        seed: int = 0,
        terrain: Sequence[Terrain] = (),
        objectives: Sequence[Objective] = (),
        initiative_player: int = 0,
        models_mode: str = "per_copy",
        deployment: Sequence[DeploymentAction] = (),
    ) -> int:
        """Tworzy bitwę single-step z dwóch rozpisek ORM (po id) i zwraca jej id.

        Wczytuje `Roster` z sesji DB (read-only), adaptuje przez
        `roster_to_engine_roster` (most ORM→engine-dict; `models_mode=per_copy`
        kanoniczny — `RosterUnit.count` osobnych blobów) i deleguje do
        `create_battle`. Pozycje startowe: placeholder z adaptera (realne
        rozstawienie w strefie to ścieżka batch przez `deployment_zones`).
        """
        return self.create_battle(
            self._load_engine_rosters(roster_id_p0, roster_id_p1, models_mode),
            seed=seed,
            terrain=terrain,
            objectives=objectives,
            initiative_player=initiative_player,
            deployment=deployment,
        )

    def simulate_roster_ids(
        self,
        roster_id_p0: int,
        roster_id_p1: int,
        player_factory: PlayerFactory,
        *,
        n: int = 1,
        seed: int = 0,
        terrain: Sequence[Terrain] = (),
        objectives: Sequence[Objective] = (),
        alternate_initiative: bool = True,
        initiative_player: int = 0,
        deployment_zones: Sequence[DeploymentZone] | None = None,
        models_mode: str = "per_copy",
    ) -> SimulationSummary:
        """Rozgrywa N gier między dwiema rozpiskami ORM (po id) i agreguje (pkt 5.f).

        Enabler C3 `simulate_engagement(roster_a, roster_b, n)`. Wczytuje rozpiski
        z sesji DB (read-only), adaptuje (SSOT `roster_to_engine_roster`) i deleguje
        do `simulate`. `deployment_zones` (D5) — gdy podane, boty rozstawiają się
        w strefach (realne pozycje); gdy None — pozycje placeholder z adaptera.
        """
        return self.simulate(
            self._load_engine_rosters(roster_id_p0, roster_id_p1, models_mode),
            player_factory,
            n=n,
            seed=seed,
            terrain=terrain,
            objectives=objectives,
            alternate_initiative=alternate_initiative,
            initiative_player=initiative_player,
            deployment_zones=deployment_zones,
        )

    # -- internal ---------------------------------------------------------

    def _load_engine_rosters(
        self, roster_id_p0: int, roster_id_p1: int, models_mode: str
    ) -> list[dict]:
        """Wczytuje obie rozpiski po id i adaptuje na engine-dict (SSOT adapter).

        Rozłączne przestrzenie id blobów per gracz (owner_player 0/1) gwarantuje
        `roster_to_engine_roster` (`_PLAYER_ID_STRIDE`).
        """
        return [
            roster_to_engine_roster(
                self._load_roster(rid), owner_player=owner, models_mode=models_mode
            ).units
            for owner, rid in ((0, roster_id_p0), (1, roster_id_p1))
        ]

    def _load_roster(self, roster_id: int) -> Any:
        """Pobiera `Roster` z sesji DB; waliduje istnienie i (opcjonalnie) własność."""
        if self._session is None:
            raise RuntimeError(
                "Ścieżka DB wymaga LocalClient(session=...); klient utworzony bez sesji."
            )
        from app.models import Roster  # lazy — unika importu ORM gdy ścieżka DB nieużywana

        roster = self._session.get(Roster, roster_id)
        if roster is None:
            raise RosterNotFoundError(f"Roster id={roster_id} nie istnieje")
        if self._user_id is not None and getattr(roster, "owner_id", None) != self._user_id:
            raise RosterNotFoundError(
                f"Roster id={roster_id} nie należy do user_id={self._user_id}"
            )
        return roster

    def _record(self, battle_id: int) -> _BattleRecord:
        try:
            return self._battles[battle_id]
        except KeyError:
            raise UnknownBattleError(battle_id) from None
