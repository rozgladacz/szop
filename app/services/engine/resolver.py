"""B3.7 — Top-level resolver (ADR-0011): public engine entry point.

`apply(state, action, dice)` jest **pure function** wywoływaną z:
- `app/routers/battles.py` (B4) — endpointy `POST /battles/{id}/actions` itp.
- `szop_client/local.py` (B5) — in-process battle client (LocalClient.take_action)
- `app/services/agents/` (Strumień D) — boty wybierają action, engine resolves

Resolver wykonuje:
1. **Walidacja** — gra nie zakończona, aktor nie pokonany, nie Aktywowany,
   odpowiedni active_player. Przy niezgodności → `IllegalActionError`.
2. **Dispatch** — delegacja do `phases.activation_phase` (która sama dispatcha
   per Action type → combat.resolve_* + Przegrupowanie + Aktywowany).
3. **Switch inicjatywy** (pkt 8.a) — po aktywacji active_player przechodzi
   na przeciwnika (chyba że przeciwnik nie ma nieaktywowanych oddziałów —
   fallback do tego samego gracza per pkt 8.a).

Helpers:
- `should_end_round(state)` — True gdy wszyscy żyjący oddziale obu graczy
  mają status Aktywowany (pkt 8.b warunek zatrzymania pętli aktywacji).
- `is_battle_over(state)` — alias dla `state.is_game_over`.

Replay determinism: dla tego samego `(state, action, seed)` → ten sam
`ResolverResult` (inwariant ADR-0010 + ADR-0012). Pure function — zero DB,
zero state mutation poza zwracanym ResolverResult.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.engine.actions import Action
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent
from app.services.engine.phases import (
    STATUS_AKTYWOWANY,
    activation_phase,
)
from app.services.engine.state import BattleState


class IllegalActionError(Exception):
    """Akcja niedozwolona w obecnym `BattleState`.

    Powody: gra zakończona (pkt 5.f), aktor pokonany (models_alive=0), aktor
    już Aktywowany w tej rundzie (pkt 22.d.i), aktor należy do innego gracza
    niż `state.active_player` (pkt 11.a).
    """


@dataclass(frozen=True, slots=True)
class ResolverResult:
    """Output `resolver.apply`. Pure data — frozen, replay-safe.

    `state` to nowy BattleState po aplikacji akcji. `events` to sekwencyjne
    BattleEvent (per ADR-0010). `next_sequence` to pierwszy sequence dla
    kolejnego `apply` call (caller propaguje przez wywołania).
    """

    state: BattleState
    events: tuple[BattleEvent, ...]
    next_sequence: int


# ---------------------------------------------------------------------------
# Walidacja
# ---------------------------------------------------------------------------


def _validate_action(state: BattleState, action: Action) -> None:
    """Raise `IllegalActionError` gdy akcja niedozwolona w obecnym state."""
    if state.is_game_over:
        raise IllegalActionError(
            "Game is over (pkt 5.f); no more actions allowed"
        )

    actor = next((b for b in state.blobs if b.id == action.unit_id), None)
    if actor is None:
        raise IllegalActionError(
            f"Unit {action.unit_id} not found in state"
        )
    if actor.models_alive == 0:
        raise IllegalActionError(
            f"Unit {action.unit_id} is defeated (models_alive=0)"
        )
    if STATUS_AKTYWOWANY in actor.status_flags:
        raise IllegalActionError(
            f"Unit {action.unit_id} already activated this round "
            f"(pkt 22.d.i)"
        )
    if actor.owner_player != state.active_player:
        raise IllegalActionError(
            f"Unit {action.unit_id} belongs to player {actor.owner_player}, "
            f"but active_player is {state.active_player} (pkt 11.a)"
        )


# ---------------------------------------------------------------------------
# Inicjatywa (pkt 8.a)
# ---------------------------------------------------------------------------


def _switch_active_player(state: BattleState) -> BattleState:
    """Pkt 8.a — gracz przekazuje inicjatywę po aktywacji.

    "Gracz, który ma inicjatywę, jeżeli może, rozpatruje aktywację jednego ze
    swoich oddziałów, a następnie przekazuje inicjatywę." Implicytnie: jeśli
    drugi gracz nie ma już oddziałów do aktywacji, inicjatywa wraca do
    aktywnego (lub runda się kończy w wyższej warstwie).
    """
    other = 1 - state.active_player
    other_has_unactivated = any(
        b.owner_player == other
        and b.models_alive > 0
        and STATUS_AKTYWOWANY not in b.status_flags
        for b in state.blobs
    )
    if other_has_unactivated:
        return replace(state, active_player=other)
    # Brak nieaktywowanych u przeciwnika — zostawiamy active_player (current player
    # kontynuuje aktywacje lub round end w wyższej warstwie)
    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply(
    state: BattleState,
    action: Action,
    dice: DeterministicDice,
    sequence: int = 1,
) -> ResolverResult:
    """Pure resolver per ADR-0011 — dispatcher dla pojedynczej aktywacji.

    Args:
        state: aktualny BattleState.
        action: jedna z `actions.Action` types.
        dice: DeterministicDice (ADR-0012).
        sequence: pierwszy sequence dla emitowanych events.

    Returns:
        ResolverResult(state, events, next_sequence).

    Raises:
        IllegalActionError: akcja niedozwolona (zob. `_validate_action`).
    """
    _validate_action(state, action)
    new_state, events = activation_phase(state, action, dice, sequence)
    new_state = _switch_active_player(new_state)
    return ResolverResult(
        state=new_state,
        events=events,
        next_sequence=sequence + len(events),
    )


# ---------------------------------------------------------------------------
# Round-flow helpers (called by higher-level orchestrator, e.g. B4 routers)
# ---------------------------------------------------------------------------


def should_end_round(state: BattleState) -> bool:
    """Pkt 8.b — runda kończy się gdy wszystkie żywe oddziale są Aktywowane.

    "Jeżeli są oddziały bez stanu Aktywowany, wracamy do pkt a." → False (loop).
    Gdy wszystkie żyjące oddziale są Aktywowane → True (call round_end_phase).
    """
    living_blobs = [b for b in state.blobs if b.models_alive > 0]
    if not living_blobs:
        return True  # Wszyscy pokonani — koniec rundy (edge case)
    return all(STATUS_AKTYWOWANY in b.status_flags for b in living_blobs)


def is_battle_over(state: BattleState) -> bool:
    """Pkt 5.f — gra zakończona po round 4 (`state.is_game_over` set by round_end_phase)."""
    return state.is_game_over
