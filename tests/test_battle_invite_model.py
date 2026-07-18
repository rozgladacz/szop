from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base


@pytest.fixture()
def database():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    yield engine, Session
    engine.dispose()


def _seed_world(session):
    inviter = models.User(username="inviter", password_hash="x")
    target = models.User(username="target", password_hash="x")
    other = models.User(username="other", password_hash="x")
    ruleset = models.RuleSet(name="Invite rules")
    armory = models.Armory(name="Invite armory")
    army = models.Army(
        name="Invite army",
        ruleset=ruleset,
        armory=armory,
    )
    inviter_roster = models.Roster(
        name="Inviter roster",
        army=army,
        owner=inviter,
    )
    target_roster = models.Roster(
        name="Target roster",
        army=army,
        owner=target,
    )
    other_roster = models.Roster(
        name="Other roster",
        army=army,
        owner=other,
    )
    session.add_all(
        [
            inviter,
            target,
            other,
            ruleset,
            armory,
            army,
            inviter_roster,
            target_roster,
            other_roster,
        ]
    )
    session.flush()
    battle = models.Battle(
        p1_user_id=inviter.id,
        p2_user_id=target.id,
        p1_roster_id=inviter_roster.id,
        p2_roster_id=target_roster.id,
        rng_seed=123,
        status="pending",
    )
    session.add(battle)
    session.commit()
    return {
        "inviter": inviter,
        "target": target,
        "other": other,
        "inviter_roster": inviter_roster,
        "target_roster": target_roster,
        "other_roster": other_roster,
        "battle": battle,
    }


def _pending_invite_ids(world) -> dict[str, object]:
    return {
        "from_user_id": world["inviter"].id,
        "to_user_id": world["target"].id,
        "roster_id": world["inviter_roster"].id,
        "scenario": "scenario-alpha",
        "expires_at": datetime(2026, 8, 1, 12, 0),
    }


def test_schema_contract_has_exact_columns_constraints_and_indexes(database):
    engine, _ = database
    inspector = inspect(engine)

    columns = {
        column["name"]: column
        for column in inspector.get_columns("battle_invites")
    }
    assert set(columns) == {
        "id",
        "from_user_id",
        "to_user_id",
        "roster_id",
        "scenario",
        "status",
        "expires_at",
        "accepted_by_user_id",
        "accepted_roster_id",
        "battle_id",
        "created_at",
        "updated_at",
    }
    assert columns["id"]["primary_key"] == 1
    assert columns["from_user_id"]["nullable"] is False
    assert columns["to_user_id"]["nullable"] is True
    assert columns["roster_id"]["nullable"] is False
    assert columns["scenario"]["nullable"] is False
    assert columns["scenario"]["type"].length == 100
    assert columns["status"]["nullable"] is False
    assert columns["status"]["type"].length == 20
    assert columns["expires_at"]["nullable"] is False
    assert columns["accepted_by_user_id"]["nullable"] is True
    assert columns["accepted_roster_id"]["nullable"] is True
    assert columns["battle_id"]["nullable"] is True
    assert columns["created_at"]["nullable"] is False
    assert columns["updated_at"]["nullable"] is False

    foreign_keys = {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
        for foreign_key in inspector.get_foreign_keys("battle_invites")
    }
    assert foreign_keys == {
        (("from_user_id",), "users"),
        (("to_user_id",), "users"),
        (("roster_id",), "rosters"),
        (("accepted_by_user_id",), "users"),
        (("accepted_roster_id",), "rosters"),
        (("battle_id",), "battles"),
    }

    checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("battle_invites")
    }
    assert set(checks) == {
        "ck_battle_invites_status_valid",
        "ck_battle_invites_direct_not_self",
        "ck_battle_invites_accepted_result_complete",
        "ck_battle_invites_nonaccepted_result_empty",
    }
    status_check = checks["ck_battle_invites_status_valid"]
    assert all(status in status_check for status in models.BATTLE_INVITE_STATUSES)

    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("battle_invites")
    }
    assert unique_constraints == {
        "uq_battle_invites_battle_id": ("battle_id",),
    }

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("battle_invites")
    }
    assert indexes == {
        "ix_battle_invites_from_status_created_at": (
            "from_user_id",
            "status",
            "created_at",
        ),
        "ix_battle_invites_to_status_expires_at": (
            "to_user_id",
            "status",
            "expires_at",
        ),
    }


def test_direct_and_open_pending_round_trip_with_default_and_timestamps(database):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        expires_at = datetime(2026, 8, 1, 12, 0)
        direct = models.BattleInvite(
            from_user=world["inviter"],
            to_user=world["target"],
            roster=world["inviter_roster"],
            scenario="scenario-direct",
            expires_at=expires_at,
        )
        open_invite = models.BattleInvite(
            from_user=world["inviter"],
            to_user=None,
            roster=world["inviter_roster"],
            scenario="scenario-open",
            expires_at=expires_at + timedelta(hours=1),
        )
        session.add_all([direct, open_invite])
        session.commit()
        direct_id = direct.id
        open_id = open_invite.id
        session.expire_all()

        loaded_direct = session.get(models.BattleInvite, direct_id)
        loaded_open = session.get(models.BattleInvite, open_id)
        assert loaded_direct is not None
        assert loaded_open is not None
        assert loaded_direct.status == models.BATTLE_INVITE_STATUS_PENDING
        assert loaded_direct.from_user.username == "inviter"
        assert loaded_direct.to_user.username == "target"
        assert loaded_direct.roster.name == "Inviter roster"
        assert loaded_direct.expires_at == expires_at
        assert loaded_direct.created_at is not None
        assert loaded_direct.updated_at is not None
        assert loaded_direct.created_at.tzinfo is None
        assert loaded_direct.updated_at.tzinfo is None
        assert loaded_open.status == models.BATTLE_INVITE_STATUS_PENDING
        assert loaded_open.to_user_id is None
        assert loaded_open.to_user is None


def test_accepted_open_invite_round_trips_first_acceptor_and_complete_result(database):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        invite_values = _pending_invite_ids(world)
        invite_values["to_user_id"] = None
        invite = models.BattleInvite(
            **invite_values,
            status=models.BATTLE_INVITE_STATUS_ACCEPTED,
            accepted_by_user_id=world["target"].id,
            accepted_roster_id=world["target_roster"].id,
            battle_id=world["battle"].id,
        )
        session.add(invite)
        session.commit()
        invite_id = invite.id
        session.expire_all()

        loaded = session.get(models.BattleInvite, invite_id)
        assert loaded is not None
        assert loaded.to_user is None
        assert loaded.accepted_by_user.username == "target"
        assert loaded.accepted_roster.name == "Target roster"
        assert loaded.battle.id == world["battle"].id


def test_invalid_status_is_rejected(database):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        invite = models.BattleInvite(**_pending_invite_ids(world), status="unknown")
        session.add(invite)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_direct_self_invite_is_rejected_but_open_invite_is_allowed(database):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        values = _pending_invite_ids(world)
        values["to_user_id"] = world["inviter"].id
        session.add(models.BattleInvite(**values))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        open_values = _pending_invite_ids(world)
        open_values["to_user_id"] = None
        session.add(models.BattleInvite(**open_values))
        session.commit()


@pytest.mark.parametrize(
    "missing_field",
    ["accepted_by_user_id", "accepted_roster_id", "battle_id"],
)
def test_accepted_invite_rejects_each_partial_result(database, missing_field):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        values = {
            **_pending_invite_ids(world),
            "status": models.BATTLE_INVITE_STATUS_ACCEPTED,
            "accepted_by_user_id": world["target"].id,
            "accepted_roster_id": world["target_roster"].id,
            "battle_id": world["battle"].id,
        }
        values[missing_field] = None
        session.add(models.BattleInvite(**values))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize(
    ("status", "result_field"),
    [
        (models.BATTLE_INVITE_STATUS_PENDING, "accepted_by_user_id"),
        (models.BATTLE_INVITE_STATUS_DECLINED, "accepted_roster_id"),
        (models.BATTLE_INVITE_STATUS_EXPIRED, "battle_id"),
    ],
)
def test_nonaccepted_invite_rejects_result_linkage(database, status, result_field):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        result_values = {
            "accepted_by_user_id": world["target"].id,
            "accepted_roster_id": world["target_roster"].id,
            "battle_id": world["battle"].id,
        }
        values = {**_pending_invite_ids(world), "status": status}
        values[result_field] = result_values[result_field]
        session.add(models.BattleInvite(**values))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_two_invites_cannot_link_the_same_battle(database):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        first = models.BattleInvite(
            **_pending_invite_ids(world),
            status=models.BATTLE_INVITE_STATUS_ACCEPTED,
            accepted_by_user_id=world["target"].id,
            accepted_roster_id=world["target_roster"].id,
            battle_id=world["battle"].id,
        )
        session.add(first)
        session.commit()

        second = models.BattleInvite(
            from_user_id=world["target"].id,
            to_user_id=world["other"].id,
            roster_id=world["target_roster"].id,
            scenario="scenario-beta",
            status=models.BATTLE_INVITE_STATUS_ACCEPTED,
            expires_at=datetime(2026, 8, 2, 12, 0),
            accepted_by_user_id=world["other"].id,
            accepted_roster_id=world["other_roster"].id,
            battle_id=world["battle"].id,
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize("missing_reference", ["user", "roster", "battle"])
def test_sqlite_foreign_keys_are_enforced_and_session_is_rolled_back(
    database,
    missing_reference,
):
    engine, Session = database
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    with Session() as session:
        world = _seed_world(session)
        values = _pending_invite_ids(world)
        if missing_reference == "user":
            values["from_user_id"] = 999_999
        elif missing_reference == "roster":
            values["roster_id"] = 999_999
        else:
            values.update(
                status=models.BATTLE_INVITE_STATUS_ACCEPTED,
                accepted_by_user_id=world["target"].id,
                accepted_roster_id=world["target_roster"].id,
                battle_id=999_999,
            )

        session.add(models.BattleInvite(**values))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(models.User, world["inviter"].id) is not None
        assert session.scalar(select(models.BattleInvite.id)) is None


def test_timestamp_listener_updates_only_updated_at(database, monkeypatch):
    _, Session = database
    with Session() as session:
        world = _seed_world(session)
        created_at = datetime(2026, 7, 19, 10, 0)
        updated_at = datetime(2026, 7, 19, 11, 0)
        timestamps = iter([created_at, updated_at])
        monkeypatch.setattr(models, "utcnow", lambda: next(timestamps))

        invite = models.BattleInvite(**_pending_invite_ids(world))
        session.add(invite)
        session.commit()
        assert invite.created_at == created_at
        assert invite.updated_at == created_at

        invite.scenario = "scenario-updated"
        session.commit()
        session.refresh(invite)
        assert invite.created_at == created_at
        assert invite.updated_at == updated_at
