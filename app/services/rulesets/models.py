"""Pydantic v2 schema dla deklaratywnych rulesetów.

Mirror struktur z `app/services/costs/_engine.py` (tabele) i
`app/data/abilities.py` (`AbilityDefinition`). Walidacja odbywa się
raz przy ładowaniu YAML (loader.py); na hot path operujemy frozen
instancjami — żadnych alokacji per quote.
"""

from __future__ import annotations

from typing import Literal

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


AbilityType = Literal["passive", "active", "aura", "weapon"]


class RulesetAbility(BaseModel):
    """Mirror `app.data.abilities.AbilityDefinition`.

    Pola opcjonalne (`value_label`, `value_type`, `value_choices`) zachowują
    None gdy abilities nie wymagają parametru (jak procedural).
    """

    model_config = _FrozenConfig

    slug: str
    name: str
    type: AbilityType
    description: str
    value_label: str | None = None
    value_type: Literal["number", "text"] | None = None
    value_choices: tuple[str, ...] | None = None


class RulesetManifest(BaseModel):
    """Korzeń rulesetu wczytywanego z `app/rulesets/<version>/`.

    Łączy `tables` (z `tables.yaml`) i `abilities` (z `abilities.yaml`) w jeden
    immutable agregat, żeby loader zwracał jedną instancję per wersja.
    """

    model_config = _FrozenConfig

    version: int = Field(ge=1)
    tables: RulesetTables
    abilities: tuple[RulesetAbility, ...]
