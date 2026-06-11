# HANDOFF — faza-b-regroup-choice

> **Wątek:** Konsekwencja nieudanego Przegrupowania (1 porażka) = WYBÓR kontrolującego gracza Wyczerpany/Przyszpilony (pkt 20.f.i po poprawce źródła). Silnik + boty.
> **Status:** In progress
> **Utworzony:** 2026-06-11

## W TRAKCIE: 2026-06-11 — callback `regroup_choice` przez phases/resolver/match + `Player.choose_regroup_consequence` + drzewo wyboru w v3. Dotykam `phases.py`/`resolver.py` (addytywny param) + `agents/{base,match,priority_v3}.py`. NIE ruszam state.py/eventów (reducer + `result_status="pinned"` JUŻ istnieją).

## Cel
Źródło pkt 20.f.i (po poprawce usera): „jedna: kontrolujący wybiera czy oddział zostaje Wyczerpany czy Przyszpilony". Silnik hardcoduje Wyczerpany (`_regroup_test`, „default Wyczerpany dla MVP"). Dodać wybór gracza.

## Kluczowe ułatwienie
Event `MoraleTestPassed.result_status` JUŻ obsługuje `"pinned"` (reducer `_reduce_morale_test` linia 284 dodaje Przyszpilony). Schemat eventu + replay gotowe → wystarczy emitować `result_status="pinned"` gdy gracz wybierze Przyszpilony. Zero zmian w events/reducers/state.

## Plan
- [x] 1: `Player.choose_regroup_consequence(state, unit)` (default "exhausted").
- [x] 2: `_regroup_test(..., regroup_choice=None)` — `failures==1`: callback → "pinned" emituje `result_status="pinned"` + Przyszpilony; inaczej Wyczerpany.
- [x] 3: `regroup_choice` przez `_apply_single_action` → `activation_phase`/`apply`/`apply_activation`. Default None → Wyczerpany (102 testy phases/resolver/replay zielone).
- [x] 4: `match.run_match` — callback dispatch do `players[blob.owner_player]`.
- [x] 5: v3 `choose_regroup_consequence` (drzewo usera).
- [x] 6: `tests/test_engine_regroup_choice.py` (4: default exhausted, choice pinned, replay bit-perfect, callback dostaje kontrolowany blob) + `test_regroup_choice_tree` (v3 drzewo). pytest 1608; smoke replay EXIT 0; both_assert 156/156.
- [x] 7: `source_hashes.yaml` (tylko hash Rozjemca). Roadmap; archiwizacja.

## Wynik
Wybór działa i jest replay-safe (event niesie `result_status`). Tylko v3 używa drzewa; reszta default Wyczerpany. Balans: lekka poprawa v3 (unit_profiles v3/random 83%→88%).

## DRIFT DO ZGŁOSZENIA (user reorganizował pkt 20 — NIE w zakresie tej zmiany)
- **pkt 20.e Nieustraszony** zmienione: NOWE „powyżej połowy → **0 testów Przegrupowania**" (skip wszystkich) vs STARE „znosi pkt 20.a" (−1 do liczby testów). Engine `_regroup_test` używa `aggregate_morale_modifier` (Nieustraszony −1) — może drift'ować (przy melee Nieustraszony nad-połową: engine daje 1 test melee, nowy .md daje 0). Do osobnego sprawdzenia/fix.
- pkt 20.a „w ostatniej akcji" (było „w wykonanej akcji") — semantycznie zgodne z obecną implementacją (per-akcja delta).

## Założenia / flagi
- Domyślnie (callback None, np. random/greedy/simple/v2) → "exhausted" (zachowanie sprzed zmiany).
- **Drift do zgłoszenia (NIE w zakresie):** user przebudował pkt 20 — Nieustraszony 20.e („powyżej połowy → 0 testów" vs stare „znosi 20.a"), „w ostatniej akcji" (20.a). Engine `_regroup_test` może drift'ować na Nieustraszony — sprawdzić osobno.

## Decyzje
- 2026-06-11: Wybór tylko w v3 (jego spec). Base + reszta botów = default "exhausted".

## Notatki
- 2026-06-11: reducer/event gotowe na "pinned" — minimalna zmiana. Replay: live emituje wybrany result_status, replay go odtwarza.
