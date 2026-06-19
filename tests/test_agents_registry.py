"""Testy rejestru botów (`agents.registry`) — SSOT klasyfikacji useful/reference + tiery.

Pilnuje: aktualnego oznaczenia (useful = priority/priority3/claude_v3), spójności tagów
status/koszt, działania zapytań po tagach (rozszerzalność) ORAZ **drift-guard**: każdy
kanoniczny bot rejestru jest konstruowalny przez `balance_simulate.make_player` i odwrotnie.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

from app.services.agents import registry as reg

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_bsim():
    spec = importlib.util.spec_from_file_location("bsim_reg", _ROOT / "scripts" / "balance_simulate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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


def test_registry_matches_make_player():
    # Drift-guard: kanoniczne kindy rejestru = konstruowalne; każdy ma odpowiednik w
    # PLAYER_KINDS (poza aliasami konstrukcyjnymi jak 'claude').
    bsim = _load_bsim()
    for kind in reg.ALL_KINDS:
        player = bsim.make_player(kind, 0)
        assert player is not None
        assert kind in bsim.PLAYER_KINDS
    # Każdy kanoniczny kind z make_player (bez aliasów) jest w rejestrze.
    aliases = {"claude"}
    for kind in bsim.PLAYER_KINDS:
        if kind in aliases:
            continue
        assert kind in reg.ALL_KINDS, f"{kind} brak w registry.BOT_SPECS"
