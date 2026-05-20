# HANDOFF — Meta

> **Co tu jest:** spis aktywnych wątków + zablokowane zasoby + szybkozmienne notatki cross-wątkowe + LOG SESJI.
> **Czego tu NIE ma:** wiedzy stabilnej (mapa submodułów, architektura) — to jest w `docs/architecture.md`.
> **Per-wątek:** szczegóły w `docs/handoffs/HANDOFF_<slug>.md`.
> **Workflow:** uruchom `/load-context` na początku sesji. Detale konwencji: [docs/handoffs/README.md](docs/handoffs/README.md).

---

## Aktywne wątki

| Wątek (link) | Cel (1 zdanie) | Pliki zablokowane | Status |
|---|---|---|---|
| *(brak aktywnych wątków)* | | | |

## Zasoby zablokowane (reverse lookup)

| Plik / katalog | Wątek blokujący | Powód |
|---|---|---|
| *(brak zablokowanych zasobów)* | | |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Po archiwizacji wątku przez `/handoff-archive` trafia tutaj 1–2 zdania podsumowania.)*

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
