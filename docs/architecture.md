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
propozycje przez `GET /agent_proposals`, czyta pojedynczą przez `GET
/agent_proposals/{id}`, zatwierdza `POST /agent_proposals/{id}/approve` albo
odrzuca `POST /agent_proposals/{id}/reject` (cudza/nieistniejąca = 404).
Ogólna decyzja nadal zapisuje tylko status i audit. Dedykowane
`POST /agent_proposals/battle-actions` (ADR-0024) wymaga jednocześnie
`battle:read` + `agent_proposals:create`, waliduje bez zapisu zamrożone
`battle_id` + `expected_sequence` + pełny `szop.action/v1`, a approval ownera
wykonuje tę akcję natychmiast. Propozycje wykonawcze mają statusy
`pending/executed/rejected/stale`; payload pozostaje niezmienny, a osobne
`result_json` przechowuje sequence wynikowe albo konflikt stale.
`app/static/js/modules/agent_proposals.js` renderuje na stronie głównej panel
owner-only approval UI: fetch listy, statusy, payload w `<details>` oraz akcje
`Zezwól i wykonaj`/`Odrzuć` wywołujące endpointy approve/reject oraz pokazuje
trwały wynik wykonania albo stale.
Pierwszy konsument B4 agent-scope to `app/routers/battles.py`: read-only
`GET /battles/{id}` zwraca metadane bitwy + `latest_sequence`,
`GET /battles/{id}/events?since=N` zwraca event-log, a wersjonowany
`GET /battles/{id}/state` zwraca bieżący `BattleState` z `sequence_at` bez
wewnętrznego RNG. Endpointy dopuszczają
sesję gracza albo bearer token ze scope `battle:read`, mapując agenta na
`owner_user_id`. Dostęp do bitwy jest participant-scoped
(`p1_user_id`/`p2_user_id`), a cudza albo nieistniejąca bitwa zwraca 404.
Bearer path używa standardowego audytu `AgentAuditLog`. Addytywny write-slice
`POST /battles` tworzy sandboxową bitwę dla ownera dwóch własnych rosterów
(`battle:create` dla agenta), zapisuje metadane `Battle`, startowy event-log
rozstawienia oraz spójny checkpoint stanu+RNG w jednej transakcji; create response zawiera addytywny
`adaptation_report` p1/p2 z raportu `roster_to_engine_roster`
(`dropped_excluded`, `inert_incomplete`, `deferred_attached_heroes`), a GET
metadata nie rekonstruuje tego raportu. `POST /battles/simulate` uruchamia
read-only sandbox batch dwóch własnych rosterów (`battle:simulate`, limit 50
gier, tylko boty `fast` z rejestru) na app-level mapach i botach, zwracając
agregat wyników bez zapisu `Battle` ani eventów. Pierwszy klient tego kontraktu
to `szop_client.HttpClient`:
`get_battle_metadata` odpytuje metadane bitwy, `get_events` odpytuje polling
endpoint i deserializuje payload przez `json_to_event`, `get_state` zwraca
domenowy `BattleState` przez bezpieczny wersjonowany codec, a `simulate_roster_ids`
odpytuje sandbox simulation i zwraca `SimulationSummary`. Lokalny
`mcp_server` jest klientem tego samego publicznego API: nie importuje ORM,
`SessionLocal` ani `app.db` i nie czyta `data/szop.db`.
Write slice B4 `POST /battles/{id}/actions` (ADR-0054) ma osobny scope
`battle:act`. Przyjmuje obowiązkowy `expected_sequence` i jedną akcję w
wersjonowanym formacie `szop.action/v1` (`ManeuverAction`, `DefendAction`,
`ShootAction`, `ChargeAction`, `SpecialAction` wraz z `Position` i
`WeaponProfile`). Principal musi być uczestnikiem bitwy oraz kontrolować stronę
`owner_player` aktora; ten sam owner przypisany do obu stron sandboxu może
kontrolować obie. Endpoint wznawia wyłącznie bieżący checkpoint state+RNG,
deleguje do `resolver.apply`, opcjonalnie domyka rundę istniejącymi helperami i
w jednym commicie zapisuje ciągłe eventy, dokładnie jeden checkpoint oraz
metadane `Battle`. Odpowiedź zawiera nowy wersjonowany stan bez RNG i deltę
eventów; conflict/race zwraca 409 po rollbacku, payload/akcja nielegalna 422.
Wspólna orkiestracja `app/services/battle_actions.py` obsługuje także approval
consent-gated (ADR-0024), dzięki czemu obie ścieżki dzielą walidację,
checkpoint/RNG i atomowy zapis zamiast duplikować logikę routerów.

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

`app/services/engine/persistence.py` — jedyny moduł `engine/` dotykający ORM (warstwa-granica; reszta silnika czysta). Trwałe tabele w `app/models.py`:
- **`battles`** (`Battle`): metadane gry (`p1/p2_user_id?`, `p1/p2_roster_id?`, `winner_user_id?`, `current_round`, `rng_seed`, `status`). Przebieg NIE tu — event-sourced.
- **`battle_events`** (`BattleEvent`, append-only): `event_type` + `payload_json` (`json.dumps(event_to_json(e))`) + `sequence`, `UniqueConstraint(battle_id, sequence)` (DB-level optimistic locking fallback).
- **`battle_checkpoints`** (`BattleCheckpoint`, ADR-0053): pełny, wersjonowany
  `BattleState` + stan `DeterministicDice` przy `sequence_at`, z unikalnością
  `(battle_id, sequence_at)`. Addytywna tabela przez `create_all`, bez Alembic.

`save_events(session, battle_id, events, *, flush=True, expected_latest_sequence=None)` (transakcyjnie neutralny) + `load_events(session, battle_id, since=0)` (rekonstrukcja przez `json_to_event`) + `latest_event_sequence(session, battle_id)`. `POST /battles/{id}/actions` (ADR-0054) przekazuje ostatni widziany sequence do `save_events(..., expected_latest_sequence=N)`: helper rzuca `BattleEventSequenceConflict` jeśli log urósł i wymaga ciągłego ogona eventów od `N+1`; `UniqueConstraint` nadal broni przed wyścigiem między sprawdzeniem i INSERT-em. `save_checkpoint`/`load_latest_checkpoint` (ADR-0053) nie commitują i uznają checkpoint za bieżący wyłącznie przy `sequence_at == latest_event_sequence`; zapisują/odtwarzają wersjonowany `BattleState` i RNG bez `pickle`. **Inwariant GATE** (`test_engine_persistence.py`): `apply_events(initial, load_events(...)) == live_state` — replay z bazy bit-perfect (rozszerza ADR-0010/0046 o warstwę DB). Brak Alembic — tabele addytywne przez `create_all`; zmiany kolumn istniejących tabel idą przez ręczny `_migrate_schema`. B2 addytywne slice'y po ADR-0050: `Unit.base_size_mm/base_shape`, auth/agent schema (`User.role`, `AgentToken.token_hash/scope_json`, `AgentAuditLog`), C1 helper `require_agent_scope(scope_name)` w `app/security.py` oraz owner-only endpointy tokenów `app/routers/agent_tokens.py`. B4 `POST /battles` zapisuje `Battle`, startowy event-log i checkpoint w jednej transakcji; participant-scoped `GET /battles/{id}/state` zwraca publiczny stan bez RNG. Odroczone: `BattleInvite` i endpointy spoza pojedynczej akcji (interrupts/replay).

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
| `maps.py` (2026-07-10) | **SSOT generowanych map bitew** dla app/routerów i skryptów: `BattleFixture`, `build_map`, `MAP_BUILDERS`, `DEFAULT_DEPLOYMENT_ZONES`. Wydzielone z `scripts/balance_simulate.py`; skrypt re-eksportuje stare nazwy, więc konsumenci `bsim.*` pozostają kompatybilni. |
| `roster_adapter.py` (2026-06-16, prereq D3) | **Most ORM `Roster`→engine-dict**: `roster_to_engine_roster(roster, *, owner_player, models_mode, positions=) -> AdaptResult`. Reuse SSOT: `costs.normalize_range_value` (zasięg→cale), `costs.ability_identifier` (nazwa→slug), `default_weapon_loadout`. Filtruje `b_mvp_exclusions` (→`dropped_excluded`, inaczej `UnsupportedAbilityError`), oznacza `INCOMPLETE_ABILITIES` (→`inert_incomplete`). `models_mode`: `per_copy` (count blobów × typical_models) \| `aggregate`. Plus `roster_points(roster) -> float` (metryka D3 `win_rate/points`, reuse `costs.roster_unit_cost`). **Slice 1:** broń = domyślny loadout; auto-deploy/extra_weapons/attached-heroes deferowane |
| `registry.py` | **SSOT klasyfikacji botów** (tagi `useful`/`reference`, `fast`/`expensive`): `BOT_SPECS` + `bot_kinds(*tags)`/`has_tag`/`ALL_KINDS`. Czyste dane; konstrukcja botów → `factory.py` |
| `factory.py` (2026-07-07) | **SSOT konstrukcji botów** (wydzielone z `scripts/balance_simulate.py` do warstwy `app` — importowalne przez router B4): `make_player(kind, seed) -> Player` (dispatch po nazwie; alias `claude`→`ClaudeV1Player`) + `PLAYER_KINDS` (lista konstrukcyjna) + `PLAYER_SEED_OFFSET` (rozłączny seed decyzji P1, finding F2). `balance_simulate` re-eksportuje (wsteczna kompat `bsim.*`); drift-guard rejestr↔fabryka w `test_agents_factory.py` |

**Konsumenci (planowane):** D2 `balance_simulate` (agreguje N `simulate_from_rosters` do win-rate), D3 `exploit_hunt` (przez `roster_adapter` + `roster_points`), D4 `minimax_player` (DONE). `run_match` to rdzeń **B5 `LocalClient.simulate`** (zob. niżej). Boty + runner testowalne headless w izolacji (95 testów: 26 graczy + 8 minimax D4 + 5 runner + 25 deployment D5 + 17 roster-adapter + 14 factory netto).

## Klient gry — `szop_client/` (Strumień B5, LocalClient 2026-06-14 + DB-backed 2026-06-19 + HttpClient read-only 2026-07-02/03, ADR-0016)

Top-level pakiet (importowany jak `app`) — **stabilny seam** między konsumentami (C3 `simulate_engagement` MCP, D-stream, UI) a wewnętrznym silnikiem/runnerem. Konsument programuje wobec Protocolu, nie wobec modułów `engine/`/`agents/`.

| Moduł | Zawartość |
|---|---|
| `types.py` | lekkie frozen typy `SimulationSummary` oraz `BattleStateCheckpoint` (`battle_id`, `sequence_at`, schema/version, domenowy state; adnotacja state bez runtime importu silnika/ORM) |
| `protocol.py` | `GameClient(Protocol)` (`create_battle`/`get_state`/`take_action`/`get_events`/`simulate` z `deployment_zones` D5), re-eksportuje `SimulationSummary` dla kompatybilności |
| `local.py` | `LocalClient(session=None, user_id=None)` in-process — single-step play (rejestr bitew w pamięci, `apply_activation`) + batch `simulate` (deleguje do `simulate_from_rosters`); **ścieżka DB** `simulate_roster_ids`/`create_battle_from_roster_ids` (wczytuje `Roster` po id, adapter ORM→engine, ownership-scoped); `UnknownBattleError`/`RosterNotFoundError` |
| `http.py` | `HttpClient(base_url, token)` — metadane/eventy/state/create/simulate, publiczne odczyty reguł/zdolności, `take_action` oraz consent-only `propose_battle_action`; publiczny `get_state_checkpoint()` dekoduje jeden spójny GET state+sequence, `get_state()` deleguje, a bezpośredni zapis używa tej samej metody bez cache (ADR-0054/0024) |
| `wire.py` | publiczne lekkie projekcje checkpointu/eventów do stabilnego JSON; walidują `sequence > since`, ścisłą kolejność i odrzucają NaN/Infinity przez `allow_nan=False` |

`szop_client.__init__` ładuje publiczne symbole leniwie, więc konsument
HTTP-only nie uruchamia importów `LocalClient`, kosztów, ORM ani konfiguracji DB.

**Ścieżki:** (1) **engine-dict** (rostery jako dict 1:1 z `build_initial_state`); (2) **DB** (`LocalClient(session, user_id)` → `Roster` po id, read-only, adaptowane przez `roster_to_engine_roster`; `user_id` wymusza `owner_id==user_id`, wspólny `RosterNotFoundError` dla braku/cudzego → brak oracle); (3) **HTTP** (`HttpClient` dla metadata/events/state/create/simulate, `lookup_rule`, `explain_ability`, pojedynczego `take_action` oraz `propose_battle_action`). Bezpośrednia akcja ma optimistic precondition pobierane świeżym GET-em, bez cache; propozycja przyjmuje jawny zamrożony sequence i nie wykonuje GET ani zapisu bitwy. Sekwencja eventów single-step kontynuuje monotonicznie od rozstawienia i obejmuje automatyczny koniec rundy wskazany przez engine. **Odłożone:** HTTP continuation/multi-action callback, interrupts, pakowanie `pip install -e`. Testy klienta (`tests/test_clients_local.py` + `tests/test_clients_http.py`): determinizm, parity z runnerem/D2/ścieżką engine-dict, parity `HttpClient.take_action(..., continuation=None)` z `LocalClient`, DB-path, URL/header/error handling i ścisłe dekodowanie state/event delta/propozycji/odczytów wiedzy.

## Publiczne odczyty reguł i zdolności (C3, 2026-07-16)

Router `app/routers/reference.py` publikuje dwa endpointy bez mutacji i bez DB:
`GET /rules/lookup` oraz `GET /abilities/explain`. Pierwszy korzysta wyłącznie
z `app/services/rule_lookup.py`, który czyta stały kanoniczny
`app/static/docs/SZOP_Rozjemca.md`; parametr ścieżki ani nazwy pliku nie jest
częścią kontraktu. Drugi deleguje do `app/services/ability_lookup.py`, a ten do
katalogu SSOT `app.data.abilities`. Te same serwisy są używane przez istniejące
CLI, więc parser reguł i resolver zdolności nie mają alternatywnej implementacji.

Oba kontrakty mają jawne schemy v1, identyfikują logiczne źródło bez ujawniania
ścieżki systemowej i ograniczają query/rozmiar wyników. `HttpClient` dekoduje je
ściśle, a MCP wykonuje dokładnie jedno wywołanie odpowiedniej metody klienta.
Publiczne pliki reguł były już dostępne statycznie; endpointy nie wprowadzają
nowego scope ani danych ownera.

## Lokalny serwer MCP — `mcp_server/` (C1/C3, 2026-07-15/16, ADR-0021/0024)

`mcp_server/server.py` uruchamia stabilną linię v1 MCP Python SDK przez stdio i
publikuje sześć read-only tools (`simulate_engagement`, `lookup_rule`,
`explain_ability`, `get_battle_metadata`, `get_battle_state`,
`get_battle_events`) oraz jeden
consent-gated write request `propose_battle_action`. Każdy deleguje do
odpowiadającej publicznej metody wstrzykniętego `HttpClient`; MCP nie ma
alternatywnej ścieżki in-process, własnego transportu HTTP ani bezpośredniego
dostępu do bazy. Metadata/state/events konsumują backendowe `battle:read`, a
symulacja `battle:simulate`; propozycja wymaga `battle:read` +
`agent_proposals:create`, ale nie `battle:act`. Backend pozostaje SSOT
walidacji tokenów/scope'ów.
Stan pochodzi z jednego publicznego checkpointu state+`sequence_at` i nie
zawiera RNG. Eventy zachowują kolejność, filtr `since` i stabilny
`last_sequence` także dla pustej delty.

`mcp_server/config.py` czyta URL z `SZOP_API_URL` (domyślnie
`http://127.0.0.1:8000`) oraz opcjonalny bearer token z `SZOP_API_TOKEN`.
Token ma wyłączony `repr` i nie jest dołączany do komunikatów błędów/logów;
trafia wyłącznie do nagłówka `Authorization` budowanego przez `HttpClient`.
Granica błędów MCP redaguje też bearer/`Authorization`, zachowując status
`HttpClientError`. Brak bezpośredniego write toola, resources/prompts,
semantycznego RAG i ogólnego executora; publiczne `HttpClient.take_action` nie
jest tool-em MCP. Warstwa dense C2.3 opisana niżej pozostaje offline i nie jest
importowana ani rejestrowana przez runtime MCP.

### Deterministyczny korpus C2.1 (2026-07-17)

`mcp_server/indexer.py` jest czystą, offline'ową warstwą przygotowania korpusu.
Czyta tylko stałą allowlistę `SZOP_Rozjemca.md` + `SZOP_Zdolnosci.md`; publiczne
funkcje i CLI nie przyjmują ścieżek źródłowych ani wyjściowych. Rozwiązanie nie
importuje ORM/DB i nie jest podpięte do runtime MCP, HTTP ani hot path aplikacji.

Chunking zachowuje pełne punkty reguł i sekcje Markdown jako preferowane
granice semantyczne. Parametry są jawne: cel 300 słów, 50 słów overlapu,
tolerancja 180–450 oraz atomowy blok do 400 słów. Manifest
`build/rag_corpus.jsonl` ma stałą kolejność, stabilne ID, `source`, nagłówki,
wykryte referencje i SHA-256 treści. `mcp_server/evaluation.py` waliduje stały
30-rekordowy `rag_evaluation.jsonl` i wymaga pokrycia każdego
`source`/`ref`/`anchor` przez korpus. To corpus-coverage gate, nie metryka
retrievalu; embeddingi, vector store i recall@5 pozostają poza C2.1.

### Leksykalny retrieval BM25 C2.2 (2026-07-17)

`mcp_server/search.py` buduje mały indeks `rank-bm25` bezpośrednio z publicznego
`indexer.build_corpus()`. Deterministyczny tokenizer stosuje Unicode NFKD,
case-folding, usuwanie znaków diakrytycznych i podział po interpunkcji. Pole
indeksowane obejmuje treść oraz jawnie ważone metadane chunku: stałą nazwę
źródła, nagłówki i referencje. Remisy zachowują kolejność korpusu C2.1.
Publiczne `search(query, limit)` waliduje query do 200 znaków i limit 1–10,
zwraca ograniczony tekst oraz skończony JSON-safe score. CLI domyślnie zachowuje
BM25 i przyjmuje wyłącznie `--mode`, `--query` i `--limit`; nie przyjmuje ścieżki
indeksu ani źródła.

`mcp_server/evaluation.py --retrieval` uruchamia top-5 dla każdego z dokładnie
30 niezmienionych rekordów i uznaje hit tylko wtedy, gdy zwrócony chunk spełnia
jednocześnie istniejące `expected.source`, `expected.ref` i `expected.anchor`.
Zmierzony baseline C2.2 to **24/30, recall@5 = 0,800**. Jest to wyłącznie
leksykalny slice offline: bez ORM/DB/HTTP, bez podpięcia do runtime MCP i bez
wpływu na hot path aplikacji.

### Trwały dense store C2.3 (2026-07-17, ADR-0022/0023)

`mcp_server/embeddings.py` jest małym, leniwym adapterem jednego modelu:
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` w przypiętej
rewizji `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Wymiar 384, CPU, batch 16,
normalizacja L2 oraz walidacja count/dimension/finite są częścią kontraktu.
Import modułu nie importuje `sentence_transformers`, `transformers` ani
`torch`; ciężki stos jest ładowany dopiero przy realnym embeddingu.

Model może pobrać wyłącznie osobna komenda do stałego, gitignored
`build/models`. Wszystkie zwykłe embeddingi, rebuild i query przekazują
`local_files_only=True`, stały model ID, rewizję, backend `torch`, `device=cpu`
i `trust_remote_code=False`. Publiczne API/CLI nie przyjmuje model ID, rewizji
ani ścieżki cache.

`mcp_server/vector_store.py` przechowuje indeks wyłącznie w
`build/rag_vectors.sqlite`. Zwykła tabela `chunks` zachowuje stabilne `chunk_id`
i JSON-safe metadane wyniku, `index_metadata` przechowuje wersję schematu,
model/revision, wymiar, normalizację, wersję sqlite-vec, count i SHA-256 całego
manifestu C2.1, a `rag_vectors` jest tabelą `vec0` z 384-wymiarowym float32 i
cosine distance. Rozszerzenie jest ładowane tylko przez oficjalny binding
`sqlite_vec.load()`; brak ścieżki rozszerzenia od użytkownika.

Rebuild najpierw embeduje cały korpus, następnie buduje bazę tymczasową w tym
samym `build/`, używa `synchronous=FULL`, zamyka i synchronizuje plik, waliduje
integrity, wszystkie metadane/chunki oraz 36 wymiarowych i skończonych wektorów,
a dopiero potem wykonuje `os.replace`. Błąd przed replace usuwa temp i zachowuje
poprzedni indeks. `check_index()` wykrywa stale corpus/model bez ładowania
MiniLM. `dense_search()` jest wyłącznie wewnętrznym API offline; pobiera
wszystkie obecne 36 odległości z `vec0` i sortuje `(distance, chunk_id)`, dzięki
czemu remisy są stabilne i nie zależą od kolejności zwróconej przez sqlite-vec.
Warstwa pozostaje bez połączenia z HTTP i discovery MCP.

### Deterministyczny hybrid i benchmark C2.4 (2026-07-18, ADR-0026)

Publiczne wewnątrz pakietu `hybrid_search(query, limit)` zachowuje limity C2.2 i
deleguje do istniejących `search()` oraz `vector_store.dense_search()`. Weighted
RRF łączy pule top-5 ze stałymi `k=60`, wagą BM25 `2,0` i dense `1,0`; nie używa
raw score obu metod. Deduplikacja jest po `chunk_id`, remisy zachowują kolejność
korpusu C2.1, a źródło, nagłówki, referencje i tekst są pobierane z
`indexer.build_corpus()`, nie z rekordów gałęzi. Wynik zawiera skończony score i
diagnostyczny rank/wagę/wkład każdej gałęzi, bez ścieżek lokalnych.

Parametry wybrano z jawnej siatki 8 wariantów (pula 5/10, `k` 20/60, waga BM25
1/2 przy dense 1). Na niezmienionych 30 rekordach tylko top-5 z wagą 2:1 nie
był gorszy od BM25; top-10 2:1 dawał 22/30, a equal-weight 21/30. Wspólny matcher
`source+ref+anchor` zmierzył finalnie BM25 **24/30 (0,800)**, dense **8/30
(0,267)** i hybrid **24/30 (0,800)**; brak przypadków naprawionych lub
pogorszonych przez hybrid względem BM25. `--retrieval` pozostaje kompatybilnym
benchmarkiem BM25, a `--hybrid` raportuje wszystkie metody, każdy case, czasy i
osobny gate hybrid 0,800. Kod nadal jest wyłącznie offline: brak importu i
rejestracji w `mcp_server.server`, zmian HTTP/DB/szop_client oraz wpływu na hot
path aplikacji.

### Procesowy lifecycle MiniLM C2.5 (2026-07-18, ADR-0027)

`mcp_server.embeddings.get_default_embedder()` jest leniwym, procesowym SSOT dla
domyślnego fixed MiniLM. Fabryka ma lock chroniący concurrent first use, a sam
adapter osobno chroni konstrukcję modelu i serializuje `encode`. Serializacja
jest świadoma: biblioteka nie gwarantuje thread-safe inference na jednej
instancji. Wyjątek ładowania nie zapisuje uszkodzonego stanu i może zostać
ponowiony. Nie są cache'owane teksty ani wektory użytkownika.

Domyślne `rebuild_index()` i `dense_search()` reuse'ują singleton; jawny
`Embedder` nadal omija go całkowicie. `download_model()` zawsze tworzy osobny
adapter dopuszczający sieć i nie zatruwa singletonu offline. Stałe modelu,
rewizji, cache, CPU, `local_files_only=True` i `trust_remote_code=False` nie
zmieniły się. Importy `mcp_server.server`, `search` i `vector_store` nadal nie
ładują sentence-transformers/transformers/torch.

`mcp_server.retrieval_benchmark` mierzy w jednym procesie sześć stałych hybrid
queries po zgodnym `check_index()` i raportuje JSON-safe cold, warm p50/p95,
total oraz rankingi. Warm p50 spadło z 2,610 s do 0,080 s (~32,5×), a pełny
benchmark nadal daje hybrid 24/30 z identycznymi hitami per-case. Warstwa
pozostaje offline; wrappery MCP/API są osobnym, otwartym etapem.

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
