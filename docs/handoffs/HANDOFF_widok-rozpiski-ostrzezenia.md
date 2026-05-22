# HANDOFF — widok-rozpiski-ostrzezenia

> **Wątek:** Wskaźnik ostrzeżeń (⚠ + tooltip) po liczniku oddziałów/bohaterów w edytorze rozpiski + cleanup martwej infrastruktury banner-warnings w backendzie.
> **Status:** Completed
> **Utworzony:** 2026-05-20
> **Ostatnia aktualizacja:** 2026-05-22

## Cel

Dodać kompaktowy znacznik `⚠ N` po nagłówku `Oddziały w rozpisce (X, bohaterów Y)`, który po najechaniu pokazuje listę aktywnych ostrzeżeń (8 reguł: liczba oddziałów <4/>8, bohaterowie 0/>4, przekroczony limit punktów, 4× nierównowaga cenowa najtańszy↔najdroższy frame, mało/dużo broni vs wytrzymałość). Recompute on-the-fly w JS, dane z DOM/`unit_payloads`. Przy okazji usunąć martwe `"warnings": []` z `rosters.py` (3 linie) i osieroconą funkcję `collect_roster_warnings()` z `rules.py`.

Plan szczegółowy: `C:\Users\mlis\.claude\plans\w-widoku-rozpiski-dodaj-mighty-oasis.md`.

## Zablokowane pliki / katalogi

- `app/templates/roster_edit.html` — wstawienie znacznika + atrybut `data-unit-weapon-cost`
- `app/static/js/modules/roster_warnings.js` — NOWY moduł
- `app/static/js/modules/roster_editor.js` — 2 linie hook (współ-blokada z primary-weapon-flag, diffy ortogonalne)
- `app/routers/rosters.py` — cleanup `warnings: []` + dodanie `weapon_cost` w `roster_items.append` (współ-blokada z primary-weapon-flag, diffy ortogonalne)
- `app/services/rules.py` — usunięcie martwej `collect_roster_warnings()`

## Blokuje / Blokowane przez

- **Blokuje:** nic
- **Blokowane przez:** **primary-weapon-flag** współ-blokuje `roster_editor.js` i `rosters.py`. Diffy mają być małe (< 5 linii) i ortogonalne (warnings hook vs primary_weapon w loadout). Koordynacja przez tę notatkę: oba wątki edytują różne sekcje plików.

## Gałąź git

- **Branch:** `Rozwoj`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Backend: expose weapon_cost (cleanup ZMIENIONY)

- [x] Krok 1.1: w `rosters.py` (`roster_items.append`, ~linia 622) dorzucić `"weapon_cost": _roster_unit_classification_weapon_cost(...)` — formuła `(melee + ranged + max(melee, ranged)) / 2`. Helper `_roster_unit_weapon_components_sum` używa `costs.weapon_cost_components` per weapon × count.
- [x] Krok 1.2: **NIE usuwamy** `"warnings": []` z 3 słowników odpowiedzi. Klucz jest częścią kontraktu AJAX — `tests/test_frontend_backend_tables_parity.py:88` asertuje `set(payload) == {"unit", "units", "warnings", "total_cost"}`.
- [x] Krok 1.3: **NIE usuwamy** `collect_roster_warnings()` z `rules.py`. Funkcja jest importowana przez `tests/test_rosters_from_fixtures.py:21` i udokumentowana w `README_INTEGRATION.md` jako publiczne API. Mimo że obecnie nie jest aktywnie asertowana w teście, jest częścią publicznego kontraktu.
- [x] Krok 1.4: `pytest -q` zielony (176/176).

**Odkrycie 2026-05-20:** w UI **NIE MA** istniejącego banera ostrzeżeń do usunięcia. Eksploracja inicjalna źle zinterpretowała `warnings: []` jako "leftover banner infra". W rzeczywistości: szablon `roster_edit.html` nigdy nie renderował tych warningów, klucz `warnings` w payloadzie jest dormant ale otestowany jako część kontraktu. Nowy moduł `roster_warnings.js` to **pierwsza** realna implementacja ostrzeżeń w UI.

### Faza 2 — Frontend: szablon + atrybut

- [x] Krok 2.1: `roster_edit.html` linia 185 — wstawić `<span data-roster-warnings>` z badge i tooltipem (template).
- [x] Krok 2.2: makro `roster_unit_card` — dodać `data-unit-weapon-cost="{{ item.weapon_cost }}"` na `[data-roster-item]`.
- [x] Krok 2.3: dodać `<script src="/static/js/modules/roster_warnings.js">` w `base.html` (po `roster_editor.js`).

### Faza 3 — Moduł `roster_warnings.js`

- [x] Krok 3.1: szkielet IIFE + `window.SZOPRosterWarnings = { mount, recompute }`.
- [x] Krok 3.2: helper `getFrames()` — agregacja top-level + attached heroes (totalCost, totalToughness, totalWeaponCost).
- [x] Krok 3.3: 8 warunków + escapowane renderowanie listy.
- [x] Krok 3.4: inicjalizacja Bootstrap Tooltipa wzorem z `battle_state.js:442-449`.
- [x] Krok 3.5: feature flagi `window.SZOP_ROSTER_WARNINGS_ENABLED` / `_HEAVY_ENABLED`.

### Faza 4 — Hooki recompute

- [x] Krok 4.1: w `roster_editor.js` — `window.SZOPRosterWarnings?.recompute()` po `updateTotalSummary()` i `refreshRosterCountDisplay()`.
- [x] Krok 4.2: aktualizacja `data-unit-weapon-cost` w `applyServerUpdate` (po `data-base-cost-per-model`).
- [x] Krok 4.3: `data-unit-weapon-cost` w `roster_rendering.js` dla JS-dodawanych pozycji.
- [x] Krok 4.4: `mount()` na `DOMContentLoaded` w samym module.

### Faza 5 — Weryfikacja end-to-end

- [x] `pytest -q` zielony (176/176).
- [x] `node --check` — Node.js niedostępny na maszynie, JS zweryfikowany manualnie.
- [x] Smoke: roster/3 (3 oddziały, 0 bohaterów, przekroczony limit) → badge ⚠3, tooltip poprawny.
- [x] Smoke: roster/13 (5 oddziałów, 2 bohaterów, poniżej limitu) → badge ukryty (0 ostrzeżeń).
- [x] Zero błędów/ostrzeżeń w konsoli przeglądarki.
- [x] BUG FIX weapon_cost: `pytest -q` 176/176 po poprawce `_roster_unit_weapon_components_sum`.

## Pliki dotknięte

*(uzupełniane w trakcie)*

## Hipotezy / pytania otwarte

- Czy `weapon_cost_components()` zwraca per‑model czy per‑unit-total? Zweryfikować przy implementacji Fazy 1.1 (czytanie kontekstu w `_classification_map`).
- Czy `collect_roster_warnings()` ma testy w `tests/`? Sprawdzić przed usunięciem.

## Jak zweryfikować

```powershell
python -m pytest -x --tb=short -q
node --check app/static/js/modules/roster_warnings.js
# make dev → otworzyć /rosters/<id> → przejść 7 scenariuszy ze smoke testu w planie
```

## Decyzje

- 2026-05-20: weapon_cost = `(melee + ranged + max(melee, ranged)) / 2` — formuła efektywna z klasyfikacji, nie surowa suma. Bez mnożenia przez count (klasyfikacja już sumuje per-unit).
- 2026-05-20: ostrzeżenie 4× droższy — tylko jedna skrajna para (max, min), nie wszystkie pary.
- 2026-05-20: bohaterowie dołączeni — wliczani do framu we wszystkich warunkach (cost, toughness, weapon_cost).

## Notatki / odkrycia w trakcie

- 2026-05-20: HANDOFF utworzony po zatwierdzeniu planu przez usera.
- 2026-05-22: BUG FIX — `_roster_unit_weapon_components_sum` używał `_unit_army_flags(unit)` który zawierał slug roli (`strzelec`) z `unit.flags`, skutkiem czego `_weapon_cost` premat­uralnie dzielił koszt broni białej o 0.5. Naprawiono: zastąpiono `_unit_army_flags` + `flags_to_ability_list` wywołaniem `costs.compute_passive_state(unit, loadout)` + `costs._strip_role_traits(ps.traits)` — dokładnie jak robi to `roster_unit_role_totals`. Efekt: dla Widmy (3 modele, 2 bronie ×3) wynik zmienił się z 51.94 → 98.17 (zgodne z oczekiwaniem użytkownika ≈98.16).
