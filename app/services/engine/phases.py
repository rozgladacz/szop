"""B3.6 — Phase composition (`SZOP_Rozjemca.md pkt 7-21 + 8.c`).

Public API:
- `setup_phase(rosters, terrain, objectives, initiative_player, ruleset_version)`
  → BattleState — pkt 7 + pkt 9 init (round 0, brak rozstawienia)
- `deployment_round(state, deployment_actions)` → (BattleState, events) — pkt 13
- `activation_phase(state, action, dice)` → (BattleState, events) — pkt 11.b + 14
  + 20 (Przegrupowanie po akcji)
- `round_end_phase(state)` → (BattleState, events) — pkt 8.c (reset Aktywowany +
  objective control + RoundEnded; pkt 5.f game over after round 4)

MVP scope:
- Pojedyncza akcja per `activation_phase` call (zamiast pętli pkt 11.b.iii — 2 akcje).
  Engine wyżej (resolver B3.7) może wywołać 2× dla 2 akcji.
- Aktywne abilities (pkt 14.e) ograniczone do `discard_exhausted` (uniwersalny).
  Konkretne aktywne zdolności (Łatanie/Mag/etc.) dorzucane stopniowo.
- Przegrupowanie pkt 20: prosty test — jeśli wounds_received > 0 w aktywacji,
  test z bazą 1 + modifiers (np. Nieustraszony -1). Pkt 20.b (<=½ wytrzymałości)
  i pkt 20.c (bilans wręcz) zaimplementowane.
- Odzyskiwanie ran (pkt 21): MVP placeholder — pusty step (Regeneracja/Odrodzenie
  dorzucane w B3.5+ effects).

Kompozycja: każda funkcja jest **pure** (state in → state+events out). Zero DB.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.combat import (
    _allocate_wounds_to_defender,
    resolve_charge_attack,
    resolve_melee_attack,
    resolve_ranged_attack,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    BattleEvent,
    EffectApplied,
    MeleeBalanceReset,
    MoraleTestPassed,
    MoveExecuted,
    MutexCollision,
    ObjectiveControlChanged,
    RoundEnded,
    StatusAdded,
    StatusRemoved,
)
from app.services.engine.geometry import distance as _distance
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    build_initial_state,
    initial_toughness_for,
)
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYSZPILONY,
    STATUS_UFORTYFIKOWANY,
    STATUS_WYCZERPANY,
    add_status as _add_status,
    remove_status as _remove_status,
)

MAX_ROUND = 4  # pkt 5.f: gra kończy się po 4 rundach
OBJECTIVE_CONTROL_RANGE = 3.0  # pkt 5.d: 3″ od celu


# ---------------------------------------------------------------------------
# ActivationContext (B3.9.c / ADR-0045) — per-aktywacja delta state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivationContext:
    """Transient kontekst dla pojedynczej aktywacji (pkt 11.b).

    Rozwiązuje dziurę A z post-B3 code review — rozróżnienie między **trwałym
    stanem** (cumulative `wounds_received` na `UnitBlob`, persisted) a **deltą
    tej aktywacji** (pkt 20.a "oddziały które otrzymały rany W TEJ
    aktywacji"). Przed B3.9.c regroup test używał cumulative `wounds_received`
    jako proxy — bug #1 (oddział z 1 raną z poprzedniej aktywacji + 0 ran w
    tej musi NIE wykonywać testu pkt 20.a, ale proxy zwracał True).

    Pola:
    - `actor_id` — oddział wykonujący aktywację (pkt 11.b.i).
    - `wounds_received_this_activation` — frozen mapa `unit_id → delta_wounds`.
      Pokrywa **wszystkie** oddziały które otrzymały rany w tej aktywacji, nie
      tylko aktora (defender szarży otrzymuje rany w aktywacji chargera per
      pkt 14.d → musi przejść Przegrupowanie w aktywacji chargera, pkt 20.a —
      bug #2).
    - `melee_combatants` — frozenset id-ów uczestników starcia wręcz (actor +
      defender(s) z ChargeAction). Używany dla reset `melee_balance` na obu
      stronach po regroup (pkt 20.c — bilans wręcz resetowany dla obu stron,
      bug #5).

    Reprezentacja `tuple[tuple[int, int], ...]` zamiast `dict` zachowuje
    frozen-dataclass purity (brak referencji do mutable dict).
    """

    actor_id: int
    wounds_received_this_activation: tuple[tuple[int, int], ...]
    melee_combatants: frozenset[int]
    # R5.d 2026-06 — default () dla backward compat (test fixtures konstruujące
    # ActivationContext bezpośrednio bez `wounds_dealt`). Production path przez
    # `_build_activation_context` zawsze populuje.
    wounds_dealt_this_activation: tuple[tuple[int, int], ...] = ()

    def delta_for(self, unit_id: int) -> int:
        """Lookup delta_wounds OTRZYMANYCH dla `unit_id`. Zwraca 0 gdy oddział
        nie otrzymał ran w tej aktywacji."""
        for uid, delta in self.wounds_received_this_activation:
            if uid == unit_id:
                return delta
        return 0

    def dealt_for(self, unit_id: int) -> int:
        """Lookup wounds_dealt dla `unit_id`. Zwraca 0 gdy oddział nie zadał ran
        w tej aktywacji. (R5.d 2026-06 — pkt 20.a NEW trigger: received > dealt.)"""
        for uid, dealt in self.wounds_dealt_this_activation:
            if uid == unit_id:
                return dealt
        return 0


def _build_activation_context(
    pre_wounds: Mapping[int, int],
    post_state: BattleState,
    actor_id: int,
    melee_combatants: frozenset[int],
    action_events: tuple[BattleEvent, ...] = (),
) -> ActivationContext:
    """Buduje `ActivationContext` z pre/post snapshot `wounds_received` per blob.

    Delta received = post - pre (klampowane do 0 — kill w aktywacji resetuje
    `wounds_received` ale to nie ujemna "ranność").

    R5.d (faza-b-rules-resync 2026-06): `wounds_dealt_this_activation` agregowane
    z `action_events` — ShotResolved/MeleeResolved emit `wounds_dealt + wounds_precise`
    per attacker_id. Używane przez `_regroup_test` dla pkt 20.a NEW trigger
    (received > dealt → test).
    """
    from app.services.engine.events import MeleeResolved, ShotResolved

    post_wounds = {b.id: b.wounds_received for b in post_state.blobs}
    received_deltas: list[tuple[int, int]] = []
    for uid in pre_wounds.keys() | post_wounds.keys():
        delta = post_wounds.get(uid, 0) - pre_wounds.get(uid, 0)
        if delta > 0:
            received_deltas.append((uid, delta))

    # R5.d: agregacja wounds_dealt per attacker_id z combat events.
    dealt_map: dict[int, int] = {}
    for event in action_events:
        if isinstance(event, (ShotResolved, MeleeResolved)):
            total = event.wounds_dealt + event.wounds_precise
            if total > 0:
                dealt_map[event.attacker_id] = dealt_map.get(event.attacker_id, 0) + total
    dealt_deltas = sorted(dealt_map.items())

    return ActivationContext(
        actor_id=actor_id,
        wounds_received_this_activation=tuple(sorted(received_deltas)),
        wounds_dealt_this_activation=tuple(dealt_deltas),
        melee_combatants=melee_combatants,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_blob(state: BattleState, unit_id: int) -> UnitBlob:
    for b in state.blobs:
        if b.id == unit_id:
            return b
    raise ValueError(f"Unit {unit_id} not found in state")


def _replace_blob(state: BattleState, new_blob: UnitBlob) -> BattleState:
    """Zwraca nowy BattleState z `blobs` zaktualizowanymi (`new_blob` zastępuje swój
    wpis po id)."""
    new_blobs = tuple(new_blob if b.id == new_blob.id else b for b in state.blobs)
    return replace(state, blobs=new_blobs)


def _replace_two_blobs(
    state: BattleState, blob_a: UnitBlob, blob_b: UnitBlob
) -> BattleState:
    new_blobs = tuple(
        blob_a if b.id == blob_a.id else (blob_b if b.id == blob_b.id else b)
        for b in state.blobs
    )
    return replace(state, blobs=new_blobs)


# ---------------------------------------------------------------------------
# setup_phase
# ---------------------------------------------------------------------------


def setup_phase(
    rosters: Iterable[dict],
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
    objectives: Iterable[Objective] = (),
    initiative_player: int = 0,
    ruleset_version: str = "v1",
) -> BattleState:
    """Buduje początkowy `BattleState` (pkt 7 — Przygotowanie gry + pkt 9 init).

    Per pkt 7: gracze ustalają zasady, przygotowują armie, losują inicjatywę,
    rozstawiają teren i cele. MVP: argumenty wejściowe (rosters/terrain/objectives/
    initiative) ustalone przez wyższą warstwę (UI / API B4). Engine tylko
    konstruuje state.

    `round=0` = runda rozstawienia (pkt 9). Po deployment_round → round=1.
    `active_player = initiative_player` — gracz z inicjatywą rozpoczyna.
    Walidacja exclusion list w `build_initial_state` (ADR-0008).
    """
    state = build_initial_state(
        rosters=rosters, terrain=terrain, ruleset_version=ruleset_version
    )
    return replace(
        state,
        active_player=initiative_player,
        objectives=tuple(objectives),
    )


# ---------------------------------------------------------------------------
# deployment_round
# ---------------------------------------------------------------------------


def deployment_round(
    state: BattleState,
    deployment_actions: Iterable[DeploymentAction],
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 13 — Aktywacje rozstawienia w kolejności podanej przez deployment_actions.

    Każda akcja umieszcza oddział w `position` (gracz odpowiada za legalność —
    engine emit MoveExecuted z move_type='deploy'). Oddział otrzymuje status
    Aktywowany (pkt 13.c).

    Po wszystkich akcjach: round = 1, status Aktywowany resetowany (engine
    automatycznie — pkt 8.c.i znajdziemy w `round_end_phase`, ale dla rundy 0
    deployment-only round bez round_end). MVP: reset tutaj.
    """
    events: list[BattleEvent] = []
    seq = 1
    current = state
    for action in deployment_actions:
        blob = _find_blob(current, action.unit_id)
        events.append(
            MoveExecuted(
                sequence=seq,
                unit_id=blob.id,
                from_pos=(blob.position.x, blob.position.y),
                to_pos=(action.position.x, action.position.y),
                move_type="deploy",
            )
        )
        seq += 1
        moved = replace(blob, position=action.position)
        current = _replace_blob(current, moved)

    # R5.f pkt 13.c (faza-b-rules-resync 2026-06): KAŻDY rozstawiony oddział
    # (niezależnie czy explicit DeploymentAction wykonana) zyskuje Ufortyfikowany
    # na początek rundy 1. Persists do startu własnej aktywacji (CR-fix G:
    # pkt 22.c.iv usuwa na początku aktywacji actor-a).
    # Finding #3 (2026-06-06): tylko oddziały ROZSTAWIONE na planszy (pkt 13.c
    # "każdy rozstawiony oddział"). Rezerwy off-board (ZAPLECZE: Zasadzka/
    # Rezerwa, pkt 26) rozstawiają się dopiero później — nie fortyfikujemy ich
    # w rundzie 1.
    for b in current.blobs:
        if (
            b.models_alive > 0
            and b.location != Lokalizacja.ZAPLECZE
            and STATUS_UFORTYFIKOWANY not in b.status_flags
        ):
            new_b = _add_status(b, STATUS_UFORTYFIKOWANY)
            current = _replace_blob(current, new_b)
            events.append(
                StatusAdded(
                    sequence=seq,
                    target_id=b.id,
                    status=STATUS_UFORTYFIKOWANY,
                )
            )
            seq += 1

    # Po deployment: round = 1, status Aktywowany resetowany przed pierwszą rundą
    reset_blobs = tuple(_remove_status(b, STATUS_AKTYWOWANY) for b in current.blobs)
    current = replace(current, blobs=reset_blobs, round=1)
    return current, tuple(events)


# ---------------------------------------------------------------------------
# Action dispatch — sub-helpers per akcja
# ---------------------------------------------------------------------------


def _apply_maneuver(
    state: BattleState,
    action: ManeuverAction,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.a Manewr — emit MoveExecuted, update position. Walidacja
    dist ≤ move_inches deferred do resolver/walidacji wyżej.

    R5.g (faza-b-rules-resync 2026-06): po move, jeśli aktor jest wewnątrz
    TerrainCircle z feature `Niebezpieczny` (pkt 4.c.v) → wykonaj test
    **per-unit**: rzut `models_alive * toughness_per_model` k6, każda 1 = rana.
    Drift uproszcza pre-drift per-model (każdy model rzucał toughness razy)
    do jednego wspólnego puli. Rany przechodzą przez standardową alokację
    (`_allocate_wounds_to_defender`, self-inflicted: attacker_id=None) — pula
    nadwyżkowa zostaje jako znaczniki (pkt 18.c), a każdy pełny komplet
    `toughness_per_model` ran pokonuje model (emit `ModelKilled`). Bez tego
    modele nigdy nie ginęły od terenu (code-review finding #1, 2026-06-06).

    Event sourcing (ADR-0046): `EffectApplied(niebezpieczny)` niesie surowe
    `wounds_inflicted` (reducer `_reduce_effect_applied` pushuje je na
    `wounds_received` przy replay) PRZED `ModelKilled`, które absorbują pulę —
    dzięki temu `apply_events` rekonstruuje stan bit-perfect (zamiast cichej
    mutacji `wounds_received` poza eventami).
    """
    blob = _find_blob(state, action.unit_id)
    events: list[BattleEvent] = []
    seq = sequence
    events.append(
        MoveExecuted(
            sequence=seq,
            unit_id=blob.id,
            from_pos=(blob.position.x, blob.position.y),
            to_pos=(action.target_position.x, action.target_position.y),
            move_type="manever",
        )
    )
    seq += 1
    moved = replace(blob, position=action.target_position)

    # R5.g pkt 4.c.v Niebezpieczny test (per-unit, post-drift 2026-06)
    in_dangerous = any(
        isinstance(t, TerrainCircle)
        and "Niebezpieczny" in t.features
        and _blob_inside_terrain_circle(moved, t)
        for t in state.terrain
    )
    if in_dangerous and moved.models_alive > 0:
        dice_count = moved.models_alive * moved.toughness_per_model
        rolls = dice.roll_d6(count=dice_count)
        wounds_inflicted = sum(1 for r in rolls if r == 1)
        if wounds_inflicted > 0:
            events.append(
                EffectApplied(
                    sequence=seq,
                    slug="niebezpieczny",
                    target_unit_id=moved.id,
                    source_unit_id=moved.id,
                    payload={
                        "applied": True,
                        "rolls": list(rolls),
                        "wounds_inflicted": wounds_inflicted,
                    },
                )
            )
            seq += 1
            # Finding #1 (2026-06-06): standardowa alokacja zamiast surowego
            # dopisania — self-inflicted (attacker_id=None, prefer_hero=False),
            # emit ModelKilled per pokonany model. SSOT z combat.
            moved, killed_events, seq = _allocate_wounds_to_defender(
                moved,
                wounds_inflicted,
                attacker_id=None,
                start_sequence=seq,
                prefer_hero=False,
            )
            events.extend(killed_events)

    return _replace_blob(state, moved), tuple(events), seq


def _blob_inside_terrain_circle(blob: UnitBlob, terrain: TerrainCircle) -> bool:
    """Helper: True gdy centrum bloba jest w obrębie `terrain` (TerrainCircle).
    R5.g — sprawdzanie czy oddział znajduje się w niebezpiecznym terenie
    po Manewrze. Używamy distance(blob.position, terrain.center) ≤ radius."""
    return _distance(blob.position, terrain.center) <= terrain.radius_inches


def _apply_defend(
    state: BattleState, action: DefendAction, sequence: int
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.b Obrona — oddział zyskuje Ufortyfikowany (pkt 22.c). Przyszpilony
    odrzucany (pkt 22.b.v: Przyszpilony zostaje odrzucony gdy oddział staje się
    Ufortyfikowany).

    B3.9.d (ADR-0046) — emit `StatusAdded(Ufortyfikowany)` + opcjonalny
    `StatusRemoved(Przyszpilony)` zamiast silent `replace(status_flags=...)`.
    `EffectApplied(slug="defend")` zachowany jako annotation/audit log (nie
    redukuje state — to dwa równolegle eventy: Status* niesie deltę state,
    EffectApplied niesie semantykę akcji).
    """
    blob = _find_blob(state, action.unit_id)
    had_przyszpilony = STATUS_PRZYSZPILONY in blob.status_flags
    blob = _add_status(blob, STATUS_UFORTYFIKOWANY)
    blob = _remove_status(blob, STATUS_PRZYSZPILONY)

    events: list[BattleEvent] = [
        EffectApplied(
            sequence=sequence,
            slug="defend",
            target_unit_id=blob.id,
            source_unit_id=blob.id,
            payload={"status_added": STATUS_UFORTYFIKOWANY},
        ),
        StatusAdded(
            sequence=sequence + 1,
            target_id=blob.id,
            status=STATUS_UFORTYFIKOWANY,
        ),
    ]
    next_seq = sequence + 2
    if had_przyszpilony:
        events.append(
            StatusRemoved(
                sequence=next_seq,
                target_id=blob.id,
                status=STATUS_PRZYSZPILONY,
            )
        )
        next_seq += 1
    return _replace_blob(state, blob), tuple(events), next_seq


def _apply_shoot(
    state: BattleState,
    action: ShootAction,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.c Ostrzał — delegacja do `combat.resolve_ranged_attack`."""
    attacker = _find_blob(state, action.unit_id)
    defender = _find_blob(state, action.target_id)
    result = resolve_ranged_attack(
        state, attacker, defender, action.weapon, dice, sequence, state.terrain
    )
    new_state = _replace_two_blobs(state, result.new_attacker, result.new_defender)
    return new_state, result.events, sequence + len(result.events)


def _apply_charge(
    state: BattleState,
    action: ChargeAction,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.d Szarża — delegacja do `combat.resolve_charge_attack`."""
    attacker = _find_blob(state, action.unit_id)
    defender = _find_blob(state, action.target_id)
    result = resolve_charge_attack(
        state, attacker, defender, action.weapon, dice, sequence,
        counter_attack_declared=action.counter_attack_declared,
    )
    new_state = _replace_two_blobs(state, result.new_charger, result.new_defender)
    return new_state, result.events, sequence + len(result.events)


def _apply_special(
    state: BattleState, action: SpecialAction, sequence: int
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.e Akcja specjalna — dispatcher do `_ACTIVE_ABILITY_REGISTRY`
    (B3.9.e / ADR-0047).

    Pre-B3.9.e: hardcoded `if slug == "discard_exhausted"` + fallback no-op dla
    pozostałych. Dziura E z post-B3 code review — nie skalowało się na ~6
    aktywnych zdolności z B3.0.1 audit (Łatanie/Mag/Mobilizacja/Presja/
    Przepowiednia/Męczennik) ani na przyszłe.

    Post-B3.9.e: lookup `effects.get_active_ability(slug)` → delegate do
    zarejestrowanego handlera (`discard_exhausted` + 6 stubów MVP w
    `effects.py`). Slug nieznany w registry → no-op `EffectApplied` annotation
    (akcja nadal legalna, ale nic nie robi — zgodne z poprzednią semantyką).
    """
    from app.services.engine.effects import get_active_ability

    blob = _find_blob(state, action.unit_id)
    handler = get_active_ability(action.ability_slug)
    if handler is not None:
        return handler(state, blob, dict(action.payload), sequence)
    # Slug spoza registry — zachowaj poprzedni no-op fallback.
    event = EffectApplied(
        sequence=sequence,
        slug=action.ability_slug,
        target_unit_id=blob.id,
        source_unit_id=blob.id,
        payload={"note": "active ability not registered", **action.payload},
    )
    return state, (event,), sequence + 1


# ---------------------------------------------------------------------------
# Przegrupowanie (pkt 20) + Odzyskiwanie ran (pkt 21)
# ---------------------------------------------------------------------------


def _regroup_test(
    state: BattleState,
    blob_id: int,
    context: ActivationContext,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 20 Przegrupowanie (post-B3.9.c — delta-based per ADR-0045).

    Per pkt 20.a: test wykonują oddziały które otrzymały rany **w tej
    aktywacji** (delta `wounds_received_this_activation`, nie cumulative
    `blob.wounds_received`). Dodatkowo: oddział z `melee_balance < 0`
    (przegrał wręcz w tej aktywacji) wykonuje test choćby bez ran (pkt 20.c).

    Liczba testów:
    - Baseline: 1 (pkt 20.a)
    - +1 jeśli wytrzymałość ≤ ½ początkowej (pkt 20.b — initial z
      `state.initial_toughness_snapshot`, fallback do current models gdy brak
      snapshot dla test fixtures)
    - +1/-1 z bilansu wręcz (pkt 20.c)
    - +modifiers ze statusów (Przyszpilony +1, Ufortyfikowany -1) (pkt 20.d)
    - +morale_modifiers z passive abilities (Nieustraszony -1) (pkt 20.d)
    - Minimum 0

    Wyniki (pkt 20.e):
    - 0 fail: nic
    - 1 fail: Wyczerpany lub Przyszpilony (default Wyczerpany dla MVP)
    - 2 fail: Wyczerpany + Przyszpilony
    - ≥3 fail: pokonany

    Zwraca (new_state, events, next_sequence).
    """
    from app.services.engine.effects import EffectContext, aggregate_morale_modifier

    blob = _find_blob(state, blob_id)
    delta_received = context.delta_for(blob_id)
    delta_dealt = context.dealt_for(blob_id)
    # R5.d (faza-b-rules-resync 2026-06): pkt 20.a NEW trigger — oddział testuje
    # gdy ZADAŁ MNIEJ RAN NIŻ OTRZYMAŁ w aktywacji. Pre-drift trigger to było
    # `delta_received > 0 OR melee_balance < 0` (każdy kto otrzymał ranę).
    # Post-drift: tylko ten kto "przegrał wymianę" wykonuje test.
    if delta_received <= delta_dealt:
        return state, (), sequence

    n_tests = 1
    # Pkt 20.b: NIE-powyżej-połowy wytrzymałości → +1 test (drift 2026-06 —
    # semantyka równoważna pre-drift "current ≤ ½ INITIAL"). Snapshot z setup
    # (initial_toughness_for); fallback gdy snapshot empty (test fixtures).
    initial_tough = initial_toughness_for(state, blob_id)
    if initial_tough == 0:
        initial_tough = (
            blob.models_alive * blob.toughness_per_model + blob.wounds_received
        )
    current_toughness = blob.models_alive * blob.toughness_per_model - blob.wounds_received
    if current_toughness <= initial_tough / 2:
        n_tests += 1
    # R5.d pkt 20.c (drift 2026-06): walczył wręcz (był uczestnikiem starcia
    # w tej aktywacji — szarża jako actor LUB defender) → +1 test. Pre-drift
    # różnicowało wygranie (-1) vs przegrane (+1) wręcz przez `melee_balance`;
    # drift uproszcza do "walczył = +1 test" (sam udział w starciu = zamieszanie).
    if blob_id in context.melee_combatants:
        n_tests += 1
    # R5.c (faza-b-rules-resync 2026-06): pkt 20.d **status modifiers usunięte**
    # per drift — pkt 22.b.iv (Przyszpilony +1 test) i pkt 22.c.ii (Ufortyfikowany
    # -1 test) **usunięte** z zasad. Status flags pozostają (informacja o stanie),
    # ale nie wpływają na liczbę testów.
    # Passive morale modifiers (Nieustraszony -1 etc.) — pozostają (pkt 20.d
    # poprzez pasywne zdolności, nie statusy).
    n_tests += aggregate_morale_modifier(EffectContext(blob=blob))
    n_tests = max(0, n_tests)

    if n_tests == 0:
        return state, (), sequence

    # Rzuty: każdy test = k6, fail < 4+ (proxy MVP — pkt 20 nie definiuje
    # threshold; używamy 4+ jako commonly understood morale test)
    roll_result = dice.roll_with_threshold(count=n_tests, threshold=4)
    failures = n_tests - roll_result.successes

    # Mapping per pkt 20.e
    new_blob = blob
    if failures == 1:
        # MVP: default Wyczerpany (gracz wybiera w pkt 20.e.i, ale tu deterministyczny)
        new_blob = _add_status(new_blob, STATUS_WYCZERPANY)
        result_status = "exhausted"
    elif failures == 2:
        new_blob = _add_status(new_blob, STATUS_WYCZERPANY)
        new_blob = _add_status(new_blob, STATUS_PRZYSZPILONY)
        result_status = "exhausted_pinned"
    elif failures >= 3:
        # Oddział pokonany (pkt 20.f.iii). Pkt 27.b: pokonany oddział staje się
        # Wycofany (pkt 26.c domyślny przypadek; ELIMINOWANY tylko przy Zgubie,
        # pkt 26.d → R4.Zguba). Lustrzane do ścieżki ran
        # (combat._allocate_wounds_to_defender) — niezmiennik "pokonany → WYCOFANY".
        new_blob = replace(
            new_blob,
            models_alive=0,
            wounds_received=0,
            location=Lokalizacja.WYCOFANY,
        )
        result_status = "broken"
    else:
        result_status = "pass"

    event = MoraleTestPassed(
        sequence=sequence,
        unit_id=blob.id,
        rolls=roll_result.rolls,
        failures=failures,
        result_status=result_status,
    )
    return _replace_blob(state, new_blob), (event,), sequence + 1


# ---------------------------------------------------------------------------
# Mutex Przyszpilony↔Ufortyfikowany (pkt 22.b/c) — R5.e (resync 2026-06)
# ---------------------------------------------------------------------------


def _apply_mutex_collisions(
    state: BattleState,
    candidate_ids: Iterable[int],
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 22.b/c — Przyszpilony i Ufortyfikowany wzajemnie się wykluczają.

    R5.e (faza-b-rules-resync 2026-06 / decyzja H2 opcja (c)): gdy oddział po
    fazie akcji+Przegrupowania ma OBA statusy, oba zostają odrzucone. Jedyne
    miejsce powstania kolizji w MVP: `_regroup_test` dodaje Przyszpilony (2
    porażki) do oddziału który był Ufortyfikowany (np. defender szarży
    rozstawiony z Ufortyfikowany w rundzie 1, testujący Przegrupowanie w
    aktywacji chargera). Deployment (pkt 13.c) i Obrona (pkt 14.b) same w
    sobie nie kolidują — deployment startuje bez statusów, `_apply_defend`
    explicite usuwa Przyszpilony.

    Pipeline event-sourced: emit `MutexCollision(target_id, dropped_statuses)`
    + mutacja live state. Reducer (`reducers._reduce_mutex_collision`) aplikuje
    removal obu na replay. Deterministyczny porządek po id (stabilny replay).

    Returns: (new_state, events, next_sequence).
    """
    events: list[BattleEvent] = []
    seq = sequence
    for uid in sorted(set(candidate_ids)):
        blob = next((b for b in state.blobs if b.id == uid), None)
        if blob is None:
            continue
        if (
            STATUS_PRZYSZPILONY in blob.status_flags
            and STATUS_UFORTYFIKOWANY in blob.status_flags
        ):
            new_blob = _remove_status(blob, STATUS_PRZYSZPILONY)
            new_blob = _remove_status(new_blob, STATUS_UFORTYFIKOWANY)
            state = _replace_blob(state, new_blob)
            events.append(
                MutexCollision(
                    sequence=seq,
                    target_id=uid,
                    dropped_statuses=(STATUS_PRZYSZPILONY, STATUS_UFORTYFIKOWANY),
                )
            )
            seq += 1
    return state, tuple(events), seq


# ---------------------------------------------------------------------------
# activation_phase
# ---------------------------------------------------------------------------


def activation_phase(
    state: BattleState,
    action,  # Action union
    dice: DeterministicDice,
    sequence: int = 1,
    initial_toughness_totals: dict[int, int] | None = None,  # deprecated, B3.9.c
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 11.b — Zwykła aktywacja: akcja → Przegrupowanie → Odzyskiwanie ran →
    status Aktywowany.

    MVP scope: pojedyncza akcja (pkt 11.b.ii). Pętla 2 akcji (pkt 11.b.iii)
    eksponowana wyżej (B3.7 resolver).

    Post-B3.9.c per ADR-0045:
    - Snapshot `pre_wounds` per blob PRZED akcją; po akcji budujemy
      `ActivationContext` z deltą — _regroup_test używa kontekstu (pkt 20.a
      "w tej aktywacji" — fix bug #1).
    - Dla `ChargeAction`: defender jest w `melee_combatants` → wykonuje test
      Przegrupowania w aktywacji chargera (pkt 20.a, fix bug #2).
    - `melee_balance` resetowany na obu uczestnikach starcia wręcz (pkt 20.c,
      fix bug #5), nie tylko na actorze.

    Args:
        state: aktualny stan.
        action: jeden z `actions.Action` typów.
        dice: DeterministicDice.
        sequence: pierwszy sequence dla eventów.
        initial_toughness_totals: **DEPRECATED** (B3.9.c — używaj
            `state.initial_toughness_snapshot`). Parametr zachowany dla
            wstecznej kompatybilności wywołań spoza engine.

    Returns:
        (new_state, events).
    """
    events: list[BattleEvent] = []
    seq = sequence

    # B3.9.c: snapshot pre-action wounds_received per blob (do delty)
    pre_wounds: dict[int, int] = {b.id: b.wounds_received for b in state.blobs}

    actor_id = action.unit_id

    # CR-fix G (pkt 22.c.iv): Ufortyfikowany odrzucany na POCZĄTKU aktywacji
    # własnego oddziału. Pre-fix: status nigdy nie był usuwany — defender Defendu
    # z runda 1 niósł Ufortyfikowany przez całą grę (+1 obrona permanentnie).
    # Emit StatusRemoved + mutacja na live state (idempotentne — guard sprawdza
    # czy status faktycznie obecny).
    actor_pre = next((b for b in state.blobs if b.id == actor_id), None)
    if actor_pre is not None and STATUS_UFORTYFIKOWANY in actor_pre.status_flags:
        new_actor = _remove_status(actor_pre, STATUS_UFORTYFIKOWANY)
        state = _replace_blob(state, new_actor)
        events.append(
            StatusRemoved(
                sequence=seq,
                target_id=actor_id,
                status=STATUS_UFORTYFIKOWANY,
            )
        )
        seq += 1

    # Faza akcji (pkt 14)
    if isinstance(action, ManeuverAction):
        state, action_events, seq = _apply_maneuver(state, action, dice, seq)
        melee_combatants: frozenset[int] = frozenset()
    elif isinstance(action, DefendAction):
        state, action_events, seq = _apply_defend(state, action, seq)
        melee_combatants = frozenset()
    elif isinstance(action, ShootAction):
        state, action_events, seq = _apply_shoot(state, action, dice, seq)
        # Ostrzał (ranged) nie wywołuje starcia wręcz — brak combatants
        melee_combatants = frozenset()
    elif isinstance(action, ChargeAction):
        state, action_events, seq = _apply_charge(state, action, dice, seq)
        # Pkt 14.d Szarża → starcie wręcz między actor a target
        melee_combatants = frozenset({actor_id, action.target_id})
    elif isinstance(action, SpecialAction):
        state, action_events, seq = _apply_special(state, action, seq)
        melee_combatants = frozenset()
    else:
        raise TypeError(f"Unknown action type: {type(action).__name__}")
    events.extend(action_events)

    # Build ActivationContext (B3.9.c / ADR-0045 + R5.d 2026-06 — wounds_dealt)
    context = _build_activation_context(
        pre_wounds, state, actor_id, melee_combatants,
        action_events=tuple(action_events),
    )

    # Faza Przegrupowanie (pkt 20) — wszystkie oddziały które otrzymały rany
    # w tej aktywacji LUB są w melee_combatants (pkt 20.a + pkt 20.c).
    # Deterministyczny porządek po id żeby replay był stabilny.
    regroup_subjects: set[int] = {actor_id}
    regroup_subjects |= {uid for uid, _ in context.wounds_received_this_activation}
    regroup_subjects |= melee_combatants
    for subject_id in sorted(regroup_subjects):
        subject = next((b for b in state.blobs if b.id == subject_id), None)
        if subject is None or subject.models_alive == 0:
            continue
        state, regroup_events, seq = _regroup_test(
            state, subject_id, context, dice, seq
        )
        events.extend(regroup_events)

    # R5.e (resync 2026-06) pkt 22.b/c: mutex Przyszpilony↔Ufortyfikowany —
    # po Przegrupowaniu oddział który zyskał Przyszpilony (2 porażki) mając już
    # Ufortyfikowany traci oba. Kandydaci = subjects Przegrupowania (jedyne
    # miejsce dodania Przyszpilony w tej aktywacji).
    state, mutex_events, seq = _apply_mutex_collisions(
        state, regroup_subjects, seq
    )
    events.extend(mutex_events)

    # Faza Odzyskiwanie ran (pkt 21) — MVP placeholder (Regeneracja/Odrodzenie B3.5+)
    # NOTE: integration point dla Łatania (cel inny oddział) — gdy w event_chain
    # SpecialAction(latanie) pojawi się tu jako side-effect.

    # Reset `melee_balance` na OBU stronach starcia (bug #5 fix — pkt 20.c bilans
    # wręcz jest właściwością starcia, nie pojedynczego oddziału). B3.9.d emit
    # `MeleeBalanceReset` event per reset dla replay invariant (ADR-0046).
    for combatant_id in sorted(melee_combatants):
        combatant = next((b for b in state.blobs if b.id == combatant_id), None)
        if combatant is not None and combatant.models_alive > 0 and combatant.melee_balance != 0:
            state = _replace_blob(state, replace(combatant, melee_balance=0))
            events.append(MeleeBalanceReset(sequence=seq, target_id=combatant_id))
            seq += 1

    # Aktor otrzymuje status Aktywowany (pkt 11.b.vi). Sprawdzenie czy nadal istnieje.
    actor = _find_blob(state, actor_id) if any(b.id == actor_id for b in state.blobs) else None
    if actor is not None and actor.models_alive > 0:
        had_aktywowany = STATUS_AKTYWOWANY in actor.status_flags
        actor = _add_status(actor, STATUS_AKTYWOWANY)
        # B3.9.d (ADR-0046) — emit StatusAdded(Aktywowany) jeśli nie był już.
        if not had_aktywowany:
            events.append(
                StatusAdded(
                    sequence=seq,
                    target_id=actor.id,
                    status=STATUS_AKTYWOWANY,
                )
            )
            seq += 1
        # Pkt 22.c.iv: Ufortyfikowany odrzucany na początku aktywacji oddziału lub
        # gdy oddział staje się Przyszpilony — tu po Aktywowany interpretujemy
        # jako "koniec aktywacji" — Ufortyfikowany NIE jest odrzucany tu (per pkt
        # 22.c.iv: "na początku aktywacji oddziału"). MVP zostawia bez zmian.
        # Reset melee_balance dla actor (gdy nie był uczestnikiem starcia — np.
        # Ostrzał z rezultatem 0). Idempotent z resetem powyżej (jeśli był
        # combatant, melee_balance jest już 0). B3.9.d emit event dla replay.
        if actor.melee_balance != 0:
            actor = replace(actor, melee_balance=0)
            events.append(MeleeBalanceReset(sequence=seq, target_id=actor.id))
            seq += 1
        state = _replace_blob(state, actor)

    return state, tuple(events)


# ---------------------------------------------------------------------------
# round_end_phase
# ---------------------------------------------------------------------------


def _check_objective_control(
    state: BattleState,
    sequence: int = 1,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 5.d sprawdzanie kontroli celów (pkt 8.c.ii).

    Pkt 5.d: cel zostaje zajęty gdy w 3″ od niego znajdują się **tylko** oddziały
    danego gracza (i co najmniej jeden). Pozostaje zajęty między rundami, dopóki
    nie zostanie zajęty przez przeciwnika.

    CR-fix A (post-B3.9.f): emit `ObjectiveControlChanged` per zmiana — replay
    `apply_events(initial, events)` rekonstruuje `state.objectives[*].controller`
    bit-perfect. Pre-fix silent `replace()` zostawiał replayed state z initial
    controllers (None lub deployment values).

    Returns: (new_state, events, next_sequence).
    """
    events: list[BattleEvent] = []
    seq = sequence
    new_objectives: list[Objective] = []
    score = [0, 0]
    for obj in state.objectives:
        players_in_range = set()
        for blob in state.blobs:
            if blob.models_alive == 0:
                continue
            if STATUS_PRZYSZPILONY in blob.status_flags:
                continue  # pkt 22.b.ii: Przyszpilony nie kontroluje celów
            # 3″ od celu — używamy centrum bloba minus radius (proxy: edge w 3″)
            edge_dist = _distance(blob.position, obj.position) - blob.radius_inches
            if edge_dist <= OBJECTIVE_CONTROL_RANGE:
                players_in_range.add(blob.owner_player)
        # Pkt 5.d: zajęty gdy tylko jeden gracz w 3″ + co najmniej 1 oddział
        if len(players_in_range) == 1:
            new_controller = next(iter(players_in_range))
        else:
            # Pkt 5.d: pozostaje zajęty między rundami dopóki nie zostanie zajęty przez przeciwnika
            new_controller = obj.controller
        new_objectives.append(replace(obj, controller=new_controller))
        if new_controller != obj.controller:
            events.append(
                ObjectiveControlChanged(
                    sequence=seq,
                    objective_id=obj.id,
                    previous_controller=obj.controller,
                    new_controller=new_controller,
                )
            )
            seq += 1
        if new_controller == 0:
            score[0] += 1
        elif new_controller == 1:
            score[1] += 1

    new_state = replace(
        state, objectives=tuple(new_objectives), score=(score[0], score[1])
    )
    return new_state, tuple(events), seq


def round_end_phase(
    state: BattleState,
    sequence: int = 1,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 8.c — Koniec rundy:
    i. Zdejmujemy wszystkie znaczniki Aktywowany
    ii. Sprawdzamy kontrolę celów (pkt 5.d)
    iii. Efekty końca rundy (MVP: placeholder)
    iv. Runda kończy się

    Plus: round += 1 (lub `is_game_over = True` gdy round == MAX_ROUND).
    Emit RoundEnded event.
    """
    events: list[BattleEvent] = []
    seq = sequence

    # Pkt 8.c.i: reset Aktywowany — B3.9.d emit StatusRemoved per blob
    # przed mutacją live state.
    for b in state.blobs:
        if STATUS_AKTYWOWANY in b.status_flags:
            events.append(
                StatusRemoved(
                    sequence=seq,
                    target_id=b.id,
                    status=STATUS_AKTYWOWANY,
                )
            )
            seq += 1
    new_blobs = tuple(_remove_status(b, STATUS_AKTYWOWANY) for b in state.blobs)
    # CR-fix G: Ufortyfikowany NIE jest resetowany tutaj — od post-CR-fix-G
    # reset wykonuje się w `activation_phase` na actorze, per pkt 22.c.iv
    # "na początku aktywacji oddziału" (semantycznie poprawnie).
    state = replace(state, blobs=new_blobs)

    # Pkt 8.c.ii: sprawdź kontrolę celów (CR-fix A: emit ObjectiveControlChanged
    # per zmiana kontroli)
    state, obj_events, seq = _check_objective_control(state, sequence=seq)
    events.extend(obj_events)

    # Pkt 5.f: gra kończy się po 4 rundach
    is_over = state.round >= MAX_ROUND

    events.append(
        RoundEnded(
            sequence=seq,
            round_number=state.round,
            objectives_held=state.score,
        )
    )

    state = replace(
        state,
        round=state.round + 1 if not is_over else state.round,
        is_game_over=is_over,
    )
    return state, tuple(events)
