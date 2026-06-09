"""faza-b-order-interrupts — Klątwa(X)/Rozkaz(X)/Oznaczenie(X) (id 45/49/50).

Faza 1: substrat temporal ability-override (effective_passives + eventy
AbilityOverrideApplied/AbilityOverridesCleared + reducery + integracja z
agregatorami effects).
"""

from __future__ import annotations

from app.services.engine.effects import EffectContext, aggregate_morale_modifier
from app.services.engine.events import (
    AbilityOverrideApplied,
    AbilityOverridesCleared,
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
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=0,
        position=Position(0.0, 0.0),
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
# Integracja z agregatorem effects — grant faktycznie zmienia modyfikator
# ---------------------------------------------------------------------------


def test_grant_nieustraszony_changes_morale_modifier():
    """Grant pasywki morale (Nieustraszony) → aggregate_morale_modifier widzi -1."""
    base = _blob(passives=())
    assert aggregate_morale_modifier(EffectContext(blob=base)) == 0
    granted = _blob(passives=(), overrides=(("nieustraszony", True),))
    assert aggregate_morale_modifier(EffectContext(blob=granted)) == -1


def test_suppress_nieustraszony_removes_morale_modifier():
    """Suppress Nieustraszony na oddziale który ją ma → modyfikator znika."""
    has = _blob(passives=("nieustraszony",))
    assert aggregate_morale_modifier(EffectContext(blob=has)) == -1
    suppressed = _blob(passives=("nieustraszony",), overrides=(("nieustraszony", False),))
    assert aggregate_morale_modifier(EffectContext(blob=suppressed)) == 0


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
