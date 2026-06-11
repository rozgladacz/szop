# HANDOFF — faza-b-engine-mvp

> **Wątek:** Strumień B — Game Engine MVP (parent). Bootstrap (B0 założenia + 4 ADR-y) + B3 (rule executor) + B3.9 (architecture hardening) → B2 (modele ORM) → B4 (API) → B5 (klient) → B6 (prezentacja) → B7 (test bed). Praca delegowana do sub-wątków (`faza-b-2-models`, `faza-b-3-executor`, `faza-b-3-hardening`, ...).
> **Status:** In progress — B0 ✅ + B3 ✅ + **B3.9 ✅** (sub-wątek `faza-b-3-hardening` ready for archive 2026-06-02, 6 faz B3.9.a-f, pytest 1337/1337, 13 ADR-ów Accepted). Następne: B2 ORM (event types stabilne — zero migration churn) + Strumień D (agenci-boty) równolegle, potem B4 API + B5 klient.
> **Utworzony:** 2026-05-30
> **Ostatnia aktualizacja:** 2026-06-02 (B3.9 hardening zamknięty — sub-wątek `faza-b-3-hardening` ready for archive)

## Cel

Zbudować symulator pełnej bitwy 1v1 oparty o `SZOP_Rozjemca.md` (reguły) + `SZOP_Zdolnosci.md` (mechaniki 77 zdolności). Engine headless-first (czyste funkcje + event sourcing), prezentacja opcjonalna. Pareto MVP: oddział = koło, brak orientacji modeli, ruch deklarowany (bez pathfindingu), LoS standardowy. 6 zdolności wykluczonych z MVP (Pareto trade-off; zob. `app/rulesets/v1/b_mvp_exclusions.yaml`).

Plan długofalowy: [docs/roadmap.md#strumień-b](../roadmap.md). Strumień B odblokowany przez zamknięcie Strumienia A (YAML SSOT) i A4 (pipeline drift detection — `build/geometry_classification.md` jako informational input).

## Zablokowane pliki / katalogi

**Sesja B0 (ta):**
- `app/rulesets/v1/tables.yaml` — dodajemy sekcję `b_mvp`
- `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — hand-curated 6 entries
- `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas
- `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()`
- `tests/test_b_mvp_config.py` (NEW) — exclusions + Pydantic walidacja
- `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- `docs/adr/0008-pareto-mvp.md` (NEW) — Status: Accepted
- `docs/adr/0010-event-sourced-battle-log.md` (NEW) — Status: Accepted
- `docs/adr/0010a-decision-freeze.md` (NEW) — Status: Accepted
- `docs/adr/0014-per-unit-wounds.md` (NEW) — Status: Accepted
- `docs/roadmap.md` — statusy B0 ✅ + ADR-y Accepted

**Sub-wątki B2+ (delegacja zakresów):**
- **`faza-b-3-executor`** ✅ **archived 2026-05-30** (B3.0-B3.8 done, 1244/1244 testów). LOG SESJI w HANDOFF.md.
- **`faza-b-3-hardening`** (NIE uruchomione — następna sesja) — refactor architektoniczny B3 przed startem B2/B4. 6 modułów + refaktorów + 3 nowe ADR-y (0045/0046/0047). Plik: `app/services/engine/{status,geometry}.py` (NEW), modyfikacje `state`/`combat`/`phases`/`effects`/`resolver`, nowe event types `StatusAdded`/`StatusRemoved` + pełne reducery, smoke replay parity test (`live_state == apply_events(initial, events)`). Powód: 7 bugów z code review (cumulative `wounds_received`, charger.radius ignored, silent status mutation, weapon inventory missing, constants drift) + brak `_ACTIVE_ABILITY_REGISTRY` blokuje skalowanie aktywnych zdolności.
- **`faza-b-2-models`** (NIE uruchomione — po B3.9 hardening) — `app/models.py` (Battle/BattleEvent/BattleInvite/BattleSnapshot/AgentToken/AgentAuditLog + Unit.base_size_mm/base_shape/melee_weapons/ranged_weapons), Alembic migration. **Decyzja:** B2 ORM zaprojektowane wokół ustabilizowanego engine (post-B3.9) żeby uniknąć migration churn przy refactor schema event-store.
- **`faza-b-4-api`** — `app/routers/battles.py` (NEW). Po B3.9 + faza-b-2-models.
- **`faza-b-5-client`** — `szop_client/` (NEW pakiet). Równolegle z B4.
- **`faza-b-7-test-bed`** — `tests/fixtures/battles/*.yaml` (NEW). Po B3.9.

**Read-only przez cały Strumień B (źródła prawdy):**
- `app/static/docs/SZOP_Rozjemca.md` — reguły gry (mechaniki)
- `app/static/docs/SZOP_Zdolnosci.md` — 77 zdolności (id, typ, opis, efekty, koszt, tagi)
- `app/static/docs/SZOP.docx`, `app/static/docs/SZOP.pdf` — rules-as-prose (SSOT dla tekstu reguł)
- `app/rulesets/v1/abilities.yaml` (88 entries) — target dla drift detection (A4 pipeline)
- `app/services/costs/` — Strumień A SSOT kosztów, B nie modyfikuje

## Blokuje / Blokowane przez

- **Blokuje:** Strumień C (MCP agent — wymaga publicznego API z B4), Strumień D (agenci-boty — wymagają engine z B3).
- **Blokowane przez:** nic — Strumień A pełen (A0+A1+A2+A3+A5+A4), `build/geometry_classification.md` jest informational.

## Gałąź git

- **Branch:** **`Faza_A` → main MERGED 2026-06-07** (PR #455, commit `418b0ff`). B2/B4/B5 sub-wątki startują na bazie `main`. Nowy branch `Faza_B` otwieramy przy starcie B2.
- **Base:** `main`

## Plan implementacji

### B0 — Pareto MVP założenia + 4 ADR-y (~1 sesja) — **DONE 2026-05-30**

**Decyzje wejściowe (z sesji 2026-05-28+2026-05-30):**

1. **SSOT split:** `SZOP_*.md` = SSOT dla engine; `SZOP.docx`/`SZOP.pdf` = SSOT dla rules-as-prose.
2. **Pareto MVP geometry:** oddział = koło. Podstawka modelu = 1 in² na punkt wytrzymałości. `radius_inches = sqrt(sum(toughness_modelu) / π)`. Bohater (id 2) liczy się jako `toughness/2`.
3. **Globalny ruch** `move_inches: 6"` z `SZOP_Rozjemca.md pkt 15.a`. Modyfikatory Szybki/Wolny (±2″) stosowane w runtime.
4. **Brak orientacji modeli** — pkt 25 SZOP_Rozjemca nieaktywowany. Jedyna zdolność wymagająca (Zwrot id 44) wykluczona.
5. **Brak pathfindingu** — ruch deklarowany przez gracza, weryfikowany jako legalny. Wymuszone ruchy: Szarża/Związanie (pkt 14.d.ii, 16) i Samolot (wykluczony).
6. **LoS standardowy** — linia z krawędzi atakującego do podstawki celu (pkt 6). Wyjątki LoS niestandardowego (Wysoki, Samolot) wykluczone.
7. **Tracking ran — 2 pule alokacji + dodatkowy licznik eliminating** (`SZOP_Rozjemca.md pkt 17.d–18 + 26.d`, user decision 2026-06-07 — KOREKTA wcześniejszego „3-pula" które było sprzeczne z pkt 17.d):
   - Pule alokacji per pkt 17.d **bez zmian**: `wounds_pending_precise` (pula atakującego, pkt 17.d.i) + `wounds_pending` (pula obrońcy, pkt 17.d.ii); znaczniki `wounds_received` (pkt 18.c); `melee_balance` (pkt 20.c).
   - **NOWE: `wounds_eliminating: int`** — dodatkowy licznik (NIE trzecia pula alokacji). Broń **Zguba** zadaje rany normalnie do precise/regular ORAZ zwiększa ten licznik o tę samą liczbę. Alokacja precise/regular zmniejsza licznik (eliminating nigdy nie alokowany samodzielnie). Model pokonany gdy licznik wciąż dodatni → **ELIMINOWANY** (pkt 26.d, nie wraca); inaczej WYCOFANY (pkt 26.c, wraca przez Leczenie pkt 21.c.ii). Reguła: „Zguba: Licz rany otrzymane tą bronią. Modele pokonane przez przydzielenie pierwszych ran do tej liczby nie mogą wrócić do gry."
   - **ADR-0014 refresh:** dodać pojedyncze pole-licznik `wounds_eliminating` (NIE restrukturyzacja na 3-pula). Szczegóły: `HANDOFF_faza-b-rules-resync.md` sekcja Decyzje 2026-06-07.

**Lista exclusions B0 (6 abilities — hand-curated, user decision 2026-05-30):**

| id | slug | name | uzasadnienie |
|---|---|---|---|
| 29 | samolot | Samolot | minimalny ruch 30-36″ w prostej linii + LoS niestandardowy |
| 37 | wrak | Wrak | pokonanie tworzy teren z 3 cechami |
| 38 | wysoki | Wysoki | LoS sprawdzane jakby z podwyższenia |
| 44 | zwrot | Zwrot | 4 strefy 180° (przód/tył/lewo/prawo) — wymaga orientacji |
| 73 | sterowany | Sterowany | 2 znaczniki broni z osobnym ruchem |
| 77 | zuzywalny | Zużywalny | raz na grę + max 1 broń tego typu per oddział |

**Rozbieżność z A4.3 result (`build/geometry_classification.md`):** A4.3 wygenerowało automatyczną listę 3 abilities (dywersant=false-positive, precyzyjny=per_model, zwrot=facing). Tylko `zwrot` jest wspólny. Powód:
- A4.3 to **heurystyka keyword match** — sklasyfikowała `dywersant` na podstawie keyword `strefy` (chodzi o strefy rozstawienia, false positive)
- A4.3 sklasyfikowała `precyzyjny` jako `per_model`, ale w MVP obsługujemy go przez `wounds_pending_precise` (ADR-0014) — atakujący wybiera deterministyczną kolejność pokonania modeli w heterogenicznym oddziale (np. Bohater vs zwykła postać)
- A4.3 nie obejmuje wykluczeń typu `terrain_generation` (Wrak), `session_state` (Zużywalny), `tokens_on_board` (Sterowany) — to są user decisions wykraczające poza geometric classification heuristyki

`b_mvp_exclusions.yaml` jest **hand-curated authoritative list** dla engine; `geometry_classification.md` zostaje jako informational artifact A4 pipeline.

**Kroki B0:**

- [x] B0.1: `app/rulesets/v1/tables.yaml` — dodaj sekcję `b_mvp` (move_inches=6, base_area_inches_sq_per_toughness=1, pi_approx)
- [x] B0.2: `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — 6 entries z {slug, reason, category}
- [x] B0.3: `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas; rozszerz `RulesetTables` o opcjonalne pole `b_mvp`
- [x] B0.4: `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()` z `@lru_cache`
- [x] B0.5: `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- [x] B0.6: `tests/test_b_mvp_config.py` (NEW) — 6 entries, slug set, sanity link do abilities.yaml
- [x] B0.7: ADR-0008 (Pareto MVP), ADR-0010 (event-sourced), ADR-0010a (decision freeze), ADR-0014 (per-unit wounds) — wszystkie Status: Accepted
- [x] B0.8: `docs/roadmap.md` — B0 ✅, ADR-y 0008/0010/0010a/0014 Accepted

> **Note (2026-05-30):** GATE pkt 3 ADR-0010a (audit akcji pkt 14 ↔ aktywne zdolności z SZOP_Zdolnosci.md) przesunięty z B0.W do **B3.0.1 preflight** w sub-wątku [HANDOFF_faza-b-3-executor](HANDOFF_faza-b-3-executor.md). Powód: B0 zamknięte deliverable-side, audit to pre-implementation requirement dla B3.

### B2 — Modele danych (4 tyg, sub-wątek `faza-b-2-models`) — **POST-B3.9**

Per `docs/roadmap.md#b2-modele-danych`. ORM (Battle, BattleEvent, BattleInvite, BattleSnapshot, Unit.base_size_mm + melee_weapons/ranged_weapons, AgentToken, AgentAuditLog) + persistence (`persistence.py`). Alembic migration. **Konsumuje ustabilizowany engine z B3.9** — `BattleEvent.payload_json` schema mapuje 1:1 na `events.py` event types (12 po B3.9: 10 oryginalnych + StatusAdded/StatusRemoved). Persisting + replay weryfikuje inwariant z ADR-0046.

ADR-0010 (event-sourced) + ADR-0014 (per-unit wounds) + ADR-0045 (activation context) + ADR-0046 (event-sourced mutations) + ADR-0047 (weapons inventory) dyktują strukturę. ADR-0042 (facing) odłożony do E3.

### B3 — Rule Executor + dice — **DONE 2026-05-30** (sub-wątek archived)

Sub-wątek `faza-b-3-executor` zarchiwizowany. 8 commitów B3.0-B3.8 na `Faza_A`. Pytest 1244/1244 (962 baseline + 282 nowych). 10 ADR-ów Accepted (0008/0010/0010a/0011/0012/0014/0015/0015a/0043/0044). Pakiet `app/services/engine/` ~2400 LOC, 12 modułów. Public API udokumentowane w ADR-0011. Smoke replay 2v2 przeszedł (21 events, 7 typów reprezentowanych). LOG SESJI w `HANDOFF.md`.

### B3.9 — Architecture hardening (~3-5 sesji, sub-wątek `faza-b-3-hardening`) — **PLANNED, runs BEFORE B2**

**Cel:** rozstrzygnąć 5 dziur architektonicznych wykrytych w post-B3 code review zanim B2 ORM / B4 API zaczną konsumować engine. Stabilizacja API engine + naprawienie 7 bugów + 1 cleanup w jednym spójnym refactor zamiast rozsiać po przyszłych ticketach.

**5 dziur architektonicznych (z code review):**

| # | Dziura | Bugi które rozwiązuje |
|---|---|---|
| A | Brak rozróżnienia "trwały stan" vs "delta tej aktywacji" (`wounds_received` cumulative używany jako proxy dla pkt 20.a "w tej aktywacji"; `melee_balance` resetowany tylko na actorze; `initial_toughness` z bieżącego `models_alive`) | #1, #2, #3, #5 |
| B | Event sourcing nie exhaustive — `combat.py` mutuje `status_flags` przez `dataclass.replace` bez emit eventu; `apply_events(initial, events)` nie odtworzy `Wyczerpany` po kontrataku. ADR-0010 inwariant niezweryfikowalny. | #6 (silent Wyczerpany) + powiązane (deployment Aktywowany reset, defend status, round_end reset) |
| C | Brak weapon inventory na `UnitBlob` — counter używa broni atakującego (komentarz w kodzie sam to przyznaje) | #7 |
| D | Geometria + constants duplikowane: `_distance` 4× (los/phases/combat ×2 inline), `STATUS_*` 3× (effects/phases/combat). `circle_edge_distance` brak — stąd `charger.radius` ignored | #4, #8 |
| E | Brak registry dla aktywnych zdolności — `_apply_special` hardcoded `if slug == "discard_exhausted"`; nie skaluje na ~6 aktywnych z B3.0.1 audit (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik) | (architectural — blokuje przyrostowe dodawanie zdolności) |

**Kroki B3.9:**

- [ ] **B3.9.a — `app/services/engine/status.py` (NEW)** — kanoniczne `StatusFlag` enum (Aktywowany/Wyczerpany/Przyszpilony/Ufortyfikowany) + idempotentne helpery `add_status(blob, flag)` / `remove_status(blob, flag)`. Refactor `effects.py`/`phases.py`/`combat.py` żeby importowały zamiast duplikować. Fix #8 (drift risk).
- [ ] **B3.9.b — `app/services/engine/geometry.py` (NEW)** — `distance(p1, p2)` przez `math.hypot`, `point_in_circle`, `segment_intersects_circle`, `segments_intersect`, **`circle_edge_distance(c1_pos, c1_r, c2_pos, c2_r)`** (rozwiązuje #4 — używane w `resolve_charge_attack` dla `min_gap = defender.radius + charger.radius + 1.0`), `UNIT_CIRCLE_16` precomputed (perf). Refactor `los.py`/`phases.py`/`combat.py`. Fix #4 + perf.
- [ ] **B3.9.c — ActivationContext + initial_toughness snapshot.** Dodać `ActivationContext` frozen dataclass (`actor_id`, `wounds_received_this_activation: dict[int, int]`, `melee_combatants: frozenset[int]`). `BattleState.initial_toughness_snapshot: dict[int, int]` ustalony w `setup_phase` raz, nigdy nie modyfikowany. `activation_phase` buduje ActivationContext, `_regroup_test` używa kontekstu zamiast cumulative `wounds_received`. Defender of charge ma wpis w `wounds_received_this_activation` → regroup test w aktywacji atakującego. Fix #1, #2, #3, #5. **ADR-0045** (NEW Accepted).
- [ ] **B3.9.d — Event-sourced state mutations.** Dodać event types `StatusAdded(target_id, status)` + `StatusRemoved(target_id, status)` w `events.py`. Refaktor `combat.resolve_charge_attack` żeby emit'ował `StatusAdded(target_id=B, status="Wyczerpany")` zamiast `replace(status_flags=...)`. Analogicznie `_apply_defend` (Ufortyfikowany), `round_end_phase` (reset Aktywowany emit `StatusRemoved`). Implementacja reducer-ów dla wszystkich 10 event types w `state.apply_events`. **Test inwariant:** smoke replay 2v2 z `live_state == apply_events(initial_state, all_events)`. Fix #6. **ADR-0046** (NEW Accepted).
- [ ] **B3.9.e — UnitBlob weapons inventory + ACTIVE_ABILITY_REGISTRY.** Rozszerz `UnitBlob` o `melee_weapons: tuple[WeaponProfile, ...]` + `ranged_weapons`. `resolve_charge_attack` używa `defender.melee_weapons[0]` (lub fallback). `build_initial_state` czyta `unit.weapons` z roster. Plus `_ACTIVE_ABILITY_REGISTRY` w `effects.py`: `@register_active_ability("latanie") def handler(state, blob, payload) → (state, events)`. `phases._apply_special` deleguje do registry. Implementacje stub dla 6 aktywnych zdolności (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik). Fix #7 + dziura E. **ADR-0047** (NEW Accepted).
- [ ] **B3.9.f — Dead code cleanup + dokumentacja.** Usuń dead loop `combat.py:378-380`, function-local `_MoveExecuted` import. Update `docs/architecture.md` sekcja "Game engine" z nową strukturą (status.py, geometry.py, ActivationContext, weapons inventory). Update ADR-0011 (Accepted) z nowymi modułami w "Public API". Update `scripts/engine_smoke_replay.py` żeby weryfikował replay invariant (`assert apply_events(...) == final_state`).
- [ ] **B3.9.W — weryfikacja:** pytest pełna suite (1244 + nowe testy ~50-80); parity gate Strumień A niezmieniony; drift gate CLEAN; smoke replay z replay invariant. Cel: 1300+ testów; **GATE: smoke replay invariant test musi pass jako proof-of-completeness ADR-0010**.

**Decyzja kolejności (B3.9 before B2):** ORM `BattleEvent.payload_json` schema musi pokrywać wszystkie event types z `events.py` (już 10 → po B3.9 ~12). Stabilizacja event types + reducery PRZED ORM eliminuje migration churn (każda zmiana event type po B2 = Alembic migration).

### B4 — API (3 tyg, sub-wątek `faza-b-4-api`)

`app/routers/battles.py` — 9 endpointów (invite/accept/create/get/events/actions/interrupts/simulate/replay). Pydantic schemas, optimistic locking na sequence.

### B5 — Klient gry `szop_client` (równolegle z B4)

Pakiet `szop_client/` z `Protocol GameClient` + `HttpClient` + `LocalClient` (in-process). ADR-0016.

### B6 — Prezentacja (opcjonalne, 3-4 tyg)

CLI replay, SSE stream, canvas frontend. ADR-0013.

### B7 — Test bed (2 tyg)

Golden battles `tests/fixtures/battles/*.yaml` + `tests/test_engine_regression.py`.

## Pliki dotknięte

*(wypełni się w trakcie B0)*

## Hipotezy / pytania otwarte

- **H1:** Wzór `radius = sqrt(sum(toughness)/π)` daje sensowne odległości w skali 6′×4′? Sanity: oddział 5 modeli toughness 3 → radius ≈ 2.19″ (= ~5.6 cm na realnej planszy). Wydaje się OK. Zweryfikujemy na realnych rosters w B2/B3 smoke.
- **H2:** Czy `precyzyjny` jako 4-ta kategoria ran (`wounds_pending_precise`) w MVP da się obsłużyć bez per-model granularity? Plan: atakujący wybiera index modelu do pokonania w heterogenicznym oddziale (np. Bohater vs zwykła postać). Dla homogeneous unit — kolejność nie ma znaczenia. Test w B3.
- **H3:** Czy `melee_balance` jako pojedynczy int (zadane − otrzymane) wystarczy gdy Porażenie (id 67) liczy rany ×2? Plan: stosujemy ×2 mnożnik tylko do calculation `melee_balance += dealt*2 if Porażenie else dealt`. Test w B3.

## Jak zweryfikować

```powershell
# Po B0
python -m pytest tests/test_b_mvp_config.py tests/test_b_mvp_tables.py -v
python -m pytest -q  # full suite — baseline 938 + ~6-8 nowych z B0

# Parity gate (nie powinno się zepsuć — B0 nie ruszało cost path)
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml_backend/

# Smoke
cat app/rulesets/v1/b_mvp_exclusions.yaml  # 6 wpisów
python -c "from app.services.rulesets.loader import load_b_mvp_exclusions; print(load_b_mvp_exclusions())"
```

## Decyzje

- 2026-05-30: Slug `faza-b-engine-mvp` (krótszy, jednoznaczny). Alternatywy odrzucone: `faza-b` (zbyt ogólne), `faza-b-symulator` (PL, niespójne).
- 2026-05-30: Branch `Faza_A` (kontynuujemy do scalenia z main). Decyzja per user wcześniej.
- 2026-05-30: Lista exclusions B0 = 6 entries (samolot/wrak/wysoki/zwrot/sterowany/zuzywalny) hand-curated. A4.3 result (`build/geometry_classification.md`) informational only.
- 2026-05-30: `precyzyjny` (id 68) NIE wykluczony z MVP — obsłużymy przez `wounds_pending_precise` + atakujący wybiera index pokonania. Wbrew sugestii A4.3 (per_model).
- 2026-05-30: `b_mvp_exclusions.yaml` jako osobny plik (separation of concerns od `abilities.yaml`); engine ładuje przez `load_b_mvp_exclusions()` z lru_cache.

## Notatki / odkrycia w trakcie

- **2026-06-11 — DRIFT pkt 20.e (Nieustraszony) do sprawdzenia.** User przebudował pkt 20 (Przegrupowanie) edytując źródło: pkt 20.e NOWE „oddział z Nieustraszony **powyżej połowy** wytrzymałości **nie wykonuje testów Przegrupowania**" (skip WSZYSTKICH) vs STARE „Nieustraszony znosi pkt 20.a" (−1 do liczby testów). Engine `phases._regroup_test` liczy testy z `aggregate_morale_modifier` (Nieustraszony = −1), co odpowiada STAREJ regule → **możliwy drift**: Nieustraszony nad-połową + walczył wręcz → engine daje 1 test (melee +1, Nieustraszony −1, base +1 = 1), nowy .md daje 0. Status `READY` (mechanika spec'owana). Fix: gdy `Nieustraszony in passives` i `current > initial/2` → `n_tests = 0` (przed rzutami). Wykryte przy `faza-b-regroup-choice` (pkt 20.f.i wybór konsekwencji — zrobione). Nie blokuje (Nieustraszony nieobecny w fixturach botów).

- **2026-06-10 — ✅ ROZWIĄZANE (wątek `faza-b-multi-action`, ADR-0051): aktywacja wieloakcyjna.** `resolver.apply_activation` realizuje pętlę do 2 akcji (pkt 11.b.iv; Manewr liczy się; Ostrzał/Szarża raz), `phases` rozdzielone (`_begin`/`_apply_single`/`_finalize`), boty napędzają przez `Player.continue_activation`. `apply` (1 akcja) zostaje dla B4. Postęp lokalny → zero zmian schematu/replay (1558 testów, smoke EXIT 0). Balans bardziej rozstrzygający; ujawnił słabość heurystyk (boty nie trzymają celów — follow-up D). Oryginalny opis luki poniżej (kontekst).
- **2026-06-10 — LUKA MVP: aktywacja = 1 akcja zamiast 2 (pkt 11.b.iv).** Wykryte przy ocenie botów (wątek `faza-d-priority-player`, pytanie usera). **Reguły (źródło, pkt cytowane):** aktywacja to **do 2 akcji** (pkt 11.b.iv) — Manewr NIE liczy się do limitu i jest powtarzalny; 2. liczona akcja musi być różna od 1. (znoszone przez Niestrudzony/Manewr); Ostrzał raz (pkt 14.c.v), Szarża raz (pkt 14.d.vi); Przegrupowanie po KAŻDEJ akcji (pkt 11.b.iii). **Stan silnika:** `phases.activation_phase` docstring „MVP scope: pojedyncza akcja"; `resolver.apply` → 1 akcja → Aktywowany; `match.py` 1 apply/oddział/rundę; boty zwracają 1 akcję. → **Manewr→Ostrzał (dojdź i strzel) niemożliwe**, Manewr zużywa aktywację (wbrew pkt 11.b.iv). **Wpływ:** zaniża realizm balansu bardziej niż liczba celów — Strzelcy nie repozycjonują się przed strzałem. **Status `READY` (mechanika spec'owana pkt 11):** pętla 2-akcji w `resolver`/`activation_phase` (Manewr free + akcja≠poprzednia + raz-strzał/szarża + Przegrupowanie/akcję) + warstwa botów wybiera sekwencję do 2 akcji + `match.py` pętla per-oddział. **Decyzja usera potrzebna:** czy podnieść teraz (engine, B-stream) przed budową zróżnicowanych fixtur (4 typy Wojownik/Strzelec), które wymagają move-then-shoot by miały sens. Zapis follow-up D: fixtury 4 typów (1×24+1×0, 1×18+1×0 Strzelec; 1×12+2×0, 3×0 Wojownik) — PO mechanice 2-akcji.

- **2026-06-10 — B2 event-store slice DONE** (wątek `faza-b-2-event-store`, ADR-0050). Persystencja: nowe tabele `battles`/`battle_events` (`app/models.py`) + `app/services/engine/persistence.py` (`save_events`/`load_events`). **GATE replay-from-DB invariant** zielony — schemat eventów (16 typów) persystuje i odtwarza bit-perfect. **B4 API odblokowane** (konsumuje persistence + optimistic locking via `UniqueConstraint(battle_id, sequence)`). **Brak Alembic** w projekcie — nowe tabele addytywne via `create_all`; zmiany kolumn istniejących tabel wymagają wpisu w `_migrate_schema` (db.py). **Odroczone z B2** (osobny wątek + user + security-review): `BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog` + kolumny `Unit.base_size_mm/base_shape`. Serializer `event_to_json`/`json_to_event` JUŻ istniał w `events.py` (B2 deliverable zrobiony wcześniej). pytest 1504.
- **2026-06-10 — Headless pętla bitwy DONE** (wątek `faza-d-match-runner`, ADR-0032). `app/services/agents/match.py`: `run_match(state, players, dice)` + `simulate_from_rosters(...)` → `MatchResult`. Domyka „pętlę bitwy" wskazaną poniżej jako brakującą po D1 — orkiestrator `apply`+`round_end_phase`+alternacja inicjatywy (pkt 8), headless (ADR-0013), zero zmian w rdzeniu. **D2 `balance_simulate` jest teraz READY** (agreguje N `simulate_from_rosters`). To zalążek B5 `LocalClient.simulate`. pytest 1494/1494. (Uwaga: rezerwy Zaplecze nie są rozstawiane mid-game w MVP — siedzą bezczynnie; pełne rozstawianie rezerw odłożone.)
- **2026-06-09 (sesja codzienna autonomiczna) — Strumień D1 MVP DONE** (wątek `faza-d-heuristic-players`, ADR-0031). Nowy pakiet `app/services/agents/` (Player ABC + `legal_actions` enumerator + RandomPlayer + GreedyPlayer + `evaluate_state`), czyta tylko publiczne API silnika (zero zmian w rdzeniu → brak kolizji z `faza-b-order-interrupts`). 26 testów, pytest 1489/1489. **Odblokowuje D2/D3, ale `balance_simulate` (D2) wymaga pętli bitwy** = orkiestrator `apply`+`round_end_phase`+alternacja inicjatywy → to **B5 LocalClient / B4 routers** (`READY` po B2 ORM). Boty są kompletne i testowalne w izolacji; brakuje tylko warstwy, która je uruchamia w pełnej grze. To kolejny naturalny krok parenta (obok B2 ORM).
- **2026-06-09 (sesja codzienna autonomiczna) — wątek `faza-b-rules-resync` ZARCHIWIZOWANY (R0–R7 + RW ✅).** Resync 3 warstw SSOT z driftem 2026-06-03 kompletny i zweryfikowany (pytest 1435/1435, both_assert 156/156, yaml 93/93, drift WARN, smoke EXIT 0). Pełny rekord driftu: **ADR-0048**. **Przejęte do tego parenta jako backlog przyrostowych zdolności engine:**
  - **[MVP DONE 2026-06-09 — wątek `faza-b-order-interrupts`, ADR-0049] Klątwa(X) / Rozkaz(X) / Oznaczenie(X)** (id 45/49/50). Zaimplementowane: substrat `ability_overrides` + `effective_passives`, handlery interrupt `BEFORE_ACTION` (zasięg 12″, ally/enemy, `rozkaz_tak`, raz-na-rundę), wygaśnięcie na końcu aktywacji, 28 testów. **Pozostaje (follow-up):** Oznaczenie precyzyjny trigger ataku + auto-orkiestracja przerwań w pętli aktywacji (H2/B4). Spec poniżej zachowany dla kontekstu. **NIE jest zablokowane decyzją** — to czysta robota engine. **Policy (user 2026-06-09):** przerwanie wyzwalane **przed akcją** — w regułach to JEDEN krok „Rozpatrujemy przerwania" (pkt 11.b.i), odwiedzany na początku każdej iteracji pętli akcji (pkt 11.b.iv→i), więc w praktyce **dwa okna przed-akcyjne** (przed akcją #1 i #2). Raz na rundę; efekt (nadanie/odebranie X) działa **do końca aktywacji**; X = dowolna pasywka z `rozkaz_tak: true` (SZOP_Zdolnosci.md #45/49/50). Cost-side + `rozkaz_tak` field done. **✅ DRIFT ADR-0015 NAPRAWIONY (2026-06-09):** enum `InterruptPoint` zredukowany do `BEFORE_ACTION` (pkt 11.b.i; ≤2 okna/aktywację via pętla 11.b.iv→i). Usunięto ACTIVATION_START/AFTER_ACTION/BEFORE_REGROUP/AFTER_REGROUP (drift — brak oparcia w pkt 11/12). ADR-0015 skorygowany (sekcja Korekta), `interrupts.py`/`events.py`/testy/ADR-0011/roadmap zsynchronizowane. **Pozostała robota engine (osobno):** mechanizm czasowego nadania/odebrania pasywki + limit `used_interrupts_this_round` + podpięcie `BEFORE_ACTION` do `phases.activation_phase` + 3 handlery. **Brakująca mechanika engine (do zbudowania):** (1) czasowe nadanie/odebranie pasywki na `UnitBlob` — dziś `passives` to statyczna krotka (`state.py:165`); potrzeba pola `granted_abilities`/`suppressed_abilities` z wygaśnięciem LUB eventów `AbilityGranted`/`AbilityRemoved` + reducery + sprzątanie na końcu aktywacji; (2) limit „raz na rundę" — `BattleState.used_interrupts_this_round` (TODO wg `interrupts.py:20-23`, nie istnieje); (3) podpięcie `InterruptPoint` do `phases.activation_phase` (dziś tylko stub Strażnika, brak integracji faz). Zakres: nowe pole + 2-3 eventy + reducery + integracja faz + limit per-runda + 3 handlery + testy replay-invariant. Wymaga ADR (interrupt orchestration + ability-grant mechanism).
  - **[H7 — czeka na fazę Leczenia pkt 21] heal-revive limit dla ELIMINOWANY/Zguby** — gdy powstanie faza Leczenia: `_apply_heal_*` przywraca tylko `location == WYCOFANY` (nie ELIMINOWANY, pkt 26.d); limit odzyskania pomniejszony o `wounds_eliminating`. Pole `wounds_eliminating` JUŻ persystowane na `UnitBlob` (R4.Zguba). **NIE blokuje B2/B4** (pole w schemacie).
  - **B2 ORM schema impact (ZAMROŻONE, zero migration churn):** `BattleEvent.payload_json` per unit +`location: Lokalizacja` +`wounds_eliminating: int`; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`; nowy event `MutexCollision`. (14 event types po resync.)

## Decyzje zamrożone (NIE podnosić ponownie)

> **Czytaj PRZED wylistowaniem „co zostało".** Poniższe są ROZSTRZYGNIĘTE przez usera. NIE są otwartymi pytaniami, NIE są blokadami, NIE wymagają ADR-a do potwierdzenia. Nie przekształcaj ich z powrotem w „PYTANIE DO USERA". Implementuj wyłącznie na wyraźne polecenie usera.

- **Dywersant (id 6) — POZA ZAKRESEM tej fazy MVP.** User potwierdził DEFER trzykrotnie (H3, 2026-06-06 + reaffirmed 2026-06-09). Cost-side done (R2, weapon mult ×1.2). Engine-side = stub w `effects.INCOMPLETE_ABILITIES` (`effects.py:392`) — to jest stan DOCELOWY dla tej fazy, nie TODO. ×2 ataki vs Przyszpilony NIE implementujemy teraz. Żadna sesja nie powinna re-eskalować tego jako pytania/blokady.

- 2026-05-30: HANDOFF utworzony. Strumień A pełen (A0-A5 + A4); ADR-y 0001-0007 Accepted. ADR-y B (0008/0010/0010a/0014) do utworzenia w B0. `abilities.yaml` ma 88 entries po YAML sync z `Rozwoj` w trakcie A4. Wszystkie 6 slug-ów B exclusions audytowane jako obecne w YAML.
- 2026-05-30: B0 done (3 commits: `67740c4` ADR-y, `2e01894` deliverables, `53de635` roadmap). 4 ADR-y Accepted, `b_mvp` w `tables.yaml`, `b_mvp_exclusions.yaml` (6 entries), Pydantic + loader + testy. Parent przechodzi w tryb koordynacji sub-wątków.
- 2026-05-30: **Sub-wątek `faza-b-3-executor` started** ([HANDOFF](HANDOFF_faza-b-3-executor.md)). Decyzja: B3 leci przed pełnym B2 ORM — executor pure-function nie potrzebuje DB, minimum runtime substrate (state/events + apply_events) zrobi się w B3.0. Pełne B2 ORM (`faza-b-2-models`) odłożone do startu B4 API. GATE ADR-0010a pkt 3 (audit) → B3.0.1.
- 2026-05-30 (post-B3 archive): **B3 zakończone, sub-wątek archived.** Code review (`/code-review medium effort`) wykrył **8 findings: 7 bugów + 1 cleanup** clusterujące się w **5 dziur architektonicznych** (A: delta vs cumulative state; B: silent status mutations bypassing events; C: missing weapon inventory; D: geometry + constants duplikacja w 3 plikach; E: brak ACTIVE_ABILITY_REGISTRY). **Decyzja:** dodać **B3.9 architecture hardening** PRZED B2/B4 zamiast naprawiać bugi pojedynczo. Powód: (1) konsolidacja refactor w jednej fazie zamiast 7 osobnych ticketów; (2) B2 ORM `BattleEvent.payload_json` musi pokrywać wszystkie event types — stabilizacja PRZED ORM eliminuje migration churn; (3) B4 API będzie eksponowane na klientów, refactor po publikacji = breaking changes. Plan B3.9 obejmuje 6 kroków (`status.py`/`geometry.py` modules NEW, `ActivationContext` + initial_toughness snapshot, event-sourced status mutations + smoke replay invariant test, weapons inventory + ACTIVE_ABILITY_REGISTRY, dead code cleanup + docs update). 3 nowe ADR-y do napisania: 0045 (activation context), 0046 (event-sourced mutations), 0047 (weapons inventory). Sub-wątek `faza-b-3-hardening` do otwarcia w następnej sesji przez `/handoff-start`.
- **2026-06-06 (zaktualizowane 2026-06-07):** **Sub-wątek `faza-b-rules-resync` w trakcie (R0–R5.a/c/d/e/f/g ✅; R5.b skip; H5 RESOLVED 2026-06-07; pozostałe R4.Zguba/Klątwa-Rozkaz-Oznaczenie/R6/R7/RW).** Impact na parent B3.9 + B2: **ADR-0014 refresh — dodać pojedyncze pole-licznik `UnitBlob.wounds_eliminating: int`** (NIE restrukturyzacja na 3-pula — wcześniejsze sformułowanie porzucone jako sprzeczne z pkt 17.d). Semantyka: 2 pule alokacji bez zmian (pkt 17.d); broń Zguba dorzuca rany do `wounds_eliminating`; alokacja precise/regular zmniejsza licznik; model pokonany @ `eliminating>0` → ELIMINOWANY (pkt 26.d). **B2 ORM impact:** `BattleEvent.payload_json` +1 pole `wounds_eliminating` + `location` enum per unit; `ModelKilled` event +`eliminated: bool`. **Status R5.a + R4.Zguba (DONE 2026-06-07):** `location=WYCOFANY` przy pokonaniu (rany `422412c` + morale 2026-06-07) ORAZ `location=ELIMINOWANY` przy pokonaniu raną broni Zguba (`wounds_eliminating` licznik + `ModelKilled.eliminated` flag + `Shot/MeleeResolved.wounds_eliminating`). **B2 ORM `BattleEvent.payload_json` ZAMROŻONE:** per unit +`wounds_eliminating: int` + `location` enum; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`. Pełna decyzja: `HANDOFF_faza-b-rules-resync.md` sekcja Decyzje 2026-06-07.
