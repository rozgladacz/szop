"""Prepare one priority/v1 proposal inside the durable attempt transaction."""

from dataclasses import replace

from sqlalchemy.orm import Session

from .. import models
from .agents.factory import make_player
from .agents.proposal_capabilities import unsupported_proposal_action, unsupported_proposal_context
from .battle_actions import (
    BattleActionForbidden,
    BattleActionInvalid,
    BattleActionProposalProtocolConflict,
    BattleActionUnavailable,
    load_battle_action_checkpoint,
    prepare_battle_action_from_checkpoint,
)
from .bot_proposal_attempts import BotProposalCommand, BotProposalDecision
from .engine.action_codec import action_to_json
from .engine.dice import DeterministicDice


def prepare_bot_proposal(
    db: Session, battle: models.Battle, command: BotProposalCommand,
) -> BotProposalDecision:
    try:
        checkpoint = load_battle_action_checkpoint(db, battle=battle, require_v1_protocol=True)
    except BattleActionProposalProtocolConflict:
        return BotProposalDecision(None, "unsupported_protocol")
    except BattleActionUnavailable:
        return BotProposalDecision(None, "checkpoint_unavailable")

    head = checkpoint.sequence_at
    if head != command.expected_sequence:
        return BotProposalDecision(head, "head_changed")

    state = checkpoint.state
    if state.round != battle.current_round or unsupported_proposal_context(
        state, command.side, status=battle.status,
    ):
        return BotProposalDecision(head, "unsupported_context")

    action = make_player(command.kind, command.seed).choose_action(state, command.side)
    if action is None:
        return BotProposalDecision(head, "no_candidate")
    # The shared action preparation validates the route in this transaction.
    if unsupported_proposal_action(state, command.side, action, check_route=False):
        return BotProposalDecision(head, "unsupported_action")

    actor_user_id = (battle.p1_user_id, battle.p2_user_id)[command.side]
    isolated = replace(
        checkpoint, dice=DeterministicDice.from_checkpoint(checkpoint.dice.to_checkpoint()),
    )
    try:
        prepared = prepare_battle_action_from_checkpoint(
            isolated, battle=battle, actor_user_id=actor_user_id,
            expected_sequence=command.expected_sequence, action_payload=action_to_json(action),
        )
    except (BattleActionForbidden, BattleActionInvalid, TypeError, ValueError):
        return BotProposalDecision(head, "invalid_action")
    return BotProposalDecision(head, prepared=prepared)
