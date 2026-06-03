from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.data.strategic_cards import (
    STRATEGIC_SUPPORTS,
    STRATEGIC_TASKS,
    SUPPORTS_BY_SLUG,
    TASKS_BY_SLUG,
)
from app.routers import rosters


# -----------------------------------------------------------------
# _parse_strategic_cards — czyste testy parsera
# -----------------------------------------------------------------
def test_parse_strategic_cards_none() -> None:
    assert rosters._parse_strategic_cards(None) == {
        "tasks": ["", "", ""],
        "supports": ["", "", ""],
    }


def test_parse_strategic_cards_empty_string() -> None:
    assert rosters._parse_strategic_cards("") == {
        "tasks": ["", "", ""],
        "supports": ["", "", ""],
    }


def test_parse_strategic_cards_invalid_json() -> None:
    assert rosters._parse_strategic_cards("not a json {") == {
        "tasks": ["", "", ""],
        "supports": ["", "", ""],
    }


def test_parse_strategic_cards_non_object() -> None:
    assert rosters._parse_strategic_cards("[1, 2, 3]") == {
        "tasks": ["", "", ""],
        "supports": ["", "", ""],
    }


def test_parse_strategic_cards_unknown_slugs_filtered() -> None:
    raw = json.dumps({
        "tasks": ["nieistnieje-1", STRATEGIC_TASKS[0].slug, "nieistnieje-2"],
        "supports": ["fake", STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug],
    })
    parsed = rosters._parse_strategic_cards(raw)
    assert parsed["tasks"] == [STRATEGIC_TASKS[0].slug, "", ""]
    assert parsed["supports"] == [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, ""]


def test_parse_strategic_cards_valid_three_plus_three() -> None:
    raw = json.dumps({
        "tasks": [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, STRATEGIC_TASKS[2].slug],
        "supports": [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, STRATEGIC_SUPPORTS[2].slug],
    })
    parsed = rosters._parse_strategic_cards(raw)
    assert parsed["tasks"] == [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, STRATEGIC_TASKS[2].slug]
    assert parsed["supports"] == [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, STRATEGIC_SUPPORTS[2].slug]


def test_parse_strategic_cards_truncates_to_three() -> None:
    raw = json.dumps({
        "tasks": [t.slug for t in STRATEGIC_TASKS],  # 7 sztuk
        "supports": [s.slug for s in STRATEGIC_SUPPORTS],  # 6 sztuk
    })
    parsed = rosters._parse_strategic_cards(raw)
    assert len(parsed["tasks"]) == 3
    assert len(parsed["supports"]) == 3
    assert parsed["tasks"] == [t.slug for t in STRATEGIC_TASKS[:3]]
    assert parsed["supports"] == [s.slug for s in STRATEGIC_SUPPORTS[:3]]


def test_parse_strategic_cards_pads_to_three() -> None:
    raw = json.dumps({
        "tasks": [STRATEGIC_TASKS[0].slug],
        "supports": [],
    })
    parsed = rosters._parse_strategic_cards(raw)
    assert parsed["tasks"] == [STRATEGIC_TASKS[0].slug, "", ""]
    assert parsed["supports"] == ["", "", ""]


def test_parse_strategic_cards_non_string_items_filtered() -> None:
    raw = json.dumps({
        "tasks": [None, 123, STRATEGIC_TASKS[0].slug],
        "supports": [{"foo": 1}, STRATEGIC_SUPPORTS[0].slug],
    })
    parsed = rosters._parse_strategic_cards(raw)
    assert parsed["tasks"] == [STRATEGIC_TASKS[0].slug, "", ""]
    assert parsed["supports"] == [STRATEGIC_SUPPORTS[0].slug, "", ""]


# -----------------------------------------------------------------
# _strategic_card_matrix — generowanie macierzy 3x3
# -----------------------------------------------------------------
def test_strategic_card_matrix_full() -> None:
    selected = {
        "tasks": [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, STRATEGIC_TASKS[2].slug],
        "supports": [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, STRATEGIC_SUPPORTS[2].slug],
    }
    matrix = rosters._strategic_card_matrix(selected)
    assert len(matrix) == 3
    for row in matrix:
        assert len(row) == 3
        for cell in row:
            assert cell is not None
            assert "task_text" in cell
            assert "support_text" in cell
    # Kolumna 0 wszystkie mają task_text = task[0].text
    assert matrix[0][0]["task_text"] == STRATEGIC_TASKS[0].text
    assert matrix[1][0]["task_text"] == STRATEGIC_TASKS[0].text
    assert matrix[2][0]["task_text"] == STRATEGIC_TASKS[0].text
    # Wiersz 0 wszystkie mają support_text = support[0].text
    assert matrix[0][0]["support_text"] == STRATEGIC_SUPPORTS[0].text
    assert matrix[0][1]["support_text"] == STRATEGIC_SUPPORTS[0].text
    assert matrix[0][2]["support_text"] == STRATEGIC_SUPPORTS[0].text


def test_strategic_card_matrix_missing_slot_becomes_none() -> None:
    selected = {
        "tasks": [STRATEGIC_TASKS[0].slug, "", STRATEGIC_TASKS[2].slug],
        "supports": [STRATEGIC_SUPPORTS[0].slug, "", ""],
    }
    matrix = rosters._strategic_card_matrix(selected)
    assert matrix[0][0] is not None
    assert matrix[0][1] is None  # task[1] = ""
    assert matrix[0][2] is not None
    assert matrix[1][0] is None  # support[1] = ""
    assert matrix[2][0] is None  # support[2] = ""


# -----------------------------------------------------------------
# Routes — testowanie funkcji bezpośrednio z mockowanymi zależnościami
# -----------------------------------------------------------------
def _make_request(path: str = "/x") -> Request:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "app": app,
            "router": app.router,
        }
    )


class _DummyDB:
    def __init__(self, roster) -> None:
        self._roster = roster
        self.committed = False

    def get(self, _model, _id):
        return self._roster

    def commit(self) -> None:
        self.committed = True


def _dummy_roster(*, owner_id: int | None = 1, strategic_cards_json: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Testowa rozpiska",
        owner_id=owner_id,
        strategic_cards_json=strategic_cards_json,
    )


def _user(*, user_id: int = 1, is_admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, is_admin=is_admin)


def test_strategic_cards_edit_redirects_when_logged_out() -> None:
    request = _make_request()
    response = rosters.strategic_cards_edit(
        roster_id=42, request=request, db=_DummyDB(_dummy_roster()), current_user=None
    )
    # RedirectResponse na /auth/login
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_strategic_cards_edit_404_when_no_roster() -> None:
    request = _make_request()
    with pytest.raises(HTTPException) as exc:
        rosters.strategic_cards_edit(
            roster_id=999, request=request, db=_DummyDB(None), current_user=_user()
        )
    assert exc.value.status_code == 404


def test_strategic_cards_edit_renders_with_selected_values() -> None:
    request = _make_request()
    raw = json.dumps({
        "tasks": [STRATEGIC_TASKS[1].slug, "", ""],
        "supports": [STRATEGIC_SUPPORTS[2].slug, "", ""],
    })
    roster = _dummy_roster(strategic_cards_json=raw)
    response = rosters.strategic_cards_edit(
        roster_id=42, request=request, db=_DummyDB(roster), current_user=_user()
    )
    ctx = response.context
    assert ctx["roster"] is roster
    assert ctx["can_edit"] is True
    assert list(ctx["tasks"]) == list(STRATEGIC_TASKS)
    assert list(ctx["supports"]) == list(STRATEGIC_SUPPORTS)
    assert ctx["selected"]["tasks"][0] == STRATEGIC_TASKS[1].slug
    assert ctx["selected"]["supports"][0] == STRATEGIC_SUPPORTS[2].slug


def test_strategic_cards_edit_forbids_other_users() -> None:
    request = _make_request()
    roster = _dummy_roster(owner_id=999)  # nie ten user
    with pytest.raises(HTTPException) as exc:
        rosters.strategic_cards_edit(
            roster_id=42, request=request, db=_DummyDB(roster), current_user=_user(user_id=1)
        )
    assert exc.value.status_code == 403


def test_strategic_cards_edit_admin_has_full_access_on_other_roster() -> None:
    # Spójne z istniejącym wzorcem edit_roster (rosters.py linia ~696):
    #   can_edit = current_user.is_admin or roster.owner_id == current_user.id
    # Admin dostaje can_edit=True nawet na cudzej rozpisce.
    request = _make_request()
    roster = _dummy_roster(owner_id=999)
    admin = _user(user_id=1, is_admin=True)
    response = rosters.strategic_cards_edit(
        roster_id=42, request=request, db=_DummyDB(roster), current_user=admin
    )
    assert response.context["can_edit"] is True


def test_strategic_cards_save_writes_json_to_roster() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    response = rosters.strategic_cards_save(
        roster_id=42,
        tasks=[STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, "nieistnieje"],
        supports=[STRATEGIC_SUPPORTS[0].slug, "", STRATEGIC_SUPPORTS[1].slug],
        redirect_to="self",
        db=db,
        current_user=_user(),
    )
    assert db.committed is True
    payload = json.loads(roster.strategic_cards_json)
    # nieznany slug "nieistnieje" odfiltrowany → trzeci slot pusty (padding)
    assert payload["tasks"] == [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, ""]
    # Filtr czyści pustki — supports[1]="" pominięty, supports[2] przeskoczył na poz. 1
    assert payload["supports"] == [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, ""]
    assert response.status_code == 303
    assert response.headers["location"] == "/rosters/42/strategic-cards"


def test_strategic_cards_save_redirect_to_print() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    response = rosters.strategic_cards_save(
        roster_id=42, tasks=[], supports=[], redirect_to="print",
        db=db, current_user=_user(),
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/rosters/42/strategic-cards/print"


def test_strategic_cards_save_redirect_to_roster() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    response = rosters.strategic_cards_save(
        roster_id=42, tasks=[], supports=[], redirect_to="roster",
        db=db, current_user=_user(),
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/rosters/42"


def test_strategic_cards_save_truncates_more_than_three() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    rosters.strategic_cards_save(
        roster_id=42,
        tasks=[c.slug for c in STRATEGIC_TASKS],  # 7 sztuk
        supports=[c.slug for c in STRATEGIC_SUPPORTS],  # 6 sztuk
        redirect_to="self",
        db=db,
        current_user=_user(),
    )
    payload = json.loads(roster.strategic_cards_json)
    assert payload["tasks"] == [c.slug for c in STRATEGIC_TASKS[:3]]
    assert payload["supports"] == [c.slug for c in STRATEGIC_SUPPORTS[:3]]


def test_strategic_cards_save_deduplicates() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    s = STRATEGIC_TASKS[0].slug
    rosters.strategic_cards_save(
        roster_id=42,
        tasks=[s, s, s, STRATEGIC_TASKS[1].slug],  # duplikaty: zlicza jako 1
        supports=[],
        redirect_to="self",
        db=db,
        current_user=_user(),
    )
    payload = json.loads(roster.strategic_cards_json)
    assert payload["tasks"] == [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, ""]
    assert payload["supports"] == ["", "", ""]


def test_strategic_cards_save_empty_lists() -> None:
    roster = _dummy_roster()
    db = _DummyDB(roster)
    rosters.strategic_cards_save(
        roster_id=42, tasks=[], supports=[], redirect_to="self", db=db, current_user=_user()
    )
    payload = json.loads(roster.strategic_cards_json)
    assert payload == {"tasks": ["", "", ""], "supports": ["", "", ""]}


def test_strategic_cards_save_forbidden_when_not_owner() -> None:
    roster = _dummy_roster(owner_id=999)
    db = _DummyDB(roster)
    with pytest.raises(HTTPException) as exc:
        rosters.strategic_cards_save(
            roster_id=42,
            tasks=[STRATEGIC_TASKS[0].slug],
            supports=[],
            redirect_to="self",
            db=db,
            current_user=_user(user_id=1),
        )
    assert exc.value.status_code == 403
    assert db.committed is False


def test_strategic_cards_print_builds_matrix() -> None:
    request = _make_request()
    raw = json.dumps({
        "tasks": [STRATEGIC_TASKS[0].slug, STRATEGIC_TASKS[1].slug, STRATEGIC_TASKS[2].slug],
        "supports": [STRATEGIC_SUPPORTS[0].slug, STRATEGIC_SUPPORTS[1].slug, STRATEGIC_SUPPORTS[2].slug],
    })
    roster = _dummy_roster(strategic_cards_json=raw)
    response = rosters.strategic_cards_print(
        roster_id=42, request=request, db=_DummyDB(roster), current_user=_user()
    )
    matrix = response.context["matrix"]
    assert len(matrix) == 3
    assert all(len(row) == 3 for row in matrix)
    # Pierwsza karta = task[0] + support[0]
    assert matrix[0][0]["task_text"] == STRATEGIC_TASKS[0].text
    assert matrix[0][0]["support_text"] == STRATEGIC_SUPPORTS[0].text


def test_strategic_cards_print_redirects_when_logged_out() -> None:
    request = _make_request()
    response = rosters.strategic_cards_print(
        roster_id=42, request=request, db=_DummyDB(_dummy_roster()), current_user=None
    )
    assert response.status_code == 303


# -----------------------------------------------------------------
# Sanity check pliku tekstów
# -----------------------------------------------------------------
def test_strategic_cards_catalog_has_unique_slugs() -> None:
    task_slugs = [c.slug for c in STRATEGIC_TASKS]
    support_slugs = [c.slug for c in STRATEGIC_SUPPORTS]
    assert len(task_slugs) == len(set(task_slugs)), "Duplikat slug w STRATEGIC_TASKS"
    assert len(support_slugs) == len(set(support_slugs)), "Duplikat slug w STRATEGIC_SUPPORTS"
    assert len(STRATEGIC_TASKS) >= 3, "Potrzeba co najmniej 3 Zadań do wyboru"
    assert len(STRATEGIC_SUPPORTS) >= 3, "Potrzeba co najmniej 3 Wsparć do wyboru"


def test_strategic_cards_indexes_match_lists() -> None:
    assert set(TASKS_BY_SLUG.keys()) == {c.slug for c in STRATEGIC_TASKS}
    assert set(SUPPORTS_BY_SLUG.keys()) == {c.slug for c in STRATEGIC_SUPPORTS}
