# HANDOFF — faza-b-rules-resync

> **Wątek:** Synchronizacja YAML SSOT + engine z nowymi wersjami zasad (SZOP_Rozjemca.md + SZOP_Zdolnosci.md po 2026-06-03 drift) — Przegrupowanie per-action, Leczenie EOA, formuła T_eff dla aur/rozkazów, Lokalizacja enum, 8 zdolności przepisanych.
> **Status:** In progress
> **Utworzony:** 2026-06-03
> **Ostatnia aktualizacja:** 2026-06-03

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

### Faza R0 — Drift classification + baseline

- [ ] Uruchomić `make rules-check` (lub Windows fallback: `python scripts/rules_sources_check.py && python scripts/rules_extract.py && python scripts/rules_extract_md.py && python scripts/rules_drift.py`). Zebrać raporty R1/R2/R3/R4 w `build/`.
- [ ] Zaktualizować `app/rulesets/v1/source_hashes.yaml` — SHA256 dla 4 plików źródłowych (DOCX, PDF, 2× MD) po update z main.
- [ ] Wygenerować klasyfikację: ile abilities ma R1 (nowe yaml-only), R2 (rozbieżność cost), R3 (wording), R4 (krytyczne). Hipoteza: R1=0 (wszystkie usunięcia aura/rozkaz), R2≥77 (każda ma usunięte aura/rozkaz pola w cost = strukturalna rozbieżność), R3=ok 8 (przepisane opisy), R4=0 (brak nowych mechanik geometrycznych).
- [ ] Decyzja: czy R2 (cost) generuje exit 1 (ERROR) — wtedy chwilowy `drift_allowlist.yaml` z wpisami "TODO faza-b-rules-resync R2/R3" do czasu R3 implementacji.

### Faza R1 — `tables.yaml`: Lokalizacja + pkt 22 + T_eff formula

- [ ] `tables.yaml`: nowa sekcja `locations: [zaplecze, front, wycofany, eliminowany]` z opisem semantyki (pkt 26.a-d).
- [ ] `tables.yaml`: sekcja `status_flags` rozszerzona (pkt 22.a-d): mapping `wyczerpany/przyszpilony/ufortyfikowany/aktywowany` → effect codes. Usunięte: pkt 22.b.iii (blokada aktywnych/aur), pkt 22.b.iv (+1 test), pkt 22.c.ii (−1 test). Dodane: pkt 22.b.iii+22.c.iv mutex (oba odrzucane).
- [ ] `tables.yaml`: nowa sekcja `aura_order_formula`: `T_eff_factor = 4/3`, `T_eff_clamp = [8, 24]`, formuły `cost.aura = bazowy * T_eff`, `cost.aura_12 = bazowy * (T_eff + 8)`, `cost.order = bazowy * (T_eff + 2)`.
- [ ] Update `app/services/rulesets/models.py` — Pydantic models dla nowych sekcji (`LocationKind`, `StatusFlag`, `AuraOrderFormula`).
- [ ] Testy: `tests/test_tables_migration.py` rozszerzony o 3 nowe sekcje (location/status/aura formula).

### Faza R2 — `abilities.yaml`: czyszczenie aura/rozkaz pól (77 abilities)

- [ ] Skrypt `scripts/_yaml_strip_aura_rozkaz.py` (helper, internal) — jednorazowy: usuwa `cost.aura` i `cost.rozkaz` z wszystkich entries gdzie obecne (NIE z Klątwa/Rozkaz/Oznaczenie — tam `cost.bazowy` jest sama formuła; ich update w R4).
- [ ] Update test `tests/test_abilities_migration.py` — assertion że `cost` ma tylko `bazowy` + opcjonalnie `tabela_*` dla weapons. (Procedural oracle w `app/data/abilities.py` — po main update — już zsynchronizowany).
- [ ] Drift run sanity — R2 powinno spadać do ~8 (tylko abilities z R3 wording).

### Faza R3 — `ability_costs.yaml` + `cost_functions`: T_eff formula

- [ ] `app/services/rulesets/cost_functions.py`: 3 nowe funkcje:
    - `aura_cost(bazowy: Decimal, T: int, *, with_range: bool=False) -> Decimal` — używa formuły z `tables.yaml`
    - `order_cost(bazowy: Decimal, T: int) -> Decimal` — używa T_eff+2
    - `t_eff(T: int) -> int` — helper `int(clamp(4/3*T, 8, 24))` (półzaokrąglenie do dyskutowania — patrz H1 poniżej)
- [ ] `app/services/rulesets/dispatcher.py` — register w `_REGISTRY`.
- [ ] `app/services/rulesets/handlers.py` — handler `aura` przepisany na `aura_cost(recipe.bazowy, T_carrier)`, `order_like` na `order_cost(recipe.bazowy, T_carrier)`.
- [ ] `ability_costs.yaml` — usunąć stałe wartości aury/rozkazu z 33 entries; dla każdej ability z `aura_tak: true` lub `rozkaz_tak: true` recipe = nowa formuła.
- [ ] Update `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — musi przejść 156/156 po update procedural side (na main już zsynchronizowane).
- [ ] Update `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` — 93/93.
- [ ] Testy: `tests/test_cost_functions.py` rozszerzony (T_eff edge cases: T=3 → 8 clamp, T=24 → 24 clamp, T=10 → 13).

### Faza R4 — 8 abilities przepisanych

- [ ] **Bohater** (id 2): dodać efekt "stale (gdy oddział z >1 profilem) — przeciwnik wybiera obronę"; dodać "Odzyskiwanie — nie przywracany"; ujednolicić opis z nowym driftem. Engine: flag `cannot_be_revived` w `state.UnitBlob` per-model dla bohatera; `_apply_heal_revive` skip jeśli flag set.
- [ ] **Dywersant** (id 6): PRZEPISANY. Effect = przy ataku jeśli atakujący bliżej strefy rozstawienia przeciwnika niż cel → przeciwnik wybiera (×2 ataki LUB Przyszpilony cel). YAML cost: `bazowy: 3.25 / pkt wytrzymałości` + `weapon_modifier: x1.2`. Engine: `effects.py` nowy interrupt point `before_hit_rolls`, dispatcher z opcją wyboru (deterministic policy w MVP: przeciwnik wybiera "tańszą" — heurystyka udokumentowana w ADR-0048).
- [ ] **Harcownik** (id 8): zmiana `kiedy` z "przed Przegrupowaniem (pkt 11.b.iv)" na "przed Leczeniem (pkt 11.b.v, pkt 21)". Engine: hook przeniesiony.
- [ ] **Nieustraszony** (id 16): nowa logika — `co: oddział nie wykonuje testu z pkt 20.a gdy oddział >50% wytrzymałości`. YAML: nowe efekty + cost `bazowy: 1.5 / pkt wytrzymałości` + tabela mnożnik 0.5. Engine: `_regroup_test` consult `effects.has_nieustraszony(blob) and blob_above_half(blob)` → skip 20.a.
- [ ] **Zemsta** (id 41): przesunięty trigger "przed Leczeniem" (pkt 11.b.v). Engine: dispatcher już ma faza Leczenia — dodać wound deferred allocation.
- [ ] **Zguba** (broń, id 76): licznik `wounds_zguba_per_victim: dict[unit_id, int]` w `UnitBlob` lub `BattleState` (decyzja w ADR-0048). Eliminowany dispatch w `state.py` lokalizacja enum. Healing limit redukowany o licznik. Modele pokonane przez pierwsze N ran → Eliminowany.
- [ ] **Klątwa(X) / Rozkaz(X) / Oznaczenie(X)** (id 45/49/50): walidacja X musi mieć `rozkaz_tak: true` w `abilities.yaml`. Wycena: `bazowy(X) × (T_eff + 2)`. Engine: `effects.py` interrupt handler — wymaga lookup `abilities.get(X).rozkaz_tak` przed apply.
- [ ] **Przewidywalny** (id 71): koszt `— → broń ×1.2`. Update `weapon_modifier` w `abilities.yaml` + tabela weapons.
- [ ] Testy: 8 nowych unit testów (po 1 per ability) w `tests/test_passive_costs.py` + `tests/test_engine_effects.py` (dla effect mechanics).

### Faza R5 — Engine: pkt 11 + 14.d.iv + 20 + 21 + 26 + 27

#### R5.a — Lokalizacja enum
- [ ] `app/services/engine/state.py`: dodać `class Lokalizacja(str, Enum): ZAPLECZE / FRONT / WYCOFANY / ELIMINOWANY`. `UnitBlob.location: Lokalizacja = Lokalizacja.ZAPLECZE` (default). `build_initial_state`: domyślnie ustawia `FRONT` dla rozstawionych w setup, `ZAPLECZE` dla rezerw (Zasadzka/Rezerwa).
- [ ] `setup_phase`/`deployment_round` — przejście ZAPLECZE → FRONT po deploy.
- [ ] `combat._allocate_wounds_to_defender` (lub apply_events ModelKilled reducer) — model `WYCOFANY` (default) lub `ELIMINOWANY` (gdy zabity bronią Zguba). Cały oddział `WYCOFANY` gdy `models_alive == 0`.
- [ ] `effects._apply_heal_revive` — może przywrócić tylko WYCOFANY, nie ELIMINOWANY (pkt 27.c).
- [ ] Reducer w `reducers.py` dla `ModelKilled` rozszerzony o `location` discrimination.
- [ ] Testy: `tests/test_engine_state.py` Lokalizacja enum + transitions.

#### R5.b — Pkt 11.b: Przegrupowanie per-action + Manewr-free + akcja-różna
- [ ] `app/services/engine/phases.py::activation_phase`: Przegrupowanie pkt 11.b.iii już per-action (B3.9.c) — doprecyzować trigger pkt 20.a NOWY: "zadał MNIEJ ran niż otrzymał" (poprzednio: "otrzymał rany"). Helper `_wounds_dealt_minus_received_in_action(actor_id, context) -> int`.
- [ ] `activation_phase`: limit 2 akcji — track tylko non-Manewr akcji (`ChargeAction/ShootAction/DefendAction/SpecialAction`). `MoveAction` nieliczona.
- [ ] `activation_phase`: requirement "akcja różna od już wykonanych" — track `actions_used: tuple[ActionKind, ...]` w aktywacji. Wyjątki: jeśli aktor ma `Niestrudzony` (slug `niestrudzony`) — drop wymóg; jeśli `ActionKind.MANEUVER` — drop wymóg (Manewr zawsze legalny).
- [ ] Pkt 11.b.v Leczenie EOA — przeniesione po pętli akcji (już end-of-activation, nie post-action). Sprawdzić czy `_apply_heal_recovery` na końcu.
- [ ] Testy: `test_engine_phases.py` — scenariusze 2× Manewr+Szarża+Manewr (legal: Szarża+Manewry); 2× Szarża (illegal — to samo); Niestrudzony 2× Szarża (legal).

#### R5.c — Pkt 14.d.iv: kontratak conditional Wyczerpany
- [ ] `combat.resolve_charge_attack`: po kontrataku check `charger.models_alive == 0` → defender NIE emituje `StatusAdded(Wyczerpany)`. Pre-fix B3.9.d zawsze emit.
- [ ] Testy: `test_engine_combat.py` 2 nowe — counter kills charger, defender no Wyczerpany; counter nie kills charger, defender Wyczerpany.

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
- [ ] `phases.deployment_round`: emit `StatusAdded(Ufortyfikowany)` + `StatusAdded(Aktywowany)` (poprzednio tylko Aktywowany).
- [ ] Testy: `test_engine_phases.py` deployment scenario.

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

## Notatki / odkrycia w trakcie

- 2026-06-03: HANDOFF utworzony. Baseline: pytest 1375 passed / 10 failed (failures = oczekiwany drift YAML vs procedural po merge `b8481d5`).
- 2026-06-03: Pliki driftu pomocnicze (nie commitowane, untracked): `_drift_rozjemca.diff` (150 linii), `_drift_zdolnosci.diff` (894 linii) — używać jako wejście do klasyfikacji R0/R4.
- 2026-06-03: **Drift summary** zachowane w głównym kontekście sesji startowej (przed R0). Najważniejsze zmiany rdzenia (pkt 11/20/21/22/26/27) + 8 abilities przepisanych + formuła T_eff (Aura/Rozkaz/Klątwa/Oznaczenie).
