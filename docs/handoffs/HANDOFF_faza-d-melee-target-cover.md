# HANDOFF — faza-d-melee-target-cover

> **Wątek:** Strumień D — naprawa skażenia heurystyki wyboru celu Szarży (melee) w botach `PriorityV2Player`/`PriorityV3Player`: scoring celów melee przez `expected_damage(..., state.terrain)` stosuje osłonę (pkt 19, ranged-only), wbrew silnikowi melee który osłony nie liczy.
> **Status:** In progress
> **Utworzony:** 2026-06-12
> **Ostatnia aktualizacja:** 2026-06-12

## Cel

Boty priorytetowe (v2/v3) wybierają cel Szarży maksymalizując `expected_damage` z `prediction.py`. `expected_damage` modeluje **Ostrzał** (pkt 17+19): gdy podany jest `terrain`, liczy osłonę przez `compute_cover` → −1 do trafienia / +1 obrony celu. Silnik melee (`combat.resolve_melee_attack` / `resolve_charge_attack`) **nie wywołuje `compute_cover`** (jedyne wywołanie to linia ~361 w ścieżce ranged). Skutek: cel za zasłoną dostaje zaniżoną wagę jako cel Szarży, mimo że faktyczny atak wręcz osłony nie uwzględnia → wybór celu melee skażony karą zasięgową/zasłony, łamie inwariant prediction↔combat (ADR-0044).

**Fix:** scoring celów Szarży (melee) musi przekazywać pusty `terrain` do `expected_damage` (osłona nie dotyczy melee, pkt 19 = Ostrzał). Dotyczy `priority_v2_player` i `priority_v3_player`. Zero zmian w rdzeniu silnika / prediction.

## Źródło reguł (odczytane 2026-06-12)

- **pkt 19** (`SZOP_Rozjemca.md:141`): „Osłona: jeżeli większość modeli atakowanego oddziału ma osłonę, atakujący otrzymuje −1 do trafienia (pkt 17.a). Jeżeli szansa trafienia wynosi już 6+, zamiast tego broniący się otrzymuje +1 do obrony (pkt 17.b)." — osłona wiązana z testem trafienia.
- **pkt 14.d.iii** (`:107`): modele w 2″ od celów wykonują „Atak (pkt 17) bronią wręcz".
- Silnik: `combat.py` wywołuje `compute_cover` **tylko** w ścieżce ranged (`resolve_ranged_attack`, ~linia 361). `resolve_melee_attack` (~480) i `resolve_charge_attack` (~629) osłony nie liczą → prediction dla melee musi być spójny (terrain pusty).

## Zablokowane pliki / katalogi

- `app/services/agents/priority_v2_player.py` — call-site scoringu Szarży (`_act`, krok 3)
- `app/services/agents/priority_v3_player.py` — `_a_charge` + `_best_achievable_target_weight` (scoring osiągalnych celów Szarży)
- `tests/test_agents_priority_v2.py`, `tests/test_agents_priority_v3.py` — testy regresyjne (cel za zasłoną = równa waga melee)

## Blokuje / Blokowane przez

- **Blokuje:** nic (jakość heurystyk, nie poprawność silnika).
- **Blokowane przez:** nic. Czysta warstwa agentów.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

- [x] **F1 — `priority_v2_player`:** w `_act` krok 3 (Szarża) scoring celu przez `_best_target(unit, reachable, weapon, ())` zamiast `state.terrain`. Komentarz pkt 19 (melee bez osłony).
- [x] **F2 — `priority_v3_player`:** `_a_charge` (`_best_target(..., ())`) + `_best_achievable_target_weight` (Szarża z pustym terrain, Ostrzał honoruje teren). Selekcja przez `_target_weight` dla broni melee → pusty terrain.
- [x] **F3 — testy regresyjne:** v2 + v3 `test_charge_target_ignores_cover_pkt19` — cel za zasłoną Obronną (id 2) vs bez (id 3), równy dystans; po fixie tie-break id → id 2. **Zweryfikowano realność regresji**: PRE-fix `_best_target(...terrain)` → id 3, POST-fix `()` → id 2 (oba boty). Ostrzał nadal honoruje teren (krok shoot bez zmian).
- [x] **F4 — weryfikacja end-to-end (DoD):** pytest pełna suite **1607 passed** (1605 baseline + 2; 1 fail = znany tripwire `test_real_source_hashes_match`, blokada pkt 20.f.i, NIE regresja). `/simplify` 4 kąty inline — 0 zmian (kod czysty; `()` to literał, v2/v3 świadomie osobne moduły, prediction.py MVP ranged-only → call-site to właściwa głębokość). `/review` pominięty warunkowo (izolowana warstwa agentów, <50 linii prod, brak hot-path/SSOT/auth). `/security-review` N/A (brak auth/DB/user-input).

## Status: DONE — gotowe do archiwizacji

Sedno naprawione w v2+v3: scoring celu Szarży przekazuje pusty `terrain` do `expected_damage` → osłona (pkt 19, ranged-only) nie skaża wyboru celu melee; spójne z silnikiem (`resolve_melee_attack`/`resolve_charge_attack` nie liczą `compute_cover`) i inwariantem ADR-0044. Ostrzał nadal honoruje teren. Zero zmian w rdzeniu silnika / prediction.

## Pliki dotknięte

*(wypełni się w trakcie)*

## Hipotezy / pytania otwarte

- Czy w obu botach pierwsza broń melee jest jedyną używaną w scoringu? Tak (MVP: `melee_weapons[0]`/`_charge_candidates`). Multi-weapon poza zakresem.

## Jak zweryfikować

```powershell
python -m pytest tests/test_agents_priority_v2.py tests/test_agents_priority_v3.py -q
python -m pytest -q   # full suite — baseline 1605 + nowe testy
```

## Decyzje

- 2026-06-12: Fix przez przekazanie pustego `terrain` do `expected_damage` przy scoringu Szarży (nie przez nowy melee-prediction) — minimalna zmiana spójna z faktem, że silnik melee osłony nie liczy. Pełny melee-prediction (Furia/Impet/kontratak) poza zakresem MVP prediction.py.

## Notatki / odkrycia w trakcie

- Pochodzenie: F6 (REVIEW_2026-06-11) + obserwacja `_target_weight` (REVIEW_2026-06-12). Oba flagowane jako „jakość heurystyk, kandydat na tuning w faza-d".
