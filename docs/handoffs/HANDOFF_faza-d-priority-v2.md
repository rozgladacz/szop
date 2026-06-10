# HANDOFF — faza-d-priority-v2

> **Wątek:** `PriorityV2Player` — rozbudowany bot pół-deterministyczny (wielokryterialna selekcja aktywacji + ruch przechwytujący + wybór celu ataku przez `prediction`). Wersja „prosta" (`PriorityPlayer`) zachowana do porównań.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — nowy moduł `app/services/agents/priority_v2_player.py` + rejestracja `priority2` w balance_simulate + testy. Zero zmian w `PriorityPlayer` (prosta wersja) i w rdzeniu silnika.

## Cel
User rozbudowuje bota priorytetowego. Zachowujemy obecny `PriorityPlayer` jako „simple" baseline; nowy `PriorityV2Player` realizuje pełniejszy spec (selekcja po stanie wroga + ruch obronny/przechwytujący + wybór celu ataku po szansie pokonania/obrażeniach). Oba dostępne w `balance_simulate` (`priority` vs `priority2`) do porównań.

## Spec usera (2026-06-10)
**Selekcja aktywacji** (lexykograficznie, własny oddział): 1) nie Przyszpilony/Wyczerpany; 2) najbliżej wroga NIEaktywowanego; 3) najbliżej wroga nie-Przyszpilony/Wyczerpany; 4) najbliżej dowolnego wroga. (remis→id)
**Akcja**: 1) zdejmij Wyczerpany; 2) Strzelaj; 3) Szarżuj; 4) zdejmij Przyszpilony; 5) ruch do niezajętego celu, dla którego jesteś najbliższym oddziałem; 6) ruch do najbliższego wroga, który jest bliżej niż ty celu zajętego przez nas, dla którego jesteś najbliższym (przechwyt obronny); 7) ruch do dowolnego niezajętego celu; 8) ruch do najbliższego wroga.
**Wybór celu ataku** (lexykograficznie): 1) nie Przyszpilony/Wyczerpany; 2) nie Aktywowany; 3) najwyższa szansa pokonania (p_full_kill); 4) najwyższe oczekiwane obrażenia (mean); 5) najbliżej. (remis→id)

## Zablokowane pliki / katalogi
- `app/services/agents/priority_v2_player.py` (NEW)
- `app/services/agents/__init__.py` (eksport `PriorityV2Player`)
- `scripts/balance_simulate.py` (`priority2` w PLAYER_KINDS + make_player)
- `tests/test_agents_priority_v2.py` (NEW)

## Plan
- [x] 1: Moduł `priority_v2_player.py` — `_select_unit` (4-kryteria), `_best_target` (prediction p_full_kill/mean), `_act` (priorytet 1–8 + `_intercept_move`), `continue_activation`. Reuse helperów base + priority_player.
- [x] 2: Eksport `PriorityV2Player` + `priority2` w balance_simulate (PLAYER_KINDS + make_player).
- [x] 3: Testy `tests/test_agents_priority_v2.py` (12: selekcja zdrowy/nieaktywowany, target zdrowy/nieaktywowany/nearest, priorytety 1/3/5/6/8, przechwyt, continue, determinizm).
- [x] 4: Balans (60 gier): v2/random 67–70%, v2/greedy 78–98% — bije oba. **v2/priority (prosty): 1.7% (demo) / 17% (clash) — v2 PRZEGRYWA z prostą wersją.**
- [x] 5: DoD: pytest **1571**; `/simplify` inline; roadmap; `/handoff-archive`.

## WYNIK / WNIOSEK
Rozbudowany v2 bije random i greedy, ale **przegrywa głową w głowę z prostym `PriorityPlayer`** (demo 1:47, clash 10:42). Hipotezy (do iteracji jeśli user chce):
- **Wybór celu „preferuj zdrowego/nieaktywowanego"** → v2 rozprasza ogień na świeże cele zamiast DOBIJAĆ ranne/skupiać ogień → mniej eliminacji. Prosty strzela najbliższego (de facto stała koncentracja). To prawdopodobnie główny powód.
- **Ruch przechwytujący (pkt 6)** cofa/odciąga oddziały do obrony zamiast naporu na cele → mniej zdobytych celów.
- Selekcja po stanie wroga (nieaktywowany) nie kompensuje powyższych.
Możliwa poprawka v2: zmienić target-priorytet na „dobij rannego/skup ogień" (np. min `models_alive` / max `expected_models_killed`) zamiast „preferuj zdrowego".

## Decyzje
- 2026-06-10: `priority` (simple) ZOSTAJE; `priority2` to NOWY bot (porównania). „szansa pokonania" = `DamageDistribution.p_full_kill()` (cały oddział); MVP target eval na `ranged_weapons[0]`/`melee_weapons[0]`.

## Notatki / odkrycia w trakcie
- 2026-06-10: Wątek z iteracji usera nad botem priorytetowym (po `faza-b-multi-action` + korekcie geometrii mapy).
