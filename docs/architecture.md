# Architecture

## Model danych i dziedziczenie

- **Armie i Rozpiski wspierają hierarchię i dziedziczenie.** Wariant trzyma tylko różnice względem bazy (nie duplikuj pełnego stanu).
- **Stabilne identyfikatory** — jeśli obiekt już istnieje, zachowaj jego ID. Zmiana modelu musi uwzględniać wpływ na warianty potomne.
- **Nie duplikuj stanu** — jeśli wystarczą nadpisania, używaj ich.
- Zmiana modelu = audyt warstw: `app/models.py` → migracje Alembic → routery → JS render → testy parity.

## Baza danych

- SQLite, `data/szop.db`.
- Traktuj bazę jako **środowisko testowe, ale współdzielone**.
- **Nigdy nie wykonuj destrukcyjnych operacji** bez wyraźnego polecenia. Zawsze trzymaj kopię zapasową.
- **Wersja w git jest źródłem prawdy** — przywracaj przez:
  ```bash
  git show <commit>:seeds/szop.db.seed > data/szop.db
  ```
- **Migracje:** jeśli zadanie wymaga zmian schematu, opisz wpływ i przygotuj migrację Alembic.
- **Preview = baza produkcyjna:** przed udostępnieniem Preview do akceptacji podłącz `data/szop.db` z danymi. Pusta baza dyskwalifikuje preview.

## Uprawnienia

Dwa poziomy: `admin` i `user`. Funkcje administracyjne **jawnie odseparowane** od user-flow. Nie rozszerzaj uprawnień usera bez wyraźnego wymagania.

## Dokumentacja reguł gry — read-only

Pliki w `app/static/docs/`:
- **Nie modyfikuj** bez osobnego zadania.
- Jeśli kod i dokumentacja są sprzeczne — **zatrzymaj się i opisz rozbieżność**, nie zgaduj znaczenia reguły.

## Pakiet `app/services/costs/` — mapa submodułów

SSOT silnika kosztów. Każda zmiana kosztów musi przechodzić przez te moduły — nie replikuj logiki inline w routerach ani w JS.

| Plik | Linie | Zawartość |
|------|-------|-----------|
| `_engine.py` | ~300 | Stałe, tabele, dataclassy (`PassiveState`, `AbilityCostComponents`), `_roster_unit_classification`, stubs importów |
| `primitives.py` | ~310 | Sekcja 4: `ability_identifier`, `normalize_name`, `_strip_role_traits` |
| `weapons.py` | ~317 | Sekcja 6: `_weapon_cost`, `weapon_cost_components`, `weapon_cost` |
| `abilities.py` | ~372 | Sekcja 5: `passive_cost`, `base_model_cost`, `ability_cost_from_name` |
| `passive_state.py` | ~347 | Sekcja 3: `compute_passive_state`, helpery army/passive |
| `unit_helpers.py` | ~351 | Sekcja 7: `ability_cost`, `unit_default_weapons`, `normalize_roster_unit_loadout` |
| `role_totals.py` | ~471 | Sekcja 9: `roster_unit_role_totals` |
| `quote.py` | ~314 | Sekcja 8: `calculate_roster_unit_quote` — **SSOT core** |
| `roster.py` | ~127 | Sekcja 10: `roster_unit_cost`, `recalculate_roster_costs` |

**Reguła SSOT:** zanim dodasz logikę klasyfikacji / kosztów / walidacji w nowym miejscu — `grep` dla istniejących funkcji (`_classification_map`, `roster_unit_role_totals`, `calculate_roster_unit_quote`) i **wywołaj istniejącą**, nie replikuj.

**Circular imports w `costs/`:** jeśli nowy moduł importuje z `_engine`, a `_engine` importuje z nowego modułu — to jest **OK**, bo stałe/dataclassy są definiowane w `_engine` przed stubem `from .nowy_modul import`.

## Frontend JS — mapa modułów

Aktualna mapa zależności i lista call sites po podziale `app/static/js/app.js`: `docs/frontend_js_modules.md`.

**Pozostałe w `app.js`** (nie wydzielone): `ROSTER EDITOR CLOSURE`, `WEAPON PICKER`, `ABILITY PICKER`, `ARMORY WEAPON TREE`, `WEAPON INHERITANCE PANEL`. Detale: `docs/app-js-guide.md`.

## Hot path / endpoint'y krytyczne

Te endpointy mają największy wpływ na user-perceived performance — każda zmiana wymaga performance gate (`docs/planning.md`):

- `/quote` — kalkulacja kosztu rozpiski (batch dla wszystkich oddziałów na liście).
- `/rosters/{id}` — render strony rozpiski (SSR + post-load batch quote).
- Pętle renderujące strony z listą oddziałów.

Baseline wydajności i benchmarki: `docs/PERFORMANCE.md`.

## Konwencja `include_item_costs`

Badge-only calls do `/quote` zawsze przekazują `include_item_costs: false`. Tylko **dedykowany quote aktywnego oddziału** w `handleStateChange` przekazuje `true`. Naruszenie tej reguły przywróci wielokrotnie wolniejsze badge refresh.
