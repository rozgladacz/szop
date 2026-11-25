"""Shared restrictions for combat and maneuver selection."""

from app.services.engine.geometry import circle_edge_distance
from app.services.engine.los import LoSState, check_los
from app.services.engine.state import BattleState, Lokalizacja, UnitBlob, effective_passives
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY

_CLOSE_ENEMY_RANGE_INCHES = 2.0
_ELEVATED_PASSIVES = {"wysoki", "samolot"}


def attack_allowed_by_status(unit: UnitBlob) -> bool:
    """Read the attack restriction from Rozjemca 22.a.i."""
    return STATUS_WYCZERPANY not in unit.status_flags


def maneuver_allowed_by_status(unit: UnitBlob) -> bool:
    """Read the Maneuver restriction from Rozjemca 22.b.i."""
    return STATUS_PRZYSZPILONY not in unit.status_flags


def shooting_lock_reason(
    state: BattleState, attacker: UnitBlob, *, require_supported_elevation: bool = False,
) -> str | None:
    """Check the action-level lock (Rozjemca 14.c.iv and 6) using MVP geometry.

    Strażnik retains its stricter supported scope for elevated LoS on terrain.
    """
    check_elevation = require_supported_elevation and bool(state.terrain)
    attacker_elevated = check_elevation and not _ELEVATED_PASSIVES.isdisjoint(
        effective_passives(attacker)
    )
    for enemy in state.blobs:
        if (
            enemy.owner_player == attacker.owner_player
            or enemy.models_alive <= 0
            or enemy.location is not Lokalizacja.FRONT
        ):
            continue
        gap = circle_edge_distance(
            attacker.position, attacker.radius_inches, enemy.position, enemy.radius_inches,
        )
        if gap > _CLOSE_ENEMY_RANGE_INCHES:
            continue
        if check_elevation and (
            attacker_elevated or not _ELEVATED_PASSIVES.isdisjoint(effective_passives(enemy))
        ):
            return "unsupported_close_enemy_line_of_sight"
        if check_los(attacker, enemy, state.terrain) is not LoSState.NIE_WIDZI:
            return "visible_enemy_within_2in"
    return None
