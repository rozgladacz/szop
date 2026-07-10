"""Testy rejestru botów (`agents.registry`) — SSOT klasyfikacji useful/reference + tiery.

Pilnuje: aktualnego oznaczenia (useful = priority/priority3/claude_v3), spójności tagów
status/koszt i działania zapytań po tagach (rozszerzalność). Drift-guard
rejestr↔fabryka żyje w `tests/test_agents_factory.py`.
"""

from __future__ import annotations

from app.services.agents import registry as reg


def test_useful_marking_current():
    assert set(reg.USEFUL_KINDS) == {"priority", "priority3", "claude_v3"}


def test_reference_is_complement_of_useful():
    assert set(reg.REFERENCE_KINDS) == set(reg.ALL_KINDS) - set(reg.USEFUL_KINDS)
    # useful i reference są rozłączne i pokrywają wszystko.
    assert not (set(reg.USEFUL_KINDS) & set(reg.REFERENCE_KINDS))
    assert set(reg.USEFUL_KINDS) | set(reg.REFERENCE_KINDS) == set(reg.ALL_KINDS)


def test_every_bot_has_status_and_cost_tag():
    for s in reg.BOT_SPECS:
        assert (reg.USEFUL in s.tags) ^ (reg.REFERENCE in s.tags), s.kind
        assert (reg.FAST in s.tags) ^ (reg.EXPENSIVE in s.tags), s.kind


def test_tag_query_and_levels():
    # Rozszerzalność: zapytanie po wielu tagach (AND) — gotowe na przyszłe poziomy.
    useful_fast = reg.bot_kinds(reg.USEFUL, reg.FAST)
    assert set(useful_fast) == {"priority", "priority3", "claude_v3"}
    # expensive bots są referencyjne (dziś nie ma useful-expensive — system to dopuszcza).
    assert set(reg.bot_kinds(reg.EXPENSIVE)) == {"minimax", "claude_v2"}
    assert reg.has_tag("claude_v3", reg.USEFUL)
    assert not reg.has_tag("greedy", reg.USEFUL)


def test_no_args_returns_all_in_order():
    assert reg.bot_kinds() == reg.ALL_KINDS


def test_spec_unknown_raises():
    import pytest

    with pytest.raises(KeyError):
        reg.spec("nie_ma_takiego")
