"""D — ClaudeV1Player: ogólny bot depth-1 (wartościowy) z gradientem celów i dobijaniem.

Rozszerza linię `GreedyPlayer` (depth-1 argmax po `legal_actions`, ocena przez Δ na
hipotetycznym stanie, 2 akcje move-then-strike) o dwa ogólne usprawnienia naprawiające
udokumentowane słabości depth-1, BEZ hardkodowania jakiejkolwiek zdolności:

1. **Świadomość zdolności za darmo** — ataki wyceniane przez `prediction.expected_damage`,
   które reużywa `combat.py` → uwzględnia każdą modelowaną przez silnik zdolność broni
   (AP/Brutalny/Precyzyjny/Niezawodny/Podwójny…) i pasywkę obrony/ataku (Cierpliwy/Tarcza…).
   Żaden slug nie jest zaszyty → nowe jednostki/zdolności działają automatycznie.
2. **Gradient celów (anty-miopia, pkt 5.f)** — `GreedyPlayer` „widzi" kontrolę celu tylko
   w 3″ (pkt 5.d), więc ignoruje dalekie cele. ClaudeV1 dodaje przyciąganie obejmujące
   całą planszę `MARCH·S/(S+gap)` ku każdemu celowi, którego NIE kontroluje → oddziały
   maszerują i kontestują (cele wygrywają grę, pkt 5.f).
3. **Dobijanie / eliminacja** — `p_full_kill·ELIM` premiuje wymiecenie całego oddziału
   (usuwa aktywację wroga + kontestera celu). Ogień skupia się na rannych zamiast muskać
   świeże (błąd, na którym poległ v2).

Złożoność: ten sam rząd co `GreedyPlayer` — kilka wywołań `expected_damage` na akcję,
bez lookahead (w odróżnieniu od depth-2 `MinimaxPlayer`). Czysta funkcja decyzji.
"""

from __future__ import annotations

import math

from app.services.agents.base import (
    Player,
    legal_actions,
    legal_followup_actions,
)
from app.services.agents.deployment import GridDeploymentMixin
from app.services.agents.greedy_player import (
    DEFEND_VALUE,
    DISCARD_VALUE,
    WOUND_VALUE,
    _apply_expected_kills,
    _blob_by_id,
    _replace_blob,
)
from app.services.engine.actions import (
    Action,
    ChargeAction,
    DefendAction,
    ManeuverAction,
    ShootAction,
    SpecialAction,
)
from app.services.engine.geometry import distance
from app.services.engine.phases import _check_objective_control
from app.services.engine.prediction import expected_damage
from app.services.engine.state import BattleState, UnitBlob

#: Waga kontroli celu (pkt 5.d/5.f) — cele rozstrzygają grę, > bilansu HP wymiany.
OBJECTIVE_WEIGHT: float = 25.0
#: Siła gradientu marszu ku niekontrolowanym celom (anty-miopia depth-1).
MARCH_WEIGHT: float = 12.0
#: Skala zaniku gradientu (″): pull = MARCH·S/(S+gap); przy gap=S połowa siły.
MARCH_SCALE: float = 12.0
#: Bonus za wymiecenie całego oddziału (usuwa aktywację + kontestera celu).
ELIM_BONUS: float = 14.0
#: Wartość akcji aktywnej innej niż discard_exhausted (próbuj, nie nadrzędnie).
SPECIAL_VALUE: float = 2.0

#: Gap zastępczy gdy gracz nie ma żywych oddziałów (gradient się nie wykłada).
_BIG_GAP: float = 1_000.0


def _objective_value(state: BattleState, perspective: int) -> float:
    """Wartość celów: kontrola (±`OBJECTIVE_WEIGHT`, pkt 5.d) + gradient marszu.

    Reużywa SSOT `phases._check_objective_control` (3″, Przyszpilony nie kontroluje
    pkt 22.b.ii). Dla każdego celu, którego gracz NIE kontroluje, dolicza
    przyciąganie `MARCH·S/(S+gap)` najbliższego własnego oddziału (gap obwód–cel) —
    ku własnym brakującym i wrogim celom. To gradient obejmujący planszę: oddział
    daleko od wszystkich celów wciąż czuje pull (naprawia miopię depth-1).
    """
    controlled, _events, _seq = _check_objective_control(state)
    own = [
        b
        for b in controlled.blobs
        if b.owner_player == perspective and b.models_alive > 0
    ]
    total = 0.0
    for obj in controlled.objectives:
        ctrl = obj.controller
        if ctrl == perspective:
            total += OBJECTIVE_WEIGHT
            continue
        if ctrl is not None:
            total -= OBJECTIVE_WEIGHT
        if own:
            gap = min(
                max(distance(u.position, obj.position) - u.radius_inches, 0.0)
                for u in own
            )
        else:
            gap = _BIG_GAP
        total += MARCH_WEIGHT * MARCH_SCALE / (MARCH_SCALE + gap)
    return total


class ClaudeV1Player(GridDeploymentMixin, Player):
    """Ogólny bot depth-1: Δ wartości celów (z gradientem) + obrażenia + dobijanie."""

    def choose_action(
        self, state: BattleState, perspective: int
    ) -> Action | None:
        candidates = legal_actions(state, perspective)
        if not candidates:
            return None
        base_objective = _objective_value(state, perspective)
        best_action: Action | None = None
        best_score = -math.inf
        for action in candidates:
            score = self._score(state, perspective, action, base_objective)
            if score > best_score:  # strict > → stabilny tie-break (pierwszy wygrywa)
                best_score = score
                best_action = action
        return best_action

    def continue_activation(
        self, state: BattleState, perspective: int, unit_id, actions_taken
    ) -> Action | None:
        """2. akcja (pkt 11.b.iv): najlepsza legalna kontynuacja wnosząca realną
        wartość (> `DEFEND_VALUE`); inaczej None (nie marnuje na Obronę).

        Umożliwia Manewr→Ostrzał: po dojściu w zasięg gradient marszu/obrażenia
        wybiorą drugą akcję bijącą próg, gdy samo „stój" by nie wniosło wartości.
        """
        followups = legal_followup_actions(state, perspective, unit_id, actions_taken)
        if not followups:
            return None
        base_objective = _objective_value(state, perspective)
        best = max(
            followups,
            key=lambda a: self._score(state, perspective, a, base_objective),
        )
        best_score = self._score(state, perspective, best, base_objective)
        return best if best_score > DEFEND_VALUE else None

    def _score(
        self,
        state: BattleState,
        perspective: int,
        action: Action,
        base_objective: float,
    ) -> float:
        if isinstance(action, (ShootAction, ChargeAction)):
            return self._attack_score(state, perspective, action, base_objective)
        if isinstance(action, ManeuverAction):
            hypothetical = _replace_blob(
                state, action.unit_id, position=action.target_position
            )
            # Ruch nie zmienia HP → Δ to czysto wartość celów (kontrola + gradient).
            return _objective_value(hypothetical, perspective) - base_objective
        if isinstance(action, DefendAction):
            return DEFEND_VALUE
        if isinstance(action, SpecialAction):
            return DISCARD_VALUE if action.ability_slug == "discard_exhausted" else SPECIAL_VALUE
        return 0.0

    def _attack_score(
        self,
        state: BattleState,
        perspective: int,
        action: ShootAction | ChargeAction,
        base_objective: float,
    ) -> float:
        attacker = _blob_by_id(state, action.unit_id)
        defender = _blob_by_id(state, action.target_id)
        if attacker is None or defender is None:
            return 0.0
        # Osłona (pkt 19) tylko Ostrzał — silnik melee jej nie liczy; Szarża z pustym terenem.
        terrain = state.terrain if isinstance(action, ShootAction) else ()
        dist = expected_damage(attacker, defender, action.weapon, terrain)
        # (a) obrażenia fine-grained (HP), (b) Δ wartości celów po wymiecionych
        # modelach (kontrola + gradient), (c) dobijanie: p(pełne wymiecenie)×ELIM.
        expected_kills = dist.expected_models_killed()
        hypothetical_kills = math.ceil(expected_kills) if expected_kills > 0 else 0
        hypothetical = _apply_expected_kills(state, defender.id, hypothetical_kills)
        raw_delta = _objective_value(hypothetical, perspective) - base_objective
        weight = (expected_kills / hypothetical_kills) if hypothetical_kills > 0 else 0.0
        objective_delta = weight * raw_delta
        return (
            dist.mean * WOUND_VALUE
            + objective_delta
            + dist.p_full_kill() * ELIM_BONUS
        )
