"""Shared D6.2/P4 boundary for one consent-gated v1 bot proposal."""

import math

from ..engine.actions import Action, DefendAction, ManeuverAction, SpecialAction
from ..engine.pathfinding import ManeuverPlanner, is_finite_position
from ..engine.state import BattleState, Lokalizacja, effective_move_inches
from ..engine.status import STATUS_AKTYWOWANY, STATUS_PRZYGOTOWANY, STATUS_WYCZERPANY
from .registry import ALL_KINDS

SUPPORTED_KINDS = tuple(kind for kind in ALL_KINDS if kind == "priority")
_SUPPORTED_STATUSES = frozenset({STATUS_AKTYWOWANY, STATUS_PRZYGOTOWANY, STATUS_WYCZERPANY})


def unsupported_proposal_context(state: BattleState, side: int, *, status: str) -> str | None:
    if status != "active" or state.is_game_over or state.round not in range(1, 5):
        return "not_combat_round"
    if state.active_player != side:
        return "wrong_perspective"
    if state.activation is not None or state.initiative_player is not None:
        return "protocol_not_supported"
    if state.pending_effects or state.pending_interrupts or state.used_interrupts_this_round:
        return "pending_context"
    if state.terrain:
        return "terrain_not_supported"
    for blob in state.blobs:
        if blob.passives or blob.ability_overrides or blob.is_hero_unit:
            return "abilities_not_supported"
        if any(
            weapon.weapon_abilities or weapon.attack_quality_override is not None
            for weapon in (*blob.melee_weapons, *blob.ranged_weapons)
        ):
            return "abilities_not_supported"
        if not set(blob.status_flags) <= _SUPPORTED_STATUSES:
            return "status_not_supported"
        if blob.wounds_pending or blob.wounds_pending_precise or blob.damage_balance:
            return "pending_context"
        try:
            finite_radius = math.isfinite(blob.radius_inches)
        except OverflowError:
            finite_radius = False
        if not is_finite_position(blob.position) or not finite_radius or blob.radius_inches <= 0:
            return "geometry_not_supported"
    if any(not is_finite_position(obj.position) for obj in state.objectives):
        return "geometry_not_supported"
    return None


def unsupported_proposal_action(
    state: BattleState, side: int, action: Action, *, check_route: bool = True,
) -> str | None:
    actor = next((blob for blob in state.blobs if blob.id == action.unit_id), None)
    if (
        actor is None or actor.owner_player != side or actor.models_alive <= 0
        or actor.location is not Lokalizacja.FRONT or STATUS_AKTYWOWANY in actor.status_flags
    ):
        return "actor_not_supported"
    if type(action) not in (ManeuverAction, DefendAction, SpecialAction):
        return "action_not_supported"
    if isinstance(action, SpecialAction) and (
        action.ability_slug != "discard_exhausted" or action.payload
        or STATUS_WYCZERPANY not in actor.status_flags
    ):
        return "action_not_supported"
    if check_route and isinstance(action, ManeuverAction) and not ManeuverPlanner(
        state, actor, effective_move_inches(actor),
    ).can_reach(action.target_position):
        return "route_not_supported"
    return None
