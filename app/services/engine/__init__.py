"""B3 — Game engine pure functions (ADR-0010 event-sourced, ADR-0011 hardcoded executor).

Pakiet konsumowany przez:
- `app/routers/battles.py` (B4) — endpoint dispatcher do `resolver.apply()`
- `szop_client/local.py` (B5) — in-process battle client
- Strumień D agents (`app/services/agents/`) — boty wybierające akcje

Substrate (B3.0):
- `state` — UnitBlob, BattleState, TerrainCircle/Line, compute_radius_inches, build_initial_state, apply_events, UnsupportedAbilityError
- `events` — 8 event types (MoveExecuted, ShotResolved, ...) + serializer

Modules (B3.1+):
- `dice` — DeterministicDice
- `los` — check_los (3-state)
- `prediction` — expected_damage (analytic, no RNG)
- `combat` — resolve_ranged_attack, resolve_melee_attack
- `effects` — EFFECT_REGISTRY (passive + active abilities)
- `interrupts` — InterruptManager (4 closed points)
- `phases` — setup, deployment, activation, round_end
- `resolver` — top-level `apply(state, action, dice, ruleset, terrain)`
"""
