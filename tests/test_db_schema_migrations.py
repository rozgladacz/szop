from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import MetaData, create_engine, event, inspect, text
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
        "activation_protocol_version IN (1, 2, 3)" in check["sqltext"]
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

    for invalid_version in (0, 4):
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

    with engine.begin() as connection:
        connection.execute(text("UPDATE battles SET activation_protocol_version = 3 WHERE id = 7"))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("UPDATE battles SET activation_protocol_version = 4 WHERE id = 7"))


def test_migrate_schema_marks_legacy_invites_v1_idempotently(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE battle_invites (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(20) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO battle_invites (id, status) "
                "VALUES (9, 'pending')"
            )
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    db._migrate_schema()
    db._migrate_schema()

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("battle_invites")
    }
    protocol_column = columns["activation_protocol_version"]
    assert protocol_column["nullable"] is False
    assert str(protocol_column["default"]).strip("'\"()") == "1"
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT activation_protocol_version "
                "FROM battle_invites WHERE id = 9"
            )
        ).scalar_one() == 1

    with engine.begin() as connection:
        connection.execute(text("UPDATE battle_invites SET activation_protocol_version = 3 WHERE id = 9"))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("UPDATE battle_invites SET activation_protocol_version = 4 WHERE id = 9"))


def test_migrate_existing_v2_checks_preserves_related_rows_and_indexes(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for statement in (
            "CREATE TABLE users (id INTEGER PRIMARY KEY)",
            "CREATE TABLE battles (id INTEGER PRIMARY KEY, p1_user_id INTEGER REFERENCES users(id), "
            "activation_protocol_version INTEGER NOT NULL CHECK (activation_protocol_version IN (1, 2)))",
            "CREATE TABLE battle_events (id INTEGER PRIMARY KEY, battle_id INTEGER NOT NULL "
            "REFERENCES battles(id), sequence INTEGER NOT NULL, payload_json TEXT NOT NULL)",
            "CREATE TABLE battle_checkpoints (id INTEGER PRIMARY KEY, battle_id INTEGER NOT NULL "
            "REFERENCES battles(id), sequence_at INTEGER NOT NULL, state_json TEXT NOT NULL)",
            "CREATE TABLE battle_invites (id INTEGER PRIMARY KEY, battle_id INTEGER REFERENCES battles(id), "
            "activation_protocol_version INTEGER NOT NULL CHECK (activation_protocol_version IN (1, 2)))",
            "CREATE INDEX ix_battle_events_head ON battle_events (battle_id, sequence)",
            "CREATE INDEX ix_battle_invites_result ON battle_invites (battle_id)",
            "INSERT INTO users VALUES (1)",
            "INSERT INTO battles VALUES (10, 1, 1), (20, 1, 2)",
            "INSERT INTO battle_events VALUES (101, 10, 1, '{\"event_type\":\"old\"}')",
            "INSERT INTO battle_checkpoints VALUES (201, 20, 2, '{\"version\":2}')",
            "INSERT INTO battle_invites VALUES (301, 20, 2)",
        ):
            connection.exec_driver_sql(statement)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    with engine.connect() as connection:
        before = {
            table: connection.exec_driver_sql(f"SELECT * FROM {table}").fetchall()
            for table in ("battles", "battle_events", "battle_checkpoints", "battle_invites")
        }
    db._migrate_schema()
    db._migrate_schema()
    with engine.connect() as connection:
        after = {
            table: connection.exec_driver_sql(f"SELECT * FROM {table}").fetchall()
            for table in before
        }
        assert after == before
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        indexes = {
            row.name for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert {"ix_battle_events_head", "ix_battle_invites_result"} <= indexes
        connection.exec_driver_sql("UPDATE battles SET activation_protocol_version = 3 WHERE id = 10")
        connection.exec_driver_sql("UPDATE battle_invites SET activation_protocol_version = 3 WHERE id = 301")
        connection.commit()
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE battles SET activation_protocol_version = 4 WHERE id = 10")


def test_migrate_v2_checks_preserves_preexisting_unrelated_fk_violations(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE battles (id INTEGER PRIMARY KEY, "
            "activation_protocol_version INTEGER NOT NULL "
            "CHECK (activation_protocol_version IN (1, 2)))"
        )
        connection.exec_driver_sql("INSERT INTO battles VALUES (1, 2)")
        connection.exec_driver_sql(
            "CREATE TABLE unrelated_parent (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE unrelated_child (id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES unrelated_parent(id))"
        )
        connection.exec_driver_sql("INSERT INTO unrelated_child VALUES (4, 999)")
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    with engine.connect() as connection:
        before = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    assert len(before) == 1

    db._migrate_schema()

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == before
        assert connection.exec_driver_sql(
            "SELECT activation_protocol_version FROM battles WHERE id = 1"
        ).scalar_one() == 2


@pytest.mark.parametrize(
    "failure_prefix",
    (
        'INSERT INTO "__c2c_battles_new"',
        'DROP TABLE "battles"',
        'INSERT INTO "__c2c_battle_invites_new"',
        "CREATE INDEX ix_invite_battle",
    ),
)
def test_protocol_check_migration_rolls_back_ddl_and_allows_retry(
    monkeypatch, failure_prefix,
):
    engine = _memory_engine()
    tables = ("battles", "battle_invites", "battle_events")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for statement in (
            "CREATE TABLE battles (id INTEGER PRIMARY KEY, "
            "activation_protocol_version INTEGER NOT NULL "
            "CHECK (activation_protocol_version IN (1, 2)))",
            "CREATE TABLE battle_invites (id INTEGER PRIMARY KEY, "
            "battle_id INTEGER REFERENCES battles(id), "
            "activation_protocol_version INTEGER NOT NULL "
            "CHECK (activation_protocol_version IN (1, 2)))",
            "CREATE TABLE battle_events (id INTEGER PRIMARY KEY, "
            "battle_id INTEGER REFERENCES battles(id))",
            "CREATE INDEX ix_invite_battle ON battle_invites (battle_id)",
            "CREATE TRIGGER tr_invite_update AFTER UPDATE ON battle_invites "
            "BEGIN SELECT 1; END",
            "INSERT INTO battles VALUES (1, 2)",
            "INSERT INTO battle_invites VALUES (2, 1, 2)",
            "INSERT INTO battle_events VALUES (3, 1)",
        ):
            connection.exec_driver_sql(statement)
    monkeypatch.setattr(db, "engine", engine)

    def snapshot():
        with engine.connect() as connection:
            return {
                "schema": connection.exec_driver_sql(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "ORDER BY type, name"
                ).fetchall(),
                "rows": {
                    table: connection.exec_driver_sql(
                        f"SELECT * FROM {table} ORDER BY id"
                    ).fetchall()
                    for table in tables
                },
                "foreign_keys": connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar_one(),
                "violations": connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).fetchall(),
            }

    before = snapshot()

    def fail_statement(connection, cursor, statement, parameters, context, many):
        if statement.startswith(failure_prefix):
            raise RuntimeError("injected migration failure")

    event.listen(engine, "before_cursor_execute", fail_statement)
    try:
        with pytest.raises(RuntimeError, match="injected migration failure"):
            db._upgrade_activation_protocol_checks()
    finally:
        event.remove(engine, "before_cursor_execute", fail_statement)

    assert snapshot() == before
    db._upgrade_activation_protocol_checks()
    after = snapshot()
    db._upgrade_activation_protocol_checks()
    assert snapshot() == after
    assert after["rows"] == before["rows"]
    assert after["foreign_keys"] == 1
    assert after["violations"] == []
    assert set(inspect(engine).get_table_names()) == set(tables)
    assert "ix_invite_battle" in {row[1] for row in after["schema"]}
    assert "tr_invite_update" in {row[1] for row in after["schema"]}
    with engine.begin() as connection:
        for table in ("battles", "battle_invites"):
            connection.exec_driver_sql(
                f"UPDATE {table} SET activation_protocol_version = 3"
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


def test_migrate_schema_adds_nullable_proposal_columns_without_changing_pending(monkeypatch):
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
        connection.execute(text(
            "INSERT INTO agent_proposals "
            "(id, owner_user_id, agent_user_id, action, summary, created_at, updated_at) "
            "VALUES (1, 3, 4, 'battle:action', 'legacy', '2026-07-19', '2026-07-19')"
        ))

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "DB_URL", "sqlite://")
    for _ in range(2):
        Base.metadata.create_all(engine)
        db._migrate_schema()

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("agent_proposals")
    }
    assert columns["result_json"]["nullable"] is True
    assert columns["producer_owner_created_at"]["nullable"] is True
    with engine.connect() as connection:
        assert tuple(connection.execute(text(
            "SELECT status, summary, payload_json, result_json, producer_owner_created_at "
            "FROM agent_proposals WHERE id=1"
        )).one()) == ("pending", "legacy", "{}", None, None)
    assert "bot_proposal_attempts" in inspect(engine).get_table_names()


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
