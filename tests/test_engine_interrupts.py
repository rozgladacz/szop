"""B3.5 — testy `app/services/engine/interrupts.py`.

Pokrywa: InterruptPoint enum (4 wartości per ADR-0015), register/dispatch
framework, get_eligible_interrupts (filtruje pokonanych, multiple at same point),
trigger_interrupt z payload, Strażnik MVP stub.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.events import InterruptTriggered
from app.services.engine.interrupts import (
    _INTERRUPT_HANDLERS,
    InterruptContext,
    InterruptPoint,
    get_eligible_interrupts,
    register_interrupt_handler,
    trigger_interrupt,
)
from app.services.engine.state import BattleState, Position, UnitBlob


def make_blob(
    blob_id: int = 1,
    passives: tuple[str, ...] = (),
    models_alive: int = 5,
    owner: int = 0,
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(0.0, 0.0),
        radius_inches=1.0,
        models_alive=models_alive,
        toughness_per_model=3,
        passives=passives,
    )


def make_state(blobs: tuple[UnitBlob, ...] = ()) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
    )


# ---------------------------------------------------------------------------
# InterruptPoint enum — ADR-0015: 4 zamknięte punkty
# ---------------------------------------------------------------------------


def test_interrupt_point_has_4_members():
    members = {p for p in InterruptPoint}
    assert len(members) == 4


def test_interrupt_point_values():
    assert InterruptPoint.ACTIVATION_START.value == "activation_start"
    assert InterruptPoint.AFTER_ACTION.value == "after_action"
    assert InterruptPoint.BEFORE_REGROUP.value == "before_regroup"
    assert InterruptPoint.AFTER_REGROUP.value == "after_regroup"


# ---------------------------------------------------------------------------
# InterruptContext frozen
# ---------------------------------------------------------------------------


def test_interrupt_context_frozen():
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.ACTIVATION_START, source_unit_id=1
    )
    with pytest.raises(FrozenInstanceError):
        ctx.source_unit_id = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_eligible_interrupts
# ---------------------------------------------------------------------------


def test_get_eligible_empty_state():
    """Brak blobów → pusta lista."""
    state = make_state()
    result = get_eligible_interrupts(state, InterruptPoint.ACTIVATION_START)
    assert result == []


def test_get_eligible_strażnik_at_activation_start():
    """Blob z `straznik` w passives → eligible at ACTIVATION_START."""
    blob = make_blob(blob_id=10, passives=("straznik",))
    state = make_state(blobs=(blob,))
    result = get_eligible_interrupts(state, InterruptPoint.ACTIVATION_START)
    assert len(result) == 1
    eligible_blob, eligible_slug = result[0]
    assert eligible_blob.id == 10
    assert eligible_slug == "straznik"


def test_get_eligible_strażnik_not_at_other_point():
    """Strażnik tylko ACTIVATION_START; inne punkty → empty."""
    blob = make_blob(blob_id=10, passives=("straznik",))
    state = make_state(blobs=(blob,))
    for point in (
        InterruptPoint.AFTER_ACTION,
        InterruptPoint.BEFORE_REGROUP,
        InterruptPoint.AFTER_REGROUP,
    ):
        assert get_eligible_interrupts(state, point) == []


def test_get_eligible_blob_without_passive():
    """Blob bez interrupt passive → nie w eligible list."""
    blob = make_blob(blob_id=10, passives=("cierpliwy",))  # passive ale nie interrupt
    state = make_state(blobs=(blob,))
    result = get_eligible_interrupts(state, InterruptPoint.ACTIVATION_START)
    assert result == []


def test_get_eligible_excludes_defeated_blobs():
    """models_alive=0 → nie eligible (pokonany oddział)."""
    defeated = make_blob(blob_id=10, passives=("straznik",), models_alive=0)
    state = make_state(blobs=(defeated,))
    result = get_eligible_interrupts(state, InterruptPoint.ACTIVATION_START)
    assert result == []


def test_get_eligible_multiple_blobs():
    """2 oddziały z Strażnikiem → oba w eligible."""
    b1 = make_blob(blob_id=10, passives=("straznik",))
    b2 = make_blob(blob_id=20, passives=("straznik", "cierpliwy"))
    state = make_state(blobs=(b1, b2))
    result = get_eligible_interrupts(state, InterruptPoint.ACTIVATION_START)
    assert len(result) == 2
    ids = {blob.id for blob, _ in result}
    assert ids == {10, 20}


# ---------------------------------------------------------------------------
# trigger_interrupt
# ---------------------------------------------------------------------------


def test_trigger_interrupt_calls_handler():
    """trigger dla zarejestrowanej (point, slug) zwraca (state, events)."""
    blob = make_blob(blob_id=10, passives=("straznik",))
    state = make_state(blobs=(blob,))
    ctx = InterruptContext(
        state=state,
        point=InterruptPoint.ACTIVATION_START,
        source_unit_id=10,
        active_unit_id=20,
    )
    new_state, events = trigger_interrupt(ctx, slug="straznik", payload={"sequence": 5})
    assert isinstance(events, tuple)
    assert len(events) == 1
    assert isinstance(events[0], InterruptTriggered)
    assert events[0].slug == "straznik"
    assert events[0].source_unit_id == 10


def test_trigger_interrupt_unknown_slug_raises():
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.ACTIVATION_START, source_unit_id=1
    )
    with pytest.raises(ValueError, match="No interrupt handler"):
        trigger_interrupt(ctx, slug="nonexistent", payload={})


def test_trigger_interrupt_wrong_point_raises():
    """Strażnik jest tylko ACTIVATION_START; wywołanie z innym punktem → raise."""
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.AFTER_REGROUP, source_unit_id=1
    )
    with pytest.raises(ValueError, match="No interrupt handler"):
        trigger_interrupt(ctx, slug="straznik", payload={})


def test_trigger_interrupt_payload_propagated():
    """Payload `sequence` propaguje do `InterruptTriggered.sequence`."""
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.ACTIVATION_START, source_unit_id=1
    )
    _, events = trigger_interrupt(ctx, slug="straznik", payload={"sequence": 42})
    assert events[0].sequence == 42


def test_trigger_interrupt_strażnik_stub_does_not_mutate_state():
    """MVP stub Strażnika nie zmienia state — full Ostrzał w B3.6."""
    state = make_state(blobs=(make_blob(),))
    ctx = InterruptContext(
        state=state, point=InterruptPoint.ACTIVATION_START, source_unit_id=1
    )
    new_state, _ = trigger_interrupt(ctx, slug="straznik", payload={})
    assert new_state is state  # MVP: identity preserved


# ---------------------------------------------------------------------------
# Duplicate handler registration raises
# ---------------------------------------------------------------------------


def test_duplicate_handler_registration_raises():
    """register dla istniejącego (point, slug) → RuntimeError."""
    with pytest.raises(RuntimeError, match="already registered"):

        @register_interrupt_handler(InterruptPoint.ACTIVATION_START, "straznik")
        def _dup(ctx, payload):
            return ctx.state, ()


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_strażnik_in_handler_registry():
    assert (InterruptPoint.ACTIVATION_START, "straznik") in _INTERRUPT_HANDLERS


def test_handler_registry_keyed_by_tuple():
    """Klucz to (point, slug) tuple — sprawdzamy istnienie strażnika tylko at ACTIVATION_START."""
    assert (InterruptPoint.AFTER_ACTION, "straznik") not in _INTERRUPT_HANDLERS
    assert (InterruptPoint.BEFORE_REGROUP, "straznik") not in _INTERRUPT_HANDLERS
