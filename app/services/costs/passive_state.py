"""Army / unit helpers and passive-state computation.

Extracted from ``_engine.py`` Section 3 (ARMY / UNIT HELPERS & PASSIVE STATE).

These helpers sit just above ``primitives`` in the dependency DAG — they only
depend on:
- ``PassiveState`` dataclass (from ``_engine`` Section 2, always loaded first)
- ``ability_identifier``, ``normalize_name`` (from ``primitives``)
- ``passive_flags_to_payload``, ``ARMY_RULE_OFF_PREFIX`` (from ``utils``)
- Standard library (``json``, typing)

No weapon- or ability-cost logic lives here.  ``compute_passive_state`` is
called from Section 7 (unit_helpers), Section 8 (quote), and Section 9
(role_totals) — all of those re-import it from ``_engine``'s globals after the
Section 3 stub fires.

Monkeypatching note: tests patch ``costs._engine.compute_passive_state`` to
override its behaviour inside ``roster_unit_role_totals`` (which lives in
``_engine``).  That still works because the stub re-exports the name into
``_engine``'s namespace.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from ... import models
from ..utils import ARMY_RULE_OFF_PREFIX, passive_flags_to_payload
from ._engine import PassiveState
from .primitives import ability_identifier, normalize_name


def normalize_roster_unit_count(count: Any, *, default: int = 0) -> int:
    """Normalize roster-unit ``count`` to a deterministic non-negative integer.

    Parsing failures return ``default``. Values less than or equal to zero
    are clamped to ``0``.
    """
    try:
        normalized = int(count)
    except (TypeError, ValueError):
        try:
            normalized = int(float(count))
        except (TypeError, ValueError):
            normalized = int(default)
    return normalized if normalized > 0 else 0


def _ensure_extra_data(extra: Any) -> dict[str, Any] | None:
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str):
        try:
            parsed = json.loads(extra)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _army_rule_entries(army: models.Army | None) -> list[dict[str, Any]]:
    if army is None:
        return []
    payload: list[dict[str, Any]] = []
    for entry in passive_flags_to_payload(getattr(army, "passive_rules", None)):
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        is_default = bool(entry.get("is_default", True))
        payload.append(
            {
                "slug": slug,
                "label": entry.get("label") or slug,
                "value": entry.get("value"),
                "description": entry.get("description") or "",
                "is_default": is_default,
                "default_count": 1 if is_default else 0,
                "is_mandatory": bool(entry.get("is_mandatory", False)),
                "is_army_rule": not slug.startswith(ARMY_RULE_OFF_PREFIX),
            }
        )
    return payload


def army_rules(
    unit: models.Unit | None = None, army: models.Army | None = None
) -> list[dict[str, Any]]:
    source_army = army or getattr(unit, "army", None)
    return [dict(entry) for entry in _army_rule_entries(source_army)]


def _passive_payload(unit: models.Unit | None) -> list[dict[str, Any]]:
    if unit is None:
        return []
    payload: list[dict[str, Any]] = []
    for entry in passive_flags_to_payload(getattr(unit, "flags", None)):
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        is_default = bool(entry.get("is_default", False))
        payload.append(
            {
                "slug": slug,
                "label": entry.get("label") or slug,
                "value": entry.get("value"),
                "is_default": is_default,
                "default_count": 1 if is_default else 0,
            }
        )
    return payload


def _passive_payload_with_army(unit: models.Unit | None) -> list[dict[str, Any]]:
    payload = _passive_payload(unit)
    if unit is None:
        return payload
    payload.extend(_army_rule_entries(getattr(unit, "army", None)))
    return payload


def _parse_passive_counts(extra: dict[str, Any] | None) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(extra, dict):
        return result
    raw_section = extra.get("passive")
    if isinstance(raw_section, dict):
        iterable = raw_section.items()
    elif isinstance(raw_section, list):
        iterable = []
        for entry in raw_section:
            if not isinstance(entry, dict):
                continue
            key = entry.get("slug") or entry.get("id")
            if key is None:
                continue
            iterable.append((key, entry.get("count") or entry.get("per_model") or entry.get("enabled")))
    else:
        return result
    for raw_key, raw_value in iterable:
        slug = str(raw_key).strip()
        if not slug:
            continue
        value = raw_value
        if isinstance(value, bool):
            result[slug] = 1 if value else 0
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            try:
                parsed = int(float(value))
            except (TypeError, ValueError):
                parsed = 1 if value else 0
        result[slug] = 1 if parsed > 0 else 0
    return result


def _apply_army_rule_overrides(
    payload: Sequence[dict[str, Any]],
    counts: dict[str, int],
    prefix: str = ARMY_RULE_OFF_PREFIX,
) -> dict[str, int]:
    disabled_slugs: set[str] = set()
    disabled_identifiers: set[str] = set()

    def _register_disabled(base_slug: str) -> None:
        if not base_slug:
            return
        disabled_slugs.add(base_slug)
        identifier = ability_identifier(base_slug)
        if identifier:
            disabled_identifiers.add(identifier)

    for entry in payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug or not slug.startswith(prefix):
            continue
        default_count = int(entry.get("default_count") or 0)
        selected = counts.get(slug, default_count)
        if selected <= 0:
            continue
        _register_disabled(slug[len(prefix) :].strip())

    for slug, value in counts.items():
        text = str(slug).strip()
        if not text.startswith(prefix) or value <= 0:
            continue
        _register_disabled(text[len(prefix) :].strip())

    if not disabled_slugs and not disabled_identifiers:
        return counts

    updated = dict(counts)
    for entry in payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug or slug.startswith(prefix):
            continue
        identifier = ability_identifier(slug)
        if slug in disabled_slugs or (identifier and identifier in disabled_identifiers):
            updated[slug] = 0

    for slug in disabled_slugs:
        updated.setdefault(slug, 0)
    for identifier in disabled_identifiers:
        updated.setdefault(identifier, 0)

    return updated


def _active_traits_from_payload(
    payload: Sequence[dict[str, Any]], counts: dict[str, int]
) -> list[str]:
    traits: list[str] = []
    for entry in payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        if slug.startswith(ARMY_RULE_OFF_PREFIX):
            continue
        identifier = ability_identifier(slug)
        target_slug = identifier or slug
        default_count = int(entry.get("default_count") or 0)
        selected = counts.get(str(slug), default_count)
        if selected <= 0:
            continue
        value = entry.get("value")
        if isinstance(value, bool):
            if value:
                traits.append(target_slug)
            continue
        if value is None:
            traits.append(target_slug)
            continue
        value_str = str(value).strip()
        if not value_str or value_str.casefold() in {"true", "yes"}:
            traits.append(target_slug)
        elif value_str.casefold() in {"false", "no", "0"}:
            continue
        else:
            traits.append(f"{target_slug}({value_str})")
    return traits


def _canonicalize_passive_counts(
    payload: Sequence[dict[str, Any]], counts: dict[str, int]
) -> dict[str, int]:
    if not counts:
        return counts
    alias_to_slug: dict[str, str] = {}
    for entry in payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug or slug.startswith(ARMY_RULE_OFF_PREFIX):
            continue
        candidates = {slug, slug.casefold(), normalize_name(slug), ability_identifier(slug)}
        label = entry.get("label")
        if label:
            label_str = str(label).strip()
            if label_str:
                candidates.update(
                    {label_str, label_str.casefold(), normalize_name(label_str), ability_identifier(label_str)}
                )
        for candidate in candidates:
            if candidate:
                alias_to_slug.setdefault(candidate, slug)
    normalized: dict[str, int] = {}
    for raw_key, raw_value in counts.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if key.startswith(ARMY_RULE_OFF_PREFIX):
            target_key = key
        else:
            canonical = None
            for candidate in (key, key.casefold(), normalize_name(key), ability_identifier(key)):
                if not candidate:
                    continue
                if candidate in alias_to_slug:
                    canonical = alias_to_slug[candidate]
                    break
            target_key = canonical or key
        if int(raw_value) > 0:
            normalized[target_key] = 1
        else:
            normalized.setdefault(target_key, 0)
    return normalized


def compute_passive_state(
    unit: models.Unit | None, extra: dict[str, Any] | str | None = None
) -> PassiveState:
    payload = _passive_payload_with_army(unit)
    extra_data = _ensure_extra_data(extra)
    counts = _parse_passive_counts(extra_data)
    counts = _canonicalize_passive_counts(payload, counts)
    counts = _apply_army_rule_overrides(payload, counts)
    traits = _active_traits_from_payload(payload, counts)
    return PassiveState(payload=payload, counts=counts, traits=traits)


def _passive_flag_maps(passive_state: PassiveState) -> tuple[dict[str, int], dict[str, int]]:
    default_map: dict[str, int] = {}
    selected_map: dict[str, int] = {}
    for entry in passive_state.payload:
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        if slug.startswith(ARMY_RULE_OFF_PREFIX):
            continue
        try:
            default_count = int(entry.get("default_count") or 0)
        except (TypeError, ValueError):
            default_count = 0
        default_flag = 1 if default_count > 0 else 0
        selected_value = passive_state.counts.get(str(slug), default_flag)
        selected_flag = 1 if selected_value else 0
        identifiers: set[str] = set()
        for token in (slug, entry.get("label")):
            if not token:
                continue
            identifiers.add(normalize_name(token))
            ident = ability_identifier(token)
            if ident:
                identifiers.add(ident)
        for ident in {value for value in identifiers if value}:
            default_map[ident] = default_flag
            selected_map[ident] = selected_flag
    return default_map, selected_map


__all__ = [
    "_active_traits_from_payload",
    "_apply_army_rule_overrides",
    "_canonicalize_passive_counts",
    "_ensure_extra_data",
    "_passive_flag_maps",
    "_passive_payload",
    "_passive_payload_with_army",
    "_parse_passive_counts",
    "army_rules",
    "compute_passive_state",
    "normalize_roster_unit_count",
]
