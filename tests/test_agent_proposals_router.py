from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.main import app
from app.routers import agent_proposals
from app.security import AgentPrincipal, hash_agent_token, hash_password


RAW_TOKEN = "proposal-agent-secret"


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_user(
    session: Session,
    *,
    username: str,
    role: str = models.USER_ROLE_USER,
) -> models.User:
    user = models.User(
        username=username,
        password_hash=hash_password("haslo"),
        role=role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_agent_principal(
    session: Session,
    *,
    owner: models.User | None = None,
) -> tuple[models.User, models.User, models.AgentToken, AgentPrincipal]:
    owner_user = owner or _seed_user(session, username="owner")
    agent_user = _seed_user(
        session,
        username=f"agent-{owner_user.id}",
        role=models.USER_ROLE_AGENT,
    )
    token = models.AgentToken(
        agent_user=agent_user,
        owner_user=owner_user,
        token_hash=hash_agent_token(f"{RAW_TOKEN}-{owner_user.id}"),
        scope_json=json.dumps({agent_proposals.CREATE_PROPOSAL_SCOPE: True}),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    principal = AgentPrincipal(
        agent_user_id=agent_user.id,
        owner_user_id=owner_user.id,
        token_id=token.id,
        scopes=frozenset({agent_proposals.CREATE_PROPOSAL_SCOPE}),
    )
    return owner_user, agent_user, token, principal


def _create_payload(
    *,
    summary: str = "Zaktualizuj rozpiskę po walidacji",
    payload: dict[str, object] | None = None,
) -> agent_proposals.AgentProposalCreate:
    return agent_proposals.AgentProposalCreate(
        action="roster:update",
        summary=summary,
        payload=payload if payload is not None else {"roster_id": 7, "changes": []},
    )


def _count_rows(session: Session, model: type[object]) -> int:
    count = session.execute(select(func.count()).select_from(model)).scalar_one()
    return int(count or 0)


def _audit_actions(session: Session) -> list[str]:
    return [
        json.loads(log.params_json)["action"]
        for log in session.execute(
            select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
        ).scalars()
    ]


def test_agent_proposals_router_is_registered_in_app() -> None:
    route_paths = {getattr(route, "path", "") for route in app.routes}
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods_by_path.setdefault(path, set()).update(getattr(route, "methods", set()))

    assert "/agent_proposals" in route_paths
    assert "GET" in methods_by_path["/agent_proposals"]
    assert "POST" in methods_by_path["/agent_proposals"]
    assert "GET" in methods_by_path["/agent_proposals/{proposal_id}"]
    assert "/agent_proposals/{proposal_id}/approve" in route_paths
    assert "/agent_proposals/{proposal_id}/reject" in route_paths


def test_create_agent_proposal_persists_pending_owner_scoped_request() -> None:
    session = _build_session()
    owner, agent, token, principal = _seed_agent_principal(session)
    payload = _create_payload(
        summary="  Zatwierdź zmianę rozpiski  ",
        payload={"roster_id": 7, "token": "not-copied-to-audit"},
    )

    response = agent_proposals.create_agent_proposal(
        payload,
        db=session,
        principal=principal,
    )

    assert response.owner_user_id == owner.id
    assert response.agent_user_id == agent.id
    assert response.token_id == token.id
    assert response.action == "roster:update"
    assert response.summary == "Zatwierdź zmianę rozpiski"
    assert response.payload == {"roster_id": 7, "token": "not-copied-to-audit"}
    assert response.status == models.AGENT_PROPOSAL_STATUS_PENDING
    assert response.decided_at is None
    assert response.decided_by_user_id is None

    stored = session.get(models.AgentProposal, response.id)
    assert stored is not None
    assert stored.owner_user_id == owner.id
    assert stored.agent_user_id == agent.id
    assert stored.token_id == token.id
    assert json.loads(stored.payload_json) == response.payload

    audit = session.execute(select(models.AgentAuditLog)).scalar_one()
    assert audit.user_id == owner.id
    assert audit.agent_user_id == agent.id
    assert audit.route == "/agent_proposals"
    audit_payload = json.loads(audit.params_json)
    assert audit_payload["action"] == "create"
    assert audit_payload["proposal_id"] == response.id
    assert audit_payload["proposal_action"] == "roster:update"
    assert "not-copied-to-audit" not in audit.params_json


@pytest.mark.parametrize(
    "payload",
    [
        _create_payload(summary="  "),
        _create_payload(payload={"blob": "x" * 20_001}),
        _create_payload(payload={"value": float("nan")}),
    ],
)
def test_create_agent_proposal_rejects_invalid_payload_without_side_effects(
    payload: agent_proposals.AgentProposalCreate,
) -> None:
    session = _build_session()
    _, _, _, principal = _seed_agent_principal(session)

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.create_agent_proposal(payload, db=session, principal=principal)

    assert exc_info.value.status_code == 400
    assert _count_rows(session, models.AgentProposal) == 0
    assert _count_rows(session, models.AgentAuditLog) == 0


def test_generic_create_rejects_reserved_battle_action_type() -> None:
    session = _build_session()
    _, _, _, principal = _seed_agent_principal(session)

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.create_agent_proposal(
            agent_proposals.AgentProposalCreate(
                action=agent_proposals.BATTLE_ACTION_PROPOSAL,
                summary="Obejście dedykowanego endpointu",
                payload={
                    "battle_id": 7,
                    "expected_sequence": 0,
                    "action": {"schema": "szop.action"},
                },
            ),
            db=session,
            principal=principal,
        )

    assert exc_info.value.status_code == 400
    assert _count_rows(session, models.AgentProposal) == 0
    assert _count_rows(session, models.AgentAuditLog) == 0


def test_list_agent_proposals_is_owner_scoped_and_newest_first() -> None:
    session = _build_session()
    owner, _, _, principal = _seed_agent_principal(session)
    other_owner = _seed_user(session, username="other")
    _, _, _, other_principal = _seed_agent_principal(session, owner=other_owner)
    first = agent_proposals.create_agent_proposal(
        _create_payload(summary="Pierwsza propozycja"),
        db=session,
        principal=principal,
    )
    second = agent_proposals.create_agent_proposal(
        _create_payload(
            summary="Druga propozycja",
            payload={"roster_id": 8, "changes": [{"field": "name"}]},
        ),
        db=session,
        principal=principal,
    )
    agent_proposals.create_agent_proposal(
        _create_payload(summary="Cudza propozycja"),
        db=session,
        principal=other_principal,
    )
    approved = agent_proposals.approve_agent_proposal(
        first.id,
        db=session,
        current_user=owner,
    )

    listed = agent_proposals.list_agent_proposals(db=session, current_user=owner)

    assert [proposal.id for proposal in listed] == [second.id, first.id]
    assert [proposal.summary for proposal in listed] == [
        "Druga propozycja",
        "Pierwsza propozycja",
    ]
    assert listed[0].status == models.AGENT_PROPOSAL_STATUS_PENDING
    assert listed[0].payload == {"roster_id": 8, "changes": [{"field": "name"}]}
    assert listed[1].status == models.AGENT_PROPOSAL_STATUS_APPROVED
    assert listed[1].decided_at == approved.decided_at


def test_get_agent_proposal_is_owner_scoped() -> None:
    session = _build_session()
    owner, agent, token, principal = _seed_agent_principal(session)
    other_owner = _seed_user(session, username="other")
    created = agent_proposals.create_agent_proposal(
        _create_payload(payload={"roster_id": 9, "changes": []}),
        db=session,
        principal=principal,
    )

    fetched = agent_proposals.get_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert fetched.id == created.id
    assert fetched.owner_user_id == owner.id
    assert fetched.agent_user_id == agent.id
    assert fetched.token_id == token.id
    assert fetched.status == models.AGENT_PROPOSAL_STATUS_PENDING
    assert fetched.payload == {"roster_id": 9, "changes": []}

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.get_agent_proposal(
            created.id,
            db=session,
            current_user=other_owner,
        )
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as missing_info:
        agent_proposals.get_agent_proposal(
            created.id + 999,
            db=session,
            current_user=owner,
        )
    assert missing_info.value.status_code == 404
    # czysty odczyt nie audytuje ani nie zmienia statusu
    assert _audit_actions(session) == ["create"]


def test_approve_agent_proposal_is_owner_only_and_idempotent() -> None:
    session = _build_session()
    owner, _, _, principal = _seed_agent_principal(session)
    other_owner = _seed_user(session, username="other")
    created = agent_proposals.create_agent_proposal(
        _create_payload(),
        db=session,
        principal=principal,
    )

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.approve_agent_proposal(
            created.id,
            db=session,
            current_user=other_owner,
        )
    assert exc_info.value.status_code == 404
    assert session.get(models.AgentProposal, created.id).status == (
        models.AGENT_PROPOSAL_STATUS_PENDING
    )

    approved = agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert approved.status == models.AGENT_PROPOSAL_STATUS_APPROVED
    assert approved.decided_at is not None
    assert approved.decided_by_user_id == owner.id

    approved_again = agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert approved_again.decided_at == approved.decided_at
    assert _audit_actions(session) == ["create", "approve"]


def test_approve_agent_proposal_rejects_non_pending_status() -> None:
    session = _build_session()
    owner, _, _, principal = _seed_agent_principal(session)
    created = agent_proposals.create_agent_proposal(
        _create_payload(),
        db=session,
        principal=principal,
    )
    proposal = session.get(models.AgentProposal, created.id)
    assert proposal is not None
    proposal.status = models.AGENT_PROPOSAL_STATUS_REJECTED
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.approve_agent_proposal(
            created.id,
            db=session,
            current_user=owner,
        )

    assert exc_info.value.status_code == 409
    assert _audit_actions(session) == ["create"]


def test_reject_agent_proposal_is_owner_only_and_idempotent() -> None:
    session = _build_session()
    owner, _, _, principal = _seed_agent_principal(session)
    other_owner = _seed_user(session, username="other")
    created = agent_proposals.create_agent_proposal(
        _create_payload(),
        db=session,
        principal=principal,
    )

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.reject_agent_proposal(
            created.id,
            db=session,
            current_user=other_owner,
        )
    assert exc_info.value.status_code == 404
    assert session.get(models.AgentProposal, created.id).status == (
        models.AGENT_PROPOSAL_STATUS_PENDING
    )

    rejected = agent_proposals.reject_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert rejected.status == models.AGENT_PROPOSAL_STATUS_REJECTED
    assert rejected.decided_at is not None
    assert rejected.decided_by_user_id == owner.id

    rejected_again = agent_proposals.reject_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert rejected_again.decided_at == rejected.decided_at
    assert _audit_actions(session) == ["create", "reject"]


def test_reject_agent_proposal_rejects_approved_status() -> None:
    session = _build_session()
    owner, _, _, principal = _seed_agent_principal(session)
    created = agent_proposals.create_agent_proposal(
        _create_payload(),
        db=session,
        principal=principal,
    )
    agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    with pytest.raises(HTTPException) as exc_info:
        agent_proposals.reject_agent_proposal(
            created.id,
            db=session,
            current_user=owner,
        )

    assert exc_info.value.status_code == 409
    assert _audit_actions(session) == ["create", "approve"]
