from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.db import Base, get_db
from app.routers import battles
from app.security import hash_agent_token
from app.services.agents.maps import DEFAULT_DEPLOYMENT_ZONES, build_map
from app.services.engine.actions import DefendAction
from app.services.engine.state_codec import battle_state_to_json
from app.services.roster_simulation import simulation_player_factory
from szop_client import (
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
    LocalClient,
    RosterNotFoundError,
    battle_events_to_wire,
)


_RAW_TOKEN = "b5-parity-token"
_SIMULATION_MATRIX = (
    ("random", "lustrzana_a", 1, 3),
    ("random", "standard_a", 2, 17),
    ("priority", "lustrzana_a", 2, 17),
    ("priority", "standard_a", 1, 3),
)


class _TestClientTransport:
    """Adapt transport-neutral client requests to an in-process FastAPI app."""

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        parsed = urlsplit(request.url)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        response = self._client.request(
            request.method,
            target,
            headers=request.headers,
            content=request.body,
        )
        return HttpResponse(status_code=response.status_code, body=response.content)


@dataclass(frozen=True, slots=True)
class _ParityWorld:
    sessions: Any
    http: HttpClient
    transport: _TestClientTransport
    owner_id: int
    roster_ids: tuple[int, int]
    foreign_roster_id: int


def _seed_world(sessions: Any) -> tuple[int, tuple[int, int], int]:
    with sessions() as session:
        owner = models.User(username="parity-owner", password_hash="x")
        outsider = models.User(username="parity-outsider", password_hash="x")
        agent = models.User(
            username="parity-agent",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name="Parity rules")
        armory = models.Armory(name="Parity armory", owner=owner)
        session.add_all([owner, outsider, agent, ruleset, armory])
        session.flush()

        army = models.Army(
            name="Parity army",
            owner=owner,
            ruleset=ruleset,
            armory=armory,
        )
        rifle = models.Weapon(
            armory=armory,
            name="Parity rifle",
            range='24"',
            attacks=2,
            ap=0,
        )
        blade = models.Weapon(
            armory=armory,
            name="Parity blade",
            range="Walka wręcz",
            attacks=1,
            ap=0,
        )
        session.add_all([army, rifle, blade])
        session.flush()

        units = [
            models.Unit(
                army=army,
                name="Parity line",
                quality=4,
                defense=5,
                toughness=2,
                typical_models=1,
                position=0,
                default_weapon=rifle,
            ),
            models.Unit(
                army=army,
                name="Parity guard",
                quality=5,
                defense=4,
                toughness=2,
                typical_models=1,
                position=1,
                default_weapon=rifle,
            ),
        ]
        session.add_all(units)
        session.flush()
        for unit in units:
            session.add_all(
                [
                    models.UnitWeapon(
                        unit=unit,
                        weapon=rifle,
                        is_default=True,
                        default_count=1,
                        is_primary=True,
                        position=0,
                    ),
                    models.UnitWeapon(
                        unit=unit,
                        weapon=blade,
                        is_default=True,
                        default_count=1,
                        is_primary=True,
                        position=1,
                    ),
                ]
            )

        rosters: list[models.Roster] = []
        for index, unit in enumerate(units):
            roster = models.Roster(
                name=f"Parity roster {index}",
                army=army,
                owner=owner,
            )
            session.add(roster)
            session.flush()
            session.add(
                models.RosterUnit(
                    roster=roster,
                    unit=unit,
                    count=1,
                    position=0,
                )
            )
            rosters.append(roster)

        foreign = models.Roster(
            name="Parity foreign roster",
            army=army,
            owner=outsider,
        )
        session.add(foreign)
        session.flush()
        session.add(
            models.RosterUnit(
                roster=foreign,
                unit=units[0],
                count=1,
                position=0,
            )
        )
        session.add(
            models.AgentToken(
                agent_user=agent,
                owner_user=owner,
                token_hash=hash_agent_token(_RAW_TOKEN),
                scope_json=json.dumps(
                    {
                        battles.BATTLE_CREATE_SCOPE: True,
                        battles.BATTLE_READ_SCOPE: True,
                        battles.BATTLE_ACT_SCOPE: True,
                        battles.BATTLE_SIMULATE_SCOPE: True,
                    }
                ),
                expires_at=datetime.now(UTC).replace(tzinfo=None)
                + timedelta(days=1),
            )
        )
        session.commit()
        return owner.id, (rosters[0].id, rosters[1].id), foreign.id


@contextmanager
def _parity_world() -> Iterator[_ParityWorld]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    owner_id, roster_ids, foreign_roster_id = _seed_world(sessions)

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="b5-parity-session")
    test_app.include_router(battles.router)

    def override_get_db():
        with sessions() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as api_client:
            transport = _TestClientTransport(api_client)
            yield _ParityWorld(
                sessions=sessions,
                http=HttpClient(
                    "http://testserver",
                    token=_RAW_TOKEN,
                    transport=transport,
                ),
                transport=transport,
                owner_id=owner_id,
                roster_ids=roster_ids,
                foreign_roster_id=foreign_roster_id,
            )
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()


def _domain_write_counts(sessions: Any) -> tuple[int, int, int]:
    with sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (models.Battle, models.BattleEvent, models.BattleCheckpoint)
        )


def _state_wire(state: Any) -> dict[str, Any]:
    return battle_state_to_json(state)


def _events_wire(events: Any, *, since: int) -> tuple[list[dict[str, Any]], int]:
    return battle_events_to_wire(events, since=since)


def test_real_http_simulation_matches_local_client_and_is_repeatable_read_only() -> None:
    with _parity_world() as world:
        before = _domain_write_counts(world.sessions)
        for bot, map_name, games, seed in _SIMULATION_MATRIX:
            via_http = world.http.simulate_roster_ids(
                p1_roster_id=world.roster_ids[0],
                p2_roster_id=world.roster_ids[1],
                bot=bot,
                n=games,
                seed=seed,
                map_name=map_name,
            )
            repeated = world.http.simulate_roster_ids(
                p1_roster_id=world.roster_ids[0],
                p2_roster_id=world.roster_ids[1],
                bot=bot,
                n=games,
                seed=seed,
                map_name=map_name,
            )
            fixture = build_map(map_name, seed)
            with world.sessions() as session:
                via_local = LocalClient(
                    session=session,
                    user_id=world.owner_id,
                ).simulate_roster_ids(
                    world.roster_ids[0],
                    world.roster_ids[1],
                    simulation_player_factory(bot, seed),
                    n=games,
                    seed=seed,
                    terrain=fixture.terrain,
                    objectives=fixture.objectives,
                    deployment_zones=DEFAULT_DEPLOYMENT_ZONES,
                )
            assert via_http == repeated == via_local

        assert _domain_write_counts(world.sessions) == before == (0, 0, 0)
        with world.sessions() as session:
            audits = session.scalars(
                select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
            ).all()
        assert len(audits) == 2 * len(_SIMULATION_MATRIX)
        assert all(_RAW_TOKEN not in audit.params_json for audit in audits)


def test_real_http_create_read_and_single_action_match_local_client() -> None:
    with _parity_world() as world:
        seed = 29
        with world.sessions() as session:
            local = LocalClient(session=session, user_id=world.owner_id)
            local_battle_id = local.create_battle_from_roster_ids(
                *world.roster_ids,
                seed=seed,
                initiative_player=0,
                terrain=(),
                objectives=(),
                deployment=(),
            )

        metadata = world.http.create_battle(
            p1_roster_id=world.roster_ids[0],
            p2_roster_id=world.roster_ids[1],
            rng_seed=seed,
            initiative_player=0,
        )
        http_checkpoint = world.http.get_state_checkpoint(metadata.battle_id)
        local_state = local.get_state(local_battle_id)
        local_initial_events = local.get_events(local_battle_id)
        local_initial_sequence = local_initial_events[-1].sequence
        http_initial_events = world.http.get_events(metadata.battle_id)

        assert _state_wire(http_checkpoint.state) == _state_wire(local_state)
        assert (
            http_checkpoint.sequence_at
            == metadata.latest_sequence
            == local_initial_sequence
        )
        assert _events_wire(http_initial_events, since=0) == _events_wire(
            local_initial_events,
            since=0,
        )

        actor = next(
            blob
            for blob in local_state.blobs
            if blob.owner_player == local_state.active_player and blob.models_alive > 0
        )
        action = DefendAction(unit_id=actor.id)
        local_after, local_delta = local.take_action(
            local_battle_id,
            action,
            continuation=None,
        )
        http_after, http_delta = world.http.take_action(
            metadata.battle_id,
            action,
            continuation=None,
        )

        assert _state_wire(http_after) == _state_wire(local_after)
        assert _events_wire(
            http_delta,
            since=local_initial_sequence,
        ) == _events_wire(local_delta, since=local_initial_sequence)
        assert _state_wire(world.http.get_state(metadata.battle_id)) == _state_wire(
            local.get_state(local_battle_id)
        )
        assert _events_wire(
            world.http.get_events(
                metadata.battle_id,
                since=local_initial_sequence,
            ),
            since=local_initial_sequence,
        ) == _events_wire(
            local.get_events(local_battle_id, since=local_initial_sequence),
            since=local_initial_sequence,
        )

        latest_sequence = local_delta[-1].sequence
        assert world.http.get_events(metadata.battle_id, since=latest_sequence) == ()
        assert local.get_events(local_battle_id, since=latest_sequence) == ()


def test_roster_no_oracle_and_http_continuation_boundary_match_public_contracts() -> None:
    with _parity_world() as world:
        missing_roster_id = world.foreign_roster_id + 10_000
        with world.sessions() as session:
            local = LocalClient(session=session, user_id=world.owner_id)
            for hidden_roster_id in (world.foreign_roster_id, missing_roster_id):
                with pytest.raises(RosterNotFoundError):
                    local.create_battle_from_roster_ids(
                        world.roster_ids[0],
                        hidden_roster_id,
                    )

        http_statuses: list[int | None] = []
        for hidden_roster_id in (world.foreign_roster_id, missing_roster_id):
            with pytest.raises(HttpClientError) as exc_info:
                world.http.create_battle(
                    p1_roster_id=world.roster_ids[0],
                    p2_roster_id=hidden_roster_id,
                )
            http_statuses.append(exc_info.value.status_code)
        assert http_statuses == [404, 404]

        with world.sessions() as session:
            local_with_callback = LocalClient(session=session, user_id=world.owner_id)
            local_without_callback = LocalClient(session=session, user_id=world.owner_id)
            with_callback_id = local_with_callback.create_battle_from_roster_ids(
                *world.roster_ids,
                seed=7,
            )
            without_callback_id = local_without_callback.create_battle_from_roster_ids(
                *world.roster_ids,
                seed=7,
            )

        actor_id = next(
            blob.id
            for blob in local_with_callback.get_state(with_callback_id).blobs
            if blob.owner_player == 0
        )
        action = DefendAction(unit_id=actor_id)
        before_requests = len(world.transport.requests)
        with pytest.raises(ValueError, match="does not support continuation"):
            world.http.take_action(
                999,
                action,
                continuation=lambda *_args: None,
            )
        assert len(world.transport.requests) == before_requests
        assert local_with_callback.take_action(
            with_callback_id,
            action,
            continuation=lambda *_args: None,
        ) == local_without_callback.take_action(
            without_callback_id,
            action,
            continuation=None,
        )
