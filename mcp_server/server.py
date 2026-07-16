"""Consent-gated MCP facade over the public SZOP HTTP API."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_server.config import McpConfig
from szop_client import (
    HttpClient,
    HttpClientError,
    battle_events_to_wire,
    battle_state_checkpoint_to_wire,
    ensure_json_safe,
)

MAX_SIMULATION_GAMES = 50
TOOL_NAME = "simulate_engagement"
TOOL_NAMES = (
    TOOL_NAME,
    "get_battle_metadata",
    "get_battle_state",
    "get_battle_events",
    "propose_battle_action",
)

_AUTHORIZATION_RE = re.compile(
    r"\bauthorization\b\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE)
_ResultT = TypeVar("_ResultT")

RosterId = Annotated[int, Field(strict=True, ge=1)]
BattleId = Annotated[int, Field(strict=True, ge=1)]
Since = Annotated[int, Field(strict=True, ge=0)]
ExpectedSequence = Annotated[int, Field(strict=True, ge=0)]
GameCount = Annotated[
    int,
    Field(strict=True, ge=1, le=MAX_SIMULATION_GAMES),
]
Seed = Annotated[int, Field(strict=True)]
NonEmptyName = Annotated[str, Field(min_length=1)]
ProposalSummary = Annotated[str, Field(min_length=1, max_length=500)]


def _redact_error_message(message: str, bearer_token: str | None) -> str:
    redacted = message.replace(bearer_token, "[REDACTED]") if bearer_token else message
    redacted = _AUTHORIZATION_RE.sub("Authorization: [REDACTED]", redacted)
    return _BEARER_RE.sub("Bearer [REDACTED]", redacted)


def _run_safely(
    operation: Callable[[], _ResultT],
    *,
    bearer_token: str | None,
) -> _ResultT:
    """Preserve useful client errors while redacting authorization secrets."""
    try:
        return operation()
    except HttpClientError as exc:
        raise HttpClientError(
            _redact_error_message(str(exc), bearer_token),
            status_code=exc.status_code,
        ) from None
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        raise RuntimeError(_redact_error_message(message, bearer_token)) from None


def _require_expected_battle_id(actual: Any, expected: int) -> None:
    if type(actual) is not int or actual != expected:
        raise ValueError("client returned a mismatched battle_id")


def create_server(
    config: McpConfig | None = None,
    *,
    client: HttpClient | None = None,
) -> FastMCP:
    """Build the MCP server with the shipped observation and proposal tools."""
    settings = config or McpConfig.from_env()
    http_client = (
        client
        if client is not None
        else HttpClient(
            settings.api_url,
            token=settings.bearer_token,
        )
    )
    server = FastMCP(
        "SZOP",
        instructions=(
            "Battle observation plus consent-gated action proposals backed by "
            "the public SZOP HTTP API."
        ),
    )

    @server.tool(name=TOOL_NAME)
    def simulate_engagement(
        roster_a: RosterId,
        roster_b: RosterId,
        games: GameCount = 10,
        bot: NonEmptyName = "priority",
        seed: Seed = 0,
        map_name: NonEmptyName = "lustrzana_a",
    ) -> dict[str, int | float]:
        """Simulate two owned roster IDs without persisting a battle."""
        def operation() -> dict[str, int | float]:
            summary = http_client.simulate_roster_ids(
                p1_roster_id=roster_a,
                p2_roster_id=roster_b,
                n=games,
                bot=bot,
                seed=seed,
                map_name=map_name,
            )
            return ensure_json_safe(
                {
                    "n_games": summary.n_games,
                    "wins_p0": summary.wins_p0,
                    "wins_p1": summary.wins_p1,
                    "draws": summary.draws,
                    "total_rounds": summary.total_rounds,
                    "win_rate_p0": summary.win_rate_p0,
                    "win_rate_p1": summary.win_rate_p1,
                    "draw_rate": summary.draw_rate,
                    "avg_rounds": summary.avg_rounds,
                }
            )

        return _run_safely(operation, bearer_token=settings.bearer_token)

    @server.tool(name="get_battle_metadata")
    def get_battle_metadata(battle_id: BattleId) -> dict[str, Any]:
        """Read participant-scoped battle metadata via the public API."""
        def operation() -> dict[str, Any]:
            metadata = http_client.get_battle_metadata(battle_id)
            _require_expected_battle_id(metadata.battle_id, battle_id)
            return ensure_json_safe(
                {
                    "battle_id": metadata.battle_id,
                    "p1_user_id": metadata.p1_user_id,
                    "p2_user_id": metadata.p2_user_id,
                    "p1_roster_id": metadata.p1_roster_id,
                    "p2_roster_id": metadata.p2_roster_id,
                    "winner_user_id": metadata.winner_user_id,
                    "current_round": metadata.current_round,
                    "rng_seed": metadata.rng_seed,
                    "status": metadata.status,
                    "latest_sequence": metadata.latest_sequence,
                }
            )

        return _run_safely(operation, bearer_token=settings.bearer_token)

    @server.tool(name="get_battle_state")
    def get_battle_state(battle_id: BattleId) -> dict[str, Any]:
        """Read one coherent versioned battle-state checkpoint without RNG."""
        def operation() -> dict[str, Any]:
            checkpoint = http_client.get_state_checkpoint(battle_id)
            _require_expected_battle_id(checkpoint.battle_id, battle_id)
            return battle_state_checkpoint_to_wire(checkpoint)

        return _run_safely(operation, bearer_token=settings.bearer_token)

    @server.tool(name="get_battle_events")
    def get_battle_events(
        battle_id: BattleId,
        since: Since = 0,
    ) -> dict[str, Any]:
        """Read the ordered event delta whose sequence is greater than ``since``."""
        def operation() -> dict[str, Any]:
            events = http_client.get_events(battle_id, since=since)
            projected, last_sequence = battle_events_to_wire(events, since=since)
            return {
                "battle_id": battle_id,
                "since": since,
                "events": projected,
                "last_sequence": last_sequence,
            }

        return _run_safely(operation, bearer_token=settings.bearer_token)

    @server.tool(name="propose_battle_action")
    def propose_battle_action(
        battle_id: BattleId,
        expected_sequence: ExpectedSequence,
        action: dict[str, Any],
        summary: ProposalSummary,
    ) -> dict[str, Any]:
        """Request owner consent for one frozen ``szop.action/v1`` action."""
        def operation() -> dict[str, Any]:
            proposal = http_client.propose_battle_action(
                battle_id,
                expected_sequence=expected_sequence,
                action=action,
                summary=summary,
            )
            _require_expected_battle_id(proposal.battle_id, battle_id)
            if proposal.expected_sequence != expected_sequence:
                raise ValueError("client returned a mismatched expected_sequence")
            return ensure_json_safe(
                {
                    "proposal_id": proposal.proposal_id,
                    "owner_user_id": proposal.owner_user_id,
                    "agent_user_id": proposal.agent_user_id,
                    "token_id": proposal.token_id,
                    "battle_id": proposal.battle_id,
                    "expected_sequence": proposal.expected_sequence,
                    "action": proposal.action,
                    "summary": proposal.summary,
                    "status": proposal.status,
                }
            )

        return _run_safely(operation, bearer_token=settings.bearer_token)

    return server


mcp = create_server()


def main() -> None:
    """Run the local server over MCP stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
