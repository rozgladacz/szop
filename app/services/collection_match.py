"""Dopasowanie kolekcji fizycznych modeli do potrzeb rozpiski (Kolekcja Faza 2).

Kierunek **suma → modele** (read-only): z agregatu RosterUnit wyliczamy ile
posiadanych modeli pokrywa zapotrzebowanie rozpiski. Bez zmian schematu — całość
liczona przy renderowaniu edytora. Kierunek modele → suma (kompozycja, write)
dochodzi w etapie 2b i też korzysta z podpisu wariantu tutaj zdefiniowanego.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models


def _coerce_int(value: Any) -> int | None:
    # Klucze/liczniki loadoutu to zawsze int lub int-stringi ("5") — float-fallback
    # zbędny.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _weapon_multiset(weapons: Any) -> dict[int, int]:
    """Sprowadza mapę {weapon_id: count} do {int_id: dodatni int count}."""
    result: dict[int, int] = {}
    if not isinstance(weapons, dict):
        return result
    for raw_id, raw_count in weapons.items():
        wid = _coerce_int(raw_id)
        cnt = _coerce_int(raw_count)
        if wid is None or cnt is None or cnt <= 0:
            continue
        result[wid] = result.get(wid, 0) + cnt
    return result


def model_variant_signature(weapons: Any) -> str:
    """Kanoniczny, niezależny od kolejności klucz wariantu per-modelowego loadoutu.

    Uzbrojenie (broń) jest fizycznym wyróżnikiem dwóch poza tym identycznych
    modeli. Zdolności są na razie celowo pominięte: rozpiska i kolekcja trzymają
    klucze zdolności w różnych przestrzeniach (gołe ability_id vs
    ``ability_link_loadout_key``), a sama broń oddaje „wariant wyposażenia", o
    który prosił użytkownik. Rozszerzenie podpisu później jest bezpieczne — nic
    go nie utrwala (pokrycie liczone na każde załadowanie strony).
    """
    multiset = _weapon_multiset(weapons)
    if not multiset:
        return "∅"  # modele „gołe" (brak broni)
    return "|".join(f"{wid}:{multiset[wid]}" for wid in sorted(multiset))


def collection_model_effective_weapons(cm: models.CollectionModel) -> dict[int, int]:
    """Broń bazowa z loadoutu + aktualnie zamontowane bronie ze slotów magnetyzacji."""
    try:
        loadout = json.loads(cm.loadout_json) if cm.loadout_json else {}
    except (json.JSONDecodeError, TypeError):
        loadout = {}
    weapons = _weapon_multiset(loadout.get("weapons") if isinstance(loadout, dict) else None)
    for slot in cm.slots:
        wid = slot.selected_weapon_id
        if wid is not None:
            weapons[int(wid)] = weapons.get(int(wid), 0) + 1
    return weapons


def build_collection_index(
    db: Session, owner_id: int, unit_ids: Iterable[int]
) -> dict[int, dict[str, int]]:
    """``owned[unit_id][signature]`` = liczba posiadanych modeli danego wariantu.

    Tylko `CollectionModel` należące do `owner_id` (izolacja właściciela).
    """
    ids = [int(u) for u in {u for u in unit_ids if u is not None}]
    owned: dict[int, dict[str, int]] = {}
    if not ids:
        return owned
    rows = (
        db.execute(
            select(models.CollectionModel)
            .where(
                models.CollectionModel.owner_id == owner_id,
                models.CollectionModel.unit_id.in_(ids),
            )
            .options(selectinload(models.CollectionModel.slots))
        )
        .scalars()
        .unique()
        .all()
    )
    for cm in rows:
        cnt = int(cm.count or 0)
        if cnt <= 0:
            continue
        sig = model_variant_signature(collection_model_effective_weapons(cm))
        unit_map = owned.setdefault(cm.unit_id, {})
        unit_map[sig] = unit_map.get(sig, 0) + cnt
    return owned


def roster_needs(
    roster_items: Iterable[dict[str, Any]],
) -> tuple[dict[int, dict[str, int]], dict[int, int]]:
    """Zapotrzebowanie rozpiski na fizyczne modele.

    Zwraca ``(needed_by_variant, needed_total)``:
    - ``needed_by_variant[unit_id][signature]`` — suma `count` oddziałów w trybie
      ``per_model`` o danym wariancie (agregacja po duplikatach oddziału).
    - ``needed_total[unit_id]`` — suma `count` WSZYSTKICH oddziałów (oba tryby);
      dla oddziałów ``total`` (broń zbiorcza) brak rozbicia na warianty, więc
      liczą się tylko do sumy.
    """
    by_variant: dict[int, dict[str, int]] = {}
    total: dict[int, int] = {}
    for item in roster_items:
        ru = item.get("instance")
        if ru is None:
            continue
        unit_id = getattr(ru, "unit_id", None)
        if unit_id is None:
            continue
        count = int(getattr(ru, "count", 0) or 0)
        if count <= 0:
            continue
        total[unit_id] = total.get(unit_id, 0) + count
        loadout = item.get("loadout") or {}
        mode = str(loadout.get("mode") or "per_model").strip().lower()
        if mode == "total":
            continue
        sig = model_variant_signature(loadout.get("weapons"))
        variant_map = by_variant.setdefault(unit_id, {})
        variant_map[sig] = variant_map.get(sig, 0) + count
    return by_variant, total


def _coverage_payload(have: int, need: int, *, variant: bool, summary: str | None) -> dict[str, Any]:
    if have <= 0:
        status = "missing"
    elif have >= need:
        status = "covered"
    else:
        status = "partial"
    return {
        "status": status,
        "owned": have,
        "needed": need,
        "variant": variant,  # False => tryb total, pokrycie tylko liczbowe
        "summary": (summary or "").strip(),
    }


def coverage_for_item(
    item: dict[str, Any],
    owned: dict[int, dict[str, int]],
    needed_by_variant: dict[int, dict[str, int]],
    needed_total: dict[int, int],
) -> dict[str, Any] | None:
    """Pokrycie kolekcji dla pojedynczej karty oddziału w edytorze.

    Tryb ``per_model``: porównanie posiadanych vs potrzebnych modeli danego
    wariantu (zagregowane po całej rozpisce). Tryb ``total``: porównanie liczbowe
    sum dla całego typu oddziału (bez rozbicia na warianty).
    """
    ru = item.get("instance")
    if ru is None:
        return None
    unit_id = getattr(ru, "unit_id", None)
    if unit_id is None:
        return None
    count = int(getattr(ru, "count", 0) or 0)
    if count <= 0:
        return None

    owned_unit = owned.get(unit_id, {})
    loadout = item.get("loadout") or {}
    mode = str(loadout.get("mode") or "per_model").strip().lower()
    summary = item.get("loadout_summary")

    if mode == "total":
        have = sum(owned_unit.values())
        need = needed_total.get(unit_id, count)
        return _coverage_payload(have, need, variant=False, summary=summary)

    sig = model_variant_signature(loadout.get("weapons"))
    have = owned_unit.get(sig, 0)
    need = needed_by_variant.get(unit_id, {}).get(sig, count)
    return _coverage_payload(have, need, variant=True, summary=summary)


# ── Faza 2b: komponowanie oddziału z modeli (modele → suma) ─────────────────

def fetch_owned_models(
    db: Session, owner_id: int, unit_id: int
) -> list[models.CollectionModel]:
    """Modele kolekcji danego użytkownika dla danego typu oddziału (ze slotami)."""
    return (
        db.execute(
            select(models.CollectionModel)
            .where(
                models.CollectionModel.owner_id == owner_id,
                models.CollectionModel.unit_id == unit_id,
            )
            .options(selectinload(models.CollectionModel.slots))
            .order_by(models.CollectionModel.position, models.CollectionModel.id)
        )
        .scalars()
        .unique()
        .all()
    )


def describe_owned_models(
    collection_models: Iterable[models.CollectionModel],
    weapon_names: dict[int, str],
    ability_names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Formatuje modele do wyboru w „Trybie modeli": efektywna broń + zdolności.

    ``weapons`` to efektywne uzbrojenie (bazowe + zamontowane sloty) jako
    ``{str(weapon_id): count}`` — frontend sumuje je do agregatu oddziału.
    ``summary`` zawiera broń oraz (po „•") nazwy zdolności niesionych przez model.
    """
    ability_names = ability_names or {}
    result: list[dict[str, Any]] = []
    for cm in collection_models:
        weapons = collection_model_effective_weapons(cm)
        weapon_parts = []
        for wid in sorted(weapons):
            name = weapon_names.get(wid, f"Broń #{wid}")
            cnt = weapons[wid]
            weapon_parts.append(f"{name} ×{cnt}" if cnt > 1 else name)
        ability_labels = [
            ability_names[bid] for bid in _model_ability_base_ids(cm) if bid in ability_names
        ]
        summary = ", ".join(weapon_parts) if weapon_parts else "—"
        if ability_labels:
            summary += " • " + ", ".join(ability_labels)
        result.append({
            "id": cm.id,
            "label": (cm.label or "").strip(),
            "count": int(cm.count or 0),
            "weapons": {str(wid): cnt for wid, cnt in weapons.items()},
            "abilities": ability_labels,
            "summary": summary,
        })
    return result


# ── Faza 2b.1: agregacja serwerowa (modele → suma), zdolności, proxy ─────────

def _unit_weapon_ids(unit: models.Unit) -> set[int]:
    """Pula dozwolonej broni oddziału (do walidacji broni proxy)."""
    ids: set[int] = set()
    for link in getattr(unit, "weapon_links", []) or []:
        if getattr(link, "weapon_id", None) is not None:
            ids.add(int(link.weapon_id))
    default_id = getattr(unit, "default_weapon_id", None)
    if default_id is not None:
        ids.add(int(default_id))
    return ids


def _unit_ability_types(unit: models.Unit) -> dict[int, str]:
    """``ability_id -> type`` ('active'/'aura'/'passive') dla zdolności oddziału."""
    out: dict[int, str] = {}
    for link in getattr(unit, "abilities", []) or []:
        ability = getattr(link, "ability", None)
        aid = getattr(ability, "id", None)
        if ability is None or aid is None:
            continue
        out[int(aid)] = ability.type
    return out


def _model_ability_base_ids(cm: models.CollectionModel) -> list[int]:
    """Bare ability_id niesione przez model (klucz `ability_link_loadout_key` → id)."""
    try:
        loadout = json.loads(cm.loadout_json) if cm.loadout_json else {}
    except (json.JSONDecodeError, TypeError):
        loadout = {}
    abilities = loadout.get("abilities") if isinstance(loadout, dict) else None
    ids: list[int] = []
    if isinstance(abilities, dict):
        for key, val in abilities.items():
            if not val:
                continue
            bid = _coerce_int(str(key).split(":", 1)[0])
            if bid is not None:
                ids.append(bid)
    return ids


def compose_loadout(
    unit: models.Unit,
    selection: Iterable[dict[str, Any]],
    base_loadout: dict[str, Any] | None,
    owned_by_id: dict[int, models.CollectionModel],
) -> tuple[dict[str, Any], int]:
    """Agreguje wybór modeli w loadout oddziału (modele → suma).

    - ``selection``: lista wpisów ``{id, qty}`` (posiadany model) lub
      ``{id: None, weapons: {...}, qty}`` (proxy z jawną bronią).
    - Broń: posiadane = efektywna broń × qty; proxy = ``weapons`` ∩ pula oddziału × qty.
    - Zdolności: aktywne/aury z posiadanych modeli (bare id) × qty; pasywne pominięte
      (ogólnooddziałowe — zostają z ``base_loadout``). Proxy bez zdolności (v1).
    - ``mode='total'``; ``passive`` zachowane z ``base_loadout``.
    Zwraca ``(loadout_dict, count)`` gdzie ``count = Σ qty``.

    Izolacja właściciela: ``owned_by_id`` zawiera wyłącznie modele bieżącego
    użytkownika dla tego oddziału; obce/nieznane id są pomijane.

    Ograniczenie: zdolności agregowane są po **bare id** — warianty
    parametryzowane (np. ``"50:furia|6"``) kolapsują do bazowego id (tracąc
    parametr), zgodnie z formatem sekcji ``active``/``aura`` loadoutu rozpiski.
    """
    valid_weapon_ids = _unit_weapon_ids(unit)
    ability_types = _unit_ability_types(unit)
    weapons: dict[str, int] = {}
    active: dict[str, int] = {}
    aura: dict[str, int] = {}
    count = 0

    def _add_abilities(base_ids: Iterable[Any], qty: int) -> None:
        for raw in base_ids:
            bid = _coerce_int(raw)
            if bid is None:
                continue
            section = ability_types.get(bid)
            if section == "active":
                active[str(bid)] = active.get(str(bid), 0) + qty
            elif section == "aura":
                aura[str(bid)] = aura.get(str(bid), 0) + qty

    for entry in selection or []:
        if not isinstance(entry, dict):
            continue
        qty = _coerce_int(entry.get("qty")) or 0
        if qty <= 0:
            continue
        cm_id = _coerce_int(entry.get("id")) if entry.get("id") is not None else None
        if cm_id is not None:
            cm = owned_by_id.get(cm_id)
            if cm is None:
                continue  # obcy/nieznany model — pomijamy (izolacja właściciela)
            count += qty
            for wid, c in collection_model_effective_weapons(cm).items():
                weapons[str(wid)] = weapons.get(str(wid), 0) + qty * c
            _add_abilities(_model_ability_base_ids(cm), qty)
        else:
            count += qty
            for wid, c in _weapon_multiset(entry.get("weapons")).items():
                if wid in valid_weapon_ids:
                    weapons[str(wid)] = weapons.get(str(wid), 0) + qty * c
            _add_abilities(entry.get("abilities") or [], qty)
    loadout = dict(base_loadout) if isinstance(base_loadout, dict) else {}
    loadout["weapons"] = weapons
    loadout["active"] = active
    loadout["aura"] = aura
    loadout["mode"] = "total"
    return loadout, count


def parse_selection(raw: Any) -> list[dict[str, Any]]:
    """Parsuje ``composed_models_json`` do listy wpisów (puste przy błędzie)."""
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def used_in_other_units(
    roster: models.Roster, unit_id: int, exclude_roster_unit_id: int | None
) -> dict[int, int]:
    """Ile sztuk każdego CollectionModel jest już użyte w INNYCH oddziałach tej
    rozpiski o tym samym ``unit_id`` (wpisy proxy ``id=null`` nie zużywają puli)."""
    used: dict[int, int] = {}
    for ru in getattr(roster, "roster_units", []) or []:
        if getattr(ru, "unit_id", None) != unit_id:
            continue
        if exclude_roster_unit_id is not None and ru.id == exclude_roster_unit_id:
            continue
        for entry in parse_selection(getattr(ru, "composed_models_json", None)):
            cid = _coerce_int(entry.get("id")) if entry.get("id") is not None else None
            if cid is None:
                continue
            qty = _coerce_int(entry.get("qty")) or 0
            if qty > 0:
                used[cid] = used.get(cid, 0) + qty
    return used


def derive_composition(
    unit: models.Unit,
    current_loadout: dict[str, Any] | None,
    count: int,
    owned_models: list[models.CollectionModel],
    available: dict[int, int],
) -> list[dict[str, Any]]:
    """Best-effort suma→modele: odtwórz oddział (broń + zdolności) jako selekcję
    modeli, preferując posiadane; braki uzupełnij proxy budowanymi z „domyślnego
    modelu" + brakująca zdolność/broń. Proxy = pełny model w ramach `count` (bez
    zawyżania liczności). Punkt startowy — user koryguje miękkimi limitami.

    Kolejność (wg ustaleń): 1) zdolności (model z pasującą zdolnością i bronią
    obecną w oddziale), 2) broń nie-podstawowa, 3) broń podstawowa, 4) dopełnienie.

    Heurystyka proxy (best-effort): broń poszukiwaną wstawiamy do „domyślnego
    modelu" PODMIENIAJĄC główną broń domyślną, ale tylko gdy model ma >1 broni —
    przy jednej domyślnej broni DODAJEMY (by nie zgubić ostatniej, np. lekkiej
    broni ręcznej). Zdolności jak w ``compose_loadout`` (bare id).
    """
    cl = current_loadout or {}
    raw = _weapon_multiset(cl.get("weapons"))
    mode = str(cl.get("mode") or "per_model").strip().lower()
    multiplier = 1 if mode == "total" else max(int(count), 1)
    weapon_target = {wid: c * multiplier for wid, c in raw.items()}

    # Zdolności do odtworzenia (aktywne + aury, bare id) z agregatu oddziału.
    ability_target: dict[int, int] = {}
    for section in ("active", "aura"):
        sec = cl.get(section)
        if isinstance(sec, dict):
            for raw_aid, cnt in sec.items():
                aid = _coerce_int(str(raw_aid).split(":", 1)[0])
                n = _coerce_int(cnt) or 0
                if aid is not None and n > 0:
                    ability_target[aid] = ability_target.get(aid, 0) + n

    # „Domyślny model" — baza proxy: domyślne uzbrojenie oddziału.
    default_weapons: dict[int, int] = {}
    for weapon, c in getattr(unit, "default_weapon_loadout", []) or []:
        wid = getattr(weapon, "id", None)
        if wid is not None and int(c) > 0:
            default_weapons[int(wid)] = default_weapons.get(int(wid), 0) + int(c)
    default_wids = set(default_weapons)
    default_weapon_id = getattr(unit, "default_weapon_id", None)
    primary_default = (
        int(default_weapon_id)
        if default_weapon_id in default_weapons
        else (max(default_weapons, key=default_weapons.get) if default_weapons else None)
    )

    avail = {cm.id: int(available.get(cm.id, 0)) for cm in owned_models}
    weapons_of = {cm.id: collection_model_effective_weapons(cm) for cm in owned_models}
    abilities_of = {cm.id: set(_model_ability_base_ids(cm)) for cm in owned_models}

    sel: dict[int, int] = {}
    proxy_entries: list[dict[str, Any]] = []
    assigned = 0

    def _overlap(cm_id: int) -> int:
        return sum(min(c, weapon_target.get(w, 0)) for w, c in weapons_of[cm_id].items())

    def _consume_weapons(ew: dict[int, int]) -> None:
        for wid, c in ew.items():
            if wid in weapon_target:
                weapon_target[wid] = max(weapon_target[wid] - c, 0)
                if weapon_target[wid] == 0:
                    weapon_target.pop(wid, None)

    def _consume_abilities(aids: Iterable[int]) -> None:
        for aid in aids:
            if aid in ability_target:
                ability_target[aid] = max(ability_target[aid] - 1, 0)
                if ability_target[aid] == 0:
                    ability_target.pop(aid, None)

    def assign_owned(cm_id: int) -> None:
        nonlocal assigned
        sel[cm_id] = sel.get(cm_id, 0) + 1
        avail[cm_id] -= 1
        assigned += 1
        _consume_weapons(weapons_of[cm_id])
        _consume_abilities(abilities_of[cm_id])

    def _sought_nondefault_weapon() -> int | None:
        for wid in sorted(weapon_target):
            if wid not in default_wids and weapon_target[wid] > 0:
                return wid
        return None

    def add_proxy(ability: int | None, weapon: int | None) -> None:
        nonlocal assigned
        pw = dict(default_weapons)
        if weapon is not None and weapon not in default_wids:
            # Podmień główną broń domyślną na poszukiwaną, zachowując pozostałe
            # (np. lekką broń ręczną). Gdy domyślny model ma tylko jedną broń —
            # DODAJ (nie gub ostatniej).
            if primary_default is not None and pw.get(primary_default) and len(pw) > 1:
                pw[primary_default] -= 1
                if pw[primary_default] <= 0:
                    pw.pop(primary_default, None)
            pw[weapon] = pw.get(weapon, 0) + 1
        abilities = [ability] if ability is not None else []
        proxy_entries.append({
            "id": None,
            "weapons": {str(w): c for w, c in pw.items()},
            "abilities": abilities,
            "qty": 1,
        })
        assigned += 1
        _consume_weapons(pw)
        _consume_abilities(abilities)

    # STEP 1: zdolności — model z pasującą zdolnością (preferuj z bronią obecną w
    # oddziale); brak → proxy z domyślnego modelu + ta zdolność (+ szukana broń).
    for aid in list(ability_target):
        while ability_target.get(aid, 0) > 0 and assigned < count:
            cands = [cm.id for cm in owned_models if aid in abilities_of[cm.id] and avail[cm.id] > 0]
            if cands:
                assign_owned(max(cands, key=_overlap))
            else:
                add_proxy(ability=aid, weapon=_sought_nondefault_weapon())

    # STEP 2-3: broń nie-podstawowa najpierw, potem podstawowa.
    ordered_weapons = sorted(w for w in weapon_target if w not in default_wids)
    ordered_weapons += sorted(w for w in weapon_target if w in default_wids)
    for wid in ordered_weapons:
        while weapon_target.get(wid, 0) > 0 and assigned < count:
            cands = [cm.id for cm in owned_models if wid in weapons_of[cm.id] and avail[cm.id] > 0]
            if cands:
                assign_owned(max(cands, key=_overlap))
            else:
                add_proxy(ability=None, weapon=wid)

    # STEP 4: dopełnij liczność posiadanymi (overlap) albo domyślnymi proxy.
    while assigned < count:
        cands = [cm.id for cm in owned_models if avail[cm.id] > 0]
        if cands:
            assign_owned(max(cands, key=_overlap))
        else:
            add_proxy(ability=None, weapon=None)

    selection: list[dict[str, Any]] = [{"id": cid, "qty": q} for cid, q in sel.items() if q > 0]
    selection.extend(proxy_entries)
    return selection
