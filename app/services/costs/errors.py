"""Cost engine error types.

Introduced in Faza A0 (Strumień A — deklaratywne reguły).
See docs/adr/0005-feature-toggle.md.
"""

from __future__ import annotations

from typing import Any


class RulesetParityError(AssertionError):
    """Raised by `both_assert` backend when procedural and YAML quotes diverge.

    Carries enough context to debug a parity break: the dotted path inside the
    quote dict that diverged, both values, and the numeric delta (None for
    non-numeric mismatches).
    """

    def __init__(
        self,
        *,
        path: str,
        proc_value: Any,
        yaml_value: Any,
        delta: float | None,
        tolerance: float | None = None,
    ) -> None:
        self.path = path
        self.proc_value = proc_value
        self.yaml_value = yaml_value
        self.delta = delta
        self.tolerance = tolerance
        if delta is None:
            detail = f"non-numeric mismatch at {path!r}: proc={proc_value!r} yaml={yaml_value!r}"
        else:
            tol_part = f" (tolerance={tolerance})" if tolerance is not None else ""
            detail = (
                f"delta={delta:.6g} at {path!r}: proc={proc_value!r} yaml={yaml_value!r}{tol_part}"
            )
        super().__init__(f"RulesetParityError: {detail}")


__all__ = ["RulesetParityError"]
