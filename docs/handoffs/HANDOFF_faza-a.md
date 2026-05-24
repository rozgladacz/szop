# HANDOFF — faza-a

> **Wątek:** Strumień A planu długofalowego — migracja proceduralnej logiki kosztów do deklaratywnej (YAML + Pydantic v2) pod feature toggle `OPR_RULES_BACKEND`, fazy A0+A1+A2+A3+A5 (A4 świadomie poza scope).
> **Status:** In progress (A0+A1 done, A2.1+A2.2+A2.3+A2.4a+A2.4b+A2.4c+A2.5 done, A2.6 next)
> **Utworzony:** 2026-05-21
> **Ostatnia aktualizacja:** 2026-05-24 (po A2.5)

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

### Faza A1 — Schema + tables.yaml + abilities.yaml (~1-2 sesje) ✅

- [x] Krok A1.1: `app/services/rulesets/{__init__,models,loader}.py` (NOWE) — Pydantic v2 (`RulesetTables`, `RulesetAbility`, `RulesetManifest`, `TransportMultiplier`) z `ConfigDict(frozen=True, extra="forbid")` + loader z LRU+SHA256 (cache klucz: `(version, sha256(tables), sha256(abilities))`)
- [x] Krok A1.2: `app/rulesets/v1/tables.yaml` (NOWY) — 18 tabel/stałych z `_engine.py:23-79` ręcznie z section comments
- [x] Krok A1.3: `app/rulesets/v1/abilities.yaml` (NOWY) — **87** definicji (nie 98 jak myślano w roadmap) wygenerowane z `ABILITY_DEFINITIONS` przez `yaml.safe_dump(allow_unicode=True, sort_keys=False, width=10000)` (zachowuje U+201D w opisach)
- [x] Krok A1.4: `tests/test_tables_migration.py` (NOWY) — 22 testy: per-tabela exact match + LRU instance reuse + unknown version reject
- [x] Krok A1.5: `tests/test_abilities_migration.py` (NOWY) — 89 testów: count + no-dup + order + parametrized per-slug (slug+name+type+description+value_*)
- [x] Krok A1.6: `docs/adr/0003-yaml-pydantic-format.md` (NOWY)
- [x] `pytest -q` → **296 passed** (185 po A0 + 111 nowych A1)
- [x] Smoke: `python -c "from app.services.rulesets import load_ruleset; m = load_ruleset(); print(m.version, len(m.abilities))"` → `1 87`
- [ ] Commit: `A1: tables.yaml + abilities.yaml + Pydantic loader + migration tests + ADR-0003`

### Faza A2 — Cost DSL + _yaml_quote (~2 sesje)

- [x] Krok A2.1: `app/services/rulesets/cost_functions.py` (NOWY) — 13 czystych funkcji + 1 prywatny helper `_weapon_cost_yaml` (mirror `weapons._weapon_cost`). Funkcje są pure, czytają `RulesetTables` z YAML, brak importów z `costs/_engine`. Smoke parity ok (8/8 delta=0): bolter, weapon-z-traitami, assault, mistrzostwo_aura, base_model_cost, defense/morale/toughness
- [x] Krok A2.2: `app/services/rulesets/dispatcher.py` (NOWY) — `CostRecipe` pydantic model + `_REGISTRY` (9 funkcji) + `call_recipe()` + `passive_cost_dsl()` jako YAML-replika oracle passive_cost. Smoke parity 22/22 na 11 abilities × {aura=False, aura=True}, 0 mismatch (włącznie z instynkt aura_alt_base i bastion/niestrudzony/ostrozny aura_required)
- [x] Krok A2.3: `app/rulesets/v1/ability_costs.yaml` (NOWY) — DSL per slug. 4 sekcje: `passive_abilities` (33 recipes), `fixed_by_slug` (7), `fixed_by_desc` (4), `handlers` (6 dla transport/open_transport/aura/mag/order_like/mistrzostwo). Plus `skip_in_default: [przygotowanie]`. Parity test 330/330 (33 slugów × 5 tou × {aura,non-aura}). Wymagało rozszerzenia `scale_by_tou` o flagę `aura_scale` (dla "dywersant": 1.25 stałe gdy aura=False, 1.25*tou gdy aura=True)
- [x] Krok A2.4: `app/services/costs/quote.py` — implementacja `_yaml_quote()` end-to-end (reprodukuje shape outputu procedural). **Podzielone na 3 podetapy:**
  - [x] A2.4a: `models.py` + `loader.py` — `AbilityCosts`/`CostRecipeSpec`/`HandlerSpec`/`HandlerMatch` pydantic schema + loader walidacja spójności wersji 3 plików YAML. Cache LRU wzbogacony o sha256 trzeciego pliku.
  - [x] A2.4b: `handlers.py` (NOWY) — 6 handlerów (open_transport/aura/mag/order_like/mistrzostwo + ablacja "transport") + `ability_cost_components_yaml()` jako wierna replika oracle dispatcher. Helper `weapon_cost_components_yaml`/`weapon_cost_yaml` dodane do cost_functions.py. **Smoke parity 37/37** vs oracle `ability_cost_components_from_name`.
  - [x] A2.4c (sub-wątek `faza-a-2-dsl-quote`, commity `5d02dd5`+`c4e01cd`): NEW `app/services/rulesets/quote_yaml.py` (~440 LOC) — `roster_unit_role_totals_yaml` (1:1 port `role_totals.py` z YAML substytucjami: `weapon_cost_components_yaml`, `ability_cost_components_yaml`, `_yaml_ability_cost` z `cost_hint` short-circuit). Body `_yaml_quote()` w `quote.py` (~190 LOC) mirror `_procedural_quote`. Fix parity-bug `transport_multiplier` (priority-first via `break`). Smoke `OPR_RULES_BACKEND=both_assert` × 10 cases (None-unit, count=0, infantry, passive nieustraszony/zwiadowca, transport-6, masywny, aura, weapon, no-item-costs) — 0 `RulesetParityError`. pytest 296/296.
- [x] Krok A2.5: `tests/test_cost_functions.py` (232 testy: per-fn parity + scale_by_tou edge cases + passive cartesian 33 slugów + base_model + mistrzostwo + weapon wrappery) + `test_quote_yaml_backend.py` (35 testów: shape parity 3 backendów × scenariusze, numeric parity yaml vs proc na 10 scenariuszach, `both_assert` no-raise, count=0/include_item_costs=False edge cases, loadout normalization parity). pytest 563/563.
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

**A1:**
- `app/services/rulesets/__init__.py` (NEW) — publiczne API (`load_ruleset`, modele)
- `app/services/rulesets/models.py` (NEW) — Pydantic v2 frozen: `RulesetTables`, `RulesetAbility`, `RulesetManifest`, `TransportMultiplier`
- `app/services/rulesets/loader.py` (NEW) — `load_ruleset(version="v1")` z LRU+SHA256, walidacja struktury YAML, mismatch version → ValueError
- `app/rulesets/v1/tables.yaml` (NEW) — 18 tabel/stałych z section comments
- `app/rulesets/v1/abilities.yaml` (NEW, generated) — 87 abilities z `ABILITY_DEFINITIONS`
- `tests/test_tables_migration.py` (NEW) — 22 testy
- `tests/test_abilities_migration.py` (NEW) — 89 testów (3 sanity + 87 parametrized + 1 count edge)
- `docs/adr/0003-yaml-pydantic-format.md` (NEW)

**A2.1-A2.4b (ta sesja):**
- `app/services/rulesets/cost_functions.py` (NEW, ~600 LOC) — 13 czystych funkcji DSL + `_weapon_cost_yaml` + `weapon_cost_components_yaml`/`weapon_cost_yaml` wrappers. Brak importów z `costs/_engine`.
- `app/services/rulesets/dispatcher.py` (NEW, ~140 LOC) — `CostRecipe` pydantic + registry (9 funkcji) + `call_recipe` + `passive_cost_dsl()` jako YAML-replika passive_cost.
- `app/services/rulesets/handlers.py` (NEW, ~310 LOC) — 5 handlerów (open_transport/aura/mag/order_like/mistrzostwo) + `ability_cost_components_yaml()` dispatcher + lokalna `AbilityCostComponents` dataclass.
- `app/services/rulesets/models.py` — +4 klasy: `AbilityCosts`, `CostRecipeSpec`, `HandlerSpec`, `HandlerMatch`; `RulesetManifest.ability_costs`.
- `app/services/rulesets/loader.py` — czyta `ability_costs.yaml`, waliduje spójność wersji 3 plików, LRU keyed na sha256 trzech.
- `app/services/rulesets/__init__.py` — wystawia 4 nowe klasy.
- `app/rulesets/v1/ability_costs.yaml` (NEW, ~145 LOC) — 33 passive recipes + 7 fixed_by_slug + 4 fixed_by_desc + 5 handlers (transport intencjonalnie nieobecny — dead code w oracle) + `skip_in_default: [przygotowanie]`.

## Stan na restart sesji (2026-05-22, po A2.4b)

**Branch:** `Faza_A`. Ostatni commit: `A2: cost DSL primitives + dispatcher + handlers (parity 37/37)` (do utworzenia w tej sesji).

**Co działa:**
- 296/296 pytest passed (procedural backend nietknięty, default).
- 6 nowych plików w `app/services/rulesets/`: `cost_functions.py`, `dispatcher.py`, `handlers.py`, `models.py` (rozszerzone), `loader.py` (rozszerzone), `__init__.py` (wystawia 4 nowe klasy).
- 1 nowy plik w `app/rulesets/v1/`: `ability_costs.yaml` (33 passive + 7 fixed_by_slug + 4 fixed_by_desc + 5 handlers + skip_in_default).
- Parytetność z oracle: 22/22 `scale_by_tou`, 330/330 `passive_cost_dsl`, 37/37 `ability_cost_components_yaml`. 0 mismatch.

**Co jest następnym krokiem:** A2.4c — `quote_yaml.py` (NEW) + integracja w `_yaml_quote()`.

**Sub-handoff zalecany:** Otwórz `/handoff-start faza-a-2-dsl-quote` jako sub dla A2.4c+A2.5+A2.6. Czas jednej sesji raczej nie pokryje wszystkich trzech, ale A2.4c sam zmieści się komfortowo.

**Plan A2.4c (do wykonania w sub-wątku):**

1. **`app/services/rulesets/quote_yaml.py` (NEW, ~300-400 LOC)** — wierna replika `app/services/costs/role_totals.py:roster_unit_role_totals`. Musi reprodukować:
   - parsing loadout-counts (`_parse_counts` closure)
   - `_passive_entries_cache` + `_ability_cost_map_cache` (trait-fingerprint keyed)
   - `_compute_total(current_traits, selected_role)` → return rounded total
   - **Dynamic transport handler** w `_effective_passive_cost` (kompensacja za usunięty handler `transport` w `ability_costs.yaml`)
   - Memoization keyed na sorted-tuple traitów (jak oracle)
2. **`app/services/costs/quote.py` — implementacja body `_yaml_quote()`** (~150 LOC):
   - Mirror `_procedural_quote` shape end-to-end
   - Zastąp oracle calls (`base_model_cost`, `weapon_cost_components`, `roster_unit_role_totals`, `ability_cost`) ich YAML replikami
   - `slug_for_name = ability_catalog.slug_for_name` wstrzykiwane przy każdym wywołaniu `ability_cost_components_yaml`
   - `item_costs.passive_deltas` — uwaga na O(N²) charakter (2× `roster_unit_role_totals_yaml` per passive ability)

**Otwarte ryzyka A2.4c (do potwierdzenia w sub-wątku):**

- **Q1**: Czy `_yaml_quote` ma wywoływać `normalize_roster_unit_loadout` z `unit_helpers.py` (oracle) czy reimplementować? Funkcja jest **parsingiem, nie cost-math** — sugeruję reuse (importować z `costs.unit_helpers`). Czyste "no-import-from-oracle" ma zastosowanie do **cost logic**, nie do data normalization. Decyzja do podjęcia w A2.4c.
- **Q2**: `compute_passive_state` z `passive_state.py` — to też parsing (parses flags → traits/counts payload). Sugeruję reuse. Decyzja do podjęcia w A2.4c.
- **Q3**: Dynamic transport multiplier w `_effective_passive_cost` — `cost_functions.transport_multiplier` już istnieje, ale w role_totals oracle używa hardcoded `_transport_multiplier(active_set)` z osobnymi stawkami (`samolot=3.5`, `zwiadowca/zasadzka=2.5`, `latajacy=1.5`, `szybki/zwinny=1.25`). To te same wartości co w `tables.transport_multipliers`. Sprawdzić w sub-wątku że `transport_multiplier()` zwraca dokładnie te same multipliers w tej samej kolejności priorytetu.
- **Q4**: Czy zachować `extract_number` capacity-parsing dla open_transport w `_effective_passive_cost`, czy delegować do nowego `dynamic_transport_cost()` w cost_functions?

**Plik blockujący pre-A2.4c (do reread w sub-wątku):**
- `app/services/costs/role_totals.py` (oracle, 470 LOC) — read na start sub-wątku, żeby świeże oko zobaczyło closures.
- `app/services/costs/quote.py:_procedural_quote` (oracle, ~270 LOC) — read na start, żeby zobaczyć shape outputu który musi być reproducowany.

**Co jeszcze pozostaje po A2.4c:**
- A2.5: `tests/test_cost_functions.py` + `tests/test_quote_yaml_backend.py` (NOWE)
- A2.6: `docs/adr/0004-cost-dsl.md` (NOWY)
- Faza A3 (parity tests + CI gate)
- Faza A5 (perf regression gate)

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
- 2026-05-23 (A2.4c, sub-wątek `faza-a-2-dsl-quote`):
  - D1: split A2.4c na 2 sub-fazy (c.1 role_totals replika izolowane, c.2 `_yaml_quote` integracja) — łatwiejsza bisekcja drift.
  - D2: fix `transport_multiplier` priority-first (`break`) w scope A2.4c — real parity bug (last-match-wins) blokujący `both_assert`.
  - D3: reuse `normalize_roster_unit_loadout` i `compute_passive_state` w `_yaml_quote` — potwierdzone pure parsing (zero imports cost_engine).
  - D4: capacity parsing inline w `_effective_passive_cost_yaml` (mirror oracle), nie ekstrahowane do `cost_functions`.
  - D5: `_ROLE_SLUGS = frozenset({"wojownik","strzelec"})` lokalnie w `quote_yaml.py` — ścisłe no-engine-import w `rulesets/*`.

## Notatki / odkrycia w trakcie

- 2026-05-21: HANDOFF utworzony. Plan zaakceptowany przez usera. Następny krok: A0.1 (requirements.txt).
- 2026-05-22: A0 zaimplementowany w jednej sesji (6 kroków). 185/185 pytest passed. Smoke `OPR_RULES_BACKEND=yaml` raise NotImplementedError zgodnie ze stubbem. Procedural pozostaje bit-identyczny (default). Oczekuje commita przed startem A1.
- 2026-05-22: Decyzja A0: dispatcher czyta `config.OPR_RULES_BACKEND` dynamicznie (atrybut modułu), nie zamraża importu. Pozwala na `monkeypatch.setattr(config, "OPR_RULES_BACKEND", ...)` w testach bez re-importu. Walidacja wartości toggle jest fail-fast przy imporcie `app.config` (ValueError).
- 2026-05-22: Decyzja A0: `_assert_quote_parity` izoluje `bool` od `int` przed numeric-branch (bool jest podklasą int w Pythonie — `True == 1` byłoby fałszywie tolerowane).
- 2026-05-22: Odkrycie A1: roadmap.md wymienia "98 ability defs" ale `ABILITY_DEFINITIONS` zawiera **87**. To estymata pre-DOCX z roadmapy — migracja A1 pracuje na rzeczywistej liczbie. A4 (pipeline DOCX→YAML) wykryje gdy DOCX wymieni dodatkowe ~11 abilities.
- 2026-05-22: Decyzja A1: `abilities.yaml` jest **generowany ze skryptu inline** (Python+PyYAML), nie pisany ręcznie — 87 wpisów × ~6 pól = za dużo na manual. Generator nie jest commitowany, ale jest dokumentowany w HANDOFF żeby A4 mógł go odtworzyć po zmianach `app/data/abilities.py`.
- 2026-05-22: Decyzja A1: `TransportMultiplier.traits` to `tuple[str, ...]` w YAML (brak setów); property `traits_set` zwraca `frozenset`. Test parity porównuje `traits_set` z `frozenset()` z procedural-oracle.
- 2026-05-22: Decyzja A1: `ConfigDict(frozen=True, extra="forbid", strict=False)` — frozen dla immutability w hot path, extra="forbid" fail-fast na nieznanych kluczach, strict=False aby `dict[int, float]` akceptował również int-keyed dict z YAML (default loader emituje natywne inty dla `2: 2.3`).
- 2026-05-22: Loader LRU keyed na `(version, sha256(tables), sha256(abilities))` — w dev edycja YAML triggeruje rewalidację automatycznie, w prod pliki są zamrożone (SHA stabilne → cache hit od drugiego wywołania).
- 2026-05-22: Start A2.1. Architektura `cost_functions.py`: funkcje **pure** przyjmujące `RulesetTables` jako argument (nie importują niczego z `app/services/costs/*` poza universal-string-utils z `primitives.py`). Słownik wejściowy = tabele z YAML. 14-ta prywatna funkcja `_weapon_cost_yaml` jest helperem dla `_mistrzostwo_weapon_cost` i `_mistrzostwo_aura_cost` (oba potrzebują pełnej maszynerii kosztu broni).
- 2026-05-22: Odkrycie A2 (oracle): `abilities.py:ability_cost_components_from_name` używa `if/if/elif` (linia 325/332/339) zamiast `if/elif/elif` dla transport-branch. To **nie bug** — "otwarty transport" nie zaczyna się od "transport" (od "otwarty"), więc gałęzie są mutually-exclusive po prefiksie. DSL może odwzorować jako trzy osobne case'y z dispatchem po prefix-match.
- 2026-05-22: A2.1 done. `cost_functions.py` zaimplementowane jako 13 funkcji + `_weapon_cost_yaml` (helper dla mistrzostwa). Decyzja: `base_model_cost` przyjmuje `passive_cost_fn` jako keyword arg (callable injection) — pozwala A2.2 wstrzyknąć recipe-driven passive_cost bez tworzenia cyklicznego importu DSL ↔ recipes. `parse_aura_value` przyjmuje `slug_for_name` jako keyword arg — zależność od `ability_catalog` przeniesiona do call-site. Smoke parity vs oracle: delta=0 na 8 case'ach włącznie z assault (rekurencja) i mistrzostwo (probe-shots). Pytest 296/296.
- 2026-05-22: A2.2 done. Decyzja: DSL recipe ma jednolity shape `{fn: str, args: dict}` walidowany przez pydantic `CostRecipe` (frozen, extra=forbid). Registry to dict z metadanymi `(callable, needs_tables)` — `scale_by_tou`/`morale_modifier` nie potrzebują tabel, reszta tak. Funkcje wybrane do registry to te wywoływane bezpośrednio z YAML recipes (passive abilities + DSL primitives), nie wszystkie 13/14 — `base_model_cost`, `parse_aura_value`, `_mistrzostwo_*`, `_weapon_cost_yaml` wywołamy bezpośrednio z `_yaml_quote` w A2.4 (są zbyt złożone żeby je wyrażać przez DSL recipe). `passive_cost_dsl` przyjmuje `passive_recipes: Mapping[str, CostRecipe]` jako argument (nie module-global) — to ta sama strategia callable-injection co `passive_cost_fn`, pozwala testom wstrzyknąć dowolny zestaw recipes bez globalnego stanu.
- 2026-05-22: Odkrycie A2.2: pełen scope wzorców passive z oracle daje się wyrazić przez 4 flagi `scale_by_tou(base, scale, aura_required, aura_alt_base)`: (1) proste `base * tou` — np. zasadzka=4.0, (2) `scale=False` — odwody=0/bastion=3, (3) `aura_required=True` — bastion/niestrudzony/ostrozny zwracają 0 gdy aura=False, (4) `aura_alt_base` — instynkt -1 ↔ +1. Smoke 22/22 parity (11 abilities × {aura ON/OFF}), 0 mismatch.
- 2026-05-22: A2.3 — odkryto **5-ty wzorzec** w oracle: `dywersant` ma scale conditional on aura (1.25 stałe gdy aura=False, 1.25*tou gdy aura=True). Wymagało rozszerzenia `scale_by_tou` o 5-tą flagę `aura_scale: bool | None` (nadpisuje `scale` gdy aura=True; None=inherit). Po tym scope DSL pokrywa **wszystkie** 33 passive slugi z oracle. Full parity test: 330/330 (kartezjan 33 × 5 tou × 2 aura).
- 2026-05-22: A2.3 design: 4 sekcje YAML mapują 1:1 do gałęzi `ability_cost_components_from_name`: `passive_abilities` (oracle: passive_cost switch), `fixed_by_slug` (oracle: `slug == X: base_result = N`), `fixed_by_desc` (oracle: `desc == X: base_result = N`), `handlers` (oracle: `desc.startswith` + `slug == "mistrzostwo"`). 6 handlerów wymaga implementacji A2.4 (transport/open_transport/aura/mag/order_like/mistrzostwo) — receptury w YAML niosą stałe gry (multipliers, inner_tou), nie logikę. Plus `skip_in_default: [przygotowanie]` dla defensive parytetu z hard-kodem oracle (przygotowanie zwraca 0 w fallback-branch).
- 2026-05-22: A2.4a — manifest YAML rozszerzony: `models.py` o 4 nowe klasy (`AbilityCosts`/`CostRecipeSpec`/`HandlerSpec`/`HandlerMatch`), `loader.py` o trzecie czytanie (`ability_costs.yaml`) z walidacją "wszystkie 3 wersje równe". `HandlerSpec` ma `extra="allow"` — pozwala niesie stałe gry (open_bonus, inner_tou, range_12_multiplier, base_multiplier, mistrzostwo_multiplier, aura_mistrzostwo_multiplier) bez schema-creep. LRU cache key wzbogacony o sha256 trzeciego pliku.
- 2026-05-22: A2.4b — **kluczowe odkrycie: dead code w oracle**. `ability_cost_components_from_name` ma `if desc.startswith("transport"):` (abilities.py:325) który ustawia `base_result = capacity * multiplier`, ale ten wynik jest **natychmiast nadpisywany** przez fallback `else` branch (linia 394+), bo: (a) `transport` ma `type=passive` w katalogu, (b) `passive_cost("transport", tou, aura=False)` zwraca 0 (brak match w switch), (c) `base_result = 0` finalnie. Faktyczny dynamic transport cost jest liczony **w `role_totals.py:_effective_passive_cost`** na podstawie active_set jednostki. YAML usunęło handler `transport` z `ability_costs.yaml` zachowując tylko `open_transport`/`platforma_strzelecka` (te DZIAŁAJĄ bo desc nie zaczyna się od "transport" w if-chain B → trafiają na poprawną gałąź `if`). Note do A2.4c: dynamic transport handling przeniesie do `quote_yaml.py:_effective_passive_cost`.
- 2026-05-22: A2.4b — pełna parytetność dispatch 37/37 vs oracle: 6 handlerów (open_transport×3, aura×4 z mistrzostwo, mag×2, order_like×4 z mistrzostwo, mistrzostwo×2), fixed_by_desc×4, fixed_by_slug×5, row_delta morale (nieustraszony) + defense (delikatny), weapon_delta (niestrudzony), skip_in_default (przygotowanie), unknown slug. Pytest baseline 296/296.
- 2026-05-24: A2.5 done. **2 nowe pliki testowe, 267 testów dodanych** (563/563 passed). `test_cost_functions.py` (232) pokrywa per-fn parytet vs oracle (range/ap/blast/deadly/morale/defense/toughness/transport — z asercją YAML priority-first), 5-flag scale_by_tou edge cases (aura_required/aura_alt_base/no_scale/aura_scale), passive_cost_dsl cartesian 35 abilities × aura ON/OFF, base_model_cost 10 scenariuszy, parse_aura_value 7 form, _weapon_cost_yaml 16 traits combinations, mistrzostwo_aura×6, mistrzostwo_weapon×3 (empty/single/skip-existing-trait), weapon_cost_components_yaml×7 + weapon_cost_yaml (ignoruje cache attr). `test_quote_yaml_backend.py` (35) odpala calculate_roster_unit_quote pod 3 backendami × 10 scenariuszy (infantry basic/wojownik/strzelec, count=1, passive Nieustraszony+Zwiadowca, aura Bastion, Transport(6)+Latajacy, Otwarty Transport(8)+Szybki, weapon z Rozprysk+Przebijajaca, loadout per_model, masywny) z asercją shape + numeric parity (1e-2) + `both_assert` no-RulesetParityError + edge cases (count=0, include_item_costs=False, loadout normalization). Cache attr (`effective_cached_cost=999`) świadomie ignorowany — komentarz w `cost_functions.py:619`.
