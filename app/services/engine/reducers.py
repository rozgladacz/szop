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
wounds_pending_precise, models_alive, is_hero_unit, status_flags, damage_balance).
Orchestration state (active_player, activations_remaining) nie jest derivowane
z eventów — to wybór resolver-a, ortogonalne do bug #6.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.engine.events import (
    ActivePlayerChanged,
    AttackAbilityOverrideApplied,
    AttackDeclared,
    AttackInterruptPriorityPassed,
    AttackInterruptTriggered,
    AttackInterruptWindowClosed,
    AttackInterruptWindowOpened,
    AttackResolved,
    ActivationActionCommitted,
    ActivationContinuationChosen,
    ActivationFinalized,
    ActivationInterruptTriggered,
    ActivationStarted,
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    EffectApplied,
    InitiativePassed,
    InitiativeTransferred,
    InterruptPriorityPassed,
    InterruptTriggered,
    InterruptWindowClosed,
    InterruptWindowOpened,
    MeleeBalanceReset,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    MoveExecuted,
    MutexCollision,
    ObjectiveControlChanged,
    RoundEnded,
    ShotResolved,
    StatusAdded,
    StatusRemoved,
)
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    AttackAbilityOverride,
    AttackState,
    BattleState,
    InterruptWindowState,
    Lokalizacja,
    Position,
    UnitBlob,
    register_reducer,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
    STATUS_PRZYSZPILONY,
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


def _activation_for_event(
    state: BattleState,
    activation_id: int,
) -> ActivationState:
    activation = state.activation
    if activation is None or activation.activation_id != activation_id:
        raise ValueError("protocol event does not match the active activation")
    return activation


def _window_for_event(
    state: BattleState,
    activation_id: int,
    window_ordinal: int,
) -> tuple[ActivationState, InterruptWindowState]:
    activation = _activation_for_event(state, activation_id)
    window = activation.window
    if window is None or window.ordinal != window_ordinal:
        raise ValueError("protocol event does not match the open interrupt window")
    return activation, window


def _attack_for_event(
    state: BattleState,
    activation_id: int,
    attack_id: int,
    attack_ordinal: int,
) -> tuple[ActivationState, AttackState]:
    activation = _activation_for_event(state, activation_id)
    attack = activation.attack
    if (
        attack is None
        or attack.attack_id != attack_id
        or attack.ordinal != attack_ordinal
    ):
        raise ValueError("protocol event does not match the pending attack")
    return activation, attack


def _attack_window_for_event(
    state: BattleState,
    activation_id: int,
    attack_id: int,
    attack_ordinal: int,
) -> tuple[ActivationState, AttackState, InterruptWindowState]:
    activation, attack = _attack_for_event(
        state,
        activation_id,
        attack_id,
        attack_ordinal,
    )
    if attack.window is None:
        raise ValueError("protocol event requires an open attack window")
    return activation, attack, attack.window


# ---------------------------------------------------------------------------
# Activation/window protocol v1 — durable replay metadata (ADR-0056)
# ---------------------------------------------------------------------------


@register_reducer("ActivationStarted")
def _reduce_activation_started(
    state: BattleState,
    event: ActivationStarted,
) -> BattleState:
    window = InterruptWindowState(
        ordinal=1,
        version=1,
        priority_player=event.initiative_player,
        passed_players=(),
        interrupt_count=0,
    )
    activation = ActivationState(
        activation_id=event.activation_id,
        version=event.activation_version,
        selected_unit_id=event.selected_unit_id,
        controlling_player=event.controlling_player,
        initiative_player=event.initiative_player,
        action_count=0,
        action_types=(),
        phase=ActivationPhase.BEFORE_ACTION,
        window=window,
    )
    return replace(state, activation=activation)


@register_reducer("InterruptWindowOpened")
def _reduce_interrupt_window_opened(
    state: BattleState,
    event: InterruptWindowOpened,
) -> BattleState:
    activation = _activation_for_event(state, event.activation_id)
    window = InterruptWindowState(
        ordinal=event.window_ordinal,
        version=event.window_version,
        priority_player=event.priority_player,
        passed_players=(),
        interrupt_count=0,
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.BEFORE_ACTION,
            window=window,
        ),
    )


@register_reducer("ActivationInterruptTriggered")
def _reduce_activation_interrupt_triggered(
    state: BattleState,
    event: ActivationInterruptTriggered,
) -> BattleState:
    activation, window = _window_for_event(
        state,
        event.activation_id,
        event.window_ordinal,
    )
    updated_window = replace(
        window,
        version=event.window_version,
        priority_player=event.priority_player,
        interrupt_count=window.interrupt_count + 1,
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            window=updated_window,
        ),
    )


@register_reducer("InterruptPriorityPassed")
def _reduce_interrupt_priority_passed(
    state: BattleState,
    event: InterruptPriorityPassed,
) -> BattleState:
    activation, window = _window_for_event(
        state,
        event.activation_id,
        event.window_ordinal,
    )
    if event.next_priority_player is None:
        return replace(
            state,
            activation=replace(
                activation,
                version=event.activation_version,
                phase=ActivationPhase.ACTION_READY,
                window=None,
            ),
        )
    updated_window = replace(
        window,
        version=event.window_version,
        priority_player=event.next_priority_player,
        passed_players=window.passed_players + (event.passed_player,),
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            window=updated_window,
        ),
    )


@register_reducer("InterruptWindowClosed")
def _reduce_interrupt_window_closed(
    state: BattleState,
    event: InterruptWindowClosed,
) -> BattleState:
    activation = _activation_for_event(state, event.activation_id)
    if activation.window is not None and activation.window.ordinal != event.window_ordinal:
        raise ValueError("protocol event does not match the open interrupt window")
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.ACTION_READY,
            window=None,
        ),
    )


@register_reducer("ActivationActionCommitted")
def _reduce_activation_action_committed(
    state: BattleState,
    event: ActivationActionCommitted,
) -> BattleState:
    activation = _activation_for_event(state, event.activation_id)
    action_types = activation.action_types + (event.action_type,)
    action_count = len(action_types)
    phase = (
        ActivationPhase.AWAITING_CONTINUATION
        if action_count == 1
        else ActivationPhase.AWAITING_FINALIZATION
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            action_count=action_count,
            action_types=action_types,
            phase=phase,
            window=None,
        ),
    )


@register_reducer("ActivationContinuationChosen")
def _reduce_activation_continuation_chosen(
    state: BattleState,
    event: ActivationContinuationChosen,
) -> BattleState:
    activation = _activation_for_event(state, event.activation_id)
    if not event.continue_activation:
        return replace(
            state,
            activation=replace(activation, version=event.activation_version),
        )
    window = InterruptWindowState(
        ordinal=2,
        version=1,
        priority_player=activation.initiative_player,
        passed_players=(),
        interrupt_count=0,
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.BEFORE_ACTION,
            window=window,
        ),
    )


@register_reducer("ActivationFinalized")
def _reduce_activation_finalized(
    state: BattleState,
    event: ActivationFinalized,
) -> BattleState:
    _activation_for_event(state, event.activation_id)
    return replace(state, activation=None)


@register_reducer("InitiativeTransferred")
def _reduce_initiative_transferred(
    state: BattleState,
    event: InitiativeTransferred,
) -> BattleState:
    return replace(state, initiative_player=event.new_initiative_player)


@register_reducer("ActivePlayerChanged")
def _reduce_active_player_changed(
    state: BattleState,
    event: ActivePlayerChanged,
) -> BattleState:
    return replace(state, active_player=event.new_active_player)


# ---------------------------------------------------------------------------
# Attack protocol v1 — private checkpoint protocol v3 (ADR-0056 section 5)
# ---------------------------------------------------------------------------


@register_reducer("AttackDeclared")
def _reduce_attack_declared(
    state: BattleState,
    event: AttackDeclared,
) -> BattleState:
    activation = _activation_for_event(state, event.activation_id)
    if (
        activation.phase is not ActivationPhase.ACTION_READY
        or activation.window is not None
        or activation.attack is not None
        or event.activation_version != activation.version + 1
        or event.attack_ordinal != activation.action_count + 1
        or event.intent.attacker_unit_id != activation.selected_unit_id
    ):
        raise ValueError("AttackDeclared does not match the activation head")
    window = InterruptWindowState(
        ordinal=event.attack_ordinal,
        version=event.attack_version,
        priority_player=activation.initiative_player,
        passed_players=(),
        interrupt_count=0,
    )
    attack = AttackState(
        attack_id=event.attack_id,
        version=event.attack_version,
        ordinal=event.attack_ordinal,
        intent=event.intent,
        window=window,
        ability_overrides=(),
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=attack,
        ),
    )


@register_reducer("AttackInterruptWindowOpened")
def _reduce_attack_interrupt_window_opened(
    state: BattleState,
    event: AttackInterruptWindowOpened,
) -> BattleState:
    activation, attack = _attack_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_WINDOW
        or event.activation_version != activation.version
        or event.attack_version != attack.version
        or attack.ability_overrides
    ):
        raise ValueError("AttackInterruptWindowOpened does not match attack head")
    window = InterruptWindowState(
        ordinal=event.attack_ordinal,
        version=event.window_version,
        priority_player=event.priority_player,
        passed_players=(),
        interrupt_count=0,
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.ATTACK_WINDOW,
            attack=replace(
                attack,
                version=event.attack_version,
                window=window,
            ),
        ),
    )


@register_reducer("AttackInterruptTriggered")
def _reduce_attack_interrupt_triggered(
    state: BattleState,
    event: AttackInterruptTriggered,
) -> BattleState:
    activation, attack, window = _attack_window_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_WINDOW
        or event.activation_version != activation.version + 1
        or event.attack_version != attack.version + 1
        or event.window_version != window.version + 1
        or event.priority_player != window.priority_player
    ):
        raise ValueError("AttackInterruptTriggered does not match attack head")
    updated_window = replace(
        window,
        version=event.window_version,
        priority_player=event.priority_player,
        interrupt_count=window.interrupt_count + 1,
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            attack=replace(
                attack,
                version=event.attack_version,
                window=updated_window,
            ),
        ),
    )


@register_reducer("AttackInterruptPriorityPassed")
def _reduce_attack_interrupt_priority_passed(
    state: BattleState,
    event: AttackInterruptPriorityPassed,
) -> BattleState:
    activation, attack, window = _attack_window_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_WINDOW
        or event.activation_version != activation.version + 1
        or event.attack_version != attack.version + 1
        or event.window_version != window.version + 1
        or event.passed_player != window.priority_player
    ):
        raise ValueError("AttackInterruptPriorityPassed does not match attack head")
    if event.next_priority_player is None:
        if window.passed_players != (1 - event.passed_player,):
            raise ValueError("closing attack pass requires the first player's pass")
        return replace(
            state,
            activation=replace(
                activation,
                version=event.activation_version,
                phase=ActivationPhase.ATTACK_RESOLUTION_READY,
                attack=replace(
                    attack,
                    version=event.attack_version,
                    window=None,
                ),
            ),
        )
    updated_window = replace(
        window,
        version=event.window_version,
        priority_player=event.next_priority_player,
        passed_players=window.passed_players + (event.passed_player,),
    )
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            attack=replace(
                attack,
                version=event.attack_version,
                window=updated_window,
            ),
        ),
    )


@register_reducer("AttackInterruptWindowClosed")
def _reduce_attack_interrupt_window_closed(
    state: BattleState,
    event: AttackInterruptWindowClosed,
) -> BattleState:
    activation, attack = _attack_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_RESOLUTION_READY
        or event.activation_version != activation.version
        or event.attack_version != attack.version
        or attack.window is not None
    ):
        raise ValueError("AttackInterruptWindowClosed does not match attack head")
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.ATTACK_RESOLUTION_READY,
            attack=replace(
                attack,
                version=event.attack_version,
                window=None,
            ),
        ),
    )


@register_reducer("AttackAbilityOverrideApplied")
def _reduce_attack_ability_override_applied(
    state: BattleState,
    event: AttackAbilityOverrideApplied,
) -> BattleState:
    activation, attack, window = _attack_window_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_WINDOW
        or event.activation_version != activation.version
        or event.attack_version != attack.version
        or event.window_version != window.version
        or event.attacker_unit_id != attack.intent.attacker_unit_id
    ):
        raise ValueError("AttackAbilityOverrideApplied does not match attack head")
    override = AttackAbilityOverride(
        source_unit_id=event.source_unit_id,
        ability_slug=event.ability_slug,
    )
    return replace(
        state,
        activation=replace(
            activation,
            attack=replace(
                attack,
                ability_overrides=attack.ability_overrides + (override,),
            ),
        ),
    )


@register_reducer("AttackResolved")
def _reduce_attack_resolved(
    state: BattleState,
    event: AttackResolved,
) -> BattleState:
    activation, attack = _attack_for_event(
        state,
        event.activation_id,
        event.attack_id,
        event.attack_ordinal,
    )
    if (
        activation.phase is not ActivationPhase.ATTACK_RESOLUTION_READY
        or attack.window is not None
        or event.activation_version != activation.version + 1
        or event.attack_version != attack.version + 1
    ):
        raise ValueError("AttackResolved does not match attack head")
    return replace(
        state,
        activation=replace(
            activation,
            version=event.activation_version,
            phase=ActivationPhase.ACTION_READY,
            window=None,
            attack=None,
        ),
    )


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
# Dodatkowo MeleeResolved: attacker.damage_balance += total; defender -= total.


def _push_wounds(
    state: BattleState,
    defender_id: int,
    total_wounds: int,
    eliminating: int = 0,
) -> BattleState:
    """Push `total_wounds` na `wounds_received` (+ `eliminating` na licznik Zguby).

    R4.Zguba: `eliminating` (rany broni Zguba) dorzucane do `wounds_eliminating`
    PRZED kolejnymi `ModelKilled` (mirror `combat.resolve_*`). Następujące
    `ModelKilled` konsumują licznik (`_reduce_model_killed`).
    """
    if total_wounds == 0 and eliminating == 0:
        return state
    defender = _find_blob_or_none(state, defender_id)
    if defender is None or defender.models_alive == 0:
        return state
    new_def = replace(
        defender,
        wounds_received=defender.wounds_received + total_wounds,
        wounds_eliminating=defender.wounds_eliminating + eliminating,
    )
    return _find_and_replace_blob(state, defender_id, new_def)


@register_reducer("ShotResolved")
def _reduce_shot_resolved(state: BattleState, event: ShotResolved) -> BattleState:
    return _push_wounds(
        state,
        event.defender_id,
        event.wounds_dealt + event.wounds_precise,
        event.wounds_eliminating,
    )


@register_reducer("MeleeResolved")
def _reduce_melee_resolved(state: BattleState, event: MeleeResolved) -> BattleState:
    total = event.wounds_dealt + event.wounds_precise
    state = _push_wounds(state, event.defender_id, total, event.wounds_eliminating)
    # Pkt 20.c bilans wręcz
    attacker = _find_blob_or_none(state, event.attacker_id)
    defender = _find_blob_or_none(state, event.defender_id)
    if attacker is not None:
        state = _find_and_replace_blob(
            state,
            event.attacker_id,
            replace(attacker, damage_balance=attacker.damage_balance + total),
        )
    if defender is not None:
        # Re-fetch po _push_wounds — wounds_received zaktualizowane.
        defender = _find_blob_or_none(state, event.defender_id)
        if defender is not None:
            state = _find_and_replace_blob(
                state,
                event.defender_id,
                replace(defender, damage_balance=defender.damage_balance - total),
            )
    return state


@register_reducer("ModelKilled")
def _reduce_model_killed(state: BattleState, event: ModelKilled) -> BattleState:
    defender = _find_blob_or_none(state, event.unit_id)
    if defender is None or defender.models_alive == 0:
        return state
    tou = defender.toughness_per_model
    new_models = defender.models_alive - 1
    wiped = new_models == 0
    # Klampowanie: gdy pokonany model był ostatni, wounds_received reset do 0
    # (consistent z combat.py `new_received if not wiped else 0`).
    new_received = max(0, defender.wounds_received - tou) if not wiped else 0
    # R4.Zguba (mirror producer): licznik Zguby maleje o `tou` per pokonany
    # model (floor 0); wipe zeruje.
    new_eliminating = max(0, defender.wounds_eliminating - tou) if not wiped else 0
    new_hero = defender.is_hero_unit and not event.is_hero
    new_def = replace(
        defender,
        models_alive=new_models,
        wounds_received=new_received,
        wounds_eliminating=new_eliminating,
        is_hero_unit=new_hero,
        # Pkt 27.b (mirror producer `combat._allocate_wounds_to_defender`):
        # pokonanie ostatniego modelu → ELIMINOWANY gdy raną Zguby
        # (`event.eliminated`, pkt 26.d), inaczej WYCOFANY (pkt 26.c). Replay
        # bit-perfect.
        location=(
            (Lokalizacja.ELIMINOWANY if event.eliminated else Lokalizacja.WYCOFANY)
            if wiped
            else defender.location
        ),
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
def _reduce_damage_balance_reset(
    state: BattleState, event: MeleeBalanceReset
) -> BattleState:
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None or blob.damage_balance == 0:
        return state
    return _find_and_replace_blob(
        state, event.target_id, replace(blob, damage_balance=0)
    )


@register_reducer("MutexCollision")
def _reduce_mutex_collision(
    state: BattleState, event: MutexCollision
) -> BattleState:
    """R5.e (resync 2026-06): odrzuca wszystkie `dropped_statuses` z oddziału.

    Mirror producer-a `phases._apply_mutex_collisions` — Przyszpilony i
    Przygotowany (pkt 22.b/c) odrzucone gdy współistnieją. Idempotentny:
    `remove_status` to no-op gdy flag nieobecny, więc powtórna aplikacja
    eventu daje ten sam state.
    """
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None:
        return state
    new_blob = blob
    for status in event.dropped_statuses:
        new_blob = remove_status(new_blob, status)
    return _find_and_replace_blob(state, event.target_id, new_blob)


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
        # Pkt 20.f.iii: oddział pokonany. Pkt 27.b/26.c → WYCOFANY (mirror
        # producer `phases._regroup_test`). Replay bit-perfect.
        new_blob = replace(
            blob,
            models_alive=0,
            wounds_received=0,
            wounds_eliminating=0,  # R4.Zguba: wipe zeruje oba liczniki (mirror producer)
            location=Lokalizacja.WYCOFANY,
        )
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
#
# WYJĄTEK — `niebezpieczny` (R5.g, finding #1 2026-06-06): rana z Niebezpiecznego
# terenu (pkt 4.c.v) NIE przechodzi przez ShotResolved/MeleeResolved (to nie
# walka), więc EffectApplied(niebezpieczny) musi sam wnieść deltę `wounds_received`
# na replay. Pushuje `wounds_inflicted` (surowa pula PRZED alokacją) na cel;
# następujące w sekwencji `ModelKilled` absorbują pełne komplety toughness.
# Mirror producer-a `phases._apply_maneuver`.


@register_reducer("EffectApplied")
def _reduce_effect_applied(state: BattleState, event: EffectApplied) -> BattleState:
    if event.slug == "niebezpieczny":
        wounds = event.payload.get("wounds_inflicted", 0)
        return _push_wounds(state, event.target_unit_id, wounds)
    return state  # annotation-only dla pozostałych slugów (MVP B3.9.d scope)


# ---------------------------------------------------------------------------
# AbilityOverrideApplied / AbilityOverridesCleared (faza-b-order-interrupts)
# ---------------------------------------------------------------------------
# Mirror producer-ów handlerów Rozkaz/Klątwa/Oznaczenie (effects.py) +
# wygaśnięcia w activation_phase (pkt 11.b.vi). `effective_passives` liczy
# efektywny zbiór z `ability_overrides` — replay bit-perfect (`ability_overrides`
# w `_BLOB_REPLAY_FIELDS`).


@register_reducer("AbilityOverrideApplied")
def _reduce_ability_override_applied(
    state: BattleState, event: AbilityOverrideApplied
) -> BattleState:
    """Dopisuje `(ability, granted)` do `target.ability_overrides`.

    Mirror handlerów Rozkaz/Klątwa/Oznaczenie. No-op gdy oddział nie istnieje.
    """
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None:
        return state
    new_overrides = blob.ability_overrides + ((event.ability, event.granted),)
    return _find_and_replace_blob(
        state, event.target_id, replace(blob, ability_overrides=new_overrides)
    )


@register_reducer("AbilityOverridesCleared")
def _reduce_ability_overrides_cleared(
    state: BattleState, event: AbilityOverridesCleared
) -> BattleState:
    """Czyści `ability_overrides` oddziału (koniec aktywacji, pkt 11.b.vi).

    Idempotentny — powtórna aplikacja na pustych override'ach = no-op.
    """
    blob = _find_blob_or_none(state, event.target_id)
    if blob is None or not blob.ability_overrides:
        return state
    return _find_and_replace_blob(
        state, event.target_id, replace(blob, ability_overrides=())
    )


# ---------------------------------------------------------------------------
# InterruptTriggered — annotation, no state delta
# ---------------------------------------------------------------------------


@register_reducer("InterruptTriggered")
def _reduce_interrupt_triggered(
    state: BattleState, event: InterruptTriggered
) -> BattleState:
    """Annotation — bez delty na blobach. Wyjątek (faza-b-order-interrupts):
    gdy event ma `consumes_round_limit` (Rozkaz/Klątwa/Oznaczenie, pkt 12)
    dopisuje `(source, slug)` do `used_interrupts_this_round` — mirror producer
    `interrupts._apply_order_like`. Generyczny: czyta flagę z eventu, nie
    hardkoduje listy slugów. Idempotentny (guard `not in`)."""
    if event.consumes_round_limit:
        key = (event.source_unit_id, event.slug)
        if key not in state.used_interrupts_this_round:
            return replace(
                state,
                used_interrupts_this_round=state.used_interrupts_this_round + (key,),
            )
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
        # faza-b-order-interrupts: reset limitu „raz na rundę" (mirror producer).
        used_interrupts_this_round=(),
    )
