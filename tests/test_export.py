from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.routers import export, rosters


class DummyRoster:
    def __init__(self) -> None:
        self.roster_units = []
        self.name = "Test roster"
        self.army = "Test army"
        self.points_limit = None


def test_roster_print_context_keys(monkeypatch) -> None:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/rosters/1/print",
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "app": app,
            "router": app.router,
        }
    )

    roster = DummyRoster()

    monkeypatch.setattr(export, "_load_roster_for_export", lambda db, roster_id: roster)
    monkeypatch.setattr(export, "_ensure_roster_view_access", lambda roster, user: None)
    monkeypatch.setattr(export.costs, "update_cached_costs", lambda units: None)
    monkeypatch.setattr(
        export,
        "_export_roster_unit_entries",
        lambda db, roster: [{"unit": "entry", "total_cost": 123.0}],
    )
    monkeypatch.setattr(export, "_army_spell_entries", lambda roster, entries: [{"label": "Spell"}])
    monkeypatch.setattr(export, "_army_rule_labels", lambda army: ["Rule A"])

    response = export.roster_print(1, request, db=None, current_user="user")

    expected_keys = {
        "request",
        "user",
        "roster",
        "roster_items",
        "total_cost",
        "total_cost_rounded",
        "generated_at",
        "spell_entries",
        "army_rules",
    }

    assert expected_keys.issubset(response.context.keys())


class DummyRosterUnit:
    def __init__(self, *, count: int, cached_cost: float) -> None:
        self.count = count
        self.cached_cost = cached_cost


def test_apply_melee_fighting_defaults_clamps_to_member_count_and_uses_anchor_base_size() -> None:
    anchor_unit = SimpleNamespace(base_size="duza")  # limit1=2
    group_members = [
        {"count": 1},  # attached hero, count=1 -> min(2, 1) = 1
        {"count": 5},  # base unit, count=5 -> min(2, 5) = 2
    ]
    export._apply_melee_fighting_defaults(anchor_unit, group_members)
    assert group_members[0]["melee_fighting_default"] == 1
    assert group_members[1]["melee_fighting_default"] == 2


def test_apply_melee_fighting_defaults_small_unit_below_limit_uses_full_count() -> None:
    anchor_unit = SimpleNamespace(base_size="mala")  # limit1=8
    members = [{"count": 5}]
    export._apply_melee_fighting_defaults(anchor_unit, members)
    assert members[0]["melee_fighting_default"] == 5


def test_apply_melee_fighting_defaults_zero_count_yields_zero() -> None:
    anchor_unit = SimpleNamespace(base_size="srednia")
    members = [{"count": 0}]
    export._apply_melee_fighting_defaults(anchor_unit, members)
    assert members[0]["melee_fighting_default"] == 0


def test_apply_melee_fighting_defaults_missing_base_size_falls_back_to_default() -> None:
    members = [{"count": 20}]
    export._apply_melee_fighting_defaults(None, members)
    assert members[0]["melee_fighting_default"] == 6  # DEFAULT_BASE_SIZE "srednia" -> limit1=6
