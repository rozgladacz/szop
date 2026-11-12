"""B3.6 — Action types per `SZOP_Rozjemca.md pkt 13 (deployment) + pkt 14 (akcje)`.

Akcje są polimorficznym wejściem `phases.activation_phase(state, action)` i
`phases.deployment_round(state, deployment_actions)`. Dispatch w `phases.py` per
`isinstance(action, ...)`.

Wszystkie akcje są frozen+slots dataclass — immutable, deterministyczne, replay-safe.

Akcje runtime (pkt 14):
- `ManeuverAction` (14.a) — Ruch oddziału do target_position
- `DefendAction` (14.b) — Status `Przygotowany`
- `ShootAction` (14.c) — Ostrzał (pojedynczy target w MVP; multi-target → przyszła iteracja)
- `ChargeAction` (14.d) — Szarża + ewentualny kontratak
- `SpecialAction` (14.e) — Akcja specjalna (Odrzuć Wyczerpany / aktywna zdolność per slug)

Akcja deployment (pkt 13):
- `DeploymentAction` — rozstawienie oddziału w strefie rozstawienia
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Union

from app.services.engine.combat import WeaponProfile
from app.services.engine.state import Position


@dataclass(frozen=True, slots=True)
class DeploymentAction:
    """Pkt 13 Aktywacja rozstawienia. `position` w strefie rozstawienia gracza."""

    unit_id: int
    position: Position


@dataclass(frozen=True, slots=True)
class ManeuverAction:
    """Pkt 14.a Manewr — oddział wykonuje Ruch (pkt 15) do `target_position`.

    Gracz deklaruje punkt końcowy. Resolver szuka legalnej trasy (ADR-0057).
    """

    unit_id: int
    target_position: Position


@dataclass(frozen=True, slots=True)
class DefendAction:
    """Pkt 14.b Obrona — oddział zyskuje stan Przygotowany (pkt 22.c)."""

    unit_id: int


@dataclass(frozen=True, slots=True)
class ShootAction:
    """Pkt 14.c Ostrzał — atak dystansowy na pojedynczy cel.

    MVP: jeden `target_id` + jedna `weapon`. Multi-target (do 2, pkt 14.c.i)
    odłożone do przyszłej iteracji.
    """

    unit_id: int
    target_id: int
    weapon: WeaponProfile


@dataclass(frozen=True, slots=True)
class ChargeAction:
    """Pkt 14.d Szarża — Związanie + kontratak + atak wręcz.

    Delegacja do `combat.resolve_charge_attack`. `counter_attack_declared` to
    decyzja obrońcy (default True per pkt 14.d.iv — domyślnie odpowiada
    kontratakiem jeśli nie Wyczerpany).
    """

    unit_id: int
    target_id: int
    weapon: WeaponProfile
    counter_attack_declared: bool = True


@dataclass(frozen=True, slots=True)
class SpecialAction:
    """Pkt 14.e Akcja specjalna.

    `ability_slug` ∈ {`discard_exhausted` (uniwersalny: pkt 22.a.ii Odrzuć Wyczerpany),
    `latanie`, `meczennik`, `mobilizacja`, `presja`, `przepowiednia`, `mag`} (per
    B3.0.1 audit). `payload` zawiera dane specyficzne (np. target_id dla Łatania,
    spell_name dla Mag).
    """

    unit_id: int
    ability_slug: str
    payload: dict[str, Any] = field(default_factory=dict)


# Polimorficzny alias — używany w `phases.activation_phase(state, action: Action)`.
Action = Union[
    ManeuverAction,
    DefendAction,
    ShootAction,
    ChargeAction,
    SpecialAction,
]


# Shared SSOT for the stable action discriminators used by the public action
# codec and durable activation checkpoints.  The immutable mapping prevents a
# runtime caller from changing the persisted vocabulary.
ACTION_TYPE_BY_CLASS = MappingProxyType(
    {
        ManeuverAction: "maneuver",
        DefendAction: "defend",
        ShootAction: "shoot",
        ChargeAction: "charge",
        SpecialAction: "special",
    }
)
ACTION_TYPE_DISCRIMINATORS = frozenset(ACTION_TYPE_BY_CLASS.values())
MAX_ACTIONS_PER_ACTIVATION = 2
_SINGLE_USE_ACTION_TYPES = frozenset(
    {
        ACTION_TYPE_BY_CLASS[ShootAction],
        ACTION_TYPE_BY_CLASS[ChargeAction],
    }
)


def can_append_activation_action_type(
    action_type: str,
    action_types: tuple[str, ...],
) -> bool:
    """Return whether one canonical action type may extend durable history."""

    if (
        type(action_type) is not str
        or action_type not in ACTION_TYPE_DISCRIMINATORS
        or type(action_types) is not tuple
        or any(
            type(item) is not str or item not in ACTION_TYPE_DISCRIMINATORS
            for item in action_types
        )
        or len(action_types) >= MAX_ACTIONS_PER_ACTIVATION
    ):
        return False
    return (
        action_type not in _SINGLE_USE_ACTION_TYPES
        or action_type not in action_types
    )
