"""B3.9.d — Event reducers per `@register_reducer` (ADR-0010 / ADR-0046).

`apply_events(initial, events)` rekonstruuje pełen `BattleState` z sekwencji
eventów. Każdy reducer mapuje `(state, event) → state` (pure), zgodnie z
mutacjami live state w `combat.py`/`phases.py`.

Reducer-y rejestrują się jako side-effect importu tego modułu — `__init__.py`
ładuje go raz, dispatcher `_EVENT_REDUCERS` ma kompletną mapę.

**Inwariant ADR-0010 / proof-of-completeness**: dla każdej sekwencji eventów
generowanej przez engine, `apply_events(initial, events) == live_state` po
zaaplikowaniu odpowiadających akcji przez `resolver.apply`. Test:
`tests/test_engine_replay_invariant.py`.

**Scope MVP**: per-blob state (position, wounds_received, wounds_pending,
wounds_pending_precise, models_alive, is_hero_unit, status_flags, melee_balance).
Orchestration state (active_player, activations_remaining) nie jest derivowane
z eventów — to wybór resolver-a, ortogonalne do bug #6.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.engine.events import (
    EffectApplied,
    InitiativePassed,
    InterruptTriggered,
    MeleeBalanceReset,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
)
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    register_reducer,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_UFORTYFIKOWANY,
    STATUS_WYCZERPANY,
    add_status,
    remove_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_and_replace_blob(
    state: BattleState, unit_id: int, new_blob: UnitBlob
) -> BattleState:
    """Replace blob with `id == unit_id` in `state.blobs`. Pure."""
    return replace(
        state,
        blobs=tuple(new_blob if b.id == unit_id else b for b in state.blobs),
    )


def _find_blob_or_none(state: BattleState, unit_id: int) -> UnitBlob | None:
    return next((b for b in state.blobs if b.id == unit_id), None)


# ---------------------------------------------------------------------------
# MoveExecuted — position update
# ---------------------------------------------------------------------------


@register_reducer("MoveExecuted")
def _reduce_move_executed(state: BattleState, event: MoveExecuted) -> BattleState:
    blob = _find_blob_or_none(state, event.unit_id)
    if blob is None:
        return state  # defensive: missing blob (deployed/killed)
    new_blob = replace(blob, position=Position(*event.to_pos))
    return _find_and_replace_blob(state, event.unit_id, new_blob)


# ---------------------------------------------------------------------------
# ShotResolved / MeleeResolved — push wounds_received do defendera
# ---------------------------------------------------------------------------
# Algorytm replay (matching `combat._allocate_wounds_to_defender`):
# 1. ShotResolved/MeleeResolved push `wounds_dealt + wounds_precise` na
#    defender.wounds_received (cała pula trafia jako markers przed alokacją).
# 2. Następne ModelKilled events absorbują toughness_per_model wounds per
#    pokonany model + decrement models_alive. Hero kill → is_hero_unit=False.
# 3. Gdy models_alive == 0 po kill → wounds_received reset do 0 (consistent
#    z `combat.py` linia 299).
#
# Dodatkowo MeleeResolved: attacker.melee_balance += total; defender -= total.


def _push_wounds(
    state: BattleState, defender_id: int, total_wounds: int
) -> BattleState:
    if total_wounds == 0:
        return state
    defender = _find_blob_or_none(state, defender_id)
    if defender is None or defender.models_alive == 0:
        return state
    new_def = replace(defender, wounds_received=defender.wounds_received + total_wounds)
    return _find_and_replace_blob(state, defender_id, new_def)


@register_reducer("ShotResolved")
def _reduce_shot_resolved(state: BattleState, event: ShotResolved) -> BattleState:
    return _push_wounds(state, event.defender_id, event.wounds_dealt + event.wounds_precise)


@register_reducer("MeleeResolved")
def _reduce_melee_resolved(state: BattleState, event: MeleeResolved) -> BattleState:
    total = event.wounds_dealt + event.wounds_precise
    state = _push_wounds(state, event.defender_id, total)
    # Pkt 20.c bilans wręcz
    attacker = _find_blob_or_none(state, event.attacker_id)
    defender = _find_blob_or_none(state, event.defender_id)
    if attacker is not None:
        state = _find_and_replace_blob(
            state,
            event.attacker_id,
            replace(attacker, melee_balance=attacker.melee_balance + total),
        )
    if defender is not None:
        # Re-fetch po _push_wounds — wounds_received zaktualizowane.
        defender = _find_blob_or_none(state, event.defender_id)
        if defender is not None:
            state = _find_and_replace_blob(
                state,
                event.defender_id,
                replace(defender, melee_balance=defender.melee_balance - total),
            )
    return state


@register_reducer("ModelKilled")
def _reduce_model_killed(state: BattleState, event: ModelKilled) -> BattleState:
    defender = _find_blob_or_none(state, event.unit_id)
    if defender is None or defender.models_alive == 0:
        return state
    new_models = defender.models_alive - 1
    new_received = defender.wounds_received - defender.toughness_per_model
    # Klampowanie: gdy pokonany model był ostatni, wounds_received reset do 0
    # (consistent z combat.py linia 299 `new_received if new_models > 0 else 0`).
    new_received = new_received if new_models > 0 else 0
    new_hero = defender.is_hero_unit and not event.is_hero
    new_def = replace(
        defender,
        models_alive=new_models,
        wounds_received=max(0, new_received),
        is_hero_unit=new_hero,
    )
    return _find_and_replace_blob(state, event.unit_id, new_def)


# ---------------------------------------------------------------------------
# StatusAdded / StatusRemoved (B3.9.d / ADR-0046) — bug #6 fix
# ---------------------------------------------------------------------------


@register_reducer("StatusAdded")
def _reduce_status_added(state: BattleState, event: StatusAdded) -> BattleState:
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None:
        return state
    return _find_and_replace_blob(state, event.target_id, add_status(blob, event.status))


@register_reducer("StatusRemoved")
def _reduce_status_removed(state: BattleState, event: StatusRemoved) -> BattleState:
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None:
        return state
    return _find_and_replace_blob(state, event.target_id, remove_status(blob, event.status))


@register_reducer("MeleeBalanceReset")
def _reduce_melee_balance_reset(
    state: BattleState, event: MeleeBalanceReset
) -> BattleState:
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None or blob.melee_balance == 0:
        return state
    return _find_and_replace_blob(
        state, event.target_id, replace(blob, melee_balance=0)
    )


# ---------------------------------------------------------------------------
# MoraleTestPassed — status mutations z result_status
# ---------------------------------------------------------------------------
# MVP simplification: rolls / failures są audit-only; status_flags update jest
# IDEMPOTENT bo `phases._regroup_test` emituje też StatusAdded? Nie, obecna
# implementacja `_regroup_test` mutuje status_flags via _add_status + emit
# MoraleTestPassed. Reducer MoraleTestPassed musi mirrorować status updates
# żeby replay miał spójny stan.


@register_reducer("MoraleTestPassed")
def _reduce_morale_test(state: BattleState, event: MoraleTestPassed) -> BattleState:
    blob = _find_blob_or_none(state, event.unit_id)
    if blob is None:
        return state
    if event.result_status == "pass":
        return state
    if event.result_status == "broken":
        # Pkt 20.e: oddział pokonany (models_alive=0, wounds_received=0)
        new_blob = replace(blob, models_alive=0, wounds_received=0)
        return _find_and_replace_blob(state, event.unit_id, new_blob)
    new_blob = blob
    if event.result_status in ("exhausted", "exhausted_pinned"):
        new_blob = add_status(new_blob, STATUS_WYCZERPANY)
    if event.result_status in ("pinned", "exhausted_pinned"):
        new_blob = add_status(new_blob, STATUS_PRZYSZPILONY)
    return _find_and_replace_blob(state, event.unit_id, new_blob)


# ---------------------------------------------------------------------------
# EffectApplied — slug-specific status logic, większość = annotation no-op
# ---------------------------------------------------------------------------
# B3.9.d: `_apply_defend` emituje EffectApplied(defend) PLUS StatusAdded/Removed
# — reducer EffectApplied NIE duplikuje status mutacji (StatusAdded/Removed je
# obsłużą). EffectApplied(defend) tu jest no-op (annotation).
# Identycznie dla `_apply_special.discard_exhausted`.
# Inne sluggi (Mag/Łatanie/Klątwa/...) → no-op MVP, integracja w przyszłych
# iteracjach przez ACTIVE_ABILITY_REGISTRY (B3.9.e).


@register_reducer("EffectApplied")
def _reduce_effect_applied(state: BattleState, event: EffectApplied) -> BattleState:
    del event  # annotation-only w MVP B3.9.d scope
    return state


# ---------------------------------------------------------------------------
# InterruptTriggered — annotation, no state delta
# ---------------------------------------------------------------------------


@register_reducer("InterruptTriggered")
def _reduce_interrupt_triggered(
    state: BattleState, event: InterruptTriggered
) -> BattleState:
    del event
    return state


# ---------------------------------------------------------------------------
# RoundEnded — round increment + score update + is_game_over
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ObjectiveControlChanged (CR-fix A) — pkt 5.d kontrola celu
# ---------------------------------------------------------------------------


@register_reducer("ObjectiveControlChanged")
def _reduce_objective_control_changed(
    state: BattleState, event: ObjectiveControlChanged
) -> BattleState:
    """Update `state.objectives[i].controller` per zmiana z eventu.

    No-op gdy obiekt nie istnieje (defensive). Idempotent: kolejne aplikacje
    tego samego eventu kończą na tym samym controller.
    """
    new_objectives = tuple(
        replace(obj, controller=event.new_controller)
        if obj.id == event.objective_id
        else obj
        for obj in state.objectives
    )
    return replace(state, objectives=new_objectives)


# ---------------------------------------------------------------------------
# InitiativePassed (CR-fix B) — pkt 8.a active_player switch
# ---------------------------------------------------------------------------


@register_reducer("InitiativePassed")
def _reduce_initiative_passed(
    state: BattleState, event: InitiativePassed
) -> BattleState:
    """Update `state.active_player`. Idempotent."""
    return replace(state, active_player=event.new_active_player)


@register_reducer("RoundEnded")
def _reduce_round_ended(state: BattleState, event: RoundEnded) -> BattleState:
    """CR-fix F: używa `event.round_number` (authoritative) zamiast `state.round`.

    Pre-fix `is_over = state.round >= MAX_ROUND` zakładał że state.round dokładnie
    matchował round który właśnie się skończył — to było prawdą w praktyce
    (test fixtures snapshotują state PO deployment), ale dla replay-from-raw-
    initial-state (round=0) reducer dawał is_game_over o jedną rundę za późno.

    Post-fix: round_number z eventu jest single source of truth dla "który
    round się skończył"; reducer ustawia state.round = round_number + 1 (lub
    is_game_over=True przy MAX_ROUND). Idempotent: powtórna aplikacja tego
    samego eventu daje ten sam state.
    """
    from app.services.engine.phases import MAX_ROUND

    is_over = event.round_number >= MAX_ROUND
    return replace(
        state,
        round=event.round_number + 1 if not is_over else event.round_number,
        is_game_over=is_over,
        score=event.objectives_held,
    )
