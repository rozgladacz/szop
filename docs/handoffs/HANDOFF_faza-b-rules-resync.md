# HANDOFF — faza-b-rules-resync

> **Wątek:** Synchronizacja YAML SSOT + engine z nowymi wersjami zasad (SZOP_Rozjemca.md + SZOP_Zdolnosci.md po 2026-06-03 drift) — Przegrupowanie per-action, Leczenie EOA, formuła T_eff dla aur/rozkazów, Lokalizacja enum, 8 zdolności przepisanych.
> **Status:** In progress (R0–R3 ✅ + R4.rozkaz_tak ✅ + R5.a[WYCOFANY pkt 27.b: rany+morale ✅]/c/d/e/f/g ✅ + R5.g findings #1/#3 ✅; R5.b skip[H4]; **H5 RESOLVED 2026-06-07** → R4.Zguba+ELIMINOWANY ODBLOKOWANE [`wounds_eliminating` licznik, do implementacji]; Dywersant defer[H3]; **R6 ✅ 2026-06-07**; **R4.Zguba + Klątwa/Rozkaz/Oznaczenie + R7/RW pozostałe**)
> **Utworzony:** 2026-06-03
> **Ostatnia aktualizacja:** 2026-06-07 (R6 done — wszystkie gates pass: 1428/1428 pytest, 156/156 both_assert, 93/93 yaml, smoke GATE OK, sources CLEAN, drift WARN exit 2; merge Faza_A→main)

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
- [ ] **Zguba** (broń, id 76): **ODBLOKOWANE — H5 RESOLVED 2026-06-07.** Dodać `UnitBlob.wounds_eliminating: int = 0` (dodatkowy licznik, NIE pula alokacji). Implementacja:
    - Broń Zguba (`ABILITY_ZGUBA` w `weapon.weapon_abilities`): w `combat.resolve_*` po obliczeniu zadanych ran zadaj je normalnie do precise/regular ORAZ `defender.wounds_eliminating += wounds_dealt + wounds_precise`.
    - `_allocate_wounds_to_defender`: przy każdym `ModelKilled`, jeśli `wounds_eliminating` pokrywa rany pokonujące model (licznik > 0 w momencie pokonania) → `ModelKilled(eliminated=True)` + `location=ELIMINOWANY` zamiast WYCOFANY przy ostatnim modelu; dekrementuj `wounds_eliminating` o liczbę faktycznie zaalokowanych ran (nigdy poniżej 0).
    - Mirror w `reducers._reduce_model_killed` + nowe pole w `ModelKilled` event (`eliminated: bool`) → replay bit-perfect. `wounds_eliminating` dodać do `_BLOB_REPLAY_FIELDS`.
    - `effects._apply_heal_revive` (niżej): tylko WYCOFANY wraca, ELIMINOWANY nie (pkt 26.d).
- [!] **Dywersant** engine policy: `before_hit_rolls` interrupt + deterministic Przyszpilony (deferred do post-MVP backlog — wymaga R5 interrupt framework + policy decision).
- [ ] **Przewidywalny** (id 71): cost ×1.2 już w cost_functions.py (done); YAML metadata `rozkaz_tak: false` — objęte przez rozkaz_tak field update.

### Faza R5 — Engine: pkt 11 + 14.d.iv + 20 + 21 + 26 + 27

#### R5.a — Lokalizacja enum
- [x] `app/services/engine/state.py`: `class Lokalizacja(str, Enum)` z ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY. `UnitBlob.location: Lokalizacja = Lokalizacja.FRONT`. `build_initial_state`: ZAPLECZE dla zasadzka/rezerwa, FRONT dla normalnych. 4 testy (commit `41d2a8a`).
- [x] **(2026-06-06)** `combat._allocate_wounds_to_defender` + `reducers._reduce_model_killed` — cały oddział `WYCOFANY` gdy `models_alive == 0` (pkt 27.b, domyślny przypadek; ELIMINOWANY/Zguba odłożone do R4.Zguba). `location` dodane do `_BLOB_REPLAY_FIELDS` → replay invariant teraz weryfikuje propagację. +3 testy (2 combat producer + 1 replay integration). Ścieżka terenu (phases→`_allocate_wounds_to_defender`) pokryta automatycznie.
- [x] **(2026-06-07)** Ścieżka pokonania przez morale (pkt 20.f.iii 'broken') → `WYCOFANY` w `phases._regroup_test` + mirror `reducers._reduce_morale_test` (follow-up z review 2026-06-07). +2 testy. Niezmiennik "pokonany → WYCOFANY" pokrywa teraz rany + morale (ELIMINOWANY/Zguba nadal R4.Zguba).
- [ ] `effects._apply_heal_revive` — może przywrócić tylko WYCOFANY, nie ELIMINOWANY (pkt 26.d/27). (po R4.Zguba)
- [x] **(2026-06-06)** Reducer w `reducers.py` dla `ModelKilled` rozszerzony o `location` (WYCOFANY przy `models_alive==0`). ELIMINOWANY dispatch dojdzie z R4.Zguba (pole `eliminated` w evencie).

#### R5.b — Pkt 11.b: Przegrupowanie per-action + Manewr-free + akcja-różna
- [ ] `app/services/engine/phases.py::activation_phase`: Przegrupowanie pkt 11.b.iii już per-action (B3.9.c) — doprecyzować trigger pkt 20.a NOWY: "zadał MNIEJ ran niż otrzymał" (poprzednio: "otrzymał rany"). Helper `_wounds_dealt_minus_received_in_action(actor_id, context) -> int`.
- [ ] `activation_phase`: limit 2 akcji — track tylko non-Manewr akcji (`ChargeAction/ShootAction/DefendAction/SpecialAction`). `MoveAction` nieliczona.
- [ ] `activation_phase`: requirement "akcja różna od już wykonanych" — track `actions_used: tuple[ActionKind, ...]` w aktywacji. Wyjątki: jeśli aktor ma `Niestrudzony` (slug `niestrudzony`) — drop wymóg; jeśli `ActionKind.MANEUVER` — drop wymóg (Manewr zawsze legalny).
- [ ] Pkt 11.b.v Leczenie EOA — przeniesione po pętli akcji (już end-of-activation, nie post-action). Sprawdzić czy `_apply_heal_recovery` na końcu.
- [ ] Testy: `test_engine_phases.py` — scenariusze 2× Manewr+Szarża+Manewr (legal: Szarża+Manewry); 2× Szarża (illegal — to samo); Niestrudzony 2× Szarża (legal).

#### R5.c — Pkt 14.d.iv: kontratak conditional Wyczerpany
- [x] `combat.resolve_charge_attack`: `charger_after_counter.models_alive > 0` guard przed Wyczerpany emit dla defendera. 2 testy (commit `41d2a8a`).
- [x] Testy: `test_engine_combat.py` — `test_charge_counter_kills_charger_defender_not_exhausted` + `test_charge_counter_does_not_kill_charger_defender_becomes_exhausted`.

#### R5.d — Pkt 20.a/b/c/f: Przegrupowanie nowe warunki — **DONE 2026-06-05** (commit `ee8975f`)
- [x] `phases._regroup_test`: 20.a trigger = `delta_received > delta_dealt` (via `ActivationContext.dealt_for`/`delta_for`, agregacja z ShotResolved/MeleeResolved).
- [x] 20.b: NIE-powyżej-połowy → +1 test (`initial_toughness_for` ÷2, fallback dla fixtures).
- [x] 20.c: walczył wręcz → +1 test (`blob_id in melee_combatants`, drop melee_balance differentiation).
- [x] 20.f/20.d: modyfikatory ze statusów usunięte (R5.c); tylko passive (Nieustraszony).
- [x] Testy: `test_engine_activation_context.py` przepisane + `test_bug2_charge_defender_regroups_in_charger_activation` pod nowy trigger.

#### R5.e — Pkt 22.b/c: status simplification + mutex — **DONE 2026-06-05** (autopilot Opus 4.8)
- [x] **Implementacja wg H2 opcja (c)** (nie pierwotny szkic `status.py` helper): NOWY event `MutexCollision(target_id, dropped_statuses)` (14ty unikalny typ w `_EVENT_REGISTRY`) + reducer `_reduce_mutex_collision` + producer `phases._apply_mutex_collisions(state, candidate_ids, seq)`.
- [x] Pipeline: producer w `activation_phase` PO pętli Przegrupowania skanuje `regroup_subjects` (jedyne miejsce dodania Przyszpilony) → gdy blob ma Przyszpilony+Ufortyfikowany emit `MutexCollision` + mutacja live state; reducer aplikuje removal obu na replay. Generyczny `dropped_statuses: tuple[str,...]` (zawsze `(Przyszpilony, Ufortyfikowany)` w MVP).
- [x] Usunięte semantyki pkt 22.b.iv (+1 test)/22.c.ii (−1 test) — już usunięte w R5.c (`_regroup_test` komentarz). 22.b.iii brak w effects.py (sprawdzone: linia 202-203 to legalny semantyk Tarczy id 34, nie blokada).
- [x] Testy: 7 testów mutex w `tests/test_engine_status.py` (producer both-flags/preserve-other/noop×4/reducer/idempotent/producer-reducer-parity), 1 round-trip w `test_engine_events.py`, 2 integracyjne property-based w `test_engine_phases.py` (charge defender invariant ∀ seed + branch-fires + replay invariant). +12 testów.

#### R5.f — Pkt 13.c: Ufortyfikowany przy rozstawieniu
- [x] `phases.deployment_round`: emit `StatusAdded(Ufortyfikowany)` dla każdego DeploymentAction. 3 testy (commit `41d2a8a`).
- [x] Testy: `test_engine_phases.py` — adds_ufortyfikowany, StatusAdded in events, aktywacja usuwa (CR-fix G weryfikacja).

#### R5.g — Pkt 4.c.v: Niebezpieczny per-oddział — **DONE 2026-06-05** (commit `203daac`) + **findings #1/#3 DONE 2026-06-06**
- [x] `phases._apply_maneuver`: Niebezpieczny test per-unit = rzut `models_alive * toughness_per_model` k6, każda 1 → rana → `wounds_received`. Helper `_blob_inside_terrain_circle`. EffectApplied(niebezpieczny).
- [x] Testy: 2 w `test_engine_phases.py` (inflicts_wounds w terenie, no-event poza terenem).
- [x] **Finding #1 (2026-06-06):** rany z terenu → `_allocate_wounds_to_defender` (kill-loop + ModelKilled + replay reducer dla `niebezpieczny`). Modele giną od terenu; replay bit-perfect. +3 testy (kills/leftover/replay-invariant).
- [x] **Finding #3 (2026-06-06):** ZAPLECZE guard w `deployment_round` (rezerwy off-board bez Ufortyfikowany). +1 test.
- [ ] **Finding #2 (2026-06-06):** czy teren wyzwala Przegrupowanie → **H6 open** (decyzja autora reguł, semantyka niezmieniona).

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
- **H3 (RESOLVED 2026-06-06, USER DECISION — DEFER):** Dywersant — w pierwszym etapie (MVP) **pomijamy tę zdolność** (engine-side stub w `INCOMPLETE_ABILITIES`). Cost-side już done (R2). Policy (×2 ataki vs Przyszpilony) czeka na follow-up ADR.
- **H4:** Czy Niestrudzony (już istniejący w `effects.py`) ma logikę "drop wymóg akcji różnej"? Czy trzeba rozszerzyć semantykę? **RESOLVED 2026-06-06 (USER DECISION):** Szarża i Ostrzał mają wprost punkt limit raz na aktywacje (nie trzeba complex per-action-different tracking). R5.b jest **nie aktualne** — nie implementujemy.
- **H6 (RESOLVED 2026-06-06, USER DECISION):** Czy samozranienie od Niebezpiecznego terenu (pkt 4.c.v) ma wyzwalać test Przegrupowania (pkt 20.a)? **TAK.** Rany z terenu to zwykłe rany przychodzące, rozpatrywane bezpośrednio po ruchu (przy szarży — przed atakami). Mogą spowodować test przegrupowania po akcji. Semantyka: teren = część bilansu received (`delta_received > delta_dealt`). **Implementacja:** wszystkie rany (bojowe + terenowe) przepływają przez `_allocate_wounds_to_defender`, unifikując kill-loop i EffectApplied reducer w replay.
- **H5 (RESOLVED 2026-06-07, USER DECISION — KOREKTA, NIE 3-pula):** Q-H5a/b/c rozstrzygnięte. **2 pule alokacji bez zmian** (pkt 17.d) + **dodatkowy licznik `UnitBlob.wounds_eliminating: int`**. Broń Zguba zadaje rany normalnie do precise/regular ORAZ zwiększa `wounds_eliminating` o tę samą liczbę; alokacja precise/regular zmniejsza licznik; model pokonany gdy licznik wciąż dodatni → ELIMINOWANY (pkt 26.d), inaczej WYCOFANY (pkt 26.c). Reguła docelowa: „Zguba: Licz rany otrzymane tą bronią. Modele pokonane przez przydzielenie pierwszych ran do tej liczby nie mogą wrócić do gry." Pełny zapis w sekcji **Decyzje** (2026-06-07). **Wcześniejsze sformułowanie „3-pula" (2026-06-06) PORZUCONE** — sprzeczne z pkt 17.d (tylko 2 pule alokacji).

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
- 2026-06-06 **H3 (Dywersant policy) DEFERRED** (user decision): Dywersant (id 6) engine-side **pomijamy w MVP** (cost-side już done R2). Engine-side stub w `effects.INCOMPLETE_ABILITIES`.
- 2026-06-06 **H4 (akcja-różna / R5.b) NOT APPLICABLE** (user decision): Szarża i Ostrzał mają wprost punkt limit raz na aktywacje. R5.b (complex per-action-different tracking) **nie implementujemy** — reguły są już jasne.
- 2026-06-06 **H6 (terrain wounds + regroup trigger) RESOLVED** (user decision): Rany z terenu (pkt 4.c.v) to zwykłe rany przychodzące, rozpatrywane po ruchu (przed atakami w szarży). **TAK, mogą wyzwolić Przegrupowanie** (pkt 20.a `received > dealt`). Semantyka: teren = część bilansu received. Implementacja: wszystkie rany (bojowe + terenowe) przez `_allocate_wounds_to_defender`.
- 2026-06-06 **H5 (wounds representation) — wstępna decyzja „3-pula"**, SKORYGOWANA 2026-06-07 (patrz niżej). Pierwotne sformułowanie („`wounds_received` split na 3 pola") było niejednoznaczne (Q-H5a/b/c) — sprzeczne z pkt 17.d który definiuje tylko 2 pule alokacji. Zastąpione decyzją z 2026-06-07.
- 2026-06-07 **H5 (wounds representation / Zguba) RESOLVED — KORekta** (user decision, rozstrzyga Q-H5a/b/c): **2 pule alokacji BEZ zmian** (pkt 17.d: pula atakującego/precyzyjna = `wounds_pending_precise`, pula obrońcy = `wounds_pending`) + **osobny DODATKOWY licznik `wounds_eliminating: int`** na `UnitBlob` (NIE trzecia pula alokacji). Semantyka:
    1. Broń ze **Zguba** zadaje rany **normalnie** do puli precise/regular (per pkt 17.d) **ORAZ** dodatkowo zwiększa licznik `wounds_eliminating` o tę samą liczbę.
    2. `eliminating` **nigdy nie jest przydzielany samodzielnie** — gdy przydzielane są rany precise/regular, licznik `eliminating` **też maleje** (o liczbę faktycznie przydzielonych/zaalokowanych ran).
    3. Jeśli model zostaje **pokonany zanim licznik `eliminating` się wyczerpie** (tj. pokonany przez przydzielenie ran mieszczących się w pierwszych `N` = wartość licznika) → model jest **ELIMINOWANY** (pkt 26.d, nie może wrócić). W przeciwnym razie → WYCOFANY (pkt 26.c, może wrócić przez Leczenie pkt 21.c.ii).
    - **Zwięzła reguła docelowa:** „Zguba: Licz rany otrzymane tą bronią. Modele pokonane przez przydzielenie **pierwszych ran do tej liczby** nie mogą wrócić do gry."
    - **Q-H5a RESOLVED:** NIE splitujemy `wounds_received`/4 pól ran — dodajemy jedno pole `wounds_eliminating`. **Q-H5b RESOLVED:** `eliminating` jest ortogonalny do `wounds_pending_precise` (precyzyjny=pula alokacji; eliminating=znacznik „pierwsze N ran są eliminujące"). **Q-H5c RESOLVED:** `eliminating` to **liczba ran**, malejąca wraz z alokacją; pokonanie modelu gdy licznik wciąż dodatni → ELIMINOWANY.
    - **Implikacja na wcześniejszą „3-pula":** porzucona — żaden split `wounds_received`. Impact ADR-0014: dodanie pojedynczego pola-licznika, nie restrukturyzacja. B2 ORM `BattleEvent.payload_json`: +1 pole `wounds_eliminating` per unit (nie 3).

## Notatki / odkrycia w trakcie

- **2026-06-07 (autopilot Opus 4.8) — FOLLOW-UP R5.a DOMKNIĘTY: morale-broken → WYCOFANY.** Ścieżka pokonania przez morale (pkt 20.f.iii `failures>=3`, `result_status='broken'`) ustawia teraz `location=Lokalizacja.WYCOFANY` w producerze (`phases._regroup_test`) i mirror-reducerze (`reducers._reduce_morale_test`) — lustrzanie do ścieżki ran z `422412c`. **Decyzja semantyki (rozstrzygnięta tekstem reguł, bez udziału usera):** pkt 20.f.iii 'pokonany' → pkt 27.b 'cały oddział staje się Wycofany i Pokonany' → pkt 26.c domyślny przypadek. Obawa z review (że morale-broken mógłby rallować) bezpodstawna: pkt 26.c.iii wprost zezwala WYCOFANemu wrócić przez Leczenie (pkt 21.c.ii) — WYCOFANY jest poprawne *niezależnie* od rally; tylko ELIMINOWANY (pkt 26.d, broń Zguba) blokuje powrót. Niezmiennik "pokonany → WYCOFANY" pokrywa teraz 2 z 3 ścieżek (rany ✅ + morale ✅; ELIMINOWANY/Zguba świadomie deferred do R4.Zguba/H5). **Testy (+2):** `test_engine_phases.py` — `test_regroup_broken_sets_location_wycofany` (producer, seed 2 → rolls [1,1,1] → 3 porażki → broken; n_tests=3 = 20.a+20.b+20.c) + `test_morale_broken_reducer_mirrors_location_wycofany` (reducer via `apply_events`). **Weryfikacja:** pytest **1428/1428** (+2); parity both_assert 156/156 + yaml 93/93; smoke replay 48 events EXIT 0 (replay invariant pokrywa `location` w `_BLOB_REPLAY_FIELDS`). `/simplify` inline: 2 edycje lustrzane do wzorca `ModelKilled` — brak duplikacji/uproszczeń.

- **2026-06-07 (R6 — procedural oracle sync):** Wszystkie R6 gates pass. **Sources SHA256 CLEAN** (exit 0). **Drift R1=0/R2=0/R3=29 WARN** (exit 2 — acceptable; R3 to description wording differences w YAML vs DOCX, nie structural issues). **Parity both_assert 156/156** — cost oracle synced. **YAML backend 93/93**. **Smoke replay GATE OK** (48 events, 12 typów, `apply_events(initial, 48) == live_state`). **pytest 1428/1428** — zero failures (baseline był 1375 z 10 failures, teraz 1428/0). **Procedural oracle (abilities.py) zsynchronizowany** z SZOP_Zdolnosci.md — wszystkie 8 abilities: Zguba/Nieustraszony/Harcownik/Zemsta/Dywersant/Klątwa/Rozkaz/Oznaczenie mają poprawne opisy. **Merge Faza_A→main** wykonany (82 commity: B0+B3+B3.9+rules-resync R0-R7 częściowo). Otwarte: R4.Zguba (wounds_eliminating impl) + R4.Klątwa/Rozkaz/Oznaczenie + R7 (ADR-0048) + RW final. B2/B4/B5 odblokowane na main.

- **2026-06-07 (code-review autonomiczny Opus 4.8) — FOLLOW-UP R5.a: niekompletny niezmiennik pkt 27.b/26.c.** *(DOMKNIĘTY tego samego dnia — patrz notatka wyżej.)* Code-review zakresu `3215f38..HEAD` (raport: `docs/handoffs/code-review/REVIEW_2026-06-07.md`, pytest 1426/1426, 0 fail, replay terenu zweryfikowany bit-perfect). **1 finding:** semantyka „pokonanie → WYCOFANY" (commit 422412c) zastosowana TYLKO do ścieżki pokonania przez rany (`combat._allocate_wounds_to_defender` + mirror `reducers._reduce_model_killed`). **DRUGA ścieżka pokonania — morale (pkt 20.e, `failures >= 3`, result_status='broken') — pomija `location=WYCOFANY`:** `phases._regroup_test:612` i mirror `reducers._reduce_morale_test:241` ustawiają `models_alive=0, wounds_received=0` BEZ location. Skutek: oddział pokonany 3 porażkami Przegrupowania ma `location` niezmienione (np. FRONT), niespójnie z oddziałem pokonanym ranami (WYCOFANY). Dziś latentne (brak konsumenta `location==WYCOFANY` dla pokonanych), ale gdy B2 ORM payload / win-condition / objective-control zaczną czytać location do detekcji pokonanych — morale-broken zostaną pominięte. **Fix trywialny** (2 linie lustrzane do 422412c) ALE **wymaga decyzji semantyki:** czy pkt 20.e 'broken' == 'pokonany → WYCOFANY' (pkt 26.c)? (silnie sugeruje TAK; ryzyko: interpretacja że morale-broken może rallować). **NIE auto-naprawione** (decyzja autora reguł, konsekwentnie z dyscypliną driftu). **TODO przy domknięciu R5.a lub R6:** ustawić `location=Lokalizacja.WYCOFANY if models_alive==0` w obu miejscach 'broken' (producer phases.py:612 + reducer reducers.py:241) po potwierdzeniu semantyki. Trzecie miejsce pokonania (ELIMINOWANY/Zguba) świadomie deferred do R4.Zguba (H5).

- **2026-06-06 (autopilot Opus 4.8) — R5.a-WYCOFANY DONE (pkt 27.b).** Pokonanie ostatniego modelu (`models_alive == 0`) ustawia `location=WYCOFANY` w producerze (`combat._allocate_wounds_to_defender`) i w replay-reducerze (`reducers._reduce_model_killed`) — bit-perfect. `location` dodane do `_BLOB_REPLAY_FIELDS` (wcześniej replay invariant tego pola NIE sprawdzał). **Weryfikacja:** pytest **1426/1426** (+3); parity both_assert 156/156 + yaml 93/93; smoke replay 48 events EXIT 0 (inwariant pokrywa teraz `location`). `/simplify` inline: kod czysty (producer/reducer celowo lustrzane per B3.9.d). ELIMINOWANY (pkt 27.a, broń Zguba) NADAL odłożone do R4.Zguba — wymaga decyzji H5 (niżej).
  - **DOPRECYZOWANIE H5 (blokada dla usera):** czytając pkt 17.d stwierdzono, że reguły definiują **tylko 2 pule alokacji** ran w ataku: „pula atakującego" (naturalna 1 na obronie → `wounds_pending_precise`) i „pula obrońcy" (`wounds_pending`). „Eliminowany" (pkt 27) to **nie trzecia pula alokacji**, lecz właściwość *modelu* pokonanego bronią Zguba (pkt 27.a) — utrzymywana jako licznik/flaga, nie pula nadchodzących ran. Decyzja H5 z 2026-06-06 („`wounds_received` → 3 pola precise/regular/eliminating") jest **niejednoznaczna**: (Q-H5a) czy splitujemy `wounds_received` (znaczniki, pkt 18.c), czy restrukturyzujemy wszystkie 4 pola ran (received/pending/pending_precise/melee_balance)? (Q-H5b) jak `eliminating` współgra z istniejącym `wounds_pending_precise` (oba „precyzyjne"?)? (Q-H5c) „alokacja precise/regular → eliminating counter maleje" — czy `eliminating` to liczba ran do zadania jako eliminujące, czy liczba pokonań-do-eliminacji? **Rekomendacja:** `eliminating` jako osobny licznik na `UnitBlob` (`wounds_eliminating: int`) NIE jako pula alokacji — `_allocate_wounds_to_defender` przy każdym `ModelKilled` sprawdza `if wounds_eliminating > 0: model→ELIMINOWANY; wounds_eliminating -= 1`. To nie wymaga zmiany 2-pulowej alokacji pkt 17.d. **Wstrzymane do decyzji usera (Q-H5a/b/c).** R5.a-WYCOFANY (pkt 27.b, domyślny przypadek) jest niezależne i implementowane teraz.

- **2026-06-06 (autopilot Opus 4.8) — R5.g findings DOMKNIĘTE (#1 + #3):** finding #1 (rany z Niebezpiecznego terenu) i #3 (ZAPLECZE guard) naprawione; finding #2 → otwarta kwestia **H6** (decyzja autora reguł, semantyka niezmieniona).
  - **Finding #1 (poprawność + replay-invariant):** `phases._apply_maneuver` — rany z terenu przechodzą teraz przez `_allocate_wounds_to_defender` (SSOT z combat, self-inflicted `attacker_id=None`, `prefer_hero=False`) zamiast surowego dopisania do `wounds_received`. Pełne komplety `toughness_per_model` pokonują modele (emit `ModelKilled`), nadwyżka zostaje jako znaczniki (pkt 18.c). **Modele giną teraz od terenu** (wcześniej `models_alive` zostawał błędnie wysoki). Dodatkowo była to CICHA mutacja stanu poza event-sourcingiem (EffectApplied no-op reducer → `apply_events` nie odtwarzał ran, analog bug #6 z B3.9): `reducers._reduce_effect_applied` dla slug `niebezpieczny` pushuje teraz `wounds_inflicted` na replay (mirror producer-a), ModelKilled absorbują pulę → bit-perfect replay.
  - **Finding #3 (higiena):** `phases.deployment_round` — guard `b.location != Lokalizacja.ZAPLECZE` przy nadawaniu Ufortyfikowany (pkt 13.c "rozstawiony oddział"; rezerwy off-board Zasadzka/Rezerwa nie są fortyfikowane w rundzie 1).
  - **Testy (+4):** `test_engine_phases.py` — `test_activation_maneuver_niebezpieczny_kills_models` (seed=1 deterministyczny, 2 zabite modele), `..._leftover_markers` (konserwacja inflicted == kills×tou + markery), `test_deployment_round_skips_ufortyfikowany_for_reserves`; istniejący `..._inflicts_wounds` przepisany na deterministyczny seed=1. `test_engine_replay_invariant.py` — `test_replay_maneuver_into_dangerous_terrain` (GATE: apply→replay bit-perfect mimo self-inflicted ran). Helper `_state_with_dangerous_terrain`.
  - **Weryfikacja:** pytest **1423/1423** (+4); parity both_assert 156/156 + yaml 93/93; smoke replay 48 events EXIT 0 (replay invariant OK). `/simplify` inline: usunięty martwy guard `target_unit_id is not None` (pole to wymagane int).
  - **Uwaga interakcja z finding #2:** po fixie #1 rany z terenu są częściowo absorbowane przez kille, więc `delta_received` z terenu = tylko nadwyżkowe markery (`wounds_inflicted % toughness`), nie pełna pula. Zmienia to magnitudę triggera Przegrupowania z terenu — patrz H6.

- 2026-06-06 (code-review autonomiczny Opus 4.8): **3 findings semantyczne** (pełny raport: `docs/handoffs/code-review/REVIEW_2026-06-06.md`). pytest 1419/1419, brak crashy — to decyzje driftu do domknięcia, nie regresje:
  1. **[R5.g — poprawność]** `phases._apply_maneuver:349`: rany z Niebezpiecznego terenu dopisywane surowo do `wounds_received` BEZ emisji `ModelKilled` i bez pętli kill (`_allocate_wounds`). **Modele nigdy nie giną od terenu** — markery rosną, `models_alive` zostaje błędnie wysoki (liczba ataków/kości liczy się z pełnych modeli). Komentarz zakłada "alokację w przyszłej aktywacji", ale taka faza drenująca markery NIE istnieje (kill pochodzi tylko z ModelKilled przy walce). **TODO R5.g:** albo uruchomić pętlę kill + emit ModelKilled, albo udokumentować konkretną fazę alokacji markerów.
  2. **[R5.d/R5.g — semantyka do potwierdzenia]** `phases._apply_maneuver:351`: ruch przez Niebezpieczny teren wyzwala test Przegrupowania (received>0 od terenu, dealt=0 → `received>dealt`). Potwierdzić z autorem reguł czy samozranienie terenu ma liczyć się w pkt 20.a; jeśli nie — wykluczyć teren z bilansu received.
  3. **[R5.f — higiena]** `phases.deployment_round:284`: Ufortyfikowany nadawany WSZYSTKIM blobom `models_alive>0`, w tym rezerwom off-board (`location==ZAPLECZE`: Zasadzka/Rezerwa). Dodać guard `and b.location != Lokalizacja.ZAPLECZE`. Nisko-szkodliwe, ale niespójne z pkt 26.

- 2026-06-05 (autopilot Opus 4.8): **R5.e DONE** — mutex Przyszpilony↔Ufortyfikowany (pkt 22.b/c) wg decyzji H2 opcja (c). NOWY event `MutexCollision(target_id, dropped_statuses)` (14ty unikalny typ w `_EVENT_REGISTRY`) + reducer `_reduce_mutex_collision` (reducers.py) + producer `_apply_mutex_collisions` w `phases.activation_phase` (skanuje `regroup_subjects` po Przegrupowaniu — jedyne miejsce dodania Przyszpilony). Pliki: `events.py`, `reducers.py`, `phases.py`, `tests/test_engine_{status,events,phases}.py`. **Weryfikacja:** pytest **1419/1419** (+12); parity both_assert 156/156 + yaml 93/93; smoke replay 48 events EXIT 0 (replay invariant OK). Jedyne miejsce kolizji: defender szarży rozstawiony z Ufortyfikowany (R5.f) który zyskuje Przyszpilony przy 2 porażkach Przegrupowania w aktywacji chargera — testy integracyjne property-based ∀ seed (invariant: żaden blob nie ma obu) + branch-fires. `/simplify`: 1 cleanup (redundant `sorted()` w call-site, helper i tak sortuje). **Pozostaje:** R5.b (Manewr-free + akcja-różna + limit 2 akcji — najbardziej złożone), R6 (drift+parity verify), R7 (ADR-0048 + docs), RW final.
- **2026-06-06 (tej sesji — user decisions):** 
  - **H3 RESOLVED:** Dywersant pomijamy w MVP (cost-side done, engine-side stub).
  - **H4 RESOLVED:** R5.b akcja-różna not applicable (Charge/Shoot już per-activation limits).
  - **H6 RESOLVED:** Terrain damage = part of received balance → regroup trigger fires normally.
  - **H5 RESOLVED:** **3-pool wounds:** `precise`, `regular`, `eliminating`. Allocate precise/regular → `eliminating` decreases. Model killed @ eliminating>0 → eliminated (no revive). Zguba wounds → precise/regular + eliminating pools. **Refactor UnitBlob:** `.wounds_received` (single int) → `.wounds_precise`, `.wounds_regular`, `.wounds_eliminating` (3 ints). Implication: ALL reducers update 3 fields; ActivationContext sums all 3 to `delta_received` for regroup test. Impact B3.9 ADR-0014 (expand from 4-category to 3-pool per new semantics); B2 ORM BattleEvent.payload → all 3 fields; B4 API schemas.
  - **Pozostały do implementacji:** R5.b (skip), R5.x (Zguba + Dywersant stub INCOMPLETE_ABILITIES — defer fully), R6/R7/RW verify+docs.

- 2026-06-03: HANDOFF utworzony. Baseline: pytest 1375 passed / 10 failed (failures = oczekiwany drift YAML vs procedural po merge `b8481d5`).
- 2026-06-03: Pliki driftu pomocnicze (nie commitowane, untracked): `_drift_rozjemca.diff` (150 linii), `_drift_zdolnosci.diff` (894 linii) — używać jako wejście do klasyfikacji R0/R4.
- 2026-06-03: **Drift summary** zachowane w głównym kontekście sesji startowej (przed R0). Najważniejsze zmiany rdzenia (pkt 11/20/21/22/26/27) + 8 abilities przepisanych + formuła T_eff (Aura/Rozkaz/Klątwa/Oznaczenie).
- 2026-06-04: **R4 cost-side closed bez kodu.** Audyt 3 abilities — wszystkie cost-side już zaimplementowane. Brak entry w `ability_costs.yaml` dla Przewidywalny jest poprawne — to weapon-multiplier. Engine-side odłożone: Klątwa/Rozkaz/Oznaczenie nadal w `INCOMPLETE_ABILITIES` stubs; Zguba wymaga Lokalizacja enum prereq. **Następne: R5 engine semantics.**
- 2026-06-05: **Autonomiczna sesja (Claude Sonnet 4.6)**. `rozkaz_tak` field (88 abilities, 30 true), Lokalizacja enum (ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY) + UnitBlob.location, kontratak conditional Wyczerpany (R5.c), Ufortyfikowany przy rozstawieniu (R5.f). Commit `41d2a8a`, pytest 1404/1404 (+13 testów). Smoke replay: 50 events (46+4 StatusAdded Ufortyfikowany w deployment). **Otwarte:** R4.Zguba (wounds_zguba_per_victim + ELIMINOWANY dispatch + heal-limit), R4.Dywersant engine policy (before_hit_rolls interrupt), R5.b (Przegrupowanie per-action + Manewr free + akcja-różna — najbardziej złożone), R5.d (Przegrupowanie warunki 20.a/b/c/f), R5.e (status mutex Przyszpilony↔Ufortyfikowany), R5.g (Niebezpieczny per-unit), R6 (drift+parity verify), R7 (ADR-0048 + docs).
- 2026-06-05 (tej sesji): **R5.d DONE** — pkt 20.a/b/c warunki Przegrupowania per drift 2026-06. `ActivationContext` rozszerzone o `wounds_dealt_this_activation: tuple[tuple[int,int],...]` + `dealt_for(uid)` helper (default `()` dla backward compat). `_build_activation_context` przyjmuje `action_events` parameter — agreguje `wounds_dealt + wounds_precise` per `attacker_id` z `ShotResolved`/`MeleeResolved` events. `_regroup_test`: pkt 20.a NEW trigger = `received > dealt` (zamiast `delta > 0 OR melee_balance < 0`); pkt 20.c = `if blob_id in melee_combatants: +1 test` (drop melee_balance > 0/< 0 differentiation — uproszczenie drift "walczył wręcz = +1"); pkt 20.b semantyka równoważna pre-drift (current ≤ ½ initial — "NIE-powyżej-połowy"). `test_bug2_charge_defender_regroups_in_charger_activation` przepisany pod nowy trigger (defender T6 Q5 — survives + nie zadaje w kontrataku → received > dealt → test fires). **Verify:** pytest 1404/1404 + parity 156/156 + smoke replay 48 events EXIT 0 (z 50 do 48 bo nowy trigger eliminuje niektóre testy które wcześniej fire'owały false positive). **Pozostaje:** R5.b (akcja-różna), R5.e (MutexCollision), R5.g (Niebezpieczny per-unit), R5.x (defer Dywersant+Zguba), R6+R7+RW.



