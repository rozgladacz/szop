"""SSOT serializacji snapshotów profili OPOS między API i ORM."""

from __future__ import annotations

import json
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.opos_rules import (
    QuoteBreakdown,
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    normalize_snapshot_abilities,
)


class UnitSnapshot(Protocol):
    name: str
    models_per_unit: int
    defense: object
    toughness: object
    passive_abilities_json: str
    special_abilities_json: str
    profiles_json: str


def _json_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def request_from_snapshot(
    snapshot: UnitSnapshot,
    *,
    unit_copies: int = 1,
    custom_stats_enabled: bool,
    simple_points_enabled: bool = False,
    small_battle_enabled: bool = False,
) -> UnitQuoteInput:
    passive_abilities, profiles, _ = normalize_snapshot_abilities(
        json.loads(snapshot.passive_abilities_json),
        json.loads(snapshot.profiles_json),
    )
    return UnitQuoteInput.model_validate(
        {
            "name": snapshot.name,
            "models_per_unit": snapshot.models_per_unit,
            "unit_copies": unit_copies,
            "defense": snapshot.defense,
            "toughness": snapshot.toughness,
            "passive_abilities": passive_abilities,
            "special_abilities": json.loads(snapshot.special_abilities_json),
            "profiles": profiles,
            "custom_stats_enabled": custom_stats_enabled,
            "simple_points_enabled": simple_points_enabled,
            "small_battle_enabled": small_battle_enabled,
        }
    )


def normalize_legacy_snapshot_records(session: Session) -> int:
    """Persist the OPOS 1.1 ability-category change in existing snapshots."""
    changed = 0
    for model in (models.UnitTemplate, models.RosterUnit):
        for snapshot in session.scalars(select(model)):
            passive_abilities, profiles, was_changed = normalize_snapshot_abilities(
                json.loads(snapshot.passive_abilities_json),
                json.loads(snapshot.profiles_json),
            )
            if not was_changed:
                continue
            snapshot.passive_abilities_json = _json_dump(passive_abilities)
            snapshot.profiles_json = _json_dump(profiles)
            changed += 1
    return changed


def _snapshot_values(request: UnitQuoteInput) -> dict[str, object]:
    return {
        "name": request.name,
        "models_per_unit": request.models_per_unit,
        "defense": request.defense,
        "toughness": request.toughness,
        "passive_abilities_json": _json_dump(list(request.passive_abilities)),
        "special_abilities_json": _json_dump(
            [item.model_dump(mode="json", exclude_none=True) for item in request.special_abilities]
        ),
        "profiles_json": _json_dump(request.profiles.model_dump(mode="json")),
    }


def apply_request_to_roster_unit(
    unit: models.RosterUnit,
    request: UnitQuoteInput,
    quote: QuoteBreakdown,
) -> None:
    for key, value in _snapshot_values(request).items():
        setattr(unit, key, value)
    unit.unit_copies = request.unit_copies
    unit.unit_cost = int(quote.rounded_unit_cost)


def create_template_from_roster_unit(
    roster_unit: models.RosterUnit,
    *,
    army: models.Army,
    position: int,
    ruleset_version: str,
) -> models.UnitTemplate:
    return models.UnitTemplate(
        army=army,
        owner_id=army.owner_id,
        name=roster_unit.name,
        models_per_unit=roster_unit.models_per_unit,
        defense=roster_unit.defense,
        toughness=roster_unit.toughness,
        passive_abilities_json=roster_unit.passive_abilities_json,
        special_abilities_json=roster_unit.special_abilities_json,
        profiles_json=roster_unit.profiles_json,
        ruleset_version=ruleset_version,
        position=position,
    )


def update_template_from_roster_unit(
    template: models.UnitTemplate,
    roster_unit: models.RosterUnit,
    *,
    ruleset_version: str,
) -> None:
    template.name = roster_unit.name
    template.models_per_unit = roster_unit.models_per_unit
    template.defense = roster_unit.defense
    template.toughness = roster_unit.toughness
    template.passive_abilities_json = roster_unit.passive_abilities_json
    template.special_abilities_json = roster_unit.special_abilities_json
    template.profiles_json = roster_unit.profiles_json
    template.ruleset_version = ruleset_version


def snapshot_requires_custom_stats(
    snapshot: UnitSnapshot,
    *,
    ruleset_version: str,
    small_battle_enabled: bool = False,
) -> bool:
    try:
        request = request_from_snapshot(
            snapshot,
            unit_copies=1,
            custom_stats_enabled=False,
            small_battle_enabled=small_battle_enabled,
        )
        calculate_unit_quote(request, ruleset_version=ruleset_version)
    except QuoteValidationError:
        return True
    return False


def template_requires_custom_stats(
    template: models.UnitTemplate, *, small_battle_enabled: bool = False
) -> bool:
    return snapshot_requires_custom_stats(
        template,
        ruleset_version=template.ruleset_version,
        small_battle_enabled=small_battle_enabled,
    )
