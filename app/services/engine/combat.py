"""B3.4 — Combat resolution (`SZOP_Rozjemca.md pkt 14.c-d + 17 + 18 + 19`).

Funkcje publiczne:
- `resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence, terrain)`
- `resolve_melee_attack` rozlicza pojedynczy atak wręcz.
- `resolve_charge_attack` rozlicza Związanie, kontratak i główny atak Szarży.

Każdy atak realizuje 3-fazową semantykę pkt 17:
- **Faza 1 — Declare + modifiers.** Sprawdzamy LoS (ranged), Osłonę pkt 19,
  AP broni. W MVP brak passive modifiers (Cierpliwy/Tarcza/Ostrożny etc.) —
  framework gotowy, integracja w B3.5 `effects.py`.
- **Faza 2 — Dice resolution.** `roll_with_threshold` dla testów trafienia
  (pkt 17.a) oraz dla każdego trafienia → test obrony (pkt 17.b). Brutalny
  (id 57) → `natural_6_auto_success=False` na testach obrony.
- **Faza 3 — Wound allocation.** Pkt 17.d:
  - Pula atakującego (`wounds_pending_precise`) — gdy `Precyzyjny` (id 68) lub
    naturalna 1 obrońcy + effective_threshold > 2+ (pkt 17.d.i).
  - Pula obrońcy (`wounds_pending`) — pozostałe (pkt 17.d.ii).
  - Pkt 17.e + 18: alokacja → znaczniki / pokonanie modeli. W MVP atakujący
    alokujący puli precyzyjnej preferuje Bohatera (per pkt 18.a — "przydzielający
    może odrzucić rany aby pokonać"); obrońca alokujący standardową preferuje
    zwykłe modele.

`resolve_charge_attack` koordynuje oba ataki wręcz z pkt 14.d.iii–iv.
`resolve_melee_attack` aktualizuje bilans ran używany przy Przegrupowaniu (pkt 20.a).

Weapon abilities w MVP scope:
- **AP(X)** (id 55) — modyfikator obrony `-X` (effective higher threshold)
- **Brutalny** (id 57) — `natural_6_auto_success=False` w testach obrony
- **Precyzyjny** (id 68) — wszystkie rany → pula atakującego

Pozostałe weapon abilities (Impet, Przebijająca, Zabójczy,
Dezintegracja, Niezawodny, Niebezpośredni, etc.) → B3.5 `effects.py` lub
przyszłe iteracje. `RollResult.rolls` zachowuje natural values dla inspekcji.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from app.services.engine.dice import DeterministicDice, RollResult
from app.services.engine.events import (
    BattleEvent,
    MeleeResolved,
    ModelKilled,
    MoveExecuted,
    ShotResolved,
    StatusAdded,
)
from app.services.engine.geometry import circle_edge_distance, distance
from app.services.engine.los import LoSState, check_los
from app.services.engine.state import (
    ActivationPhase,
    AttackState,
    BattleState,
    ChargeAttackIntent,
    Lokalizacja,
    Position,
    Terrain,
    UNARMED_WEAPON,
    UnitBlob,
    WeaponProfile,
    effective_attack_passives,
    effective_passives,
)
from app.services.engine.status import (
    STATUS_PRZYGOTOWANY,
    STATUS_WYCZERPANY,
    add_status,
)


def effective_attack_quality(weapon: WeaponProfile, attacker: UnitBlob) -> int:
    """Quality threshold po uwzględnieniu weapon abilities (Niezawodny id 63).

    Niezawodny: "Atakuje z jakością 2+" — overrides attacker.quality do 2.
    `weapon.attack_quality_override` (jeśli ustawione) ma niższy priorytet niż
    Niezawodny — Niezawodny zawsze ma 2 niezależnie od profilu.
    """
    if ABILITY_NIEZAWODNY in weapon.weapon_abilities:
        return 2
    if weapon.attack_quality_override is not None:
        return weapon.attack_quality_override
    return attacker.quality


def _count_hits(
    hit_result: RollResult,
    weapon: WeaponProfile,
    *,
    canonical_aliases: bool = False,
    furia: bool = False,
) -> int:
    """Count normal hits and bonuses from Podwójny (66) and Furia (7)."""
    podwojny = (
        ABILITY_PODWOJNY in weapon.weapon_abilities
        or (canonical_aliases and ABILITY_ROZRYWAJACY in weapon.weapon_abilities)
    )
    bonuses = podwojny + furia
    if bonuses:
        return hit_result.successes + bonuses * hit_result.rolls.count(6)
    return hit_result.successes


def _aggregate_passive_attack(attacker: UnitBlob, **ctx_kwargs: object) -> int:
    """Lazy import + delegacja do effects.aggregate_attack_modifier.

    Lazy import unika cyclic dependency combat ↔ effects (effects.py importuje
    WeaponProfile z combat.py).
    """
    from app.services.engine.effects import EffectContext, aggregate_attack_modifier

    ctx = EffectContext(blob=attacker, **ctx_kwargs)  # type: ignore[arg-type]
    return aggregate_attack_modifier(ctx)


def _aggregate_passive_defense(defender: UnitBlob, **ctx_kwargs: object) -> int:
    """Lazy import + delegacja do effects.aggregate_defense_modifier."""
    from app.services.engine.effects import EffectContext, aggregate_defense_modifier

    ctx = EffectContext(blob=defender, **ctx_kwargs)  # type: ignore[arg-type]
    return aggregate_defense_modifier(ctx)

# Weapon ability sluggi (zob. `app/rulesets/v1/abilities.yaml` type=weapon)
ABILITY_AP = "ap"
ABILITY_BRUTALNY = "brutalny"
ABILITY_PRECYZYJNY = "precyzyjny"
ABILITY_NIEZAWODNY = "niezawodny"  # weapon Q=2+ (id 63)
ABILITY_PODWOJNY = "podwojny"  # natural 6 hit → dodatkowe trafienie (id 66)
ABILITY_ROZRYWAJACY = "rozrywajacy"  # canonical YAML slug for Podwójny
ABILITY_NAMIERZANIE = "namierzanie"
ABILITY_ZGUBA = "zguba"  # pokonane modele → ELIMINOWANY, nie wracają (id 76, pkt 26.d/27.a)

FEATURE_OBRONNY = "Obronny"


# `WeaponProfile` przeniesiony do `state.py` (B3.9.e / ADR-0047). Re-eksport
# z `state` zachowuje wsteczną kompatybilność call sites (testy, scripts).


@dataclass(frozen=True, slots=True)
class CombatResult:
    """Output combat resolution.

    `events` — sekwencyjne battle events (ShotResolved / MeleeResolved + ModelKilled).
    `new_attacker` / `new_defender` — zaktualizowane bloby; immutability gwarantuje
    że stary state można zachować dla replay.
    """

    events: tuple[BattleEvent, ...]
    new_attacker: UnitBlob
    new_defender: UnitBlob


@dataclass(frozen=True, slots=True)
class _RangedProfileDeclaration:
    """One canonical ranged profile assigned to one target."""

    defender: UnitBlob
    weapon: WeaponProfile
    weapon_count: int = 1


@dataclass(frozen=True, slots=True)
class _RangedProfilePools:
    """Dice outcome for one profile before any wound allocation."""

    hits: int
    wounds_pending: int
    wounds_pending_precise: int
    wounds_eliminating: int


@dataclass(frozen=True, slots=True)
class _RangedVolleyResult:
    """Whole multi-profile Attack after target-scoped pool allocation."""

    events: tuple[BattleEvent, ...]
    new_attacker: UnitBlob
    new_defenders: tuple[UnitBlob, ...]


# ---------------------------------------------------------------------------
# Helpers — Osłona pkt 19, modifiers
# ---------------------------------------------------------------------------


def compute_cover(
    attacker: UnitBlob,
    defender: UnitBlob,
    terrain: Iterable[Terrain] = (),
) -> bool:
    """True gdy defender ma osłonę (pkt 19).

    Pkt 19: "Jeżeli większość modeli atakowanego oddziału ma osłonę". W Pareto
    MVP (oddział = blob) sprawdzamy:
    - LoS state OSLONA z `check_los`, **lub**
    - centrum defendera wewnątrz terenu z cechą `Obronny` (pkt 4.a, 4.c.vi).
    """
    terrain_list = list(terrain)
    los_state = check_los(attacker, defender, terrain_list)
    if los_state == LoSState.OSLONA:
        return True
    return any(
        FEATURE_OBRONNY in t.features and t.contains_point(defender.position)
        for t in terrain_list
    )


def compute_attack_modifiers(
    *,
    attacker_quality: int,
    has_cover: bool,
) -> tuple[int, int]:
    """Zwraca (attack_modifier, extra_defense_bonus) per pkt 19.

    Pkt 19: "−1 do trafienia. Jeżeli szansa trafienia wynosi już 6+, zamiast
    tego broniący się otrzymuje +1 do obrony."

    `attacker_quality` to base threshold; "szansa trafienia 6+" = potrzeba 6+
    żeby trafić = base threshold ≥ 6.

    Returns:
        (attack_modifier, extra_defense_bonus) — modifier do roll_with_threshold
        dla trafienia (negatywny ⇒ trudniej) oraz bonus do obrońcy
        (dodatni ⇒ łatwiej obrońcy).
    """
    attack_modifier = 0
    extra_defense_bonus = 0
    if has_cover:
        if attacker_quality >= 6:
            extra_defense_bonus = 1  # +1 obrona
        else:
            attack_modifier = -1  # -1 trafienie
    return attack_modifier, extra_defense_bonus


def compute_defense_modifier(
    *,
    weapon_ap: int,
    extra_defense_bonus: int,
) -> int:
    """Defense modifier per pkt 17.b: AP −X (z broni) + bonus z osłony pkt 19.

    Modifier do `roll_with_threshold(defender.defense, modifier=...)`. AP −X
    obniża skuteczność obrony (effective threshold rośnie), bonus z osłony
    obniża threshold (łatwiej).

    Returns:
        modifier (int). Wynik: `effective_def = max(2, defender.defense - modifier)`.
    """
    return -weapon_ap + extra_defense_bonus


# ---------------------------------------------------------------------------
# Wound allocation — pkt 17.d, 17.e, 18
# ---------------------------------------------------------------------------


def _allocate_wounds_to_defender(
    defender: UnitBlob,
    wounds_to_alloc: int,
    *,
    attacker_id: int | None,
    start_sequence: int,
    prefer_hero: bool,
) -> tuple[UnitBlob, tuple[ModelKilled, ...], int]:
    """Alokuje N ran do oddziału per pkt 17.e + 18.

    Args:
        defender: aktualny stan obrońcy.
        wounds_to_alloc: liczba ran do przydzielenia.
        attacker_id: ID atakującego (do `ModelKilled.by_attacker_id`).
        start_sequence: pierwszy sequence dla generowanych eventów.
        prefer_hero: gdy True (pula atakującego/Precyzyjny) — pokonuje Bohatera
            pierwszego jeśli `defender.is_hero_unit`; gdy False — zwykłe modele.

    Returns:
        (new_defender, killed_events, next_sequence).

    Algorithm (homogenized MVP):
    - `wounds_received += wounds_to_alloc`
    - Pętla: gdy `wounds_received >= toughness_per_model` i `models_alive > 0`:
      - decrement `models_alive` o 1, decrement `wounds_received` o toughness
      - emit `ModelKilled`
    - Pkt 18.c: pozostałe rany zostają jako znaczniki.

    Heterogeniczne oddziały (Bohater): w MVP używamy proxy — gdy `prefer_hero` i
    `is_hero_unit`, atakujący "wybiera" hero do pokonania (model index 0 jako hero
    domyślnie). Faktyczne pokonanie redukuje `models_alive` o 1 (Bohater liczy się
    jako 1 model w models_alive).

    R4.Zguba (H5 RESOLVED 2026-06-07): `defender.wounds_eliminating` (licznik
    dorzucany przez broń Zguba PRZED alokacją) jest konsumowany równolegle z
    alokacją. Model pokonany gdy licznik wciąż dodatni (`> 0` w momencie
    pokonania, per decyzja H5) → `ModelKilled(eliminated=True)`; licznik maleje
    o `toughness_per_model` per pokonany model (floor 0). Gdy pokonano ostatni
    model z `eliminated=True` → `location=ELIMINOWANY` (pkt 26.d, nie wraca),
    inaczej WYCOFANY (pkt 26.c). Wipe zeruje `wounds_eliminating` (spójnie z
    `wounds_received`).
    """
    new_received = defender.wounds_received + wounds_to_alloc
    new_models = defender.models_alive
    new_hero = defender.is_hero_unit
    new_eliminating = defender.wounds_eliminating  # R4.Zguba — budżet ran Zguby
    killed_events: list[ModelKilled] = []
    seq = start_sequence

    tou = defender.toughness_per_model
    last_kill_eliminated = False
    while new_received >= tou and new_models > 0:
        new_received -= tou
        new_models -= 1
        # R4.Zguba: model pokonany gdy budżet Zguby wciąż dodatni → ELIMINOWANY.
        # Ocena PRZED dekrementem (licznik > 0 w momencie pokonania, decyzja H5).
        eliminated = new_eliminating > 0
        last_kill_eliminated = eliminated
        new_eliminating = max(0, new_eliminating - tou)
        # Pierwsza ofiara w puli atakującego z prefer_hero → hero (jeśli jest).
        hero_killed = False
        if prefer_hero and new_hero:
            hero_killed = True
            new_hero = False
        killed_events.append(
            ModelKilled(
                sequence=seq,
                unit_id=defender.id,
                model_index=new_models,  # index = remaining count (jako proxy)
                is_hero=hero_killed,
                eliminated=eliminated,
                by_attacker_id=attacker_id,
            )
        )
        seq += 1

    wiped = new_models == 0
    # `location` zmieniamy TYLKO gdy to wywołanie faktycznie pokonało ostatni
    # model (`killed_events` niepuste) — inaczej druga pula alokacji (pending po
    # precise) wywołana na już-pokonanym oddziale (models_alive==0) nadpisałaby
    # ELIMINOWANY z pierwszej puli na WYCOFANY. Mirror reducer-a, który pomija
    # ModelKilled gdy `models_alive == 0`. Zerowanie znaczników/licznika zależy
    # tylko od `wiped` (martwy oddział nie nosi ran).
    wiped_this_call = wiped and bool(killed_events)
    new_defender = replace(
        defender,
        models_alive=new_models,
        wounds_received=new_received if not wiped else 0,
        wounds_eliminating=new_eliminating if not wiped else 0,
        is_hero_unit=new_hero,
        # Pkt 27.b: gdy ostatni model oddziału zostaje pokonany, cały oddział
        # staje się Wycofany (pkt 26.c, domyślnie) lub ELIMINOWANY (pkt 26.d,
        # gdy pokonujący cios był raną Zguby — last_kill_eliminated).
        location=(
            (Lokalizacja.ELIMINOWANY if last_kill_eliminated else Lokalizacja.WYCOFANY)
            if wiped_this_call
            else defender.location
        ),
    )
    return new_defender, tuple(killed_events), seq


# ---------------------------------------------------------------------------
# Public — resolve_ranged_attack
# ---------------------------------------------------------------------------


def _resolve_ranged_profile_pools(
    state: BattleState,
    attacker: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    weapon_count: int,
    dice: DeterministicDice,
    terrain: Iterable[Terrain],
    *,
    source_correct: bool,
) -> _RangedProfilePools:
    """Resolve all dice for one profile without allocating any wounds."""

    terrain_list = list(terrain)
    defender_passives = effective_passives(defender)
    has_cover = compute_cover(attacker, defender, terrain_list) or (
        source_correct and "samolot" in defender_passives
    )
    attack_quality = effective_attack_quality(weapon, attacker)
    attack_modifier, extra_defense_bonus = compute_attack_modifiers(
        attacker_quality=attack_quality,
        has_cover=has_cover,
    )
    defense_modifier = compute_defense_modifier(
        weapon_ap=weapon.ap,
        extra_defense_bonus=extra_defense_bonus,
    )
    attack_modifier += _aggregate_passive_attack(
        attacker,
        state=state if source_correct else None,
        weapon=weapon,
        attack_state=state.activation.attack if state.activation is not None else None,
    )
    defense_modifier += _aggregate_passive_defense(
        defender,
        state=state if source_correct else None,
        weapon=weapon,
    )
    if source_correct and STATUS_PRZYGOTOWANY in defender.status_flags:
        defense_modifier += 1
    if (
        source_correct
        and ABILITY_NAMIERZANIE in weapon.weapon_abilities
    ):
        attack_modifier = max(0, attack_modifier)

    is_precyzyjny = ABILITY_PRECYZYJNY in weapon.weapon_abilities
    is_brutalny = ABILITY_BRUTALNY in weapon.weapon_abilities
    disables_auto_six = is_brutalny or (
        source_correct and "delikatny" in defender_passives
    )

    total_attacks = attacker.models_alive * weapon.attacks * weapon_count
    hit_result = dice.roll_with_threshold(
        count=total_attacks,
        threshold=attack_quality,
        modifier=attack_modifier,
    )
    hits = _count_hits(
        hit_result,
        weapon,
        canonical_aliases=source_correct,
    )

    wounds_pending = 0
    wounds_pending_precise = 0
    if hits > 0:
        defense_result = dice.roll_with_threshold(
            count=hits,
            threshold=defender.defense,
            modifier=defense_modifier,
            natural_6_auto_success=not disables_auto_six,
        )
        defense_successes = defense_result.successes
        if (
            source_correct
            and "niewrazliwy" in defender_passives
            and not is_brutalny
        ):
            defense_successes += sum(
                1
                for roll in defense_result.rolls
                if roll == 5 and roll < defense_result.effective_threshold
            )
        failed_count = hits - defense_successes
        if failed_count > 0:
            if is_precyzyjny:
                wounds_pending_precise = failed_count
            elif defense_result.effective_threshold > 2:
                natural_ones_count = sum(
                    1 for roll in defense_result.rolls if roll == 1
                )
                wounds_pending_precise = natural_ones_count
                wounds_pending = failed_count - natural_ones_count
            else:
                wounds_pending = failed_count

    wounds_eliminating = (
        wounds_pending + wounds_pending_precise
        if ABILITY_ZGUBA in weapon.weapon_abilities
        else 0
    )
    return _RangedProfilePools(
        hits=hits,
        wounds_pending=wounds_pending,
        wounds_pending_precise=wounds_pending_precise,
        wounds_eliminating=wounds_eliminating,
    )


def _resolve_ranged_volley(
    state: BattleState,
    attacker: UnitBlob,
    declarations: tuple[_RangedProfileDeclaration, ...],
    dice: DeterministicDice,
    sequence: int,
    terrain: Iterable[Terrain] = (),
    *,
    source_correct: bool = False,
) -> _RangedVolleyResult:
    """Resolve one whole ranged Attack before allocating target-scoped pools.

    All profile hit/defense tests happen first. Only then are the accumulated
    attacker and defender pools allocated, target by target, preserving pkt 17.
    """

    events: list[BattleEvent] = []
    pools_by_target: dict[int, list[int]] = {}
    defenders_by_id: dict[int, UnitBlob] = {}
    target_order: list[int] = []
    next_sequence = sequence

    for declaration in declarations:
        defender = declaration.defender
        if defender.id not in pools_by_target:
            pools_by_target[defender.id] = [0, 0, 0]
            defenders_by_id[defender.id] = defender
            target_order.append(defender.id)
        pools = _resolve_ranged_profile_pools(
            state,
            attacker,
            defender,
            declaration.weapon,
            declaration.weapon_count,
            dice,
            terrain,
            source_correct=source_correct,
        )
        events.append(
            ShotResolved(
                sequence=next_sequence,
                attacker_id=attacker.id,
                defender_id=defender.id,
                weapon_slug=declaration.weapon.slug,
                hits=pools.hits,
                wounds_dealt=pools.wounds_pending,
                wounds_precise=pools.wounds_pending_precise,
                wounds_eliminating=pools.wounds_eliminating,
            )
        )
        target_pools = pools_by_target[defender.id]
        target_pools[0] += pools.wounds_pending_precise
        target_pools[1] += pools.wounds_pending
        target_pools[2] += pools.wounds_eliminating
        next_sequence += 1

    new_defenders: list[UnitBlob] = []
    for target_id in target_order:
        precise, regular, eliminating = pools_by_target[target_id]
        new_defender = defenders_by_id[target_id]
        if eliminating > 0:
            new_defender = replace(
                new_defender,
                wounds_eliminating=new_defender.wounds_eliminating + eliminating,
            )
        if precise > 0:
            new_defender, killed, next_sequence = _allocate_wounds_to_defender(
                new_defender,
                precise,
                attacker_id=attacker.id,
                start_sequence=next_sequence,
                prefer_hero=True,
            )
            events.extend(killed)
        if regular > 0:
            new_defender, killed, next_sequence = _allocate_wounds_to_defender(
                new_defender,
                regular,
                attacker_id=attacker.id,
                start_sequence=next_sequence,
                prefer_hero=False,
            )
            events.extend(killed)
        new_defenders.append(new_defender)

    return _RangedVolleyResult(
        events=tuple(events),
        new_attacker=attacker,
        new_defenders=tuple(new_defenders),
    )


def resolve_ranged_attack(
    state: BattleState,
    attacker: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    dice: DeterministicDice,
    sequence: int,
    terrain: Iterable[Terrain] = (),
) -> CombatResult:
    """Resolve the legacy one-profile ranged Attack through the volley SSOT."""

    result = _resolve_ranged_volley(
        state,
        attacker,
        (_RangedProfileDeclaration(defender=defender, weapon=weapon),),
        dice,
        sequence,
        terrain,
    )
    return CombatResult(
        events=result.events,
        new_attacker=result.new_attacker,
        new_defender=result.new_defenders[0],
    )


# ---------------------------------------------------------------------------
# Public — resolve_melee_attack
# ---------------------------------------------------------------------------


def resolve_melee_attack(
    state: BattleState,
    attacker: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    dice: DeterministicDice,
    sequence: int,
    terrain: Iterable[Terrain] = (),
    *,
    charging_attack: AttackState | None = None,
    canonical_aliases: bool = False,
) -> CombatResult:
    """Rozlicza pojedynczy atak wręcz (pkt 17).

    `resolve_charge_attack` przekazuje `charging_attack` tylko dla głównego
    ataku kwalifikującego się do Furii (poz. 7 i 10).
    `canonical_aliases` obejmuje także kontratak zamkniętej Szarży v3;
    nie zależy od kwalifikacji do Furii (Podwójny, poz. 66).

    Algorithm:
    1. Faza 1: brak LoS (wręcz), brak Osłony pkt 19 standard (osłona dotyczy
       głównie ranged; Parowanie id 24 daje osłonę w walce wręcz — passive,
       B3.5).
    2. Faza 2: hit roll (attacker.quality) → defense roll (defender.defense),
       Brutalny / Precyzyjny / AP per ranged.
    3. Faza 3: alokacja per pkt 17.d-e + 18. Bilans wręcz:
       - `attacker.damage_balance += wounds_dealt`
       - `defender.damage_balance -= wounds_dealt`
    """
    del terrain  # melee MVP: brak osłony / cover (Parowanie id 24 → B3.5+)
    attack_quality = effective_attack_quality(weapon, attacker)
    is_precyzyjny = ABILITY_PRECYZYJNY in weapon.weapon_abilities
    is_brutalny = ABILITY_BRUTALNY in weapon.weapon_abilities

    # Passive modifiers (Cierpliwy/Tarcza dla obrońcy; Ostrożny/Przygotowanie/etc. dla atakującego)
    attack_modifier = _aggregate_passive_attack(
        attacker,
        weapon=weapon,
        attack_state=state.activation.attack if state.activation is not None else None,
    )
    defense_modifier = -weapon.ap + _aggregate_passive_defense(defender, weapon=weapon)

    # Faza 2 — Dice
    total_attacks = attacker.models_alive * weapon.attacks
    hit_result = dice.roll_with_threshold(
        count=total_attacks,
        threshold=attack_quality,
        modifier=attack_modifier,
    )
    furia = charging_attack is not None and ABILITY_FURIA in effective_attack_passives(
        attacker, charging_attack
    )
    hits = _count_hits(
        hit_result, weapon, canonical_aliases=canonical_aliases, furia=furia,
    )

    wounds_pending = 0
    wounds_pending_precise = 0
    if hits > 0:
        defense_result = dice.roll_with_threshold(
            count=hits,
            threshold=defender.defense,
            modifier=defense_modifier,
            natural_6_auto_success=not is_brutalny,
        )
        failed_count = hits - defense_result.successes
        if failed_count > 0:
            if is_precyzyjny:
                wounds_pending_precise = failed_count
            else:
                if defense_result.effective_threshold > 2:
                    natural_ones_count = sum(
                        1 for r in defense_result.rolls if r == 1
                    )
                    wounds_pending_precise = natural_ones_count
                    wounds_pending = failed_count - natural_ones_count
                else:
                    wounds_pending = failed_count

    total_wounds = wounds_pending + wounds_pending_precise

    # R4.Zguba (pkt 26.d): broń Zguba dorzuca licznik `wounds_eliminating`.
    is_zguba = ABILITY_ZGUBA in weapon.weapon_abilities
    wounds_eliminating = total_wounds if is_zguba else 0

    events: list[BattleEvent] = [
        MeleeResolved(
            sequence=sequence,
            attacker_id=attacker.id,
            defender_id=defender.id,
            weapon_slug=weapon.slug,
            hits=hits,
            wounds_dealt=wounds_pending,
            wounds_precise=wounds_pending_precise,
            wounds_eliminating=wounds_eliminating,
        )
    ]
    next_sequence = sequence + 1

    # Faza 3 — Wound allocation
    new_defender = defender
    if wounds_eliminating > 0:
        new_defender = replace(
            new_defender,
            wounds_eliminating=new_defender.wounds_eliminating + wounds_eliminating,
        )
    if wounds_pending_precise > 0:
        new_defender, killed_a, next_sequence = _allocate_wounds_to_defender(
            new_defender,
            wounds_pending_precise,
            attacker_id=attacker.id,
            start_sequence=next_sequence,
            prefer_hero=True,
        )
        events.extend(killed_a)
    if wounds_pending > 0:
        new_defender, killed_b, next_sequence = _allocate_wounds_to_defender(
            new_defender,
            wounds_pending,
            attacker_id=attacker.id,
            start_sequence=next_sequence,
            prefer_hero=False,
        )
        events.extend(killed_b)

    # Pkt 20.c bilans wręcz: attacker.damage_balance += dealt; defender -=
    new_attacker = replace(attacker, damage_balance=attacker.damage_balance + total_wounds)
    new_defender = replace(
        new_defender, damage_balance=new_defender.damage_balance - total_wounds
    )

    return CombatResult(
        events=tuple(events),
        new_attacker=new_attacker,
        new_defender=new_defender,
    )


# ---------------------------------------------------------------------------
# Public — resolve_charge_attack (Szarża pkt 14.d + reactive kontratak pkt 14.d.iv)
# ---------------------------------------------------------------------------

# Passive ability sluggi dotyczące reactive kontrataku (Szarża pkt 14.d.iv)
ABILITY_BASTION = "bastion"  # nie zostajesz Wyczerpany po kontrataku (id 1)
ABILITY_KONTRA = "kontra"  # kontratak przed atakami szarżującego (id 10)
ABILITY_FURIA = "furia"  # dodatkowe trafienia szarżującego (id 7)


def _matching_closed_charge(
    state: BattleState,
    charger: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    counter_attack_declared: bool,
) -> AttackState | None:
    activation = state.activation
    if activation is None or activation.phase is not ActivationPhase.ATTACK_RESOLUTION_READY:
        return None
    attack = activation.attack
    if attack is None or not isinstance(attack.intent, ChargeAttackIntent):
        return None
    intent = attack.intent
    if (
        intent.attacker_unit_id == charger.id
        and intent.target_unit_id == defender.id
        and intent.weapon_slug == weapon.slug
        and intent.counter_attack_declared == counter_attack_declared
    ):
        return attack
    return None


@dataclass(frozen=True, slots=True)
class ChargeResult:
    """Output `resolve_charge_attack` per pkt 14.d.

    `events` — sekwencyjne eventy w kolejności: charger MoveExecuted (Związanie),
    potencjalnie defender MeleeResolved + ModelKilled (kontratak pkt 14.d.iv),
    charger MeleeResolved + ModelKilled (główny atak).
    `new_charger` / `new_defender` — zaktualizowane bloby.
    """

    events: tuple[BattleEvent, ...]
    new_charger: UnitBlob
    new_defender: UnitBlob


def resolve_charge_attack(
    state: BattleState,
    charger: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    dice: DeterministicDice,
    sequence: int,
    *,
    counter_attack_declared: bool = True,
) -> ChargeResult:
    """Pełna Szarża (pkt 14.d.i-vi) z reactive window kontrataku (ADR-0015a).

    Sekwencja:
    1. **Pkt 14.d.ii (Związanie)** — emit `MoveExecuted` z `move_type="binding"`
       od `charger.position` do pozycji 1″ od `defender.position`.
    2. **Pkt 14.d.iv (Kontratak — reactive window)** — jeśli defender NIE
       Wyczerpany i `counter_attack_declared`: defender wykonuje pełen
       `resolve_melee_attack` jako attacker → charger; po kontrataku defender
       otrzymuje status `Wyczerpany` (chyba że ma `bastion`, id 1).
       Per **ADR-0015a**: reactive jednorazowe + atomowe + bez nested.
    3. **Pkt 14.d.iii (Główny atak)** — charger wykonuje `resolve_melee_attack`.
       Pominięty jeśli charger został pokonany w kontrataku.
    4. **Pkt 14.d.vi** — Szarża można wykonać raz w aktywacji (enforce w `phases.py`).

    W prywatnej Szarży v3 faktycznie wykonany kontratak z Kontrą (poz. 10)
    odbiera szarżującemu Furię dla głównego ataku. Kolejność MVP jest wspólna
    z pozostałymi wywołaniami.

    Args:
        state, charger, defender, weapon, dice, sequence: jak w resolve_melee_attack
        counter_attack_declared: czy obrońca deklaruje kontratak (gracz/AI decyzja
            spoza engine; default True dla MVP).

    Returns:
        ChargeResult z eventami w kolejności + new_charger + new_defender.
    """
    events: list[BattleEvent] = []
    next_seq = sequence
    closed_attack = _matching_closed_charge(
        state, charger, defender, weapon, counter_attack_declared
    )

    # Faza 1: Związanie (pkt 14.d.ii) — emit MoveExecuted
    # MVP: binding ruch do 1″ od obwodu defendera w prostej linii.
    # B3.9.b fix #4: minimalna pozycja końcowa (gap między **obwodami** kół) =
    # 1″, czyli `distance(centers) >= charger.radius + defender.radius + 1.0`.
    # Przed fixem: `min_gap = defender.radius + 1.0` ignorował `charger.radius`
    # i pozwalał obwodom kół przenikać o `charger.radius` cali.
    dx = defender.position.x - charger.position.x
    dy = defender.position.y - charger.position.y
    dist = distance(charger.position, defender.position)
    if dist > 0:
        # `min_gap` = minimalna odległość między centrami żeby obwody były
        # rozdzielone o ≥ 1″ (Pareto MVP — pkt 14.d.ii Związanie do "stykania
        # się podstawek" interpretowane jako 1″ z marginesem przeciw flicker).
        min_gap = defender.radius_inches + charger.radius_inches + 1.0
        edge_gap = circle_edge_distance(
            charger.position, charger.radius_inches,
            defender.position, defender.radius_inches,
        )
        if edge_gap > 1.0:
            # Charger przesuwa się tak, żeby zostać `min_gap` od centrum defendera.
            t = (dist - min_gap) / dist
            new_x = charger.position.x + t * dx
            new_y = charger.position.y + t * dy
        else:
            # Już w zasięgu Związania — bez ruchu.
            new_x = charger.position.x
            new_y = charger.position.y
        # B3.9.f cleanup: function-local `_MoveExecuted` import usunięty — używamy
        # `MoveExecuted` z module-level imports (linia 46) bez aliasu.
        events.append(
            MoveExecuted(
                sequence=next_seq,
                unit_id=charger.id,
                from_pos=(charger.position.x, charger.position.y),
                to_pos=(new_x, new_y),
                move_type="binding",
            )
        )
        next_seq += 1
        new_charger = replace(charger, position=Position(new_x, new_y))
    else:
        new_charger = charger

    new_defender = defender

    # Faza 2: Kontratak pkt 14.d.iv (reactive window — ADR-0015a)
    can_counter = (
        counter_attack_declared
        and STATUS_WYCZERPANY not in defender.status_flags
        and defender.models_alive > 0
    )
    if can_counter:
        # B3.9.e fix #7 (ADR-0047) + CR-fix E: defender używa SWOJEJ broni wręcz
        # z `melee_weapons` inventory. Fallback do `UNARMED_WEAPON` (1 atak,
        # AP 0) gdy inventory pusty — explicit "unarmed defender" semantyka.
        # Pre-CR-fix-E fallback wracał do `weapon` argumentu (broń atakującego)
        # — silently reintroducing bug #7 dla ranged-only units.
        defender_weapon = (
            new_defender.melee_weapons[0]
            if new_defender.melee_weapons
            else UNARMED_WEAPON
        )
        counter_result = resolve_melee_attack(
            state, new_defender, new_charger, defender_weapon, dice, next_seq,
            canonical_aliases=closed_attack is not None,
        )
        events.extend(counter_result.events)
        next_seq += len(counter_result.events)
        # Po kontrataku: Wyczerpany (chyba że Bastion id 1 lub charger pokonany).
        # Pkt 14.d.iv R5.c (2026-06): jeśli charger models_alive == 0 → skip.
        # B3.9.d (ADR-0046) — emit StatusAdded event + idempotentny `add_status`.
        # Reducer `_reduce_status_added` rekonstruuje status_flags w replay.
        post_counter_defender = counter_result.new_attacker
        charger_after_counter = counter_result.new_defender
        if (
            charger_after_counter.models_alive > 0
            and ABILITY_BASTION not in effective_passives(post_counter_defender)
            and STATUS_WYCZERPANY not in post_counter_defender.status_flags
        ):
            post_counter_defender = add_status(post_counter_defender, STATUS_WYCZERPANY)
            events.append(
                StatusAdded(
                    sequence=next_seq,
                    target_id=post_counter_defender.id,
                    status=STATUS_WYCZERPANY,
                )
            )
            next_seq += 1
        new_defender = post_counter_defender
        new_charger = charger_after_counter

    # Faza 3: Główny atak szarżującego pkt 14.d.iii — pominięty jeśli charger pokonany
    if new_charger.models_alive > 0 and new_defender.models_alive > 0:
        charging_attack = closed_attack
        if charging_attack is not None and can_counter and ABILITY_KONTRA in effective_passives(defender):
            charging_attack = None
        charge_result = resolve_melee_attack(
            state, new_charger, new_defender, weapon, dice, next_seq,
            charging_attack=charging_attack,
            canonical_aliases=closed_attack is not None,
        )
        events.extend(charge_result.events)
        next_seq += len(charge_result.events)
        new_charger = charge_result.new_attacker
        new_defender = charge_result.new_defender

    return ChargeResult(
        events=tuple(events),
        new_charger=new_charger,
        new_defender=new_defender,
    )
