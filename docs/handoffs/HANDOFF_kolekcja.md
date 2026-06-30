# HANDOFF — kolekcja

> **Wątek:** Kolekcja — śledzenie fizycznych modeli użytkownika i integracja z rozpiską. Faza 1 (CRUD) zakończona i scommitowana; Faza 2 (integracja z rozpiską) w toku, etap 2a gotowy.
> **Status:** In progress (Faza 2)
> **Utworzony:** 2026-06-17
> **Ostatnia aktualizacja:** 2026-06-29

## Cel

Użytkownik chce móc rejestrować posiadane fizyczne modele (miniatury) per oddział armii — z konkretnymi broniami, zdolnościami i opcjonalnymi slotami magnetyzacji. Faza 1 obejmuje wyłącznie warstwę kolekcji (CRUD modeli) bez integracji z kreatorem rozpiski. Integracja z rozpiską (tryb modeli, proxy, eliminowanie) to Faza 2 — osobny wątek.

## Zablokowane pliki / katalogi

- `app/models.py` — dodano nowe modele ORM
- `app/routers/collections.py` — nowy router (NEW)
- `app/routers/__init__.py` — rejestracja routera
- `app/main.py` — include_router
- `app/templates/base.html` — link nawigacyjny
- `app/templates/collections_list.html` — nowy szablon (NEW)
- `app/templates/collection_unit_detail.html` — nowy szablon (NEW)

## Blokuje / Blokowane przez

- **Blokuje:** Faza 2 (integracja kolekcji z kreatorem rozpiski — tryb modeli, proxy, eliminowanie)
- **Blokowane przez:** brak

## Gałąź git

- **Branch:** `Rozwoj`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Model danych
- [x] Krok 1.1: Dodać `CollectionModel` i `CollectionModelSlot` do `app/models.py`
- [x] Krok 1.2: Dodać `User.collection_models` relationship
- [x] Krok 1.3: Dodać obie klasy do event listenerów `touch_timestamps`
- [x] Krok 1.4: Potwierdzić że `create_all()` tworzy tabele (brak Alembic — nowe tabele tworzone automatycznie)

### Faza 2 — Backend router
- [x] Krok 2.1: `app/routers/collections.py` z endpointami GET /collections, GET /collections?army_id, GET /collections/units/{id}, POST add/update/delete
- [x] Krok 2.2: Rejestracja w `__init__.py` i `main.py`
- [x] Krok 2.3: Walidacja slotów magnetyzacji (opcje ∈ pula broni oddziału)
- [x] Krok 2.4: `_build_collection_card` z pełnym `loadout` dict (potrzebny do pre-fill edycji w JS)

### Faza 3 — Frontend
- [x] Krok 3.1: Link "Kolekcja" w `base.html`
- [x] Krok 3.2: Szablon `collections_list.html` (lista armii + oddziałów z licznikami)
- [x] Krok 3.3: Szablon `collection_unit_detail.html` — lista kart + formularz AJAX
- [x] Krok 3.4: Slot builder JS (dynamiczne dodawanie/usuwanie slotów magnetyzacji)
- [x] Krok 3.5: Edit mode JS (pre-fill formularza z `data-card` attr, `forceescape` XSS fix)
- [x] Krok 3.6: AJAX delete z potwierdzeniem

### Faza 4 — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — 222/222 passed (bez regresji)
- [!] Smoke test JS (nie dotyczy — kolekcja nie zmienia `app.js`, dedykowany JS inline w szablonie)
- [x] Call-site check: `CollectionModel`/`CollectionModelSlot` nowe — brak istniejących call sites do sprawdzenia; `User.collection_models` relacja nowa — cascade delete działa
- [x] `/simplify` — usunięto: dead code `_require_login`, `form_data` zmienną, wasted query reload, unreachable `name is None`; wyciągnięto `_parse_form_multi`; uproszczono `_safe_int` → inline loop
- [x] `/security-review` — znaleziono i naprawiono: IDOR w `GET /collections/units/{unit_id}` (brak sprawdzenia army ownership); fix: HTTPException 403 jeśli army.owner_id ≠ current_user.id
- [x] Re-run `pytest -q` po `/simplify` + `/security-review` — 222/222 passed
- [x] Diff review przed commitem — scommitowane w `199858b` ("Pomieszany", razem z innymi wątkami)

---

## Faza 2 — integracja z rozpiską (etapowo, dopasowanie wariantowe)

Plan: `~/.claude/plans/nowa-funkcjonalno-kolekcja-chcemy-wiggly-shore.md`. Decyzja: dopasowanie **wyliczane**; schemat dotyka tylko 2b (`RosterUnit.composed_models_json`). Dwa kierunki: **suma→modele** (2a/derived) i **modele→suma** (2b/compose, główna wartość).

### Etap 2a — Wskaźnik pokrycia (badge) — WYCOFANY
- Zbudowany (serwis `collection_match.py` + badge na karcie + 12 testów), ale **badge wycofany** na życzenie usera (2026-06-29): „plakietki" zaśmiecały listę „Oddziały w rozpisce". Pokrycie/modele mają być w prawym panelu za przyciskiem „Tryb modeli" (→ 2b).
- Zostaje: **serwis `app/services/collection_match.py`** (`model_variant_signature`, `build_collection_index`, `roster_needs`, `coverage_for_item`, + helpery 2b) + testy. Martwa logika pokrycia w `edit_roster` i badge w `roster_edit.html` usunięte.

### Etap 2b — Komponowanie oddziału z modeli (modele→suma, WRITE) ✅ v1 GOTOWE
Decyzja UX usera (2026-06-29): „Tryb modeli" w prawym panelu **zastępuje** edytor (przełącznik), ale **nagłówek (nazwa, Jakość/Obrona/Wytrzymałość) i zdolności pasywne zostają**. v1 bez proxy (komponujemy tylko z posiadanych modeli).
- [x] Kolumna `RosterUnit.composed_models_json` (TEXT, nullable) + migracja `app/db.py` (ALTER TABLE).
- [x] `collection_match`: `collection_model_effective_weapons` (broń bazowa + zamontowane sloty), `fetch_owned_models`, `describe_owned_models`.
- [x] `update_roster_unit`: + Form `composed_models_json` (zapis dla głównego oddziału; czyszczenie przy zwykłej edycji; guard `isinstance(str)` na sentinel `Form`).
- [x] Endpoint `GET /rosters/{id}/units/{ru_id}/collection-models` → JSON {models, composed, current_loadout, weapon_names, coverage}. Owner isolation + view-access.
- [x] `roster_edit.html`: przycisk „Tryb modeli" (`data-roster-models-toggle`), panel `data-roster-models-panel`, sekcje `data-models-hide` (liczność/aktywne/aury/wyposażenie; pasywne+nagłówek zostają).
- [x] `roster_collection_models.js` (NEW, samodzielny IIFE): wybór ilości per model, podgląd agregatu (count + broń), zapis przez update (broń + `mode=total` + `composed_models_json`) → reload. Rejestracja w `base.html`.
- [x] `tests/test_collection_match.py`: +`describe_owned_models`, +`fetch_owned_models` (izolacja). pytest 253/253.
- [x] Weryfikacja statyczna: `node --check` modułu OK, Jinja OK, app import + serwowanie strony/modułu OK.
- [x] **Smoke przeglądarkowy** — user potwierdził: „Jest ok w tym etapie" (2026-06-29). Poprawki z testu: autosave po zmianie, brak reloadu per zmiana (zaznaczenie zostaje), usunięte dolne przyciski, klasyczny edytor read-only w trybie modeli (konflikt autosave'ów).
- [x] `/simplify` — zastosowano klasę CSS `.roster-models-readonly` zamiast inline-style; reszta odrzucona (uproszczenia flag JS niepoprawne, ekstrakcje poza diffem); follow-up: agregacja serwerowa (wyżej).
- [x] `/security-review` — CLEAN. Dwa wstępne findingi (IDOR composed_models_json, weapon-injection) odfiltrowane 2/10: pierwszy echo'wany/inert, drugi pre-existing + self-affecting.
- [x] Commit `9390cd7` na `Rozwoj`.

**v1 ograniczenia / do 2b.1:** brak proxy (tylko posiadane modele); broń agregowana, aktywne/aury/pasywne zachowane z bieżącego loadoutu (nie pochodzą z modeli); zmiana wyboru oddziału w trybie modeli wraca do trybu klasycznego.

**Follow-up z `/simplify` (altitude, do 2b.1):** agregacja broni liczona po stronie JS, serwer ją tylko re-waliduje (`_sanitize_loadout`). Docelowo backend powinien liczyć loadout autorytatywnie z `composed_models_json` (JS = tylko podgląd). Nie jest to luka bezpieczeństwa (sanitize waliduje ID broni; zawyżone liczniki dotykają tylko własnej rozpiski usera), ale czystsza architektura. ~2h, nowy endpoint + testy. Pozostałe uwagi `/simplify` odrzucone jako niepoprawne (uproszczenia flag JS `savedSomething`/`pendingChanges` zepsułyby reset per-sesja / okno debounce) lub poza diffem (ekstrakcje do Fazy 1).

### Etap 2b.1 + 2b.2 — rozszerzenia kompozycji ✅ GOTOWE (commit `6830c92`)
Cztery braki zgłoszone przez usera przed 2c + dopracowanie UI.
- [x] **Agregacja serwerowa** (`compose_loadout`): gdy `update_roster_unit` dostaje `composed_models_json`, backend liczy broń+aktywne/aury+liczność autorytatywnie z selekcji; pasywne z klienta. Rozwiązuje follow-up F5.
- [x] **Zdolności z modeli**: `compose_loadout` agreguje aktywne/aury (bare id) z wybranych modeli i z proxy.
- [x] **Wspólna dostępność** (w obrębie rozpiski): `used_in_other_units` — `available` = posiadane − użyte w innych oddziałach; limit miękki (nadwyżka = proxy).
- [x] **Pasywne w panelu**: reuse `window.SZOPRosterRendering.renderPassiveEditor`; klasyczna sekcja pasywnych ukryta (jeden edytor).
- [x] **Derywacja v2** (`derive_composition`): zdolności-first → broń nie-podstawowa → podstawowa → dopełnienie; proxy z „domyślnego modelu" + brakująca zdolność + podmiana broni (`len(pw)>1`), bez zawyżania liczności.
- [x] **UI 2b.2**: ukrycie klasycznego formularza (luka w szerokim układzie), kolejność pasywne→podgląd→modele, brak linii przy braku nazwy, zdolności w opisie modelu (`broń • zdolności`), proxy ze zdolnościami round-trip.
- [x] `composed_models_json` v2: `{id,qty}` (owned) | `{id:null, weapons, abilities, qty}` (proxy).
- [x] DoD: pytest 266/266, `node --check`, `/simplify` (parsery, selectinload, cache, docstringi), commit `6830c92`. `/security-review` pominięty (decyzja usera — brak nowej powierzchni: ten sam endpoint + owner-iso co w 2b).
- **Ograniczenia / do dalej:** aury parametryzowane kolapsują do bare id; proxy swap-vs-add to heurystyka (`len(pw)>1`) — do dostrojenia per oddział jeśli trzeba; ręczne „Dodaj proxy" tylko broń (bez zdolności).

### Etap 2c — Eliminowanie fizycznych modeli w Stanie Bitewnym (localStorage) — TODO
- [ ] Sloty egzemplarzy z `composed_models_json` w kontekście `roster_battle_state` (`export.py`).
- [ ] `battle_state.js`: `eliminatedSlots`, render egzemplarzy, styl `.is-defeated`, synchronizacja z `activeModels`.

## Pliki dotknięte

- `app/models.py` — +`CollectionModel`, +`CollectionModelSlot`, +`User.collection_models`
- `app/routers/collections.py` — NEW: cały router kolekcji (ok. 280 linii)
- `app/routers/__init__.py` — dodano `collections` do importów i `__all__`
- `app/main.py` — dodano `collections` do importów i `include_router`
- `app/templates/base.html` — +link "Kolekcja" w nawigacji
- `app/templates/collections_list.html` — NEW: lista armii + oddziałów
- `app/templates/collection_unit_detail.html` — NEW: widok oddziału z formularzem i JS

## Hipotezy / pytania otwarte

- Czy zdolności (abilities) powinny być pokazywane w formularzu per typ (`passive`/`active`/`aura`) czy wszystkie razem? Obecna implementacja pokazuje wszystkie.
- W Fazie 2 (integracja rozpiski): jak liczyć kolekcję gdy ten sam unit pojawia się wielokrotnie w rozpisce? Decyzja z usera: "śledzić kolekcję wspólnie jeżeli jest kilka oddziałów jednego typu" — wymaga agregacji w Fazie 2.
- Przypisanie jednego fizycznego modelu do wielu armii/oddziałów: user nie ma jeszcze pomysłu na UX — odłożone poza Fazę 1 i 2.
- Markery (Sztandar itp.) — odłożone, w Fazie 1 to zwykła pozycja o koszcie 0.

## Jak zweryfikować

```bash
python -m pytest -x --tb=short -q
# Manualne smoke:
# 1. /collections → lista armii
# 2. /collections?army_id=X → lista oddziałów z licznikami
# 3. /collections/units/Y → formularz + dodaj model (bez magnetyzacji), dodaj z magnetyzacją
# 4. Edytuj model (kliknij ✏️, sprawdź pre-fill formularza), Zapisz
# 5. Usuń model (kliknij ✕, potwierdź)
# 6. Przeładuj stronę — sprawdź persystencję
```

## Decyzje

- 2026-06-17: Magnetyzacja per model w kolekcji (nie per szablon Unit) — opcjonalna, domyślnie wyłączona. Opcje slotu z puli broni oddziału + "nic".
- 2026-06-17: loadout_json format prostszy niż RosterUnit: `{"weapons": {id: count}, "abilities": {id: 1}}` — nie reużywamy `normalize_roster_unit_loadout` (zbyt sprzężona z passive_state). Faza 2 może znormalizować przy integracji.
- 2026-06-17: `data-card` atrybut używa `forceescape` (nie `e`) — `tojson` zwraca Markup, `e` nie re-escapuje, `forceescape` robi to zawsze → label z `'` nie łamie atrybutu.
- 2026-06-17: Brak Alembic — nowe tabele tworzone przez `create_all()` przy starcie. `_migrate_schema()` wymagane tylko dla ALTER TABLE na istniejących tabelach.

## Notatki / odkrycia w trakcie

- 2026-06-17: `_unit_weapon_options` jest funkcją prywatną `rosters.py` (nie `unit_helpers.py` jak zakładał plan) — zduplikowano uproszczoną wersję w `collections.py` zamiast importować funkcję prywatną.
- 2026-06-17: Encoding Polish chars w curl/Bash na Windows (CP1250) wygląda jak corruption, ale to artifact testu — przeglądarki wysyłają UTF-8 poprawnie. Weryfikacja: `data-card` w HTML zawiera poprawne `\uXXXX` escape sequences dla polskich znaków.
- 2026-06-17: Test curl z `-F "slot_name_0=Broń pokładowa"` daje garbled output — to terminal encoding (CP1250 bytes interpretowane jako Latin-1). Nie jest bugiem aplikacji.

## Co NIE wchodzi w Fazę 1 (do Fazy 2)

- Tryb "modele" vs "obecny układ" w edytorze rozpiski
- Auto-przypisywanie modeli z kolekcji do aktualnego układu RosterUnit
- Proxy modele (gdy brakuje w kolekcji)
- Eliminowanie modeli w widoku dynamicznym (Stan Bitewny)
- Współdzielenie liczników kolekcji między wieloma RosterUnit tego samego Unit w rozpisce
- Przypisanie jednego fizycznego modelu do wielu oddziałów/armii
- Formalna kategoria `equipment_type` (marker/upgrade) — np. Sztandar
