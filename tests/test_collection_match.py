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
            slots=[SimpleNamespace(
                id=10, name="Wieżyczka",
                option_weapon_ids_json=json.dumps([7]), selected_weapon_id=7,
            )],
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
        "base_weapons": {"5": 2},
        "slots": [{
            "id": 10, "name": "Wieżyczka", "selected": 7,
            "options": [{"id": 7, "name": "Miotacz"}],
        }],
        "abilities": [],
        "ability_cost": 0.0,
        "summary": "Bolter ×2, Miotacz",
    }
    # brak broni → podsumowanie „—", brakująca nazwa broni → fallback
    assert out[1]["label"] == ""
    assert out[1]["summary"] == "—"
    assert out[1]["base_weapons"] == {} and out[1]["slots"] == []


def test_describe_owned_models_includes_ability_names() -> None:
    doubles = [
        SimpleNamespace(
            id=1, label="Sierżant", count=1,
            loadout_json=json.dumps({"weapons": {"5": 1}, "abilities": {"50": 1, "60:furia|6": 1}}),
            slots=[],
        ),
    ]
    # ability_names keyed by FULL loadout key (z wartością)
    out = cm.describe_owned_models(doubles, {5: "Bolter"}, {"50": "Medyk", "60:furia|6": "Aura: Furia"})
    assert out[0]["abilities"] == ["Medyk", "Aura: Furia"]
    assert out[0]["summary"] == "Bolter • Medyk, Aura: Furia"


def test_describe_owned_models_ability_cost_sums_bare_ids() -> None:
    doubles = [
        SimpleNamespace(
            id=1, label="Sierżant", count=1,
            loadout_json=json.dumps({"weapons": {"5": 1}, "abilities": {"50": 1, "60:furia|6": 1}}),
            slots=[],
        ),
    ]
    # koszt zdolności z mapy bare-id (front dolicza go do bazy + broni)
    out = cm.describe_owned_models(doubles, {5: "Bolter"}, None, {50: 3.0, 60: 4.5})
    assert out[0]["ability_cost"] == 7.5


def test_unit_ability_display_uses_value_with_bare_fallback() -> None:
    from app.services.costs import ability_link_loadout_key
    link = SimpleNamespace(
        ability=SimpleNamespace(id=60, name="Aura", type="aura"),
        params_json=json.dumps({"value": "furia|6"}),
    )
    unit = SimpleNamespace(abilities=[link])
    names = cm.unit_ability_display(unit)
    key = ability_link_loadout_key(link)
    # pełny klucz → nazwa z wartością; goły id → generyczna (fallback np. dla proxy)
    assert "Furia" in names[key]
    assert names["60"] == "Aura"


def test_effective_weapons_mounted_override_validates_options() -> None:
    slot = SimpleNamespace(
        id=10, name="Wieżyczka",
        option_weapon_ids_json=json.dumps([7, 8]), selected_weapon_id=7,
    )
    model = SimpleNamespace(loadout_json=json.dumps({"weapons": {"5": 1}}), slots=[slot])
    # bez mounted → broń bazowa + zapisany slot (7)
    assert cm.collection_model_effective_weapons(model) == {5: 1, 7: 1}
    # mounted → inna dozwolona opcja (8)
    assert cm.collection_model_effective_weapons(model, {"10": 8}) == {5: 1, 8: 1}
    # mounted null → slot pusty
    assert cm.collection_model_effective_weapons(model, {"10": None}) == {5: 1}
    # mounted broń spoza opcji (9) → fallback do zapisanego (7), bez wstrzyknięcia
    assert cm.collection_model_effective_weapons(model, {"10": 9}) == {5: 1, 7: 1}


def test_parse_slots_ability_option_and_mounted_selection() -> None:
    from app.routers.collections import _parse_slots
    form = {
        "slot_name_0": "Ulepszenie",
        "slot_options_0": ["5", "7"],
        "slot_ability_options_0": ["60:furia|6", "99:obce"],  # 99 spoza puli → odrzucone
        "slot_selected_0": "a:60:furia|6",                     # montujemy zdolność
        "slot_name_1": "Broń pokł.",
        "slot_options_1": ["5"],
        "slot_selected_1": "w:5",                              # montujemy broń
    }
    slots = _parse_slots(form, {5, 7}, {"60:furia|6"})
    assert slots[0]["option_weapon_ids"] == [5, 7]
    assert slots[0]["option_ability_keys"] == ["60:furia|6"]  # obca odfiltrowana
    assert slots[0]["selected_ability_key"] == "60:furia|6"
    assert slots[0]["selected_weapon_id"] is None
    assert slots[1]["selected_weapon_id"] == 5
    assert slots[1]["selected_ability_key"] is None


def test_model_ability_keys_includes_slot_mounted_ability() -> None:
    # Magnetyzacja może przełączać zdolność: slot z zamontowaną zdolnością „60:furia|6"
    # dokłada ją do zdolności modelu (obok bazowej „50").
    model = SimpleNamespace(
        loadout_json=json.dumps({"weapons": {"5": 1}, "abilities": {"50": 1}}),
        slots=[SimpleNamespace(
            option_weapon_ids_json=None, selected_weapon_id=None,
            option_ability_keys_json=json.dumps(["60:furia|6", "70"]),
            selected_ability_key="60:furia|6",
        )],
    )
    assert sorted(cm._model_ability_keys(model)) == ["50", "60:furia|6"]
    assert sorted(cm._model_ability_base_ids(model)) == [50, 60]


def test_describe_owned_models_slot_ability_in_summary_and_cost() -> None:
    model = SimpleNamespace(
        id=1, label="Sierżant", count=1,
        loadout_json=json.dumps({"weapons": {"5": 1}}),
        slots=[SimpleNamespace(
            id=9, name="Ulepszenie", option_weapon_ids_json=None, selected_weapon_id=None,
            option_ability_keys_json=json.dumps(["60:furia|6"]),
            selected_ability_key="60:furia|6",
        )],
    )
    out = cm.describe_owned_models([model], {5: "Bolter"},
                                   {"60:furia|6": "Aura: Furia"}, {60: 4.0})
    assert out[0]["abilities"] == ["Aura: Furia"]
    assert out[0]["ability_cost"] == 4.0
    # slot bez opcji broni nie tworzy pustego dropdownu broni w UI mount
    assert out[0]["slots"] == []


def test_describe_owned_models_unknown_weapon_name_fallback() -> None:
    doubles = [
        SimpleNamespace(
            id=9, label="X", count=1,
            loadout_json=json.dumps({"weapons": {"99": 1}}), slots=[],
        )
    ]
    out = cm.describe_owned_models(doubles, {})
    assert out[0]["summary"] == "Broń #99"


def _compose_unit() -> SimpleNamespace:
    return SimpleNamespace(
        weapon_links=[
            SimpleNamespace(weapon_id=5),
            SimpleNamespace(weapon_id=7),
        ],
        default_weapon_id=None,
        abilities=[
            SimpleNamespace(ability=SimpleNamespace(id=50, type="active")),
            SimpleNamespace(ability=SimpleNamespace(id=60, type="aura")),
        ],
    )


def _owned_model(mid: int, weapons: dict, abilities: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        loadout_json=json.dumps({"weapons": weapons, "abilities": abilities or {}}),
        slots=[],
    )


def test_compose_loadout_aggregates_weapons_and_abilities() -> None:
    unit = _compose_unit()
    model = _owned_model(1, {"5": 1}, {"50": 1, "60": 1})  # active 50 + aura 60
    loadout, count = cm.compose_loadout(
        unit, [{"id": 1, "qty": 3}], {"passive": {"masywny": 1}}, {1: model}
    )
    assert count == 3
    assert loadout["weapons"] == {"5": 3}
    assert loadout["active"] == {"50": 3}
    assert loadout["aura"] == {"60": 3}
    assert loadout["mode"] == "total"
    # pasywne zachowane z base_loadout (nie z modeli)
    assert loadout["passive"] == {"masywny": 1}


def test_compose_loadout_proxy_filters_to_unit_pool() -> None:
    unit = _compose_unit()
    # proxy z bronią 7 (w puli) i 999 (spoza puli → odrzucona)
    loadout, count = cm.compose_loadout(
        unit, [{"id": None, "weapons": {"7": 1, "999": 1}, "qty": 2}], {}, {}
    )
    assert count == 2
    assert loadout["weapons"] == {"7": 2}
    assert loadout["active"] == {} and loadout["aura"] == {}


def test_compose_loadout_mixed_owned_and_proxy() -> None:
    unit = _compose_unit()
    model = _owned_model(1, {"5": 1})
    loadout, count = cm.compose_loadout(
        unit,
        [{"id": 1, "qty": 3}, {"id": None, "weapons": {"7": 1}, "qty": 2}],
        {},
        {1: model},
    )
    assert count == 5
    assert loadout["weapons"] == {"5": 3, "7": 2}


def test_compose_loadout_skips_foreign_model_ids() -> None:
    unit = _compose_unit()
    # id 99 nie ma w owned_by_id (cudzy/nieznany) → pominięty (izolacja)
    loadout, count = cm.compose_loadout(unit, [{"id": 99, "qty": 5}], {}, {})
    assert count == 0
    assert loadout["weapons"] == {}


def test_used_in_other_units_sums_owned_excluding_self_and_proxies() -> None:
    roster = SimpleNamespace(roster_units=[
        SimpleNamespace(id=1, unit_id=100, composed_models_json=json.dumps(
            [{"id": 5, "qty": 2}, {"id": 6, "qty": 1}, {"id": None, "weapons": {}, "qty": 3}]
        )),
        SimpleNamespace(id=2, unit_id=100, composed_models_json=json.dumps(
            [{"id": 5, "qty": 1}]
        )),
        SimpleNamespace(id=3, unit_id=200, composed_models_json=json.dumps(
            [{"id": 5, "qty": 9}]
        )),
    ])
    # wykluczamy oddział 2, inny unit (3) pomijany, proxy (id=null) nie liczy się
    used = cm.used_in_other_units(roster, 100, exclude_roster_unit_id=2)
    assert used == {5: 2, 6: 1}


def test_derive_composition_owned_overflow_not_proxy() -> None:
    unit = _compose_unit()
    owned = [_owned_model(1, {"5": 1})]
    # per_model {5:1} × count 5 = total {5:5}; posiadany wariant PASUJE — miękki
    # limit: nadwyżka ponad available 3 to nadal ten model (qty 5), NIE proxy.
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 1}, "mode": "per_model"}, 5, owned, {1: 3}
    )
    assert selection == [{"id": 1, "qty": 5}]


def test_derive_composition_owned_with_extra_weapon_not_used() -> None:
    # Filozofia: agregat = DOKŁADNIE loadout. Posiadany {5,7} ma broń 7 spoza
    # rozpiski {5} → NIE używany (nie dodajemy 7 do sumy), tylko proxy odtwarza {5}.
    unit = _compose_unit()
    owned = [_owned_model(1, {"5": 1, "7": 1})]
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 1}, "mode": "per_model"}, 3, owned, {1: 5}
    )
    assert all(e.get("id") is None for e in selection)
    total: dict[str, int] = {}
    for e in selection:
        for w, c in e["weapons"].items():
            total[w] = total.get(w, 0) + c * int(e["qty"])
    assert total == {"5": 3}  # dokładnie loadout ×3, bez 7


def test_derive_composition_owns_enough_no_proxies() -> None:
    unit = _compose_unit()
    owned = [_owned_model(1, {"5": 1})]
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 1}, "mode": "per_model"}, 3, owned, {1: 10}
    )
    assert selection == [{"id": 1, "qty": 3}]


def test_derive_composition_no_owned_fills_proxies() -> None:
    unit = _compose_unit()
    # brak posiadanych; total {7:2} → proxy odtwarzające broń, dopełnione do count
    selection = cm.derive_composition(
        unit, {"weapons": {"7": 2}, "mode": "total"}, 3, [], {}
    )
    assert all(e.get("id") is None for e in selection)
    assert sum(int(e["qty"]) for e in selection) == 3
    # łączna broń proxy odtwarza agregat {7:2}
    total7 = sum(int(e["qty"]) * e["weapons"].get("7", 0) for e in selection)
    assert total7 == 2


def test_compose_loadout_proxy_carries_abilities() -> None:
    unit = _compose_unit()
    loadout, count = cm.compose_loadout(
        unit, [{"id": None, "weapons": {"5": 1}, "abilities": [50], "qty": 2}], {}, {}
    )
    assert count == 2
    assert loadout["weapons"] == {"5": 2}
    assert loadout["active"] == {"50": 2}  # 50 to active w _compose_unit


def test_derive_composition_owned_partial_variant_not_used() -> None:
    # Posiadany {275,209} ma broń 209 SPOZA rozpiski {182,275} → NIE używany
    # (agregat = dokładnie loadout, bez 209); proxy odtwarza {182,275}×count.
    unit = SimpleNamespace(
        default_weapon_id=182,
        default_weapon_loadout=[(SimpleNamespace(id=182), 1), (SimpleNamespace(id=275), 2)],
    )
    owned = [_owned_model(3, {"275": 2, "209": 1})]
    selection = cm.derive_composition(
        unit, {"weapons": {"182": 1, "275": 2}, "mode": "per_model"}, 3, owned, {3: 1}
    )
    assert all(e.get("id") is None for e in selection)  # model nie użyty (209 spoza)
    total: dict[str, int] = {}
    for e in selection:
        for w, c in e["weapons"].items():
            total[w] = total.get(w, 0) + c * int(e["qty"])
    assert total == {"182": 3, "275": 6}  # dokładnie {182:1,275:2}×3, bez 209


def test_derive_composition_proxy_partitions_no_base_inflation() -> None:
    # Bug (roster 21/unit 270): dodanie broni specjalistycznej klonowało pełny
    # domyślny model → inflacja broni podstawowej (2 Grobowe + 1 Podwójne na 2
    # modele dawało 4 Grobowe). Fix: partycjonuj residual dokładnie.
    # obie bronie to WRĘCZ (ostrza) — metadane zasięgu, by kategoryzacja była poprawna
    unit = SimpleNamespace(
        weapon_links=[
            SimpleNamespace(weapon_id=1, weapon=SimpleNamespace(effective_range="melee")),
            SimpleNamespace(weapon_id=2, weapon=SimpleNamespace(effective_range="melee")),
        ],
        default_weapon_id=1,
        default_weapon_loadout=[(SimpleNamespace(id=1), 2)],  # domyślnie 2× Grobowe
    )
    selection = cm.derive_composition(
        unit, {"weapons": {"1": 2, "2": 1}, "mode": "total"}, 2, [], {}
    )
    assert all(e.get("id") is None for e in selection)
    total: dict[str, int] = {}
    for e in selection:
        for w, c in e["weapons"].items():
            total[w] = total.get(w, 0) + c * int(e["qty"])
    assert total == {"1": 2, "2": 1}, total  # dokładny agregat, NIE 4× Grobowe
    assert sum(int(e["qty"]) for e in selection) == 2
    # ideał: model specjalistyczny (2=Podwójne) osobno, model podstawowy 2× Grobowe (1)
    special = [e for e in selection if "2" in e["weapons"]]
    base = [e for e in selection if "2" not in e["weapons"]]
    assert len(special) == 1 and special[0]["weapons"] == {"2": 1}
    assert len(base) == 1 and base[0]["weapons"] == {"1": 2}


def test_derive_composition_proxy_pairs_melee_ranged() -> None:
    # roster 16: wręcz {Lekka(1):9, Piłomiecz(2):1} + dystans {Hellgun(3):9,
    # Hellpistol(4):1}, 10 modeli. Ideał: 9× {Lekka, Hellgun} + 1× {Piłomiecz,
    # Hellpistol} — każdy model z bronią wręcz, specjaliści sparowani.
    def _w(wid: int, rng: str) -> SimpleNamespace:
        return SimpleNamespace(weapon_id=wid, weapon=SimpleNamespace(effective_range=rng))
    unit = SimpleNamespace(
        weapon_links=[_w(1, "melee"), _w(2, "melee"), _w(3, "24"), _w(4, "12")],
        default_weapon_id=1,
        default_weapon_loadout=[(SimpleNamespace(id=1), 1), (SimpleNamespace(id=3), 1)],
    )
    selection = cm.derive_composition(
        unit, {"weapons": {"1": 9, "2": 1, "3": 9, "4": 1}, "mode": "total"}, 10, [], {}
    )
    total: dict[str, int] = {}
    for e in selection:
        for w, c in e["weapons"].items():
            total[w] = total.get(w, 0) + c * int(e["qty"])
    assert total == {"1": 9, "2": 1, "3": 9, "4": 1}, total
    assert sum(int(e["qty"]) for e in selection) == 10
    special = [e for e in selection if "2" in e["weapons"]]
    assert len(special) == 1 and special[0]["weapons"] == {"2": 1, "4": 1} and int(special[0]["qty"]) == 1
    base = [e for e in selection if "1" in e["weapons"]]
    assert len(base) == 1 and base[0]["weapons"] == {"1": 1, "3": 1} and int(base[0]["qty"]) == 9


def test_derive_composition_picks_matching_mount() -> None:
    # Model magnetyzowany (Sentinel): slot z opcjami {Miotacz(7), Działo Plazmowe(8)},
    # ZAPISANY=8. Loadout ma 7 → derywacja przypisuje model z mounted slot=7 (nie 8).
    slot = SimpleNamespace(
        id=10, name="Wieżyczka",
        option_weapon_ids_json=json.dumps([7, 8]), selected_weapon_id=8,
    )
    model = SimpleNamespace(
        id=1, label="Sentinel", loadout_json=json.dumps({"weapons": {"5": 1}}), slots=[slot],
    )
    unit = SimpleNamespace(
        default_weapon_id=5, default_weapon_loadout=[(SimpleNamespace(id=5), 1)],
    )
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 1, "7": 1}, "mode": "total"}, 1, [model], {1: 1}
    )
    assert selection == [{"id": 1, "qty": 1, "mounted": {"10": 7}}]


def test_derive_composition_two_magnetized_models_different_mounts() -> None:
    # 2 identyczne Sentinele, slot opcje {7,8}; loadout potrzebuje OBU (7 i 8) →
    # oba przypisane jako POSIADANE, każdy z innym mountem (nie owned+proxy).
    def _sentinel(mid: int) -> SimpleNamespace:
        slot = SimpleNamespace(
            id=10, name="Główna",
            option_weapon_ids_json=json.dumps([7, 8]), selected_weapon_id=7,
        )
        return SimpleNamespace(
            id=mid, label="Sentinel",
            loadout_json=json.dumps({"weapons": {"5": 1}}), slots=[slot],
        )
    unit = SimpleNamespace(
        default_weapon_id=5, default_weapon_loadout=[(SimpleNamespace(id=5), 1)],
    )
    owned = [_sentinel(1), _sentinel(2)]
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 2, "7": 1, "8": 1}, "mode": "total"}, 2, owned, {1: 1, 2: 1}
    )
    assert all(e.get("id") is not None for e in selection), selection  # oba posiadane
    mounts = sorted(next(iter(e["mounted"].values())) for e in selection)
    assert mounts == [7, 8]  # jeden Sentinel z 7, drugi z 8
    assert sum(int(e["qty"]) for e in selection) == 2


def test_derive_composition_one_magnetized_model_extra_mount_is_proxy() -> None:
    # 1 fizyczny Sentinel (available 1); loadout potrzebuje 2 różnych mountów (7 i 8)
    # na 2 modele → 1 posiadany (mount 7) + PROXY z bronią 8 (NIE nadwyżka tego
    # samego modelu z innym mountem — front trzyma jeden mount na model).
    slot = SimpleNamespace(
        id=10, name="Główna",
        option_weapon_ids_json=json.dumps([7, 8]), selected_weapon_id=7,
    )
    model = SimpleNamespace(
        id=1, label="Sentinel",
        loadout_json=json.dumps({"weapons": {"5": 1}}), slots=[slot],
    )
    unit = SimpleNamespace(
        default_weapon_id=5, default_weapon_loadout=[(SimpleNamespace(id=5), 1)],
    )
    selection = cm.derive_composition(
        unit, {"weapons": {"5": 2, "7": 1, "8": 1}, "mode": "total"}, 2, [model], {1: 1}
    )
    owned = [e for e in selection if e.get("id") == 1]
    proxy = [e for e in selection if e.get("id") is None]
    assert len(owned) == 1 and owned[0]["mounted"] == {"10": 7} and int(owned[0]["qty"]) == 1
    assert len(proxy) == 1 and proxy[0]["weapons"].get("8") == 1  # inny mount jako proxy
    assert sum(int(e["qty"]) for e in selection) == 2


def test_derive_composition_base_weapon_not_cloned_by_slot() -> None:
    # Bug (roster 16/RU200): 2 Sentinele, każdy baza {Miażdżenie(275):2, Miotacz(182):1}
    # + slot „Główna" z opcją 182. Loadout total {182:2, 275:4}, 2 modele. Baza obu
    # modeli daje DOKŁADNIE {182:2, 275:4} — slot NIE może domontować 3. Miotacza
    # (co dawniej robiło owned z 2 Miotaczami + proxy z Miażdżeniem). Oba posiadane,
    # sloty puste, bez proxy.
    def _sentinel(mid: int) -> SimpleNamespace:
        slot = SimpleNamespace(
            id=5, name="Główna",
            option_weapon_ids_json=json.dumps([182, 209, 215, 221]), selected_weapon_id=182,
        )
        return SimpleNamespace(
            id=mid, label="Sentinel",
            loadout_json=json.dumps({"weapons": {"275": 2, "182": 1}}), slots=[slot],
        )
    unit = SimpleNamespace(
        weapon_links=[
            SimpleNamespace(weapon_id=182, weapon=SimpleNamespace(effective_range="18")),
            SimpleNamespace(weapon_id=275, weapon=SimpleNamespace(effective_range="melee")),
        ],
        default_weapon_id=275,
        default_weapon_loadout=[(SimpleNamespace(id=275), 2)],
    )
    owned = [_sentinel(3), _sentinel(6)]
    selection = cm.derive_composition(
        unit, {"weapons": {"182": 2, "275": 4}, "mode": "total"}, 2, owned, {3: 1, 6: 1}
    )
    assert all(e.get("id") is not None for e in selection), selection  # oba posiadane, brak proxy
    assert sum(int(e["qty"]) for e in selection) == 2
    # sloty puste (baza pokrywa) — żaden mount nie dokłada Miotacza
    for e in selection:
        assert all(v is None for v in (e.get("mounted") or {}).values()), e
    # agregat = dokładnie loadout
    total: dict[str, int] = {}
    for e in selection:
        eff = dict(cm.collection_model_effective_weapons(
            next(m for m in owned if m.id == e["id"]),
            e.get("mounted"),
        ))
        for w, c in eff.items():
            total[str(w)] = total.get(str(w), 0) + c * int(e["qty"])
    assert total == {"182": 2, "275": 4}, total


def test_derive_composition_duplicate_entries_do_not_block_needed_mount() -> None:
    # Bug (code-review #1): 2 SKOPIOWANE wpisy (przycisk „Kopiuj"), każdy avail=2,
    # count=2. base_supply liczone z NAJWYŻEJ count modeli — inaczej K×count zawyżało
    # podaż, zerowało mount_need i potrzebny mount 7 szedł jako fałszywe proxy.
    # Loadout {7:3} = 2 bazowe (po 1 na model) + 1 zamontowany. Oczekiwane: oba
    # posiadane, jeden montuje 7, brak proxy.
    def _mdl(mid: int) -> SimpleNamespace:
        slot = SimpleNamespace(id=9, name="Hardpoint",
                               option_weapon_ids_json=json.dumps([7]), selected_weapon_id=None)
        return SimpleNamespace(id=mid, label="Walker",
                               loadout_json=json.dumps({"weapons": {"7": 1}}), slots=[slot])
    unit = SimpleNamespace(
        weapon_links=[SimpleNamespace(weapon_id=7, weapon=SimpleNamespace(effective_range="18"))],
        default_weapon_id=7, default_weapon_loadout=[(SimpleNamespace(id=7), 1)],
    )
    owned = [_mdl(1), _mdl(2)]
    selection = cm.derive_composition(
        unit, {"weapons": {"7": 3}, "mode": "total"}, 2, owned, {1: 2, 2: 2}
    )
    assert all(e.get("id") is not None for e in selection), selection  # brak proxy
    total = 0
    for e in selection:
        eff = cm.collection_model_effective_weapons(
            next(m for m in owned if m.id == e["id"]), e.get("mounted"))
        total += eff.get(7, 0) * int(e["qty"])
    assert total == 3, selection  # 2 bazowe + 1 zamontowany, dokładnie loadout


def test_best_mount_effective_two_slots_same_weapon_respects_budget() -> None:
    # Bug (code-review #3): model z DWOMA slotami tej samej broni (7) nie może
    # zamontować jej dwa razy ponad mount_need=1 (drugi slot pusty).
    slot_a = SimpleNamespace(id=1, name="Lewy",
                             option_weapon_ids_json=json.dumps([7]), selected_weapon_id=None)
    slot_b = SimpleNamespace(id=2, name="Prawy",
                             option_weapon_ids_json=json.dumps([7]), selected_weapon_id=None)
    model = SimpleNamespace(loadout_json=json.dumps({"weapons": {}}), slots=[slot_a, slot_b])
    eff, mounted = cm._best_mount_effective(model, {7: 2}, {7: 1})
    assert eff.get(7, 0) == 1  # tylko JEDEN mount w ramach budżetu
    assert sorted(mounted.values(), key=lambda v: v is None) == [7, None]


def test_derive_composition_matches_model_with_ability() -> None:
    unit = _compose_unit()
    with_ability = _owned_model(1, {"5": 1}, {"50": 1})
    plain = _owned_model(2, {"5": 1})
    selection = cm.derive_composition(
        unit,
        {"weapons": {"5": 2}, "active": {"50": 1}, "mode": "total"},
        2, [with_ability, plain], {1: 1, 2: 5},
    )
    # model ze zdolnością 50 wybrany do pokrycia zdolności; brak proxy (są modele)
    assert {"id": 1, "qty": 1} in selection
    assert all(e.get("id") is not None for e in selection)


def test_derive_composition_proxy_for_missing_ability() -> None:
    unit = _compose_unit()
    # brak posiadanych ze zdolnością 50 → proxy niosące tę zdolność
    selection = cm.derive_composition(
        unit, {"active": {"50": 1}, "weapons": {}, "mode": "total"}, 1, [], {}
    )
    assert selection == [{"id": None, "weapons": {}, "abilities": [50], "qty": 1}]


def test_composition_groups_groups_by_variant_sorted_by_cost() -> None:
    owned = {
        1: _owned_model(1, {"5": 1}, {"50": 1}),  # Bolter + Medyk
        2: _owned_model(2, {"7": 1}),             # Karabin
    }
    selection = [
        {"id": 1, "qty": 2},
        {"id": 2, "qty": 1},
        {"id": None, "weapons": {"9": 1}, "abilities": [60], "qty": 1},  # proxy Plazma+Aura
        {"id": 99, "qty": 5},  # obcy → pomijany
    ]
    groups = cm.composition_groups(
        selection, owned,
        weapon_names={5: "Bolter", 7: "Karabin", 9: "Plazma"},
        ability_names={"50": "Medyk", "60": "Aura"},
        weapon_cost_map={5: 2.0, 7: 1.0, 9: 5.0},
        ability_cost_map={50: 3.0, 60: 4.0},
    )
    # sort rosnąco po koszcie: Karabin(1.0) < Bolter+Medyk(5.0) < Plazma+Aura(9.0)
    assert [g["summary"] for g in groups] == ["Karabin", "Bolter • Medyk", "Plazma • Aura"]
    assert [g["count"] for g in groups] == [1, 2, 1]
    assert [g["cost"] for g in groups] == [1.0, 5.0, 9.0]
    assert groups[1]["weapons"] == {"5": 1} and groups[1]["abilities"] == [50]


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
