from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.db import Base
from app.services import collection_match as cm


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


# ── model_variant_signature ─────────────────────────────────────────────────

def test_signature_is_order_independent() -> None:
    assert cm.model_variant_signature({"5": 1, "7": 2}) == cm.model_variant_signature(
        {"7": 2, "5": 1}
    )


def test_signature_merges_and_drops_nonpositive() -> None:
    # Liczby <= 0 i niby-int klucze pomijane; te same id sumowane.
    assert cm.model_variant_signature({"5": 1, "9": 0, "x": 3}) == "5:1"


def test_signature_empty_loadout() -> None:
    assert cm.model_variant_signature({}) == cm.model_variant_signature(None)
    assert cm.model_variant_signature({}) == "∅"


def test_signature_distinguishes_variants() -> None:
    assert cm.model_variant_signature({"5": 1}) != cm.model_variant_signature(
        {"5": 1, "7": 1}
    )


# ── collection_model_effective_weapons ──────────────────────────────────────

def test_effective_weapons_merge_base_and_mounted_slots() -> None:
    double = SimpleNamespace(
        loadout_json=json.dumps({"weapons": {"5": 2}}),
        slots=[
            SimpleNamespace(selected_weapon_id=7),
            SimpleNamespace(selected_weapon_id=None),  # pusty slot — pomijany
            SimpleNamespace(selected_weapon_id=5),  # ta sama broń co bazowa — sumuje
        ],
    )
    assert cm.collection_model_effective_weapons(double) == {5: 3, 7: 1}


def test_effective_weapons_handles_bad_json() -> None:
    double = SimpleNamespace(loadout_json="not json {", slots=[])
    assert cm.collection_model_effective_weapons(double) == {}


# ── roster_needs ────────────────────────────────────────────────────────────

def _item(unit_id: int, count: int, mode: str, weapons: dict) -> dict:
    return {
        "instance": SimpleNamespace(unit_id=unit_id, count=count),
        "loadout": {"mode": mode, "weapons": weapons},
        "loadout_summary": "podsumowanie",
    }


def test_roster_needs_aggregates_duplicate_units_by_variant() -> None:
    items = [
        _item(1, 3, "per_model", {"5": 1}),
        _item(1, 2, "per_model", {"5": 1}),  # ten sam wariant, inny oddział
        _item(1, 4, "per_model", {"5": 1, "7": 1}),  # inny wariant
    ]
    by_variant, total = cm.roster_needs(items)
    assert by_variant[1]["5:1"] == 5
    assert by_variant[1]["5:1|7:1"] == 4
    assert total[1] == 9


def test_roster_needs_total_mode_counts_only_to_total() -> None:
    items = [
        _item(1, 3, "per_model", {"5": 1}),
        _item(1, 4, "total", {"5": 4}),  # broń zbiorcza — brak wariantu
    ]
    by_variant, total = cm.roster_needs(items)
    assert by_variant[1]["5:1"] == 3
    assert "5:4" not in by_variant[1]
    assert total[1] == 7


# ── coverage_for_item ───────────────────────────────────────────────────────

def test_coverage_per_model_partial_covered_missing() -> None:
    owned = {1: {"5:1": 4}}
    needed_by_variant = {1: {"5:1": 5}}
    needed_total = {1: 5}

    partial = cm.coverage_for_item(
        _item(1, 3, "per_model", {"5": 1}), owned, needed_by_variant, needed_total
    )
    assert partial["status"] == "partial"
    assert (partial["owned"], partial["needed"], partial["variant"]) == (4, 5, True)

    owned_covered = {1: {"5:1": 5}}
    covered = cm.coverage_for_item(
        _item(1, 3, "per_model", {"5": 1}), owned_covered, needed_by_variant, needed_total
    )
    assert covered["status"] == "covered"

    missing = cm.coverage_for_item(
        _item(1, 3, "per_model", {"9": 1}), owned, needed_by_variant, needed_total
    )
    assert missing["status"] == "missing"
    assert missing["owned"] == 0


def test_coverage_total_mode_is_count_only() -> None:
    owned = {1: {"5:1": 2, "5:1|7:1": 3}}  # różne warianty, suma 5
    needed_total = {1: 6}
    cov = cm.coverage_for_item(
        _item(1, 6, "total", {"5": 6}), owned, {}, needed_total
    )
    assert cov["variant"] is False
    assert cov["owned"] == 5
    assert cov["needed"] == 6
    assert cov["status"] == "partial"


# ── build_collection_index (DB, izolacja właściciela) ───────────────────────

def test_build_collection_index_groups_by_variant_and_isolates_owner() -> None:
    session = _session()
    try:
        user1 = models.User(username="u1", password_hash="x")
        user2 = models.User(username="u2", password_hash="x")
        session.add_all([user1, user2])
        session.flush()

        def _model(owner, unit_id, count, weapons, slot_weapon=None):
            m = models.CollectionModel(
                owner_id=owner.id,
                unit_id=unit_id,
                count=count,
                loadout_json=json.dumps({"weapons": weapons, "abilities": {}}),
            )
            if slot_weapon is not None:
                m.slots.append(
                    models.CollectionModelSlot(
                        name="slot", selected_weapon_id=slot_weapon, position=0
                    )
                )
            return m

        session.add_all([
            _model(user1, 100, 3, {"5": 1}),            # wariant 5:1
            _model(user1, 100, 1, {"5": 1}),            # wariant 5:1 (sumuje -> 4)
            _model(user1, 100, 2, {"5": 1, "7": 1}),    # wariant 5:1|7:1
            _model(user1, 100, 1, {"5": 1}, slot_weapon=9),  # efektywnie 5:1|9:1
            _model(user2, 100, 10, {"5": 1}),           # inny właściciel — pomijany
            _model(user1, 200, 5, {"3": 1}),            # inny unit
        ])
        session.commit()

        owned = cm.build_collection_index(session, user1.id, [100, 200])

        assert owned[100]["5:1"] == 4
        assert owned[100]["5:1|7:1"] == 2
        assert owned[100]["5:1|9:1"] == 1
        assert owned[200]["3:1"] == 5
        # właściciel 2 nie podbija sumy wariantu 5:1
        assert sum(owned[100].values()) == 7
    finally:
        session.close()


def test_build_collection_index_empty_for_no_units() -> None:
    session = _session()
    try:
        assert cm.build_collection_index(session, 1, []) == {}
    finally:
        session.close()


# ── describe_owned_models (Faza 2b) ─────────────────────────────────────────

def test_describe_owned_models_formats_weapons_and_summary() -> None:
    doubles = [
        SimpleNamespace(
            id=1,
            label="  Zwiadowca  ",
            count=3,
            loadout_json=json.dumps({"weapons": {"5": 2}}),
            slots=[SimpleNamespace(selected_weapon_id=7)],
        ),
        SimpleNamespace(
            id=2,
            label=None,
            count=1,
            loadout_json=json.dumps({"weapons": {}}),
            slots=[],
        ),
    ]
    weapon_names = {5: "Bolter", 7: "Miotacz"}
    out = cm.describe_owned_models(doubles, weapon_names)

    assert out[0] == {
        "id": 1,
        "label": "Zwiadowca",
        "count": 3,
        "weapons": {"5": 2, "7": 1},
        "summary": "Bolter ×2, Miotacz",
    }
    # brak broni → podsumowanie „—", brakująca nazwa broni → fallback
    assert out[1]["label"] == ""
    assert out[1]["summary"] == "—"


def test_describe_owned_models_unknown_weapon_name_fallback() -> None:
    doubles = [
        SimpleNamespace(
            id=9, label="X", count=1,
            loadout_json=json.dumps({"weapons": {"99": 1}}), slots=[],
        )
    ]
    out = cm.describe_owned_models(doubles, {})
    assert out[0]["summary"] == "Broń #99"


def test_fetch_owned_models_isolates_owner_and_unit() -> None:
    session = _session()
    try:
        user1 = models.User(username="u1", password_hash="x")
        user2 = models.User(username="u2", password_hash="x")
        session.add_all([user1, user2])
        session.flush()

        session.add_all([
            models.CollectionModel(owner_id=user1.id, unit_id=100, count=2,
                                   loadout_json="{}", position=1),
            models.CollectionModel(owner_id=user1.id, unit_id=100, count=1,
                                   loadout_json="{}", position=0),
            models.CollectionModel(owner_id=user1.id, unit_id=200, count=5,
                                   loadout_json="{}", position=0),
            models.CollectionModel(owner_id=user2.id, unit_id=100, count=9,
                                   loadout_json="{}", position=0),
        ])
        session.commit()

        rows = cm.fetch_owned_models(session, user1.id, 100)
        # tylko user1 + unit 100; posortowane po position
        assert [r.count for r in rows] == [1, 2]
        assert all(r.owner_id == user1.id and r.unit_id == 100 for r in rows)
    finally:
        session.close()
