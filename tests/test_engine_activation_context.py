"""B3.9.c — testy `ActivationContext` + `initial_toughness_snapshot` (ADR-0045).

Pokrywa 4 buggi z post-B3 code review:
- **bug #1**: regroup test używa delty `wounds_received_this_activation`, nie
  cumulative `blob.wounds_received` (pkt 20.a "w tej aktywacji").
- **bug #2**: defender szarży wykonuje regroup w aktywacji chargera (był w
  `melee_combatants`).
- **bug #3**: `_regroup_test` pkt 20.b używa `state.initial_toughness_snapshot`,
  nie post-akcji `models_alive * toughness + wounds_received` proxy.
- **bug #5**: `melee_balance` reset na obu uczestnikach starcia wręcz.

Plus: immutability `ActivationContext`, helper `initial_toughness_for`,
`_build_activation_context` delta computation.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from app.services.engine.actions import ChargeAction, ManeuverAction, ShootAction
from app.services.engine.combat import WeaponProfile
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoraleTestPassed
from app.services.engine.phases import (
    ActivationContext,
    _build_activation_context,
    _regroup_test,
    activation_phase,
)
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    build_initial_state,
    initial_toughness_for,
)


# ---------------------------------------------------------------------------
# Helpers — fixtures via build_initial_state (so snapshot is populated)
# ---------------------------------------------------------------------------


def _make_state_via_roster(
    units: list[dict] | None = None,
) -> BattleState:
    """State z 2 oddziałami (player 0 + player 1) używając `build_initial_state`."""
    if units is None:
        units = [
            {
                "owner_player": 0,
                "units": [
                    {
                        "id": 1,
                        "position": (0.0, 0.0),
                        "models": 5,
                        "toughness": 3,
                        "quality": 4,
                        "defense": 5,
                        "passives": (),
                    }
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {
                        "id": 2,
                        "position": (10.0, 0.0),
                        "models": 4,
                        "toughness": 4,
                        "quality": 3,
                        "defense": 4,
                        "passives": (),
                    }
                ],
            },
        ]
    return build_initial_state(units)


# ---------------------------------------------------------------------------
# initial_toughness_snapshot — populated in build_initial_state
# ---------------------------------------------------------------------------


def test_snapshot_populated_from_models_times_toughness():
    state = _make_state_via_roster()
    # blob 1: 5 modeli × 3 toughness = 15
    # blob 2: 4 modeli × 4 toughness = 16
    assert initial_toughness_for(state, 1) == 15
    assert initial_toughness_for(state, 2) == 16


def test_snapshot_missing_unit_returns_zero():
    """Fallback path dla test fixtures bypassujących build_initial_state."""
    state = _make_state_via_roster()
    assert initial_toughness_for(state, 999) == 0


def test_snapshot_persists_through_dataclass_replace():
    """Snapshot przeżywa `dataclasses.replace` (shared reference, frozen tuple)."""
    state = _make_state_via_roster()
    snap_before = state.initial_toughness_snapshot
    state2 = replace(state, round=5)
    assert state2.initial_toughness_snapshot is snap_before


def test_snapshot_stable_after_models_decimated():
    """Bug #3 fix — snapshot stabilny niezależnie od `models_alive` decline."""
    state = _make_state_via_roster()
    initial = initial_toughness_for(state, 1)
    # Simulate 2 models killed in earlier activation
    state2 = replace(
        state,
        blobs=tuple(
            replace(b, models_alive=3, wounds_received=0) if b.id == 1 else b
            for b in state.blobs
        ),
    )
    assert initial_toughness_for(state2, 1) == initial  # stable
    assert initial_toughness_for(state2, 1) == 15  # original 5 × 3


# ---------------------------------------------------------------------------
# ActivationContext — immutability + helpers
# ---------------------------------------------------------------------------


def test_activation_context_is_frozen():
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 2),),
        melee_combatants=frozenset({1, 2}),
    )
    with pytest.raises(FrozenInstanceError):
        ctx.actor_id = 99  # type: ignore[misc]


def test_activation_context_delta_for_lookup():
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 2), (2, 3)),
        melee_combatants=frozenset({1, 2}),
    )
    assert ctx.delta_for(1) == 2
    assert ctx.delta_for(2) == 3
    assert ctx.delta_for(99) == 0  # missing = 0


def test_activation_context_melee_combatants_is_frozenset():
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=(),
        melee_combatants=frozenset({1, 2}),
    )
    with pytest.raises(AttributeError):
        ctx.melee_combatants.add(3)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _build_activation_context — delta semantics
# ---------------------------------------------------------------------------


def test_build_context_computes_positive_delta():
    state = _make_state_via_roster()
    pre = {1: 0, 2: 0}
    # Post: blob 2 received 3 wounds
    post = replace(
        state,
        blobs=tuple(
            replace(b, wounds_received=3) if b.id == 2 else b for b in state.blobs
        ),
    )
    ctx = _build_activation_context(pre, post, actor_id=1, melee_combatants=frozenset())
    assert ctx.delta_for(2) == 3
    assert ctx.delta_for(1) == 0


def test_build_context_filters_zero_delta():
    state = _make_state_via_roster()
    pre = {1: 2, 2: 0}
    # Post: blob 1 unchanged (still 2), blob 2 got 1 wound
    post = replace(
        state,
        blobs=tuple(
            replace(b, wounds_received=2 if b.id == 1 else 1) for b in state.blobs
        ),
    )
    ctx = _build_activation_context(pre, post, actor_id=1, melee_combatants=frozenset())
    # blob 1 ma delta 0 — nie powinien być w wounds_received_this_activation
    assert ctx.delta_for(1) == 0
    assert (1, 0) not in ctx.wounds_received_this_activation
    assert ctx.delta_for(2) == 1


def test_build_context_negative_delta_clamped():
    """Pokonanie modela resetuje `wounds_received` → ujemna delta. Zignorowana
    (nie znaczy "oddział się wyleczył"). Tylko dodatnie delty trafiają do ctx."""
    state = _make_state_via_roster()
    pre = {1: 5}
    post = replace(
        state,
        blobs=tuple(
            replace(b, wounds_received=0) if b.id == 1 else b for b in state.blobs
        ),
    )
    ctx = _build_activation_context(pre, post, actor_id=1, melee_combatants=frozenset())
    assert (1, 0) not in ctx.wounds_received_this_activation


# ---------------------------------------------------------------------------
# Bug #1 — cumulative wounds NIE triggerują pkt 20.a, tylko delta
# ---------------------------------------------------------------------------


def test_bug1_cumulative_wounds_dont_trigger_regroup():
    """Bug #1: oddział z `wounds_received=2` z poprzednich aktywacji + 0 delta
    w tej NIE wykonuje testu Przegrupowania."""
    state = _make_state_via_roster()
    state = replace(
        state,
        blobs=tuple(
            replace(b, wounds_received=2) if b.id == 1 else b for b in state.blobs
        ),
    )
    # ActivationContext z 0 delty — symuluje "nic się nie stało w tej aktywacji"
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=(),
        melee_combatants=frozenset(),
    )
    _, events, _ = _regroup_test(state, 1, ctx, DeterministicDice(42), sequence=1)
    assert events == ()


def test_bug1_delta_wounds_trigger_regroup():
    """Bug #1 inverse: delta > 0 → test się wykonuje."""
    state = _make_state_via_roster()
    state = replace(
        state,
        blobs=tuple(
            replace(b, wounds_received=2) if b.id == 1 else b for b in state.blobs
        ),
    )
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 2),),
        melee_combatants=frozenset(),
    )
    _, events, _ = _regroup_test(state, 1, ctx, DeterministicDice(42), sequence=1)
    assert any(isinstance(e, MoraleTestPassed) for e in events)


# ---------------------------------------------------------------------------
# Bug #3 — initial_toughness z snapshot, nie z post-action proxy
# ---------------------------------------------------------------------------


def test_bug3_initial_toughness_from_snapshot_not_proxy():
    """Po pokonaniu 2 modeli, current toughness = 9 (3 modele × 3 tough).
    Initial w snapshot = 15 (5 × 3). Pkt 20.b: 9 ≤ 15/2 = 7.5 → False, +0 testów.

    BUG (pre-fix): proxy `models_alive*tough + wounds_received` = 3*3 + 0 = 9.
    9 ≤ 9/2 = 4.5 → False (przypadkowo OK w tym scenariuszu).

    Inny scenariusz: 1 model żyje, 0 wounds → current=3, initial=15 → 3 ≤ 7.5
    → True, +1 test. Proxy: 1*3+0=3, 3 ≤ 1.5 → False. Bug widoczny!
    """
    state = _make_state_via_roster()
    # 1 model żyje (z 5 oryginalnych), bez akumulowanych ran (kill clean).
    state = replace(
        state,
        blobs=tuple(
            replace(b, models_alive=1, wounds_received=0) if b.id == 1 else b
            for b in state.blobs
        ),
    )
    # ActivationContext z delta=1 żeby trigger testu (delta > 0 → test pkt 20.a)
    ctx = ActivationContext(
        actor_id=1,
        wounds_received_this_activation=((1, 1),),
        melee_combatants=frozenset(),
    )
    _, events, _ = _regroup_test(state, 1, ctx, DeterministicDice(42), sequence=1)
    morale = next(e for e in events if isinstance(e, MoraleTestPassed))
    # Test pkt 20.b odpalił (current=3, initial=15, 3 ≤ 7.5) → +1 test
    # Baseline: 1 (pkt 20.a) + 1 (pkt 20.b ≤½) = 2 rolls
    assert len(morale.rolls) == 2


def test_bug3_fallback_when_snapshot_empty():
    """Fallback gdy state nie ma snapshot (test fixtures direct-constructing
    BattleState bez build_initial_state) — używa proxy formuły."""
    blob = UnitBlob(
        id=1,
        owner_player=0,
        position=Position(x=0.0, y=0.0),
        radius_inches=1.0,
        models_alive=5,
        toughness_per_model=3,
        wounds_received=0,
    )
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 0),
        blobs=(blob,),
        terrain=(),
    )
    assert state.initial_toughness_snapshot == ()  # empty
    assert initial_toughness_for(state, 1) == 0  # fallback signal


# ---------------------------------------------------------------------------
# Bug #2 — defender szarży regroup-test w aktywacji chargera
# ---------------------------------------------------------------------------


def test_bug2_charge_defender_regroups_in_charger_activation():
    """Bug #2: ChargeAction defender otrzymuje rany w aktywacji chargera —
    musi wykonać test pkt 20.a w tej samej aktywacji.

    **R5.d 2026-06 update**: pkt 20.a NEW trigger = `received > dealt`. Test
    używa scenario gdzie charger trafia (Q2), ale defender (strong HP T6, low
    Q5) NIE zadaje w kontrataku (high threshold). Defender otrzymuje >0 ran,
    zadaje 0 ran w kontrataku → received > dealt → test fires.
    """
    units = [
        {
            "owner_player": 0,
            "units": [
                {
                    "id": 1,
                    "position": (0.0, 0.0),
                    "models": 5,
                    "toughness": 3,
                    "quality": 2,  # high — trafi
                    "defense": 5,
                    "passives": (),
                }
            ],
        },
        {
            "owner_player": 1,
            "units": [
                {
                    "id": 2,
                    "position": (3.0, 0.0),  # blisko, żeby Związanie zadziałało
                    "models": 5,
                    "toughness": 6,  # high HP — survives charge
                    "quality": 5,  # low — kontratak nie trafi
                    "defense": 5,
                    "passives": (),
                }
            ],
        },
    ]
    state = build_initial_state(units)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=2)
    action = ChargeAction(unit_id=1, target_id=2, weapon=weapon)
    state = replace(state, active_player=0)

    _, events = activation_phase(state, action, DeterministicDice(7))
    morale_tests = [e for e in events if isinstance(e, MoraleTestPassed)]
    # Defender (id 2) musi mieć test Przegrupowania w tej aktywacji
    # (received > dealt po fix R5.d)
    defender_morales = [e for e in morale_tests if e.unit_id == 2]
    assert len(defender_morales) >= 1, (
        f"Defender powinien zrobić test pkt 20.a (received > dealt). "
        f"Wszystkie morale events: {[(e.unit_id, e.failures) for e in morale_tests]}"
    )


# ---------------------------------------------------------------------------
# Bug #5 — melee_balance reset na obu stronach starcia
# ---------------------------------------------------------------------------


def test_bug5_melee_balance_reset_both_combatants():
    """Po szarży `melee_balance` resetowany na charger AND defender."""
    units = [
        {
            "owner_player": 0,
            "units": [
                {
                    "id": 1,
                    "position": (0.0, 0.0),
                    "models": 5,
                    "toughness": 3,
                    "quality": 2,
                    "defense": 5,
                    "passives": (),
                }
            ],
        },
        {
            "owner_player": 1,
            "units": [
                {
                    "id": 2,
                    "position": (3.0, 0.0),
                    "models": 4,
                    "toughness": 3,
                    "quality": 4,
                    "defense": 6,
                    "passives": (),
                }
            ],
        },
    ]
    state = build_initial_state(units)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=3)
    action = ChargeAction(unit_id=1, target_id=2, weapon=weapon)
    state = replace(state, active_player=0)

    new_state, _ = activation_phase(state, action, DeterministicDice(7))
    charger = next(b for b in new_state.blobs if b.id == 1)
    defender = next((b for b in new_state.blobs if b.id == 2), None)
    assert charger.melee_balance == 0
    if defender is not None and defender.models_alive > 0:
        assert defender.melee_balance == 0


def test_bug5_no_reset_for_ranged_action():
    """Ostrzał (ranged) NIE ma melee_combatants → brak reset overhead."""
    state = _make_state_via_roster()
    weapon = WeaponProfile(slug="bow", name="Bow", range_inches=24, attacks=2)
    action = ShootAction(unit_id=1, target_id=2, weapon=weapon)
    state = replace(state, active_player=0)

    new_state, _ = activation_phase(state, action, DeterministicDice(7))
    # Test: melee_balance na obu pozostaje 0 (był 0 — pure ostrzał nie zmienia)
    for b in new_state.blobs:
        assert b.melee_balance == 0
