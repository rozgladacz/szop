"""C3 — tests for `scripts/simulate_engagement.py`.

The script is a DB-read leaf over `LocalClient.simulate_roster_ids`; tests use
seeded in-memory SQLite and never touch `data/szop.db`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base
from szop_client import LocalClient, SimulationSummary

import scripts.simulate_engagement as se


def _sessionmaker():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _patch_cli_db(monkeypatch, sm):
    calls: list[str] = []
    monkeypatch.setattr("app.db.init_db", lambda: calls.append("init"))
    monkeypatch.setattr("app.db.SessionLocal", sm)
    return calls


def _seed_two_rosters(session):
    user = models.User(username="engagement-tester", password_hash="x")
    ruleset = models.RuleSet(name="Rules")
    armory = models.Armory(name="Armory", owner=user)
    session.add_all([user, ruleset, armory])
    session.flush()
    army = models.Army(name="Army", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()
    blade = models.Weapon(armory=armory, name="Blade", range="melee", attacks=1, ap=0)
    rifle = models.Weapon(armory=armory, name="Rifle", range="24", attacks=1, ap=0)
    session.add_all([blade, rifle])
    session.flush()

    def _unit(name, weapon):
        unit = models.Unit(
            army=army,
            name=name,
            quality=4,
            defense=5,
            toughness=3,
            typical_models=5,
            position=0,
            default_weapon=weapon,
        )
        session.add(unit)
        session.flush()
        session.add(
            models.UnitWeapon(
                unit=unit,
                weapon=weapon,
                is_default=True,
                default_count=1,
                is_primary=True,
                position=0,
            )
        )
        session.flush()
        return unit

    unit_a = _unit("Infantry A", rifle)
    unit_b = _unit("Infantry B", blade)

    def _roster(name, unit):
        roster = models.Roster(name=name, army_id=army.id)
        session.add(roster)
        session.flush()
        session.add(
            models.RosterUnit(roster_id=roster.id, unit_id=unit.id, count=2, position=0)
        )
        session.flush()
        return roster.id

    rid_a = _roster("Roster A", unit_a)
    rid_b = _roster("Roster B", unit_b)
    session.commit()
    return rid_a, rid_b


def test_format_engagement_report_handles_equal_points():
    summary = SimulationSummary(n_games=1, wins_p0=1, wins_p1=0, draws=0, total_rounds=4)
    info_a = se.RosterInfo(1, "A", "Army", 100.0, "2x A")
    info_b = se.RosterInfo(2, "B", "Army", 100.0, "2x B")

    report = se.format_engagement_report(
        summary, info_a, info_b, bot="priority", map_name="lustrzana_a"
    )

    assert "Koszt równy" in report
    assert "1 gra" in report
    assert "A wygrane" in report
    assert "B wygrane" in report


def test_list_rosters_reports_points_and_composition():
    sm = _sessionmaker()
    with sm() as session:
        _seed_two_rosters(session)
        infos = se.list_rosters(session)

    assert [i.name for i in infos] == ["Roster A", "Roster B"]
    assert all(i.points > 0 for i in infos)
    rendered = se.format_roster_list(infos)
    assert "Roster A" in rendered
    assert "Infantry A" in rendered


def test_simulate_engagement_matches_local_client():
    sm = _sessionmaker()
    with sm() as session:
        rid_a, rid_b = _seed_two_rosters(session)
        summary, info_a, info_b = se.simulate_engagement(
            session, rid_a, rid_b, bot="random", n=3, seed=7, map_name="lustrzana_a"
        )
        map_fixture = se.bsim.build_map("lustrzana_a", 7)
        expected = LocalClient(session=session).simulate_roster_ids(
            rid_a,
            rid_b,
            se._player_factory("random", 7),
            n=3,
            seed=7,
            terrain=map_fixture.terrain,
            objectives=map_fixture.objectives,
            deployment_zones=se.DEPLOY_ZONES,
        )

    assert summary == expected
    assert info_a.name == "Roster A"
    assert info_b.name == "Roster B"


def test_simulate_engagement_deterministic():
    sm = _sessionmaker()
    with sm() as session:
        rid_a, rid_b = _seed_two_rosters(session)
        a = se.simulate_engagement(
            session, rid_a, rid_b, bot="priority", n=2, seed=4, map_name="standard_a"
        )[0]
        b = se.simulate_engagement(
            session, rid_a, rid_b, bot="priority", n=2, seed=4, map_name="standard_a"
        )[0]

    assert a == b


def test_main_list_uses_sessionlocal(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        _seed_two_rosters(session)
    init_calls = _patch_cli_db(monkeypatch, sm)

    rc = se.main(["--list"])
    out = capsys.readouterr().out

    assert rc == 0
    assert init_calls == ["init"]
    assert "Rozpiski w bazie" in out
    assert "Roster A" in out


def test_main_missing_args_returns_usage_error(monkeypatch, capsys):
    _patch_cli_db(monkeypatch, _sessionmaker())

    rc = se.main([])
    err = capsys.readouterr().err

    assert rc == 2
    assert "Podaj dwa id" in err


def test_main_unknown_roster_returns_not_found(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        rid_a, _rid_b = _seed_two_rosters(session)
    _patch_cli_db(monkeypatch, sm)

    rc = se.main([str(rid_a), "99999", "-n", "1"])
    err = capsys.readouterr().err

    assert rc == 1
    assert "Nie znaleziono rozpiski" in err


def test_main_unknown_bot_returns_usage_error(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        rid_a, rid_b = _seed_two_rosters(session)
    _patch_cli_db(monkeypatch, sm)

    rc = se.main([str(rid_a), str(rid_b), "-n", "1", "--bot", "nope"])
    err = capsys.readouterr().err

    assert rc == 2
    assert "Nieznany typ gracza" in err
