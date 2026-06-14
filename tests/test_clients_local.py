"""B5 — testy `szop_client.LocalClient` (ADR-0016).

Pokrycie: determinizm batcha, parity z runnerem (`simulate_from_rosters`) i z
D2 (`scripts.balance_simulate.simulate_balance`), wierność single-step play
(`take_action` == `resolver.apply_activation`), walidacja błędów.
"""

from __future__ import annotations

import pytest

from app.services.agents.match import simulate_from_rosters
from app.services.agents.random_player import RandomPlayer
from app.services.engine.actions import DefendAction, ManeuverAction
from app.services.engine.dice import DeterministicDice
from app.services.engine.phases import deployment_round, setup_phase
from app.services.engine.resolver import IllegalActionError, apply_activation
from app.services.engine.state import Objective, Position
from app.services.engine.status import STATUS_UFORTYFIKOWANY
from scripts.balance_simulate import (
    PLAYER_SEED_OFFSET,
    load_battle_fixture,
    make_player,
    simulate_balance,
)
from szop_client import LocalClient, SimulationSummary, UnknownBattleError

# Minimalna 1v1 fixtura engine-dict (1 oddział/stronę, czysto wręcz).
_ROSTERS = [
    {
        "owner_player": 0,
        "units": [
            {
                "id": 1,
                "position": (10, 10),
                "models": 5,
                "toughness": 3,
                "quality": 4,
                "defense": 5,
                "passives": [],
                "weapons": [
                    {"slug": "blade", "name": "Ostrze", "range_inches": 0, "attacks": 1, "ap": 0}
                ],
            }
        ],
    },
    {
        "owner_player": 1,
        "units": [
            {
                "id": 2,
                "position": (10, 30),
                "models": 5,
                "toughness": 3,
                "quality": 4,
                "defense": 5,
                "passives": [],
                "weapons": [
                    {"slug": "blade", "name": "Ostrze", "range_inches": 0, "attacks": 1, "ap": 0}
                ],
            }
        ],
    },
]
_OBJECTIVES = (Objective(id=1, position=Position(10, 20)),)

_FIXTURE_PATH = "tests/fixtures/battles/unit_profiles.yaml"


def _random_factory(base_seed: int):
    """Fabryka graczy z rozłącznymi seedami per stronę (F2)."""

    def factory(i: int):
        return [
            RandomPlayer(seed=base_seed + i),
            RandomPlayer(seed=base_seed + i + PLAYER_SEED_OFFSET),
        ]

    return factory


# --- batch simulate -------------------------------------------------------


def test_simulate_returns_summary():
    client = LocalClient()
    fixture = load_battle_fixture(_FIXTURE_PATH)
    summary = client.simulate(
        fixture.rosters,
        _random_factory(0),
        n=5,
        seed=0,
        terrain=fixture.terrain,
        objectives=fixture.objectives,
    )
    assert isinstance(summary, SimulationSummary)
    assert summary.n_games == 5
    assert summary.wins_p0 + summary.wins_p1 + summary.draws == 5
    assert 0.0 <= summary.win_rate_p0 <= 1.0
    assert summary.avg_rounds > 0


def test_simulate_deterministic_same_seed():
    fixture = load_battle_fixture(_FIXTURE_PATH)
    a = LocalClient().simulate(
        fixture.rosters, _random_factory(0), n=6, seed=3,
        terrain=fixture.terrain, objectives=fixture.objectives,
    )
    b = LocalClient().simulate(
        fixture.rosters, _random_factory(0), n=6, seed=3,
        terrain=fixture.terrain, objectives=fixture.objectives,
    )
    assert a == b


def test_simulate_aggregates_match_runner():
    """`simulate` agreguje dokładnie to, co manualna pętla `simulate_from_rosters`."""
    fixture = load_battle_fixture(_FIXTURE_PATH)
    n, base = 6, 11
    summary = LocalClient().simulate(
        fixture.rosters, _random_factory(base), n=n, seed=base,
        terrain=fixture.terrain, objectives=fixture.objectives,
    )
    wins = [0, 0]
    draws = 0
    rounds = 0
    factory = _random_factory(base)
    for i in range(n):
        result = simulate_from_rosters(
            fixture.rosters,
            factory(i),
            seed=base + i,
            terrain=fixture.terrain,
            objectives=fixture.objectives,
            initiative_player=i % 2,
        )
        if result.winner is None:
            draws += 1
        else:
            wins[result.winner] += 1
        rounds += result.rounds_played
    assert (summary.wins_p0, summary.wins_p1, summary.draws, summary.total_rounds) == (
        wins[0], wins[1], draws, rounds,
    )


def test_simulate_parity_with_balance_simulate():
    """Parity z D2 `simulate_balance` (ta sama metodyka seedów/inicjatywy)."""
    fixture = load_battle_fixture(_FIXTURE_PATH)
    n, base = 8, 0
    kinds = ("random", "random")

    def factory(i: int):
        return [
            make_player(kinds[0], base + i),
            make_player(kinds[1], base + i + PLAYER_SEED_OFFSET),
        ]

    summary = LocalClient().simulate(
        fixture.rosters, factory, n=n, seed=base,
        terrain=fixture.terrain, objectives=fixture.objectives,
    )
    ref = simulate_balance(fixture, n=n, player_kinds=kinds, base_seed=base)
    assert (summary.wins_p0, summary.wins_p1, summary.draws) == (
        ref.wins_p0, ref.wins_p1, ref.draws,
    )
    assert summary.total_rounds == ref.total_rounds


def test_simulate_rejects_nonpositive_n():
    client = LocalClient()
    with pytest.raises(ValueError):
        client.simulate(_ROSTERS, _random_factory(0), n=0)


# --- single-step play -----------------------------------------------------


def test_create_battle_starts_round_one():
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=1, objectives=_OBJECTIVES)
    state = client.get_state(bid)
    assert state.round == 1
    assert state.active_player == 0
    assert {b.id for b in state.blobs} == {1, 2}


def test_create_battle_unique_ids():
    client = LocalClient()
    a = client.create_battle(_ROSTERS, objectives=_OBJECTIVES)
    b = client.create_battle(_ROSTERS, objectives=_OBJECTIVES)
    assert a != b


def test_take_action_matches_resolver():
    """`take_action` to wierne opakowanie `apply_activation` (ten sam stan + eventy)."""
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=7, objectives=_OBJECTIVES)
    new_state, events = client.take_action(bid, DefendAction(unit_id=1))

    ref_state = setup_phase(_ROSTERS, objectives=_OBJECTIVES, initiative_player=0)
    ref_state, deploy_events = deployment_round(ref_state, ())
    # Sekwencja kontynuuje monotonicznie od eventów rozstawienia (Ufortyfikowany
    # pkt 13.c) — tak jak `LocalClient.create_battle` (event-sourcing, B2 persist).
    ref = apply_activation(
        ref_state,
        DefendAction(unit_id=1),
        DeterministicDice(seed=7),
        sequence=len(deploy_events) + 1,
    )
    assert new_state == ref.state
    assert events == ref.events
    # Obrona → Ufortyfikowany (pkt 22.c).
    blob1 = next(b for b in new_state.blobs if b.id == 1)
    assert STATUS_UFORTYFIKOWANY in blob1.status_flags


def test_get_events_since():
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=7, objectives=_OBJECTIVES)
    _, events = client.take_action(bid, DefendAction(unit_id=1))
    all_events = client.get_events(bid)
    # all_events = eventy rozstawienia (Ufortyfikowany pkt 13.c — oddziały, które
    # nie ruszyły się w rozstawieniu) + eventy aktywacji. `take_action` zwraca
    # samą deltę aktywacji, więc jest sufiksem pełnego logu.
    assert len(all_events) > len(events)
    assert all_events[-len(events):] == events
    assert all(e.sequence > 0 for e in all_events)
    # since = ostatni sequence → pusto
    last_seq = max(e.sequence for e in all_events)
    assert client.get_events(bid, since=last_seq) == ()


def test_take_action_advances_active_player():
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=2, objectives=_OBJECTIVES)
    client.take_action(bid, DefendAction(unit_id=1))
    # Po aktywacji P0 inicjatywa przechodzi do P1 (pkt 8.a).
    assert client.get_state(bid).active_player == 1


def test_take_action_illegal_wrong_player():
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=1, objectives=_OBJECTIVES)
    # active_player=0; oddział 2 należy do gracza 1 → IllegalActionError (pkt 11.a).
    with pytest.raises(IllegalActionError):
        client.take_action(bid, DefendAction(unit_id=2))


def test_take_action_illegal_already_activated():
    client = LocalClient()
    bid = client.create_battle(_ROSTERS, seed=1, objectives=_OBJECTIVES)
    client.take_action(bid, DefendAction(unit_id=1))  # P0 aktywował oddział 1
    # Inicjatywa u P1; P1 aktywuje oddział 2, inicjatywa wraca do P0.
    client.take_action(bid, DefendAction(unit_id=2))
    # Oddział 1 już Aktywowany w tej rundzie → IllegalActionError (pkt 22.d.i).
    with pytest.raises(IllegalActionError):
        client.take_action(bid, ManeuverAction(unit_id=1, target_position=Position(12, 10)))


def test_unknown_battle_id_raises():
    client = LocalClient()
    with pytest.raises(UnknownBattleError):
        client.get_state(999)
    with pytest.raises(UnknownBattleError):
        client.take_action(999, DefendAction(unit_id=1))
    with pytest.raises(KeyError):  # UnknownBattleError dziedziczy po KeyError
        client.get_events(999)
