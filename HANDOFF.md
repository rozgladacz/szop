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
Ekstrakcja sekcji `app/static/js/app.js` do modułów 1:1 (start od najniższego sprzężenia: refresh token/priority), bez zmian funkcjonalnych.

## W toku
- Przygotowanie modułów sekcyjnych i jawnego bootstrap chain.
- Integracja pierwszego modułu (`refresh_priority.js`) do `app.js`.
- Weryfikacja parity testami backend/frontend + smoke manualny.

## Pliki dotknięte
- `app/static/js/app.js`
- `app/static/js/modules/*`
- `app/templates/base.html`
- `HANDOFF.md`

## Hipotezy / pytania otwarte
- Czy loader jest non-module (`<script src=...>`), więc moduły muszą publikować API przez `window`.
- Pełna ekstrakcja closure `initRosterEditor` może wymagać etapowania.

## Jak zweryfikować
```bash
make test
python -m pytest tests/test_frontend_backend_tables_parity.py -q
python -m pytest tests/test_frontend_roster_refresh_priority_regression.py -q
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

---

# LOG SESJI

### 2026-05-12 — Start zadania: modularizacja app.js
- Zamknięto poprzedni stan "BRAK AKTYWNEGO ZADANIA".
- Nowy cel: sekcyjna ekstrakcja `app.js` z zachowaniem 1:1 i pełną weryfikacją parity/smoke.
