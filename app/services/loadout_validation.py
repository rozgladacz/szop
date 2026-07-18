"""Read-only loadout diff validation over the canonical cost services.

This module owns the production validation contract shared by the leaf CLI,
HTTP endpoint, and indirect MCP client. It never persists a loadout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.services.costs import calculate_roster_unit_quote
from app.services.costs.primitives import ability_identifier, normalize_name
from app.services.costs.unit_helpers import normalize_roster_unit_loadout

LOADOUT_VALIDATION_SCHEMA = "szop.validate_loadout/v1"
LOADOUT_VALIDATION_VERSION = 1
_SECTIONS = ("weapons", "active", "aura")


class LoadoutValidationError(Exception):
    """Base class for controlled loadout-validation failures."""


class UnitNotFoundError(LoadoutValidationError):
    """The requested global catalog unit does not exist."""


class LoadoutSerializationError(LoadoutValidationError):
    """A service result cannot be represented by the public JSON contract."""


@dataclass(frozen=True)
class SectionDiff:
    """Diff for one ID-based loadout section."""

    section: str
    accepted: dict[str, int]
    rejected: list[tuple[str, str]] = field(default_factory=list)
    clamped: list[tuple[str, Any, int]] = field(default_factory=list)


@dataclass(frozen=True)
class LoadoutDiff:
    """Normalized loadout selections, rejected inputs, and canonical quote."""

    unit_id: int
    unit_name: str
    count: int
    raw_mode: Any
    normalized_mode: str
    mode_clamped: bool
    sections: list[SectionDiff]
    passive_accepted: dict[str, int]
    passive_rejected: list[str]
    selected_role: Any
    selected_total: float
    components: dict[str, float]

    @property
    def has_issues(self) -> bool:
        if self.mode_clamped or self.passive_rejected:
            return True
        return any(diff.rejected or diff.clamped for diff in self.sections)


def _enumerate_raw_section(section: Any) -> list[tuple[str, Any]]:
    """Enumerate raw IDs without applying the canonical allowlist filter."""
    if isinstance(section, dict):
        items: list[tuple[Any, Any]] = list(section.items())
    elif isinstance(section, list):
        items = []
        for entry in section:
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
            items.append((entry_id, entry.get("count") or entry.get("per_model") or 0))
    else:
        items = []

    pairs: list[tuple[str, Any]] = []
    for raw_id, raw_value in items:
        id_str = str(raw_id).strip()
        if id_str:
            pairs.append((id_str, raw_value))
    return pairs


def _coerce_int(value: Any) -> int | None:
    """Parse a count exactly like the canonical loadout normalizer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _id_is_parseable(id_str: str) -> bool:
    """Return whether the normalizer can parse the ID base before ``:``."""
    return _coerce_int(id_str.split(":", 1)[0]) is not None


def diff_section(
    name: str,
    raw_section: Any,
    normalized_section: dict[str, int],
) -> SectionDiff:
    """Compare a raw ID section with the canonical normalized section."""
    rejected: list[tuple[str, str]] = []
    clamped: list[tuple[str, Any, int]] = []
    for id_str, raw_value in _enumerate_raw_section(raw_section):
        if id_str not in normalized_section:
            reason = (
                "niedozwolone dla tej jednostki"
                if _id_is_parseable(id_str)
                else "niepoprawne id"
            )
            rejected.append((id_str, reason))
            continue
        normalized_value = normalized_section[id_str]
        parsed = _coerce_int(raw_value)
        if parsed is None or parsed != normalized_value:
            clamped.append((id_str, raw_value, normalized_value))
    return SectionDiff(
        section=name,
        accepted=dict(normalized_section),
        rejected=rejected,
        clamped=clamped,
    )


def _passive_kept(raw_slug: str, normalized_keys: set[str]) -> bool:
    candidates = {
        raw_slug,
        raw_slug.casefold(),
        normalize_name(raw_slug),
        ability_identifier(raw_slug),
    }
    return bool(candidates & normalized_keys)


def diff_passive(
    raw_loadout: dict[str, Any],
    normalized_passive: dict[str, int],
) -> list[str]:
    """Return positively selected passive slugs removed by normalization."""
    raw_passive = raw_loadout.get("passive")
    if not isinstance(raw_passive, dict):
        return []
    normalized_keys = set(normalized_passive)
    rejected: list[str] = []
    for slug, value in raw_passive.items():
        slug_text = str(slug).strip()
        if not slug_text or (_coerce_int(value) or 0) <= 0:
            continue
        if not _passive_kept(slug_text, normalized_keys):
            rejected.append(slug_text)
    return rejected


def validate_loadout(
    unit: models.Unit,
    raw_loadout: dict[str, Any],
    count: int = 1,
) -> LoadoutDiff:
    """Validate without persistence using only canonical normalize and quote."""
    raw = raw_loadout if isinstance(raw_loadout, dict) else {}
    normalized = normalize_roster_unit_loadout(unit, raw)
    sections = [
        diff_section(name, raw.get(name), normalized.get(name, {}))
        for name in _SECTIONS
    ]

    raw_mode = raw.get("mode")
    raw_mode_str = str(raw_mode).strip().lower() if raw_mode is not None else ""
    normalized_mode = normalized["mode"]
    mode_clamped = bool(raw_mode_str) and raw_mode_str not in ("total", "per_model")
    passive_rejected = diff_passive(raw, normalized.get("passive", {}))
    quote = calculate_roster_unit_quote(
        unit,
        raw,
        count,
        include_item_costs=False,
    )

    return LoadoutDiff(
        unit_id=int(getattr(unit, "id", 0) or 0),
        unit_name=str(getattr(unit, "name", "?") or "?"),
        count=count,
        raw_mode=raw_mode,
        normalized_mode=normalized_mode,
        mode_clamped=mode_clamped,
        sections=sections,
        passive_accepted=dict(normalized.get("passive", {})),
        passive_rejected=passive_rejected,
        selected_role=quote.get("selected_role"),
        selected_total=float(quote.get("selected_total") or 0.0),
        components={
            str(key): float(value)
            for key, value in sorted((quote.get("components") or {}).items())
        },
    )


def _unit_eager_options() -> tuple[Any, ...]:
    """Reuse the catalog-loading convention used by roster quote paths."""
    return (
        selectinload(models.Unit.weapon_links)
        .selectinload(models.UnitWeapon.weapon)
        .selectinload(models.Weapon.parent)
        .selectinload(models.Weapon.parent),
        selectinload(models.Unit.default_weapon)
        .selectinload(models.Weapon.parent)
        .selectinload(models.Weapon.parent),
        selectinload(models.Unit.abilities).selectinload(models.UnitAbility.ability),
        selectinload(models.Unit.army),
    )


def validate_loadout_by_id(
    session: Session,
    unit_id: int,
    raw_loadout: dict[str, Any],
    count: int = 1,
) -> LoadoutDiff:
    """Load one global catalog unit and return its read-only validation diff."""
    unit = session.execute(
        select(models.Unit)
        .where(models.Unit.id == unit_id)
        .options(*_unit_eager_options())
    ).scalar_one_or_none()
    if unit is None:
        raise UnitNotFoundError(f"Jednostka id={unit_id} nie istnieje")
    return validate_loadout(unit, raw_loadout, count)


def diff_to_dict(diff: LoadoutDiff) -> dict[str, Any]:
    """Serialize to a stable, finite ``szop.validate_loadout/v1`` payload."""
    payload = {
        "schema": LOADOUT_VALIDATION_SCHEMA,
        "version": LOADOUT_VALIDATION_VERSION,
        "unit_id": diff.unit_id,
        "unit_name": diff.unit_name,
        "count": diff.count,
        "mode": {
            "raw": diff.raw_mode,
            "normalized": diff.normalized_mode,
            "clamped": diff.mode_clamped,
        },
        "sections": [
            {
                "section": section.section,
                "accepted": section.accepted,
                "rejected": [
                    {"id": item_id, "reason": reason}
                    for item_id, reason in section.rejected
                ],
                "clamped": [
                    {"id": item_id, "raw": raw, "normalized": normalized}
                    for item_id, raw, normalized in section.clamped
                ],
            }
            for section in diff.sections
        ],
        "passive": {
            "accepted": diff.passive_accepted,
            "rejected": diff.passive_rejected,
        },
        "cost": {
            "selected_role": diff.selected_role,
            "selected_total": diff.selected_total,
            "components": diff.components,
        },
        "has_issues": diff.has_issues,
    }
    try:
        strict_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise LoadoutSerializationError(
            "Loadout validation result is not JSON-safe"
        ) from None
    return json.loads(strict_json)


__all__ = [
    "LOADOUT_VALIDATION_SCHEMA",
    "LOADOUT_VALIDATION_VERSION",
    "LoadoutDiff",
    "LoadoutSerializationError",
    "LoadoutValidationError",
    "SectionDiff",
    "UnitNotFoundError",
    "diff_passive",
    "diff_section",
    "diff_to_dict",
    "validate_loadout",
    "validate_loadout_by_id",
]
