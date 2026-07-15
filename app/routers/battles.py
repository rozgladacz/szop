from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import get_current_user, require_agent_scope
from ..services.agents import PLAYER_SEED_OFFSET, make_player, simulate_from_rosters
from ..services.agents.maps import DEFAULT_DEPLOYMENT_ZONES, build_map
from ..services.agents.registry import FAST, bot_kinds
from ..services.agents.roster_adapter import AdaptResult, roster_to_engine_roster
from ..services.engine.dice import DeterministicDice
from ..services.engine.events import BattleEvent as EngineBattleEvent
from ..services.engine.events import event_to_json
from ..services.engine.persistence import (
    latest_event_sequence,
    load_events,
    load_latest_checkpoint,
    save_checkpoint,
    save_events,
)
from ..services.engine.phases import deployment_round, setup_phase
from ..services.engine.state_codec import battle_state_to_json

router = APIRouter(prefix="/battles", tags=["battles"])

BATTLE_CREATE_SCOPE = "battle:create"
BATTLE_READ_SCOPE = "battle:read"
BATTLE_SIMULATE_SCOPE = "battle:simulate"
MAX_SIMULATION_GAMES = 50
BATTLE_SIMULATION_BOTS = bot_kinds(FAST)


@dataclass(frozen=True)
class BattleCreator:
    user_id: int


@dataclass(frozen=True)
class BattleReader:
    user_id: int


@dataclass(frozen=True)
class BattleSimulator:
    user_id: int


class BattleCreate(BaseModel):
    p1_roster_id: int = Field(..., ge=1)
    p2_roster_id: int = Field(..., ge=1)
    rng_seed: int = 0
    initiative_player: int = Field(0, ge=0, le=1)


class BattleSimulate(BaseModel):
    p1_roster_id: int = Field(..., ge=1)
    p2_roster_id: int = Field(..., ge=1)
    games: int = Field(10, ge=1, le=MAX_SIMULATION_GAMES)
    bot: str = "priority"
    seed: int = 0
    map_name: str = "lustrzana_a"


class BattleEventPublic(BaseModel):
    sequence: int = Field(..., ge=1)
    event_type: str
    payload: dict[str, Any]


class BattleEventsPublic(BaseModel):
    battle_id: int
    events: list[BattleEventPublic]


class BattleStatePublic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    checkpoint_schema: str = Field(..., alias="schema")
    version: int = Field(..., ge=1)
    battle_id: int
    sequence_at: int = Field(..., ge=0)
    state: dict[str, Any]


class RosterAdaptationPublic(BaseModel):
    dropped_excluded: list[str] = Field(default_factory=list)
    inert_incomplete: list[str] = Field(default_factory=list)
    deferred_attached_heroes: list[int] = Field(default_factory=list)


class BattleAdaptationPublic(BaseModel):
    p1: RosterAdaptationPublic
    p2: RosterAdaptationPublic


class BattlePublic(BaseModel):
    battle_id: int
    p1_user_id: int | None
    p2_user_id: int | None
    p1_roster_id: int | None
    p2_roster_id: int | None
    winner_user_id: int | None
    current_round: int = Field(..., ge=0)
    rng_seed: int
    status: str
    latest_sequence: int = Field(..., ge=0)
    adaptation_report: BattleAdaptationPublic | None = None


class BattleSimulationPublic(BaseModel):
    p1_roster_id: int
    p2_roster_id: int
    bot: str
    map_name: str
    n_games: int = Field(..., ge=1)
    wins_p0: int = Field(..., ge=0)
    wins_p1: int = Field(..., ge=0)
    draws: int = Field(..., ge=0)
    total_rounds: int = Field(..., ge=0)
    win_rate_p0: float
    win_rate_p1: float
    draw_rate: float
    avg_rounds: float


def _authorization_header(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if value is None:
        value = request.headers.get("Authorization")
    return value


def _has_authorization_header(request: Request) -> bool:
    value = _authorization_header(request)
    return bool(value and value.strip())


def _authorized_owner_user_id(
    *,
    request: Request,
    db: Session,
    current_user: models.User | None,
    agent_scope: str,
) -> int:
    if _has_authorization_header(request):
        principal = require_agent_scope(agent_scope)(request=request, db=db)
        return principal.owner_user_id

    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return current_user.id


def _battle_creator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleCreator:
    return BattleCreator(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_CREATE_SCOPE,
        )
    )


def _battle_reader(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleReader:
    return BattleReader(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_READ_SCOPE,
        )
    )


def _battle_simulator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
) -> BattleSimulator:
    return BattleSimulator(
        user_id=_authorized_owner_user_id(
            request=request,
            db=db,
            current_user=current_user,
            agent_scope=BATTLE_SIMULATE_SCOPE,
        )
    )


def _get_accessible_battle(
    db: Session, *, battle_id: int, reader: BattleReader
) -> models.Battle:
    battle = db.execute(
        select(models.Battle).where(
            models.Battle.id == battle_id,
            or_(
                models.Battle.p1_user_id == reader.user_id,
                models.Battle.p2_user_id == reader.user_id,
            ),
        )
    ).scalar_one_or_none()
    if battle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return battle


def _get_owned_roster(
    db: Session, *, roster_id: int, owner_user_id: int
) -> models.Roster:
    roster = db.execute(
        select(models.Roster).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == owner_user_id,
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return roster


def _public_event(event: EngineBattleEvent) -> BattleEventPublic:
    payload = event_to_json(event)
    return BattleEventPublic(
        sequence=int(payload["sequence"]),
        event_type=str(payload["event_type"]),
        payload=payload,
    )


def _public_adaptation(result: AdaptResult) -> RosterAdaptationPublic:
    return RosterAdaptationPublic(
        dropped_excluded=list(result.dropped_excluded),
        inert_incomplete=list(result.inert_incomplete),
        deferred_attached_heroes=list(result.deferred_attached_heroes),
    )


def _public_battle(
    db: Session,
    battle: models.Battle,
    *,
    adaptation_report: BattleAdaptationPublic | None = None,
) -> BattlePublic:
    return BattlePublic(
        battle_id=battle.id,
        p1_user_id=battle.p1_user_id,
        p2_user_id=battle.p2_user_id,
        p1_roster_id=battle.p1_roster_id,
        p2_roster_id=battle.p2_roster_id,
        winner_user_id=battle.winner_user_id,
        current_round=battle.current_round,
        rng_seed=battle.rng_seed,
        status=battle.status,
        latest_sequence=latest_event_sequence(db, battle.id),
        adaptation_report=adaptation_report,
    )


def _simulation_players(bot: str, base_seed: int, game_index: int):
    seed = base_seed + game_index
    return [
        make_player(bot, seed),
        make_player(bot, seed + PLAYER_SEED_OFFSET),
    ]


@router.post("", response_model=BattlePublic, status_code=status.HTTP_201_CREATED)
def create_battle(
    payload: BattleCreate,
    db: Session = Depends(get_db),
    creator: BattleCreator = Depends(_battle_creator),
) -> BattlePublic:
    roster_p0 = _get_owned_roster(
        db, roster_id=payload.p1_roster_id, owner_user_id=creator.user_id
    )
    roster_p1 = _get_owned_roster(
        db, roster_id=payload.p2_roster_id, owner_user_id=creator.user_id
    )
    adapted_p0 = roster_to_engine_roster(roster_p0, owner_player=0)
    adapted_p1 = roster_to_engine_roster(roster_p1, owner_player=1)
    rosters = [adapted_p0.units, adapted_p1.units]
    state = setup_phase(
        rosters,
        terrain=(),
        objectives=(),
        initiative_player=payload.initiative_player,
    )
    state, deploy_events = deployment_round(state, ())
    battle = models.Battle(
        p1_user_id=creator.user_id,
        p2_user_id=creator.user_id,
        p1_roster_id=roster_p0.id,
        p2_roster_id=roster_p1.id,
        current_round=state.round,
        rng_seed=payload.rng_seed,
        status="active",
    )
    db.add(battle)
    db.flush()
    save_events(db, battle.id, deploy_events, expected_latest_sequence=0)
    sequence_at = deploy_events[-1].sequence if deploy_events else 0
    save_checkpoint(
        db,
        battle.id,
        sequence_at,
        state,
        DeterministicDice(seed=payload.rng_seed),
    )
    db.commit()
    db.refresh(battle)
    return _public_battle(
        db,
        battle,
        adaptation_report=BattleAdaptationPublic(
            p1=_public_adaptation(adapted_p0),
            p2=_public_adaptation(adapted_p1),
        ),
    )


@router.post("/simulate", response_model=BattleSimulationPublic)
def simulate_battle(
    payload: BattleSimulate,
    db: Session = Depends(get_db),
    simulator: BattleSimulator = Depends(_battle_simulator),
) -> BattleSimulationPublic:
    roster_p0 = _get_owned_roster(
        db, roster_id=payload.p1_roster_id, owner_user_id=simulator.user_id
    )
    roster_p1 = _get_owned_roster(
        db, roster_id=payload.p2_roster_id, owner_user_id=simulator.user_id
    )
    try:
        map_fixture = build_map(payload.map_name, payload.seed)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    bot = payload.bot.lower()
    if bot not in BATTLE_SIMULATION_BOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Nieznany lub zbyt drogi bot {payload.bot!r}; dozwolone: "
                f"{', '.join(BATTLE_SIMULATION_BOTS)}"
            ),
        )

    rosters = [
        roster_to_engine_roster(roster_p0, owner_player=0).units,
        roster_to_engine_roster(roster_p1, owner_player=1).units,
    ]
    wins = [0, 0]
    draws = 0
    total_rounds = 0
    for i in range(payload.games):
        try:
            players = _simulation_players(bot, payload.seed, i)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        result = simulate_from_rosters(
            rosters,
            players,
            seed=payload.seed + i,
            terrain=map_fixture.terrain,
            objectives=map_fixture.objectives,
            initiative_player=i % 2,
            deployment_zones=DEFAULT_DEPLOYMENT_ZONES,
        )
        if result.winner is None:
            draws += 1
        else:
            wins[result.winner] += 1
        total_rounds += result.rounds_played

    n_games = payload.games
    return BattleSimulationPublic(
        p1_roster_id=roster_p0.id,
        p2_roster_id=roster_p1.id,
        bot=bot,
        map_name=payload.map_name.lower(),
        n_games=n_games,
        wins_p0=wins[0],
        wins_p1=wins[1],
        draws=draws,
        total_rounds=total_rounds,
        win_rate_p0=wins[0] / n_games,
        win_rate_p1=wins[1] / n_games,
        draw_rate=draws / n_games,
        avg_rounds=total_rounds / n_games,
    )


@router.get("/{battle_id}", response_model=BattlePublic)
def get_battle(
    battle_id: int,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattlePublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    return _public_battle(db, battle)


@router.get("/{battle_id}/events", response_model=BattleEventsPublic)
def get_battle_events(
    battle_id: int,
    since: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleEventsPublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    events = load_events(db, battle.id, since=since)
    return BattleEventsPublic(
        battle_id=battle.id,
        events=[_public_event(event) for event in events],
    )


@router.get("/{battle_id}/state", response_model=BattleStatePublic)
def get_battle_state(
    battle_id: int,
    db: Session = Depends(get_db),
    reader: BattleReader = Depends(_battle_reader),
) -> BattleStatePublic:
    battle = _get_accessible_battle(db, battle_id=battle_id, reader=reader)
    checkpoint = load_latest_checkpoint(db, battle.id)
    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Current battle checkpoint is unavailable",
        )
    serialized = battle_state_to_json(checkpoint.state)
    return BattleStatePublic(
        checkpoint_schema=str(serialized["schema"]),
        version=int(serialized["version"]),
        battle_id=battle.id,
        sequence_at=checkpoint.sequence_at,
        state=serialized["state"],
    )
