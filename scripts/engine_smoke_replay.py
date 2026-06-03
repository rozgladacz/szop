"""B3.8 smoke replay — minimal 2v2 battle demonstrujący public API engine.

Uruchom: `python scripts/engine_smoke_replay.py` (lub `python -m scripts.engine_smoke_replay`).

Co robi:
1. Setup: 2 rosters × 2 oddziały (Q4/D5/T3, 5 modeli), terrain pillar w środku,
   1 objective w środku planszy.
2. Deployment round: rozstawia po 2 oddziały każdej strony.
3. 2 rundy z 4 aktywacjami każda (każdy oddział raz):
   - P0 unit 1 — Maneuver
   - P1 unit 3 — Shoot at unit 1
   - P0 unit 2 — Charge unit 3
   - P1 unit 4 — Defend
4. Po każdej rundzie round_end_phase z objective check.
5. Print sumaryczny event log + finalstate.

Demonstracja **inwariantu replay** (ADR-0010): rebuild state z eventów daje
identyczny finalstate co stepwise execution. Smoke parity dla `apply_events`.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.engine.actions import (
    ChargeAction,
    DefendAction,
    DeploymentAction,
    ManeuverAction,
    ShootAction,
)
from app.services.engine.combat import WeaponProfile
from app.services.engine.dice import DeterministicDice
from app.services.engine.los import FEATURE_BLOKUJACY
from app.services.engine.phases import (
    deployment_round,
    round_end_phase,
    setup_phase,
)
from app.services.engine.resolver import apply, is_battle_over, should_end_round
from app.services.engine.state import (
    Objective,
    Position,
    TerrainCircle,
    apply_events,
)


def make_unit(uid: int, x: float, y: float) -> dict:
    return {
        "id": uid,
        "position": (x, y),
        "models": 5,
        "toughness": 3,
        "quality": 4,
        "defense": 5,
        "passives": [],
    }


def main() -> None:
    # === Setup ===
    rosters = [
        {"owner_player": 0, "units": [make_unit(1, 0, 0), make_unit(2, 0, 6)]},
        {"owner_player": 1, "units": [make_unit(3, 36, 0), make_unit(4, 36, 6)]},
    ]
    terrain = [
        TerrainCircle(
            center=Position(18, 3),
            radius_inches=3,
            features=(FEATURE_BLOKUJACY,),
        ),
    ]
    objectives = [Objective(id=1, position=Position(18, 3))]

    state = setup_phase(rosters, terrain=terrain, objectives=objectives, initiative_player=0)
    print(f"Setup: {len(state.blobs)} blobs, {len(state.terrain)} terrain, {len(state.objectives)} objectives")

    # === Deployment ===
    deployment = [
        DeploymentAction(unit_id=1, position=Position(6, 0)),
        DeploymentAction(unit_id=2, position=Position(6, 6)),
        DeploymentAction(unit_id=3, position=Position(30, 0)),
        DeploymentAction(unit_id=4, position=Position(30, 6)),
    ]
    state, events = deployment_round(state, deployment)
    print(f"\nDeployment: {len(events)} events, round = {state.round}")

    # B3.9.d (ADR-0046) — snapshot state PO deployment jako `initial_for_replay`.
    # Round transition 0→1 nie jest event-sourced (deployment scope), więc replay
    # startuje stąd. Eventy deployment też nie są re-applied (Move-Executed
    # reducer wymaga blobu na pozycji startowej — incompatible).
    initial_for_replay = state

    # === Battle ===
    dice = DeterministicDice(seed=2026)
    weapon_rifle = WeaponProfile(slug="rifle", name="Rifle", range_inches=24, attacks=1, ap=0)
    weapon_sword = WeaponProfile(slug="sword", name="Sword", range_inches=0, attacks=2, ap=0)

    # `all_events` od momentu `initial_for_replay` (deployment events excluded).
    all_events: list = []
    seq = len(events) + 1

    while not is_battle_over(state) and state.round <= 2:
        print(f"\n=== ROUND {state.round} ===")
        # Sekwencja akcji w tej rundzie
        actions = [
            (0, ManeuverAction(unit_id=1, target_position=Position(15, 0))),
            (1, ShootAction(unit_id=3, target_id=1, weapon=weapon_rifle)),
            (0, ChargeAction(unit_id=2, target_id=4, weapon=weapon_sword)),
            (1, DefendAction(unit_id=4)),
        ]
        for expected_player, action in actions:
            if should_end_round(state):
                break
            # Sprawdź czy aktor żyje i nie jest Aktywowany
            blob = next((b for b in state.blobs if b.id == action.unit_id), None)
            if blob is None or blob.models_alive == 0:
                continue
            if state.active_player != expected_player:
                # Pomiń jeśli inicjatywa się rozjechała (np. fallback)
                continue
            try:
                result = apply(state, action, dice, sequence=seq)
                state = result.state
                seq = result.next_sequence
                all_events.extend(result.events)
                print(
                    f"  P{expected_player} {type(action).__name__:18s} "
                    f"unit={action.unit_id} -> {len(result.events)} events"
                )
            except Exception as e:
                print(f"  [SKIP] {type(action).__name__} unit={action.unit_id}: {e}")

        state, end_events = round_end_phase(state, sequence=seq)
        seq += len(end_events)
        all_events.extend(end_events)
        print(f"  ROUND END: objectives={state.score}, round -> {state.round}, game_over={state.is_game_over}")

    # === Final state summary ===
    print(f"\n{'='*60}")
    print(f"FINAL STATE")
    print(f"{'='*60}")
    print(f"Total events: {len(all_events)}")
    print(f"Round: {state.round}, game_over: {state.is_game_over}, score: {state.score}")
    for blob in state.blobs:
        print(
            f"  Unit {blob.id} (P{blob.owner_player}): "
            f"models_alive={blob.models_alive}, "
            f"wounds_received={blob.wounds_received}, "
            f"status={blob.status_flags}"
        )

    # Event type distribution
    event_types: dict[str, int] = {}
    for e in all_events:
        event_types[type(e).__name__] = event_types.get(type(e).__name__, 0) + 1
    print(f"\nEvent type distribution:")
    for et, n in sorted(event_types.items(), key=lambda x: -x[1]):
        print(f"  {et:25s} {n}")

    # === Replay invariant GATE (ADR-0010 / ADR-0046) ===
    print(f"\n{'='*60}")
    print(f"REPLAY INVARIANT (ADR-0010 / ADR-0046 proof-of-completeness)")
    print(f"{'='*60}")
    replayed = apply_events(initial_for_replay, all_events)
    mismatches: list[str] = []
    blob_fields = (
        "position",
        "models_alive",
        "wounds_received",
        "wounds_pending",
        "wounds_pending_precise",
        "is_hero_unit",
        "status_flags",
        "melee_balance",
    )
    live_by_id = {b.id: b for b in state.blobs}
    rep_by_id = {b.id: b for b in replayed.blobs}
    for uid in sorted(live_by_id):
        lb = live_by_id[uid]
        rb = rep_by_id.get(uid)
        if rb is None:
            mismatches.append(f"  blob {uid}: missing in replay")
            continue
        for field in blob_fields:
            if getattr(lb, field) != getattr(rb, field):
                mismatches.append(
                    f"  blob {uid}.{field}: live={getattr(lb, field)!r} "
                    f"replayed={getattr(rb, field)!r}"
                )
    # CR-fix A/B: również state-level fields (objectives.controller,
    # active_player) muszą się zgadzać — przed CR-fix-A/B były silent mutacjami.
    live_obj_ctrl = tuple((o.id, o.controller) for o in state.objectives)
    rep_obj_ctrl = tuple((o.id, o.controller) for o in replayed.objectives)
    if live_obj_ctrl != rep_obj_ctrl:
        mismatches.append(
            f"  objectives.controller: live={live_obj_ctrl!r} replayed={rep_obj_ctrl!r}"
        )
    if state.active_player != replayed.active_player:
        mismatches.append(
            f"  active_player: live={state.active_player} replayed={replayed.active_player}"
        )
    if mismatches:
        print("MISMATCH:")
        for m in mismatches:
            print(m)
        raise SystemExit(1)
    print(f"OK — apply_events(initial, {len(all_events)} events) == live_state")
    print(f"     round: live={state.round} replayed={replayed.round}")
    print(f"     score: live={state.score} replayed={replayed.score}")
    print(f"     active_player: live={state.active_player} replayed={replayed.active_player}")
    print(f"     objectives: {live_obj_ctrl}")


if __name__ == "__main__":
    main()
