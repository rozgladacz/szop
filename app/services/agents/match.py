"""D1/D2 substrat — headless match runner: napędza dwóch `Player`-ów przez pełną grę.

D1 dał graczy (`choose_action`), ale nikt ich nie uruchamia w pełnej grze.
`run_match` orkiestruje publiczne API silnika (ADR-0011) w pętlę rund (pkt 8):

    while not is_battle_over(state):          # pkt 5.f (MAX_ROUND=4)
        while not should_end_round(state):    # pkt 8.b
            aktywny gracz wybiera akcję → resolver.apply (1 akcja = 1 aktywacja)
        round_end_phase(state)                # pkt 8.c

Headless-first (ADR-0013): zero DB/HTTP, czysta orkiestracja. Seed
`DeterministicDice` → pełna gra deterministyczna (replay-safe, ADR-0010/0012).
To **zalążek** `B5 LocalClient.simulate` (pełen B5 z Protocol GameClient +
HttpClient poza zakresem); konsument: D2 `scripts/balance_simulate.py`.

Model aktywacji (ADR-0032 / H1): `resolver.apply` to JEDNA akcja = jedna
aktywacja — silnik ustawia Aktywowany i przełącza inicjatywę po każdym `apply`
(limit 2 akcji/aktywację pkt 11.b.iv nieaktywny w MVP). Runner respektuje ten
model: jedno `apply` per oddział per runda.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from app.services.agents.base import Player, own_active_units
from app.services.agents.deployment import DeploymentZone
from app.services.engine.actions import DeploymentAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent, InitiativePassed
from app.services.engine.phases import (
    deployment_round,
    round_end_phase,
    setup_phase,
)
from app.services.engine.resolver import (
    IllegalActionError,
    apply_activation,
    is_battle_over,
    should_end_round,
)
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    TerrainCircle,
    TerrainLine,
)

#: Bezpiecznik anty-zapętlenie — maks. aktywacji na całą grę. Realna gra to
#: ≤ 4 rundy × liczba oddziałów; cap chroni przed custom Player-em, który nigdy
#: nie kończy (np. zwraca akcję nie zmieniającą stanu w nieskończoność).
DEFAULT_MAX_ACTIVATIONS: int = 2000


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Wynik pojedynczej gry.

    `winner ∈ {0, 1, None}` — gracz z większą liczbą zajętych celów na koniec
    gry (pkt 5.f); `None` = remis. `events` to log od startu `run_match`
    (eventy rozstawienia z `simulate_from_rosters` NIE są dołączone — patrz
    tam). `rounds_played` = `final_state.round` (po grze == MAX_ROUND).
    """

    final_state: BattleState
    events: tuple[BattleEvent, ...]
    winner: int | None
    rounds_played: int


def _winner(state: BattleState) -> int | None:
    """Zwycięzca per pkt 5.f: więcej zajętych celów. Remis → None."""
    p0, p1 = state.score
    if p0 > p1:
        return 0
    if p1 > p0:
        return 1
    return None


def run_match(
    state: BattleState,
    players: Sequence[Player],
    dice: DeterministicDice,
    *,
    max_activations: int = DEFAULT_MAX_ACTIVATIONS,
) -> MatchResult:
    """Rozgrywa pełną grę od stanu **po rozstawieniu** (round ≥ 1) do końca.

    Args:
        state: BattleState po `deployment_round` (round=1, units FRONT).
        players: 2 `Player`-zy indeksowani przez `owner_player` (0, 1).
        dice: `DeterministicDice` — seed determinuje całą grę.
        max_activations: bezpiecznik anty-zapętlenie.

    Returns:
        `MatchResult(final_state, events, winner, rounds_played)`.

    Raises:
        RuntimeError: przekroczono `max_activations` (Player nie kończy gry).
    """
    events: list[BattleEvent] = []
    seq = 1
    activations = 0

    while not is_battle_over(state):
        while not should_end_round(state):
            active = state.active_player
            action = players[active].choose_action(state, active)
            if action is None:
                # Brak własnych aktywowalnych oddziałów (legal_actions zawsze
                # daje Obronę per oddział → None ⟺ own_active_units pusty).
                opponent = 1 - active
                if own_active_units(state, opponent):
                    # Przekaż inicjatywę (pkt 8.a) — emit InitiativePassed dla
                    # spójności log-u eventów (jak resolver._switch_active_player).
                    events.append(
                        InitiativePassed(
                            sequence=seq,
                            previous_active_player=active,
                            new_active_player=opponent,
                        )
                    )
                    seq += 1
                    state = replace(state, active_player=opponent)
                    continue
                # Żaden gracz nie ma aktywowalnych oddziałów na Froncie —
                # kończymy rundę. Ścieżka istotna dla rezerw Zaplecze (pkt 26):
                # `should_end_round` liczy je jako "żywe nieaktywowane", ale
                # runner ich nie rozstawia mid-game (MVP) → bez tego break pętla
                # rundy nie zakończyłaby się. Round_end i tak domknie grę po pkt 5.f.
                break

            # Aktywacja do 2 akcji (pkt 11.b.iv) — aktywny gracz dostarcza
            # kolejne akcje przez `continue_activation`.
            player = players[active]
            result = apply_activation(
                state,
                action,
                dice,
                sequence=seq,
                continuation=lambda s, uid, taken, _p=player, _a=active: _p.continue_activation(
                    s, _a, uid, taken
                ),
            )
            state = result.state
            seq = result.next_sequence
            events.extend(result.events)
            activations += 1
            if activations >= max_activations:
                raise RuntimeError(
                    f"run_match exceeded max_activations={max_activations} "
                    f"— possible non-terminating player"
                )

        state, end_events = round_end_phase(state, sequence=seq)
        seq += len(end_events)
        events.extend(end_events)

    return MatchResult(
        final_state=state,
        events=tuple(events),
        winner=_winner(state),
        rounds_played=state.round,
    )


def _build_deployment_from_players(
    state: BattleState,
    players: Sequence[Player],
    deployment_zones: Sequence[DeploymentZone],
) -> list[DeploymentAction]:
    """D5 — pyta każdego gracza o pozycję startową jego oddziałów (pkt 13).

    Iteruje oddziały na Froncie w deterministycznej kolejności (jak w `state.blobs`),
    pyta `players[owner].choose_deployment(state, unit_id, zone)` i waliduje, że
    całe koło mieści się w strefie gracza (pkt 13.a MVP: `zone.contains_circle`).
    Rezerwy Zaplecze (pkt 26) pomijane — rozstawiają się mid-game (poza MVP).

    Raises:
        IllegalActionError: pozycja poza strefą rozstawienia gracza (pkt 13.a).
    """
    actions: list[DeploymentAction] = []
    for blob in state.blobs:
        if blob.models_alive <= 0 or blob.location != Lokalizacja.FRONT:
            continue
        zone = deployment_zones[blob.owner_player]
        pos = players[blob.owner_player].choose_deployment(state, blob.id, zone)
        if not zone.contains_circle(pos, blob.radius_inches):
            raise IllegalActionError(
                f"Rozstawienie oddziału {blob.id} (gracz {blob.owner_player}) "
                f"poza strefą (pkt 13.a): pozycja {pos} koło r={blob.radius_inches} "
                f"nie mieści się w {zone}"
            )
        actions.append(DeploymentAction(unit_id=blob.id, position=pos))
    return actions


def simulate_from_rosters(
    rosters: Sequence[dict],
    players: Sequence[Player],
    *,
    seed: int = 0,
    terrain: Sequence[TerrainCircle | TerrainLine] = (),
    objectives: Sequence[Objective] = (),
    initiative_player: int = 0,
    deployment: Sequence = (),
    deployment_zones: Sequence[DeploymentZone] | None = None,
    ruleset_version: str = "v1",
    max_activations: int = DEFAULT_MAX_ACTIVATIONS,
) -> MatchResult:
    """Wygoda dla D2: `setup_phase` + `deployment_round` + `run_match`.

    `deployment` (lista `DeploymentAction`) domyślnie puste — oddziały startują
    na pozycjach z roster (pkt 13: rozstawienie bez ruchu). Eventy rozstawienia
    są pominięte w `MatchResult.events` (runner liczy od startu rundy 1).

    `deployment_zones` (D5) — gdy podane (`(zone_p0, zone_p1)`), boty wybierają
    pozycje startowe przez `Player.choose_deployment` (walidacja strefy pkt 13.a).
    Ma pierwszeństwo przed explicit `deployment`; gdy None — zachowanie bez zmian
    (pozycje z roster). Wzajemnie wykluczające z `deployment` (jawny deployment
    + auto-deployment botów byłby dwuznaczny).

    Raises:
        ValueError: podano jednocześnie `deployment` i `deployment_zones`.
        IllegalActionError: bot zwrócił pozycję poza swoją strefą (pkt 13.a).
    """
    state = setup_phase(
        rosters,
        terrain=terrain,
        objectives=objectives,
        initiative_player=initiative_player,
        ruleset_version=ruleset_version,
    )
    if deployment_zones is not None:
        if deployment:
            raise ValueError(
                "simulate_from_rosters: podaj albo `deployment` (jawne akcje), "
                "albo `deployment_zones` (auto-deployment botów), nie oba naraz"
            )
        deployment = _build_deployment_from_players(state, players, deployment_zones)
    state, _deploy_events = deployment_round(state, deployment)
    dice = DeterministicDice(seed=seed)
    return run_match(state, players, dice, max_activations=max_activations)
