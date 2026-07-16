# LOG SESJI — archiwum

> Starsze wpisy LOG SESJI przeniesione z `HANDOFF.md`, aby główny plik trzymał
> tylko rzeczy obecnie użyteczne. Append-only historia, najnowsze na górze.
> Bieżące (najnowsze) wpisy są w [HANDOFF.md](../../HANDOFF.md).

---

### 2026-05-22 — widok-rozpiski-ostrzezenia (archived)
- Nowy moduł `roster_warnings.js` z badge `⚠ N` + tooltip (8 reguł: liczność, bohaterowie, limit punktów, nierównowaga cenowa, broń vs wytrzymałość). Backend: `weapon_cost` w `roster_items`. BUG FIX: `_roster_unit_weapon_components_sum` — zastąpiono `_unit_army_flags` wywołaniem `costs.compute_passive_state` + `_strip_role_traits` (wynik 51.94 → 98.17 dla Widmy, zgodny z oczekiwaniem).
- Pliki: `roster_warnings.js` (NEW), `roster_edit.html`, `roster_editor.js`, `roster_rendering.js`, `rosters.py`.
- Weryfikacja: pytest 176/176, smoke roster/3 i roster/13 OK, konsola czysta. Commit `588d27c`.

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
