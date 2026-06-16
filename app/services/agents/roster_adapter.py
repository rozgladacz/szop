"""Most ORM `Roster` → engine-dict (warstwa-liść agentów).

Konwertuje ORM `Roster` (relacje `RosterUnit`→`Unit`→`Weapon`/`UnitAbility`) na
format **engine-dict** konsumowany przez `state.build_initial_state` /
`agents.simulate_from_rosters`:

    {"owner_player": int,
     "units": [{"id", "position": (x, y), "models", "toughness",
                "quality", "defense", "passives": [...], "weapons": [...]}]}

Prereq dla D3 `exploit_hunt` (metryka win_rate/points), odłożonego D2 breakdown
per-zdolność/broń oraz DB-backed `LocalClient`. Warstwa-liść: czyta tylko ORM +
publiczne SSOT (zero zmian w rdzeniu `engine/*`).

**Reuse SSOT (mandat [CRITICAL] #3):**
- `costs.normalize_range_value` — string zasięgu (`24"`, `Walka wręcz`) → cale (0 = wręcz).
- `costs.ability_identifier` — nazwa zdolności → slug (`abilities.yaml`).
- `costs.normalize_name` — fallback slug dla broni.
- `load_b_mvp_exclusions` — zdolności wykluczone z MVP (inaczej `build_initial_state`
  rzuca `UnsupportedAbilityError`).
- `effects.INCOMPLETE_ABILITIES` — zdolności bez engine-impl (engine cicho ignoruje).

**Uproszczenia slice 1 (udokumentowane, follow-up w HANDOFF_faza-d-roster-adapter):**
- Broń: tylko `Unit.default_weapon_loadout` (domyślny loadout). Override'y rozpiski
  `RosterUnit.extra_weapons_json` DEFEROWANE.
- Koszt/punkty: poza zakresem — D3 woła `costs.calculate_roster_unit_quote` (gotowe SSOT).
- Pozycje: placeholder (spread liniowy) — realne rozstawienie z D5 `deployment_zones`.
- Attached heroes (`RosterUnit.parent_roster_unit_id`): DEFEROWANE (raportowane).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services import costs
from app.services.engine.effects import INCOMPLETE_ABILITIES
from app.services.rulesets.loader import load_b_mvp_exclusions

# Engine wymaga unikalnych id blobów w obrębie `BattleState`. Rozłączamy
# przestrzenie id graczy żeby konwersja 2 rosterów (owner 0/1) nie kolidowała.
_PLAYER_ID_STRIDE = 10_000


@dataclass(frozen=True)
class AdaptResult:
    """Wynik adaptacji jednego rostera.

    - `units` — engine-dict gotowy dla `build_initial_state` / `simulate_from_rosters`.
    - `dropped_excluded` — slugi zdolności odfiltrowane (na `b_mvp_exclusions`),
      inaczej `build_initial_state` rzuciłby `UnsupportedAbilityError`.
    - `inert_incomplete` — slugi przepuszczone do engine, ale bez impl (cicho ignorowane).
    - `deferred_attached_heroes` — `RosterUnit.id` dołączonych bohaterów pominiętych
      w tym slice (poprawny merge do oddziału macierzystego = follow-up).
    """

    units: dict[str, Any]
    dropped_excluded: list[str] = field(default_factory=list)
    inert_incomplete: list[str] = field(default_factory=list)
    deferred_attached_heroes: list[int] = field(default_factory=list)


def _ability_slugs(unit: Any) -> list[str]:
    """Slugi zdolności oddziału z `unit.abilities` (przez nazwę → SSOT slug)."""
    slugs: list[str] = []
    for link in getattr(unit, "abilities", []) or []:
        ability = getattr(link, "ability", None)
        name = getattr(ability, "name", None)
        if not name:
            continue
        slug = costs.ability_identifier(name)
        if slug:
            slugs.append(slug)
    return slugs


def _weapon_slug(weapon: Any) -> str:
    name = getattr(weapon, "effective_name", None) or "bron"
    return costs.normalize_name(name) or "bron"


def _weapon_abilities(weapon: Any) -> tuple[str, ...]:
    """Tagi broni (`Weapon.effective_tags`, comma-separated) → slugi."""
    raw = getattr(weapon, "effective_tags", None)
    if not raw:
        return ()
    out: list[str] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        slug = costs.ability_identifier(part)
        if slug:
            out.append(slug)
    return tuple(out)


def _weapon_to_dict(weapon: Any) -> dict[str, Any]:
    attacks = int(round(getattr(weapon, "effective_attacks", 1.0) or 1.0))
    return {
        "slug": _weapon_slug(weapon),
        "name": getattr(weapon, "effective_name", "") or "",
        "range_inches": costs.normalize_range_value(
            getattr(weapon, "effective_range", "") or ""
        ),
        "attacks": max(attacks, 1),
        "ap": int(getattr(weapon, "effective_ap", 0) or 0),
        "weapon_abilities": _weapon_abilities(weapon),
    }


def _unit_weapons(unit: Any) -> list[dict[str, Any]]:
    """Lista WeaponProfile-dict z domyślnego loadoutu, primary-first per kategoria.

    Engine (MVP) używa pierwszej broni każdej kategorii (`melee_weapons[0]` /
    `ranged_weapons[0]`), więc broń primary musi trafić na początek.
    """
    # Tożsamość obiektu (nie `weapon_id`) — transient ORM nie ma FK przed flush.
    primary_obj_ids = {
        id(link.weapon)
        for link in getattr(unit, "weapon_links", []) or []
        if getattr(link, "is_primary", False) and link.weapon is not None
    }
    seen: set[tuple[str, int]] = set()
    flagged: list[tuple[bool, dict[str, Any]]] = []
    for weapon, _count in getattr(unit, "default_weapon_loadout", []) or []:
        if weapon is None:
            continue
        wd = _weapon_to_dict(weapon)
        key = (wd["slug"], wd["range_inches"])
        if key in seen:
            continue
        seen.add(key)
        flagged.append((id(weapon) in primary_obj_ids, wd))
    # Stabilne sortowanie primary-first (zachowuje kolejność loadoutu wewnątrz grupy).
    flagged.sort(key=lambda t: 0 if t[0] else 1)
    return [wd for _is_primary, wd in flagged]


def roster_to_engine_roster(
    roster: Any,
    *,
    owner_player: int,
    models_mode: str = "per_copy",
    positions: list[tuple[float, float]] | None = None,
    ruleset_version: str = "v1",
) -> AdaptResult:
    """Adaptuje ORM `Roster` na engine-dict dla jednego gracza.

    `models_mode`:
    - ``"per_copy"`` (default) — `RosterUnit.count` osobnych blobów, każdy
      `Unit.typical_model_count` modeli (oddziały aktywują się niezależnie, pkt 11).
    - ``"aggregate"`` — 1 blob × (count × typical_models).

    `positions`: opcjonalna lista pozycji per blob (w kolejności emisji). Gdy brak —
    placeholder spread liniowy (realne rozstawienie z D5 `deployment_zones`).

    Zdolności wykluczone z MVP (`b_mvp_exclusions`) są ODFILTROWANE i raportowane
    w `AdaptResult.dropped_excluded` (inaczej `build_initial_state` rzuciłby
    `UnsupportedAbilityError`). `INCOMPLETE_ABILITIES` przepuszczone (engine ignoruje),
    raportowane w `inert_incomplete`.
    """
    if models_mode not in ("per_copy", "aggregate"):
        raise ValueError(f"models_mode must be 'per_copy' or 'aggregate', got {models_mode!r}")

    excluded = load_b_mvp_exclusions(ruleset_version).slugs()
    dropped_excluded: list[str] = []
    inert_incomplete: list[str] = []
    deferred_attached_heroes: list[int] = []

    blobs: list[dict[str, Any]] = []
    next_id = owner_player * _PLAYER_ID_STRIDE

    for ru in getattr(roster, "roster_units", []) or []:
        if getattr(ru, "parent_roster_unit_id", None) is not None:
            # Attached hero — DEFEROWANE w slice 1 (poprawny merge do macierzystego).
            deferred_attached_heroes.append(getattr(ru, "id", -1))
            continue
        unit = getattr(ru, "unit", None)
        if unit is None:
            continue

        raw_slugs = _ability_slugs(unit)
        passives: list[str] = []
        for slug in raw_slugs:
            if slug in excluded:
                if slug not in dropped_excluded:
                    dropped_excluded.append(slug)
                continue
            if slug in INCOMPLETE_ABILITIES and slug not in inert_incomplete:
                inert_incomplete.append(slug)
            passives.append(slug)

        weapons = _unit_weapons(unit)
        typical = int(getattr(unit, "typical_model_count", 1))
        count = max(int(getattr(ru, "count", 1)), 1)
        quality = int(getattr(unit, "quality", 4))
        defense = int(getattr(unit, "defense", 5))
        toughness = int(getattr(unit, "toughness", 1))

        if models_mode == "aggregate":
            groups = [count * typical]
        else:
            groups = [typical] * count

        for models in groups:
            blobs.append(
                {
                    "id": next_id,
                    "position": (0.0, 0.0),  # placeholder; nadpisane niżej
                    "models": max(models, 1),
                    "toughness": toughness,
                    "quality": quality,
                    "defense": defense,
                    "passives": list(passives),
                    "weapons": [dict(w) for w in weapons],
                }
            )
            next_id += 1

    _assign_positions(blobs, positions, owner_player)

    return AdaptResult(
        units={"owner_player": owner_player, "units": blobs},
        dropped_excluded=dropped_excluded,
        inert_incomplete=inert_incomplete,
        deferred_attached_heroes=deferred_attached_heroes,
    )


def _assign_positions(
    blobs: list[dict[str, Any]],
    positions: list[tuple[float, float]] | None,
    owner_player: int,
) -> None:
    """Nadaje pozycje blobom: jawne z `positions` lub placeholder spread liniowy.

    Placeholder unika zdegenerowanego stackowania (wszystkie w (0,0)); realne
    rozstawienie w strefie zapewnia D5 `deployment_zones`, które nadpisuje pozycje.
    """
    for i, blob in enumerate(blobs):
        if positions is not None and i < len(positions):
            blob["position"] = (float(positions[i][0]), float(positions[i][1]))
        else:
            # Spread wzdłuż osi X, y rozdzielone per gracz (placeholder).
            blob["position"] = (3.0 + i * 4.0, 6.0 + owner_player * 12.0)
