# HANDOFF — Meta

> **Co tu jest:** spis aktywnych wątków + zablokowane zasoby + szybkozmienne notatki cross-wątkowe + LOG SESJI.
> **Czego tu NIE ma:** wiedzy stabilnej (mapa submodułów, architektura) — to jest w `docs/architecture.md`.
> **Per-wątek:** szczegóły w `docs/handoffs/HANDOFF_<slug>.md`.
> **Workflow:** uruchom `/load-context` na początku sesji. Detale konwencji: [docs/handoffs/README.md](docs/handoffs/README.md).

---

## Aktywne wątki

| Wątek (link) | Cel (1 zdanie) | Pliki zablokowane | Status |
|---|---|---|---|
| [HANDOFF_faza-b-engine-mvp](docs/handoffs/HANDOFF_faza-b-engine-mvp.md) | Strumień B — Game Engine MVP (parent). B0 ✅ + B3 ✅ + **B3.9 ✅** → B2 → B4 → B5 → B6 → B7. | (delegowane do sub-wątków; parent koordynuje) | In progress (B3.9 done; B2 ORM lub D pierwsze) |
| [HANDOFF_faza-b-rules-resync](docs/handoffs/HANDOFF_faza-b-rules-resync.md) | Sync YAML+engine z driftem zasad 2026-06-03 (Przegrupowanie per-action, Leczenie EOA, formuła T_eff aur/rozkazów, Lokalizacja enum, 8 abilities przepisanych). | `app/rulesets/v1/*.yaml`, `app/services/engine/{phases,combat,status,state,actions,effects}.py`, `app/services/rulesets/{cost_functions,handlers}.py` | In progress (R0–R7 + RW) |


## Zasoby zablokowane (reverse lookup)

| Plik / katalog | Wątek blokujący | Powód |
|---|---|---|
| `app/rulesets/v1/tables.yaml` | faza-b-engine-mvp | B0.1 — sekcja `b_mvp` (move_inches, base_area_inches_sq_per_toughness) |
| `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) | faza-b-engine-mvp | B0.2 — hand-curated lista 6 wykluczeń |
| `app/services/rulesets/models.py` | faza-b-engine-mvp | B0.3 — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic |
| `app/services/rulesets/loader.py` | faza-b-engine-mvp | B0.4 — `load_b_mvp_exclusions()` z lru_cache |
| `tests/test_b_mvp_tables.py` (NEW) | faza-b-engine-mvp | B0.5 |
| `tests/test_b_mvp_config.py` (NEW) | faza-b-engine-mvp | B0.6 |
| `docs/adr/0008-pareto-mvp.md` (NEW) | faza-b-engine-mvp | B0.7 — Status: Accepted |
| `docs/adr/0010-event-sourced-battle-log.md` (NEW) | faza-b-engine-mvp | B0.7 — Status: Accepted |
| `docs/adr/0010a-decision-freeze.md` (NEW) | faza-b-engine-mvp | B0.7 — Status: Accepted (GATE dla B3) |
| `docs/adr/0014-per-unit-wounds.md` (NEW) | faza-b-engine-mvp | B0.7 — Status: Accepted |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Po archiwizacji wątku przez `/handoff-archive` trafia tutaj 1–2 zdania podsumowania.)*

### 2026-06-02 — faza-b-3-hardening (archived) — B3.9 architecture hardening done

- Sub-wątek `faza-b-engine-mvp` zamykający Strumień B3.9 — 7 bugów + 1 dead-code cleanup w 5 dziurach architektonicznych post-B3 code review (status/geometry/ActivationContext/event-sourced status mutations/weapons inventory/ACTIVE_ABILITY_REGISTRY). Stabilizacja public API engine PRZED B2 ORM (zero migration churn dla `BattleEvent.payload_json`). 6 faz (B3.9.a–f) + B3.9.W weryfikacja + post-B3.9 code review pass (8 fixów).
- **3 nowe ADR-y Accepted**: 0045 ActivationContext, 0046 Event-sourced state mutations (proof-of-completeness ADR-0010 empirycznie), 0047 Weapons inventory + ACTIVE_ABILITY_REGISTRY.
- **Bugfixy**: #1 cumulative wounds w pkt 20.a (delta vs cumulative), #2 defender szarży regroup-testuje w aktywacji chargera (melee_combatants), #3 initial_toughness_snapshot zamiast post-action proxy, #4 charger.radius w min_gap szarzy (circle_edge_distance), #5 melee_balance reset obu stron (loop po melee_combatants), #6 silent status mutations (StatusAdded/StatusRemoved events + 13 reducerów), #7 defender kontrataku używa defender.melee_weapons[0]. Plus 8 CR-fixów: ObjectiveControlChanged + InitiativePassed events, StatusRemoved(Ufortyfikowany) emit, UNARMED_WEAPON sentinel, off-by-one w `_reduce_round_ended`, idempotency w discard_exhausted.
- Pliki NEW: `app/services/engine/{status,geometry,reducers}.py` (~500 LOC łącznie), `tests/test_engine_{status,geometry,activation_context,replay_invariant,weapons_inventory}.py` (90 nowych testów), `docs/adr/{0045,0046,0047}-*.md`. Pliki MOD: state/events/combat/phases/effects/los/resolver + `scripts/engine_smoke_replay.py` z end-to-end replay invariant assertion. Commity na `Faza_A`: `4b7df4c` (B3.9 + 3 ADR + CR-fixów).
- Weryfikacja: pytest **1340/1340 passed** (1244 baseline + 96 nowych w B3.9.a-e + CR-fix testy); parity gate `both_assert` 156/156 + `yaml` 93/93 (Strumień A niezmieniony); smoke replay GATE: 46 events, 13 event types, EXIT 0 (`apply_events(initial, all_events) == live_state` per-blob + objectives + active_player); `make rules-check` drift gate pominięty na Windows (CI weryfikuje).
- Doc updates: `docs/architecture.md` sekcja "Game engine" rozszerzona o B3.9 (status/geometry/reducers + ActivationContext + initial_toughness_snapshot + weapons inventory + ACTIVE_ABILITY_REGISTRY + 13 event types + tabela 7 bugów + 5 dziur architektonicznych zmapowanych do faz/ADR), `docs/adr/0011-rule-executor.md` refresh (Status: Accepted refreshed 2026-06-02; tabela modułów + Public API export zaktualizowane), `docs/roadmap.md` nowa sekcja "B3.9. Architecture hardening" po B3.8 + ADR index uzupełniony o 0045/0046/0047 ✓.
- **GATE ADR-0010 spełniony empirycznie** — `tests/test_engine_replay_invariant.py::test_gate_full_multi_action_replay` pass + `test_all_event_types_have_reducer` sanity (13/13 typów ma reducer). **Strumień B2 ORM odblokowany** (event types stabilne, payload_json schema zero churn). **Strumień D może startować** (engine public API stable).

### 2026-05-30 — faza-b-3-executor (archived) — B3 Game Engine MVP done

- Sub-wątek `faza-b-engine-mvp` zamykający Strumień B3 (Rule Executor + dice) — pełna semantyka SZOP_Rozjemca pkt 1, 5, 7-22 + 28 zdolności mapowanych (3 passive Cierpliwy/Tarcza/Nieustraszony + 5 weapon AP/Brutalny/Precyzyjny/Niezawodny/Podwójny + Bohater id 2 w build_initial_state + 6 wykluczeń pkt ADR-0008 + Bastion id 1 reactive + Strażnik id 31 framework stub). Pure functions + event sourcing per ADR-0010/0011.
- **8 etapów (B3.0–B3.7) + B3.8 weryfikacja** w 8 commitach na `Faza_A`: `3072488` (B3.0 preflight GATE+state+events), `6f163d6` (B3.1 dice), `f2b39a5` (B3.2 LoS), `fe5fcfc` (B3.4 combat base), `9886151` (B3.5 effects/interrupts framework), `f97dd7c` (B3.3 prediction analytic), `622f61f` (B3.4 extension: Szarża+kontratak+effects integration+Niezawodny/Podwójny), `3907f6e` (B3.6 phases), `81023e6` (B3.7 resolver + ADR-0011 Accepted), `<this>` (B3.8 weryfikacja + smoke + architecture.md + archiwizacja).
- Pliki NEW: `app/services/engine/{__init__,state,events,dice,los,prediction,combat,effects,interrupts,actions,phases,resolver}.py` (~2400 LOC łącznie), `tests/test_engine_{state,events,dice,combat,effects,interrupts,phases,resolver}.py` + `tests/test_los_geometry.py` + `tests/test_prediction_vs_simulation.py`, `scripts/engine_smoke_replay.py`, `build/b3_action_ability_audit.md` (gitignored), `docs/adr/{0011,0012,0015,0015a,0043,0044}-*.md` (6 nowych Accepted ADR).
- Weryfikacja: pytest **1244/1244 passed** (962 baseline + 282 nowych w B3.x); parity gate niezmieniona (`both_assert` 156/156 + `yaml` 93/93); drift gate CLEAN (4/4 sources SHA256 + R1=0/R2=0/R3=31 acceptable WARN); smoke replay 21 events w 7 typach reprezentowanych.
- Doc updates: `docs/architecture.md` sekcja "Game engine" z mapą modułów + event-sourced data flow + typowa orkiestracja, `docs/roadmap.md` (B3.x wszystkie ✅, ADR-y 0011/0012/0015/0015a/0043/0044 ✓), ADR-0011 promote Proposed → Accepted z 8 punktami empirycznymi rozstrzygniętymi w B3.1-B3.7.
- **Public API engine zdefiniowane** w ADR-0011 — gotowe do konsumpcji przez Strumień D (`app/services/agents/`), B4 routers (po B2 ORM), B5 szop_client, Strumień C (`mcp_server.tools.simulate_engagement` po B4).
- **GATE ADR-0010a** spełniony (5/5 punktów). **Co odkładamy do przyrostowych PR-ów** (bez zmiany ADR-0011): pozostałe ~30 passive/weapon abilities (Furia/Impet/Maskowanie/Niewrazliwy/Przebijająca/Zabójczy/Łatanie/Mag/...), full Strażnik impl, multi-target Ostrzał (pkt 14.c.i: 1-2 cele), pełna interrupt orchestracja w phases (Klątwa/Rozkaz/Oznaczenie/Usprawnienie).
- **Następne strumienie odblokowane:** B4 (API — wymaga B2 ORM models), B5 (klient), D (agenci-boty mogą startować na bazie public API). Sub-wątek `faza-b-2-models` (ORM B2) → otworzymy gdy B4 startuje.

### 2026-05-29 — faza-a-4-drift (archived) — Faza A4 done, Strumień B0 odblokowany
- Strumień A4 (pipeline drift detection DOCX/MD↔YAML, ADR-0006). 6 nowych skryptów `scripts/rules_*.py` (extract DOCX, extract MD, drift, classify geometry, sources SHA256, + `_regen_abilities_yaml.py` helper), `Makefile` cel `rules-check` orchestrator z 5 subceli, `.github/workflows/rules_drift.yml` GHA CI gate path-filtered z exit code semantics (0=pass / 1=fail / 2=warn-pass). 4 nowe YAML files: `abilities.yaml` zregenerowane (88 entries po YAML sync z Rozwoj), `drift_allowlist.yaml` symetric (`allowed_yaml_only` + `allowed_docx_only`), `source_hashes.yaml` (centralna SHA256 dla 4 source files: DOCX+PDF+2×MD). ADR-0006 promoted `Proposed → Accepted` z 8 punktami rewizji rozstrzygniętymi empirycznie. **Sub-wątek `faza-a-4-extract` archived 2026-05-26 (A4.1).** **YAML sync z `Rozwoj`** (cherry-pick `a051bb4` Bugfix + `313fb1d` Klaryfikacja zasad): abilities.py +blocked field +parowanie, kontra 2.0→1.0, transport_multipliers update (usunięte zasadzka/zwiadowca pair, samolot 3.5→4.0). **3-source canonical state** (DOCX+MD strukturalnie identyczne, YAML mirror sync). **Real drift report:** R1=0/R1w=6/R2=0/R2w=17/R3=31/R4=0 → exit 2 WARN (description wording differences akceptowane jako WARN per Q1 A4.2). **B MVP exclusion list (A4.3):** 3 abilities — `zwrot` (facing), `precyzyjny` (per_model), `dywersant` (false-positive na "strefy rozstawienia"). **Strumień B0 odblokowany** — `build/geometry_classification.md` daje hard prereq input.
- Pliki: `scripts/rules_{extract,extract_md,drift,classify_geometry,sources_check}.py` (NEW, ~1300 LOC łącznie), `scripts/_regen_abilities_yaml.py` (NEW, internal helper), `scripts/README.md` (NEW, ~200 LOC dokumentacji), `tests/test_rules_{extract,extract_md,drift,classify_geometry,sources_check}.py` (NEW, **123 nowe testy**), `app/rulesets/v1/{abilities.yaml regen, ability_costs.yaml, tables.yaml, drift_allowlist.yaml NEW, source_hashes.yaml NEW}`, `app/data/abilities.py` + `app/services/costs/{_engine,abilities,role_totals}.py` + `app/services/ability_registry.py` + `app/routers/armies.py` (z YAML sync z Rozwoj), `Makefile` (cel `rules-check` + 5 subcele), `.github/workflows/rules_drift.yml` (NEW), `requirements-dev.txt` (`python-docx>=1.1.0,<2.0`), `.gitignore` (`build/`), `app/static/docs/SZOP.docx/pdf` (z Rozwoj canon). Plus: `docs/adr/0006-pipeline-drift.md` (Proposed→Accepted), `docs/roadmap.md` (A4 all done + ADR index ✓), `docs/testing.md` (sekcja A4 pipeline), `AGENTS.md` (Komendy section), `scripts/README.md`. **Commit chain (11 commitów na `Faza_A`):** `6f74d26` (chore pyc), `2298d03` (A4.0+A4.1), `5f34ec7` (A4.1 archive + post-review), `6205c1e` (A4.2), `594f323` (A4.2+ MD), `707914f` (DOCX sync), `b15bf40`+`e6c76ec` (Rozwoj cherry-picks), `70e5444` (YAML sync), `b2bb5d3` (A4.3), `dfa0552` (A4.4), `0be37e5` (A4.5), `d4e28c5` (A4.6), `752a6b0` (A4.7 ADR Accepted).
- Weryfikacja: pytest **938/938 passed** (815 baseline + 123 nowych A4: 29 extract + 27 drift + 15 extract_md + 28 classify + 21 sources_check + 3 abilities migration delta z +1 ability). `OPR_RULES_BACKEND=both_assert pytest test_ruleset_parity.py` → **156/156** (procedural ↔ yaml parity zachowana po Rozwoj YAML sync — kontra=1.0, parowanie=1.5, transport_multipliers update wszystkie zsynchronizowane). Simulated `make rules-check` na Windows fallback (brak `make` w PATH per cross-thread notatka): sources-check CLEAN + extract 77 + extract-md 77 + classify 88→3 excluded + drift exit 2. GHA dry-run deferred (wymaga push'a na origin) — pierwszy realny PR z paths-match przetestuje workflow.
- Doc updates: `docs/roadmap.md` (A4 wszystkie checkboxy ✅, ADR index 0006 ✓), `docs/testing.md` (sekcja "A4 drift pipeline — `make rules-check`"), `AGENTS.md` Komendy (dodane `make rules-check` + `make profile`), `scripts/README.md` (NEW, pełna dokumentacja per skrypt + konwencje pisania CLI), `docs/README.md` (link do `scripts/README.md`). `docs/architecture.md` + `docs/overview.md` świadomie nieaktualizowane — A4 to dev tooling/CI gate, nie runtime architecture.
- Faza A4 zamknięta — Strumień A pełen (A0–A5 + A4). Pipeline drift detection operational. **Strumień B0 odblokowany** przez `build/geometry_classification.md`. Następne strumienie (B/C/D) mogą startować — wszystkie miały soft/hard prereq na YAML SSOT z Strumienia A.

### 2026-05-26 — faza-a-4-extract (archived)
- Sub-wątek `faza-a-4-drift` zamykający A4.1. `scripts/rules_extract.py` (~240 LOC) — content-based state machine DOCX parser (brak Headingów w `SZOP.docx`, tylko `Normal`/`List Paragraph`). Pydantic v2 `ExtractedAbility/RulesExtract`, slug z NFKD + explicit `Ł/ł→L/l` pre-replace (NFKD nie decomposuje Ł/ł). Critical bugs fixed: (1) embedded `\n` (Word soft line break) łączące wiele zdolności w jeden paragraf — fix przez `paragraph.text.split("\n")`; (2) slug "Łatanie"→"atanie" przez ASCII drop — fix przez pre-replace. **Wynik: 85 abilities** vs 87 w `ABILITY_DEFINITIONS` — różnica = **realny drift** (YAML splituje `Szybki/Wolny`, używa `burzaca`/`masywny`/`rozrywajacy`/`unik` zamiast DOCX `przelamanie`/`sekcje`/`podwojny`/`przewidywalny`, ma abstract `aura`, nie ma `AP(X)`) — A4.2 wykryje.
- Pliki: `scripts/rules_extract.py` (NEW), `tests/test_rules_extract.py` (NEW, 29 testów), `requirements-dev.txt` (`python-docx>=1.1.0,<2.0`), `.gitignore` (`build/`). Plus: ADR-0006 (Proposed), `HANDOFF_faza-a-4-drift.md` (parent, in progress), `HANDOFF_faza-a-4-extract.md` (this, archived).
- Weryfikacja: pytest 844/844 passed (815 baseline + 29 nowe). Commity: `6f74d26` (chore: untrack __pycache__), `2298d03` (A4.0+A4.1 bundle).
- Doc updates: `docs/roadmap.md` (A4 section: stan z "poza scope Fazy A" → in progress z checklistą A4.0–A4.7, A4.0+A4.1 ✅; ADR index 0006: `—` → `Proposed`).
- Następny krok: parent `faza-a-4-drift` startuje A4.2 (`scripts/rules_drift.py`) — `build/rules_extracted.yaml` jest wejściem.

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
### 2026-05-28 — strategic-cards (archived, main)
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
