"""B3.5 — testy `app/services/engine/interrupts.py`.

Pokrywa: InterruptPoint enum (1 punkt BEFORE_ACTION, pkt 11.b.i — korekta
2026-06-09 z 4 punktów ADR-0015), register/dispatch framework,
get_eligible_interrupts (filtruje pokonanych, multiple at same point),
trigger_interrupt z payload, Strażnik MVP stub.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from app.services.engine.dice import DeterministicDice
from app.services.engine.events import InterruptTriggered
from app.services.engine.interrupts import (
    _INTERRUPT_HANDLERS,
    InterruptContext,
    InterruptPoint,
    InvalidInterruptError,
    READY_INTERRUPT_HANDLERS,
    execute_ready_activation_interrupt_outcomes,
    get_eligible_interrupts,
    register_interrupt_handler,
    trigger_interrupt,
)
from app.services.engine.activation_protocol import start_activation
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Position,
    UnitBlob,
    apply_events,
)


def make_blob(
    blob_id: int = 1,
    passives: tuple[str, ...] = (),
    models_alive: int = 5,
    owner: int = 0,
    pos: tuple[float, float] = (0.0, 0.0),
    location: Lokalizacja = Lokalizacja.FRONT,
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(*pos),
        radius_inches=1.0,
        models_alive=models_alive,
        toughness_per_model=3,
        passives=passives,
        location=location,
    )


def make_state(
    blobs: tuple[UnitBlob, ...] = (),
    *,
    initiative_player: int | None = None,
) -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=blobs,
        terrain=(),
        initiative_player=initiative_player,
    )


# ---------------------------------------------------------------------------
# InterruptPoint enum — 1 punkt BEFORE_ACTION (pkt 11.b.i; korekta 2026-06-09)
# ---------------------------------------------------------------------------


def test_interrupt_point_has_single_member():
    members = {p for p in InterruptPoint}
    assert len(members) == 1


def test_interrupt_point_values():
    assert InterruptPoint.BEFORE_ACTION.value == "before_action"


# ---------------------------------------------------------------------------
# InterruptContext frozen
# ---------------------------------------------------------------------------


def test_interrupt_context_frozen():
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=1
    )
    with pytest.raises(FrozenInstanceError):
        ctx.source_unit_id = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_eligible_interrupts
# ---------------------------------------------------------------------------


def test_get_eligible_empty_state():
    """Brak blobów → pusta lista."""
    state = make_state()
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
    assert result == []


def test_get_eligible_strażnik_at_activation_start():
    """Blob z `straznik` w passives → eligible at BEFORE_ACTION."""
    blob = make_blob(blob_id=10, passives=("straznik",))
    state = make_state(blobs=(blob,))
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
    assert len(result) == 1
    eligible_blob, eligible_slug = result[0]
    assert eligible_blob.id == 10
    assert eligible_slug == "straznik"


def test_get_eligible_only_for_registered_slug():
    """Eligible tylko dla zarejestrowanego (point, slug); nie-interrupt passive → empty."""
    blob = make_blob(blob_id=10, passives=("straznik", "cierpliwy"))
    state = make_state(blobs=(blob,))
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
    # tylko straznik jest zarejestrowany jako interrupt; cierpliwy to passive modifier
    assert [slug for _, slug in result] == ["straznik"]


def test_get_eligible_blob_without_passive():
    """Blob bez interrupt passive → nie w eligible list."""
    blob = make_blob(blob_id=10, passives=("cierpliwy",))  # passive ale nie interrupt
    state = make_state(blobs=(blob,))
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
    assert result == []


def test_get_eligible_excludes_defeated_blobs():
    """models_alive=0 → nie eligible (pokonany oddział)."""
    defeated = make_blob(blob_id=10, passives=("straznik",), models_alive=0)
    state = make_state(blobs=(defeated,))
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
    assert result == []


def test_get_eligible_multiple_blobs():
    """2 oddziały z Strażnikiem → oba w eligible."""
    b1 = make_blob(blob_id=10, passives=("straznik",))
    b2 = make_blob(blob_id=20, passives=("straznik", "cierpliwy"))
    state = make_state(blobs=(b1, b2))
    result = get_eligible_interrupts(state, InterruptPoint.BEFORE_ACTION)
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
        point=InterruptPoint.BEFORE_ACTION,
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
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=1
    )
    with pytest.raises(ValueError, match="No interrupt handler"):
        trigger_interrupt(ctx, slug="nonexistent", payload={})


def test_trigger_interrupt_unregistered_slug_at_point_raises():
    """Slug niezarejestrowany w BEFORE_ACTION → raise (lookup po (point, slug)).

    `koordynacja` to przyszłe przerwanie (ADR-0015) jeszcze nie zaimplementowane —
    brak handlera. (rozkaz/klatwa/oznaczenie SĄ zarejestrowane od faza-b-order-interrupts.)
    """
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=1
    )
    with pytest.raises(ValueError, match="No interrupt handler"):
        trigger_interrupt(ctx, slug="koordynacja", payload={})


def test_trigger_interrupt_payload_propagated():
    """Payload `sequence` propaguje do `InterruptTriggered.sequence`."""
    state = make_state()
    ctx = InterruptContext(
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=1
    )
    _, events = trigger_interrupt(ctx, slug="straznik", payload={"sequence": 42})
    assert events[0].sequence == 42


def test_trigger_interrupt_strażnik_stub_does_not_mutate_state():
    """MVP stub Strażnika nie zmienia state — full Ostrzał w B3.6."""
    state = make_state(blobs=(make_blob(),))
    ctx = InterruptContext(
        state=state, point=InterruptPoint.BEFORE_ACTION, source_unit_id=1
    )
    new_state, _ = trigger_interrupt(ctx, slug="straznik", payload={})
    assert new_state is state  # MVP: identity preserved


# ---------------------------------------------------------------------------
# Duplicate handler registration raises
# ---------------------------------------------------------------------------


def test_duplicate_handler_registration_raises():
    """register dla istniejącego (point, slug) → RuntimeError."""
    with pytest.raises(RuntimeError, match="already registered"):

        @register_interrupt_handler(InterruptPoint.BEFORE_ACTION, "straznik")
        def _dup(ctx, payload):
            return ctx.state, ()


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_strażnik_in_handler_registry():
    assert (InterruptPoint.BEFORE_ACTION, "straznik") in _INTERRUPT_HANDLERS


def test_handler_registry_keyed_by_tuple():
    """Klucz to (point, slug) tuple — niezarejestrowany slug w tym punkcie → brak."""
    assert (InterruptPoint.BEFORE_ACTION, "straznik") in _INTERRUPT_HANDLERS
    assert (InterruptPoint.BEFORE_ACTION, "nonexistent") not in _INTERRUPT_HANDLERS


def _started_rozkaz_state(
    *,
    source: UnitBlob | None = None,
    target: UnitBlob | None = None,
    extra_blobs: tuple[UnitBlob, ...] = (),
) -> BattleState:
    actual_source = source or make_blob(
        blob_id=10,
        owner=0,
        passives=("rozkaz",),
        pos=(0.0, 0.0),
    )
    actual_target = target or make_blob(
        blob_id=20,
        owner=0,
        pos=(5.0, 0.0),
    )
    state = make_state(
        (actual_source, actual_target, *extra_blobs),
        initiative_player=0,
    )
    return start_activation(state, selected_unit_id=20, sequence=10).state


def _execute_rozkaz(
    state: BattleState,
    *,
    source: UnitBlob | None = None,
    payload=None,
    ability_slug: str = "rozkaz",
):
    actual_source = source or next(blob for blob in state.blobs if blob.id == 10)
    return execute_ready_activation_interrupt_outcomes(
        state=state,
        source=actual_source,
        ability_slug=ability_slug,
        payload=(
            {"target_id": 20, "ability": "niewrazliwy", "granted": True}
            if payload is None
            else payload
        ),
        dice=DeterministicDice(2026),
        sequence=20,
    )


def _started_klatwa_state() -> BattleState:
    state = make_state(
        (
            make_blob(
                blob_id=10,
                owner=0,
                passives=("klatwa",),
                pos=(0.0, 0.0),
            ),
            make_blob(blob_id=20, owner=0, pos=(2.0, 0.0)),
            make_blob(blob_id=30, owner=1, pos=(5.0, 0.0)),
        ),
        initiative_player=0,
    )
    return start_activation(state, selected_unit_id=20, sequence=10).state


def _execute_klatwa(state: BattleState, *, granted: bool = True):
    source = next(blob for blob in state.blobs if blob.id == 10)
    return execute_ready_activation_interrupt_outcomes(
        state=state,
        source=source,
        ability_slug="klatwa",
        payload={
            "target_id": 30,
            "ability": "delikatny",
            "granted": granted,
        },
        dice=DeterministicDice(2026),
        sequence=20,
    )


def test_ready_interrupt_allowlist_is_immutable_and_narrower_than_registry():
    assert READY_INTERRUPT_HANDLERS == frozenset(
        {"rozkaz", "klatwa", "straznik"}
    )
    assert {"rozkaz", "klatwa", "oznaczenie", "straznik"} <= {
        slug for _, slug in _INTERRUPT_HANDLERS
    }


def test_ready_adapter_rejects_registered_unready_handler_before_dispatch(
    monkeypatch,
):
    state = _started_rozkaz_state()
    called = False

    def forbidden_dispatch(context, payload):
        nonlocal called
        called = True
        return context.state, ()

    monkeypatch.setitem(
        _INTERRUPT_HANDLERS,
        (InterruptPoint.BEFORE_ACTION, "oznaczenie"),
        forbidden_dispatch,
    )
    with pytest.raises(InvalidInterruptError, match="not ready"):
        _execute_rozkaz(state, ability_slug="oznaczenie")
    assert called is False


@pytest.mark.parametrize("granted", [True, False])
def test_ready_klatwa_uses_internal_sequence_and_replays_exactly(granted):
    state = _started_klatwa_state()
    outcome_state, events = _execute_klatwa(state, granted=granted)

    assert [event.sequence for event in events] == [20, 21]
    assert outcome_state == apply_events(state, events)
    assert events[0].payload == {"ability": "delikatny", "granted": granted}
    target = next(blob for blob in outcome_state.blobs if blob.id == 30)
    assert target.ability_overrides == (("delikatny", granted),)
    assert outcome_state.used_interrupts_this_round == ((10, "klatwa"),)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"target_id": True, "ability": "niewrazliwy", "granted": True},
        {"target_id": "20", "ability": "niewrazliwy", "granted": True},
        {"target_id": 20, "ability": 1, "granted": True},
        {"target_id": 20, "ability": "", "granted": True},
        {"target_id": 20, "ability": "niewrazliwy", "granted": 1},
        {"target_id": 20, "ability": "niewrazliwy", "granted": "true"},
        {
            "target_id": 20,
            "ability": "niewrazliwy",
            "granted": True,
            "extra": "transport",
        },
        {
            "target_id": 20,
            "ability": "niewrazliwy",
            "granted": True,
            "sequence": 999,
        },
    ],
)
def test_ready_rozkaz_rejects_malformed_coerced_extra_or_client_sequence(payload):
    state = _started_rozkaz_state()
    with pytest.raises(InvalidInterruptError):
        _execute_rozkaz(state, payload=payload)


@pytest.mark.parametrize(
    ("ability", "granted"),
    [("niewrazliwy", False), ("nieustraszony", True)],
)
def test_ready_rozkaz_rejects_granted_direction_mismatch(ability, granted):
    state = _started_rozkaz_state()
    with pytest.raises(InvalidInterruptError, match="rozkaz_kierunek"):
        _execute_rozkaz(
            state,
            payload={"target_id": 20, "ability": ability, "granted": granted},
        )


def test_ready_rozkaz_uses_internal_sequence_and_replays_exactly():
    state = _started_rozkaz_state()
    outcome_state, events = _execute_rozkaz(state)

    assert [event.sequence for event in events] == [20, 21]
    assert outcome_state == apply_events(state, events)
    assert events[0].payload == {"ability": "niewrazliwy", "granted": True}


@pytest.mark.parametrize(
    "target",
    [
        make_blob(blob_id=30, owner=1, pos=(5.0, 0.0)),
        make_blob(blob_id=30, owner=0, pos=(5.0, 0.0), models_alive=0),
        make_blob(
            blob_id=30,
            owner=0,
            pos=(5.0, 0.0),
            location=Lokalizacja.ZAPLECZE,
        ),
        make_blob(blob_id=30, owner=0, pos=(20.0, 0.0)),
    ],
)
def test_ready_rozkaz_rejects_enemy_dead_off_field_or_out_of_range_target(target):
    state = _started_rozkaz_state(extra_blobs=(target,))
    with pytest.raises(InvalidInterruptError):
        _execute_rozkaz(
            state,
            payload={
                "target_id": 30,
                "ability": "niewrazliwy",
                "granted": True,
            },
        )


def test_ready_rozkaz_rejects_missing_target_and_noncanonical_ability():
    state = _started_rozkaz_state()
    with pytest.raises(InvalidInterruptError):
        _execute_rozkaz(
            state,
            payload={"target_id": 999, "ability": "niewrazliwy", "granted": True},
        )
    with pytest.raises(InvalidInterruptError, match="canonical rozkaz tags"):
        _execute_rozkaz(
            state,
            payload={"target_id": 20, "ability": "wolny", "granted": False},
        )


@pytest.mark.parametrize(
    "source",
    [
        make_blob(blob_id=10, owner=0, passives=(), pos=(0.0, 0.0)),
        make_blob(
            blob_id=10,
            owner=1,
            passives=("rozkaz",),
            pos=(0.0, 0.0),
        ),
        make_blob(
            blob_id=10,
            owner=0,
            passives=("rozkaz",),
            pos=(0.0, 0.0),
            models_alive=0,
        ),
        make_blob(
            blob_id=10,
            owner=0,
            passives=("rozkaz",),
            pos=(0.0, 0.0),
            location=Lokalizacja.ZAPLECZE,
        ),
    ],
)
def test_ready_adapter_rejects_source_without_slug_dead_or_off_field(source):
    state = _started_rozkaz_state(source=source)
    with pytest.raises(InvalidInterruptError):
        _execute_rozkaz(state)


def test_ready_adapter_rejects_forged_or_missing_source():
    state = _started_rozkaz_state()
    forged = replace(
        next(blob for blob in state.blobs if blob.id == 10),
        owner_player=1,
    )
    missing = make_blob(blob_id=999, passives=("rozkaz",))
    for source in (forged, missing):
        with pytest.raises(InvalidInterruptError):
            _execute_rozkaz(state, source=source)
