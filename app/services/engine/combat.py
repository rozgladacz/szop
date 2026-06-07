"""B3.4 — Combat resolution (`SZOP_Rozjemca.md pkt 14.c-d + 17 + 18 + 19`).

Funkcje publiczne:
- `resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence, terrain)`
- `resolve_melee_attack(state, attacker, defender, weapon, dice, sequence, *, is_charger, is_counter_attack)`

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

Reactive window (pkt 14.d.iv — kontratak w Szarży) zaplanowany w `resolve_charge_attack`
(future, B3.4 extension). MVP `resolve_melee_attack` jest pojedynczym atakiem (bez
Szarży/kontrataku) z `melee_balance` accounting per pkt 20.c.

Weapon abilities w MVP scope:
- **AP(X)** (id 55) — modyfikator obrony `-X` (effective higher threshold)
- **Brutalny** (id 57) — `natural_6_auto_success=False` w testach obrony
- **Precyzyjny** (id 68) — wszystkie rany → pula atakującego

Pozostałe weapon abilities (Furia, Impet, Podwójny, Przebijająca, Zabójczy,
Dezintegracja, Niezawodny, Niebezpośredni, etc.) → B3.5 `effects.py` lub
przyszłe iteracje. `RollResult.rolls` zachowuje natural values dla inspekcji.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    BattleEvent,
    MeleeResolved,
    ModelKilled,
    MoveExecuted,
    ShotResolved,
    StatusAdded,
)
from app.services.engine.geometry import circle_edge_distance, distance, point_in_circle
from app.services.engine.los import LoSState, check_los
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Position,
    TerrainCircle,
    TerrainLine,
    UNARMED_WEAPON,
    UnitBlob,
    WeaponProfile,
)
from app.services.engine.status import STATUS_WYCZERPANY, add_status


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


def _apply_podwojny_extra_hits(hit_result, weapon: WeaponProfile) -> int:
    """Podwojny (id 66): "6 na trafienie dają dodatkowe normalne trafienie".

    Post-process inspekcja `hit_result.rolls`: za każdą naturalną 6 dorzucamy
    +1 trafienie (poza zwykłym sukcesem z auto-6). Zwraca total hits po
    augmentation.
    """
    hits = hit_result.successes
    if ABILITY_PODWOJNY in weapon.weapon_abilities:
        extra = sum(1 for r in hit_result.rolls if r == 6)
        hits += extra
    return hits


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


# ---------------------------------------------------------------------------
# Helpers — Osłona pkt 19, modifiers
# ---------------------------------------------------------------------------


def _blob_inside_circle(blob: UnitBlob, terrain: TerrainCircle) -> bool:
    """Centrum bloba ≤ radius od centrum koła."""
    return point_in_circle(blob.position, terrain.center, terrain.radius_inches)


def compute_cover(
    attacker: UnitBlob,
    defender: UnitBlob,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
) -> bool:
    """True gdy defender ma osłonę (pkt 19).

    Pkt 19: "Jeżeli większość modeli atakowanego oddziału ma osłonę". W Pareto
    MVP (oddział = blob) sprawdzamy:
    - LoS state OSLONA z `check_los`, **lub**
    - defender wewnątrz `TerrainCircle` z cechą `Obronny` (pkt 4.c.vi).
    """
    terrain_list = list(terrain)
    los_state = check_los(attacker, defender, terrain_list)
    if los_state == LoSState.OSLONA:
        return True
    for t in terrain_list:
        if isinstance(t, TerrainCircle) and FEATURE_OBRONNY in t.features:
            if _blob_inside_circle(defender, t):
                return True
    return False


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
    """
    new_received = defender.wounds_received + wounds_to_alloc
    new_models = defender.models_alive
    new_hero = defender.is_hero_unit
    killed_events: list[ModelKilled] = []
    seq = start_sequence

    tou = defender.toughness_per_model
    while new_received >= tou and new_models > 0:
        new_received -= tou
        new_models -= 1
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
                by_attacker_id=attacker_id,
            )
        )
        seq += 1

    new_defender = replace(
        defender,
        models_alive=new_models,
        wounds_received=new_received if new_models > 0 else 0,
        is_hero_unit=new_hero,
        # Pkt 27.b: gdy ostatni model oddziału zostaje pokonany, cały oddział
        # staje się Wycofany. ELIMINOWANY (pkt 27.a, broń Zguba) odłożone do
        # R4.Zguba — domyślnym przypadkiem pokonania jest WYCOFANY (pkt 26.c).
        location=Lokalizacja.WYCOFANY if new_models == 0 else defender.location,
    )
    return new_defender, tuple(killed_events), seq


# ---------------------------------------------------------------------------
# Public — resolve_ranged_attack
# ---------------------------------------------------------------------------


def resolve_ranged_attack(
    state: BattleState,
    attacker: UnitBlob,
    defender: UnitBlob,
    weapon: WeaponProfile,
    dice: DeterministicDice,
    sequence: int,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
) -> CombatResult:
    """Resolves Ostrzał (pkt 14.c + 17 + 18 + 19).

    Pure function. Brak DB access, brak mutation `state`/`attacker`/`defender`.

    Args:
        state: aktualny BattleState (read-only; pozwala query na inne bloby/teren).
        attacker, defender: zamieszane bloby.
        weapon: profile broni atakującego.
        dice: DeterministicDice; konsumuje rolls deterministycznie.
        sequence: pierwszy sequence dla generowanych eventów.
        terrain: lista terrainów; dla Osłony pkt 19.

    Returns:
        CombatResult(events, new_attacker, new_defender).
    """
    del state  # MVP: state nie wpływa na pojedynczy ranged attack poza tymi argami
    terrain_list = list(terrain)

    # Faza 1 — Declare + modifiers
    has_cover = compute_cover(attacker, defender, terrain_list)
    attack_quality = effective_attack_quality(weapon, attacker)
    attack_modifier, extra_defense_bonus = compute_attack_modifiers(
        attacker_quality=attack_quality, has_cover=has_cover
    )
    defense_modifier = compute_defense_modifier(
        weapon_ap=weapon.ap, extra_defense_bonus=extra_defense_bonus
    )

    # Passive modifiers z effects.py (Cierpliwy/Tarcza/Ostrożny/etc.)
    attack_modifier += _aggregate_passive_attack(attacker, weapon=weapon)
    defense_modifier += _aggregate_passive_defense(defender, weapon=weapon)

    is_precyzyjny = ABILITY_PRECYZYJNY in weapon.weapon_abilities
    is_brutalny = ABILITY_BRUTALNY in weapon.weapon_abilities

    # Faza 2 — Dice (per model living attacker rolls weapon.attacks dice)
    total_attacks = attacker.models_alive * weapon.attacks
    hit_result = dice.roll_with_threshold(
        count=total_attacks,
        threshold=attack_quality,
        modifier=attack_modifier,
    )
    # Podwójny (id 66): natural 6 trafienia → dodatkowe normalne trafienie
    hits = _apply_podwojny_extra_hits(hit_result, weapon)

    # Per trafienie → test obrony
    wounds_pending = 0
    wounds_pending_precise = 0
    if hits > 0:
        defense_result = dice.roll_with_threshold(
            count=hits,
            threshold=defender.defense,
            modifier=defense_modifier,
            natural_6_auto_success=not is_brutalny,
        )
        # Każda porażka obrony → rana; klasyfikacja per pkt 17.d
        # 17.d.i: pula atakującego gdy naturalna 1 + effective threshold > 2+
        # 17.d.ii: pula obrońcy w pozostałych
        # Precyzyjny (id 68): wszystkie rany do puli atakującego.
        # B3.9.f cleanup: usunięty dead-loop `for r in defense_result.rolls: if r == 1: continue`
        # (no-op, TODO marker który nigdy nie dostał logiki — faktyczna logika w
        # `if failed_count > 0` poniżej, gdzie liczymy natural_ones_count).
        failed_count = hits - defense_result.successes
        if failed_count > 0:
            if is_precyzyjny:
                wounds_pending_precise = failed_count
            else:
                # Per pkt 17.d.i: natural 1 + effective_threshold > 2 → pula attacker
                # Liczymy ile failed rolls miało natural 1 (każdy 1 jest auto-fail per 1.c).
                if defense_result.effective_threshold > 2:
                    natural_ones_count = sum(
                        1 for r in defense_result.rolls if r == 1
                    )
                    wounds_pending_precise = natural_ones_count
                    wounds_pending = failed_count - natural_ones_count
                else:
                    wounds_pending = failed_count

    # Emit ShotResolved event
    events: list[BattleEvent] = [
        ShotResolved(
            sequence=sequence,
            attacker_id=attacker.id,
            defender_id=defender.id,
            weapon_slug=weapon.slug,
            hits=hits,
            wounds_dealt=wounds_pending,
            wounds_precise=wounds_pending_precise,
        )
    ]
    next_sequence = sequence + 1

    # Faza 3 — Wound allocation (pkt 17.e + 18)
    new_defender = defender
    # Pula atakującego najpierw (pkt 17.e: "najpierw w całości pulę atakującego")
    if wounds_pending_precise > 0:
        new_defender, killed_a, next_sequence = _allocate_wounds_to_defender(
            new_defender,
            wounds_pending_precise,
            attacker_id=attacker.id,
            start_sequence=next_sequence,
            prefer_hero=True,
        )
        events.extend(killed_a)
    # Pula obrońcy potem
    if wounds_pending > 0:
        new_defender, killed_b, next_sequence = _allocate_wounds_to_defender(
            new_defender,
            wounds_pending,
            attacker_id=attacker.id,
            start_sequence=next_sequence,
            prefer_hero=False,
        )
        events.extend(killed_b)

    return CombatResult(
        events=tuple(events),
        new_attacker=attacker,  # ranged: attacker nie ulega zmianie
        new_defender=new_defender,
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
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
) -> CombatResult:
    """Resolves pojedynczy atak wręcz (pkt 17 + 20.c bilans).

    Brak Szarży / kontrataku — to integracja w przyszłym `resolve_charge_attack`
    (B3.4 extension). MVP traktuje jako pojedynczy atak wręcz; `melee_balance`
    update per pkt 20.c (Przegrupowanie sprawdzi w `phases.py` B3.6).

    Algorithm:
    1. Faza 1: brak LoS (wręcz), brak Osłony pkt 19 standard (osłona dotyczy
       głównie ranged; Parowanie id 24 daje osłonę w walce wręcz — passive,
       B3.5).
    2. Faza 2: hit roll (attacker.quality) → defense roll (defender.defense),
       Brutalny / Precyzyjny / AP per ranged.
    3. Faza 3: alokacja per pkt 17.d-e + 18. Bilans wręcz:
       - `attacker.melee_balance += wounds_dealt`
       - `defender.melee_balance -= wounds_dealt`
    """
    del state, terrain  # melee MVP: brak osłony / cover (Parowanie id 24 → B3.5+)
    attack_quality = effective_attack_quality(weapon, attacker)
    is_precyzyjny = ABILITY_PRECYZYJNY in weapon.weapon_abilities
    is_brutalny = ABILITY_BRUTALNY in weapon.weapon_abilities

    # Passive modifiers (Cierpliwy/Tarcza dla obrońcy; Ostrożny/Przygotowanie/etc. dla atakującego)
    attack_modifier = _aggregate_passive_attack(attacker, weapon=weapon)
    defense_modifier = -weapon.ap + _aggregate_passive_defense(defender, weapon=weapon)

    # Faza 2 — Dice
    total_attacks = attacker.models_alive * weapon.attacks
    hit_result = dice.roll_with_threshold(
        count=total_attacks,
        threshold=attack_quality,
        modifier=attack_modifier,
    )
    hits = _apply_podwojny_extra_hits(hit_result, weapon)

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

    events: list[BattleEvent] = [
        MeleeResolved(
            sequence=sequence,
            attacker_id=attacker.id,
            defender_id=defender.id,
            weapon_slug=weapon.slug,
            hits=hits,
            wounds_dealt=wounds_pending,
            wounds_precise=wounds_pending_precise,
        )
    ]
    next_sequence = sequence + 1

    # Faza 3 — Wound allocation
    new_defender = defender
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

    # Pkt 20.c bilans wręcz: attacker.melee_balance += dealt; defender -=
    new_attacker = replace(attacker, melee_balance=attacker.melee_balance + total_wounds)
    new_defender = replace(
        new_defender, melee_balance=new_defender.melee_balance - total_wounds
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

    Kontra (id 10) modyfikuje timing kontrataku (sygnalizowane przez Kontra w
    `defender.passives`); semantyka MVP: kontratak nadal "przed atakami" — to
    zgodne z default sequence (pkt 14.d.iv mówi "przerwać żeby kontratak").
    Wpływ na zdolności Furia/Impet (wyłącza "szarżującego") — implementacja
    odłożona do momentu gdy Furia/Impet są w combat scope.

    Args:
        state, charger, defender, weapon, dice, sequence: jak w resolve_melee_attack
        counter_attack_declared: czy obrońca deklaruje kontratak (gracz/AI decyzja
            spoza engine; default True dla MVP).

    Returns:
        ChargeResult z eventami w kolejności + new_charger + new_defender.
    """
    events: list[BattleEvent] = []
    next_seq = sequence

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
            state, new_defender, new_charger, defender_weapon, dice, next_seq
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
            and ABILITY_BASTION not in post_counter_defender.passives
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
        charge_result = resolve_melee_attack(
            state, new_charger, new_defender, weapon, dice, next_seq
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
