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
from ..data import abilities as ability_catalog
from .costs import ability_link_loadout_key, normalize_range_value


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


def _model_base_weapons(cm: models.CollectionModel) -> dict[int, int]:
    """Broń bazowa modelu (z `loadout_json.weapons`, bez slotów magnetyzacji)."""
    try:
        loadout = json.loads(cm.loadout_json) if cm.loadout_json else {}
    except (json.JSONDecodeError, TypeError):
        loadout = {}
    return _weapon_multiset(loadout.get("weapons") if isinstance(loadout, dict) else None)


def _slot_option_ids(slot: models.CollectionModelSlot) -> set[int]:
    """Dozwolone bronie slotu magnetyzacji (z `option_weapon_ids_json`)."""
    try:
        ids = json.loads(slot.option_weapon_ids_json) if slot.option_weapon_ids_json else []
    except (json.JSONDecodeError, TypeError):
        ids = []
    if not isinstance(ids, list):
        return set()
    return {w for w in (_coerce_int(x) for x in ids) if w is not None}


def collection_model_effective_weapons(
    cm: models.CollectionModel, mounted: dict[str, Any] | None = None
) -> dict[int, int]:
    """Broń bazowa + zamontowane bronie ze slotów magnetyzacji.

    ``mounted`` (opcjonalny override per-oddział, `{str(slot_id): weapon_id|null}`)
    nadpisuje zamontowaną broń wybranego slotu — waliduje ją względem opcji slotu
    (obca/nieznana → fallback do zapisanej `selected_weapon_id`; ``null`` = slot
    pusty). Bez ``mounted`` używa zapisanej konfiguracji modelu (jak w Kolekcji).
    """
    weapons = _model_base_weapons(cm)
    mounted_map = mounted if isinstance(mounted, dict) else None
    for slot in cm.slots:
        wid = slot.selected_weapon_id
        if mounted_map is not None and str(slot.id) in mounted_map:
            raw = mounted_map.get(str(slot.id))
            if raw is None:
                wid = None  # jawnie pusty slot
            else:
                chosen = _coerce_int(raw)
                if chosen is not None and chosen in _slot_option_ids(slot):
                    wid = chosen
                # nieprawidłowa opcja → zostaje zapisana (izolacja przed obcą bronią)
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
    ability_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Formatuje modele do wyboru w „Trybie modeli": efektywna broń + zdolności.

    ``weapons`` to efektywne uzbrojenie (bazowe + zamontowane sloty) jako
    ``{str(weapon_id): count}`` — podgląd dla modeli bez slotów; dla modeli ze
    slotami frontend przelicza z ``base_weapons`` + wyborów ``slots``. ``summary``
    zawiera broń oraz (po „•") nazwy zdolności. ``ability_names`` mapuje **pełny
    klucz zdolności** → nazwa display (z wartością, np. „Aura: Kontra").
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
        ability_labels = []
        for k in _model_ability_keys(cm):
            # Pełny klucz (z wartością); gdy nieznany (np. armia zmieniła wartość
            # po rejestracji modelu) — fallback do nazwy po gołym id, spójnie z
            # composition_groups (zamiast pomijać zdolność).
            name = ability_names.get(k) or ability_names.get(k.split(":", 1)[0])
            if name:
                ability_labels.append(name)
        summary = ", ".join(weapon_parts) if weapon_parts else "—"
        if ability_labels:
            summary += " • " + ", ".join(ability_labels)
        slots = [
            {
                "id": slot.id,
                "name": slot.name,
                "selected": slot.selected_weapon_id,
                "options": [
                    {"id": oid, "name": weapon_names.get(oid, f"Broń #{oid}")}
                    for oid in sorted(_slot_option_ids(slot))
                ],
            }
            for slot in cm.slots
        ]
        result.append({
            "id": cm.id,
            "label": (cm.label or "").strip(),
            "count": int(cm.count or 0),
            "weapons": {str(wid): cnt for wid, cnt in weapons.items()},
            "base_weapons": {str(wid): cnt for wid, cnt in _model_base_weapons(cm).items()},
            "slots": slots,
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


def _model_ability_keys(cm: models.CollectionModel) -> list[str]:
    """Pełne klucze zdolności modelu (`ability_link_loadout_key`, np. `"50:kontra|6"`)."""
    try:
        loadout = json.loads(cm.loadout_json) if cm.loadout_json else {}
    except (json.JSONDecodeError, TypeError):
        loadout = {}
    abilities = loadout.get("abilities") if isinstance(loadout, dict) else None
    keys: list[str] = []
    if isinstance(abilities, dict):
        for key, val in abilities.items():
            if val:
                keys.append(str(key))
    return keys


def _model_ability_base_ids(cm: models.CollectionModel) -> list[int]:
    """Bare ability_id niesione przez model (pełny klucz → część przed `:`)."""
    ids: list[int] = []
    for key in _model_ability_keys(cm):
        bid = _coerce_int(key.split(":", 1)[0])
        if bid is not None:
            ids.append(bid)
    return ids


def unit_ability_display(unit: models.Unit) -> dict[str, str]:
    """Mapa nazw zdolności oddziału do wyświetlania: ``{pełny_klucz: nazwa}``.

    Nazwa uwzględnia wartość parametru (np. „Aura: Kontra" zamiast generycznego
    „Aura: Zdolność") przez ``ability_catalog.display_with_value`` — spójnie z
    ``collections._ability_options``. Dodatkowo wpis fallback ``{str(bare_id):
    nazwa_generyczna}`` dla wyszukań po samym id (np. proxy bez wartości).
    """
    out: dict[str, str] = {}
    for link in getattr(unit, "abilities", []) or []:
        ability = getattr(link, "ability", None)
        if ability is None:
            continue
        value = None
        params = getattr(link, "params_json", None)
        if params:
            try:
                value = json.loads(params).get("value")
            except (json.JSONDecodeError, TypeError, AttributeError):
                value = None
        slug = ability_catalog.slug_for_name(ability.name)
        definition = ability_catalog.find_definition(slug) if slug else None
        if definition is not None and value is not None:
            display_name = ability_catalog.display_with_value(definition, str(value))
        else:
            display_name = ability.name
        key = ability_link_loadout_key(link)
        if key:
            out[key] = display_name
        bid = getattr(ability, "id", None)
        if bid is not None:
            out.setdefault(str(bid), ability.name)  # fallback po samym id → generyczna
    return out


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
            for wid, c in collection_model_effective_weapons(cm, entry.get("mounted")).items():
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


def _best_mount_effective(
    cm: models.CollectionModel, target: dict[int, int]
) -> tuple[dict[int, int], dict[str, int | None] | None]:
    """Dla derywacji: dobierz zamontowaną broń modelu magnetyzowanego tak, by
    pasowała do `target` (loadout), zamiast zapisanej domyślnej. Zwraca
    ``(efektywna_broń, mounted|None)``. ``mounted=None`` dla modeli bez slotów.

    Dla każdego slotu wybiera opcję POTRZEBNĄ w loadoutcie (a nie np. zapisane
    „Działo Plazmowe", gdy oddział ma „Miotacz ognia"); jeśli żadna opcja nie jest
    potrzebna — zostawia zapisaną (o ile mieści się w loadoutcie), inaczej pusty.
    """
    slots = list(getattr(cm, "slots", []) or [])
    if not slots:
        return _model_base_weapons(cm), None
    eff = _model_base_weapons(cm)
    mounted: dict[str, int | None] = {}
    for slot in slots:
        chosen: int | None = None
        for oid in sorted(_slot_option_ids(slot)):
            if target.get(oid, 0) - eff.get(oid, 0) > 0:
                chosen = oid
                break
        if chosen is None and slot.selected_weapon_id is not None:
            sid = int(slot.selected_weapon_id)
            if target.get(sid, 0) - eff.get(sid, 0) > 0:
                chosen = sid
        if chosen is not None:
            eff[chosen] = eff.get(chosen, 0) + 1
        mounted[str(slot.id)] = chosen
    return eff, mounted


def derive_composition(
    unit: models.Unit,
    current_loadout: dict[str, Any] | None,
    count: int,
    owned_models: list[models.CollectionModel],
    available: dict[int, int],
) -> list[dict[str, Any]]:
    """Best-effort suma→modele: odtwórz oddział (broń + zdolności) jako selekcję
    modeli, preferując posiadane; braki uzupełnij proxy. Punkt startowy — user
    koryguje miękkimi limitami.

    FAZA A: przypisz posiadane modele pokrywające zapotrzebowanie (najpierw
    pokrycie zdolności, potem nakład broni). FAZA B: RESZTĘ (residual weapon/
    ability target) rozłóż DOKŁADNIE na pozostałe sloty proxy — broń
    specjalistyczna po jednej na model (round-robin), broń podstawowa dopełnia.
    Dzięki temu proxy odtwarzają dokładny agregat broni oddziału (nie zawyżają
    broni podstawowej klonowaniem „domyślnego modelu"). Zdolności bare id.
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

    # Kategoria broni: wręcz (zasięg 0) vs dystans — do parowania w proxy tak, by
    # każdy model miał broń do walki wręcz (i pary specjalistów melee+dystans).
    weapon_is_melee: dict[int, bool] = {}
    for link in getattr(unit, "weapon_links", []) or []:
        wid = getattr(link, "weapon_id", None)
        if wid is None:
            continue
        w = getattr(link, "weapon", None)
        rng = getattr(w, "effective_range", None) if w is not None else None
        weapon_is_melee[int(wid)] = normalize_range_value(rng) == 0
    dwid = getattr(unit, "default_weapon_id", None)
    if dwid is not None:
        dw = getattr(unit, "default_weapon", None)
        rng = getattr(dw, "effective_range", None) if dw is not None else None
        weapon_is_melee.setdefault(int(dwid), normalize_range_value(rng) == 0)

    avail = {cm.id: int(available.get(cm.id, 0)) for cm in owned_models}
    # Efektywna broń + dobrany mount (magnetyzacja pasująca do loadoutu, nie
    # zapisana domyślna) — kluczowe dla modeli z magnesami (np. Sentinel).
    weapons_of: dict[int, dict[int, int]] = {}
    mount_of: dict[int, dict[str, int | None] | None] = {}
    for cm in owned_models:
        eff, mounted = _best_mount_effective(cm, weapon_target)
        weapons_of[cm.id] = eff
        mount_of[cm.id] = mounted
    abilities_of = {cm.id: set(_model_ability_base_ids(cm)) for cm in owned_models}

    sel: dict[int, int] = {}
    proxy_entries: list[dict[str, Any]] = []
    assigned = 0

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

    # FAZA A: przypisz posiadane modele, których PEŁNE uzbrojenie (i zdolności)
    # mieści się w RESZCIE zapotrzebowania. Agregat = DOKŁADNIE loadout — nie
    # dodajemy broni spoza rozpiski (np. modelu „Plazma gunner" z bronią, której
    # oddział nie ma). Preferuj fizycznie dostępne (avail>0), potem większe
    # pokrycie; nadwyżka ponad available dozwolona (miękki limit → proxy wariantu).
    def _fits_residual(cm_id: int) -> bool:
        ew = weapons_of[cm_id]
        if not ew or not all(weapon_target.get(w, 0) >= c for w, c in ew.items()):
            return False
        return all(ability_target.get(aid, 0) > 0 for aid in abilities_of[cm_id])

    def _coverage(cm_id: int) -> int:
        return sum(weapons_of[cm_id].values()) + len(abilities_of[cm_id])

    while assigned < count:
        cands = [cm.id for cm in owned_models if _fits_residual(cm.id)]
        if not cands:
            break
        assign_owned(max(cands, key=lambda cid: (avail[cid] > 0, _coverage(cid))))

    # FAZA B: RESZTĘ zapotrzebowania (residual po Fazie A) rozłóż na sloty proxy,
    # PARTYCJONUJĄC dokładnie broń i zdolności. Per KATEGORIA (wręcz/dystans):
    # broń specjalistyczna pakowana na najmniej modeli (o `slots` domyślnych na
    # model), broń podstawowa tworzy PEŁNE modele domyślne na pozostałych. Dzięki
    # temu: {Grobowe:2, Podwójne:1} → {Podwójne} + {Grobowe ×2}; a układ
    # melee+dystans → pary specjalistów i każdy model z bronią do walki wręcz
    # (np. {Piłomiecz, Hellpistol} + {Lekka, Hellgun}×9).
    remaining = max(count - assigned, 0)
    if remaining > 0:
        bucket_w: list[dict[str, int]] = [{} for _ in range(remaining)]
        bucket_a: list[list[int]] = [[] for _ in range(remaining)]
        slot = 0
        for aid in sorted(ability_target):
            for _ in range(ability_target[aid]):
                bucket_a[slot % remaining].append(aid)
                slot += 1

        def _cat(wid: int) -> int:
            return 0 if weapon_is_melee.get(wid, False) else 1  # 0=wręcz, 1=dystans

        def _flat(predicate) -> list[int]:
            out: list[int] = []
            for wid in sorted(w for w in weapon_target if predicate(w)):
                out.extend([wid] * weapon_target[wid])
            return out

        # Sloty domyślne per kategoria (ile broni danej kategorii ma model domyślny).
        default_slots = {0: 0, 1: 0}
        for wid, c in default_weapons.items():
            default_slots[_cat(wid)] += c

        # Per kategoria: broń specjalistyczną upchnij na PIERWSZE `cn` modeli
        # (cn = ceil(specjalistów / slotów) — najmniej modeli), broń podstawową
        # rozłóż na POZOSTAŁE. Wszystkie kategorie startują od modelu 0, więc
        # specjaliści melee+dystans parują się na tych samych (najniższych) modelach,
        # a bazowa broń wypełnia luki kategorii (np. {Piłomiecz,Bolt}+{Lekka,Granatnik}).
        for cat in (0, 1):
            slots = default_slots[cat] or 1
            spec = _flat(lambda w: w not in default_wids and _cat(w) == cat)
            cn = min(-(-len(spec) // slots), remaining) if spec else 0
            for i, wid in enumerate(spec):
                b = bucket_w[i % max(cn, 1)]
                b[str(wid)] = b.get(str(wid), 0) + 1
            base_models = list(range(cn, remaining)) or list(range(remaining))
            base = _flat(lambda w: w in default_wids and _cat(w) == cat)
            for j, wid in enumerate(base):
                b = bucket_w[base_models[j % len(base_models)]]
                b[str(wid)] = b.get(str(wid), 0) + 1

        for wdict, alist in zip(bucket_w, bucket_a):
            proxy_entries.append({
                "id": None,
                "weapons": wdict,
                "abilities": sorted(set(alist)),
                "qty": 1,
            })

    selection: list[dict[str, Any]] = []
    for cid, q in sel.items():
        if q <= 0:
            continue
        entry: dict[str, Any] = {"id": cid, "qty": q}
        mounted = mount_of.get(cid)
        if mounted:  # magnetyzacja dobrana do loadoutu (per-oddział)
            entry["mounted"] = dict(mounted)
        selection.append(entry)
    # Scal identyczne proxy (ten sam wariant) w jeden wpis z qty.
    merged: dict[tuple, dict[str, Any]] = {}
    for p in proxy_entries:
        key = (tuple(sorted(p["weapons"].items())), tuple(p["abilities"]))
        if key in merged:
            merged[key]["qty"] += p["qty"]
        else:
            merged[key] = dict(p)
    selection.extend(merged.values())
    return selection


# ── Faza 2c: grupy wariantów do trybu „Modele" w Stanie Bitewnym ────────────

def composition_groups(
    selection: Iterable[dict[str, Any]],
    owned_by_id: dict[int, models.CollectionModel],
    weapon_names: dict[int, str],
    ability_names: dict[str, str],
    weapon_cost_map: dict[int, float],
    ability_cost_map: dict[int, float],
    unit_name: str = "",
) -> list[dict[str, Any]]:
    """Grupuje kompozycję (`parse_selection`) po WARIANCIE (broń + zdolności) do
    widoku „Modele" w Stanie Bitewnym; sortuje **rosnąco po koszcie wariantu**.

    Każda grupa: ``{key, weapons:{str(wid):per_model_cnt}, abilities:[aid],
    summary, count, cost}``. `key` — stabilny podpis wariantu (klucz stanu JS).
    `cost` = Σ broń×koszt + Σ koszt zdolności (do sortowania i zdejmowania
    najtańszego). Izolacja właściciela przez `owned_by_id` (obce id pomijane).
    ``ability_names`` mapuje **pełny klucz zdolności** → nazwa display (z wartością).
    """
    groups: dict[str, dict[str, Any]] = {}
    for entry in selection or []:
        if not isinstance(entry, dict):
            continue
        qty = _coerce_int(entry.get("qty")) or 0
        if qty <= 0:
            continue
        cm_id = _coerce_int(entry.get("id")) if entry.get("id") is not None else None
        entry_label = ""
        if cm_id is not None:
            cm = owned_by_id.get(cm_id)
            if cm is None:
                continue  # obcy/nieznany model — pomijamy (izolacja właściciela)
            weapons = collection_model_effective_weapons(cm, entry.get("mounted"))
            entry_label = (getattr(cm, "label", "") or "").strip()
            # Pełne klucze (z wartością) rozróżniają warianty parametryzowane aur;
            # `abilities` (gołe id) służą kosztowi i mapowaniu przekreśleń (#4).
            display_keys = sorted(set(_model_ability_keys(cm)))
        else:
            weapons = _weapon_multiset(entry.get("weapons"))
            display_keys = sorted(
                {str(a) for a in (_coerce_int(x) for x in (entry.get("abilities") or [])) if a is not None}
            )
        bare_ids = sorted({
            b for b in (_coerce_int(dk.split(":", 1)[0]) for dk in display_keys) if b is not None
        })
        key = f"{model_variant_signature(weapons)}#{','.join(display_keys)}"
        grp = groups.get(key)
        if grp is None:
            wparts = []
            for wid in sorted(weapons):
                name = weapon_names.get(wid, f"Broń #{wid}")
                cnt = weapons[wid]
                wparts.append(f"{name} ×{cnt}" if cnt > 1 else name)
            summary = ", ".join(wparts) if wparts else "—"
            aparts = [
                ability_names.get(dk) or f"Zdolność #{dk.split(':', 1)[0]}" for dk in display_keys
            ]
            if aparts:
                summary += " • " + ", ".join(aparts)
            cost = sum(weapon_cost_map.get(w, 0.0) * c for w, c in weapons.items())
            cost += sum(ability_cost_map.get(a, 0.0) for a in bare_ids)
            grp = {
                "key": key,
                "name": entry_label,  # etykieta modelu z Kolekcji (fallback niżej)
                "weapons": {str(w): c for w, c in weapons.items()},
                "abilities": bare_ids,
                "summary": summary,
                "count": 0,
                "cost": round(float(cost), 2),
            }
            groups[key] = grp
        elif entry_label and not grp["name"]:
            grp["name"] = entry_label  # pierwsza niepusta etykieta wariantu
        grp["count"] += qty
    result = sorted(groups.values(), key=lambda g: (g["cost"], g["summary"]))
    for g in result:
        if not g["name"]:
            g["name"] = unit_name  # fallback: nazwa oddziału (np. proxy/bez etykiety)
    return result
