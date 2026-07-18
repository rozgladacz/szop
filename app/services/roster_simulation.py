"""Shared read-only roster-pair simulation used by API, clients, and leaf CLIs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.services.agents import PLAYER_SEED_OFFSET, make_player, simulate_from_rosters
from app.services.agents.maps import DEFAULT_DEPLOYMENT_ZONES, build_map
from app.services.agents.registry import FAST, bot_kinds
from app.services.agents.roster_adapter import roster_to_engine_roster
from szop_client.types import SimulationSummary

DEFAULT_SIMULATION_MAP = "lustrzana_a"
MAX_PUBLIC_SIMULATION_GAMES = 50
BATTLE_SIMULATION_BOTS = bot_kinds(FAST)


def simulation_players(bot: str, base_seed: int, game_index: int) -> list[Any]:
    """Build the two fresh players used for one deterministic batch game."""
    game_seed = base_seed + game_index
    return [
        make_player(bot, game_seed),
        make_player(bot, game_seed + PLAYER_SEED_OFFSET),
    ]


def simulation_player_factory(bot: str, base_seed: int) -> Callable[[int], list[Any]]:
    """Return the canonical per-game player factory for roster comparisons."""

    def factory(game_index: int) -> list[Any]:
        return simulation_players(bot, base_seed, game_index)

    return factory


def simulate_batch(
    rosters: Sequence[dict[str, Any]],
    player_factory: Callable[[int], Sequence[Any]],
    *,
    n: int = 1,
    seed: int = 0,
    terrain: Sequence[Any] = (),
    objectives: Sequence[Any] = (),
    alternate_initiative: bool = True,
    initiative_player: int = 0,
    deployment_zones: Sequence[Any] | None = None,
) -> SimulationSummary:
    """Run and aggregate a deterministic batch without database access or writes."""
    if type(n) is not int or n <= 0:
        raise ValueError(f"n musi być > 0, jest {n}")

    wins = [0, 0]
    draws = 0
    total_rounds = 0
    for game_index in range(n):
        players = player_factory(game_index)
        active_player = (
            game_index % 2 if alternate_initiative else initiative_player
        )
        result = simulate_from_rosters(
            rosters,
            players,
            seed=seed + game_index,
            terrain=terrain,
            objectives=objectives,
            initiative_player=active_player,
            deployment_zones=deployment_zones,
        )
        if result.winner is None:
            draws += 1
        else:
            wins[result.winner] += 1
        total_rounds += result.rounds_played

    return SimulationSummary(
        n_games=n,
        wins_p0=wins[0],
        wins_p1=wins[1],
        draws=draws,
        total_rounds=total_rounds,
    )


def simulate_roster_pair(
    roster_p0: Any,
    roster_p1: Any,
    *,
    bot: str = "priority",
    games: int = 10,
    seed: int = 0,
    map_name: str = DEFAULT_SIMULATION_MAP,
    allowed_bots: Sequence[str] | None = None,
) -> SimulationSummary:
    """Adapt two already-loaded ORM rosters and simulate them without DB queries."""
    if type(games) is not int or games <= 0:
        raise ValueError(f"games musi być > 0, jest {games}")
    if not isinstance(map_name, str) or not map_name:
        raise ValueError("map_name musi być niepustą nazwą")
    fixture = build_map(map_name, seed)
    if not isinstance(bot, str) or not bot:
        raise ValueError("bot musi być niepustą nazwą")
    normalized_bot = bot.lower()
    if allowed_bots is not None and normalized_bot not in allowed_bots:
        raise ValueError(
            f"Nieznany lub zbyt drogi bot {bot!r}; dozwolone: "
            f"{', '.join(allowed_bots)}"
        )
    rosters = [
        roster_to_engine_roster(roster_p0, owner_player=0).units,
        roster_to_engine_roster(roster_p1, owner_player=1).units,
    ]
    return simulate_batch(
        rosters,
        simulation_player_factory(normalized_bot, seed),
        n=games,
        seed=seed,
        terrain=fixture.terrain,
        objectives=fixture.objectives,
        deployment_zones=DEFAULT_DEPLOYMENT_ZONES,
    )


__all__ = [
    "BATTLE_SIMULATION_BOTS",
    "DEFAULT_SIMULATION_MAP",
    "MAX_PUBLIC_SIMULATION_GAMES",
    "simulate_batch",
    "simulate_roster_pair",
    "simulation_player_factory",
    "simulation_players",
]
