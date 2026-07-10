"""Regression guard for Starlette `TemplateResponse` call signatures."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"


def _is_template_response_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "TemplateResponse"
    if isinstance(node.func, ast.Name):
        return node.func.id == "TemplateResponse"
    return False


def _uses_request_first_signature(call: ast.Call) -> bool:
    if call.args:
        first_arg = call.args[0]
        return isinstance(first_arg, ast.Name) and first_arg.id == "request"
    return any(keyword.arg == "request" for keyword in call.keywords)


def _dict_has_request_key(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "request" for key in node.keys
    )


def _has_inline_request_context(call: ast.Call) -> bool:
    return any(_dict_has_request_key(arg) for arg in call.args[1:]) or any(
        keyword.arg == "context" and _dict_has_request_key(keyword.value)
        for keyword in call.keywords
    )


def test_template_response_uses_request_first_signature() -> None:
    findings: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not _is_template_response_call(node):
                continue
            location = f"{path.relative_to(ROOT)}:{node.lineno}"
            if not _uses_request_first_signature(node):
                findings.append(f"{location}: first argument must be request")
            if _has_inline_request_context(node):
                findings.append(f'{location}: remove redundant "request" context key')

    assert not findings, "Old TemplateResponse signature remains:\n" + "\n".join(findings)
