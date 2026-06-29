# HANDOFF — Meta

> **Co tu jest:** spis aktywnych wątków + zablokowane zasoby + szybkozmienne notatki cross-wątkowe + LOG SESJI.
> **Czego tu NIE ma:** wiedzy stabilnej (mapa submodułów, architektura) — to jest w `docs/architecture.md`.
> **Per-wątek:** szczegóły w `docs/handoffs/HANDOFF_<slug>.md`.
> **Workflow:** uruchom `/load-context` na początku sesji. Detale konwencji: [docs/handoffs/README.md](docs/handoffs/README.md).

---

## Aktywne wątki

| Wątek (link) | Cel (1 zdanie) | Pliki zablokowane | Status |
|---|---|---|---|
| [HANDOFF_kolekcja](docs/handoffs/HANDOFF_kolekcja.md) | Faza 1: CRUD fizycznych modeli w kolekcji użytkownika (bazy danych + UI) | `app/models.py`, `app/routers/collections.py`, `app/templates/collection_unit_detail.html` | In progress |
| [HANDOFF_demoralizacja-mag](docs/handoffs/HANDOFF_demoralizacja-mag.md) | Demoralizacja + koszt Maga + koszty/tabela Rozkaz-Klątwa-Oznaczenie + UI trudności zaklęć | `app/data/abilities.py`, `app/services/costs/abilities.py`, `app/services/ability_registry.py`, `app/routers/armies.py`, `app/models.py`, `app/db.py`, `app/templates/army_spells.html` | In progress |


## Zasoby zablokowane (reverse lookup)

| Plik / katalog | Wątek blokujący | Powód |
|---|---|---|
| `app/models.py` | kolekcja | +CollectionModel, +CollectionModelSlot |
| `app/routers/collections.py` | kolekcja | nowy router (NEW) |
| `app/templates/collection_unit_detail.html` | kolekcja | nowy szablon (NEW) |
| `app/models.py` | demoralizacja-mag | +`ArmySpell.cast_difficulty` (zmiana rozłączna z kolekcją) |
| `app/data/abilities.py` | demoralizacja-mag | Demoralizacja + tagi psujących cech + opis Maga |
| `app/services/costs/abilities.py` | demoralizacja-mag | koszty Mag/Rozkaz/Klątwa/Oznaczenie/Demoralizacja |
| `app/services/ability_registry.py` | demoralizacja-mag | filtrowanie pickerów tag-driven |
| `app/routers/armies.py` | demoralizacja-mag | spell details + add-ability + weapon preview + ability-cost-preview |
| `app/templates/army_spells.html` | demoralizacja-mag | UI wyboru trudności + kolumna Trudność |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Po archiwizacji wątku przez `/handoff-archive` trafia tutaj 1–2 zdania podsumowania.)*

### 2026-05-22 — widok-rozpiski-ostrzezenia (archived)
- Nowy moduł `roster_warnings.js` z badge `⚠ N` + tooltip (8 reguł: liczność, bohaterowie, limit punktów, nierównowaga cenowa, broń vs wytrzymałość). Backend: `weapon_cost` w `roster_items`. BUG FIX: `_roster_unit_weapon_components_sum` — zastąpiono `_unit_army_flags` wywołaniem `costs.compute_passive_state` + `_strip_role_traits` (wynik 51.94 → 98.17 dla Widmy, zgodny z oczekiwaniem).
- Pliki: `roster_warnings.js` (NEW), `roster_edit.html`, `roster_editor.js`, `roster_rendering.js`, `rosters.py`.
- Weryfikacja: pytest 176/176, smoke roster/3 i roster/13 OK, konsola czysta. Commit `588d27c`.

### 2026-06-04 — primary-weapon-flag (archived)
- Klikalna flaga ⚑ broni podstawowej w edytorze rozpiski z zapisem override w `loadout_json.primary_weapon` (per typ: melee/ranged). Backend `_loadout_weapon_details` honoruje override przy budowaniu `weapon_details` dla Stanu Bitewnego. Dodatkowe fixy: null-override gubiony w `createLoadoutState` (deserialization), `assignDefaultWeapon` przepinane na `isCurrentPrimary` zamiast `isPrimaryWeapon` (slot-filler podąża za flagą).
- Pliki: `loadout_state.js`, `editor_renderers.js`, `roster_editor.js`, `rosters.py`.
- Weryfikacja: pytest 176/176, smoke OK.

### 2026-05-28 — strategic-cards (archived)
- Nowa funkcja: Karty Strategiczne w edytorze rozpiski — checkboxy wyboru 3 Zadań + 3 Wsparć (10+8 kart w pliku `app/data/strategic_cards.py`, zapis w `Roster.strategic_cards_json`), druk macierzy 3×3 na A4 z auto `window.print()`. UI: checkboxy z JS-limitem do 3, 3 przyciski submit (Zapisz / Zapisz i drukuj / Zapisz i wróć). Treści kart zaktualizowane do finalnej wersji (4 kategorie Zadań: Natarcie/Obrona/Dywersja/Zwiad).
- Pliki: `app/data/strategic_cards.py` (NEW), `app/models.py`, `app/routers/rosters.py`, `app/templates/roster_edit.html`, `app/templates/roster_strategic_cards{,_print}.html` (NEW), `tests/test_strategic_cards.py` (NEW, 27 testów).
- Weryfikacja: pytest 203/203, smoke przeglądarkowy OK, wydruk PDF zweryfikowany ręcznie. Migracja: `ALTER TABLE rosters ADD COLUMN strategic_cards_json TEXT`.

### 2026-05-20 — handoff-template polish (follow-up do refactor-agents-md)
- Rozszerzono stany kroków HANDOFF z 2 do 4: `[ ]` TODO / `[~]` rozpoczęto / `[x]` sukces / `[!]` błąd-porzucone. Legenda w `docs/handoffs/README.md`, zaktualizowane skille `handoff-archive` (sprawdza stany finalne), `handoff-status` (pokazuje progres `5[x] / 1[~] / 2[ ]`), `handoff-start` (zachowuje Definition of Done w szablonie).
- Dodano "Definition of Done" w `docs/planning.md`: pytest + `/simplify` (zawsze) + `/review` (warunkowo: diff >50 linii / hot path / SSOT) + `/security-review` (warunkowo: auth, user input → DB). Szablon `HANDOFF_<slug>.md` zawiera te kroki w "Faza N — Weryfikacja end-to-end".
- AGENTS.md: nowy [REQUIRED] #7 + Workflow oczekiwany krok 3/4 zaktualizowany. Długość 74 linii (cel ~90).
- Weryfikacja: pytest 221/221 passed.

### 2026-05-20 — refactor-agents-md (archived)
- Podział AGENTS.md (267 → 73 linii) na manifest `[CRITICAL]/[REQUIRED]/[RECOMMENDED]` + szczegóły w `docs/`. HANDOFF.md przebudowany na meta-spis (95 → 61 linii). System per-wątek `docs/handoffs/HANDOFF_<slug>.md` + 5 skilli (`/handoff-start`, `/handoff-archive`, `/handoff-status`, `/load-context`, `/handoff-sync`) + obowiązkowy SessionStart hook w `.claude/settings.json`.
- Pliki: AGENTS.md, HANDOFF.md, `docs/{README,overview,architecture,roadmap,planning,developing,testing,git-workflow,app-js-guide}.md`, `docs/handoffs/README.md`, `.claude/settings.json`, `.claude/skills/handoff-{start,archive,status,sync}/SKILL.md`, `.claude/skills/load-context/SKILL.md`.
- Weryfikacja: pytest 172/172 passed, 0 zbitych linków w 13 plikach, JSON `.claude/settings.json` poprawny, SessionStart hook output zweryfikowany ręcznie.

### 2026-05-14 — Faza III modułów pomocniczych app.js (zaimplementowana)
- Wydzielono 8 sekcji do modułów IIFE: text parsing, UI pickers, spell weapon preview, spell ability forms, roster rendering, loadout state, editor renderers, roster adders.
- Dodano `docs/frontend_js_modules.md` jako mapę zależności i call-site checklist.
- Weryfikacja: `node --check` dla nowych modułów i `app.js`, sandbox load-test, call-site grep — przeszły.
- Pytest/full smoke zablokowany niedostępnym Python/make w lokalnym środowisku Windows (dalej notatka cross-wątkowa wyżej).
- Commity: `b1ccd78` (faza I-III), `ef4bbf7` (faza IV), `65f8b6f` (merge).

### 2026-05-14 — Faza II payload adapters (zakończona)
- Dodano `payload_adapters.js`, flagę `window.SZOP_DEV_MODE`, podpięcia w `app.js` i testy regresyjne (`tests/test_frontend_payload_adapters.py`).
- Weryfikacja automatyczna: pełne `pytest -q` przeszło.
- Smoke przeglądarkowy wymagał ręcznej akceptacji w UI.

### 2026-05-13 — Start Fazy II payload adapters
- Zamknięto etap startowej modularizacji jako kontekst bazowy.
- Cel: adaptery i walidatory payloadów przed dalszym podziałem `app.js`.

### 2026-05-12 — Start modularizacji app.js
- Zamknięto stan "BRAK AKTYWNEGO ZADANIA".
- Nowy cel: sekcyjna ekstrakcja `app.js` z zachowaniem 1:1 i pełną weryfikacją parity/smoke.
