# ADR-0011 — Rule executor: hardcoded klasy/funkcje na MVP

- **Status:** Proposed (promote do Accepted po B3.7 z empirycznymi wnioskami)
- **Data:** 2026-05-30 (Proposed)
- **Kontekst:** Strumień B, Faza B3 (`docs/handoffs/HANDOFF_faza-b-3-executor.md`). Rule executor (`app/services/engine/{dice,los,prediction,combat,effects,interrupts,phases,resolver}.py`) implementuje mechaniki SZOP. Pytanie projektowe: czy zasady są **hardcoded w Pythonie** (klasy / funkcje per akcja / efekt), czy **deklaratywne w YAML** z generic executor (jak `app/services/rulesets/` dla kosztów)?

## Decyzja

**Hardcoded klasy/funkcje w `app/services/engine/`** dla MVP — każda akcja (pkt 14) i każda aktywna zdolność z mapowaniem (B3.0.1 audit) ma dedykowaną funkcję w Pythonie. Zasady gry rozproszone po `combat.py` / `effects.py` / `phases.py` / `interrupts.py` zgodnie z domeną.

### Struktura

| Moduł | Zakres | Wejście / Wyjście |
|---|---|---|
| `state.py` | Substrate: `UnitBlob`, `BattleState`, `Position`, terrain, `apply_events`, `register_reducer`, `UnsupportedAbilityError`, `compute_radius_inches`, `build_initial_state` | (immutable types + pure builders) |
| `events.py` | 8 event types + serializer `event_to_json` / `json_to_event` | (immutable types) |
| `dice.py` (B3.1) | `DeterministicDice(seed)`, `roll_d6`, `roll_with_threshold` | seed → kości |
| `los.py` (B3.2) | `check_los(attacker, target, terrain, N=16) → LoSState` | sampling N=16 |
| `prediction.py` (B3.3) | `expected_damage(...) → DamageDistribution` | analityczny binomial CDF (bez RNG) |
| `combat.py` (B3.4) | `resolve_ranged_attack`, `resolve_melee_attack` — 3 fazy + reactive window | (state, attacker, target, weapon, dice, ruleset, terrain) → CombatResult |
| `effects.py` (B3.5) | `EFFECT_REGISTRY: dict[slug, Callable]` — pasywne i aktywne | (UnitBlob, context) → UnitBlob |
| `interrupts.py` (B3.5) | `InterruptManager` — 4 zamknięte punkty (ADR-0015) | (state, interrupt_point) → events |
| `phases.py` (B3.6) | `setup_phase`, `deployment_round`, `activation_phase`, `round_end_phase` | (state, action, ruleset) → (state, events) |
| `resolver.py` (B3.7) | `apply(state, action, dice, ruleset, terrain)` — top-level dispatcher | polimorficzny Action |

### Cechy

- **Każda funkcja w `app/services/engine/` jest pure.** Zero DB access, zero `print`, zero mutation. Argumenty in → wynik out.
- **Eventy jako jedyna persistowana strona.** Wszystko inne (UnitBlob, BattleState, terrain) rekonstruowane z `apply_events(initial, events)` (ADR-0010).
- **Dispatch polimorficzny przez Action class hierarchy** (Pydantic discriminated union) w `resolver.apply()`. Akcje 14.a-d mają hardcoded handlery; 14.e dispatchuje przez `effects.ACTIVE_ABILITY_REGISTRY` per slug.
- **Czytanie YAML (abilities/tables/b_mvp_exclusions) jest read-only** — `load_ruleset()` + `load_b_mvp_exclusions()` zwracają immutable Pydantic models.

### Co NIE robimy w MVP

- **Generic YAML rule executor** (jak `app/services/rulesets/dispatcher.py` dla kosztów). Zasady gry są bogatsze niż koszty — wymagałyby mini-DSL z control flow (`if/then`, loops, state queries). Premature.
- **Plugin architecture** — żaden moduł nie jest "pluggable" przez konfigurację. Każda nowa zdolność = osobny PR z funkcją w `effects.py` lub `interrupts.py`.
- **Reflection / introspection** — engine nie inspekcjonuje typu Action w runtime poza dispatcherem `resolver.apply`.

## Konsekwencje

**Pozytywne:**
- **Czytelność.** Implementacja zasady = konkretna funkcja, łatwa do nawigacji.
- **Testowalność.** Każda funkcja w izolacji (pure). Brak globalnego state machine.
- **Performance.** Direct function call bez warstwy interpretacji DSL.
- **Type safety.** Pełne type hints + mypy/Pylance autocomplete.
- **Refactor.** Zmiana mechaniki = edycja Pythona z testem; nie wymaga zmiany YAML schema + parsing logic.
- **Mapping audit (B3.0.1)** wykonalny — 12 aktywnych zdolności → 12 entries w `ACTIVE_ABILITY_REGISTRY`.

**Negatywne / koszty:**
- **Każda nowa zdolność wymaga PR z Pythonem.** Brak ekspozycji do "powers users" (np. balance designer) bez programowania.
- **Skalowalność.** Gdy lista zdolności wzrośnie >100, `effects.py` może stać się przytłaczająca — refactor na sub-moduły per kategoria (passive_morale / passive_combat / active_command / etc.) jako prevention.
- **Duplikacja vs procedural cost engine.** Strumień A ma `dispatcher.py` + `handlers.py` jako YAML-driven; B3 jest hardcoded. Inwariant rozważony: koszty są deterministyczne i statyczne (sensowne dla DSL), engine ma control flow (events / interrupts / state queries — nie pasuje do DSL).

**Co odkładamy:**
- **YAML rule DSL dla zdolności pasywnych** (np. `Nieustraszony: morale_tests -1`). Po B3.7 ocena — jeśli `effects.py` ma >50 entries z prostymi pattern-ami, rozważymy migrację części do YAML jako sub-DSL.
- **Plugin architecture dla custom rulesetów** (community-contributed abilities). Strategiczne; po stabilizacji v1.

## Alternatywy rozważone

- **YAML rule DSL** (analogicznie do `ability_costs.yaml` dla kosztów). Odrzucone — zasady gry mają control flow (`if cel jest Latający, broń Niebezpośredni nie może atakować`), state queries (`if wrogie jednostki w 3"`), pomiarów geometrycznych (LoS, dystans), eventów — wszystko wymaga "kodu", nie deklaracji. DSL by stał się full programming language z gorszym tooling.
- **State machine framework** (e.g., `transitions` library). Odrzucone — battle state nie jest linearnym FSM; ma branching (akcje), interrupty (przerwania pkt 12), reactive windows (kontratak), pętle (multi-ataki w aktywacji). Framework dodaje narzut bez zysku.
- **Plugin architecture** (każda zdolność jako oddzielna klasa implementująca interface `Ability`). Odrzucone w MVP — overkill dla 88 abilities; refactor na plugin pattern po stabilizacji, jeśli zajdzie potrzeba.
- **Rule engine library** (e.g., `durable-rules`, `pyknow`). Odrzucone — narzut runtime, krzywa nauki, ograniczona kontrola nad event sourcing. Hardcoded daje 1:1 mapping między dokumentem (SZOP) a kodem.
- **Hybrid: hardcoded core + YAML extensions.** Odrzucone w MVP, możliwe w przyszłości (zob. "Co odkładamy"). Każda zmiana wymagałaby walidacji w obu warstwach — koszt utrzymania.

## Do rewizji przed promocją na Accepted (po B3.7)

1. **`effects.py` size & shape.** Czy `EFFECT_REGISTRY` rośnie powyżej 50 entries z mocnymi wzorcami powtórzeń? Wtedy rozważyć YAML sub-DSL dla pasywnych modyfikatorów morale/test.
2. **`combat.py` cyclomatic complexity.** Czy 3 fazy + reactive window + wound allocation mieszczą się w czytelnych <200 LOC functions? Jeśli nie — split (`combat_phases.py`, `wound_allocation.py`).
3. **`Action` polimorfizm** (B3.7). Czy Pydantic discriminated union wystarczył, czy trzeba własnego dispatchera?
4. **Test coverage.** Czy każda zdolność aktywna ma ≥1 test? Każda akcja 14.a-e?
5. **Decoupling.** Czy moduły są ortogonalne (`dice` → `los` → `prediction` → `combat` → `effects` → `phases` → `resolver`), czy mają cyclic deps?
6. **Perf.** Czy `resolver.apply()` < 10ms dla typowej akcji? Jeśli nie — gdzie hot path?
7. **Reactive window stability.** Czy ADR-0015a (jednorazowy reactive, no nested) wystarczył, czy `Kontratak` + `Strażnik` wymagają więcej niż 1 sub-event?
8. **Replay determinism.** Czy `apply_events(initial, events)` = `apply_events(initial, events)` zawsze (bit-for-bit)?

Każdy nieadresowany punkt = blocker dla promocji na Accepted lub nowy ADR.
