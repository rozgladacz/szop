"""Generate the tracked JSON Schema for physical ruleset v1 documents."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.rulesets.models import RulesetDocument

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://szop.local/schemas/ruleset_v1.schema.json"
SCHEMA_RELATIVE_PATH = Path("docs/schemas/ruleset_v1.schema.json")
OUTPUT_PATH = ROOT_DIR / SCHEMA_RELATIVE_PATH


def build_schema() -> dict[str, Any]:
    """Build the JSON Schema without reading or writing repository files."""
    schema = RulesetDocument.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    variants = schema.pop("anyOf")
    schema["oneOf"] = variants
    schema["$schema"] = SCHEMA_DRAFT
    schema["$id"] = SCHEMA_ID
    return schema


def serialize(schema: dict[str, Any]) -> str:
    """Serialize deterministically as UTF-8-ready text with one trailing LF."""
    return (
        json.dumps(
            schema,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _expected_bytes() -> bytes:
    return serialize(build_schema()).encode("utf-8")


def _write_if_changed(payload: bytes) -> bool:
    if OUTPUT_PATH.exists() and OUTPUT_PATH.read_bytes() == payload:
        return False

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=OUTPUT_PATH.parent,
        prefix=f".{OUTPUT_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)

    try:
        os.replace(temp_path, OUTPUT_PATH)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def _check(payload: bytes) -> int:
    if not OUTPUT_PATH.exists():
        print("ruleset schema missing; run make generate-schema", file=sys.stderr)
        return 1
    if OUTPUT_PATH.read_bytes() != payload:
        print("ruleset schema drift; run make generate-schema", file=sys.stderr)
        return 1
    print("ruleset schema is current")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or check the tracked ruleset v1 JSON Schema."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail on a missing or stale artifact without writing it",
    )
    args = parser.parse_args(argv)

    payload = _expected_bytes()
    if args.check:
        return _check(payload)

    changed = _write_if_changed(payload)
    state = "written" if changed else "unchanged"
    print(f"ruleset schema {state}: {SCHEMA_RELATIVE_PATH.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
