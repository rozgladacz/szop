"""D — ClaudeV2Player: depth-2 z modelowaniem przeciwnika (świadomie droższy).

Diagnoza (benchmark 2026-06-17): zarówno depth-1 value-max (`ClaudeV1Player`) jak i
istniejący depth-2 `MinimaxPlayer` przegrywają z `priority`/`priority3` (~4–8%), bo
**wąskim gardłem jest ocena liścia** (rodzina value-max), nie głębokość. `MinimaxPlayer`
dodatkowo kosztuje ~185× `priority` (enumeruje KAŻDĄ odpowiedź wroga nad słabą oceną).

ClaudeV2 próbuje zamknąć lukę inaczej, świadomie wyższym kosztem niż depth-1:
1. **Modelowanie przeciwnika (nie enumeracja).** Odpowiedź wroga = JEDNA realistyczna
   akcja silnej taniej polityki (`PriorityV3Player.choose_action`), nie maximin po
   wszystkich akcjach nad `evaluate_state`. Tańsze (1 decyzja zamiast ~A_opp) i wierniejsze
   (modeluje przeciwnika, którego faktycznie spotka). Lookahead „widzi" riposte, np. że
   zajęty cel zostanie ostrzelany.
2. **Próbkowanie combatu (expectimax-lite).** `samples` rzutów `DeterministicDice(seed+k)`
   → uśredniona ocena (redukcja wariancji vs pojedynczy deterministyczny rollout minimaxu).
3. **Ocena świadoma zdolności (slugi dozwolone).** HP + cele z gradientem (jak v1) +
   człon statusów (wrogi Przyszpilony/Wyczerpany = mniejsze zagrożenie; własne = kara).

Złożoność: depth-2, ale rząd taniej niż `minimax` (brak enumeracji wroga). Pomiar
kosztu względem `priority` w `docs/roadmap.md` (D4).
"""

from __future__ import annotations

import math
from statistics import fmean

from app.services.agents.base import (
    Player,
    legal_actions,
    legal_followup_actions,
)
from app.services.agents.claude_v1_player import _objective_value
from app.services.agents.deployment import GridDeploymentMixin
from app.services.agents.policy_eval import _hp_balance
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.engine.actions import Action
from app.services.engine.dice import DeterministicDice
from app.services.engine.resolver import IllegalActionError, apply
from app.services.engine.state import BattleState
from app.services.engine.status import STATUS_PRZYSZPILONY, STATUS_WYCZERPANY

#: Wartość statusu osłabiającego (wrogi → +; własny → −). Mały człon taktyczny.
STATUS_VALUE: float = 4.0
#: Statusy osłabiające oddział (slugi dozwolone — user 2026-06-17).
_DEBUFFS = (STATUS_PRZYSZPILONY, STATUS_WYCZERPANY)


def _status_term(state: BattleState, perspective: int) -> float:
    """Człon statusów: wrogie debuffy (Przyszpilony/Wyczerpany) dobre, własne złe.

    Reużywa enuma `StatusFlag` (slugi statusów). Przyszpilony nie kontroluje celu
    (pkt 22.b.ii) — częściowo widać już w kontroli; tu dodatkowo wycena „zmniejszego
    zagrożenia" oddziału osłabionego.
    """
    total = 0.0
    for b in state.blobs:
        if b.models_alive <= 0:
            continue
        debuffs = sum(1 for s in _DEBUFFS if s in b.status_flags)
        if not debuffs:
            continue
        total += (STATUS_VALUE if b.owner_player != perspective else -STATUS_VALUE) * debuffs
    return total


class ClaudeV2Player(GridDeploymentMixin, Player):
    """Depth-2 z modelowaniem przeciwnika (`priority3`) + expectimax-lite + ocena ability-aware."""

    def __init__(self, seed: int = 0, samples: int = 2) -> None:
        self._seed = int(seed)
        self._samples = max(int(samples), 1)
        #: Model przeciwnika — silna tania polityka (jedna realistyczna riposta).
        self._opponent = PriorityV3Player()

    # -- ocena liścia (ability-aware) -------------------------------------

    def _evaluate(self, state: BattleState, perspective: int) -> float:
        return (
            _hp_balance(state, perspective)
            + _objective_value(state, perspective)
            + _status_term(state, perspective)
        )

    # -- rollout depth-2 z modelem przeciwnika ----------------------------

    def _value(self, state: BattleState, action: Action, perspective: int) -> float:
        """Wartość akcji: uśredniona po `samples` rzutach (aplikuj → riposta wroga → ocena).

        Riposta wroga = `priority3.choose_action` (jedna realistyczna akcja), nie
        maximin. Akcja nielegalna w rollout → `-inf`. Gdy gra skończona lub wróg nie
        ma akcji (inicjatywa nie przeszła) → ocena bez riposty.
        """
        opponent = 1 - perspective
        values: list[float] = []
        for k in range(self._samples):
            try:
                applied = apply(state, action, DeterministicDice(self._seed + k)).state
            except IllegalActionError:
                return -math.inf
            if not applied.is_game_over:
                reply = self._opponent.choose_action(applied, opponent)
                if reply is not None:
                    try:
                        applied = apply(applied, reply, DeterministicDice(self._seed + k)).state
                    except IllegalActionError:
                        pass
            values.append(self._evaluate(applied, perspective))
        return fmean(values)

    def _pick(
        self, state: BattleState, actions: list[Action], perspective: int, floor: float
    ) -> Action | None:
        best_action: Action | None = None
        best_value = floor
        for action in actions:
            value = self._value(state, action, perspective)
            if value > best_value:  # strict > → deterministyczny tie-break
                best_value = value
                best_action = action
        return best_action

    # -- API gracza -------------------------------------------------------

    def choose_action(self, state: BattleState, perspective: int) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        return self._pick(state, candidates, perspective, -math.inf)

    def continue_activation(
        self, state: BattleState, perspective: int, unit_id, actions_taken
    ) -> Action | None:
        followups = legal_followup_actions(state, perspective, unit_id, actions_taken)
        if not followups:
            return None
        # Pass = ocena bieżącego stanu (inicjatywa jeszcze nie przeszła) → bierz
        # kontynuację tylko gdy ściśle poprawia (strict > we floor).
        pass_value = self._evaluate(state, perspective)
        return self._pick(state, followups, perspective, pass_value)
