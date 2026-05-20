# Roadmap

> Kierunki długofalowe. Bieżące zadania per wątek: `docs/handoffs/HANDOFF_*.md`. Stan zarchiwizowany: LOG SESJI w `HANDOFF.md`.

## Aktywne inicjatywy

### SSOT initiative — konsolidacja kalkulacji kosztów

**Cel:** Wszystkie kalkulacje kosztów (oddziałów, broni, abilities) liczy backend w `app/services/costs/`. JS renderuje wyniki, nie liczy.

**Status:** 5-fazowy plan. Detale per faza w odpowiednich `HANDOFF_*.md` lub LOG SESJI.

**Faza końcowa:** usunięcie ostatnich inline cost calc w JS (`app/static/js/app.js`).

### Refaktoryzacja `app/static/js/app.js`

**Cel:** Podział monolitycznego `app.js` (~6500 linii) na moduły IIFE.

**Status:**
- **Faza I-III** — zakończone (merge `b1ccd78`, `ef4bbf7`, `65f8b6f`). Wydzielono: text parsing, UI pickers, spell weapon preview, spell ability forms, roster rendering, loadout state, editor renderers, roster adders, refresh priority.
- **Faza IV** — w toku (commit `ef4bbf7`).
- **Pozostałe sekcje monolitu:** `ROSTER EDITOR CLOSURE` (~2000 linii), `WEAPON PICKER`, `ABILITY PICKER`, `ARMORY WEAPON TREE`, `WEAPON INHERITANCE PANEL`.

**Detale techniczne:** `docs/app-js-guide.md`, `docs/frontend_js_modules.md`.

### System handoff i dokumentacja (ta refaktoryzacja)

**Cel:** AGENTS.md → manifest invariantów + linki. Szczegóły w `docs/`. Per-wątek `docs/handoffs/HANDOFF_*.md` + 5 skilli automatyzujących workflow.

**Status:** in progress — szczegóły w `docs/handoffs/HANDOFF_refactor-agents-md.md`.

## Otwarte sprawy (do zaplanowania)

- **Merge conflicts gałęzi Klasyfikacja** — nierozwiązane, blokują finalizację SSOT Phase 5.
- **Lokalny runtime na Windows** — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.

## Decyzje strategiczne

- **Backend = SSOT dla kosztów.** Frontend renderuje, nie liczy.
- **Hierarchia oddziałów = dziedziczenie z różnicami.** Wariant trzyma tylko delta, nie pełen stan.
- **Monolityczne pliki dzielimy stopniowo, sekcjami.** Komentarze `// === SECTION: ... ===` są mapą — patrz `docs/developing.md`.
- **Reguły gry (`app/static/docs/`) są źródłem prawdy.** Niedopuszczalna dywergencja kod ↔ dokumentacja reguł.
