"""Optional, in-process observation records for the headless runner."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Literal

from app.services.engine.actions import Action, SpecialAction
from app.services.engine.events import BattleEvent, EffectApplied, InterruptTriggered
from app.services.engine.state import BattleState


@dataclass(frozen=True, slots=True)
class ActionDecision:
    """One policy call, with only the events produced by its applied action."""

    kind: Literal["choose_action", "continue_activation"]
    seen_state: BattleState
    unit_id: int | None
    prior_actions: tuple[Action, ...]
    action: Action | None
    outcome: Literal["applied", "rejected", "none", "error"]
    reason: str | None = None
    before: BattleState | None = None
    after: BattleState | None = None
    events: tuple[BattleEvent, ...] = ()

    @property
    def perspective(self) -> int:
        return self.seen_state.active_player


@dataclass(frozen=True, slots=True)
class AutomaticTransition:
    """A runner or engine step with no policy call of its own."""

    kind: Literal[
        "deployment_moved", "deployment_finished", "activation_started",
        "activation_stopped", "activation_finished", "initiative_passed", "round_ended",
    ]
    before: BattleState
    after: BattleState
    events: tuple[BattleEvent, ...] = ()
    unit_id: int | None = None
    reason: str | None = None


BattleObserver = Callable[[ActionDecision | AutomaticTransition], None]
TransitionObserver = Callable[[AutomaticTransition], None]


def snapshot_action(action: Action) -> Action:
    """SpecialAction is frozen but its payload is mutable."""
    return deepcopy(action) if isinstance(action, SpecialAction) else action


def snapshot_events(events: tuple[BattleEvent, ...]) -> tuple[BattleEvent, ...]:
    return tuple(
        deepcopy(event) if isinstance(event, (EffectApplied, InterruptTriggered)) else event
        for event in events
    )
