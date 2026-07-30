from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from app.services.engine.dice import DeterministicDice
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    AttackAbilityOverride,
    AttackState,
    BattleState,
    ChargeAttackIntent,
    InterruptWindowState,
    Lokalizacja,
    Objective,
    Position,
    ShootAttackIntent,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.state_codec import (
    BattleStateCodecError,
    _battle_state_from_json_v3,
    _battle_state_to_json_v3,
    battle_state_from_json,
    battle_state_to_json,
)


def _complete_state() -> BattleState:
    melee = WeaponProfile(
        slug="miecz",
        name="Miecz",
        range_inches=0,
        attacks=2,
        ap=1,
        attack_quality_override=3,
        weapon_abilities=("brutalny",),
    )
    ranged = WeaponProfile(
        slug="karabin",
        name="Karabin",
        range_inches=24,
        attacks=3,
        weapon_abilities=("precyzyjny", "niezawodny"),
    )
    return BattleState(
        round=3,
        active_player=1,
        activations_remaining=(2, 1),
        blobs=(
            UnitBlob(
                id=11,
                owner_player=0,
                position=Position(1.25, 2.5),
                radius_inches=1.75,
                models_alive=4,
                toughness_per_model=3,
                quality=2,
                defense=4,
                is_hero_unit=True,
                passives=("bohater", "szybki"),
                ability_overrides=(("szybki", False), ("furia", True)),
                status_flags=("Aktywowany", "Przyszpilony"),
                wounds_received=2,
                wounds_pending=1,
                wounds_pending_precise=3,
                wounds_eliminating=1,
                damage_balance=-2,
                melee_weapons=(melee,),
                ranged_weapons=(ranged,),
                location=Lokalizacja.ELIMINOWANY,
            ),
        ),
        terrain=(
            TerrainCircle(
                center=Position(8.0, 9.0),
                radius_inches=2.25,
                features=("Obronny", "Trudny"),
            ),
            TerrainLine(
                start=Position(0.0, 0.0),
                end=Position(12.0, 3.0),
                features=("Blokujacy",),
            ),
        ),
        objectives=(Objective(id=5, position=Position(6.0, 7.0), controller=1),),
        pending_effects=("efekt-a",),
        pending_interrupts=("interrupt-b",),
        score=(2, 3),
        is_game_over=True,
        initial_toughness_snapshot=((11, 12),),
        used_interrupts_this_round=((11, "rozkaz"),),
    )


def test_battle_state_json_round_trip_preserves_complete_state() -> None:
    original = _complete_state()

    json_payload = json.loads(json.dumps(battle_state_to_json(original)))
    restored = battle_state_from_json(json_payload)

    assert restored == original
    assert isinstance(restored.blobs, tuple)
    assert isinstance(restored.blobs[0], UnitBlob)
    assert isinstance(restored.blobs[0].location, Lokalizacja)
    assert isinstance(restored.terrain[0], TerrainCircle)
    assert isinstance(restored.terrain[1], TerrainLine)
    assert isinstance(restored.blobs[0].ability_overrides[0], tuple)


V1_BATTLE_STATE_FIELDS = {
    "round",
    "active_player",
    "activations_remaining",
    "blobs",
    "terrain",
    "objectives",
    "pending_effects",
    "pending_interrupts",
    "score",
    "is_game_over",
    "initial_toughness_snapshot",
    "used_interrupts_this_round",
}
V2_BATTLE_STATE_FIELDS = (
    V1_BATTLE_STATE_FIELDS
    - {"pending_interrupts"}
    | {"initiative_player", "activation"}
)
V3_BATTLE_STATE_FIELDS = V2_BATTLE_STATE_FIELDS
V2_ACTIVATION_STATE_FIELDS = {
    "activation_id",
    "version",
    "selected_unit_id",
    "controlling_player",
    "initiative_player",
    "action_count",
    "action_types",
    "phase",
    "window",
}
V3_ACTIVATION_STATE_FIELDS = V2_ACTIVATION_STATE_FIELDS | {"attack"}


def _window(
    ordinal: int,
    *,
    version: int = 1,
    priority_player: int = 0,
    passed_players: tuple[int, ...] = (),
    interrupt_count: int = 0,
) -> InterruptWindowState:
    return InterruptWindowState(
        ordinal=ordinal,
        version=version,
        priority_player=priority_player,
        passed_players=passed_players,
        interrupt_count=interrupt_count,
    )


def _activation(
    phase: ActivationPhase,
    *,
    version: int,
    action_types: tuple[str, ...],
    window: InterruptWindowState | None = None,
) -> ActivationState:
    return ActivationState(
        activation_id=41,
        version=version,
        selected_unit_id=11,
        controlling_player=1,
        initiative_player=0,
        action_count=len(action_types),
        action_types=action_types,
        phase=phase,
        window=window,
    )


def _v2_state(activation: ActivationState | None) -> BattleState:
    return replace(
        _complete_state(),
        active_player=1 if activation is not None else 0,
        pending_interrupts=(),
        initiative_player=0,
        activation=activation,
    )


def _attack_activation(
    phase: ActivationPhase,
    *,
    intent: ShootAttackIntent | ChargeAttackIntent,
    ability_overrides: tuple[AttackAbilityOverride, ...] = (),
    ordinal: int = 1,
) -> ActivationState:
    interrupt_count = len(ability_overrides)
    action_types = () if ordinal == 1 else ("defend",)
    if phase is ActivationPhase.ATTACK_WINDOW:
        attack_version = 1 + interrupt_count
        attack_window = _window(
            ordinal,
            version=attack_version,
            interrupt_count=interrupt_count,
        )
    else:
        attack_version = 3 + interrupt_count
        attack_window = None
    attack = AttackState(
        attack_id=73,
        version=attack_version,
        ordinal=ordinal,
        intent=intent,
        window=attack_window,
        ability_overrides=ability_overrides,
    )
    return ActivationState(
        activation_id=41,
        version=(3 if ordinal == 1 else 7) + attack_version,
        selected_unit_id=11,
        controlling_player=1,
        initiative_player=0,
        action_count=len(action_types),
        action_types=action_types,
        phase=phase,
        window=None,
        attack=attack,
    )


def _v3_state(activation: ActivationState | None) -> BattleState:
    return replace(
        _complete_state(),
        active_player=1 if activation is not None else 0,
        pending_interrupts=(),
        initiative_player=0,
        activation=activation,
    )


def _shoot_intent() -> ShootAttackIntent:
    return ShootAttackIntent(
        attacker_unit_id=11,
        target_unit_id=21,
        weapon_slug="karabin",
    )


def _charge_intent() -> ChargeAttackIntent:
    return ChargeAttackIntent(
        attacker_unit_id=11,
        target_unit_id=21,
        weapon_slug="miecz",
        counter_attack_declared=True,
    )


def test_default_encoder_and_historical_v1_round_trip_are_exact() -> None:
    historical_payload = json.loads(json.dumps(battle_state_to_json(_complete_state())))

    assert historical_payload["version"] == 1
    assert set(historical_payload["state"]["fields"]) == V1_BATTLE_STATE_FIELDS
    restored = battle_state_from_json(historical_payload)
    assert restored.initiative_player is None
    assert restored.activation is None
    assert battle_state_to_json(restored) == historical_payload


def test_v1_rejects_v2_fields_and_lossy_encoding() -> None:
    payload = battle_state_to_json(_complete_state())
    payload["state"]["fields"]["initiative_player"] = 0
    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(payload)

    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(_v2_state(None))


def test_v2_encoder_requires_durable_initiative() -> None:
    state = replace(_complete_state(), pending_interrupts=())

    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(state, version=2)


def test_v2_encoder_rejects_bool_in_inherited_integer_field() -> None:
    state = replace(_v2_state(None), active_player=True)

    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(state, version=2)


@pytest.mark.parametrize(
    "activation",
    [
        None,
        _activation(
            ActivationPhase.BEFORE_ACTION,
            version=1,
            action_types=(),
            window=_window(1),
        ),
        _activation(
            ActivationPhase.ACTION_READY,
            version=3,
            action_types=(),
        ),
        _activation(
            ActivationPhase.AWAITING_CONTINUATION,
            version=4,
            action_types=("defend",),
        ),
        _activation(
            ActivationPhase.BEFORE_ACTION,
            version=5,
            action_types=("defend",),
            window=_window(2),
        ),
        _activation(
            ActivationPhase.AWAITING_FINALIZATION,
            version=8,
            action_types=("defend", "maneuver"),
        ),
    ],
    ids=(
        "idle",
        "before-action-window-1",
        "action-ready",
        "awaiting-continuation",
        "before-action-window-2",
        "awaiting-finalization",
    ),
)
def test_v2_golden_checkpoint_round_trip(activation: ActivationState | None) -> None:
    state = _v2_state(activation)

    payload = json.loads(json.dumps(battle_state_to_json(state, version=2)))
    restored = battle_state_from_json(payload)

    assert payload["version"] == 2
    assert set(payload["state"]["fields"]) == V2_BATTLE_STATE_FIELDS
    assert "pending_interrupts" not in payload["state"]["fields"]
    assert restored == state
    assert restored.pending_interrupts == ()
    assert battle_state_to_json(restored, version=2) == payload


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _window(True),
        lambda: _window(0),
        lambda: _window(1, version=0),
        lambda: _window(1, priority_player=2),
        lambda: _window(1, interrupt_count=65, version=66),
        lambda: _window(
            1,
            version=3,
            priority_player=1,
            passed_players=(0, 0),
        ),
        lambda: _activation(
            ActivationPhase.BEFORE_ACTION,
            version=1,
            action_types=("invented",),
            window=_window(2),
        ),
        lambda: _activation(
            ActivationPhase.ACTION_READY,
            version=3,
            action_types=(),
            window=_window(1),
        ),
        lambda: _activation(
            ActivationPhase.BEFORE_ACTION,
            version=1,
            action_types=(),
            window=_window(2),
        ),
    ],
)
def test_activation_model_rejects_invalid_or_unreachable_state(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def _v2_before_action_payload() -> dict:
    state = _v2_state(
        _activation(
            ActivationPhase.BEFORE_ACTION,
            version=1,
            action_types=(),
            window=_window(1),
        )
    )
    return battle_state_to_json(state, version=2)


def _activation_fields(payload: dict) -> dict:
    return payload["state"]["fields"]["activation"]["fields"]


def _window_fields(payload: dict) -> dict:
    return _activation_fields(payload)["window"]["fields"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["state"]["fields"].update(initiative_player=True),
        lambda payload: payload["state"]["fields"].update(initiative_player=None),
        lambda payload: payload["state"]["fields"].update(pending_interrupts={"$tuple": []}),
        lambda payload: payload["state"]["fields"].pop("initiative_player"),
        lambda payload: payload["state"]["fields"].update(extra=None),
        lambda payload: _activation_fields(payload).update(activation_id=0),
        lambda payload: _activation_fields(payload).update(action_count=True),
        lambda payload: _activation_fields(payload).update(action_count=1),
        lambda payload: _activation_fields(payload)["action_types"]["$tuple"].append(
            "invented"
        ),
        lambda payload: _activation_fields(payload).update(
            phase={"$enum": "ActivationPhase", "value": "ACTION_READY"}
        ),
        lambda payload: _activation_fields(payload).update(
            phase={"$enum": "UnknownPhase", "value": "BEFORE_ACTION"}
        ),
        lambda payload: _activation_fields(payload).update(
            phase={"$enum": [], "value": "BEFORE_ACTION"}
        ),
        lambda payload: payload["state"]["fields"].update(
            activation={"$dataclass": "UnknownActivation", "fields": {}}
        ),
        lambda payload: _window_fields(payload).update(ordinal=2),
        lambda payload: _window_fields(payload).update(interrupt_count=65),
    ],
)
def test_v2_decoder_rejects_strict_schema_and_state_failures(mutation) -> None:
    payload = deepcopy(_v2_before_action_payload())
    mutation(payload)

    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(payload)


def test_v2_decoder_rejects_duplicate_pass() -> None:
    state = _v2_state(
        _activation(
            ActivationPhase.BEFORE_ACTION,
            version=2,
            action_types=(),
            window=_window(
                1,
                version=2,
                priority_player=1,
                passed_players=(0,),
            ),
        )
    )
    payload = battle_state_to_json(state, version=2)
    _window_fields(payload)["passed_players"]["$tuple"].append(0)

    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(payload)


def test_v2_encoder_rejects_legacy_pending_interrupts() -> None:
    state = replace(
        _complete_state(),
        initiative_player=0,
    )

    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(state, version=2)


@pytest.mark.parametrize(
    "value",
    [
        _shoot_intent(),
        _charge_intent(),
        AttackAbilityOverride(source_unit_id=12, ability_slug="furia"),
        AttackState(
            attack_id=73,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
    ],
)
def test_attack_model_types_are_frozen_and_slotted(value) -> None:
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.version = 99


@pytest.mark.parametrize(
    ("phase", "intent", "ability_overrides"),
    [
        (phase, intent, ability_overrides)
        for phase in (
            ActivationPhase.ATTACK_WINDOW,
            ActivationPhase.ATTACK_RESOLUTION_READY,
        )
        for intent in (_shoot_intent(), _charge_intent())
        for ability_overrides in (
            (),
            (AttackAbilityOverride(source_unit_id=12, ability_slug="furia"),),
        )
    ],
)
def test_v3_attack_heads_round_trip_exact_types(
    phase: ActivationPhase,
    intent: ShootAttackIntent | ChargeAttackIntent,
    ability_overrides: tuple[AttackAbilityOverride, ...],
) -> None:
    original = _v3_state(
        _attack_activation(
            phase,
            intent=intent,
            ability_overrides=ability_overrides,
        )
    )

    payload = json.loads(json.dumps(_battle_state_to_json_v3(original)))
    restored = _battle_state_from_json_v3(payload)

    assert payload["version"] == 3
    assert set(payload["state"]["fields"]) == V3_BATTLE_STATE_FIELDS
    activation_payload = payload["state"]["fields"]["activation"]["fields"]
    assert set(activation_payload) == V3_ACTIVATION_STATE_FIELDS
    assert restored == original
    assert type(restored.activation.attack.intent) is type(intent)
    assert isinstance(restored.activation.attack.ability_overrides, tuple)
    assert _battle_state_to_json_v3(restored) == payload


def test_v3_second_attack_ordinal_round_trip() -> None:
    original = _v3_state(
        _attack_activation(
            ActivationPhase.ATTACK_WINDOW,
            intent=_shoot_intent(),
            ordinal=2,
        )
    )

    restored = _battle_state_from_json_v3(
        json.loads(json.dumps(_battle_state_to_json_v3(original)))
    )

    assert restored == original
    assert restored.activation.action_count == 1
    assert restored.activation.attack.ordinal == 2


@pytest.mark.parametrize(
    "activation",
    [
        None,
        _activation(
            ActivationPhase.BEFORE_ACTION,
            version=1,
            action_types=(),
            window=_window(1),
        ),
        _activation(
            ActivationPhase.ACTION_READY,
            version=3,
            action_types=(),
        ),
        _activation(
            ActivationPhase.AWAITING_CONTINUATION,
            version=4,
            action_types=("defend",),
        ),
        _activation(
            ActivationPhase.AWAITING_FINALIZATION,
            version=8,
            action_types=("defend", "maneuver"),
        ),
    ],
)
def test_v3_preserves_non_attack_activation_heads(
    activation: ActivationState | None,
) -> None:
    original = _v3_state(activation)

    payload = _battle_state_to_json_v3(original)
    restored = _battle_state_from_json_v3(json.loads(json.dumps(payload)))

    assert restored == original
    if activation is not None:
        assert _activation_fields(payload)["attack"] is None


def test_attack_override_bound_accepts_exactly_64_items() -> None:
    overrides = tuple(
        AttackAbilityOverride(index, f"ability-{index}")
        for index in range(64)
    )

    attack = AttackState(
        attack_id=73,
        version=65,
        ordinal=1,
        intent=_shoot_intent(),
        window=_window(1, version=65, interrupt_count=64),
        ability_overrides=overrides,
    )

    assert len(attack.ability_overrides) == 64


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ShootAttackIntent(True, 2, "karabin"),
        lambda: ShootAttackIntent(-1, 2, "karabin"),
        lambda: ShootAttackIntent(1, -1, "karabin"),
        lambda: ShootAttackIntent(1, 2, ""),
        lambda: ShootAttackIntent(1, 2, "x" * 129),
        lambda: ChargeAttackIntent(1, 2, "miecz", 1),
        lambda: AttackAbilityOverride(True, "furia"),
        lambda: AttackAbilityOverride(1, ""),
        lambda: AttackState(
            attack_id=True,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=0,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=True,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=1,
            ordinal=3,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=1,
            ordinal=1,
            intent={},
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(2),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=2,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=2,
            ordinal=1,
            intent=_shoot_intent(),
            window=None,
            ability_overrides=(),
        ),
        lambda: AttackState(
            attack_id=1,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=[],
        ),
        lambda: AttackState(
            attack_id=1,
            version=2,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1, version=2, interrupt_count=1),
            ability_overrides=(
                AttackAbilityOverride(12, "furia"),
                AttackAbilityOverride(12, "furia"),
            ),
        ),
        lambda: AttackState(
            attack_id=1,
            version=1,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1),
            ability_overrides=(AttackAbilityOverride(12, "furia"),),
        ),
        lambda: AttackState(
            attack_id=1,
            version=65,
            ordinal=1,
            intent=_shoot_intent(),
            window=_window(1, version=65, interrupt_count=64),
            ability_overrides=tuple(
                AttackAbilityOverride(index, f"ability-{index}")
                for index in range(65)
            ),
        ),
    ],
)
def test_attack_model_rejects_wrong_types_duplicates_and_bounds(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def _attack(
    *,
    ordinal: int = 1,
    version: int = 1,
    window: InterruptWindowState | None = None,
) -> AttackState:
    return AttackState(
        attack_id=73,
        version=version,
        ordinal=ordinal,
        intent=_shoot_intent(),
        window=_window(ordinal) if window is None and version == 1 else window,
        ability_overrides=(),
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _activation(
            ActivationPhase.ATTACK_WINDOW,
            version=4,
            action_types=(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=4,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=_window(1),
            attack=_attack(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=6,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=_attack(version=3, window=None),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=4,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_RESOLUTION_READY,
            window=None,
            attack=_attack(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=4,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ACTION_READY,
            window=None,
            attack=_attack(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=8,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=_attack(ordinal=2),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=4,
            selected_unit_id=99,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=_attack(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=3,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=_attack(),
        ),
        lambda: ActivationState(
            activation_id=41,
            version=4,
            selected_unit_id=11,
            controlling_player=1,
            initiative_player=0,
            action_count=0,
            action_types=(),
            phase=ActivationPhase.ATTACK_WINDOW,
            window=None,
            attack=AttackState(
                attack_id=73,
                version=1,
                ordinal=1,
                intent=_shoot_intent(),
                window=_window(1, priority_player=1),
                ability_overrides=(),
            ),
        ),
    ],
)
def test_activation_model_rejects_unreachable_attack_snapshots(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def _v3_attack_payload() -> dict:
    activation = _attack_activation(
        ActivationPhase.ATTACK_WINDOW,
        intent=_shoot_intent(),
        ability_overrides=(
            AttackAbilityOverride(source_unit_id=12, ability_slug="furia"),
        ),
    )
    return _battle_state_to_json_v3(_v3_state(activation))


def _attack_fields(payload: dict) -> dict:
    return _activation_fields(payload)["attack"]["fields"]


def _intent_fields(payload: dict) -> dict:
    return _attack_fields(payload)["intent"]["fields"]


def _attack_override_fields(payload: dict) -> dict:
    return _attack_fields(payload)["ability_overrides"]["$tuple"][0]["fields"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: _activation_fields(payload).pop("attack"),
        lambda payload: _activation_fields(payload).update(extra=None),
        lambda payload: _attack_fields(payload).pop("version"),
        lambda payload: _attack_fields(payload).update(extra=None),
        lambda payload: _attack_fields(payload).update(attack_id=True),
        lambda payload: _attack_fields(payload).update(ordinal=True),
        lambda payload: _attack_fields(payload).update(
            intent={"$dataclass": "UnknownAttackIntent", "fields": {}}
        ),
        lambda payload: _intent_fields(payload).pop("weapon_slug"),
        lambda payload: _intent_fields(payload).update(extra=None),
        lambda payload: _intent_fields(payload).update(attacker_unit_id=True),
        lambda payload: _intent_fields(payload).update(weapon_slug=""),
        lambda payload: _intent_fields(payload).update(weapon_slug="x" * 129),
        lambda payload: _attack_override_fields(payload).update(source_unit_id=True),
        lambda payload: _attack_override_fields(payload).update(ability_slug=""),
        lambda payload: _activation_fields(payload).update(
            phase={
                "$enum": "ActivationPhase",
                "value": "UNKNOWN_ATTACK_PHASE",
            }
        ),
    ],
)
def test_v3_decoder_rejects_extra_missing_wrong_and_unknown_fields(mutation) -> None:
    payload = deepcopy(_v3_attack_payload())
    mutation(payload)

    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(payload)


def test_v3_decoder_rejects_non_boolean_charge_counter_attack() -> None:
    payload = _battle_state_to_json_v3(
        _v3_state(
            _attack_activation(
                ActivationPhase.ATTACK_WINDOW,
                intent=_charge_intent(),
            )
        )
    )
    _intent_fields(payload)["counter_attack_declared"] = 1

    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(payload)


def test_v3_decoder_rejects_duplicate_and_oversized_overrides() -> None:
    duplicate_payload = deepcopy(_v3_attack_payload())
    overrides = _attack_fields(duplicate_payload)["ability_overrides"]["$tuple"]
    overrides.append(deepcopy(overrides[0]))
    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(duplicate_payload)

    oversized_payload = deepcopy(_v3_attack_payload())
    override = overrides[0]
    oversized_payload_overrides = _attack_fields(oversized_payload)[
        "ability_overrides"
    ]["$tuple"]
    oversized_payload_overrides[:] = []
    for index in range(65):
        item = deepcopy(override)
        item["fields"]["source_unit_id"] = index
        item["fields"]["ability_slug"] = f"ability-{index}"
        oversized_payload_overrides.append(item)
    _attack_fields(oversized_payload)["version"] = 65
    _attack_fields(oversized_payload)["window"]["fields"]["version"] = 65
    _attack_fields(oversized_payload)["window"]["fields"]["interrupt_count"] = 64
    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(oversized_payload)


def test_v1_v2_golden_bytes_remain_frozen() -> None:
    cases = {
        "v1": (
            battle_state_to_json(_complete_state()),
            "0f3b7b8c6b2bf35aa337835909111334fcecbb479dd99ff0f1fbdfd7ef2e0804",
        ),
        "v2-idle": (
            battle_state_to_json(_v2_state(None), version=2),
            "74d4e3331dad638ae691d07a3608b3829621a03e7b41f668475e9b038b9bdd32",
        ),
        "v2-before-action": (
            _v2_before_action_payload(),
            "2b1a5a6808311fe17eeba16fa5ea107c40da009990f3fc2c4abe1d826d2dcf21",
        ),
    }

    for payload, expected_digest in cases.values():
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        assert sha256(serialized).hexdigest() == expected_digest


def test_v1_v2_reject_attack_fields_and_new_phases() -> None:
    v1_payload = battle_state_to_json(_complete_state())
    v1_payload["state"]["fields"]["attack"] = None
    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(v1_payload)

    v2_payload = _v2_before_action_payload()
    _activation_fields(v2_payload)["attack"] = None
    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(v2_payload)

    v2_payload = _v2_before_action_payload()
    _activation_fields(v2_payload)["phase"]["value"] = "ATTACK_WINDOW"
    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(v2_payload)

    attack_state = _v3_state(
        _attack_activation(
            ActivationPhase.ATTACK_WINDOW,
            intent=_shoot_intent(),
        )
    )
    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(attack_state, version=2)


def test_public_codec_entrypoints_reject_private_v3() -> None:
    state = _v3_state(
        _attack_activation(
            ActivationPhase.ATTACK_WINDOW,
            intent=_shoot_intent(),
        )
    )
    payload = _battle_state_to_json_v3(state)

    with pytest.raises(BattleStateCodecError):
        battle_state_to_json(state, version=3)
    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(payload)


def test_v3_rejects_legacy_and_unknown_registry_entries() -> None:
    payload = _v3_attack_payload()
    payload["state"]["fields"]["pending_interrupts"] = {"$tuple": []}
    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(payload)

    payload = _v3_attack_payload()
    _attack_fields(payload)["intent"]["$dataclass"] = "ActivationState"
    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(payload)


def test_v3_rejects_payload_nested_deeper_than_64() -> None:
    payload = _v3_attack_payload()
    nested: object = 3
    for _ in range(65):
        nested = {"$tuple": [nested]}
    payload["state"]["fields"]["round"] = nested

    with pytest.raises(BattleStateCodecError):
        _battle_state_from_json_v3(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(version=True),
        lambda payload: payload.update(version=999),
        lambda payload: payload["state"].update({"$dataclass": "__import__"}),
        lambda payload: payload["state"]["fields"].pop("round"),
        lambda payload: payload["state"]["fields"].update(round="three"),
    ],
)
def test_battle_state_json_rejects_unknown_or_incomplete_payload(mutation) -> None:
    payload = battle_state_to_json(_complete_state())
    mutation(payload)

    with pytest.raises(BattleStateCodecError):
        battle_state_from_json(payload)


def test_dice_checkpoint_round_trip_preserves_future_rng_sequence() -> None:
    dice = DeterministicDice(seed=987654)
    dice.roll_d6(17)

    payload = json.loads(json.dumps(dice.to_checkpoint()))
    restored = DeterministicDice.from_checkpoint(payload)

    assert restored.seed == dice.seed
    assert restored.roll_d6(100) == dice.roll_d6(100)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema": "szop.deterministic_dice",
            "version": 999,
            "seed": 1,
            "random_state": [],
        },
        {
            "schema": "szop.deterministic_dice",
            "version": True,
            "seed": 1,
            "random_state": [],
        },
        {
            "schema": "szop.deterministic_dice",
            "version": 1,
            "seed": True,
            "random_state": [],
        },
    ],
)
def test_dice_checkpoint_rejects_malformed_payload(payload) -> None:
    with pytest.raises(ValueError):
        DeterministicDice.from_checkpoint(payload)
