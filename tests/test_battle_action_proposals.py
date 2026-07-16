from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.db import Base
from app.main import app
from app.routers import agent_proposals, battles
from app.security import AgentPrincipal, hash_agent_token
from app.services.engine.action_codec import action_to_json
from app.services.engine.actions import DefendAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.persistence import load_latest_checkpoint, save_checkpoint
from app.services.engine.phases import deployment_round, setup_phase


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_user(
    session: Session,
    username: str,
    *,
    role: str = models.USER_ROLE_USER,
) -> models.User:
    user = models.User(username=username, password_hash="x", role=role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_principal(
    session: Session,
    *,
    owner: models.User,
) -> AgentPrincipal:
    agent = _seed_user(
        session,
        f"agent-{owner.id}",
        role=models.USER_ROLE_AGENT,
    )
    token = models.AgentToken(
        agent_user=agent,
        owner_user=owner,
        token_hash=hash_agent_token(f"battle-proposal-{owner.id}"),
        scope_json=json.dumps(
            {
                agent_proposals.BATTLE_READ_SCOPE: True,
                agent_proposals.CREATE_PROPOSAL_SCOPE: True,
            }
        ),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    return AgentPrincipal(
        agent_user_id=agent.id,
        owner_user_id=owner.id,
        token_id=token.id,
        scopes=frozenset(
            {
                agent_proposals.BATTLE_READ_SCOPE,
                agent_proposals.CREATE_PROPOSAL_SCOPE,
            }
        ),
    )


def _action_state():
    state = setup_phase(
        [
            {
                "owner_player": 0,
                "units": [
                    {
                        "id": 1,
                        "position": (0, 0),
                        "models": 3,
                        "toughness": 10,
                    }
                ],
            },
            {
                "owner_player": 1,
                "units": [
                    {
                        "id": 2,
                        "position": (12, 0),
                        "models": 3,
                        "toughness": 10,
                    }
                ],
            },
        ],
        initiative_player=0,
    )
    state, _ = deployment_round(state, ())
    return state


def _persist_battle(
    session: Session,
    *,
    p1: models.User,
    p2: models.User,
) -> models.Battle:
    state = _action_state()
    battle = models.Battle(
        p1_user_id=p1.id,
        p2_user_id=p2.id,
        current_round=state.round,
        rng_seed=2026,
        status="active",
    )
    session.add(battle)
    session.flush()
    save_checkpoint(
        session,
        battle.id,
        0,
        state,
        DeterministicDice(2026),
    )
    session.commit()
    session.refresh(battle)
    return battle


def _battle_snapshot(session: Session, battle_id: int) -> tuple:
    session.expire_all()
    battle = session.get(models.Battle, battle_id)
    event_count = session.execute(
        select(func.count())
        .select_from(models.BattleEvent)
        .where(models.BattleEvent.battle_id == battle_id)
    ).scalar_one()
    checkpoint_count = session.execute(
        select(func.count())
        .select_from(models.BattleCheckpoint)
        .where(models.BattleCheckpoint.battle_id == battle_id)
    ).scalar_one()
    checkpoint = load_latest_checkpoint(session, battle_id)
    return (
        int(event_count),
        int(checkpoint_count),
        battle.current_round,
        battle.status,
        battle.winner_user_id,
        checkpoint.sequence_at if checkpoint is not None else None,
        checkpoint.state if checkpoint is not None else None,
        checkpoint.dice.to_checkpoint() if checkpoint is not None else None,
    )


def _create_proposal(
    session: Session,
    *,
    battle: models.Battle,
    principal: AgentPrincipal,
    unit_id: int = 1,
) -> agent_proposals.AgentProposalPublic:
    return agent_proposals.create_battle_action_proposal(
        agent_proposals.BattleActionProposalCreate(
            battle_id=battle.id,
            expected_sequence=0,
            action=action_to_json(DefendAction(unit_id=unit_id)),
            summary=f"Oddział {unit_id}: przyjmij postawę obronną",
        ),
        db=session,
        principal=principal,
    )


def test_battle_action_proposal_route_is_registered() -> None:
    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/agent_proposals/battle-actions" in route_paths


def test_create_battle_action_proposal_freezes_validated_wire_without_rng_drift() -> None:
    session = _build_session()
    owner = _seed_user(session, "proposal-owner")
    principal = _seed_principal(session, owner=owner)
    battle = _persist_battle(session, p1=owner, p2=owner)
    before = _battle_snapshot(session, battle.id)

    created = _create_proposal(
        session,
        battle=battle,
        principal=principal,
    )

    assert created.action == agent_proposals.BATTLE_ACTION_PROPOSAL
    assert created.status == models.AGENT_PROPOSAL_STATUS_PENDING
    assert created.summary == "Oddział 1: przyjmij postawę obronną"
    assert created.payload == {
        "battle_id": battle.id,
        "expected_sequence": 0,
        "action": action_to_json(DefendAction(unit_id=1)),
    }
    assert created.result is None
    assert _battle_snapshot(session, battle.id) == before

    audits = session.execute(
        select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
    ).scalars().all()
    assert len(audits) == 1
    audit = audits[0]
    audit_payload = json.loads(audit.params_json)
    assert audit.user_id == owner.id
    assert audit.agent_user_id == principal.agent_user_id
    assert audit.route == "/agent_proposals/battle-actions"
    assert audit_payload["token_id"] == principal.token_id
    assert audit_payload["proposal_id"] == created.id
    assert audit_payload["battle_id"] == battle.id
    assert audit_payload["expected_sequence"] == 0
    assert "szop.action" not in audit.params_json


def test_create_battle_action_proposal_rejects_illegal_side_and_no_oracle() -> None:
    session = _build_session()
    owner = _seed_user(session, "proposal-p1")
    opponent = _seed_user(session, "proposal-p2")
    stranger = _seed_user(session, "proposal-stranger")
    owner_principal = _seed_principal(session, owner=owner)
    stranger_principal = _seed_principal(session, owner=stranger)
    battle = _persist_battle(session, p1=owner, p2=opponent)
    before = _battle_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as side_info:
        _create_proposal(
            session,
            battle=battle,
            principal=owner_principal,
            unit_id=2,
        )
    assert side_info.value.status_code == 403

    for battle_id in (battle.id, battle.id + 999):
        with pytest.raises(HTTPException) as oracle_info:
            agent_proposals.create_battle_action_proposal(
                agent_proposals.BattleActionProposalCreate(
                    battle_id=battle_id,
                    expected_sequence=0,
                    action=action_to_json(DefendAction(unit_id=1)),
                    summary="Spróbuj wykonać cudzą akcję",
                ),
                db=session,
                principal=stranger_principal,
            )
        assert oracle_info.value.status_code == 404

    assert _battle_snapshot(session, battle.id) == before
    assert session.execute(select(models.AgentProposal)).scalars().all() == []


def test_approve_executes_once_and_persists_result_and_full_audit() -> None:
    session = _build_session()
    owner = _seed_user(session, "execute-owner")
    principal = _seed_principal(session, owner=owner)
    battle = _persist_battle(session, p1=owner, p2=owner)
    created = _create_proposal(session, battle=battle, principal=principal)
    frozen_payload = created.payload
    before = _battle_snapshot(session, battle.id)

    executed = agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )
    after_first = _battle_snapshot(session, battle.id)
    executed_again = agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )
    after_second = _battle_snapshot(session, battle.id)

    assert executed.status == models.AGENT_PROPOSAL_STATUS_EXECUTED
    assert executed.decided_by_user_id == owner.id
    assert executed.payload == frozen_payload
    assert executed.result == {
        "battle_id": battle.id,
        "previous_sequence": 0,
        "new_sequence": executed.result["new_sequence"],
        "event_count": executed.result["event_count"],
    }
    assert executed.result["new_sequence"] > 0
    assert executed.result["event_count"] == after_first[0] - before[0]
    assert after_first[1] == before[1] + 1
    assert executed_again.result == executed.result
    assert executed_again.decided_at == executed.decided_at
    assert after_second == after_first

    audit_rows = session.execute(
        select(models.AgentAuditLog).order_by(models.AgentAuditLog.id)
    ).scalars().all()
    assert [json.loads(row.params_json)["action"] for row in audit_rows] == [
        "create",
        "execute",
    ]
    execute_audit = json.loads(audit_rows[-1].params_json)
    assert execute_audit["token_id"] == principal.token_id
    assert execute_audit["decided_by_user_id"] == owner.id
    assert execute_audit["battle_id"] == battle.id
    assert execute_audit["expected_sequence"] == 0
    assert execute_audit["previous_sequence"] == 0
    assert execute_audit["new_sequence"] == executed.result["new_sequence"]


def test_approve_marks_stale_without_second_battle_mutation() -> None:
    session = _build_session()
    owner = _seed_user(session, "stale-proposal-owner")
    principal = _seed_principal(session, owner=owner)
    battle = _persist_battle(session, p1=owner, p2=owner)
    created = _create_proposal(session, battle=battle, principal=principal)
    direct = battles.take_battle_action(
        battle.id,
        battles.BattleActionCreate(
            expected_sequence=0,
            action=action_to_json(DefendAction(unit_id=1)),
        ),
        db=session,
        actor=battles.BattleActor(user_id=owner.id),
    )
    before_approve = _battle_snapshot(session, battle.id)

    stale = agent_proposals.approve_agent_proposal(
        created.id,
        db=session,
        current_user=owner,
    )

    assert stale.status == models.AGENT_PROPOSAL_STATUS_STALE
    assert stale.result == {
        "battle_id": battle.id,
        "expected_sequence": 0,
        "actual_sequence": direct.new_sequence,
    }
    assert _battle_snapshot(session, battle.id) == before_approve


def test_reject_and_execution_permission_rechecks_do_not_mutate_battle() -> None:
    session = _build_session()
    owner = _seed_user(session, "decision-owner")
    other = _seed_user(session, "decision-other")
    principal = _seed_principal(session, owner=owner)
    battle = _persist_battle(session, p1=owner, p2=owner)
    rejected_created = _create_proposal(session, battle=battle, principal=principal)
    before_reject = _battle_snapshot(session, battle.id)

    rejected = agent_proposals.reject_agent_proposal(
        rejected_created.id,
        db=session,
        current_user=owner,
    )
    assert rejected.status == models.AGENT_PROPOSAL_STATUS_REJECTED
    assert _battle_snapshot(session, battle.id) == before_reject

    side_created = _create_proposal(session, battle=battle, principal=principal)
    battle.p1_user_id = other.id
    battle.p2_user_id = owner.id
    session.commit()
    before_side_check = _battle_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as side_info:
        agent_proposals.approve_agent_proposal(
            side_created.id,
            db=session,
            current_user=owner,
        )
    assert side_info.value.status_code == 403
    assert _battle_snapshot(session, battle.id) == before_side_check
    assert session.get(models.AgentProposal, side_created.id).status == (
        models.AGENT_PROPOSAL_STATUS_PENDING
    )

    battle.p1_user_id = owner.id
    battle.p2_user_id = owner.id
    session.commit()
    participant_created = _create_proposal(
        session,
        battle=battle,
        principal=principal,
    )
    battle.p1_user_id = other.id
    battle.p2_user_id = other.id
    session.commit()
    before_participant_check = _battle_snapshot(session, battle.id)

    with pytest.raises(HTTPException) as participant_info:
        agent_proposals.approve_agent_proposal(
            participant_created.id,
            db=session,
            current_user=owner,
        )
    assert participant_info.value.status_code == 404
    assert _battle_snapshot(session, battle.id) == before_participant_check
    assert session.get(models.AgentProposal, participant_created.id).status == (
        models.AGENT_PROPOSAL_STATUS_PENDING
    )


def test_concurrent_approvals_write_one_action_and_one_execution_audit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'proposal-concurrency.db'}",
        future=True,
        connect_args={"timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    with SessionLocal() as setup:
        owner = _seed_user(setup, "concurrent-owner")
        principal = _seed_principal(setup, owner=owner)
        battle = _persist_battle(setup, p1=owner, p2=owner)
        created = _create_proposal(setup, battle=battle, principal=principal)
        owner_id = owner.id
        battle_id = battle.id
        proposal_id = created.id

    barrier = threading.Barrier(2)
    original_claim = agent_proposals._claim_battle_action_proposal

    def synchronized_claim(*args, **kwargs):
        barrier.wait(timeout=10)
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(
        agent_proposals,
        "_claim_battle_action_proposal",
        synchronized_claim,
    )
    results: list[agent_proposals.AgentProposalPublic] = []
    errors: list[BaseException] = []

    def approve() -> None:
        try:
            with SessionLocal() as session:
                current_user = session.get(models.User, owner_id)
                results.append(
                    agent_proposals.approve_agent_proposal(
                        proposal_id,
                        db=session,
                        current_user=current_user,
                    )
                )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert {result.status for result in results} == {
        models.AGENT_PROPOSAL_STATUS_EXECUTED
    }
    assert results[0].result == results[1].result

    with SessionLocal() as verify:
        event_count = verify.execute(
            select(func.count())
            .select_from(models.BattleEvent)
            .where(models.BattleEvent.battle_id == battle_id)
        ).scalar_one()
        checkpoint_count = verify.execute(
            select(func.count())
            .select_from(models.BattleCheckpoint)
            .where(models.BattleCheckpoint.battle_id == battle_id)
        ).scalar_one()
        execute_audit_count = sum(
            json.loads(row.params_json)["action"] == "execute"
            for row in verify.execute(select(models.AgentAuditLog)).scalars()
        )
        assert event_count == results[0].result["event_count"]
        assert checkpoint_count == 2
        assert execute_audit_count == 1
