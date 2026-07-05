# HANDOFF — fastapi-lifespan

> **Wątek:** Migracja przedawnionego `@app.on_event("startup")` na handler `lifespan` (FastAPI/Starlette), domknięcie latentnego długu higieny odnotowanego w REVIEW_2026-07-05.
> **Status:** Ready for archive
> **Utworzony:** 2026-07-05
> **Ostatnia aktualizacja:** 2026-07-05

## Cel
FastAPI/Starlette deprecował dekorator `@app.on_event("startup")` na rzecz
context managera `lifespan=` przekazywanego do konstruktora `FastAPI(...)`.
Jedyne użycie w projekcie to `app/main.py:56` (`startup_event` → `init_db()` +
log). Celem jest mechaniczna migracja bez zmiany zachowania runtime (init_db
nadal woła się przy starcie ASGI), usuwając `DeprecationWarning` z sygnału
testów. To czysta higiena — brak zmian reguł gry, kosztów, schematu ani auth.

## Zablokowane pliki / katalogi
- `app/main.py` — migracja startup handlera (jedyny plik produkcyjny).

## Blokuje / Blokowane przez
- **Blokuje:** nic.
- **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Migracja startup handlera
- [x] Krok 1.1: dodać `from contextlib import asynccontextmanager` (+ `AsyncIterator`).
- [x] Krok 1.2: zdefiniować `lifespan(app)` PRZED `app = FastAPI(...)` (woła
  `init_db()` + log, `yield`); przekazać `lifespan=lifespan` do konstruktora.
- [x] Krok 1.3: usunąć blok `@app.on_event("startup") def startup_event`.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] Pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` — **2084 passed**, warnings 14→12 (zniknął `on_event` DeprecationWarning).
- [!] Smoke test JS — N/A (brak zmian `app.js`).
- [x] Call-site check — `startup_event`/`on_event` bez innych referencji (jedyne trafienie to niezwiązana nazwa testu `test_event_to_json_raises_for_non_event`).
- [x] `/simplify` — 0 zmian; kod idiomatyczny (wzorzec lifespan z docs FastAPI, param `app` wymagany przez sygnaturę).
- [!] `/review` — pominięty warunkowo (diff ~10 linii, brak hot path/SSOT/auth).
- [!] `/security-review` — N/A (brak auth/user input→DB; `init_db` bez zmian).
- [x] `git diff --check` — czysto; diff review OK (scope 1 plik prod).

## Pliki dotknięte
- `app/main.py` — `@app.on_event("startup")` → `@asynccontextmanager lifespan` przekazany do `FastAPI(lifespan=...)`; `init_db()` + log przeniesione do startup części lifespan (zachowanie 1:1). Smoke: `async with lifespan(app)` woła `init_db()` (potwierdzone).

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak)

## Hipotezy / pytania otwarte
- `READY`: migracja nie wymaga decyzji usera — mechaniczny 1:1 wzorzec FastAPI.

## Jak zweryfikować
```bash
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q
# sanity: import app.main bez błędu; startup wywołuje init_db przy starcie ASGI
```

## Decyzje
- 2026-07-05: migracja bez zmiany zachowania — `init_db()` nadal wykonuje się
  przy starcie aplikacji przez lifespan startup; brak nowych zależności.

## Notatki / odkrycia w trakcie
- 2026-07-05: brak testów używających `TestClient`/ASGI lifecycle — testy routerów
  wołają funkcje endpointów wprost, więc startup handler nigdy nie odpala się w
  suicie; migracja to czysta higiena produkcyjna bez wpływu na testy.
