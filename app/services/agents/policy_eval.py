"""D1 — Funkcja oceny stanu (`evaluate_state`) dla botów heurystycznych.

Skalarna ocena `BattleState` z perspektywy gracza: wyższa = lepsza. Składowe:

1. **Bilans wytrzymałości** (HP) — Σ `models_alive * toughness_per_model` własne
   minus wroga. Toughness pool ≈ "Stan bitewny" (pkt 17.d–18); proxy siły bojowej.
2. **Cele** (pkt 5) — kontrola celów wygrywa grę (pkt 5.f: więcej zajętych celów
   = wygrana). Zajęty cel: `+OBJECTIVE_WEIGHT`; zajęty przez wroga: `−OBJECTIVE_WEIGHT`.
   Niezajęty cel: mały bonus za bliskość najbliższego własnego oddziału (zachęta
   do marszu na cele zanim runda 4 je rozstrzygnie, pkt 5.e/8.c.ii).

Wagi dobrane tak, by jeden cel (~strategiczny) przeważał kilka punktów ran
(taktyczny) — cele rozstrzygają grę. Czysta funkcja: zero RNG, zero I/O.
"""

from __future__ import annotations

from app.services.engine.geometry import distance
from app.services.engine.phases import _check_objective_control
from app.services.engine.state import BattleState, Objective, UnitBlob

#: Waga zajętego celu w punktach oceny. Dobrana > typowego bilansu HP jednej
#: wymiany ognia (kilka ran) — pkt 5.f czyni cele rozstrzygającymi.
OBJECTIVE_WEIGHT: float = 25.0

#: Maks. bonus za bliskość do niezajętego celu (gdy oddział praktycznie na celu).
#: Maleje z odległością; nigdy nie przewyższa kontroli celu.
PROXIMITY_WEIGHT: float = 5.0


def _unit_hp(blob: UnitBlob) -> int:
    """Pula wytrzymałości oddziału (`models_alive * toughness_per_model`)."""
    return blob.models_alive * blob.toughness_per_model


def _proximity_bonus(
    objective: Objective, own_units: list[UnitBlob]
) -> float:
    """Bonus za bliskość najbliższego własnego oddziału do niezajętego celu.

    `PROXIMITY_WEIGHT / (1 + gap)` gdzie `gap` = dystans środek-cel minus promień
    oddziału (≈ odległość obwodu od celu, pkt 5.d mierzy 3″ od celu). Brak
    własnych oddziałów → 0.
    """
    if not own_units:
        return 0.0
    nearest_gap = min(
        max(distance(u.position, objective.position) - u.radius_inches, 0.0)
        for u in own_units
    )
    return PROXIMITY_WEIGHT / (1.0 + nearest_gap)


def _hp_balance(state: BattleState, perspective: int) -> float:
    """Bilans wytrzymałości: Σ HP własne − Σ HP wroga (proxy siły bojowej)."""
    own_hp = sum(
        _unit_hp(b)
        for b in state.blobs
        if b.owner_player == perspective and b.models_alive > 0
    )
    enemy_hp = sum(
        _unit_hp(b)
        for b in state.blobs
        if b.owner_player != perspective and b.models_alive > 0
    )
    return float(own_hp - enemy_hp)


def _objective_balance(state: BattleState, perspective: int) -> float:
    """Składowa celów: kontrola (`±OBJECTIVE_WEIGHT`, wg `obj.controller`) +
    proximity dla niezajętych. Czyta `state.objectives[*].controller` jak jest —
    przeliczenie z pozycji robi `objective_balance_with_control`.
    """
    own_units = [
        b
        for b in state.blobs
        if b.owner_player == perspective and b.models_alive > 0
    ]
    total = 0.0
    for obj in state.objectives:
        if obj.controller == perspective:
            total += OBJECTIVE_WEIGHT
        elif obj.controller is not None:
            total -= OBJECTIVE_WEIGHT
        else:
            total += _proximity_bonus(obj, own_units)
    return total


def evaluate_state(state: BattleState, perspective: int) -> float:
    """Skalarna ocena `state` z perspektywy gracza `perspective` (wyższa lepsza).

    Patrz docstring modułu: bilans HP + kontrola/bliskość celów. Czyta
    `obj.controller` jak jest (kontrola aktualizowana w `round_end_phase`,
    pkt 8.c.ii); boty chcące wycenić zmianę kontroli *w obrębie* akcji używają
    `objective_balance_with_control`.
    """
    return _hp_balance(state, perspective) + _objective_balance(state, perspective)


def objective_balance_with_control(state: BattleState, perspective: int) -> float:
    """Wartość celów po **przeliczeniu kontroli z aktualnych pozycji** (pkt 5.d).

    Wspólna waluta dla botów: pozwala wycenić przejęcie/utratę celu *w obrębie*
    rozważanej akcji, zanim `round_end_phase` to potwierdzi (pkt 8.c.ii). Bez tego
    ruch na niezajęty cel widać tylko jako proximity (≤`PROXIMITY_WEIGHT`), nie
    jako kontrolę (`OBJECTIVE_WEIGHT`). Reużywa `phases._check_objective_control`
    (SSOT pkt 5.d — 3″, Przyszpilony nie kontroluje pkt 22.b.ii).
    """
    controlled, _events, _seq = _check_objective_control(state)
    return _objective_balance(controlled, perspective)
