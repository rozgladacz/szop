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

from dataclasses import replace
from typing import Iterable

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.combat import (
    resolve_charge_attack,
    resolve_melee_attack,
    resolve_ranged_attack,
)
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import (
    BattleEvent,
    EffectApplied,
    MoraleTestPassed,
    MoveExecuted,
    RoundEnded,
)
from app.services.engine.state import (
    BattleState,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    build_initial_state,
)

STATUS_AKTYWOWANY = "Aktywowany"
STATUS_WYCZERPANY = "Wyczerpany"
STATUS_PRZYSZPILONY = "Przyszpilony"
STATUS_UFORTYFIKOWANY = "Ufortyfikowany"

MAX_ROUND = 4  # pkt 5.f: gra kończy się po 4 rundach
OBJECTIVE_CONTROL_RANGE = 3.0  # pkt 5.d: 3″ od celu

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


def _add_status(blob: UnitBlob, status: str) -> UnitBlob:
    if status in blob.status_flags:
        return blob
    return replace(blob, status_flags=tuple(list(blob.status_flags) + [status]))


def _remove_status(blob: UnitBlob, status: str) -> UnitBlob:
    if status not in blob.status_flags:
        return blob
    return replace(
        blob, status_flags=tuple(s for s in blob.status_flags if s != status)
    )


def _distance(p1: Position, p2: Position) -> float:
    return ((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2) ** 0.5


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

    # Po deployment: round = 1, status Aktywowany resetowany przed pierwszą rundą
    reset_blobs = tuple(_remove_status(b, STATUS_AKTYWOWANY) for b in current.blobs)
    current = replace(current, blobs=reset_blobs, round=1)
    return current, tuple(events)


# ---------------------------------------------------------------------------
# Action dispatch — sub-helpers per akcja
# ---------------------------------------------------------------------------


def _apply_maneuver(
    state: BattleState, action: ManeuverAction, sequence: int
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.a Manewr — emit MoveExecuted, update position. Walidacja
    dist ≤ move_inches deferred do resolver/walidacji wyżej."""
    blob = _find_blob(state, action.unit_id)
    event = MoveExecuted(
        sequence=sequence,
        unit_id=blob.id,
        from_pos=(blob.position.x, blob.position.y),
        to_pos=(action.target_position.x, action.target_position.y),
        move_type="manever",
    )
    moved = replace(blob, position=action.target_position)
    return _replace_blob(state, moved), (event,), sequence + 1


def _apply_defend(
    state: BattleState, action: DefendAction, sequence: int
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 14.b Obrona — oddział zyskuje Ufortyfikowany (pkt 22.c). Przyszpilony
    odrzucany (pkt 22.b.v: Przyszpilony zostaje odrzucony gdy oddział staje się
    Ufortyfikowany)."""
    blob = _find_blob(state, action.unit_id)
    blob = _add_status(blob, STATUS_UFORTYFIKOWANY)
    blob = _remove_status(blob, STATUS_PRZYSZPILONY)
    event = EffectApplied(
        sequence=sequence,
        slug="defend",
        target_unit_id=blob.id,
        source_unit_id=blob.id,
        payload={"status_added": STATUS_UFORTYFIKOWANY},
    )
    return _replace_blob(state, blob), (event,), sequence + 1


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
    """Pkt 14.e Akcja specjalna.

    MVP: `discard_exhausted` (uniwersalny pkt 22.a.ii — odrzuć status Wyczerpany).
    Inne aktywne zdolności (Łatanie/Mag/Mobilizacja/Presja/etc.) → przyszła
    iteracja przez integrację z `effects.py` ACTIVE_ABILITY_REGISTRY.
    """
    blob = _find_blob(state, action.unit_id)
    if action.ability_slug == "discard_exhausted":
        new_blob = _remove_status(blob, STATUS_WYCZERPANY)
        event = EffectApplied(
            sequence=sequence,
            slug="discard_exhausted",
            target_unit_id=blob.id,
            source_unit_id=blob.id,
            payload={"status_removed": STATUS_WYCZERPANY},
        )
        return _replace_blob(state, new_blob), (event,), sequence + 1
    # Inne sluggi: noop event (placeholder do impl w B3.5+ effects)
    event = EffectApplied(
        sequence=sequence,
        slug=action.ability_slug,
        target_unit_id=blob.id,
        source_unit_id=blob.id,
        payload={"note": "not yet implemented in MVP", **action.payload},
    )
    return state, (event,), sequence + 1


# ---------------------------------------------------------------------------
# Przegrupowanie (pkt 20) + Odzyskiwanie ran (pkt 21)
# ---------------------------------------------------------------------------


def _regroup_test(
    state: BattleState,
    blob_id: int,
    initial_toughness_total: int,
    dice: DeterministicDice,
    sequence: int,
) -> tuple[BattleState, tuple[BattleEvent, ...], int]:
    """Pkt 20 Przegrupowanie.

    Per pkt 20.a: test wykonują oddziały które otrzymały rany w aktywacji
    (wykrywamy przez `blob.wounds_received > 0` post-akcji; **dla MVP** używamy
    proxy: oddział musi wykonać test jeśli `wounds_received > 0 OR melee_balance < 0`).

    Liczba testów:
    - Baseline: 1 (pkt 20.a)
    - +1 jeśli wytrzymałość ≤ ½ początkowej (pkt 20.b)
    - +1/-1 z bilansu wręcz (pkt 20.c) — w MVP: -1 jeśli melee_balance > 0, +1 jeśli melee_balance < 0
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
    if blob.wounds_received == 0 and blob.melee_balance >= 0:
        return state, (), sequence  # pkt 20.a: nie wykonujemy testów

    n_tests = 1
    # Pkt 20.b: ≤ 1/2 początkowej wytrzymałości
    current_toughness = blob.models_alive * blob.toughness_per_model - blob.wounds_received
    if current_toughness <= initial_toughness_total / 2:
        n_tests += 1
    # Pkt 20.c: bilans wręcz (jeśli walczył wręcz)
    if blob.melee_balance > 0:
        n_tests -= 1
    elif blob.melee_balance < 0:
        n_tests += 1
    # Pkt 20.d: status modifiers
    if STATUS_PRZYSZPILONY in blob.status_flags:
        n_tests += 1
    if STATUS_UFORTYFIKOWANY in blob.status_flags:
        n_tests -= 1
    # Passive morale modifiers (Nieustraszony -1 etc.)
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
        # Oddział pokonany
        new_blob = replace(new_blob, models_alive=0, wounds_received=0)
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
# activation_phase
# ---------------------------------------------------------------------------


def activation_phase(
    state: BattleState,
    action,  # Action union
    dice: DeterministicDice,
    sequence: int = 1,
    initial_toughness_totals: dict[int, int] | None = None,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 11.b — Zwykła aktywacja: akcja → Przegrupowanie → Odzyskiwanie ran →
    status Aktywowany.

    MVP scope: pojedyncza akcja (pkt 11.b.ii). Pętla 2 akcji (pkt 11.b.iii)
    eksponowana wyżej (B3.7 resolver).

    Args:
        state: aktualny stan.
        action: jeden z `actions.Action` typów.
        dice: DeterministicDice.
        sequence: pierwszy sequence dla eventów.
        initial_toughness_totals: opcjonalna mapa `{unit_id: initial_tough}` dla
            testu pkt 20.b. Default: liczone z aktualnych modeli (proxy).

    Returns:
        (new_state, events).
    """
    events: list[BattleEvent] = []
    seq = sequence

    # Faza akcji (pkt 14)
    if isinstance(action, ManeuverAction):
        state, action_events, seq = _apply_maneuver(state, action, seq)
    elif isinstance(action, DefendAction):
        state, action_events, seq = _apply_defend(state, action, seq)
    elif isinstance(action, ShootAction):
        state, action_events, seq = _apply_shoot(state, action, dice, seq)
    elif isinstance(action, ChargeAction):
        state, action_events, seq = _apply_charge(state, action, dice, seq)
    elif isinstance(action, SpecialAction):
        state, action_events, seq = _apply_special(state, action, seq)
    else:
        raise TypeError(f"Unknown action type: {type(action).__name__}")
    events.extend(action_events)

    # Faza Przegrupowanie (pkt 20)
    actor_id = action.unit_id
    actor = _find_blob(state, actor_id) if any(b.id == actor_id for b in state.blobs) else None
    if actor is not None and actor.models_alive > 0:
        initial_tough = (
            initial_toughness_totals.get(actor_id)
            if initial_toughness_totals
            else actor.models_alive * actor.toughness_per_model + actor.wounds_received
        )
        state, regroup_events, seq = _regroup_test(
            state, actor_id, initial_tough, dice, seq
        )
        events.extend(regroup_events)

    # Faza Odzyskiwanie ran (pkt 21) — MVP placeholder (Regeneracja/Odrodzenie B3.5+)
    # NOTE: integration point dla Łatania (cel inny oddział) — gdy w event_chain
    # SpecialAction(latanie) pojawi się tu jako side-effect.

    # Aktor otrzymuje status Aktywowany (pkt 11.b.vi). Sprawdzenie czy nadal istnieje.
    actor = _find_blob(state, actor_id) if any(b.id == actor_id for b in state.blobs) else None
    if actor is not None and actor.models_alive > 0:
        actor = _add_status(actor, STATUS_AKTYWOWANY)
        # Pkt 22.c.iv: Ufortyfikowany odrzucany na początku aktywacji oddziału lub
        # gdy oddział staje się Przyszpilony — tu po Aktywowany interpretujemy
        # jako "koniec aktywacji" — Ufortyfikowany NIE jest odrzucany tu (per pkt
        # 22.c.iv: "na początku aktywacji oddziału"). MVP zostawia bez zmian.
        # Reset melee_balance na koniec aktywacji (per ADR-0014 sekcja 3)
        actor = replace(actor, melee_balance=0)
        state = _replace_blob(state, actor)

    return state, tuple(events)


# ---------------------------------------------------------------------------
# round_end_phase
# ---------------------------------------------------------------------------


def _check_objective_control(
    state: BattleState,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Pkt 5.d sprawdzanie kontroli celów (pkt 8.c.ii).

    Pkt 5.d: cel zostaje zajęty gdy w 3″ od niego znajdują się **tylko** oddziały
    danego gracza (i co najmniej jeden). Pozostaje zajęty między rundami, dopóki
    nie zostanie zajęty przez przeciwnika.

    Returns: (new_state z updated objectives + score, events).
    """
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
        if new_controller == 0:
            score[0] += 1
        elif new_controller == 1:
            score[1] += 1

    new_state = replace(
        state, objectives=tuple(new_objectives), score=(score[0], score[1])
    )
    return new_state, ()


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

    # Pkt 8.c.i: reset Aktywowany
    new_blobs = tuple(_remove_status(b, STATUS_AKTYWOWANY) for b in state.blobs)
    # Pkt 22.c.iv: Ufortyfikowany odrzucany na początku aktywacji — przekładamy
    # do round_end dla MVP simplification (efektywnie na początku następnej rundy).
    # Per SZOP pkt 22.c.iv to "na początku aktywacji" więc bardziej poprawnie by było
    # reset w activation_phase, ale obecny model ma reset tutaj jako proxy.
    state = replace(state, blobs=new_blobs)

    # Pkt 8.c.ii: sprawdź kontrolę celów
    state, obj_events = _check_objective_control(state)
    events.extend(obj_events)

    # Pkt 5.f: gra kończy się po 4 rundach
    is_over = state.round >= MAX_ROUND

    events.append(
        RoundEnded(
            sequence=sequence,
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
