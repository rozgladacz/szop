# HANDOFF — faza-d-greedy-melee-cover

> **Wątek:** Strumień D — domknięcie rodziny fixu „melee bez osłony" (pkt 19) w `GreedyPlayer`: `_attack_score` skoruje też Szarżę (`ChargeAction`) przez `expected_damage(..., state.terrain)`, stosując osłonę wbrew silnikowi melee.
> **Status:** In progress
> **Utworzony:** 2026-06-12
> **Ostatnia aktualizacja:** 2026-06-12

## Cel

Kontynuacja `faza-d-melee-target-cover` (archived 2026-06-12, commit `8a8154d`). Call-site search tamtego wątku był niepełny — `GreedyPlayer._attack_score` (`greedy_player.py:151`) ma ten sam wzorzec: scoruje zarówno Ostrzał (`ShootAction`) jak i Szarżę (`ChargeAction`) przez `expected_damage(attacker, defender, action.weapon, state.terrain)`. Dla Szarży (melee) osłona (pkt 19) nie dotyczy — silnik melee (`resolve_melee_attack`/`resolve_charge_attack`) nie liczy `compute_cover`. Skutek: `dist.mean` (człon HP) oraz `expected_kills` (Δ kontroli celów) zaniżone dla celów Szarży za zasłoną → skażony scoring akcji greedy.

**Fix:** w `_attack_score` przekazać teren do `expected_damage` tylko dla `ShootAction`; dla `ChargeAction` pusty `()`. Zero zmian w rdzeniu silnika/prediction.

## Źródło reguł (odczytane 2026-06-12, wspólne z poprzednim wątkiem)

- **pkt 19** (`SZOP_Rozjemca.md:141`): osłona wiązana z testem trafienia Ostrzału (pkt 17.a/b).
- Silnik: `combat.compute_cover` wywoływane tylko w ścieżce ranged (`resolve_ranged_attack`, ~linia 361). Melee paths osłony nie liczą.

## Zablokowane pliki / katalogi

- `app/services/agents/greedy_player.py` — `_attack_score` (linia ~151) + docstring modułu
- `tests/test_agents_greedy.py` — test regresyjny

## Blokuje / Blokowane przez

- **Blokuje:** nic (jakość heurystyk).
- **Blokowane przez:** nic.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

- [x] **G1 — `greedy_player._attack_score`:** `terrain = state.terrain if isinstance(action, ShootAction) else ()`; `expected_damage(..., terrain)`. Komentarz pkt 19 + docstring modułu zaktualizowany (Szarża pusty teren).
- [x] **G2 — test regresyjny:** `test_charge_score_ignores_cover_pkt19` — score Szarży na cel za zasłoną Obronną == bez zasłony (fix); kontrola: Ostrzał z osłoną < bez (teren realnie tworzy osłonę).
- [x] **G3 — weryfikacja end-to-end (DoD):** pytest pełna suite **1608 passed** (1607 baseline + 1; 1 fail = znany tripwire `test_real_source_hashes_match`, NIE regresja). `/simplify` 4 kąty inline — 0 zmian (call-site to właściwa głębokość; prediction.py MVP ranged-only). `/review`/`/security-review` pominięte warunkowo (izolowana warstwa agentów, ~6 linii prod, brak hot-path/SSOT/auth/DB).

## Status: DONE — gotowe do archiwizacji

`GreedyPlayer._attack_score` scoruje Szarżę z pustym terenem (osłona pkt 19 = tylko Ostrzał). Domknięta rodzina fixu z `faza-d-melee-target-cover` (v2/v3 + teraz greedy). Wszystkie 3 boty używające `expected_damage` spójne.

**Follow-up (NIE blokujące, odnotowane w parent):** wzorzec „melee → pusty teren" powtarza się w 3 botach. Rozważyć centralizację: `prediction.expected_melee_damage(attacker, defender, weapon)` (cienki wrapper `expected_damage(..., terrain=())`) gdy melee-prediction dostanie melee-specyficzne efekty (Furia/Impet/kontratak). Dziś przedwczesne — call-site z komentarzem wystarcza.

## Pliki dotknięte

*(wypełni się w trakcie)*

## Decyzje

- 2026-06-12: Rozróżnienie melee/ranged przez `isinstance(action, ShootAction)` w call-site (spójne z `faza-d-melee-target-cover`; prediction.py MVP ranged-only).

## Notatki / odkrycia w trakcie

- Wykryte podczas KROK 5 (drugi task sesji autonomicznej) — pełny `grep expected_damage app/services/agents/` ujawnił 3 boty z tym wzorcem; v2/v3 naprawione w `faza-d-melee-target-cover`, greedy pozostał.
