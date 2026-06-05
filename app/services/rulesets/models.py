"""Pydantic v2 schema dla deklaratywnych rulesetów.

Mirror struktur z `app/services/costs/_engine.py` (tabele) i
`app/data/abilities.py` (`AbilityDefinition`). Walidacja odbywa się
raz przy ładowaniu YAML (loader.py); na hot path operujemy frozen
instancjami — żadnych alokacji per quote.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Frozen-model konfiguracja: immutable + szybkie odczyty w hot path.
_FrozenConfig = ConfigDict(frozen=True, extra="forbid", strict=False)


class TransportMultiplier(BaseModel):
    """Jedna reguła z `TRANSPORT_MULTIPLIERS` w `_engine.py`.

    `traits` w oryginale jest setem; YAML nie ma setu, więc przechowujemy
    listę i porównujemy semantycznie (kolejność nieistotna).
    """

    model_config = _FrozenConfig

    traits: tuple[str, ...]
    multiplier: float

    @property
    def traits_set(self) -> frozenset[str]:
        return frozenset(self.traits)


class BMvpConfig(BaseModel):
    """B0 Pareto MVP konstantne dla game engine (ADR-0008).

    Subsekcja `b_mvp` w `tables.yaml`. Konsumowane przez `app/services/engine/`,
    nie używane w Strumieniu A (koszty). Pole opcjonalne w `RulesetTables` —
    YAML bez sekcji `b_mvp` nadal parsuje (backward compat).
    """

    model_config = _FrozenConfig

    move_inches: int = Field(ge=1)
    base_area_inches_sq_per_toughness: float = Field(gt=0)
    pi_approx: float = Field(gt=0)


class LocationKind(BaseModel):
    """Pojedyncza lokalizacja oddziału/modelu (SZOP_Rozjemca pkt 26).

    Wszystkie pola opcjonalne poza `description` — pozwala na rozszerzenia
    bez breaking change. Konsumowane przez `app/services/engine/state.py`
    (enum `Lokalizacja`). Patrz HANDOFF_faza-b-rules-resync.
    """

    model_config = ConfigDict(frozen=True, extra="allow", strict=False)

    description: str
    on_field: bool = False
    can_activate: bool = False
    can_return: bool | None = None


class StatusFlagSpec(BaseModel):
    """Stan oddziału po driftcie 2026-06 (SZOP_Rozjemca pkt 22).

    Pola semantyczne — engine używa do reducerów/dispatcher decyzji
    (np. `mutex_with` dla pkt 22.b.iii+22.c.iv). Patrz ADR-0048.
    """

    model_config = ConfigDict(frozen=True, extra="allow", strict=False)

    point: str
    description: str
    mutex_with: tuple[str, ...] = Field(default_factory=tuple)


class AuraOrderFormula(BaseModel):
    """Formuła wyceny Aury / Rozkazu / Klątwy / Oznaczenia (SZOP_Zdolnosci).

    Wprowadzona w faza-b-rules-resync 2026-06. Zastępuje stałe pola `aura`/
    `rozkaz` w `cost` per ability. Konsumowane przez `cost_functions.aura_cost`
    i `cost_functions.order_cost`. Patrz ADR-0048.
    """

    model_config = _FrozenConfig

    t_eff_factor: float = Field(gt=0)
    t_eff_clamp_min: int = Field(ge=1)
    t_eff_clamp_max: int = Field(ge=1)
    aura_range_bonus: int = Field(ge=0)
    order_bonus: int = Field(ge=0)


class RulesetTables(BaseModel):
    """Wszystkie tabele kosztów z `_engine.py:23-79`.

    Klucze tabel intowych (`defense_base_values`, `range_table`, `ap_base`, ...)
    pozostają intami — YAML loader tak je deserializuje (`2: 2.3`).
    """

    model_config = _FrozenConfig

    morale_ability_multipliers: dict[str, float]
    defense_base_values: dict[int, float]
    defense_ability_modifiers: dict[str, dict[int, float]]
    toughness_special: dict[int, float]
    range_table: dict[int, float]
    artillery_range_bonus: dict[int, float]
    unwieldy_range_penalty: dict[int, float]
    cautious_hit_bonus: dict[int, float]
    ap_base: dict[int, float]
    ap_lance: dict[int, float]
    penetrating_multiplier: dict[int, float]
    waagh_ap_modifier: dict[int, float]
    blast_multiplier: dict[int, float]
    deadly_multiplier: dict[int, float]
    brutalny_ap_cost: dict[int, float]
    transport_multipliers: tuple[TransportMultiplier, ...]
    overcharge_multiplier: float
    base_cost_factor: float
    b_mvp: BMvpConfig | None = None
    locations: dict[str, LocationKind] = Field(default_factory=dict)
    status_flags: dict[str, StatusFlagSpec] = Field(default_factory=dict)
    aura_order_formula: AuraOrderFormula | None = None


AbilityType = Literal["passive", "active", "aura", "weapon"]


class RulesetAbility(BaseModel):
    """Mirror `app.data.abilities.AbilityDefinition`.

    Pola opcjonalne (`value_label`, `value_type`, `value_choices`) zachowują
    None gdy abilities nie wymagają parametru (jak procedural).

    `rozkaz_tak` (R4 2026-06): czy ability może być X w Rozkaz(X)/Klątwa(X)/
    Oznaczenie(X). Tylko passive abilities mają to pole. None = nieznane/false.
    """

    model_config = _FrozenConfig

    slug: str
    name: str
    type: AbilityType
    description: str
    value_label: str | None = None
    value_type: Literal["number", "text"] | None = None
    value_choices: tuple[str, ...] | None = None
    rozkaz_tak: bool | None = None


class CostRecipeSpec(BaseModel):
    """Atomowa receptura DSL — odczytywana z `ability_costs.yaml`.

    Używany jednolicie przez loader (YAML → spec) i dispatcher (spec →
    `call_recipe`). `dispatcher.CostRecipe` to alias na tę klasę (zero
    konwersji w runtime, A5 perf optimization).
    """

    model_config = _FrozenConfig

    fn: str
    args: dict[str, Any] = Field(default_factory=dict)


class HandlerMatch(BaseModel):
    """Match-pattern handlera z `ability_costs.yaml:handlers[i].match`.

    Dokładnie jeden z trzech kluczy powinien być wypełniony — walidacja w
    loaderze (Pydantic nie wyraża dobrze `oneOf` w prostej formie).
    """

    model_config = _FrozenConfig

    prefix: str | None = None
    prefix_any: tuple[str, ...] | None = None
    slug: str | None = None


class HandlerSpec(BaseModel):
    """Handler dispatch entry z `ability_costs.yaml:handlers[i]`.

    `fn_name` jest dispatchowane przez `handlers.py` (A2.4b) — NIE przez
    `dispatcher.py` registry (tamto registry to prymitywy DSL).

    Dodatkowe pola (`open_bonus`, `inner_tou`, `range_12_multiplier`, ...) to
    stałe gry zachowane w YAML zamiast hard-kodować w handlerach. Pole `Extra`
    pozostawione na rozszerzenia DSL bez schema-creep — strict=False pozwala
    na dodatkowe klucze, których nie wszystkie handlery używają.
    """

    model_config = ConfigDict(frozen=True, extra="allow", strict=False)

    id: str
    match: HandlerMatch
    fn_name: str


class AbilityCosts(BaseModel):
    """Cost DSL recipes z `ability_costs.yaml` (A2.3).

    Konsumowane przez `_yaml_quote()` (A2.4) i `handlers.py` (A2.4b).
    `passive_abilities` to słownik slug → receptura `scale_by_tou` użyta
    przez `passive_cost_dsl`. `fixed_by_*` to słowniki na wzór gałęzi
    `slug == X` / `desc == X` w oracle. `handlers` to lista (kolejność
    znacząca: dispatch w kolejności list-order).
    """

    model_config = _FrozenConfig

    version: int = Field(ge=1)
    passive_abilities: dict[str, CostRecipeSpec]
    fixed_by_slug: dict[str, float]
    fixed_by_desc: dict[str, float]
    handlers: tuple[HandlerSpec, ...]
    skip_in_default: tuple[str, ...] = Field(default_factory=tuple)


class RulesetManifest(BaseModel):
    """Korzeń rulesetu wczytywanego z `app/rulesets/<version>/`.

    Łączy `tables` (z `tables.yaml`), `abilities` (z `abilities.yaml`) i
    `ability_costs` (z `ability_costs.yaml`) w jeden immutable agregat,
    żeby loader zwracał jedną instancję per wersja.
    """

    model_config = _FrozenConfig

    version: int = Field(ge=1)
    tables: RulesetTables
    abilities: tuple[RulesetAbility, ...]
    ability_costs: AbilityCosts


class BMvpExclusion(BaseModel):
    """Pojedynczy wpis w `b_mvp_exclusions.yaml` (ADR-0008).

    Hand-curated decyzja: zdolności wykluczone z B MVP. Engine raise
    `UnsupportedAbilityError` przy budowie BattleState gdy roster zawiera
    oddział z którąkolwiek z tych zdolności.
    """

    model_config = _FrozenConfig

    slug: str
    reason: str
    category: str


class BMvpExclusions(BaseModel):
    """Korzeń `b_mvp_exclusions.yaml` — lista wykluczeń + version.

    Loader (`load_b_mvp_exclusions()`) zwraca cache'owany frozen-model.
    """

    model_config = _FrozenConfig

    version: int = Field(ge=1)
    excluded_abilities: tuple[BMvpExclusion, ...]

    def slugs(self) -> frozenset[str]:
        """Frozen set slugów — O(1) lookup w runtime."""
        return frozenset(e.slug for e in self.excluded_abilities)

    def is_excluded(self, slug: str) -> bool:
        return slug in self.slugs()
