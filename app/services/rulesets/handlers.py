"""Cost handlers — replikują 6 gałęzi dispatch z `ability_cost_components_from_name`.

Strumień A, Faza A2.4b. Łączy:
- `cost_functions.py` (DSL prymitywy: scale_by_tou, weapon_cost_yaml, ...)
- `dispatcher.py` (passive_cost_dsl, registry DSL fn)
- `models.py:AbilityCosts` (YAML recipes z `ability_costs.yaml`)

w jednolity dispatcher `ability_cost_components_yaml(...)` zwracający
`AbilityCostComponents(base, weapon_delta)` — wierna replika
`abilities.ability_cost_components_from_name` z oracle.

**Inwariant czystości**: ten moduł NIE importuje z `app/services/costs/_engine`
ani z `app/services/costs/abilities`. Importuje tylko universal-string utils
z `costs/primitives` i własne moduły rulesets/*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..costs.primitives import (
    ability_identifier,
    extract_number,
    normalize_name,
)
from .cost_functions import (
    _mistrzostwo_aura_cost,
    _mistrzostwo_weapon_cost,
    aura_range_bonus,
    base_model_cost,
    order_bonus,
    parse_aura_value,
    t_eff,
    transport_multiplier,
    weapon_cost_yaml,
)
from .dispatcher import CostRecipe, passive_cost_dsl
from .models import AbilityCosts, HandlerSpec, RulesetManifest


# ---------------------------------------------------------------------------
# Lokalna kopia `_engine.AbilityCostComponents`. Trzymamy własną żeby zachować
# inwariant "rulesets/* nie importuje z costs/_engine". Shape musi być
# zgodny — `.base` i `.total` są jedynymi access patternami w call-sites.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbilityCostComponents:
    base: float
    weapon_delta: float = 0.0

    @property
    def total(self) -> float:
        return self.base + self.weapon_delta


# ---------------------------------------------------------------------------
# Helpers wspólne dla handlerów + dispatcher.
# ---------------------------------------------------------------------------


def _build_passive_recipes(ac: AbilityCosts) -> Mapping[str, CostRecipe]:
    """Zwraca `ac.passive_abilities` jako passive recipe map.

    **Post-review cleanup**: `CostRecipeSpec` (`models.py`) i dispatcher
    `CostRecipe` zostały zunifikowane — `passive_abilities` ma już shape
    `dict[str, CostRecipe]`, brak potrzeby konwersji. Wcześniej ten helper
    rebuildował 33 nowe `CostRecipe` instancje per call (A5 wymagało
    id-keyed cache by to zniwelować); teraz to no-op pass-through.

    Pozostaje jako publiczne API żeby caller (`_yaml_quote`, testy A2.5)
    nie musieli wiedzieć o detalu wewnętrznym.
    """
    return ac.passive_abilities


def _clear_passive_recipes_cache() -> None:
    """No-op po unifikacji `CostRecipeSpec`/`CostRecipe` (post-review).

    Zostawione jako stub dla wsteczna kompatybilność z dev workflow
    (`load_ruleset.cache_clear()` + ten helper). Bezpieczne do usunięcia
    gdy nikt zewnętrznie nie wywołuje.
    """
    return None


def _ability_identifier_set(abilities: Sequence[str]) -> set[str]:
    result: set[str] = set()
    for ability in abilities:
        ident = ability_identifier(ability)
        if ident:
            result.add(ident)
    return result


# ---------------------------------------------------------------------------
# Handler context — niezmienna struktura przekazywana do każdego handlera.
# Wszystkie pola pre-computed raz w `ability_cost_components_yaml` żeby uniknąć
# powtarzania `ability_identifier`/`normalize_name` w każdym handlerze.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HandlerCtx:
    manifest: RulesetManifest
    name: str
    value: str | None
    desc: str
    slug: str
    abilities: tuple[str, ...]
    ability_set: frozenset[str]
    toughness: float
    quality: int | None
    defense: int | None
    weapons: tuple[Any, ...]
    passive_recipes: Mapping[str, CostRecipe]
    slug_for_name: Callable[[str], str | None]


# ---------------------------------------------------------------------------
# 6 handlerów — wszystkie zwracają `base_result` (float). Każdy handler dostaje
# `HandlerSpec` z YAML, z którego czyta stałe gry przez `getattr` (HandlerSpec
# ma `extra="allow"`).
# ---------------------------------------------------------------------------


def _transport_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """desc.startswith("transport"): capacity × transport_multiplier."""
    capacity = extract_number(ctx.value or ctx.name)
    mult = transport_multiplier(ctx.manifest.tables, ctx.ability_set)
    return capacity * mult


def _open_transport_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """otwarty_transport / platforma_strzelecka: capacity × (multiplier + open_bonus)."""
    capacity = extract_number(ctx.value or ctx.name)
    mult = transport_multiplier(ctx.manifest.tables, ctx.ability_set)
    open_bonus = float(getattr(spec, "open_bonus", 0.25))
    return capacity * (mult + open_bonus)


def _aura_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """desc.startswith("aura"): passive_cost(target, T_eff(carrier, extra), aura=True).

    **faza-b-rules-resync 2026-06** (ADR-0048): zastąpiona stara formuła
    "× range_12_mult" przez T_eff additive `extra` (mirror oracle
    `_aura_eff_tou`). T_eff = clamp(4/3 × T_carrier, 8, 24); extra = 0
    (zasięg domyślny) lub `aura_range_bonus` (=8 dla zasięgu 12").
    T_carrier pobierane z `ctx.toughness` (legacy fixtures bez toughness
    używają default 6 → T_eff=8, kompatybilność z pre-resync).

    Special-case `value="mistrzostwo:<weapon_slug>"`: użyj `_mistrzostwo_aura_cost`
    × T_eff(carrier, extra) zamiast passive_cost.
    """
    tables = ctx.manifest.tables
    carrier = ctx.toughness if ctx.toughness else None

    value = ctx.value
    if value and value.startswith("mistrzostwo:"):
        parts = value.split("|", 1)
        w_slug = parts[0][len("mistrzostwo:") :].strip()
        aura_range = extract_number(parts[1]) if len(parts) == 2 else 6.0
        extra = aura_range_bonus(tables) if abs(aura_range - 12.0) < 1e-6 else 0.0
        return _mistrzostwo_aura_cost(tables, w_slug) * t_eff(tables, carrier, extra=extra)

    target_slug, aura_range = parse_aura_value(
        ctx.name, value, slug_for_name=ctx.slug_for_name
    )
    extra = aura_range_bonus(tables) if abs(aura_range - 12.0) < 1e-6 else 0.0
    return passive_cost_dsl(
        tables,
        ctx.passive_recipes,
        target_slug,
        tou=t_eff(tables, carrier, extra=extra),
        aura=True,
    )


def _mag_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """desc.startswith("mag"): base_multiplier × number."""
    base_mult = float(getattr(spec, "base_multiplier", 8.0))
    return base_mult * extract_number(ctx.value or ctx.name)


def _order_like_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """rozkaz/klatwa/oznaczenie: passive_cost(target, T_eff(carrier, +order_bonus), aura=True).

    **faza-b-rules-resync 2026-06** (ADR-0048): zastąpiona stała `inner_tou=10.0`
    przez T_eff additive `order_bonus` (=2). T_eff = clamp(4/3 × T_carrier, 8, 24) + 2.
    T_carrier z `ctx.toughness` (default 6 dla legacy → T_eff=10, kompatybilność).

    Special-case mistrzostwo: `_mistrzostwo_aura_cost(w_slug) × T_eff(carrier, +2)`.
    Mirror oracle (abilities.py:375-382): `ability_ref = value or desc.split(":")[1]`.
    """
    tables = ctx.manifest.tables
    carrier = ctx.toughness if ctx.toughness else None
    bonus = order_bonus(tables)

    ability_ref = ctx.value or (
        ctx.desc.split(":", 1)[1].strip() if ":" in ctx.desc else ""
    )
    if ability_ref.startswith("mistrzostwo:"):
        w_slug = ability_ref[len("mistrzostwo:") :].strip()
        return _mistrzostwo_aura_cost(tables, w_slug) * t_eff(tables, carrier, extra=bonus)

    target_slug = ctx.slug_for_name(ability_ref) or ability_identifier(ability_ref)
    return passive_cost_dsl(
        tables,
        ctx.passive_recipes,
        target_slug,
        tou=t_eff(tables, carrier, extra=bonus),
        aura=True,
    )


def _mistrzostwo_cost(ctx: _HandlerCtx, spec: HandlerSpec) -> float:
    """slug == "mistrzostwo": _mistrzostwo_weapon_cost dla wszystkich broni jednostki."""
    weapon_slug = ability_identifier(ctx.value or "")
    if not (ctx.weapons and weapon_slug and ctx.quality is not None):
        return 0.0
    return _mistrzostwo_weapon_cost(
        ctx.manifest.tables,
        weapon_slug,
        list(ctx.weapons),
        int(ctx.quality),
        list(ctx.abilities),
    )


_HANDLER_FNS: dict[str, Callable[[_HandlerCtx, HandlerSpec], float]] = {
    "transport_cost": _transport_cost,
    "open_transport_cost": _open_transport_cost,
    "aura_cost": _aura_cost,
    "mag_cost": _mag_cost,
    "order_like_cost": _order_like_cost,
    "mistrzostwo_cost": _mistrzostwo_cost,
}


def _match_handler(spec: HandlerSpec, desc: str, slug: str) -> bool:
    """Returns True if `spec.match` pasuje do (desc, slug). Mirror logiki
    if/elif z `ability_cost_components_from_name`."""
    m = spec.match
    if m.slug is not None and slug == m.slug:
        return True
    if m.prefix is not None and desc.startswith(m.prefix):
        return True
    if m.prefix_any:
        return any(desc.startswith(p) for p in m.prefix_any)
    return False


def _dispatch_base_result(
    ctx: _HandlerCtx,
    ac: AbilityCosts,
) -> tuple[float, bool]:
    """Returns (base_result, matched). `matched=False` ⇒ caller fallback to passive."""
    desc = ctx.desc
    slug = ctx.slug

    # 1) Handlers — kolejność z YAML (transport, open_transport, aura, mag, order_like, mistrzostwo).
    for spec in ac.handlers:
        if not _match_handler(spec, desc, slug):
            continue
        fn = _HANDLER_FNS.get(spec.fn_name)
        if fn is None:
            raise KeyError(
                f"Handler fn_name {spec.fn_name!r} not implemented; "
                f"registered: {sorted(_HANDLER_FNS)}"
            )
        return fn(ctx, spec), True

    # 2) fixed_by_desc — exact desc match (oracle: `desc == "przekaznik"`).
    fixed_d = ac.fixed_by_desc.get(desc)
    if fixed_d is not None:
        return float(fixed_d), True

    # 3) fixed_by_slug — slug match (oracle: `slug == "latanie"`).
    fixed_s = ac.fixed_by_slug.get(slug) if slug else None
    if fixed_s is not None:
        return float(fixed_s), True

    return 0.0, False


# ---------------------------------------------------------------------------
# Public entrypoint — replika `abilities.ability_cost_components_from_name`.
# ---------------------------------------------------------------------------


def ability_cost_components_yaml(
    manifest: RulesetManifest,
    name: str,
    value: str | None = None,
    unit_abilities: Sequence[str] | None = None,
    *,
    toughness: int | float | None = None,
    quality: int | None = None,
    defense: int | None = None,
    weapons: Sequence[Any] | None = None,
    slug_for_name: Callable[[str], str | None],
) -> AbilityCostComponents:
    """YAML-replika `ability_cost_components_from_name`.

    `slug_for_name` jest wstrzykiwane (oracle używa `ability_catalog.slug_for_name`).
    Trzymane jako parametr żeby `rulesets/*` nie miało zależności od
    `app/data/abilities`.
    """
    desc = normalize_name(name)
    if not desc:
        return AbilityCostComponents(base=0.0, weapon_delta=0.0)

    tables = manifest.tables
    ac = manifest.ability_costs
    passive_recipes = _build_passive_recipes(ac)
    abilities = list(unit_abilities or [])
    slug = ability_identifier(name)

    # --- 1) Build abilities-with / abilities-without (mirror oracle) ---
    def _contains_slug(items: Sequence[str], needle: str) -> bool:
        if not needle:
            return False
        return any(ability_identifier(el) == needle for el in items)

    if slug and not _contains_slug(abilities, slug):
        if value is not None and str(value).strip():
            abilities.append(f"{slug}({value})")
        else:
            abilities.append(slug)

    if slug:
        abilities_without: list[str] = []
        removed = False
        for item in abilities:
            if not removed and ability_identifier(item) == slug:
                removed = True
                continue
            abilities_without.append(item)
    else:
        abilities_without = list(abilities)

    ability_set = frozenset(_ability_identifier_set(abilities))

    # --- 2) row_delta dla MORALE/DEFENSE slugów ---
    morale_slugs = set(tables.morale_ability_multipliers)
    defense_slugs = set(tables.defense_ability_modifiers)

    def _passive_fn(name_arg, tou_arg, aura_arg, abs_arg):
        return passive_cost_dsl(
            tables, passive_recipes, name_arg, tou=tou_arg, aura=aura_arg, abilities=abs_arg,
        )

    row_delta: float | None = None
    if (
        slug
        and quality is not None
        and defense is not None
        and toughness is not None
        and abilities_without != abilities
        and (slug in morale_slugs or slug in defense_slugs)
    ):
        row_delta = base_model_cost(
            tables, int(quality), int(defense), int(float(toughness)),
            abilities, passive_cost_fn=_passive_fn,
        ) - base_model_cost(
            tables, int(quality), int(defense), int(float(toughness)),
            abilities_without, passive_cost_fn=_passive_fn,
        )

    # --- 3) weapon_delta ---
    weapon_delta = 0.0
    if weapons and slug and quality is not None and abilities_without != abilities:
        total_with = 0.0
        total_without = 0.0
        for wpn in weapons:
            total_with += weapon_cost_yaml(tables, wpn, int(quality), abilities)
            total_without += weapon_cost_yaml(tables, wpn, int(quality), abilities_without)
        weapon_delta = total_with - total_without

    # --- 4) Dispatch base_result (handlers → fixed_by_desc → fixed_by_slug) ---
    ctx = _HandlerCtx(
        manifest=manifest,
        name=name,
        value=value,
        desc=desc,
        slug=slug,
        abilities=tuple(unit_abilities or ()),
        ability_set=ability_set,
        toughness=float(toughness) if toughness is not None else 1.0,
        quality=quality,
        defense=defense,
        weapons=tuple(weapons or ()),
        passive_recipes=passive_recipes,
        slug_for_name=slug_for_name,
    )
    base_result, matched = _dispatch_base_result(ctx, ac)

    # --- 5) Fallback gdy nic nie zmatchowało — passive_cost_dsl ---
    if not matched:
        if slug and slug in ac.skip_in_default:
            base_result = 0.0
        else:
            # Oracle (abilities.py:395-404): jeśli definition.type == passive lub
            # slug bez definition, zwróć passive_cost(name, tou). Tu uproszczamy —
            # zawsze próbujemy passive_cost_dsl (brak recipe ⇒ 0.0 — równoważne
            # oracle "definition None && slug None ⇒ 0").
            tou_value = float(toughness) if toughness is not None else 1.0
            base_result = passive_cost_dsl(
                tables, passive_recipes, name, tou=tou_value, aura=False,
            )

    # --- 6) row_delta override ---
    if row_delta is not None:
        base_result = row_delta

    return AbilityCostComponents(base=float(base_result), weapon_delta=float(weapon_delta))


__all__ = [
    "AbilityCostComponents",
    "ability_cost_components_yaml",
]
