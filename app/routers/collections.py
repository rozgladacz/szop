from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..data import abilities as ability_catalog
from ..db import get_db
from ..paths import TEMPLATES_DIR
from ..security import get_current_user
from ..services.costs import ability_link_loadout_key

router = APIRouter(prefix="/collections", tags=["collections"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── helpers ────────────────────────────────────────────────────────────────────

def _unit_eager_opts():
    return (
        selectinload(models.Unit.weapon_links).selectinload(models.UnitWeapon.weapon).selectinload(models.Weapon.parent),
        selectinload(models.Unit.default_weapon).selectinload(models.Weapon.parent),
        selectinload(models.Unit.abilities).selectinload(models.UnitAbility.ability),
        selectinload(models.Unit.army),
    )


def _accessible_armies(db: Session, current_user: models.User):
    q = select(models.Army).order_by(models.Army.name)
    if not current_user.is_admin:
        q = q.where(or_(
            models.Army.owner_id == current_user.id,
            models.Army.owner_id.is_(None),
        ))
    return db.execute(q).scalars().all()


def _weapon_options(unit: models.Unit) -> list[dict]:
    seen: set[int] = set()
    opts = []
    for link in unit.weapon_links:
        if link.weapon_id is None or link.weapon is None or link.weapon_id in seen:
            continue
        opts.append({
            "id": link.weapon_id,
            "name": link.weapon.effective_name,
            "is_default": bool(link.is_default),
            "default_count": link.default_count if link.default_count is not None else (1 if link.is_default else 0),
        })
        seen.add(link.weapon_id)
    if unit.default_weapon_id and unit.default_weapon_id not in seen and unit.default_weapon:
        opts.append({
            "id": unit.default_weapon_id,
            "name": unit.default_weapon.effective_name,
            "is_default": True,
            "default_count": 1,
        })
    opts.sort(key=lambda x: (not x["is_default"], x["name"].casefold()))
    return opts


def _ability_options(unit: models.Unit) -> list[dict]:
    opts = []
    for link in unit.abilities:
        if link.ability is None:
            continue
        key = ability_link_loadout_key(link)
        value = None
        if link.params_json:
            try:
                value = json.loads(link.params_json).get("value")
            except (json.JSONDecodeError, TypeError):
                pass
        slug = ability_catalog.slug_for_name(link.ability.name)
        definition = ability_catalog.find_definition(slug) if slug else None
        if definition and value is not None:
            display_name = ability_catalog.display_with_value(definition, str(value))
        else:
            display_name = link.ability.name
        opts.append({
            "key": key,
            "id": link.ability_id,
            "name": display_name,
            "type": link.ability.type,
        })
    return opts


def _loadout_summary(loadout: dict, weapon_map: dict[int, str], ability_map: dict[int, str]) -> str:
    parts = []
    for wid_str, cnt in loadout.get("weapons", {}).items():
        try:
            wid = int(wid_str)
            cnt = int(cnt)
        except (ValueError, TypeError):
            continue
        if cnt <= 0:
            continue
        name = weapon_map.get(wid, f"Broń #{wid}")
        parts.append(f"{name} x{cnt}" if cnt > 1 else name)
    for key, flag in loadout.get("abilities", {}).items():
        if not flag:
            continue
        name = ability_map.get(key, f"Zdolność #{key}")
        parts.append(name)
    return ", ".join(parts) if parts else "—"


def _parse_loadout(form_data: dict[str, Any], valid_weapon_ids: set[int], valid_ability_keys: set[str]) -> dict:
    weapons = {}
    for wid in valid_weapon_ids:
        raw = form_data.get(f"weapon_{wid}", "0")
        try:
            cnt = max(0, int(raw))
        except (ValueError, TypeError):
            cnt = 0
        if cnt > 0:
            weapons[str(wid)] = cnt
    abilities = {}
    for key in valid_ability_keys:
        if form_data.get(f"ability_{key}"):
            abilities[key] = 1
    return {"weapons": weapons, "abilities": abilities}


def _parse_form_multi(form) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in form.multi_items():
        if k in result:
            existing = result[k]
            if isinstance(existing, list):
                existing.append(v)
            else:
                result[k] = [existing, v]
        else:
            result[k] = v
    return result


def _parse_slots(form_data: dict[str, Any], valid_weapon_ids: set[int]) -> list[dict]:
    slots = []
    idx = 0
    while True:
        name = form_data.get(f"slot_name_{idx}", "").strip()
        if name == "" and f"slot_name_{idx}" not in form_data:
            break
        if not name:
            idx += 1
            continue
        raw_options = form_data.get(f"slot_options_{idx}", "")
        if isinstance(raw_options, list):
            option_ids = raw_options
        elif raw_options:
            option_ids = [raw_options]
        else:
            option_ids = []
        valid_opts = []
        for o in option_ids:
            try:
                oi = int(o)
            except (ValueError, TypeError):
                continue
            if oi in valid_weapon_ids:
                valid_opts.append(oi)

        raw_selected = form_data.get(f"slot_selected_{idx}", "")
        try:
            selected_id = int(raw_selected) if raw_selected else None
        except (ValueError, TypeError):
            selected_id = None
        if selected_id is not None and selected_id not in valid_opts:
            selected_id = None

        slots.append({
            "name": name,
            "option_weapon_ids": valid_opts,
            "selected_weapon_id": selected_id,
        })
        idx += 1
    return slots


def _collection_model_eager():
    return (
        selectinload(models.CollectionModel.unit).options(
            selectinload(models.Unit.weapon_links).selectinload(models.UnitWeapon.weapon).selectinload(models.Weapon.parent),
            selectinload(models.Unit.default_weapon).selectinload(models.Weapon.parent),
            selectinload(models.Unit.abilities).selectinload(models.UnitAbility.ability),
        ),
        selectinload(models.CollectionModel.slots).selectinload(models.CollectionModelSlot.selected_weapon),
    )


def _require_owner(model: models.CollectionModel, current_user: models.User) -> None:
    if not current_user.is_admin and model.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Brak uprawnień")


def _build_collection_card(cm: models.CollectionModel, weapon_map: dict, ability_map: dict) -> dict:
    try:
        loadout = json.loads(cm.loadout_json) if cm.loadout_json else {}
    except (json.JSONDecodeError, TypeError):
        loadout = {}
    return {
        "id": cm.id,
        "label": cm.label or "",
        "count": cm.count,
        "summary": _loadout_summary(loadout, weapon_map, ability_map),
        "loadout": loadout,
        "slots": [
            {
                "id": s.id,
                "name": s.name,
                "option_weapon_ids": json.loads(s.option_weapon_ids_json or "[]"),
                "selected_weapon_id": s.selected_weapon_id,
                "selected_weapon_name": s.selected_weapon.effective_name if s.selected_weapon else "nic",
            }
            for s in cm.slots
        ],
    }


# ── endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def list_collections(
    request: Request,
    army_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    armies = _accessible_armies(db, current_user)

    selected_army = None
    unit_summaries = []

    if army_id:
        selected_army = db.get(models.Army, army_id)
        if not selected_army:
            raise HTTPException(status_code=404)
        if not current_user.is_admin:
            if selected_army.owner_id is not None and selected_army.owner_id != current_user.id:
                raise HTTPException(status_code=403)

        units_stmt = (
            select(models.Unit)
            .where(models.Unit.army_id == army_id)
            .options(*_unit_eager_opts())
            .order_by(models.Unit.position, models.Unit.id)
        )
        units = db.execute(units_stmt).scalars().unique().all()

        owned_counts: dict[int, int] = {}
        if units:
            unit_ids = [u.id for u in units]
            cm_rows = db.execute(
                select(models.CollectionModel.unit_id, models.CollectionModel.count)
                .where(
                    models.CollectionModel.owner_id == current_user.id,
                    models.CollectionModel.unit_id.in_(unit_ids),
                )
            ).all()
            for row in cm_rows:
                owned_counts[row.unit_id] = owned_counts.get(row.unit_id, 0) + row.count

        for unit in units:
            unit_summaries.append({
                "unit": unit,
                "owned_count": owned_counts.get(unit.id, 0),
            })

    return templates.TemplateResponse("collections_list.html", {
        "request": request,
        "user": current_user,
        "armies": armies,
        "selected_army": selected_army,
        "army_id": army_id,
        "unit_summaries": unit_summaries,
    })


@router.get("/units/{unit_id}", response_class=HTMLResponse)
def unit_collection(
    unit_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    unit = db.execute(
        select(models.Unit).where(models.Unit.id == unit_id).options(*_unit_eager_opts())
    ).scalars().unique().one_or_none()
    if not unit:
        raise HTTPException(status_code=404)
    if not current_user.is_admin:
        army = unit.army
        if army and army.owner_id is not None and army.owner_id != current_user.id:
            raise HTTPException(status_code=403)

    weapon_opts = _weapon_options(unit)
    ability_opts = _ability_options(unit)

    weapon_map = {o["id"]: o["name"] for o in weapon_opts}
    ability_map = {o["key"]: o["name"] for o in ability_opts}

    cm_stmt = (
        select(models.CollectionModel)
        .where(
            models.CollectionModel.unit_id == unit_id,
            models.CollectionModel.owner_id == current_user.id,
        )
        .options(*_collection_model_eager())
        .order_by(models.CollectionModel.position, models.CollectionModel.id)
    )
    collection_models = db.execute(cm_stmt).scalars().unique().all()

    cards = [_build_collection_card(cm, weapon_map, ability_map) for cm in collection_models]

    return templates.TemplateResponse("collection_unit_detail.html", {
        "request": request,
        "user": current_user,
        "unit": unit,
        "weapon_opts": weapon_opts,
        "ability_opts": ability_opts,
        "cards": cards,
        "army_id": unit.army_id,
    })


@router.post("/units/{unit_id}/models/add")
async def add_collection_model(
    unit_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    unit = db.execute(
        select(models.Unit).where(models.Unit.id == unit_id).options(*_unit_eager_opts())
    ).scalars().unique().one_or_none()
    if not unit:
        raise HTTPException(status_code=404)

    form = await request.form()
    form_multi = _parse_form_multi(form)

    label = str(form_multi.get("label", "")).strip() or None
    try:
        count = max(1, int(form_multi.get("count", 1)))
    except (ValueError, TypeError):
        count = 1

    weapon_opts = _weapon_options(unit)
    ability_opts = _ability_options(unit)
    valid_weapon_ids = {o["id"] for o in weapon_opts}
    valid_ability_keys = {o["key"] for o in ability_opts}

    loadout = _parse_loadout(form_multi, valid_weapon_ids, valid_ability_keys)

    max_pos_row = db.execute(
        select(models.CollectionModel.position)
        .where(models.CollectionModel.owner_id == current_user.id, models.CollectionModel.unit_id == unit_id)
        .order_by(models.CollectionModel.position.desc())
        .limit(1)
    ).scalar_one_or_none()
    next_pos = (max_pos_row or 0) + 1

    cm = models.CollectionModel(
        owner_id=current_user.id,
        unit_id=unit_id,
        label=label,
        count=count,
        loadout_json=json.dumps(loadout, ensure_ascii=False),
        position=next_pos,
    )
    db.add(cm)
    db.flush()

    if form_multi.get("magnetyzacja"):
        slots = _parse_slots(form_multi, valid_weapon_ids)
        for i, slot in enumerate(slots):
            db.add(models.CollectionModelSlot(
                collection_model_id=cm.id,
                name=slot["name"],
                option_weapon_ids_json=json.dumps(slot["option_weapon_ids"]),
                selected_weapon_id=slot["selected_weapon_id"],
                position=i,
            ))

    db.commit()
    db.refresh(cm)

    weapon_map = {o["id"]: o["name"] for o in weapon_opts}
    ability_map = {o["key"]: o["name"] for o in ability_opts}

    card = _build_collection_card(cm, weapon_map, ability_map)

    want_json = "application/json" in request.headers.get("accept", "")
    if want_json:
        return JSONResponse({"ok": True, "card": card})
    return RedirectResponse(url=f"/collections/units/{unit_id}", status_code=303)


@router.post("/models/{model_id}/update")
async def update_collection_model(
    model_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    cm = db.execute(
        select(models.CollectionModel)
        .where(models.CollectionModel.id == model_id)
        .options(*_collection_model_eager())
    ).scalars().unique().one_or_none()
    if not cm:
        raise HTTPException(status_code=404)
    _require_owner(cm, current_user)

    unit = db.execute(
        select(models.Unit).where(models.Unit.id == cm.unit_id).options(*_unit_eager_opts())
    ).scalars().unique().one_or_none()
    if not unit:
        raise HTTPException(status_code=404)

    form = await request.form()
    form_multi = _parse_form_multi(form)

    label = str(form_multi.get("label", "")).strip() or None
    try:
        count = max(1, int(form_multi.get("count", 1)))
    except (ValueError, TypeError):
        count = 1

    weapon_opts = _weapon_options(unit)
    ability_opts = _ability_options(unit)
    valid_weapon_ids = {o["id"] for o in weapon_opts}
    valid_ability_keys = {o["key"] for o in ability_opts}

    loadout = _parse_loadout(form_multi, valid_weapon_ids, valid_ability_keys)

    cm.label = label
    cm.count = count
    cm.loadout_json = json.dumps(loadout, ensure_ascii=False)

    # replace slots
    for slot in list(cm.slots):
        db.delete(slot)
    db.flush()

    if form_multi.get("magnetyzacja"):
        slots = _parse_slots(form_multi, valid_weapon_ids)
        for i, slot in enumerate(slots):
            db.add(models.CollectionModelSlot(
                collection_model_id=cm.id,
                name=slot["name"],
                option_weapon_ids_json=json.dumps(slot["option_weapon_ids"]),
                selected_weapon_id=slot["selected_weapon_id"],
                position=i,
            ))

    db.commit()

    want_json = "application/json" in request.headers.get("accept", "")
    if want_json:
        weapon_map = {o["id"]: o["name"] for o in weapon_opts}
        ability_map = {o["key"]: o["name"] for o in ability_opts}
        db.refresh(cm)
        card = _build_collection_card(cm, weapon_map, ability_map)
        return JSONResponse({"ok": True, "card": card})
    return RedirectResponse(url=f"/collections/units/{cm.unit_id}", status_code=303)


@router.post("/models/{model_id}/delete")
async def delete_collection_model(
    model_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    cm = db.get(models.CollectionModel, model_id)
    if not cm:
        raise HTTPException(status_code=404)
    _require_owner(cm, current_user)

    unit_id = cm.unit_id
    db.delete(cm)
    db.commit()

    want_json = "application/json" in request.headers.get("accept", "")
    if want_json:
        return JSONResponse({"ok": True})
    return RedirectResponse(url=f"/collections/units/{unit_id}", status_code=303)
