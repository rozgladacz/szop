"""Internal SQLite ledger for single-step bot proposal attempts (ADR-0060)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from sqlite3 import SQLITE_BUSY, SQLITE_LOCKED

from sqlalchemy import Engine, and_, delete, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import models
from ..battle_protocol import ACTIVATION_PROTOCOL_VERSION_V1
from ..db import utcnow
from .agent_proposal_records import BATTLE_ACTION_PROPOSAL, audit_proposal
from .battle_actions import PreparedBattleAction

_MAX_SAFE_INTEGER = 2**53 - 1
_ATTEMPT_ID = re.compile(
    r"([0-9]{13})-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_EPOCH = datetime(1970, 1, 1)
_RETRY_WINDOW = timedelta(hours=24)
_FUTURE_SKEW = timedelta(minutes=2)
_RETENTION = timedelta(days=30)
_BUSY_TIMEOUT_MS = 2_000
_NO_PROPOSAL_REASONS = frozenset({
    "unsupported_protocol",
    "checkpoint_unavailable",
    "unsupported_context",
    "no_candidate",
    "unsupported_action",
    "invalid_action",
})


class BotProposalAttemptError(ValueError):
    """A bounded failure that can be mapped to the ADR's public error codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _safe_integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= _MAX_SAFE_INTEGER


def _issued_at(attempt_id: str) -> datetime:
    match = _ATTEMPT_ID.fullmatch(attempt_id) if isinstance(attempt_id, str) else None
    if match is None:
        raise BotProposalAttemptError("invalid_command")
    return _EPOCH + timedelta(milliseconds=int(match[1]))


@dataclass(frozen=True, slots=True)
class BotProposalCommand:
    battle_id: int
    attempt_id: str
    schema_version: int
    side: int
    kind: str
    seed: int
    protocol: int
    expected_sequence: int

    def __post_init__(self) -> None:
        _issued_at(self.attempt_id)
        if (
            not _safe_integer(self.battle_id, 1)
            or type(self.schema_version) is not int or self.schema_version != 1
            or type(self.side) is not int or self.side not in (0, 1)
            or type(self.kind) is not str or self.kind != "priority"
            or not _safe_integer(self.seed, -_MAX_SAFE_INTEGER)
            or type(self.protocol) is not int or self.protocol != ACTIVATION_PROTOCOL_VERSION_V1
            or not _safe_integer(self.expected_sequence)
        ):
            raise BotProposalAttemptError("invalid_command")

    def canonical_json(self, owner_user_id: int, owner_created_at: datetime) -> str:
        return json.dumps(
            {
                "attempt_id": self.attempt_id,
                "battle_id": self.battle_id,
                "expected_sequence": self.expected_sequence,
                "kind": self.kind,
                "owner_created_at": owner_created_at.isoformat(timespec="microseconds") + "Z",
                "owner_user_id": owner_user_id,
                "protocol": self.protocol,
                "schema_version": self.schema_version,
                "seed": self.seed,
                "side": self.side,
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class BotProposalDecision:
    """Outcome from preparation on the transaction's coherent checkpoint."""

    actual_sequence: int | None
    reason: str | None = None
    prepared: PreparedBattleAction | None = None


@dataclass(frozen=True, slots=True)
class BotProposalAttemptResult:
    attempt_id: str
    battle_id: int
    status: str
    reason: str | None
    proposal_id: int | None
    expected_sequence: int
    actual_sequence: int | None
    created_at: datetime
    expires_at: datetime
    schema_version: int = 1

    @classmethod
    def from_record(cls, record: models.BotProposalAttempt) -> BotProposalAttemptResult:
        return cls(
            attempt_id=record.attempt_id,
            battle_id=record.battle_id,
            status=record.status,
            reason=record.reason,
            proposal_id=record.proposal_id,
            expected_sequence=record.expected_sequence,
            actual_sequence=record.actual_sequence,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )


def _owner_controls_side(owner_user_id, side):
    return or_(
        and_(side == 0, models.Battle.p1_user_id == owner_user_id),
        and_(side == 1, models.Battle.p2_user_id == owner_user_id),
    )


def _current_owner_conditions(owner_created_at):
    return (
        models.User.created_at == owner_created_at,
        models.User.role.in_((models.USER_ROLE_USER, models.USER_ROLE_ADMIN)),
        models.Battle.created_at >= models.User.created_at,
    )


@contextmanager
def _write_session(engine: Engine):
    # Keep the timeout local to this checked-out connection. The Session
    # participates in the enclosing transaction but cannot commit it early.
    with engine.connect() as connection:
        with closing(connection.connection.driver_connection.cursor()) as cursor:
            timeout = int(cursor.execute("PRAGMA busy_timeout").fetchone()[0])
            cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            try:
                with connection.begin():
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    with Session(
                        bind=connection, autoflush=False, join_transaction_mode="rollback_only",
                    ) as db:
                        yield db
                        db.flush()
            except OperationalError as exc:
                sqlite_code = getattr(exc.orig, "sqlite_errorcode", 0) & 0xFF
                if sqlite_code in (SQLITE_BUSY, SQLITE_LOCKED):
                    raise BotProposalAttemptError("attempt_temporarily_unavailable") from exc
                raise
            finally:
                cursor.execute(f"PRAGMA busy_timeout={timeout}")


def _record_decision(
    db: Session,
    attempt: models.BotProposalAttempt,
    decision: BotProposalDecision,
) -> None:
    actual = decision.actual_sequence
    if actual is not None and not _safe_integer(actual):
        raise ValueError("Invalid proposal decision sequence")

    prepared = decision.prepared
    if prepared is not None:
        if (
            decision.reason is not None
            or actual != attempt.expected_sequence
            or prepared.previous_sequence != actual
            or prepared.battle_id != attempt.battle_id
        ):
            raise ValueError("Prepared action does not match the frozen attempt")
        action = prepared.action_wire
        proposal = models.AgentProposal(
            owner_user_id=attempt.owner_user_id,
            agent_user_id=attempt.owner_user_id,
            producer_owner_created_at=attempt.owner_created_at,
            action=BATTLE_ACTION_PROPOSAL,
            summary=f"priority: {action['action_type']}",
            payload_json=json.dumps(
                {
                    "battle_id": attempt.battle_id,
                    "expected_sequence": attempt.expected_sequence,
                    "action": action,
                },
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            ),
        )
        db.add(proposal)
        db.flush()
        audit_proposal(
            db,
            proposal=proposal,
            action="create",
            route="/battles/{battle_id}/bot-proposal-attempts/{attempt_id}",
            details={
                "producer": "server/priority-v1",
                "battle_id": attempt.battle_id,
                "expected_sequence": attempt.expected_sequence,
                "attempt_digest": attempt.command_sha256,
            },
        )
        attempt.status = "proposal_created"
        attempt.proposal_id = proposal.id
    elif decision.reason == "head_changed" and actual is not None and actual != attempt.expected_sequence:
        attempt.status = "stale"
    elif decision.reason in _NO_PROPOSAL_REASONS and actual in (None, attempt.expected_sequence):
        attempt.status = "no_proposal"
    else:
        raise ValueError("Invalid proposal decision")

    attempt.reason = decision.reason
    attempt.actual_sequence = actual


def create_bot_proposal_attempt(
    engine: Engine,
    command: BotProposalCommand,
    *,
    owner_user_id: int,
    owner_created_at: datetime,
    decide: Callable[[Session, models.Battle, BotProposalCommand], BotProposalDecision],
    now: Callable[[], datetime] = utcnow,
) -> tuple[BotProposalAttemptResult, bool]:
    """Return the committed result and whether this call created the attempt.

    The caller supplies authenticated account identity. This service rechecks
    the live account and side in the transaction. Preparation must only read
    game state and return a decision. It gets no authority to execute the action.
    """
    with _write_session(engine) as db:
        stamp = now()
        battle = db.scalar(
            select(models.Battle)
            .join(models.User, models.User.id == owner_user_id)
            .where(
                models.Battle.id == command.battle_id,
                *_current_owner_conditions(owner_created_at),
                _owner_controls_side(owner_user_id, command.side),
            )
        )
        if battle is None:
            raise BotProposalAttemptError("not_found")

        issued_at = _issued_at(command.attempt_id)
        if issued_at > stamp + _FUTURE_SKEW:
            raise BotProposalAttemptError("invalid_command")
        expires_at = issued_at + _RETRY_WINDOW
        if stamp >= expires_at:
            raise BotProposalAttemptError("attempt_expired")

        command_json = command.canonical_json(owner_user_id, owner_created_at)
        digest = sha256(command_json.encode("utf-8")).hexdigest()
        attempt = db.scalar(
            select(models.BotProposalAttempt).where(
                models.BotProposalAttempt.owner_user_id == owner_user_id,
                models.BotProposalAttempt.owner_created_at == owner_created_at,
                models.BotProposalAttempt.attempt_id == command.attempt_id,
            )
        )
        if attempt is not None:
            if attempt.command_sha256 != digest or attempt.command_json != command_json:
                raise BotProposalAttemptError("attempt_payload_conflict")
            return BotProposalAttemptResult.from_record(attempt), False

        attempt = models.BotProposalAttempt(
            owner_user_id=owner_user_id,
            owner_created_at=owner_created_at,
            battle_id=command.battle_id,
            attempt_id=command.attempt_id,
            side=command.side,
            command_json=command_json,
            command_sha256=digest,
            expected_sequence=command.expected_sequence,
            created_at=stamp,
            expires_at=expires_at,
        )
        _record_decision(db, attempt, decide(db, battle, command))
        db.add(attempt)
        return BotProposalAttemptResult.from_record(attempt), True


def get_bot_proposal_attempt(
    engine: Engine,
    *,
    owner_user_id: int,
    owner_created_at: datetime,
    battle_id: int,
    attempt_id: str,
    now: Callable[[], datetime] = utcnow,
) -> BotProposalAttemptResult:
    _issued_at(attempt_id)
    attempt = models.BotProposalAttempt
    with Session(engine, autoflush=False) as db:
        record = db.scalar(
            select(attempt)
            .join(models.Battle, models.Battle.id == attempt.battle_id)
            .join(models.User, models.User.id == attempt.owner_user_id)
            .where(
                attempt.owner_user_id == owner_user_id,
                attempt.owner_created_at == owner_created_at,
                attempt.battle_id == battle_id,
                attempt.attempt_id == attempt_id,
                attempt.created_at > now() - _RETENTION,
                *_current_owner_conditions(owner_created_at),
                _owner_controls_side(owner_user_id, attempt.side),
            )
        )
        if record is None:
            raise BotProposalAttemptError("not_found")
        return BotProposalAttemptResult.from_record(record)


def purge_bot_proposal_attempts(
    engine: Engine, *, batch_size: int, now: Callable[[], datetime] = utcnow,
) -> int:
    """Remove one batch of expired ledger rows while retaining proposals."""
    if type(batch_size) is not int or not 1 <= batch_size <= 1_000:
        raise ValueError("Invalid bot proposal attempts purge batch size")
    attempt = models.BotProposalAttempt
    with _write_session(engine) as db:
        expired = (
            select(attempt.id)
            .where(attempt.created_at <= now() - _RETENTION)
            .order_by(attempt.created_at, attempt.id)
            .limit(batch_size)
        )
        return db.execute(delete(attempt).where(attempt.id.in_(expired))).rowcount
