"""Cost DSL dispatcher — fn_name (string) → callable, recipe → float.

Strumień A, Faza A2.2. Hardcoded registry (NIE eval/exec) — każda funkcja
musi być jawnie zarejestrowana, żeby YAML nie mógł zainjectować arbitralnego
kodu.

DSL ma trzy poziomy abstrakcji:

1. **Recipe** (`CostRecipe`): atomowe wywołanie `{fn: str, args: dict}`.
   Args są mergowane z runtime_args (`tou`, `aura`, ...) wstrzykiwanymi przez
   caller.

2. **Passive recipes map** (`Mapping[str, CostRecipe]`): słownik
   slug → recipe. Pochodzi z `ability_costs.yaml` (sekcja `passive_abilities`,
   A2.3). Konsumowane przez `passive_cost_dsl`.

3. **Higher-level handlers** (transport/aura/mistrzostwo/...): zostaną
   zaimplementowane w A2.4 jako gałęzie w `_yaml_quote`, używając funkcji
   z `cost_functions.py` jako prymitywów.

Inwariant czystości (CRITICAL): ten moduł i `cost_functions.py` NIE importują
z `app/services/costs/_engine` ani z `app/services/costs/abilities` — to są
oracle SSOT, których YAML backend musi być niezależną repliką. Wolno importować
universal-string utils z `costs/primitives` (parsery wejścia, nie tabele kosztów).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ..costs.primitives import ability_identifier, normalize_name
from . import cost_functions
from .models import CostRecipeSpec, RulesetTables

# Atomowa receptura kosztu: `{fn: <name>, args: <map>}`. Walidowana raz
# przy ładowaniu `ability_costs.yaml` (A2.3). Alias na `CostRecipeSpec`
# z `models.py` — wcześniej była tu duplikatowa klasa, eliminacja
# rebuild-loopa per quote (A5 cleanup, post-review).
CostRecipe = CostRecipeSpec


# ---------------------------------------------------------------------------
# Registry — fn_name → (callable, needs_tables).
#
# `needs_tables=True` ⇒ dispatcher wstrzykuje `tables` jako pierwszy argument
# pozycyjny. False ⇒ funkcja jest czysto numeryczna (np. `scale_by_tou`).
#
# Dodawanie nowych funkcji: rozszerz mapę i upewnij się że sygnatura zgadza
# się z wywołaniem (kwargs). Brak entry ⇒ KeyError → fail-fast.
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, tuple[Callable[..., float], bool]] = {
    "scale_by_tou": (cost_functions.scale_by_tou, False),
    "morale_modifier": (cost_functions.morale_modifier, False),
    "range_multiplier": (cost_functions.range_multiplier, True),
    "ap_modifier": (cost_functions.ap_modifier, True),
    "blast_cost": (cost_functions.blast_cost, True),
    "deadly_cost": (cost_functions.deadly_cost, True),
    "defense_modifier": (cost_functions.defense_modifier, True),
    "toughness_modifier": (cost_functions.toughness_modifier, True),
    "transport_multiplier": (cost_functions.transport_multiplier, True),
}


def registered_functions() -> tuple[str, ...]:
    """Lista zarejestrowanych nazw DSL — dla introspekcji testów i ADR."""
    return tuple(sorted(_REGISTRY))


def resolve_fn(name: str) -> Callable[..., float]:
    """Zwraca callable dla `fn_name`. Rzuca `KeyError` gdy brak rejestracji."""
    entry = _REGISTRY.get(name)
    if entry is None:
        raise KeyError(
            f"Unknown cost function {name!r}; registered: {registered_functions()}"
        )
    return entry[0]


def call_recipe(
    tables: RulesetTables, recipe: CostRecipe, /, **runtime_args: Any
) -> float:
    """Rozwiązuje `recipe.fn` przez registry i woła funkcję z mergem args.

    `runtime_args` mają pierwszeństwo nad `recipe.args` (caller wie więcej
    o kontekście). `tables` wstrzykiwane tylko dla funkcji z `needs_tables=True`.
    """
    fn_name = recipe.fn
    entry = _REGISTRY.get(fn_name)
    if entry is None:
        raise KeyError(
            f"Unknown cost function {fn_name!r}; registered: {registered_functions()}"
        )
    fn, needs_tables = entry
    merged: dict[str, Any] = {**recipe.args, **runtime_args}
    if needs_tables:
        return float(fn(tables, **merged))
    return float(fn(**merged))


# ---------------------------------------------------------------------------
# passive_cost_dsl — YAML-replika `abilities.passive_cost` z oracle.
#
# Klucz różnicy względem oracle: nie ma 30+ hard-coded gałęzi `if slug == X:`.
# Wszystkie pary slug→base są w `passive_recipes` (z `ability_costs.yaml`).
# Funkcja jest pure — przyjmuje recipes jako argument, więc testy mogą
# wstrzyknąć dowolny zestaw recipes (parytet vs oracle weryfikowany w A2.5/A3).
#
# Sygnatura (`name, tou, aura, abilities`) zachowana dla zgodności z
# wstrzyknięciem do `base_model_cost(passive_cost_fn=...)` w cost_functions.py.
# ---------------------------------------------------------------------------


def passive_cost_dsl(
    tables: RulesetTables,
    passive_recipes: Mapping[str, CostRecipe],
    ability_name: str,
    tou: float = 1.0,
    aura: bool = False,
    abilities: Sequence[str] | None = None,
) -> float:
    """Koszt passive ability wg recipe z `ability_costs.yaml`.

    Returns 0.0 gdy:
    - puste/None `ability_name`
    - slug nie ma wpisu w `passive_recipes`
    - recipe match-uje ale `aura_required=True` i `aura=False` (delegowane
      do `scale_by_tou`)
    """
    del abilities  # passive_cost w oracle przyjmuje, ale go nie używa
    slug = ability_identifier(ability_name)
    norm = normalize_name(ability_name)
    key = slug or norm
    if not key:
        return 0.0
    recipe = passive_recipes.get(slug)
    if recipe is None:
        return 0.0
    return call_recipe(tables, recipe, tou=float(tou), aura=bool(aura))


__all__ = [
    "CostRecipe",
    "call_recipe",
    "passive_cost_dsl",
    "registered_functions",
    "resolve_fn",
]
