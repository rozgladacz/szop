"""B3 — Game engine pure functions (ADR-0010 event-sourced, ADR-0011 hardcoded executor).

Pakiet konsumowany przez:
- `app/routers/battles.py` (B4) — endpoint dispatcher do `resolver.apply()`
- `szop_client/local.py` (B5) — in-process battle client
- Strumień D agents (`app/services/agents/`) — boty wybierające akcje

Substrate (B3.0 + B3.9):
- `state` — UnitBlob, BattleState, TerrainCircle/Line, compute_radius_inches, build_initial_state, apply_events, UnsupportedAbilityError, initial_toughness_for (B3.9.c)
- `events` — 10 event types (MoveExecuted, ShotResolved, ..., StatusAdded/Removed B3.9.d) + serializer
- `status` (B3.9.a) — StatusFlag enum + idempotentne helpery
- `geometry` (B3.9.b) — pure prymityki (distance, point_in_circle, circle_edge_distance, ...)
- `reducers` (B3.9.d) — `@register_reducer` dla wszystkich 10 event types; importowany tu dla side-effect rejestracji

Modules (B3.1+):
- `dice` — DeterministicDice
- `los` — check_los (3-state)
- `prediction` — expected_damage (analytic, no RNG)
- `combat` — resolve_ranged_attack, resolve_melee_attack
- `effects` — EFFECT_REGISTRY (passive + active abilities)
- `interrupts` — InterruptManager (4 closed points)
- `phases` — setup, deployment, activation, round_end + ActivationContext (B3.9.c)
- `resolver` — top-level `apply(state, action, dice, ruleset, terrain)`
"""

# Side-effect import — rejestruje reducers w `_EVENT_REDUCERS` dispatcher per
# ADR-0046. Musi być importowane przed `apply_events` w jakimkolwiek call site.
from app.services.engine import reducers as _reducers  # noqa: F401
