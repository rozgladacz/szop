"""A1.1 — deterministic JSON Schema for physical ruleset v1 documents."""

from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from app.services.rulesets.models import (
    AbilityCosts,
    RulesetAbilitiesDocument,
    RulesetDocument,
    RulesetTablesDocument,
)
from scripts import generate_ruleset_schema as schema_generator

ROOT_DIR = Path(__file__).resolve().parents[1]
RULESET_DIR = ROOT_DIR / "app/rulesets/v1"
ARTIFACT_PATH = ROOT_DIR / schema_generator.SCHEMA_RELATIVE_PATH
SCRIPT_PATH = ROOT_DIR / "scripts/generate_ruleset_schema.py"

DOCUMENT_MODELS: dict[str, type[BaseModel]] = {
    "tables.yaml": RulesetTablesDocument,
    "abilities.yaml": RulesetAbilitiesDocument,
    "ability_costs.yaml": AbilityCosts,
}


def _load_yaml(filename: str) -> dict:
    payload = yaml.safe_load((RULESET_DIR / filename).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_two_generations_are_byte_exact_and_write_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "docs/schemas/ruleset_v1.schema.json"
    monkeypatch.setattr(schema_generator, "OUTPUT_PATH", output_path)

    replace_calls = 0
    original_replace = schema_generator.os.replace

    def recording_replace(source, target) -> None:
        nonlocal replace_calls
        replace_calls += 1
        original_replace(source, target)

    monkeypatch.setattr(schema_generator.os, "replace", recording_replace)

    assert schema_generator.main([]) == 0
    first = output_path.read_bytes()
    assert schema_generator.main([]) == 0
    second = output_path.read_bytes()

    assert first == second
    assert first == schema_generator.serialize(schema_generator.build_schema()).encode(
        "utf-8"
    )
    assert first.endswith(b"\n")
    assert not first.endswith(b"\n\n")
    assert replace_calls == 1


def test_check_success_and_failures_never_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "nested/ruleset_v1.schema.json"
    monkeypatch.setattr(schema_generator, "OUTPUT_PATH", output_path)

    assert schema_generator.main(["--check"]) == 1
    assert not output_path.exists()
    assert not output_path.parent.exists()
    assert capsys.readouterr().err == (
        "ruleset schema missing; run make generate-schema\n"
    )

    output_path.parent.mkdir(parents=True)
    drift = b'{"drift": true}\n'
    output_path.write_bytes(drift)
    assert schema_generator.main(["--check"]) == 1
    assert output_path.read_bytes() == drift
    assert capsys.readouterr().err == (
        "ruleset schema drift; run make generate-schema\n"
    )

    expected = schema_generator.serialize(schema_generator.build_schema()).encode(
        "utf-8"
    )
    output_path.write_bytes(expected)
    assert schema_generator.main(["--check"]) == 0
    assert output_path.read_bytes() == expected
    assert capsys.readouterr().out == "ruleset schema is current\n"


def test_tracked_artifact_matches_pure_build_exactly() -> None:
    expected = schema_generator.serialize(schema_generator.build_schema()).encode(
        "utf-8"
    )
    assert ARTIFACT_PATH.read_bytes() == expected


def test_schema_metadata_and_three_distinct_document_variants() -> None:
    schema = schema_generator.build_schema()

    assert schema["$schema"] == schema_generator.SCHEMA_DRAFT
    assert schema["$id"] == schema_generator.SCHEMA_ID
    assert schema["$id"] == "https://szop.local/schemas/ruleset_v1.schema.json"
    assert schema["title"] == "SZOP ruleset v1 document"
    assert schema["description"]
    assert "anyOf" not in schema
    assert schema["oneOf"] == [
        {"$ref": "#/$defs/RulesetTablesDocument"},
        {"$ref": "#/$defs/RulesetAbilitiesDocument"},
        {"$ref": "#/$defs/AbilityCosts"},
    ]

    defs = schema["$defs"]
    variants = {
        "RulesetTablesDocument": (
            "Ruleset v1 tables.yaml document",
            "morale_ability_multipliers",
        ),
        "RulesetAbilitiesDocument": (
            "Ruleset v1 abilities.yaml document",
            "abilities",
        ),
        "AbilityCosts": (
            "Ruleset v1 ability_costs.yaml document",
            "passive_abilities",
        ),
    }
    for name, (title, distinguishing_key) in variants.items():
        variant = defs[name]
        assert variant["title"] == title
        assert variant["description"]
        assert variant["additionalProperties"] is False
        assert "version" in variant["required"]
        assert distinguishing_key in variant["required"]


@pytest.mark.parametrize(
    ("filename", "model"),
    DOCUMENT_MODELS.items(),
    ids=DOCUMENT_MODELS,
)
def test_current_yaml_validates_with_its_document_model(
    filename: str,
    model: type[BaseModel],
) -> None:
    validated = model.model_validate(_load_yaml(filename))
    assert validated.model_config["frozen"] is True


@pytest.mark.parametrize(
    ("filename", "expected_type"),
    DOCUMENT_MODELS.items(),
    ids=DOCUMENT_MODELS,
)
def test_root_model_selects_the_expected_document_variant(
    filename: str,
    expected_type: type[BaseModel],
) -> None:
    validated = RulesetDocument.model_validate(_load_yaml(filename))
    assert type(validated.root) is expected_type


@pytest.mark.parametrize(
    ("filename", "model"),
    DOCUMENT_MODELS.items(),
    ids=DOCUMENT_MODELS,
)
@pytest.mark.parametrize("version_case", ["missing", "zero"])
def test_document_models_reject_missing_or_invalid_version(
    filename: str,
    model: type[BaseModel],
    version_case: str,
) -> None:
    payload = _load_yaml(filename)
    if version_case == "missing":
        payload.pop("version")
    else:
        payload["version"] = 0

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_root_model_rejects_unknown_top_level_shape() -> None:
    with pytest.raises(ValidationError):
        RulesetDocument.model_validate({"version": 1, "unknown": {}})


def test_abilities_document_rejects_wrong_abilities_type() -> None:
    payload = _load_yaml("abilities.yaml")
    payload["abilities"] = {"not": "a list"}
    with pytest.raises(ValidationError):
        RulesetAbilitiesDocument.model_validate(payload)


def test_tables_document_rejects_unknown_top_level_field() -> None:
    payload = _load_yaml("tables.yaml")
    payload["unknown_table"] = {}
    with pytest.raises(ValidationError):
        RulesetTablesDocument.model_validate(payload)


def test_ability_costs_document_rejects_wrong_key_field_type() -> None:
    payload = _load_yaml("ability_costs.yaml")
    payload["passive_abilities"] = []
    with pytest.raises(ValidationError):
        AbilityCosts.model_validate(payload)


def test_declared_extension_points_remain_extra_allow() -> None:
    schema = schema_generator.build_schema()
    for definition in ("LocationKind", "StatusFlagSpec", "HandlerSpec"):
        assert schema["$defs"][definition]["additionalProperties"] is True

    tables = deepcopy(_load_yaml("tables.yaml"))
    tables["locations"]["front"]["editor_extension"] = True
    tables["status_flags"]["wyczerpany"]["editor_extension"] = True
    RulesetTablesDocument.model_validate(tables)

    costs = deepcopy(_load_yaml("ability_costs.yaml"))
    costs["handlers"][0]["editor_extension"] = True
    AbilityCosts.model_validate(costs)


def test_import_has_no_artifact_side_effect() -> None:
    before_bytes = ARTIFACT_PATH.read_bytes()
    before_mtime = ARTIFACT_PATH.stat().st_mtime_ns
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", "import scripts.generate_ruleset_schema"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert ARTIFACT_PATH.read_bytes() == before_bytes
    assert ARTIFACT_PATH.stat().st_mtime_ns == before_mtime


def test_check_cli_is_independent_of_cwd_and_stdio_encoding(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1250"
    env["PYTHONUTF8"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ruleset schema is current\n"


def test_runtime_loader_and_costs_do_not_import_generator_or_artifact() -> None:
    runtime_paths = [ROOT_DIR / "app/services/rulesets/loader.py"]
    runtime_paths.extend(sorted((ROOT_DIR / "app/services/costs").glob("*.py")))
    for path in runtime_paths:
        source = path.read_text(encoding="utf-8")
        assert "generate_ruleset_schema" not in source, path
        assert "ruleset_v1.schema.json" not in source, path

    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            (
                "import sys; "
                "import app.services.rulesets.loader; "
                "import app.services.costs.quote; "
                "assert 'scripts.generate_ruleset_schema' not in sys.modules"
            ),
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
