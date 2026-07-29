from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sysconfig
import tomllib
import venv


REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = REPO_ROOT / "szop_client"
SOURCE_ARTIFACTS = (
    CLIENT_ROOT / "szop_client.egg-info",
    CLIENT_ROOT / "build",
    CLIENT_ROOT / "dist",
)


def test_editable_metadata_freezes_monorepo_mapping() -> None:
    metadata = tomllib.loads(
        (CLIENT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["build-system"] == {
        "requires": ["setuptools>=77,<84"],
        "build-backend": "setuptools.build_meta",
    }
    assert metadata["project"]["name"] == "szop-client"
    assert metadata["project"]["version"] == "0.1.0"
    assert metadata["project"]["requires-python"] == ">=3.13,<3.14"
    assert metadata["project"]["dependencies"] == [
        "pydantic>=2,<3",
        "PyYAML>=6,<7",
        "SQLAlchemy>=2,<3",
    ]
    assert metadata["tool"]["setuptools"] == {
        "packages": ["szop_client"],
        "package-dir": {"": ".."},
    }


def test_editable_install_imports_from_outside_repo_without_io(tmp_path: Path) -> None:
    environment_root = tmp_path / "venv"
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    venv.EnvBuilder(
        with_pip=True,
        clear=True,
    ).create(environment_root)
    environment_python = (
        environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    environment_site_packages = _environment_site_packages(environment_python)
    parent_site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    (environment_site_packages / "_szop_client_test_dependencies.pth").write_text(
        str(parent_site_packages),
        encoding="utf-8",
    )
    before = {path: path.exists() for path in SOURCE_ARTIFACTS}
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PIP_")
    }
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_BUILD_ISOLATION": "0",
            "PIP_NO_DEPS": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SZOP_EXPECTED_REPO_ROOT": str(REPO_ROOT),
        }
    )

    try:
        install = subprocess.run(
            [
                str(environment_python),
                "-m",
                "pip",
                "install",
                "-e",
                r".\szop_client",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert install.returncode == 0, install.stdout + install.stderr

        smoke = subprocess.run(
            [str(environment_python), "-I", "-X", "utf8", "-c", _SMOKE_SCRIPT],
            cwd=outside_cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert smoke.returncode == 0, smoke.stdout + smoke.stderr
        assert json.loads(smoke.stdout) == {
            "distribution": "0.1.0",
            "http_client": "HttpClient",
            "lazy_top_level": True,
            "shared_checkout": True,
        }
    finally:
        _remove_new_source_artifacts(before)


def _remove_new_source_artifacts(before: dict[Path, bool]) -> None:
    for path, existed_before in before.items():
        if existed_before or not path.exists():
            continue
        resolved = path.resolve()
        if CLIENT_ROOT.resolve() not in resolved.parents:
            raise AssertionError(f"refusing to remove artifact outside client root: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _environment_site_packages(environment_python: Path) -> Path:
    result = subprocess.run(
        [
            str(environment_python),
            "-X",
            "utf8",
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    path = Path(result.stdout.strip()).resolve()
    if environment_python.parent.parent.resolve() not in path.parents:
        raise AssertionError(f"temporary site-packages escaped its venv: {path}")
    return path


_SMOKE_SCRIPT = r"""
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import sys


def forbid_database_open(*args, **kwargs):
    raise AssertionError("client import/construct attempted to open SQLite")


sqlite3.connect = forbid_database_open
repo_root = Path(os.environ["SZOP_EXPECTED_REPO_ROOT"]).resolve()

import szop_client

assert not any(
    name == "app" or name.startswith(("app.", "sqlalchemy", "fastapi"))
    for name in sys.modules
)

from szop_client import (
    ActivationMutationResult,
    BattleActionProposal,
    BattleInviteMetadata,
    BattleMetadata,
    BattleReplayResult,
    BattleStateCheckpoint,
    HttpClient,
    HttpClientError,
    HttpRequest,
    HttpResponse,
    SimulationSummary,
)

client = HttpClient("http://127.0.0.1:8000", token="not-used")
assert type(client).__name__ == "HttpClient"
assert all(
    value is not None
    for value in (
        HttpClientError,
        ActivationMutationResult,
        BattleActionProposal,
        BattleInviteMetadata,
        BattleMetadata,
        BattleReplayResult,
        BattleStateCheckpoint,
        HttpRequest,
        HttpResponse,
        SimulationSummary,
    )
)
assert not any(
    name.startswith(("app.db", "app.models", "sqlalchemy", "fastapi"))
    for name in sys.modules
)

import app

assert Path(szop_client.__file__).resolve().parent == repo_root / "szop_client"
assert Path(app.__file__).resolve().parent == repo_root / "app"
print(
    json.dumps(
        {
            "distribution": importlib.metadata.version("szop-client"),
            "http_client": type(client).__name__,
            "lazy_top_level": True,
            "shared_checkout": True,
        },
        sort_keys=True,
    )
)
"""
