# HANDOFF — Meta

> **Co tu jest:** spis aktywnych wątków + zablokowane zasoby + szybkozmienne notatki cross-wątkowe + LOG SESJI.
> **Czego tu NIE ma:** wiedzy stabilnej (mapa submodułów, architektura) — to jest w `docs/architecture.md`.
> **Per-wątek:** szczegóły w `docs/handoffs/HANDOFF_<slug>.md`.
> **Workflow:** uruchom `/load-context` na początku sesji. Detale konwencji: [docs/handoffs/README.md](docs/handoffs/README.md).

---

## Aktywne wątki

| Wątek (link) | Cel (1 zdanie) | Pliki zablokowane | Status |
|---|---|---|---|
| [HANDOFF_faza-a](docs/handoffs/HANDOFF_faza-a.md) | Migracja proceduralnej logiki kosztów do YAML+Pydantic v2 pod feature toggle `OPR_RULES_BACKEND` (A0+A1+A2+A3+A5) | `quote.py`, `config.py`, `requirements.txt`, `app/rulesets/v1/*`, `app/services/rulesets/*`, `Makefile` | In progress |

## Zasoby zablokowane (reverse lookup)

| Plik / katalog | Wątek blokujący | Powód |
|---|---|---|
| `app/services/costs/quote.py` | faza-a | dispatcher (A0) + `_yaml_quote()` (A2) |
| `app/config.py` | faza-a | `OPR_RULES_BACKEND` ENV var (A0) |
| `requirements.txt` | faza-a | pydantic v2 + pyyaml (A0) |
| `app/rulesets/v1/` (NEW) | faza-a | tables.yaml + abilities.yaml + ability_costs.yaml (A1, A2) |
| `app/services/rulesets/` (NEW) | faza-a | models, loader, cost_functions, dispatcher (A1, A2) |
| `app/services/costs/errors.py` (NEW) | faza-a | `RulesetParityError` (A0) |
| `Makefile` | faza-a | cel `test-parity` (A3) |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Po archiwizacji wątku przez `/handoff-archive` trafia tutaj 1–2 zdania podsumowania.)*

### 2026-05-24 — faza-a A2.6 (ADR-0004 + faza A2 zamknięta)
- A2.6 done. `docs/adr/0004-cost-dsl.md` (NEW) podsumowuje decyzje strukturalne fazy A2: hardcoded fn-dispatcher (nie eval), callable injection (`passive_cost_fn`, `slug_for_name`), inwariant czystości "no-oracle-import" w `rulesets/*`, świadome odchylenie `transport_multiplier` priority-first vs oracle last-match-wins (parity-bug fix). Plus 5 alternatyw odrzuconych. Faza A2 (DSL + YAML backend) zamknięta — następna jest **A3** (parity tests + CI gate).
- Pliki: `docs/adr/0004-cost-dsl.md` (NEW), `HANDOFF.md`, `docs/handoffs/HANDOFF_faza-a.md`.
- Następny krok: A3.1 (`tests/test_ruleset_parity.py` — 100 cartesian + 50 manual cases, delta ≤ 1e-3).

### 2026-05-24 — faza-a A2.5 (test suite)
- A2.5 done w jednej sesji. 2 nowe pliki testowe: `tests/test_cost_functions.py` (232 testy) i `tests/test_quote_yaml_backend.py` (35 testów). Pełna suita 563/563 passed. Pokrycie: per-fn parytet 13 DSL prymitywów vs oracle (range/ap/blast/deadly/morale/defense/toughness/transport priority-first), 5-flag scale_by_tou edge cases, cartesian passive_cost_dsl × 35 abilities × aura, base_model_cost 10 scenariuszy, weapon wrappers, mistrzostwo. End-to-end: 3 backendy × 10 scenariuszy (basic/passive/aura/transport/weapon-traits/loadout/masywny) z `both_assert` no-raise + edge cases (count=0, include_item_costs=False, loadout normalization).
- Pliki: `tests/test_cost_functions.py` (NEW), `tests/test_quote_yaml_backend.py` (NEW), `docs/handoffs/HANDOFF_faza-a.md` (A2.5 odznaczony).
- Następny krok: A2.6 (`docs/adr/0004-cost-dsl.md`).

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
