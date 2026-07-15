from __future__ import annotations

import json

import pytest

from app.services.engine.dice import DeterministicDice
from app.services.engine.state import (
    BattleState,
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
