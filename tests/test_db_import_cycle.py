"""Regresja: `import app.db` nie może zależeć od kolejności importu modułów.

Historycznie `app/db.py` importował `from .services import ability_registry,
costs` na poziomie modułu. `ability_registry` ładuje `app.models`, które
importuje `Base` z `app.db` — gdy `app.db` był pierwszym importowanym modułem
pary (np. standalone skrypty silnika z `--from-db`), `Base` nie był jeszcze
zdefiniowany i import wybuchał `ImportError`. Fix: lazy-import w `init_db()`.

Testy uruchamiają ŚWIEŻY interpreter (subprocess), bo sesja pytest ma już
zaimportowane `app.*` — cykl ujawnia się tylko przy zimnym imporcie. Żaden
test nie woła `init_db()` (sam import modułu nie dotyka pliku bazy).
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_fresh(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_import_app_db_first_does_not_cycle():
    """`import app.db` jako pierwszy moduł aplikacji eksponuje `Base` bez cyklu."""
    result = _run_fresh("import app.db; assert app.db.Base is not None")
    assert result.returncode == 0, result.stderr
    assert "ImportError" not in result.stderr
    assert "circular import" not in result.stderr


def test_import_app_db_then_models_consistent_base():
    """`Base` jest tym samym obiektem niezależnie od kolejności db/models."""
    result = _run_fresh(
        "import app.db, app.models; "
        "assert app.models.Base is app.db.Base"
    )
    assert result.returncode == 0, result.stderr


def test_init_db_still_resolves_lazy_imports():
    """Lazy-import w `init_db` nie psuje dostępności `ability_registry`/`costs`."""
    result = _run_fresh(
        "import app.db; "
        "from app.services import ability_registry, costs; "
        "assert hasattr(ability_registry, 'sync_definitions'); "
        "assert hasattr(costs, 'weapon_cost')"
    )
    assert result.returncode == 0, result.stderr
