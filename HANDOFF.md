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
| *(brak)* | | |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Po archiwizacji wątku przez `/handoff-archive` trafia tutaj 1–2 zdania podsumowania.)*

### 2026-05-24 — faza-a (archived)
- Strumień A planu długofalowego — migracja proceduralnej logiki kosztów do deklaratywnej (YAML + Pydantic v2) pod feature toggle `OPR_RULES_BACKEND ∈ {procedural, yaml, both_assert}`. Procedural pozostał SSOT (oracle); YAML jest niezależną repliką liczącą identycznie (parity ≤ 1e-3). **Wszystkie 5 zaplanowanych podfaz zamknięte ✅** (A0 toggle, A1 schema+87 abilities, A2 cost DSL z 13 fn + 6 handlers + 33 passive recipes, A3 parity gate 156 testów + yaml mirror 93 testów, A5 perf gate 1.158× ≤ budget 1.30×). A4 (DOCX→YAML drift pipeline) świadomie poza scope — osobny wątek gdy wymagane. **Strumień A odblokowuje strumienie B (game engine), C (MCP/RAG), D (boty)** — wszystkie potrzebowały YAML SSOT.
- Pliki: `app/services/rulesets/{__init__,models,loader,cost_functions,dispatcher,handlers,quote_yaml}.py` (NEW pakiet, ~2300 LOC), `app/rulesets/v1/{tables,abilities,ability_costs}.yaml` (NEW), `app/services/costs/{quote.py:_yaml_quote,errors.py:RulesetParityError}` (zmiany + NEW), `app/config.py` (OPR_RULES_BACKEND), `requirements.txt` (pydantic v2 + PyYAML), `Makefile` (cel `test-parity` + flag BACKEND= dla profile), `scripts/profile_quote.py` (--backend), 8 nowych plików testowych (`test_feature_toggle/tables_migration/abilities_migration/cost_functions/quote_yaml_backend/ruleset_parity/quote_performance_regression.py` + `tests/yaml_backend/` z 4 mirror suite + conftest), 4 nowe ADR (`0003-yaml-pydantic-format`, `0004-cost-dsl`, `0005-feature-toggle`, `0007-ruleset-cache`), `docs/PERFORMANCE.md` (A5 baseline obu backendów). Commity: `ebddf68` (A0), `938da20` (A1), `a70601d` (A2.1-2.4b), `5d02dd5`+`c4e01cd`+`0ed400c`+`1574f42` (sub-wątek A2.4c), `9c19ddb` (A2.5), `da71895` (A2.6), `d7fc8c3` (A3), `610919b` (A5), `08b8662` (post-review cleanup: unify CostRecipe/CostRecipeSpec + dedupe helpers).
- Weryfikacja: pytest 815/815 passed default procedural; `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` → 156/156 0 RulesetParityError; `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` → 93/93; perf ratio yaml/procedural 1.158× (mediana z 5 runs). Smoke UI pod `both_assert` deferred — lokalna DB pusta, do uruchomienia gdy ktoś zaimportuje prod DB.

### 2026-05-23 — faza-a-2-dsl-quote (archived)
- Sub-wątek `faza-a` zamykający A2.4c. NEW `app/services/rulesets/quote_yaml.py` (~440 LOC) — `roster_unit_role_totals_yaml` jako 1:1 port `costs/role_totals.py` z YAML substytucjami (`weapon_cost_components_yaml`, `ability_cost_components_yaml`, `_yaml_ability_cost` z `cost_hint` short-circuit). Body `_yaml_quote()` (~190 LOC) w `quote.py` — mirror `_procedural_quote` end-to-end. Fix parity-bug `transport_multiplier` (priority-first via `break` — był last-match-wins).
- Pliki: `app/services/rulesets/quote_yaml.py` (NEW), `app/services/costs/quote.py`, `app/services/rulesets/cost_functions.py`, `tests/test_feature_toggle.py`. Commity: `5d02dd5` (c.0+c.1), `c4e01cd` (c.2), `0ed400c` (parent update).
- Weryfikacja: pytest 296/296, smoke `OPR_RULES_BACKEND=both_assert` × 10 cases (None-unit, count=0, infantry, passive nieustraszony/zwiadowca, transport-6, masywny, aura, weapon, no-item-costs) — 0 RulesetParityError. UI-smoke deferred do A3 (lokalna DB pusta).

### 2026-05-21 — widok-rozpiski-ostrzezenia (archived)
- Dodany moduł `roster_warnings.js` + znacznik `⚠ N` z tooltipem po liczniku oddziałów/bohaterów (8 reguł: liczność oddziałów/bohaterów, limit punktów, nierównowaga cenowa 4×, broń vs wytrzymałość). Backend dorzuca `weapon_cost` do `roster_items`. Klucz `warnings:[]` i `collect_roster_warnings()` zostawione jako publiczny kontrakt AJAX.
- Pliki: `app/static/js/modules/roster_warnings.js` (NEW), `app/templates/roster_edit.html`, `app/static/js/modules/roster_editor.js`, `app/static/js/modules/roster_rendering.js`, `app/routers/rosters.py`.
- Weryfikacja: pytest 176/176, smoke roster/3 i roster/13 OK. Commit `588d27c`.

### 2026-05-21 — primary-weapon-flag (archived)
- Klikalna flaga ⚑ broni podstawowej w edytorze rozpiski z zapisem override w `loadout_json.primary_weapon` (per typ: melee/ranged). Backend `_loadout_weapon_details` honoruje override przy budowaniu `weapon_details` dla Stanu Bitewnego.
- Pliki: `app/static/js/modules/loadout_state.js`, `editor_renderers.js`, `roster_editor.js`, `app/routers/rosters.py`.
- Weryfikacja: pytest 176/176, smoke OK po bugfixach (zachowanie w `_sanitize_loadout`, warunek `totalCount>0`, null sentinel dla zdejmowania default-primary). Commit `c8d6d52`.

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
