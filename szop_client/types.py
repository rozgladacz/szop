"""Lightweight public value types shared by SZOP client implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.engine.state import BattleState


class RosterNotFoundError(LookupError):
    """A roster ID is missing or outside the caller's ownership scope."""


@dataclass(frozen=True, slots=True)
class BattleInviteMetadata:
    """Public metadata returned after creating a pending battle invite."""

    invite_id: int
    from_user_id: int
    to_user_id: int | None
    roster_id: int
    scenario: str
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for name in ("invite_id", "from_user_id", "roster_id"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be an int >= 1")
        if self.to_user_id is not None and (
            type(self.to_user_id) is not int or self.to_user_id < 1
        ):
            raise ValueError("to_user_id must be an int >= 1 or None")
        if not isinstance(self.scenario, str) or not self.scenario.strip():
            raise ValueError("scenario must be a non-empty string")
        if self.status != "pending":
            raise ValueError("new battle invite must be pending")
        for name in ("expires_at", "created_at", "updated_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is not None:
                raise ValueError(f"{name} must be a naive UTC datetime")


@dataclass(frozen=True, slots=True)
class BattleStateCheckpoint:
    """One coherent public state snapshot returned by ``GET /state``."""

    battle_id: int
    sequence_at: int
    schema: str
    version: int
    state: BattleState

    def __post_init__(self) -> None:
        if type(self.battle_id) is not int or self.battle_id < 1:
            raise ValueError("battle_id must be an int >= 1")
        if type(self.sequence_at) is not int or self.sequence_at < 0:
            raise ValueError("sequence_at must be an int >= 0")
        if not isinstance(self.schema, str) or not self.schema:
            raise ValueError("schema must be a non-empty string")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be an int >= 1")


@dataclass(frozen=True, slots=True)
class BattleActionProposal:
    """Frozen consent request returned by the public proposal endpoint."""

    proposal_id: int
    owner_user_id: int
    agent_user_id: int
    token_id: int | None
    battle_id: int
    expected_sequence: int
    action: dict[str, Any]
    summary: str
    status: str

    def __post_init__(self) -> None:
        for name in ("proposal_id", "owner_user_id", "agent_user_id", "battle_id"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be an int >= 1")
        if self.token_id is not None and (
            type(self.token_id) is not int or self.token_id < 1
        ):
            raise ValueError("token_id must be an int >= 1 or None")
        if type(self.expected_sequence) is not int or self.expected_sequence < 0:
            raise ValueError("expected_sequence must be an int >= 0")
        if type(self.action) is not dict:
            raise ValueError("action must be a JSON object")
        if not isinstance(self.summary, str) or not self.summary:
            raise ValueError("summary must be a non-empty string")
        if self.status != "pending":
            raise ValueError("new battle action proposal must be pending")


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    """Aggregated result of a simulation batch."""

    n_games: int
    wins_p0: int
    wins_p1: int
    draws: int
    total_rounds: int

    @property
    def win_rate_p0(self) -> float:
        return self.wins_p0 / self.n_games if self.n_games else 0.0

    @property
    def win_rate_p1(self) -> float:
        return self.wins_p1 / self.n_games if self.n_games else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.n_games if self.n_games else 0.0

    @property
    def avg_rounds(self) -> float:
        return self.total_rounds / self.n_games if self.n_games else 0.0
