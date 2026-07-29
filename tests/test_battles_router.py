from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.db import Base
from app.main import app
from app.routers import battles
from app.security import hash_agent_token, hash_password
from app.services import battle_actions as battle_action_service
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction, ManeuverAction, ShootAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.events import MoveExecuted, StatusAdded, json_to_event
from app.services.engine.persistence import (
    load_events,
    load_latest_checkpoint,
    save_checkpoint,
    save_events,
)
from app.services.engine.phases import deployment_round, round_end_phase, setup_phase
from app.services.engine.resolver import apply, should_end_round
from app.services.engine.state import Objective, Position
from app.services.engine.state_codec import battle_state_from_json
from szop_client import LocalClient

RAW_TOKEN = "battle-read-secret"


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_user(session: Session, username: str) -> models.User:
    user = models.User(username=username, password_hash=hash_password("haslo"))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_battle(
    session: Session,
    *,
    p1: models.User | None,
    p2: models.User | None,
) -> models.Battle:
    battle = models.Battle(
        p1_user_id=p1.id if p1 is not None else None,
        p2_user_id=p2.id if p2 is not None else None,
        rng_seed=2026,
        status="active",
    )
    session.add(battle)
    session.commit()
    session.refresh(battle)
    return battle


def _seed_events(session: Session, battle: models.Battle) -> None:
    save_events(
        session,
        battle.id,
        [
            MoveExecuted(sequence=1, unit_id=1, from_pos=(0, 0), to_pos=(1, 1)),
            StatusAdded(sequence=2, target_id=1, status="Aktywowany"),
        ],
    )
    session.commit()


def _action_state(*, objectives: tuple[Objective, ...] = ()):
    weapon = {
        "slug": "test-rifle",
        "name": "Test rifle",
        "range_inches": 24,
        "attacks": 1,
        "ap": 0,
    }
    state = setup_phase(
        [
            {
                "owner_player": 0,
                "units": [
                    {
                        "id": 1,
                        "position": (0, 0),
                        "models": 3,
                        "toughness": 10,
                        "weapons": [weapon],
                    }
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {
                        "id": 2,
                        "position": (12, 0),
                        "models": 3,
                        "toughness": 10,
                        "weapons": [weapon],
                    }
                ],
            },
        ],
        objectives=objectives,
        initiative_player=0,
    )
    state, _ = deployment_round(state, ())
    return state


def _persist_action_battle(
    session: Session,
    *,
    p1: models.User,
    p2: models.User,
    state,
    seed: int = 2026,
) -> models.Battle:
    battle = models.Battle(
        p1_user_id=p1.id,
        p2_user_id=p2.id,
        current_round=state.round,
        rng_seed=seed,
        status="active",
    )
    session.add(battle)
    session.flush()
    save_checkpoint(
        session,
        battle.id,
        0,
        state,
        DeterministicDice(seed),
    )
    session.commit()
    session.refresh(battle)
    return battle


def _action_db_snapshot(session: Session, battle_id: int) -> tuple:
    session.expire_all()
    battle = session.get(models.Battle, battle_id)
    events = session.execute(
        select(models.BattleEvent).where(models.BattleEvent.battle_id == battle_id)
    ).scalars().all()
    checkpoints = session.execute(
        select(models.BattleCheckpoint).where(
            models.BattleCheckpoint.battle_id == battle_id
        )
    ).scalars().all()
    latest = load_latest_checkpoint(session, battle_id)
    return (
        len(events),
        len(checkpoints),
        battle.current_round,
        battle.status,
        battle.winner_user_id,
        latest.sequence_at if latest is not None else None,
        latest.state if latest is not None else None,
        latest.dice.to_checkpoint() if latest is not None else None,
    )


def _seed_agent_token(
    session: Session,
    *,
    owner: models.User,
    raw_token: str = RAW_TOKEN,
    scopes: dict[str, bool] | None = None,
) -> models.AgentToken:
    agent = models.User(
        username=f"agent-{owner.id}",
        password_hash=hash_password("sekret"),
        role=models.USER_ROLE_AGENT,
    )
    token = models.AgentToken(
        agent_user=agent,
        owner_user=owner,
        token_hash=hash_agent_token(raw_token),
        scope_json=json.dumps(scopes or {battles.BATTLE_READ_SCOPE: True}),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    )
    session.add_all([agent, token])
    session.commit()
    session.refresh(token)
    return token


def _seed_roster(
    session: Session,
    *,
    name: str,
    owner_id: int,
) -> models.Roster:
    ruleset = models.RuleSet(name=f"Rules {name}")
    armory = models.Armory(name=f"Armory {name}", owner_id=owner_id)
    session.add_all([ruleset, armory])
    session.flush()
    army = models.Army(
        name=f"Army {name}",
        owner_id=owner_id,
        ruleset=ruleset,
        armory=armory,
    )
    session.add(army)
    session.flush()
    blade = models.Weapon(
        armory=armory,
        name=f"Ostrze {name}",
        range="Walka wręcz",
        attacks=1,
        ap=0,
    )
    session.add(blade)
    session.flush()
    unit = models.Unit(
        army=army,
        name=f"Piechota {name}",
        quality=4,
        defense=5,
        toughness=3,
        typical_models=2,
        position=0,
        default_weapon=blade,
    )
    session.add(unit)
    session.flush()
    session.add(
        models.UnitWeapon(
            unit=unit,
            weapon=blade,
            is_default=True,
            default_count=1,
            is_primary=True,
            position=0,
        )
    )
    roster = models.Roster(name=f"Roster {name}", army=army, owner_id=owner_id)
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
    session.commit()
    session.refresh(roster)
    return roster


def _attach_roster_unit(session: Session, roster: models.Roster) -> models.RosterUnit:
    parent = roster.roster_units[0]
    attached = models.RosterUnit(
        roster_id=roster.id,
        unit_id=parent.unit_id,
        count=1,
        position=parent.position + 1,
        parent_roster_unit_id=parent.id,
    )
    session.add(attached)
    session.commit()
    session.refresh(attached)
    session.expire(roster, ["roster_units"])
    return attached


def _fake_request(
    token: str | None = RAW_TOKEN,
    *,
    battle_id: int = 7,
    query_params: dict[str, str] | None = None,
    method: str = "GET",
    path: str | None = None,
    path_params: dict[str, str] | None = None,
) -> SimpleNamespace:
    headers = {}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    route_path = path or f"/battles/{battle_id}/events"
    return SimpleNamespace(
        headers=headers,
        method=method,
        url=SimpleNamespace(path=route_path),
        path_params=path_params if path_params is not None else {"battle_id": str(battle_id)},
        query_params=query_params or {},
    )


def test_battles_router_is_registered_in_app() -> None:
    route_paths = {getattr(route, "path", "") for route in app.routes}
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods_by_path.setdefault(path, set()).update(getattr(route, "methods", set()))

    assert "/battles/{battle_id}" in route_paths
    assert "GET" in methods_by_path["/battles/{battle_id}"]
    assert "/battles" in route_paths
    assert "POST" in methods_by_path["/battles"]
    assert "/battles/simulate" in route_paths
    assert "POST" in methods_by_path["/battles/simulate"]
    assert "/battles/{battle_id}/events" in route_paths
    assert "GET" in methods_by_path["/battles/{battle_id}/events"]
    assert "/battles/{battle_id}/state" in route_paths
    assert "GET" in methods_by_path["/battles/{battle_id}/state"]
    assert "/battles/{battle_id}/actions" in route_paths
    assert "POST" in methods_by_path["/battles/{battle_id}/actions"]
    assert "/battles/{battle_id}/activations" in route_paths
    assert "POST" in methods_by_path["/battles/{battle_id}/activations"]
    assert "/battles/{battle_id}/interrupts" in route_paths
    assert "POST" in methods_by_path["/battles/{battle_id}/interrupts"]
    transitions_path = (
        "/battles/{battle_id}/activations/{activation_id}/transitions"
    )
    assert transitions_path in route_paths
    assert "POST" in methods_by_path[transitions_path]


def test_create_battle_starts_owner_scoped_battle_and_persists_events() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)

    response = battles.create_battle(
        battles.BattleCreate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            rng_seed=777,
        ),
        db=session,
        creator=battles.BattleCreator(user_id=owner.id),
    )

    battle = session.get(models.Battle, response.battle_id)
    assert battle is not None
    assert battle.p1_user_id == owner.id
    assert battle.p2_user_id == owner.id
    assert battle.p1_roster_id == roster_a.id
    assert battle.p2_roster_id == roster_b.id
    assert battle.current_round == 1
    assert battle.rng_seed == 777
    assert battle.status == "active"
    assert battle.activation_protocol_version == 1
    events = load_events(session, battle.id)
    checkpoint = load_latest_checkpoint(session, battle.id)
    assert events
    assert checkpoint is not None
    assert response.latest_sequence == len(events)
    assert checkpoint.sequence_at == response.latest_sequence
    assert checkpoint.state.round == battle.current_round
    assert checkpoint.state.initiative_player is None
    assert checkpoint.dice.seed == battle.rng_seed
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    checkpoint_row = session.execute(
        select(models.BattleCheckpoint).where(
            models.BattleCheckpoint.battle_id == battle.id
        )
    ).scalar_one()
    assert json.loads(checkpoint_row.state_json)["version"] == 1
    assert response.activation_protocol_version == 1


def test_create_battle_explicit_v2_persists_coherent_idle_checkpoint() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner-v2")
    roster_a = _seed_roster(session, name="A-v2", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B-v2", owner_id=owner.id)

    response = battles.create_battle(
        battles.BattleCreate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            rng_seed=778,
            initiative_player=1,
            activation_protocol_version=2,
        ),
        db=session,
        creator=battles.BattleCreator(user_id=owner.id),
    )

    battle = session.get(models.Battle, response.battle_id)
    checkpoint = load_latest_checkpoint(session, response.battle_id)
    checkpoint_row = session.execute(
        select(models.BattleCheckpoint).where(
            models.BattleCheckpoint.battle_id == response.battle_id
        )
    ).scalar_one()
    assert battle is not None
    assert checkpoint is not None
    assert response.activation_protocol_version == 2
    assert battle.activation_protocol_version == 2
    assert checkpoint.state.initiative_player == 1
    assert checkpoint.state.activation is None
    assert json.loads(checkpoint_row.state_json)["version"] == 2


@pytest.mark.parametrize("invalid_version", [0, 3, True, "2", 2.0, None])
def test_create_battle_protocol_version_is_strict_before_write(
    invalid_version,
) -> None:
    session = _build_session()
    with pytest.raises(ValueError):
        battles.BattleCreate.model_validate(
            {
                "p1_roster_id": 1,
                "p2_roster_id": 2,
                "activation_protocol_version": invalid_version,
            }
        )
    assert session.execute(select(models.Battle)).scalars().all() == []


def _direct_create_statement_count(protocol_version: int) -> tuple[int, int]:
    session = _build_session()
    owner = _seed_user(session, f"sql-owner-{protocol_version}")
    roster_a = _seed_roster(
        session,
        name=f"SQL-A-{protocol_version}",
        owner_id=owner.id,
    )
    roster_b = _seed_roster(
        session,
        name=f"SQL-B-{protocol_version}",
        owner_id=owner.id,
    )
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = battles.create_battle(
            battles.BattleCreate(
                p1_roster_id=roster_a.id,
                p2_roster_id=roster_b.id,
                activation_protocol_version=protocol_version,
            ),
            db=session,
            creator=battles.BattleCreator(user_id=owner.id),
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
        session.close()
    assert response.activation_protocol_version == protocol_version
    select_count = sum(
        statement.lstrip().upper().startswith("SELECT")
        for statement in statements
    )
    return len(statements), select_count


def test_direct_create_v2_has_zero_sql_statement_delta_from_v1() -> None:
    assert _direct_create_statement_count(2) == _direct_create_statement_count(1)


def test_create_battle_reports_roster_adapter_omissions() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)
    attached = _attach_roster_unit(session, roster_a)

    response = battles.create_battle(
        battles.BattleCreate(p1_roster_id=roster_a.id, p2_roster_id=roster_b.id),
        db=session,
        creator=battles.BattleCreator(user_id=owner.id),
    )

    assert response.adaptation_report is not None
    assert response.adaptation_report.p1.deferred_attached_heroes == [attached.id]
    assert response.adaptation_report.p1.dropped_excluded == []
    assert response.adaptation_report.p1.inert_incomplete == []
    assert response.adaptation_report.p2.deferred_attached_heroes == []


def test_create_battle_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)
    token = _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_CREATE_SCOPE: True},
    )

    creator = battles._battle_creator(
        request=_fake_request(method="POST", path="/battles", path_params={}),
        db=session,
        current_user=None,
    )
    response = battles.create_battle(
        battles.BattleCreate(p1_roster_id=roster_a.id, p2_roster_id=roster_b.id),
        db=session,
        creator=creator,
    )

    assert response.p1_user_id == owner.id
    assert response.p2_user_id == owner.id
    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/battles"
    payload = json.loads(audit.params_json)
    assert payload["scope"] == battles.BATTLE_CREATE_SCOPE
    assert payload["method"] == "POST"
    assert payload["path_params"] == {}
    assert RAW_TOKEN not in audit.params_json


def test_create_battle_rejects_missing_and_cross_owner_rosters() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    other = _seed_user(session, "other")
    own_roster = _seed_roster(session, name="own", owner_id=owner.id)
    other_roster = _seed_roster(session, name="other", owner_id=other.id)

    with pytest.raises(HTTPException) as cross_owner_info:
        battles.create_battle(
            battles.BattleCreate(
                p1_roster_id=own_roster.id,
                p2_roster_id=other_roster.id,
            ),
            db=session,
            creator=battles.BattleCreator(user_id=owner.id),
        )
    assert cross_owner_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.create_battle(
            battles.BattleCreate(p1_roster_id=own_roster.id, p2_roster_id=99999),
            db=session,
            creator=battles.BattleCreator(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404
    assert session.execute(select(models.Battle)).scalars().all() == []


def test_simulate_battle_returns_owner_scoped_summary_without_persisting_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)

    response = battles.simulate_battle(
        battles.BattleSimulate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            games=2,
            bot="random",
            seed=3,
            map_name="lustrzana_a",
        ),
        db=session,
        simulator=battles.BattleSimulator(user_id=owner.id),
    )

    assert response.p1_roster_id == roster_a.id
    assert response.p2_roster_id == roster_b.id
    assert response.bot == "random"
    assert response.map_name == "lustrzana_a"
    assert response.n_games == 2
    assert response.wins_p0 + response.wins_p1 + response.draws == 2
    assert response.total_rounds > 0
    assert response.win_rate_p0 + response.win_rate_p1 + response.draw_rate == pytest.approx(1.0)
    assert session.execute(select(models.Battle)).scalars().all() == []


def test_simulate_battle_matches_local_client_batch_methodology() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)
    seed = 11
    games = 3
    map_name = "lustrzana_a"

    response = battles.simulate_battle(
        battles.BattleSimulate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            games=games,
            bot="random",
            seed=seed,
            map_name=map_name,
        ),
        db=session,
        simulator=battles.BattleSimulator(user_id=owner.id),
    )
    map_fixture = battles.build_map(map_name, seed)
    summary = LocalClient(session=session, user_id=owner.id).simulate_roster_ids(
        roster_a.id,
        roster_b.id,
        lambda i: battles._simulation_players("random", seed, i),
        n=games,
        seed=seed,
        terrain=map_fixture.terrain,
        objectives=map_fixture.objectives,
        deployment_zones=battles.DEFAULT_DEPLOYMENT_ZONES,
    )

    assert response.n_games == summary.n_games
    assert response.wins_p0 == summary.wins_p0
    assert response.wins_p1 == summary.wins_p1
    assert response.draws == summary.draws
    assert response.total_rounds == summary.total_rounds
    assert response.win_rate_p0 == pytest.approx(summary.win_rate_p0)
    assert response.win_rate_p1 == pytest.approx(summary.win_rate_p1)
    assert response.draw_rate == pytest.approx(summary.draw_rate)
    assert response.avg_rounds == pytest.approx(summary.avg_rounds)


def test_simulate_battle_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)
    token = _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_SIMULATE_SCOPE: True},
    )

    simulator = battles._battle_simulator(
        request=_fake_request(method="POST", path="/battles/simulate", path_params={}),
        db=session,
        current_user=None,
    )
    response = battles.simulate_battle(
        battles.BattleSimulate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            games=1,
        ),
        db=session,
        simulator=simulator,
    )

    assert response.n_games == 1
    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/battles/simulate"
    payload = json.loads(audit.params_json)
    assert payload["scope"] == battles.BATTLE_SIMULATE_SCOPE
    assert payload["method"] == "POST"
    assert payload["path_params"] == {}
    assert RAW_TOKEN not in audit.params_json


def test_simulate_battle_rejects_cross_owner_and_missing_rosters() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    other = _seed_user(session, "other")
    own_roster = _seed_roster(session, name="own", owner_id=owner.id)
    other_roster = _seed_roster(session, name="other", owner_id=other.id)

    with pytest.raises(HTTPException) as cross_owner_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=own_roster.id,
                p2_roster_id=other_roster.id,
                games=1,
            ),
            db=session,
            simulator=battles.BattleSimulator(user_id=owner.id),
        )
    assert cross_owner_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=own_roster.id,
                p2_roster_id=99999,
                games=1,
            ),
            db=session,
            simulator=battles.BattleSimulator(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404
    assert session.execute(select(models.Battle)).scalars().all() == []


def test_simulate_battle_rejects_unknown_bot_and_map() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    roster_a = _seed_roster(session, name="A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="B", owner_id=owner.id)
    simulator = battles.BattleSimulator(user_id=owner.id)

    with pytest.raises(HTTPException) as map_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=roster_a.id,
                p2_roster_id=roster_b.id,
                games=1,
                map_name="nieistniejaca",
            ),
            db=session,
            simulator=simulator,
        )
    assert map_info.value.status_code == 400

    with pytest.raises(HTTPException) as map_precedence_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=roster_a.id,
                p2_roster_id=roster_b.id,
                games=1,
                bot="nieistniejacy",
                map_name="nieistniejaca",
            ),
            db=session,
            simulator=simulator,
        )
    assert map_precedence_info.value.status_code == 400
    assert map_precedence_info.value.detail == map_info.value.detail

    with pytest.raises(HTTPException) as bot_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=roster_a.id,
                p2_roster_id=roster_b.id,
                games=1,
                bot="nieistniejacy",
            ),
            db=session,
            simulator=simulator,
        )
    assert bot_info.value.status_code == 400

    with pytest.raises(HTTPException) as expensive_bot_info:
        battles.simulate_battle(
            battles.BattleSimulate(
                p1_roster_id=roster_a.id,
                p2_roster_id=roster_b.id,
                games=1,
                bot="minimax",
            ),
            db=session,
            simulator=simulator,
        )
    assert expensive_bot_info.value.status_code == 400


def test_get_battle_returns_owner_scoped_metadata_with_latest_sequence() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    battle = _seed_battle(session, p1=owner, p2=opponent)
    battle.current_round = 3
    battle.rng_seed = 777
    battle.status = "active"
    session.commit()
    session.refresh(battle)
    _seed_events(session, battle)

    response = battles.get_battle(
        battle.id,
        db=session,
        reader=battles.BattleReader(user_id=owner.id),
    )

    assert response.battle_id == battle.id
    assert response.p1_user_id == owner.id
    assert response.p2_user_id == opponent.id
    assert response.p1_roster_id is None
    assert response.p2_roster_id is None
    assert response.winner_user_id is None
    assert response.current_round == 3
    assert response.rng_seed == 777
    assert response.status == "active"
    assert response.latest_sequence == 2


def test_get_battle_reports_zero_latest_sequence_for_empty_log() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    battle = _seed_battle(session, p1=owner, p2=opponent)

    response = battles.get_battle(
        battle.id,
        db=session,
        reader=battles.BattleReader(user_id=opponent.id),
    )

    assert response.latest_sequence == 0


def test_get_battle_rejects_non_participant_and_missing_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    stranger = _seed_user(session, "stranger")
    battle = _seed_battle(session, p1=owner, p2=opponent)

    with pytest.raises(HTTPException) as stranger_info:
        battles.get_battle(
            battle.id,
            db=session,
            reader=battles.BattleReader(user_id=stranger.id),
        )
    assert stranger_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.get_battle(
            battle.id + 999,
            db=session,
            reader=battles.BattleReader(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404


def test_get_battle_events_returns_owner_scoped_event_log_with_since_filter() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    battle = _seed_battle(session, p1=owner, p2=opponent)
    _seed_events(session, battle)

    response = battles.get_battle_events(
        battle.id,
        request=_fake_request(token=None, battle_id=battle.id),
        since=1,
        db=session,
        reader=battles.BattleReader(user_id=owner.id),
    )

    assert response.battle_id == battle.id
    assert [event.sequence for event in response.events] == [2]
    assert response.events[0].event_type == "StatusAdded"
    assert response.events[0].payload["status"] == "Aktywowany"


def test_get_battle_events_rejects_non_participant_and_missing_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    opponent = _seed_user(session, "opponent")
    stranger = _seed_user(session, "stranger")
    battle = _seed_battle(session, p1=owner, p2=opponent)

    with pytest.raises(HTTPException) as stranger_info:
        battles.get_battle_events(
            battle.id,
            request=_fake_request(token=None, battle_id=battle.id),
            db=session,
            reader=battles.BattleReader(user_id=stranger.id),
        )
    assert stranger_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.get_battle_events(
            battle.id + 999,
            request=_fake_request(token=None, battle_id=battle.id + 999),
            db=session,
            reader=battles.BattleReader(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404


def test_get_battle_state_returns_versioned_checkpoint_without_rng() -> None:
    session = _build_session()
    owner = _seed_user(session, "state-owner")
    roster_a = _seed_roster(session, name="State A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="State B", owner_id=owner.id)
    created = battles.create_battle(
        battles.BattleCreate(
            p1_roster_id=roster_a.id,
            p2_roster_id=roster_b.id,
            rng_seed=4321,
        ),
        db=session,
        creator=battles.BattleCreator(user_id=owner.id),
    )

    response = battles.get_battle_state(
        created.battle_id,
        db=session,
        reader=battles.BattleReader(user_id=owner.id),
    )
    restored = battle_state_from_json(
        {
            "schema": response.checkpoint_schema,
            "version": response.version,
            "state": response.state,
        }
    )

    assert response.battle_id == created.battle_id
    assert response.sequence_at == created.latest_sequence
    assert restored.round == 1
    assert restored == load_latest_checkpoint(session, created.battle_id).state
    public_json = json.dumps(response.model_dump(by_alias=True))
    assert "rng_json" not in public_json
    assert "random_state" not in public_json


def test_get_battle_state_rejects_non_participant_and_missing_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "state-owner-scope")
    opponent = _seed_user(session, "state-opponent-scope")
    stranger = _seed_user(session, "state-stranger-scope")
    battle = _seed_battle(session, p1=owner, p2=opponent)

    with pytest.raises(HTTPException) as stranger_info:
        battles.get_battle_state(
            battle.id,
            db=session,
            reader=battles.BattleReader(user_id=stranger.id),
        )
    assert stranger_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        battles.get_battle_state(
            battle.id + 999,
            db=session,
            reader=battles.BattleReader(user_id=owner.id),
        )
    assert missing_info.value.status_code == 404


def test_get_battle_state_reports_conflict_for_participant_without_checkpoint() -> None:
    session = _build_session()
    owner = _seed_user(session, "state-owner-no-checkpoint")
    battle = _seed_battle(session, p1=owner, p2=owner)

    with pytest.raises(HTTPException) as exc_info:
        battles.get_battle_state(
            battle.id,
            db=session,
            reader=battles.BattleReader(user_id=owner.id),
        )

    assert exc_info.value.status_code == 409


def test_get_battle_state_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "state-agent-owner")
    roster_a = _seed_roster(session, name="Agent State A", owner_id=owner.id)
    roster_b = _seed_roster(session, name="Agent State B", owner_id=owner.id)
    created = battles.create_battle(
        battles.BattleCreate(p1_roster_id=roster_a.id, p2_roster_id=roster_b.id),
        db=session,
        creator=battles.BattleCreator(user_id=owner.id),
    )
    token = _seed_agent_token(session, owner=owner)
    reader = battles._battle_reader(
        request=_fake_request(
            battle_id=created.battle_id,
            path=f"/battles/{created.battle_id}/state",
        ),
        db=session,
        current_user=None,
    )

    response = battles.get_battle_state(created.battle_id, db=session, reader=reader)

    assert response.battle_id == created.battle_id
    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == f"/battles/{created.battle_id}/state"
    assert json.loads(audit.params_json)["scope"] == battles.BATTLE_READ_SCOPE
    assert RAW_TOKEN not in audit.params_json


def test_battle_reader_accepts_session_user_without_agent_audit() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    reader = battles._battle_reader(
        request=_fake_request(token=None),
        db=session,
        current_user=owner,
    )

    assert reader == battles.BattleReader(user_id=owner.id)
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_battle_reader_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    token = _seed_agent_token(session, owner=owner)

    reader = battles._battle_reader(
        request=_fake_request(query_params={"since": "1", "token": "leaked"}),
        db=session,
        current_user=None,
    )

    assert reader == battles.BattleReader(user_id=owner.id)

    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/battles/7/events"
    payload = json.loads(audit.params_json)
    assert payload["scope"] == battles.BATTLE_READ_SCOPE
    assert payload["path_params"] == {"battle_id": "7"}
    assert payload["query_params"] == {"since": "1", "token": "[REDACTED]"}
    assert RAW_TOKEN not in audit.params_json


def test_battle_reader_rejects_missing_auth_and_missing_scope() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    with pytest.raises(HTTPException) as missing_info:
        battles._battle_reader(
            request=_fake_request(token=None),
            db=session,
            current_user=None,
        )
    assert missing_info.value.status_code == 401

    _seed_agent_token(
        session,
        owner=owner,
        scopes={"battle:write": True},
    )
    with pytest.raises(HTTPException) as scope_info:
        battles._battle_reader(
            request=_fake_request(),
            db=session,
            current_user=None,
        )
    assert scope_info.value.status_code == 403
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_battle_creator_rejects_missing_auth_and_missing_scope() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    with pytest.raises(HTTPException) as missing_info:
        battles._battle_creator(
            request=_fake_request(token=None, method="POST", path="/battles"),
            db=session,
            current_user=None,
        )
    assert missing_info.value.status_code == 401

    _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_READ_SCOPE: True},
    )
    with pytest.raises(HTTPException) as scope_info:
        battles._battle_creator(
            request=_fake_request(method="POST", path="/battles"),
            db=session,
            current_user=None,
        )
    assert scope_info.value.status_code == 403
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_battle_simulator_rejects_missing_auth_and_missing_scope() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")

    with pytest.raises(HTTPException) as missing_info:
        battles._battle_simulator(
            request=_fake_request(token=None, method="POST", path="/battles/simulate"),
            db=session,
            current_user=None,
        )
    assert missing_info.value.status_code == 401

    _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_READ_SCOPE: True},
    )
    with pytest.raises(HTTPException) as scope_info:
        battles._battle_simulator(
            request=_fake_request(method="POST", path="/battles/simulate"),
            db=session,
            current_user=None,
        )
    assert scope_info.value.status_code == 403
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_agent_reader_cannot_read_battle_owned_by_other_user() -> None:
    session = _build_session()
    owner = _seed_user(session, "owner")
    other = _seed_user(session, "other")
    opponent = _seed_user(session, "opponent")
    _seed_agent_token(session, owner=owner)
    battle = _seed_battle(session, p1=other, p2=opponent)
    _seed_events(session, battle)

    reader = battles._battle_reader(
        request=_fake_request(battle_id=battle.id),
        db=session,
        current_user=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        battles.get_battle_events(
            battle.id,
            request=_fake_request(token=None, battle_id=battle.id),
            db=session,
            reader=reader,
        )

    assert exc_info.value.status_code == 404


def test_take_battle_action_persists_contiguous_delta_checkpoint_and_metadata() -> None:
    session = _build_session()
    owner = _seed_user(session, "action-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)

    response = battles.take_battle_action(
        battle.id,
        battles.BattleActionCreate(
            expected_sequence=0,
            action=action_to_json(DefendAction(unit_id=1)),
        ),
        db=session,
        actor=battles.BattleActor(user_id=owner.id),
    )

    after = _action_db_snapshot(session, battle.id)
    restored = battle_state_from_json(response.state.model_dump(by_alias=True))
    persisted = load_events(session, battle.id)
    assert response.previous_sequence == 0
    assert response.new_sequence == len(response.events)
    assert [event.sequence for event in response.events] == list(
        range(1, response.new_sequence + 1)
    )
    assert tuple(json_to_event(event.payload) for event in response.events) == tuple(
        persisted
    )
    assert restored == load_latest_checkpoint(session, battle.id).state
    assert after[0] == before[0] + len(response.events)
    assert after[1] == before[1] + 1
    assert after[2:5] == (1, "active", None)
    assert after[5] == response.new_sequence


def test_take_battle_action_stale_sequence_does_not_mutate_db() -> None:
    session = _build_session()
    owner = _seed_user(session, "stale-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=1,
                action=action_to_json(DefendAction(unit_id=1)),
            ),
            db=session,
            actor=battles.BattleActor(user_id=owner.id),
        )

    assert exc_info.value.status_code == 409
    assert _action_db_snapshot(session, battle.id) == before


def test_take_battle_action_invalid_wire_is_safe_422_without_mutation() -> None:
    session = _build_session()
    owner = _seed_user(session, "invalid-wire-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)
    invalid_wire = action_to_json(DefendAction(unit_id=1))
    invalid_wire["unexpected"] = "field"

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=invalid_wire,
            ),
            db=session,
            actor=battles.BattleActor(user_id=owner.id),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid action payload"
    assert _action_db_snapshot(session, battle.id) == before


def test_battle_action_request_rejects_bool_expected_sequence() -> None:
    with pytest.raises(ValueError):
        battles.BattleActionCreate(
            expected_sequence=True,
            action=action_to_json(DefendAction(unit_id=1)),
        )


def test_take_battle_action_race_rolls_back_flushed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_session()
    owner = _seed_user(session, "race-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)

    def fail_checkpoint(*_args, **_kwargs):
        raise IntegrityError("checkpoint race", {}, Exception("unique"))

    monkeypatch.setattr(battle_action_service, "save_checkpoint", fail_checkpoint)

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=action_to_json(DefendAction(unit_id=1)),
            ),
            db=session,
            actor=battles.BattleActor(user_id=owner.id),
        )

    assert exc_info.value.status_code == 409
    assert _action_db_snapshot(session, battle.id) == before


def test_take_battle_action_illegal_action_does_not_mutate_db() -> None:
    session = _build_session()
    owner = _seed_user(session, "illegal-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=action_to_json(
                    ManeuverAction(unit_id=1, target_position=Position(100, 100))
                ),
            ),
            db=session,
            actor=battles.BattleActor(user_id=owner.id),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Illegal action"
    assert _action_db_snapshot(session, battle.id) == before


def test_take_battle_action_invalid_target_is_safe_422_without_mutation() -> None:
    session = _build_session()
    owner = _seed_user(session, "invalid-target-owner")
    state = _action_state()
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=state,
    )
    before = _action_db_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=action_to_json(
                    ShootAction(
                        unit_id=1,
                        target_id=999,
                        weapon=state.blobs[0].ranged_weapons[0],
                    )
                ),
            ),
            db=session,
            actor=battles.BattleActor(user_id=owner.id),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Illegal action"
    assert _action_db_snapshot(session, battle.id) == before


def test_take_battle_action_rejects_other_side_without_mutation() -> None:
    session = _build_session()
    p1 = _seed_user(session, "side-p1")
    p2 = _seed_user(session, "side-p2")
    battle = _persist_action_battle(
        session,
        p1=p1,
        p2=p2,
        state=_action_state(),
    )
    before = _action_db_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as exc_info:
        battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=action_to_json(DefendAction(unit_id=2)),
            ),
            db=session,
            actor=battles.BattleActor(user_id=p1.id),
        )

    assert exc_info.value.status_code == 403
    assert _action_db_snapshot(session, battle.id) == before


def test_take_battle_action_same_user_can_control_both_sandbox_sides() -> None:
    session = _build_session()
    owner = _seed_user(session, "both-sides-owner")
    battle = _persist_action_battle(
        session,
        p1=owner,
        p2=owner,
        state=_action_state(),
    )
    first = battles.take_battle_action(
        battle.id,
        battles.BattleActionCreate(
            expected_sequence=0,
            action=action_to_json(DefendAction(unit_id=1)),
        ),
        db=session,
        actor=battles.BattleActor(user_id=owner.id),
    )

    second = battles.take_battle_action(
        battle.id,
        battles.BattleActionCreate(
            expected_sequence=first.new_sequence,
            action=action_to_json(DefendAction(unit_id=2)),
        ),
        db=session,
        actor=battles.BattleActor(user_id=owner.id),
    )

    assert second.new_sequence > first.new_sequence
    assert any(event.event_type == "RoundEnded" for event in second.events)
    assert battle_state_from_json(second.state.model_dump(by_alias=True)).round == 2


def test_take_battle_action_nonparticipant_and_missing_are_same_404() -> None:
    session = _build_session()
    p1 = _seed_user(session, "oracle-p1")
    p2 = _seed_user(session, "oracle-p2")
    stranger = _seed_user(session, "oracle-stranger")
    battle = _persist_action_battle(
        session,
        p1=p1,
        p2=p2,
        state=_action_state(),
    )
    payload = battles.BattleActionCreate(
        expected_sequence=0,
        action=action_to_json(DefendAction(unit_id=1)),
    )

    for battle_id in (battle.id, battle.id + 999):
        with pytest.raises(HTTPException) as exc_info:
            battles.take_battle_action(
                battle_id,
                payload,
                db=session,
                actor=battles.BattleActor(user_id=stranger.id),
            )
        assert exc_info.value.status_code == 404


def test_take_battle_action_automatically_ends_round_and_updates_winner() -> None:
    session = _build_session()
    p1 = _seed_user(session, "winner-p1")
    p2 = _seed_user(session, "winner-p2")
    state = _action_state(objectives=(Objective(id=1, position=Position(0, 0)),))
    state = replace(
        state,
        round=4,
        blobs=(state.blobs[0], replace(state.blobs[1], models_alive=0)),
    )
    battle = _persist_action_battle(session, p1=p1, p2=p2, state=state)

    response = battles.take_battle_action(
        battle.id,
        battles.BattleActionCreate(
            expected_sequence=0,
            action=action_to_json(DefendAction(unit_id=1)),
        ),
        db=session,
        actor=battles.BattleActor(user_id=p1.id),
    )

    final_state = battle_state_from_json(response.state.model_dump(by_alias=True))
    session.refresh(battle)
    assert any(event.event_type == "RoundEnded" for event in response.events)
    assert final_state.is_game_over is True
    assert final_state.score == (1, 0)
    assert battle.current_round == 4
    assert battle.status == "finished"
    assert battle.winner_user_id == p1.id


def test_take_battle_action_reopened_session_preserves_next_rng_action(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'http-action-rng.db'}",
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    seed = 314159
    initial_state = _action_state()
    reference_dice = DeterministicDice(seed)

    with SessionLocal() as writer:
        p1 = _seed_user(writer, "rng-p1")
        p2 = _seed_user(writer, "rng-p2")
        battle = _persist_action_battle(
            writer,
            p1=p1,
            p2=p2,
            state=initial_state,
            seed=seed,
        )
        battle_id = battle.id
        p1_id = p1.id
        p2_id = p2.id
        first_action = ShootAction(
            unit_id=1,
            target_id=2,
            weapon=initial_state.blobs[0].ranged_weapons[0],
        )
        reference_first = apply(initial_state, first_action, reference_dice, sequence=1)
        first_response = battles.take_battle_action(
            battle.id,
            battles.BattleActionCreate(
                expected_sequence=0,
                action=action_to_json(first_action),
            ),
            db=writer,
            actor=battles.BattleActor(user_id=p1.id),
        )
        assert battle_state_from_json(
            first_response.state.model_dump(by_alias=True)
        ) == reference_first.state

    with SessionLocal() as reader:
        checkpoint = load_latest_checkpoint(reader, battle_id)
        assert checkpoint is not None
        second_action = ShootAction(
            unit_id=2,
            target_id=1,
            weapon=checkpoint.state.blobs[1].ranged_weapons[0],
        )
        reference_second = apply(
            reference_first.state,
            second_action,
            reference_dice,
            sequence=reference_first.next_sequence,
        )
        reference_state = reference_second.state
        reference_events = list(reference_second.events)
        if should_end_round(reference_state):
            reference_state, round_events = round_end_phase(
                reference_state,
                sequence=reference_second.next_sequence,
            )
            reference_events.extend(round_events)

        second_response = battles.take_battle_action(
            battle_id,
            battles.BattleActionCreate(
                expected_sequence=checkpoint.sequence_at,
                action=action_to_json(second_action),
            ),
            db=reader,
            actor=battles.BattleActor(user_id=p2_id),
        )

        assert battle_state_from_json(
            second_response.state.model_dump(by_alias=True)
        ) == reference_state
        assert tuple(
            json_to_event(event.payload) for event in second_response.events
        ) == tuple(reference_events)
        checkpoint_count = len(
            reader.execute(
                select(models.BattleCheckpoint).where(
                    models.BattleCheckpoint.battle_id == battle_id
                )
            ).scalars().all()
        )
        assert checkpoint_count == 3
        assert reader.get(models.Battle, battle_id).p1_user_id == p1_id


def test_battle_actor_accepts_session_user_without_agent_audit() -> None:
    session = _build_session()
    owner = _seed_user(session, "actor-session-owner")

    actor = battles._battle_actor(
        request=_fake_request(
            token=None,
            method="POST",
            path="/battles/7/actions",
        ),
        db=session,
        current_user=owner,
    )

    assert actor == battles.BattleActor(user_id=owner.id)
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None


def test_battle_actor_accepts_agent_scope_and_audits_request() -> None:
    session = _build_session()
    owner = _seed_user(session, "actor-agent-owner")
    token = _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_ACT_SCOPE: True},
    )

    actor = battles._battle_actor(
        request=_fake_request(
            method="POST",
            path="/battles/7/actions",
        ),
        db=session,
        current_user=None,
    )

    assert actor == battles.BattleActor(user_id=owner.id)
    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == token.agent_user_id
    assert audit.route == "/battles/7/actions"
    assert json.loads(audit.params_json)["scope"] == battles.BATTLE_ACT_SCOPE
    assert RAW_TOKEN not in audit.params_json


def test_battle_actor_rejects_missing_auth_and_missing_scope() -> None:
    session = _build_session()
    owner = _seed_user(session, "actor-scope-owner")

    with pytest.raises(HTTPException) as missing_info:
        battles._battle_actor(
            request=_fake_request(
                token=None,
                method="POST",
                path="/battles/7/actions",
            ),
            db=session,
            current_user=None,
        )
    assert missing_info.value.status_code == 401

    _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_READ_SCOPE: True},
    )
    with pytest.raises(HTTPException) as scope_info:
        battles._battle_actor(
            request=_fake_request(method="POST", path="/battles/7/actions"),
            db=session,
            current_user=None,
        )
    assert scope_info.value.status_code == 403


@pytest.mark.parametrize("invalid_token", ["expired", "revoked"])
def test_battle_actor_rejects_expired_and_revoked_tokens(invalid_token: str) -> None:
    session = _build_session()
    owner = _seed_user(session, f"actor-{invalid_token}-owner")
    token = _seed_agent_token(
        session,
        owner=owner,
        scopes={battles.BATTLE_ACT_SCOPE: True},
    )
    if invalid_token == "expired":
        token.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    else:
        token.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        battles._battle_actor(
            request=_fake_request(method="POST", path="/battles/7/actions"),
            db=session,
            current_user=None,
        )

    assert exc_info.value.status_code == 401
    assert session.execute(select(models.AgentAuditLog)).scalar_one_or_none() is None
