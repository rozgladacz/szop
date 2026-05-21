# Testing

## Reguła ogólna

**Po każdej zmianie kodu uruchom testy. Nawet jednolinijkowej.**

PostToolUse hook wymusza pytest po edycjach `.py` — **nie suppressuj jego output**. Zignorowanie tej reguły = top friction category (11 hits, "tests skipped before declaring done").

## Kolejność uruchamiania — zawsze ta sama

### 1. Natychmiast po zmianie — tylko dotknięty plik lub moduł

```bash
python -m pytest tests/test_roster_classification.py -x --tb=short -q
```

Szybki feedback zanim pójdziesz dalej. Jeśli tu nie przejdzie — nie ma sensu uruchamiać reszty.

### 2. Przed deklaracją "gotowe" — filtruj po obszarze

```bash
python -m pytest -k "roster or cost or classification" -x --tb=short
```

### 3. Przed commitem — pełna suita, obowiązkowo

```bash
python -m pytest --tb=short -q
```

## Środowisko Windows

`make` może być poza PATH (znany problem — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu). Używaj bezpośrednio:

```bash
python -m pytest -x --tb=short -q          # szybki, stop na pierwszym błędzie
python -m pytest -x --tb=short -q <plik>   # fokusowany na jeden plik
```

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
- Windows fallback: `python -m pytest -x --tb=short -q`
