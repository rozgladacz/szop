"""B3.0.5 — testy `app/services/engine/state.py`.

Pokrywa: immutability dataclasses, compute_radius (zgodny z ADR-0008),
build_initial_state z walidacją exclusions (ADR-0008), apply_events +
register_reducer pure replay (ADR-0010).
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from app.services.engine.events import MoveExecuted
from app.services.engine.state import (
    BattleState,
    Position,
    TerrainCircle,
    TerrainLine,
    UnitBlob,
    UnsupportedAbilityError,
    _EVENT_REDUCERS,
    apply_events,
    build_initial_state,
    compute_radius_inches,
    register_reducer,
)
from app.services.rulesets.models import BMvpConfig

# Helper config dla testów — niezależny od load_ruleset().
_TEST_CONFIG = BMvpConfig(
    move_inches=6,
    base_area_inches_sq_per_toughness=1,
    pi_approx=math.pi,
)


# ---------------------------------------------------------------------------
# Immutability — frozen dataclasses
# ---------------------------------------------------------------------------


def test_position_is_frozen():
    pos = Position(x=1.0, y=2.0)
    with pytest.raises(FrozenInstanceError):
        pos.x = 99.0  # type: ignore[misc]


def test_unit_blob_is_frozen():
    blob = UnitBlob(
        id=1,
        owner_player=0,
        position=Position(0.0, 0.0),
        radius_inches=1.0,
        models_alive=5,
        toughness_per_model=3,
    )
    with pytest.raises(FrozenInstanceError):
        blob.models_alive = 0  # type: ignore[misc]


def test_battle_state_is_frozen():
    state = BattleState(
        round=0,
        active_player=0,
        activations_remaining=(0, 0),
        blobs=(),
        terrain=(),
    )
    with pytest.raises(FrozenInstanceError):
        state.round = 5  # type: ignore[misc]


def test_terrain_circle_is_frozen():
    t = TerrainCircle(center=Position(0.0, 0.0), radius_inches=2.0, features=("Blokujacy",))
    with pytest.raises(FrozenInstanceError):
        t.radius_inches = 3.0  # type: ignore[misc]


def test_terrain_line_is_frozen():
    t = TerrainLine(start=Position(0.0, 0.0), end=Position(10.0, 0.0), features=("Blokujacy",))
    with pytest.raises(FrozenInstanceError):
        t.features = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# compute_radius_inches — ADR-0008 wzór
# ---------------------------------------------------------------------------


def test_compute_radius_homogeneous_unit():
    """5 modeli toughness 3 → radius = sqrt(15/pi) ≈ 2.1851."""
    radius = compute_radius_inches(toughness_sum=5 * 3, config=_TEST_CONFIG)
    assert math.isclose(radius, math.sqrt(15 / math.pi), rel_tol=1e-9)


def test_compute_radius_with_hero():
    """Bohater jako toughness/2: 1×T3 + 1×T6 hero → sum = 3 + 3 = 6 → sqrt(6/pi)."""
    radius = compute_radius_inches(toughness_sum=3 + 6 / 2, config=_TEST_CONFIG)
    assert math.isclose(radius, math.sqrt(6 / math.pi), rel_tol=1e-9)


def test_compute_radius_default_config_uses_ruleset():
    """Brak config arg → load z `tables.yaml > b_mvp`."""
    radius = compute_radius_inches(toughness_sum=15)
    expected = math.sqrt(15 / math.pi)
    assert math.isclose(radius, expected, rel_tol=1e-6)


def test_compute_radius_zero_toughness():
    """Brzeg: brak modeli → radius 0 (engine może to obsłużyć w innych miejscach)."""
    radius = compute_radius_inches(toughness_sum=0, config=_TEST_CONFIG)
    assert radius == 0


# ---------------------------------------------------------------------------
# build_initial_state — walidacja exclusions
# ---------------------------------------------------------------------------


def _minimal_unit(unit_id: int, passives: tuple[str, ...] = ()) -> dict:
    return {
        "id": unit_id,
        "position": (10.0, 10.0),
        "models": 5,
        "toughness": 3,
        "passives": list(passives),
    }


def test_build_initial_state_basic_2_players():
    rosters = [
        {"owner_player": 0, "units": [_minimal_unit(1), _minimal_unit(2)]},
        {"owner_player": 1, "units": [_minimal_unit(3)]},
    ]
    state = build_initial_state(rosters)
    assert state.round == 0
    assert state.active_player == 0
    assert len(state.blobs) == 3
    assert state.activations_remaining == (2, 1)


def test_build_initial_state_assigns_owner_correctly():
    rosters = [
        {"owner_player": 0, "units": [_minimal_unit(1)]},
        {"owner_player": 1, "units": [_minimal_unit(2)]},
    ]
    state = build_initial_state(rosters)
    blob_by_id = {b.id: b for b in state.blobs}
    assert blob_by_id[1].owner_player == 0
    assert blob_by_id[2].owner_player == 1


def test_build_initial_state_hero_handling():
    """Oddział z bohaterem ma `is_hero_unit=True` i mniejszy radius."""
    rosters = [
        {
            "owner_player": 0,
            "units": [
                {**_minimal_unit(1), "passives": ["bohater"]},
                _minimal_unit(2),
            ],
        },
        {"owner_player": 1, "units": [_minimal_unit(3)]},
    ]
    state = build_initial_state(rosters)
    blob_by_id = {b.id: b for b in state.blobs}
    assert blob_by_id[1].is_hero_unit is True
    assert blob_by_id[2].is_hero_unit is False
    # hero unit ma toughness_sum = models*tou/2 = 5*3/2 = 7.5 → r = sqrt(7.5/pi) ≈ 1.545
    # plain unit ma toughness_sum = 15 → r = sqrt(15/pi) ≈ 2.185
    assert blob_by_id[1].radius_inches < blob_by_id[2].radius_inches


@pytest.mark.parametrize(
    "excluded_slug",
    ["samolot", "wrak", "wysoki", "zwrot", "sterowany", "zuzywalny"],
)
def test_build_initial_state_raises_for_each_exclusion(excluded_slug):
    """Każda z 6 wykluczeń z `b_mvp_exclusions.yaml` raise."""
    rosters = [
        {
            "owner_player": 0,
            "units": [{**_minimal_unit(1), "passives": [excluded_slug]}],
        },
        {"owner_player": 1, "units": [_minimal_unit(2)]},
    ]
    with pytest.raises(UnsupportedAbilityError) as exc_info:
        build_initial_state(rosters)
    assert exc_info.value.slug == excluded_slug
    assert exc_info.value.reason  # niepusty reason


def test_build_initial_state_allows_supported_abilities():
    """Wspierane zdolności (np. Bohater, Nieustraszony) nie powodują raise."""
    rosters = [
        {
            "owner_player": 0,
            "units": [
                {**_minimal_unit(1), "passives": ["bohater", "nieustraszony"]},
            ],
        },
        {"owner_player": 1, "units": [_minimal_unit(2)]},
    ]
    state = build_initial_state(rosters)
    assert len(state.blobs) == 2


# ---------------------------------------------------------------------------
# apply_events + register_reducer
# ---------------------------------------------------------------------------


def test_apply_events_empty_returns_initial():
    initial = BattleState(
        round=0,
        active_player=0,
        activations_remaining=(0, 0),
        blobs=(),
        terrain=(),
    )
    result = apply_events(initial, [])
    assert result is initial


def test_apply_events_unknown_event_raises():
    """Brak reducera → NotImplementedError. Post-B3.9.d (ADR-0046): wszystkie
    10 znanych event types mają reducer w `reducers.py`. Test używa syntetycznego
    event type spoza rejestru."""
    initial = BattleState(
        round=0,
        active_player=0,
        activations_remaining=(0, 0),
        blobs=(),
        terrain=(),
    )

    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class UnknownEvent:
        sequence: int = 1

    with pytest.raises(NotImplementedError, match="UnknownEvent"):
        apply_events(initial, [UnknownEvent()])


def test_register_reducer_duplicate_raises(monkeypatch):
    """Re-registracja tego samego event type raise."""
    # Czyścimy globalny rejestr na czas testu (nie modyfikujemy go trwale)
    monkeypatch.setattr(
        "app.services.engine.state._EVENT_REDUCERS",
        {},
        raising=False,
    )

    @register_reducer("FooEvent")
    def _r1(state, event):  # noqa: ANN001
        return state

    with pytest.raises(RuntimeError):

        @register_reducer("FooEvent")
        def _r2(state, event):  # noqa: ANN001
            return state


def test_apply_events_with_registered_reducer(monkeypatch):
    """Reducer wywołany dla zarejestrowanego typu — dispatch działa."""
    monkeypatch.setattr(
        "app.services.engine.state._EVENT_REDUCERS",
        {},
        raising=False,
    )

    @register_reducer("MoveExecuted")
    def _reduce_move(state, event):
        # Symulujemy że event update'uje round (placeholder logiczny).
        return BattleState(
            round=state.round + 1,
            active_player=state.active_player,
            activations_remaining=state.activations_remaining,
            blobs=state.blobs,
            terrain=state.terrain,
        )

    initial = BattleState(
        round=0,
        active_player=0,
        activations_remaining=(0, 0),
        blobs=(),
        terrain=(),
    )
    event = MoveExecuted(sequence=1, unit_id=1, from_pos=(0.0, 0.0), to_pos=(1.0, 0.0))
    result = apply_events(initial, [event])
    assert result.round == 1


def test_apply_events_deterministic_with_same_events(monkeypatch):
    """Identyczna sekwencja eventów → identyczny output state."""
    monkeypatch.setattr(
        "app.services.engine.state._EVENT_REDUCERS",
        {},
        raising=False,
    )

    @register_reducer("MoveExecuted")
    def _r(state, event):
        return BattleState(
            round=state.round + 1,
            active_player=state.active_player,
            activations_remaining=state.activations_remaining,
            blobs=state.blobs,
            terrain=state.terrain,
        )

    initial = BattleState(
        round=0,
        active_player=0,
        activations_remaining=(0, 0),
        blobs=(),
        terrain=(),
    )
    events = [
        MoveExecuted(sequence=i, unit_id=1, from_pos=(0.0, 0.0), to_pos=(1.0, 0.0))
        for i in range(1, 4)
    ]
    s1 = apply_events(initial, events)
    s2 = apply_events(initial, events)
    assert s1 == s2
    assert s1.round == 3
