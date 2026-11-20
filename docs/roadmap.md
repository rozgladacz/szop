# Roadmap

> Kierunki długofalowe i kolejka etapów poniżej. Historyczne decyzje są w `docs/handoffs/` i `HANDOFF.md`.
>
> Pełny plan architektoniczny 12–24 mies.: [docs/plans/architektura-dlugofala.md](plans/architektura-dlugofala.md)
>
> Etykieta `[automation-ready]` jawnie dopuszcza otwarty etap do automatycznego
> uruchomienia przez koordynatora. Brak etykiety oznacza wymagany wybór ręczny.

---

## Aktywna kolejka — akceptacje 2026-11-19

Użytkownik zaakceptował Ostrożnego (wyłącznie dystansowo), audyty Bastionu,
Planowania i Niestrudzonego, obie części D5.3, przygotowanie publikacji
Oznaczenia, audyt botów, podłączenie istniejących agentów i podział Play vs AI.
[Zakresy, DoD, warstwy, weryfikacja i backup](kolejka-po-c2d3.md).
Jeden worker naraz; obowiązuje poniższa kolejność, każdy punkt zależy od
zamknięcia poprzedniego. Wcześniejsze odłożenie D5.3 jest uchylone.

- [x] **B4.4d.C2d3** — **DONE 2026-11-19**: prywatny Ostrożny w pasującym closed Shoot v3 i jawny prediction opt-in; tylko dystansowo, bez publikacji. Core **347 passed**, Strażnik/scoring **92 passed**, pełne **3987 passed**. [Wynik, pomiary i backup](kolejka-po-c2d3.md#1-b44dc2d3--implementacja-ostrożnego).
- [x] **B4.4d.C2d4-spec** — **DONE 2026-11-19 (audyt)**: [Bastion](bastion-spec.md) dotyczy kontratakującego; wykluczony z publikacji obecnego main-attacker-only Oznaczenia. Źródła **4/4 CLEAN**, bez zmian kodu/tagów; brak nowej decyzji użytkownika.
- [x] **B4.4d.C2d5-spec** — **DONE 2026-11-19 (audyt)**: [Planowanie](planowanie-spec.md), status Przygotowany i lifecycle, propozycja prywatnego hooka v3 oraz istniejący drift mutex Mobilizacji. Źródła **4/4 CLEAN**, bez zmiany kodu; brak nowych pytań.
- [x] **B4.4d.C2d6-spec** — **DONE 2026-11-20 (audyt)**: [Niestrudzony](niestrudzony-spec.md) wykluczony z obecnego attack-only Oznaczenia; istniejąca luka native/Rozkazu w legalności powtórzeń i drift katalogu YAML. Źródła **4/4 CLEAN**, bez zmiany kodu/tagów; brak nowych pytań.
- [x] **D5.3a** — **DONE 2026-11-20**: jawne strategie rozstawienia per strona (`None`/grid/cele), wspólna pula i walidacja D5.1/D5.2, deterministyczne przydziały. Celowane **219 passed**, pełne **4008 passed**. [Kontrakt, pomiary i backup](kolejka-po-c2d3.md); domyślne rozstawienie bez zmian.
- [x] **D5.3b** — **DONE 2026-11-20**: [eksperyment grid/cele](experiments/d5_3b/README.md), 480 przypadków/960 wykonań, pełny replay i determinizm; 240 mieszanych: cele 174/grid 30/remis 36. Efekt strony i koszt opisane, grid nadal domyślny. Celowane **214 passed**, pełne **4025 passed**.
- [ ] **B4.4d.C2-publication-spec** [automation-ready] — przygotowanie ograniczonej publikacji Oznaczenia, katalog i security gates; bez samej publikacji.
- [ ] **D6.1-audit** [automation-ready] — audyt istniejących botów i gotowości do publicznego lifecycle.
- [ ] **D6.2-connect** [automation-ready] — podłączenie istniejących agentów przez klienta i propozycje akcji z zachowaniem zatwierdzania.
- [ ] **D6.3-play-plan** [automation-ready] — podział Play vs AI na małe etapy na podstawie wyników audytu/integracji.

## Kolejka po C2d1 — akceptacje 2026-11-18

Jeden przebieg wykonuje jeden etap. [Zakresy, zależności, testy i warunki
przekazania na kolejny komputer](kolejka-po-c2d1.md) są punktem startowym.
Użytkownik zaakceptował punkty 1, 2, 3 i 5 oraz poprawkę kontroli celu do 2″.
Kolejność realizacji to B3.objectives-2in → C2d2 → D5.1 → D5.2 → C2d3-spec.
W tej historycznej kolejce D5.3a/b były odłożone; akceptacja z 2026-11-19
powyżej przywraca je do realizacji. Cykl ma działać w istniejącym czacie.

- [x] **B3.objectives-2in** — **DONE 2026-11-18**: kontrola celu ≤2″ od obwodu oddziału, regresje silnika/botów i replay; celowane **226 passed**, pełne **3828 passed**. Uzasadnienie goldenów w [ADR-0058](adr/0058-objective-control-two-inches.md), wynik w [kolejce](kolejka-po-c2d1.md#0-b3objectives-2in--kontrola-celu-w-zasięgu-2).
- [x] **B4.4d.C2d2** — **DONE 2026-11-18**: oba aliasy Podwójnego w głównym ataku i kontrataku zamkniętej Szarży v3, niezależnie od Furii/Kontry; celowane **370 passed**, pełne **3848 passed**. Wynik, replay/RNG, ograniczenia i obserwacja testowa w [kolejce](kolejka-po-c2d1.md#1-b44dc2d2--nazwa-podwójnego-w-prywatnym-melee-v3).
- [x] **D5.1** — **DONE 2026-11-18**: czysty walidator miejsca rozstawienia i wspólna statyczna geometria E4; jawne zajęte pozycje, strefa i Niedostępny wszystkich kształtów. Celowane **227 passed**, pełne **3906 passed**. Wynik i granica integracji D5.2 w [kolejce](kolejka-po-c2d1.md#2-d51--wspólna-walidacja-miejsca-rozstawienia).
- [x] **D5.2** — **DONE 2026-11-18**: Grid/Random i runner używają walidatora D5.1, sekwencyjnego roboczego stanu i jawnych zajętych pozycji; ograniczony fallback i błędy bez częściowego zapisu. Celowane **195 passed**, pełne **3926 passed**. Kontrakt, pomiary, replay i backup w [kolejce](kolejka-po-c2d1.md#3-d52--boty-wybierają-wolne-miejsca).
- Dalsze D5.3a/b są osobnymi zaakceptowanymi etapami w aktywnej kolejce powyżej.
- [x] **B4.4d.C2d3-spec** — **DONE 2026-11-18 (audyt)**: [specyfikacja Ostrożnego](ostrozny-spec.md), mapa combat/prediction, granice i DoD. Źródła 4/4 CLEAN; decyzja użytkownika 2026-11-19: tylko ataki dystansowe; implementacja zaakceptowana 2026-11-19 jako C2d3 w aktywnej kolejce. Sam audyt nie zmieniał kodu.

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
- [x] `make generate-schema` → `docs/schemas/ruleset_v1.schema.json` — **DONE 2026-07-18 (A1.1):** deterministyczny draft 2020-12 dla trzech fizycznych dokumentów v1 + read-only `make schema-check`.
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

> **Event-store slice DONE 2026-06-10** (wątek `faza-b-2-event-store`, ADR-0050): `Battle` + `BattleEvent` (nowe tabele, addytywne via `create_all`) + `app/services/engine/persistence.py` (`save_events`/`load_events`) + replay-from-DB invariant (10 testów, pytest 1504). **Trwały checkpoint DONE 2026-07-15 (ADR-0053):** wersjonowany, bezpieczny codec pełnego `BattleState` + JSON-safe stan `DeterministicDice`, tabela `BattleCheckpoint` i helpery spójne z końcem event-store. **BattleInvite schema DONE 2026-07-19 (ADR-0055):** addytywna tabela, czterostanowy lifecycle i trwały result linkage dla przyszłej idempotentnej akceptacji. **Unit base geometry slice DONE 2026-06-26:** `Unit.base_size_mm` + `Unit.base_shape` z ręcznym `_migrate_schema` (brak Alembic). **Auth/agent schema slice DONE 2026-06-26:** `User.role`, `AgentToken`, `AgentAuditLog`; **runtime helper tokenów DONE 2026-06-27:** `security.require_agent_scope(scope_name)` weryfikuje bearer token hash + scope i zapisuje `AgentAuditLog`. **Endpointy tokenów DONE 2026-06-28:** `POST/GET/DELETE /agent_tokens` tworzą/listują/cofają własne tokeny ownera; raw bearer token wraca tylko przy tworzeniu. Projekt NIE używa Alembic — schema z `Base.metadata.create_all` + ręczny `_migrate_schema` (db.py).

**ORM — persistence layer (`app/models.py`):**
- [x] `User` — `role ∈ {user, agent, admin}` (DONE 2026-06-26; addytywne ORM + `_migrate_schema`; `is_admin` zostaje źródłem uprawnień UI w tym slice)
- [x] `Battle` — `(p1_user_id?, p2_user_id?, p1_roster_id?, p2_roster_id?, winner_user_id?, current_round, rng_seed, status)` — tabela `battles` (ADR-0050)
- [x] `BattleInvite` — `(from_user_id, to_user_id?, roster_id, scenario, status ∈ {pending/accepted/declined/expired}, expires_at)` + nullable result linkage `(accepted_by_user_id, accepted_roster_id, battle_id UNIQUE)` — DONE 2026-07-19 (ADR-0055)
- [x] `BattleEvent` — append-only: `(battle_id, sequence, event_type, payload_json, timestamp)` + `UniqueConstraint(battle_id, sequence)` — tabela `battle_events` (ADR-0050)
- [x] `BattleCheckpoint` — `(battle_id, sequence_at, state_json, rng_json, timestamp)`; tylko checkpoint dokładnie na końcu event-logu jest bieżący (ADR-0053)
- [x] `Unit` — `base_size_mm: int = 25`, `base_shape: str = "round"` (DONE 2026-06-26; addytywne ORM + `_migrate_schema`)
- [x] `AgentToken` — `(agent_user_id, owner_user_id, token_hash, scope_json, expires_at, revoked_at?, last_used_at)` (DONE 2026-06-26; `token_hash` zamiast raw tokena)
- [x] `AgentAuditLog` — `(user_id?, agent_user_id?, route, params_json, timestamp)` (DONE 2026-06-26)
- [!] Migracja Alembic: `XXX_add_battle_models.py` — N/A: projekt nie używa Alembic; nowe tabele addytywne przez `create_all`.

**Runtime dataclass'y — czysty Python (`app/services/engine/state.py`):** — **DONE w B3** (zaimplementowane jako prereq rule executora; `frozen=True, slots=True`)
- [x] `UnitBlob(frozen=True)` — `app/services/engine/state.py:127`; semantyka wounds jak istniejący „Stan bitewny" (rozszerzony w B3.9/rules-resync o `melee_weapons`/`ranged_weapons`, `wounds_eliminating`, `location: Lokalizacja`)
- [x] `BattleState(frozen=True)` — `app/services/engine/state.py:199` (z `initial_toughness_snapshot` B3.9.c + `effective_move_inches` helper)
- [x] `TerrainCircle(frozen=True)`, `TerrainLine(frozen=True)` — `app/services/engine/state.py:67`/`:76` (+ `Position`, `Objective`, `WeaponProfile` w tym samym module)

**Event definitions (`app/services/engine/events.py`):** — **DONE** (B3.0.3, 16 typów)
- [x] Frozen dataclass per event type (16: Move/Shot/Melee/ModelKilled/MoraleTest/Effect/Interrupt/RoundEnded/StatusAdded/StatusRemoved/MeleeBalanceReset/MutexCollision/ObjectiveControlChanged/InitiativePassed/AbilityOverrideApplied/AbilityOverridesCleared)
- [x] `event_to_json()` + `json_to_event()` serializer (+ `_EVENT_REGISTRY` discriminator)

**Persistence (`app/services/engine/persistence.py`):** — **DONE 2026-06-10** (ADR-0050)
- [x] `save_events(session, battle_id, events, *, flush=True, expected_latest_sequence=None)` — append do BattleEvent (transakcyjnie neutralny) + optional optimistic precondition dla B4 write endpointów
- [x] `load_events(session, battle_id, since=0)` — odczyt z db + rekonstrukcja przez `json_to_event`
- [x] `save_checkpoint()` / `load_latest_checkpoint()` — transakcyjnie neutralne, wersjonowany pełny state+RNG, brak stale fallback (ADR-0053)

- [x] ADR-0010: Event-sourced battle log ✓
- [x] ADR-0010b: Eventy + immutable state; ORM tylko persistence ✓ (scalone z 0010)
- [x] ADR-0014: Obrażenia per-oddział (zgodne z „Stan bitewny") ✓

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
- [~] `app/routers/battles.py` — **read-only slices DONE 2026-07-02/03,
  sandbox create DONE 2026-07-04, sandbox simulate DONE 2026-07-10**:
  `GET /battles/{id}` zwraca metadane bitwy z `battles` + `latest_sequence`
  z event-store, `GET /battles/{id}/events?since=N` zwraca zapisany event-log,
  a `GET /battles/{id}/state` zwraca wersjonowany checkpoint `BattleState`
  z `sequence_at` bez wewnętrznego RNG. `POST /battles` tworzy
  owner-scoped sandboxową bitwę z dwóch własnych rozpisek, adaptuje je przez
  `roster_to_engine_roster`, wykonuje setup/deployment i zapisuje startowy
  event-log przez `persistence.save_events(..., expected_latest_sequence=0)`
  oraz checkpoint stanu+RNG w tej samej transakcji.
  Create response zwraca addytywny `adaptation_report` p1/p2 z raportu adaptera
  (`dropped_excluded`, `inert_incomplete`, `deferred_attached_heroes`), żeby
  sandbox nie ukrywał pominiętych zdolności/jednostek; GET metadata nie
  rekonstruuje raportu. `POST /battles/simulate` uruchamia read-only batch dwóch
  własnych rozpisek (`battle:simulate`, limit 50 gier, tylko boty `fast` z
  rejestru), używa app-level map `app.services.agents.maps` + `make_player`
  i zwraca agregat wyników bez zapisu `Battle`/eventów. Invite'y i gra między
  różnymi ownerami nadal osobno.
  `POST /battles/{id}/actions` **DONE 2026-07-15 (ADR-0054)**: pojedyncza
  wersjonowana akcja, obowiązkowy `expected_sequence`, wznowienie state+RNG,
  `resolver.apply`, automatyczny round-end przez istniejące helpery i atomowy
  zapis eventów + dokładnie jednego checkpointu + metadanych; odpowiedź zwraca
  nowy state i deltę eventów. `POST /battles/invite` **DONE 2026-07-19
  (B4.1, ADR-0055)**: session user albo agent scope `battle:invite` tworzy direct
  lub open `BattleInvite(status=pending)` dla własnego rosteru. Strict body
  przyjmuje `to_user_id?`, `roster_id`, canonical lowercase `scenario` oraz
  `expires_in_hours` 1..168; odpowiedź zawiera wyłącznie immutable input,
  status i timestampy, bez result linkage. Każdy legalny POST tworzy nowy
  rekord — świadomie brak idempotency/deduplikacji bez constraintu i
  rate-limit infrastruktury. `POST /battles/invite/{id}/accept` **DONE
  2026-07-19 (B4.2, ADR-0055)**: strict body zawiera tylko roster acceptora,
  direct/open stosują wspólne no-oracle, a bearer ma osobny scope
  `battle:accept`. Pierwszy sukces losuje server-side seed, buduje scenario,
  adaptuje oba rostery i przez wspólne `stage_battle_creation` zapisuje jedną
  aktywną `Battle`, startowy event-log i checkpoint. Pełne invite linkage jest
  ustawiane warunkowym CAS po PK/status/expiry/target w tej samej transakcji;
  przegrany CAS rollbackuje cały provisional graph. Retry tego samego
  acceptora/rostera zwraca istniejący `battle_id`, expiry jest trwale
  commitowane przed stałym 409. **B4.4a design DONE 2026-07-19 (ADR-0056):**
  zamrożono trwały, event-sourced protocol v2: wybór oddziału przed pierwszym
  oknem, priorytet interruptów od inicjatywy, jawny pass/handoff, akcja dopiero
  po zamknięciu `BEFORE_ACTION`, opcjonalne drugie okno oraz jawne
  recovery/finalizacja ([`SZOP_Rozjemca.md` pkt 10, 11.b.i–vi i
  12.a–c](../app/static/docs/SZOP_Rozjemca.md)). Legacy checkpoint v1 nie
  dostaje wymyślonej inicjatywy; Strażnik stub i activation-scoped Oznaczenie
  nie są publicznie gotowe ([`SZOP_Zdolnosci.md` pozycje 31 i
  49](../app/static/docs/SZOP_Zdolnosci.md)). **B4.4b.1 state+codec DONE
  2026-07-21:** `BattleState` ma nullable, niewymyślane
  `initiative_player`/`activation`, frozen model aktywacji i okna odrzuca
  nieosiągalne snapshoty, a ścisły codec zachowuje dokładny i domyślny v1 oraz
  dodaje wyłącznie jawny v2 bez `pending_interrupts`. Persistence, routery i
  klienci nadal zapisują/publikują v1. **B4.4b.2 eventy+reducery DONE
  2026-07-27:** 10 nowych payloadów v1 ma kompatybilny codec i komplet
  reducerów, a ręczne ogony eventów odtwarzają wszystkie checkpointy
  aktywacji/okien v2 bez duplikowania outcome events. **B4.4b.3 pure
  control-plane transitions DONE 2026-07-27:** `start_activation`, jawny
  `pass_interrupt_priority` i `continue_activation` emitują istniejące eventy,
  a live state pochodzi wyłącznie z reducerów; testy dowodzą fail-closed v1,
  atomowości, replay equality i restart parity checkpointu v2. **B4.4b.4
  accepted-interrupt core DONE 2026-07-27:** `trigger_activation_interrupt`
  waliduje jawne guardy, priority i source przez `effective_passives`, składa
  dokładnie jeden `ActivationInterruptTriggered` z ograniczonym batchem
  istniejących outcome events oraz fail-closed sprawdza ciągłą sekwencję,
  dokładnie jeden kanoniczny `InterruptTriggered`, no-nested, event version i
  live/replay parity. Priorytet i wcześniejsze passy pozostają bez zmian,
  wersje/licznik rosną raz, a limit 64 accepted interruptów działa przed
  executorem. **B4.4b.5 action bridge DONE 2026-07-27:**
  `commit_activation_action` wykonuje dokładnie jeden istniejący leaf
  `_apply_single_action`, waliduje outcome/live-replay/sequence/no-nested,
  dopisuje na końcu `ActivationActionCommitted` i zwraca osobny checkpointowalny
  RNG. Trwałe `activation.action_types` jest SSOT limitu dwóch akcji oraz
  ograniczeń powtórnego Ostrzału/Szarży
  ([pkt 11.b.iv, 14.c.v i 14.d.vi](../app/static/docs/SZOP_Rozjemca.md)); most
  nie finalizuje aktywacji ani nie zmienia gracza. **B4.4b.6 finalization core
  DONE 2026-07-28:** `finalize_activation` obsługuje wyłącznie jawnie puste
  recovery po jednej albo dwóch akcjach, reużywa `_finalize_activation` dla
  statusu Aktywowany, safety resetu i wygaśnięcia override'ów, a następnie
  emituje `ActivationFinalized`, `InitiativeTransferred` i
  `ActivePlayerChanged`. Batch jest ciągły, fail-closed i replayowalny;
  inicjatywa przechodzi ze snapshotu aktywacji, a protokół wraca do `IDLE`.
  **B4.4b.7 source-correct Rozkaz adapter DONE 2026-07-28:** osobna immutable
  `READY_INTERRUPT_HANDLERS` dopuszcza tylko `rozkaz`, a pure built-in executor
  buduje `InterruptContext` z trwałego okna i deleguje do outcome SSOT.
  Rozkaz ma exact payload bez klientowego `sequence`, żywy/frontowy source i
  target, ally/range/round-limit oraz kierunek `granted` wynikający z
  kanonicznego `rozkaz_kierunek`; outcome zachowuje replay/restart parity i
  wygasa przez finalizację
  ([pozycja 50 i konwencje tagów](../app/static/docs/SZOP_Zdolnosci.md),
  [pkt 11.b.i i 12.a–c](../app/static/docs/SZOP_Rozjemca.md)).
  **B4.4c.1 activation protocol persistence DONE 2026-07-28:** `Battle` ma
  trwałe, ograniczone do `1|2` `activation_protocol_version`; świeży schema i
  idempotentna migracja SQLite oznaczają historię dokładnie v1 bez przepisywania
  checkpointów. `save_checkpoint` oraz wspólne `stage_battle_creation`
  zachowują domyślne v1, a wewnętrzny jawny opt-in v2 zapisuje spójny checkpoint
  `szop.battle_state/v2` z trwałą inicjatywą i bez rozpoczętej aktywacji.
  Publiczne create/invite/action schemas, payloady i domyślne call sites nie
  zostały zmienione.
  **B4.4c.2 durable activation start service DONE 2026-07-28:**
  `app/services/battle_activations.py` dodaje transakcyjnie neutralny start
  aktywacji wyłącznie dla trwałych bitew v2. Participant/no-oracle lookup,
  mapowanie ownera na aktywną stronę (także same-owner sandbox), ścisły
  `expected_sequence`, spójny checkpoint state+RNG i pure `start_activation`
  poprzedzają jeden guarded batch eventów oraz dokładnie jeden checkpoint v2.
  Caller nadal zarządza commit/rollback; restart odtwarza identyczny
  `BEFORE_ACTION`, a RNG pozostaje bez zmian. Operacja ma stałe 5 SELECT-ów bez
  N+1; v1, stale/race, niespójny checkpoint, cudzy caller i nielegalny wybór
  failują bez częściowych zapisów. Routery, publiczne schema/scope'y, klient i
  pozostałe przejścia protokołu nie zostały dodane.
  **B4.4c.3 durable explicit priority pass service DONE 2026-07-28:**
  ten sam wąski serwis persistence dodaje jeden transakcyjnie neutralny pass
  bieżącego `priority_player`. Z trwałego headu v2 sprawdza
  participant/no-oracle, status, strict sequence oraz activation/window guardy,
  mapuje ownera z trwałego priorytetu i deleguje całe handoff/close do pure
  `pass_interrupt_priority` ([pkt 10 i 12.a–c](../app/static/docs/SZOP_Rozjemca.md)).
  Każde jawne wywołanie stage'uje dokładny ciągły event delta oraz jeden
  checkpoint v2 z bitowo niezmienionym RNG; pierwszy pass przetrwa restart z
  przekazanym priorytetem, a drugi osobny pass właściwego ownera zamyka okno.
  Same-owner nadal wymaga dwóch wywołań, two-owner egzekwuje bieżącego ownera,
  a v1/checkpoint/stale/guard/phase/race/rollback failują bez częściowego zapisu.
  Sukces pozostaje na 5 SELECT-ach bez N+1. Router, publiczne schema/scope'y,
  accepted interrupt, akcja, continue/finalize, recovery i klient nie weszły
  w ten slice.
  **B4.4c.4 durable activation action service DONE 2026-07-28:**
  `stage_battle_activation_action` z jednego participant-scoped trwałego headu
  v2 stage'uje dokładnie jedną legalną akcję oddziału w `ACTION_READY`. Wire
  payload jest ściśle dekodowany i kanonizowany przez istniejący action codec,
  caller_player pochodzi z trwałego `activation.controlling_player`, a outcome,
  reguły akcji i RNG pozostają w pure `commit_activation_action`
  ([pkt 11.b.ii–iv i 14](../app/static/docs/SZOP_Rozjemca.md)). Dokładny ciągły
  event delta oraz jeden checkpoint v2 z RNG transition są zapisywane bez
  commit/rollback w serwisie. Pierwsza i osiągalna druga akcja zachowują
  restart/replay oraz przyszłe rzuty; v1, malformed/coercive payload, auth,
  stale/checkpoint/phase, race i rollback failują bez częściowego zapisu.
  Same-owner/two-owner matrix oraz stałe 5 SELECT-ów bez N+1 są pokryte testami.
  Routery, publiczne schema/scope'y, wspólny envelope, finalize,
  recovery i klient nie weszły w ten slice.
  **B4.4c.5 durable activation continuation service DONE 2026-07-28:**
  `stage_battle_activation_continue` z jednego participant-scoped trwałego
  headu v2 stage'uje wyłącznie jawną deklarację drugiej akcji w
  `AWAITING_CONTINUATION`. Caller_player pochodzi z trwałego
  `activation.controlling_player`, a pure `continue_activation` pozostaje SSOT
  fazy, guardów, wersji, priorytetu inicjatywy oraz dokładnego delta
  `ActivationContinuationChosen(continue_activation=True)` +
  `InterruptWindowOpened(ordinal=2)` zgodnie z
  [pkt 10, 11.b.i–iv i 12.a–c](../app/static/docs/SZOP_Rozjemca.md).
  Jeden guarded event batch i jeden checkpoint v2 zachowują bitowo niezmieniony
  RNG bez commit/rollback w serwisie. Restart/replay prowadzi przez dwa
  istniejące pass service calls do `ACTION_READY`, a istniejąca action service
  zapisuje drugą akcję do `AWAITING_FINALIZATION`. Strict input, v1,
  status/phase/action-count, auth/no-oracle, stale/coherence, race/rollback,
  same-owner/two-owner oraz stałe 5 SELECT-ów bez N+1 są pokryte testami.
  Finalizacja, transport, publiczne schema/scope'y, envelope i klient nie weszły
  w ten slice.
  **B4.4c.6 durable activation finalization service DONE 2026-07-28:**
  `stage_battle_activation_finalize` z jednego participant-scoped trwałego
  headu v2 stage'uje legalny terminalny delta po jednej albo dwóch akcjach.
  Strict `recovery_uses` akceptuje wyłącznie dokładnie `()`, caller_player
  pochodzi z trwałego `activation.controlling_player`, a pure
  `finalize_activation` pozostaje SSOT fazy/action_count, jawnego
  `continue=False` po jednej akcji, legacy outcome, statusu Aktywowany,
  czyszczenia override'ów oraz transferu inicjatywy i active playera zgodnie z
  [pkt 10, 11.b.iv–vi, 21 i 22.d](../app/static/docs/SZOP_Rozjemca.md).
  Jeden guarded event batch i jeden checkpoint v2 zachowują bitowo niezmieniony
  RNG bez commit/rollback w serwisie. Oba warianty mają restart/replay parity,
  a po commicie finalizacji istniejący start service może rozpocząć następną
  legalną aktywację. Strict input, v1, status/phase/action-count,
  auth/no-oracle, stale/coherence, race/rollback, same-owner/two-owner oraz
  stałe 5 SELECT-ów bez N+1 są pokryte testami. Nie dodano produkcyjnego call
  site, transportu, publicznych schema/scope'ów, envelope ani klienta.
  **B4.4c.7 durable activation interrupt service DONE 2026-07-28:**
  `stage_battle_activation_interrupt` z participant-scoped trwałego headu v2
  przyjmuje dokładnie jeden public-ready Rozkaz bieżącego `priority_player`.
  Source-independent preflight reużywa allowlistę i strict payload SSOT przed
  pierwszym I/O, a pure `trigger_activation_interrupt` wraz z
  `execute_ready_activation_interrupt_outcomes` pozostają jedynymi właścicielami
  semantyki source/target/range/kierunku/raz-na-rundę zgodnie z
  [pozycją 50](../app/static/docs/SZOP_Zdolnosci.md) oraz
  [pkt 11.b.i i 12.a–c](../app/static/docs/SZOP_Rozjemca.md).
  Dokładny delta `ActivationInterruptTriggered` + `InterruptTriggered` +
  outcome trafia przez jeden guarded event batch do jednego checkpointu v2 z
  bitowo niezmienionym RNG; priority i pass counters nie dryfują. Restart/replay,
  dalsze pass/action/finalize i czyszczenie override'u są pokryte wraz z v1,
  no-oracle, strict/stale/coherence/race/rollback, same-owner/two-owner oraz
  odrzuceniem Klątwy/Oznaczenia/Strażnika bez zapisu. Sukces pozostaje na stałych
  5 SELECT-ach bez N+1. Nie dodano produkcyjnego call site, transportu,
  publicznych schema/scope'ów, envelope ani klienta.
  **B4.4c.8 public activation protocol opt-in DONE 2026-07-29:** publiczne
  direct create i create invite przyjmują opcjonalne, strict
  `activation_protocol_version: 1|2` z dokładnym defaultem v1. Obie ścieżki
  reużywają `stage_battle_creation`; v2 zapisuje zgodne metadata, trwałą
  inicjatywę i checkpoint v2 w `IDLE`. `BattleInvite` utrwala niezmienny wybór
  z idempotentną migracją SQLite do v1, a accept używa wyłącznie tej wartości;
  CAS oraz idempotentny reread odrzucają mismatch invite↔battle. Publiczne
  `BattlePublic`/`BattleInvitePublic` i ścisłe `BattleMetadata`/
  `BattleInviteMetadata` ujawniają wersję. `HttpClient` zachowuje dotychczasowe
  body dla defaultu v1, emituje pole dla jawnego v2 i odrzuca brakujące,
  nieznane lub błędnie typowane metadata. Auth/scope'y są bez zmian, a opt-in
  ma zerową deltę liczby SQL statements dla direct create, invite create i
  accept.
  **B4.4c.9 public durable activation transport DONE 2026-07-29:** trzy nowe
  participant-scoped trasy FastAPI wystawiają start, interrupt/pass oraz
  continue/finalize, a istniejące `POST /actions` addytywnie obsługuje strict
  guardy v2 przy niezmienionym body/statusie/semantyce v1. Router reużywa
  wyłącznie `stage_battle_activation_*`, wspólny zamknięty envelope state v2 +
  exact event delta oraz stabilne kody błędów bez oracle. `battle:act` chroni
  start/action/continue/finalize, a nowy `battle:interrupt` — interrupt/pass;
  sesje i bearer ownera zachowują body-blind audit. Publiczny allowlist nadal
  dopuszcza tylko source-correct Rozkaz
  ([`SZOP_Zdolnosci.md` pozycja 50](../app/static/docs/SZOP_Zdolnosci.md),
  [`SZOP_Rozjemca.md` pkt 12.a–c](../app/static/docs/SZOP_Rozjemca.md)),
  recovery wyłącznie dokładnie puste `uses`. Realny transport
  same-owner/two-owner przechodzi od `IDLE` do
  następnego `IDLE`, w tym dwa jawne passy każdego okna, opcjonalną drugą akcję,
  restart, stale/race/rollback i replay/RNG parity. Pełny request ma stały
  ceiling 6 SELECT-ów dla sesji i 7 dla bearera; v1 action pozostaje przy
  6 SELECT-ach i historycznym 200.
  **B4.4d.C0 source-correct publiczna Klątwa(X) DONE 2026-07-29:** addytywny
  immutable `RulesetAbility.klatwa_tak` i schema rulesetu zamrażają pięć
  source-correct X: `delikatny`, `instynkt`, `nieruchomy`, `niezgrabny`,
  `wolny` ([`SZOP_Zdolnosci.md` pozycje 4, 9, 15, 18 i 33](../app/static/docs/SZOP_Zdolnosci.md)).
  Osobny strict validator nie reużywa tagów ani kierunku Rozkazu; payload ma
  dokładnie `{target_id, ability, granted}`, oba boole są legalne, a brak
  jawnego `klatwa_tak: true`, nie-pasywka i nieznany slug failują zamknięcie.
  Istniejący activation protocol v2 egzekwuje żywy/frontowy source z Klątwą,
  wrogi żywy/frontowy cel w edge-to-edge 12″, limit `(source_id, "klatwa")`
  raz/rundę i wygaśnięcie override'u przy finalizacji zgodnie z
  [pozycją 45](../app/static/docs/SZOP_Zdolnosci.md) oraz
  [`SZOP_Rozjemca.md` pkt 11.b.i/iv i 12.a–c](../app/static/docs/SZOP_Rozjemca.md).
  Publiczny allowlist wynosi teraz dokładnie `{"rozkaz", "klatwa"}`;
  Oznaczenie i Strażnik pozostają niedostępne. Walidacja używa załadowanego
  state i cache'owanego rulesetu bez N+1; zmierzony sukces ma taki sam koszt
  jak Rozkaz: 5 SELECT-ów w serwisie, 6 w pełnym request session i 7 dla
  bearera. `HttpClient.interrupt(..., ability_slug="klatwa", ...)` reużywa
  istniejące API i wykonuje dokładnie jeden POST bez GET/retry/cache.
  **B4.4d.C1a RNG-aware accepted-interrupt substrate DONE 2026-07-29:**
  `trigger_activation_interrupt` klonuje RNG z wejściowego checkpointu przed
  outcome i zwraca typowany state/events/next-sequence wraz z prywatnym,
  ewentualnie zaawansowanym RNG. Błąd executora, malformed wynik,
  live/replay mismatch albo protocol event po częściowym zużyciu RNG failują
  bez zmiany wejściowego state/RNG. Durable interrupt zapisuje zwrócony RNG w
  tym samym pojedynczym checkpointcie co jeden guarded event batch; rollback,
  write race i optimistic race zachowują poprzedni trwały RNG. Rozkaz i Klątwa
  nadal nie konsumują RNG, zachowują dokładne eventy i future-roll parity, a
  publiczny transport nadal nie ujawnia RNG. Bez dodatkowych SQL i bez zmiany
  allowlisty: pozostaje dokładnie `{"rozkaz", "klatwa"}`.
  To wyłącznie fundament C1. Strażnik nadal jest stubem i pozostaje publicznie
  niedostępny; rzeczywisty Ostrzał, późniejszy Wyczerpany oraz walidacja
  source/broni/celu z [pozycji 31](../app/static/docs/SZOP_Zdolnosci.md)
  pozostają otwartym dalszym zakresem C1.
  **B4.4d.C1b private pure Strażnik foundation DONE 2026-07-29:**
  activation-v2 ma prywatny frozen plan i strict decoder przypisań
  `{weapon_slug,target_id}` bez statystyk broni od callera. Profile są
  rozwiązywane wyłącznie z `source.ranged_weapons`; coercion, extra fields,
  duplikaty, niejednoznaczne inventory i mechaniki bez reprezentowalnego stanu
  failują zamknięcie. Pure outcome egzekwuje wrogą trwającą aktywację,
  żywy Front, brak Wyczerpanego i blokady 2″, 1–2 wrogie cele, zasięg oraz LoS
  z jawnymi wyjątkami broni. Combat SSOT rozpatruje wszystkie testy profili
  przed per-target alokacją pul, emituje dokładnie jeden
  `InterruptTriggered(straznik)`, komplet `ShotResolved`/`ModelKilled`, a na
  końcu `StatusAdded(Wyczerpany)` zgodnie z
  [`SZOP_Rozjemca.md` pkt 14.c, 17 i 22.a](../app/static/docs/SZOP_Rozjemca.md)
  oraz [pozycją 31](../app/static/docs/SZOP_Zdolnosci.md). Prywatny RNG C1a
  przesuwa się tylko o wykonane rzuty; replay/restart/future-roll parity i
  rollback po częściowym zużyciu są pokryte. Sam slice C1b nie tworzył
  produkcyjnego call site'u ani nie zmieniał allowlisty; publiczne podpięcie
  zamyka C1c poniżej.
  **B4.4d.C1c durable/public source-correct Strażnik DONE 2026-07-29:**
  `READY_INTERRUPT_HANDLERS` wynosi dokładnie
  `{"rozkaz", "klatwa", "straznik"}`. Handler-specific preflight odrzuca przed
  DB I/O wszystko poza exact payloadem
  `{"assignments":[{"weapon_slug": <non-empty str>, "target_id": <strict int >= 0>}, ...]}`
  z limitami C1b; caller nie podaje statystyk broni, sequence ani source/player
  w payloadzie. Publiczny executor omija legacy stub i deleguje Strażnika
  bezpośrednio do prywatnego activation-v2 outcome C1b z klonem RNG C1a.
  Istniejący `stage_battle_activation_interrupt` zapisuje w jednym guarded
  batchu ciągły delta od `ActivationInterruptTriggered` przez dokładnie jeden
  `InterruptTriggered(straznik)`, pełny Ostrzał/alokację i końcowy
  `StatusAdded(Wyczerpany)`, a zwrócony RNG trafia atomowo do tego samego
  pojedynczego checkpointu. Ta sama trasa `POST /battles/{id}/interrupts`,
  scope `battle:interrupt`, status 200, zamknięty state-v2/exact-event envelope,
  no-oracle i body-blind audit pozostają bez zmian. Same-owner, dwaj ownerzy z
  dwoma bearerami, replay/restart/finalize, strict payload, auth, stale/duplicate/
  race i rollback są pokryte; `HttpClient.interrupt` używa istniejącej metody i
  wykonuje dokładnie jeden POST. Pełne listy SELECT są takie same jak dla
  Rozkazu/Klątwy: 5 w serwisie, 6 w request session i 7 dla bearera, bez N+1.
  **C1/Strażnik jest public-ready DONE.**
  **B4.4d.C2a0 attack-declaration/attack-scope design DONE 2026-07-30:**
  [ADR-0056 sekcja 5](adr/0056-interrupt-activation-protocol.md) zamroziła
  jawny protocol/checkpoint v3. **C2a1 model + codec DONE 2026-07-30:** dodaje
  wyłącznie immutable pending-attack model i prywatny exact checkpoint codec
  v3. **C2a2 eventy + reducery + pure lifecycle DONE 2026-08-07:** dodaje siedem
  strict attack-protocol eventów, kompletne reducery i prywatne pure
  declare/pass/close/resolve dla `ShootAction|ChargeAction`. V3 zachowuje
  maneuver/defend/special jak v2, a deklaracja utrwala minimalny frozen intent
  `{attacker,target,weapon_slug[,counter_attack_declared]}` i otwiera osobny
  no-nested attack window. Statystyki broni zawsze pochodzą z kanonicznego
  inventory, declaration/pass/close nie wykonują rzutów, resolve używa
  prywatnego klonu RNG, a każdy restart head zachowuje complete-tail replay
  equality. V1/v2 pozostają niezmienione, a persistence/publiczny wire nadal
  akceptują v3 po jawnym opt-in C2c; v1/v2 zachowują zgodność.

  Priority/passy reużywają dwugraczową kolejkę od snapshotu inicjatywy.
  Oznaczenie może nadać tylko X z `oznaczenie_tak: true` innemu żywemu/frontowemu
  sojuszniczemu atakującemu; edge-to-edge 12″ mierzy się do utrwalonego celu
  ataku, a strict payload nie może podmienić attacker/target ani podać statystyk
  ([`SZOP_Zdolnosci.md` konwencje tagów i pozycja 49](../app/static/docs/SZOP_Zdolnosci.md)).
  Attack-only override żyje w `AttackState`, combat widzi go tylko dla
  zadeklarowanego attacker ID, a `AttackResolved` usuwa wyłącznie ten scope po
  wszystkich outcome eventach; nie używa ani nie czyści
  `UnitBlob.ability_overrides`, więc Rozkaz/Klątwa pozostają do końca aktywacji.
  Event ordering deklaracji/interruptu/passów/close/resolve, optimistic guardy,
  same-owner/two-owner, complete-tail replay, prywatny RNG resolve, atomowy
  rollback/race/no-oracle/auth i pułapy 5/6/7 SELECT są normatywne w ADR.

  Nie dochodzi nowa trasa ani scope: v3 używa istniejących
  `POST /actions` do declaration i `operation=resolve_attack` oraz
  `POST /interrupts` ze strict `scope=attack`; klient rozpozna pending scope ze
  state v3 i dostanie tylko jedną nową metodę resolve. Intent nie istnieje w
  trwałym/publicznym stanie przed legalną deklaracją. Publiczny allowlist po
  C2a0 nadal wynosi dokładnie `{"rozkaz", "klatwa", "straznik"}`;
  `oznaczenie` nadal jest odrzucane bez zapisu.

  Status slice'ów C2 (każdy ma osobny commit/DoD):

  - [x] **B4.4d.C2a2** — siedem eventów, reducery i pure
    declare/pass/close/resolve z restart/RNG parity; DONE 2026-08-07.
  - [x] **B4.4d.C2b** — immutable `oznaczenie_tak`, strict private handler i
    attack effect view bez I/O/allowlisty; DONE 2026-10-18.
  - [x] **B4.4d.C2c** — durable service, opt-in/DB constraint v3, FastAPI,
    strict attack scope i `HttpClient.resolve_activation_attack` z
    same-owner/two-bearer, auth/audit, stale/race/rollback/no-oracle i exact
    5/6/7 SELECT gates; DONE 2026-10-19. Publiczne Oznaczenie pozostaje
    fail-closed (`unsupported_interrupt`) do osobnego etapu mechanik X.
  - [x] **B4.4d.C2d1** — prywatna Furia w Szarży v3; DONE 2026-11-17.
    Publiczna allowlista Oznaczenia pozostaje pusta. Pełny lokalny `pytest -q`:
    3777 zaliczonych testów. [Zakres, weryfikacja i dalsze decyzje](oznaczenie-mechaniki-plan.md#wynik-c2d1-2026-11-17).
  **C2/Oznaczenie implementacja pozostaje OPEN; niepuste recovery,
  LocalClient/Protocol, MCP i UI pozostają osobnymi slice'ami.**
  `POST /battles/{id}/replay` **DONE
  2026-07-19 (B4.3)**: participant lub agent z `battle:read` wykonuje read-only,
  bounded rekonstrukcję `BattleState` z najwcześniejszego trwałego checkpointu
  i ciągłego ogona event-logu przez SSOT `apply_events`, po czym wynik jest
  dokładnie porównywany ze stanem checkpointu na bieżącym końcu logu. Limit
  10 000 eventów jest egzekwowany jednym odczytem `LIMIT 10_001` (413 po
  przekroczeniu); brak checkpointu, luka, kontrolowany błąd codec/reducera lub
  mismatch daje stałe 409. Serwis ma stałe 4 SELECT-y (earliest checkpoint,
  max sequence, current checkpoint, bounded event batch), bez N+1 i zapisów
  domenowych; odpowiedź zwraca wersjonowany wire state oraz metadane
  weryfikacji, ale nie RNG — endpoint nie rekonstruuje ani nie weryfikuje RNG.
- [~] Auth: read-only battle endpoints mają participant scope
  (`p1_user_id`/`p2_user_id`; cudza/nieistniejąca = 404) oraz agent bearer scope
  `battle:read` z audytem `AgentAuditLog`. `POST /battles` ma osobny agent scope
  `battle:create`, mapuje agenta na `owner_user_id` i wymaga obu rosterów z
  `owner_id == owner`. `POST /battles/simulate` ma osobny scope
  `battle:simulate`, mapuje agenta na `owner_user_id` i wymaga obu rosterów z
  `owner_id == owner`. `POST /battles/{id}/actions` ma scope `battle:act`,
  participant/no-oracle check oraz kontrolę strony `owner_player`; auth i zapis
  przeszły osobny security-review. Create invite ma osobny least-privilege
  scope `battle:invite`, owner-scoped roster, wspólne no-oracle 404 dla
  missing/foreign roster oraz missing/self/agent target i body-blind standardowy
  audit. Accept ma osobny least-privilege `battle:accept`, mapowanie bearer →
  owner, no-oracle dla invite/target/author/agent/roster/open-loser oraz ten sam
  body-blind audit; B4.2 przeszło osobny security-review. Pozostałe write
  endpointy nadal wymagają osobnego security-review.
- [~] Pydantic schemas w `app/schemas.py` — lokalne response modele metadanych,
  event-logu, state, action oraz strict create/accept invite w routerze gotowe. Bezpieczny wspólny codec
  `app/services/engine/action_codec.py` (`szop.action/v1`, zamknięty union 5
  akcji) DONE 2026-07-15; przeniesienie modeli do wspólnego `schemas.py` nie jest
  potrzebne dla obecnego klienta.
- [x] Optimistic locking na `BattleEvent.sequence` — helper persistence +
  `expected_sequence` w `POST /actions`; precondition i DB race mapowane na 409,
  cała transakcja rollbackowana (ADR-0054)

### B5. Klient gry `szop_client` (równolegle z B4, 2 tyg) — **DONE 2026-07-29: LocalClient + DB-backed + pełny HttpClient + lokalna instalacja editable (B5.5)** (wątki `faza-b-5-client`/`faza-b-5-db-client`, ADR-0016/0056)

> Slice engine-dict: `GameClient` Protocol + `LocalClient` in-process. 13 testów (`tests/test_clients_local.py`): determinizm batcha, parity z runnerem (`simulate_from_rosters`) i z D2 (`simulate_balance`), wierność single-step (`take_action == apply_activation`), walidacja błędów. **Odblokowuje C3 `simulate_engagement`.** **DB-backed slice 2026-06-19** (wątek `faza-b-5-db-client`): `LocalClient(session, user_id)` + `simulate_roster_ids`/`create_battle_from_roster_ids` wczytują `Roster` po id (read-only) i adaptują przez `roster_to_engine_roster` (most ORM→engine, `faza-d-roster-adapter`); `simulate` zyskał passthrough `deployment_zones` (D5). Scoping własności (`owner_id==user_id`, `RosterNotFoundError` wspólny dla braku/cudzego → brak oracle). +7 testów (seeded in-memory SQLite). **HttpClient slices 2026-07-02/10/15:** metadata/events/state/create/simulate oraz `take_action` (ADR-0054). Klient akcji pobiera świeży checkpoint sequence, POST-uje wspólny wire `Action`, dekoduje state + deltę bez GET po sukcesie i odrzuca continuation przed transportem. **Parity gate B5.1 2026-07-18:** realny FastAPI auth/router/serialization oraz decoder `HttpClient` dają dokładnie te same wyniki co DB-backed `LocalClient` dla publicznych simulate i create/read/single-action flow. **B5.2 2026-07-19:** publiczne `create_battle_invite` i `accept_battle_invite` obsługują istniejące B4.1/B4.2 jednym POST-em, typują pending create jako `BattleInviteMetadata`, a accept reużywa `BattleMetadata`; realny gate obejmuje direct/open i idempotentny retry bez drugiego grafu bitwy. **B5.3 2026-07-19:** publiczne `replay_battle` wykonuje jeden bezbody POST do B4.3 i fail-closed dekoduje wersjonowany stan oraz metadane weryfikacji do frozen `BattleReplayResult`; realny gate obejmuje trwały ogon eventów, zero-tail i brak zapisów domenowych. **B5.4 2026-07-29:** `HttpClient` publikuje pełny jawny flow mutacji activation v2 (`start_activation`, `interrupt`, `pass_interrupt_priority`, `commit_activation_action`, `continue_activation`, `finalize_activation`) z frozen `ActivationMutationResult`, strict guardami i dokładnie jednym POST-em per krok; realny gate obejmuje same-owner, dwa niezależne bearery, handoff, race, restart, dwie akcje i puste recovery.

- [x] `szop_client/protocol.py` — `class GameClient(Protocol)` z metodami: `create_battle`, `get_state`, `take_action`, `get_events`, `simulate` (`SimulationSummary` wydzielony do lekkiego `types.py` i re-eksportowany; `simulate` ma `deployment_zones` D5). `szop_client.__init__` ładuje eksporty leniwie, żeby klient HTTP/MCP nie importował ścieżki LocalClient/ORM. `subscribe_events` realizowany jako pull `get_events(battle_id, since)`; SSE → B6.
- [x] `szop_client/http.py` — metadata/events/state/create/simulate oraz
  `take_action` DONE 2026-07-15: świeży GET sequence → optimistic POST jednej
  akcji, wspólny codec, domenowy `(BattleState, tuple[BattleEvent, ...])`, brak
  cache i brak GET po sukcesie; `continuation != None` jawnie niedostępne.
  `create_battle_invite`/`accept_battle_invite` **DONE 2026-07-19 (B5.2)**:
  dokładnie jeden POST, ścisłe wejście i fail-closed decode, bez follow-up GET,
  retry klienta ani cache. `replay_battle` **DONE 2026-07-19 (B5.3)**:
  dokładnie jeden POST bez body, typowany zweryfikowany `BattleState`, ścisłe
  metadane i brak kontraktu RNG/sekretów. Activation protocol v2
  **DONE 2026-07-29 (B5.4)**: jawne strict guardy, osobna metoda
  `commit_activation_action`, wspólny exact-delta decoder state v2, typowany
  zamknięty błąd z HTTP status + `detail.code` i zero ukrytych GET/retry/cache.
  Historyczne `take_action` zachowuje wire v1 i dla v2 kieruje do nowych metod.
  Ostatnia jawna luka pełnego klienta, lokalne pakowanie editable, została
  domknięta w B5.5.
- [x] `szop_client/local.py` — `LocalClient` in-process. Ścieżka **engine-dict** (rostery dict 1:1 z `build_initial_state`) + **ścieżka DB** (`LocalClient(session, user_id)` + `*_roster_ids`, most ORM→engine przez `roster_adapter`, read-only, ownership-scoped). DONE 2026-06-19.
- [x] `szop_client/pyproject.toml` — PEP 517/660, dystrybucja
  `szop-client==0.1.0` dla Pythona 3.13; `python -m pip install -e
  .\szop_client` mapuje ten sam checkout monorepo, dzięki czemu `app` pozostaje
  SSOT codeców i in-process `LocalClient`. To kontrakt lokalnego editable
  install, nie publikowalny wheel/sdist ani bundling serwera. Offline smoke z
  CWD poza repo: `tests/test_szop_client_packaging.py`. DONE 2026-07-29 (B5.5).
- [x] `tests/test_clients_parity.py` — realny transport FastAPI potwierdza dokładne parity `HttpClient` ↔ `LocalClient` dla macierzy simulate oraz create/read/single-action, w tym sequence/event/state, powtarzalność, read-only simulate i no-oracle. DONE 2026-07-18.
- [x] ADR-0016: szop_client jako wydzielony moduł (Accepted)

### B6. Prezentacja (opcjonalne, 3–4 tyg) — **CLI replay slice DONE 2026-06-15** (wątek `faza-b-6-replay`, ADR-0013)
- [x] `scripts/battle_replay.py` — CLI terminal output: narracja PL per event (16 typów), grupowanie w rundy (delimiter `RoundEnded`), podsumowanie (wynik celów pkt 5.f + rozkład typów + zwycięzca). Rdzeń = czyste funkcje (`format_event`/`render_battle_log`, bez I/O). Dwa źródła: `--fixture`/`--map` (reuse `balance_simulate` SSOT + `simulate_from_rosters`, ADR-0032) oraz `--from-db <id>` (`persistence.load_events`, ADR-0050, read-only). Render z samego event-logu (bez rekonstrukcji stanu — jednolite dla obu trybów). 16 testów. Skrypt-liść (zero zmian w rdzeniu). **Odłożone:** bogatszy widok stanu (po N-tym evencie via `apply_events`) — narracja per-event wystarcza MVP.
- [x] SSE stream `GET /battles/{id}/events` — **DONE 2026-07-19 (B6.1)**:
  ta sama participant-scoped trasa negocjuje `text/event-stream` przez `Accept`,
  zachowując bez zmian JSON polling. Wznawianie używa `since`/`Last-Event-ID`,
  backlog jest czytany bounded batchami, idle emituje keep-alive, `finished`
  kończy stream, a krótkie sesje per poll respektują production i testowy
  `get_db`. Auth/no-oracle/audit obowiązują przy zestawieniu połączenia; koszt
  polla to 1 SELECT z eventami i najwyżej 2 na idle/terminal check.
- [ ] `app/static/js/modules/battle_canvas.js` — minimalny 2D canvas (Konva.js lub goły Canvas)
- [x] ADR-0013: Engine headless-first, UI opcjonalne (Accepted)

### B7. Test bed (2 tyg) — **DONE 2026-06-13** (wątek `faza-b-7-test-bed`)
- [x] `tests/fixtures/battles/*.yaml` — golden scenariusze (reuse 3 fixtur wiernych regułom z D2: `demo_skirmish`/`objective_clash`/`unit_profiles`; predefiniowany seed + matchup botów = przepis na deterministyczny przebieg).
- [x] `tests/test_engine_regression.py` — 6 golden battles deterministycznych (winner/rounds/score/event-count + sha256 digest event-logu) + 6 reproducible + 2 sanity = 14 testów. **Zmiana golden = świadoma zmiana rulesetu/silnika/heurystyki → ADR.** Regen przez `python tests/test_engine_regression.py` (blok `__main__`). Reuse `balance_simulate` (SSOT ładowania fixtur + budowy graczy) — zero zmian w rdzeniu. Pokrycie wyników 0/1/None; pętla 100% deterministyczna (ADR-0010/0012).

---

## Strumień C — Lokalny agent MCP (RAG + klient API)

> MCP server jako klient publicznego API (przez szop_client HTTP). Nie łączy się bezpośrednio z DB.

### C1. Infrastruktura (3 tyg)
- [x] `mcp_server/{server.py, config.py}` — **minimalny stdio slice DONE
  2026-07-15 + battle observation DONE 2026-07-15 + consent proposal DONE
  2026-07-18**: stabilny MCP
  Python SDK v1, konfiguracja `SZOP_API_URL` + redagowany `SZOP_API_TOKEN` oraz
  dziewięć read-only tools (`simulate_engagement`, `lookup_rule`, `search_rules`,
  `explain_ability`, `validate_loadout`, `score_list`, metadata/state/events bitwy) oraz
  `propose_battle_action`. Serwer jest wyłącznie klientem publicznego API
  przez `szop_client.HttpClient`; bez ORM/DB, bezpośredniego `take_action`,
  resources/prompts, lokalnego dostępu MCP do RAG i ogólnego executora. Publiczny
  `BattleStateCheckpoint` gwarantuje state+`sequence_at` z jednego GET; eventy
  mają stabilną, JSON-safe projekcję.
- [x] Endpointy tokenów — **DONE 2026-06-28**: `POST /agent_tokens`, `GET /agent_tokens`, `DELETE /agent_tokens/{id}`. JSON API dla zalogowanego ownera; tworzy dedykowanego `User.role="agent"` bez hasła użytkowego, zapisuje tylko `AgentToken.token_hash`, zwraca raw bearer token tylko raz, limituje ownera do 20 aktywnych tokenów, listuje/cofa wyłącznie tokeny ownera i audytuje create/revoke bez sekretów. Brak UI; konsumenci B4/MCP nadal osobny zakres.
- [x] Middleware `require_agent_scope(scope_name)` — **DONE 2026-06-27**: `app/security.py` hash bearer tokena (`sha256:`), lookup `AgentToken.token_hash`, scope JSON (`*` albo konkretny scope), odrzucenie expired/revoked/non-agent i `AgentAuditLog` z redakcją sekretów z query/path params. 8 testów. Konsumenci B4/MCP jeszcze niepodpięci.
- [x] `AgentProposal` model + backend JSON endpointy — **backend slice DONE 2026-06-29**:
  `POST /agent_proposals` (agent bearer scope `agent_proposals:create` tworzy
  propozycję `pending` owner-scoped), `GET /agent_proposals` (owner listuje
  własne propozycje, najnowsze pierwsze), `GET /agent_proposals/{id}` (owner
  czyta pojedynczą; cudza/nieistniejąca = 404), `POST /agent_proposals/{id}/approve`
  (owner zatwierdza własną propozycję idempotentnie) + `POST
  /agent_proposals/{id}/reject` (owner odrzuca własną propozycję idempotentnie).
  **Battle-action executor DONE 2026-07-16 (ADR-0024):**
  `POST /agent_proposals/battle-actions` zamraża zweryfikowane
  `battle_id`/`expected_sequence`/`szop.action/v1`, a approval ownera wykonuje
  akcję atomowo dokładnie raz. Statusy wykonawcze:
  `pending/executed/rejected/stale`; osobne `result_json`, pełny audit i
  concurrency CAS.
- [x] Frontend: approval UI — **DONE 2026-06-30**:
  `app/static/js/modules/agent_proposals.js` + panel na stronie głównej ownera
  pobiera `GET /agent_proposals`, pokazuje status/payload/result i pozwala
  wykonać `Zezwól i wykonaj`/`Odrzuć` przez endpointy approve/reject.
- [x] ADR-0021: MCP jako klient publicznego API — **Accepted 2026-07-15**: lokalna fasada deleguje wyłącznie do `HttpClient`, bez DB/ORM/własnego transportu; backend pozostaje SSOT auth/scope/audytu.
- [x] ADR-0024: Consent-gated agent writes — **Accepted 2026-07-16**:
  propozycja wymaga `battle:read` + `agent_proposals:create`, approval ownera
  wykonuje akcję dokładnie raz przez wspólną atomową ścieżkę, stale nie zmienia
  bitwy, a MCP nie publikuje `take_action`.
- [x] ADR-0025: Rola agent + scoped tokens — **DONE 2026-06-28** (`docs/adr/0025-agent-scoped-tokens.md`, Accepted): spisuje zaimplementowaną infrastrukturę (rola `agent`, `AgentToken` z `token_hash`, scope JSON `*`/konkretny, `require_agent_scope`, audyt bez sekretów, owner-only endpointy).

### C2. RAG (3 tyg)
- [x] **C2.1 deterministyczny korpus + kanoniczna ewaluacja DONE 2026-07-17:**
  `mcp_server/indexer.py` czyta wyłącznie stałą allowlistę obu kanonicznych MD,
  zachowuje granice punktów/sekcji, nagłówki i referencje, generuje stabilny
  manifest JSONL (cel 300 słów, 50 overlap; jawna tolerancja 180–450) z ID i
  SHA-256 do gitignored `build/`. `mcp_server/rag_evaluation.jsonl` zawiera
  dokładnie 30 ręcznie sprawdzonych pytań obejmujących oba źródła, a
  `mcp_server/evaluation.py` egzekwuje schemat, unikalność i pełne pokrycie
  anchorów. `make rag-corpus` + `make rag-eval-check`; offline, bez DB/ORM,
  dowolnych ścieżek, embeddingów i vector store. To corpus-coverage gate, nie
  deklaracja recall@5.
- [x] **C2.2 deterministyczny leksykalny BM25 DONE 2026-07-17:**
  `mcp_server/search.py` używa `rank-bm25` nad korpusem C2.1, indeksuje treść,
  źródło, nagłówki i referencje po deterministycznym Unicode/case/diacritics
  foldingu, waliduje publiczne `query`/`limit` i zwraca stabilne JSON-safe
  top-k. Offline CLI: `python -m mcp_server.search --query ... --limit 5`.
  `python -m mcp_server.evaluation --retrieval` oraz `make rag-bm25-eval`
  mierzą niezmienione 30 rekordów wyłącznie po `source`/`ref`/`anchor`.
  Rzeczywisty baseline: **24/30, recall@5 = 0,800**. To nie jest pełny RAG ani
  runtime tool MCP; brak DB/ORM/HTTP i arbitralnych ścieżek.
- [x] **C2.3 trwały dense store DONE 2026-07-17:** opcjonalny profil
  `requirements-rag.txt` instaluje sqlite-vec 0.1.9, sentence-transformers 5.6.0
  i PyTorch CPU. `mcp_server/embeddings.py` ma jeden model MiniLM (384D,
  przypięta rewizja, batch, L2, finite/dimension validation, leniwy import),
  jawny download do `build/models` i tryb offline po pobraniu.
  `mcp_server/vector_store.py` atomowo przebudowuje stały
  `build/rag_vectors.sqlite`, waliduje 36 chunków/wektorów oraz metadata/hash
  korpusu i udostępnia wewnętrzny JSON-safe dense top-k ze stabilnym tie-break.
  `make rag-model-download`, `make reindex-rules`, `make rag-index-check`;
  prawdziwy smoke CPU + offline reopen przeszedł. ADR-0022/0023 Accepted.
- [x] **C2.4 deterministic dense+BM25 hybrid + docelowa ewaluacja DONE
  2026-07-18 (ADR-0026):** `hybrid_search(query, limit)` stosuje weighted RRF
  nad top-5 obu istniejących gałęzi (`k=60`, BM25:dense `2:1`), deduplikuje po
  `chunk_id`, pobiera metadane z korpusu C2.1 i zwraca JSON-safe diagnostykę
  składowych. Parametry wybrano z jawnej siatki 8 wariantów bez zmian gold setu,
  korpusu, chunkingu ani modelu. Wspólny matcher zmierzył BM25 **24/30 (0,800)**,
  dense **8/30 (0,267)** i hybrid **24/30 (0,800)**; hybrid vs BM25: brak
  naprawionych i pogorszonych przypadków. `make rag-hybrid-eval` wymaga zgodnego
  indeksu i wymusza offline. Brak zmian runtime MCP/HTTP.
- [x] **C2.5 procesowy, leniwy lifecycle MiniLM DONE 2026-07-18 (ADR-0027):**
  domyślne rebuild/dense/hybrid reuse'ują jeden offline embedder na proces;
  concurrent first use tworzy model raz, a `encode` jest serializowane ze
  względu na brak gwarancji thread-safety współdzielonego SentenceTransformer.
  Download i dependency injection pozostają odseparowane, importy są lazy, a
  teksty/wektory użytkownika nie są cache'owane. Stały JSON benchmark po
  `check_index()` zmierzył warm p50 **2,610 s → 0,080 s (~32,5×)**; pełny hybrid
  nadal **24/30** z identycznymi hitami per-case. Brak zmian runtime MCP/HTTP.
- [x] **C2.6 scoped runtime hybrid search DONE 2026-07-18 (ADR-0028):**
  `POST /rules/search` z body-only query i scope `rules:search`, ścisły
  `szop.search_rules/v1`, stałe 503 bez query/ścieżek, pojedyncza delegacja do
  `hybrid_search`; `HttpClient.search_rules` ma lokalny timeout min. 30 s, a
  ósmy tool MCP deleguje tylko do klienta i nie importuje lokalnego RAG. Raw
  dense pozostaje internal. Model-free gate 264/264 oraz realny scoped
  HttpClient/MCP smoke przeszły: cold 20,239 s, warm 0,093 s, identyczne top-5
  względem direct hybrid, bez query/sekretów w audycie i bez zmian DB/build.

### C3. Narzędzia MCP (3 tyg)
- [x] `lookup_rule(query)` — **leaf-CLI DONE 2026-06-29 + public API/HttpClient/MCP DONE 2026-07-16**: wspólny parser `app.services.rule_lookup` obsługuje hierarchiczną numerację kanonicznego `SZOP_Rozjemca.md` (`N.`→`a.`→`i.`, myślniki 4. poziomu doklejane do rodzica), dokładny resolver `pkt X` oraz tekstowe wyszukiwanie z normalizacją polskich znaków. Publiczny `GET /rules/lookup`, `HttpClient.lookup_rule()` i MCP mają schemę `szop.lookup_rule/v1`, limit 1–10, query do 200 znaków, stałą etykietę źródła bez ścieżki systemowej i nie przyjmują pliku od klienta. CLI zachowuje `--list`/`--search`/`--limit`/`--json`/`--rules-file`, ale publiczna ścieżka zawsze używa SSOT. Semantyczne parafrazy obsługuje osobny `search_rules` C2.6; exact lookup pozostaje lekkie.
- [x] `explain_ability(slug)` — **leaf-CLI DONE 2026-06-24 + public API/HttpClient/MCP DONE 2026-07-16**: wspólna warstwa `app.services.ability_lookup` rozwiązuje slug/nazwę PL wyłącznie przez katalog SSOT `app.data.abilities`; publiczny `GET /abilities/explain`, `HttpClient.explain_ability()` i MCP zwracają `szop.explain_ability/v1`, nie dotykają DB i limitują query do 100 znaków. CLI zachowuje `--list`, `--type` i `--json`.
- [x] `validate_loadout(payload)` — **leaf-CLI DONE 2026-06-26 + public API/HttpClient/MCP DONE 2026-07-18 (ADR-0029)**: produkcyjny SSOT `app.services.loadout_validation` zachowuje read-only diff raw→normalized (odrzucone id / sklampowane count i `mode` / nierozpoznane passive) i deleguje koszt do `calculate_roster_unit_quote` oraz sanityzację do `normalize_roster_unit_loadout`; CLI re-eksportuje serwis i zachowuje `--list`/JSON. Agent-only `POST /units/{unit_id}/validate-loadout` wymaga `loadout:validate`, body `{loadout, count 1–100}`, zwraca ścisłe `szop.validate_loadout/v1` i nie zapisuje loadoutu. `HttpClient` używa globalnego timeoutu, dziewiąty tool MCP deleguje raz. Seeded end-to-end smoke oraz SQL gate 11 statements dla małego i 300-elementowego payloadu przeszły bez zmian katalogu/rosterów i bez body/tokena/kosztu w audycie.
- [x] `find_exploit_candidates(army_id)` — **leaf-CLI DONE 2026-06-29 + owner-scoped API/HttpClient/MCP DONE 2026-07-18 (ADR-0034)**: produkcyjny SSOT `app.services.exploit_candidates` zachowuje round-robin każdej nieuporządkowanej pary, deterministyczny pair seed, agregację obu stron i ranking `win_rate/points*100`; CLI re-eksportuje serwis i zachowuje `--list`/`--json`/`-n`/`--bot`/`--seed`/`--map`/`--top`. Agent-only `POST /armies/{army_id}/exploit-candidates` wymaga `roster:exploit-search`; armia jest owner-visible albo globalna, lecz pole zawsze obejmuje wyłącznie rostery ownera z tej armii. Workload: 2–7 rosterów, do 21 par i 50 gier, default bounded `LIMIT 8`, bez truncation. `HttpClient` wykonuje jeden POST na timeoutcie 120 s ze ścisłym decoderem, a jedenasty tool MCP deleguje raz. Seeded direct/API/client/MCP smoke i SQL gate 14 statements dla jawnego pola 2/7 rosterów oraz 1/3 gier (15 dla default) przeszły bez zapisów poza body-blind audytem. Ranking pozostaje sygnałem do ręcznej weryfikacji; interpretator/generowanie/zapis są poza zakresem.
- [x] `score_list(roster_id)` — **leaf-CLI DONE 2026-06-27 + owner-scoped API/HttpClient/MCP DONE 2026-07-18 (ADR-0033)**: produkcyjny SSOT `app.services.roster_scoring` zachowuje agregację symulacji vs pole, bezpieczną projekcję, siłę w polu i strukturalne sygnały kosztowe; CLI re-eksportuje serwis i zachowuje `--list`/`--vs`/`--army`/`-n`/`--bot`/`--seed`/`--map`. Agent-only `POST /rosters/{roster_id}/score` wymaga `roster:score`, wybiera owner-scoped pole bez oracle i zwraca `szop.score_list/v1`. Workload ma limit 10 przeciwników, 10 gier per przeciwnik i 50 łącznie bez cichego truncation; puste pole daje zerowy agregat. `HttpClient` wykonuje jeden POST na lokalnym timeoutcie 120 s, a dziesiąty tool MCP deleguje raz. Seeded direct/API/client/MCP smoke i SQL gate 13 statements dla jawnego pola 1/10 gier oraz 1/3 przeciwników (15 dla bounded pola domyślnego) przeszły bez zapisów poza audytem. Interpretacja dedykowanego agenta i `find_exploit_candidates` pozostają osobno.
- [x] `simulate_engagement(roster_a, roster_b, n)` — **leaf-CLI DONE 2026-06-24** (`scripts/simulate_engagement.py`): dwie konkretne rozpiski z DB po id, `LocalClient.simulate_roster_ids`, `--list`, koszt/skład/win-rate, testy seeded SQLite. HTTP sandbox wrapper DONE 2026-07-10 (`POST /battles/simulate` + `HttpClient.simulate_roster_ids`); **minimalny MCP wrapper DONE 2026-07-15** (`mcp_server.server`, stdio, wyłącznie publiczne API, zakres 1–50 gier).
- [x] `get_battle_metadata/state/events` — **MCP wrappers DONE 2026-07-15**: dokładnie jedno publiczne wywołanie `HttpClient` per tool; scope `battle:read` egzekwuje backend, state używa spójnego checkpointu bez RNG, events zachowują `since`/kolejność/`last_sequence`; brak bezpośredniego toola wykonującego akcję.
- [x] `propose_battle_action` — **MCP + public API DONE 2026-07-16
  (ADR-0024)**: tworzy zweryfikowaną, zamrożoną propozycję przez
  `HttpClient.propose_battle_action`; wymaga `battle:read` +
  `agent_proposals:create`, nie `battle:act`; wykonanie następuje wyłącznie po
  kliknięciu ownera.

---

## Strumień D — Agenci konkurujący (testowanie)

> Bot players do exploit-hunting i balansu. Wszystko na MVP modelu z B.

### D1. Heuristic players (4 tyg) — **MVP DONE 2026-06-09** (wątek `faza-d-heuristic-players`, ADR-0031)
- [x] `app/services/agents/base.py` — `class Player(ABC)`: `choose_action(state, perspective) → Action | None` + współdzielony enumerator `legal_actions` (silnik celowo jednoakcyjny — kandydaci budowani z `actions.Action`) + selektory.
- [x] `random_player.py` — `RandomPlayer(seed)` losowy uniform z `legal_actions`, deterministyczny per seed.
- [x] `priority_v3_player.py` — **`PriorityV3Player` 2026-06-11** (spec usera): bot z drzewem decyzyjnym akcji (29 węzłów, gałąź Wojownik/Strzelec) + selekcja 5-kryterialna (1. ma cel o najwyższej wadze ataku) + ważony wybór celu (`-1 Aktywowany; -0.25/debuff; +x(4-x)`, x=obrażenia/HP). `--players priority3`. 9 testów + audyt legalności. **Wynik:** najsilniejszy na zróżnicowanych armiach (unit_profiles: bije prosty 30:15, v2 38:25, greedy 55%), ale na jednorodnych prosty wygrywa (demo 52:37). **Uwaga:** `x(4-x)` symetryczne wokół x=2 — karze overkill, NIE premiuje monotonicznie dobijania. **Odłożone:** drzewo konsekwencji Przegrupowania (pkt 20.f.i = stały Wyczerpany; wymaga zmiany reguł+silnika). **Fix 2026-06-12** (wątek `faza-d-melee-target-cover`): scoring celu Szarży przekazuje pusty `terrain` do `expected_damage` — osłona (pkt 19) dotyczy tylko Ostrzału, silnik melee jej nie liczy; dotyczy `_a_charge` + `_best_achievable_target_weight`.
- [x] `priority_v2_player.py` — **`PriorityV2Player` 2026-06-10** (spec usera): rozbudowany wariant `PriorityPlayer`. Selekcja aktywacji 4-kryterialna (zdrowy → najbliżej nieaktywowanego/zdrowego/dowolnego wroga); akcja 1–8 (+ ruch przechwytujący broniący własnych celów); wybór celu ataku przez `prediction` (zdrowy → nieaktywowany → `p_full_kill` → `mean` → najbliżej). `--players priority2`. 12 testów. **Wynik (porównanie):** bije random (67–70%) i greedy (78–98%), ale **przegrywa głową w głowę z prostym `PriorityPlayer`** (demo 1:47, clash 10:42) — „preferuj zdrowy cel" rozprasza ogień zamiast dobijać; prosty (strzel najbliższego) koncentruje. Wniosek: złożoność ≠ siła; prosty pozostaje baseline. **Fix 2026-06-12** (wątek `faza-d-melee-target-cover`): `_best_target` dla Szarży (krok 3) scoruje cele z pustym `terrain` — osłona (pkt 19) nie dotyczy melee (finding F6 REVIEW_2026-06-11).
- [x] `priority_player.py` — **`PriorityPlayer` 2026-06-10** (spec usera, rev. 2): bot pół-deterministyczny. Selekcja: **oddział najbliżej wroga** (remis→id). Priorytet 1–7: zdejmij Wyczerpany → Ostrzał najbliższego → Szarża → zdejmij Przyszpilony → ruch do niezajętego celu **dla którego jest najbliższym własnym oddziałem** (anty-klastrowanie) → ruch do dowolnego niezajętego celu → ruch do najbliższego wroga. Kontrola celów z pozycji przez `_check_objective_control` (SSOT pkt 5.d); `continue_activation` przechodzi pełny priorytet (pomija zużyty Ostrzał/Szarżę). 14 testów. **Wynik balansu (realna geometria 72×48, strefy 24″ apart):** najsilniejszy bot — priority/random 73%, priority/greedy 80–95% na obu fixturach. (Wcześniejszy „przegrywa na rozległych" był artefaktem nierealnej geometrii 36″ — przy poprawnym 24″ priority dominuje; overextension nie występuje.)
- [x] `claude_v1_player.py` — **`ClaudeV1Player` 2026-06-17** (`--players claude`): ogólny bot depth-1 (value-maximizer, rozszerza `GreedyPlayer`). Trzy ogólne usprawnienia bez hardkodowania zdolności: (1) świadomość zdolności przez `prediction.expected_damage` (reuse `combat.py` → AP/Brutalny/Cierpliwy/… automatycznie), (2) gradient marszu `MARCH·S/(S+gap)` ku niekontrolowanym celom (anty-miopia depth-1, pkt 5.f), (3) bonus dobijania `p_full_kill·ELIM` (skupia ogień na rannych). 9 testów + audyt legalności. **Wynik (bot-vs-bot, 3 fixtury):** decydująco **bije `greedy`** (68–100%), ale **przegrywa z `priority`/`priority3`** (0–20%). Sweep wag (M/E/W/O) potwierdza: luka **strukturalna** (depth-1 value-max < heurystyka „strzel najbliższego + koncentruj"), nie parametryczna — replikuje wcześniejsze „złożoność ≠ siła" (v2/greedy < prosty). Wartość: najmocniejszy z rodziny value-max + ogólny/ability-aware baseline pod przyszłe jednostki ze zdolnościami. Pobicie priority wymagałoby depth-2 (`minimax`, poza „tym samym rzędem złożoności").
- [x] `greedy_player.py` — `GreedyPlayer` depth-1 argmax: `expected_damage(...).mean × WOUND_VALUE` (HP, ADR-0044) **+ Δ kontroli celów** (`objective_balance_with_control`, pkt 5.d/5.f) dla ataku i manewru. **Kontrola celów 2026-06-10** (wątek `faza-d-greedy-objectives`): atak/manewr punktowane na wspólnej walucie wartości celów (przeliczenie kontroli z pozycji), nie tylko obrażeniach — bot zajmuje/broni celów osiągalnych w horyzoncie. **Ograniczenie depth-1:** cele >1 ruch poza horyzontem (D4 minimax to adresuje). **Fix 2026-06-12** (wątek `faza-d-greedy-melee-cover`): `_attack_score` scoruje Szarżę z pustym `terrain` — osłona (pkt 19) dotyczy tylko Ostrzału, silnik melee jej nie liczy (domyka rodzinę fixu v2/v3/greedy).
- [x] `policy_eval.py` — `evaluate_state` (bilans HP + kontrola/bliskość celów pkt 5) + `objective_balance_with_control` (przelicza kontrolę pkt 5.d przez `phases._check_objective_control`, SSOT).
- [x] ADR-0031 (Accepted) + 26 testów (`tests/test_agents_{base,random,policy,greedy}.py`). **Odłożone (H2):** pętla bitwy / driver przebiegu gry (B4/B5 LocalClient) — boty produkują akcje, ale D2 `balance_simulate` wymaga orkiestratora `apply`+`round_end_phase`+alternacja.

### D2. Balance simulation (2 tyg)
> **Prereq DONE 2026-06-10** (wątek `faza-d-match-runner`, ADR-0032): headless pętla bitwy `app/services/agents/match.py` — `run_match(state, players, dice)` + `simulate_from_rosters(rosters, players, *, seed, ...)` → `MatchResult(final_state, events, winner, rounds_played)`. Jedno wywołanie = jedna pełna gra (pkt 8 pętla rund, pkt 5.f winner). D2 agreguje N gier. 6 testów.
- [x] `scripts/balance_simulate.py` — **MVP DONE 2026-06-10** (wątek `faza-d-2-balance-sim`): agreguje N gier (`simulate_from_rosters`) → win-rate per rozpiska (owner_player 0/1) + draw-rate + śr. rund, CSV (`--out`) + podsumowanie. Inicjatywa naprzemienna (`i % 2`) usuwa bias 1. gracza; gracze konfigurowalni (`--players random,greedy`); fixtura roster-pair YAML (`tests/fixtures/battles/*.yaml`). 15 testów. **Fixtury wierne regułom + realnej geometrii** (2026-06-10): 5 celów (pkt 5.a/b/c) + 4 proste oddziały/stronę (pkt 2.a) na **72″×48″, strefy rozstawienia 12″ głębokie, 24″ od siebie (pkt 3.a/b)**, oddziały przyklejone do granicy (y=12/y=36 → armie 24″ od siebie, w zasięgu karabinu od r.1). `demo_skirmish` (front rozłożony) + `objective_clash` (centralny napór) + **`unit_profiles`** (4 zróżnicowane profile uzbrojenia: Strzelec-24/18, Wojownik-mix 12″+2×0″, Wojownik 3×0″; jednolite staty). Kontrola celów trwała między rundami (pkt 5.d — opuszczony cel zostaje, odbija tylko przeciwnik w 3″; potwierdzone testami `test_objective_persists_when_vacated`/`_recaptured_only_by_opponent`). **Wniosek kontekstowy:** `PriorityV2Player` przegrywa z prostym na jednorodnych armiach (1:47), ale **wygrywa na zróżnicowanych** (`unit_profiles` priority2/priority 33:25) — wartość wyboru celu rośnie, gdy oddziały się różnią. **Odłożone:** breakdown per zdolność/broń (wymaga adaptera ORM `Roster`→engine-dict + heurystyki auto-rozstawienia pozycji). **Mapy generowane 2026-06-12** (wątek `faza-d-test-maps`): `--map {standard_a, lustrzana_a, symetryczna_a}` — Standard_A deterministyczna (środkowo-sym., teren z reflekcji danych usera); Lustrzana_A (losowa, lustro y=24) + Symetryczna_A (losowa, środkowo-sym., strefy pod losowym kątem), rejection-sampling pkt 5.b/5.c (cele ≥12″/≥6″) + 18 linii Niedostępny+Blokujący (≥6″/≥3″) + koła 8 Obronny/4 Trudny/2 Niebezpieczny (⌀3–6, overlap-OK). 4 profile/stronę symetrycznie. 7 testów. Ruch nie egzekwuje Trudny/Niedostępny (LoS/osłona/Niebezpieczny tak).
- [x] `scripts/balance_report.py` → `reports/balance/YYYY-MM-DD.md` — **DONE 2026-06-10** (wątek `faza-d-balance-report`): round-robin turniej (fixtura × para botów, kombinacje z powtórzeniem) reużywa `simulate_balance` (SSOT, ADR-0032) → markdown z tabelą win-rate + tekstowymi (unicode) wykresami słupkowymi. CLI `--fixtures/--players/-n/--seed/--out`. Wykresy **tekstowe, nie obrazowe** (bez matplotlib — dependency-free; obrazy = follow-up gdy user zechce zależności). `reports/` gitignored. 19 testów.

### D3. Exploit hunting (2 tyg)

> **Prereq — adapter ORM→engine-dict slice 1 DONE 2026-06-16** (wątek `faza-d-roster-adapter`): `app/services/agents/roster_adapter.py` — `roster_to_engine_roster(roster, *, owner_player, models_mode, positions=)` konwertuje ORM `Roster` na engine-dict konsumowany przez `build_initial_state`/`simulate_from_rosters`. Reuse SSOT (`normalize_range_value`/`ability_identifier`/`default_weapon_loadout`); filtruje `b_mvp_exclusions` (+ raportuje), oznacza `INCOMPLETE_ABILITIES`. `models_mode` per_copy (default)/aggregate. 14 testów, warstwa-liść (zero zmian w rdzeniu). **Domyka most ORM→engine** wskazany jako blokada D3 (win_rate/**points**). **Odłożone (follow-up):** koszt/punkty (D3 woła `calculate_roster_unit_quote` — SSOT gotowe), auto-rozstawienie (integracja z D5 `deployment_zones`), `extra_weapons_json` override, attached heroes (`parent_roster_unit_id`). **PYTANIE DO USERA (models_mode):** default `per_copy` (count osobnych blobów) — do potwierdzenia jako kanoniczny dla balansu (HANDOFF_faza-d-roster-adapter).

- [x] `scripts/exploit_hunt.py` — **Opcja A (in-memory) DONE 2026-06-16** (wątek `faza-d-exploit-hunt`, user decision): generuje losowe **efemeryczne** rozpiski (transient `Roster`, bez DB-write) z jednostek bazy bez cech pomijanych (`b_mvp_exclusions`) + z bronią; round-robin self-play (reuse `simulate_from_rosters`+`deployment_zones` D5+mapa lustrzana); ranking wg `win_rate` i `win_rate/points` (exploit). Most ORM→engine: `roster_to_engine_roster` ✓; koszt: `roster_points` ✓; rozstawienie: `deployment_zones` ✓. 12 testów (syntetyczne transient, bez DB). **Robustness 2026-06-16:** filtr kandydatów odrzuca oddziały, których koło nie mieści się w strefie rozstawienia (pkt 13.a, ≤6″ dla strefy 12″; reuse `compute_radius_inches`) — bez tego losowy oddział-gigant crashował cały turniej `IllegalActionError` (+3 testy). **Analiza koszt↔wynik 2026-06-17:** `--army NAZWA` (pula z jednej armii, np. `Testowa`), `--vary-size` (rozpiski o różnym koszcie) + sekcja „różnica kosztu vs wynik w **binach %**" (% wahnięcie od średniej kosztów dwóch armii: `<1%/1–3%/3–5%/5–10%/>10%`; per bin win-rate droższej; `PairOutcome`/`format_cost_outcome`/`--pairs-out`). **Bugfix `roster_points` = SSOT kalkulatora rozpisek** (per_copy `Σ kopie × quote(typical)` + **domyślny loadout**, wcześniej `quote(count modeli)` z pustym loadoutem — np. 6× Wzorcowy 80.62→**182.98**). Real run Testowa: >10% różnicy → droższa 92.9%, 1–3% → ~równo (37.5%/50%) → punkty TRAFNIE rankują siłę (równy koszt ≈ 50/50, większy koszt → więcej wygranych); brak sygnału exploitu (tańsza nie wygrywa ponad swój koszt). Sygnał exploitu = tańsza >50% w binie. **DB-read + `main()` pokryte** integracyjnie (`tests/test_exploit_hunt_db.py`, seeded in-memory). **Różnorodność generatora 2026-06-17:** `--min-distinct N` (default 2) wymusza ≥N różnych typów oddziałów — jednorodne rozpiski (`8×U0`) rzadziej ujawniają outliery koszt/skuteczność; efekt widoczny przy małej puli (np. real-run `--army Testowa` seed 117: `4×Łucznik` → `3×Łucznik, 1×Wojownik`). Funkcja `generate_random_roster(min_distinct=)` default 1 = wsteczna kompat. **Opcja B (odłożona — B2 auth):** konto `agent_kind=exploit_hunter` + `AgentToken` (DB-write, security-review).
- [x] **Real-run na danych usera DONE 2026-06-19** (sesja autonomiczna): 64 jednostki w 7 armiach. Pipeline DB→raport end-to-end OK. **Wynik:** sygnał exploitu jest **kompozycyjny, nie uniwersalny** — koszt agreguje siłę poprawnie przy dużych różnicach (global >10% droższa 74%, Necroni >10% droższa 81%), ale przy ~równym koszcie skład decyduje skrajnie (Gwardia budget-matched win-rate 12–79% przy ~równych pkt). Tania piechota/mobilne biją drogi pancerz/pojazdy (Gwardia `3×Weterani` 585 pkt → 93% vs Leman Russ/Sentinele 1022 pkt → 55%; Orkowie `2×Ultrasy+2×Szefuńcio` 781 pkt → 86%). Sterownik strukturalny: pkt 5.f (wygrana = kontrola 5 celów po 4 rundach → liczba mobilnych ciał > droga trwałość). **Caveat:** balans silnika MVP, nie potwierdzony exploit reguł (MVP pomija per-model/bohaterów/pełne zdolności/teren/r.4; cost-model celuje w pełną grę). Szczegóły + pytanie do usera (ADR DOCX vs akcept artefaktu MVP): `HANDOFF_faza-d-exploit-hunt.md`.
- [x] Każdy exploit → ADR z propozycją zmiany DOCX — **RESOLVED 2026-06-20 (decyzja usera B): bez ADR.** Kompozycyjny sygnał (tania piechota/mobilne biją drogi pancerz przy ~równym koszcie) = świadomy artefakt wierności silnika MVP (pomija per-model/bohaterów/pełne zdolności/teren, kończy na r.4 — pkt 5.f), NIE błąd wyceny punktów. Cost-model Strumienia A poprawny. Temat do powrotu po podniesieniu wierności (E1 per-model + E2 teren + E3 zdolności). Wątek `faza-d-exploit-hunt` zarchiwizowany.

> **Rejestr botów (SSOT, 2026-06-17; factory app-level 2026-07-07):** `app/services/agents/registry.py` klasyfikuje boty dowolnym zbiorem **tagów** (rozszerzalne): status `useful` (do testów/analiz) | `reference` (nieaktualny, porównawczo); koszt `fast` | `expensive`. `app/services/agents/factory.py` konstruuje boty przez `make_player(kind, seed)` i re-export w `balance_simulate.py` zachowuje kompatybilność skryptów. **Useful = `priority`, `priority3`, `claude_v3`**; reszta `reference`. Zapytania `bot_kinds(USEFUL, FAST)` (AND) — gotowe na przyszłe poziomy (np. useful-expensive) bez zmian API. `balance_report --players useful|fast|reference|all|<nazwa>` (domyślnie `useful`); `exploit_hunt --bot` domyślnie `priority`. Drift-guard: `tests/test_agents_factory.py` pilnuje spójności rejestr↔factory, a `tests/test_agents_registry.py` tagów.

### D4. Adversarial play (4 tyg, opcjonalne)
- [ ] Frontend UI "Play vs AI" — wybór agenta z listy
- [x] `minimax_player.py` — **DONE 2026-06-18** (wątek `faza-d-minimax`): `MinimaxPlayer(seed)` lookahead depth-2 (maximin: moja akcja → najlepsza odpowiedź wroga 1-ply → ocena `evaluate_state` po przeliczeniu kontroli `_check_objective_control`, SSOT pkt 5.d). Reużywa `resolver.apply` (rzeczywista semantyka + przekazanie inicjatywy pkt 8.a) zamiast heurystycznych hipotetycznych stanów (różnica jakościowa vs depth-1 greedy). **Deterministyczny rollout** (`DeterministicDice(seed)` świeży per aplikacja — silnik stochastyczny → czysty minimax niemożliwy; pełny expectiminimax odłożony). `--players minimax`. ~30 ms/akcja (cap niepotrzebny). 8 testów. **Wynik balansu (lustrzana_a):** bije greedy 100%, random 67%, ale **przegrywa z `priority` 0:6** — spójne z udokumentowanym „złożoność ≠ siła" (prosty marsz-na-cele bije taktyczny lookahead; cele rozstrzygają się na końcu rundy poza horyzontem 1-ply). Warstwa-liść, zero zmian w rdzeniu.
- [x] `claude_v2_player.py` — **`ClaudeV2Player` 2026-06-17** (`--players claude_v2`): depth-2 z **modelowaniem przeciwnika** zamiast maximinu. Diagnoza: i depth-1 value-max (`claude_v1`) i depth-2 `minimax` przegrywają ~4–8% z priority, bo wąskim gardłem jest OCENA LIŚCIA (rodzina value-max), nie głębokość; `minimax` dodatkowo enumeruje każdą odpowiedź wroga (~185× koszt priority). ClaudeV2: riposta wroga = JEDNA realistyczna akcja `priority3.choose_action` (nie enumeracja), expectimax-lite (`samples=2` rzutów `DeterministicDice`), ocena ability-aware (HP + cele z gradientem + człon statusów Przyszpilony/Wyczerpany przez slugi). **Wynik (3 fixtury, 60 gier/matchup):** dramatyczna poprawa vs poprzedniki — **35% vs priority, 28% vs priority3** (claude_v1/minimax: 4–8%), bije claude_v1 75% i greedy 95%. **Nadal NIE bije priority/priority3.** Sweep `samples∈{1,2,3}`: 2 optymalne (1 słabszy, 3 bez zysku). **Koszt ~100–130× priority** (≈ minimax, taniej niż enumeracja byłaby, ale 2 próbki + model przeciwnika). 5 testów.
  - **Wniosek (D4):** priority/priority3 (hand-tuned, depth-1, ~6× koszt) pozostają najlepszym stosunkiem siła/koszt. Ani głębokość (depth-2), ani modelowanie przeciwnika nie wystarczają, by je pobić — sufit to jakość OCENY/POLITYKI, nie lookahead. Realna droga do pobicia: imitacja silnej polityki (np. uczona) lub ocena kalibrowana do pkt 5.f, nie głębsze drzewo.
  - **Koszt obliczeniowy / decyzję (mediana, self-play, względem priority=1.0):** `priority` 1.0 · `claude_v3` ~1.8 · `priority3` 5.7 · `greedy` 7.0 · `claude_v1` 8.6 · `minimax` ~185 · `claude_v2` ~100–130.
- [x] `claude_v3_player.py` — **`ClaudeV3Player` 2026-06-17** (`--players claude_v3`): **najlepsze podejście** — zamiast walczyć z polityką priority, DZIEDZICZY szkielet `PriorityPlayer` (selekcja oddziału + kolejność 1–7 + ruch na cele) i nadpisuje TYLKO wybór celu (krok 2/3): „dobij/koncentruj" (`mean + p_full_kill·30 + expected_kills·14`, ability-aware przez `expected_damage`) zamiast „najbliższy". Naprawia udokumentowaną słabość (priority strzela najbliższego — rozprasza; priority3 `x(4-x)` nie premiuje dobijania). **Depth-1, ~1.8× koszt priority** (zgodnie z „ten sam rząd"). **Wynik (3 fixtury, 120 gier/matchup):** bije priority2 60%, greedy 88%, claude_v1 75%, ~remis claude_v2 52% — **najlepszy z botów Claude vs priority (~42%) i priority3 (~33%)**. **Nadal NIE bije priority/priority3.** Sweep 10+ konfiguracji wag (finish/kill/deny/proximity): wszystkie 30–43% — sufit STRUKTURALNY: „strzel najbliższego" to mocne lokalne optimum (proximity-anchoring i odcięcie celów sprawdzone, nie pomogły; czysty focus-fire najlepszy). 5 testów.
  - **Wniosek finalny D4 (3 podejścia × ~15 wariantów):** żaden bot heurystyczny — depth-1 value-max (v1), depth-2 z modelem przeciwnika (v2), ani priority+smart-targeting (v3) — nie bije `priority`/`priority3` przy 2–130× ich kosztu. **Sufit to jakość polityki, nie głębokość ani wybór celu.** `priority` (depth-1, ~6× `priority3`... a sam priority bazowy 1×) pozostaje najlepszym stosunkiem siła/koszt. Realna droga do pobicia: nauczona polityka (imitation/RL) lub ocena kalibrowana do pkt 5.f — poza zakresem botów heurystycznych.
- [x] Leaderboard `reports/leaderboard.md` — **DONE 2026-06-19** (wątek `faza-d-leaderboard`, ADR-0030): `scripts/leaderboard.py` — round-robin **różnych** botów (mirror self-play wykluczony) ponad fixturami, agregacja **ponad parami** w jeden standing per bot (gry/wygrane/porażki/remisy/win-rate) → markdown z tabelą rankingową + tekstowymi (unicode) słupkami. Reuse `simulate_balance` (SSOT, ADR-0032) + wspólna infrastruktura `scripts/balance_common.py` współdzielona z `balance_report.py` (cleanup 2026-06-20). Skrypt-liść, 20 testów. Real-run (5 botów × 3 fixtury, n=8): **priority3 66.7% > claude_v3 62.5% > priority 46.9% > random 26% > greedy 12.5%** — potwierdza udokumentowany wniosek D4 (priority/priority3 najsilniejsze). `reports/` gitignored. Domyślny zestaw botów = tag `useful` z `agents/registry.py` (`priority`, `priority3`, `claude_v3`); `--players all` przywraca pełny ranking z botami referencyjnymi/drogimi.
- [x] ADR-0030: Wielu agentów konkurujących — **część 1 (ranking botów) DONE; część 2 (osobne konta + leaderboard międzykontowy) ODŁOŻONA do B2 auth.** (Accepted)

### D5. Rozstawienie jako decyzja bota — **Proste strategie DONE 2026-06-15** (wątek `faza-d-deployment`)

> Wcześniej pozycje startowe brały się z fikstury YAML; `deployment_round` było wywoływane z pustą listą akcji — boty nie miały wpływu na start. Slice „proste strategie" (bez E4) zrealizowany: `app/services/agents/deployment.py` (`DeploymentZone` pkt 24 + `grid_positions`/`random_position_in_zone`) + `Player.choose_deployment` (ABC, default=pozycja z roster) + `simulate_from_rosters(deployment_zones=)` (auto-deployment + walidacja strefy). 18 testów. Warstwa-liść agentów, zero zmian w rdzeniu silnika.

- [x] `Player.choose_deployment(state, unit_id, zone) → Position` — nowa metoda ABC (default: pozycja z roster/fikstury = wsteczna kompat). `RandomPlayer` override (losowa legalna pozycja w strefie, deterministyczna per seed).
- [x] `simulate_from_rosters(deployment_zones=(zone_p0, zone_p1))` pyta graczy o pozycje przed `deployment_round`; waliduje całe koło oddziału w strefie (pkt 13.a MVP) przez `IllegalActionError`. Wzajemnie wykluczające z explicit `deployment` (ValueError).
- [x] Proste strategie deploymentu (nie wymagają E4): grid równomierny w strefie (`grid_positions`), losowa-w-strefie (`random_position_in_zone`). **Boty deterministyczne** (Greedy/Priority/V2/V3) rozstawiają się gridem przez `GridDeploymentMixin` (`grid_deployment_position` — slot per oddział, grid liczony dla maks. promienia własnych oddziałów); `RandomPlayer` losuje w strefie. Wpięcie addytywne (aktywne tylko z `deployment_zones`) → B7 golden digesty bez zmian. **Uproszczenie pkt 13.a (MVP):** legalność = całe koło w prostokącie strefy; cecha Niedostępny (pkt 4.c.i) + reguła >1″ od innych oddziałów świadomie pominięte (E4 kolizje).
- [ ] Strategie zaawansowane (wymagają E4 kolizji): rozstaw bez nachodzenia; coverage-based (maksymalizuj liczbę pokrytych celów z pozycji startowej)
- [x] Testy: pozycja poza strefą rozstawienia odrzucona; gracze dostają różne pozycje na tej samej planszy; grid deterministyczny + legalny; backward compat (None → pozycje z roster); integracja+determinizm.

---

## Strumień E — Wzbogacanie modelu (po B stabilne, tydzień 20+)

### E1. Per-model granularity (4–5 tyg)
- [ ] `BattleModel` frozen dataclass w `app/services/engine/per_model.py`
- [ ] `expand_blob_to_models(blob)` — na potrzeby heterogenicznych loadoutów
- [ ] Adapter eventów: `BlobModified` → `ModelModified`
- [ ] ADR-0040: Migration blob → per-model

### E2. Geometria terenu — DONE 2026-11-12
- [x] `TerrainPolygon` w `app/services/engine/terrain_complex.py`: prosty obrys wypukły lub wklęsły, także w fixturach YAML.
- [x] Linia wzroku dla poligonów, zapis i odczyt checkpointów v1–v3 oraz rysowanie w podglądzie 2D.
- [x] [ADR-0041: Wielokąty terenu](adr/0041-terrain-polygons.md). Pełny `pytest -q`: 3739 testów zaliczonych. Smoke w Edge: uwierzytelniony odczyt checkpointu i rysowanie poligonu.

### E3. Złożone zdolności (iteracyjnie)
- [ ] Lista priorytetowa z `build/geometry_classification.md`
- [ ] Zdolność `Zwrot` wprowadza `UnitBlob.facing_deg: float = 0.0`
- [ ] Każda zdolność = osobny PR + test + ADR

### E4. Ruch — kolizje i pathfinding Manewru — DONE 2026-11-12

- [x] `find_reachable_positions` w `app/services/engine/pathfinding.py` używa lokalnej siatki heksagonalnej o kroku 1″. Walidator sprawdza prostą trasę oraz objazd z dokładnym połączeniem do celu poza siatką.
- [x] Silnik sprawdza obrys poruszającego się oddziału na całej trasie. Żywe oddziały na Froncie i teren Niedostępny stanowią przeszkody (pkt 2.d i 4.c.i). Możliwy jest styk kół oddziałów (pkt 15.c). [Źródło reguł](../app/static/docs/SZOP_Rozjemca.md)
- [x] Przejście przez Trudny zmniejsza budżet całej trasy o połowę (pkt 4.c.iv). Planer dopuszcza dłuższy objazd mieszczący się w pełnym budżecie, jeśli omija ten teren. [Źródło reguł](../app/static/docs/SZOP_Rozjemca.md)
- [x] Boty Greedy i rodzina Priority korzystają z tego samego planera co walidator Manewru. Zdarzenia nadal zapisują punkt początkowy i końcowy, a odtwarzanie bitew stosuje zapisane wyniki.
- [x] [ADR-0057: Trasy Manewru i kolizje](adr/0057-maneuver-pathfinding.md) opisuje zakres i ograniczenia siatki. Pełny `pytest -q`: 3763 testy zaliczone. Próby API v1–v3 obejmują odrzucenie ruchu przez przeszkodę bez zapisu i odtworzenie legalnego objazdu.

---

## Cross-cutting: telemetria od dnia 1 (ADR-0017)

> **Slice analityki z event-logu DONE 2026-06-21** (wątek `faza-telemetry-analyze`): `scripts/analyze_battle.py` — analityczny raport markdown bitwy **z samego event-logu** (komplementarny do `battle_replay.py` narracji): wynik gry (zwycięzca pkt 5.f + timeline kontroli celów per runda pkt 5.d/8.c.ii), statystyki ataku/obrony per oddział i per strona (obrażenia/trafienia/straty/ELIMINOWANY pkt 26.d), rozkład akcji + typów eventów, szczęście kości Przegrupowania (rozkład 1–6 + średnia pkt 20). Dwa źródła (jak `battle_replay`): `--fixture`/`--map` (sim, mapowanie oddział→strona z `final_state`) + `--from-db` (`persistence.load_events`, read-only; bez `initial_state` → degradacja do per-oddział). **Tryb agregatu `--games N`** (wątek `faza-telemetry-aggregate`): N gier z naprzemienną inicjatywą (metodyka `balance_simulate`) → średnie per strona (obrażenia/straty/akcje na grę) + rozkład wyników + zagregowane kości — diagnostyka „DLACZEGO bot wygrywa" (luka poza leaderboard/balance_report; np. priority vs claude_v3 mają ~równe obrażenia, różni je kontrola celów — potwierdza wniosek D4). Skrypt-liść, 27 testów. **Maszynowy eksport `--json PATH` (DONE 2026-06-21, wątek `faza-telemetry-json`):** serializuje `BattleAnalysis`/`AggregateAnalysis` do JSON-owalnego dict (schema `szop.battle_metrics/v1`, jedna linia = rekord jsonl) — metryki strukturalne odzyskiwalne z event-logu (additive do markdown). Live structlog-emission + pola czasowe (poniżej) odłożone — wymaga zmian w hot-path silnika. **Telemetria decyzji bota DONE 2026-06-22 (wątek `faza-telemetry-agents`):** `scripts/analyze_agents.py` realizuje box `data/agent_metrics/*.jsonl` (`decision_time_ms` wall-clock `choose_action` + `decision_quality_score` = Δ `evaluate_state`, samoocena bota) **per agent** z re-symulacji, przez additive `on_decision` hook w `match.run_match` (default None → B7 golden bez zmian). Schema `szop.agent_metrics/v1`. To pierwsze pole CZASOWE telemetrii (offline, wall-clock) — live-emission decyzji w produkcyjnym B4 wciąż odłożona.

- [ ] `structlog` w `app/services/engine/{resolver, persistence}.py` — każdy event: `battle_id, action_id, actor_user_id`
- [~] `data/battle_metrics/{battle_id}.jsonl` — **slice DONE 2026-06-21** (`analyze_battle.py --json PATH`): pola ODZYSKIWALNE z event-logu (`action_count`/`event_type_counts`, `dice_distribution`, staty per oddział/strona, kontrola celów; schema `szop.battle_metrics/v1`, jsonl-kompatybilny rekord). Pola czasowe `time_per_action_ms`/`dice_rolls_total` live odłożone (hot-path).
- [x] `data/agent_metrics/{agent_user_id}.jsonl` — `decision_time_ms, decision_quality_score` — **slice DONE 2026-06-22** (`scripts/analyze_agents.py --json`): telemetria decyzji **per bot** z re-symulacji. `decision_time_ms` = wall-clock `choose_action`; `decision_quality_score` = Δ `evaluate_state` (samoocena bota, SSOT `policy_eval`). Agregat: śr./mediana/max czas, śr. jakość, odsetek decyzji poprawiających, miks akcji (schema `szop.agent_metrics/v1`). Instrumentacja przez additive `on_decision` hook w `match.run_match` (default None → zero zmian zachowania). `agent` = nazwa bota; konta DB (`agent_user_id`) + live-emission w produkcyjnym przepływie B4 odłożone do B2 auth (ADR-0030 cz. 2).
- [!] Raw combat rolls / pełny audyt szczęścia kości bojowych — decyzja 2026-06-26: odłożone do czasu konkretnej potrzeby; niska wartość teraz, a zmiana wymagałaby schemy eventów + ADR + regen B7.
- [x] `scripts/analyze_battle.py` — raport markdown z (tekstowymi) wykresami z event-logu — **DONE 2026-06-21** (slice; `<id>` przez `--from-db`; `--json` = maszynowy eksport metryk)
- [x] `scripts/analyze_agents.py` — telemetria decyzji bota per agent (`decision_time_ms`/`decision_quality_score`, `--json`) — **DONE 2026-06-22**
- [x] `.gitignore`: `data/{battle,agent}_metrics/` — pokryte blankietowym `data/` (wyjątek `!app/data/`)

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
| 0017 | Telemetria od dnia 1: analiza offline z event-logu | ✓ |
| 0020 | MCP runtime: Python SDK | — |
| 0021 | MCP jako klient publicznego API | ✓ |
| 0022 | Vector store: sqlite-vec | ✓ |
| 0023 | Embeddings: sentence-transformers offline | ✓ |
| 0024 | Consent-gated agent writes | ✓ |
| 0025 | Rola agent + scoped tokens (schema + helper + endpointy) | ✓ |
| 0026 | Weighted RRF dla offline hybrid retrieval | ✓ |
| 0027 | Procesowy lifecycle fixed MiniLM | ✓ |
| 0028 | Runtime hybrid rules search przez publiczne API | ✓ |
| 0029 | Publiczna walidacja loadoutu bez zapisu | ✓ |
| 0030 | Wielu agentów: ranking botów (leaderboard) ✓ + osobne konta (odłożone do B2 auth) | ✓ |
| 0031 | Gracze heurystyczni D1: enumerator akcji + Random/Greedy | ✓ |
| 0032 | Headless match runner (orkiestrator pełnej gry dla botów) | ✓ |
| 0033 | Owner-scoped score_list przez publiczne API | ✓ |
| 0034 | Owner-scoped granica wyszukiwania kandydatów exploitu | ✓ |
| 0040 | Migration blob → per-model | — |
| 0041 | [Wielokąty terenu](adr/0041-terrain-polygons.md) | Accepted |
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
| 0052 | Końcowy odstęp Manewru od innych oddziałów | Zastąpiony przez ADR-0057 |
| 0053 | Wersjonowane checkpointy BattleState + RNG | ✓ |
| 0054 | Atomowe pojedyncze akcje bitwy przez HTTP | ✓ |
| 0055 | Trwały lifecycle zaproszenia do bitwy | ✓ |
| 0056 | Trwały protokół aktywacji i okien przerwań (B4.4a design) | ✓ |
| 0057 | [Trasy Manewru i kolizje](adr/0057-maneuver-pathfinding.md) | Accepted |
| 0058 | [Kontrola celu w promieniu 2″](adr/0058-objective-control-two-inches.md) | Accepted |

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
