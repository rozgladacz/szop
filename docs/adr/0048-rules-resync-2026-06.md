# ADR-0048 — Rules resync 2026-06: Lokalizacja enum, T_eff formula, status mutex, Zguba eliminating

- **Status:** Accepted
- **Data:** 2026-06-08 (zamyka wątek [HANDOFF_faza-b-rules-resync](../handoffs/HANDOFF_faza-b-rules-resync.md), fazy R0–R7)
- **Kontekst:** Strumień B (Game Engine). User dostarczył nowe wersje `SZOP_Rozjemca.md` (reguły przebiegu gry) + `SZOP_Zdolnosci.md` (mechaniki zdolności) — drift wykryty 2026-06-03. Poprzednie wersje w `app/static/docs/previous version/`. Pipeline drift A4 (`make rules-check`, ADR-0006) zaraportował rozbieżności DOCX/MD↔YAML wymagające synchronizacji **trzech warstw SSOT**: YAML reguł, proceduralnego oracle'a kosztów, oraz engine (semantyka przebiegu bitwy). Resync był prerekwizytem dla B2 ORM / B4 API / Strumień D — bez niego `BattleEvent.payload_json` schema i policy agentów byłyby nieaktualne od dnia 1.

  Ten ADR jest **rekordem driftu** (co się zmieniło w zasadach), zapisem **decyzji projektowych** podjętych przy implementacji, oraz **mapowaniem pkt zasad ↔ moduły engine**. Empiryczny przebieg implementacji: fazy R0–R7 w HANDOFF (commity `549476d` → `9a3ac96`).

## Drift — co się zmieniło w zasadach (2026-06)

Drift objął **rdzeń przebiegu gry** (`SZOP_Rozjemca.md`, ~150 linii diff) oraz **8 zdolności** (`SZOP_Zdolnosci.md`, ~894 linie diff — głównie reformat opisów). Zmiany istotne dla engine, pogrupowane:

| Obszar | Punkt zasad | Zmiana |
|---|---|---|
| **Lokalizacja oddziału** | pkt 26 | NOWY enum stanu oddziału: Zaplecze / Front / Wycofany / Eliminowany. Wycofany może wrócić przez Leczenie (pkt 21.c.ii); Eliminowany (broń Zguba) nie wraca (pkt 27.c). |
| **Pokonanie oddziału** | pkt 27.b | Pokonanie ostatniego modelu (rany lub 3× porażka Przegrupowania) → cały oddział `Wycofany + Pokonany`. |
| **Koszt aur/rozkazów** | (zdolności) | Stałe wartości aury/rozkazu z tabeli s.5 zastąpione **formułą `T_eff = clamp(4/3 × T, 8, 24)`** liczoną z wytrzymałości nosiciela. |
| **Przegrupowanie (trigger)** | pkt 20.a | Trigger testu = „**zadał MNIEJ ran niż otrzymał** w tej aktywacji" (poprzednio: „otrzymał rany"). |
| **Status pkt 22** | pkt 22.b/c | Przyszpilony uproszczony (bez +1 test/bez blokady aktywnych); **mutex Przyszpilony ↔ Ufortyfikowany** (oba znoszone gdy razem). |
| **Niebezpieczny teren** | pkt 4.c.v | Test per-oddział (rzut `models_alive × toughness` k6, każda 1 = rana); rany terenowe wliczają się w bilans Przegrupowania (pkt 20.a). |
| **Ufortyfikowany** | pkt 13.c | Nadawany przy rozstawieniu (rozstawiony oddział; rezerwy off-board/Zaplecze pomijane). |
| **Kontratak** | pkt 14.d.iv | Defender **nie** staje się Wyczerpany jeśli charger pokonany w kontrataku. |
| **8 zdolności przepisanych** | (zdolności) | Bohater (przeciwnik wybiera obronę, nie przywracany), Dywersant (×2 ataki vs Przyszpilony — engine deferred), Harcownik/Zemsta (przesunięte do fazy Leczenia), Nieustraszony (nie testuje gdy >50% wytrzymałości), Zguba (rany „eliminujące"), Klątwa/Rozkaz/Oznaczenie (wymagają `rozkaz_tak`), Przewidywalny (koszt broni). |

## Decyzje projektowe

### D1. Lokalizacja jako enum na `UnitBlob`, nie status flag

`Lokalizacja(str, Enum)` w `state.py` (ZAPLECZE/FRONT/WYCOFANY/ELIMINOWANY), pole `UnitBlob.location: Lokalizacja = FRONT`. **Nie** dodano do `StatusFlag` (pkt 22) bo Lokalizacja jest **wzajemnie wykluczająca** (oddział jest w dokładnie jednym stanie), podczas gdy statusy są niezależnymi flagami. `build_initial_state` ustawia ZAPLECZE dla Zasadzka/Rezerwa, FRONT dla reszty. Pole dodane do `_BLOB_REPLAY_FIELDS` → replay invariant weryfikuje propagację.

### D2. T_eff formula bez zaokrąglania (H1 RESOLVED)

`cost_functions.t_eff(tables, carrier_tou, *, extra)` = `clamp(4/3 × T, 8, 24) + extra`, **float bez floor/round**. Konfiguracja w `tables.yaml > aura_order_formula` (`t_eff_factor=4/3`, `t_eff_clamp_min=8`, `t_eff_clamp_max=24`). Pochodne: `aura_range_bonus` (zasięg 12"), `order_bonus` (Rozkaz/Klątwa/Oznaczenie = `t_eff + 2`). **Świadomie zastępuje** stare arbitralne wartości aury/rozkazu z SZOP s.5 — formuła jest nowym SSOT. Handlery `_aura_cost`/`_order_like_cost` używają `t_eff` zamiast stałych `inner_tou=8/10`.

### D3. Zguba = dodatkowy licznik `wounds_eliminating`, NIE trzecia pula alokacji (H5 RESOLVED — korekta)

Pkt 17.d definiuje **tylko 2 pule alokacji** ran (atakującego/precyzyjna + obrońcy). „Eliminowany" (pkt 27) to właściwość *modelu pokonanego bronią Zguba*, nie pula nadchodzących ran. Implementacja: `UnitBlob.wounds_eliminating: int = 0` — broń Zguba zadaje rany **normalnie** do precise/regular **ORAZ** zwiększa licznik o tę samą liczbę; alokacja precise/regular zmniejsza licznik. Model pokonany gdy licznik wciąż dodatni → ELIMINOWANY (pkt 26.d). Invariant: `0 <= wounds_eliminating <= wounds_received`; każdy wipe (`models_alive=0`) zeruje oba liczniki. **Wcześniejsze sformułowanie „3-pula" (`wounds_received` split) PORZUCONE** jako sprzeczne z pkt 17.d.

### D4. Status mutex jako event `MutexCollision` (H2 RESOLVED)

Mutex Przyszpilony ↔ Ufortyfikowany (pkt 22.b/c) rozwiązany przez **NOWY event `MutexCollision(target_id, dropped_statuses)`** (14ty typ w `_EVENT_REGISTRY`) + reducer `_reduce_mutex_collision` + producer `phases._apply_mutex_collisions` (skanuje `regroup_subjects` po Przegrupowaniu — jedyne miejsce dodania Przyszpilony). Wybrano model event-sourced (nie producer-only silent removal) dla czystego event logu — explicit collision marker widoczny w replay/analytics. Spójne z ADR-0046 (event-sourced mutations).

### D5. Przegrupowanie: trigger przez `ActivationContext`, nie cumulative state

Pkt 20.a NOWY trigger = `delta_received > delta_dealt` **w tej aktywacji** — liczony z `ActivationContext` (ADR-0045): `dealt_for(uid)` agreguje `wounds_dealt + wounds_precise` z `ShotResolved`/`MeleeResolved` per `attacker_id`. Pkt 20.b = NIE-powyżej-połowy (`initial_toughness_for ÷ 2`); pkt 20.c = walczył wręcz (`blob_id in melee_combatants`, drop damage_balance differentiation). Defender szarży ma wpis w kontekście → regroup-testuje w aktywacji chargera.

### D6. Wszystkie rany przez `_allocate_wounds_to_defender` (SSOT kill-loop) (H6 RESOLVED)

Rany z Niebezpiecznego terenu (pkt 4.c.v, self-inflicted) przechodzą przez ten sam `combat._allocate_wounds_to_defender` co rany bojowe (zamiast surowego `wounds_received +=`). Unifikuje: kill-loop (emit `ModelKilled`), reducer replay (`niebezpieczny` slug pushuje rany na replay), oraz bilans Przegrupowania (teren = część `received`). Bez tego modele nigdy nie ginęły od terenu i replay nie był bit-perfect (cicha mutacja poza event-sourcingiem, analog bug #6 z B3.9).

### D7. Pokonanie → location w producerze ORAZ mirror-reducerze

Każde pokonanie ostatniego modelu ustawia `location` w **dwóch lustrzanych miejscach**: producer (`combat`/`phases`) + reducer (`reducers.py`) — wymóg bit-perfect replay (`apply_events(initial, events) == live_state`). Pokrywa 3 ścieżki: rany (`_allocate_wounds_to_defender` → WYCOFANY, lub ELIMINOWANY gdy `wounds_eliminating>0`), morale (`_regroup_test` `failures>=3` → WYCOFANY), Zguba (ELIMINOWANY przez `ModelKilled.eliminated`). Guard `wiped_this_call = wiped and bool(killed_events)` zapobiega nadpisaniu location przez drugą pulę alokacji na już-pokonanym oddziale.

### D8. Dywersant + R5.b deferred (H3, H4 RESOLVED — user decisions)

- **Dywersant (id 6)** — cost-side done (R2: recipe + weapon mult ×1.2), engine-side policy (×2 ataki vs Przyszpilony) **deferred do post-MVP** (`effects.INCOMPLETE_ABILITIES` stub). Wymaga interrupt framework + decyzji policy.
- **R5.b (akcja-różna / Manewr-free / per-action tracking) NIE implementowane** — Szarża i Ostrzał mają wprost limit „raz na aktywację" w zasadach; złożone per-action-different tracking jest zbędne.
- **Klątwa/Rozkaz/Oznaczenie (id 45/49/50)** — `rozkaz_tak` field dodany (cost + metadata), engine interrupt handler **odłożony** (wymaga interrupt orchestracji w phases + decyzji policy; osobny podetap).

## Mapowanie: pkt zasad ↔ moduły engine

| Punkt zasad | Moduł / symbol | Faza |
|---|---|---|
| pkt 26 (Lokalizacja) | `state.Lokalizacja`, `UnitBlob.location`, `build_initial_state` ZAPLECZE guard | R5.a |
| pkt 27.b (pokonanie → Wycofany) | `combat._allocate_wounds_to_defender`, `phases._regroup_test`, `reducers._reduce_model_killed`/`_reduce_morale_test` | R5.a |
| pkt 26.d/27.a (Eliminowany / Zguba) | `UnitBlob.wounds_eliminating`, `combat` ABILITY_ZGUBA, `ModelKilled.eliminated`, `Shot/MeleeResolved.wounds_eliminating` | R4.Zguba |
| pkt 20.a/b/c (Przegrupowanie) | `phases._regroup_test`, `ActivationContext.dealt_for`/`delta_for` | R5.d |
| pkt 22.b/c (mutex statusów) | `events.MutexCollision`, `reducers._reduce_mutex_collision`, `phases._apply_mutex_collisions` | R5.e |
| pkt 13.c (Ufortyfikowany rozstawienie) | `phases.deployment_round` StatusAdded(Ufortyfikowany) + ZAPLECZE guard | R5.f |
| pkt 4.c.v (Niebezpieczny teren) | `phases._apply_maneuver`, `_blob_inside_terrain_circle`, `_allocate_wounds_to_defender` | R5.g |
| pkt 14.d.iv (kontratak Wyczerpany) | `combat.resolve_charge_attack` (`charger_after_counter.models_alive > 0` guard) | R5.c |
| Aury/Rozkazy (T_eff) | `cost_functions.t_eff`/`aura_range_bonus`/`order_bonus`, `handlers._aura_cost`/`_order_like_cost`, `tables.aura_order_formula` | R1/R3 |
| `rozkaz_tak` (Klątwa/Rozkaz/Oznaczenie) | `abilities.yaml` (88 abilities: 30 true), `RulesetAbility` Pydantic | R4 |
| 8 zdolności (opisy) | `abilities.yaml`, `app/data/abilities.py` (procedural oracle) | R2/R6 |

## Konsekwencje

**Pozytywne:**
- **B2 ORM schema zamrożone** — `BattleEvent.payload_json` per unit: +`location: Lokalizacja` enum, +`wounds_eliminating: int`; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`; nowy event `MutexCollision`. Zero migration churn dla B2.
- **Drift gate CLEAN/WARN** — sources SHA256 match (4 pliki), drift R1=0/R2=0/R3=29 WARN (description wording, akceptowalne per ADR-0006).
- **Parity zachowana** — `both_assert` 156/156, `yaml` 93/93 mimo wymiany formuły aur/rozkazów (procedural oracle zsynchronizowany).
- **Replay bit-perfect** — `location` + `wounds_eliminating` w `_BLOB_REPLAY_FIELDS`; smoke replay GATE EXIT 0.

**Negatywne / dług:**
- **Faza Leczenia (pkt 21) nie istnieje** w engine — heal-revive (ELIMINOWANY nie wraca, limit odzyskania pomniejszony o `wounds_eliminating`) zapisane jako **H7 (OPEN)**. Pole `wounds_eliminating` jest już persystowane, więc to czysto logika przyszłej fazy (nie blokuje B2/B4).
- **Klątwa/Rozkaz/Oznaczenie + Dywersant engine policy** odłożone — `INCOMPLETE_ABILITIES` stubs. Cost-side done.
- **T_eff zastąpiło referencyjne wartości s.5** — stare aury/rozkazy nie produkują już dokładnie 24/30 dolarów; to świadoma zmiana SSOT, nie regresja.

## Alternatywy odrzucone

1. **T_eff z floor/round** (H1 opcja a/b). Odrzucone — formuła zastępuje arbitralne wartości s.5; float bez zaokrąglania jest prostszy i nie wymaga uzgadniania z nieistniejącymi już referencjami. `both_assert` przeszedł z float.
2. **Zguba jako 3-cia pula alokacji ran** (`wounds_received` split na precise/regular/eliminating). Odrzucone — sprzeczne z pkt 17.d (tylko 2 pule alokacji). Restrukturyzacja 4 pól ran vs dodanie 1 licznika. Wybrano licznik.
3. **Mutex w reducerze (deterministic)** lub **producer-only silent removal**. Odrzucone — reducer-deterministic wkłada logikę gry do reducera (komplikuje replay); producer-only nie zostawia śladu w event logu. Wybrano explicit `MutexCollision` event (ADR-0046 spójność).
4. **Lokalizacja jako StatusFlag**. Odrzucone — Lokalizacja jest wzajemnie wykluczająca (1 z 4), statusy są niezależnymi flagami; enum na blobie jest naturalniejszy i type-safe.
5. **R5.b per-action-different tracking** (track `actions_used` + Niestrudzony/Manewr exceptions). Odrzucone (H4) — zasady mają wprost limit „raz na aktywację" dla Szarży/Ostrzału; complex tracking byłby premature.

## Powiązane ADR-y

- **ADR-0006** (pipeline drift) — `make rules-check` wykrył drift, zweryfikował resync (sources SHA256 + R1-R4).
- **ADR-0008** (Pareto MVP) — Lokalizacja/Zguba mieszczą się w modelu oddział=koło; Dywersant deferred spójnie z Pareto trade-off.
- **ADR-0010** + **ADR-0046** (event-sourced) — `MutexCollision` + `location`/`wounds_eliminating` propagacja przez reducery; replay invariant rozszerzony.
- **ADR-0011** (rule executor) — Public API rozszerzone o `Lokalizacja`, `t_eff`/`aura_range_bonus`/`order_bonus` (refresh 2026-06-08).
- **ADR-0014** (per-unit wounds) — **refresh:** dodanie pojedynczego pola-licznika `wounds_eliminating` (NIE restrukturyzacja na 3-pula).
- **ADR-0045** (ActivationContext) — trigger Przegrupowania (D5) używa `dealt_for`/`delta_for`.
