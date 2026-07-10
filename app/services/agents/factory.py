"""Fabryka botów — SSOT konstrukcji `Player` z nazwy (`kind`) + seeda.

Wydzielone z `scripts/balance_simulate.py` do warstwy `app`, żeby konsumenci
aplikacyjni (router B4 `POST /battles/simulate`, przyszłe UI „Play vs AI") mogli
budować boty bez importu ze `scripts/`. `registry.py` (klasyfikacja tagów) i ten
moduł (konstrukcja) to dwie strony tej samej SSOT: `tests/test_agents_factory.py`
+ `tests/test_agents_registry.py` pilnują, że każdy kanoniczny `kind` rejestru jest
konstruowalny tutaj i odwrotnie.

`PLAYER_KINDS` to lista **konstrukcyjna** (zawiera alias `claude` → `ClaudeV1Player`),
szersza niż `registry.ALL_KINDS` (kanoniczne kindy bez aliasów). `PLAYER_SEED_OFFSET`
to offset seeda decyzji drugiego gracza — bez niego dwa `RandomPlayer` na symetrycznej
planszy grają lustrzanie (finding F2, `HANDOFF.md` LOG 2026-06-11).
"""

from __future__ import annotations

from app.services.agents.base import Player
from app.services.agents.claude_v1_player import ClaudeV1Player
from app.services.agents.claude_v2_player import ClaudeV2Player
from app.services.agents.claude_v3_player import ClaudeV3Player
from app.services.agents.greedy_player import GreedyPlayer
from app.services.agents.minimax_player import MinimaxPlayer
from app.services.agents.priority_player import PriorityPlayer
from app.services.agents.priority_v2_player import PriorityV2Player
from app.services.agents.priority_v3_player import PriorityV3Player
from app.services.agents.random_player import RandomPlayer

#: Wszystkie budowalne `kind` (incl. alias konstrukcyjny `claude` → ClaudeV1Player).
#: Kanoniczne kindy (bez aliasów) muszą pokrywać się z `registry.ALL_KINDS` —
#: pilnuje `tests/test_agents_factory.py`.
PLAYER_KINDS = (
    "random",
    "greedy",
    "priority",
    "priority2",
    "priority3",
    "minimax",
    "claude",
    "claude_v1",
    "claude_v2",
    "claude_v3",
)

#: Offset seeda decyzji P1 względem P0. Bez niego oba `RandomPlayer` dostają
#: ten sam seed → na symetrycznej fixturze produkują **lustrzane** strumienie
#: decyzji, co daje systematyczny bias pozycyjny zamiast ~50/50 (finding F2,
#: REVIEW_2026-06-11). Duża liczba pierwsza: rozłączna od seeda kości kolejnych
#: gier (`base_seed + i`, i << OFFSET) i względnie pierwsza, więc strumienie
#: P0/P1 się nie pokrywają. Seed bazowy nadal w pełni determinuje przebieg.
PLAYER_SEED_OFFSET = 1_000_003


def make_player(kind: str, seed: int) -> Player:
    """Buduje gracza z nazwy. `greedy`/`priority` ignorują seed (deterministyczne)."""
    kind = kind.lower()
    if kind == "random":
        return RandomPlayer(seed=seed)
    if kind == "greedy":
        return GreedyPlayer()
    if kind == "priority":
        return PriorityPlayer()
    if kind == "priority2":
        return PriorityV2Player()
    if kind == "priority3":
        return PriorityV3Player()
    if kind == "minimax":
        return MinimaxPlayer(seed=seed)
    if kind in ("claude", "claude_v1"):
        return ClaudeV1Player()
    if kind == "claude_v2":
        return ClaudeV2Player(seed=seed)
    if kind == "claude_v3":
        return ClaudeV3Player()
    raise ValueError(f"Nieznany typ gracza: {kind!r} (oczekiwano {PLAYER_KINDS})")
