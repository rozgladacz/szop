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
**BRAK AKTYWNEGO ZADANIA** — restrukturyzacja `costs/` zakończona 2026-05-02.
Czekam na nowe polecenie użytkownika.

## W toku
—

## Pliki dotknięte
—

## Hipotezy / pytania otwarte
—

## Jak zweryfikować
```bash
python -m pytest tests/ -q   # 143/143 — baseline po zakończeniu restrukturyzacji
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

## Monkeypatching guide

- `costs.weapons._weapon_cost` — formuła kosztu broni
- `costs.role_totals.compute_passive_state` — passive state wewnątrz role totals
- `costs.quote.compute_passive_state` — passive state wewnątrz quote
- `costs.quote.roster_unit_role_totals` — role totals wewnątrz quote

## Performance baseline (rosters/10)

- Total: ~334 ms, Chmiera: ~70 ms (po optymalizacjach 2026-04-30)
- Badge-only refresh (`include_item_costs=False`): ~3 ms/oddział

---

# LOG SESJI
*(Dopisuj na górze. Zachowaj max ~5 ostatnich wpisów — starsze usuń lub skróć do jednej linii.)*



### 2026-05-02 — Ekstrakcja role_totals.py + quote.py; naprawa błędów poprzedniej sesji

**Cel:** Dokończyć restrukturyzację — sekcje 8 i 9 ostatnie żywe bloki w `_engine.py`.

**Diagoza zmarnowanego kontekstu (poprzednia sesja):**
1. `Write` tool z 400-liniowym ciałem `roster_unit_role_totals` — weszło do kontekstu.
2. `Edit` zastąpił tylko 6 pierwszych linii sekcji → ciało zostało jako `_roster_unit_role_totals_DELETED`.
3. Sesja skończyła się przed aktualizacją HANDOFF.md.

**Wykonane:**
- `role_totals.py` — już istniał z poprzedniej sesji (310 linii, poprawny).
- `_engine.py` — Python text-surgery usunął martwą `_roster_unit_role_totals_DELETED` (~409 linii).
- `quote.py` — Python text-surgery skopiował sekcję 8 z `_engine.py`; ciało nigdy nie weszło do kontekstu.
- `_engine.py` sekcja 8 → stub `from .quote import calculate_roster_unit_quote`.
- `__init__.py` — dodano `role_totals`, `quote`; zaktualizowany docstring.
- `tests/test_passive_costs.py:572` — patch zmieniony na `costs.role_totals.compute_passive_state`; zbędna łatka `ability_cost_from_name` (nigdy nie działała — `ability_cost_components_from_name` rozwiązuje `ability_cost_from_name` przez własne globals `abilities.py`, nie przez `role_totals`) usunięta z wyjaśnieniem.
- `AGENTS.md` — nowa sekcja "Przenoszenie dużych bloków kodu", poprawka HANDOFF zasady, stała referencja `costs.py` → `costs/_engine.py`.

**Weryfikacja:**
- `python -m pytest tests/ -q` → **143/143 passed**.

---

### 2026-05-01 — Ekstrakcja passive_state.py + unit_helpers.py + roster.py

> *Wpis dopisany retrospektywnie — sesja wybiła limit kontekstu przed aktualizacją HANDOFF.md.*

**Cel:** Wyciągnąć sekcje 3, 7, 10.

**Wykonane:**
- `passive_state.py` — `compute_passive_state`, `army_rules`, `normalize_roster_unit_count`, helpery payload/counts.
- `unit_helpers.py` — `unit_default_weapons`, `ability_cost`, `ability_uses_order_like_cost`, `normalize_roster_unit_loadout`, `unit_total_cost`.
- `roster.py` — `roster_unit_cost`, `recalculate_roster_costs`, `roster_total`, `ensure_cached_costs`, `update_cached_costs`.
- `_engine.py` sekcje 3, 7, 10 → stuby importów.
- `__init__.py` — dodano `passive_state`, `unit_helpers`, `roster`.

**Weryfikacja:**
- `pytest tests/ -q` → 143/143. Profile: Chmiera ~70 ms, total ~352 ms.

---

### 2026-05-01 — Ekstrakcja weapons.py + abilities.py
`weapons.py` (sekcja 6), `abilities.py` (sekcja 5+6 shims). Kluczowe: mutual dependency rozwiązana kolejnością (weapons first, abilities importuje weapon_cost). Patch `costs.weapons._weapon_cost` zamiast `costs._engine._weapon_cost`. 143/143.

### 2026-04-30 — Rozbicie costs.py → pakiet costs/
`costs.py` → `costs/_engine.py` (git mv) + `__init__.py` (re-eksport API) + `primitives.py` (sekcja 4). Wzorzec ekstrakcji z re-importem przez globals `_engine` potwierdzony. 143/143.

### 2026-04-30 — Optymalizacja cost engine
`lru_cache` na `normalize_name` + `ability_identifier`. Hoisting + memoizacja w `roster_unit_role_totals`. Wynik: Leman Russ 4480 ms → 41 ms, Chmiera kilkanaście s → 55 ms. Badge-only: 3 ms. 143/143.

**Pominięte i odłożone:**
- A2 — `selectinload(Weapon.parent).selectinload(Weapon.parent)` w `_unit_eager_options`
  okazał się intencjonalnym dziadkiem (`utils.py:207-209`), nie duplikatem.
- B3 — skip render gdy zmienia się tylko `count`. Niepotrzebne po B1.
- C1 — lazy unit_payloads + AJAX endpoint. Osobne zadanie, niższy priorytet.
