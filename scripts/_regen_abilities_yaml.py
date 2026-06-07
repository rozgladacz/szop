"""Internal helper: regenerate abilities.yaml from app/data/abilities.py.

**Nie jest częścią A4 pipeline'u** (`make rules-check` go nie wywołuje).
Underscore prefix oznacza ad-hoc dev helper — używany podczas YAML sync
gdy `app/data/abilities.py` ulega zmianie (np. merge/cherry-pick z innej
gałęzi z nowymi `ABILITY_DEFINITIONS`).

Workflow:
    1. Cherry-pick / merge zmiany w `app/data/abilities.py` (procedural SSOT).
    2. `python scripts/_regen_abilities_yaml.py` — regeneruje YAML mirror.
    3. Sprawdź `pytest tests/test_abilities_migration.py` — exact match.
    4. Update `app/rulesets/v1/{tables,ability_costs}.yaml` ręcznie jeśli
       zmieniły się cost path tables (transport_multipliers, scale_by_tou args).
    5. Sprawdź `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py`.

Test parity (`tests/test_abilities_migration.py`) jest źródłem prawdy —
ten skrypt to tylko convenience generator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.data.abilities import ABILITY_DEFINITIONS  # noqa: E402

HEADER = """# Ruleset v1 — definicje zdolnosci (mirror app/data/abilities.py).
#
# Procedural engine pozostaje SSOT przez caly Strumien A (ADR-0005). Ten plik jest
# zrodlem dla YAML backend uruchamianego pod OPR_RULES_BACKEND=yaml.
# Test tests/test_abilities_migration.py wymusza exact match (slug, name, type,
# description, value_label, value_type, value_choices) wzgledem ABILITY_DEFINITIONS.

"""


def main() -> int:
    entries = []
    for d in ABILITY_DEFINITIONS:
        entry: dict = {
            "slug": d.slug,
            "name": d.name,
            "type": d.type,
            "description": d.description,
        }
        if d.value_label is not None:
            entry["value_label"] = d.value_label
        if d.value_type is not None:
            entry["value_type"] = d.value_type
        if d.value_choices is not None:
            entry["value_choices"] = list(d.value_choices)
        entries.append(entry)

    payload = {"version": 1, "abilities": entries}
    output = _PROJECT_ROOT / "app" / "rulesets" / "v1" / "abilities.yaml"
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False, width=10000)
    print(f"Regenerated {output} with {len(entries)} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
