"""Transactional boundary for creating durable battle invites."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import utcnow
from .agents.maps import MAP_BUILDERS


class BattleInviteCreateError(RuntimeError):
    """Base class for controlled invite-creation failures."""


class BattleInviteRosterNotFound(BattleInviteCreateError, LookupError):
    """The inviting principal cannot use the requested roster."""


class BattleInviteTargetNotFound(BattleInviteCreateError, LookupError):
    """The direct target is unavailable to the inviting principal."""


class BattleInviteScenarioInvalid(BattleInviteCreateError, ValueError):
    """The scenario is not present in the public map registry."""


def create_battle_invite(
    session: Session,
    *,
    from_user_id: int,
    to_user_id: int | None,
    roster_id: int,
    scenario: str,
    expires_in_hours: int,
    now: datetime | None = None,
) -> models.BattleInvite:
    """Stage one pending invite without committing the caller's transaction."""
    canonical_scenario = scenario.strip().lower()
    if canonical_scenario not in MAP_BUILDERS:
        raise BattleInviteScenarioInvalid

    owned_roster_id = session.execute(
        select(models.Roster.id).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == from_user_id,
        )
    ).scalar_one_or_none()
    if owned_roster_id is None:
        raise BattleInviteRosterNotFound

    if to_user_id is not None:
        target_user_id = session.execute(
            select(models.User.id).where(
                models.User.id == to_user_id,
                models.User.id != from_user_id,
                models.User.role != models.USER_ROLE_AGENT,
            )
        ).scalar_one_or_none()
        if target_user_id is None:
            raise BattleInviteTargetNotFound

    timestamp = utcnow() if now is None else now
    if timestamp.tzinfo is not None:
        raise ValueError("now must be naive UTC")

    invite = models.BattleInvite(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        roster_id=owned_roster_id,
        scenario=canonical_scenario,
        status=models.BATTLE_INVITE_STATUS_PENDING,
        expires_at=timestamp + timedelta(hours=expires_in_hours),
        accepted_by_user_id=None,
        accepted_roster_id=None,
        battle_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(invite)
    session.flush()
    return invite


__all__ = [
    "BattleInviteCreateError",
    "BattleInviteRosterNotFound",
    "BattleInviteScenarioInvalid",
    "BattleInviteTargetNotFound",
    "create_battle_invite",
]
