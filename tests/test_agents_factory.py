"""Testy fabryki botów (`agents.factory`) — SSOT konstrukcji `Player` z nazwy.

Kluczowe: fabryka jest importowalna z warstwy `app` (bez ładowania `scripts/`),
co odblokowuje konsumentów aplikacyjnych (router B4 `POST /battles/simulate`).
Tu pinujemy konstrukcję każdego `kind`, alias `claude`, błąd na nieznanym oraz
drift-guard `PLAYER_KINDS` względem rejestru.
"""

from __future__ import annotations

import pytest

from app.services.agents import (
    PLAYER_KINDS,
    PLAYER_SEED_OFFSET,
    make_player,
)
from app.services.agents import factory
from app.services.agents import registry as reg
from app.services.agents.base import Player


def test_factory_importable_from_app_package():
    # Enabler: app-level import działa bez ładowania scripts/balance_simulate.py.
    assert callable(make_player)
    assert make_player is factory.make_player


@pytest.mark.parametrize(
    "kind, cls_name",
    [
        ("random", "RandomPlayer"),
        ("greedy", "GreedyPlayer"),
        ("priority", "PriorityPlayer"),
        ("priority2", "PriorityV2Player"),
        ("priority3", "PriorityV3Player"),
        ("minimax", "MinimaxPlayer"),
        ("claude_v1", "ClaudeV1Player"),
        ("claude_v2", "ClaudeV2Player"),
        ("claude_v3", "ClaudeV3Player"),
    ],
)
def test_make_player_builds_each_kind(kind, cls_name):
    player = make_player(kind, seed=0)
    assert isinstance(player, Player)
    assert type(player).__name__ == cls_name


def test_claude_alias_builds_v1():
    # 'claude' to alias konstrukcyjny (nie kanoniczny kind rejestru).
    assert type(make_player("claude", 0)).__name__ == "ClaudeV1Player"
    assert "claude" not in reg.ALL_KINDS


def test_make_player_is_case_insensitive():
    assert type(make_player("PRIORITY", 0)).__name__ == "PriorityPlayer"


def test_unknown_kind_raises_value_error():
    with pytest.raises(ValueError):
        make_player("nie_ma_takiego_bota", 0)


def test_player_kinds_covers_registry_canonical_kinds():
    # Każdy kanoniczny kind rejestru jest budowalny (poza aliasami).
    for kind in reg.ALL_KINDS:
        assert kind in PLAYER_KINDS
        assert make_player(kind, 0) is not None
    # Każdy kanoniczny kind fabryki (bez aliasu 'claude') jest w rejestrze.
    for kind in PLAYER_KINDS:
        if kind == "claude":
            continue
        assert kind in reg.ALL_KINDS, f"{kind} brak w registry.BOT_SPECS"


def test_seed_offset_is_positive_int():
    assert isinstance(PLAYER_SEED_OFFSET, int)
    assert PLAYER_SEED_OFFSET > 0
