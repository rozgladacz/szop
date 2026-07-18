"""Production SSOT for read-only scoring of one roster against an owned field."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app import models
from app.services.agents.roster_adapter import roster_points
from app.services.roster_simulation import simulate_roster_pair
from szop_client.types import RosterNotFoundError, SimulationSummary

SCORE_LIST_SCHEMA = "szop.score_list/v1"
SCORE_LIST_VERSION = 1
MAX_SCORE_OPPONENTS = 10
MAX_SCORE_GAMES_PER_OPPONENT = 10
MAX_SCORE_TOTAL_GAMES = 50
MAX_ROSTER_COMPOSITION_LENGTH = 4000
MAX_DATABASE_ID = 2**63 - 1


class RosterScoringError(RuntimeError):
    """Base class for controlled score-list failures."""


class ScoreWorkloadError(RosterScoringError):
    """The requested field would exceed the public bounded workload."""


class ScoreRequestError(RosterScoringError):
    """The requested opponent field is structurally invalid."""


class ScoreSerializationError(RosterScoringError):
    """A roster or score cannot be projected to the stable public schema."""


@dataclass(frozen=True, slots=True)
class RosterInfo:
    """Lightweight roster projection that never retains an ORM object."""

    id: int
    name: str
    army: str
    points: float
    composition: str


@dataclass(frozen=True, slots=True)
class OpponentResult:
    """Target-as-player-zero result against one opponent."""

    opponent: RosterInfo
    summary: SimulationSummary

    @property
    def win_rate(self) -> float:
        return self.summary.win_rate_p0


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    """Aggregate from the target perspective; empty groups use zero rates."""

    n_opponents: int
    n_games_total: int
    wins: int
    losses: int
    draws: int
    total_rounds: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.n_games_total if self.n_games_total else 0.0

    @property
    def loss_rate(self) -> float:
        return self.losses / self.n_games_total if self.n_games_total else 0.0

    @property
    def draw_rate(self) -> float:
        return self.draws / self.n_games_total if self.n_games_total else 0.0

    @property
    def avg_rounds(self) -> float:
        return self.total_rounds / self.n_games_total if self.n_games_total else 0.0


def _unit_eager_options() -> tuple[Any, ...]:
    """Load every relation used by roster projection, costing, and adaptation."""
    return (
        selectinload(models.Unit.weapon_links)
        .selectinload(models.UnitWeapon.weapon),
        selectinload(models.Unit.default_weapon),
        selectinload(models.Unit.abilities).selectinload(models.UnitAbility.ability),
        selectinload(models.Unit.army),
    )


def _roster_eager_options() -> tuple[Any, ...]:
    return (
        selectinload(models.Roster.army),
        selectinload(models.Roster.roster_units).options(
            selectinload(models.RosterUnit.unit).options(*_unit_eager_options())
        ),
    )


def _load_weapon_ancestors(
    session: Session,
    rosters: Sequence[models.Roster],
) -> None:
    """Populate every referenced weapon ancestor with one recursive batch query."""
    weapon_ids = {
        weapon_id
        for roster in rosters
        for roster_unit in roster.roster_units
        for weapon_id in (
            roster_unit.unit.default_weapon_id,
            *(link.weapon_id for link in roster_unit.unit.weapon_links),
        )
        if weapon_id is not None
    }
    if not weapon_ids:
        return

    ancestors = (
        select(models.Weapon.id, models.Weapon.parent_id)
        .where(models.Weapon.id.in_(weapon_ids))
        .cte("score_weapon_ancestors", recursive=True)
    )
    parent = aliased(models.Weapon)
    ancestors = ancestors.union(
        select(parent.id, parent.parent_id).join(
            ancestors,
            parent.id == ancestors.c.parent_id,
        )
    )
    loaded = list(
        session.execute(
            select(models.Weapon).where(
                models.Weapon.id.in_(select(ancestors.c.id))
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_id = {int(weapon.id): weapon for weapon in loaded}
    for weapon in loaded:
        set_committed_value(
            weapon,
            "parent",
            by_id.get(int(weapon.parent_id)) if weapon.parent_id is not None else None,
        )


def _bounded_composition(value: str) -> str:
    if len(value) <= MAX_ROSTER_COMPOSITION_LENGTH:
        return value
    return value[: MAX_ROSTER_COMPOSITION_LENGTH - 1] + "…"


def _composition_summary(roster: models.Roster) -> str:
    parts: list[str] = []
    roster_units = sorted(
        roster.roster_units,
        key=lambda item: (int(item.position), int(item.id)),
    )
    for roster_unit in roster_units:
        unit_name = roster_unit.unit.name if roster_unit.unit is not None else "?"
        parts.append(f"{int(roster_unit.count)}×{unit_name or '?'}")
    return _bounded_composition(", ".join(parts))


def roster_info(roster: models.Roster) -> RosterInfo:
    """Project an eagerly loaded roster to finite, bounded public values."""
    points = round(float(roster_points(roster)), 2)
    if not math.isfinite(points) or points < 0.0:
        raise ScoreSerializationError("roster points are not finite and non-negative")
    roster_id = int(roster.id)
    if roster_id < 1:
        raise ScoreSerializationError("roster id is not positive")
    return RosterInfo(
        id=roster_id,
        name=str(roster.name or "?")[:120],
        army=str(roster.army.name if roster.army is not None else "?")[:120],
        points=points,
        composition=_composition_summary(roster),
    )


def _load_rosters(
    session: Session,
    *,
    roster_ids: Sequence[int] | None = None,
    owner_user_id: int | None = None,
) -> list[models.Roster]:
    statement = select(models.Roster).options(*_roster_eager_options())
    if roster_ids is not None:
        statement = statement.where(models.Roster.id.in_(tuple(roster_ids)))
    if owner_user_id is not None:
        statement = statement.where(models.Roster.owner_id == owner_user_id)
    rosters = list(
        session.execute(statement.order_by(models.Roster.id))
        .scalars()
        .unique()
        .all()
    )
    _load_weapon_ancestors(session, rosters)
    return rosters


def list_rosters(session: Session) -> list[RosterInfo]:
    """Return every roster for the administrative leaf CLI, ordered by ID."""
    return [roster_info(roster) for roster in _load_rosters(session)]


def _select_opponents(
    session: Session,
    roster_id: int,
    *,
    vs_ids: Sequence[int] | None,
    army: str | None,
) -> list[RosterInfo]:
    """Compatibility selector used by the leaf CLI."""
    field = [info for info in list_rosters(session) if info.id != roster_id]
    if vs_ids is not None:
        wanted = set(vs_ids)
        field = [info for info in field if info.id in wanted]
    elif army is not None:
        wanted_army = army.casefold()
        field = [info for info in field if info.army.casefold() == wanted_army]
    return field


def _owned_default_opponent_ids(
    session: Session,
    roster_id: int,
    *,
    owner_user_id: int,
    max_opponents: int | None,
) -> list[int]:
    target_id = session.scalar(
        select(models.Roster.id).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == owner_user_id,
        )
    )
    if target_id is None:
        raise RosterNotFoundError("roster is not visible in owner scope")

    statement = (
        select(models.Roster.id)
        .where(
            models.Roster.owner_id == owner_user_id,
            models.Roster.id != roster_id,
        )
        .order_by(models.Roster.id)
    )
    if max_opponents is not None:
        statement = statement.limit(max_opponents + 1)
    return list(session.scalars(statement).all())


def _owned_field(
    session: Session,
    roster_id: int,
    *,
    owner_user_id: int,
    opponent_roster_ids: Sequence[int] | None,
    games_per_opponent: int,
    max_opponents: int | None,
    max_total_games: int | None,
) -> tuple[models.Roster, list[models.Roster]]:
    if opponent_roster_ids is None:
        selected_ids = _owned_default_opponent_ids(
            session,
            roster_id,
            owner_user_id=owner_user_id,
            max_opponents=max_opponents,
        )
    else:
        selected_ids = list(opponent_roster_ids)
        if roster_id in selected_ids or len(set(selected_ids)) != len(selected_ids):
            raise ScoreRequestError("opponent IDs must be unique and exclude target")
        if any(item > MAX_DATABASE_ID for item in selected_ids):
            raise RosterNotFoundError("roster is not visible in owner scope")

    if max_opponents is not None and len(selected_ids) > max_opponents:
        raise ScoreWorkloadError("score field exceeds opponent limit")
    if (
        max_total_games is not None
        and games_per_opponent * len(selected_ids) > max_total_games
    ):
        raise ScoreWorkloadError("score field exceeds total game limit")

    requested_ids = sorted({roster_id, *selected_ids})
    loaded = _load_rosters(
        session,
        roster_ids=requested_ids,
        owner_user_id=owner_user_id,
    )
    by_id = {int(roster.id): roster for roster in loaded}
    if set(by_id) != set(requested_ids):
        raise RosterNotFoundError("roster is not visible in owner scope")
    return by_id[roster_id], [by_id[item] for item in sorted(selected_ids)]


def _global_cli_field(
    session: Session,
    roster_id: int,
    *,
    opponent_roster_ids: Sequence[int] | None,
    army: str | None,
) -> tuple[models.Roster, list[models.Roster]]:
    loaded = _load_rosters(session)
    by_id = {int(roster.id): roster for roster in loaded}
    target = by_id.get(roster_id)
    if target is None:
        raise RosterNotFoundError(f"Roster id={roster_id} nie istnieje")
    opponents = [roster for roster in loaded if int(roster.id) != roster_id]
    if opponent_roster_ids is not None:
        selected = set(opponent_roster_ids)
        opponents = [roster for roster in opponents if int(roster.id) in selected]
    elif army is not None:
        wanted_army = army.casefold()
        opponents = [
            roster
            for roster in opponents
            if (roster.army.name if roster.army is not None else "?").casefold()
            == wanted_army
        ]
    return target, opponents


def aggregate_score(results: Sequence[OpponentResult]) -> ScoreSummary:
    """Sum pair results from the target/player-zero perspective."""
    return ScoreSummary(
        n_opponents=len(results),
        n_games_total=sum(result.summary.n_games for result in results),
        wins=sum(result.summary.wins_p0 for result in results),
        losses=sum(result.summary.wins_p1 for result in results),
        draws=sum(result.summary.draws for result in results),
        total_rounds=sum(result.summary.total_rounds for result in results),
    )


def score_list(
    session: Session,
    roster_id: int,
    *,
    bot: str = "priority",
    n: int = 10,
    seed: int = 0,
    map_name: str = "lustrzana_a",
    vs_ids: Sequence[int] | None = None,
    army: str | None = None,
    owner_user_id: int | None = None,
    allowed_bots: Sequence[str] | None = None,
    max_opponents: int | None = None,
    max_total_games: int | None = None,
) -> tuple[RosterInfo, list[OpponentResult]]:
    """Score one roster against a deterministic field without domain writes."""
    if (
        type(roster_id) is not int
        or roster_id < 1
        or roster_id > MAX_DATABASE_ID
    ):
        raise RosterNotFoundError("roster is not visible in owner scope")
    if type(n) is not int or n < 1:
        raise ScoreRequestError("games per opponent must be positive")

    if owner_user_id is None:
        target, opponents = _global_cli_field(
            session,
            roster_id,
            opponent_roster_ids=vs_ids,
            army=army,
        )
    else:
        target, opponents = _owned_field(
            session,
            roster_id,
            owner_user_id=owner_user_id,
            opponent_roster_ids=vs_ids,
            games_per_opponent=n,
            max_opponents=max_opponents,
            max_total_games=max_total_games,
        )

    projected = {int(roster.id): roster_info(roster) for roster in [target, *opponents]}
    results = [
        OpponentResult(
            opponent=projected[int(opponent.id)],
            summary=simulate_roster_pair(
                target,
                opponent,
                bot=bot,
                games=n,
                seed=seed,
                map_name=map_name,
                allowed_bots=allowed_bots,
            ),
        )
        for opponent in opponents
    ]
    return projected[int(target.id)], results


def _roster_info_to_dict(info: RosterInfo) -> dict[str, Any]:
    return {
        "id": info.id,
        "name": info.name,
        "army": info.army,
        "points": float(info.points),
        "composition": info.composition,
    }


def _summary_to_dict(summary: ScoreSummary) -> dict[str, int | float]:
    return {
        "n_opponents": summary.n_opponents,
        "n_games": summary.n_games_total,
        "wins": summary.wins,
        "losses": summary.losses,
        "draws": summary.draws,
        "rounds": summary.total_rounds,
        "win_rate": float(summary.win_rate),
        "loss_rate": float(summary.loss_rate),
        "draw_rate": float(summary.draw_rate),
        "avg_rounds": float(summary.avg_rounds),
    }


def score_list_to_dict(
    target: RosterInfo,
    results: Sequence[OpponentResult],
    *,
    games_per_opponent: int,
    bot: str,
    seed: int,
    map_name: str,
) -> dict[str, Any]:
    """Project score results to the stable finite ``szop.score_list/v1`` schema.

    Empty overall or cost-comparison groups have zero counts, zero rounds, and
    all rates equal to ``0.0``; no textual interpretation is included.
    """
    ordered = sorted(results, key=lambda result: result.opponent.id)
    aggregate = aggregate_score(ordered)
    cheaper = [result for result in ordered if result.opponent.points < target.points]
    pricier = [result for result in ordered if result.opponent.points > target.points]
    payload = {
        "schema": SCORE_LIST_SCHEMA,
        "version": SCORE_LIST_VERSION,
        "target": _roster_info_to_dict(target),
        "parameters": {
            "games_per_opponent": games_per_opponent,
            "bot": bot.lower(),
            "seed": seed,
            "map_name": map_name.lower(),
            "opponent_roster_ids": [result.opponent.id for result in ordered],
        },
        "results": [
            {
                "opponent": _roster_info_to_dict(result.opponent),
                "n": result.summary.n_games,
                "wins": result.summary.wins_p0,
                "losses": result.summary.wins_p1,
                "draws": result.summary.draws,
                "rounds": result.summary.total_rounds,
                "win_rate": float(result.summary.win_rate_p0),
                "loss_rate": float(result.summary.win_rate_p1),
                "draw_rate": float(result.summary.draw_rate),
                "avg_rounds": float(result.summary.avg_rounds),
            }
            for result in ordered
        ],
        "aggregate": _summary_to_dict(aggregate),
        "cost_signals": {
            "vs_cheaper": _summary_to_dict(aggregate_score(cheaper)),
            "vs_pricier": _summary_to_dict(aggregate_score(pricier)),
        },
    }
    for value in _numeric_values(payload):
        if type(value) is float and not math.isfinite(value):
            raise ScoreSerializationError("score payload contains a non-finite value")
    return payload


def _numeric_values(value: Any):
    if type(value) in {int, float}:
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numeric_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numeric_values(item)


__all__ = [
    "MAX_ROSTER_COMPOSITION_LENGTH",
    "MAX_DATABASE_ID",
    "MAX_SCORE_GAMES_PER_OPPONENT",
    "MAX_SCORE_OPPONENTS",
    "MAX_SCORE_TOTAL_GAMES",
    "OpponentResult",
    "RosterInfo",
    "RosterNotFoundError",
    "SCORE_LIST_SCHEMA",
    "SCORE_LIST_VERSION",
    "ScoreRequestError",
    "ScoreSerializationError",
    "ScoreSummary",
    "ScoreWorkloadError",
    "_select_opponents",
    "aggregate_score",
    "list_rosters",
    "roster_info",
    "score_list",
    "score_list_to_dict",
]
