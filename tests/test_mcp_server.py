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
from app.services.ability_lookup import (
    MAX_ABILITY_QUERY_LENGTH as API_ABILITY_QUERY_LENGTH,
)
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction
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
from app.services.rule_lookup import (
    MAX_RULE_QUERY_LENGTH as API_RULE_QUERY_LENGTH,
    MAX_RULE_RESULTS as API_RULE_RESULTS,
)
from mcp_server.config import McpConfig
from mcp_server.server import (
    MAX_ABILITY_QUERY_LENGTH,
    MAX_RULE_QUERY_LENGTH,
    MAX_RULE_RESULTS,
    MAX_SIMULATION_GAMES,
    TOOL_NAME,
    TOOL_NAMES,
    create_server,
)
from szop_client import (
    BattleActionProposal,
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


def test_server_registers_exactly_the_nine_public_api_tools() -> None:
    tools = asyncio.run(_list_tools(create_server(McpConfig("http://localhost"))))

    assert [tool.name for tool in tools.tools] == list(TOOL_NAMES)
    assert len(tools.tools) == 9


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


def test_mcp_import_does_not_load_local_rag_or_heavy_modules() -> None:
    code = (
        "import sys; import mcp_server.server; "
        "forbidden = {'mcp_server.search', 'mcp_server.vector_store', 'torch', "
        "'transformers', 'sentence_transformers', 'sqlite_vec'}; "
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

    server_source = (package / "server.py").read_text(encoding="utf-8")
    assert "mcp_server.search" not in server_source
    assert "mcp_server.vector_store" not in server_source
    assert "app.services.costs" not in server_source
    assert "scripts.validate_loadout" not in server_source


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


def test_reference_tools_delegate_once_to_public_http_client() -> None:
    client = Mock(spec=HttpClient)
    client.lookup_rule.return_value = {
        "schema": "szop.lookup_rule/v1",
        "version": 1,
        "source": "SZOP_Rozjemca.md",
        "query": "pkt 14.d.iv",
        "normalized_query": "14.d.iv",
        "mode": "reference",
        "matches": [
            {
                "ref": "14.d.iv",
                "text": "Obrońca może wykonać kontratak.",
                "parents": [],
                "children": [],
                "score": None,
            }
        ],
    }
    client.explain_ability.return_value = {
        "schema": "szop.explain_ability/v1",
        "version": 1,
        "source": "app.data.abilities",
        "query": "Podwojny",
        "ability": {
            "slug": "rozrywajacy",
            "name": "Podwójny",
            "display_name": "Podwójny",
            "type": "weapon",
            "description": "Naturalne 6 dają dodatkowe trafienie.",
            "value_label": None,
            "value_type": None,
            "requires_value": False,
            "value_choices": [],
            "blocked": False,
        },
    }
    server = create_server(McpConfig("http://localhost"), client=client)

    rule_result = asyncio.run(
        _call_tool(
            server,
            {"query": "pkt 14.d.iv", "limit": 3},
            tool_name="lookup_rule",
        )
    )
    ability_result = asyncio.run(
        _call_tool(
            server,
            {"query": "Podwojny"},
            tool_name="explain_ability",
        )
    )

    client.lookup_rule.assert_called_once_with("pkt 14.d.iv", limit=3)
    client.explain_ability.assert_called_once_with("Podwojny")
    assert rule_result.structuredContent == client.lookup_rule.return_value
    assert ability_result.structuredContent == client.explain_ability.return_value
    json.dumps(rule_result.structuredContent, ensure_ascii=False, allow_nan=False)
    json.dumps(ability_result.structuredContent, ensure_ascii=False, allow_nan=False)


def test_search_rules_tool_delegates_once_and_distinguishes_semantic_search() -> None:
    client = Mock(spec=HttpClient)
    client.search_rules.return_value = {
        "schema": "szop.search_rules/v1",
        "version": 1,
        "query": "Jak działa osłona?",
        "strategy": "hybrid_weighted_rrf",
        "count": 1,
        "results": [
            {
                "rank": 1,
                "chunk_id": "szop-rozjemca-0019",
                "source": "SZOP_Rozjemca.md",
                "headings": ["19. Osłona"],
                "refs": ["19"],
                "text": "Osłona zmienia test trafienia.",
                "score": 0.048915917504,
                "components": {
                    "bm25": {
                        "rank": 1,
                        "weight": 2.0,
                        "contribution": 0.032786885246,
                    },
                    "dense": {
                        "rank": 2,
                        "weight": 1.0,
                        "contribution": 0.016129032258,
                    },
                },
            }
        ],
    }
    server = create_server(McpConfig("http://localhost"), client=client)

    result = asyncio.run(
        _call_tool(
            server,
            {"query": "Jak działa osłona?", "limit": 3},
            tool_name="search_rules",
        )
    )
    tools = asyncio.run(_list_tools(server)).tools
    descriptions = {tool.name: tool.description or "" for tool in tools}

    client.search_rules.assert_called_once_with("Jak działa osłona?", limit=3)
    assert result.structuredContent == client.search_rules.return_value
    json.dumps(result.structuredContent, ensure_ascii=False, allow_nan=False)
    assert "semantic" in descriptions["search_rules"].lower()
    assert "paraphrase" in descriptions["search_rules"].lower()
    assert "exact" in descriptions["lookup_rule"].lower()


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "", "limit": 1},
        {"query": "x" * 201, "limit": 1},
        {"query": "osłona", "limit": 0},
        {"query": "osłona", "limit": True},
    ],
)
def test_search_rules_tool_rejects_invalid_input_before_client_call(
    arguments: dict[str, Any],
) -> None:
    client = Mock(spec=HttpClient)

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            arguments,
            tool_name="search_rules",
            raise_exceptions=False,
        )
    )

    assert result.isError is True
    client.search_rules.assert_not_called()


def test_search_rules_tool_redacts_query_token_and_paths_from_errors() -> None:
    private_query = "sekretna parafraza użytkownika"
    client = Mock(spec=HttpClient)
    client.search_rules.side_effect = HttpClientError(
        f"Authorization: Bearer {RAW_TOKEN}; {private_query}; C:\\private\\models",
        status_code=503,
    )
    config = McpConfig("http://localhost", RAW_TOKEN)

    result = asyncio.run(
        _call_tool(
            create_server(config, client=client),
            {"query": private_query, "limit": 5},
            tool_name="search_rules",
            raise_exceptions=False,
        )
    )

    observed = repr(result)
    assert result.isError is True
    assert "HTTP" not in observed or "503" in observed
    assert RAW_TOKEN not in observed
    assert private_query not in observed
    assert "C:\\private" not in observed


def test_validate_loadout_tool_delegates_once_to_public_client() -> None:
    client = Mock(spec=HttpClient)
    payload = {
        "schema": "szop.validate_loadout/v1",
        "version": 1,
        "unit_id": 7,
        "unit_name": "Strzelcy",
        "count": 3,
        "mode": {"raw": "bad", "normalized": "per_model", "clamped": True},
        "sections": [
            {
                "section": "weapons",
                "accepted": {"3": 0},
                "rejected": [
                    {"id": "999", "reason": "niedozwolone dla tej jednostki"}
                ],
                "clamped": [{"id": "3", "raw": -2, "normalized": 0}],
            },
            {"section": "active", "accepted": {}, "rejected": [], "clamped": []},
            {"section": "aura", "accepted": {}, "rejected": [], "clamped": []},
        ],
        "passive": {"accepted": {}, "rejected": ["unknown-passive"]},
        "cost": {
            "selected_role": "strzelec",
            "selected_total": 12.5,
            "components": {
                "active": 0.0,
                "aura": 0.0,
                "base": 10.0,
                "passive": 0.0,
                "weapon": 2.5,
            },
        },
        "has_issues": True,
    }
    client.validate_loadout.return_value = payload

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            {
                "unit_id": 7,
                "loadout": {"mode": "bad", "weapons": {"3": -2, "999": 1}},
                "count": 3,
            },
            tool_name="validate_loadout",
        )
    )

    client.validate_loadout.assert_called_once_with(
        7,
        {"mode": "bad", "weapons": {"3": -2, "999": 1}},
        count=3,
    )
    assert result.structuredContent == payload
    json.dumps(result.structuredContent, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(
    "arguments",
    [
        {"unit_id": 0, "loadout": {}, "count": 1},
        {"unit_id": True, "loadout": {}, "count": 1},
        {"unit_id": 1, "loadout": [], "count": 1},
        {"unit_id": 1, "loadout": {}, "count": True},
        {"unit_id": 1, "loadout": {}, "count": 101},
    ],
)
def test_validate_loadout_tool_rejects_invalid_input_before_client_call(
    arguments,
) -> None:
    client = Mock(spec=HttpClient)
    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            arguments,
            tool_name="validate_loadout",
            raise_exceptions=False,
        )
    )
    assert result.isError is True
    client.validate_loadout.assert_not_called()


def test_validate_loadout_tool_redacts_body_token_cost_and_paths_from_errors() -> None:
    private_value = "private-loadout-value"
    client = Mock(spec=HttpClient)
    client.validate_loadout.side_effect = HttpClientError(
        f"Authorization: Bearer {RAW_TOKEN}; {private_value}; "
        "selected_total=99; C:\\private\\loadout.json",
        status_code=500,
    )
    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost", RAW_TOKEN), client=client),
            {"unit_id": 7, "loadout": {"private": private_value}, "count": 1},
            tool_name="validate_loadout",
            raise_exceptions=False,
        )
    )
    observed = repr(result)
    assert result.isError is True
    assert "HTTP 500" in observed
    assert RAW_TOKEN not in observed
    assert private_value not in observed
    assert "selected_total" not in observed
    assert "C:\\private" not in observed


@pytest.mark.parametrize(
    ("tool_name", "arguments", "method_name"),
    [
        ("lookup_rule", {"query": "", "limit": 1}, "lookup_rule"),
        ("lookup_rule", {"query": "x" * 201, "limit": 1}, "lookup_rule"),
        ("lookup_rule", {"query": "osłona", "limit": 0}, "lookup_rule"),
        ("lookup_rule", {"query": "osłona", "limit": True}, "lookup_rule"),
        ("explain_ability", {"query": ""}, "explain_ability"),
        ("explain_ability", {"query": "x" * 101}, "explain_ability"),
    ],
)
def test_reference_tools_reject_invalid_input_before_client_call(
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


def test_reference_tool_limits_match_public_api_contract() -> None:
    assert MAX_RULE_QUERY_LENGTH == API_RULE_QUERY_LENGTH
    assert MAX_RULE_RESULTS == API_RULE_RESULTS
    assert MAX_ABILITY_QUERY_LENGTH == API_ABILITY_QUERY_LENGTH


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


def test_propose_battle_action_calls_only_public_client_proposal_method() -> None:
    client = Mock(spec=HttpClient)
    wire_action = action_to_json(DefendAction(unit_id=11))
    client.propose_battle_action.return_value = BattleActionProposal(
        proposal_id=17,
        owner_user_id=10,
        agent_user_id=20,
        token_id=30,
        battle_id=42,
        expected_sequence=9,
        action=wire_action,
        summary="Oddział 11: obrona",
        status="pending",
    )

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            {
                "battle_id": 42,
                "expected_sequence": 9,
                "action": wire_action,
                "summary": "Oddział 11: obrona",
            },
            tool_name="propose_battle_action",
        )
    )

    client.propose_battle_action.assert_called_once_with(
        42,
        expected_sequence=9,
        action=wire_action,
        summary="Oddział 11: obrona",
    )
    client.take_action.assert_not_called()
    assert result.structuredContent == {
        "proposal_id": 17,
        "owner_user_id": 10,
        "agent_user_id": 20,
        "token_id": 30,
        "battle_id": 42,
        "expected_sequence": 9,
        "action": wire_action,
        "summary": "Oddział 11: obrona",
        "status": "pending",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "battle_id": 0,
            "expected_sequence": 0,
            "action": {},
            "summary": "x",
        },
        {
            "battle_id": 1,
            "expected_sequence": True,
            "action": {},
            "summary": "x",
        },
        {
            "battle_id": 1,
            "expected_sequence": 0,
            "action": {},
            "summary": "",
        },
    ],
)
def test_propose_battle_action_rejects_invalid_shape_before_client_call(
    arguments: dict[str, Any],
) -> None:
    client = Mock(spec=HttpClient)

    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            arguments,
            tool_name="propose_battle_action",
            raise_exceptions=False,
        )
    )

    assert result.isError is True
    client.propose_battle_action.assert_not_called()


def test_propose_battle_action_rejects_invalid_wire_before_http() -> None:
    def transport(_request: HttpRequest) -> HttpResponse:
        raise AssertionError("HTTP transport should not be called")

    client = HttpClient("http://localhost", transport=transport)
    result = asyncio.run(
        _call_tool(
            create_server(McpConfig("http://localhost"), client=client),
            {
                "battle_id": 1,
                "expected_sequence": 0,
                "action": {},
                "summary": "Niepoprawna akcja",
            },
            tool_name="propose_battle_action",
            raise_exceptions=False,
        )
    )

    assert result.isError is True


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
