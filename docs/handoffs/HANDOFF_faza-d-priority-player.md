# HANDOFF — faza-d-priority-player

> **Wątek:** Bot pół-deterministyczny `PriorityPlayer` (selekcja po koszcie + cel-w-zasięgu, akcja po stałym priorytecie 1–7) + ocena w `balance_simulate`.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — `app/services/agents/priority_player.py` (NEW) + testy + eksport. Zakres: warstwa agentów, zero zmian w `engine/*` → brak kolizji z `faza-b-order-interrupts`.

## Cel

Zaimplementować zaproponowanego przez usera bota pół-deterministycznego i zmierzyć go (`balance_simulate`) vs Random/Greedy na fixturach wiernych regułom (5 celów / 4 oddziały).

**Spec usera:**
- **Selekcja oddziału:** aktywuj najdroższy oddział, który ma cel w zasięgu.
- **Priorytet akcji (w aktywacji):** 1) Strzelaj do najbliższego; 2) Szarżuj na najbliższego; 3) Zdejmij Wyczerpany; 4) Zdejmij Przyszpilony; 5) Jeśli (Wojownik/Mag) i kontrolujesz mniej celów niż przeciwnik → ruch do najbliższego nie-twojego celu; 6) Ruch do najbliższego celu, jeśli nie jesteś na celu; 7) Obrona.

## Mapowanie spec → silnik (źródło + kod, ta sesja)
- Krok 1 → `ShootAction` (pkt 14.c), `_can_shoot` (zasięg + LoS≠NIE_WIDZI).
- Krok 2 → `ChargeAction` (pkt 14.d), `_can_charge` (gap ≤ move).
- Krok 3 → `SpecialAction("discard_exhausted")` (pkt 22.a) gdy `STATUS_WYCZERPANY`.
- Krok 4 → `DefendAction` gdy `STATUS_PRZYSZPILONY` — Obrona daje Ufortyfikowany, który **odrzuca Przyszpilony** (pkt 22.b.v, `phases._apply_defend`). Ta sama akcja silnika co krok 7, inny warunek.
- Krok 5/6 → `ManeuverAction` ku celowi (`_move_toward`, clamp move_inches). Kontrola liczona `phases._check_objective_control` (SSOT pkt 5.d).
- Krok 7 → `DefendAction` (pkt 14.b).

## Założenia (udokumentowane — nie blokują wyniku na fixturach)
- **„najdroższy"**: silnik nie ma kosztu punktowego na `UnitBlob` → proxy `models_alive × toughness_per_model` (HP). Remis → najniższe id. **Na prostych oddziałach (identyczne statystyki) proxy jest uniform → wymiar kosztu inertny.**
- **„cel w zasięgu" (selekcja)**: cel w `circle_edge_distance ≤ move_inches`. Brak takiego oddziału → fallback: najdroższy aktywny.
- **Krok 5 „Wojownik/Mag"**: `wojownik` NIE jest slugiem w rulesecie (`mag`, `bohater` są) → warunek = pasywka ∈ {mag, bohater}. **Inertny na fixturach prostych** (brak zdolności). Pełny test wymaga fixtur ze zdolnościami + doprecyzowania „Wojownik".

## Zablokowane pliki / katalogi
- `app/services/agents/priority_player.py` (NEW)
- `app/services/agents/__init__.py` (eksport `PriorityPlayer`)
- `scripts/balance_simulate.py` (`--players` musi akceptować `priority`)
- `tests/test_agents_priority.py` (NEW)

## Plan implementacji
### Faza 1 — bot
- [x] 1.1: `PriorityPlayer(Player)` — `_select_unit` (cost + objective-in-range + fallback) + `_act` (priorytet 1–7). Reuse helpery z `base.py` + `_check_objective_control` (SSOT) + `effective_passives`.
- [x] 1.2: Eksport w `__init__`; `balance_simulate.make_player`/`PLAYER_KINDS` + `priority`.
### Faza 2 — testy (13)
- [x] 2.1: `test_agents_priority.py` — selekcja po koszcie + fallback + tie-break, każdy priorytet 1–7, hold-on-objective, determinizm.
### Faza 3 — ocena balansu
- [x] 3.1: `balance_simulate` priority vs random/greedy/priority na demo + clash (patrz Notatki).
### Faza 4 — DoD
- [x] pytest -q **1539 passed** (1526 + 13); both_assert **156/156**. `/simplify` inline (czysto, reuse OK). roadmap/HANDOFF + `/handoff-archive`.

## Pliki dotknięte
- `app/services/agents/priority_player.py` (NEW) — bot.
- `app/services/agents/__init__.py` (eksport `PriorityPlayer`).
- `scripts/balance_simulate.py` (`priority` w `PLAYER_KINDS` + `make_player`).
- `tests/test_agents_priority.py` (NEW, 13 testów).
- `docs/roadmap.md` (D1 — PriorityPlayer).

## Hipotezy / pytania otwarte
- **H1 (`READY`):** krok 5 „Wojownik" niezdefiniowany w regułach — inertny na prostych fixturach. Doprecyzowanie + fixtury ze zdolnościami = osobny follow-up jeśli user chce testować tę gałąź.

## Notatki / odkrycia w trakcie
- 2026-06-10: Hipoteza — bot powinien TRZYMAĆ cele lepiej niż Greedy: gdy oddział jest na celu i nie ma akcji combat, krok 6 nie odpala (jest na celu) → krok 7 Obrona = stoi i trzyma. Częściowo potwierdzone (patrz wyniki).
- 2026-06-10: **Wyniki balansu (60 gier/zestaw, inicjatywa naprzemienna):**
  - `demo_skirmish` (fronty 36″, brak ognia w r.1): priority vs random **20-7-33** (priority wygrywa); priority vs greedy **0-0-60** (remis); priority vs priority **0-0-60** (symetria).
  - `objective_clash` (fronty 28″, ogień od r.1): priority vs random **9-14-37** (priority PRZEGRYWA); priority vs greedy **0-0-60**; priority vs priority **0-0-60**.
- 2026-06-10: **Wniosek.** PriorityPlayer zachowuje się jak Greedy: wygrywa gdy nie ma wczesnej walki (maszeruje na cele krok 6 i trzyma — krok 6 nie odpala gdy na celu → Obrona), przegrywa gdy ogień dostępny od startu — bo **kroki 1–2 (strzał/szarża) są NAD ruchem na cel (6)**, więc oddział nie na celu strzela zamiast iść na cel; random czasem wejdzie na cel i wygra. To wprost efekt kolejności priorytetów ze spec. **„najdroższy" i krok 5 (Wojownik/Mag) są inertne** na prostych fixturach (równe statystyki, brak zdolności) — zgodnie z przewidywaniem.
- 2026-06-10: priority vs greedy = 100% remisów na obu mapach — oba deterministyczne, symetryczna mapa → lustrzane przebiegi → remis. Nie ma między nimi przewagi w tej konfiguracji.
