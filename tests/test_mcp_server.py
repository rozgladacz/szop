from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from app.routers import battles
from app.services.engine.events import EffectApplied, StatusAdded
from app.services.engine.state import (
    BattleState,
    Lokalizacja,
    Objective,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    WeaponProfile,
)
from mcp_server.config import McpConfig
from mcp_server.server import (
    MAX_SIMULATION_GAMES,
    TOOL_NAME,
    TOOL_NAMES,
    create_server,
)
from szop_client import (
    BattleMetadata,
    BattleStateCheckpoint,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
)

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


async def _call_tool(
    server,
    arguments: dict[str, Any],
    *,
    tool_name: str = TOOL_NAME,
    raise_exceptions: bool = True,
):
    async with create_connected_server_and_client_session(
        server, raise_exceptions=raise_exceptions
    ) as session:
        return await session.call_tool(tool_name, arguments)


async def _list_non_tool_capabilities(server):
    async with create_connected_server_and_client_session(
        server, raise_exceptions=True
    ) as session:
        resources = await session.list_resources()
        templates = await session.list_resource_templates()
        prompts = await session.list_prompts()
        return resources, templates, prompts


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


def test_server_registers_exactly_the_four_read_only_tools() -> None:
    tools = asyncio.run(_list_tools(create_server(McpConfig("http://localhost"))))

    assert [tool.name for tool in tools.tools] == list(TOOL_NAMES)


def test_server_registers_no_resources_templates_or_prompts() -> None:
    resources, templates, prompts = asyncio.run(
        _list_non_tool_capabilities(create_server(McpConfig("http://localhost")))
    )

    assert resources.resources == []
    assert templates.resourceTemplates == []
    assert prompts.prompts == []


def test_stdio_server_starts_and_publishes_exact_tool_surface() -> None:
    assert asyncio.run(_stdio_tool_names()) == list(TOOL_NAMES)


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


def test_mcp_package_has_no_direct_app_or_database_imports() -> None:
    package = Path(__file__).resolve().parents[1] / "mcp_server"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in package.glob("*.py")
    )

    assert "from app" not in source
    assert "import app" not in source
    assert "Session" not in source
    assert "sqlalchemy" not in source


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
    with patch.object(
        client,
        "simulate_roster_ids",
        wraps=client.simulate_roster_ids,
    ) as simulate_roster_ids:
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
    simulate_roster_ids.assert_called_once_with(
        p1_roster_id=100,
        p2_roster_id=200,
        n=3,
        bot="random",
        seed=5,
        map_name="lustrzana_a",
    )
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


def _complete_state() -> BattleState:
    weapon = WeaponProfile(
        slug="karabin",
        name="Karabin",
        range_inches=24,
        attacks=2,
        ap=1,
        attack_quality_override=3,
        weapon_abilities=("precyzyjny",),
    )
    return BattleState(
        round=3,
        active_player=1,
        activations_remaining=(2, 1),
        blobs=(
            UnitBlob(
                id=11,
                owner_player=0,
                position=Position(1.25, 2.5),
                radius_inches=1.75,
                models_alive=4,
                toughness_per_model=3,
                quality=2,
                defense=4,
                is_hero_unit=True,
                passives=("bohater",),
                ability_overrides=(("furia", True),),
                status_flags=("Aktywowany",),
                wounds_received=2,
                wounds_pending=1,
                wounds_pending_precise=3,
                wounds_eliminating=1,
                damage_balance=-2,
                melee_weapons=(),
                ranged_weapons=(weapon,),
                location=Lokalizacja.FRONT,
            ),
        ),
        terrain=(
            TerrainCircle(Position(8.0, 9.0), 2.25, ("Obronny", "Trudny")),
            TerrainLine(Position(0.0, 0.0), Position(12.0, 3.0), ("Blokujacy",)),
        ),
        objectives=(Objective(5, Position(6.0, 7.0), 1),),
        pending_effects=("efekt-a",),
        pending_interrupts=("interrupt-b",),
        score=(2, 3),
        is_game_over=True,
        initial_toughness_snapshot=((11, 12),),
        used_interrupts_this_round=((11, "rozkaz"),),
    )


def test_battle_observation_tools_call_exact_public_client_methods() -> None:
    client = Mock(spec=HttpClient)
    metadata = BattleMetadata(
        battle_id=42,
        p1_user_id=10,
        p2_user_id=20,
        p1_roster_id=100,
        p2_roster_id=200,
        winner_user_id=None,
        current_round=3,
        rng_seed=777,
        status="active",
        latest_sequence=9,
    )
    checkpoint = BattleStateCheckpoint(
        battle_id=42,
        sequence_at=9,
        schema="szop.battle_state",
        version=1,
        state=_complete_state(),
    )
    events = (
        StatusAdded(sequence=8, target_id=11, status="Aktywowany"),
        EffectApplied(
            sequence=9,
            slug="rozkaz",
            target_unit_id=11,
            source_unit_id=12,
            payload={"amount": 2},
        ),
    )
    client.get_battle_metadata.return_value = metadata
    client.get_state_checkpoint.return_value = checkpoint
    client.get_events.return_value = events
    server = create_server(McpConfig("http://localhost"), client=client)

    metadata_result = asyncio.run(
        _call_tool(server, {"battle_id": 42}, tool_name="get_battle_metadata")
    )
    state_result = asyncio.run(
        _call_tool(server, {"battle_id": 42}, tool_name="get_battle_state")
    )
    events_result = asyncio.run(
        _call_tool(
            server,
            {"battle_id": 42, "since": 7},
            tool_name="get_battle_events",
        )
    )

    client.get_battle_metadata.assert_called_once_with(42)
    client.get_state_checkpoint.assert_called_once_with(42)
    client.get_events.assert_called_once_with(42, since=7)
    assert metadata_result.structuredContent == {
        "battle_id": 42,
        "p1_user_id": 10,
        "p2_user_id": 20,
        "p1_roster_id": 100,
        "p2_roster_id": 200,
        "winner_user_id": None,
        "current_round": 3,
        "rng_seed": 777,
        "status": "active",
        "latest_sequence": 9,
    }
    assert state_result.structuredContent["battle_id"] == 42
    assert state_result.structuredContent["sequence_at"] == 9
    assert state_result.structuredContent["schema"] == "szop.battle_state"
    assert state_result.structuredContent["version"] == 1
    assert "rng" not in state_result.structuredContent
    assert events_result.structuredContent == {
        "battle_id": 42,
        "since": 7,
        "events": [
            {
                "sequence": 8,
                "type": "StatusAdded",
                "payload": {
                    "sequence": 8,
                    "target_id": 11,
                    "status": "Aktywowany",
                    "version": 1,
                    "event_type": "StatusAdded",
                },
            },
            {
                "sequence": 9,
                "type": "EffectApplied",
                "payload": {
                    "sequence": 9,
                    "slug": "rozkaz",
                    "target_unit_id": 11,
                    "source_unit_id": 12,
                    "payload": {"amount": 2},
                    "version": 1,
                    "event_type": "EffectApplied",
                },
            },
        ],
        "last_sequence": 9,
    }
    json.dumps(metadata_result.structuredContent, allow_nan=False)
    json.dumps(state_result.structuredContent, allow_nan=False)
    json.dumps(events_result.structuredContent, allow_nan=False)


def test_empty_battle_event_delta_has_stable_last_sequence() -> None:
    client = Mock(spec=HttpClient)
    client.get_events.return_value = ()

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            {"battle_id": 42, "since": 7},
            tool_name="get_battle_events",
        )
    )

    assert result.structuredContent == {
        "battle_id": 42,
        "since": 7,
        "events": [],
        "last_sequence": 7,
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments", "method_name"),
    [
        ("get_battle_metadata", {"battle_id": 0}, "get_battle_metadata"),
        ("get_battle_metadata", {"battle_id": True}, "get_battle_metadata"),
        ("get_battle_state", {"battle_id": 1.0}, "get_state_checkpoint"),
        (
            "get_battle_events",
            {"battle_id": 1, "since": True},
            "get_events",
        ),
        (
            "get_battle_events",
            {"battle_id": 1, "since": -1},
            "get_events",
        ),
    ],
)
def test_battle_observation_tools_reject_non_strict_input_before_client_call(
    tool_name: str,
    arguments: dict[str, Any],
    method_name: str,
) -> None:
    client = Mock(spec=HttpClient)

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            arguments,
            tool_name=tool_name,
            raise_exceptions=False,
        )
    )

    assert result.isError is True
    getattr(client, method_name).assert_not_called()


def test_malformed_client_event_data_is_returned_as_tool_error() -> None:
    client = Mock(spec=HttpClient)
    client.get_events.return_value = (
        StatusAdded(sequence=9, target_id=11, status="Aktywowany"),
        StatusAdded(sequence=8, target_id=11, status="Aktywowany"),
    )

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            {"battle_id": 42, "since": 7},
            tool_name="get_battle_events",
            raise_exceptions=False,
        )
    )

    assert result.isError is True


def test_battle_observation_rejects_mismatched_client_battle_ids() -> None:
    client = Mock(spec=HttpClient)
    client.get_battle_metadata.return_value = BattleMetadata(
        battle_id=43,
        p1_user_id=10,
        p2_user_id=20,
        p1_roster_id=100,
        p2_roster_id=200,
        winner_user_id=None,
        current_round=3,
        rng_seed=777,
        status="active",
        latest_sequence=9,
    )
    client.get_state_checkpoint.return_value = BattleStateCheckpoint(
        battle_id=43,
        sequence_at=9,
        schema="szop.battle_state",
        version=1,
        state=_complete_state(),
    )
    server = create_server(McpConfig("http://localhost"), client=client)

    metadata_result = asyncio.run(
        _call_tool(
            server,
            {"battle_id": 42},
            tool_name="get_battle_metadata",
            raise_exceptions=False,
        )
    )
    state_result = asyncio.run(
        _call_tool(
            server,
            {"battle_id": 42},
            tool_name="get_battle_state",
            raise_exceptions=False,
        )
    )

    assert metadata_result.isError is True
    assert state_result.isError is True


def test_battle_observation_rejects_malformed_state_and_nonfinite_event() -> None:
    client = Mock(spec=HttpClient)
    client.get_state_checkpoint.return_value = BattleStateCheckpoint(
        battle_id=42,
        sequence_at=9,
        schema="unknown.schema",
        version=1,
        state=_complete_state(),
    )
    client.get_events.return_value = (
        EffectApplied(
            sequence=8,
            slug="bad",
            target_unit_id=11,
            payload={"value": float("inf")},
        ),
    )
    server = create_server(McpConfig("http://localhost"), client=client)

    state_result = asyncio.run(
        _call_tool(
            server,
            {"battle_id": 42},
            tool_name="get_battle_state",
            raise_exceptions=False,
        )
    )
    events_result = asyncio.run(
        _call_tool(
            server,
            {"battle_id": 42, "since": 7},
            tool_name="get_battle_events",
            raise_exceptions=False,
        )
    )

    assert state_result.isError is True
    assert events_result.isError is True


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


def test_client_error_boundary_redacts_authorization_and_preserves_status() -> None:
    client = Mock(spec=HttpClient)
    client.get_battle_metadata.side_effect = HttpClientError(
        f"GET metadata failed with HTTP 403; Authorization: Bearer {RAW_TOKEN}",
        status_code=403,
    )
    config = McpConfig("http://localhost", RAW_TOKEN)

    result = asyncio.run(
        _call_tool(
            create_server(config, client=client),
            {"battle_id": 42},
            tool_name="get_battle_metadata",
            raise_exceptions=False,
        )
    )

    observed = repr(result)
    assert result.isError is True
    assert "HTTP 403" in observed
    assert RAW_TOKEN not in observed
    assert "Authorization: Bearer" not in observed
