"""Rejestr botów + uniwersalne tagi — SSOT „jakie boty do czego".

Lista botów „użytecznych" (do testów/analiz) zmienia się w czasie, a poziomów będzie
więcej — dlatego klasyfikacja to **dowolny zbiór tagów** per bot (rozszerzalny bez
zmian API), a nie sztywne flagi. Zdefiniowane wymiary (każdy = jeden tag):

- **status:** ``useful`` (rekomendowany do testów/analiz) | ``reference`` (nieaktualny,
  trzymany tylko do porównań historycznych).
- **koszt:** ``fast`` (≲20× `priority`/decyzję) | ``expensive`` (≳20×).

Nowy poziom = po prostu nowy tag (np. bot „useful"+"expensive"); zapytania `kinds(...)`
działają bez zmian. `cost_ratio` (≈× `priority`) jest informacyjny (pomiar self-play,
patrz roadmap D4). Ten moduł to czyste dane — `make_player` (konstrukcja z seedem) żyje
w `scripts/balance_simulate.py`; spójność pilnuje `tests/test_agents_registry.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Kanoniczne tagi (stałe — unikają literówek; dowolny string też jest legalnym tagiem).
USEFUL = "useful"
REFERENCE = "reference"
FAST = "fast"
EXPENSIVE = "expensive"


@dataclass(frozen=True)
class BotSpec:
    """Metadane jednego bota: kanoniczny `kind`, zbiór `tags`, koszt, krótka nota."""

    kind: str
    tags: frozenset[str]
    cost_ratio: float  # ≈× priority/decyzję (informacyjnie; pomiar self-play)
    note: str = ""

    def has(self, *required: str) -> bool:
        """Czy spełnia WSZYSTKIE podane tagi (AND)."""
        return set(required) <= self.tags


# SSOT klasyfikacji. Kolejność: useful najpierw (czytelne w help/raportach).
BOT_SPECS: tuple[BotSpec, ...] = (
    BotSpec("priority", frozenset({USEFUL, FAST}), 1.0, "heurystyka 'strzel najbliższego + zajmij cele' — najmocniejszy stosunek siła/koszt"),
    BotSpec("priority3", frozenset({USEFUL, FAST}), 5.7, "drzewo decyzyjne 29-węzłowe; silny na napór"),
    BotSpec("claude_v3", frozenset({USEFUL, FAST}), 1.8, "szkielet priority + wybór celu dobij/koncentruj (ability-aware)"),
    BotSpec("random", frozenset({REFERENCE, FAST}), 1.0, "baseline losowy"),
    BotSpec("greedy", frozenset({REFERENCE, FAST}), 7.0, "depth-1 value-max (słaby vs priority)"),
    BotSpec("priority2", frozenset({REFERENCE, FAST}), 6.0, "rozbudowany priority; przegrywa z prostym"),
    BotSpec("claude_v1", frozenset({REFERENCE, FAST}), 8.6, "depth-1 value-max + gradient celów"),
    BotSpec("minimax", frozenset({REFERENCE, EXPENSIVE}), 185.0, "depth-2 maximin; nie bije priority"),
    BotSpec("claude_v2", frozenset({REFERENCE, EXPENSIVE}), 115.0, "depth-2 + model przeciwnika; nie bije priority"),
)

_BY_KIND: dict[str, BotSpec] = {s.kind: s for s in BOT_SPECS}

#: Wszystkie kanoniczne `kind` (bez aliasów konstrukcyjnych jak 'claude').
ALL_KINDS: tuple[str, ...] = tuple(s.kind for s in BOT_SPECS)


def spec(kind: str) -> BotSpec:
    """`BotSpec` dla `kind`. `KeyError` z czytelnym komunikatem gdy nieznany."""
    try:
        return _BY_KIND[kind]
    except KeyError:
        raise KeyError(f"nieznany bot {kind!r}; znane: {', '.join(ALL_KINDS)}") from None


def has_tag(kind: str, tag: str) -> bool:
    """Czy bot `kind` ma tag `tag`."""
    return tag in spec(kind).tags


def bot_kinds(*required: str) -> tuple[str, ...]:
    """Boty mające WSZYSTKIE podane tagi (AND), w kolejności `BOT_SPECS`.

    Bez argumentów → wszystkie. `bot_kinds(USEFUL)` = użyteczne; `bot_kinds(USEFUL,
    FAST)` = użyteczne-szybkie (gotowe na przyszłe poziomy bez zmian API).
    """
    return tuple(s.kind for s in BOT_SPECS if s.has(*required))


def all_tags() -> frozenset[str]:
    """Zbiór wszystkich użytych tagów (do walidacji/expandowania w CLI)."""
    return frozenset().union(*(s.tags for s in BOT_SPECS)) if BOT_SPECS else frozenset()


#: Skróty (pochodne — NIE duplikuj prawdy, licz z tagów).
USEFUL_KINDS: tuple[str, ...] = bot_kinds(USEFUL)
REFERENCE_KINDS: tuple[str, ...] = bot_kinds(REFERENCE)
