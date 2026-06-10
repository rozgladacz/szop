# HANDOFF — faza-d-greedy-objectives

> **Wątek:** Dodanie kontroli celów (pkt 5.d/5.f) do heurystyki `GreedyPlayer` — atak/manewr punktowane na wspólnej skali wartości celów, nie tylko obrażeń.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — `app/services/agents/{policy_eval,greedy_player}.py` + testy. Zakres: warstwa agentów (NIE rdzeń silnika) — `engine/*` nietknięte → brak kolizji z lockami `faza-b-order-interrupts`.

## Cel

`GreedyPlayer` (D1) przegrywa z `RandomPlayer` na symetrycznym demo (D2 balance_simulate ujawniło ~0:7), bo zwycięstwo liczy się po zajętych celach (pkt 5.f), a bot przy Ostrzale/Szarży maksymalizuje **wyłącznie** oczekiwane obrażenia (`mean × WOUND_VALUE`), ignorując cele. Dodatkowo kontrola celów (`obj.controller`) jest przeliczana dopiero w `round_end_phase` (pkt 8.c.ii), więc w hipotetycznym stanie ruch na cel widać tylko jako proximity (≤5), nie przejęcie (`OBJECTIVE_WEIGHT`=25).

Cel: punktować **każdą** akcję na wspólnej walucie wartości celów (kontrola pkt 5.d przeliczona z pozycji + proximity), nie tylko obrażeniach. Atak czyszczący wroga z celu i manewr zajmujący cel dostają kredyt za zmianę kontroli.

## Zablokowane pliki / katalogi
- `app/services/agents/policy_eval.py` — refaktor na `_hp_balance`/`_objective_balance` + nowy `objective_balance_with_control` (przelicza kontrolę przez `phases._check_objective_control`, SSOT pkt 5.d).
- `app/services/agents/greedy_player.py` — atak/manewr dodają Δ`objective_balance_with_control`.
- `tests/test_agents_greedy.py`, `tests/test_agents_policy.py` — nowe testy.

## Blokuje / Blokowane przez
- **Blokuje:** nic.
- **Blokowane przez:** nic — czysta warstwa agentów nad publicznym API silnika.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — policy_eval: wspólna waluta celów
- [x] 1.1: Refaktor `evaluate_state` na `_hp_balance(state, p)` + `_objective_balance(state, p)` (reuse; zachowanie 1:1 — testy istniejące zielone).
- [x] 1.2: `objective_balance_with_control(state, p)` — `_check_objective_control(state)` (SSOT pkt 5.d, import z `phases`) → `_objective_balance(controlled, p)`. Brak cyklu importów (phases już w grafie agentów via match.py).

### Faza 2 — greedy: atak/manewr widzą cele
- [x] 2.1: `choose_action` liczy `base_objective = objective_balance_with_control(state, p)` raz.
- [x] 2.2: `_maneuver_score` = Δ`objective_balance_with_control` (hipotetyczny ruch przez `_replace_blob`) − base.
- [x] 2.3: `_attack_score` = `mean × WOUND_VALUE` (fine-grained HP) **+** Δ`objective_balance_with_control` na hipotetycznym stanie (`_apply_expected_kills` obniża `models_alive` o `round(expected_models_killed())`). Brak double-count.

### Faza 3 — testy (+6: 4 policy + 2 greedy)
- [x] 3.1: `test_agents_policy` (+4): control flip na niezajętym celu, kontestacja zostaje None, Przyszpilony nie kontroluje (pkt 22.b.ii), wróg na celu = −OBJECTIVE_WEIGHT.
- [x] 3.2: `test_agents_greedy` (+2): `test_prefers_taking_objective_over_weak_attack`, `test_attack_prefers_enemy_contesting_my_objective`.
- [x] 3.3: istniejące 10 testów greedy/policy zielone (brak regresji).

### Faza 4 — Weryfikacja end-to-end (Definition of Done)
- [x] `python -m pytest -q` — **1525 passed** (1519 baseline + 6).
- [x] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — **156/156**.
- [x] `balance_simulate` na fixturze `objective_clash` (cel w 1 ruchu): greedy vs random **18:0** (36% W, 64% remis, 0 porażek) vs random-random ~remisy → mechanizm działa. Na demo (cel ~12″) greedy nadal przegrywa = miopia depth-1 (D4).
- [x] `/simplify` inline 4 kąty — 1 dedup (`_replace_blob` wspólny dla manewru i kills); reuse `_check_objective_control` (SSOT) + `_hp_balance`/`_objective_balance`. Call-site check: `evaluate_state` tylko testy+export (zachowanie 1:1).
- [~] `/review` — warunkowo (zmiana logiki decyzji bota; izolowana warstwa, pełne pokrycie testami → decyzja przy domknięciu).
- [!] `/security-review` — N/A (brak auth/DB).
- [x] roadmap update (D1 greedy + policy_eval) + `/handoff-archive` w toku.

## Pliki dotknięte
- `app/services/agents/policy_eval.py` (MOD) — `_hp_balance`/`_objective_balance` refaktor + `objective_balance_with_control` (przelicza kontrolę pkt 5.d).
- `app/services/agents/greedy_player.py` (MOD) — atak/manewr Δ wartości celów; `_replace_blob`/`_apply_expected_kills` helpery.
- `tests/test_agents_policy.py` (+4), `tests/test_agents_greedy.py` (+2).
- `tests/fixtures/battles/objective_clash.yaml` (NEW) — demonstracja: cel osiągalny w 1 ruchu.
- `docs/roadmap.md` (MOD) — D1 greedy/policy update.

## Decyzje zamrożone (NIE podnosić ponownie)
*(brak)*

## Hipotezy / pytania otwarte
- **H1 (`READY`):** Hipotetyczne ofiary ataku modelowane przez `round(expected_models_killed())` — kontrola celu flipuje tylko gdy atak praktycznie wymiata oddział (models→0 opuszcza 3″). Częściowe obrażenia nie zmieniają kontroli, ale fine-grained `mean × WOUND_VALUE` nadal je wycenia. Rozsądny Pareto MVP.

## Jak zweryfikować
```powershell
python -m pytest tests/test_agents_greedy.py tests/test_agents_policy.py -v
python -m pytest -q
python scripts/balance_simulate.py -n 50 --players greedy,random
```

## Decyzje
- 2026-06-10: Reużycie `phases._check_objective_control` jako SSOT pkt 5.d zamiast replikacji 3″-checku ([CRITICAL] #3).

## Notatki / odkrycia w trakcie
- 2026-06-10: `evaluate_state` JUŻ zawiera kontrolę celów (`OBJECTIVE_WEIGHT`); luka tylko w `GreedyPlayer._attack_score` (omija evaluate_state) + brak przeliczenia kontroli w hipotetycznym stanie (controller aktualizowany dopiero w round_end_phase).
