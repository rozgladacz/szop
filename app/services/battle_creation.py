"""Shared transactionally neutral staging for durable Battle creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from .. import models
from .agents.roster_adapter import AdaptResult, roster_to_engine_roster
from .engine.dice import DeterministicDice
from .engine.persistence import save_checkpoint, save_events
from .engine.phases import deployment_round, setup_phase
from .engine.state import Objective, TerrainCircle, TerrainLine


@dataclass(frozen=True, slots=True)
class StagedBattleCreation:
    battle: models.Battle
    adapted_p1: AdaptResult
    adapted_p2: AdaptResult


def stage_battle_creation(
    session: Session,
    *,
    p1_user_id: int,
    p2_user_id: int,
    p1_roster: models.Roster,
    p2_roster: models.Roster,
    rng_seed: int,
    initiative_player: int,
    terrain: Iterable[TerrainCircle | TerrainLine] = (),
    objectives: Iterable[Objective] = (),
) -> StagedBattleCreation:
    """Stage one active Battle, its initial events, and current checkpoint."""
    adapted_p1 = roster_to_engine_roster(p1_roster, owner_player=0)
    adapted_p2 = roster_to_engine_roster(p2_roster, owner_player=1)
    state = setup_phase(
        [adapted_p1.units, adapted_p2.units],
        terrain=terrain,
        objectives=objectives,
        initiative_player=initiative_player,
    )
    state, deploy_events = deployment_round(state, ())
    battle = models.Battle(
        p1_user_id=p1_user_id,
        p2_user_id=p2_user_id,
        p1_roster_id=p1_roster.id,
        p2_roster_id=p2_roster.id,
        current_round=state.round,
        rng_seed=rng_seed,
        status="active",
    )
    session.add(battle)
    session.flush()
    save_events(
        session,
        battle.id,
        deploy_events,
        expected_latest_sequence=0,
    )
    sequence_at = deploy_events[-1].sequence if deploy_events else 0
    save_checkpoint(
        session,
        battle.id,
        sequence_at,
        state,
        DeterministicDice(seed=rng_seed),
    )
    return StagedBattleCreation(
        battle=battle,
        adapted_p1=adapted_p1,
        adapted_p2=adapted_p2,
    )


__all__ = ["StagedBattleCreation", "stage_battle_creation"]
