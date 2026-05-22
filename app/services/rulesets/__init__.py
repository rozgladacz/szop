"""Deklaratywne reguły kosztów (Strumień A).

Pakiet równoległy do `app/services/costs/`. Procedural pozostaje SSOT;
ten pakiet zapewnia odczyt deklaratywnego rulesetu YAML (Faza A1+) oraz
funkcje DSL kosztów (Faza A2+). Wpinany pod feature toggle
`config.OPR_RULES_BACKEND` — patrz `docs/adr/0005-feature-toggle.md`.
"""

from .loader import RULESET_VERSIONS, load_ruleset
from .models import (
    RulesetAbility,
    RulesetManifest,
    RulesetTables,
    TransportMultiplier,
)

__all__ = [
    "RULESET_VERSIONS",
    "RulesetAbility",
    "RulesetManifest",
    "RulesetTables",
    "TransportMultiplier",
    "load_ruleset",
]
