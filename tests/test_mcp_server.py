from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from app.routers import battles
from mcp_server.config import McpConfig
from mcp_server.server import MAX_SIMULATION_GAMES, create_server
from szop_client.http import HttpClient, HttpRequest, HttpResponse

RAW_TOKEN = "mcp-bearer-secret"


def _json_response(payload: Mapping[str, Any], *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload).encode("utf-8"),
    )


async def _list_tools(server):
    async with create_connected_server_and_client_session(
        server, raise_exceptions=True
    ) as session:
        return await session.list_tools()


async def _call_tool(server, arguments: dict[str, Any], *, raise_exceptions: bool = True):
    async with create_connected_server_and_client_session(
        server, raise_exceptions=raise_exceptions
    ) as session:
        return await session.call_tool("simulate_engagement", arguments)


async def _stdio_tool_names() -> list[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-X", "utf8", "-m", "mcp_server.server"],
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [tool.name for tool in tools.tools]


def test_config_loads_api_settings_and_redacts_token() -> None:
    config = McpConfig.from_env(
        {
            "SZOP_API_URL": " https://szop.example/api/ ",
            "SZOP_API_TOKEN": f" {RAW_TOKEN} ",
        }
    )

    assert config.api_url == "https://szop.example/api/"
    assert config.bearer_token == RAW_TOKEN
    assert RAW_TOKEN not in repr(config)


def test_config_uses_local_default_and_rejects_empty_url_without_secret() -> None:
    assert McpConfig.from_env({}).api_url == "http://127.0.0.1:8000"

    with pytest.raises(ValueError) as exc_info:
        McpConfig.from_env({"SZOP_API_URL": " ", "SZOP_API_TOKEN": RAW_TOKEN})

    assert RAW_TOKEN not in str(exc_info.value)


def test_server_registers_exactly_the_first_read_only_tool() -> None:
    tools = asyncio.run(_list_tools(create_server(McpConfig("http://localhost"))))

    assert [tool.name for tool in tools.tools] == ["simulate_engagement"]


def test_stdio_server_starts_and_publishes_the_tool() -> None:
    assert asyncio.run(_stdio_tool_names()) == ["simulate_engagement"]


def test_mcp_import_does_not_load_orm_or_database_modules() -> None:
    code = (
        "import sys; import mcp_server.server; "
        "forbidden = {'app.models', 'app.db', 'sqlalchemy.orm'}; "
        "loaded = sorted(forbidden.intersection(sys.modules)); "
        "print(','.join(loaded)); raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_simulate_engagement_posts_public_api_request_and_returns_result() -> None:
    seen: list[HttpRequest] = []

    def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return _json_response(
            {
                "n_games": 3,
                "wins_p0": 1,
                "wins_p1": 1,
                "draws": 1,
                "total_rounds": 12,
            }
        )

    config = McpConfig("https://szop.example/api/", RAW_TOKEN)
    client = HttpClient(config.api_url, token=config.bearer_token, transport=transport)
    result = asyncio.run(
        _call_tool(
            create_server(config, client=client),
            {
                "roster_a": 100,
                "roster_b": 200,
                "games": 3,
                "bot": "random",
                "seed": 5,
                "map_name": "lustrzana_a",
            },
        )
    )

    assert result.isError is False
    assert result.structuredContent == {
        "n_games": 3,
        "wins_p0": 1,
        "wins_p1": 1,
        "draws": 1,
        "total_rounds": 12,
        "win_rate_p0": pytest.approx(1 / 3),
        "win_rate_p1": pytest.approx(1 / 3),
        "draw_rate": pytest.approx(1 / 3),
        "avg_rounds": 4.0,
    }
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url == "https://szop.example/api/battles/simulate"
    assert request.headers["Authorization"] == f"Bearer {RAW_TOKEN}"
    assert json.loads(request.body.decode("utf-8")) == {
        "p1_roster_id": 100,
        "p2_roster_id": 200,
        "games": 3,
        "bot": "random",
        "seed": 5,
        "map_name": "lustrzana_a",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"roster_a": 0, "roster_b": 2, "games": 1},
        {"roster_a": 1, "roster_b": 2, "games": 0},
        {"roster_a": 1, "roster_b": 2, "games": MAX_SIMULATION_GAMES + 1},
        {"roster_a": 1, "roster_b": 2, "games": 1, "bot": ""},
        {"roster_a": 1, "roster_b": 2, "games": 1, "map_name": ""},
    ],
)
def test_simulate_engagement_rejects_invalid_input_before_http(
    arguments: dict[str, Any],
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("HTTP transport should not be called")

    client = HttpClient("http://localhost", transport=transport)
    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            arguments,
            raise_exceptions=False,
        )
    )

    assert result.isError is True


def test_mcp_games_limit_matches_public_api_contract() -> None:
    assert MAX_SIMULATION_GAMES == battles.MAX_SIMULATION_GAMES


def test_http_error_is_returned_as_tool_error_without_leaking_token(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=403, body=b'{"detail":"forbidden"}')

    config = McpConfig("http://localhost", RAW_TOKEN)
    client = HttpClient(config.api_url, token=config.bearer_token, transport=transport)
    result = asyncio.run(
        _call_tool(
            create_server(config, client=client),
            {"roster_a": 1, "roster_b": 2, "games": 1},
            raise_exceptions=False,
        )
    )
    captured = capsys.readouterr()
    observed = "\n".join(
        [
            repr(config),
            repr(result),
            caplog.text,
            captured.out,
            captured.err,
        ]
    )

    assert result.isError is True
    assert "HTTP 403" in repr(result)
    assert RAW_TOKEN not in observed
