"""faza-b-order-interrupts — Klątwa(X)/Rozkaz(X)/Oznaczenie(X) (id 45/49/50).

Faza 1: substrat temporal ability-override (effective_passives + eventy
AbilityOverrideApplied/AbilityOverridesCleared + reducery + integracja z
agregatorami effects).
"""

from __future__ import annotations

import pytest

from app.services.engine.events import (
    AbilityOverrideApplied,
    AbilityOverridesCleared,
    InterruptTriggered,
)
from app.services.engine.interrupts import (
    InterruptContext,
    InterruptPoint,
    InvalidInterruptError,
    trigger_interrupt,
)
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    apply_events,
    effective_passives,
)


def _blob(
    blob_id: int = 1,
    passives: tuple[str, ...] = (),
    overrides: tuple[tuple[str, bool], ...] = (),
    owner: int = 0,
    pos: tuple[float, float] = (0.0, 0.0),
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(*pos),
        radius_inches=1.0,
        models_alive=5,
        toughness_per_model=3,
        passives=passives,
        ability_overrides=overrides,
    )


def _state(*blobs: UnitBlob) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=tuple(blobs),
        terrain=(),
    )


# ---------------------------------------------------------------------------
# Faza 2 — handlery Rozkaz/Klątwa/Oznaczenie (interrupt BEFORE_ACTION)
# ---------------------------------------------------------------------------


def _ctx(state: BattleState, source_id: int) -> InterruptContext:
    return InterruptContext(
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=source_id
    )


def test_rozkaz_grants_ability_to_ally_in_range():
    """Rozkaz(nieustraszony) na sojuszniku w 12″ → override + efekt morale."""
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0, pos=(0.0, 0.0))
    ally = _blob(blob_id=2, owner=0, pos=(5.0, 0.0))
    state = _state(source, ally)
    new_state, events = trigger_interrupt(
        _ctx(state, 1),
        slug="rozkaz",
        payload={"target_id": 2, "ability": "nieustraszony", "sequence": 1},
    )
    target = next(b for b in new_state.blobs if b.id == 2)
    assert target.ability_overrides == (("nieustraszony", True),)
    assert effective_passives(target) == ("nieustraszony",)
    assert (1, "rozkaz") in new_state.used_interrupts_this_round
    assert any(isinstance(e, AbilityOverrideApplied) for e in events)
    assert any(isinstance(e, InterruptTriggered) for e in events)


def test_rozkaz_suppress_variant_removes_ability():
    """granted=False odbiera X (wariant negatywny — pkt 12 „(nie)miał")."""
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    ally = _blob(blob_id=2, passives=("nieustraszony",), owner=0, pos=(3.0, 0.0))
    state = _state(source, ally)
    new_state, _ = trigger_interrupt(
        _ctx(state, 1),
        slug="rozkaz",
        payload={"target_id": 2, "ability": "nieustraszony", "granted": False},
    )
    target = next(b for b in new_state.blobs if b.id == 2)
    assert effective_passives(target) == ()


def test_klatwa_targets_enemy():
    """Klątwa działa na wroga w 12″."""
    source = _blob(blob_id=1, passives=("klatwa",), owner=0, pos=(0.0, 0.0))
    enemy = _blob(blob_id=2, owner=1, pos=(4.0, 0.0))
    state = _state(source, enemy)
    new_state, _ = trigger_interrupt(
        _ctx(state, 1),
        slug="klatwa",
        payload={"target_id": 2, "ability": "nieustraszony", "granted": False},
    )
    target = next(b for b in new_state.blobs if b.id == 2)
    assert target.ability_overrides == (("nieustraszony", False),)


def test_klatwa_rejects_ally():
    source = _blob(blob_id=1, passives=("klatwa",), owner=0)
    ally = _blob(blob_id=2, owner=0, pos=(3.0, 0.0))
    state = _state(source, ally)
    with pytest.raises(InvalidInterruptError, match="must be enemy"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="klatwa",
            payload={"target_id": 2, "ability": "nieustraszony"},
        )


def test_rozkaz_rejects_enemy():
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    enemy = _blob(blob_id=2, owner=1, pos=(3.0, 0.0))
    state = _state(source, enemy)
    with pytest.raises(InvalidInterruptError, match="must be ally"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="rozkaz",
            payload={"target_id": 2, "ability": "nieustraszony"},
        )


def test_order_rejects_out_of_range():
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0, pos=(0.0, 0.0))
    ally = _blob(blob_id=2, owner=0, pos=(20.0, 0.0))  # gap 18 > 12
    state = _state(source, ally)
    with pytest.raises(InvalidInterruptError, match="out of"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="rozkaz",
            payload={"target_id": 2, "ability": "nieustraszony"},
        )


def test_order_rejects_non_rozkaz_capable_ability():
    """X bez rozkaz_tak (np. mag) → odrzucone (pkt 12)."""
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    ally = _blob(blob_id=2, owner=0, pos=(3.0, 0.0))
    state = _state(source, ally)
    with pytest.raises(InvalidInterruptError, match="rozkaz_tak"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="rozkaz",
            payload={"target_id": 2, "ability": "mag"},
        )


def test_order_once_per_round_limit():
    """Druga próba tego samego (source, slug) w rundzie → odrzucona."""
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    a1 = _blob(blob_id=2, owner=0, pos=(3.0, 0.0))
    a2 = _blob(blob_id=3, owner=0, pos=(4.0, 0.0))
    state = _state(source, a1, a2)
    state, _ = trigger_interrupt(
        _ctx(state, 1),
        slug="rozkaz",
        payload={"target_id": 2, "ability": "nieustraszony"},
    )
    with pytest.raises(InvalidInterruptError, match="raz na rundę"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="rozkaz",
            payload={"target_id": 3, "ability": "nieustraszony"},
        )


def test_order_rejects_defeated_target():
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    dead = UnitBlob(
        id=2, owner_player=0, position=Position(3.0, 0.0), radius_inches=1.0,
        models_alive=0, toughness_per_model=3,
    )
    state = _state(source, dead)
    with pytest.raises(InvalidInterruptError, match="not found or defeated"):
        trigger_interrupt(
            _ctx(state, 1),
            slug="rozkaz",
            payload={"target_id": 2, "ability": "nieustraszony"},
        )


def test_order_replay_reconstructs_override_and_limit():
    """apply_events([InterruptTriggered, AbilityOverrideApplied]) odtwarza
    override na celu ORAZ used_interrupts_this_round (replay bit-perfect)."""
    source = _blob(blob_id=1, passives=("rozkaz",), owner=0)
    ally = _blob(blob_id=2, owner=0, pos=(3.0, 0.0))
    state = _state(source, ally)
    live_state, events = trigger_interrupt(
        _ctx(state, 1),
        slug="rozkaz",
        payload={"target_id": 2, "ability": "nieustraszony", "sequence": 1},
    )
    replayed = apply_events(state, events)
    target = next(b for b in replayed.blobs if b.id == 2)
    assert target.ability_overrides == (("nieustraszony", True),)
    assert replayed.used_interrupts_this_round == live_state.used_interrupts_this_round
    assert (1, "rozkaz") in replayed.used_interrupts_this_round


# ---------------------------------------------------------------------------
# Faza 3 — wygaśnięcie override'ów na końcu aktywacji (pkt 11.b.vi)
# ---------------------------------------------------------------------------


def test_activation_phase_clears_ability_overrides():
    """Po aktywacji override'y wszystkich oddziałów są wyczyszczone (pkt 11.b.vi)."""
    from app.services.engine.actions import ManeuverAction
    from app.services.engine.dice import DeterministicDice
    from app.services.engine.phases import activation_phase

    actor = _blob(blob_id=1, owner=0, pos=(0.0, 0.0))
    affected = _blob(
        blob_id=2, owner=0, pos=(5.0, 0.0), overrides=(("nieustraszony", True),)
    )
    state = _state(actor, affected)
    new_state, events = activation_phase(
        state,
        ManeuverAction(unit_id=1, target_position=Position(1.0, 0.0)),
        DeterministicDice(seed=1),
        sequence=1,
    )
    aff = next(b for b in new_state.blobs if b.id == 2)
    assert aff.ability_overrides == ()
    assert any(
        isinstance(e, AbilityOverridesCleared) and e.target_id == 2 for e in events
    )


def test_activation_phase_override_clear_replay_invariant():
    """apply_events(initial, events) odtwarza wyczyszczone override'y (bit-perfect)."""
    from app.services.engine.actions import ManeuverAction
    from app.services.engine.dice import DeterministicDice
    from app.services.engine.phases import activation_phase

    actor = _blob(blob_id=1, owner=0, pos=(0.0, 0.0))
    affected = _blob(
        blob_id=2, owner=0, pos=(5.0, 0.0), overrides=(("nieustraszony", True),)
    )
    state = _state(actor, affected)
    new_state, events = activation_phase(
        state,
        ManeuverAction(unit_id=1, target_position=Position(1.0, 0.0)),
        DeterministicDice(seed=1),
        sequence=1,
    )
    replayed = apply_events(state, events)
    for uid in (1, 2):
        live_b = next(b for b in new_state.blobs if b.id == uid)
        rep_b = next(b for b in replayed.blobs if b.id == uid)
        assert live_b.ability_overrides == rep_b.ability_overrides == ()


def test_activation_phase_no_overrides_no_clear_event():
    """Brak override'ów → brak AbilityOverridesCleared (producer emituje tylko gdy są)."""
    from app.services.engine.actions import ManeuverAction
    from app.services.engine.dice import DeterministicDice
    from app.services.engine.phases import activation_phase

    actor = _blob(blob_id=1, owner=0, pos=(0.0, 0.0))
    state = _state(actor)
    _, events = activation_phase(
        state,
        ManeuverAction(unit_id=1, target_position=Position(1.0, 0.0)),
        DeterministicDice(seed=1),
        sequence=1,
    )
    assert not any(isinstance(e, AbilityOverridesCleared) for e in events)


# ---------------------------------------------------------------------------
# effective_passives
# ---------------------------------------------------------------------------


def test_effective_passives_no_overrides_identity():
    blob = _blob(passives=("cierpliwy", "tarcza"))
    # fast-path: zwraca dokładnie blob.passives (identity)
    assert effective_passives(blob) is blob.passives


def test_effective_passives_grant_adds():
    blob = _blob(passives=("cierpliwy",), overrides=(("nieustraszony", True),))
    assert effective_passives(blob) == ("cierpliwy", "nieustraszony")


def test_effective_passives_grant_idempotent_when_present():
    blob = _blob(passives=("cierpliwy",), overrides=(("cierpliwy", True),))
    assert effective_passives(blob) == ("cierpliwy",)


def test_effective_passives_suppress_removes():
    blob = _blob(passives=("cierpliwy", "tarcza"), overrides=(("tarcza", False),))
    assert effective_passives(blob) == ("cierpliwy",)


def test_effective_passives_suppress_absent_noop():
    blob = _blob(passives=("cierpliwy",), overrides=(("tarcza", False),))
    assert effective_passives(blob) == ("cierpliwy",)


def test_effective_passives_order_last_wins_grant_then_suppress():
    blob = _blob(passives=(), overrides=(("mag", True), ("mag", False)))
    assert effective_passives(blob) == ()


def test_effective_passives_order_last_wins_suppress_then_grant():
    blob = _blob(passives=("mag",), overrides=(("mag", False), ("mag", True)))
    assert effective_passives(blob) == ("mag",)


def test_effective_passives_preserves_base_order():
    blob = _blob(
        passives=("a", "b", "c"),
        overrides=(("b", False), ("d", True)),
    )
    assert effective_passives(blob) == ("a", "c", "d")


# ---------------------------------------------------------------------------
# Integracja z effective_passives — grant/suppress faktycznie zmienia pasywki
# ---------------------------------------------------------------------------


def test_grant_nieustraszony_adds_to_effective_passives():
    """Grant pasywki (Nieustraszony) → effective_passives ją widzi (efekt
    binarny pkt 20.e konsumowany później w `phases._regroup_test`)."""
    base = _blob(passives=())
    assert "nieustraszony" not in effective_passives(base)
    granted = _blob(passives=(), overrides=(("nieustraszony", True),))
    assert "nieustraszony" in effective_passives(granted)


def test_suppress_nieustraszony_removes_from_effective_passives():
    """Suppress Nieustraszony na oddziale który ją ma → znika z effective_passives."""
    has = _blob(passives=("nieustraszony",))
    assert "nieustraszony" in effective_passives(has)
    suppressed = _blob(passives=("nieustraszony",), overrides=(("nieustraszony", False),))
    assert "nieustraszony" not in effective_passives(suppressed)


# ---------------------------------------------------------------------------
# Reducery + replay (apply_events)
# ---------------------------------------------------------------------------


def test_reduce_ability_override_applied_appends():
    state = _state(_blob(blob_id=10, passives=("cierpliwy",)))
    ev = AbilityOverrideApplied(
        sequence=1, target_id=10, ability="nieustraszony", granted=True, source_id=20
    )
    new_state = apply_events(state, [ev])
    blob = next(b for b in new_state.blobs if b.id == 10)
    assert blob.ability_overrides == (("nieustraszony", True),)
    assert effective_passives(blob) == ("cierpliwy", "nieustraszony")


def test_reduce_ability_overrides_cleared():
    state = _state(_blob(blob_id=10, overrides=(("nieustraszony", True),)))
    ev = AbilityOverridesCleared(sequence=1, target_id=10)
    new_state = apply_events(state, [ev])
    blob = next(b for b in new_state.blobs if b.id == 10)
    assert blob.ability_overrides == ()


def test_reduce_ability_overrides_cleared_idempotent_when_empty():
    state = _state(_blob(blob_id=10))
    ev = AbilityOverridesCleared(sequence=1, target_id=10)
    new_state = apply_events(state, [ev])
    blob = next(b for b in new_state.blobs if b.id == 10)
    assert blob.ability_overrides == ()


def test_replay_grant_then_clear_round_trip():
    """apply_events: grant → clear odtwarza pusty override (bit-perfect)."""
    state = _state(_blob(blob_id=10, passives=("cierpliwy",)))
    events = [
        AbilityOverrideApplied(
            sequence=1, target_id=10, ability="mag", granted=True
        ),
        AbilityOverridesCleared(sequence=2, target_id=10),
    ]
    new_state = apply_events(state, events)
    blob = next(b for b in new_state.blobs if b.id == 10)
    assert blob.ability_overrides == ()
    assert effective_passives(blob) == ("cierpliwy",)


def test_reduce_override_missing_blob_noop():
    state = _state(_blob(blob_id=10))
    ev = AbilityOverrideApplied(sequence=1, target_id=999, ability="mag", granted=True)
    new_state = apply_events(state, [ev])
    assert new_state.blobs == state.blobs
