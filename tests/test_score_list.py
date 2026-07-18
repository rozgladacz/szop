"""C3 — tests for `scripts/score_list.py`.

The script is a DB-read leaf that aggregates `simulate_engagement` pairings
(itself over `LocalClient.simulate_roster_ids`). Tests use seeded in-memory
SQLite and never touch `data/szop.db`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base
from app.services import roster_scoring as scoring_service
from szop_client import SimulationSummary

import scripts.score_list as sl
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


def _seed_field(session, *, second_army: bool = False):
    """Seed one army with three rosters (+ optional second army with one roster).

    Returns the list of created roster ids in creation order.
    """
    user = models.User(username="score-tester", password_hash="x")
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

    def _unit(name, weapon, owner_army):
        unit = models.Unit(
            army=owner_army,
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

    def _roster(name, unit, owner_army):
        roster = models.Roster(name=name, army_id=owner_army.id)
        session.add(roster)
        session.flush()
        session.add(
            models.RosterUnit(roster_id=roster.id, unit_id=unit.id, count=2, position=0)
        )
        session.flush()
        return roster.id

    u_rifle = _unit("Shooter", rifle, army)
    u_blade = _unit("Fighter", blade, army)
    ids = [
        _roster("Roster A", u_rifle, army),
        _roster("Roster B", u_blade, army),
        _roster("Roster C", u_rifle, army),
    ]

    if second_army:
        army2 = models.Army(name="Army Two", owner=user, ruleset=ruleset, armory=armory)
        session.add(army2)
        session.flush()
        u2 = _unit("Other", blade, army2)
        ids.append(_roster("Roster D", u2, army2))

    session.commit()
    return ids


# --- pure aggregation / rendering -----------------------------------------


def _result(opp_id, *, wins_p0, wins_p1, draws, points=100.0):
    info = sl.RosterInfo(opp_id, f"Opp{opp_id}", "Army", points, "2x X")
    summary = SimulationSummary(
        n_games=wins_p0 + wins_p1 + draws,
        wins_p0=wins_p0,
        wins_p1=wins_p1,
        draws=draws,
        total_rounds=(wins_p0 + wins_p1 + draws) * 4,
    )
    return sl.OpponentResult(opponent=info, summary=summary)


def test_aggregate_score_sums_pairings_from_target_perspective():
    results = [
        _result(2, wins_p0=3, wins_p1=1, draws=0),
        _result(3, wins_p0=1, wins_p1=2, draws=1),
    ]

    agg = sl.aggregate_score(results)

    assert agg.n_opponents == 2
    assert agg.n_games_total == 8
    assert agg.wins == 4
    assert agg.losses == 3
    assert agg.draws == 1
    assert agg.win_rate == pytest.approx(0.5)
    assert agg.avg_rounds == pytest.approx(4.0)


def test_leaf_cli_reexports_production_scoring_ssot():
    assert sl.RosterInfo is scoring_service.RosterInfo
    assert sl.OpponentResult is scoring_service.OpponentResult
    assert sl.ScoreSummary is scoring_service.ScoreSummary
    assert sl.RosterNotFoundError is se.RosterNotFoundError
    assert sl.aggregate_score is scoring_service.aggregate_score
    assert sl.score_list is scoring_service.score_list


def test_public_projection_has_structural_cost_signals_and_empty_group_semantics():
    target = sl.RosterInfo(1, "Target", "Army", 100.0, "2× T")
    results = [
        _result(2, wins_p0=3, wins_p1=0, draws=0, points=50.0),
        _result(3, wins_p0=1, wins_p1=2, draws=0, points=200.0),
    ]

    payload = scoring_service.score_list_to_dict(
        target,
        results,
        games_per_opponent=3,
        bot="priority",
        seed=4,
        map_name="lustrzana_a",
    )

    assert payload["schema"] == "szop.score_list/v1"
    assert payload["parameters"]["opponent_roster_ids"] == [2, 3]
    assert payload["cost_signals"]["vs_cheaper"]["wins"] == 3
    assert payload["cost_signals"]["vs_pricier"]["losses"] == 2

    empty = scoring_service.score_list_to_dict(
        target,
        [],
        games_per_opponent=3,
        bot="priority",
        seed=4,
        map_name="lustrzana_a",
    )
    assert empty["aggregate"] == {
        "n_opponents": 0,
        "n_games": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "rounds": 0,
        "win_rate": 0.0,
        "loss_rate": 0.0,
        "draw_rate": 0.0,
        "avg_rounds": 0.0,
    }
    assert empty["cost_signals"]["vs_cheaper"] == empty["aggregate"]
    assert empty["cost_signals"]["vs_pricier"] == empty["aggregate"]


def test_app_never_imports_leaf_scripts_and_batch_loop_has_one_production_ssot():
    repo = Path(__file__).resolve().parents[1]
    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (repo / "app").rglob("*.py")
    )
    assert "from scripts" not in app_source
    assert "import scripts" not in app_source

    local_source = (repo / "szop_client" / "local.py").read_text(encoding="utf-8")
    battles_source = (repo / "app" / "routers" / "battles.py").read_text(
        encoding="utf-8"
    )
    assert "for game_index in range(n)" not in local_source
    assert "for i in range(payload.games)" not in battles_source
    assert "simulate_batch(" in local_source
    assert "simulate_roster_pair(" in battles_source


def test_format_score_report_renders_field_and_cost_signal():
    target = sl.RosterInfo(1, "Target", "Army", 100.0, "2x T")
    results = [
        _result(2, wins_p0=4, wins_p1=0, draws=0, points=50.0),   # cheaper opp
        _result(3, wins_p0=3, wins_p1=1, draws=0, points=200.0),  # pricier opp
    ]
    agg = sl.aggregate_score(results)

    report = sl.format_score_report(target, results, agg, bot="priority", map_name="lustrzana_a")

    assert "Ocena rozpiski [1] Target" in report
    assert "SIŁA W POLU" in report
    assert "vs tańsi" in report
    assert "vs drożsi" in report
    # Wins vs pricier opp (75%) > 50% → niedoszacowanie signal.
    assert "niedoszacowanie" in report


def test_format_score_report_handles_empty_field():
    target = sl.RosterInfo(1, "Solo", "Army", 100.0, "2x T")
    agg = sl.aggregate_score([])

    report = sl.format_score_report(target, [], agg, bot="priority", map_name="lustrzana_a")

    assert "Brak przeciwników" in report


# --- opponent selection (DB) ----------------------------------------------


def test_select_opponents_excludes_self():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
        field = sl._select_opponents(session, ids[0], vs_ids=None, army=None)

    assert ids[0] not in [info.id for info in field]
    assert set(info.id for info in field) == {ids[1], ids[2]}


def test_select_opponents_vs_filter_restricts_field():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
        field = sl._select_opponents(session, ids[0], vs_ids=[ids[2]], army=None)

    assert [info.id for info in field] == [ids[2]]


def test_select_opponents_army_filter_restricts_field():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session, second_army=True)
        # Field for Roster D (army Two): army filter "Army" keeps only first-army rosters.
        field = sl._select_opponents(session, ids[3], vs_ids=None, army="Army")

    assert set(info.id for info in field) == {ids[0], ids[1], ids[2]}


# --- score_list (DB path) -------------------------------------------------


def test_score_list_evaluates_against_whole_field():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
        target, results = sl.score_list(
            session, ids[0], bot="random", n=2, seed=5, map_name="lustrzana_a"
        )

    assert target.id == ids[0]
    assert [r.opponent.id for r in results] == [ids[1], ids[2]]
    for r in results:
        assert 0.0 <= r.win_rate <= 1.0


def test_score_list_parity_with_simulate_engagement():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
        _target, results = sl.score_list(
            session, ids[0], bot="random", n=3, seed=4, map_name="lustrzana_a"
        )
        # Each pairing must equal a direct simulate_engagement call.
        direct, _ia, _ib = sl.simulate_engagement(
            session, ids[0], ids[1], bot="random", n=3, seed=4, map_name="lustrzana_a"
        )

    first = next(r for r in results if r.opponent.id == ids[1])
    assert first.summary == direct


def test_score_list_deterministic():
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
        a = sl.aggregate_score(
            sl.score_list(session, ids[0], bot="priority", n=2, seed=3, map_name="standard_a")[1]
        )
        b = sl.aggregate_score(
            sl.score_list(session, ids[0], bot="priority", n=2, seed=3, map_name="standard_a")[1]
        )

    assert a == b


def test_score_list_unknown_target_raises():
    sm = _sessionmaker()
    with sm() as session:
        _seed_field(session)
        with pytest.raises(sl.RosterNotFoundError):
            sl.score_list(session, 99999, n=1)


# --- CLI ------------------------------------------------------------------


def test_main_list_uses_sessionlocal(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        _seed_field(session)
    init_calls = _patch_cli_db(monkeypatch, sm)

    rc = sl.main(["--list"])
    out = capsys.readouterr().out

    assert rc == 0
    assert init_calls == ["init"]
    assert "Rozpiski w bazie" in out
    assert "Roster A" in out


def test_main_scores_roster_against_field(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
    _patch_cli_db(monkeypatch, sm)

    rc = sl.main([str(ids[0]), "-n", "1", "--bot", "random", "--seed", "2"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Ocena rozpiski" in out
    assert "SIŁA W POLU" in out


def test_main_missing_roster_returns_usage_error(monkeypatch, capsys):
    _patch_cli_db(monkeypatch, _sessionmaker())

    rc = sl.main([])
    err = capsys.readouterr().err

    assert rc == 2
    assert "Podaj id" in err


def test_main_unknown_roster_returns_not_found(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        _seed_field(session)
    _patch_cli_db(monkeypatch, sm)

    rc = sl.main(["99999", "-n", "1"])
    err = capsys.readouterr().err

    assert rc == 1
    assert "Nie znaleziono rozpiski" in err


def test_main_bad_vs_returns_usage_error(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
    _patch_cli_db(monkeypatch, sm)

    rc = sl.main([str(ids[0]), "--vs", "2,xyz"])
    err = capsys.readouterr().err

    assert rc == 2
    assert "--vs" in err


def test_main_unknown_bot_returns_usage_error(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        ids = _seed_field(session)
    _patch_cli_db(monkeypatch, sm)

    rc = sl.main([str(ids[0]), "-n", "1", "--bot", "nope"])
    err = capsys.readouterr().err

    assert rc == 2
    assert "Nieznany typ gracza" in err
