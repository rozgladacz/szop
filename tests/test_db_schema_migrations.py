from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, models
from app.db import Base


def _memory_engine():
    return create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_unit_base_geometry_defaults_on_fresh_schema():
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session() as session:
        user = models.User(username="base-defaults", password_hash="x")
        agent = models.User(
            username="agent-defaults",
            password_hash="x",
            role=models.USER_ROLE_AGENT,
        )
        ruleset = models.RuleSet(name="Rules")
        armory = models.Armory(name="Armory", owner=user)
        army = models.Army(name="Army", owner=user, ruleset=ruleset, armory=armory)
        unit = models.Unit(
            army=army,
            name="Piechota",
            quality=4,
            defense=5,
            toughness=3,
        )
        token = models.AgentToken(
            agent_user=agent,
            owner_user=user,
            token_hash="sha256:test-token",
            scope_json='{"battle:read": true}',
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        audit = models.AgentAuditLog(
            user=user,
            agent_user=agent,
            route="/api/battles",
            params_json='{"battle_id": 1}',
        )
        proposal = models.AgentProposal(
            owner_user=user,
            agent_user=agent,
            token=token,
            action="battle:action",
            summary="Obrona oddziału",
            payload_json="{}",
        )
        session.add_all(
            [user, agent, ruleset, armory, army, unit, token, audit, proposal]
        )
        session.commit()
        session.refresh(unit)
        session.refresh(user)
        session.refresh(token)
        session.refresh(audit)
        session.refresh(proposal)

        assert user.role == models.USER_ROLE_USER
        assert unit.base_size_mm == 25
        assert unit.base_shape == "round"
        assert token.agent_user_id == agent.id
        assert token.owner_user_id == user.id
        assert token.revoked_at is None
        assert token.last_used_at is None
        assert audit.user_id == user.id
        assert audit.agent_user_id == agent.id
        assert audit.timestamp is not None
        assert proposal.result_json is None

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert {"agent_tokens", "agent_audit_logs"}.issubset(table_names)
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["role"]["nullable"] is False
    token_columns = {
        column["name"]: column for column in inspector.get_columns("agent_tokens")
    }
    assert token_columns["token_hash"]["nullable"] is False
    assert token_columns["expires_at"]["nullable"] is False
    audit_columns = {
        column["name"]: column for column in inspector.get_columns("agent_audit_logs")
    }
    assert audit_columns["route"]["nullable"] is False
    proposal_columns = {
        column["name"]: column for column in inspector.get_columns("agent_proposals")
    }
    assert proposal_columns["result_json"]["nullable"] is True


def test_battle_activation_protocol_version_fresh_schema_is_strict_v1_default():
    engine = _memory_engine()
    Base.metadata.create_all(engine)

    with pytest.raises(ValueError, match="activation_protocol_version"):
        models.Battle(activation_protocol_version=True)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("battles")
    }
    protocol_column = columns["activation_protocol_version"]
    assert protocol_column["nullable"] is False
    assert str(protocol_column["default"]).strip("'\"()") == "1"
    checks = inspect(engine).get_check_constraints("battles")
    assert any(
        "activation_protocol_version IN (1, 2)" in check["sqltext"]
        for check in checks
    )

    timestamp = "2026-07-28 10:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO battles (
                    current_round, rng_seed, status, created_at, updated_at
                ) VALUES (0, 7, 'active', :timestamp, :timestamp)
                """
            ),
            {"timestamp": timestamp},
        )
        assert connection.execute(
            text("SELECT activation_protocol_version FROM battles")
        ).scalar_one() == 1

    for invalid_version in (0, 3):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO battles (
                            current_round, rng_seed, status,
                            activation_protocol_version, created_at, updated_at
                        ) VALUES (
                            0, 7, 'active', :version, :timestamp, :timestamp
                        )
                        """
                    ),
                    {"version": invalid_version, "timestamp": timestamp},
                )


def test_migrate_schema_marks_legacy_battles_v1_once_without_rewriting_logs(
    monkeypatch,
):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE battles (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(20) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO battles (id, status) VALUES (7, 'active')")
        )
        connection.execute(
            text(
                """
                CREATE TABLE battle_events (
                    id INTEGER PRIMARY KEY,
                    battle_id INTEGER NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO battle_events (
                    id, battle_id, sequence, payload_json
                ) VALUES (11, 7, 1, '{"event_type":"legacy"}')
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE battle_checkpoints (
                    id INTEGER PRIMARY KEY,
                    battle_id INTEGER NOT NULL,
                    sequence_at INTEGER NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO battle_checkpoints (
                    id, battle_id, sequence_at, state_json
                ) VALUES (
                    13, 7, 1, :state_json
                )
                """
            ),
            {
                "state_json": (
                    '{"schema":"szop.battle_state","version":1,"state":{}}'
                )
            },
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()

    with engine.connect() as connection:
        first_snapshot = {
            "battle": connection.execute(
                text(
                    "SELECT id, status, activation_protocol_version "
                    "FROM battles"
                )
            ).mappings().all(),
            "event": connection.execute(
                text(
                    "SELECT id, battle_id, sequence, payload_json "
                    "FROM battle_events"
                )
            ).mappings().all(),
            "checkpoint": connection.execute(
                text(
                    "SELECT id, battle_id, sequence_at, state_json "
                    "FROM battle_checkpoints"
                )
            ).mappings().all(),
        }

    db._migrate_schema()

    with engine.connect() as connection:
        second_snapshot = {
            "battle": connection.execute(
                text(
                    "SELECT id, status, activation_protocol_version "
                    "FROM battles"
                )
            ).mappings().all(),
            "event": connection.execute(
                text(
                    "SELECT id, battle_id, sequence, payload_json "
                    "FROM battle_events"
                )
            ).mappings().all(),
            "checkpoint": connection.execute(
                text(
                    "SELECT id, battle_id, sequence_at, state_json "
                    "FROM battle_checkpoints"
                )
            ).mappings().all(),
        }

    assert first_snapshot == second_snapshot
    assert first_snapshot["battle"] == [
        {"id": 7, "status": "active", "activation_protocol_version": 1}
    ]
    assert first_snapshot["event"][0]["payload_json"] == '{"event_type":"legacy"}'
    assert '"version":1' in first_snapshot["checkpoint"][0]["state_json"]

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE battles SET activation_protocol_version = 3 "
                    "WHERE id = 7"
                )
            )


def test_migrate_schema_adds_unit_base_geometry_columns(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE armories (id INTEGER PRIMARY KEY, owner_id INTEGER)"))
        connection.execute(text("INSERT INTO armories (id, owner_id) VALUES (1, NULL)"))
        connection.execute(
            text(
                """
                CREATE TABLE units (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    quality INTEGER NOT NULL,
                    defense INTEGER NOT NULL,
                    toughness INTEGER NOT NULL,
                    flags TEXT,
                    default_weapon_id INTEGER,
                    parent_id INTEGER,
                    army_id INTEGER NOT NULL,
                    owner_id INTEGER,
                    position INTEGER NOT NULL DEFAULT 0,
                    typical_models INTEGER NOT NULL DEFAULT 1,
                    group_id INTEGER
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO units (
                    id, name, quality, defense, toughness, army_id, position,
                    typical_models, group_id
                )
                VALUES (1, 'Stara piechota', 4, 5, 3, 10, 2, 6, NULL)
                """
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()

    columns = {column["name"]: column for column in inspect(engine).get_columns("units")}
    assert columns["base_size_mm"]["nullable"] is False
    assert columns["base_shape"]["nullable"] is False

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT base_size_mm, base_shape FROM units WHERE id = 1")
        ).mappings().one()

    assert row["base_size_mm"] == 25
    assert row["base_shape"] == "round"


def test_migrate_schema_adds_user_role_column(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE armories (id INTEGER PRIMARY KEY, owner_id INTEGER)"))
        connection.execute(text("INSERT INTO armories (id, owner_id) VALUES (1, NULL)"))
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO users (id, username, password_hash, is_admin)
                VALUES
                    (1, 'admin', 'x', 1),
                    (2, 'regular', 'x', 0)
                """
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()

    columns = {column["name"]: column for column in inspect(engine).get_columns("users")}
    assert columns["role"]["nullable"] is False

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT username, role FROM users ORDER BY id")
        ).mappings().all()

    assert rows == [
        {"username": "admin", "role": models.USER_ROLE_ADMIN},
        {"username": "regular", "role": models.USER_ROLE_USER},
    ]


def test_migrate_schema_adds_agent_proposal_result_column(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE armories (id INTEGER PRIMARY KEY, owner_id INTEGER)")
        )
        connection.execute(text("INSERT INTO armories (id, owner_id) VALUES (1, NULL)"))
        connection.execute(
            text(
                """
                CREATE TABLE agent_proposals (
                    id INTEGER PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    agent_user_id INTEGER NOT NULL,
                    token_id INTEGER,
                    action VARCHAR(120) NOT NULL,
                    summary VARCHAR(500) NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    decided_at DATETIME,
                    decided_by_user_id INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("agent_proposals")
    }
    assert columns["result_json"]["nullable"] is True


def test_create_all_adds_battle_invites_to_legacy_schema_idempotently():
    engine = _memory_engine()
    legacy_metadata = MetaData()
    for table in Base.metadata.tables.values():
        if table.name != "battle_invites":
            table.to_metadata(legacy_metadata)
    legacy_metadata.create_all(engine)

    existing_at = "2026-07-19 08:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    username, password_hash, is_admin, role, created_at, updated_at
                ) VALUES (
                    :username, :password_hash, 0, :role, :created_at, :updated_at
                )
                """
            ),
            {
                "username": "legacy-user",
                "password_hash": "x",
                "role": models.USER_ROLE_USER,
                "created_at": existing_at,
                "updated_at": existing_at,
            },
        )

    assert "battle_invites" not in inspect(engine).get_table_names()
    Base.metadata.create_all(engine)
    assert "battle_invites" in inspect(engine).get_table_names()
    Base.metadata.create_all(engine)

    with engine.connect() as connection:
        existing_user = connection.execute(
            text(
                "SELECT username, password_hash, role FROM users "
                "WHERE username = 'legacy-user'"
            )
        ).mappings().one()
        invite_count = connection.execute(
            text("SELECT COUNT(*) FROM battle_invites")
        ).scalar_one()

    assert existing_user == {
        "username": "legacy-user",
        "password_hash": "x",
        "role": models.USER_ROLE_USER,
    }
    assert invite_count == 0
