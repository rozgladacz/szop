"""Consent-gated MCP facade over the public SZOP HTTP API."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from mcp.server.fastmcp import FastMCP
from pydantic import Field, WithJsonSchema

from mcp_server.config import McpConfig
from szop_client import (
    HttpClient,
    HttpClientError,
    MAX_EXPLOIT_GAMES_PER_PAIR,
    MAX_EXPLOIT_ROSTERS,
    MAX_EXPLOIT_TOTAL_GAMES,
    MAX_ABILITY_QUERY_LENGTH,
    MAX_RULE_QUERY_LENGTH,
    MAX_RULE_RESULTS,
    MAX_SCORE_GAMES_PER_OPPONENT,
    MAX_SCORE_OPPONENTS,
    MAX_SCORE_SEED,
    MAX_SCORE_TOTAL_GAMES,
    MIN_EXPLOIT_ROSTERS,
    MIN_SCORE_SEED,
    SCORE_LIST_BOTS,
    SCORE_LIST_MAPS,
    battle_events_to_wire,
    battle_state_checkpoint_to_wire,
    ensure_json_safe,
)

MAX_SIMULATION_GAMES = 50
TOOL_NAME = "simulate_engagement"
TOOL_NAMES = (
    TOOL_NAME,
    "lookup_rule",
    "search_rules",
    "explain_ability",
    "validate_loadout",
    "score_list",
    "find_exploit_candidates",
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
UnitId = Annotated[int, Field(strict=True, ge=1)]
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
RuleQuery = Annotated[str, Field(min_length=1, max_length=MAX_RULE_QUERY_LENGTH)]
RuleLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_RULE_RESULTS)]
LoadoutCount = Annotated[int, Field(strict=True, ge=1, le=100)]
ScoreRosterIdInput = Annotated[
    Any,
    WithJsonSchema({"type": "integer", "minimum": 1}),
]
ScoreGameCountInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_SCORE_GAMES_PER_OPPONENT,
        }
    ),
]
ScoreBotInput = Annotated[
    Any,
    WithJsonSchema({"type": "string", "minLength": 1}),
]
ScoreSeedInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "type": "integer",
            "minimum": MIN_SCORE_SEED,
            "maximum": MAX_SCORE_SEED,
        }
    ),
]
ScoreMapInput = Annotated[
    Any,
    WithJsonSchema({"type": "string", "minLength": 1}),
]
ScoreOpponentIdsInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "anyOf": [
                {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": MAX_SCORE_OPPONENTS,
                },
                {"type": "null"},
            ]
        }
    ),
]
ExploitArmyIdInput = Annotated[
    Any,
    WithJsonSchema({"type": "integer", "minimum": 1}),
]
ExploitGameCountInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_EXPLOIT_GAMES_PER_PAIR,
        }
    ),
]
ExploitRosterIdsInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "anyOf": [
                {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": MIN_EXPLOIT_ROSTERS,
                    "maxItems": MAX_EXPLOIT_ROSTERS,
                },
                {"type": "null"},
            ]
        }
    ),
]
AbilityQuery = Annotated[
    str,
    Field(min_length=1, max_length=MAX_ABILITY_QUERY_LENGTH),
]


def _redact_error_message(message: str, bearer_token: str | None) -> str:
    redacted = message.replace(bearer_token, "[REDACTED]") if bearer_token else message
    redacted = _AUTHORIZATION_RE.sub("Authorization: [REDACTED]", redacted)
    return _BEARER_RE.sub("Bearer [REDACTED]", redacted)


def _run_safely(
    operation: Callable[[], _ResultT],
    *,
    bearer_token: str | None,
    safe_error_label: str | None = None,
) -> _ResultT:
    """Preserve useful client errors while redacting authorization secrets."""
    try:
        return operation()
    except HttpClientError as exc:
        message = str(exc)
        if safe_error_label is not None:
            message = safe_error_label
            if exc.status_code is not None:
                message += f" with HTTP {exc.status_code}"
        raise HttpClientError(
            _redact_error_message(message, bearer_token),
            status_code=exc.status_code,
        ) from None
    except Exception as exc:
        message = safe_error_label or str(exc) or type(exc).__name__
        raise RuntimeError(_redact_error_message(message, bearer_token)) from None


def _require_expected_battle_id(actual: Any, expected: int) -> None:
    if type(actual) is not int or actual != expected:
        raise ValueError("client returned a mismatched battle_id")


def create_server(
    config: McpConfig | None = None,
    *,
    client: HttpClient | None = None,
) -> FastMCP:
    """Build the MCP server with the shipped knowledge, battle, and proposal tools."""
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
            "Canonical exact and semantic rule lookup, ability and loadout "
            "validation, battle observation, and consent-gated action proposals "
            "backed by the public SZOP HTTP API."
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

    @server.tool(name="lookup_rule")
    def lookup_rule(
        query: RuleQuery,
        limit: RuleLimit = 5,
    ) -> dict[str, Any]:
        """Find an exact ``pkt X`` or exact/folded canonical rule text."""
        return _run_safely(
            lambda: ensure_json_safe(
                http_client.lookup_rule(query, limit=limit)
            ),
            bearer_token=settings.bearer_token,
        )

    @server.tool(name="search_rules")
    def search_rules(
        query: RuleQuery,
        limit: RuleLimit = 5,
    ) -> dict[str, Any]:
        """Find semantic/paraphrased rules; use lookup_rule for exact text."""
        return _run_safely(
            lambda: ensure_json_safe(
                http_client.search_rules(query, limit=limit)
            ),
            bearer_token=settings.bearer_token,
            safe_error_label="POST rules search failed",
        )

    @server.tool(name="explain_ability")
    def explain_ability(query: AbilityQuery) -> dict[str, Any]:
        """Explain one canonical ability by slug or normalized Polish name."""
        return _run_safely(
            lambda: ensure_json_safe(http_client.explain_ability(query)),
            bearer_token=settings.bearer_token,
        )

    @server.tool(name="validate_loadout")
    def validate_loadout(
        unit_id: UnitId,
        loadout: dict[str, Any],
        count: LoadoutCount = 1,
    ) -> dict[str, Any]:
        """Validate and quote a unit loadout without persisting it."""
        return _run_safely(
            lambda: ensure_json_safe(
                http_client.validate_loadout(unit_id, loadout, count=count)
            ),
            bearer_token=settings.bearer_token,
            safe_error_label="POST loadout validation failed",
        )

    @server.tool(name="score_list")
    def score_list(
        roster_id: ScoreRosterIdInput,
        games_per_opponent: ScoreGameCountInput = 3,
        bot: ScoreBotInput = "priority",
        seed: ScoreSeedInput = 0,
        map_name: ScoreMapInput = "lustrzana_a",
        opponent_roster_ids: ScoreOpponentIdsInput = None,
    ) -> dict[str, Any]:
        """Score one owned roster against an owned, explicitly bounded field."""
        def operation() -> dict[str, Any]:
            if (
                type(roster_id) is not int
                or roster_id < 1
                or type(games_per_opponent) is not int
                or not 1
                <= games_per_opponent
                <= MAX_SCORE_GAMES_PER_OPPONENT
                or not isinstance(bot, str)
                or not bot
                or not isinstance(map_name, str)
                or not map_name
                or type(seed) is not int
                or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED
            ):
                raise ValueError("invalid score_list request")

            normalized_bot = bot.lower()
            normalized_map = map_name.lower()
            if (
                normalized_bot not in SCORE_LIST_BOTS
                or normalized_map not in SCORE_LIST_MAPS
            ):
                raise ValueError("invalid score_list request")

            normalized_opponents: list[int] | None = None
            if opponent_roster_ids is not None:
                if (
                    type(opponent_roster_ids) is not list
                    or len(opponent_roster_ids) > MAX_SCORE_OPPONENTS
                    or any(
                        type(item) is not int or item < 1
                        for item in opponent_roster_ids
                    )
                    or len(set(opponent_roster_ids)) != len(opponent_roster_ids)
                    or roster_id in opponent_roster_ids
                    or games_per_opponent * len(opponent_roster_ids)
                    > MAX_SCORE_TOTAL_GAMES
                ):
                    raise ValueError("invalid score_list request")
                normalized_opponents = sorted(opponent_roster_ids)

            return ensure_json_safe(
                http_client.score_list(
                    roster_id,
                    games_per_opponent=games_per_opponent,
                    bot=normalized_bot,
                    seed=seed,
                    map_name=normalized_map,
                    opponent_roster_ids=normalized_opponents,
                )
            )

        return _run_safely(
            operation,
            bearer_token=settings.bearer_token,
            safe_error_label="POST roster score failed",
        )

    @server.tool(name="find_exploit_candidates")
    def find_exploit_candidates(
        army_id: ExploitArmyIdInput,
        games_per_pair: ExploitGameCountInput = 2,
        bot: ScoreBotInput = "priority",
        seed: ScoreSeedInput = 0,
        map_name: ScoreMapInput = "lustrzana_a",
        roster_ids: ExploitRosterIdsInput = None,
    ) -> dict[str, Any]:
        """Rank a bounded field of existing owner rosters for manual review."""
        def operation() -> dict[str, Any]:
            if (
                type(army_id) is not int
                or not 1 <= army_id <= 2**63 - 1
                or type(games_per_pair) is not int
                or not 1 <= games_per_pair <= MAX_EXPLOIT_GAMES_PER_PAIR
                or not isinstance(bot, str)
                or not bot
                or not isinstance(map_name, str)
                or not map_name
                or type(seed) is not int
                or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED
            ):
                raise ValueError("invalid exploit candidate request")

            normalized_bot = bot.lower()
            normalized_map = map_name.lower()
            if (
                normalized_bot not in SCORE_LIST_BOTS
                or normalized_map not in SCORE_LIST_MAPS
            ):
                raise ValueError("invalid exploit candidate request")

            normalized_rosters: list[int] | None = None
            if roster_ids is not None:
                if type(roster_ids) is not list:
                    raise ValueError("invalid exploit candidate request")
                pair_count = len(roster_ids) * (len(roster_ids) - 1) // 2
                if (
                    not MIN_EXPLOIT_ROSTERS <= len(roster_ids) <= MAX_EXPLOIT_ROSTERS
                    or any(
                        type(item) is not int or not 1 <= item <= 2**63 - 1
                        for item in roster_ids
                    )
                    or len(set(roster_ids)) != len(roster_ids)
                    or pair_count * games_per_pair > MAX_EXPLOIT_TOTAL_GAMES
                ):
                    raise ValueError("invalid exploit candidate request")
                normalized_rosters = sorted(roster_ids)

            return ensure_json_safe(
                http_client.find_exploit_candidates(
                    army_id,
                    games_per_pair=games_per_pair,
                    bot=normalized_bot,
                    seed=seed,
                    map_name=normalized_map,
                    roster_ids=normalized_rosters,
                )
            )

        return _run_safely(
            operation,
            bearer_token=settings.bearer_token,
            safe_error_label="POST exploit candidate search failed",
        )

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
