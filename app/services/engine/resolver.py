"""B3.7 — Top-level resolver (ADR-0011): public engine entry point.

`apply(state, action, dice)` jest **pure function** wywoływaną z:
- `app/routers/battles.py` (B4) — endpointy `POST /battles/{id}/actions` itp.
- `szop_client/local.py` (B5) — in-process battle client (LocalClient.take_action)
- `app/services/agents/` (Strumień D) — boty wybierają action, engine resolves

Resolver wykonuje:
1. **Walidacja** — gra nie zakończona, aktor nie pokonany, nie Aktywowany,
   odpowiedni active_player i legalna trasa Manewru (pkt 2.d, 4.c.i/iv,
   14.a i 15). Przy niezgodności → `IllegalActionError`.
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
from typing import Callable, Literal

from app.services.engine.actions import (
    ACTION_TYPE_BY_CLASS,
    MAX_ACTIONS_PER_ACTIVATION,
    Action,
    ManeuverAction,
    can_append_activation_action_type,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import BattleEvent, InitiativePassed
from app.services.engine.geometry import distance
from app.services.engine.movement import MOVE_EPSILON
from app.services.engine.observation import (
    ActionDecision,
    AutomaticTransition,
    BattleObserver,
    snapshot_action,
    snapshot_events,
)
from app.services.engine.pathfinding import ManeuverPlanner, is_finite_position
from app.services.engine.phases import (
    _apply_single_action,
    _begin_activation,
    _finalize_activation,
    activation_phase,
)
from app.services.engine.state import BattleState, UnitBlob, effective_move_inches
from app.services.engine.status import STATUS_AKTYWOWANY

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
    niż `state.active_player` (pkt 11.a), albo nie ma legalnej trasy Manewru
    do zadeklarowanego punktu (pkt 2.d, 4.c.i/iv, 14.a i 15).
    """

    def __init__(self, *args: object, code: str = "illegal_action") -> None:
        super().__init__(*args)
        self.code = code


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


def _validate_maneuver(state: BattleState, actor: UnitBlob, action: ManeuverAction) -> None:
    budget = effective_move_inches(actor)
    if ManeuverPlanner(state, actor, budget).can_reach(action.target_position):
        return
    if not is_finite_position(action.target_position):
        raise IllegalActionError(
            f"Unit {action.unit_id} maneuver target must be finite",
            code="non_finite_maneuver_target",
        )
    dist = distance(actor.position, action.target_position)
    if dist > budget + MOVE_EPSILON:
        raise IllegalActionError(
            f"Unit {action.unit_id} maneuver distance {dist:.3f}\" exceeds move "
            f"budget {budget:.3f}\" (pkt 15.a + zdolność 33 Szybki/Wolny)",
            code="maneuver_over_budget",
        )
    raise IllegalActionError(
        f"Unit {action.unit_id} has no legal maneuver route to target "
        "(pkt 2.d, 4.c.i/iv, 14.a i 15)",
        code="no_maneuver_route",
    )


def _validate_action(state: BattleState, action: Action) -> None:
    """Raise `IllegalActionError` gdy akcja niedozwolona w obecnym state."""
    if state.is_game_over:
        raise IllegalActionError(
            "Game is over (pkt 5.f); no more actions allowed", code="game_over",
        )

    actor = next((b for b in state.blobs if b.id == action.unit_id), None)
    if actor is None:
        raise IllegalActionError(
            f"Unit {action.unit_id} not found in state", code="unit_not_found",
        )
    if actor.models_alive == 0:
        raise IllegalActionError(
            f"Unit {action.unit_id} is defeated (models_alive=0)", code="unit_defeated",
        )
    if STATUS_AKTYWOWANY in actor.status_flags:
        raise IllegalActionError(
            f"Unit {action.unit_id} already activated this round "
            "(pkt 22.d.i)", code="unit_already_activated",
        )
    if actor.owner_player != state.active_player:
        raise IllegalActionError(
            f"Unit {action.unit_id} belongs to player {actor.owner_player}, "
            f"but active_player is {state.active_player} (pkt 11.a)", code="wrong_player",
        )
    if isinstance(action, ManeuverAction):
        _validate_maneuver(state, actor, action)


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
    def discriminator(item: Action) -> str | None:
        return next(
            (
                action_type
                for action_class, action_type in ACTION_TYPE_BY_CLASS.items()
                if isinstance(item, action_class)
            ),
            None,
        )

    action_type = discriminator(action)
    action_types = tuple(discriminator(item) for item in actions_taken)
    if action_type is None or any(item is None for item in action_types):
        return False
    return can_append_activation_action_type(action_type, action_types)


def _followup_rejection(
    state: BattleState, actor: UnitBlob, action: Action, taken: tuple[Action, ...],
) -> str | None:
    if action.unit_id != actor.id:
        return "different_activation_unit"
    if not _can_take_followup(action, taken):
        return "followup_not_allowed"
    if isinstance(action, ManeuverAction):
        try:
            _validate_maneuver(state, actor, action)
        except IllegalActionError as exc:
            return exc.code
    return None


def apply_activation(
    state: BattleState,
    first_action: Action,
    dice: DeterministicDice,
    sequence: int = 1,
    *,
    continuation: ActionProvider | None = None,
    on_action: ActionObserver | None = None,
    on_observation: BattleObserver | None = None,
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

    `on_observation` odbiera wynik pierwszego wyboru dostarczonego przez runner,
    decyzje `continuation` oraz automatyczne przejścia w kolejności wykonania.

    Raises:
        IllegalActionError: pierwsza akcja niedozwolona (zob. `_validate_action`).
    """
    try:
        _validate_action(state, first_action)
    except IllegalActionError as exc:
        if on_observation is not None:
            on_observation(ActionDecision(
                "choose_action", state, first_action.unit_id, (),
                snapshot_action(first_action), "rejected", reason=exc.code,
            ))
        raise
    unit_id = first_action.unit_id
    events: list[BattleEvent] = []
    seq = sequence

    seen_state = state
    state, begin_events, seq = _begin_activation(state, unit_id, seq)
    events.extend(begin_events)
    if on_observation is not None:
        on_observation(AutomaticTransition(
            "activation_started", seen_state, state, begin_events, unit_id=unit_id,
        ))

    actions_taken: list[Action] = []
    prior_actions: tuple[Action, ...] = ()
    kind: Literal["choose_action", "continue_activation"] = "choose_action"
    action = first_action
    while True:
        state_before_action = state
        observed = snapshot_action(action) if on_observation is not None else None
        try:
            state, action_events, seq = _apply_single_action(state, action, dice, seq)
        except Exception:
            if on_observation is not None:
                on_observation(ActionDecision(
                    kind, seen_state, unit_id, prior_actions, observed,
                    "error", reason="action_execution_error", before=state_before_action,
                ))
            raise
        events.extend(action_events)
        actions_taken.append(action)
        if on_observation is not None:
            on_observation(ActionDecision(
                kind, seen_state, unit_id, prior_actions, observed, "applied",
                before=state_before_action, after=state, events=snapshot_events(action_events),
            ))
        if on_action is not None:
            on_action(action, state_before_action, state)

        if continuation is None:
            stop_reason = "no_continuation_provider"
            break
        if len(actions_taken) >= MAX_ACTIONS_PER_ACTIVATION:
            stop_reason = "action_limit"
            break
        actor = next((b for b in state.blobs if b.id == unit_id), None)
        if actor is None or actor.models_alive == 0:
            stop_reason = "activation_unit_unavailable"
            break
        taken = tuple(actions_taken)
        if on_observation is not None:
            kind = "continue_activation"
            seen_state = state
            prior_actions = tuple(snapshot_action(item) for item in taken)
        try:
            nxt = continuation(state, unit_id, taken)
        except Exception:
            if on_observation is not None:
                on_observation(ActionDecision(
                    kind, seen_state, unit_id, prior_actions, None,
                    "error", reason="policy_error",
                ))
            raise
        rejection = None if nxt is None else _followup_rejection(state, actor, nxt, taken)
        if nxt is None or rejection is not None:
            stop_reason = None
            if on_observation is not None:
                on_observation(ActionDecision(
                    kind, seen_state, unit_id, prior_actions,
                    snapshot_action(nxt) if nxt is not None else None,
                    "none" if nxt is None else "rejected", reason=rejection,
                ))
            break
        action = nxt

    if on_observation is not None and stop_reason is not None:
        on_observation(AutomaticTransition(
            "activation_stopped", state, state, unit_id=unit_id, reason=stop_reason,
        ))
    before_finalization = state
    state, final_events, seq = _finalize_activation(state, unit_id, seq)
    events.extend(final_events)
    if on_observation is not None:
        on_observation(AutomaticTransition(
            "activation_finished", before_finalization, state, final_events, unit_id=unit_id,
        ))
    before_switch = state
    state, switch_events = _switch_active_player(state, sequence=seq)
    events.extend(switch_events)
    if on_observation is not None and switch_events:
        on_observation(AutomaticTransition(
            "initiative_passed", before_switch, state, switch_events,
            unit_id=unit_id, reason="activation_finished",
        ))

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
