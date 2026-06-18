"""D4 — MinimaxPlayer: lookahead głębokości 2 (maximin) nad publicznym API silnika.

Strumień D (roadmap `docs/roadmap.md#d4-adversarial-play`). W odróżnieniu od
botów depth-1 (`GreedyPlayer` przybliża skutek akcji heurystycznym hipotetycznym
stanem), `MinimaxPlayer` **faktycznie aplikuje** każdą kandydującą akcję przez
`resolver.apply` (rzeczywista semantyka combatu + przekazanie inicjatywy pkt 8.a),
a następnie symuluje **najlepszą odpowiedź wroga** (1 ply) i ocenia wynikowy stan.
Wybiera akcję maksymalizującą ten zminimalizowany przez wroga wynik (maximin) —
adresuje udokumentowaną „miopię depth-1" (cele oddalone o >1 ruch, wymiany ognia
w których wróg odpowiada).

Decyzje projektowe:
- **Deterministyczny rollout.** Silnik jest stochastyczny (kości, ADR-0012), więc
  czysty minimax jest nieosiągalny. Lookahead używa `DeterministicDice(seed)`
  (świeży na każdą hipotetyczną aplikację) — wynik odtwarzalny per seed, jak
  `RandomPlayer`. Pełny expectiminimax (uśrednianie po rzutach) odłożony jako
  przedwczesny dla „depth-2 do testów" (roadmap D4).
- **Głębokość 2 = moja aktywacja + 1 odpowiedź wroga.** Pełne drzewo gry (wiele
  aktywacji/runda, pkt 8.b) jest niewykonalne w budżecie ~100 ms/akcja; maximin
  na jednym ply wroga to standardowy „depth-2".
- **Ocena stanu** = `evaluate_state` po przeliczeniu kontroli celów z pozycji
  (`_check_objective_control`, SSOT pkt 5.d). Bez przeliczenia zmiana kontroli z
  ruchu byłaby niewidoczna aż do `round_end_phase` (pkt 8.c.ii) — lookahead by jej
  nie „widział". Wróg jest traktowany jako maksymalizujący własną `evaluate_state`
  (ocena ~antysymetryczna: HP i kontrola celów zero-sum), co przybliża minimalizację
  mojej oceny.

Czysta funkcja decyzji — RNG lookahead jest lokalny (nie zaburza RNG realnej gry).
"""

from __future__ import annotations

import math

from app.services.agents.base import (
    Player,
    legal_actions,
    legal_followup_actions,
)
from app.services.agents.deployment import GridDeploymentMixin
from app.services.agents.policy_eval import evaluate_state
from app.services.engine.actions import Action
from app.services.engine.dice import DeterministicDice
from app.services.engine.phases import _check_objective_control
from app.services.engine.resolver import IllegalActionError, apply
from app.services.engine.state import BattleState


class MinimaxPlayer(GridDeploymentMixin, Player):
    """Bot z lookahead depth-2 (maximin). Rozstawia się gridem (jak boty determ.)."""

    def __init__(self, seed: int = 0) -> None:
        #: Seed deterministycznego rolloutu lookahead (odtwarzalność per seed).
        self._seed = int(seed)

    # -- ocena ------------------------------------------------------------

    def _evaluate(self, state: BattleState, perspective: int) -> float:
        """Skalarna ocena `state` z `perspective` po przeliczeniu kontroli celów.

        Reużywa `_check_objective_control` (SSOT pkt 5.d) → `evaluate_state`
        (bilans HP + kontrola/bliskość celów). Przeliczenie kontroli z pozycji
        czyni zmianę kontroli z akcji widoczną od razu (przed `round_end_phase`).
        """
        controlled, _events, _seq = _check_objective_control(state)
        return evaluate_state(controlled, perspective)

    # -- rollout ----------------------------------------------------------

    def _apply(self, state: BattleState, action: Action) -> BattleState | None:
        """Hipotetyczny stan po `action` (deterministyczny rollout) lub None.

        Świeży `DeterministicDice(seed)` na każdą aplikację → odtwarzalne,
        niezależne od kolejności oceny kandydatów. `IllegalActionError` (akcja
        odrzucona przez resolver, np. nie ta tura) → None, kandydat pomijany.
        """
        try:
            return apply(state, action, DeterministicDice(self._seed)).state
        except IllegalActionError:
            return None

    def _opponent_best_value(
        self, state: BattleState, perspective: int
    ) -> float:
        """Wartość `state` z `perspective` po NAJLEPSZEJ odpowiedzi wroga (1 ply).

        Wróg (`1 - perspective`) wybiera akcję maksymalizującą własną
        `evaluate_state`; zwracamy ocenę wynikowego stanu z MOJEJ perspektywy.
        Gdy gra skończona (pkt 5.f) lub wróg nie ma legalnej odpowiedzi
        (np. inicjatywa nie przeszła — wszystkie jego oddziały Aktywowane) →
        ocena `state` bez odpowiedzi.
        """
        if state.is_game_over:
            return self._evaluate(state, perspective)
        opponent = 1 - perspective
        best_reply: BattleState | None = None
        best_opp_value = -math.inf
        for reply in legal_actions(state, opponent):
            applied = self._apply(state, reply)
            if applied is None:
                continue
            opp_value = self._evaluate(applied, opponent)
            if opp_value > best_opp_value:  # strict > → stabilny tie-break
                best_opp_value = opp_value
                best_reply = applied
        if best_reply is None:
            return self._evaluate(state, perspective)
        return self._evaluate(best_reply, perspective)

    def _action_value(
        self, state: BattleState, action: Action, perspective: int
    ) -> float:
        """Wartość maximin akcji: aplikuj → najlepsza odpowiedź wroga → ocena.

        Akcja nielegalna w rollout (None) → `-inf` (nigdy nie wybrana).
        """
        applied = self._apply(state, action)
        if applied is None:
            return -math.inf
        return self._opponent_best_value(applied, perspective)

    def _pick(
        self,
        state: BattleState,
        actions: list[Action],
        perspective: int,
        floor: float,
    ) -> Action | None:
        """Akcja o najwyższej wartości maximin powyżej `floor`, albo None.

        `strict >` → deterministyczny tie-break (pierwsza w stabilnej kolejności
        `legal_actions` wygrywa). `floor=-inf` w `choose_action` (zawsze wybiera
        coś, jeśli jest legalny kandydat); `floor=wartość-pass` w
        `continue_activation` (kontynuuj tylko gdy realnie poprawia).
        """
        best_action: Action | None = None
        best_value = floor
        for action in actions:
            value = self._action_value(state, action, perspective)
            if value > best_value:
                best_value = value
                best_action = action
        return best_action

    # -- API gracza -------------------------------------------------------

    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        return self._pick(state, candidates, perspective, -math.inf)

    def continue_activation(
        self, state: BattleState, perspective: int, unit_id, actions_taken
    ) -> Action | None:
        """2. akcja (pkt 11.b.iv): najlepsza legalna kontynuacja, jeśli jej wartość
        maximin przewyższa zakończenie aktywacji.

        Pass (zakończenie) przybliżamy oceną bieżącego stanu z mojej perspektywy:
        na tym etapie inicjatywa NIE przeszła (finalize/switch następują po
        zwróceniu z `continuation`), więc wróg jeszcze nie odpowiada — wartość
        pass = `_evaluate(state, perspective)`. Kontynuację bierzemy tylko gdy jej
        wartość maximin (z odpowiedzią wroga) jest ściśle wyższa → konserwatywnie
        nie przeciągamy 2. akcji, jeśli wróg by ją skontrował.
        """
        followups = legal_followup_actions(
            state, perspective, unit_id, actions_taken
        )
        if not followups:
            return None
        # Pass (zakończenie) = ocena bieżącego stanu — `strict >` w `_pick` znaczy:
        # bierz kontynuację tylko gdy ściśle poprawia względem zakończenia.
        pass_value = self._evaluate(state, perspective)
        return self._pick(state, followups, perspective, pass_value)
