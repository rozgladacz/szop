"""B3.9.d — GATE: replay invariant test (proof-of-completeness ADR-0010).

Inwariant: dla każdej sekwencji akcji wykonanej przez `resolver.apply`,
`apply_events(initial_state, all_events)` rekonstruuje per-blob state
identyczny z `live_state`. Pokrywa fix #6 (silent status mutations bypassing
events) — przed B3.9.d `combat.resolve_charge_attack` mutował `status_flags`
przez `replace()` bez emit eventu, więc replayed state nie miał `Wyczerpany`
po kontrataku.

Scope (B3.9.d MVP):
- Per-blob state: `position`, `models_alive`, `wounds_received`,
  `wounds_pending` (zerowane po alokacji), `wounds_pending_precise`,
  `is_hero_unit`, `status_flags`, `melee_balance`, `quality`, `defense`,
  `toughness_per_model`, `radius_inches`, `owner_player`, `passives`.
- BattleState orchestration (`active_player`, `activations_remaining`) — NIE
  jest event-derived (decyzja resolver-a). Sprawdzane wyłącznie blob-level.
- `state.round` — derived via `RoundEnded` reducer; sprawdzane.
- `state.score` / `is_game_over` — derived via `RoundEnded`.

`initial_for_replay` = state PO `deployment_round` (round=1). Deployment
phase round-transition (0→1) nie jest event-sourced (pkt 13 deployment) —
poza scope B3.9.d.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.combat import WeaponProfile
from app.services.engine.dice import DeterministicDice
from app.services.engine.phases import (
    deployment_round,
    round_end_phase,
    setup_phase,
)
from app.services.engine.resolver import apply
from app.services.engine.state import (
    BattleState,
    Position,
    UnitBlob,
    apply_events,
)


# ---------------------------------------------------------------------------
# Helpers — compare per-blob state (not orchestration)
# ---------------------------------------------------------------------------


_BLOB_REPLAY_FIELDS = (
    "id",
    "owner_player",
    "position",
    "radius_inches",
    "models_alive",
    "toughness_per_model",
    "quality",
    "defense",
    "is_hero_unit",
    "passives",
    "status_flags",
    "wounds_received",
    "wounds_pending",
    "wounds_pending_precise",
    "melee_balance",
    "location",  # R5.a (pkt 27.b): event-derived przez ModelKilled reducer
)


def assert_blobs_match(live: BattleState, replayed: BattleState) -> None:
    """Compare blob-level state between live and replayed BattleState.

    Skipuje orchestration fields (`active_player`, `activations_remaining`,
    `pending_effects`, `pending_interrupts`) bo nie są event-derived w B3.9.d
    scope.
    """
    live_by_id = {b.id: b for b in live.blobs}
    replayed_by_id = {b.id: b for b in replayed.blobs}
    assert set(live_by_id) == set(replayed_by_id), (
        f"Blob id set mismatch: live={set(live_by_id)} replayed={set(replayed_by_id)}"
    )
    for uid in sorted(live_by_id):
        live_b = live_by_id[uid]
        rep_b = replayed_by_id[uid]
        for field_name in _BLOB_REPLAY_FIELDS:
            live_val = getattr(live_b, field_name)
            rep_val = getattr(rep_b, field_name)
            assert live_val == rep_val, (
                f"Blob {uid} field {field_name!r} mismatch: "
                f"live={live_val!r} replayed={rep_val!r}"
            )


def make_unit(uid: int, x: float, y: float, **kwargs) -> dict:
    base = {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
    }
    base.update(kwargs)
    return base


def _setup_and_deploy() -> BattleState:
    """Zwraca state po deployment_round — wszystkie bloby ustawione, round=1."""
    rosters = [
        {"owner_player": 0, "units": [make_unit(1, 0, 0), make_unit(2, 0, 6)]},
        {"owner_player": 1, "units": [make_unit(3, 36, 0), make_unit(4, 36, 6)]},
    ]
    state = setup_phase(rosters, terrain=(), objectives=(), initiative_player=0)
    deployment = [
        DeploymentAction(unit_id=1, position=Position(6, 0)),
        DeploymentAction(unit_id=2, position=Position(6, 6)),
        DeploymentAction(unit_id=3, position=Position(30, 0)),
        DeploymentAction(unit_id=4, position=Position(30, 6)),
    ]
    state, _ = deployment_round(state, deployment)
    return state


# ---------------------------------------------------------------------------
# Simple replay tests — per action type
# ---------------------------------------------------------------------------


def test_replay_single_maneuver():
    initial = _setup_and_deploy()
    live = initial
    all_events: list = []

    action = ManeuverAction(unit_id=1, target_position=Position(12, 0))
    live2, evs = apply(live, action, DeterministicDice(7)).state, apply(
        live, action, DeterministicDice(7)
    ).events
    # Re-run for clean event capture (deterministic)
    result = apply(initial, action, DeterministicDice(7))
    live = result.state
    all_events.extend(result.events)

    replayed = apply_events(initial, all_events)
    assert_blobs_match(live, replayed)


def test_replay_single_defend_emits_status_added():
    """`_apply_defend` po B3.9.d emituje StatusAdded(Ufortyfikowany) —
    replayed state ma Ufortyfikowany dzięki temu eventowi."""
    initial = _setup_and_deploy()
    result = apply(initial, DefendAction(unit_id=1), DeterministicDice(7))
    assert any(type(e).__name__ == "StatusAdded" for e in result.events)
    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)
    blob = next(b for b in replayed.blobs if b.id == 1)
    assert "Ufortyfikowany" in blob.status_flags


def test_replay_single_shoot_with_kills():
    initial = _setup_and_deploy()
    weapon = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=2, ap=0)
    action = ShootAction(unit_id=1, target_id=3, weapon=weapon)
    result = apply(initial, action, DeterministicDice(42))
    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)


def test_replay_charge_with_counter_attack():
    """GATE bug #6: szarża + kontratak → defender otrzymuje Wyczerpany.
    Przed B3.9.d silent mutation: live=Wyczerpany, replayed=NoStatus → MISMATCH.
    Po B3.9.d: StatusAdded emit → replayed ma Wyczerpany. ASSERT MATCH."""
    initial = _setup_and_deploy()
    # Pozycje blisko siebie żeby Szarża zadziałała (move_inches=6, blob radius~1)
    initial = replace(
        initial,
        blobs=tuple(
            replace(b, position=Position(8, 0)) if b.id == 2
            else (replace(b, position=Position(12, 0)) if b.id == 4 else b)
            for b in initial.blobs
        ),
    )
    weapon = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2, ap=0)
    action = ChargeAction(unit_id=2, target_id=4, weapon=weapon)
    result = apply(initial, action, DeterministicDice(42))

    # Sprawdź że event StatusAdded(Wyczerpany) jest w sekwencji
    status_added_events = [e for e in result.events if type(e).__name__ == "StatusAdded"]
    # Defender (4) po kontrataku powinien mieć StatusAdded(Wyczerpany)
    wyczerpany_events = [e for e in status_added_events if e.status == "Wyczerpany"]
    if any(
        b.id == 4 and "Wyczerpany" in b.status_flags
        for b in result.state.blobs
    ):
        assert len(wyczerpany_events) >= 1, (
            "Live defender ma Wyczerpany ale brak StatusAdded eventu — bug #6 nie naprawiony!"
        )

    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)


def test_replay_special_discard_exhausted():
    """SpecialAction discard_exhausted emituje StatusRemoved(Wyczerpany) gdy
    oddział miał ten status."""
    initial = _setup_and_deploy()
    # Pre-stage: blob 1 ma Wyczerpany
    initial = replace(
        initial,
        blobs=tuple(
            replace(b, status_flags=("Wyczerpany",)) if b.id == 1 else b
            for b in initial.blobs
        ),
    )
    action = SpecialAction(unit_id=1, ability_slug="discard_exhausted")
    result = apply(initial, action, DeterministicDice(7))
    assert any(type(e).__name__ == "StatusRemoved" for e in result.events)
    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)
    blob = next(b for b in replayed.blobs if b.id == 1)
    assert "Wyczerpany" not in blob.status_flags


def test_replay_maneuver_into_dangerous_terrain():
    """R5.g finding #1 (2026-06-06): Manewr w Niebezpieczny teren zadaje rany
    (EffectApplied(niebezpieczny)) i pokonuje modele (ModelKilled). Replay musi
    odtworzyć `models_alive` + `wounds_received`: reducer EffectApplied(
    niebezpieczny) pushuje surową pulę ran, następujące ModelKilled ją absorbują.

    Przed fixem rana była CICHĄ mutacją `wounds_received` poza event-sourcingiem
    (EffectApplied no-op reducer) → `apply_events` nie odtwarzał stanu (mismatch),
    a modele nigdy nie ginęły od terenu (brak pętli kill / ModelKilled)."""
    from app.services.engine.events import EffectApplied, ModelKilled
    from app.services.engine.state import TerrainCircle

    rosters = [
        {"owner_player": 0, "units": [make_unit(1, 0, 0, models=6, toughness=1)]},
        {"owner_player": 1, "units": [make_unit(3, 36, 0)]},
    ]
    terrain = (
        TerrainCircle(
            center=Position(12, 0), radius_inches=3.0, features=("Niebezpieczny",)
        ),
    )
    state = setup_phase(rosters, terrain=terrain, objectives=(), initiative_player=0)
    deployment = [
        DeploymentAction(unit_id=1, position=Position(6, 0)),
        DeploymentAction(unit_id=3, position=Position(30, 0)),
    ]
    state, _ = deployment_round(state, deployment)
    initial = state

    action = ManeuverAction(unit_id=1, target_position=Position(11, 0))
    result = apply(initial, action, DeterministicDice(1))

    # Teren faktycznie zadał rany i pokonał modele (finding #1 — kill loop)
    assert any(
        isinstance(e, EffectApplied) and e.slug == "niebezpieczny"
        for e in result.events
    )
    assert any(
        isinstance(e, ModelKilled) and e.unit_id == 1 for e in result.events
    )
    blob1 = next(b for b in result.state.blobs if b.id == 1)
    assert blob1.models_alive < 6  # modele zginęły od terenu

    # GATE: replay rekonstruuje stan bit-perfect mimo self-inflicted ran
    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)


def test_replay_last_model_killed_becomes_wycofany():
    """R5.a (pkt 27.b): gdy ostatni model oddziału zostaje pokonany, oddział
    staje się WYCOFANY. Producer (`combat`) i reducer (`ModelKilled`) muszą
    ustawić `location` identycznie — replay bit-perfect (`location` w
    `_BLOB_REPLAY_FIELDS`).

    Setup: kruchy obrońca (1 model, toughness=1) ostrzelany bronią o wielu
    atakach z seedem, który gwarantuje pokonanie ostatniego modelu."""
    from app.services.engine.state import Lokalizacja

    rosters = [
        {"owner_player": 0, "units": [make_unit(1, 0, 0, models=5, toughness=3)]},
        {
            "owner_player": 1,
            "units": [make_unit(3, 36, 0, models=1, toughness=1, defense=6)],
        },
    ]
    state = setup_phase(rosters, terrain=(), objectives=(), initiative_player=0)
    state, _ = deployment_round(
        state,
        [
            DeploymentAction(unit_id=1, position=Position(6, 0)),
            DeploymentAction(unit_id=3, position=Position(10, 0)),
        ],
    )
    initial = state

    weapon = WeaponProfile(
        slug="cannon", name="Cannon", range_inches=24, attacks=12, ap=3
    )
    action = ShootAction(unit_id=1, target_id=3, weapon=weapon)
    result = apply(initial, action, DeterministicDice(7))

    defender_live = next(b for b in result.state.blobs if b.id == 3)
    assert defender_live.models_alive == 0, "fixture: obrońca powinien zginąć"
    assert defender_live.location is Lokalizacja.WYCOFANY

    # GATE: replay rekonstruuje location (event-derived przez ModelKilled)
    replayed = apply_events(initial, list(result.events))
    assert_blobs_match(result.state, replayed)
    defender_rep = next(b for b in replayed.blobs if b.id == 3)
    assert defender_rep.location is Lokalizacja.WYCOFANY


# ---------------------------------------------------------------------------
# Round-end replay
# ---------------------------------------------------------------------------


def test_replay_round_end_removes_aktywowany():
    """round_end_phase emituje StatusRemoved(Aktywowany) per blob — replay
    odzwierciedla reset."""
    initial = _setup_and_deploy()
    # Pre-stage: 2 bloby z Aktywowany (jakby po aktywacjach w rundzie)
    initial = replace(
        initial,
        blobs=tuple(
            replace(b, status_flags=("Aktywowany",)) if b.id in (1, 3) else b
            for b in initial.blobs
        ),
    )
    state_after, events = round_end_phase(initial, sequence=100)
    # Powinno być min 2 StatusRemoved(Aktywowany) + 1 RoundEnded
    status_removed_count = sum(
        1
        for e in events
        if type(e).__name__ == "StatusRemoved" and e.status == "Aktywowany"
    )
    assert status_removed_count == 2

    replayed = apply_events(initial, list(events))
    assert_blobs_match(state_after, replayed)


# ---------------------------------------------------------------------------
# CR-fix A — ObjectiveControlChanged replay
# ---------------------------------------------------------------------------


def test_replay_objective_control_change():
    """CR-fix A: `round_end_phase` z objective w 3″ od oddziału player 0
    emituje `ObjectiveControlChanged` — replay rekonstruuje `objectives[i].controller`."""
    from app.services.engine.state import Objective
    from app.services.engine.phases import round_end_phase

    initial = _setup_and_deploy()
    # Dodaj objective w pobliżu blob 1 (player 0, position (6,0))
    initial = replace(
        initial,
        objectives=(Objective(id=1, position=Position(6.0, 0.0), controller=None),),
    )
    state_after, events = round_end_phase(initial, sequence=100)
    # Powinien być co najmniej 1 ObjectiveControlChanged
    occ_events = [e for e in events if type(e).__name__ == "ObjectiveControlChanged"]
    assert len(occ_events) >= 1
    assert occ_events[0].new_controller == 0

    replayed = apply_events(initial, list(events))
    live_ctrl = tuple((o.id, o.controller) for o in state_after.objectives)
    rep_ctrl = tuple((o.id, o.controller) for o in replayed.objectives)
    assert live_ctrl == rep_ctrl


# ---------------------------------------------------------------------------
# CR-fix B — InitiativePassed replay
# ---------------------------------------------------------------------------


def test_replay_initiative_passed_after_action():
    """CR-fix B: `resolver.apply` emituje `InitiativePassed` gdy przeciwnik
    ma nieaktywowane oddziały — replay rekonstruuje `state.active_player`."""
    initial = _setup_and_deploy()
    # Initial active_player=0; po aktywacji blob 1 inicjatywa idzie do player 1
    action = ManeuverAction(unit_id=1, target_position=Position(12, 0))
    result = apply(initial, action, DeterministicDice(7))
    # InitiativePassed event emitowany
    ip_events = [e for e in result.events if type(e).__name__ == "InitiativePassed"]
    assert len(ip_events) == 1
    assert ip_events[0].previous_active_player == 0
    assert ip_events[0].new_active_player == 1
    # Replay rekonstruuje active_player
    replayed = apply_events(initial, list(result.events))
    assert replayed.active_player == result.state.active_player == 1


# ---------------------------------------------------------------------------
# CR-fix G — Ufortyfikowany removed at start of own activation
# ---------------------------------------------------------------------------


def test_replay_ufortyfikowany_removed_at_activation_start():
    """CR-fix G (pkt 22.c.iv): oddział z Ufortyfikowany traci status na
    początku własnej aktywacji — emit `StatusRemoved(Ufortyfikowany)`."""
    initial = _setup_and_deploy()
    initial = replace(
        initial,
        blobs=tuple(
            replace(b, status_flags=("Ufortyfikowany",)) if b.id == 1 else b
            for b in initial.blobs
        ),
    )
    action = ManeuverAction(unit_id=1, target_position=Position(12, 0))
    result = apply(initial, action, DeterministicDice(7))
    # Powinien być StatusRemoved(Ufortyfikowany) dla bloba 1
    sr_events = [
        e
        for e in result.events
        if type(e).__name__ == "StatusRemoved" and e.target_id == 1 and e.status == "Ufortyfikowany"
    ]
    assert len(sr_events) == 1
    # Po aktywacji actor nie ma już Ufortyfikowany
    blob1_post = next(b for b in result.state.blobs if b.id == 1)
    assert "Ufortyfikowany" not in blob1_post.status_flags
    # Replay rekonstruuje stan
    replayed = apply_events(initial, list(result.events))
    blob1_rep = next(b for b in replayed.blobs if b.id == 1)
    assert "Ufortyfikowany" not in blob1_rep.status_flags


# ---------------------------------------------------------------------------
# Multi-step replay (GATE — full 2v2 sequence)
# ---------------------------------------------------------------------------


def test_gate_full_multi_action_replay():
    """**GATE**: pełna sekwencja Maneuver → Shoot → Charge → Defend → round_end.
    `apply_events(initial, all_events)` musi rekonstruować live state bit-perfect
    na poziomie blob-state.

    Ten test jest proof-of-completeness ADR-0010 dla B3.9.d scope (bug #6 +
    pełny zestaw reducerów).
    """
    initial = _setup_and_deploy()
    live = initial
    all_events: list = []
    seq = 1

    dice = DeterministicDice(seed=2026)
    weapon_rifle = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1, ap=0)
    weapon_sword = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2, ap=0)

    # Zbliżamy blob 2 do blob 4 żeby Charge był legalny
    live = replace(
        live,
        blobs=tuple(
            replace(b, position=Position(8, 6)) if b.id == 2
            else (replace(b, position=Position(12, 6)) if b.id == 4 else b)
            for b in live.blobs
        ),
    )
    initial = live  # reset initial_for_replay po manualnej korekcie pozycji

    actions = [
        ManeuverAction(unit_id=1, target_position=Position(15, 0)),
        ShootAction(unit_id=3, target_id=1, weapon=weapon_rifle),
        ChargeAction(unit_id=2, target_id=4, weapon=weapon_sword),
        DefendAction(unit_id=4),
    ]

    for action in actions:
        actor = next((b for b in live.blobs if b.id == action.unit_id), None)
        if actor is None or actor.models_alive == 0:
            continue
        # Force active_player żeby pominąć resolver._validate_action ownership check
        live = replace(live, active_player=actor.owner_player)
        result = apply(live, action, dice, sequence=seq)
        live = result.state
        seq = result.next_sequence
        all_events.extend(result.events)

    # Round end
    live, end_events = round_end_phase(live, sequence=seq)
    all_events.extend(end_events)
    seq += len(end_events)

    # REPLAY
    replayed = apply_events(initial, all_events)
    assert_blobs_match(live, replayed)

    # Round + score per RoundEnded reducer
    assert replayed.round == live.round
    assert replayed.score == live.score


# ---------------------------------------------------------------------------
# Reducer registration sanity
# ---------------------------------------------------------------------------


def test_all_event_types_have_reducer():
    """B3.9.d invariant: każdy event type w `_EVENT_REGISTRY` ma reducer."""
    from app.services.engine.events import _EVENT_REGISTRY
    from app.services.engine.state import _EVENT_REDUCERS

    for event_type_name in _EVENT_REGISTRY:
        assert event_type_name in _EVENT_REDUCERS, (
            f"Event type {event_type_name!r} missing reducer — replay invariant "
            f"ADR-0010 broken"
        )
