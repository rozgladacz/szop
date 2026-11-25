from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .battle_protocol import (
    ACTIVATION_PROTOCOL_VERSION_V1,
    ACTIVATION_PROTOCOL_VERSIONS,
    validate_activation_protocol_version,
)
from .db import Base, utcnow


ARMY_SPELL_NAME_MAX_LENGTH = 60
USER_ROLE_USER = "user"
USER_ROLE_AGENT = "agent"
USER_ROLE_ADMIN = "admin"
AGENT_PROPOSAL_STATUS_PENDING = "pending"
AGENT_PROPOSAL_STATUS_APPROVED = "approved"
AGENT_PROPOSAL_STATUS_EXECUTED = "executed"
AGENT_PROPOSAL_STATUS_REJECTED = "rejected"
AGENT_PROPOSAL_STATUS_STALE = "stale"
BATTLE_INVITE_STATUS_PENDING = "pending"
BATTLE_INVITE_STATUS_ACCEPTED = "accepted"
BATTLE_INVITE_STATUS_DECLINED = "declined"
BATTLE_INVITE_STATUS_EXPIRED = "expired"
BATTLE_INVITE_STATUSES = (
    BATTLE_INVITE_STATUS_PENDING,
    BATTLE_INVITE_STATUS_ACCEPTED,
    BATTLE_INVITE_STATUS_DECLINED,
    BATTLE_INVITE_STATUS_EXPIRED,
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


def touch_timestamps(mapper, connection, target) -> None:  # pragma: no cover - SQLAlchemy hook
    now = utcnow()
    if getattr(target, "created_at", None) is None:
        target.created_at = now
    target.updated_at = now


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=USER_ROLE_USER, nullable=False)

    armies: Mapped[List["Army"]] = relationship(back_populates="owner")
    armories: Mapped[List["Armory"]] = relationship(back_populates="owner")
    weapons: Mapped[List["Weapon"]] = relationship(back_populates="owner")
    rosters: Mapped[List["Roster"]] = relationship(back_populates="owner")
    abilities: Mapped[List["Ability"]] = relationship(
        "Ability", back_populates="owner", cascade="all, delete-orphan"
    )


class AgentToken(TimestampMixin, Base):
    __tablename__ = "agent_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    agent_user: Mapped[User] = relationship(foreign_keys=[agent_user_id])
    owner_user: Mapped[User] = relationship(foreign_keys=[owner_user_id])


class AgentAuditLog(Base):
    __tablename__ = "agent_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    agent_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )

    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])
    agent_user: Mapped[Optional[User]] = relationship(foreign_keys=[agent_user_id])


class AgentProposal(TimestampMixin, Base):
    __tablename__ = "agent_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    agent_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agent_tokens.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=AGENT_PROPOSAL_STATUS_PENDING, nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    producer_owner_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    owner_user: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    agent_user: Mapped[User] = relationship(foreign_keys=[agent_user_id])
    token: Mapped[Optional[AgentToken]] = relationship(foreign_keys=[token_id])
    decided_by_user: Mapped[Optional[User]] = relationship(
        foreign_keys=[decided_by_user_id]
    )


class BotProposalAttempt(Base):
    """Frozen result of creating one proposal for one account generation."""

    __tablename__ = "bot_proposal_attempts"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "owner_created_at", "attempt_id"),
        Index("ix_bot_proposal_attempts_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Historical identities deliberately survive deletion of an account or battle.
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    battle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[int] = mapped_column(Integer, nullable=False)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(32))
    expected_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_sequence: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    proposal_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agent_proposals.id", ondelete="RESTRICT"), unique=True
    )


class RuleSet(TimestampMixin, Base):
    __tablename__ = "rulesets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    armies: Mapped[List["Army"]] = relationship(back_populates="ruleset")


class Ability(TimestampMixin, Base):
    __tablename__ = "abilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost_hint: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    owner: Mapped[Optional[User]] = relationship(back_populates="abilities")
    unit_links: Mapped[List["UnitAbility"]] = relationship(back_populates="ability")


class Armory(TimestampMixin, Base):
    __tablename__ = "armories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("armories.id"), nullable=True)

    owner: Mapped[Optional[User]] = relationship(back_populates="armories")
    parent: Mapped[Optional["Armory"]] = relationship(remote_side="Armory.id", back_populates="variants")
    variants: Mapped[List["Armory"]] = relationship(back_populates="parent")
    weapons: Mapped[List["Weapon"]] = relationship(
        back_populates="armory", cascade="all, delete-orphan"
    )
    armies: Mapped[List["Army"]] = relationship(back_populates="armory")


class ArmoryDisabledWeapon(TimestampMixin, Base):
    __tablename__ = "armory_disabled_weapons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    armory_id: Mapped[int] = mapped_column(ForeignKey("armories.id"), nullable=False)
    weapon_id: Mapped[int] = mapped_column(ForeignKey("weapons.id"), nullable=False)

    armory: Mapped[Armory] = relationship()
    weapon: Mapped["Weapon"] = relationship()

    __table_args__ = (UniqueConstraint("armory_id", "weapon_id"),)


class Weapon(TimestampMixin, Base):
    __tablename__ = "weapons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    attacks: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cached_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weapons.id"), nullable=True)
    armory_id: Mapped[int] = mapped_column(ForeignKey("armories.id"), nullable=False)
    army_id: Mapped[Optional[int]] = mapped_column(ForeignKey("armies.id"), nullable=True)

    owner: Mapped[Optional[User]] = relationship(back_populates="weapons", foreign_keys=[owner_id])
    parent: Mapped[Optional["Weapon"]] = relationship(remote_side="Weapon.id")
    armory: Mapped[Armory] = relationship(back_populates="weapons")
    army: Mapped[Optional["Army"]] = relationship(back_populates="weapons")
    units: Mapped[List["Unit"]] = relationship(back_populates="default_weapon")

    def _inherited_value(self, attr: str, default=None):
        current: Weapon | None = self
        visited: set[int] = set()
        while current is not None:
            identifier = getattr(current, "id", None)
            if identifier is not None:
                if identifier in visited:
                    break
                visited.add(identifier)
            value = getattr(current, attr)
            if value is not None:
                return value
            current = current.parent
        return default

    def inherits_from_parent(self) -> bool:
        return self.parent_id is not None

    def is_overriding(self, attr: str) -> bool:
        if not self.parent:
            return True
        value = getattr(self, attr)
        if value is None:
            return False
        parent_value = self.parent._inherited_value(attr)
        return value != parent_value

    @property
    def effective_name(self) -> str:
        value = self._inherited_value("name", "")
        return value or ""

    @property
    def effective_range(self) -> str:
        value = self._inherited_value("range", "")
        return value or ""

    @property
    def effective_attacks(self) -> float:
        value = self._inherited_value("attacks", 1.0)
        return float(value if value is not None else 1.0)

    @property

    def display_attacks(self) -> int:
        value = self.effective_attacks
        if not math.isfinite(value):
            return 0
        return int(math.floor(value + 0.5))

    @property

    def effective_ap(self) -> int:
        value = self._inherited_value("ap", 0)
        return int(value if value is not None else 0)

    @property
    def effective_tags(self) -> Optional[str]:
        return self._inherited_value("tags")

    @property
    def effective_notes(self) -> Optional[str]:
        return self._inherited_value("notes")

    @property
    def effective_cached_cost(self) -> Optional[float]:
        value = self._inherited_value("cached_cost")
        return float(value) if value is not None else None

    def has_overrides(self) -> bool:
        if not self.parent:
            return True
        for attr in ("name", "range", "attacks", "ap", "tags", "notes"):
            if getattr(self, attr) is not None:
                return True
        return False


class Army(TimestampMixin, Base):
    __tablename__ = "armies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("armies.id"), nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    ruleset_id: Mapped[int] = mapped_column(ForeignKey("rulesets.id"), nullable=False)
    armory_id: Mapped[int] = mapped_column(ForeignKey("armories.id"), nullable=False)
    passive_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    parent: Mapped[Optional["Army"]] = relationship(remote_side="Army.id")
    owner: Mapped[Optional[User]] = relationship(back_populates="armies")
    ruleset: Mapped[RuleSet] = relationship(back_populates="armies")
    armory: Mapped[Armory] = relationship(back_populates="armies")
    units: Mapped[List["Unit"]] = relationship(
        back_populates="army",
        cascade="all, delete-orphan",
        order_by="Unit.position",
    )
    weapons: Mapped[List[Weapon]] = relationship(back_populates="army")
    rosters: Mapped[List["Roster"]] = relationship(back_populates="army")
    spells: Mapped[List["ArmySpell"]] = relationship(
        back_populates="army",
        cascade="all, delete-orphan",
        order_by="ArmySpell.position",
    )
    unit_groups: Mapped[List["UnitGroup"]] = relationship(
        back_populates="army",
        cascade="all, delete-orphan",
        order_by="UnitGroup.position",
    )


class ArmySpell(TimestampMixin, Base):
    __tablename__ = "army_spells"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    army_id: Mapped[int] = mapped_column(ForeignKey("armies.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ability_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("abilities.id"), nullable=True
    )
    ability_value: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    weapon_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("weapons.id"), nullable=True
    )
    base_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    custom_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    army: Mapped[Army] = relationship(back_populates="spells")
    ability: Mapped[Optional[Ability]] = relationship()
    weapon: Mapped[Optional[Weapon]] = relationship()

    @property
    def normalized_custom_name(self) -> str:
        value = (self.custom_name or "").strip()
        return value[:ARMY_SPELL_NAME_MAX_LENGTH]

    @property
    def base_display_label(self) -> str:
        return (self.base_label or "").strip()

    @property
    def display_label(self) -> str:
        base = self.base_display_label
        custom = self.normalized_custom_name
        if custom and base:
            return f"{custom} [{base}]"
        if custom:
            return custom
        return base

    @property
    def export_label(self) -> str:
        base = self.base_display_label
        custom = self.normalized_custom_name
        if custom and base:
            return f'"{custom}" {base}'
        if custom:
            return f'"{custom}"'
        return base

    @property
    def export_payload(self) -> dict[str, object]:
        return {
            "cost": int(self.cost or 0),
            "label": self.export_label,
            "description": (self.description or "").strip(),
        }


class UnitGroup(TimestampMixin, Base):
    __tablename__ = "unit_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    army_id: Mapped[int] = mapped_column(ForeignKey("armies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    army: Mapped["Army"] = relationship(back_populates="unit_groups")
    units: Mapped[List["Unit"]] = relationship(
        back_populates="group",
        order_by=lambda: (Unit.position, Unit.id),
    )


class Unit(TimestampMixin, Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quality: Mapped[int] = mapped_column(Integer, nullable=False)
    defense: Mapped[int] = mapped_column(Integer, nullable=False)
    toughness: Mapped[int] = mapped_column(Integer, nullable=False)
    flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_weapon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weapons.id"), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id"), nullable=True)
    army_id: Mapped[int] = mapped_column(ForeignKey("armies.id"), nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    typical_models: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_size_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    base_shape: Mapped[str] = mapped_column(String(20), nullable=False, default="round")
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("unit_groups.id"), nullable=True
    )

    army: Mapped[Army] = relationship(back_populates="units")
    group: Mapped[Optional["UnitGroup"]] = relationship(back_populates="units")
    owner: Mapped[Optional[User]] = relationship()
    default_weapon: Mapped[Optional[Weapon]] = relationship(back_populates="units", foreign_keys=[default_weapon_id])
    weapon_links: Mapped[List["UnitWeapon"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by=lambda: (UnitWeapon.position, UnitWeapon.id),
    )
    parent: Mapped[Optional["Unit"]] = relationship(remote_side="Unit.id")
    abilities: Mapped[List["UnitAbility"]] = relationship(
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by=lambda: (UnitAbility.position, UnitAbility.id),
    )
    roster_units: Mapped[List["RosterUnit"]] = relationship(back_populates="unit")

    @property
    def typical_model_count(self) -> int:
        try:
            value = int(getattr(self, "typical_models", 1))
        except (TypeError, ValueError):
            value = 1
        if value < 1:
            value = 1
        return value

    @property
    def default_weapons(self) -> List[Weapon]:
        weapons: list[Weapon] = []
        added = False
        for link in getattr(self, "weapon_links", []):
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
            weapons.extend([link.weapon] * count)
            added = True
        if not added and self.default_weapon:
            weapons.append(self.default_weapon)
        return weapons

    @property
    def default_weapon_ids(self) -> List[int]:
        ids: list[int] = []
        seen: set[int] = set()
        for link in getattr(self, "weapon_links", []):
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
            if not is_default or count <= 0 or link.weapon_id is None:
                continue
            if link.weapon_id not in seen:
                ids.append(link.weapon_id)
                seen.add(link.weapon_id)
        if self.default_weapon_id and self.default_weapon_id not in seen:
            ids.append(self.default_weapon_id)
        return ids

    @property
    def default_weapon_loadout(self) -> List[tuple[Weapon, int]]:
        loadout: list[tuple[Weapon, int]] = []
        for link in getattr(self, "weapon_links", []):
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
            loadout.append((link.weapon, count))
        if not loadout and self.default_weapon:
            loadout.append((self.default_weapon, 1))
        return loadout


class UnitWeapon(TimestampMixin, Base):
    __tablename__ = "unit_weapons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    weapon_id: Mapped[int] = mapped_column(ForeignKey("weapons.id"), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    unit: Mapped[Unit] = relationship(back_populates="weapon_links")
    weapon: Mapped[Weapon] = relationship()


class UnitAbility(TimestampMixin, Base):
    __tablename__ = "unit_abilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id"), nullable=False)
    params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    unit: Mapped[Unit] = relationship(back_populates="abilities")
    ability: Mapped[Ability] = relationship(back_populates="unit_links")


class Roster(TimestampMixin, Base):
    __tablename__ = "rosters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    army_id: Mapped[int] = mapped_column(ForeignKey("armies.id"), nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    points_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strategic_cards_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    army: Mapped[Army] = relationship(back_populates="rosters")
    owner: Mapped[Optional[User]] = relationship(back_populates="rosters")
    roster_units: Mapped[List["RosterUnit"]] = relationship(
        back_populates="roster",
        cascade="all, delete-orphan",
        order_by="RosterUnit.position",
    )


class RosterUnit(TimestampMixin, Base):
    __tablename__ = "roster_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    roster_id: Mapped[int] = mapped_column(ForeignKey("rosters.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extra_weapons_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cached_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    custom_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_roster_unit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roster_units.id", ondelete="SET NULL"), nullable=True
    )

    roster: Mapped[Roster] = relationship(back_populates="roster_units")
    unit: Mapped[Unit] = relationship(back_populates="roster_units")
    parent: Mapped[Optional["RosterUnit"]] = relationship(
        "RosterUnit",
        remote_side=[id],
        back_populates="attached_heroes",
        foreign_keys=[parent_roster_unit_id],
    )
    attached_heroes: Mapped[List["RosterUnit"]] = relationship(
        "RosterUnit",
        back_populates="parent",
        foreign_keys=[parent_roster_unit_id],
    )


class Battle(TimestampMixin, Base):
    """Pojedyncza bitwa 1v1 (Strumień B / ADR-0010 / roadmap B2).

    Wiersz `battles` przechowuje metadane gry; przebieg jest event-sourced w
    `battle_events` (append-only). `rng_seed` zapewnia determinizm replayu
    (ADR-0012). `p1_user_id`/`p2_user_id` są nullable — bitwy botów (Strumień D)
    nie mają człowieka po danej stronie. `status` ∈ {"pending", "active",
    "finished"} (MVP string; enum w B4). `winner_user_id` ustawiany po pkt 5.f
    (None = remis lub gra w toku).
    """

    __tablename__ = "battles"
    __table_args__ = (
        CheckConstraint(
            "activation_protocol_version IN "
            f"({', '.join(str(version) for version in ACTIVATION_PROTOCOL_VERSIONS)})",
            name="ck_battles_activation_protocol_version_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    p1_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    p2_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    p1_roster_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rosters.id"), nullable=True
    )
    p2_roster_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rosters.id"), nullable=True
    )
    winner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rng_seed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    activation_protocol_version: Mapped[int] = mapped_column(
        Integer,
        default=ACTIVATION_PROTOCOL_VERSION_V1,
        server_default=str(ACTIVATION_PROTOCOL_VERSION_V1),
        nullable=False,
    )

    events: Mapped[List["BattleEvent"]] = relationship(
        back_populates="battle",
        cascade="all, delete-orphan",
        order_by="BattleEvent.sequence",
    )
    checkpoints: Mapped[List["BattleCheckpoint"]] = relationship(
        back_populates="battle",
        cascade="all, delete-orphan",
        order_by="BattleCheckpoint.sequence_at",
    )

    @validates("activation_protocol_version")
    def _validate_activation_protocol_version(self, key: str, value: object) -> int:
        del key
        return validate_activation_protocol_version(value)


class BattleInvite(TimestampMixin, Base):
    """Trwałe zaproszenie do bitwy z pojedynczym wynikiem akceptacji."""

    __tablename__ = "battle_invites"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(status) for status in BATTLE_INVITE_STATUSES)})",
            name="ck_battle_invites_status_valid",
        ),
        CheckConstraint(
            "to_user_id IS NULL OR from_user_id <> to_user_id",
            name="ck_battle_invites_direct_not_self",
        ),
        CheckConstraint(
            f"status != '{BATTLE_INVITE_STATUS_ACCEPTED}' OR "
            "(accepted_by_user_id IS NOT NULL AND "
            "accepted_roster_id IS NOT NULL AND battle_id IS NOT NULL)",
            name="ck_battle_invites_accepted_result_complete",
        ),
        CheckConstraint(
            f"status = '{BATTLE_INVITE_STATUS_ACCEPTED}' OR "
            "(accepted_by_user_id IS NULL AND "
            "accepted_roster_id IS NULL AND battle_id IS NULL)",
            name="ck_battle_invites_nonaccepted_result_empty",
        ),
        CheckConstraint(
            "activation_protocol_version IN "
            f"({', '.join(str(version) for version in ACTIVATION_PROTOCOL_VERSIONS)})",
            name="ck_battle_invites_activation_protocol_version_valid",
        ),
        UniqueConstraint("battle_id", name="uq_battle_invites_battle_id"),
        Index(
            "ix_battle_invites_to_status_expires_at",
            "to_user_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_battle_invites_from_status_created_at",
            "from_user_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    roster_id: Mapped[int] = mapped_column(
        ForeignKey("rosters.id"), nullable=False
    )
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=BATTLE_INVITE_STATUS_PENDING, nullable=False
    )
    activation_protocol_version: Mapped[int] = mapped_column(
        Integer,
        default=ACTIVATION_PROTOCOL_VERSION_V1,
        server_default=str(ACTIVATION_PROTOCOL_VERSION_V1),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    accepted_roster_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rosters.id"), nullable=True
    )
    battle_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("battles.id"), nullable=True
    )

    from_user: Mapped[User] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped[Optional[User]] = relationship(foreign_keys=[to_user_id])
    roster: Mapped[Roster] = relationship(foreign_keys=[roster_id])
    accepted_by_user: Mapped[Optional[User]] = relationship(
        foreign_keys=[accepted_by_user_id]
    )
    accepted_roster: Mapped[Optional[Roster]] = relationship(
        foreign_keys=[accepted_roster_id]
    )
    battle: Mapped[Optional[Battle]] = relationship(foreign_keys=[battle_id])

    @validates("activation_protocol_version")
    def _validate_activation_protocol_version(self, key: str, value: object) -> int:
        del key
        return validate_activation_protocol_version(value)


class BattleEvent(Base):
    """Append-only event w bitwie (ADR-0010 / ADR-0046 — proof-of-completeness).

    Każdy wiersz to jeden `events.BattleEvent` (16 typów) zserializowany przez
    `event_to_json` → `payload_json`. `event_type` = nazwa klasy (discriminator,
    redundantna z payloadem dla zapytań/indeksu). `UniqueConstraint(battle_id,
    sequence)` egzekwuje globalne uporządkowanie i zapobiega duplikatom przy
    współbieżnym zapisie (optimistic locking — B4 API obsługuje retry).

    NIE używa `TimestampMixin` — event jest niemutowalny (append-only), więc
    `updated_at` nie ma sensu; własny `timestamp` znaczy moment zapisu.
    """

    __tablename__ = "battle_events"
    __table_args__ = (UniqueConstraint("battle_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(
        ForeignKey("battles.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    battle: Mapped[Battle] = relationship(back_populates="events")


class BattleCheckpoint(Base):
    """Versioned state + RNG checkpoint coherent with an event sequence."""

    __tablename__ = "battle_checkpoints"
    __table_args__ = (UniqueConstraint("battle_id", "sequence_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    battle_id: Mapped[int] = mapped_column(
        ForeignKey("battles.id"), nullable=False, index=True
    )
    sequence_at: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    rng_json: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    battle: Mapped[Battle] = relationship(back_populates="checkpoints")


for cls in [
    User,
    RuleSet,
    Ability,
    Armory,
    Weapon,
    Army,
    Unit,
    UnitWeapon,
    UnitAbility,
    Roster,
    RosterUnit,
    ArmySpell,
    Battle,
    BattleInvite,
    AgentToken,
    AgentProposal,
]:
    event.listen(cls, "before_insert", touch_timestamps)
    event.listen(cls, "before_update", touch_timestamps)
