"""D6.2: one public v1 priority decision, submitted only for owner consent.

This optional leaf loads the existing local bot. It never executes a battle
action, reads a database, approves a proposal, or retries a request.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter

from app.services.agents.factory import make_player
from app.services.agents.registry import ALL_KINDS
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction, ManeuverAction, SpecialAction
from app.services.engine.pathfinding import ManeuverPlanner, is_finite_position
from app.services.engine.state import BattleState, Lokalizacja, effective_move_inches
from app.services.engine.status import (
    STATUS_AKTYWOWANY,
    STATUS_PRZYGOTOWANY,
    STATUS_WYCZERPANY,
)
from szop_client.http import HttpClient, HttpClientError


# === SECTION: Capability boundary -- narrower than the legacy resolver ===
SUPPORTED_KINDS = tuple(kind for kind in ALL_KINDS if kind == "priority")
_SUPPORTED_STATUSES = frozenset(
    {STATUS_AKTYWOWANY, STATUS_PRZYGOTOWANY, STATUS_WYCZERPANY}
)


def _unsupported_state(state: BattleState) -> str | None:
    if state.pending_effects or state.pending_interrupts or state.used_interrupts_this_round:
        return "pending_context"
    # Initial slice has verified empty terrain only, including no hazardous route.
    # It does not infer movement safety from the endpoint (Rozjemca 4.c.v).
    if state.terrain:
        return "terrain_not_supported"
    for blob in state.blobs:
        if blob.passives or blob.ability_overrides or blob.is_hero_unit:
            return "abilities_not_supported"
        if any(
            weapon.weapon_abilities or weapon.attack_quality_override is not None
            for weapon in (*blob.melee_weapons, *blob.ranged_weapons)
        ):
            return "abilities_not_supported"
        # Pinned and unknown states are excluded, including the audited mutex drift.
        if not set(blob.status_flags) <= _SUPPORTED_STATUSES:
            return "status_not_supported"
        if blob.wounds_pending or blob.wounds_pending_precise or blob.damage_balance:
            return "pending_context"
        try:
            finite_radius = math.isfinite(blob.radius_inches)
        except OverflowError:
            finite_radius = False
        if not is_finite_position(blob.position) or not finite_radius or blob.radius_inches <= 0:
            return "geometry_not_supported"
    if any(not is_finite_position(obj.position) for obj in state.objectives):
        return "geometry_not_supported"
    return None


@dataclass(frozen=True, slots=True)
class ProposalAttemptResult:
    """Closed, secret-free outcome. No raw errors, headers, state, or RNG."""

    outcome: str
    code: str
    proposal_id: int | None = None
    expected_sequence: int | None = None
    action_type: str | None = None
    decision_ms: float | None = None
    http_status: int | None = None


def _http_failure(exc: Exception, *, posting: bool) -> ProposalAttemptResult:
    status = exc.status_code if isinstance(exc, HttpClientError) else None
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    codes = {400: "invalid_request", 401: "unauthorized", 403: "forbidden",
             404: "not_found", 409: "stale_sequence", 422: "invalid_action"}
    if status in codes:
        return ProposalAttemptResult(
            "stale" if status == 409 else "rejected", codes[status], http_status=status
        )
    # Even malformed 2xx and disconnect-after-commit are ambiguous after POST.
    # Never copy exception text, response bodies, or chained exception details.
    return ProposalAttemptResult(
        "uncertain" if posting else "unavailable",
        "reconciliation_required" if posting else "read_failed",
        http_status=status,
    )


# === SECTION: One-shot orchestration -- no execution and no automatic retry ===
class BotProposalAttempt:
    """One-shot ledger in one instance; concurrent/repeated run returns its result.

    No server idempotency key exists. A new instance/process is a new attempt:
    callers must reconcile pending proposals before creating one after uncertainty.
    """

    def __init__(
        self, client: HttpClient, *, battle_id: int, perspective: int,
        decision_seed: int, kind: str,
    ) -> None:
        self._client = client
        self._battle_id = battle_id
        self._perspective = perspective
        self._seed = decision_seed
        self._kind = kind
        self._lock = Lock()
        self._result: ProposalAttemptResult | None = None

    def run(self) -> ProposalAttemptResult:
        with self._lock:
            if self._result is None:
                # Consume the attempt even if interrupted. Never issue a second POST.
                self._result = ProposalAttemptResult("uncertain", "reconciliation_required")
                self._result = self._run()
            return self._result

    def _run(self) -> ProposalAttemptResult:
        if (
            type(self._battle_id) is not int or self._battle_id < 1
            or type(self._perspective) is not int or self._perspective not in (0, 1)
            or type(self._seed) is not int
        ):
            return ProposalAttemptResult("rejected", "invalid_arguments")
        if self._kind not in ALL_KINDS:
            return ProposalAttemptResult("unsupported", "unknown_kind")
        if self._kind not in SUPPORTED_KINDS:
            return ProposalAttemptResult("unsupported", "kind_not_supported")
        try:
            metadata = self._client.get_battle_metadata(self._battle_id)
            if metadata.activation_protocol_version != 1:
                return ProposalAttemptResult("unsupported", "protocol_not_supported")
            checkpoint = self._client.get_state_checkpoint(self._battle_id)
        except Exception as exc:
            return _http_failure(exc, posting=False)
        if checkpoint.version != 1:
            return ProposalAttemptResult("unsupported", "protocol_not_supported")
        state = checkpoint.state
        if (
            metadata.battle_id != self._battle_id or checkpoint.battle_id != self._battle_id
            or metadata.latest_sequence != checkpoint.sequence_at
            or metadata.current_round != state.round
        ):
            return ProposalAttemptResult("stale", "snapshot_changed")
        if metadata.status != "active" or state.is_game_over or state.round not in range(1, 5):
            return ProposalAttemptResult("unsupported", "not_combat_round")
        if state.active_player != self._perspective:
            return ProposalAttemptResult("unsupported", "wrong_perspective")
        if state.activation is not None or state.initiative_player is not None:
            return ProposalAttemptResult("unsupported", "protocol_not_supported")
        reason = _unsupported_state(state)
        if reason:
            return ProposalAttemptResult("unsupported", reason)
        try:
            player = make_player(self._kind, self._seed)  # fresh, explicit, registry-checked
            started = perf_counter()
            action = player.choose_action(state, self._perspective)
            elapsed = (perf_counter() - started) * 1000
            if action is None:
                return ProposalAttemptResult("unsupported", "no_candidate", decision_ms=elapsed)
            actor = next((blob for blob in state.blobs if blob.id == action.unit_id), None)
            if (
                actor is None or actor.owner_player != self._perspective
                or actor.models_alive <= 0 or actor.location is not Lokalizacja.FRONT
                or STATUS_AKTYWOWANY in actor.status_flags
            ):
                return ProposalAttemptResult("unsupported", "actor_not_supported", decision_ms=elapsed)
            if type(action) not in (ManeuverAction, DefendAction, SpecialAction):
                return ProposalAttemptResult("unsupported", "action_not_supported", decision_ms=elapsed)
            if isinstance(action, SpecialAction) and (
                action.ability_slug != "discard_exhausted" or action.payload
                or STATUS_WYCZERPANY not in actor.status_flags
            ):
                return ProposalAttemptResult("unsupported", "action_not_supported", decision_ms=elapsed)
            if isinstance(action, ManeuverAction) and not ManeuverPlanner(
                state, actor, effective_move_inches(actor)
            ).can_reach(action.target_position):
                return ProposalAttemptResult("unsupported", "route_not_supported", decision_ms=elapsed)
            wire = action_to_json(action)
        except Exception:
            return ProposalAttemptResult("unsupported", "decision_failed")
        try:
            proposal = self._client.propose_battle_action(
                self._battle_id, expected_sequence=checkpoint.sequence_at, action=wire,
                summary=f"D6.2 priority seed={self._seed}: {wire['action_type']}; owner consent required",
            )
        except Exception as exc:
            return _http_failure(exc, posting=True)
        return ProposalAttemptResult(
            "pending", "owner_approval_required", proposal_id=proposal.proposal_id,
            expected_sequence=checkpoint.sequence_at, action_type=wire["action_type"], decision_ms=elapsed,
        )


# === SECTION: Explicit CLI -- token from environment, one attempt, safe JSON ===
def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import os
    from urllib.parse import urlsplit

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--battle-id", required=True, type=int)
    parser.add_argument("--perspective", required=True, type=int, choices=(0, 1))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--kind", default="priority")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    parsed = urlsplit(args.url)
    if (
        parsed.scheme not in ("http", "https") or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or not math.isfinite(args.timeout) or args.timeout <= 0
    ):
        parser.error("expected an HTTP(S) base URL without credentials/query and a positive finite timeout")
    token = os.environ.get("SZOP_AGENT_TOKEN", "").strip()
    if not token:
        parser.error("SZOP_AGENT_TOKEN is required (battle:read + agent_proposals:create)")
    result = BotProposalAttempt(
        HttpClient(args.url, token=token, timeout=args.timeout), battle_id=args.battle_id,
        perspective=args.perspective, decision_seed=args.seed, kind=args.kind,
    ).run()
    print(json.dumps(asdict(result), allow_nan=False))
    return 0 if result.outcome == "pending" else 3 if result.outcome == "uncertain" else 2


if __name__ == "__main__":
    raise SystemExit(main())
