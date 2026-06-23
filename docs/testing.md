# Testing

## Reguła ogólna

**Po każdej zmianie kodu uruchom testy. Nawet jednolinijkowej.**

PostToolUse hook wymusza pytest po edycjach `.py` — **nie suppressuj jego output**. Zignorowanie tej reguły = top friction category (11 hits, "tests skipped before declaring done").

## Kolejność uruchamiania — zawsze ta sama

### 1. Natychmiast po zmianie — tylko dotknięty plik lub moduł

```bash
python -X utf8 -m pytest tests/test_roster_classification.py -x --tb=short -q
```

Szybki feedback zanim pójdziesz dalej. Jeśli tu nie przejdzie — nie ma sensu uruchamiać reszty.

### 2. Przed deklaracją "gotowe" — filtruj po obszarze

```bash
python -X utf8 -m pytest -k "roster or cost or classification" -x --tb=short
```

### 3. Przed commitem — pełna suita, obowiązkowo

```bash
python -X utf8 -m pytest --tb=short -q
```

## Środowisko i uruchamianie (Windows / agenci)

**Uruchamiaj z roota repo.** Nie ma pliku konfiguracyjnego pytest (`pytest.ini`/`pyproject.toml`/`conftest.py`), więc `rootdir` = bieżący katalog — `import app.*` rozwiązuje się **tylko** gdy CWD = root repo.

**Interpreter:** globalny `python` (Python 3.13; zależności z `requirements-dev.txt`). **Brak `.venv`** w repo — nie używaj `.venv\Scripts\python`.

**[CRITICAL] Kodowanie — prefiksuj `-X utf8`.** W trybie nieinterakcyjnym (output przechwytywany przez agenta / hook / pipe) `python` ustawia `sys.stdout.encoding = cp1250` (locale Windows-PL) **nawet gdy `chcp` = 65001**. Pierwszy polski znak / strzałka / `INCH` (U+201D) w tracebacku → `UnicodeEncodeError`, co wygląda jak „testy nie działają" (typowy problem agenta uruchamiającego pytest bez `make`, np. Codex). Flaga `-X utf8` (UTF-8 mode, PEP 540) wymusza UTF-8 na stdio niezależnie od powłoki i code page:

```bash
python -X utf8 -m pytest -q --tb=short            # pełna suita
python -X utf8 -m pytest tests/test_x.py -x -q    # jeden plik
```

Alternatywa gdy nie chcesz flagi: `$env:PYTHONIOENCODING="utf-8"` (PowerShell) / `set PYTHONIOENCODING=utf-8` (cmd) przed komendą. `make` ustawia to globalnie (`export PYTHONIOENCODING=utf-8`), więc `make test` problemu nie ma — ale `make` bywa poza PATH, stąd preferuj `python -X utf8 -m pytest`.

## Przydatne flagi pytest

| Flaga | Kiedy użyć |
|---|---|
| `-x` | Zawsze — stop na pierwszym błędzie, nie czekaj na resztę |
| `--tb=short` | Domyślnie — czytelny traceback bez szumu |
| `-q` | Szybki przebieg — jedna linia per test, podsumowanie na końcu |
| `-v` | Debugging — pełna nazwa każdego testu + status |
| `-k "słowo"` | Filtruj testy po nazwie funkcji lub pliku (np. `-k "classification"`) |
| `--lf` | Uruchom ponownie tylko ostatnio nieudane — przy poprawianiu |
| `-s` | Pokaż `print()` w testach — tylko do debugowania, nie zostawiaj w commicie |

## Co jeszcze sprawdzić po zmianie

- **Po zmianie logiki** — uruchom testy związane z dotkniętym obszarem.
- **Po zmianie UI** — sprawdź stan pusty, błędny i podstawowy scenariusz.
- **Jeśli testów brakuje** — dodaj minimalny test regresji.
- **Nie uznawaj zadania za zakończone bez krótkiej weryfikacji diffu.**
- **Call-site check przed zamknięciem:** znajdź wszystkie call sites zmodyfikowanego kodu, wyjaśnij wpływ na każdy.

## Kiedy testy dezaktualizują się

Jeśli zmieniasz zachowanie funkcji — **najpierw** sprawdź czy istniejące testy testują stare zachowanie. Jeśli tak: **popraw testy jako pierwszy krok**, zanim zmienisz kod produkcyjny. Stare testy blokują dalszą pracę i generują fałszywe błędy.

## Testy frontendu — payload parity

Pliki `tests/test_frontend_*.py` weryfikują payload parity (JS ↔ backend). Uruchom je **po każdej zmianie** w:

- `app/routers/rosters.py`
- `app/services/costs/*` (cokolwiek SSOT)
- `app/static/js/payload_adapters.js`
- `app/routers/export.py`

**Backend unit tests NIE pokrywają inicjalizacji JS** — smoke test manualny wymagany po zmianie `app.js`.

## Smoke test po zmianie `app/static/js/app.js`

Po każdej zmianie `app.js` uruchom aplikację (`make dev`) i **ręcznie** sprawdź:

1. **Zbrojownia** → czy lista broni jest widoczna?
2. **Edytor Armii** → czy przy dodaniu oddziału widoczne są bronie?
3. **Rozpiski** → czy można zaznaczyć oddział i czy otwiera się panel edytora?

Testy backendowe nie pokrywają inicjalizacji JS — te trzy scenariusze **muszą być sprawdzone ręcznie**. Bezpieczeństwo dla dużych plików: przed usunięciem funkcji z `app.js` zrób `grep -n "nazwaFunkcji" app/static/js/app.js` i zweryfikuj brak wywołań. W szczególności sprawdź łańcuch DOMContentLoaded (`docs/app-js-guide.md`).

## Diagnoza bugów UI

Przed analizą backendu **ustal pełną ścieżkę wywołania:** JS event → fetch → endpoint → render. Sprawdź czy wynik nie jest nadpisywany przez inny fetch po załadowaniu strony (np. batch `/quote` po renderowaniu SSR).

## Komendy projektu

- Test (wszystkie): `make test`
- Test (szybki, stop na pierwszym błędzie): `make test-fast`
- Lint: `make lint`
- Windows fallback: `python -X utf8 -m pytest -x --tb=short -q`

## A4 drift pipeline — `make rules-check`

Orchestrator pipeline'u drift detection (ADR-0006). Uruchamia 5 skryptów sekwencyjnie z fail-fast:

```bash
make rules-check                # full pipeline
make rules-sources-check        # SHA256 dla SZOP.docx/pdf/md×2
make rules-extract              # DOCX → build/rules_extracted.yaml
make rules-extract-md           # MD → build/rules_md.yaml
make rules-classify             # abilities.yaml → build/geometry_classification.md
make rules-drift                # DOCX vs YAML → build/drift_report.md
```

**Kolejność `rules-check`:** sources-check → extract → extract-md → classify → drift (drift LAST bo może wyjść z exit 2 WARN i zatrzymać chain — wszystkie inne artefakty wcześniej już zapisane).

**Exit codes:**
- `0` — clean (wszystko match, brak drift)
- `1` — ERROR (R1/R4 w drift, mismatch w sources, parse error w extract/classify)
- `2` — WARN-only (R2/R3 w drift, missing source files)

**Kiedy uruchamiać:**
- Po edycji `app/static/docs/SZOP.*` (DOCX, PDF, MD) — wykryje silent edits.
- Po edycji `app/rulesets/v1/*.yaml` — wykryje drift od source-of-truth.
- Po edycji `app/data/abilities.py` — pośrednio sprawdza spójność YAML mirror.
- W CI (planowane A4.6 GHA workflow `rules_drift.yml`).

Po świadomej edycji source files: `python scripts/rules_sources_check.py --update` regeneruje `app/rulesets/v1/source_hashes.yaml`.

Detale: [scripts/README.md](../scripts/README.md), [docs/adr/0006-pipeline-drift.md](adr/0006-pipeline-drift.md).
