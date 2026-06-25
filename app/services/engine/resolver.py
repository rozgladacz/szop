"""B3.7 — Top-level resolver (ADR-0011): public engine entry point.

`apply(state, action, dice)` jest **pure function** wywoływaną z:
- `app/routers/battles.py` (B4) — endpointy `POST /battles/{id}/actions` itp.
- `szop_client/local.py` (B5) — in-process battle client (LocalClient.take_action)
- `app/services/agents/` (Strumień D) — boty wybierają action, engine resolves

Resolver wykonuje:
1. **Walidacja** — gra nie zakończona, aktor nie pokonany, nie Aktywowany,
   odpowiedni active_player, Manewr w budżecie ruchu (dist ≤ efektywny budżet,
   pkt 15.a + Szybki/Wolny) i z końcowym odstępem >1″ od innych oddziałów
   (pkt 15.b.iii). Przy niezgodności → `IllegalActionError`.
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
from typing import Callable

from app.services.engine.actions import (
    Action,
    ChargeAction,
    ManeuverAction,
    ShootAction,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent, InitiativePassed
from app.services.engine.geometry import distance
from app.services.engine.movement import (
    MIN_MANEUVER_UNIT_GAP,
    maneuver_destination_blocker,
)
from app.services.engine.phases import (
    _apply_single_action,
    _begin_activation,
    _finalize_activation,
    activation_phase,
)
from app.services.engine.state import BattleState, UnitBlob, effective_move_inches
from app.services.engine.status import STATUS_AKTYWOWANY

#: Maks. liczba akcji w aktywacji (pkt 11.b.iv — Manewr liczy się do limitu).
MAX_ACTIONS_PER_ACTIVATION = 2

#: Tolerancja float dla walidacji dystansu Manewru (pkt 15.a). Boty skalują ruch
#: dokładnie do budżetu (`_move_toward` ratio = max_dist/d) → wynik bywa
#: max_dist ± ~1e-12; epsilon zapobiega fałszywym odrzuceniom legalnych ruchów.
_MOVE_EPSILON = 1e-6

#: Callback dostarczający kolejną akcję w aktywacji (lub None = koniec).
#: `(state, unit_id, actions_taken) -> Action | None`.
ActionProvider = Callable[[BattleState, int, "tuple[Action, ...]"], "Action | None"]

#: Czysto obserwacyjny hook telemetrii (ADR-0017) — wołany po KAŻDEJ zaaplikowanej
#: akcji aktywacji z `(action, state_before_action, state_after_action)`. Stany
#: bracketują pojedynczą akcję (przed `_finalize_activation`/switch). `None` =
#: zero wywołań; nie wpływa na stan, event-log ani replay (silnik raportuje fakt,
#: warstwa telemetrii dokłada czas — patrz `match._apply_activation_with_telemetry`).
ActionObserver = Callable[["Action", "BattleState", "BattleState"], None]


class IllegalActionError(Exception):
    """Akcja niedozwolona w obecnym `BattleState`.

    Powody: gra zakończona (pkt 5.f), aktor pokonany (models_alive=0), aktor
    już Aktywowany w tej rundzie (pkt 22.d.i), aktor należy do innego gracza
    niż `state.active_player` (pkt 11.a), Manewr przekracza budżet ruchu
    (`dist > efektywny_budżet`, pkt 15.a + zdolność 33 Szybki/Wolny), albo
    kończy się zbyt blisko innego oddziału (pkt 15.b.iii).
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


def _validate_maneuver_distance(actor: UnitBlob, action: ManeuverAction) -> None:
    """Raise `IllegalActionError` gdy Manewr przekracza budżet ruchu (pkt 15.a).

    Domyka kontrakt deklarowany w `actions.py` (`ManeuverAction` docstring) +
    `phases._apply_maneuver` docstring — engine egzekwuje legalność dystansu.
    Budżet = `effective_move_inches(actor)` (pkt 15.a + zdolność 33 Szybki/Wolny).
    Krytyczne pod B4: klient `POST /battles/{id}/actions` nie może teleportować
    oddziału. Trudny/Niedostępny (pkt 4.c) świadomie nieegzekwowane → E4.
    """
    dist = distance(actor.position, action.target_position)
    budget = effective_move_inches(actor)
    if dist > budget + _MOVE_EPSILON:
        raise IllegalActionError(
            f"Unit {action.unit_id} maneuver distance {dist:.3f}\" exceeds move "
            f"budget {budget:.3f}\" (pkt 15.a + zdolność 33 Szybki/Wolny)"
        )


def _validate_maneuver_clearance(
    state: BattleState, actor: UnitBlob, action: ManeuverAction
) -> None:
    """Raise `IllegalActionError` when Maneuver ends too close to another unit."""
    blocker = maneuver_destination_blocker(state, actor, action.target_position)
    if blocker is not None:
        raise IllegalActionError(
            f"Unit {action.unit_id} maneuver target is too close to unit "
            f"{blocker.unit_id}: gap {blocker.gap_inches:.3f}\" <= required "
            f"{MIN_MANEUVER_UNIT_GAP:.3f}\" (pkt 15.b.iii)"
        )


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
    if isinstance(action, ManeuverAction):
        _validate_maneuver_distance(actor, action)
        _validate_maneuver_clearance(state, actor, action)


# ---------------------------------------------------------------------------
# Inicjatywa (pkt 8.a)
# ---------------------------------------------------------------------------


def _switch_active_player(
    state: BattleState, sequence: int
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 8.a — gracz przekazuje inicjatywę po aktywacji.

    "Gracz, który ma inicjatywę, jeżeli może, rozpatruje aktywację jednego ze
    swoich oddziałów, a następnie przekazuje inicjatywę." Implicytnie: jeśli
    drugi gracz nie ma już oddziałów do aktywacji, inicjatywa wraca do
    aktywnego (lub runda się kończy w wyższej warstwie).

    CR-fix B (post-B3.9.f): emit `InitiativePassed` event przy zmianie. Pre-fix
    silent `replace(active_player=...)` zostawiał replay state na initial
    active_player. Post-fix: replay z eventów rekonstruuje sekwencję
    aktywacji.
    """
    other = 1 - state.active_player
    other_has_unactivated = any(
        b.owner_player == other
        and b.models_alive > 0
        and STATUS_AKTYWOWANY not in b.status_flags
        for b in state.blobs
    )
    if other_has_unactivated:
        event = InitiativePassed(
            sequence=sequence,
            previous_active_player=state.active_player,
            new_active_player=other,
        )
        return replace(state, active_player=other), (event,)
    # Brak nieaktywowanych u przeciwnika — zostawiamy active_player (current player
    # kontynuuje aktywacje lub round end w wyższej warstwie). Brak eventu — no-op.
    return state, ()


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
    new_state, activation_events = activation_phase(
        state, action, dice, sequence
    )
    # CR-fix B: InitiativePassed event emit (gdy inicjatywa się zmienia)
    new_state, switch_events = _switch_active_player(
        new_state, sequence=sequence + len(activation_events)
    )
    events = activation_events + switch_events
    return ResolverResult(
        state=new_state,
        events=events,
        next_sequence=sequence + len(events),
    )


def _can_take_followup(action: Action, actions_taken: tuple[Action, ...]) -> bool:
    """Czy `action` jest legalną KOLEJNĄ akcją w aktywacji (pkt 11.b.iv).

    Limit 2 akcji (Manewr liczy się — pkt 11.b.iv po poprawce reguł 2026-06).
    Brak reguły „akcja różna" na poziomie pkt 11; ograniczenia powtórzeń tylko
    z definicji: Ostrzał raz (pkt 14.c.v), Szarża raz (pkt 14.d.vi). Więc
    Manewr+Manewr / Manewr+Ostrzał / Ostrzał+Szarża OK; Ostrzał+Ostrzał i
    Szarża+Szarża zabronione.
    """
    if len(actions_taken) >= MAX_ACTIONS_PER_ACTIVATION:
        return False
    if isinstance(action, ShootAction) and any(
        isinstance(a, ShootAction) for a in actions_taken
    ):
        return False  # pkt 14.c.v
    if isinstance(action, ChargeAction) and any(
        isinstance(a, ChargeAction) for a in actions_taken
    ):
        return False  # pkt 14.d.vi
    return True


def apply_activation(
    state: BattleState,
    first_action: Action,
    dice: DeterministicDice,
    sequence: int = 1,
    *,
    continuation: ActionProvider | None = None,
    on_action: ActionObserver | None = None,
) -> ResolverResult:
    """Pełna aktywacja (pkt 11.b) — do 2 akcji jednego oddziału, potem switch.

    Odpowiednik `apply`, ale realizuje pętlę pkt 11.b.iv: po pierwszej akcji
    pyta `continuation` o kolejną (dla TEGO samego oddziału), aż zwróci `None`,
    limit 2 akcji zostanie osiągnięty, akcja będzie nielegalna (Ostrzał/Szarża
    drugi raz), albo oddział zostanie pokonany. Następnie nadaje Aktywowany
    (`_finalize_activation`) i przekazuje inicjatywę (pkt 8.a).

    `continuation=None` → zachowanie jak `apply` (1 akcja). Postęp aktywacji
    (lista akcji) jest LOKALNY — `BattleState` bez zmian schematu, replay
    invariant zachowany (eventy te same prymitywy: akcja* + Aktywowany + switch).

    `on_action` (opcjonalny, ADR-0017): czysto obserwacyjny hook wołany po KAŻDEJ
    zaaplikowanej akcji z `(action, state_before, state_after)`. `None` → zero
    wywołań; nie zmienia stanu, eventów ani replay (B7 golden bez zmian).

    Raises:
        IllegalActionError: pierwsza akcja niedozwolona (zob. `_validate_action`).
    """
    _validate_action(state, first_action)
    unit_id = first_action.unit_id
    events: list[BattleEvent] = []
    seq = sequence

    state, begin_events, seq = _begin_activation(state, unit_id, seq)
    events.extend(begin_events)

    actions_taken: list[Action] = []
    action: Action | None = first_action
    while action is not None:
        state_before_action = state
        state, action_events, seq = _apply_single_action(state, action, dice, seq)
        events.extend(action_events)
        actions_taken.append(action)
        if on_action is not None:
            on_action(action, state_before_action, state)

        if continuation is None or len(actions_taken) >= MAX_ACTIONS_PER_ACTIVATION:
            break
        actor = next((b for b in state.blobs if b.id == unit_id), None)
        if actor is None or actor.models_alive == 0:
            break  # oddział pokonany w trakcie — koniec aktywacji
        nxt = continuation(state, unit_id, tuple(actions_taken))
        if (
            nxt is None
            or nxt.unit_id != unit_id  # tylko ten sam oddział (pkt 11: jedna aktywacja)
            or not _can_take_followup(nxt, tuple(actions_taken))
        ):
            break
        action = nxt

    state, final_events, seq = _finalize_activation(state, unit_id, seq)
    events.extend(final_events)
    state, switch_events = _switch_active_player(state, sequence=seq)
    events.extend(switch_events)

    return ResolverResult(
        state=state,
        events=tuple(events),
        next_sequence=seq + len(switch_events),
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
