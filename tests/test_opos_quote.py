from decimal import Decimal

import pytest

from app.services.opos_rules import (
    AttackProfileInput,
    AttackProfilesInput,
    QuoteValidationError,
    SpecialAbilityInput,
    UnitQuoteInput,
    calculate_unit_quote,
    rescale_points_limit,
)


def unit_input(**overrides: object) -> UnitQuoteInput:
    payload: dict[str, object] = {
        "name": "Straż",
        "models_per_unit": 1,
        "unit_copies": 1,
        "defense": 3,
        "toughness": 1,
        "profiles": AttackProfilesInput(
            melee=AttackProfileInput(dice=1, strength=0),
            short=AttackProfileInput(dice=0, strength=0),
            long=AttackProfileInput(dice=0, strength=0),
        ),
    }
    payload.update(overrides)
    return UnitQuoteInput.model_validate(payload)


def test_golden_basic_unit_has_no_intermediate_rounding() -> None:
    quote = calculate_unit_quote(unit_input())

    assert quote.toughness_sum == Decimal("1")
    assert quote.effective_defense == Decimal("3")
    assert quote.defense_multiplier == Decimal("1.24")
    assert quote.base_cost == Decimal("7.44")
    assert quote.weapon_cost == Decimal("7.2")
    assert quote.raw_unit_cost == Decimal("14.7864")
    assert quote.rounded_unit_cost == Decimal("15")


def test_models_and_copies_are_applied_at_distinct_stages() -> None:
    quote = calculate_unit_quote(unit_input(models_per_unit=3, unit_copies=4))

    assert quote.toughness_sum == Decimal("3")
    assert quote.base_cost == Decimal("22.32")
    assert quote.weapon_cost == Decimal("21.6")
    assert quote.rounded_unit_cost == Decimal("44")
    assert quote.entry_cost == Decimal("176")


def test_simple_points_divide_raw_cost_before_half_up_rounding() -> None:
    regular = calculate_unit_quote(unit_input(models_per_unit=25, defense=5, toughness=6))
    simple = calculate_unit_quote(
        unit_input(
            models_per_unit=25,
            defense=5,
            toughness=6,
            simple_points_enabled=True,
        )
    )

    assert simple.points_divisor == Decimal("10")
    assert simple.raw_unit_cost == regular.raw_unit_cost / Decimal("10")
    assert simple.raw_unit_cost == Decimal("238.50000")
    assert simple.rounded_unit_cost == Decimal("239")
    assert simple.base_cost == regular.base_cost / Decimal("10")


def test_points_limit_tracks_simple_points_scale_with_half_up_rounding() -> None:
    assert rescale_points_limit(505, from_simple=False, to_simple=True) == 51
    assert rescale_points_limit(51, from_simple=True, to_simple=False) == 510
    assert rescale_points_limit(None, from_simple=False, to_simple=True) is None


def test_small_battle_uses_doubled_standard_toughness_list() -> None:
    accepted = calculate_unit_quote(
        unit_input(toughness=18, small_battle_enabled=True)
    )
    assert accepted.toughness_sum == Decimal("18")

    with pytest.raises(QuoteValidationError, match="Toughness"):
        calculate_unit_quote(
            unit_input(toughness=1, small_battle_enabled=True)
        )


def test_hero_is_applied_before_patching() -> None:
    quote = calculate_unit_quote(
        unit_input(
            models_per_unit=2,
            toughness=3,
            passive_abilities=("hero",),
            special_abilities=(SpecialAbilityInput(slug="patching"),),
        )
    )

    assert quote.toughness_sum == Decimal("15")


def test_airplane_subtracts_one_from_ability_cost() -> None:
    regular = calculate_unit_quote(unit_input())
    airplane = calculate_unit_quote(unit_input(passive_abilities=("airplane",)))

    assert airplane.ability_cost_modifier == Decimal("-1")
    assert airplane.base_cost < regular.base_cost


def test_deadly_uses_multiplier_four() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0, abilities=("deadly",)),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            )
        )
    )

    assert quote.profiles[0].ability_multiplier == Decimal("4")
    assert quote.profiles[0].cost_per_model == Decimal("28.8")


def test_charge_and_prepared_only_affect_their_ranges() -> None:
    quote = calculate_unit_quote(
        unit_input(
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(
                    dice=1, strength=0, abilities=("charge",)
                ),
                short=AttackProfileInput(
                    dice=1, strength=0, abilities=("prepared",)
                ),
                long=AttackProfileInput(
                    dice=1, strength=0, abilities=("prepared",)
                ),
            ),
        )
    )

    assert [item.ability_multiplier for item in quote.profiles] == [
        Decimal("1.4"), Decimal("1.4"), Decimal("1.4"),
    ]


def test_order_is_ten_percent_of_base() -> None:
    quote = calculate_unit_quote(
        unit_input(special_abilities=(SpecialAbilityInput(slug="order"),))
    )
    assert quote.order_cost == quote.base_cost * Decimal("0.1")


def test_aura_cost_is_raw_delta_with_minimum_plus_one_equivalent() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(SpecialAbilityInput(slug="aura", target_slug="agile"),)
        )
    )

    assert quote.aura_cost == Decimal("1.24")


def test_aura_can_grant_a_weapon_ability_to_compatible_profiles() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(
                SpecialAbilityInput(slug="aura", target_slug="double"),
            )
        )
    )

    assert quote.aura_cost == Decimal("3.60")


def test_aura_weapon_range_restrictions_are_respected() -> None:
    quote = calculate_unit_quote(
        unit_input(
            special_abilities=(
                SpecialAbilityInput(slug="aura", target_slug="prepared"),
            ),
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=0),
                short=AttackProfileInput(dice=1, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )

    assert quote.aura_cost == Decimal("4.80")


def test_non_aura_eligible_ability_is_rejected() -> None:
    with pytest.raises(QuoteValidationError, match="not a valid Aura target"):
        calculate_unit_quote(
            unit_input(
                special_abilities=(SpecialAbilityInput(slug="aura", target_slug="airplane"),)
            )
        )


def test_special_target_contract_comes_from_ruleset() -> None:
    with pytest.raises(QuoteValidationError, match="requires target_slug"):
        calculate_unit_quote(
            unit_input(special_abilities=(SpecialAbilityInput(slug="aura"),))
        )

    with pytest.raises(QuoteValidationError, match="does not accept target_slug"):
        calculate_unit_quote(
            unit_input(
                special_abilities=(
                    SpecialAbilityInput(slug="order", target_slug="agile"),
                )
            )
        )


def test_custom_stats_require_positive_strength_multiplier() -> None:
    accepted = calculate_unit_quote(
        unit_input(
            defense=Decimal("3.5"),
            toughness=Decimal("4.5"),
            custom_stats_enabled=True,
            profiles=AttackProfilesInput(
                melee=AttackProfileInput(dice=1, strength=Decimal("3.5")),
                short=AttackProfileInput(dice=0, strength=0),
                long=AttackProfileInput(dice=0, strength=0),
            ),
        )
    )
    assert accepted.profiles[0].strength_multiplier > 0

    with pytest.raises(QuoteValidationError, match="must be positive"):
        calculate_unit_quote(
            unit_input(
                custom_stats_enabled=True,
                profiles=AttackProfilesInput(
                    melee=AttackProfileInput(dice=1, strength=20),
                    short=AttackProfileInput(dice=0, strength=0),
                    long=AttackProfileInput(dice=0, strength=0),
                ),
            )
        )


def test_standard_mode_rejects_custom_stats() -> None:
    with pytest.raises(QuoteValidationError, match="Defense"):
        calculate_unit_quote(unit_input(defense=Decimal("3.5")))


def test_unit_name_is_trimmed_and_bounded() -> None:
    assert unit_input(name="  Straż  ").name == "Straż"
    with pytest.raises(ValueError):
        unit_input(name="   ")
    with pytest.raises(ValueError):
        unit_input(name="x" * 121)
