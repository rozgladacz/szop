# HANDOFF — faza-a

> **Wątek:** Strumień A planu długofalowego — migracja proceduralnej logiki kosztów do deklaratywnej (YAML + Pydantic v2) pod feature toggle `OPR_RULES_BACKEND`, fazy A0+A1+A2+A3+A5 (A4 świadomie poza scope).
> **Status:** In progress (A0 done, A1 next)
> **Utworzony:** 2026-05-21
> **Ostatnia aktualizacja:** 2026-05-22

## Cel

Wprowadzić deklaratywny ruleset (YAML + Pydantic v2) jako równoległy backend silnika kosztów pod ENV toggle `OPR_RULES_BACKEND ∈ {procedural, yaml, both_assert}`. Procedural engine pozostaje SSOT (oracle) i nie jest modyfikowany. YAML musi liczyć identycznie (±1e-3, weryfikowane testami parity). Migracja odblokowuje strumienie B (game engine), C (MCP/RAG) i D (boty).

Plan szczegółowy: `C:\Users\mlis\.claude\plans\twoje-zadanie-skoordynowa-prac-async-lark.md`.

## Zablokowane pliki / katalogi

- `app/services/costs/quote.py` — dispatcher (A0) + `_yaml_quote()` (A2)
- `app/config.py` — `OPR_RULES_BACKEND` (A0)
- `requirements.txt` — `pydantic>=2.0`, `pyyaml>=6.0` (A0)
- `app/rulesets/v1/` — NOWY katalog (`tables.yaml`, `abilities.yaml`, `ability_costs.yaml`) — A1, A2
- `app/services/rulesets/` — NOWY pakiet (`models.py`, `loader.py`, `cost_functions.py`, `dispatcher.py`) — A1, A2
- `app/services/costs/errors.py` — NOWY (`RulesetParityError`) — A0
- `Makefile` — nowy cel `test-parity` (A3)
- `tests/test_feature_toggle.py`, `test_tables_migration.py`, `test_abilities_migration.py`, `test_cost_functions.py`, `test_quote_yaml_backend.py`, `test_ruleset_parity.py`, `test_quote_performance_regression.py` — NOWE
- `tests/yaml/` — NOWY katalog (mirror testów costs pod `OPR_RULES_BACKEND=yaml`) — A3
- `docs/adr/0003`–`0005`, `0007` — NOWE pliki ADR

**Read-only (oracle, nie modyfikujemy):**
- `app/services/costs/_engine.py`, `app/data/abilities.py`, `app/services/costs/abilities.py`, `app/services/costs/weapons.py`, `app/services/costs/role_totals.py`
- `app/rulesets/default.json` — uznany za nieaktualny, zostaje w repo bez ruchu

## Blokuje / Blokowane przez

- **Blokuje:** Strumień B (Game Engine), C (MCP/RAG), D (boty) — wszystkie potrzebują YAML SSOT. Faza A4 (pipeline DOCX→YAML drift) startuje po stabilizacji A3.
- **Blokowane przez:** nic

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

*(5 faz sekwencyjnych. Sub-handoff wydzielamy reaktywnie gdy faza > 1 sesji lub ortogonalny incydent.)*

### Faza A0 — Feature toggle + dispatcher (1 sesja) ✅

- [x] Krok A0.1: `requirements.txt` — dodano `pydantic>=2.0,<3.0`, `PyYAML>=6.0,<7.0`
- [x] Krok A0.2: `app/config.py` — `OPR_RULES_BACKEND` z fail-fast walidacją (`RULES_BACKEND_CHOICES`)
- [x] Krok A0.3: `app/services/costs/errors.py` (NOWY) — `class RulesetParityError(AssertionError)` z polami `(path, proc_value, yaml_value, delta, tolerance)`
- [x] Krok A0.4: `app/services/costs/quote.py` — wyciągnięto ciało do `_procedural_quote()`; dispatcher na top-level; `_yaml_quote()` stub (NotImplementedError z odsyłaczem do A2); `_both_assert_quote()` + `_assert_quote_parity()` rekurencyjny compare (dict/list/numeric/struct mismatch, bool guard przed int-subclass)
- [x] Krok A0.5: `tests/test_feature_toggle.py` (NOWY) — 9 testów: default==procedural empty payload, yaml raise, both_assert propaguje yaml stub, invalid backend rejected at import, parity helper equal/tolerance/numeric-delta/structural-mismatch
- [x] Krok A0.6: `docs/adr/0005-feature-toggle.md` + `docs/adr/README.md` (NOWY szablon ADR)
- [x] `pytest -q` → **185 passed** (176 baseline + 9 nowych)
- [x] Smoke: `OPR_RULES_BACKEND=yaml python -c ...` → NotImplementedError z message wskazującym A2
- [ ] Commit: `A0: feature toggle OPR_RULES_BACKEND + dispatcher stub + ADR-0005`

### Faza A1 — Schema + tables.yaml + abilities.yaml (~1-2 sesje)

- [ ] Krok A1.1: `app/services/rulesets/{__init__,models,loader}.py` (NOWE) — Pydantic v2 (`TableDefinition`, `AbilityDefinition`, `RulesetManifest`) + loader z LRU+SHA256
- [ ] Krok A1.2: `app/rulesets/v1/tables.yaml` (NOWY) — 18 stałych z `_engine.py:23-79`
- [ ] Krok A1.3: `app/rulesets/v1/abilities.yaml` (NOWY) — 98 definicji z `app/data/abilities.py`
- [ ] Krok A1.4: `tests/test_tables_migration.py` (NOWY) — exact match każda stała ↔ node YAML
- [ ] Krok A1.5: `tests/test_abilities_migration.py` (NOWY) — exact match 98 wpisów
- [ ] Krok A1.6: `docs/adr/0003-yaml-pydantic-format.md` (NOWY)
- [ ] `pytest -q` → 178+ passed
- [ ] Commit: `A1: tables.yaml + abilities.yaml + Pydantic loader + migration tests + ADR-0003`

### Faza A2 — Cost DSL + _yaml_quote (~2 sesje)

- [ ] Krok A2.1: `app/services/rulesets/cost_functions.py` (NOWY) — 13 czystych funkcji (`scale_by_tou`, `defense_modifier`, `morale_modifier`, `toughness_modifier`, `base_model_cost`, `range_multiplier`, `ap_modifier`, `blast_cost`, `deadly_cost`, `transport_multiplier`, `_mistrzostwo_weapon_cost`, `_mistrzostwo_aura_cost`, `parse_aura_value`)
- [ ] Krok A2.2: `app/services/rulesets/dispatcher.py` (NOWY) — hardcoded mapping `fn_name → callable`, **nie eval**
- [ ] Krok A2.3: `app/rulesets/v1/ability_costs.yaml` (NOWY) — DSL per slug
- [ ] Krok A2.4: `app/services/costs/quote.py` — implementacja `_yaml_quote()` end-to-end (reprodukuje shape outputu procedural)
- [ ] Krok A2.5: `tests/test_cost_functions.py`, `test_quote_yaml_backend.py` (NOWE)
- [ ] Krok A2.6: `docs/adr/0004-cost-dsl.md` (NOWY)
- [ ] `pytest -q` → wszystko zielone; `OPR_RULES_BACKEND=yaml pytest tests/test_quote_yaml_backend.py -v` zielone
- [ ] Commit: `A2: Cost DSL (13 fn) + _yaml_quote + ability_costs.yaml + ADR-0004`

### Faza A3 — Parity tests + CI gate (~1 sesja)

- [ ] Krok A3.1: `tests/test_ruleset_parity.py` (NOWY) — 100 cartesian + 50 manual; asercja delta ≤ 1e-3
- [ ] Krok A3.2: `tests/yaml/test_{passive,active,weapon,mistrzostwo}_costs_yaml.py` (NOWE) — mirror istniejących pod yaml backendem
- [ ] Krok A3.3: `Makefile` — cel `test-parity`
- [ ] `OPR_RULES_BACKEND=both_assert pytest -q` → 0 RulesetParityError
- [ ] Smoke: `make dev` pod both_assert, otwórz dowolną rozpiskę
- [ ] Commit: `A3: parity tests (100 cartesian + 50 manual) + both_assert CI gate`

### Faza A5 — Perf regression gate (~0.5 sesji)

- [ ] Krok A5.1: `tests/test_quote_performance_regression.py` (NOWY) — `yaml_time/proc_time <= 1.20`
- [ ] Krok A5.2: `scripts/profile_quote.py` — flaga `--backend`
- [ ] Krok A5.3: `docs/PERFORMANCE.md` — baseline obu backendów
- [ ] Krok A5.4: `docs/adr/0007-ruleset-cache.md` (NOWY)
- [ ] Commit: `A5: perf regression gate + ADR-0007`

### Weryfikacja end-to-end (po A3, finalny przed A5)

- [ ] `pytest -q` — wszystko zielone (default procedural)
- [ ] `$env:OPR_RULES_BACKEND="yaml"; pytest tests/yaml/ -v` — wszystko zielone
- [ ] `$env:OPR_RULES_BACKEND="both_assert"; pytest tests/test_ruleset_parity.py -v` — 150/150 passed
- [ ] Smoke UI pod `both_assert` — quoty bit-identyczne

## Pliki dotknięte

**A0:**
- `requirements.txt` — pydantic v2 + PyYAML
- `app/config.py` — `OPR_RULES_BACKEND` + `RULES_BACKEND_*` stałe
- `app/services/costs/quote.py` — dispatcher (top-level) + `_procedural_quote` + `_yaml_quote` stub + `_both_assert_quote` + `_assert_quote_parity`
- `app/services/costs/errors.py` (NEW) — `RulesetParityError`
- `tests/test_feature_toggle.py` (NEW) — 9 testów
- `docs/adr/README.md` (NEW) — szablon ADR
- `docs/adr/0005-feature-toggle.md` (NEW)

## Hipotezy / pytania otwarte

- Czy `_apply_ruleset_overrides()` w `_engine.py:131` (czyta `app/rulesets/default.json`) wpływa na wartości stałych modułowych? Jeśli tak — `tables.yaml` musi reprezentować stan **po** override, nie surowy. Sprawdzić w A1.
- Czy istnieją testy które ustawiają ENV vars na starcie sesji (kolizja z `OPR_RULES_BACKEND`)? Sprawdzić `tests/conftest.py` w A0.

## Jak zweryfikować

```powershell
python -m pytest -q
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml/ -v; Remove-Item Env:OPR_RULES_BACKEND
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py -v; Remove-Item Env:OPR_RULES_BACKEND
```

## Decyzje

- 2026-05-21: Jeden wątek `faza-a` z 5-fazowym planem (A0+A1+A2+A3+A5). Sub-handoffy reaktywnie. Powód: migracja sekwencyjna, mało współ-blokad — overhead 5 osobnych HANDOFF > 1 koordynator.
- 2026-05-21: Dispatcher backendu w `calculate_roster_unit_quote` top-level (nie 3 miejsca). Powód: `both_assert` porównuje kompletne wyniki, nie intermediate.
- 2026-05-21: `app/rulesets/default.json` traktowany jako nieaktualny, nie migrujemy. Zaczynamy od `app/rulesets/v1/`.
- 2026-05-21: Pydantic v2 + PyYAML w `requirements.txt` (runtime, nie dev-only) — koszt importu akceptowalny.
- 2026-05-21: Cost DSL = hardcoded function dispatcher (nie eval/exec). Ok 13 czystych funkcji.
- 2026-05-21: A4 (DOCX→YAML drift pipeline) świadomie poza scope — osobny wątek po stabilizacji A3.

## Notatki / odkrycia w trakcie

- 2026-05-21: HANDOFF utworzony. Plan zaakceptowany przez usera. Następny krok: A0.1 (requirements.txt).
- 2026-05-22: A0 zaimplementowany w jednej sesji (6 kroków). 185/185 pytest passed. Smoke `OPR_RULES_BACKEND=yaml` raise NotImplementedError zgodnie ze stubbem. Procedural pozostaje bit-identyczny (default). Oczekuje commita przed startem A1.
- 2026-05-22: Decyzja A0: dispatcher czyta `config.OPR_RULES_BACKEND` dynamicznie (atrybut modułu), nie zamraża importu. Pozwala na `monkeypatch.setattr(config, "OPR_RULES_BACKEND", ...)` w testach bez re-importu. Walidacja wartości toggle jest fail-fast przy imporcie `app.config` (ValueError).
- 2026-05-22: Decyzja A0: `_assert_quote_parity` izoluje `bool` od `int` przed numeric-branch (bool jest podklasą int w Pythonie — `True == 1` byłoby fałszywie tolerowane).
