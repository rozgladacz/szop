"""Transactional boundary for durable battle-invite lifecycle operations."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..battle_protocol import (
    ACTIVATION_PROTOCOL_VERSION_V1,
    validate_activation_protocol_version,
)
from ..db import utcnow
from .agents.maps import MAP_BUILDERS, build_map
from .agents.roster_adapter import AdaptResult
from .battle_creation import stage_battle_creation


class BattleInviteCreateError(RuntimeError):
    """Base class for controlled invite-creation failures."""


class BattleInviteRosterNotFound(BattleInviteCreateError, LookupError):
    """The inviting principal cannot use the requested roster."""


class BattleInviteTargetNotFound(BattleInviteCreateError, LookupError):
    """The direct target is unavailable to the inviting principal."""


class BattleInviteScenarioInvalid(BattleInviteCreateError, ValueError):
    """The scenario is not present in the public map registry."""


class BattleInviteAcceptError(RuntimeError):
    """Base class for controlled invite-acceptance failures."""


class BattleInviteAcceptNotFound(BattleInviteAcceptError, LookupError):
    """The invite or a principal-scoped resource must remain undisclosed."""


class BattleInviteAcceptConflict(BattleInviteAcceptError):
    """The invite cannot produce the requested durable result."""


class BattleInviteAcceptRace(BattleInviteAcceptError):
    """A conditional transition lost a race and must be reread after rollback."""


class BattleInviteAcceptPending(BattleInviteAcceptRace):
    """A post-rollback reread still observes a pending invite."""


@dataclass(frozen=True, slots=True)
class BattleInviteAccepted:
    """A new or previously durable acceptance result."""

    battle: models.Battle
    created: bool
    adapted_p1: AdaptResult | None = None
    adapted_p2: AdaptResult | None = None


@dataclass(frozen=True, slots=True)
class BattleInviteExpiredStaged:
    """The caller must commit the staged pending-to-expired transition."""

    invite_id: int


BattleInviteAcceptOutcome = BattleInviteAccepted | BattleInviteExpiredStaged

_MAX_RNG_SEED = (1 << 63) - 1


def create_battle_invite(
    session: Session,
    *,
    from_user_id: int,
    to_user_id: int | None,
    roster_id: int,
    scenario: str,
    expires_in_hours: int,
    activation_protocol_version: int = ACTIVATION_PROTOCOL_VERSION_V1,
    now: datetime | None = None,
) -> models.BattleInvite:
    """Stage one pending invite without committing the caller's transaction."""
    protocol_version = validate_activation_protocol_version(
        activation_protocol_version
    )
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
        activation_protocol_version=protocol_version,
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


def stage_battle_invite_acceptance(
    session: Session,
    *,
    invite_id: int,
    acceptor_user_id: int,
    accepted_roster_id: int,
    session_acceptor_is_agent: bool = False,
    now: datetime | None = None,
    rng_seed_factory: Callable[[], int] | None = None,
) -> BattleInviteAcceptOutcome:
    """Stage expiry or one complete accepted result without commit/rollback.

    A first acceptance stages the provisional Battle graph before the final
    conditional UPDATE because ``battle_id`` is part of the invite CAS.  If the
    CAS loses, the caller must roll back, which removes that entire provisional
    graph before a safe reread.
    """
    if session_acceptor_is_agent:
        raise BattleInviteAcceptNotFound
    timestamp = _naive_utc(now)
    invite = _load_visible_invite(
        session,
        invite_id=invite_id,
        acceptor_user_id=acceptor_user_id,
    )
    if invite.status == models.BATTLE_INVITE_STATUS_ACCEPTED:
        return _existing_acceptance(
            session,
            invite=invite,
            acceptor_user_id=acceptor_user_id,
            accepted_roster_id=accepted_roster_id,
        )
    if invite.status in {
        models.BATTLE_INVITE_STATUS_DECLINED,
        models.BATTLE_INVITE_STATUS_EXPIRED,
    }:
        raise BattleInviteAcceptConflict
    if invite.status != models.BATTLE_INVITE_STATUS_PENDING:
        raise BattleInviteAcceptConflict

    if invite.expires_at <= timestamp:
        result = session.execute(
            update(models.BattleInvite)
            .where(
                models.BattleInvite.id == invite.id,
                models.BattleInvite.status == models.BATTLE_INVITE_STATUS_PENDING,
                models.BattleInvite.expires_at <= timestamp,
                models.BattleInvite.from_user_id == invite.from_user_id,
                _acceptor_target_clause(acceptor_user_id),
            )
            .values(
                status=models.BATTLE_INVITE_STATUS_EXPIRED,
                updated_at=timestamp,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise BattleInviteAcceptRace
        return BattleInviteExpiredStaged(invite_id=invite.id)

    roster_p1, roster_p2 = _load_acceptance_rosters(
        session,
        invite=invite,
        acceptor_user_id=acceptor_user_id,
        accepted_roster_id=accepted_roster_id,
    )
    if invite.scenario not in MAP_BUILDERS:
        raise BattleInviteAcceptConflict

    seed_factory = rng_seed_factory or _new_rng_seed
    rng_seed = seed_factory()
    if type(rng_seed) is not int or not 0 <= rng_seed <= _MAX_RNG_SEED:
        raise ValueError("rng_seed_factory must return an unsigned 63-bit integer")
    initiative_player = rng_seed & 1
    fixture = build_map(invite.scenario, rng_seed)
    staged = stage_battle_creation(
        session,
        p1_user_id=invite.from_user_id,
        p2_user_id=acceptor_user_id,
        p1_roster=roster_p1,
        p2_roster=roster_p2,
        rng_seed=rng_seed,
        initiative_player=initiative_player,
        terrain=fixture.terrain,
        objectives=fixture.objectives,
        activation_protocol_version=invite.activation_protocol_version,
    )
    battle = staged.battle

    claimed = session.execute(
        update(models.BattleInvite)
        .where(
            models.BattleInvite.id == invite.id,
            models.BattleInvite.status == models.BATTLE_INVITE_STATUS_PENDING,
            models.BattleInvite.expires_at > timestamp,
            models.BattleInvite.from_user_id == invite.from_user_id,
            models.BattleInvite.roster_id == invite.roster_id,
            models.BattleInvite.scenario == invite.scenario,
            models.BattleInvite.activation_protocol_version
            == invite.activation_protocol_version,
            _acceptor_target_clause(acceptor_user_id),
        )
        .values(
            status=models.BATTLE_INVITE_STATUS_ACCEPTED,
            accepted_by_user_id=acceptor_user_id,
            accepted_roster_id=roster_p2.id,
            battle_id=battle.id,
            updated_at=timestamp,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise BattleInviteAcceptRace
    return BattleInviteAccepted(
        battle=battle,
        created=True,
        adapted_p1=staged.adapted_p1,
        adapted_p2=staged.adapted_p2,
    )


def read_battle_invite_acceptance(
    session: Session,
    *,
    invite_id: int,
    acceptor_user_id: int,
    accepted_roster_id: int,
    session_acceptor_is_agent: bool = False,
) -> BattleInviteAccepted:
    """Classify a post-rollback result without staging any domain writes."""
    if session_acceptor_is_agent:
        raise BattleInviteAcceptNotFound
    invite = _load_visible_invite(
        session,
        invite_id=invite_id,
        acceptor_user_id=acceptor_user_id,
    )
    if invite.status == models.BATTLE_INVITE_STATUS_ACCEPTED:
        return _existing_acceptance(
            session,
            invite=invite,
            acceptor_user_id=acceptor_user_id,
            accepted_roster_id=accepted_roster_id,
        )
    if invite.status == models.BATTLE_INVITE_STATUS_PENDING:
        raise BattleInviteAcceptPending
    raise BattleInviteAcceptConflict


def _load_visible_invite(
    session: Session,
    *,
    invite_id: int,
    acceptor_user_id: int,
) -> models.BattleInvite:
    invite = session.execute(
        select(models.BattleInvite)
        .join(models.User, models.User.id == acceptor_user_id)
        .where(
            models.BattleInvite.id == invite_id,
            models.User.role.in_(
                (models.USER_ROLE_USER, models.USER_ROLE_ADMIN)
            ),
        )
    ).scalar_one_or_none()
    if (
        invite is None
        or invite.from_user_id == acceptor_user_id
        or (
            invite.to_user_id is not None
            and invite.to_user_id != acceptor_user_id
        )
    ):
        raise BattleInviteAcceptNotFound
    return invite


def _existing_acceptance(
    session: Session,
    *,
    invite: models.BattleInvite,
    acceptor_user_id: int,
    accepted_roster_id: int,
) -> BattleInviteAccepted:
    if (
        invite.accepted_by_user_id is None
        or invite.accepted_roster_id is None
        or invite.battle_id is None
    ):
        raise BattleInviteAcceptConflict
    if invite.accepted_by_user_id != acceptor_user_id:
        if invite.to_user_id is None:
            raise BattleInviteAcceptNotFound
        raise BattleInviteAcceptConflict
    if invite.accepted_roster_id != accepted_roster_id:
        raise BattleInviteAcceptConflict

    battle = session.execute(
        select(models.Battle).where(models.Battle.id == invite.battle_id)
    ).scalar_one_or_none()
    if (
        battle is None
        or battle.p1_user_id != invite.from_user_id
        or battle.p2_user_id != invite.accepted_by_user_id
        or battle.p1_roster_id != invite.roster_id
        or battle.p2_roster_id != invite.accepted_roster_id
        or battle.activation_protocol_version
        != invite.activation_protocol_version
    ):
        raise BattleInviteAcceptConflict
    return BattleInviteAccepted(battle=battle, created=False)


def _load_acceptance_rosters(
    session: Session,
    *,
    invite: models.BattleInvite,
    acceptor_user_id: int,
    accepted_roster_id: int,
) -> tuple[models.Roster, models.Roster]:
    rosters = session.execute(
        select(models.Roster)
        .where(
            or_(
                and_(
                    models.Roster.id == invite.roster_id,
                    models.Roster.owner_id == invite.from_user_id,
                ),
                and_(
                    models.Roster.id == accepted_roster_id,
                    models.Roster.owner_id == acceptor_user_id,
                ),
            )
        )
        .options(*_roster_eager_options())
    ).scalars().all()
    roster_p2 = next(
        (
            roster
            for roster in rosters
            if roster.id == accepted_roster_id
            and roster.owner_id == acceptor_user_id
        ),
        None,
    )
    if roster_p2 is None:
        raise BattleInviteAcceptNotFound
    roster_p1 = next(
        (
            roster
            for roster in rosters
            if roster.id == invite.roster_id
            and roster.owner_id == invite.from_user_id
        ),
        None,
    )
    if roster_p1 is None:
        raise BattleInviteAcceptConflict
    return roster_p1, roster_p2


def _roster_eager_options() -> tuple:
    """Bounded graph required by ``roster_to_engine_roster`` for both sides."""
    return (
        selectinload(models.Roster.roster_units).options(
            selectinload(models.RosterUnit.unit).options(
                selectinload(models.Unit.weapon_links)
                .selectinload(models.UnitWeapon.weapon)
                .selectinload(models.Weapon.parent)
                .selectinload(models.Weapon.parent),
                selectinload(models.Unit.default_weapon)
                .selectinload(models.Weapon.parent)
                .selectinload(models.Weapon.parent),
                selectinload(models.Unit.abilities).selectinload(
                    models.UnitAbility.ability
                ),
            )
        ),
    )


def _acceptor_target_clause(acceptor_user_id: int):
    return or_(
        models.BattleInvite.to_user_id.is_(None),
        models.BattleInvite.to_user_id == acceptor_user_id,
    )


def _naive_utc(now: datetime | None) -> datetime:
    timestamp = utcnow() if now is None else now
    if timestamp.tzinfo is not None:
        raise ValueError("now must be naive UTC")
    return timestamp


def _new_rng_seed() -> int:
    return secrets.randbits(63)


__all__ = [
    "BattleInviteAcceptConflict",
    "BattleInviteAcceptError",
    "BattleInviteAcceptNotFound",
    "BattleInviteAcceptOutcome",
    "BattleInviteAcceptPending",
    "BattleInviteAcceptRace",
    "BattleInviteAccepted",
    "BattleInviteCreateError",
    "BattleInviteExpiredStaged",
    "BattleInviteRosterNotFound",
    "BattleInviteScenarioInvalid",
    "BattleInviteTargetNotFound",
    "create_battle_invite",
    "read_battle_invite_acceptance",
    "stage_battle_invite_acceptance",
]
