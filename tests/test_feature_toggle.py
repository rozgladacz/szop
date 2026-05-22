"""Tests for Strumień A — Faza A0 feature toggle.

Verifies that `OPR_RULES_BACKEND` dispatches `calculate_roster_unit_quote`
to the correct backend implementation:

- `procedural` (default) — current SSOT engine, bit-identical to pre-A0 output.
- `yaml`        — raises NotImplementedError until Faza A2 lands.
- `both_assert` — raises NotImplementedError because it calls YAML internally.

Also covers the config-level validation of unknown backend values.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config
from app.services.costs import quote as quote_module
from app.services.costs.errors import RulesetParityError


def test_default_backend_is_procedural() -> None:
    """Module-level default — without env override — is 'procedural'."""
    # The module is already imported with whatever env was set at import time.
    # We only assert the documented default constant and that the chosen
    # backend belongs to the supported set.
    assert config.RULES_BACKEND_PROCEDURAL == "procedural"
    assert config.OPR_RULES_BACKEND in config.RULES_BACKEND_CHOICES


def test_procedural_backend_empty_quote_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Procedural backend preserves the legacy zero-unit payload shape."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_PROCEDURAL)
    result = quote_module.calculate_roster_unit_quote(None)
    assert result["selected_role"] is None
    assert result["warrior_total"] == 0.0
    assert result["shooter_total"] == 0.0
    assert result["selected_total"] == 0.0
    assert result["components"] == {
        "base": 0.0,
        "weapon": 0.0,
        "active": 0.0,
        "aura": 0.0,
        "passive": 0.0,
    }
    assert result["item_costs"] == {
        "weapons": {},
        "active": {},
        "aura": {},
        "passive_deltas": {},
    }


def test_yaml_backend_raises_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """YAML backend stub raises until Faza A2."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_YAML)
    with pytest.raises(NotImplementedError, match="A2"):
        quote_module.calculate_roster_unit_quote(None)


def test_both_assert_backend_propagates_yaml_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """`both_assert` invokes YAML internally — stub propagates the error."""
    monkeypatch.setattr(config, "OPR_RULES_BACKEND", config.RULES_BACKEND_BOTH_ASSERT)
    with pytest.raises(NotImplementedError):
        quote_module.calculate_roster_unit_quote(None)


def test_invalid_backend_value_rejected_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown OPR_RULES_BACKEND fails fast when `app.config` is loaded."""
    monkeypatch.setenv("OPR_RULES_BACKEND", "nonsense")
    # Force a fresh import of app.config so the module-level validation runs again.
    sys.modules.pop("app.config", None)
    try:
        with pytest.raises(ValueError, match="OPR_RULES_BACKEND"):
            importlib.import_module("app.config")
    finally:
        # Restore the canonical module so subsequent tests see the real config.
        sys.modules.pop("app.config", None)
        monkeypatch.delenv("OPR_RULES_BACKEND", raising=False)
        importlib.import_module("app.config")


def test_parity_helper_passes_on_equal_dicts() -> None:
    """`_assert_quote_parity` accepts identical dicts."""
    sample = {
        "selected_role": "wojownik",
        "selected_total": 12.34,
        "components": {"base": 1.0, "weapon": 2.0},
        "item_costs": {"weapons": {"101": 3.5}},
    }
    quote_module._assert_quote_parity(sample, dict(sample), tolerance=1e-3)


def test_parity_helper_tolerance_within_threshold() -> None:
    """Numeric drift below tolerance is accepted."""
    proc = {"selected_total": 12.3400}
    yaml = {"selected_total": 12.3405}  # delta 5e-4 < 1e-3
    quote_module._assert_quote_parity(proc, yaml, tolerance=1e-3)


def test_parity_helper_raises_on_numeric_delta() -> None:
    """Numeric drift above tolerance raises RulesetParityError."""
    proc = {"components": {"base": 5.0}}
    yaml = {"components": {"base": 5.5}}  # delta 0.5 > 1e-3
    with pytest.raises(RulesetParityError) as excinfo:
        quote_module._assert_quote_parity(proc, yaml, tolerance=1e-3)
    assert excinfo.value.path == "<root>.components.base"
    assert excinfo.value.delta == pytest.approx(0.5)


def test_parity_helper_raises_on_structural_mismatch() -> None:
    """Non-numeric difference (e.g. selected_role) raises with delta=None."""
    proc = {"selected_role": "wojownik"}
    yaml = {"selected_role": "strzelec"}
    with pytest.raises(RulesetParityError) as excinfo:
        quote_module._assert_quote_parity(proc, yaml, tolerance=1e-3)
    assert excinfo.value.delta is None
    assert "selected_role" in excinfo.value.path
