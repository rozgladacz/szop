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

from .models import RulesetAbility, RulesetManifest, RulesetTables, TransportMultiplier

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


@lru_cache(maxsize=8)
def _load_ruleset_cached(version: str, tables_sha: str, abilities_sha: str) -> RulesetManifest:
    """Inner cached builder — keyed on (version, sha256(tables), sha256(abilities))."""
    del tables_sha, abilities_sha  # used only as cache discriminator
    base = _RULESETS_ROOT / version
    tables_doc = _parse_yaml(_read_bytes(base / "tables.yaml"))
    abilities_doc = _parse_yaml(_read_bytes(base / "abilities.yaml"))

    if not isinstance(tables_doc, dict):
        raise ValueError(f"{base / 'tables.yaml'}: top-level must be a mapping")
    if not isinstance(abilities_doc, dict):
        raise ValueError(f"{base / 'abilities.yaml'}: top-level must be a mapping")

    tables_version = int(tables_doc.get("version", 0))
    abilities_version = int(abilities_doc.get("version", 0))
    if tables_version != abilities_version:
        raise ValueError(
            f"Ruleset version mismatch: tables={tables_version}, abilities={abilities_version}"
        )
    if tables_version <= 0:
        raise ValueError(f"Ruleset {version}: invalid version {tables_version}")

    tables = _build_tables({k: v for k, v in tables_doc.items() if k != "version"})
    abilities_payload = abilities_doc.get("abilities", [])
    if not isinstance(abilities_payload, list):
        raise ValueError(f"{base / 'abilities.yaml'}: 'abilities' must be a list")
    abilities = _build_abilities(abilities_payload)

    return RulesetManifest(version=tables_version, tables=tables, abilities=abilities)


def load_ruleset(version: str = "v1") -> RulesetManifest:
    """Public entrypoint — zwraca cache'owany manifest dla podanej wersji.

    Re-czytamy SHA256 obu plików, żeby zmiana w dev triggerowała rewalidację
    bez ręcznego invalidate'u cache. W prod (pliki zamrożone) SHA jest stabilne
    → cache hit od drugiego wywołania.
    """
    if version not in RULESET_VERSIONS:
        raise ValueError(f"Unknown ruleset version: {version!r}; known: {RULESET_VERSIONS}")
    base = _RULESETS_ROOT / version
    tables_sha = _sha256(_read_bytes(base / "tables.yaml"))
    abilities_sha = _sha256(_read_bytes(base / "abilities.yaml"))
    return _load_ruleset_cached(version, tables_sha, abilities_sha)
