# HANDOFF — faza-d-priority-v3

> **Wątek:** `PriorityV3Player` — bot z drzewem decyzyjnym akcji (29 węzłów), wielokryterialną selekcją aktywacji i ważonym wyborem celu. Wersje prosty/v2 zachowane do porównań.
> **Status:** In progress
> **Utworzony:** 2026-06-11

## W TRAKCIE: 2026-06-11 — nowy moduł `priority_v3_player.py` + `priority3` w balance_simulate + testy. Zero zmian w prostym/v2/silniku.

## Spec usera (2026-06-11)
- **Selekcja aktywacji** (lexyko): 1) ma w zasięgu cel o najwyższej wadze ataku; 2) zdrowy (nie Przyszpilony/Wyczerpany); 3) najbliżej wroga nieaktywowanego; 4) najbliżej zdrowego; 5) najbliżej dowolnego.
- **Akcja**: drzewo decyzyjne 29 węzłów (Wojownik vs Strzelec; Szarża/Ostrzał/Manewr/Obrona/discard zależnie od stanu, celów i kontroli punktów).
- **Wybór celu ataku** (waga, MAX): `-1 jeśli Aktywowany; -0.25 za każdy z {Przyszpilony, Wyczerpany, Ufortyfikowany}; +x*(4-x)` gdzie `x = oczekiwane_obrażenia / pozostała_wytrzymałość celu`.
- **Konsekwencja nieudanego Przegrupowania** (drzewo) — **ODŁOŻONE** (sprzeczne z pkt 20.f.i źródła: 1 porażka = Wyczerpany, bez wyboru; wymaga zmiany reguł + silnika).

## Założenia (udokumentowane)
- **Wojownik vs Strzelec** (silnik nie ma klasyfikacji): proxy `sum(melee attacks) > sum(ranged attacks)` → Wojownik; inaczej Strzelec. (Dla 4 profili: Strzelec-24/18 = Strzelec, Wojownik-mix/Wojownik = Wojownik.)
- **„Masz Przygotowanie"** = pasywka slug `przygotowanie` (id 25). Inertne na fixturach bez tej zdolności.
- **„Masz cel w zasięgu X"** = istnieje wróg osiągalny (range+LoS dla Ostrzału / gap≤move dla Szarży), niezależnie od stanu/zużycia. **„Możesz X"** = + nie zużyte w tej aktywacji + nie Wyczerpany (pkt 22.a.i).

## Zablokowane pliki
- `app/services/agents/priority_v3_player.py` (NEW), `__init__.py`, `scripts/balance_simulate.py` (`priority3`), `tests/test_agents_priority_v3.py` (NEW).

## Plan
- [x] 1: Moduł `priority_v3_player.py` — `_DECISION_TREE` (29 węzłów, tabela + walker z guard-em cykli), `_target_weight`, `_select_unit` (5-kryteriów z `_best_achievable_target_weight`), `continue_activation`.
- [x] 2: Eksport `PriorityV3Player` + `priority3` w balance_simulate.
- [x] 3: `tests/test_agents_priority_v3.py` (9): klasyfikacja Wojownik, waga (penalizacja Aktywowany + overkill), drzewo (Wojownik→Szarża, Strzelec→Ostrzał, exhausted→discard, ruch do celu), determinizm, **audyt legalności w 12 meczach** (0 naruszeń).
- [x] 4: Balans (60 gier): v3/random 83–90%, v3/greedy 55–98%. **v3 najsilniejszy na zróżnicowanych** (`unit_profiles`: v3 bije prosty 30:15, v2 38:25, greedy 55%), ale na jednorodnych (demo) **prosty wygrywa z v3 (52:37)**, v3 bije v2 (48:32).
- [x] 5: pytest 1603; `/simplify` inline; roadmap; archiwizacja.

## WNIOSKI
- **v3 ≈ najlepszy na zróżnicowanych armiach** (drzewo + ważony cel wykorzystują różnice profili). Na jednorodnych prosty pozostaje baseline (jak v2 — złożoność opłaca się dopiero przy różnorodności).
- **Formuła wagi celu `x*(4-x)` NIE premiuje monotonicznie dobijania** — jest symetryczna wokół x=2 (obrażenia = 2× pozostałej HP), karze overkill (x>4 → ujemne). Cel pełny (x≈0.67) i ranny-z-overkillem (x≈3.33) wychodzą RÓWNO. Jeśli intencją jest „dobijaj rannych", formuła wymaga zmiany (np. człon rosnący z malejącą HP).
- **Regroup-consequence ODŁOŻONE** — pkt 20.f.i źródła = stały Wyczerpany (bez wyboru). Bot-choice wymaga zmiany reguł + hooka w `_regroup_test` (silnik pyta gracza). Do decyzji usera.

## Decyzje
- 2026-06-11: Regroup-consequence ODŁOŻONE (źródło pkt 20.f.i = stały Wyczerpany; bot-choice wymaga rules+engine). Reszta v3 bot-only.

## Notatki
- 2026-06-11: v2 punkt 3 celu = `p_full_kill` (premiuje dobijanie) — potwierdzone w kodzie.
