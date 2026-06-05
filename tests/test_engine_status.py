"""B3.9.a — testy `app/services/engine/status.py`.

Pokrywa:
- `StatusFlag` enum (4 statusy MVP per `SZOP_Rozjemca.md pkt 22`)
- `str` subclass equivalence — `StatusFlag.AKTYWOWANY == "Aktywowany"` i mieszane
  porównania w `tuple[str, ...]`
- Idempotencja `add_status` / `remove_status` — no-op + identity preservation
- Wsteczna kompatybilność re-exports z `effects.py` / `phases.py` / `combat.py`
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.state import Position, UnitBlob
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_UFORTYFIKOWANY,
    STATUS_WYCZERPANY,
    StatusFlag,
    add_status,
    remove_status,
)


def _make_blob(status_flags: tuple[str, ...] = ()) -> UnitBlob:
    return UnitBlob(
        id=1,
        owner_player=0,
        position=Position(x=0.0, y=0.0),
        radius_inches=1.0,
        models_alive=3,
        toughness_per_model=3,
        status_flags=status_flags,
    )


# ---------------------------------------------------------------------------
# StatusFlag enum
# ---------------------------------------------------------------------------


def test_status_flag_has_exactly_four_members_for_mvp():
    """B3.9 MVP scope per ADR-0008: 4 statusy z pkt 22 (Aktywowany/Wyczerpany/
    Przyszpilony/Ufortyfikowany). Nowy status = zmiana scope MVP."""
    assert set(StatusFlag) == {
        StatusFlag.AKTYWOWANY,
        StatusFlag.WYCZERPANY,
        StatusFlag.PRZYSZPILONY,
        StatusFlag.UFORTYFIKOWANY,
    }


@pytest.mark.parametrize(
    ("flag", "literal"),
    [
        (StatusFlag.AKTYWOWANY, "Aktywowany"),
        (StatusFlag.WYCZERPANY, "Wyczerpany"),
        (StatusFlag.PRZYSZPILONY, "Przyszpilony"),
        (StatusFlag.UFORTYFIKOWANY, "Ufortyfikowany"),
    ],
)
def test_status_flag_equals_polish_literal(flag: StatusFlag, literal: str):
    """`StatusFlag(str, Enum)` — wartość equal bare stringowi z `SZOP_Rozjemca.md
    pkt 22`. Crucial dla wstecznej kompatybilności z `tuple[str, ...]` w
    `UnitBlob.status_flags`."""
    assert flag == literal
    assert flag.value == literal


def test_status_flag_module_aliases_point_to_enum_members():
    """`STATUS_*` aliasy są identyczne z enumem (jeden obiekt, brak drift-u)."""
    assert STATUS_AKTYWOWANY is StatusFlag.AKTYWOWANY
    assert STATUS_WYCZERPANY is StatusFlag.WYCZERPANY
    assert STATUS_PRZYSZPILONY is StatusFlag.PRZYSZPILONY
    assert STATUS_UFORTYFIKOWANY is StatusFlag.UFORTYFIKOWANY


def test_status_flag_membership_in_str_tuple():
    """`StatusFlag` member musi być wyszukiwalny w `tuple[str, ...]` zawierającym
    bare stringi — gwarancja dla call sites: `STATUS_X in blob.status_flags`."""
    flags: tuple[str, ...] = ("Aktywowany", "Wyczerpany")
    assert StatusFlag.AKTYWOWANY in flags
    assert STATUS_WYCZERPANY in flags
    assert StatusFlag.PRZYSZPILONY not in flags


# ---------------------------------------------------------------------------
# add_status — idempotencja
# ---------------------------------------------------------------------------


def test_add_status_to_empty_blob_appends():
    blob = _make_blob()
    new_blob = add_status(blob, STATUS_AKTYWOWANY)
    assert STATUS_AKTYWOWANY in new_blob.status_flags
    assert len(new_blob.status_flags) == 1


def test_add_status_preserves_existing_flags():
    blob = _make_blob(status_flags=("Aktywowany",))
    new_blob = add_status(blob, STATUS_WYCZERPANY)
    assert new_blob.status_flags == ("Aktywowany", STATUS_WYCZERPANY)


def test_add_status_idempotent_returns_same_blob_identity():
    """Idempotencja: drugie wywołanie z tym samym statusem = no-op + identity."""
    blob = _make_blob(status_flags=("Aktywowany",))
    same = add_status(blob, STATUS_AKTYWOWANY)
    assert same is blob


def test_add_status_idempotent_with_bare_string():
    """`status_flags` historycznie trzymał bare stringi — idempotencja musi
    działać przy `str ↔ StatusFlag` cross-matching."""
    blob = _make_blob(status_flags=("Aktywowany",))
    same = add_status(blob, "Aktywowany")
    assert same is blob


def test_add_status_accepts_bare_string_argument():
    blob = _make_blob()
    new_blob = add_status(blob, "Przyszpilony")
    assert "Przyszpilony" in new_blob.status_flags
    assert STATUS_PRZYSZPILONY in new_blob.status_flags


# ---------------------------------------------------------------------------
# remove_status — idempotencja
# ---------------------------------------------------------------------------


def test_remove_status_removes_existing_flag():
    blob = _make_blob(status_flags=("Aktywowany", "Wyczerpany"))
    new_blob = remove_status(blob, STATUS_WYCZERPANY)
    assert STATUS_WYCZERPANY not in new_blob.status_flags
    assert "Aktywowany" in new_blob.status_flags


def test_remove_status_idempotent_returns_same_blob_identity():
    """Idempotencja: usunięcie nieistniejącego statusu = no-op + identity."""
    blob = _make_blob(status_flags=("Aktywowany",))
    same = remove_status(blob, STATUS_WYCZERPANY)
    assert same is blob


def test_remove_status_idempotent_with_bare_string():
    blob = _make_blob(status_flags=("Aktywowany",))
    new_blob = remove_status(blob, "Aktywowany")
    assert new_blob.status_flags == ()


def test_remove_status_on_empty_status_flags():
    blob = _make_blob()
    same = remove_status(blob, STATUS_AKTYWOWANY)
    assert same is blob


# ---------------------------------------------------------------------------
# Immutability — UnitBlob frozen dataclass kontrakt
# ---------------------------------------------------------------------------


def test_add_status_does_not_mutate_input_blob():
    """`UnitBlob` jest frozen — `add_status` zwraca nowy obiekt, nie mutuje."""
    blob = _make_blob()
    add_status(blob, STATUS_AKTYWOWANY)
    assert blob.status_flags == ()


def test_remove_status_does_not_mutate_input_blob():
    blob = _make_blob(status_flags=("Aktywowany",))
    remove_status(blob, STATUS_AKTYWOWANY)
    assert blob.status_flags == ("Aktywowany",)


def test_unit_blob_status_flags_remain_immutable():
    """Sanity: po `add_status` nie da się mutować `status_flags` bezpośrednio."""
    blob = _make_blob()
    new_blob = add_status(blob, STATUS_AKTYWOWANY)
    with pytest.raises(FrozenInstanceError):
        new_blob.status_flags = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Wsteczna kompatybilność — STATUS_* re-exported z effects/phases/combat
# ---------------------------------------------------------------------------


def test_effects_module_reexports_status_constants():
    from app.services.engine import effects

    assert effects.STATUS_AKTYWOWANY is STATUS_AKTYWOWANY
    assert effects.STATUS_WYCZERPANY is STATUS_WYCZERPANY
    assert effects.STATUS_PRZYSZPILONY is STATUS_PRZYSZPILONY
    assert effects.STATUS_UFORTYFIKOWANY is STATUS_UFORTYFIKOWANY


def test_phases_module_reexports_status_constants():
    from app.services.engine import phases

    assert phases.STATUS_AKTYWOWANY is STATUS_AKTYWOWANY
    assert phases.STATUS_WYCZERPANY is STATUS_WYCZERPANY
    assert phases.STATUS_PRZYSZPILONY is STATUS_PRZYSZPILONY
    assert phases.STATUS_UFORTYFIKOWANY is STATUS_UFORTYFIKOWANY


def test_combat_module_reexports_status_wyczerpany():
    """`combat.py` używa tylko `STATUS_WYCZERPANY` (po kontrataku pkt 14.d.iv)."""
    from app.services.engine import combat

    assert combat.STATUS_WYCZERPANY is STATUS_WYCZERPANY


# ---------------------------------------------------------------------------
# R5.e (resync 2026-06) — mutex Przyszpilony↔Ufortyfikowany (pkt 22.b/c)
# ---------------------------------------------------------------------------


def _state_with(blob: UnitBlob) -> "BattleState":
    from app.services.engine.state import BattleState

    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(blob,),
        terrain=(),
    )


def test_mutex_drops_both_when_blob_has_both_flags():
    """Oddział z Przyszpilony + Ufortyfikowany → oba odrzucone + MutexCollision."""
    from app.services.engine.events import MutexCollision
    from app.services.engine.phases import _apply_mutex_collisions

    blob = _make_blob(status_flags=("Przyszpilony", "Ufortyfikowany"))
    state = _state_with(blob)
    new_state, events, next_seq = _apply_mutex_collisions(state, [1], sequence=5)

    new_blob = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_PRZYSZPILONY not in new_blob.status_flags
    assert STATUS_UFORTYFIKOWANY not in new_blob.status_flags
    assert len(events) == 1
    assert isinstance(events[0], MutexCollision)
    assert events[0].target_id == 1
    assert events[0].sequence == 5
    assert set(events[0].dropped_statuses) == {
        STATUS_PRZYSZPILONY,
        STATUS_UFORTYFIKOWANY,
    }
    assert next_seq == 6


def test_mutex_preserves_other_flags():
    """Mutex odrzuca tylko parę Przyszpilony/Ufortyfikowany — Aktywowany zostaje."""
    from app.services.engine.phases import _apply_mutex_collisions

    blob = _make_blob(
        status_flags=("Aktywowany", "Przyszpilony", "Ufortyfikowany")
    )
    new_state, _events, _seq = _apply_mutex_collisions(_state_with(blob), [1], 1)
    new_blob = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_AKTYWOWANY in new_blob.status_flags
    assert STATUS_PRZYSZPILONY not in new_blob.status_flags
    assert STATUS_UFORTYFIKOWANY not in new_blob.status_flags


@pytest.mark.parametrize(
    "flags",
    [
        (),
        ("Przyszpilony",),
        ("Ufortyfikowany",),
        ("Aktywowany", "Wyczerpany"),
    ],
)
def test_mutex_noop_when_no_collision(flags: tuple[str, ...]):
    """Brak współistnienia obu statusów → no-op (zero eventów, identyczny stan)."""
    from app.services.engine.phases import _apply_mutex_collisions

    blob = _make_blob(status_flags=flags)
    new_state, events, next_seq = _apply_mutex_collisions(_state_with(blob), [1], 7)
    new_blob = next(b for b in new_state.blobs if b.id == 1)
    assert events == ()
    assert next_seq == 7
    assert new_blob.status_flags == flags


def test_mutex_reducer_removes_both_via_apply_events():
    """Reducer `MutexCollision` w `apply_events` odrzuca oba statusy (replay)."""
    from app.services.engine.events import MutexCollision
    from app.services.engine.state import apply_events

    blob = _make_blob(status_flags=("Przyszpilony", "Ufortyfikowany"))
    initial = _state_with(blob)
    event = MutexCollision(
        sequence=1,
        target_id=1,
        dropped_statuses=(STATUS_PRZYSZPILONY, STATUS_UFORTYFIKOWANY),
    )
    replayed = apply_events(initial, [event])
    new_blob = next(b for b in replayed.blobs if b.id == 1)
    assert STATUS_PRZYSZPILONY not in new_blob.status_flags
    assert STATUS_UFORTYFIKOWANY not in new_blob.status_flags


def test_mutex_reducer_idempotent():
    """Powtórna aplikacja MutexCollision daje ten sam stan (idempotencja)."""
    from app.services.engine.events import MutexCollision
    from app.services.engine.state import apply_events

    blob = _make_blob(status_flags=("Aktywowany", "Przyszpilony", "Ufortyfikowany"))
    initial = _state_with(blob)
    event = MutexCollision(
        sequence=1,
        target_id=1,
        dropped_statuses=(STATUS_PRZYSZPILONY, STATUS_UFORTYFIKOWANY),
    )
    once = apply_events(initial, [event])
    twice = apply_events(initial, [event, event])
    assert once.blobs[0].status_flags == twice.blobs[0].status_flags


def test_mutex_producer_reducer_parity():
    """Producer (`_apply_mutex_collisions`) i reducer (`apply_events`) dają
    identyczny stan dla tej samej kolizji — proof-of-completeness ADR-0046."""
    from app.services.engine.phases import _apply_mutex_collisions
    from app.services.engine.state import apply_events

    blob = _make_blob(status_flags=("Przyszpilony", "Ufortyfikowany"))
    initial = _state_with(blob)
    live_state, events, _seq = _apply_mutex_collisions(initial, [1], 1)
    replayed = apply_events(initial, list(events))
    assert live_state.blobs[0].status_flags == replayed.blobs[0].status_flags
