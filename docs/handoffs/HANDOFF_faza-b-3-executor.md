# HANDOFF — faza-b-3-executor

> **Wątek:** Strumień B, Faza B3 — Rule Executor + dice. Sub-wątek `faza-b-engine-mvp`. 7 modułów engine pure-functions (`dice`, `los`, `prediction`, `combat`, `effects`, `interrupts`, `phases`, `resolver`) + minimalny substrate runtime (`state.py` + `events.py`) + 6 nowych ADR-ów.
> **Status:** In progress (B3.0 ✅ + B3.1 dice ✅ + B3.2 LoS ✅ + B3.4 combat ✅ done 2026-05-30; GATE OPEN; B3.3 prediction lub B3.5 effects/interrupts next)
> **Utworzony:** 2026-05-30
> **Ostatnia aktualizacja:** 2026-05-30

## Cel

Zaimplementować pure-function rule executor symulatora SZOP zgodnie z `SZOP_Rozjemca.md` (mechaniki) + `SZOP_Zdolnosci.md` (efekty 77 zdolności). Engine bez I/O, bez DB — każdy moduł testowalny w izolacji. Wejście preflight: ADR-0010a GATE pkt 3 (audit akcji ↔ zdolności) + minimalne runtime dataclasses (`UnitBlob`, `BattleState`, `TerrainCircle/Line`, eventy + `apply_events`). Pełne B2 (ORM persistence + Alembic) świadomie wydzielone do osobnego sub-wątku `faza-b-2-models` — executor nie potrzebuje DB do testów.

Plan długofalowy: [docs/roadmap.md#b3-rule-executor--dice](../roadmap.md). Parent: [HANDOFF_faza-b-engine-mvp.md](HANDOFF_faza-b-engine-mvp.md).

## Zablokowane pliki / katalogi

**Sesja B3.0 (preflight):**
- `app/services/engine/__init__.py` (NEW) — pakiet
- `app/services/engine/state.py` (NEW) — `UnitBlob`, `BattleState`, `TerrainCircle`, `TerrainLine` frozen dataclasses + `apply_events()` pure rebuilder
- `app/services/engine/events.py` (NEW) — `MoveExecuted`, `ShotResolved`, `MeleeResolved`, `ModelKilled`, `MoraleTestPassed`, `EffectApplied`, `InterruptTriggered`, `RoundEnded` + `event_to_json()` / `json_to_event()`
- `tests/test_engine_state.py` (NEW) — UnitBlob/BattleState immutability + radius helper (zgodne z ADR-0008 wzór `radius = sqrt(sum(toughness)/π)`)
- `tests/test_engine_events.py` (NEW) — serializacja round-trip + replay deterministic
- `docs/adr/0011-rule-executor.md` (NEW) — Status: Proposed → Accepted po B3.7
- `build/b3_action_ability_audit.md` (NEW) — wynik audytu GATE pkt 3 ADR-0010a (mapping akcji 14.a–e ↔ zdolności aktywne z `abilities.yaml` tag=`active`)

**Sesja B3.1+ (per moduł, w kolejności):**
- B3.1 dice: `app/services/engine/dice.py` (NEW, ~80 LOC), `tests/test_engine_dice.py` (NEW), `docs/adr/0012-dice-deterministic.md` (NEW Accepted)
- B3.2 los: `app/services/engine/los.py` (NEW), `tests/test_los_geometry.py` (NEW, 30 scenarios), `docs/adr/0043-los-3-state.md` (NEW Accepted)
- B3.3 prediction: `app/services/engine/prediction.py` (NEW), `tests/test_prediction_vs_simulation.py` (NEW, 100×1000), `docs/adr/0044-prediction-module.md` (NEW Accepted)
- B3.4 combat: `app/services/engine/combat.py` (NEW), `tests/test_engine_combat.py` (NEW), `docs/adr/0015a-reactive-window.md` (NEW Accepted)
- B3.5 effects + interrupts: `app/services/engine/effects.py` (NEW), `app/services/engine/interrupts.py` (NEW), `tests/test_engine_effects.py` (NEW), `tests/test_engine_interrupts.py` (NEW), `docs/adr/0015-interrupt-points.md` (NEW Accepted)
- B3.6 phases: `app/services/engine/phases.py` (NEW), `tests/test_engine_phases.py` (NEW)
- B3.7 resolver: `app/services/engine/resolver.py` (NEW), `tests/test_engine_resolver.py` (NEW)
- B3.9 weryfikacja: `docs/roadmap.md` (B3 status update), `docs/adr/0011-rule-executor.md` (promote Proposed → Accepted)

**Read-only przez cały B3 (źródła prawdy, freeze per ADR-0010a):**
- `app/static/docs/SZOP_Rozjemca.md` — reguły gry (mechaniki, fazy, akcje, eventy)
- `app/static/docs/SZOP_Zdolnosci.md` — 77 zdolności (id, typ, opis, efekty, koszt, tagi)
- `app/rulesets/v1/abilities.yaml` (88 entries) — lookup ability data
- `app/rulesets/v1/tables.yaml > b_mvp` — `move_inches`, `base_area_inches_sq_per_toughness`, `pi_approx`
- `app/rulesets/v1/b_mvp_exclusions.yaml` (6 entries) — engine raise `UnsupportedAbilityError` przy budowie `BattleState`
- `app/services/rulesets/` — Pydantic schemas + loader; B3 importuje, NIE modyfikuje
- `app/services/costs/` — Strumień A SSOT; B3 nie dotyka

## Blokuje / Blokowane przez

- **Blokuje:**
  - B4 (API) — `app/routers/battles.py` wymaga `resolver.apply()` jako entrypoint
  - B5 (klient `szop_client`) — `LocalClient` opakowuje resolver
  - B7 (test bed) — golden battles `tests/fixtures/battles/*.yaml` wymagają pełnego executor
  - Strumień C (MCP agent) — `simulate_engagement` tool wymaga engine
  - Strumień D (boty) — wszyscy gracze (random/greedy/minimax) wymagają executor + prediction
- **Blokowane przez:**
  - **ADR-0010a GATE pkt 3** (audit mapping akcji pkt 14 ↔ aktywne zdolności w `SZOP_Zdolnosci.md`) — niezrobione w B0; przesunięte do B3.0 preflight tego sub-wątku
  - **Minimalne B2 substrate** (runtime dataclasses `UnitBlob`, `BattleState`, event types + `apply_events`) — fundamenty dla testów B3; zrobione w B3.0
- **Świadomie wydzielone (równolegle dozwolone):**
  - **Pełne B2** (ORM `Battle`/`BattleEvent`/`BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog` + Alembic migration + `Unit.base_size_mm`) → osobny sub-wątek `faza-b-2-models` (do utworzenia gdy B4 API startuje). Executor pure-function nie potrzebuje DB do testów.

## Gałąź git

- **Branch:** `Faza_A` (kontynuujemy z parent, niezmienione)
- **Base:** `main`

## Plan implementacji

### B3.0 — Preflight (GATE audit + runtime substrate) — **DONE 2026-05-30**

**Cel:** spełnić ADR-0010a GATE pkt 3 + dostarczyć minimalne runtime dataclasses, na których buduje się dice/los/prediction/combat/etc. Bez tego B3.1+ nie startuje.

- [x] **B3.0.1 — GATE audit (ADR-0010a pkt 3):** porównać akcje z `SZOP_Rozjemca.md pkt 14.a–e` z aktywnymi zdolnościami w `SZOP_Zdolnosci.md` (`type=active` w `abilities.yaml`). Output: [`build/b3_action_ability_audit.md`](../../build/b3_action_ability_audit.md) — 12 aktywnych zdolności sklasyfikowanych (6× 14.e_in_activation + 6× przerwanie pkt 12). Hardcoded handlery dla akcji 14.a-d w `combat.py`/`phases.py`; 14.e → `ACTIVE_ABILITY_REGISTRY` w `effects.py`. **Brak braków mapowania.**
- [x] **B3.0.2 — Runtime substrate (`app/services/engine/state.py`):** `UnitBlob(frozen=True, slots=True)` z 4 kategoriami ran (ADR-0014) + position/radius_inches/models_alive/toughness_per_model/is_hero_unit/passives/status_flags + `BattleState(frozen=True)` + `TerrainCircle`/`TerrainLine` + helper `compute_radius_inches(toughness_sum, config)` per ADR-0008. `apply_events(initial, events)` pure rebuilder z dispatch przez `_EVENT_REDUCERS` + `@register_reducer(event_type_name)` decorator.
- [x] **B3.0.3 — Eventy (`app/services/engine/events.py`):** 8 frozen dataclass-ów (MoveExecuted, ShotResolved, MeleeResolved, ModelKilled, MoraleTestPassed, EffectApplied, InterruptTriggered, RoundEnded) + `event_to_json()` / `json_to_event()` z `event_type` discriminator. `version: int = SCHEMA_VERSION` (=1) w każdym event payload. `_EVENT_REGISTRY` mapping name → class.
- [x] **B3.0.4 — Engine raise dla wykluczonych zdolności:** `build_initial_state(rosters, terrain, ruleset_version)` w `state.py` walidauje każdy `unit["passives"]` względem `load_b_mvp_exclusions().slugs()`; raise `UnsupportedAbilityError(slug, reason)` przy pierwszym napotkaniu. Wszystkie 6 case'ów (samolot/wrak/wysoki/zwrot/sterowany/zuzywalny) pokryte parametrized testem.
- [x] **B3.0.5 — Testy substrate:** `tests/test_engine_state.py` (24 testy: 5× frozen immutability, 4× compute_radius, 8× build_initial_state włącznie z parametrized exclusions, 7× apply_events + register_reducer) + `tests/test_engine_events.py` (13 testów: 8 typów round-trip, JSON cycle, tuple preservation, schema versioning, error handling). **36 testów, wszystkie zielone.**
- [x] **B3.0.6 — ADR-0011 (Proposed):** `docs/adr/0011-rule-executor.md` — hardcoded klasy/funkcje na MVP (zamiast YAML rule engine). Sekcja "Do rewizji przed promocją na Accepted (po B3.7)" lista 8 punktów do weryfikacji empirycznej (size of effects.py, combat complexity, Action polimorfizm, etc.).
- [x] **B3.0.7 — GATE check:** **GATE → OPEN** ✅. Wszystkie 5 punktów ADR-0010a spełnione: (1) SZOP_Rozjemca.md w repo, (2) SZOP_Zdolnosci.md w repo, (3) mapping audit kompletny (B3.0.1), (4) b_mvp_exclusions.yaml zatwierdzony, (5) ADR-y 0008/0010/0014 Accepted + 0010a sam w użyciu (Status: Accepted). **B3.1 (dice) może startować w następnej sesji.**

### B3.1 — Dice — **DONE 2026-05-30**

- [x] `app/services/engine/dice.py` (~110 LOC): `DeterministicDice(seed)` wrapping `random.Random`, `roll_d6(count) -> tuple[int, ...]`, `roll_with_threshold(count, threshold, *, modifier=0, natural_6_auto_success=True, natural_1_auto_failure=True) -> RollResult`. `RollResult` frozen+slots z `rolls/successes/effective_threshold/base_threshold/modifier`. Pełne reguły `SZOP_Rozjemca.md pkt 1` (a/b/c/d) zaszyte; logika konkretnych zdolności (Brutalny/Delikatny/Furia/Niewrazliwy) flagami / inspekcją natural rolls przez combat.py.
- [x] Testy `tests/test_engine_dice.py` (24 testy): reproducibility (same seed → same sequence × 10), different seeds → different (anti-collision), distribution (chi-square 10k rolls < 20.515 dla df=5 p=0.001), threshold semantics (basic 4+, natural 1 always fail, natural 6 auto-success default), Brutalny case (`natural_6_auto_success=False`), Delikatny case (analogicznie, plus natural 6 jeszcze success gdy ≥ threshold), modifier (+/-/clamp to 2+), edge cases (count=0, negative raises), RollResult frozen + natural rolls preserved.
- [x] ADR-0012 (`docs/adr/0012-dice-deterministic.md`) Status: Accepted — `random.Random(seed)` z stdlib (brak zewnętrznej biblioteki), 4 inwarianty replay, 6 alternatyw odrzuconych (numpy, secrets, `dice` lib, globalny random.seed(), inline rolling, NamedTuple).

### B3.2 — LoS (Line of Sight, 3-state) — **DONE 2026-05-30**

- [x] `app/services/engine/los.py` (~210 LOC): `LoSState` Enum (WIDZI/NIE_WIDZI/OSLONA), `check_los(attacker, target, terrain, n_samples=16) → LoSState`. Sampling N=16 punktów na obwodzie celu (równomierne kąty 2π·i/N). Attacker edge point na obwodzie ku celowi. Filtruje Blokujący (zawsze) + Zasłaniający (z wyjątkiem pkt 4.c.iii — atakujący/cel wewnątrz pozwala pass-through).
- [x] Geometry helpers (private, pure): `_distance`, `_point_in_circle`, `_segment_intersects_circle` (closest point projection + clamp), `_segments_intersect` (CCW orientation test z colinearity), `_blob_inside_terrain` (proxy przez centrum bloba, line zawsze False).
- [x] Testy `tests/test_los_geometry.py` (43 testy): geometry primitives (12: distance/point-in-circle/segment-circle/segments), Blokujący scenarios (4: full block circle/line, partial OSLONA, far terrain), Zasłaniający scenarios (5: neither/attacker-inside/target-inside/both-inside/Blokujący nie ma wyjątku), multiple terrain (2), non-blocking features ignored (3: Trudny/Obronny/multi-feature), edge cases (4: n_samples=0/-N/default/1), enum (2), realistic battle scenarios (2: thin pillar, wall behind).
- [x] ADR-0043 (`docs/adr/0043-los-3-state.md`) Status: Accepted — uzasadnienie N=16 (Pareto sweet spot ~1.96″ spacing dla cel r=5″), trade-off table (N=4/8/16/32), 6 alternatyw odrzuconych (binary LoS, analytic tangent, ray-marching, sample-on-attacker, modele blokery from day 1, LoSState as string), plan B (N=32 lub analytic tangent jeśli >5% false-positive).

### B3.3 — Prediction (analytic, no RNG)

- [ ] `app/services/engine/prediction.py`: `expected_damage(attacker, defender, weapon_slug, terrain, ruleset) → DamageDistribution` — analityczny binomial CDF, bez RNG; uwzględnia osłonę (pkt 19), bonusy/kary trafienia (pkt 17.a) i obrony (pkt 17.b)
- [ ] `DamageDistribution(mean, pmf: dict[int, float], p_at_least(n) → float, p_kill() → float)`
- [ ] `would_see(blob_pos, target_blob, terrain) → LoSState` — hipotetyczny LoS bez modyfikacji state (dla heuristic players)
- [ ] Testy `tests/test_prediction_vs_simulation.py`: 100 scenariuszy × 1000 Monte Carlo via `DeterministicDice(seed_i)`; assert `analytic.mean within ±3σ of simulated.mean`; Chi-square dla pmf (p > 0.01)
- [ ] ADR-0044 (`docs/adr/0044-prediction-module.md`) Status: Accepted — agentom-botom (Strumień D) i MCP (`simulate_engagement`) potrzebny tanie expected_damage bez full simulation

### B3.4 — Combat (ranged + melee, 3 fazy + reactive window) — **DONE 2026-05-30** (kontratak/Szarża/reactive window deferred do B3.5+)

- [x] `app/services/engine/combat.py` (~430 LOC):
  - `WeaponProfile` frozen (slug/name/range/attacks/ap/attack_quality_override/weapon_abilities)
  - `CombatResult` frozen (events/new_attacker/new_defender)
  - `resolve_ranged_attack(state, attacker, defender, weapon, dice, sequence, terrain)` — 3-fazowa semantyka pkt 17 + 19. Faza 1 declare + Osłona (compute_cover, compute_attack_modifiers, compute_defense_modifier). Faza 2 hit/defense rolls (dice.roll_with_threshold + Brutalny flag). Faza 3 wound allocation pkt 17.d-e (pula attacker precise / pula defender) + pkt 18 (model kills).
  - `resolve_melee_attack(...)` — analogicznie + `melee_balance` accounting per pkt 20.c (attacker += wounds, defender -= wounds). Bez Szarży/kontrataku — pojedynczy atak.
  - Helpers: `compute_cover` (LoS OSLONA lub defender wewnątrz Obronny pkt 4.c.vi), `compute_attack_modifiers` (pkt 19: -1 trafienie LUB +1 obrony gdy threshold≥6), `compute_defense_modifier` (AP + bonus), `_allocate_wounds_to_defender` (pkt 18 model kills + prefer_hero dla puli precyzyjnej), `_blob_inside_circle`.
- [x] Weapon abilities MVP: **AP(X)** (id 55), **Brutalny** (id 57 — `natural_6_auto_success=False`), **Precyzyjny** (id 68 — wszystkie rany → pula atakującego, prefer_hero kills hero first). Pozostałe (Furia/Impet/Podwójny/Przebijająca/Zabójczy/Dezintegracja/etc.) — TODO docstring, integracja w B3.5 `effects.py`.
- [x] Testy `tests/test_engine_combat.py` (37 testów): WeaponProfile/CombatResult frozen (3), compute_cover (4: no terrain, OSLONA partial block, Obronny inside, clear), compute_attack_modifiers (4: no cover, cover Q4, cover Q6→def bonus, Q7), compute_defense_modifier (4: combinations AP/bonus), _allocate_wounds (7: marker, kill, multiple, mixed, defeated, prefer hero, no prefer), resolve_ranged (9: ShotResolved, no hits, attacker unchanged, deterministic replay, AP↑wounds, Precyzyjny→hero killed first, Brutalny↑wounds, sequence, full kill), resolve_melee (4: MeleeResolved, balance, no wounds no balance, pure function), immutability (2).
- [x] State update: `UnitBlob` rozszerzony o `quality: int = 4` + `defense: int = 5` (per SZOP_Rozjemca pkt 1 + 17.a-b). `build_initial_state` czyta z rosters (`quality`/`defense` keys, defaults). 100% backward compat — istniejące testy state.py + dice.py + los.py zielone (103/103).
- [x] ADR-0015a (`docs/adr/0015a-reactive-window.md`) Status: Accepted — jednorazowe, atomowe, brak nested. Rozróżnienie reactive window (combat.py) vs interrupt pkt 12 (interrupts.py B3.5). Strażnik (id 31) jako interrupt, Kontratak (pkt 14.d.iv) i Kontra (id 10) jako reactive window. 4 inwarianty replay. Framework gotowy, **konkretne reactive zdolności + kontratak w Szarży w B3.5+** (`resolve_charge_attack`).
- **Note:** B3.4 zamknięte w **uproszczonym zakresie** — pełny `resolve_charge_attack` z reactive window kontrataku (pkt 14.d.iv) wymaga effects/interrupts substrate; przeniesione do follow-up (część B3.5 lub B3.6 phases).

### B3.5 — Effects + Interrupts

- [ ] `app/services/engine/effects.py`: `EFFECT_REGISTRY: dict[slug, Callable[[UnitBlob, EffectContext], UnitBlob]]` — każda funkcja czysta. Slug-i pasywne (`Nieustraszony`, `Furia`, `Maskowanie`, `Regeneracja`, etc.) jako `passive_effect_fn`. Aktywne (np. `Strażnik` jako reactive — collaboruje z `interrupts.py`)
- [ ] `app/services/engine/interrupts.py`: `InterruptManager` z 4 zamkniętymi punktami per ADR-0015: `activation_start`, `after_action`, `before_regroup`, `after_regroup`. Constraint: interrupt nie generuje nowego punktu — wykonywany atomowo, wraca do głównego flow
- [ ] Testy `tests/test_engine_effects.py` (pasywne na `UnitBlob`) + `tests/test_engine_interrupts.py` (kolejność wywołania per punkt, atomowość)
- [ ] ADR-0015 (`docs/adr/0015-interrupt-points.md`) Status: Accepted — 4 zamknięte punkty; alternatywy odrzucone (CPS-style continuation, async event queue)

### B3.6 — Phases (round flow)

- [ ] `app/services/engine/phases.py`:
  - `setup_phase(roster_p0, roster_p1, scenario, ruleset) → BattleState` (per `SZOP_Rozjemca.md pkt 7–13`)
  - `deployment_round(state, deployment_actions) → (BattleState, list[BattleEvent])` (pkt 13)
  - `activation_phase(state, action) → (BattleState, list[BattleEvent])` (pkt 11 + 14 + 17 + 18 + 20)
  - `round_end_phase(state) → (BattleState, list[BattleEvent])` (pkt 8.c — wszyscy `Aktywowani` resetują; pkt 21 Odzyskiwanie ran)
- [ ] Testy `tests/test_engine_phases.py`: setup z 2 rosters generuje sensowny `BattleState`; pełna runda działa deterministycznie; round_end resetuje statusy

### B3.7 — Resolver (top-level entry)

- [ ] `app/services/engine/resolver.py`: `apply(state, action, dice, ruleset, terrain) → (BattleState, list[BattleEvent])` — **pure function**, zero DB access; dispatcher: `Action` polimorficzny → `phases.activation_phase` lub `combat.resolve_*` lub specjalne handlery
- [ ] `Action` schema: `ActivateUnit | DeclareAction (Manewr/Obrona/Ostrzał/Szarża/SpecialAction) | AllocateWounds | InterruptResponse | ...`
- [ ] Testy `tests/test_engine_resolver.py`: idempotency (zastosowanie tej samej akcji 2× → drugi raz daje pustą listę eventów lub ValidationError, decyzja w trakcie); replay = identical eventy
- [ ] Promote ADR-0011 Proposed → **Accepted** z empirycznymi wnioskami z B3.1–B3.6

### B3.8 — Weryfikacja end-to-end

- [ ] `pytest -q` cały projekt: baseline 938 (z B0) + ~150–200 nowych z B3 modułów; bez regresji
- [ ] Parity gate Strumień A nieuszkodzona: `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` → 156/156; `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` → 93/93
- [ ] Smoke replay: zbuduj prosty `BattleState` z 2 rosters × 2 unit, zastosuj sekwencję 10 akcji, sprawdź event log + finalstate
- [ ] `make rules-check` (drift gate) — nie powinno się zmienić: B3 nie modyfikuje YAML
- [ ] Call-site check: każda funkcja `resolver.apply` / `phases.*` / `combat.*` ma test
- [ ] `docs/roadmap.md` — wszystkie checkboxy B3 ✅ + ADR-y 0011/0012/0015/0015a/0043/0044 ✓
- [ ] `docs/architecture.md` — sekcja "Game engine" z mapą `app/services/engine/` modułów (event-sourced data flow diagram)

## Pliki dotknięte

*(wypełni się w trakcie B3.0 → B3.7)*

## Hipotezy / pytania otwarte

- **Q1 (do decyzji userem przed B3.0.1):** Czy GATE audit (B3.0.1) odbywa się w tym sub-wątku, czy lepiej w osobnym mikrowątku `faza-b-3-gate-audit` żeby B3.0 było pure-implementation? **Rekomendacja:** zostaje w B3.0 — audit to mała 1-sesyjna praca (~50 zdolności aktywnych do sklasyfikowania w tabeli), wydzielanie sub-sub-wątku to overhead. Wynik (`build/b3_action_ability_audit.md`) jest informational, nie blokuje innych wątków.
- **Q2 (do decyzji userem):** Czy pełne B2 (ORM models + Alembic) leci równolegle w `faza-b-2-models`, czy odkładamy do startu B4 API? **Rekomendacja:** odłożyć — B3 testuje pure functions bez DB; ORM models i migration to ~2-3 sesje, zrobić tuż przed B4. Eliminuje konflikty plików między B2-ORM a B3-runtime.
- **H1 (do weryfikacji w B3.2):** Czy N=16 sampling punktów na okręgu celu daje akceptowalny false-positive rate (>95% accuracy vs analytic tangent na 30 hand-crafted scenarios)? **Plan B:** N=32 lub analytic tangent dla `TerrainCircle` z prostym wzorem geometrycznym.
- **H2 (do weryfikacji w B3.3):** Czy `expected_damage` analityczny daje wynik mean ±3σ w 95%+ Monte Carlo runs (100 scen × 1000 sym)? **Plan B:** uprościć formułę (pominąć rzadkie interakcje typu Porażenie ×2), lub przejść na Monte Carlo z fixed seed w prediction module.
- **H3 (do weryfikacji w B3.4):** Reactive window per ADR-0015a — jednorazowa, atomowa — czy `Strażnik` + `Kontratak` (pkt 14.d.iv) dają się złożyć bez kolizji semantycznych? **Plan B:** explicit priority ordering w `InterruptManager`.
- **H4 (do weryfikacji w B3.7):** `Action` polimorficzny w Pydantic — czy `discriminated union` (Pydantic v2 `Discriminator`) wystarcza, czy potrzebujemy własnej dispatch table?

## Jak zweryfikować

```powershell
# B3.0 preflight check
cat build/b3_action_ability_audit.md  # GATE pkt 3
python -c "from app.services.engine.state import UnitBlob, BattleState, compute_radius_inches; print(compute_radius_inches(15))"
python -c "from app.services.engine.events import MoveExecuted, event_to_json, json_to_event; e = MoveExecuted(unit_id=1, from_pos=(0,0), to_pos=(6,0), sequence=1); assert json_to_event(event_to_json(e)) == e"
python -m pytest tests/test_engine_state.py tests/test_engine_events.py -v

# Per moduł (B3.1-B3.7)
python -m pytest tests/test_engine_dice.py -v
python -m pytest tests/test_los_geometry.py -v
python -m pytest tests/test_prediction_vs_simulation.py -v
python -m pytest tests/test_engine_{combat,effects,interrupts,phases,resolver}.py -v

# End-to-end (B3.9)
python -m pytest -q  # baseline 938 + ~150-200 B3
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py  # 156/156
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml_backend/  # 93/93
make rules-check  # drift unchanged

# Smoke replay
python scripts/engine_smoke_replay.py  # NEW w B3.9 — minimal 2v2 battle replay
```

## Decyzje

- 2026-05-30: Sub-wątek `faza-b-3-executor` jako odgałęzienie `faza-b-engine-mvp`. Branch pozostaje `Faza_A` (zgodnie z parent).
- 2026-05-30: **GATE audit (ADR-0010a pkt 3) przesunięty z B0.W do B3.0.1.** Powód: B0 zamknięte deliverable-side (tables + exclusions + Pydantic + ADR-y), audit jest pre-implementation requirement dla B3 — naturalne miejsce w preflight executor. Nie wymaga otwierania B0 ponownie.
- 2026-05-30: **B3.0 dostarcza minimalne B2 substrate (runtime dataclasses + eventy + apply_events)**, NIE pełne ORM B2 (Battle/BattleEvent/BattleInvite/etc. + Alembic). Powód: executor pure-function nie potrzebuje DB do testów; pełne B2 ORM → osobny sub-wątek `faza-b-2-models` przed B4 API. Pliki nie kolidują (`state.py`/`events.py` w `app/services/engine/` vs `app/models.py` ORM).
- 2026-05-30: Plan B3 ma 8 etapów (B3.0–B3.7) + weryfikacja (B3.8). 6 nowych ADR-ów (0011, 0012, 0015, 0015a, 0043, 0044). ADR-0011 startuje jako Proposed, promote do Accepted po B3.7 z empirycznymi wnioskami.
- 2026-05-30: ADR-0010 (event-sourced) wymaga 8 event types — zaczynamy w B3.0.3 od full set (`MoveExecuted`, `ShotResolved`, `MeleeResolved`, `ModelKilled`, `MoraleTestPassed`, `EffectApplied`, `InterruptTriggered`, `RoundEnded`); jeśli któryś okaże się niepotrzebny w B3.7, pozostaje w schemacie z `__version__` (kompatybilność wstecz).

## Notatki / odkrycia w trakcie

- 2026-05-30: Sub-wątek utworzony. Parent `faza-b-engine-mvp` w stanie B0 done (commit `53de635`). ADR-y B0 wszystkie Accepted (0008, 0010, 0010a, 0014). GATE ADR-0010a status: 4/5 punktów ✅, pkt 3 (audit) ⏳ w B3.0.1. Sub-wątek `faza-b-2-models` celowo NIE otwarty teraz — czeka na potrzebę przed B4 API.
- 2026-05-30: Audyt sygnatur do napisania w B3.0.1: `SZOP_Zdolnosci.md` ma 77 zdolności (`grep -c "^### " ≈ 77`), z tego pasywnych ~60, aktywnych ~17. Aktywne mapują się na akcję 14.e (Akcja specjalna). Pasywne mapują się przez `EFFECT_REGISTRY` bez akcji.
- 2026-05-30: `app/services/engine/` katalog NIE istnieje jeszcze (zweryfikowane przed bootstrap sub-wątku). Pełna struktura zostanie utworzona w B3.0.2 + dotworzona per moduł w B3.1+.
- 2026-05-30 (post-B3.0): **B3.0 zamknięte.** `app/services/engine/` powstał z `__init__.py` + `state.py` + `events.py`. Audit B3.0.1 wykazał że abilities.yaml ma **12** aktywnych zdolności (różnica od MD: 5 dodanych w Rozwoj YAML sync: koordynacja, mobilizacja, presja, przekaznik, przepowiednia). Wszystkie 12 sklasyfikowanych: 6× akcja w aktywacji (14.e), 6× przerwanie (pkt 12). Pytest 998/998 (962 baseline + 36 nowych z test_engine_state + test_engine_events). GATE ADR-0010a → **OPEN**. B3.1 dice w następnej sesji.
- 2026-05-30 (post-B3.1): **B3.1 dice zamknięte.** `app/services/engine/dice.py` (~110 LOC) + `RollResult` frozen + dokładnie zaszyte 4 reguły z pkt 1 (a-d) + flagi dla Brutalny/Delikatny. 24 nowe testy zielone (reproducibility, distribution chi-square, threshold semantics, modifier clamp). ADR-0012 Accepted. Pytest 1022/1022 (998 baseline + 24 nowych). Logika konkretnych zdolności (Furia, Niewrazliwy, Podwójny) deferred do `combat.py`/`effects.py` (B3.4-B3.5) — `RollResult.rolls` preserves natural values for inspection. Następny krok: B3.2 LoS (3-state).
- 2026-05-30 (post-B3.2): **B3.2 LoS zamknięte.** `app/services/engine/los.py` (~210 LOC) — `check_los` z sampling N=16, attacker edge point + N target points na obwodzie celu, segment-vs-circle / segment-vs-segment intersection, Zasłaniający exception pkt 4.c.iii. 43 nowe testy (geometry primitives 12, Blokujący 4, Zasłaniający 5, multi-terrain 2, non-blocking 3, edge cases 4, enum 2, realistic 2 — plus integration). ADR-0043 Accepted (N=16 Pareto sweet spot, plan B N=32/analytic). Pytest 1065/1065. Następny krok: B3.3 prediction (analytic expected_damage, no RNG).
- 2026-05-30 (post-B3.4): **B3.4 combat zamknięte (uproszczone — pojedyncze ranged/melee bez Szarży/kontrataku).** `app/services/engine/combat.py` (~430 LOC) z WeaponProfile + CombatResult, resolve_ranged_attack i resolve_melee_attack jako pure functions; compute_cover/attack_modifiers/defense_modifier helpers; _allocate_wounds_to_defender z prefer_hero. Weapon abilities MVP: AP(X)/Brutalny/Precyzyjny. UnitBlob rozszerzony o quality+defense (backward compat). 37 nowych testów. ADR-0015a Accepted (reactive window framework gotowy, konkretne zdolności w B3.5). Pytest **1102/1102** (1065 + 37). Następny krok: **B3.5 effects + interrupts** (passive abilities + InterruptManager + Strażnik + kontratak/Kontra). **Alternatywa: B3.3 prediction** (analytic expected_damage, używa same logic co combat ale bez RNG) — może być teraz pisany lub po B3.5.
