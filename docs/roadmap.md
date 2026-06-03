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
- [x] A4.4: `scripts/rules_sources_check.py` — SHA256 dla 4 source files (extended scope vs PDF-only). `app/rulesets/v1/source_hashes.yaml` centralizacja, 21 testów.
- [x] A4.5: `Makefile` cel `rules-check` (orchestracja 5 skryptów; drift LAST żeby exit 2 WARN nie zatrzymał wcześniejszych artefaktów). + AGENTS.md/docs/testing.md udokumentowane.
- [x] A4.6: `.github/workflows/rules_drift.yml` — CI gate path-filtered (PR+push), exit code semantics (0=pass, 1=fail, 2=warn-pass), artifact upload + step summary z raportów.
- [x] A4.7: ADR-0006 promocja `Proposed → Accepted` — 8 punktów rewizji rozstrzygnięte empirycznie po A4.1–A4.6. **Faza A4 done. Strumień B0 odblokowany.**
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

### B0. Pareto MVP — założenia (prereq) ✅ (2026-05-30, wątek `faza-b-engine-mvp`)
- [x] `tables.yaml > b_mvp`: `move_inches=6`, `base_area_inches_sq_per_toughness=1` (podstawka modelu = 1 in²/punkt wytrzymałości), `pi_approx`. Wzór: `radius_inches = sqrt(sum(toughness)/pi)`; Bohater (id 2) liczy się jako `toughness/2`.
- [x] `b_mvp_exclusions.yaml` (NEW): hand-curated 6 entries (samolot/wrak/wysoki/zwrot/sterowany/zuzywalny). Rozbieżność z A4.3 (3 entries: dywersant/precyzyjny/zwrot) udokumentowana w ADR-0008 — A4.3 jest heurystyką keyword match, B0 list to user decision.
- [x] `app/services/rulesets/{models.py BMvpConfig/Exclusion/Exclusions, loader.py load_b_mvp_exclusions}` — Pydantic + lru_cache; engine raise `UnsupportedAbilityError` przy budowie BattleState
- [x] ADR-0008: Pareto MVP specification (Accepted)
- [x] ADR-0010: Event-sourced battle log (Accepted; sub-decyzja 0010b scalona)
- [x] ADR-0010a: Decision freeze GATE — 5 warunków (Accepted)
- [x] ADR-0014: Per-unit wounds — 4 kategorie ran (Accepted; Zguba/Zemsta wykluczone)

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

- [ ] ADR-0010: Event-sourced battle log ✓
- [ ] ADR-0010b: Eventy + immutable state; ORM tylko persistence ✓ (scalone z 0010)
- [ ] ADR-0014: Obrażenia per-oddział (zgodne z „Stan bitewny") ✓

### B3. Rule Executor + dice — **DONE 2026-05-30** (sub-wątek `faza-b-3-executor`, 8 commitów)

Pełna semantyka SZOP_Rozjemca pkt 1, 5, 7-22 + 28 zdolności (3 passive + 5 weapon + Bohater + 6 wykluczeń + Strażnik stub + reactive Bastion). Pure functions + event sourcing. **1244/1244 testów** (282 nowych vs 962 pre-B3 baseline). **10 ADR-ów Accepted**: 0008/0010/0010a/0011/0012/0014/0015/0015a/0043/0044.

**Dice (`app/services/engine/dice.py`):**
- [x] `DeterministicDice(seed)` na `random.Random` (stdlib), `roll_d6(count)`, `roll_with_threshold(count, threshold, modifier, natural_6/1 flags)` per pkt 1 a-d. `RollResult` frozen z natural rolls.
- [x] 24 testy (reproducibility, distribution chi-square, threshold semantics, Brutalny/Delikatny, modifier clamp).
- [x] ADR-0012 Accepted: `random.Random` z stdlib, brak biblioteki zewnętrznej, 4 inwarianty replay.

**LoS (`app/services/engine/los.py`):**
- [x] 3-state `LoSState ∈ {WIDZI, NIE_WIDZI, OSŁONA}` z sampling N=16 punktów na obwodzie celu, Zasłaniający exception pkt 4.c.iii.
- [x] Geometry primitives: `_segment_intersects_circle` (closest point projection), `_segments_intersect` (CCW orientation).
- [x] 43 testy (geometry 12, Blokujący 4, Zasłaniający 5, multi-terrain 2, non-blocking 3, edge cases 4, enum 2, realistic 2).
- [x] ADR-0043 Accepted: N=16 Pareto sweet spot, plan B N=32/analytic.

**Prediction (`app/services/engine/prediction.py`):**
- [x] `expected_damage(attacker, defender, weapon, terrain)` analityczny binomial bez RNG. `DamageDistribution(pmf, mean, p_at_least, p_kill, p_full_kill, expected_models_killed)`. `would_see` hipotetyczny LoS.
- [x] REUSES `compute_cover/compute_attack_modifiers/compute_defense_modifier` z combat.py (consistency invariant).
- [x] 38 testów + **Monte Carlo parity 8 scenariuszy × 500 sym + cover** — ±3σ tolerance.
- [x] ADR-0044 Accepted: analytic dla agents/MCP, 5 planowanych konsumentów.

**Combat (`app/services/engine/combat.py`):**
- [x] `WeaponProfile` + `CombatResult` + `ChargeResult` frozen.
- [x] `resolve_ranged_attack` (pkt 17 + 19): osłona, AP, Brutalny, Precyzyjny, hit/defense rolls, wound allocation pkt 17.d-e + pkt 18 z prefer_hero.
- [x] `resolve_melee_attack`: + bilans wręcz pkt 20.c.
- [x] `resolve_charge_attack`: pełna Szarża pkt 14.d.i-vi z reactive kontratakiem pkt 14.d.iv (ADR-0015a) + Bastion id 1.
- [x] Helpers: `effective_attack_quality` (Niezawodny id 63 → Q=2), `_apply_podwojny_extra_hits` (Podwójny id 66).
- [x] Lazy import z effects.py — Cierpliwy/Tarcza/Nieustraszony faktycznie modyfikują rolls.
- [x] 56 testów (combat base 37 + extension 19).
- [x] ADR-0015a Accepted: reactive jednorazowy/atomowy/no nested.

**Effects + Interrupts (`app/services/engine/{effects,interrupts}.py`):**
- [x] `EffectContext` frozen + 4 per-hook registries (defense/attack/morale/weapon modifiers). `aggregate_*_modifier` aggregators. MVP passive: Cierpliwy/Tarcza/Nieustraszony.
- [x] `InterruptPoint` enum (4 punkty per ADR-0015), `register_interrupt_handler(point, slug)`, `get_eligible_interrupts`, `trigger_interrupt`. Strażnik (id 31) MVP stub.
- [x] 38 testów (21 effects + 17 interrupts).
- [x] ADR-0015 Accepted: 4 zamknięte punkty per pkt 12, no nested.

**Phases (`app/services/engine/phases.py`):**
- [x] `setup_phase(rosters, terrain, objectives, initiative)` — pkt 7+9.
- [x] `deployment_round(state, actions)` — pkt 13, emit MoveExecuted move_type="deploy".
- [x] `activation_phase(state, action, dice)` — dispatch per Action type → akcja → Przegrupowanie pkt 20 (uwzględnia pkt 20.b/c/d + passive morale modifiers) → Aktywowany.
- [x] `round_end_phase(state)` — pkt 8.c reset Aktywowany + `_check_objective_control` pkt 5.d (Przyszpilony nie kontroluje pkt 22.b.ii) + RoundEnded + is_game_over po round 4 pkt 5.f.
- [x] 25 testów.

**Resolver (`app/services/engine/resolver.py`) — PUBLIC API:**
- [x] `apply(state, action, dice, sequence) → ResolverResult(state, events, next_sequence)` — pure function dispatcher.
- [x] Walidacja `IllegalActionError` (5 powodów). Switch active_player pkt 8.a + fallback. Helpers `should_end_round` / `is_battle_over`.
- [x] 22 testów (per Action type, walidacja, switch, determinism, smoke 2v2 + game over after round 4).
- [x] ADR-0011 Accepted: hardcoded klasy/funkcje, isinstance dispatch dla 5 Action types, lazy import dla combat↔effects cycle. Public API engine zdefiniowane.

**B3.8 weryfikacja end-to-end:**
- [x] Pytest **1244/1244** (962 baseline + 282 nowych w B3)
- [x] Parity gate Strumień A: `both_assert` 156/156, `yaml` 93/93 — niezmieniony
- [x] Drift gate: 4/4 sources SHA256 CLEAN, R1=0/R2=0/R3=31 (acceptable warn per ADR-0006)
- [x] Smoke replay: `scripts/engine_smoke_replay.py` — minimal 2v2 battle, 21 events, 7 typów eventów reprezentowanych
- [x] `docs/architecture.md` — sekcja "Game engine" z mapą modułów + event-sourced data flow + typowa orkiestracja

### B3.9. Architecture hardening — **DONE 2026-06-02** (sub-wątek `faza-b-3-hardening`, 6 faz)

7 bug-fixów + 1 dead-code cleanup z post-B3 code review, zorganizowane w 5 dziurach architektonicznych. **PRZED B2 ORM** żeby stabilizować event types schema (zero migration churn). **3 nowe ADR-y Accepted**: 0045/0046/0047. Pytest **1337/1337** (1244 baseline + 93 nowych w B3.9.a-e), parity 156/156, drift CLEAN, smoke replay GATE pass (replay invariant assertion EXIT 0).

- [x] **B3.9.a** — `app/services/engine/status.py` (NEW) — `StatusFlag(str, Enum)` + idempotentne `add_status`/`remove_status`. Konsolidacja 3 kopii STATUS_* z effects/phases/combat. 22 testów (`test_engine_status.py`).
- [x] **B3.9.b** — `app/services/engine/geometry.py` (NEW) — `distance` (math.hypot), `point_in_circle`, `segment_intersects_circle`, `segments_intersect`, **`circle_edge_distance`** (fix bug #4: charger.radius ignored w min_gap), `UNIT_CIRCLE_16` precomputed. Konsolidacja 4 kopii `_distance`. 27 testów (`test_engine_geometry.py`).
- [x] **B3.9.c** — `ActivationContext` (`phases.py`) + `BattleState.initial_toughness_snapshot` (`state.py`) — frozen delta state per aktywacja: `wounds_received_this_activation` zamiast cumulative (fix bug #1 pkt 20.a), `melee_combatants` frozenset (fix bug #2: defender szarży regroup-testuje w aktywacji chargera + bug #5: melee_balance reset obu stron). `initial_toughness_for(state, blob_id)` helper (fix bug #3: snapshot zamiast post-action proxy). **ADR-0045 Accepted**. 17 testów (`test_engine_activation_context.py`).
- [x] **B3.9.d** — `app/services/engine/reducers.py` (NEW) z `@register_reducer` dla wszystkich 11 typów; 3 nowe eventy w `events.py`: `StatusAdded`/`StatusRemoved`/`MeleeBalanceReset`. Emit Status* w combat/phases zamiast silent `replace()` (fix bug #6). Algorytm wound allocation w reducerach mirror `combat._allocate_wounds_to_defender`. **ADR-0046 Accepted** — proof-of-completeness ADR-0010 empirycznie. 8 testów + GATE `test_gate_full_multi_action_replay` (per-blob bit-perfect) + sanity `test_all_event_types_have_reducer` (`test_engine_replay_invariant.py`).
- [x] **B3.9.e** — `UnitBlob.melee_weapons`/`ranged_weapons: tuple[WeaponProfile, ...]` + `WeaponProfile` migration z combat.py do state.py. `build_initial_state` parsuje `unit["weapons"]` z partycją po `range_inches`. Fix bug #7: `resolve_charge_attack` counter używa `defender.melee_weapons[0]` z fallback. `_ACTIVE_ABILITY_REGISTRY` w `effects.py` + `register_active_ability(slug)` decorator + `get_active_ability(slug)` lookup. `phases._apply_special` redukcja do dispatcher-a. Built-in: pełen `discard_exhausted` + 6 stubów (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik). **ADR-0047 Accepted**. 18 testów (`test_engine_weapons_inventory.py`).
- [x] **B3.9.f** — Dead code cleanup w combat.py (dead loop linia 378-380 + function-local `_MoveExecuted` import). Update `docs/architecture.md` sekcja "Game engine" z nową strukturą modułów. Refresh ADR-0011 Public API (post-B3.9). Update `scripts/engine_smoke_replay.py` z replay invariant assertion (B3.9.d). `docs/roadmap.md` aktualizacja statusów.

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
| 0006 | Pipeline docx↔yaml: drift-only | ✓ |
| 0007 | Cache rulesetów: LRU na load_ruleset | ✓ |
| 0008 | Pareto MVP: oddział = koło, pełne zasady | ✓ |
| 0010 | Event-sourced battle log | ✓ |
| 0010a | Decision freeze (GATE dla B3 actions) | ✓ |
| 0010b | Eventy + immutable state; ORM tylko persistence | ✓ (scalone w ADR-0010) |
| 0011 | Rule executor: hardcoded klasy/funkcje na MVP | ✓ |
| 0012 | Dice: własna biblioteka, deterministyczny seed | ✓ |
| 0013 | Engine headless-first | — |
| 0014 | Obrażenia per-oddział (= Stan bitewny) — 4 kategorie ran | ✓ |
| 0015 | 4 zamknięte interrupt points | ✓ |
| 0015a | Reactive window w akcji ataku (atomowe) | ✓ |
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
| 0043 | LoS 3-stanowy (sampling N=16) | ✓ |
| 0044 | Prediction module (damage PMF + visibility) | ✓ |
| 0045 | ActivationContext + initial_toughness_snapshot (B3.9.c) | ✓ |
| 0046 | Event-sourced state mutations (B3.9.d, proof ADR-0010) | ✓ |
| 0047 | UnitBlob weapons inventory + ACTIVE_ABILITY_REGISTRY (B3.9.e) | ✓ |

---

## Decyzje strategiczne

- **Backend = SSOT dla kosztów.** Frontend renderuje, nie liczy. ✅
- **Procedural engine nie jest usuwany** — feature toggle, usunięcie po ≥3 mies. prod stabilności + perf audit.
- **Hierarchia oddziałów = dziedziczenie z różnicami.** Wariant trzyma tylko delta.
- **Monolityczne pliki dzielimy stopniowo.** Komentarze sekcji w `app.js`, `_engine.py` — patrz `docs/developing.md`.
- **Reguły gry (`app/static/docs/`) = source of truth.** Niedopuszczalna dywergencja kod ↔ DOCX.
- **SSOT split (od 2026-05-30, B0):** `SZOP_Rozjemca.md` + `SZOP_Zdolnosci.md` = SSOT dla **engine** (mechaniki, drift target). `SZOP.docx`/`SZOP.pdf` = SSOT dla **rules-as-prose** (oficjalny tekst reguł). A4 drift gate weryfikuje synchronizację 4 plików źródłowych.
- **Procedural ↔ YAML parity = CI gate.** `both_assert` wykrywa każdą rozbieżność > 1e-3.
- **Game engine = czyste funkcje + event sourcing.** ORM tylko do persistence, brak logiki gry w ORM.
- **MCP agent = klient HTTP, nie direct DB.** Jeden mechanizm uprawnień, jeden audit trail.
