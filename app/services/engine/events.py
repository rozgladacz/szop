"""B3.0.3 — Battle events: 10 typów + serializer (ADR-0010 / ADR-0046).

Każdy event to frozen dataclass z polami zgodnymi z `BattleEvent.payload_json`
(przyszła ORM, B2). Wszystkie eventy mają:
- `sequence: int` — global ordering w bitwie (UniqueConstraint w ORM)
- `__version__: int = 1` — wersja schematu eventu (kompatybilność wsteczna)

Serializer:
- `event_to_json(event) → dict` — `{"event_type": str, "version": int, **fields}`
- `json_to_event(data) → BattleEvent` — odwrotna; raise `ValueError` dla nieznanego type lub schema mismatch.

Wszystkie 10 typów:
- `MoveExecuted` — ruch oddziału (Manewr / Związanie / Szarża move)
- `ShotResolved` — rozliczony Ostrzał (pkt 14.c)
- `MeleeResolved` — rozliczona Szarża / Kontratak (pkt 14.d)
- `ModelKilled` — pokonany model w oddziale (pkt 18.a/b)
- `MoraleTestPassed` — wynik Przegrupowania (pkt 20)
- `EffectApplied` — efekt zdolności (pasywnej / aktywnej) na oddziale
- `InterruptTriggered` — wywołanie przerwania (pkt 12)
- `RoundEnded` — koniec rundy (pkt 8.c)
- `StatusAdded` (B3.9.d / ADR-0046) — status flag dodany do oddziału (pkt 22)
- `StatusRemoved` (B3.9.d / ADR-0046) — status flag usunięty z oddziału
- `MeleeBalanceReset` (B3.9.d / ADR-0046) — reset bilansu wręcz po Przegrupowaniu
- `MutexCollision` (R5.e / resync 2026-06) — Przyszpilony↔Ufortyfikowany mutex, oba odrzucone (pkt 22.b/c)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Union

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class MoveExecuted:
    """Ruch oddziału (pkt 15 + 16). `from_pos`/`to_pos` jako `(x, y)` w calach."""

    sequence: int
    unit_id: int
    from_pos: tuple[float, float]
    to_pos: tuple[float, float]
    move_type: str = "manever"  # ∈ {manever, binding, charge_move}
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ShotResolved:
    """Rozliczony Ostrzał (pkt 14.c + 17). `hits` = trafienia; `wounds_*` per ADR-0014."""

    sequence: int
    attacker_id: int
    defender_id: int
    weapon_slug: str
    hits: int
    wounds_dealt: int  # do `wounds_pending` defendera
    wounds_precise: int = 0  # do `wounds_pending_precise` defendera
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MeleeResolved:
    """Rozliczona Szarża / Kontratak (pkt 14.d + 17).

    `charger_id` = oddział szarżujący w danej sekwencji (kontratak: defender
    z poprzedniego sub-Ataku staje się attackerem). `attacker_id`/`defender_id`
    odzwierciedlają role w tej połowie wymiany.
    """

    sequence: int
    attacker_id: int
    defender_id: int
    weapon_slug: str
    hits: int
    wounds_dealt: int
    wounds_precise: int = 0
    charger_id: int = 0  # 0 = nieustalone / kontratak; >0 = jednoznacznie szarżujący
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ModelKilled:
    """Pokonany model w oddziale (pkt 18.a/b).

    `unit_id` = oddział tracący model. `model_index` = pozycja w oddziale (per
    deterministyczna kolejność, dla Precyzyjny atakujący wybiera). `is_hero`
    = czy pokonany model to Bohater (id 2).
    """

    sequence: int
    unit_id: int
    model_index: int
    is_hero: bool = False
    by_attacker_id: int | None = None  # source oddział (atakujący)
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MoraleTestPassed:
    """Wynik Przegrupowania oddziału (pkt 20).

    `rolls` = lista k6 result (np. `[3, 5, 2]` — 3 testy). `failures` = liczba
    porażek (k < threshold). `result_status` ∈ {"pass", "exhausted",
    "pinned", "exhausted_pinned", "broken"} per pkt 20.e.
    """

    sequence: int
    unit_id: int
    rolls: tuple[int, ...]
    failures: int
    result_status: str
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class EffectApplied:
    """Efekt zdolności (pasywnej / aktywnej / aury) na oddziale.

    `slug` z `abilities.yaml`. `target_unit_id` = oddział otrzymujący efekt.
    `source_unit_id` = oddział emitujący (dla aur / aktywnych). `payload` to
    dowolne dane specyficzne dla zdolności (np. wartość parametru X dla
    Mistrzostwo / Klątwa / Rozkaz).
    """

    sequence: int
    slug: str
    target_unit_id: int
    source_unit_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class InterruptTriggered:
    """Wywołanie przerwania (pkt 12).

    `interrupt_point` ∈ {"activation_start", "after_action", "before_regroup",
    "after_regroup"} per ADR-0015. `slug` = zdolność triggerująca (Strażnik /
    Rozkaz / Klątwa / etc.).
    """

    sequence: int
    interrupt_point: str
    slug: str
    source_unit_id: int
    target_unit_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RoundEnded:
    """Koniec rundy (pkt 8.c).

    `round_number` ∈ 0-4 (0 = deployment; 4 = ostatnia). `objectives_held` =
    pula zajętych celów per gracz (pkt 5.d) — output pkt 8.c.ii.
    """

    sequence: int
    round_number: int
    objectives_held: tuple[int, int] = (0, 0)  # per player
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class StatusAdded:
    """Status flag dodany do oddziału (`SZOP_Rozjemca.md pkt 22`).

    B3.9.d (ADR-0046): zastępuje silent `replace(blob, status_flags=...)` na
    "live state" — każda mutacja `status_flags` emituje teraz event, dzięki
    czemu `apply_events(initial, events)` rekonstruuje pełen stan (proof-of-
    completeness dla ADR-0010 invariant).

    Reducer jest idempotentny — dodanie istniejącego flagu = no-op, zgodny z
    `status.add_status` helper.

    `status` ∈ {"Aktywowany", "Wyczerpany", "Przyszpilony", "Ufortyfikowany"}
    (`StatusFlag` enum z `status.py`).
    """

    sequence: int
    target_id: int
    status: str  # StatusFlag (str-equivalent)
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class StatusRemoved:
    """Status flag usunięty z oddziału.

    B3.9.d (ADR-0046). Idempotentny — usunięcie nieistniejącego flagu = no-op.
    Używany przez `round_end_phase` (reset Aktywowany pkt 8.c.i),
    `_apply_defend` (Przyszpilony→Ufortyfikowany pkt 22.b.v),
    `_apply_special.discard_exhausted` (Wyczerpany pkt 22.a.ii).
    """

    sequence: int
    target_id: int
    status: str
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ObjectiveControlChanged:
    """Zmiana kontroli celu (pkt 5.d).

    CR-fix A (post-B3.9.f code review): pre-fix `_check_objective_control`
    mutowal `state.objectives[*].controller` przez `replace()` bez emit eventu
    — replay state nie odzwierciedlał zmian. ADR-0010 invariant naruszony dla
    `objectives`. Post-fix: emit per zmianę kontroli + reducer.

    `previous_controller`/`new_controller`: ∈ {None, 0, 1}. None = niezajęty;
    0/1 = owner_player. Reducer updates `state.objectives[i].controller`.
    """

    sequence: int
    objective_id: int
    previous_controller: int | None
    new_controller: int | None
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class InitiativePassed:
    """Przekazanie inicjatywy (pkt 8.a).

    CR-fix B (post-B3.9.f code review): pre-fix `resolver._switch_active_player`
    mutowal `state.active_player` przez `replace()` bez emit eventu — replay
    state pozostawał na `initial.active_player`. Per-aktywacja initiative
    pass jest teraz event-sourced.

    Reducer ustawia `state.active_player = new_active_player`. Jeśli engine
    decyduje że inicjatywa NIE zmienia się (drugi gracz nie ma nieaktywowanych),
    event NIE jest emitowany (no-op).
    """

    sequence: int
    previous_active_player: int
    new_active_player: int
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MeleeBalanceReset:
    """Reset `melee_balance` na oddziale (pkt 20.c — bilans wręcz po regroup).

    B3.9.d (ADR-0046). Emitowany w `activation_phase` po fazie Przegrupowania
    dla każdego uczestnika starcia wręcz (`melee_combatants`) i dla actora gdy
    `melee_balance != 0`. Reducer ustawia `blob.melee_balance = 0`.

    Powód osobnego eventu (zamiast pakowania w MoraleTestPassed): reset
    następuje DLA WSZYSTKICH combatants, nawet gdy nie wykonali testu (np.
    defender pokonany w aktywacji chargera nie ma morale test).
    """

    sequence: int
    target_id: int
    version: int = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MutexCollision:
    """Wzajemne wykluczenie statusów odrzuca oba (`SZOP_Rozjemca.md pkt 22.b/c`).

    R5.e (faza-b-rules-resync 2026-06 / decyzja H2 opcja (c)): Przyszpilony
    (pkt 22.b) i Ufortyfikowany (pkt 22.c) nie mogą współistnieć na jednym
    oddziale. Gdy producer (`phases.activation_phase` po fazie Przegrupowania)
    wykryje że oddział ma OBA statusy — emituje `MutexCollision`, a reducer
    odrzuca oba.

    Pipeline event-sourced (zamiast producer-only silent removal): explicit
    collision marker w replay log daje debug/analytics widoczność "tu doszło
    do mutex collision". `dropped_statuses` to lista statusów odrzuconych
    (zawsze `("Przyszpilony", "Ufortyfikowany")` w MVP — pole generyczne na
    wypadek przyszłych par mutex).

    Idempotentny — reducer usuwa statusy z `remove_status` (no-op gdy brak).
    """

    sequence: int
    target_id: int
    dropped_statuses: tuple[str, ...] = ()
    version: int = SCHEMA_VERSION


# Union polimorficzny dla type hints. `BattleEvent` jest aliasem.
BattleEvent = Union[
    MoveExecuted,
    ShotResolved,
    MeleeResolved,
    ModelKilled,
    MoraleTestPassed,
    EffectApplied,
    InterruptTriggered,
    RoundEnded,
    StatusAdded,
    StatusRemoved,
    MeleeBalanceReset,
    MutexCollision,
    ObjectiveControlChanged,
    InitiativePassed,
]

_EVENT_REGISTRY: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        MoveExecuted,
        ShotResolved,
        MeleeResolved,
        ModelKilled,
        MoraleTestPassed,
        EffectApplied,
        InterruptTriggered,
        RoundEnded,
        StatusAdded,
        StatusRemoved,
        MeleeBalanceReset,
        MutexCollision,
        ObjectiveControlChanged,
        InitiativePassed,
    )
}


def event_to_json(event: BattleEvent) -> dict[str, Any]:
    """Serializuje event do dict z `event_type` discriminator.

    Wynik: `{"event_type": "MoveExecuted", **all_fields}`. `payload_json`
    w `BattleEvent` ORM (B2) to `json.dumps(event_to_json(event))`.
    """
    if not is_dataclass(event):
        raise TypeError(f"Not a dataclass event: {type(event).__name__}")
    payload = asdict(event)
    payload["event_type"] = type(event).__name__
    return payload


def json_to_event(data: dict[str, Any]) -> BattleEvent:
    """Deserializuje dict do event dataclass.

    Raise `ValueError` dla:
    - Brak klucza `event_type`
    - Nieznany `event_type` (nie w `_EVENT_REGISTRY`)
    - Brak required field-ów lub niezgodność schematu (`__init__` raise)
    """
    if "event_type" not in data:
        raise ValueError("event payload missing 'event_type' key")
    event_type = data["event_type"]
    cls = _EVENT_REGISTRY.get(event_type)
    if cls is None:
        raise ValueError(
            f"Unknown event type: {event_type!r}; known: {list(_EVENT_REGISTRY)}"
        )
    # Filtruj klucze do tych, które ma dataclass — `event_type` to discriminator,
    # nie field. Tuple fields wymagają konwersji z list (JSON nie ma tuple).
    known_fields = {f.name for f in fields(cls)}
    payload = {k: v for k, v in data.items() if k in known_fields}
    # Convert lists → tuples for fields typed as tuple (sequence/rolls etc.)
    for f in fields(cls):
        if f.name in payload and isinstance(payload[f.name], list):
            payload[f.name] = tuple(payload[f.name])
    return cls(**payload)
