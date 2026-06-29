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
) -> list[dict[str, Any]]:
    """Formatuje modele do wyboru w „Trybie modeli": efektywna broń + podsumowanie.

    ``weapons`` to efektywne uzbrojenie (bazowe + zamontowane sloty) jako
    ``{str(weapon_id): count}`` — frontend sumuje je do agregatu oddziału.
    """
    result: list[dict[str, Any]] = []
    for cm in collection_models:
        weapons = collection_model_effective_weapons(cm)
        parts = []
        for wid in sorted(weapons):
            name = weapon_names.get(wid, f"Broń #{wid}")
            cnt = weapons[wid]
            parts.append(f"{name} ×{cnt}" if cnt > 1 else name)
        result.append({
            "id": cm.id,
            "label": (cm.label or "").strip(),
            "count": int(cm.count or 0),
            "weapons": {str(wid): cnt for wid, cnt in weapons.items()},
            "summary": ", ".join(parts) if parts else "—",
        })
    return result
