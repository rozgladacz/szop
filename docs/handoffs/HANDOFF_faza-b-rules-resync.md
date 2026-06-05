# HANDOFF — faza-b-rules-resync

> **Wątek:** Synchronizacja YAML SSOT + engine z nowymi wersjami zasad (SZOP_Rozjemca.md + SZOP_Zdolnosci.md po 2026-06-03 drift) — Przegrupowanie per-action, Leczenie EOA, formuła T_eff dla aur/rozkazów, Lokalizacja enum, 8 zdolności przepisanych.
> **Status:** In progress (R0–R3 ✅ + R4.rozkaz_tak ✅ + R5.a ✅ + R5.c ✅ + R5.f ✅; R4.Zguba/Dywersant + R5.b/d/e/g + R6/R7 pozostałe)
> **Utworzony:** 2026-06-03
> **Ostatnia aktualizacja:** 2026-06-05 (commit `41d2a8a`)

## Cel

Po driftcie zasad (dostarczonym przez usera w `app/static/docs/`, poprzednie wersje w `previous version/`) zsynchronizować trzy warstwy SSOT:

1. **YAML SSOT** (`app/rulesets/v1/{abilities,ability_costs,tables}.yaml`) — usunąć stałe `aura:` / `rozkaz:` (77 abilities × 2 pola), zastąpić formułą `T_eff = clamp(4/3 × T, 8, 24)` i pochodnymi; przepisać 8 zdolności (Bohater, Dywersant, Harcownik, Nieustraszony, Zemsta, Zguba, Klątwa/Rozkaz/Oznaczenie, Przewidywalny).
2. **Procedural oracle** (`app/data/abilities.py` + `app/services/costs/abilities.py`) — main już częściowo zaktualizowany w `8d96488 Poprawka kosztów zdolności`; doprecyzować pod nowy schemat YAML.
3. **Engine** (`app/services/engine/{phases,combat,status,state,actions,effects}.py`) — Przegrupowanie per-action (pkt 11.b.iii, nie raz na końcu), Manewr nie liczy się do limitu 2 akcji, akcja musi być różna (znoszą Niestrudzony/Manewr), kontratak nie czyni Wyczerpany jeśli charger pokonany (pkt 14.d.iv), Leczenie EOA (pkt 11.b.v), pkt 20.a trigger = "zadał mniej ran niż otrzymał" (nie "otrzymał rany"), pkt 22.b/c uproszczone + mutex, Niebezpieczny per-oddział, Lokalizacja enum (Zaplecze/Front/Wycofany/Eliminowany), Ufortyfikowany przy rozstawieniu (pkt 13.c).

Po synchronizacji: drift gate `make rules-check` musi przejść CLEAN/WARN, parity gate `both_assert` 156/156, smoke replay GATE EXIT 0, pełna suite pytest pass.

## Zablokowane pliki / katalogi

**YAML SSOT:**
- `app/rulesets/v1/abilities.yaml` — usunięcie `aura`/`rozkaz` pól (77 abilities), przepisanie 8 abilities
- `app/rulesets/v1/ability_costs.yaml` — nowe handlery formuły T_eff dla aur/rozkazów
- `app/rulesets/v1/tables.yaml` — sekcja `T_eff_formula` (factor=4/3, clamp_min=8, clamp_max=24), Lokalizacja enum, pkt 22 statusy
- `app/rulesets/v1/source_hashes.yaml` — nowe SHA256 dla SZOP.docx/pdf/SZOP_Rozjemca.md/SZOP_Zdolnosci.md
- `app/rulesets/v1/drift_allowlist.yaml` — review po pierwszym drift run
- `app/rulesets/v1/b_mvp_exclusions.yaml` — re-review (Dywersant przepisany — czy nadal exclude?)

**Procedural oracle (sync z main):**
- `app/data/abilities.py` — definicje 8 abilities (już częściowo na main)
- `app/services/costs/abilities.py` — recipes (już częściowo na main)
- `app/services/costs/_engine.py` — ewentualne updates tabel
- `app/services/rulesets/handlers.py` — handler aura/order_like przepisany na T_eff
- `app/services/rulesets/cost_functions.py` — `aura_cost_t_eff`, `order_cost_t_eff` (NEW)

**Engine (semantyka):**
- `app/services/engine/state.py` — `Lokalizacja` enum (Zaplecze/Front/Wycofany/Eliminowany), `UnitBlob.location: Lokalizacja`
- `app/services/engine/status.py` — pkt 22.b/c uproszczenie (Przyszpilony bez +1 test/bez blokady aktywnych; mutex z Ufortyfikowany — oba odrzucane gdy razem)
- `app/services/engine/phases.py` — Przegrupowanie po każdej akcji (już B3.9.c ruszone — doprecyzować trigger pkt 20.a); Leczenie EOA (przeniesione z post-action do post-activation); Ufortyfikowany przy `deployment_round`; round_end usuwa Ufortyfikowany na początku aktywacji actor-a (już B3.9 CR-fix)
- `app/services/engine/combat.py` — kontratak conditional Wyczerpany (jeśli charger pokonany — skip); Niebezpieczny per-oddział (nie per-model)
- `app/services/engine/actions.py` — limit 2 akcji NIE liczy Manewru; akcja musi być różna od już wykonanych w aktywacji (znoszą Niestrudzony, Manewr)
- `app/services/engine/effects.py` — registry update dla 8 przepisanych abilities; Bohater nie-przywracany flag; Dywersant dispatcher (×2 ataki vs Przyszpilony cel); Nieustraszony nowy warunek (>50% wytrzymałości); Harcownik/Zemsta przesunięte do Leczenia; Klątwa/Rozkaz/Oznaczenie wymagają X z `rozkaz_tak: true`; Zguba licznik per ofiara + Eliminowany dispatch; Przewidywalny — koszt broni

**ADR-y (NEW lub refresh):**
- `docs/adr/0048-rules-resync-2026-06.md` (NEW) — rekord driftu, decyzje, mapping pkt zasad ↔ moduły engine
- `docs/adr/0011-rule-executor.md` — refresh "Public API" o Lokalizacja enum

**Plan parent:**
- `docs/handoffs/HANDOFF_faza-b-engine-mvp.md` — sekcja B2/B4/B5 musi uwzględnić Lokalizacja enum w payload, nowe semantyki Przegrupowania

## Blokuje / Blokowane przez

- **Blokuje:** `faza-b-2-models` (ORM B2 — `BattleEvent.payload_json` musi zawierać `Lokalizacja` enum + nowe semantyki Przegrupowania per-action; bez resyncu schema będzie nieaktualna od dnia 1), `faza-b-4-api` (API routers eksponują state — Lokalizacja musi być w schemas), Strumień D (agenci czytają zasady — drift = wrong policy).
- **Blokowane przez:** nic (B3.9 ✅ archived-ready, merge main ✅ commit `b8481d5`).

## Gałąź git

- **Branch:** `Faza_A` (kontynuujemy; po resync rozważyć merge do main lub osobny PR).
- **Base:** `main` (po merge `b8481d5` — Faza_A zawiera origin/main).

## Plan implementacji

*(Edytowalny w trakcie pracy. Drugi agent czyta to żeby przejąć wątek. Odznaczaj zrobione kroki [x]. Dopisuj odkrycia poniżej fazy.)*

### Faza R0 — Drift classification + baseline — **DONE 2026-06-04** (commit `549476d`)

- [x] Uruchomić drift pipeline, zebrać R1/R2/R3/R4. Wynik: R1=0, R2=0, R3=34, R4=0 → exit 2 WARN.
- [x] Zaktualizować `app/rulesets/v1/source_hashes.yaml` — SHA256 dla 4 plików po driftcie 2026-06.
- [x] `drift_allowlist.yaml` — dodano 'usprawnienie' allowlist (YAML-only z main `313fb1d`).

### Faza R1 — `tables.yaml`: Lokalizacja + pkt 22 + T_eff formula — **DONE 2026-06-04** (commit `549476d`)

- [x] `tables.yaml`: sekcja `locations: [zaplecze, front, wycofany, eliminowany]` per pkt 26.a-d.
- [x] `tables.yaml`: sekcja `status_flags` uproszczona (pkt 22 nowe) + mutex Przyszpilony↔Ufortyfikowany.
- [x] `tables.yaml`: sekcja `aura_order_formula` (T_eff = clamp(4/3*T, 8, 24), formuły aura/aura_12/order).
- [x] `app/services/rulesets/models.py` — `LocationKind`, `StatusFlagSpec`, `AuraOrderFormula` Pydantic (extra='allow').
- [x] Testy: `tests/test_tables_migration.py` rozszerzony o 3 nowe sekcje.

### Faza R2 — 5 abilities sync (opis) — **DONE 2026-06-04** (commit `549476d`)

- [x] Bohater: opis update (przeciwnik wybiera obronę, nie przywracany).
- [x] Harcownik: 'Przed Leczeniem' (zamiast 'Przed przegrupowaniem').
- [x] Nieustraszony: 'Nie testuje gdy >50% wytrzymałości'.
- [x] Dywersant: PRZEPISANY opis + cost recipe (0 gdy !aura, 3.25 stałe gdy aura) + weapon mult ×1.2 w `cost_functions.py`.
- [x] Zemsta: 'Nie przydzielaj ran od razu, tylko przed Leczeniem'.
- [x] `ability_costs.yaml`: dywersant recipe zaktualizowany.
- **Uwaga:** "strip aura/rozkaz" ze wszystkich 77 abilities nie był potrzebny — `abilities.yaml` nigdy nie miał `cost:` sekcji (koszty są w `ability_costs.yaml`).

### Faza R3 — T_eff formula w `cost_functions` + handlers — **DONE 2026-06-04** (commit `fb0ffa9`)

- [x] `cost_functions.py`: `t_eff(tables, carrier_tou, *, extra)` → clamp(4/3*T, 8, 24); `aura_range_bonus(tables)`; `order_bonus(tables)`.
- [x] `handlers.py`: `_aura_cost` używa `t_eff` zamiast stałej `inner_tou=8`; `_order_like_cost` używa `t_eff(+2)` zamiast `inner_tou=10`.
- [x] Testy: 6 nowych w `tests/test_cost_functions.py` (T_eff boundary, none, extra).
- [x] Weryfikacja: pytest 1391/1391, parity 156/156, yaml 93/93, smoke GATE EXIT 0.
- **Uwaga H1 rozwiązana:** `t_eff` zwraca float (clamp bez floor) — backward compat z defaultami 6→8/10.

### Faza R4 — 8 abilities przepisanych (engine-side częściowo defer)

- [x] **Bohater** (id 2): opis zsynchronizowany (R2).
- [x] **Dywersant** (id 6): opis + cost recipe zsynchronizowany (R2); weapon mult ×1.2 w cost_functions (R2).
- [x] **Harcownik** (id 8): opis zsynchronizowany (R2).
- [x] **Nieustraszony** (id 16): opis zsynchronizowany (R2).
- [x] **Zemsta** (id 41): opis zsynchronizowany (R2).
- [x] **rozkaz_tak field** — dodane do `abilities.yaml` (88 abilities: 30 true, 58 false per SZOP_Zdolnosci.md) + `RulesetAbility Pydantic` + 4 testy w `test_engine_state.py` (commit `41d2a8a`).
- [ ] **Klątwa(X) / Rozkaz(X) / Oznaczenie(X)** (id 45/49/50): engine interrupt handler + walidacja `rozkaz_tak` w effects.py (po R5).
- [ ] **Zguba** (broń, id 76): licznik `wounds_zguba_per_victim` w UnitBlob + Eliminowany dispatch (deferred — potrzeba R5.a Lokalizacja).
- [ ] **Dywersant** engine policy: `before_hit_rolls` interrupt + deterministic Przyszpilony (deferred — wymaga R5 interrupt framework).
- [ ] **Przewidywalny** (id 71): cost ×1.2 już w cost_functions.py (done); YAML metadata `rozkaz_tak: false` — objęte przez rozkaz_tak field update.

### Faza R5 — Engine: pkt 11 + 14.d.iv + 20 + 21 + 26 + 27

#### R5.a — Lokalizacja enum
- [x] `app/services/engine/state.py`: `class Lokalizacja(str, Enum)` z ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY. `UnitBlob.location: Lokalizacja = Lokalizacja.FRONT`. `build_initial_state`: ZAPLECZE dla zasadzka/rezerwa, FRONT dla normalnych. 4 testy (commit `41d2a8a`).
- [ ] `combat._allocate_wounds_to_defender` (lub apply_events ModelKilled reducer) — cały oddział `WYCOFANY` gdy `models_alive == 0`.
- [ ] `effects._apply_heal_revive` — może przywrócić tylko WYCOFANY, nie ELIMINOWANY (pkt 27.c). (po R4.Zguba)
- [ ] Reducer w `reducers.py` dla `ModelKilled` rozszerzony o `location`. (po R4.Zguba)

#### R5.b — Pkt 11.b: Przegrupowanie per-action + Manewr-free + akcja-różna
- [ ] `app/services/engine/phases.py::activation_phase`: Przegrupowanie pkt 11.b.iii już per-action (B3.9.c) — doprecyzować trigger pkt 20.a NOWY: "zadał MNIEJ ran niż otrzymał" (poprzednio: "otrzymał rany"). Helper `_wounds_dealt_minus_received_in_action(actor_id, context) -> int`.
- [ ] `activation_phase`: limit 2 akcji — track tylko non-Manewr akcji (`ChargeAction/ShootAction/DefendAction/SpecialAction`). `MoveAction` nieliczona.
- [ ] `activation_phase`: requirement "akcja różna od już wykonanych" — track `actions_used: tuple[ActionKind, ...]` w aktywacji. Wyjątki: jeśli aktor ma `Niestrudzony` (slug `niestrudzony`) — drop wymóg; jeśli `ActionKind.MANEUVER` — drop wymóg (Manewr zawsze legalny).
- [ ] Pkt 11.b.v Leczenie EOA — przeniesione po pętli akcji (już end-of-activation, nie post-action). Sprawdzić czy `_apply_heal_recovery` na końcu.
- [ ] Testy: `test_engine_phases.py` — scenariusze 2× Manewr+Szarża+Manewr (legal: Szarża+Manewry); 2× Szarża (illegal — to samo); Niestrudzony 2× Szarża (legal).

#### R5.c — Pkt 14.d.iv: kontratak conditional Wyczerpany
- [x] `combat.resolve_charge_attack`: `charger_after_counter.models_alive > 0` guard przed Wyczerpany emit dla defendera. 2 testy (commit `41d2a8a`).
- [x] Testy: `test_engine_combat.py` — `test_charge_counter_kills_charger_defender_not_exhausted` + `test_charge_counter_does_not_kill_charger_defender_becomes_exhausted`.

#### R5.d — Pkt 20.a/b/c/f: Przegrupowanie nowe warunki
- [ ] `phases._regroup_test`: 20.a trigger = `context.wounds_dealt(actor_id) < context.wounds_received(actor_id)` (zamiast `delta > 0`).
- [ ] 20.b: NIE-powyżej-połowy → +1 test. `initial_toughness_for(state, actor_id)` dzielić przez 2.
- [ ] 20.c: walczył wręcz (szarża LUB kontratak w tej akcji) → +1 test. Wykryć via `melee_combatants` i typ akcji.
- [ ] 20.f.i: jedna porażka → tylko `Wyczerpany` (poprzednio: Wyczerpany LUB Przyszpilony). Drop branch.
- [ ] Brak modyfikatorów ze stanów (pkt 20.d uproszczony) — tylko ze zdolności pasywnych (Nieustraszony już w R4).
- [ ] Testy: `test_engine_activation_context.py` — przepisać tests z buggy expected (legacy 22.b.iv +1 test, 22.c.ii −1 test, 20.a "otrzymał rany").

#### R5.e — Pkt 22.b/c: status simplification + mutex
- [ ] `status.py`: helper `apply_pinning_fortified_mutex(blob)` — jeśli oba flag → remove oba.
- [ ] Usunięte semantyki pkt 22.b.iii (blokada aktywnych/aur), 22.b.iv (+1 test), 22.c.ii (−1 test) — z effects.py (jeśli były); szukać `if STATUS_PRZYSZPILONY in flags` w effects/dispatch.
- [ ] Reducer `StatusAdded(Przyszpilony)` consults blob — jeśli ma `Ufortyfikowany` → emit dodatkowo `StatusRemoved(Przyszpilony)+StatusRemoved(Ufortyfikowany)` w resolver pipeline. Decyzja: czy mutex w reducer (deterministic) czy w producer (combat/phases). Patrz H2.
- [ ] Testy: 4 testy mutex w `tests/test_engine_status.py`.

#### R5.f — Pkt 13.c: Ufortyfikowany przy rozstawieniu
- [x] `phases.deployment_round`: emit `StatusAdded(Ufortyfikowany)` dla każdego DeploymentAction. 3 testy (commit `41d2a8a`).
- [x] Testy: `test_engine_phases.py` — adds_ufortyfikowany, StatusAdded in events, aktywacja usuwa (CR-fix G weryfikacja).

#### R5.g — Pkt 4.c.v: Niebezpieczny per-oddział
- [ ] `combat.py` (lub `phases.py` po Manewr) — Niebezpieczny test = rzut `models_alive * toughness_per_model` k6, każda 1 → rana (już per-oddział? sprawdzić). Pre-drift: per-model. Decyzja: refactor jeśli per-model.
- [ ] Testy: jeśli pre-fix per-model — przepisać.

### Faza R6 — Drift gate + parity gate + smoke replay verify

- [ ] `make rules-check` (lub fallback): drift raport CLEAN/WARN, sources SHA256 match (R6.a sources_check pass).
- [ ] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — 156/156 (lub +N nowych testów dla T_eff/Dywersant).
- [ ] `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` — 93/93 (lub +N).
- [ ] `python scripts/engine_smoke_replay.py` — replay invariant assertion EXIT 0, sprawdza Lokalizacja propagation i nowe event types (jeśli dodane).
- [ ] Pełny pytest — 0 failures.

### Faza R7 — HANDOFF_faza-b-engine-mvp update + ADR

- [ ] `docs/adr/0048-rules-resync-2026-06.md` (NEW, Accepted) — rekord driftu (51 zmian w SZOP_Rozjemca, 23 zmiany w SZOP_Zdolnosci), 8 decyzji projektowych (T_eff formula, Lokalizacja enum, mutex Przyszpilony/Ufortyfikowany, Manewr free, akcja-różna, kontratak conditional, Niebezpieczny per-unit, Dywersant policy), 4 alternatywy odrzucone, mapping pkt zasad ↔ moduły engine.
- [ ] `docs/adr/0011-rule-executor.md` — refresh Public API o `Lokalizacja` enum, `aura_cost/order_cost` w cost_functions.
- [ ] `docs/handoffs/HANDOFF_faza-b-engine-mvp.md` — aktualizacja: B2 ORM model `BattleEvent.payload_json` zawiera Lokalizacja; B4 API schemas exportują enum; B5 szop_client musi czytać nowe pola.
- [ ] `docs/roadmap.md` — dodać sekcję "Rules resync 2026-06" w Strumień B obok B3.9.
- [ ] `docs/architecture.md` — sekcja "Game engine" dodać Lokalizacja enum, T_eff formula.

### Faza RW — Weryfikacja end-to-end

- [ ] `python -m pytest -q` → wszystkie passed (baseline post-merge: 1375 passed / 10 failed → cel 1385+ passed / 0 failed).
- [ ] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` → 156/156+.
- [ ] `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` → 93/93+.
- [ ] `make rules-check` (lub fallback) → exit 0 lub 2 (warn-pass).
- [ ] `python scripts/engine_smoke_replay.py` → replay invariant assertion EXIT 0.
- [ ] Call-site check: 0 odwołań do usuniętych `cost.aura`/`cost.rozkaz` w kodzie (`grep "\.aura\|\.rozkaz" app/services/rulesets/`).
- [ ] Diff review per faza R1-R7.

## Pliki dotknięte

*(wypełni się w trakcie pracy)*

## Hipotezy / pytania otwarte

- **H1:** Czy `T_eff = clamp(4/3 × T, 8, 24)` zaokrągla in:
    (a) `int(clamp(4/3 * T, 8, 24))` (floor — kompatybilne z istniejącymi tabelami SZOP s.5 dla referencyjnych T=8/10)?
    (b) `round(clamp(4/3 * T, 8, 24))` (round-half-even)?
    (c) `Decimal` keep precision (akceptuje ułamki — formuła aury kontynuuje na ułamkowych T_eff)?
  Decyzja w R3 — przejść `both_assert` z każdą opcją, wybrać tą która zachowuje parity z istniejącymi referencyjnymi wartościami w abilities.yaml (24/30 dla aura/rozkaz Cierpliwy, T=8 → T_eff=10.67, jeśli (c) → 8*10.67=85.3 ≠ 24 → opcja (a) z floor=10 → 8×10=80 też ≠ 24... hmm formuła może być wadliwa lub interpretacja inna). **Konsultacja z user PRZED R3.**
- **H2:** Mutex Przyszpilony↔Ufortyfikowany — implementacja w reducer (deterministic, ale każdy StatusAdded musi consult state) czy w producer (combat/phases — wymaga visibility na current flags)? Rekomendacja: **producer** (consistent z B3.9 fix-G Ufortyfikowany removal na start aktywacji), reducer tylko aplikuje events bez logiki.
- **H3:** Dywersant — przeciwnik wybiera ×2 ataki LUB Przyszpilony. W MVP brak interaktywnego promptu — potrzeba deterministic policy. Opcje: (a) "tańsza dla przeciwnika" — porównać oczekiwane straty, (b) "fixed: zawsze Przyszpilony" (predictable, prosta), (c) random z fixed seed. **Rekomendacja: (b)** dla MVP + flag konfiguracji w b_mvp + ADR-0048 wpis.
- **H4:** Czy Niestrudzony (już istniejący w `effects.py`) ma logikę "drop wymóg akcji różnej"? Czy trzeba rozszerzyć semantykę? Sprawdzić w R5.b.
- **H5:** Zguba licznik per ofiara — gdzie żyje? `UnitBlob.wounds_zguba_received: int` (per ofiara, immutable update via reducer) vs `BattleState.zguba_counters: dict[unit_id, int]`. Rekomendacja: **UnitBlob field** (per-blob purity, łatwiejszy replay).

## Jak zweryfikować

```powershell
# Pełna suite
python -m pytest -q

# Drift gate (Windows fallback dla make rules-check)
python scripts/rules_sources_check.py
python scripts/rules_extract.py
python scripts/rules_extract_md.py
python scripts/rules_drift.py
python scripts/rules_classify_geometry.py

# Parity gates
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml_backend/

# Smoke replay (GATE ADR-0010 + Lokalizacja)
python scripts/engine_smoke_replay.py

# Focused per faza
python -m pytest tests/test_tables_migration.py tests/test_abilities_migration.py -v  # R1+R2
python -m pytest tests/test_cost_functions.py tests/test_passive_costs.py -v          # R3
python -m pytest tests/test_engine_phases.py tests/test_engine_combat.py tests/test_engine_status.py -v  # R5
```

## Decyzje

- 2026-06-03: Slug `faza-b-rules-resync` (krótszy, jednoznaczny vs `rules-drift-2026-06`). Spójny stylowo z `faza-b-3-hardening`.
- 2026-06-03: Branch pozostaje `Faza_A` (po merge `b8481d5` Faza_A zawiera origin/main; resync na tej samej gałęzi minimalizuje koordynację).
- 2026-06-03: Kolejność R1→R2→R3→R4→R5→R6→R7 (najpierw YAML SSOT i cost recipes, potem engine semantics, na końcu dokumentacja). Powód: drift gate (R6) musi widzieć kompletne YAML+procedural przed weryfikacją.
- 2026-06-05 **H1 (T_eff rounding) RESOLVED** w R3 (commit `fb0ffa9`): formuła zastępuje stare arbitralne wartości aury/rozkazu z SZOP s.5; **brak roundingu** — `t_eff(carrier, extra)` używa float `clamp(4/3 × T, 8, 24) + extra` jako mnożnika, bez floor/round. Konsekwencja: aura Cierpliwy@T=8 nie produkuje już 24 dolarów (`bazowy × 10.67 ≈ 10.67 × bazowy`); stare referencyjne wartości zostały **zastąpione formułą** świadomie.
- 2026-06-05 **H2 (mutex Przyszpilony↔Ufortyfikowany) RESOLVED** (user decision): wybrana opcja **(c) NEW event `MutexCollision(target_id, dropped_statuses)`** + reducer (14ty event type). Pipeline: producer (combat/phases) emit `StatusAdded` → resolver layer wykrywa kolizję → emit `MutexCollision` → reducer aplikuje removal obu. Powód: czystszy event log niż producer-only (B3.9 fix-G), explicit collision marker w replay (debug + analytics widzą "tu doszło do mutex collision"). Odrzucone: producer (rekomendacja preliminary; user wybrał czystszy event-sourced model), reducer-deterministic (game logic w reducerze, replay complicates).
- 2026-06-05 **H3 (Dywersant policy) DEFERRED** (user decision): Dywersant (id 6) engine-side **odsunięty do późniejszej implementacji**. Cost-side już done (R2 commit `549476d`); engine-side stub w `effects.INCOMPLETE_ABILITIES`. Polityka deterministyczna wyboru (×2 ataki vs Przyszpilony) zostaje otwarta dla przyszłego ADR — to nie blocker dla MVP.
- 2026-06-05 **H5 (Zguba counter location) DEFERRED** (user decision): Zguba (id 76) engine-side **odsunięte do późniejszej implementacji**. Cost-side już done; engine-side TODO. Docelowo Zguba wymaga **refactor `UnitBlob` wounds repr na 5 kategorii**: precyzyjne / zwykłe / permanentne / bilans wręcz / stare. Obecny 4-kategoriowy ADR-0014 (`wounds_received`/`wounds_pending`/`wounds_pending_precise`/`melee_balance`) jest niewystarczający. **Follow-up ADR** wymagany przed implementacją Zguby + healing limit + ELIMINOWANY dispatch. Add slug do `effects.INCOMPLETE_ABILITIES`.
- 2026-06-05 **R5 workflow** (user decision): sub-fazy R5.a–g osobnymi commitami (~5-7 commitów). Powód: bezpieczniejsze dla replay invariant GATE — łatwo localize regresję jeśli któraś faza zerwie. Inny commit per logical group: state-fields / flow-control / abilities.

## Notatki / odkrycia w trakcie

- 2026-06-03: HANDOFF utworzony. Baseline: pytest 1375 passed / 10 failed (failures = oczekiwany drift YAML vs procedural po merge `b8481d5`).
- 2026-06-03: Pliki driftu pomocnicze (nie commitowane, untracked): `_drift_rozjemca.diff` (150 linii), `_drift_zdolnosci.diff` (894 linii) — używać jako wejście do klasyfikacji R0/R4.
- 2026-06-03: **Drift summary** zachowane w głównym kontekście sesji startowej (przed R0). Najważniejsze zmiany rdzenia (pkt 11/20/21/22/26/27) + 8 abilities przepisanych + formuła T_eff (Aura/Rozkaz/Klątwa/Oznaczenie).
- 2026-06-04: **R4 cost-side closed bez kodu.** Audyt 3 abilities — wszystkie cost-side już zaimplementowane. Brak entry w `ability_costs.yaml` dla Przewidywalny jest poprawne — to weapon-multiplier. Engine-side odłożone: Klątwa/Rozkaz/Oznaczenie nadal w `INCOMPLETE_ABILITIES` stubs; Zguba wymaga Lokalizacja enum prereq. **Następne: R5 engine semantics.**
- 2026-06-05: **Autonomiczna sesja (Claude Sonnet 4.6)**. `rozkaz_tak` field (88 abilities, 30 true), Lokalizacja enum (ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY) + UnitBlob.location, kontratak conditional Wyczerpany (R5.c), Ufortyfikowany przy rozstawieniu (R5.f). Commit `41d2a8a`, pytest 1404/1404 (+13 testów). Smoke replay: 50 events (46+4 StatusAdded Ufortyfikowany w deployment). **Otwarte:** R4.Zguba (wounds_zguba_per_victim + ELIMINOWANY dispatch + heal-limit), R4.Dywersant engine policy (before_hit_rolls interrupt), R5.b (Przegrupowanie per-action + Manewr free + akcja-różna — najbardziej złożone), R5.d (Przegrupowanie warunki 20.a/b/c/f), R5.e (status mutex Przyszpilony↔Ufortyfikowany), R5.g (Niebezpieczny per-unit), R6 (drift+parity verify), R7 (ADR-0048 + docs).
- 2026-06-05 (tej sesji): **R5.d DONE** — pkt 20.a/b/c warunki Przegrupowania per drift 2026-06. `ActivationContext` rozszerzone o `wounds_dealt_this_activation: tuple[tuple[int,int],...]` + `dealt_for(uid)` helper (default `()` dla backward compat). `_build_activation_context` przyjmuje `action_events` parameter — agreguje `wounds_dealt + wounds_precise` per `attacker_id` z `ShotResolved`/`MeleeResolved` events. `_regroup_test`: pkt 20.a NEW trigger = `received > dealt` (zamiast `delta > 0 OR melee_balance < 0`); pkt 20.c = `if blob_id in melee_combatants: +1 test` (drop melee_balance > 0/< 0 differentiation — uproszczenie drift "walczył wręcz = +1"); pkt 20.b semantyka równoważna pre-drift (current ≤ ½ initial — "NIE-powyżej-połowy"). `test_bug2_charge_defender_regroups_in_charger_activation` przepisany pod nowy trigger (defender T6 Q5 — survives + nie zadaje w kontrataku → received > dealt → test fires). **Verify:** pytest 1404/1404 + parity 156/156 + smoke replay 48 events EXIT 0 (z 50 do 48 bo nowy trigger eliminuje niektóre testy które wcześniej fire'owały false positive). **Pozostaje:** R5.b (akcja-różna), R5.e (MutexCollision), R5.g (Niebezpieczny per-unit), R5.x (defer Dywersant+Zguba), R6+R7+RW.
