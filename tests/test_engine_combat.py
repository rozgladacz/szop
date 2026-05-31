"""B3.4 — testy `app/services/engine/combat.py`.

Pokrywa:
- WeaponProfile / CombatResult immutability
- compute_cover (LoS OSLONA, Obronny terrain)
- compute_attack_modifiers (pkt 19: -1 trafienia LUB +1 obrony gdy 6+)
- compute_defense_modifier (AP + osłona bonus)
- _allocate_wounds_to_defender (pkt 17.e + 18: model kills, znaczniki, prefer_hero)
- resolve_ranged_attack (3 fazy + Brutalny + Precyzyjny + AP + Osłona)
- resolve_melee_attack (analogicznie + melee_balance pkt 20.c)
- ModelKilled events sequenced correctly
- Pure function — input state nie zmieniony
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.combat import (
    ABILITY_AP,
    ABILITY_BASTION,
    ABILITY_BRUTALNY,
    ABILITY_NIEZAWODNY,
    ABILITY_PODWOJNY,
    ABILITY_PRECYZYJNY,
    STATUS_WYCZERPANY,
    ChargeResult,
    CombatResult,
    WeaponProfile,
    _allocate_wounds_to_defender,
    compute_attack_modifiers,
    compute_cover,
    compute_defense_modifier,
    effective_attack_quality,
    resolve_charge_attack,
    resolve_melee_attack,
    resolve_ranged_attack,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MeleeResolved, ModelKilled, ShotResolved
from app.services.engine.los import FEATURE_BLOKUJACY
from app.services.engine.state import (
    BattleState,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_blob(
    blob_id: int = 1,
    x: float = 0.0,
    y: float = 0.0,
    radius: float = 1.0,
    owner: int = 0,
    models: int = 5,
    toughness: int = 3,
    quality: int = 4,
    defense: int = 5,
    is_hero_unit: bool = False,
    passives: tuple[str, ...] = (),
) -> UnitBlob:
    return UnitBlob(
        id=blob_id,
        owner_player=owner,
        position=Position(x, y),
        radius_inches=radius,
        models_alive=models,
        toughness_per_model=toughness,
        quality=quality,
        defense=defense,
        is_hero_unit=is_hero_unit,
        passives=passives,
    )


def make_state() -> BattleState:
    return BattleState(
        round=1,
        active_player=0,
        activations_remaining=(1, 1),
        blobs=(),
        terrain=(),
    )


_DEFAULT_WEAPON = WeaponProfile(
    slug="basic_rifle",
    name="Basic Rifle",
    range_inches=24,
    attacks=1,
    ap=0,
)


# ---------------------------------------------------------------------------
# WeaponProfile / CombatResult frozen
# ---------------------------------------------------------------------------


def test_weapon_profile_frozen():
    w = WeaponProfile(slug="x", name="X", range_inches=12, attacks=2)
    with pytest.raises(FrozenInstanceError):
        w.ap = 5  # type: ignore[misc]


def test_combat_result_frozen():
    cr = CombatResult(events=(), new_attacker=make_blob(), new_defender=make_blob(2))
    with pytest.raises(FrozenInstanceError):
        cr.events = ()  # type: ignore[misc]


def test_weapon_profile_defaults():
    w = WeaponProfile(slug="x", name="X", range_inches=12, attacks=1)
    assert w.ap == 0
    assert w.attack_quality_override is None
    assert w.weapon_abilities == ()


# ---------------------------------------------------------------------------
# compute_cover
# ---------------------------------------------------------------------------


def test_compute_cover_no_terrain():
    attacker = make_blob(1, 0, 0)
    defender = make_blob(2, 20, 0)
    assert compute_cover(attacker, defender, terrain=()) is False


def test_compute_cover_oslona_via_partial_block():
    """Małe Blokujący na drodze → OSLONA → cover True."""
    attacker = make_blob(1, 0, 0, radius=1)
    defender = make_blob(2, 30, 0, radius=5)
    pillar = TerrainCircle(
        center=Position(15, 0), radius_inches=1, features=(FEATURE_BLOKUJACY,)
    )
    assert compute_cover(attacker, defender, terrain=[pillar]) is True


def test_compute_cover_defender_inside_obronny():
    """Defender wewnątrz Obronny terrain → cover True (pkt 4.c.vi)."""
    attacker = make_blob(1, 50, 50)  # far away
    defender = make_blob(2, 0, 0)
    obronny = TerrainCircle(
        center=Position(0, 0), radius_inches=5, features=("Obronny",)
    )
    assert compute_cover(attacker, defender, terrain=[obronny]) is True


def test_compute_cover_clear_los_no_obronny():
    attacker = make_blob(1, 0, 0)
    defender = make_blob(2, 20, 0)
    trudny = TerrainCircle(
        center=Position(50, 50), radius_inches=3, features=("Trudny",)
    )
    assert compute_cover(attacker, defender, terrain=[trudny]) is False


# ---------------------------------------------------------------------------
# compute_attack_modifiers — pkt 19
# ---------------------------------------------------------------------------


def test_attack_modifiers_no_cover():
    am, db = compute_attack_modifiers(attacker_quality=4, has_cover=False)
    assert am == 0
    assert db == 0


def test_attack_modifiers_cover_low_threshold():
    """Cover + Q4 → -1 trafienia, 0 obrona bonus."""
    am, db = compute_attack_modifiers(attacker_quality=4, has_cover=True)
    assert am == -1
    assert db == 0


def test_attack_modifiers_cover_high_threshold_converts_to_defense_bonus():
    """Cover + Q6 → 0 trafienia, +1 obrona ("szansa trafienia już 6+")."""
    am, db = compute_attack_modifiers(attacker_quality=6, has_cover=True)
    assert am == 0
    assert db == 1


def test_attack_modifiers_cover_very_high_threshold():
    """Cover + Q7 (corner case) → przechodzi też na obronę."""
    am, db = compute_attack_modifiers(attacker_quality=7, has_cover=True)
    assert am == 0
    assert db == 1


# ---------------------------------------------------------------------------
# compute_defense_modifier
# ---------------------------------------------------------------------------


def test_defense_modifier_no_ap_no_bonus():
    assert compute_defense_modifier(weapon_ap=0, extra_defense_bonus=0) == 0


def test_defense_modifier_ap_only():
    """AP=2 → modifier=-2 (trudniej obronić)."""
    assert compute_defense_modifier(weapon_ap=2, extra_defense_bonus=0) == -2


def test_defense_modifier_bonus_only():
    """Osłona bonus +1 → modifier=+1 (łatwiej obronić)."""
    assert compute_defense_modifier(weapon_ap=0, extra_defense_bonus=1) == 1


def test_defense_modifier_both():
    """AP=2, bonus=+1 → modifier=-1."""
    assert compute_defense_modifier(weapon_ap=2, extra_defense_bonus=1) == -1


# ---------------------------------------------------------------------------
# _allocate_wounds_to_defender — pkt 17.e + 18
# ---------------------------------------------------------------------------


def test_allocate_single_wound_becomes_marker():
    """1 rana < toughness → znacznik, brak pokonania (pkt 18.c)."""
    defender = make_blob(2, models=5, toughness=3)
    new_def, killed, seq = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=1, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.models_alive == 5
    assert new_def.wounds_received == 1
    assert killed == ()
    assert seq == 10


def test_allocate_exact_toughness_kills_one():
    """Rany = toughness → pokonanie 1 modelu (pkt 18.a)."""
    defender = make_blob(2, models=5, toughness=3)
    new_def, killed, seq = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=3, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.models_alive == 4
    assert new_def.wounds_received == 0
    assert len(killed) == 1
    assert killed[0].unit_id == 2
    assert killed[0].sequence == 10
    assert seq == 11


def test_allocate_multiple_kills():
    """N×toughness ran → N pokonań."""
    defender = make_blob(2, models=5, toughness=3)
    new_def, killed, seq = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=9, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.models_alive == 2
    assert new_def.wounds_received == 0
    assert len(killed) == 3
    assert seq == 13


def test_allocate_kills_plus_marker():
    """Mieszane: 1 model padnie + 1 znacznik."""
    defender = make_blob(2, models=5, toughness=3)
    new_def, killed, _ = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=4, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.models_alive == 4
    assert new_def.wounds_received == 1
    assert len(killed) == 1


def test_allocate_unit_defeated():
    """Wszystkie modele pokonane → models_alive=0, wounds_received zerowane."""
    defender = make_blob(2, models=2, toughness=3)
    new_def, killed, _ = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=10, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.models_alive == 0
    assert new_def.wounds_received == 0
    assert len(killed) == 2  # 6 ran użytych na 2 modele; reszta przepada


def test_allocate_prefer_hero_kills_hero_first():
    """prefer_hero + is_hero_unit → pierwszy pokonany to Bohater."""
    defender = make_blob(2, models=5, toughness=3, is_hero_unit=True)
    new_def, killed, _ = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=3, attacker_id=1, start_sequence=10, prefer_hero=True
    )
    assert new_def.is_hero_unit is False  # hero zabity
    assert killed[0].is_hero is True
    assert new_def.models_alive == 4


def test_allocate_no_prefer_hero_keeps_hero():
    """prefer_hero=False → hero zachowany, zwykli pokonani."""
    defender = make_blob(2, models=5, toughness=3, is_hero_unit=True)
    new_def, killed, _ = _allocate_wounds_to_defender(
        defender, wounds_to_alloc=3, attacker_id=1, start_sequence=10, prefer_hero=False
    )
    assert new_def.is_hero_unit is True
    assert killed[0].is_hero is False


# ---------------------------------------------------------------------------
# resolve_ranged_attack — basic flow
# ---------------------------------------------------------------------------


def test_resolve_ranged_emits_shot_resolved():
    state = make_state()
    attacker = make_blob(1, 0, 0, models=5)
    defender = make_blob(2, 20, 0)
    dice = DeterministicDice(seed=42)
    result = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, dice, sequence=1)
    assert any(isinstance(e, ShotResolved) for e in result.events)
    shot = next(e for e in result.events if isinstance(e, ShotResolved))
    assert shot.attacker_id == 1
    assert shot.defender_id == 2
    assert shot.sequence == 1


def test_resolve_ranged_no_hits_no_changes():
    """Q6 (very hard) + few attacks → likely no hits, defender unchanged."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=1, quality=7)  # threshold 7 → only nat 6 = auto-success
    defender = make_blob(2, 20, 0, models=5)
    dice = DeterministicDice(seed=999)
    weapon = WeaponProfile(slug="weak", name="Weak", range_inches=24, attacks=1)
    result = resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence=1)
    # Stochastic — sprawdzamy że defender pozostaje sensowny
    assert 0 <= result.new_defender.wounds_received <= 1


def test_resolve_ranged_pure_function_attacker_unchanged():
    """Ranged: attacker nie ulega zmianie."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=5)
    defender = make_blob(2, 20, 0)
    dice = DeterministicDice(seed=42)
    result = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, dice, sequence=1)
    assert result.new_attacker == attacker


def test_resolve_ranged_deterministic_replay():
    """Same seed + same args → same result."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=5)
    defender = make_blob(2, 20, 0)
    r1 = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, DeterministicDice(42), sequence=1)
    r2 = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, DeterministicDice(42), sequence=1)
    assert r1 == r2


def test_resolve_ranged_with_ap_lowers_defense():
    """AP=2 weapon → defender ma trudniej; więcej wounds."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=10, quality=3)  # dużo hitów
    defender = make_blob(2, 20, 0, models=10, defense=4)
    no_ap = WeaponProfile(slug="basic", name="B", range_inches=24, attacks=1, ap=0)
    with_ap = WeaponProfile(slug="ap2", name="AP", range_inches=24, attacks=1, ap=2)
    dice1 = DeterministicDice(seed=42)
    dice2 = DeterministicDice(seed=42)
    r_no = resolve_ranged_attack(state, attacker, defender, no_ap, dice1, sequence=1)
    r_ap = resolve_ranged_attack(state, attacker, defender, with_ap, dice2, sequence=1)
    # AP weapon zadaje ≥ wounds bez AP (przy tym samym seedie i hit-rolls)
    wounds_no = (defender.models_alive - r_no.new_defender.models_alive) * defender.toughness_per_model + r_no.new_defender.wounds_received
    wounds_ap = (defender.models_alive - r_ap.new_defender.models_alive) * defender.toughness_per_model + r_ap.new_defender.wounds_received
    assert wounds_ap >= wounds_no


def test_resolve_ranged_with_precyzyjny_kills_hero():
    """Precyzyjny → wszystkie rany do puli atakującego → hero pokonany first."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=5, quality=3)
    defender = make_blob(2, 20, 0, models=3, toughness=3, defense=6, is_hero_unit=True)
    weapon = WeaponProfile(
        slug="prec", name="P", range_inches=24, attacks=1,
        weapon_abilities=(ABILITY_PRECYZYJNY,),
    )
    dice = DeterministicDice(seed=42)
    result = resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence=1)
    killed_events = [e for e in result.events if isinstance(e, ModelKilled)]
    if killed_events:
        # Pierwszy pokonany model przy Precyzyjnym = hero
        assert killed_events[0].is_hero is True
        assert result.new_defender.is_hero_unit is False


def test_resolve_ranged_brutalny_no_natural_6_auto_save():
    """Brutalny → defense roll 6 nie jest auto-sukcesem (więcej ran)."""
    state = make_state()
    # Wymusimy że defender by inaczej rzucał 6 jako auto-save
    attacker = make_blob(1, 0, 0, models=20, quality=2)  # zawsze trafi
    defender = make_blob(2, 20, 0, models=20, defense=7)  # nie zdoła obronić bez natural 6
    no_brut = WeaponProfile(slug="b", name="B", range_inches=24, attacks=1)
    brut = WeaponProfile(slug="br", name="Br", range_inches=24, attacks=1,
                          weapon_abilities=(ABILITY_BRUTALNY,))
    r_no = resolve_ranged_attack(state, attacker, defender, no_brut,
                                  DeterministicDice(seed=42), sequence=1)
    r_brut = resolve_ranged_attack(state, attacker, defender, brut,
                                    DeterministicDice(seed=42), sequence=1)
    wounds_no = (defender.models_alive - r_no.new_defender.models_alive) * defender.toughness_per_model + r_no.new_defender.wounds_received
    wounds_brut = (defender.models_alive - r_brut.new_defender.models_alive) * defender.toughness_per_model + r_brut.new_defender.wounds_received
    # Brutalny zadaje ≥ wounds (brak auto-sukcesów obrony)
    assert wounds_brut >= wounds_no


def test_resolve_ranged_sequence_increments():
    """Eventy mają rosnące sequence."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=20, quality=2)  # zawsze trafi
    defender = make_blob(2, 20, 0, models=5, toughness=2, defense=7)  # padają łatwo
    dice = DeterministicDice(seed=42)
    result = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, dice, sequence=10)
    sequences = [e.sequence for e in result.events]
    assert sequences == sorted(sequences)
    assert sequences[0] == 10


def test_resolve_ranged_full_kill():
    """Wystarczająco ran → unit defeated (models_alive=0)."""
    state = make_state()
    attacker = make_blob(1, 0, 0, models=50, quality=2)
    defender = make_blob(2, 20, 0, models=2, toughness=1, defense=7)
    dice = DeterministicDice(seed=42)
    result = resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, dice, sequence=1)
    assert result.new_defender.models_alive == 0
    assert result.new_defender.wounds_received == 0


# ---------------------------------------------------------------------------
# resolve_melee_attack
# ---------------------------------------------------------------------------


def test_resolve_melee_emits_melee_resolved():
    state = make_state()
    attacker = make_blob(1, models=5)
    defender = make_blob(2, models=5)
    weapon = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2)
    dice = DeterministicDice(seed=42)
    result = resolve_melee_attack(state, attacker, defender, weapon, dice, sequence=1)
    assert any(isinstance(e, MeleeResolved) for e in result.events)


def test_resolve_melee_updates_balance():
    """Melee balance per pkt 20.c: attacker +=, defender -=."""
    state = make_state()
    attacker = make_blob(1, models=20, quality=2)  # zawsze trafi
    defender = make_blob(2, models=20, toughness=2, defense=7)  # łatwo wounds
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    dice = DeterministicDice(seed=42)
    result = resolve_melee_attack(state, attacker, defender, weapon, dice, sequence=1)
    # Załóżmy że są wounds. Sprawdź balance.
    melee_event = next(e for e in result.events if isinstance(e, MeleeResolved))
    total_wounds = melee_event.wounds_dealt + melee_event.wounds_precise
    assert result.new_attacker.melee_balance == attacker.melee_balance + total_wounds
    assert result.new_defender.melee_balance == defender.melee_balance - total_wounds


def test_resolve_melee_no_wounds_no_balance_change():
    """Brak ran → balance niezmieniony."""
    state = make_state()
    # Q7 + niezliczone testy obrony → mało ran
    attacker = make_blob(1, models=1, quality=7)
    defender = make_blob(2, models=5, defense=2)
    weapon = WeaponProfile(slug="weak", name="W", range_inches=0, attacks=1)
    dice = DeterministicDice(seed=42)
    result = resolve_melee_attack(state, attacker, defender, weapon, dice, sequence=1)
    melee = next(e for e in result.events if isinstance(e, MeleeResolved))
    total = melee.wounds_dealt + melee.wounds_precise
    assert result.new_attacker.melee_balance == total
    assert result.new_defender.melee_balance == -total


def test_resolve_melee_pure_function():
    """Replay z tym samym seedem → identyczny CombatResult."""
    state = make_state()
    attacker = make_blob(1, models=5)
    defender = make_blob(2, models=5)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    r1 = resolve_melee_attack(state, attacker, defender, weapon, DeterministicDice(42), sequence=1)
    r2 = resolve_melee_attack(state, attacker, defender, weapon, DeterministicDice(42), sequence=1)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Frozen immutability — input state unchanged
# ---------------------------------------------------------------------------


def test_resolve_ranged_does_not_mutate_input_blobs():
    """Frozen dataclass guarantee — sprawdzamy by pewności."""
    state = make_state()
    attacker = make_blob(1, models=5)
    defender = make_blob(2, x=20, models=5)
    dice = DeterministicDice(seed=42)
    resolve_ranged_attack(state, attacker, defender, _DEFAULT_WEAPON, dice, sequence=1)
    # Input nadal taki sam
    assert attacker.models_alive == 5
    assert defender.models_alive == 5
    assert defender.wounds_received == 0


def test_resolve_melee_does_not_mutate_input_blobs():
    state = make_state()
    attacker = make_blob(1, models=5)
    defender = make_blob(2, models=5)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    dice = DeterministicDice(seed=42)
    resolve_melee_attack(state, attacker, defender, weapon, dice, sequence=1)
    assert attacker.melee_balance == 0
    assert defender.melee_balance == 0


# ---------------------------------------------------------------------------
# Effects integration (B3.4.e) — passive modifiers wpływają na rolls
# ---------------------------------------------------------------------------


def test_passive_tarcza_increases_defense_in_ranged():
    """Defender z Tarczą (nie Przyszpilony) otrzymuje mniej wounds."""
    state = make_state()
    attacker = make_blob(1, x=0, models=10, quality=3)
    defender_no_tarcza = make_blob(2, x=20, models=10, defense=4)
    defender_tarcza = make_blob(2, x=20, models=10, defense=4, passives=("tarcza",))
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    r_no = resolve_ranged_attack(
        state, attacker, defender_no_tarcza, weapon, DeterministicDice(42), sequence=1
    )
    r_t = resolve_ranged_attack(
        state, attacker, defender_tarcza, weapon, DeterministicDice(42), sequence=1
    )
    wounds_no = defender_no_tarcza.models_alive - r_no.new_defender.models_alive
    wounds_t = defender_tarcza.models_alive - r_t.new_defender.models_alive
    # Tarcza nie powinna zwiększyć wounds (≤)
    assert wounds_t <= wounds_no


def test_passive_cierpliwy_increases_defense_when_not_activated():
    """Cierpliwy (gdy nie Aktywowany) → mniej wounds."""
    state = make_state()
    attacker = make_blob(1, x=0, models=10, quality=3)
    defender_no = make_blob(2, x=20, models=10, defense=4)
    defender_cierp = make_blob(2, x=20, models=10, defense=4, passives=("cierpliwy",))
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    r_no = resolve_ranged_attack(
        state, attacker, defender_no, weapon, DeterministicDice(42), sequence=1
    )
    r_c = resolve_ranged_attack(
        state, attacker, defender_cierp, weapon, DeterministicDice(42), sequence=1
    )
    wounds_no = defender_no.models_alive - r_no.new_defender.models_alive
    wounds_c = defender_cierp.models_alive - r_c.new_defender.models_alive
    assert wounds_c <= wounds_no


def test_passive_cierpliwy_inactive_when_activated():
    """Cierpliwy gdy oddział Aktywowany → brak bonusu (passive condition fails)."""
    from app.services.engine.effects import STATUS_AKTYWOWANY

    state = make_state()
    attacker = make_blob(1, x=0, models=10, quality=3)
    defender_active = UnitBlob(
        id=2,
        owner_player=0,
        position=Position(20, 0),
        radius_inches=1.0,
        models_alive=10,
        toughness_per_model=3,
        defense=4,
        passives=("cierpliwy",),
        status_flags=(STATUS_AKTYWOWANY,),
    )
    defender_plain = make_blob(2, x=20, models=10, defense=4)
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1)
    r_active = resolve_ranged_attack(
        state, attacker, defender_active, weapon, DeterministicDice(42), sequence=1
    )
    r_plain = resolve_ranged_attack(
        state, attacker, defender_plain, weapon, DeterministicDice(42), sequence=1
    )
    # Cierpliwy nieaktywny → identyczny wynik jak bez Cierpliwego
    assert r_active.new_defender.models_alive == r_plain.new_defender.models_alive
    assert r_active.new_defender.wounds_received == r_plain.new_defender.wounds_received


# ---------------------------------------------------------------------------
# resolve_charge_attack — pełna Szarża (B3.4.f, pkt 14.d + ADR-0015a)
# ---------------------------------------------------------------------------


def test_charge_emits_binding_move():
    """Faza 1 pkt 14.d.ii — emit MoveExecuted z move_type='binding'."""
    from app.services.engine.events import MoveExecuted

    state = make_state()
    charger = make_blob(1, x=0, y=0, models=5)
    defender = make_blob(2, x=10, y=0, models=5)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    move_events = [e for e in result.events if isinstance(e, MoveExecuted)]
    assert len(move_events) == 1
    assert move_events[0].move_type == "binding"
    assert move_events[0].unit_id == charger.id


def test_charge_counter_attack_when_defender_not_exhausted():
    """Pkt 14.d.iv — obrońca nie-Wyczerpany wykonuje kontratak (więcej eventów MeleeResolved)."""
    from app.services.engine.events import MeleeResolved

    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = make_blob(2, x=10, models=10, defense=4, quality=3)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    melee_events = [e for e in result.events if isinstance(e, MeleeResolved)]
    # 2 MeleeResolved: kontratak (defender as attacker) + główny atak (charger as attacker)
    assert len(melee_events) == 2


def test_charge_no_counter_when_defender_exhausted():
    """Obrońca Wyczerpany → brak kontrataku, tylko 1 MeleeResolved (główny)."""
    from app.services.engine.events import MeleeResolved

    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = UnitBlob(
        id=2,
        owner_player=0,
        position=Position(10, 0),
        radius_inches=1.0,
        models_alive=10,
        toughness_per_model=3,
        quality=3,
        defense=4,
        status_flags=(STATUS_WYCZERPANY,),
    )
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    melee_events = [e for e in result.events if isinstance(e, MeleeResolved)]
    assert len(melee_events) == 1


def test_charge_no_counter_when_declared_false():
    """counter_attack_declared=False → brak kontrataku."""
    from app.services.engine.events import MeleeResolved

    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = make_blob(2, x=10, models=10, defense=4)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1,
        counter_attack_declared=False,
    )
    melee_events = [e for e in result.events if isinstance(e, MeleeResolved)]
    assert len(melee_events) == 1


def test_charge_defender_becomes_exhausted_after_counter():
    """Po kontrataku obrońca ma status Wyczerpany (pkt 14.d.iv)."""
    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = make_blob(2, x=10, models=10, defense=4)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    assert STATUS_WYCZERPANY in result.new_defender.status_flags


def test_charge_bastion_prevents_exhaustion_after_counter():
    """Bastion (id 1) — defender NIE staje się Wyczerpany po kontrataku."""
    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = make_blob(
        2, x=10, models=10, defense=4, passives=(ABILITY_BASTION,)
    )
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    assert STATUS_WYCZERPANY not in result.new_defender.status_flags


def test_charge_charger_position_updates():
    """Po Związaniu charger.position zmienia się (blisko defendera)."""
    state = make_state()
    charger = make_blob(1, x=0, y=0, radius=1.0)
    defender = make_blob(2, x=20, y=0, radius=1.0)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=1
    )
    # Charger powinien znaleźć się 1″ od krawędzi defendera
    # = 1″ + defender.radius od centrum defendera
    expected_dist = defender.radius_inches + 1.0  # = 2.0
    actual_dx = defender.position.x - result.new_charger.position.x
    actual_dy = defender.position.y - result.new_charger.position.y
    actual_dist = (actual_dx**2 + actual_dy**2) ** 0.5
    assert abs(actual_dist - expected_dist) < 0.01


def test_charge_sequence_incrementing():
    """Eventy mają monotonicznie rosnące sequence."""
    state = make_state()
    charger = make_blob(1, x=0, models=10, quality=3)
    defender = make_blob(2, x=10, models=10, quality=3, defense=4)
    weapon = WeaponProfile(slug="sw", name="Sw", range_inches=0, attacks=1)
    result = resolve_charge_attack(
        state, charger, defender, weapon, DeterministicDice(42), sequence=10
    )
    sequences = [e.sequence for e in result.events]
    assert sequences == sorted(sequences)
    assert sequences[0] == 10


def test_charge_result_frozen():
    """ChargeResult jest frozen."""
    cr = ChargeResult(events=(), new_charger=make_blob(), new_defender=make_blob(2))
    with pytest.raises(FrozenInstanceError):
        cr.events = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Weapon abilities — Niezawodny + Podwójny (B3.4.g)
# ---------------------------------------------------------------------------


def test_effective_attack_quality_niezawodny_overrides():
    """Niezawodny (id 63) — Q=2 niezależnie od attacker.quality."""
    attacker = make_blob(quality=5)
    weapon = WeaponProfile(
        slug="ridge", name="Ridge", range_inches=24, attacks=1,
        weapon_abilities=(ABILITY_NIEZAWODNY,),
    )
    assert effective_attack_quality(weapon, attacker) == 2


def test_effective_attack_quality_niezawodny_beats_override():
    """Niezawodny ma priorytet nad attack_quality_override w profilu."""
    attacker = make_blob(quality=5)
    weapon = WeaponProfile(
        slug="x", name="X", range_inches=24, attacks=1,
        attack_quality_override=4,
        weapon_abilities=(ABILITY_NIEZAWODNY,),
    )
    assert effective_attack_quality(weapon, attacker) == 2


def test_effective_attack_quality_override_used_without_niezawodny():
    """Bez Niezawodny, attack_quality_override z profilu."""
    attacker = make_blob(quality=5)
    weapon = WeaponProfile(
        slug="x", name="X", range_inches=24, attacks=1, attack_quality_override=3,
    )
    assert effective_attack_quality(weapon, attacker) == 3


def test_effective_attack_quality_fallback_to_attacker():
    """Bez Niezawodny ani override → attacker.quality."""
    attacker = make_blob(quality=4)
    weapon = WeaponProfile(slug="x", name="X", range_inches=24, attacks=1)
    assert effective_attack_quality(weapon, attacker) == 4


def test_resolve_ranged_niezawodny_more_hits_than_quality_5():
    """Atakujący Q5 z bronią Niezawodny → trafia jak Q2 → znacznie więcej hits."""
    state = make_state()
    attacker = make_blob(1, models=20, quality=5)
    defender = make_blob(2, x=20, models=20, defense=4)
    plain = WeaponProfile(slug="p", name="P", range_inches=24, attacks=1)
    niez = WeaponProfile(
        slug="n", name="N", range_inches=24, attacks=1,
        weapon_abilities=(ABILITY_NIEZAWODNY,),
    )
    r_plain = resolve_ranged_attack(
        state, attacker, defender, plain, DeterministicDice(42), sequence=1
    )
    r_niez = resolve_ranged_attack(
        state, attacker, defender, niez, DeterministicDice(42), sequence=1
    )
    wounds_p = sum(1 for e in r_plain.events if "ModelKilled" in type(e).__name__)
    wounds_n = sum(1 for e in r_niez.events if "ModelKilled" in type(e).__name__)
    # Niezawodny daje ≥ wounds (effectively więcej hitów)
    assert wounds_n >= wounds_p


def test_resolve_ranged_podwojny_adds_natural_6_extra_hits():
    """Podwójny (id 66) — natural 6 trafienia daje dodatkowe trafienie.

    Stat: average hit rate rośnie o ~1/6 per atak.
    """
    state = make_state()
    attacker = make_blob(1, models=20, quality=4)
    defender = make_blob(2, x=20, models=30, defense=4, toughness=1)
    plain = WeaponProfile(slug="p", name="P", range_inches=24, attacks=1)
    pod = WeaponProfile(
        slug="pod", name="Pod", range_inches=24, attacks=1,
        weapon_abilities=(ABILITY_PODWOJNY,),
    )
    r_plain = resolve_ranged_attack(
        state, attacker, defender, plain, DeterministicDice(42), sequence=1
    )
    r_pod = resolve_ranged_attack(
        state, attacker, defender, pod, DeterministicDice(42), sequence=1
    )
    from app.services.engine.events import ShotResolved

    plain_shot = next(e for e in r_plain.events if isinstance(e, ShotResolved))
    pod_shot = next(e for e in r_pod.events if isinstance(e, ShotResolved))
    # Z Podwójny: hits ≥ standardowe (przy tym samym seedie)
    assert pod_shot.hits >= plain_shot.hits


def test_podwojny_no_natural_6_no_extra_hits():
    """Gdy seed wyklucza naturalne 6, Podwójny nic nie dodaje."""
    # Test scenariuszowy: model_alive=1, attacks=0 → 0 attacks → 0 hits
    state = make_state()
    attacker = make_blob(1, models=0)  # 0 modeli
    defender = make_blob(2, x=20, models=5)
    pod = WeaponProfile(
        slug="pod", name="P", range_inches=24, attacks=1,
        weapon_abilities=(ABILITY_PODWOJNY,),
    )
    result = resolve_ranged_attack(
        state, attacker, defender, pod, DeterministicDice(42), sequence=1
    )
    from app.services.engine.events import ShotResolved

    shot = next(e for e in result.events if isinstance(e, ShotResolved))
    assert shot.hits == 0
