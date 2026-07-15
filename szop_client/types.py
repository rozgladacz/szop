"""Lightweight public value types shared by SZOP client implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.engine.state import BattleState


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
