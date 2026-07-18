"""C3 — tests for `scripts/validate_loadout.py`.

The script is a DB-read leaf diff validator over `normalize_roster_unit_loadout`
+ `calculate_roster_unit_quote`; tests use seeded in-memory SQLite and never touch
`data/szop.db`. Pure diff helpers are exercised directly without DB where possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app import config
from app.db import Base
from app.services import loadout_validation as service

import scripts.validate_loadout as vl


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


def _seed_unit(session):
    """Jednostka z 1 dozwoloną bronią + 1 aktywną + 1 aurą; zwraca (unit_id, ids)."""
    user = models.User(username="loadout-tester", password_hash="x")
    ruleset = models.RuleSet(name="Rules")
    armory = models.Armory(name="Armory", owner=user)
    session.add_all([user, ruleset, armory])
    session.flush()
    army = models.Army(name="Army", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()

    rifle = models.Weapon(armory=armory, name="Karabin", range="24", attacks=1, ap=0)
    active = models.Ability(name="Furia", type="active", description="")
    aura = models.Ability(name="Dowodzenie", type="aura", description="")
    session.add_all([rifle, active, aura])
    session.flush()

    unit = models.Unit(
        army=army,
        name="Strzelcy",
        quality=4,
        defense=5,
        toughness=3,
        typical_models=5,
        position=0,
        default_weapon=rifle,
    )
    session.add(unit)
    session.flush()
    session.add_all(
        [
            models.UnitWeapon(
                unit=unit, weapon=rifle, is_default=True, default_count=1,
                is_primary=True, position=0,
            ),
            models.UnitAbility(unit=unit, ability=active, position=0),
            models.UnitAbility(unit=unit, ability=aura, position=1),
        ]
    )
    session.commit()
    return unit.id, {"weapon": rifle.id, "active": active.id, "aura": aura.id}


# --- pure diff helpers ---------------------------------------------------------


def test_enumerate_raw_section_dict_and_list():
    assert vl._enumerate_raw_section({"3": 1, " 5 ": 2}) == [("3", 1), ("5", 2)]
    listed = vl._enumerate_raw_section([{"id": 7, "count": 2}, {"weapon_id": 9}])
    assert listed == [("7", 2), ("9", 0)]
    assert vl._enumerate_raw_section(None) == []
    # puste / niemapowalne wpisy pomijane
    assert vl._enumerate_raw_section({"": 1}) == []


def test_coerce_int_and_parseable():
    assert vl._coerce_int(3) == 3
    assert vl._coerce_int("4") == 4
    assert vl._coerce_int(2.9) == 2
    assert vl._coerce_int("abc") is None
    assert vl._id_is_parseable("12:variant") is True
    assert vl._id_is_parseable("abc") is False


def test_diff_section_accept_reject_clamp():
    # normalized zawiera tylko "3" (dozwolony); "99" odrzucony; "3" raw=-2 sklampowany do 0
    raw = {"3": -2, "99": 1, "abc": 1}
    normalized = {"3": 0}
    diff = vl.diff_section("weapons", raw, normalized)
    assert diff.accepted == {"3": 0}
    reasons = dict(diff.rejected)
    assert reasons["99"] == "niedozwolone dla tej jednostki"
    assert reasons["abc"] == "niepoprawne id"
    assert diff.clamped == [("3", -2, 0)]


# --- integration via DB --------------------------------------------------------


def test_validate_clean_loadout_no_issues():
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        raw = {"mode": "per_model", "weapons": {str(ids["weapon"]): 1}}
        diff = vl.validate_loadout_by_id(session, uid, raw, count=5)
    assert diff.unit_id == uid
    assert diff.has_issues is False
    assert diff.normalized_mode == "per_model"
    assert diff.selected_total > 0
    weapons = next(s for s in diff.sections if s.section == "weapons")
    assert str(ids["weapon"]) in weapons.accepted


def test_validate_rejects_disallowed_weapon():
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        raw = {"weapons": {str(ids["weapon"]): 1, "99999": 1}}
        diff = vl.validate_loadout_by_id(session, uid, raw)
    weapons = next(s for s in diff.sections if s.section == "weapons")
    assert ("99999", "niedozwolone dla tej jednostki") in weapons.rejected
    assert diff.has_issues is True


def test_validate_accepts_active_and_aura_ids():
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        raw = {"active": {str(ids["active"]): 1}, "aura": {str(ids["aura"]): 1}}
        diff = vl.validate_loadout_by_id(session, uid, raw)
    active = next(s for s in diff.sections if s.section == "active")
    aura = next(s for s in diff.sections if s.section == "aura")
    assert str(ids["active"]) in active.accepted
    assert str(ids["aura"]) in aura.accepted


def test_validate_mode_clamped():
    sm = _sessionmaker()
    with sm() as session:
        uid, _ = _seed_unit(session)
        diff = vl.validate_loadout_by_id(session, uid, {"mode": "bogus"})
    assert diff.mode_clamped is True
    assert diff.normalized_mode == "per_model"
    assert diff.has_issues is True


def test_validate_passive_rejected_unknown_slug():
    sm = _sessionmaker()
    with sm() as session:
        uid, _ = _seed_unit(session)
        diff = vl.validate_loadout_by_id(session, uid, {"passive": {"nieistniejaca": 1}})
    assert "nieistniejaca" in diff.passive_rejected
    assert diff.has_issues is True


def test_validate_passive_zero_not_rejected():
    sm = _sessionmaker()
    with sm() as session:
        uid, _ = _seed_unit(session)
        # passive=0 = świadome wyłączenie, nie „odrzucenie"
        diff = vl.validate_loadout_by_id(session, uid, {"passive": {"cokolwiek": 0}})
    assert diff.passive_rejected == []


def test_unknown_unit_id_raises():
    sm = _sessionmaker()
    with sm() as session:
        _seed_unit(session)
        try:
            vl.validate_loadout_by_id(session, 99999, {})
        except vl.UnitNotFoundError:
            pass
        else:  # pragma: no cover
            raise AssertionError("oczekiwano UnitNotFoundError")


def test_diff_to_dict_round_trip():
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        raw = {"mode": "bad", "weapons": {str(ids["weapon"]): 1, "99": 1}}
        diff = vl.validate_loadout_by_id(session, uid, raw)
    import json

    payload = json.loads(json.dumps(vl.diff_to_dict(diff)))
    assert payload["schema"] == "szop.validate_loadout/v1"
    assert payload["version"] == 1
    assert payload["unit_id"] == uid
    assert payload["mode"]["clamped"] is True
    assert payload["has_issues"] is True


def test_leaf_module_reexports_the_production_service_ssot():
    assert vl.SectionDiff is service.SectionDiff
    assert vl.LoadoutDiff is service.LoadoutDiff
    assert vl.UnitNotFoundError is service.UnitNotFoundError
    assert vl.diff_section is service.diff_section
    assert vl.diff_passive is service.diff_passive
    assert vl.validate_loadout is service.validate_loadout
    assert vl.validate_loadout_by_id is service.validate_loadout_by_id
    assert vl.diff_to_dict is service.diff_to_dict


@pytest.mark.parametrize(
    "backend",
    [
        config.RULES_BACKEND_PROCEDURAL,
        config.RULES_BACKEND_YAML,
        config.RULES_BACKEND_BOTH_ASSERT,
    ],
)
def test_service_cost_output_has_backend_parity(monkeypatch, backend):
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", backend)
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        diff = service.validate_loadout_by_id(
            session,
            uid,
            {
                "mode": "bad",
                "weapons": {str(ids["weapon"]): -2, "99999": 1},
                "active": {str(ids["active"]): 1},
                "passive": {"nieistniejaca": 1},
            },
            count=3,
        )

    payload = service.diff_to_dict(diff)
    assert payload["mode"]["clamped"] is True
    assert payload["sections"][0]["clamped"]
    assert payload["sections"][0]["rejected"]
    assert payload["passive"]["rejected"] == ["nieistniejaca"]
    assert payload["cost"]["selected_total"] >= 0.0


def test_service_has_no_dependency_on_leaf_script():
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "scripts.validate_loadout" not in source
    assert "from scripts" not in source


def test_format_diff_report_contains_sections():
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
        raw = {"weapons": {str(ids["weapon"]): 1, "99": 1}}
        diff = vl.validate_loadout_by_id(session, uid, raw)
    text = vl.format_diff_report(diff)
    assert "Walidacja loadoutu" in text
    assert "ODRZUCONE 99" in text
    assert "Koszt" in text


# --- CLI main() ----------------------------------------------------------------


def test_main_list(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        _seed_unit(session)
    init_calls = _patch_cli_db(monkeypatch, sm)
    rc = vl.main(["--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert init_calls == ["init"]
    assert "Strzelcy" in out


def test_main_validate_ok(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        uid, ids = _seed_unit(session)
    _patch_cli_db(monkeypatch, sm)
    rc = vl.main([str(uid), "--loadout", '{"weapons":{"%d":1}}' % ids["weapon"]])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Walidacja loadoutu" in out


def test_main_json_output(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        uid, _ = _seed_unit(session)
    _patch_cli_db(monkeypatch, sm)
    rc = vl.main([str(uid), "--loadout", '{"mode":"bad"}', "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    import json

    payload = json.loads(out)
    assert payload["mode"]["clamped"] is True


def test_main_missing_unit_id_usage_error(monkeypatch, capsys):
    _patch_cli_db(monkeypatch, _sessionmaker())
    rc = vl.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "id jednostki" in err


def test_main_bad_json_returns_error(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        uid, _ = _seed_unit(session)
    _patch_cli_db(monkeypatch, sm)
    rc = vl.main([str(uid), "--loadout", "{not json"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Błąd wczytania loadoutu" in err


def test_main_unknown_unit_returns_not_found(monkeypatch, capsys):
    sm = _sessionmaker()
    with sm() as session:
        _seed_unit(session)
    _patch_cli_db(monkeypatch, sm)
    rc = vl.main(["99999", "--loadout", "{}"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "nie istnieje" in err
