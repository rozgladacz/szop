# ADR-0051 — Aktywacja wieloakcyjna (pkt 11.b.iv): orkiestrator zamiast stanu

**Status:** Accepted (2026-06-10)
**Kontekst wątku:** `faza-b-multi-action` (z pytania usera w `faza-d-priority-player`).

## Kontekst

Silnik MVP kończył aktywację po **jednej** akcji (`activation_phase` → Aktywowany; `resolver.apply` → switch; `match.py` 1 apply/oddział). Reguły (pkt 11.b.iv, źródło po korekcie usera 2026-06-10) dają aktywacji **do 2 akcji** (Manewr **liczy się** do limitu; punkt „akcja różna od już wykonanych" usunięty), z ograniczeniami z definicji: **Ostrzał raz** (pkt 14.c.v), **Szarża raz** (pkt 14.d.vi), Przegrupowanie **po każdej akcji** (pkt 11.b.iii). Brak tego = brak Manewr→Ostrzał (Strzelcy nie repozycjonują się przed strzałem) → istotne zaniżenie realizmu balansu (wykryte w D2).

## Decyzja

1. **Postęp aktywacji lokalny w orkiestratorze, nie w `BattleState`.** Lista wykonanych akcji żyje w pętli `resolver.apply_activation` — `BattleState` bez nowego pola. → zero zmian schematu/replay, zero kolizji z lockiem `state.py` (`faza-b-order-interrupts`). Eventy pozostają per-akcja (prymitywy Move/Shot/... + Aktywowany + InitiativePassed) → **replay invariant zachowany bez nowych typów eventów**.
2. **Split `activation_phase`** na `_begin_activation` (zdejmij Ufortyfikowany RAZ, pkt 22.c.iv — inaczej Obrona jako akcja #1 byłaby kasowana przez start #2) + `_apply_single_action` (akcja + ActivationContext + Przegrupowanie per akcja + mutex + reset melee) + `_finalize_activation` (Aktywowany + wygaśnięcie efektów „do końca aktywacji"). Wrapper `activation_phase` = złożenie trzech (zachowanie 1:1).
3. **Dwa entry-pointy:** `apply` (1 akcja — B4 per-action API, istniejące testy) ZOSTAJE; `apply_activation(state, first_action, dice, *, continuation)` realizuje pętlę pkt 11.b.iv. `continuation: (state, unit_id, actions_taken) -> Action | None` dostarcza kolejne akcje TEGO oddziału; `None`/limit/nielegalność (`_can_take_followup`)/pokonanie → koniec.
4. **Napęd botów:** `Player.continue_activation` z domyślą `None` (1 akcja — wsteczna kompatybilność dla dowolnego `Player`). Override w Random/Greedy/Priority; kandydaci z `base.legal_followup_actions` (reużywa `legal_actions` + `_can_take_followup`, SSOT reguły).

## Konsekwencje

- **+** Manewr→Ostrzał / Ostrzał→Szarża możliwe; pętla rundy bardziej rozstrzygająca (mniej remisów w balansie). Brak migration churn (zero zmian ORM/replay).
- **+** `apply` niezmienione → B4/testy stabilne; mechanika izolowana w orkiestratorze.
- **−** Ujawnia (wzmacnia) słabość heurystyk botów: 2 akcje = więcej walki, a boty zaniedbują kontrolę celów (pkt 5.f) — follow-up D (bot objective-aware/„hold" lub depth-2).
- **Odłożone:** pełna powtarzalność Manewru jest już zgodna (limit 2 total); „Niestrudzony" (znosi ograniczenia powtórzeń) — gdy dojdzie aktywna zdolność, rozluźnić `_can_take_followup`. Aktywacja interaktywna per-akcja (B4 API z postępem między żądaniami) — gdy B4 tego wymaga, postęp przeniesie się do warstwy API/sesji (nie silnika).
