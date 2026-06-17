"""Unit-level cost helpers.

Extracted from ``_engine.py`` Section 7 (UNIT-LEVEL COST AGGREGATION).

These helpers bridge the gap between the raw weapon/ability cost primitives and
the full per-roster-unit quote:

- ``unit_default_weapons``      — collect a unit's default weapon loadout
- ``_ability_link_is_default``  — parse ``params_json`` to detect default flag
- ``ability_cost``              — cost for a single ``UnitAbility`` link
- ``ability_uses_order_like_cost`` — detect order/curse/mark abilities
- ``unit_total_cost``           — simple per-model cost (no loadout)
- ``unit_typical_total_cost``   — ``unit_total_cost`` × model count
- ``normalize_roster_unit_loadout`` — sanitise & canonicalise a raw loadout dict

Section 9 (``roster_unit_role_totals``) calls ``unit_default_weapons``,
``_ability_link_is_default``, and ``ability_cost`` — those are re-imported into
``_engine``'s globals via the Section 7 stub so unqualified calls inside
``_engine`` still resolve correctly.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from ... import models
from ..utils import ARMY_RULE_OFF_PREFIX
from ._engine import ORDER_LIKE_ACTIVE_SLUGS, ROLE_SLUGS
from .abilities import ability_cost_from_name, base_model_cost
from .passive_state import (
    _parse_passive_counts,
    compute_passive_state,
)
from .primitives import ability_identifier, normalize_name
from .primitives import ability_link_loadout_key as _loadout_key_for_id_value
from .weapons import weapon_cost


def unit_default_weapons(unit: models.Unit | None) -> list[models.Weapon]:
    if unit is None:
        return []

    weapons: list[models.Weapon] = []
    seen: set[int] = set()
    links = getattr(unit, "weapon_links", None) or []
    for link in links:
        if link.weapon is None:
            continue
        is_default = bool(getattr(link, "is_default", False))
        count_raw = getattr(link, "default_count", None)
        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            count = 1 if is_default else 0
        if count < 0:
            count = 0
        if not is_default and count > 0:
            is_default = True
        if not is_default or count <= 0:
            continue
        for _ in range(count):
            weapons.append(link.weapon)
        seen.add(link.weapon.id)
    if unit.default_weapon:
        default_id = unit.default_weapon_id or getattr(unit.default_weapon, "id", None)
        if default_id is None or default_id not in seen:
            weapons.append(unit.default_weapon)
            if default_id is not None:
                seen.add(default_id)
    return weapons


def _ability_link_is_default(link: models.UnitAbility) -> bool:
    def _coerce_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False
            lowered = text.casefold()
            if lowered in {"true", "yes", "1", "on"}:
                return True
            if lowered in {"false", "no", "0", "off"}:
                return False
            try:
                return float(text) != 0.0
            except ValueError:
                return True
        return bool(value)

    params_json = getattr(link, "params_json", None)
    if not params_json:
        return False
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError:
        return False
    default_flag: bool | None = None
    for key in ("default", "is_default"):
        if key in params:
            default_flag = _coerce_bool(params.get(key))
            break
    if default_flag is None and "default_count" in params:
        try:
            return int(params.get("default_count") or 0) > 0
        except (TypeError, ValueError):
            return False
    return bool(default_flag)


def _ability_link_value(ability_link: models.UnitAbility) -> Any:
    params_json = getattr(ability_link, "params_json", None)
    if not params_json:
        return None
    try:
        data = json.loads(params_json)
    except json.JSONDecodeError:
        return None
    return data.get("value")


def ability_link_loadout_key(ability_link: models.UnitAbility) -> str:
    """Per-link disambiguating key — see ``primitives.ability_link_loadout_key``.

    Needed because several ``UnitAbility`` links (e.g. multiple "Aura: X"
    selections on one unit) can share the same generic ``ability_id``.

    Reads the id via the ``.ability`` relationship (not the raw ``ability_id``
    FK column) to match how ``ability_cost`` and the rest of this module
    resolve a link's ability — and so lightweight test doubles only need to
    set ``.ability``, not a separate ``ability_id`` attribute.
    """
    ability_id = getattr(getattr(ability_link, "ability", None), "id", None)
    return _loadout_key_for_id_value(ability_id, _ability_link_value(ability_link))


def ability_cost(
    ability_link: models.UnitAbility,
    unit_traits: Sequence[str] | None = None,
    toughness: int | float | None = None,
) -> float:
    ability = ability_link.ability
    if not ability:
        return 0.0
    if ability.cost_hint is not None and not ability_uses_order_like_cost(ability):
        return float(ability.cost_hint)
    unit = getattr(ability_link, "unit", None)
    value = _ability_link_value(ability_link)
    base_toughness = toughness
    if base_toughness is None and unit is not None:
        base_toughness = getattr(unit, "toughness", None)
    return ability_cost_from_name(
        ability.name or "",
        value,
        unit_traits,
        toughness=base_toughness,
        quality=getattr(unit, "quality", None) if unit is not None else None,
        defense=getattr(unit, "defense", None) if unit is not None else None,
        weapons=unit_default_weapons(unit) if unit is not None else None,
    )


def ability_uses_order_like_cost(ability: models.Ability | None) -> bool:
    if ability is None:
        return False
    slug = ""
    raw_config = getattr(ability, "config_json", None)
    if raw_config:
        try:
            parsed = json.loads(raw_config)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            slug = str(parsed.get("slug") or "").strip()
    normalized_slug = slug.casefold() if slug else ""
    if slug and not normalized_slug:
        normalized_slug = ""
    if not normalized_slug and slug:
        normalized_slug = ability_identifier(slug)
    elif slug:
        normalized_slug = ability_identifier(normalized_slug) or normalized_slug
    if normalized_slug and normalized_slug in ORDER_LIKE_ACTIVE_SLUGS:
        return True
    if not slug:
        normalized_slug = ability_identifier(getattr(ability, "name", "") or "")
    return normalized_slug in ORDER_LIKE_ACTIVE_SLUGS


def unit_total_cost(unit: models.Unit) -> float:
    passive_state = compute_passive_state(unit)
    unit_traits = passive_state.traits
    cost = base_model_cost(unit.quality, unit.defense, unit.toughness, unit_traits)
    for weapon in unit_default_weapons(unit):
        cost += weapon_cost(weapon, unit.quality, unit_traits)
    cost += sum(
        ability_cost(link, unit_traits, toughness=unit.toughness)
        for link in unit.abilities
        if _ability_link_is_default(link)
    )
    return round(cost, 2)


def unit_typical_total_cost(
    unit: models.Unit,
    model_count: int | None = None,
    *,
    per_model: float | None = None,
) -> float:
    if per_model is None:
        per_model_value = unit_total_cost(unit)
    else:
        try:
            per_model_value = float(per_model)
        except (TypeError, ValueError):
            per_model_value = unit_total_cost(unit)
    if model_count is None:
        try:
            model_count = unit.typical_model_count
        except AttributeError:  # pragma: no cover - compatibility
            model_count = getattr(unit, "typical_models", 1)
    try:
        count = int(model_count)
    except (TypeError, ValueError):
        count = 1
    if count < 1:
        count = 1
    return round(per_model_value * count, 2)


def _normalize_loadout_section_ids(
    section_data: Any,
    *,
    allowed_ids: set[int],
) -> dict[str, int]:
    normalized: dict[str, int] = {}
    if isinstance(section_data, dict):
        items = section_data.items()
    elif isinstance(section_data, list):
        pairs: list[tuple[Any, Any]] = []
        for entry in section_data:
            if not isinstance(entry, dict):
                continue
            entry_id = (
                entry.get("loadout_key")
                or entry.get("key")
                or entry.get("id")
                or entry.get("weapon_id")
                or entry.get("ability_id")
            )
            if entry_id is None:
                continue
            pairs.append((entry_id, entry.get("count") or entry.get("per_model") or 0))
        items = pairs
    else:
        items = []

    for raw_id, raw_value in items:
        raw_id_str = str(raw_id).strip()
        if not raw_id_str:
            continue
        base_id = raw_id_str.split(":", 1)[0]
        try:
            parsed_id = int(base_id)
        except (TypeError, ValueError):
            try:
                parsed_id = int(float(base_id))
            except (TypeError, ValueError):
                continue
        if parsed_id not in allowed_ids:
            continue
        try:
            parsed_value = int(raw_value)
        except (TypeError, ValueError):
            try:
                parsed_value = int(float(raw_value))
            except (TypeError, ValueError):
                parsed_value = 0
        normalized[raw_id_str] = max(parsed_value, 0)
    return normalized


def normalize_roster_unit_loadout(
    unit: models.Unit | None,
    loadout: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_loadout = loadout if isinstance(loadout, dict) else {}
    mode = str(raw_loadout.get("mode") or "").strip().lower()
    normalized_mode = "total" if mode == "total" else "per_model"

    weapon_ids: set[int] = set()
    for link in getattr(unit, "weapon_links", []) or []:
        weapon_id = getattr(link, "weapon_id", None)
        if weapon_id is not None:
            weapon_ids.add(int(weapon_id))
    default_weapon_id = getattr(unit, "default_weapon_id", None)
    if default_weapon_id is not None:
        weapon_ids.add(int(default_weapon_id))

    active_ids: set[int] = set()
    aura_ids: set[int] = set()
    for link in getattr(unit, "abilities", []) or []:
        ability = getattr(link, "ability", None)
        ability_id = getattr(ability, "id", None)
        if ability is None or ability_id is None:
            continue
        if ability.type == "active":
            active_ids.add(int(ability_id))
        elif ability.type == "aura":
            aura_ids.add(int(ability_id))

    passive_state = compute_passive_state(unit, raw_loadout)
    allowed_passive_lookup: dict[str, str] = {}
    for entry in passive_state.payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        identifier = ability_identifier(slug) or slug
        for candidate in (slug, slug.casefold(), normalize_name(slug), identifier):
            if candidate:
                allowed_passive_lookup.setdefault(candidate, identifier)
    # Role slugs (wojownik/strzelec) are classification markers persisted into
    # loadout.passive by _apply_classification_to_loadout. They must always be
    # accepted — even when the unit's army flags declare only one of them — so
    # that an attached hero whose group classifies as Strzelec keeps its
    # passive.strzelec=1 flag through sanitization. Without this, the role
    # marker is dropped and role_totals falls back to the unit's default flag,
    # producing the regressed "stale 49.14" cost.
    for role in ROLE_SLUGS:
        allowed_passive_lookup.setdefault(role, role)

    passive_counts = _parse_passive_counts(raw_loadout)
    sanitized_passive: dict[str, int] = {}
    for slug, value in passive_counts.items():
        slug_text = str(slug).strip()
        if not slug_text:
            continue
        # Army-rule off-toggles (e.g. "__army_off__odwody") must be preserved
        # as-is and must NOT be canonicalized via ability_identifier — that
        # would strip the prefix and map them to the base slug (e.g. "odwody"),
        # inverting the semantics: a stored value of 0 (meaning "do not
        # disable this rule") would become passive["odwody"]=0 (meaning "rule
        # is off"), silently disabling the army rule and distorting the cost.
        # Pass them through unchanged; _apply_army_rule_overrides inside
        # compute_passive_state interprets them correctly.
        if slug_text.startswith(ARMY_RULE_OFF_PREFIX):
            if value > 0:
                sanitized_passive[slug_text] = 1
            # value == 0: off-toggle inactive; leave the rule at its default.
            continue
        canonical = None
        for candidate in (
            slug_text,
            slug_text.casefold(),
            normalize_name(slug_text),
            ability_identifier(slug_text),
        ):
            if candidate and candidate in allowed_passive_lookup:
                canonical = allowed_passive_lookup[candidate]
                break
        if canonical is None:
            continue
        sanitized_passive[canonical] = 1 if value > 0 else 0

    return {
        "mode": normalized_mode,
        "weapons": _normalize_loadout_section_ids(
            raw_loadout.get("weapons"), allowed_ids=weapon_ids
        ),
        "active": _normalize_loadout_section_ids(
            raw_loadout.get("active"), allowed_ids=active_ids
        ),
        "aura": _normalize_loadout_section_ids(
            raw_loadout.get("aura"), allowed_ids=aura_ids
        ),
        "passive": sanitized_passive,
    }


__all__ = [
    "_ability_link_is_default",
    "_normalize_loadout_section_ids",
    "ability_cost",
    "ability_link_loadout_key",
    "ability_uses_order_like_cost",
    "normalize_roster_unit_loadout",
    "unit_default_weapons",
    "unit_total_cost",
    "unit_typical_total_cost",
]
