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

> **Event-store slice DONE 2026-06-10** (wątek `faza-b-2-event-store`, ADR-0050): `Battle` + `BattleEvent` (nowe tabele, addytywne via `create_all`) + `app/services/engine/persistence.py` (`save_events`/`load_events`) + replay-from-DB invariant (10 testów, pytest 1504). Reszta B2 (User.role/invite/snapshot/Unit-kolumny/AgentToken/AuditLog) odroczona — auth wymaga usera + `/security-review`; kolumny `Unit` wymagają ręcznego ALTER (brak Alembic). Projekt NIE używa Alembic — schema z `Base.metadata.create_all` + ręczny `_migrate_schema` (db.py).

**ORM — persistence layer (`app/models.py`):**
- [ ] `User` — rozszerz: `role` (dodaj `agent`), `owner_user_id?`, `agent_kind?`
- [x] `Battle` — `(p1_user_id?, p2_user_id?, p1_roster_id?, p2_roster_id?, winner_user_id?, current_round, rng_seed, status)` — tabela `battles` (ADR-0050)
- [ ] `BattleInvite` — `(from_user_id, to_user_id?, roster_id, scenario, status ∈ {pending/accepted/declined/expired}, expires_at)`
- [x] `BattleEvent` — append-only: `(battle_id, sequence, event_type, payload_json, timestamp)` + `UniqueConstraint(battle_id, sequence)` — tabela `battle_events` (ADR-0050)
- [ ] `BattleSnapshot` — opcjonalny: `(battle_id, sequence_at, state_json)` (MVP: nie używany)
- [ ] `Unit` — dodaj: `base_size_mm: int = 25`, `base_shape: str = "round"`
- [ ] `AgentToken` — `(agent_user_id, owner_user_id, scope_json, expires_at, revoked_at?, last_used_at)`
- [ ] `AgentAuditLog` — `(user_id?, agent_user_id?, route, params_json, timestamp)`
- [!] Migracja Alembic: `XXX_add_battle_models.py` — N/A: projekt nie używa Alembic; nowe tabele addytywne przez `create_all`.

**Runtime dataclass'y — czysty Python (`app/services/engine/state.py`):**
- [ ] `UnitBlob(frozen=True)` — `(id, owner_player, position, radius_inches, models_alive, wounds_remaining, passives, status_flags)` — semantyka wounds jak istniejący „Stan bitewny"
- [ ] `BattleState(frozen=True)` — `(round, active_player, activations_remaining, blobs, terrain, pending_effects, pending_interrupts, score)`
- [ ] `TerrainCircle(frozen=True)`, `TerrainLine(frozen=True)`

**Event definitions (`app/services/engine/events.py`):** — **DONE** (B3.0.3, 16 typów)
- [x] Frozen dataclass per event type (16: Move/Shot/Melee/ModelKilled/MoraleTest/Effect/Interrupt/RoundEnded/StatusAdded/StatusRemoved/MeleeBalanceReset/MutexCollision/ObjectiveControlChanged/InitiativePassed/AbilityOverrideApplied/AbilityOverridesCleared)
- [x] `event_to_json()` + `json_to_event()` serializer (+ `_EVENT_REGISTRY` discriminator)

**Persistence (`app/services/engine/persistence.py`):** — **DONE 2026-06-10** (ADR-0050)
- [x] `save_events(session, battle_id, events, *, flush=True)` — append do BattleEvent (transakcyjnie neutralny)
- [x] `load_events(session, battle_id, since=0)` — odczyt z db + rekonstrukcja przez `json_to_event`
- [!] `create_snapshot()` — N/A w slice (MVP nie wywołuje snapshotów; `BattleSnapshot` model odroczony)

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
- [x] `EffectContext` frozen + per-hook registries (defense/attack/weapon modifiers; morale-modifier usunięty 2026-06 — drift pkt 20.e, Nieustraszony binarny). `aggregate_*_modifier` aggregators. MVP passive: Cierpliwy/Tarcza.
- [x] `InterruptPoint` enum (1 punkt `BEFORE_ACTION` pkt 11.b.i per ADR-0015, korekta 2026-06-09 z 4 punktów), `register_interrupt_handler(point, slug)`, `get_eligible_interrupts`, `trigger_interrupt`. Strażnik (id 31) MVP stub.
- [x] 38 testów (21 effects + 17 interrupts).
- [x] ADR-0015 Accepted (korekta 2026-06-09): 1 punkt `BEFORE_ACTION` per pkt 11.b.i (≤2 okna/aktywację via pętla 11.b.iv), no nested.

**Phases (`app/services/engine/phases.py`):**
- [x] `setup_phase(rosters, terrain, objectives, initiative)` — pkt 7+9.
- [x] `deployment_round(state, actions)` — pkt 13, emit MoveExecuted move_type="deploy".
- [x] `activation_phase(state, action, dice)` — dispatch per Action type → akcja → Przegrupowanie pkt 20 (uwzględnia pkt 20.b/c/d + passive morale modifiers) → Aktywowany. **Aktywacja wieloakcyjna 2026-06-10** (ADR-0051, wątek `faza-b-multi-action`): split na `_begin_activation`/`_apply_single_action`/`_finalize_activation`; `resolver.apply_activation` realizuje pętlę do 2 akcji (pkt 11.b.iv — Manewr liczy się; Ostrzał/Szarża raz, pkt 14.c.v/14.d.vi) napędzaną `Player.continue_activation`. `apply` (1 akcja) zostaje dla B4. Postęp lokalny → replay invariant bez nowych eventów.
- [x] **Wybór konsekwencji Przegrupowania (pkt 20.f.i) 2026-06-11** (wątek `faza-b-regroup-choice`): przy 1 porażce kontrolujący wybiera Wyczerpany/Przyszpilony. Callback `regroup_choice(state, blob)` przez `_regroup_test`/`_apply_single_action`/`activation_phase`/`apply`/`apply_activation`; `match` dispatchuje do `players[blob.owner_player].choose_regroup_consequence` (default "exhausted" = wsteczna kompat). Replay-safe (`MoraleTestPassed.result_status="pinned"` + reducer już istniały). v3 ma drzewo wyboru. **Pkt 20.e Nieustraszony — DRIFT NAPRAWIONY 2026-06-11** (sesja autonomiczna): binarny skip „powyżej połowy → 0 testów" w `_regroup_test` (`effective_passives`); usunięto stary morale-modifier `-1` + obsoletny mechanizm `aggregate_morale_modifier`. Zgodne z ADR-0048. **Otwarte (BLOKADA, decyzja usera):** pkt 20.f.i — źródło czyta „1 porażka → Przyszpilony" (deterministycznie) vs zaimplementowane „kontrolujący wybiera, default Wyczerpany"; patrz HANDOFF_faza-b-engine-mvp.
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
- [x] **B3.9.c** — `ActivationContext` (`phases.py`) + `BattleState.initial_toughness_snapshot` (`state.py`) — frozen delta state per aktywacja: `wounds_received_this_activation` zamiast cumulative (fix bug #1 pkt 20.a), `melee_combatants` frozenset (fix bug #2: defender szarży regroup-testuje w aktywacji chargera + bug #5: damage_balance reset obu stron). `initial_toughness_for(state, blob_id)` helper (fix bug #3: snapshot zamiast post-action proxy). **ADR-0045 Accepted**. 17 testów (`test_engine_activation_context.py`).
- [x] **B3.9.d** — `app/services/engine/reducers.py` (NEW) z `@register_reducer` dla wszystkich 11 typów; 3 nowe eventy w `events.py`: `StatusAdded`/`StatusRemoved`/`MeleeBalanceReset`. Emit Status* w combat/phases zamiast silent `replace()` (fix bug #6). Algorytm wound allocation w reducerach mirror `combat._allocate_wounds_to_defender`. **ADR-0046 Accepted** — proof-of-completeness ADR-0010 empirycznie. 8 testów + GATE `test_gate_full_multi_action_replay` (per-blob bit-perfect) + sanity `test_all_event_types_have_reducer` (`test_engine_replay_invariant.py`).
- [x] **B3.9.e** — `UnitBlob.melee_weapons`/`ranged_weapons: tuple[WeaponProfile, ...]` + `WeaponProfile` migration z combat.py do state.py. `build_initial_state` parsuje `unit["weapons"]` z partycją po `range_inches`. Fix bug #7: `resolve_charge_attack` counter używa `defender.melee_weapons[0]` z fallback. `_ACTIVE_ABILITY_REGISTRY` w `effects.py` + `register_active_ability(slug)` decorator + `get_active_ability(slug)` lookup. `phases._apply_special` redukcja do dispatcher-a. Built-in: pełen `discard_exhausted` + 6 stubów (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik). **ADR-0047 Accepted**. 18 testów (`test_engine_weapons_inventory.py`).
- [x] **B3.9.f** — Dead code cleanup w combat.py (dead loop linia 378-380 + function-local `_MoveExecuted` import). Update `docs/architecture.md` sekcja "Game engine" z nową strukturą modułów. Refresh ADR-0011 Public API (post-B3.9). Update `scripts/engine_smoke_replay.py` z replay invariant assertion (B3.9.d). `docs/roadmap.md` aktualizacja statusów.

### Rules resync 2026-06 — **in progress** (wątek `faza-b-rules-resync`, ADR-0048)

Synchronizacja 3 warstw SSOT (YAML reguł + procedural oracle + engine) po driftcie `SZOP_Rozjemca.md`/`SZOP_Zdolnosci.md` (2026-06-03). Drift: Lokalizacja enum (pkt 26), formuła kosztu aur/rozkazów `T_eff = clamp(4/3×T, 8, 24)`, mutex statusów (pkt 22.b/c), broń Zguba = licznik `wounds_eliminating` (pkt 26.d/27.a), trigger Przegrupowania (pkt 20.a), Niebezpieczny teren per-oddział (pkt 4.c.v), 8 zdolności przepisanych. Pełny rekord: [ADR-0048](adr/0048-rules-resync-2026-06.md).

- [x] **R0–R3** — drift baseline + `tables.yaml` (locations/status_flags/aura_order_formula) + 5 abilities (opis) + `cost_functions.t_eff`/`aura_range_bonus`/`order_bonus` + handlers. Parity 156/156.
- [x] **R4.Zguba** — `UnitBlob.wounds_eliminating` + ELIMINOWANY dispatch (`ModelKilled.eliminated`, `Shot/MeleeResolved.wounds_eliminating`). `rozkaz_tak` field (88 abilities, 30 true).
- [x] **R5.a/c/d/e/f/g** — Lokalizacja enum + pokonanie→WYCOFANY (rany+morale), kontratak conditional Wyczerpany (pkt 14.d.iv), Przegrupowanie warunki (pkt 20.a/b/c via ActivationContext), `MutexCollision` event (pkt 22.b/c), Ufortyfikowany rozstawienie (pkt 13.c), Niebezpieczny teren (pkt 4.c.v). R5.b skip (H4).
- [x] **R6** — drift gate WARN + parity both_assert 156/156 + yaml 93/93 + smoke replay EXIT 0 + procedural oracle sync.
- [x] **R7** — ADR-0048 (NEW Accepted) + refresh ADR-0011 (Lokalizacja/MutexCollision w Public API) + roadmap + architecture.
- [x] **R4.Klątwa/Rozkaz/Oznaczenie** (id 45/49/50) — **MVP DONE 2026-06-09** (wątek `faza-b-order-interrupts`, ADR-0049): substrat `ability_overrides` + `effective_passives` + handlery interrupt `BEFORE_ACTION` (zasięg 12″, ally/enemy, `rozkaz_tak`, raz-na-rundę) + wygaśnięcie na końcu aktywacji. Uproszczenia: Oznaczenie precyzyjny trigger ataku + auto-orkiestracja w pętli aktywacji → H2/B4.
- [ ] **Dywersant engine policy** (id 6) — ×2 ataki vs Przyszpilony. Deferred post-MVP (`INCOMPLETE_ABILITIES` stub). Cost-side done.
- [ ] **H7 (open)** — heal-revive limit dla ELIMINOWANY/Zguby; czeka na fazę Leczenia (pkt 21), nie blokuje B2/B4.

> **B2 ORM schema impact:** `BattleEvent.payload_json` per unit +`location: Lokalizacja` +`wounds_eliminating: int`; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`; nowy event `MutexCollision`. Zamrożone — zero migration churn.

### B4. API (3 tyg)
- [ ] `app/routers/battles.py` — endpointy: `POST /battles/invite`, `POST /battles/invite/{id}/accept`, `POST /battles`, `GET /battles/{id}`, `GET /battles/{id}/events`, `POST /battles/{id}/actions`, `POST /battles/{id}/interrupts`, `POST /battles/{id}/simulate`, `POST /battles/{id}/replay`
- [ ] Auth: tylko gracze bitwy (nie trzecia osoba); agent wymaga scope
- [ ] Pydantic schemas w `app/schemas.py` — BattleState, BattleEvent, Action (polimorficzne)
- [ ] Optimistic locking na `BattleEvent.sequence` — zapobiega race condition

### B5. Klient gry `szop_client` (równolegle z B4, 2 tyg) — **LocalClient slice DONE 2026-06-14** (wątek `faza-b-5-client`, ADR-0016)

> Slice engine-dict: `GameClient` Protocol + `LocalClient` in-process. 13 testów (`tests/test_clients_local.py`): determinizm batcha, parity z runnerem (`simulate_from_rosters`) i z D2 (`simulate_balance`), wierność single-step (`take_action == apply_activation`), walidacja błędów. **Odblokowuje C3 `simulate_engagement`.** `HttpClient` + DB-backed loading + pakowanie odłożone (patrz niżej).

- [x] `szop_client/protocol.py` — `class GameClient(Protocol)` z metodami: `create_battle`, `get_state`, `take_action`, `get_events`, `simulate` (+ `SimulationSummary`). `subscribe_events` realizowany jako pull `get_events(battle_id, since)`; SSE → B6.
- [ ] `szop_client/http.py` — `HttpClient(base_url, token)` — odłożone do B4 (API musi istnieć). Protocol strukturalny → dołączy bez dziedziczenia.
- [x] `szop_client/local.py` — `LocalClient` in-process (ścieżka **engine-dict**: rostery jako dict 1:1 z `build_initial_state`). DB-backed `LocalClient(db_session, user_id)` odłożony do `faza-d-roster-adapter` (most ORM→engine-dict).
- [ ] `szop_client/setup.py` — `pip install -e` odłożone (sens dopiero z `HttpClient`; `LocalClient` z natury in-process z `app`).
- [ ] `tests/test_clients_parity.py` — `HttpClient.simulate == LocalClient.simulate` odłożone do B4.
- [x] ADR-0016: szop_client jako wydzielony moduł (Accepted)

### B6. Prezentacja (opcjonalne, 3–4 tyg) — **CLI replay slice DONE 2026-06-15** (wątek `faza-b-6-replay`, ADR-0013)
- [x] `scripts/battle_replay.py` — CLI terminal output: narracja PL per event (16 typów), grupowanie w rundy (delimiter `RoundEnded`), podsumowanie (wynik celów pkt 5.f + rozkład typów + zwycięzca). Rdzeń = czyste funkcje (`format_event`/`render_battle_log`, bez I/O). Dwa źródła: `--fixture`/`--map` (reuse `balance_simulate` SSOT + `simulate_from_rosters`, ADR-0032) oraz `--from-db <id>` (`persistence.load_events`, ADR-0050, read-only). Render z samego event-logu (bez rekonstrukcji stanu — jednolite dla obu trybów). 16 testów. Skrypt-liść (zero zmian w rdzeniu). **Odłożone:** bogatszy widok stanu (po N-tym evencie via `apply_events`) — narracja per-event wystarcza MVP.
- [ ] SSE stream `GET /battles/{id}/events` — wymaga B4 API
- [ ] `app/static/js/modules/battle_canvas.js` — minimalny 2D canvas (Konva.js lub goły Canvas)
- [x] ADR-0013: Engine headless-first, UI opcjonalne (Accepted)

### B7. Test bed (2 tyg) — **DONE 2026-06-13** (wątek `faza-b-7-test-bed`)
- [x] `tests/fixtures/battles/*.yaml` — golden scenariusze (reuse 3 fixtur wiernych regułom z D2: `demo_skirmish`/`objective_clash`/`unit_profiles`; predefiniowany seed + matchup botów = przepis na deterministyczny przebieg).
- [x] `tests/test_engine_regression.py` — 6 golden battles deterministycznych (winner/rounds/score/event-count + sha256 digest event-logu) + 6 reproducible + 2 sanity = 14 testów. **Zmiana golden = świadoma zmiana rulesetu/silnika/heurystyki → ADR.** Regen przez `python tests/test_engine_regression.py` (blok `__main__`). Reuse `balance_simulate` (SSOT ładowania fixtur + budowy graczy) — zero zmian w rdzeniu. Pokrycie wyników 0/1/None; pętla 100% deterministyczna (ADR-0010/0012).

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

### D1. Heuristic players (4 tyg) — **MVP DONE 2026-06-09** (wątek `faza-d-heuristic-players`, ADR-0031)
- [x] `app/services/agents/base.py` — `class Player(ABC)`: `choose_action(state, perspective) → Action | None` + współdzielony enumerator `legal_actions` (silnik celowo jednoakcyjny — kandydaci budowani z `actions.Action`) + selektory.
- [x] `random_player.py` — `RandomPlayer(seed)` losowy uniform z `legal_actions`, deterministyczny per seed.
- [x] `priority_v3_player.py` — **`PriorityV3Player` 2026-06-11** (spec usera): bot z drzewem decyzyjnym akcji (29 węzłów, gałąź Wojownik/Strzelec) + selekcja 5-kryterialna (1. ma cel o najwyższej wadze ataku) + ważony wybór celu (`-1 Aktywowany; -0.25/debuff; +x(4-x)`, x=obrażenia/HP). `--players priority3`. 9 testów + audyt legalności. **Wynik:** najsilniejszy na zróżnicowanych armiach (unit_profiles: bije prosty 30:15, v2 38:25, greedy 55%), ale na jednorodnych prosty wygrywa (demo 52:37). **Uwaga:** `x(4-x)` symetryczne wokół x=2 — karze overkill, NIE premiuje monotonicznie dobijania. **Odłożone:** drzewo konsekwencji Przegrupowania (pkt 20.f.i = stały Wyczerpany; wymaga zmiany reguł+silnika). **Fix 2026-06-12** (wątek `faza-d-melee-target-cover`): scoring celu Szarży przekazuje pusty `terrain` do `expected_damage` — osłona (pkt 19) dotyczy tylko Ostrzału, silnik melee jej nie liczy; dotyczy `_a_charge` + `_best_achievable_target_weight`.
- [x] `priority_v2_player.py` — **`PriorityV2Player` 2026-06-10** (spec usera): rozbudowany wariant `PriorityPlayer`. Selekcja aktywacji 4-kryterialna (zdrowy → najbliżej nieaktywowanego/zdrowego/dowolnego wroga); akcja 1–8 (+ ruch przechwytujący broniący własnych celów); wybór celu ataku przez `prediction` (zdrowy → nieaktywowany → `p_full_kill` → `mean` → najbliżej). `--players priority2`. 12 testów. **Wynik (porównanie):** bije random (67–70%) i greedy (78–98%), ale **przegrywa głową w głowę z prostym `PriorityPlayer`** (demo 1:47, clash 10:42) — „preferuj zdrowy cel" rozprasza ogień zamiast dobijać; prosty (strzel najbliższego) koncentruje. Wniosek: złożoność ≠ siła; prosty pozostaje baseline. **Fix 2026-06-12** (wątek `faza-d-melee-target-cover`): `_best_target` dla Szarży (krok 3) scoruje cele z pustym `terrain` — osłona (pkt 19) nie dotyczy melee (finding F6 REVIEW_2026-06-11).
- [x] `priority_player.py` — **`PriorityPlayer` 2026-06-10** (spec usera, rev. 2): bot pół-deterministyczny. Selekcja: **oddział najbliżej wroga** (remis→id). Priorytet 1–7: zdejmij Wyczerpany → Ostrzał najbliższego → Szarża → zdejmij Przyszpilony → ruch do niezajętego celu **dla którego jest najbliższym własnym oddziałem** (anty-klastrowanie) → ruch do dowolnego niezajętego celu → ruch do najbliższego wroga. Kontrola celów z pozycji przez `_check_objective_control` (SSOT pkt 5.d); `continue_activation` przechodzi pełny priorytet (pomija zużyty Ostrzał/Szarżę). 14 testów. **Wynik balansu (realna geometria 72×48, strefy 24″ apart):** najsilniejszy bot — priority/random 73%, priority/greedy 80–95% na obu fixturach. (Wcześniejszy „przegrywa na rozległych" był artefaktem nierealnej geometrii 36″ — przy poprawnym 24″ priority dominuje; overextension nie występuje.)
- [x] `greedy_player.py` — `GreedyPlayer` depth-1 argmax: `expected_damage(...).mean × WOUND_VALUE` (HP, ADR-0044) **+ Δ kontroli celów** (`objective_balance_with_control`, pkt 5.d/5.f) dla ataku i manewru. **Kontrola celów 2026-06-10** (wątek `faza-d-greedy-objectives`): atak/manewr punktowane na wspólnej walucie wartości celów (przeliczenie kontroli z pozycji), nie tylko obrażeniach — bot zajmuje/broni celów osiągalnych w horyzoncie. **Ograniczenie depth-1:** cele >1 ruch poza horyzontem (D4 minimax to adresuje). **Fix 2026-06-12** (wątek `faza-d-greedy-melee-cover`): `_attack_score` scoruje Szarżę z pustym `terrain` — osłona (pkt 19) dotyczy tylko Ostrzału, silnik melee jej nie liczy (domyka rodzinę fixu v2/v3/greedy).
- [x] `policy_eval.py` — `evaluate_state` (bilans HP + kontrola/bliskość celów pkt 5) + `objective_balance_with_control` (przelicza kontrolę pkt 5.d przez `phases._check_objective_control`, SSOT).
- [x] ADR-0031 (Accepted) + 26 testów (`tests/test_agents_{base,random,policy,greedy}.py`). **Odłożone (H2):** pętla bitwy / driver przebiegu gry (B4/B5 LocalClient) — boty produkują akcje, ale D2 `balance_simulate` wymaga orkiestratora `apply`+`round_end_phase`+alternacja.

### D2. Balance simulation (2 tyg)
> **Prereq DONE 2026-06-10** (wątek `faza-d-match-runner`, ADR-0032): headless pętla bitwy `app/services/agents/match.py` — `run_match(state, players, dice)` + `simulate_from_rosters(rosters, players, *, seed, ...)` → `MatchResult(final_state, events, winner, rounds_played)`. Jedno wywołanie = jedna pełna gra (pkt 8 pętla rund, pkt 5.f winner). D2 agreguje N gier. 6 testów.
- [x] `scripts/balance_simulate.py` — **MVP DONE 2026-06-10** (wątek `faza-d-2-balance-sim`): agreguje N gier (`simulate_from_rosters`) → win-rate per rozpiska (owner_player 0/1) + draw-rate + śr. rund, CSV (`--out`) + podsumowanie. Inicjatywa naprzemienna (`i % 2`) usuwa bias 1. gracza; gracze konfigurowalni (`--players random,greedy`); fixtura roster-pair YAML (`tests/fixtures/battles/*.yaml`). 15 testów. **Fixtury wierne regułom + realnej geometrii** (2026-06-10): 5 celów (pkt 5.a/b/c) + 4 proste oddziały/stronę (pkt 2.a) na **72″×48″, strefy rozstawienia 12″ głębokie, 24″ od siebie (pkt 3.a/b)**, oddziały przyklejone do granicy (y=12/y=36 → armie 24″ od siebie, w zasięgu karabinu od r.1). `demo_skirmish` (front rozłożony) + `objective_clash` (centralny napór) + **`unit_profiles`** (4 zróżnicowane profile uzbrojenia: Strzelec-24/18, Wojownik-mix 12″+2×0″, Wojownik 3×0″; jednolite staty). Kontrola celów trwała między rundami (pkt 5.d — opuszczony cel zostaje, odbija tylko przeciwnik w 3″; potwierdzone testami `test_objective_persists_when_vacated`/`_recaptured_only_by_opponent`). **Wniosek kontekstowy:** `PriorityV2Player` przegrywa z prostym na jednorodnych armiach (1:47), ale **wygrywa na zróżnicowanych** (`unit_profiles` priority2/priority 33:25) — wartość wyboru celu rośnie, gdy oddziały się różnią. **Odłożone:** breakdown per zdolność/broń (wymaga adaptera ORM `Roster`→engine-dict + heurystyki auto-rozstawienia pozycji). **Mapy generowane 2026-06-12** (wątek `faza-d-test-maps`): `--map {standard_a, lustrzana_a, symetryczna_a}` — Standard_A deterministyczna (środkowo-sym., teren z reflekcji danych usera); Lustrzana_A (losowa, lustro y=24) + Symetryczna_A (losowa, środkowo-sym., strefy pod losowym kątem), rejection-sampling pkt 5.b/5.c (cele ≥12″/≥6″) + 18 linii Niedostępny+Blokujący (≥6″/≥3″) + koła 8 Obronny/4 Trudny/2 Niebezpieczny (⌀3–6, overlap-OK). 4 profile/stronę symetrycznie. 7 testów. Ruch nie egzekwuje Trudny/Niedostępny (LoS/osłona/Niebezpieczny tak).
- [x] `scripts/balance_report.py` → `reports/balance/YYYY-MM-DD.md` — **DONE 2026-06-10** (wątek `faza-d-balance-report`): round-robin turniej (fixtura × para botów, kombinacje z powtórzeniem) reużywa `simulate_balance` (SSOT, ADR-0032) → markdown z tabelą win-rate + tekstowymi (unicode) wykresami słupkowymi. CLI `--fixtures/--players/-n/--seed/--out`. Wykresy **tekstowe, nie obrazowe** (bez matplotlib — dependency-free; obrazy = follow-up gdy user zechce zależności). `reports/` gitignored. 19 testów.

### D3. Exploit hunting (2 tyg)
- [ ] `scripts/exploit_hunt.py` — generuje losowe rozpiski na koncie `agent_kind=exploit_hunter`, gra vs siebie, raportuje top 10 (win_rate/points)
- [ ] Każdy exploit → ADR z propozycją zmiany DOCX

### D4. Adversarial play (4 tyg, opcjonalne)
- [ ] Frontend UI "Play vs AI" — wybór agenta z listy
- [ ] `minimax_player.py` — depth-2 (dla testów, ~100 ms/action)
- [ ] Leaderboard `reports/leaderboard.md`
- [ ] ADR-0030: Wielu agentów konkurujących — osobne konta + leaderboard

### D5. Rozstawienie jako decyzja bota (po E4 kolizjach)

> Aktualnie pozycje startowe biorą się z fikstury YAML; `deployment_round` jest wywoływane z pustą listą akcji — boty nie mają wpływu na start.

- [ ] `Player.choose_deployment(state, unit_id) → Position` — nowa metoda ABC (default: pozycja z fikstury = wsteczna kompat)
- [ ] `simulate_from_rosters` pyta graczy o pozycje przed `deployment_round`; waliduje `position` w strefie rozstawienia gracza (pkt 13.a) przez `IllegalActionError`
- [ ] Proste strategie deploymentu (nie wymagają E4): grid równomierny w strefie, kopia fikstury ze skalowaniem
- [ ] Strategie zaawansowane (wymagają E4 kolizji): rozstaw bez nachodzenia; coverage-based (maksymalizuj liczbę pokrytych celów z pozycji startowej)
- [ ] Testy: pozycja poza strefą rozstawienia odrzucona; gracze mogą dostać różne pozycje na tej samej planszy

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

### E4. Ruch — kolizje i pathfinding (po E2, tydzień 28+)

> MVP: ruch deklarowany, brak kolizji jednostka–jednostka (B0 decyzja #5). Oddziały mogą na siebie wchodzić. Poniższe implementują pełny model ruchu po stabilizacji silnika.

**Kolizje jednostka–jednostka:**
- [ ] Walidacja w `phases._apply_maneuver` — `circle_edge_distance(moved, other) >= 0` dla każdego innego blobu na planszy; rzuć `IllegalActionError` jeśli nachodzenie
- [ ] `base.legal_actions` / `legal_followup_actions` — filtruj `ManeuverAction` których `target_position` prowadzi do kolizji (boty nie próbują niedozwolonych ruchów)
- [ ] Testy regresyjne: overlap po manewrze niedozwolony; Szarża dalej ustawia `min_gap`

**Pathfinding:**
- [ ] `app/services/engine/pathfinding.py` — `find_reachable_positions(state, blob, move_inches) → list[Position]` (siatka hex lub ciągła)
- [ ] Obsługa terenu `Trudny` (½ ruchu, pkt 4.c.iv) — ważona siatka
- [ ] Obsługa terenu `Niedostępny` (pkt 4.c.i) — blokada węzłów
- [ ] Boty (Greedy/Priority/V2/V3) zastępują heurestyczne `_move_toward` wywołaniem `find_reachable_positions`
- [ ] ADR: model pathfindingu (grid rozdzielczość vs graph nawigacji)

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
| 0013 | Engine headless-first, prezentacja opcjonalna (B6 CLI replay slice) | ✓ |
| 0014 | Obrażenia per-oddział (= Stan bitewny) — 4 kategorie ran | ✓ |
| 0015 | Interrupt point `BEFORE_ACTION` (pkt 11.b.i; korekta 2026-06-09 z 4 punktów) | ✓ |
| 0015a | Reactive window w akcji ataku (atomowe) | ✓ |
| 0016 | szop_client jako wydzielony moduł (Protocol + LocalClient slice) | ✓ |
| 0017 | Telemetria od dnia 1 | — |
| 0020 | MCP runtime: Python SDK | — |
| 0021 | MCP jako klient publicznego API | — |
| 0022 | Vector store: sqlite-vec | — |
| 0023 | Embeddings: sentence-transformers offline | — |
| 0024 | Consent-gated agent writes | — |
| 0025 | Rola agent + scoped tokens | — |
| 0030 | Wielu agentów: osobne konta + leaderboard | — |
| 0031 | Gracze heurystyczni D1: enumerator akcji + Random/Greedy | ✓ |
| 0032 | Headless match runner (orkiestrator pełnej gry dla botów) | ✓ |
| 0040 | Migration blob → per-model | — |
| 0041 | Terrain shapes beyond circle/line | — |
| 0042 | Facing: wprowadzane z Zwrot | — |
| 0043 | LoS 3-stanowy (sampling N=16) | ✓ |
| 0044 | Prediction module (damage PMF + visibility) | ✓ |
| 0045 | ActivationContext + initial_toughness_snapshot (B3.9.c) | ✓ |
| 0046 | Event-sourced state mutations (B3.9.d, proof ADR-0010) | ✓ |
| 0047 | UnitBlob weapons inventory + ACTIVE_ABILITY_REGISTRY (B3.9.e) | ✓ |
| 0048 | Rules resync 2026-06: Lokalizacja enum + T_eff + status mutex + Zguba eliminating | ✓ |
| 0049 | Czasowy ability-override + przerwania Rozkaz/Klątwa/Oznaczenie (BEFORE_ACTION) | ✓ |
| 0050 | Persystencja event-store: Battle + BattleEvent + persistence.py (B2 slice) | ✓ |
| 0051 | Aktywacja wieloakcyjna (pkt 11.b.iv): orkiestrator `apply_activation` + `continue_activation` | ✓ |

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
