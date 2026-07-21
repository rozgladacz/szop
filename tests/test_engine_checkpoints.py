from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from app.services.engine.dice import DeterministicDice
from app.services.engine.state import (
    ActivationPhase,
    ActivationState,
    BattleState,
    InterruptWindowState,
    Lokalizacja,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.state_codec import (
    BattleStateCodecError,
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
