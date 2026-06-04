"""Cost DSL — funkcje czyste budujące koszt z `RulesetTables`.

Strumień A, Faza A2. Mirror logiki proceduralnej z:
- `app/services/costs/primitives.py`  (modyfikatory bazowe)
- `app/services/costs/abilities.py`   (passive_cost, parse_aura_value, mistrzostwo)
- `app/services/costs/weapons.py`     (_weapon_cost)

**Inwarianty**:
1. Każda funkcja jest pure — read-only nad `RulesetTables`/argumentami, brak globalnego stanu.
2. Brak importów z `app/services/costs/_engine` (bo to oracle SSOT, którego YAML backend
   ma być niezależną repliką). Wolno importować `primitives.py` tylko po universal-string
   helpers (`ability_identifier`, `normalize_name`, `extract_number`, `split_traits`,
   `normalize_range_value`) — to parsery wejścia, nie tabele kosztów.
3. Dispatch via hardcoded mapping (patrz `dispatcher.py`) — NIE `eval`/`exec`.
4. Format DSL: każda funkcja przyjmuje `tables: RulesetTables` (lub None gdy nie używa)
   plus argumenty domenowe. Caller (dispatcher) wstrzykuje `tables` przed wywołaniem.

Parytet z oracle wymuszony w `tests/test_cost_functions.py` (A2.5)
i `tests/test_ruleset_parity.py` (A3.1).
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from ..costs.primitives import (
    ability_identifier,
    extract_number,
    lookup_with_nearest,
    normalize_name,
    normalize_range_value,
    split_traits,
)
from .models import RulesetTables


# Lookup nearest-key z dict — primitives.lookup_with_nearest jest na allow-list
# importowej (universal-string utils, nie tabele kosztów). Float-coercion
# zostawiamy callerom; primitives zwraca już to co siedzi w table.


def _weapon_attr(weapon, base: str, default):
    """Zwraca `weapon.effective_<base>` jeśli ustawione, inaczej `weapon.<base>`.

    Duck-typed reader replikujący wzorzec z oracle (`weapons._weapon_cost`):
    `models.Weapon` ma `effective_X` properties cache'ujące derived values,
    SimpleNamespace fixtures w testach też je dostarczają. Wzorzec
    `getattr(w, "effective_X", None) or getattr(w, "X", default)` powtarza
    się w 3 miejscach — extract.

    UWAGA: zachowujemy semantykę `if X is not None` dla numerycznych pól
    (attacks, ap) — `or` byłoby błędne dla `effective_attacks=0` lub
    `effective_ap=0`. Per-typ wybór dispatch by caller (range/tags używają
    `or`, attacks/ap używają `is not None`).
    """
    effective = getattr(weapon, f"effective_{base}", None)
    if effective is not None:
        return effective
    return getattr(weapon, base, default)


def _weapon_str_attr(weapon, base: str, default: str = "") -> str:
    """Wariant dla pól tekstowych (range, tags) — `effective` może być pustym
    stringiem (falsy), wtedy `or` fallback'uje na surowy atrybut. Dokładnie
    mirror oracle pattern."""
    return getattr(weapon, f"effective_{base}", None) or getattr(weapon, base, default)


# ---------------------------------------------------------------------------
# 1. range_multiplier — lookup_with_nearest nad tables.range_table.
# ---------------------------------------------------------------------------


def range_multiplier(tables: RulesetTables, range_value: int) -> float:
    return lookup_with_nearest(tables.range_table, int(range_value))


# ---------------------------------------------------------------------------
# 2. ap_modifier — lookup nad tables.ap_base.
# ---------------------------------------------------------------------------


def ap_modifier(tables: RulesetTables, ap_value: int) -> float:
    return lookup_with_nearest(tables.ap_base, int(ap_value))


# ---------------------------------------------------------------------------
# 3. blast_cost — mnożnik dla cechy "rozprysk(N)" / "blast(N)".
# Procedural używa BLAST_MULTIPLIER[N] gdy N w mapie, inaczej brak modyfikacji
# (continue w pętli traits). Tu zwracamy mnożnik (1.0 gdy brak), caller mnoży.
# ---------------------------------------------------------------------------


def blast_cost(tables: RulesetTables, value: int) -> float:
    return float(tables.blast_multiplier.get(int(value), 1.0))


# ---------------------------------------------------------------------------
# 4. deadly_cost — analogicznie dla "zabojczy(N)" / "deadly(N)".
# ---------------------------------------------------------------------------


def deadly_cost(tables: RulesetTables, value: int) -> float:
    return float(tables.deadly_multiplier.get(int(value), 1.0))


# ---------------------------------------------------------------------------
# 5. morale_modifier — czysta formuła quality-based, bez tabel.
# Mirror `primitives.morale_modifier`.
# ---------------------------------------------------------------------------


def morale_modifier(quality: int, penalty_multiplier: float = 1.0) -> float:
    q = max(2, min(6, int(quality)))
    penalty = max(float(penalty_multiplier), 0.0)
    return 1.3 - (q - 1) / 10.0 * penalty


# ---------------------------------------------------------------------------
# 6. defense_modifier — wartość bazowa z tables.defense_base_values plus
# delty z tables.defense_ability_modifiers per matching ability slug.
# Mirror `primitives.defense_modifier`.
# ---------------------------------------------------------------------------


def defense_modifier(
    tables: RulesetTables,
    defense: int,
    ability_slugs: Iterable[str] | None = None,
) -> float:
    d = max(2, min(6, int(defense)))
    value = float(tables.defense_base_values[d])
    if ability_slugs:
        for slug in ability_slugs:
            modifier_map = tables.defense_ability_modifiers.get(slug)
            if modifier_map:
                value += float(modifier_map.get(d, 0.0))
    return value


# ---------------------------------------------------------------------------
# 7. toughness_modifier — tables.toughness_special dla {1..4}, inaczej
# max(1, (5*tou)//3 - 2). Mirror `primitives.toughness_modifier`.
# ---------------------------------------------------------------------------


def toughness_modifier(tables: RulesetTables, toughness: int) -> float:
    t = max(int(toughness), 1)
    if t in tables.toughness_special:
        return float(tables.toughness_special[t])
    return float(max(1.0, (5 * t) // 3 - 2))


# ---------------------------------------------------------------------------
# 8. transport_multiplier — iteracja po tables.transport_multipliers, ostatnie
# matching trafienie wygrywa (oracle też używa pętli `for options, value in ...:
# if ability_set & options: multiplier = value` — bez breaku).
# ---------------------------------------------------------------------------


def transport_multiplier(
    tables: RulesetTables, ability_set: Iterable[str]
) -> float:
    ident_set = {a for a in ability_set if a}
    multiplier = 1.0
    for rule in tables.transport_multipliers:
        if ident_set & rule.traits_set:
            multiplier = float(rule.multiplier)
            break
    return multiplier


# ---------------------------------------------------------------------------
# 9. scale_by_tou — uniwersalny pattern z `abilities.passive_cost`:
# większość gałęzi to "return BASE * tou", część "return BASE * (tou if aura else 1)".
# DSL recipe: {fn: scale_by_tou, args: {base: X, aura_required: bool,
# aura_alt_base: float, only_in_aura: bool}}.
# ---------------------------------------------------------------------------


def scale_by_tou(
    tou: float,
    base: float,
    *,
    aura: bool = False,
    aura_required: bool = False,
    aura_alt_base: float | None = None,
    scale: bool = True,
    aura_scale: bool | None = None,
) -> float:
    """Skala bazowego kosztu passive ability przez toughness.

    - `aura_required=True`: gdy `aura=False` zwraca 0.0 (np. "bastion" liczy się
      tylko w aurze).
    - `aura_alt_base` (np. dla "instynkt"): podstawa ma inny znak w trybie aury
      vs domyślnym. Gdy podane, używamy `aura_alt_base` gdy `aura=True`.
    - `scale=False`: zwraca `base` bez mnożenia (np. "bastion" w aurze: 3.0).
    - `aura_scale`: gdy podane, NADPISUJE `scale` ale tylko gdy `aura=True`.
      Dla `dywersant`: `{base: 1.25, scale: false, aura_scale: true}` →
      aura=False zwraca 1.25 (bez mnożenia), aura=True zwraca 1.25*tou.
    """
    if aura_required and not aura:
        return 0.0
    chosen = base if (aura_alt_base is None or not aura) else aura_alt_base
    effective_scale = scale if (not aura or aura_scale is None) else aura_scale
    if not effective_scale:
        return float(chosen)
    return float(chosen) * float(tou)


# ---------------------------------------------------------------------------
# 10. t_eff — efektywna wytrzymałość nosiciela dla wyceny Aury/Rozkazu/Klątwy/
# Oznaczenia (SZOP_Zdolnosci.md, faza-b-rules-resync 2026-06, ADR-0048).
#
# Czyta parametry formuły z `tables.aura_order_formula` (R1). Backward compat:
# gdy tables nie ma sekcji (legacy YAML), używamy defaultów odpowiadających
# zachowaniu pre-resync (T_eff = 8 dla aury, 10 dla rozkazu — implementowane
# w callerach przez `extra=0/2`).
#
# Mirror oracle `app/services/costs/abilities.py:_aura_eff_tou`:
#   _aura_eff_tou(extra) = clamp(4/3 * carrier_tou, 8, 24) + extra
# T_carrier domyślnie 6.0 (gdy toughness=None) — daje 4/3*6=8 zachowując
# kompatybilność z legacy "inner_tou=8.0" przed driftcie.
# ---------------------------------------------------------------------------


def t_eff(
    tables: RulesetTables,
    carrier_tou: float | None = None,
    *,
    extra: float = 0.0,
) -> float:
    """Efektywna wytrzymałość nosiciela aury/rozkazu + opcjonalny bonus.

    - `tables.aura_order_formula` (NEW R1) dostarcza factor/clamp; backward
      compat: gdy None użyj 4/3, 8, 24.
    - `carrier_tou=None` → 6.0 (default, mirror oracle linia 313).
    - `extra` to bonus dodawany po clamp: 0 = aura zasięg domyślny,
      `aura_range_bonus` (=8) = aura zasięg 12", `order_bonus` (=2) = Rozkaz/
      Klątwa/Oznaczenie.

    Patrz `handlers._aura_cost` / `handlers._order_like_cost`.
    """
    f = tables.aura_order_formula
    factor = f.t_eff_factor if f else (4.0 / 3.0)
    cmin = f.t_eff_clamp_min if f else 8
    cmax = f.t_eff_clamp_max if f else 24

    tou = 6.0 if carrier_tou is None else float(carrier_tou)
    scaled = factor * tou
    clamped = max(float(cmin), min(float(cmax), scaled))
    return clamped + float(extra)


def aura_range_bonus(tables: RulesetTables) -> float:
    """`tables.aura_order_formula.aura_range_bonus` lub default 8.0 (legacy)."""
    f = tables.aura_order_formula
    return float(f.aura_range_bonus) if f else 8.0


def order_bonus(tables: RulesetTables) -> float:
    """`tables.aura_order_formula.order_bonus` lub default 2.0 (legacy)."""
    f = tables.aura_order_formula
    return float(f.order_bonus) if f else 2.0


# ---------------------------------------------------------------------------
# 10. base_model_cost — replikuje `abilities.base_model_cost`.
# Iteruje abilities, dzieli na (morale-multipliers, defense-modifiers, passive).
# `passive_cost_fn` to callable wstrzykiwany przez dispatcher: zwraca koszt passive
# dla pojedynczego ability — pozwala uniknąć cyklicznego importu DSL ↔ recipes.
# ---------------------------------------------------------------------------

# Domyślne sloty defense modifiers (klucze z `tables.defense_ability_modifiers`).
# DSL nie zna ich z góry — czyta z tables.


def base_model_cost(
    tables: RulesetTables,
    quality: int,
    defense: int,
    toughness: int,
    abilities: Sequence[str] | None,
    *,
    passive_cost_fn,
) -> float:
    """Pełen mirror `abilities.base_model_cost` z procedural.

    `passive_cost_fn(name, tou, aura=False, abilities)` — wstrzykiwane,
    odpowiada `abilities.passive_cost` z oracle (lub jego YAML repliki).
    """
    ability_list = list(abilities or [])
    morale_multiplier = 1.0
    applied_morale: set[str] = set()
    defense_slugs: list[str] = []
    passive_total = 0.0
    defense_ability_slugs = set(tables.defense_ability_modifiers)

    for ability in ability_list:
        slug = ability_identifier(ability)
        norm = slug or normalize_name(ability)
        if not norm:
            continue
        if slug in tables.morale_ability_multipliers and slug not in applied_morale:
            morale_multiplier *= float(tables.morale_ability_multipliers[slug])
            applied_morale.add(slug)
            continue
        if slug in defense_ability_slugs:
            defense_slugs.append(slug)
            continue
        passive_total += float(
            passive_cost_fn(ability, float(toughness), False, ability_list)
        )

    morale_value = morale_modifier(int(quality), morale_multiplier)
    defense_value = defense_modifier(tables, int(defense), defense_slugs)
    toughness_value = toughness_modifier(tables, int(toughness))
    cost = float(tables.base_cost_factor) * morale_value * defense_value * toughness_value
    cost += passive_total
    return cost


# ---------------------------------------------------------------------------
# 11. parse_aura_value — czyste parsowanie "aura(X): slug" lub "aura: slug |
# range".  Mirror `abilities._parse_aura_value`.  `slug_for_name` wstrzykiwane,
# bo zależność od ability_catalog jest poza scope DSL.
# ---------------------------------------------------------------------------


def parse_aura_value(
    name: str,
    value: str | None,
    *,
    slug_for_name,
) -> tuple[str, float]:
    aura_range = 6.0
    ability_ref = ""
    if value:
        parts = value.split("|", 1)
        if len(parts) == 2:
            ability_ref = parts[0].strip()
            aura_range = extract_number(parts[1]) or 6.0
        else:
            ability_ref = value.strip()
    if not ability_ref:
        desc = normalize_name(name)
        if desc.startswith("aura("):
            match = re.match(r"aura\(([^)]+)\)\s*[:\-–]?\s*(.*)", desc)
            if match:
                aura_range = extract_number(match.group(1)) or 6.0
                raw_ref = match.group(2)
                ability_ref = raw_ref.lstrip(": -–").strip().rstrip(") ")
                ability_ref = ability_ref.strip()
        elif desc.startswith("aura:"):
            ability_ref = desc.split(":", 1)[1].strip()
        else:
            ability_ref = desc[4:].lstrip(": -–").strip()
    slug = slug_for_name(ability_ref) or ability_identifier(ability_ref)
    return slug, aura_range


# ---------------------------------------------------------------------------
# Prywatny helper: pełna replika `weapons._weapon_cost`.  Używany przez
# `_mistrzostwo_aura_cost` i `_mistrzostwo_weapon_cost`.  Eksportowany jako
# `_weapon_cost_yaml` żeby uniknąć kolizji z `costs.weapons._weapon_cost`.
# ---------------------------------------------------------------------------


def _weapon_cost_yaml(
    tables: RulesetTables,
    quality: int,
    range_value: int,
    attacks: float,
    ap: int,
    weapon_traits: Sequence[str],
    unit_traits: Sequence[str],
    *,
    allow_assault_extra: bool = True,
) -> float:
    """Cost broni — mirror `weapons._weapon_cost`. Recursion przez assault."""
    chance = 7.0
    a = float(attacks if attacks is not None else 1.0)
    a = max(a, 0.0)
    base_ap = int(ap or 0)
    range_mod = range_multiplier(tables, range_value)
    ap_mod = ap_modifier(tables, base_ap)
    mult = 1.0
    q = int(quality)
    range_bonus = 0.0
    range_penalty = 0.0

    unit_set: set[str] = set()
    for trait in unit_traits:
        identifier = ability_identifier(trait)
        if identifier:
            unit_set.add(identifier)
    melee = range_value == 0

    waagh_penalty = 0.0
    if "waagh" in unit_set:
        waagh_penalty = lookup_with_nearest(tables.waagh_ap_modifier, base_ap)

    if melee and "furia" in unit_set:
        chance += 0.65
    if "przygotowanie" in unit_set and "samolot" not in unit_set:
        chance += 0.2 if "niestrudzony" in unit_set else 0.65
    if "niestrudzony" in unit_set and "samolot" not in unit_set:
        mult *= 1.5
    if "straznik" in unit_set and not melee:
        mult *= 1.7
    if "bastion" in unit_set and melee:
        mult *= 1.2
    if "dywersant" in unit_set:
        mult *= 1.2
    if "szpica" in unit_set:
        chance += 0.5
    if "ostrozny" in unit_set:
        chance += lookup_with_nearest(tables.cautious_hit_bonus, range_value)
    if not melee and "wojownik" in unit_set:
        mult *= 0.5
    if melee and "strzelec" in unit_set:
        mult *= 0.5
    if not melee and "zle_strzela" in unit_set:
        q = 5
    if not melee and "dobrze_strzela" in unit_set:
        q = 4
    if "zemsta" in unit_set:
        mult *= 1.2
    if "rezerwa" in unit_set:
        mult *= 0.6
    if "zasadzka" in unit_set and not melee:
        mult *= 0.6
    if "odwody" in unit_set and not (unit_set & {"rezerwa", "zwiadowca", "zasadzka"}):
        mult *= 0.75

    assault = False
    overcharge = False
    finezja = False
    has_namierzanie = False

    for trait in weapon_traits:
        norm = normalize_name(trait)
        if not norm:
            continue

        if norm.startswith("rozprysk") or norm.startswith("blast"):
            value = int(round(extract_number(trait)))
            if value in tables.blast_multiplier:
                mult *= float(tables.blast_multiplier[value])
                continue

        if norm.startswith("zabojczy") or norm.startswith("deadly"):
            value = int(round(extract_number(trait)))
            if value in tables.deadly_multiplier:
                mult *= float(tables.deadly_multiplier[value])
                continue

        if norm in {
            "seria",
            "rozrywajacy",
            "rozrywajaca",
            "rozrwyajaca",
            "podwojny",
            "podwojna",
            "rending",
        }:
            chance += 1.0
        elif norm in {"lanca", "lance"}:
            chance += 0.65
        elif norm in {"namierzanie", "lock on"}:
            has_namierzanie = True
            mult *= 1.1
        elif norm in {"impet", "impact"}:
            chance += 0.65
            ap_mod += lookup_with_nearest(tables.ap_lance, base_ap)
        elif norm in {"przebijajaca", "przebijajacy", "penetrating"}:
            mult *= lookup_with_nearest(tables.penetrating_multiplier, base_ap)
        elif norm in {"finezja"}:
            finezja = True
        elif norm in {"brutalny", "brutalna", "brutal"}:
            ap_mod += lookup_with_nearest(tables.brutalny_ap_cost, base_ap)
        elif norm in {
            "zguba",
            "bez regeneracji",
            "bez regegenracji",
            "no regen",
            "no regeneration",
        }:
            mult *= 1.05
        elif norm in {"dezintegracja", "disintegration"}:
            chance += 2.9 / ap_mod - 1
        elif norm in {"niebezposredni", "indirect"}:
            mult *= 1.2
        elif norm in {"zuzywalny", "limited"}:
            mult *= 0.4
        elif norm in {"precyzyjny", "precise"}:
            mult *= 1.5
        elif norm in {"niezawodny", "niezawodna", "reliable"}:
            q = 2
        elif norm in {"szturmowy", "szturmowa", "assault"}:
            assault = True
        elif norm in {"artyleria", "artillery"}:
            range_bonus += lookup_with_nearest(tables.artillery_range_bonus, range_value)
        elif norm in {"nieporeczny", "unwieldy"}:
            range_penalty += lookup_with_nearest(tables.unwieldy_range_penalty, range_value)
        elif norm in {"podkrecenie", "overcharge", "overclock"}:
            overcharge = True
        elif norm in {"burzaca"}:
            mult *= 1.5
        elif norm in {"unik", "przewidywalny"}:
            mult *= 1.2
        elif norm in {"sterowany"}:
            mult *= 1.5
        elif melee and norm in {"porazenie"}:
            mult *= 1.1

    if waagh_penalty:
        ap_mod = max(ap_mod - waagh_penalty, 0.0)

    if not has_namierzanie:
        chance -= 0.6 if not melee else 0.3
    range_mod = max(range_mod + range_bonus - range_penalty, 0.0)
    chance = max(chance - q, 0.9)
    if finezja:
        chance += ((7 - q) * (6 - q) ** 2) / 50.0
    cost = a * 2.0 * range_mod * chance * ap_mod * mult

    if overcharge and (not assault or range_value != 0):
        cost *= float(tables.overcharge_multiplier)

    if assault and allow_assault_extra and range_value != 0:
        melee_part = _weapon_cost_yaml(
            tables,
            quality,
            0,
            attacks,
            base_ap,
            weapon_traits,
            unit_traits,
            allow_assault_extra=False,
        )
        cost += melee_part

    return cost


# ---------------------------------------------------------------------------
# 12. _mistrzostwo_aura_cost — mirror `abilities._mistrzostwo_aura_cost`.
# Quality fixed = 4, dwa probe-shoty (24/1/2 melee=0 i 0/2/2 melee=1).
# ---------------------------------------------------------------------------


def _mistrzostwo_aura_cost(
    tables: RulesetTables,
    weapon_slug: str,
) -> float:
    q = 4
    delta1 = abs(
        _weapon_cost_yaml(tables, q, 24, 1, 2, [weapon_slug], [])
        - _weapon_cost_yaml(tables, q, 24, 1, 2, [], [])
    )
    delta2 = abs(
        _weapon_cost_yaml(tables, q, 0, 2, 2, [weapon_slug], [])
        - _weapon_cost_yaml(tables, q, 0, 2, 2, [], [])
    )
    return max(delta1, delta2)


# ---------------------------------------------------------------------------
# 13. _mistrzostwo_weapon_cost — mirror `abilities._mistrzostwo_weapon_cost`.
# `WeaponLike` to dowolny obiekt z atrybutami `effective_range`/`range`,
# `effective_tags`/`tags`, `effective_attacks`/`attacks`, `effective_ap`/`ap`.
# Procedural przyjmuje `models.Weapon`; my przyjmujemy ten sam (duck typing).
# ---------------------------------------------------------------------------


def _mistrzostwo_weapon_cost(
    tables: RulesetTables,
    weapon_slug: str,
    weapons,
    quality: int,
    unit_traits: Sequence[str],
) -> float:
    total = 0.0
    for wpn in weapons:
        range_v = normalize_range_value(_weapon_str_attr(wpn, "range"))
        existing = list(split_traits(_weapon_str_attr(wpn, "tags")))
        attacks = float(_weapon_attr(wpn, "attacks", 1.0))
        ap = int(_weapon_attr(wpn, "ap", 0))
        if weapon_slug in {normalize_name(t) for t in existing}:
            continue
        cost_without = _weapon_cost_yaml(
            tables, quality, range_v, attacks, ap, existing, list(unit_traits)
        )
        cost_with = _weapon_cost_yaml(
            tables,
            quality,
            range_v,
            attacks,
            ap,
            existing + [weapon_slug],
            list(unit_traits),
        )
        total += abs(cost_with - cost_without)
    return total


# ---------------------------------------------------------------------------
# Wrappery wokół `_weapon_cost_yaml` — mirror `weapons.weapon_cost_components`
# i `weapons.weapon_cost`. Używane przez `handlers.py` (A2.4b) do liczenia
# `weapon_delta` w ability_cost_components, i przez `quote_yaml.py` (A2.4c)
# do agregacji weapon buckets.
# ---------------------------------------------------------------------------


def weapon_cost_components_yaml(
    tables: RulesetTables,
    weapon,
    unit_quality: int,
    unit_traits: Sequence[str],
) -> dict[str, float]:
    """Mirror `weapons.weapon_cost_components` — {melee, ranged, total} per weapon."""
    range_value = normalize_range_value(_weapon_str_attr(weapon, "range"))
    traits = split_traits(_weapon_str_attr(weapon, "tags"))
    attacks_value = _weapon_attr(weapon, "attacks", 1.0)
    ap_value = _weapon_attr(weapon, "ap", 0)
    assault = any(
        normalize_name(trait) in {"szturmowy", "szturmowa", "assault"}
        for trait in traits
    )
    ranged_cost = 0.0
    melee_cost = 0.0
    if range_value > 0:
        ranged_cost = _weapon_cost_yaml(
            tables,
            unit_quality,
            range_value,
            attacks_value,
            ap_value,
            traits,
            unit_traits,
            allow_assault_extra=False,
        )
    if range_value == 0 or (range_value > 0 and assault):
        melee_cost = _weapon_cost_yaml(
            tables,
            unit_quality,
            0,
            attacks_value,
            ap_value,
            traits,
            unit_traits,
            allow_assault_extra=False,
        )
    ranged = max(float(ranged_cost or 0.0), 0.0)
    melee = max(float(melee_cost or 0.0), 0.0)
    return {
        "melee": round(melee, 2),
        "ranged": round(ranged, 2),
        "total": round(melee + ranged, 2),
    }


def weapon_cost_yaml(
    tables: RulesetTables,
    weapon,
    unit_quality: int = 4,
    unit_traits: Sequence[str] | None = None,
) -> float:
    """Mirror `weapons.weapon_cost` — total cost rounded, clamped at 0.

    Brak `use_cached` short-circuita — YAML backend liczy zawsze od nowa
    (cache jest atrybutem `weapon.effective_cached_cost` z procedural; tu
    chcemy świadomie pominąć, żeby parity nie zależało od pre-warmu).
    """
    components = weapon_cost_components_yaml(
        tables, weapon, int(unit_quality), list(unit_traits or [])
    )
    return round(max(float(components.get("total", 0.0)), 0.0), 2)


__all__ = [
    "_mistrzostwo_aura_cost",
    "_mistrzostwo_weapon_cost",
    "_weapon_cost_yaml",
    "ap_modifier",
    "base_model_cost",
    "blast_cost",
    "deadly_cost",
    "defense_modifier",
    "morale_modifier",
    "parse_aura_value",
    "range_multiplier",
    "scale_by_tou",
    "toughness_modifier",
    "transport_multiplier",
    "weapon_cost_components_yaml",
    "weapon_cost_yaml",
]
