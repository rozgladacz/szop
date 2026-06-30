# Architecture

## Model danych i dziedziczenie

- **Armie i Rozpiski wspierają hierarchię i dziedziczenie.** Wariant trzyma tylko różnice względem bazy (nie duplikuj pełnego stanu).
- **Stabilne identyfikatory** — jeśli obiekt już istnieje, zachowaj jego ID. Zmiana modelu musi uwzględniać wpływ na warianty potomne.
- **Nie duplikuj stanu** — jeśli wystarczą nadpisania, używaj ich.
- Zmiana modelu = audyt warstw: `app/models.py` → migracje Alembic → routery → JS render → testy parity.

## Baza danych

- SQLite, `data/szop.db`.
- Traktuj bazę jako **środowisko testowe, ale współdzielone**.
- **Nigdy nie wykonuj destrukcyjnych operacji** bez wyraźnego polecenia. Zawsze trzymaj kopię zapasową.
- **Wersja w git jest źródłem prawdy** — przywracaj przez:
  ```bash
  git show <commit>:seeds/szop.db.seed > data/szop.db
  ```
- **Migracje:** jeśli zadanie wymaga zmian schematu, opisz wpływ i przygotuj migrację Alembic.
- **Preview = baza produkcyjna:** przed udostępnieniem Preview do akceptacji podłącz `data/szop.db` z danymi. Pusta baza dyskwalifikuje preview.

## Uprawnienia

UI nadal ma dwa poziomy: `admin` i `user`. Funkcje administracyjne **jawnie odseparowane** od user-flow. Nie rozszerzaj uprawnień usera bez wyraźnego wymagania.

Agent access (B2/C1) jest osobnym torem: `User.role="agent"` + `AgentToken`
przechowuje wyłącznie `token_hash`, a `app/security.py:require_agent_scope(scope_name)`
weryfikuje bearer token przez hash, sprawdza scope (`*` albo konkretny scope),
odrzuca tokeny wygasłe/cofnięte oraz zapisuje `AgentAuditLog` z redakcją
sekretów w parametrach. `app/routers/agent_tokens.py` udostępnia JSON API
owner-only: `POST /agent_tokens` generuje raw bearer token tylko raz i zapisuje
wyłącznie hash, egzekwując limit 20 aktywnych tokenów ownera; `GET /agent_tokens`
listuje własne tokeny bez sekretów, a `DELETE /agent_tokens/{id}` cofa własny
token. Pełny kontrakt: [ADR-0025](adr/0025-agent-scoped-tokens.md).
`app/routers/agent_proposals.py` dodaje backendowy consent gate dla przyszłych
zapisów agentów: bearer scope `agent_proposals:create` tworzy owner-scoped
`AgentProposal(status="pending")`, owner przez sesję użytkownika listuje własne
propozycje przez `GET /agent_proposals`, zatwierdza `POST
/agent_proposals/{id}/approve` albo odrzuca `POST /agent_proposals/{id}/reject`.
Decyzja zapisuje status i audit, ale nie wykonuje jeszcze akcji domenowej.
Konsumenci B4/MCP oraz UI zatwierdzania pozostają osobnym zakresem.

## Dokumentacja reguł gry — read-only

Pliki w `app/static/docs/`:
- **Nie modyfikuj** bez osobnego zadania.
- Jeśli kod i dokumentacja są sprzeczne — **zatrzymaj się i opisz rozbieżność**, nie zgaduj znaczenia reguły.

## Silnik kosztów — dwa backendy pod feature toggle

Od fazy A Strumienia A silnik kosztów działa w dwóch wariantach przełączanych przez ENV `OPR_RULES_BACKEND`:

| Wartość | Backend | Status |
|---|---|---|
| `procedural` (default) | `app/services/costs/` — historyczny silnik proceduralny | **SSOT (oracle)** — nie modyfikujemy |
| `yaml` | `app/services/rulesets/` + `app/rulesets/v1/*.yaml` — deklaratywny | Niezależna replika (parity ≤ 1e-3 z procedural) |
| `both_assert` | Wywołuje oba, porównuje rekurencyjnie, raise `RulesetParityError` przy delcie > 1e-3 | CI gate (`make test-parity`) |

Top-level dispatcher żyje **tylko** w `app/services/costs/quote.py:calculate_roster_unit_quote`. Detale: [ADR-0005](adr/0005-feature-toggle.md), [ADR-0004](adr/0004-cost-dsl.md), [ADR-0007](adr/0007-ruleset-cache.md).

### Pakiet `app/services/costs/` — procedural SSOT (oracle)

Każda zmiana kosztów musi przechodzić przez te moduły — nie replikuj logiki inline w routerach ani w JS.

| Plik | Linie | Zawartość |
|------|-------|-----------|
| `_engine.py` | ~300 | Stałe, tabele, dataclassy (`PassiveState`, `AbilityCostComponents`), `_roster_unit_classification`, stubs importów |
| `primitives.py` | ~310 | Sekcja 4: `ability_identifier`, `normalize_name`, `_strip_role_traits`, `lookup_with_nearest` |
| `weapons.py` | ~317 | Sekcja 6: `_weapon_cost`, `weapon_cost_components`, `weapon_cost` |
| `abilities.py` | ~372 | Sekcja 5: `passive_cost`, `base_model_cost`, `ability_cost_from_name` |
| `passive_state.py` | ~347 | Sekcja 3: `compute_passive_state`, helpery army/passive |
| `unit_helpers.py` | ~351 | Sekcja 7: `ability_cost`, `unit_default_weapons`, `normalize_roster_unit_loadout` |
| `role_totals.py` | ~471 | Sekcja 9: `roster_unit_role_totals` |
| `quote.py` | ~382 | Sekcja 8: dispatcher + `_procedural_quote` + `_yaml_quote` + `_both_assert_quote` + `_assert_quote_parity` — **SSOT core** |
| `roster.py` | ~127 | Sekcja 10: `roster_unit_cost`, `recalculate_roster_costs` |
| `errors.py` | ~30 | `RulesetParityError(AssertionError)` z polami `(path, proc_value, yaml_value, delta, tolerance)` |

**Reguła SSOT:** zanim dodasz logikę klasyfikacji / kosztów / walidacji w nowym miejscu — `grep` dla istniejących funkcji (`_classification_map`, `roster_unit_role_totals`, `calculate_roster_unit_quote`) i **wywołaj istniejącą**, nie replikuj.

**Circular imports w `costs/`:** jeśli nowy moduł importuje z `_engine`, a `_engine` importuje z nowego modułu — to jest **OK**, bo stałe/dataclassy są definiowane w `_engine` przed stubem `from .nowy_modul import`.

### Pakiet `app/services/rulesets/` — YAML backend (replika)

Wczytuje deklaratywny ruleset z `app/rulesets/v1/*.yaml` przez Pydantic v2 i liczy quoty niezależnie od oracle.

| Plik | Linie | Zawartość |
|------|-------|-----------|
| `models.py` | ~170 | Pydantic v2 frozen: `RulesetTables`, `RulesetAbility`, `RulesetManifest`, `TransportMultiplier`, `AbilityCosts`, `CostRecipeSpec`, `HandlerSpec`, `HandlerMatch` |
| `loader.py` | ~230 | `load_ruleset(version)` z `@lru_cache(maxsize=4)`, walidacja spójności wersji 3 plików YAML |
| `cost_functions.py` | ~640 | 13 czystych funkcji DSL prymitywów (`range_multiplier`, `ap_modifier`, `blast_cost`, `scale_by_tou` z 5 flagami, `base_model_cost` z `passive_cost_fn` injection, `_weapon_cost_yaml`, `_mistrzostwo_*`) + wrappery `weapon_cost_components_yaml`/`weapon_cost_yaml` |
| `dispatcher.py` | ~140 | `CostRecipe` (alias `CostRecipeSpec`) + `_REGISTRY` 9 fn DSL + `call_recipe()` + `passive_cost_dsl()` |
| `handlers.py` | ~400 | 6 handlerów (transport/open_transport/aura/mag/order_like/mistrzostwo) + `ability_cost_components_yaml()` jako YAML replika oracle dispatchera |
| `quote_yaml.py` | ~510 | `roster_unit_role_totals_yaml` — 1:1 port `role_totals.py` z YAML substytucjami. Konsumowane przez `quote.py:_yaml_quote()` |

Pliki YAML w `app/rulesets/v1/`:

| Plik | Zawartość |
|---|---|
| `tables.yaml` | 18 tabel/stałych (mirror `_engine.py:23-79`) |
| `abilities.yaml` | 87 definicji abilities (slug+name+type+description+value_*) |
| `ability_costs.yaml` | Cost DSL: 33 passive recipes + 7 fixed_by_slug + 4 fixed_by_desc + 6 handlers + `skip_in_default` |

**Inwariant czystości (CRITICAL):** `rulesets/*` NIE importuje z `costs/_engine`, `costs/abilities`, `costs/weapons` — oracle SSOT, którego YAML jest **niezależną repliką**. Wolno importować universal-string utils z `costs/primitives` (`ability_identifier`, `normalize_name`, `extract_number`, `lookup_with_nearest`, ...) oraz pure parsers z `costs/passive_state`/`costs/unit_helpers`. Naruszenie inwariantu = fałszywy parity check.

**Parity weryfikowane przez:**
- `tests/test_ruleset_parity.py` — 156 testów pod `both_assert` (100 cartesian + 55 manual + None-unit)
- `tests/yaml_backend/` — 93 testy mirrorujące passive/active/weapon/mistrzostwo pod `yaml`
- `tests/test_quote_performance_regression.py` — perf ratio yaml/procedural ≤ 1.30× (3 attempts × min)
- `make test-parity` — uruchamia oba sety pod odpowiednimi backendami

Detale: [ADR-0003](adr/0003-yaml-pydantic-format.md), [ADR-0004](adr/0004-cost-dsl.md).

## Game engine — `app/services/engine/` (Strumień B, B3 zamknięte 2026-05-30, B3.9 hardening zamknięty 2026-06-02)

Pakiet implementuje symulator bitwy 1v1 oparty o `SZOP_Rozjemca.md` (reguły) + `SZOP_Zdolnosci.md` (mechaniki 77 zdolności). **Pure functions + event sourcing** per [ADR-0010](adr/0010-event-sourced-battle-log.md) + [ADR-0011](adr/0011-rule-executor.md). Pareto MVP: oddział = koło, brak orientacji, ruch deklarowany (bez pathfindingu), LoS standardowy. 6 zdolności wykluczonych: `samolot/wrak/wysoki/zwrot/sterowany/zuzywalny` ([ADR-0008](adr/0008-pareto-mvp.md) + `app/rulesets/v1/b_mvp_exclusions.yaml`).

**B3.9 architecture hardening (2026-06-02)** zamknął 7 bug-fixów + 1 dead-code cleanup z post-B3 code review, dodał 2 moduły (`status.py`, `geometry.py`, `reducers.py`) + `ActivationContext` + `initial_toughness_snapshot` + weapons inventory + `ACTIVE_ABILITY_REGISTRY` + 3 nowe event types (StatusAdded/Removed/MeleeBalanceReset). Replay invariant ADR-0010 osiągnięty empirycznie (per-blob + round + score reconstruction z eventów). 3 nowe ADR-y: [ADR-0045](adr/0045-activation-context.md), [ADR-0046](adr/0046-event-sourced-mutations.md), [ADR-0047](adr/0047-weapons-inventory.md).

**Rules resync 2026-06** ([ADR-0048](adr/0048-rules-resync-2026-06.md), wątek `faza-b-rules-resync`) zsynchronizował engine z driftem zasad: **`Lokalizacja` enum** (`state.py`: ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY, pkt 26) na `UnitBlob.location`; **`wounds_eliminating: int`** licznik ran broni Zguba (pkt 26.d/27.a — model pokonany przy `wounds_eliminating>0` → ELIMINOWANY, nie wraca); **`MutexCollision` event** (14ty typ, mutex Przyszpilony↔Ufortyfikowany pkt 22.b/c); trigger Przegrupowania `delta_received > delta_dealt` (pkt 20.a via ActivationContext); Niebezpieczny teren per-oddział przez `_allocate_wounds_to_defender` (pkt 4.c.v). Koszt aur/rozkazów: formuła `T_eff = clamp(4/3×T, 8, 24)` w `rulesets/cost_functions.py` (`t_eff`/`aura_range_bonus`/`order_bonus`). Invariant `0 <= wounds_eliminating <= wounds_received`; każdy wipe zeruje oba liczniki. **B2 ORM impact:** `BattleEvent.payload_json` per unit +`location`+`wounds_eliminating`, `ModelKilled` +`eliminated`, `Shot/MeleeResolved` +`wounds_eliminating`.

### Mapa modułów (dependency graph)

```
                  loader (Strumień A)
                       │
                       ▼
            status ──► state ◄────── events ── (serializer JSON↔dataclass)
                       │              ▲
                       │              │
                  geometry             reducers ── (B3.9.d, ADR-0046 — auto-rejestracja
                       │                 │          przez __init__.py side-effect import)
       ┌───────────────┼──────────────┼─────────────────┐
       ▼               ▼              │                 │
     dice ──────►   los    ──────► prediction    interrupts (ADR-0015)
       │              │                ▲                 │
       │              │                │                 │
       └──────► combat ────────────────┴── effects ◄─────┘
                  │                       (passive + ACTIVE_ABILITY_REGISTRY,
                  ▼                        ADR-0015a kontratak, ADR-0047)
               phases  ── (setup/deployment/activation/round_end per pkt 7-21,
                  │       ActivationContext per ADR-0045)
                  ▼
              resolver  ── PUBLIC API: apply(state, action, dice) -> ResolverResult
```

| Moduł | LOC | Zakres |
|---|---|---|
| `status.py` **(B3.9.a)** | ~95 | `StatusFlag(str, Enum)` (Aktywowany/Wyczerpany/Przyszpilony/Ufortyfikowany) + module-level `STATUS_*` aliasy + idempotentne `add_status(blob, flag)`/`remove_status(blob, flag)`. Konsolidacja 3 kopii STATUS_* z effects/phases/combat. |
| `geometry.py` **(B3.9.b)** | ~175 | Pure prymityki: `distance` (math.hypot), `point_in_circle`, `segment_intersects_circle`, `segments_intersect`, **`circle_edge_distance`** (fix bug #4), `UNIT_CIRCLE_16` precomputed. Konsolidacja 4 kopii `_distance` z los/phases/combat. |
| `state.py` | ~340 | `UnitBlob` (4 kategorie ran per ADR-0014 + **`wounds_eliminating` licznik Zguby [ADR-0048]**, B3.9.e `melee_weapons`/`ranged_weapons` inventory), **`Lokalizacja` enum + `UnitBlob.location` [ADR-0048, pkt 26]**, `BattleState` (B3.9.c `initial_toughness_snapshot` frozen), `Position`, `TerrainCircle/Line`, `Objective`, `WeaponProfile` (przeniesiony z combat.py w B3.9.e), `apply_events` + `register_reducer` (event replay), `initial_toughness_for` helper, `build_initial_state` (parsuje `unit["weapons"]`, ZAPLECZE dla rezerw, raise `UnsupportedAbilityError` dla wykluczeń) |
| `events.py` | ~270 | **14 event types** (B3.0: `MoveExecuted/ShotResolved/MeleeResolved/ModelKilled/MoraleTestPassed/EffectApplied/InterruptTriggered/RoundEnded` + **B3.9**: `StatusAdded/StatusRemoved/MeleeBalanceReset/ObjectiveControlChanged/InitiativePassed` + **rules-resync 2026-06 [ADR-0048]**: `MutexCollision`; pola: `ModelKilled.eliminated`, `Shot/MeleeResolved.wounds_eliminating`) + `event_to_json` / `json_to_event` |
| `reducers.py` **(B3.9.d)** | ~250 | `@register_reducer` dla wszystkich 14 event types. Algorytm wound allocation w `_reduce_shot_resolved`/`_reduce_melee_resolved`/`_reduce_model_killed` mirror `combat._allocate_wounds_to_defender` (propagacja `location`/`wounds_eliminating`). Auto-rejestracja przez side-effect import w `__init__.py`. ADR-0046 proof-of-completeness ADR-0010. |
| `dice.py` | ~110 | `DeterministicDice(seed)` na `random.Random` (ADR-0012), `RollResult` z natural rolls, `roll_with_threshold` pełna semantyka pkt 1 (a/b/c/d) |
| `los.py` | ~175 | `check_los` 3-state (WIDZI/NIE_WIDZI/OSŁONA) z sampling N=16 (ADR-0043), Zasłaniający exception pkt 4.c.iii. **B3.9.b**: importuje primitive z `geometry.py`; `UNIT_CIRCLE_16` precomputed dla perf (16× math.cos/sin → 0 per call). |
| `prediction.py` | ~210 | Analytic binomial bez RNG (ADR-0044), `expected_damage(...) → DamageDistribution`, `would_see` hipotetyczny LoS. **Monte Carlo parity** ±3σ z combat.resolve_ranged_attack |
| `combat.py` | ~580 | `CombatResult` + `ChargeResult` + `resolve_ranged_attack` (3 fazy pkt 17 + osłona pkt 19) + `resolve_melee_attack` (z damage_balance pkt 20.c) + `resolve_charge_attack` (pkt 14.d + reactive kontratak ADR-0015a). **B3.9.b fix #4**: `circle_edge_distance` w `min_gap` (uwzględnia charger.radius). **B3.9.d**: emit `StatusAdded(Wyczerpany)` po kontrataku. **B3.9.e fix #7**: counter używa `defender.melee_weapons[0]` z fallback. Weapon abilities MVP: AP/Brutalny/Precyzyjny/Niezawodny/Podwójny |
| `effects.py` | ~340 | Per-hook passive registry (3 kategorie: defense/attack/weapon modifiers; morale-modifier usunięty 2026-06 — drift pkt 20.e, Nieustraszony binarny w `phases._regroup_test`) + **`_ACTIVE_ABILITY_REGISTRY`** (B3.9.e/ADR-0047) z `register_active_ability(slug)` dekoratorem + `get_active_ability(slug)` lookup. MVP passive: Cierpliwy/Tarcza (defense). Built-in active: pełen `discard_exhausted` + 6 stubów (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik). |
| `interrupts.py` | ~150 | `InterruptManager` z 4 zamkniętymi punktami per [ADR-0015](adr/0015-interrupt-points.md), `register_interrupt_handler(point, slug)` decorator. Strażnik (id 31) jako MVP stub |
| `actions.py` | ~80 | 6 Action types frozen (`DeploymentAction/ManeuverAction/DefendAction/ShootAction/ChargeAction/SpecialAction`) + `Action` Union alias |
| `phases.py` | ~530 | `setup_phase` (pkt 7+9), `deployment_round` (pkt 13), `activation_phase` (pkt 11.b dispatch). **B3.9.c**: `ActivationContext` frozen dataclass + `_build_activation_context` (delta `wounds_received_this_activation` per blob + `melee_combatants` frozenset) — `_regroup_test` używa delty zamiast cumulative (fix bug #1), defender szarży regroup-testuje w aktywacji chargera (fix #2), `damage_balance` reset na obu combatants (fix #5). **B3.9.d**: emit Status* + MeleeBalanceReset. **B3.9.e**: `_apply_special` redukcja do dispatcher-a `effects.get_active_ability`. |
| `resolver.py` | ~160 | **PUBLIC API**: `apply(state, action, dice) → ResolverResult` z walidacją (6 reguł IllegalActionError; m.in. Manewr `dist ≤ effective_move_inches`, pkt 15.a + Szybki/Wolny — Trudny/Niedostępny pkt 4.c → E4) + switch active_player pkt 8.a. Helpers `should_end_round` / `is_battle_over` |

### Event-sourced data flow

```
Player action ──► resolver.apply() ──► validate ──► phases.activation_phase()
                       │                                     │
                       │                                     ▼
                       │                            combat.resolve_*() ──► [BattleEvent...]
                       │                                     │
                       │                            phases._regroup_test()
                       │                                     │
                       ▼                                     ▼
              ResolverResult(state, events, next_sequence)  apply_events(state, events) → BattleState
                       │                                     │
                       ▼                                     ▼
            persistence.save_events() (B2)            replay path (audit/debug)
```

### Typowa orkiestracja (z ADR-0011)

```python
state = setup_phase(rosters, terrain, objectives, initiative_player=0)
state, events = deployment_round(state, deployment_actions)
while not is_battle_over(state):
    while not should_end_round(state):
        result = resolver.apply(state, action_from_player, dice)
        state = result.state
        save_events(result.events)  # do BattleEvent ORM (B2)
    state, end_events = round_end_phase(state)
    save_events(end_events)
```

### Persystencja event-store (B2 slice, ADR-0050, 2026-06-10)

`app/services/engine/persistence.py` — jedyny moduł `engine/` dotykający ORM (warstwa-granica; reszta silnika czysta). Dwie nowe tabele w `app/models.py`:
- **`battles`** (`Battle`): metadane gry (`p1/p2_user_id?`, `p1/p2_roster_id?`, `winner_user_id?`, `current_round`, `rng_seed`, `status`). Przebieg NIE tu — event-sourced.
- **`battle_events`** (`BattleEvent`, append-only): `event_type` + `payload_json` (`json.dumps(event_to_json(e))`) + `sequence`, `UniqueConstraint(battle_id, sequence)` (optimistic locking).

`save_events(session, battle_id, events, *, flush=True)` (transakcyjnie neutralny) + `load_events(session, battle_id, since=0)` (rekonstrukcja przez `json_to_event`). **Inwariant GATE** (`test_engine_persistence.py`): `apply_events(initial, load_events(...)) == live_state` — replay z bazy bit-perfect (rozszerza ADR-0010/0046 o warstwę DB). Brak Alembic — tabele addytywne przez `create_all`; zmiany kolumn istniejących tabel idą przez ręczny `_migrate_schema`. B2 addytywne slice'y po ADR-0050: `Unit.base_size_mm/base_shape`, auth/agent schema (`User.role`, `AgentToken.token_hash/scope_json`, `AgentAuditLog`), C1 helper `require_agent_scope(scope_name)` w `app/security.py` oraz owner-only endpointy tokenów `app/routers/agent_tokens.py`. Odroczone: `BattleInvite`, `BattleSnapshot` i konsumenci B4 API.

### Status B3 (zamknięte 2026-05-30) + B3.9 hardening (zamknięte 2026-06-02)

- **1337/1337 testów** (962 baseline + 282 B3 + 93 nowych w B3.9.a-e: 22 status, 27 geometry, 17 activation_context, 8 replay_invariant, 18 weapons_inventory + 1 regression test)
- **13 ADR-ów Accepted dla Strumienia B**: 0008/0010/0010a/0011/0012/0014/0015/0015a/0043/0044 + **B3.9: 0045/0046/0047**
- **Smoke replay**: `scripts/engine_smoke_replay.py` — minimal 2v2 battle, 39 events (10 typów reprezentowanych) + end-to-end **replay invariant assertion** (`apply_events(initial, all_events) == live_state` per-blob + round + score, EXIT 0)
- **GATE OPEN** per ADR-0010a (5/5 punktów) + **ADR-0010 spełnione empirycznie** (replay invariant test jako proof-of-completeness)
- **Consumers ready**: Strumień D (agenci-boty), B4 routers (po B2 ORM), B5 `szop_client`

**B3.9 hardening — 7 bugów + 1 cleanup + 5 dziur architektonicznych zamkniętych:**

| # | Bug / dziura | Faza B3.9 | ADR |
|---|---|---|---|
| #1 | `_regroup_test` używa cumulative `wounds_received` zamiast delty (pkt 20.a) | c (ActivationContext) | ADR-0045 |
| #2 | Defender szarży nie regroup-testuje w aktywacji chargera | c | ADR-0045 |
| #3 | `initial_toughness` z post-action proxy zamiast snapshotu | c | ADR-0045 |
| #4 | `charger.radius` ignored w `min_gap` szarży | b (geometry) | — |
| #5 | `damage_balance` reset tylko na actorze, nie obu combatants | c | ADR-0045 |
| #6 | Silent `status_flags` mutacje w combat (bypass eventów) + brak production reducerów | d (event-sourced) | ADR-0046 |
| #7 | Counter-attack używa broni atakującego zamiast `defender.melee_weapons[0]` | e (weapons inventory) | ADR-0047 |
| #8 | Geometry/STATUS_* duplikacja w 3 modułach (drift risk) | a (status) + b (geometry) | — |
| dziura A | brak rozróżnienia trwały stan / delta tej aktywacji | c | ADR-0045 |
| dziura B | event sourcing nie exhaustive (brak production reducerów) | d | ADR-0046 |
| dziura C | brak weapon inventory na UnitBlob | e | ADR-0047 |
| dziura D | geometry + constants duplikacja | a + b | — |
| dziura E | brak `_ACTIVE_ABILITY_REGISTRY` | e | ADR-0047 |

Pozostałe rozszerzenia (Furia/Impet/Maskowanie/Niewrazliwy/Przebijająca/Zabójczy + pełne implementacje 6 stubów aktywnych zdolności z B3.9.e) → przyrostowe PR-y bez zmian ADR-0011/0045/0046/0047 (architecture stable, registry patterns pozwalają dodawać bez modyfikacji dispatcher-ów).

## Gracze heurystyczni — `app/services/agents/` (Strumień D1, MVP 2026-06-09, ADR-0031)

Czysta warstwa decyzji botów **nad** publicznym API silnika — zero zmian w rdzeniu (`agents/` tylko czyta `engine/`). Silnik jest jednoakcyjny (`resolver.apply`); enumerację legalnych akcji i ocenę stanu trzyma warstwa agentów.

| Moduł | Zawartość |
|---|---|
| `base.py` | `Player(ABC)` (`choose_action(state, perspective) -> Action \| None`) + `legal_actions(state, perspective)` (enumerator kandydatów z `actions.Action`, pkt 14; Manewr/Szarża clampowane per-oddział przez `state.effective_move_inches` — pkt 15.a ± Szybki/Wolny, spójnie z walidacją resolvera) + selektory `own_active_units`/`enemy_units` |
| `random_player.py` | `RandomPlayer(seed)` — uniform z `legal_actions`, deterministyczny per seed |
| `greedy_player.py` | `GreedyPlayer` — depth-1 argmax: `prediction.expected_damage(...).mean` dla ataków, Δ`evaluate_state` dla ruchu |
| `minimax_player.py` (D4, 2026-06-18) | `MinimaxPlayer(seed)` — lookahead depth-2 (maximin): **faktycznie aplikuje** akcję przez `resolver.apply` (vs heurystyka greedy) → symuluje najlepszą odpowiedź wroga (1 ply) → ocenia `evaluate_state` po przeliczeniu kontroli (`_check_objective_control`, pkt 5.d). Deterministyczny rollout (`DeterministicDice(seed)` per aplikacja; pełny expectiminimax odłożony). `--players minimax`. Bije greedy/random, przegrywa z `priority` (cele poza horyzontem 1-ply) |
| `policy_eval.py` | `evaluate_state(state, perspective) -> float` — bilans HP + kontrola/bliskość celów (pkt 5) |
| `match.py` (ADR-0032) | **Headless pętla bitwy**: `run_match(state, players, dice) -> MatchResult` + `simulate_from_rosters(rosters, players, *, seed, deployment_zones=, ...)`. Orkiestruje `apply`+`round_end_phase`+alternacja inicjatywy (pkt 8); jedno wywołanie = jedna pełna gra (pkt 5.f winner). `deployment_zones` (D5) → boty wybierają pozycje startowe. Additive `on_decision` hook (telemetria ADR-0017, default None → zero zmian) |
| `deployment.py` (D5, 2026-06-15) | **Rozstawienie jako decyzja bota** (pkt 24/13.a): `DeploymentZone` (prostokąt strefy, parametr runnera — nie pole stanu) + `grid_positions`/`random_position_in_zone`/`grid_deployment_position` (proste strategie) + `GridDeploymentMixin` (boty deterministyczne) + `Player.choose_deployment(state, unit_id, zone)` (ABC, default=pozycja z roster; `RandomPlayer`=losowa-w-strefie). Walidacja: całe koło w strefie (MVP; Niedostępny + >1″ → E4) |
| `roster_adapter.py` (2026-06-16, prereq D3) | **Most ORM `Roster`→engine-dict**: `roster_to_engine_roster(roster, *, owner_player, models_mode, positions=) -> AdaptResult`. Reuse SSOT: `costs.normalize_range_value` (zasięg→cale), `costs.ability_identifier` (nazwa→slug), `default_weapon_loadout`. Filtruje `b_mvp_exclusions` (→`dropped_excluded`, inaczej `UnsupportedAbilityError`), oznacza `INCOMPLETE_ABILITIES` (→`inert_incomplete`). `models_mode`: `per_copy` (count blobów × typical_models) \| `aggregate`. Plus `roster_points(roster) -> float` (metryka D3 `win_rate/points`, reuse `costs.roster_unit_cost`). **Slice 1:** broń = domyślny loadout; auto-deploy/extra_weapons/attached-heroes deferowane |

**Konsumenci (planowane):** D2 `balance_simulate` (agreguje N `simulate_from_rosters` do win-rate), D3 `exploit_hunt` (przez `roster_adapter` + `roster_points`), D4 `minimax_player` (DONE). `run_match` to rdzeń **B5 `LocalClient.simulate`** (zob. niżej). Boty + runner testowalne headless w izolacji (81 testów: 26 graczy + 8 minimax D4 + 5 runner + 25 deployment D5 + 17 roster-adapter).

## Klient gry — `szop_client/` (Strumień B5, LocalClient 2026-06-14 + DB-backed 2026-06-19, ADR-0016)

Top-level pakiet (importowany jak `app`) — **stabilny seam** między konsumentami (C3 `simulate_engagement` MCP, D-stream, UI) a wewnętrznym silnikiem/runnerem. Konsument programuje wobec Protocolu, nie wobec modułów `engine/`/`agents/`.

| Moduł | Zawartość |
|---|---|
| `protocol.py` | `GameClient(Protocol)` (`create_battle`/`get_state`/`take_action`/`get_events`/`simulate` z `deployment_zones` D5) + `SimulationSummary` (frozen, win_rate/draw_rate/avg_rounds) |
| `local.py` | `LocalClient(session=None, user_id=None)` in-process — single-step play (rejestr bitew w pamięci, `apply_activation`) + batch `simulate` (deleguje do `simulate_from_rosters`); **ścieżka DB** `simulate_roster_ids`/`create_battle_from_roster_ids` (wczytuje `Roster` po id, adapter ORM→engine, ownership-scoped); `UnknownBattleError`/`RosterNotFoundError` |

**Dwie ścieżki:** (1) **engine-dict** (rostery jako dict 1:1 z `build_initial_state`); (2) **DB** (`LocalClient(session, user_id)` → `Roster` po id, read-only, adaptowane przez `roster_to_engine_roster`; `user_id` wymusza `owner_id==user_id`, wspólny `RosterNotFoundError` dla braku/cudzego → brak oracle). Sekwencja eventów single-step kontynuuje monotonicznie od rozstawienia (Ufortyfikowany pkt 13.c) — spójna z `persistence.save_events`. **Odłożone:** `HttpClient` (po B4 API; Protocol strukturalny → dołączy bez dziedziczenia), pakowanie `pip install -e`. 20 testów (`tests/test_clients_local.py`): determinizm, parity z runnerem/D2/ścieżką engine-dict, wierność `take_action == apply_activation`, DB-path (seeded in-memory SQLite, ownership scoping).

## Prezentacja — `scripts/battle_replay.py` (Strumień B6, CLI replay slice 2026-06-15, ADR-0013)

**Headless-first (ADR-0013):** silnik nie zależy od prezentacji; UI/replay to opcjonalni konsumenci publicznego API + strumienia eventów. `battle_replay.py` to **skrypt-liść** renderujący event-log bitwy na czytelny tekst.

| Element | Zawartość |
|---|---|
| `format_event(event) -> str` | Jednolinijkowa narracja PL per typ eventu (dispatch `_FORMATTERS` po nazwie klasy + fallback `repr` dla nieznanego typu) |
| `render_battle_log(events, *, header, winner) -> str` | Pełny log: grupowanie w rundy (delimiter `RoundEnded`), numeracja sekwencją, podsumowanie (cele końcowe pkt 5.f + rozkład typów + zwycięzca) |
| Źródła eventów | `--fixture`/`--map` (reuse `balance_simulate` SSOT + `simulate_from_rosters`) lub `--from-db <id>` (`persistence.load_events`, read-only) |

Rdzeń renderujący to czyste funkcje (bez I/O) — render **z samego event-logu** (bez rekonstrukcji stanu), więc tryb sim i `--from-db` dzielą ścieżkę (persystencja nie trzyma `initial_state`). **Odłożone (B6):** bogatszy widok stanu (po N-tym evencie via `apply_events`), SSE stream (po B4), canvas frontend. 16 testów (`tests/test_battle_replay.py`).

## Telemetria — `scripts/analyze_battle.py` (ADR-0017, slice z event-logu 2026-06-21)

Siostrzany skrypt-liść do `battle_replay.py`: ten sam event-log, ale zamiast narracji — **analityka** (markdown). Drugi konsument strumienia eventów (headless-first, ADR-0013).

| Element | Zawartość |
|---|---|
| `analyze_battle_log(events, *, owner_map, winner) -> BattleAnalysis` | Jednoprzebiegowa agregacja: `UnitStats` per oddział + `SideStats` per strona (gdy `owner_map`), timeline kontroli celów (pkt 5.d/8.c.ii), rozkład akcji + typów eventów, rozkład rzutów Przegrupowania (pkt 20) |
| `render_analysis(analysis, *, header) -> str` | Raport markdown: wynik (pkt 5.f) + tabele per strona/oddział + tekstowe słupki (`_bar`) |
| Źródła eventów | `--fixture`/`--map` (`simulate_from_rosters`, `owner_map` z `final_state`) lub `--from-db <id>` (`persistence.load_events`, read-only; bez `owner_map` → degradacja do per-oddział) |

**Scope (slice):** pełny ADR-0017 (structlog w `resolver`/`persistence` + pliki `data/*_metrics/*.jsonl`) odłożony — wymaga zmian w hot-path silnika; ten skrypt czyta sam event-log. 27 testów (`tests/test_analyze_battle.py`, incl. `--games` agregat + `--json`).

### Telemetria decyzji bota — `scripts/analyze_agents.py` (slice `data/agent_metrics`, 2026-06-22)

Trzeci skrypt-liść telemetrii — metryki **per bot** (nie per bitwa). Mierzy KOSZT i JAKOŚĆ decyzji **per AKCJĘ** (opcja A, ADR-0017 — aktywacja może mieć 2 akcje pkt 11.b.iv): `decision_time_ms` (wall-clock wyboru akcji: `choose_action` dla 1., `continue_activation` dla kolejnych) + `decision_quality_score` (Δ `evaluate_state` przed/po akcji, samoocena bota wg SSOT `policy_eval`). Spójny zakres `action_mix`/`decision_time_ms`/`quality`. Agregat per agent (śr./mediana/max czas, śr. jakość, % decyzji poprawiających, miks akcji; schema `szop.agent_metrics/v1`).

Instrumentacja przez **additive hook `on_decision`** w `match.run_match`/`simulate_from_rosters` (`OnDecision = Callable[[perspective, unit_id, action, state_before, state_after, elapsed_ms], None]`, default `None` → zero zmian zachowania, B7 golden bez zmian). Wołany dla **każdej akcji aktywacji**: runner koreluje czas wyboru z czysto-obserwacyjnym hookiem `resolver.apply_activation(on_action=...)` przez helper `_apply_activation_with_telemetry` (czas mierzony tam, gdzie akcja wybierana; silnik raportuje stany before/after per akcja). To pierwszy szew telemetrii czasowej — gotowy też pod live-instrumentację B4. `agent` = nazwa bota (konta DB `agent_user_id` + live-emission produkcyjna odłożone do B2 auth, ADR-0030 cz. 2). 21 testów (`tests/test_analyze_agents.py`) + hook per-akcja w `tests/test_agents_match.py` / `tests/test_engine_multi_action.py`.

## Frontend JS — mapa modułów

Aktualna mapa zależności i lista call sites po podziale `app/static/js/app.js`: `docs/frontend_js_modules.md`.

**Pozostałe w `app.js`** (nie wydzielone): `ROSTER EDITOR CLOSURE`, `WEAPON PICKER`, `ABILITY PICKER`, `ARMORY WEAPON TREE`, `WEAPON INHERITANCE PANEL`. Detale: `docs/app-js-guide.md`.

## Hot path / endpoint'y krytyczne

Te endpointy mają największy wpływ na user-perceived performance — każda zmiana wymaga performance gate (`docs/planning.md`):

- `/quote` — kalkulacja kosztu rozpiski (batch dla wszystkich oddziałów na liście).
- `/rosters/{id}` — render strony rozpiski (SSR + post-load batch quote).
- Pętle renderujące strony z listą oddziałów.

Baseline wydajności i benchmarki: `docs/PERFORMANCE.md`.

## Konwencja `include_item_costs`

Badge-only calls do `/quote` zawsze przekazują `include_item_costs: false`. Tylko **dedykowany quote aktywnego oddziału** w `handleStateChange` przekazuje `true`. Naruszenie tej reguły przywróci wielokrotnie wolniejsze badge refresh.
