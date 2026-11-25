"""Shared persistence for the agent proposal audit."""

import json
from typing import Any

from sqlalchemy.orm import Session

from .. import models

BATTLE_ACTION_PROPOSAL = "battle:action"


def audit_proposal(
    db: Session,
    *,
    proposal: models.AgentProposal,
    action: str,
    route: str = "/agent_proposals",
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "action": action,
        "proposal_id": proposal.id,
        "proposal_action": proposal.action,
        "token_id": proposal.token_id,
    }
    if details:
        payload.update(details)
    db.add(models.AgentAuditLog(
        user_id=proposal.owner_user_id,
        agent_user_id=proposal.agent_user_id,
        route=route,
        params_json=json.dumps(payload, sort_keys=True),
    ))
