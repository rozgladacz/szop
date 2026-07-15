"""Read-only MCP facade over the public SZOP HTTP API."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_server.config import McpConfig
from szop_client.http import HttpClient

MAX_SIMULATION_GAMES = 50
TOOL_NAME = "simulate_engagement"

RosterId = Annotated[int, Field(strict=True, ge=1)]
GameCount = Annotated[
    int,
    Field(strict=True, ge=1, le=MAX_SIMULATION_GAMES),
]
Seed = Annotated[int, Field(strict=True)]
NonEmptyName = Annotated[str, Field(min_length=1)]


def create_server(
    config: McpConfig | None = None,
    *,
    client: HttpClient | None = None,
) -> FastMCP:
    """Build the MCP server with exactly the shipped read-only tool."""
    settings = config or McpConfig.from_env()
    http_client = client or HttpClient(
        settings.api_url,
        token=settings.bearer_token,
    )
    server = FastMCP(
        "SZOP",
        instructions="Read-only tools backed by the public SZOP HTTP API.",
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
        summary = http_client.simulate_roster_ids(
            p1_roster_id=roster_a,
            p2_roster_id=roster_b,
            n=games,
            bot=bot,
            seed=seed,
            map_name=map_name,
        )
        return {
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

    return server


mcp = create_server()


def main() -> None:
    """Run the local server over MCP stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
