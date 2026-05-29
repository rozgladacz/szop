# Roadmap

> Kierunki długofalowe. Bieżące zadania per wątek: `docs/handoffs/HANDOFF_*.md`. Stan zarchiwizowany: LOG SESJI w `HANDOFF.md`.
>
> Pełny plan architektoniczny 12–24 mies.: [docs/plans/architektura-dlugofala.md](plans/architektura-dlugofala.md)

---

## Plan długofalowy — 5 strumieni (12–24 mies.)

```
        ┌──────────────────────────────────────┐
        │  A. Deklaratywne reguły (YAML SSOT) │  hard prereq dla B
        └────┬─────────────────────┬───────────┘  soft prereq dla C
             ▼                     ▼
   ┌──────────────────┐   ┌───────────────────────┐
   │  B. Game engine  │   │  C. MCP agent (RAG)   │
   │  MVP (event-src) │   │  klient API + tokeny  │
   └────────┬─────────┘   └──────┬────────────────┘
            └───────────┬─────────┘
                        ▼
             ┌──────────┴─────────┐
             │  D. Agenci (boty)  │  E. Wzbogacanie modelu
             │  exploit-hunting   │  (po stabilizacji B)
             └────────────────────┘
```

Strumienie równoległe. Aplikacja użyteczna w każdej fazie. Procedural engine **nie jest usuwany** — koexistuje z YAML pod feature toggle do ≥3 mies. stabilności w prod.

---

## Strumień A — Deklaratywne reguły (YAML + SSOT) ✅

> Zamiana hardcoded tabel i `if/elif` na YAML + Pydantic. Feature toggle `OPR_RULES_BACKEND ∈ {procedural, yaml, both_assert}`. **Faza A done (2026-05-24); A4 świadomie poza scope — osobny wątek gdy wymagane.** Pełny przebieg: `HANDOFF.md → LOG SESJI → 2026-05-24 — faza-a (archived)`.

### A0. Feature toggle (prereq) ✅
- [x] ENV `OPR_RULES_BACKEND` z defaultem `procedural`
- [x] Dispatcher w `app/services/costs/quote.py` (procedural | yaml | both_assert)
- [x] Tryb `both_assert`: wywołuje oba, raise `RulesetParityError` jeśli delta > 1e-3, zwraca wynik procedurala
- [x] CI gate: `make test-parity` — uruchamia `both_assert` na `test_ruleset_parity.py` i `yaml` na `tests/yaml_backend/`
- [x] ADR-0005: Feature toggle — procedural i YAML koexistują do dojrzałości

### A1. Schema + słowniki ✅
- [x] `app/rulesets/v1/` — katalog plików YAML
- [x] `app/services/rulesets/models.py` — Pydantic v2 schema (`RulesetTables`, `RulesetAbility`, `RulesetManifest`, `TransportMultiplier`)
- [ ] `make generate-schema` → `docs/schemas/ruleset_v1.schema.json` (deferred — VS Code YAML extension nice-to-have)
- [x] `app/rulesets/v1/tables.yaml` — migracja 18 tabel z `app/services/costs/_engine.py`
- [x] `app/rulesets/v1/abilities.yaml` — **87** definicji z `app/data/abilities.py` (nie 98 jak myślano w pre-A1 estymacie)
- [x] `app/services/rulesets/loader.py` — `@lru_cache(maxsize=4)` na public entrypoincie + SHA256 discriminators dla dev reload
- [x] Testy: `tests/test_tables_migration.py` (22), `tests/test_abilities_migration.py` (89) — exact match vs oryginał
- [x] ADR-0003: YAML + Pydantic v2 jako format reguł

### A2. Cost DSL ✅
- [x] `app/services/rulesets/cost_functions.py` — 13 czystych funkcji DSL + wrappery weapon_cost
- [x] `app/services/rulesets/dispatcher.py` — `_REGISTRY` (9 fn) + `call_recipe()` + `passive_cost_dsl()`
- [x] `app/services/rulesets/handlers.py` — 6 handlerów (transport/open_transport/aura/mag/order_like/mistrzostwo) + `ability_cost_components_yaml()`
- [x] `app/services/rulesets/quote_yaml.py` — `roster_unit_role_totals_yaml`, 1:1 port `role_totals.py` z YAML substytucjami
- [x] `app/rulesets/v1/ability_costs.yaml` — 33 passive recipes + 7 fixed_by_slug + 4 fixed_by_desc + 6 handlers + `skip_in_default`
- [x] `_yaml_quote()` w `app/services/costs/quote.py` — dispatcher + body mirror `_procedural_quote`
- [x] Testy: `tests/test_cost_functions.py` (232), `tests/test_quote_yaml_backend.py` (35)
- [x] ADR-0004: Cost DSL — hardcoded function dispatcher zamiast eval, callable injection (`passive_cost_fn`, `slug_for_name`), inwariant czystości "no-oracle-import" w `rulesets/*`

### A3. Testy (cross-cutting) ✅
- [x] Golden tests procedurala (istniejące) — semantyka nieruszona; baseline dla `both_assert`
- [x] `tests/yaml_backend/test_*_yaml.py` — te same scenariusze pod `OPR_RULES_BACKEND=yaml` (93 testy w 4 plikach: passive/active/weapon/mistrzostwo)
- [x] `tests/test_ruleset_parity.py` — 100 cartesian + 55 manual + None-unit = 156 testów pod `both_assert`; delta ≤ 1e-3
- [x] CI gate: `make test-parity` (cel w Makefile)

### A4. Pipeline DOCX → PDF → YAML (in progress — wątek `faza-a-4-drift` od 2026-05-26)
- [x] A4.0: ADR-0006 (Proposed) + HANDOFF bootstrap (`faza-a-4-drift` parent + `faza-a-4-extract` sub-thread). Plan 7 faz, decyzja: drift-only (nie auto-gen YAML); 4 typy raportów R1/R4 ERROR + R2/R3 WARN.
- [x] A4.1: `scripts/rules_extract.py` — DOCX → `build/rules_extracted.yaml`. Parser content-based state machine (brak Headingów w DOCX), `python-docx>=1.1.0` w `requirements-dev.txt`, 29 testów.
- [x] A4.1+: `scripts/rules_extract_md.py` — formalna MD (SZOP_Zdolnosci.md) → `build/rules_md.yaml`. Schema reuse `RulesetAbility`. 15 testów.
- [x] A4.2: `scripts/rules_drift.py` — diff 4 raporty + allowlist (R1+R2 symetria) + exit 0/1/2 + 28 testów. Pierwszy real run: R1=0 R2=0 R3=31 R4=0 → exit 2 WARN.
- [x] A4.2+: YAML sync z `Rozwoj` (cherry-pick a051bb4+313fb1d) — abilities.py 88 entries +blocked field, cost path (kontra=1.0 +parowanie=1.5, transport_multipliers), abilities.yaml/tables.yaml/ability_costs.yaml mirror sync. both_assert parity 156/156.
- [x] A4.3: `scripts/rules_classify_geometry.py` — `build/geometry_classification.md` z 3 excluded (zwrot/precyzyjny/dywersant), 7 kategorii, 28 testów. **Strumień B0 odblokowany.**
- [ ] A4.4: `scripts/rules_pdf_check.py` — DOCX vs PDF SHA256
- [ ] A4.5: `Makefile` cel `rules-check` (orchestracja 4 skryptów)
- [ ] A4.6: `.github/workflows/rules_drift.yml` (CI gate path-filtered)
- [ ] A4.7: ADR-0006 promocja `Proposed → Accepted` (8 punktów rewizji w sekcji "Do rewizji")

### A5. Wydajność ✅
- [x] `tests/test_quote_performance_regression.py` — `min(yaml_time/proc_time)` ≤ 1.30 (3 attempts × min, headroom 0.10 na Windows noise; bare-metal Linux median ~1.10×)
- [x] **A5 optymalizacje wymuszone przez test:** `@lru_cache(maxsize=4)` na `load_ruleset()` (skip SHA recheck na hot path); `CostRecipe = CostRecipeSpec` alias (eliminacja per-quote rebuild loopa po post-review cleanup). Ratio 3.57× → 1.158×.
- [x] `scripts/profile_quote.py --backend procedural|yaml|both_assert` (argparse) + `Makefile:profile BACKEND=...`
- [x] `docs/PERFORMANCE.md` — baseline obu backendów (sekcja "Baseline YAML backend (Faza A5)")
- [x] ADR-0007: Cache rulesetów — single LRU level (id-keyed cache usunięty w post-review)

---

## Strumień B — Game Engine MVP (event-sourced, Pareto)

> Symulator pełnej bitwy 1v1. Uproszczony model: oddział = koło, tereny = koła/linie, brak orientacji/per-model loadout. Pełne zasady przebiegu rundy.

### B0. Pareto MVP — założenia (prereq)
- [ ] Zdefiniuj w `tables.yaml`: wzór na radius_inches = f(models_count, toughness, base_size_mm)
- [ ] Globalna stała ruchu: 6" w `tables.yaml` (nie per-unit)
- [ ] Lista exclusions z `build/geometry_classification.md` (A4) — engine raise `UnsupportedAbilityError` dla tych zdolności
- [ ] ADR-0008: Pareto MVP specification
- [ ] ADR-0010a: Decision freeze — "rules text dojrzały do implementacji B3 actions" (GATE)

### B2. Modele danych (4 tyg)

**ORM — persistence layer (`app/models.py`):**
- [ ] `User` — rozszerz: `role` (dodaj `agent`), `owner_user_id?`, `agent_kind?`
- [ ] `Battle` — `(p1_user_id, p2_user_id, p1_roster_id, p2_roster_id, winner_user_id?, current_round, rng_seed, status, …)`
- [ ] `BattleInvite` — `(from_user_id, to_user_id?, roster_id, scenario, status ∈ {pending/accepted/declined/expired}, expires_at)`
- [ ] `BattleEvent` — append-only: `(battle_id, sequence, event_type, payload_json, timestamp)` + UniqueConstraint
- [ ] `BattleSnapshot` — opcjonalny: `(battle_id, sequence_at, state_json)` (MVP: nie używany)
- [ ] `Unit` — dodaj: `base_size_mm: int = 25`, `base_shape: str = "round"`
- [ ] `AgentToken` — `(agent_user_id, owner_user_id, scope_json, expires_at, revoked_at?, last_used_at)`
- [ ] `AgentAuditLog` — `(user_id?, agent_user_id?, route, params_json, timestamp)`
- [ ] Migracja Alembic: `XXX_add_battle_models.py`

**Runtime dataclass'y — czysty Python (`app/services/engine/state.py`):**
- [ ] `UnitBlob(frozen=True)` — `(id, owner_player, position, radius_inches, models_alive, wounds_remaining, passives, status_flags)` — semantyka wounds jak istniejący „Stan bitewny"
- [ ] `BattleState(frozen=True)` — `(round, active_player, activations_remaining, blobs, terrain, pending_effects, pending_interrupts, score)`
- [ ] `TerrainCircle(frozen=True)`, `TerrainLine(frozen=True)`

**Event definitions (`app/services/engine/events.py`):**
- [ ] Frozen dataclass per event type: `MoveExecuted`, `ShotResolved`, `MeleeResolved`, `ModelKilled`, `MoraleTestPassed`, `EffectApplied`, `InterruptTriggered`, `RoundEnded`
- [ ] `event_to_json()` + `json_to_event()` serializer

**Persistence (`app/services/engine/persistence.py`):**
- [ ] `save_events(session, battle_id, events)` — append do BattleEvent
- [ ] `load_events(session, battle_id, since=0)` — odczyt z db
- [ ] `create_snapshot()` — optionally save snapshot (MVP: nie wywoływane)

- [ ] ADR-0010: Event-sourced battle log
- [ ] ADR-0010b: Eventy + immutable state; ORM tylko persistence
- [ ] ADR-0014: Obrażenia per-oddział (zgodne z „Stan bitewny")

### B3. Rule Executor + dice (5–7 tyg, gate: ADR-0010a)

**Dice (`app/services/engine/dice.py`, ~80 linii):**
- [ ] `DeterministicDice(seed)` — `roll_d6(count, modifiers)`, `roll_with_threshold(pool, threshold)`
- [ ] Testy: reproducibility, distribution, threshold
- [ ] ADR-0012: Własna biblioteka dice, deterministic seed

**LoS (`app/services/engine/los.py`):**
- [ ] 3-state: `WIDZI` / `NIE_WIDZI` / `OSŁONA` — via N=16 deterministycznych punktów na okręgu celu
- [ ] `check_los(attacker, target, terrain, N=16) → LoSState`
- [ ] Testy: `tests/test_los_geometry.py` — 30 hand-crafted scenarios
- [ ] ADR-0043: LoS 3-stanowy — sampling N=16, plan B: N=32 lub analytic tangent

**Prediction (`app/services/engine/prediction.py`):**
- [ ] `expected_damage(attacker, defender, weapon_slug, terrain, ruleset) → DamageDistribution` — analitycznie, binomial CDF, bez RNG
- [ ] `DamageDistribution(mean, pmf, p_at_least(), p_kill())`
- [ ] `would_see(pos, target, terrain) → LoSState`
- [ ] Testy: `tests/test_prediction_vs_simulation.py` — 100 scenariuszy × 1000 Monte Carlo; mean ±3σ; Chi-square dla pmf
- [ ] ADR-0044: Prediction module dla agentów (bez symulacji)

**Combat (`app/services/engine/combat.py`):**
- [ ] `resolve_ranged_attack(attacker, defender, weapon, dice, terrain, ruleset) → CombatResult`
- [ ] Faza 1: Declare + attacker modifiers; REACTIVE WINDOW dla broniącego (jednorazowe, atomowe); Faza 2: Dice resolution; Faza 3: Wound allocation
- [ ] `resolve_melee_attack(…)` — analogicznie
- [ ] ADR-0015a: Reactive window — jednorazowa, atomowa, nie generuje nowych okien

**Effects + Interrupts (`app/services/engine/effects.py`, `interrupts.py`):**
- [ ] `EFFECT_REGISTRY` — `{slug: apply_fn}`; każda funkcja czysta: `(unit, context) → unit`
- [ ] `InterruptManager` — 4 zamknięte punkty: `activation_start`, `after_action`, `before_regroup`, `after_regroup`; constraint: interrupt nie generuje nowego punktu
- [ ] ADR-0015: 4 zamknięte interrupt points

**Phases (`app/services/engine/phases.py`):**
- [ ] `setup_phase(roster_p0, roster_p1, scenario, ruleset) → BattleState`
- [ ] `deployment_round(state, actions) → (BattleState, events)`
- [ ] `activation_phase(state, action) → (BattleState, events)`
- [ ] `round_end_phase(state) → (BattleState, events)`

**Resolver (`app/services/engine/resolver.py`):**
- [ ] `apply(state, action, dice, ruleset, terrain) → (BattleState, list[BattleEvent])` — czysta funkcja, zero DB access
- [ ] ADR-0011: Rule executor — hardcoded klasy na MVP

### B4. API (3 tyg)
- [ ] `app/routers/battles.py` — endpointy: `POST /battles/invite`, `POST /battles/invite/{id}/accept`, `POST /battles`, `GET /battles/{id}`, `GET /battles/{id}/events`, `POST /battles/{id}/actions`, `POST /battles/{id}/interrupts`, `POST /battles/{id}/simulate`, `POST /battles/{id}/replay`
- [ ] Auth: tylko gracze bitwy (nie trzecia osoba); agent wymaga scope
- [ ] Pydantic schemas w `app/schemas.py` — BattleState, BattleEvent, Action (polimorficzne)
- [ ] Optimistic locking na `BattleEvent.sequence` — zapobiega race condition

### B5. Klient gry `szop_client` (równolegle z B4, 2 tyg)
- [ ] `szop_client/protocol.py` — `class GameClient(Protocol)` z metodami: `create_battle`, `get_state`, `take_action`, `subscribe_events`, `simulate`
- [ ] `szop_client/http.py` — `HttpClient(base_url, token)` — wywołuje FastAPI przez httpx
- [ ] `szop_client/local.py` — `LocalClient(db_session, user_id)` — in-process BattleEngine; szybki batch (1000 bitew/min)
- [ ] `szop_client/setup.py` — `pip install -e szop_client/`
- [ ] `tests/test_clients_parity.py` — `HttpClient.simulate(...) == LocalClient.simulate(...)` dla tych samych args + seed
- [ ] ADR-0016: szop_client jako wydzielony moduł

### B6. Prezentacja (opcjonalne, 3–4 tyg)
- [ ] `scripts/battle_replay.py <id>` — CLI terminal output
- [ ] SSE stream `GET /battles/{id}/events`
- [ ] `app/static/js/modules/battle_canvas.js` — minimalny 2D canvas (Konva.js lub goły Canvas)
- [ ] ADR-0013: Engine headless-first, UI opcjonalne

### B7. Test bed (2 tyg)
- [ ] `tests/fixtures/battles/*.yaml` — golden scenariusze z predefined seed i oczekiwanym wynikiem
- [ ] `tests/test_engine_regression.py` — golden battles deterministyczne (zmiana golden = świadoma zmiana rulesetu → ADR)

---

## Strumień C — Lokalny agent MCP (RAG + klient API)

> MCP server jako klient publicznego API (przez szop_client HTTP). Nie łączy się bezpośrednio z DB.

### C1. Infrastruktura (3 tyg)
- [ ] `mcp_server/{server.py, config.py}` — MCP Python SDK, rejestracja narzędzi
- [ ] Endpointy tokenów: `POST /agent_tokens`, `DELETE /agent_tokens/{id}`, `GET /agent_tokens`
- [ ] Middleware `require_agent_scope(scope_name)` — weryfikacja + `AgentAuditLog`
- [ ] `AgentProposal` model + `POST /agent_proposals`, `POST /agent_proposals/{id}/approve`
- [ ] Frontend: approval UI "[Agent chce X] [Zezwól] [Odrzuć]"
- [ ] ADR-0021: MCP jako klient publicznego API; ADR-0024: Consent-gated writes; ADR-0025: Rola agent + scoped tokens

### C2. RAG (3 tyg)
- [ ] `mcp_server/indexer.py` — chunki ~300 słów / 50 overlap z DOCX; embed via `paraphrase-multilingual-MiniLM-L12-v2`; store w `sqlite-vec`
- [ ] `mcp_server/search.py` — hybrid: dense + BM25 (`rank_bm25`)
- [ ] `make reindex-rules` — rebuild vector store
- [ ] Ewaluacja: ≥70% recall@5 na 30 ręcznych Q&A
- [ ] ADR-0022: sqlite-vec; ADR-0023: sentence-transformers offline

### C3. Narzędzia MCP (3 tyg)
- [ ] `lookup_rule(query)` — RAG nad SZOP.docx + YAML
- [ ] `explain_ability(slug)` — strukturalny lookup z `abilities.yaml`
- [ ] `validate_loadout(payload)` — `POST /rosters/.../quote`
- [ ] `find_exploit_candidates(army_id)` — heurystyka cost/effectiveness
- [ ] `score_list(roster_id)` — quick heuristic
- [ ] `simulate_engagement(roster_a, roster_b, n)` — LocalClient batch

---

## Strumień D — Agenci konkurujący (testowanie)

> Bot players do exploit-hunting i balansu. Wszystko na MVP modelu z B.

### D1. Heuristic players (4 tyg)
- [ ] `app/services/agents/base.py` — `class Player(ABC)`: `choose_action(state) → Action`
- [ ] `random_player.py` — losowy wybór spośród valid actions
- [ ] `greedy_player.py` — maks `damage_dealt - damage_taken` w 1 turze; używa `prediction.py`
- [ ] `policy_eval.py` — `evaluate_state(state, perspective) → float` (HP balance + board control)

### D2. Balance simulation (2 tyg)
- [ ] `scripts/balance_simulate.py --ruleset v1 -n 1000` → CSV: win rates per rozpiska/zdolność/broń
- [ ] `scripts/balance_report.py` → `reports/balance/YYYY-MM-DD.md` z wykresami

### D3. Exploit hunting (2 tyg)
- [ ] `scripts/exploit_hunt.py` — generuje losowe rozpiski na koncie `agent_kind=exploit_hunter`, gra vs siebie, raportuje top 10 (win_rate/points)
- [ ] Każdy exploit → ADR z propozycją zmiany DOCX

### D4. Adversarial play (4 tyg, opcjonalne)
- [ ] Frontend UI "Play vs AI" — wybór agenta z listy
- [ ] `minimax_player.py` — depth-2 (dla testów, ~100 ms/action)
- [ ] Leaderboard `reports/leaderboard.md`
- [ ] ADR-0030: Wielu agentów konkurujących — osobne konta + leaderboard

---

## Strumień E — Wzbogacanie modelu (po B stabilne, tydzień 20+)

### E1. Per-model granularity (4–5 tyg)
- [ ] `BattleModel` frozen dataclass w `app/services/engine/per_model.py`
- [ ] `expand_blob_to_models(blob)` — na potrzeby heterogenicznych loadoutów
- [ ] Adapter eventów: `BlobModified` → `ModelModified`
- [ ] ADR-0040: Migration blob → per-model

### E2. Geometria terenu (3 tyg)
- [ ] `TerrainPolygon` w `app/services/engine/terrain_complex.py`
- [ ] Ray-casting w `los.py` dla poligonów
- [ ] ADR-0041: Terrain shapes beyond circle/line

### E3. Złożone zdolności (iteracyjnie)
- [ ] Lista priorytetowa z `build/geometry_classification.md`
- [ ] Zdolność `Zwrot` wprowadza `UnitBlob.facing_deg: float = 0.0`
- [ ] Każda zdolność = osobny PR + test + ADR

---

## Cross-cutting: telemetria od dnia 1 (ADR-0017)

- [ ] `structlog` w `app/services/engine/{resolver, persistence}.py` — każdy event: `battle_id, action_id, actor_user_id`
- [ ] `data/battle_metrics/{battle_id}.jsonl` — `action_count, dice_rolls_total, dice_distribution, time_per_action_ms`
- [ ] `data/agent_metrics/{agent_user_id}.jsonl` — `decision_time_ms, decision_quality_score`
- [ ] `scripts/analyze_battle.py <id>` — raport markdown z wykresami
- [ ] `.gitignore`: `data/{battle,agent}_metrics/`

---

## ADR index

| # | Tytuł | Status |
|---|-------|--------|
| 0001 | Refaktor app.js — IIFE bez bundlera | ✓ |
| 0002 | SSOT kosztów: calculate_roster_unit_quote | ✓ |
| 0003 | Format reguł: YAML + Pydantic v2 | ✓ |
| 0004 | Cost DSL: function dispatcher | ✓ |
| 0005 | Feature toggle: procedural + YAML | ✓ |
| 0006 | Pipeline docx↔yaml: drift-only | Proposed (promocja na Accepted w A4.7) |
| 0007 | Cache rulesetów: LRU na load_ruleset | ✓ |
| 0008 | Pareto MVP: oddział = koło, pełne zasady | — |
| 0010 | Event-sourced battle log | — |
| 0010a | Decision freeze (GATE dla B3 actions) | — |
| 0010b | Eventy + immutable state; ORM tylko persistence | — |
| 0011 | Rule executor: hardcoded → YAML handlers | — |
| 0012 | Dice: własna biblioteka, deterministyczny seed | — |
| 0013 | Engine headless-first | — |
| 0014 | Obrażenia per-oddział (= Stan bitewny) | — |
| 0015 | 4 zamknięte interrupt points | — |
| 0015a | Reactive window w akcji ataku (atomowe) | — |
| 0016 | szop_client jako wydzielony moduł | — |
| 0017 | Telemetria od dnia 1 | — |
| 0020 | MCP runtime: Python SDK | — |
| 0021 | MCP jako klient publicznego API | — |
| 0022 | Vector store: sqlite-vec | — |
| 0023 | Embeddings: sentence-transformers offline | — |
| 0024 | Consent-gated agent writes | — |
| 0025 | Rola agent + scoped tokens | — |
| 0030 | Wielu agentów: osobne konta + leaderboard | — |
| 0040 | Migration blob → per-model | — |
| 0041 | Terrain shapes beyond circle/line | — |
| 0042 | Facing: wprowadzane z Zwrot | — |
| 0043 | LoS 3-stanowy (sampling N=16) | — |
| 0044 | Prediction module (damage PMF + visibility) | — |

---

## Decyzje strategiczne

- **Backend = SSOT dla kosztów.** Frontend renderuje, nie liczy. ✅
- **Procedural engine nie jest usuwany** — feature toggle, usunięcie po ≥3 mies. prod stabilności + perf audit.
- **Hierarchia oddziałów = dziedziczenie z różnicami.** Wariant trzyma tylko delta.
- **Monolityczne pliki dzielimy stopniowo.** Komentarze sekcji w `app.js`, `_engine.py` — patrz `docs/developing.md`.
- **Reguły gry (`app/static/docs/`) = source of truth.** Niedopuszczalna dywergencja kod ↔ DOCX.
- **Procedural ↔ YAML parity = CI gate.** `both_assert` wykrywa każdą rozbieżność > 1e-3.
- **Game engine = czyste funkcje + event sourcing.** ORM tylko do persistence, brak logiki gry w ORM.
- **MCP agent = klient HTTP, nie direct DB.** Jeden mechanizm uprawnień, jeden audit trail.
