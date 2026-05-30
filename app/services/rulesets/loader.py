"""Loader rulesetu z YAML.

Wczytuje `app/rulesets/<version>/{tables,abilities}.yaml`, waliduje przez
Pydantic, zwraca immutable `RulesetManifest`. LRU keyed na (version, sha256
treści) — zmiana plików w dev triggeruje rewalidację, w prod cache jest
permanentny (pliki zamrożone w obrazie).

Hot path: po pierwszym wywołaniu `load_ruleset(...)` zwraca tę samą
instancję frozen-modelu, zero alokacji.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AbilityCosts,
    BMvpExclusion,
    BMvpExclusions,
    CostRecipeSpec,
    HandlerMatch,
    HandlerSpec,
    RulesetAbility,
    RulesetManifest,
    RulesetTables,
    TransportMultiplier,
)

# Korzeń katalogu rulesetów: `app/rulesets/`. Plik żyje w
# `app/services/rulesets/loader.py`, więc parent.parent.parent = `app/`.
_RULESETS_ROOT = Path(__file__).resolve().parent.parent.parent / "rulesets"

RULESET_VERSIONS: tuple[str, ...] = ("v1",)


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_yaml(payload: bytes) -> Any:
    return yaml.safe_load(payload)


def _build_transport_multipliers(raw: list[Any]) -> tuple[TransportMultiplier, ...]:
    out: list[TransportMultiplier] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"transport_multipliers: expected mapping, got {item!r}")
        out.append(
            TransportMultiplier(
                traits=tuple(item.get("traits", ())),
                multiplier=float(item["multiplier"]),
            )
        )
    return tuple(out)


def _build_tables(raw: dict[str, Any]) -> RulesetTables:
    payload = dict(raw)
    payload["transport_multipliers"] = _build_transport_multipliers(
        payload.get("transport_multipliers", [])
    )
    return RulesetTables.model_validate(payload)


def _build_abilities(raw: list[Any]) -> tuple[RulesetAbility, ...]:
    out: list[RulesetAbility] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"abilities: expected mapping, got {item!r}")
        normalized = dict(item)
        choices = normalized.get("value_choices")
        if choices is not None:
            normalized["value_choices"] = tuple(choices)
        out.append(RulesetAbility.model_validate(normalized))
    return tuple(out)


def _build_cost_recipe(raw: Any, *, ctx: str) -> CostRecipeSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}: expected mapping {{fn, args}}, got {raw!r}")
    fn_name = raw.get("fn")
    if not isinstance(fn_name, str) or not fn_name:
        raise ValueError(f"{ctx}: missing/empty 'fn'")
    args = raw.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError(f"{ctx}: 'args' must be a mapping, got {args!r}")
    return CostRecipeSpec(fn=fn_name, args=dict(args))


def _build_handler(raw: Any, *, ctx: str) -> HandlerSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}: expected mapping, got {raw!r}")
    match_raw = raw.get("match")
    if not isinstance(match_raw, dict):
        raise ValueError(f"{ctx}: missing/invalid 'match'")
    match_payload: dict[str, Any] = {}
    if "prefix" in match_raw:
        match_payload["prefix"] = str(match_raw["prefix"])
    if "prefix_any" in match_raw:
        prefixes = match_raw["prefix_any"]
        if not isinstance(prefixes, list):
            raise ValueError(f"{ctx}.match.prefix_any: must be a list")
        match_payload["prefix_any"] = tuple(str(p) for p in prefixes)
    if "slug" in match_raw:
        match_payload["slug"] = str(match_raw["slug"])
    if not match_payload:
        raise ValueError(f"{ctx}.match: requires at least one of prefix/prefix_any/slug")
    payload = {k: v for k, v in raw.items() if k != "match"}
    payload["match"] = HandlerMatch(**match_payload)
    return HandlerSpec(**payload)


def _build_ability_costs(raw: dict[str, Any], *, ctx: str) -> AbilityCosts:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx}: top-level must be a mapping")
    version = int(raw.get("version", 0))
    if version <= 0:
        raise ValueError(f"{ctx}: invalid version {version}")
    passive_raw = raw.get("passive_abilities", {}) or {}
    if not isinstance(passive_raw, dict):
        raise ValueError(f"{ctx}.passive_abilities: must be a mapping")
    passive: dict[str, CostRecipeSpec] = {
        str(slug): _build_cost_recipe(spec, ctx=f"{ctx}.passive_abilities.{slug}")
        for slug, spec in passive_raw.items()
    }
    fixed_by_slug = {
        str(k): float(v) for k, v in (raw.get("fixed_by_slug") or {}).items()
    }
    fixed_by_desc = {
        str(k): float(v) for k, v in (raw.get("fixed_by_desc") or {}).items()
    }
    handlers_raw = raw.get("handlers") or []
    if not isinstance(handlers_raw, list):
        raise ValueError(f"{ctx}.handlers: must be a list")
    handlers = tuple(
        _build_handler(h, ctx=f"{ctx}.handlers[{i}]") for i, h in enumerate(handlers_raw)
    )
    skip_in_default = tuple(str(s) for s in (raw.get("skip_in_default") or ()))
    return AbilityCosts(
        version=version,
        passive_abilities=passive,
        fixed_by_slug=fixed_by_slug,
        fixed_by_desc=fixed_by_desc,
        handlers=handlers,
        skip_in_default=skip_in_default,
    )


@lru_cache(maxsize=8)
def _load_ruleset_cached(
    version: str, tables_sha: str, abilities_sha: str, ability_costs_sha: str
) -> RulesetManifest:
    """Inner cached builder — keyed on (version, sha256(*) per YAML file)."""
    del tables_sha, abilities_sha, ability_costs_sha  # cache discriminators
    base = _RULESETS_ROOT / version
    tables_doc = _parse_yaml(_read_bytes(base / "tables.yaml"))
    abilities_doc = _parse_yaml(_read_bytes(base / "abilities.yaml"))
    ability_costs_doc = _parse_yaml(_read_bytes(base / "ability_costs.yaml"))

    if not isinstance(tables_doc, dict):
        raise ValueError(f"{base / 'tables.yaml'}: top-level must be a mapping")
    if not isinstance(abilities_doc, dict):
        raise ValueError(f"{base / 'abilities.yaml'}: top-level must be a mapping")
    if not isinstance(ability_costs_doc, dict):
        raise ValueError(f"{base / 'ability_costs.yaml'}: top-level must be a mapping")

    tables_version = int(tables_doc.get("version", 0))
    abilities_version = int(abilities_doc.get("version", 0))
    ability_costs_version = int(ability_costs_doc.get("version", 0))
    if not (tables_version == abilities_version == ability_costs_version):
        raise ValueError(
            f"Ruleset version mismatch: tables={tables_version}, "
            f"abilities={abilities_version}, ability_costs={ability_costs_version}"
        )
    if tables_version <= 0:
        raise ValueError(f"Ruleset {version}: invalid version {tables_version}")

    tables = _build_tables({k: v for k, v in tables_doc.items() if k != "version"})
    abilities_payload = abilities_doc.get("abilities", [])
    if not isinstance(abilities_payload, list):
        raise ValueError(f"{base / 'abilities.yaml'}: 'abilities' must be a list")
    abilities = _build_abilities(abilities_payload)
    ability_costs = _build_ability_costs(
        ability_costs_doc, ctx=str(base / "ability_costs.yaml")
    )

    return RulesetManifest(
        version=tables_version,
        tables=tables,
        abilities=abilities,
        ability_costs=ability_costs,
    )


@lru_cache(maxsize=4)
def load_ruleset(version: str = "v1") -> RulesetManifest:
    """Public entrypoint — zwraca cache'owany manifest dla podanej wersji.

    **Performance (A5):** outer `@lru_cache` bypassuje SHA recheck na hot path.
    Pierwszy call czyta + parsuje YAML + waliduje przez Pydantic; każdy następny
    zwraca cached `RulesetManifest` w O(1). Bez tego cache hot path tracił
    ~0.27 ms per file × 3 files × quote = ~0.8 ms/quote tylko na SHA256 + I/O.

    Dev workflow (zmiana YAML wymaga reload):
    ```python
    from app.services.rulesets import load_ruleset
    load_ruleset.cache_clear()
    ```
    lub restart procesu. Inner `_load_ruleset_cached` (z SHA discriminators)
    pozostaje dostępny do kontrolowanej rewalidacji w testach migracji.
    """
    if version not in RULESET_VERSIONS:
        raise ValueError(f"Unknown ruleset version: {version!r}; known: {RULESET_VERSIONS}")
    base = _RULESETS_ROOT / version
    tables_sha = _sha256(_read_bytes(base / "tables.yaml"))
    abilities_sha = _sha256(_read_bytes(base / "abilities.yaml"))
    ability_costs_sha = _sha256(_read_bytes(base / "ability_costs.yaml"))
    return _load_ruleset_cached(version, tables_sha, abilities_sha, ability_costs_sha)


@lru_cache(maxsize=2)
def _load_b_mvp_exclusions_cached(version: str, payload_sha: str) -> BMvpExclusions:
    """Inner cached builder — keyed on (version, sha256 b_mvp_exclusions.yaml)."""
    del payload_sha  # cache discriminator
    base = _RULESETS_ROOT / version
    doc = _parse_yaml(_read_bytes(base / "b_mvp_exclusions.yaml"))

    if not isinstance(doc, dict):
        raise ValueError(
            f"{base / 'b_mvp_exclusions.yaml'}: top-level must be a mapping"
        )

    version_field = int(doc.get("version", 0))
    if version_field <= 0:
        raise ValueError(f"b_mvp_exclusions.yaml: invalid version {version_field}")

    excluded_raw = doc.get("excluded_abilities", []) or []
    if not isinstance(excluded_raw, list):
        raise ValueError(
            f"b_mvp_exclusions.yaml: 'excluded_abilities' must be a list"
        )

    excluded = tuple(BMvpExclusion.model_validate(item) for item in excluded_raw)
    return BMvpExclusions(version=version_field, excluded_abilities=excluded)


@lru_cache(maxsize=2)
def load_b_mvp_exclusions(version: str = "v1") -> BMvpExclusions:
    """Public entrypoint dla `b_mvp_exclusions.yaml` (ADR-0008, B0).

    Cache analogiczny do `load_ruleset()` — pierwszy call parsuje YAML +
    waliduje przez Pydantic; kolejne zwracają cached instance w O(1).
    Engine konsumuje przez `is_excluded(slug) -> bool` (frozenset lookup).
    """
    if version not in RULESET_VERSIONS:
        raise ValueError(
            f"Unknown ruleset version: {version!r}; known: {RULESET_VERSIONS}"
        )
    base = _RULESETS_ROOT / version
    payload_sha = _sha256(_read_bytes(base / "b_mvp_exclusions.yaml"))
    return _load_b_mvp_exclusions_cached(version, payload_sha)
