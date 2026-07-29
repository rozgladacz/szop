"""B4.4d.C1b — private source-correct Strażnik activation-v2 outcome."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

import app.services.engine.interrupts as interrupts_module
from app.services.engine.activation_protocol import (
    ActivationProtocolError,
    ActivationProtocolErrorReason,
    start_activation,
    trigger_activation_interrupt,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    ActivationInterruptTriggered,
    InterruptTriggered,
    InterruptWindowOpened,
    ShotResolved,
    StatusAdded,
    event_to_json,
)
from app.services.engine.interrupts import (
    READY_INTERRUPT_HANDLERS,
    _StraznikShootPlan,
    _execute_straznik_activation_interrupt_outcomes,
)
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Position,
    TerrainCircle,
    UnitBlob,
    WeaponProfile,
    apply_events,
)
from app.services.engine.state_codec import (
    battle_state_from_json,
    battle_state_to_json,
)
from app.services.engine.status import STATUS_WYCZERPANY


RIFLE = WeaponProfile(
    slug="rifle",
    name="Rifle",
    range_inches=24,
    attacks=3,
    ap=2,
    weapon_abilities=("niezawodny", "brutalny"),
)
CANNON = WeaponProfile(
    slug="cannon",
    name="Cannon",
    range_inches=30,
    attacks=3,
    ap=3,
    weapon_abilities=("precyzyjny",),
)


def _unit(
    unit_id: int,
    owner: int,
    x: float,
    *,
    models: int = 4,
    toughness: int = 2,
    quality: int = 4,
    defense: int = 6,
    passives: tuple[str, ...] = (),
    statuses: tuple[str, ...] = (),
    ranged_weapons: tuple[WeaponProfile, ...] = (),
    location: Lokalizacja = Lokalizacja.FRONT,
) -> UnitBlob:
    return UnitBlob(
        id=unit_id,
        owner_player=owner,
        position=Position(x, 0),
        radius_inches=1.0,
        models_alive=models,
        toughness_per_model=toughness,
        quality=quality,
        defense=defense,
        passives=passives,
        status_flags=statuses,
        ranged_weapons=ranged_weapons,
        location=location,
    )


def _idle_state(
    *,
    source: UnitBlob | None = None,
    active: UnitBlob | None = None,
    secondary: UnitBlob | None = None,
    extra_blobs: tuple[UnitBlob, ...] = (),
    terrain: tuple[TerrainCircle, ...] = (),
) -> BattleState:
    source = source or _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(RIFLE, RIFLE, CANNON),
    )
    active = active or _unit(20, 1, 10)
    secondary = secondary or _unit(21, 1, 16)
    return BattleState(
        round=1,
        active_player=1,
        activations_remaining=(1, 1),
        blobs=(source, active, secondary, *extra_blobs),
        terrain=terrain,
        initiative_player=0,
    )


def _started(state: BattleState | None = None):
    return start_activation(
        state or _idle_state(),
        selected_unit_id=20,
        sequence=100,
    )


def _trigger(
    started,
    *,
    payload: object | None = None,
    dice: DeterministicDice | None = None,
    source_unit_id: int = 10,
):
    activation = started.state.activation
    return trigger_activation_interrupt(
        started.state,
        caller_player=0,
        activation_id=activation.activation_id,
        expected_activation_version=activation.version,
        expected_window_version=activation.window.version,
        source_unit_id=source_unit_id,
        ability_slug="straznik",
        payload=(
            {
                "assignments": [
                    {"weapon_slug": "rifle", "target_id": 20},
                    {"weapon_slug": "cannon", "target_id": 21},
                ]
            }
            if payload is None
            else payload
        ),
        dice=dice or DeterministicDice(73),
        sequence=started.next_sequence,
        outcome_executor=_execute_straznik_activation_interrupt_outcomes,
    )


def _assert_rejected_without_mutation(
    started,
    *,
    payload: object | None = None,
    dice: DeterministicDice | None = None,
) -> None:
    input_dice = dice or DeterministicDice(73)
    rng_before = input_dice.to_checkpoint()
    state_before = started.state
    with pytest.raises(ActivationProtocolError) as exc_info:
        _trigger(started, payload=payload, dice=input_dice)
    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert started.state == state_before
    assert input_dice.to_checkpoint() == rng_before


def _blob(state: BattleState, unit_id: int) -> UnitBlob:
    return next(blob for blob in state.blobs if blob.id == unit_id)


def test_private_plan_contract_is_frozen() -> None:
    assert READY_INTERRUPT_HANDLERS == frozenset({"rozkaz", "klatwa"})
    plan = _StraznikShootPlan(assignments=(), target_ids=())
    with pytest.raises(FrozenInstanceError):
        plan.target_ids = (20,)  # type: ignore[misc]


def test_straznik_resolves_all_profiles_targets_then_exhausts_with_replay_rng() -> None:
    initial = _idle_state()
    started = _started(initial)
    input_dice = DeterministicDice(73)
    input_rng = input_dice.to_checkpoint()

    result = _trigger(started, dice=input_dice)

    assert input_dice.to_checkpoint() == input_rng
    assert result.dice is not input_dice
    assert result.dice.to_checkpoint() != input_rng
    assert result.state == apply_events(started.state, result.events)
    assert [event.sequence for event in result.events] == list(
        range(started.next_sequence, result.next_sequence)
    )
    assert isinstance(result.events[0], ActivationInterruptTriggered)
    outcome_events = result.events[1:]
    assert sum(type(event) is InterruptTriggered for event in outcome_events) == 1
    assert [event.weapon_slug for event in outcome_events if type(event) is ShotResolved] == [
        "rifle",
        "cannon",
    ]
    assert isinstance(outcome_events[-1], StatusAdded)
    assert outcome_events[-1].target_id == 10
    assert outcome_events[-1].status == STATUS_WYCZERPANY
    assert STATUS_WYCZERPANY in _blob(result.state, 10).status_flags
    assert any(
        shot.wounds_dealt + shot.wounds_precise > 0
        for shot in outcome_events
        if type(shot) is ShotResolved
    )
    assert _blob(result.state, 20) != _blob(started.state, 20)
    assert _blob(result.state, 21) != _blob(started.state, 21)

    shots = [event for event in outcome_events if type(event) is ShotResolved]
    expected_dice = DeterministicDice.from_checkpoint(input_rng)
    expected_dice.roll_d6(12)  # rifle: 2 models × 3 attacks × 2 copies
    expected_dice.roll_d6(shots[0].hits)
    expected_dice.roll_d6(6)  # cannon: 2 models × 3 attacks
    expected_dice.roll_d6(shots[1].hits)
    assert result.dice.to_checkpoint() == expected_dice.to_checkpoint()

    restarted_state = battle_state_from_json(
        battle_state_to_json(started.state, version=2)
    )
    restarted = _trigger(
        replace(started, state=restarted_state),
        dice=DeterministicDice.from_checkpoint(input_rng),
    )
    assert restarted.state == result.state
    assert [event_to_json(event) for event in restarted.events] == [
        event_to_json(event) for event in result.events
    ]
    assert restarted.dice.to_checkpoint() == result.dice.to_checkpoint()
    future_live = DeterministicDice.from_checkpoint(result.dice.to_checkpoint())
    future_restart = DeterministicDice.from_checkpoint(
        restarted.dice.to_checkpoint()
    )
    assert future_live.roll_d6(12) == future_restart.roll_d6(12)


def test_same_canonical_profile_copies_are_one_assignment_and_one_shot_event() -> None:
    result = _trigger(
        _started(),
        payload={
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20},
            ]
        },
    )
    shots = [event for event in result.events if type(event) is ShotResolved]
    assert len(shots) == 1
    assert shots[0].weapon_slug == "rifle"
    # 2 source models × 3 attacks × 2 canonical copies; hits cannot exceed
    # 12 plus Podwójny, which this profile does not have.
    assert 0 <= shots[0].hits <= 12


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"assignments": [], "extra": True},
        {"assignments": ()},
        {"assignments": []},
        {"assignments": [{"weapon_slug": "rifle", "target_id": True}]},
        {"assignments": [{"weapon_slug": 1, "target_id": 20}]},
        {
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20, "attacks": 999}
            ]
        },
        {
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20},
                {"weapon_slug": "rifle", "target_id": 21},
            ]
        },
        {"assignments": [{"weapon_slug": "spoof", "target_id": 20}]},
    ],
)
def test_straznik_payload_is_strict_fail_closed(payload: object) -> None:
    _assert_rejected_without_mutation(_started(), payload=payload)


def test_ambiguous_canonical_profile_is_rejected_without_rng_use() -> None:
    other_rifle = replace(RIFLE, attacks=99)
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(RIFLE, other_rifle),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload={
            "assignments": [{"weapon_slug": "rifle", "target_id": 20}]
        },
    )


def test_three_targets_are_rejected() -> None:
    mortar = replace(CANNON, slug="mortar", name="Mortar")
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(RIFLE, CANNON, mortar),
    )
    third = _unit(22, 1, 18)
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source, extra_blobs=(third,))),
        payload={
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20},
                {"weapon_slug": "cannon", "target_id": 21},
                {"weapon_slug": "mortar", "target_id": 22},
            ]
        },
    )


@pytest.mark.parametrize(
    ("source_change", "target_change"),
    [
        ({"statuses": (STATUS_WYCZERPANY,)}, {}),
        ({"location": Lokalizacja.ZAPLECZE}, {}),
        ({"models": 0, "location": Lokalizacja.WYCOFANY}, {}),
        ({}, {"location": Lokalizacja.ZAPLECZE}),
        ({}, {"models": 0, "location": Lokalizacja.WYCOFANY}),
    ],
)
def test_source_and_target_must_be_live_front_and_source_not_exhausted(
    source_change: dict[str, object],
    target_change: dict[str, object],
) -> None:
    source = _unit(
        10,
        0,
        0,
        models=int(source_change.get("models", 2)),
        passives=("straznik",),
        statuses=source_change.get("statuses", ()),  # type: ignore[arg-type]
        ranged_weapons=(RIFLE,),
        location=source_change.get("location", Lokalizacja.FRONT),  # type: ignore[arg-type]
    )
    active = _unit(
        20,
        1,
        10,
        models=int(target_change.get("models", 4)),
        location=target_change.get("location", Lokalizacja.FRONT),  # type: ignore[arg-type]
    )
    state = _idle_state(source=source, active=active)
    if active.models_alive <= 0 or active.location is not Lokalizacja.FRONT:
        # Start itself is source-correct; corrupt only the already-started
        # snapshot to exercise the interrupt edge.
        valid_started = _started(_idle_state(source=source))
        state_after_start = replace(
            valid_started.state,
            blobs=tuple(
                active if blob.id == active.id else blob
                for blob in valid_started.state.blobs
            ),
        )
        _assert_rejected_without_mutation(
            replace(valid_started, state=state_after_start),
            payload={
                "assignments": [{"weapon_slug": "rifle", "target_id": 20}]
            },
        )
        return
    if source.models_alive <= 0 or source.location is not Lokalizacja.FRONT:
        with pytest.raises(ActivationProtocolError):
            _trigger(
                _started(state),
                payload={
                    "assignments": [{"weapon_slug": "rifle", "target_id": 20}]
                },
            )
        return
    _assert_rejected_without_mutation(
        _started(state),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 20}]},
    )


def test_source_must_actually_have_straznik() -> None:
    source = _unit(
        10,
        0,
        0,
        models=2,
        ranged_weapons=(RIFLE,),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 20}]},
    )


def test_straznik_requires_an_enemy_activation() -> None:
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(RIFLE,),
    )
    friendly_active = _unit(20, 0, 10)
    enemy = _unit(21, 1, 16)
    state = BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(source, friendly_active, enemy),
        terrain=(),
        initiative_player=0,
    )
    _assert_rejected_without_mutation(
        _started(state),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 21}]},
    )


def test_visible_enemy_within_two_inches_locks_the_whole_shoot() -> None:
    locking_enemy = _unit(22, 1, 4)
    _assert_rejected_without_mutation(
        _started(_idle_state(extra_blobs=(locking_enemy,)))
    )


def test_range_and_direct_line_of_sight_are_validated_before_rolls() -> None:
    short = replace(RIFLE, range_inches=5)
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(short,),
    )
    payload = {"assignments": [{"weapon_slug": "rifle", "target_id": 20}]}
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload=payload,
    )

    blocker = TerrainCircle(
        center=Position(5, 0),
        radius_inches=2,
        features=("Blokujacy",),
    )
    direct_source = replace(source, ranged_weapons=(RIFLE,))
    _assert_rejected_without_mutation(
        _started(_idle_state(source=direct_source, terrain=(blocker,))),
        payload=payload,
    )


def test_niebezposredni_bypasses_los_but_never_targets_samolot() -> None:
    indirect = replace(
        RIFLE,
        weapon_abilities=("niezawodny", "niebezposredni"),
    )
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(indirect,),
    )
    blocker = TerrainCircle(
        center=Position(5, 0),
        radius_inches=2,
        features=("Blokujacy",),
    )
    payload = {"assignments": [{"weapon_slug": "rifle", "target_id": 20}]}
    result = _trigger(
        _started(_idle_state(source=source, terrain=(blocker,))),
        payload=payload,
    )
    assert any(type(event) is ShotResolved for event in result.events)

    plane = _unit(20, 1, 10, passives=("samolot",))
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source, active=plane)),
        payload=payload,
    )


def test_samolot_range_penalty_and_namierzanie_exception() -> None:
    plane = _unit(20, 1, 20, passives=("samolot",))
    payload = {"assignments": [{"weapon_slug": "rifle", "target_id": 20}]}
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(RIFLE,),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source, active=plane)),
        payload=payload,
    )

    tracking = replace(
        RIFLE,
        weapon_abilities=("niezawodny", "namierzanie"),
    )
    tracking_source = replace(source, ranged_weapons=(tracking,))
    result = _trigger(
        _started(_idle_state(source=tracking_source, active=plane)),
        payload=payload,
    )
    assert any(type(event) is ShotResolved for event in result.events)


def test_nieporeczny_and_artillery_declaration_rules() -> None:
    awkward = replace(RIFLE, weapon_abilities=("nieporeczny",))
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(awkward,),
    )
    payload = {"assignments": [{"weapon_slug": "rifle", "target_id": 20}]}
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload=payload,
    )

    artillery = replace(
        RIFLE,
        range_inches=5,
        weapon_abilities=("artyleria",),
    )
    artillery_source = replace(source, ranged_weapons=(artillery,))
    far_active = _unit(20, 1, 30)
    spotter = _unit(11, 0, 22)
    result = _trigger(
        _started(
            _idle_state(
                source=artillery_source,
                active=far_active,
                extra_blobs=(spotter,),
            )
        ),
        payload=payload,
    )
    assert any(type(event) is ShotResolved for event in result.events)


def _single_profile_wounds(
    *,
    target_passives: tuple[str, ...] = (),
    target_statuses: tuple[str, ...] = (),
    defense: int = 8,
    seed: int = 13,
) -> int:
    weapon = WeaponProfile(
        slug="test",
        name="Test",
        range_inches=24,
        attacks=8,
        ap=0,
        weapon_abilities=("niezawodny",),
    )
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(weapon,),
    )
    target = _unit(
        21,
        1,
        16,
        models=20,
        toughness=10,
        defense=defense,
        passives=target_passives,
        statuses=target_statuses,
    )
    result = _trigger(
        _started(_idle_state(source=source, secondary=target)),
        payload={
            "assignments": [{"weapon_slug": "test", "target_id": 21}]
        },
        dice=DeterministicDice(seed),
    )
    shot = next(event for event in result.events if type(event) is ShotResolved)
    return shot.wounds_dealt + shot.wounds_precise


def test_target_defense_abilities_and_prepared_status_are_applied() -> None:
    plain = _single_profile_wounds()
    delicate = _single_profile_wounds(target_passives=("delikatny",))
    invulnerable = _single_profile_wounds(target_passives=("niewrazliwy",))
    plain_for_prepared = _single_profile_wounds(defense=6)
    prepared = _single_profile_wounds(
        target_statuses=("Przygotowany",),
        defense=6,
    )

    assert delicate > plain
    assert invulnerable < plain
    assert prepared < plain_for_prepared


def test_canonical_rozrywajacy_slug_adds_podwojny_hits() -> None:
    plain = replace(RIFLE, slug="plain", weapon_abilities=("niezawodny",))
    doubled = replace(
        plain,
        slug="double",
        weapon_abilities=("niezawodny", "rozrywajacy"),
    )

    def hits(weapon: WeaponProfile) -> int:
        source = _unit(
            10,
            0,
            0,
            models=2,
            passives=("straznik",),
            ranged_weapons=(weapon,),
        )
        result = _trigger(
            _started(_idle_state(source=source)),
            payload={
                "assignments": [
                    {"weapon_slug": weapon.slug, "target_id": 20}
                ]
            },
            dice=DeterministicDice(19),
        )
        return next(
            event.hits for event in result.events if type(event) is ShotResolved
        )

    assert hits(doubled) > hits(plain)


@pytest.mark.parametrize(
    "unsupported",
    ["rozprysk", "sterowany", "zabojczy", "zuzywalny"],
)
def test_unrepresented_weapon_state_fails_closed(unsupported: str) -> None:
    weapon = replace(RIFLE, weapon_abilities=(unsupported,))
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(weapon,),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 20}]},
    )


@pytest.mark.parametrize("unsupported", ["instynkt", "ostrozny", "mistrzostwo"])
def test_unrepresented_source_attack_passives_fail_closed(unsupported: str) -> None:
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik", unsupported),
        ranged_weapons=(RIFLE,),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 20}]},
    )


@pytest.mark.parametrize("unsupported", ["maskowanie", "okopany", "zemsta", "zwrot"])
def test_unrepresented_target_defense_passives_fail_closed(unsupported: str) -> None:
    active = _unit(20, 1, 10, passives=(unsupported,))
    _assert_rejected_without_mutation(
        _started(_idle_state(active=active)),
        payload={"assignments": [{"weapon_slug": "rifle", "target_id": 20}]},
    )


def test_active_target_may_be_defeated_without_nested_window() -> None:
    fragile_active = _unit(20, 1, 10, models=1, toughness=1, defense=9)
    result = _trigger(
        _started(_idle_state(active=fragile_active)),
        payload={
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20},
            ]
        },
        dice=DeterministicDice(1),
    )
    assert _blob(result.state, 20).models_alive == 0
    assert result.state.activation.selected_unit_id == 20
    assert result.state.activation.window is not None
    assert result.state.activation.window.interrupt_count == 1
    assert not any(type(event) is InterruptWindowOpened for event in result.events)
    assert sum(type(event) is ActivationInterruptTriggered for event in result.events) == 1


def test_event_bound_rejects_before_rng_consumption() -> None:
    huge_active = _unit(20, 1, 10, models=63, toughness=1)
    started = _started(_idle_state(active=huge_active))
    _assert_rejected_without_mutation(started)


def test_payload_and_dice_work_are_bounded_before_rng_consumption() -> None:
    _assert_rejected_without_mutation(
        _started(),
        payload={
            "assignments": [
                {"weapon_slug": "rifle", "target_id": 20}
                for _ in range(65)
            ]
        },
    )

    oversized = replace(RIFLE, attacks=6_000)
    source = _unit(
        10,
        0,
        0,
        models=2,
        passives=("straznik",),
        ranged_weapons=(oversized,),
    )
    _assert_rejected_without_mutation(
        _started(_idle_state(source=source)),
        payload={
            "assignments": [{"weapon_slug": "rifle", "target_id": 20}]
        },
    )


def test_executor_failure_after_partial_rng_use_preserves_transition_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _started()
    dice = DeterministicDice(89)
    rng_before = dice.to_checkpoint()
    original = interrupts_module._resolve_ranged_volley
    consumed: list[dict[str, object]] = []

    def fail_after_rolls(*args, **kwargs):
        result = original(*args, **kwargs)
        consumed.append(kwargs.get("dice", args[3]).to_checkpoint())
        raise RuntimeError("failure after combat RNG")

    monkeypatch.setattr(
        interrupts_module,
        "_resolve_ranged_volley",
        fail_after_rolls,
    )
    with pytest.raises(ActivationProtocolError) as exc_info:
        _trigger(started, dice=dice)
    assert exc_info.value.reason is ActivationProtocolErrorReason.ILLEGAL_INTERRUPT
    assert consumed and consumed[0] != rng_before
    assert dice.to_checkpoint() == rng_before
    assert started.state == _started().state
