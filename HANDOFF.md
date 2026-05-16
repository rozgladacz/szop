# HANDOFF

> **Protokół przy ZMIANIE ZADANIA:** Na początku nowego zadania (jeśli
> sekcja BIEŻĄCE ZADANIE opisuje inny cel) — nadpisz całą sekcję
> BIEŻĄCE ZADANIE. Sekcji WIEDZA PROJEKTU nie czyść — to trwała
> referencja. Dopisz wpis do Logu.
>
> **Protokół przy KONTYNUACJI:** Aktualizuj PRZED każdym podetapem,
> nie po sesji — kontekst może się skończyć w trakcie pracy.

---

# BIEŻĄCE ZADANIE
*(Nadpisz tę sekcję przy każdej zmianie zadania)*

## Cel
Faza III refaktoryzacji `app/static/js/app.js`: wydzielenie 8 sekcji pomocniczych do modułów IIFE bez ruszania `ROSTER EDITOR CLOSURE`.

## W toku
- Ekstrakcja modułów wykonana.
- Call-site check, `node --check` i sandbox load-test JS przeszły.
- Pytest/smoke dev zablokowane lokalnym runtime: `make`/`pytest` poza PATH, `.venv\Scripts\python` wskazuje na WindowsApps Python z odmową dostępu; eskalacja została odrzucona przez limit aplikacji.
- Warstwy: JS moduły, `app.js`, `base.html`, testy Node/frontend, mapa zależności/call sites.

## Pliki dotknięte
- `app/static/js/app.js`
- `app/static/js/modules/*`
- `app/templates/base.html`
- `tests/test_frontend_*.py`
- `docs/frontend_js_modules.md`
- `HANDOFF.md`

## Hipotezy / pytania otwarte
- Moduły pozostają jako IIFE publikujące API na `window`.
- `initRosterEditor`, `WEAPON PICKER`, `ABILITY PICKER`, `ARMORY WEAPON TREE`, `WEAPON INHERITANCE PANEL` zostają w `app.js`.

## Jak zweryfikować
```bash
make test
python -m pytest tests/test_frontend_loadout_state.py tests/test_frontend_payload_adapters.py tests/test_frontend_roster_refresh_priority_regression.py -q
pytest -q
# manual smoke: make dev -> Zbrojownia / Edytor Armii / Rozpiski
```

---

# WIEDZA PROJEKTU
*(Nie czyść przy zmianie zadania — aktualizuj tylko gdy architektura się zmienia)*

## Pakiet `app/services/costs/` — mapa submodułów

| Plik | Linie | Zawartość |
|------|-------|-----------|
| `_engine.py` | ~300 | Stałe, tabele, dataclassy (`PassiveState`, `AbilityCostComponents`), `_roster_unit_classification`, stubs importów |
| `primitives.py` | ~310 | Sekcja 4: `ability_identifier`, `normalize_name`, `_strip_role_traits` |
| `weapons.py` | ~317 | Sekcja 6: `_weapon_cost`, `weapon_cost_components`, `weapon_cost` |
| `abilities.py` | ~372 | Sekcja 5: `passive_cost`, `base_model_cost`, `ability_cost_from_name` |
| `passive_state.py` | ~347 | Sekcja 3: `compute_passive_state`, helpery army/passive |
| `unit_helpers.py` | ~351 | Sekcja 7: `ability_cost`, `unit_default_weapons`, `normalize_roster_unit_loadout` |
| `role_totals.py` | ~471 | Sekcja 9: `roster_unit_role_totals` |
| `quote.py` | ~314 | Sekcja 8: `calculate_roster_unit_quote` (SSOT core) |
| `roster.py` | ~127 | Sekcja 10: `roster_unit_cost`, `recalculate_roster_costs` |

## Frontend JS — mapa modułów

- Aktualna mapa zależności i lista call sites po podziale `app/static/js/app.js`: `docs/frontend_js_modules.md`.
- `ROSTER EDITOR CLOSURE`, `WEAPON PICKER`, `ABILITY PICKER`, `ARMORY WEAPON TREE`, `WEAPON INHERITANCE PANEL` nadal mieszkają w `app.js`.

---

# LOG SESJI

### 2026-05-12 — Start zadania: modularizacja app.js
- Zamknięto poprzedni stan "BRAK AKTYWNEGO ZADANIA".
- Nowy cel: sekcyjna ekstrakcja `app.js` z zachowaniem 1:1 i pełną weryfikacją parity/smoke.

### 2026-05-13 — Przejście do Fazy II payload adapters
- Zamknięto etap startowej modularizacji jako kontekst bazowy.
- Nowy cel: adaptery i walidatory payloadów przed dalszym podziałem `app.js`.

### 2026-05-14 — Faza II payload adapters zakończona
- Dodano `payload_adapters.js`, flagę `window.SZOP_DEV_MODE`, podpięcia w `app.js` i testy regresyjne.
- Weryfikacja automatyczna: `tests/test_frontend_payload_adapters.py`, istniejące testy frontendowe oraz pełne `pytest -q` przeszły.
- Smoke przeglądarkowy wymaga ręcznej akceptacji w UI, bo automatyczna przeglądarka została zablokowana przez uprawnienia środowiska.

### 2026-05-14 — Start Fazy III modułów pomocniczych app.js
- Zamknięto poprzedni cel Fazy II jako bazę roboczą.
- Nowy cel: 8 małych ekstrakcji sekcji bez zmian zachowania kosztów, loadoutu i bootstrap order.

### 2026-05-14 — Faza III modułów pomocniczych app.js zaimplementowana
- Wydzielono sekcje: text parsing, UI pickers, spell weapon preview, spell ability forms, roster rendering, loadout state, editor renderers, roster adders.
- Dodano `docs/frontend_js_modules.md` jako mapę zależności i call-site checklist.
- Weryfikacja wykonana: `node --check` dla nowych modułów i `app.js`, sandbox load-test modułów + `app.js`, call-site grep.
- Weryfikacja zablokowana: pytest/full smoke przez niedostępny Python/make w lokalnym środowisku.
