# HANDOFF — faza-d-heuristic-players

> **Wątek:** Strumień D1 — gracze heurystyczni (`app/services/agents/`): `Player(ABC)` + enumerator legalnych akcji + RandomPlayer + GreedyPlayer + `evaluate_state`. Czysta warstwa decyzji nad publicznym API silnika (B3.9), zero zmian w rdzeniu.
> **Status:** Ready for archive
> **Utworzony:** 2026-06-09
> **Ostatnia aktualizacja:** 2026-06-09

## Cel

Zbudować pierwszą warstwę botów (Strumień D, roadmap D1) konsumujących stabilne publiczne API silnika z B3/B3.9. Bot to czysta funkcja decyzji `choose_action(state, perspective) -> Action | None`. Wspólny rdzeń = **enumerator legalnych akcji** (`legal_actions`) — silnik celowo NIE udostępnia listy legalnych akcji (resolver jest jednoakcyjny), więc enumerator musi zbudować kandydatów z `actions.Action` typów. `RandomPlayer` losuje, `GreedyPlayer` maksymalizuje `prediction.expected_damage` + `evaluate_state`. To odblokowuje D2 (balance_simulate) i D3 (exploit hunt) — choć te wymagają jeszcze pętli bitwy (B4/B5 LocalClient).

**Świadome ograniczenie zakresu:** ten wątek NIE buduje pętli bitwy (driver `apply` + `round_end_phase` + alternacja inicjatywy) — to warstwa B4/B5. Boty są testowane na ręcznie zbudowanych `BattleState` (przez `build_initial_state`/`setup_phase`), bez pełnego przebiegu gry.

## Zablokowane pliki / katalogi
- `app/services/agents/` (NEW pakiet) — `__init__.py`, `base.py`, `random_player.py`, `greedy_player.py`, `policy_eval.py`
- `tests/test_agents_*.py` (NEW)
- `docs/adr/0031-heuristic-players.md` (NEW) — projekt enumeratora + dyskretyzacja ruchu

> **Brak kolizji z `faza-b-order-interrupts`:** ten wątek tworzy nowy pakiet i tylko CZYTA `app/services/engine/*` (state/resolver/prediction/los/combat/geometry). Nie edytuje żadnego pliku rdzenia silnika.

## Blokuje / Blokowane przez
- **Blokuje:** D2 (balance simulation), D3 (exploit hunting) — potrzebują graczy. (Oba też potrzebują pętli bitwy z B4/B5.)
- **Blokowane przez:** nic — engine public API stabilne po B3.9 (ADR-0011/0045/0046/0047).

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Pakiet + Player ABC + enumerator legalnych akcji — **rdzeń** — DONE
- [x] 1.1: `app/services/agents/__init__.py` — eksport `Player`, `RandomPlayer`, `GreedyPlayer`, `legal_actions`, `evaluate_state`.
- [x] 1.2: `app/services/agents/base.py`:
  - `Player(ABC)` z `choose_action(state, perspective: int) -> Action | None` (None = brak legalnej akcji dla tego gracza).
  - `legal_actions(state, perspective) -> list[Action]` — enumeruje per własny oddział nie-Aktywowany, `models_alive>0`, `location==FRONT`:
    - `DefendAction` (pkt 14.b) — zawsze.
    - `SpecialAction("discard_exhausted")` (pkt 14.e + 22.a) — jeśli Wyczerpany.
    - `ManeuverAction` (pkt 14.a) — dyskretyzacja: "stój" + ruch ≤ `move_inches` (b_mvp=6, pkt 15.a) ku najbliższemu wrogowi i ku najbliższemu celowi (clamp do dystansu ruchu).
    - `ShootAction` (pkt 14.c) — per `ranged_weapon`, per wrogi oddział z `range_inches` zasięgu i `check_los != NIE_WIDZI`.
    - `ChargeAction` (pkt 14.d) — per `melee_weapon`, per wrogi oddział w zasięgu szarży (`circle_edge_distance ≤ move_inches`).
  - Helper `_own_active_units`, `_enemies`, geometry przez `engine.geometry`.

### Faza 2 — RandomPlayer — DONE
- [x] 2.1: `random_player.py` — `RandomPlayer(seed)` na `random.Random`; `choose_action` losuje uniform z `legal_actions`. Deterministyczny per seed (replay-safe).

### Faza 3 — evaluate_state (policy_eval) — DONE
- [x] 3.1: `policy_eval.py` — `evaluate_state(state, perspective) -> float`. Bilans HP (Σ `models_alive*toughness` swoje − wroga) + kontrola/bliskość celów (pkt 5.d). `OBJECTIVE_WEIGHT=25`, `PROXIMITY_WEIGHT=5`.

### Faza 4 — GreedyPlayer — DONE
- [x] 4.1: `greedy_player.py` — `GreedyPlayer` ocenia każdą akcję: ataki przez `prediction.expected_damage(...).mean × WOUND_VALUE`; ruch przez Δ`evaluate_state`; Obrona/Odrzuć Wyczerpany stałe. Argmax, tie-break deterministyczny (pierwszy w stabilnej kolejności).

### Faza 5 — Weryfikacja end-to-end (Definition of Done) — DONE
- [x] `python -m pytest tests/test_agents_*.py -v` — **26 passed**.
- [x] `python -m pytest -q` (pełna suite) — **1489 passed** (1463 baseline + 26).
- [x] Parity gate niezmieniony (`both_assert` 156/156, `yaml` 93/93) — bot path nie rusza kosztów, sanity OK.
- [x] Call-site check — pakiet nowy, brak istniejących call sites (nikt jeszcze nie importuje `agents`).
- [x] `/simplify` (zawsze) — przegląd 4 kątów inline (reuse/simplification/efficiency/altitude): kod czysty, **0 zmian**. Reuse: brak publicznego helpera lookupu bloba (`_find_blob` prywatny) → lokalny `_blob_by_id` poprawny.
- [x] `/review` — **świadomie pominięty (judgment)**: izolowany nowy pakiet, czyste funkcje, brak hot-path/SSOT/auth, brak integracji w runtime (nikt nie wywołuje), pełne pokrycie 26 testami. Inline self-review correctness wykonany (sygnatury `expected_damage`/`check_los`/`replace` zweryfikowane). `/security-review` N/A (brak auth/user-input→DB).
- [x] Re-run `pytest` — N/A, simplify nic nie zmienił.
- [x] ADR-0031 (Accepted) + roadmap D1 statusy + ADR index + parent `faza-b-engine-mvp` notatka.
- [ ] `/handoff-archive faza-d-heuristic-players` — po commicie.

## Pliki dotknięte
- `app/services/agents/__init__.py` (NEW) — public API pakietu.
- `app/services/agents/base.py` (NEW) — `Player` ABC + `legal_actions` enumerator + selektory + `_move_inches` (lru_cache).
- `app/services/agents/random_player.py` (NEW) — `RandomPlayer`.
- `app/services/agents/policy_eval.py` (NEW) — `evaluate_state` + wagi.
- `app/services/agents/greedy_player.py` (NEW) — `GreedyPlayer` depth-1.
- `tests/test_agents_{base,random,policy,greedy}.py` (NEW) — 26 testów.
- `docs/adr/0031-heuristic-players.md` (NEW Accepted).
- `docs/roadmap.md` (D1 statusy + ADR index 0031), `docs/handoffs/HANDOFF_faza-b-engine-mvp.md` (notatka), `HANDOFF.md` (tabela wątków).

## Decyzje zamrożone (NIE podnosić ponownie)
*(brak — wątek czysto implementacyjny)*

## Hipotezy / pytania otwarte
*(Każdą pozycję taguj statusem.)*
- **H1 (`READY` — decyzja autonomiczna, udokumentowana w ADR-0031):** dyskretyzacja `ManeuverAction` — pozycja docelowa jest ciągła. MVP: kandydaci = {stój, ruch ku najbliższemu wrogowi clamp do move, ruch ku najbliższemu celowi clamp do move}. Pełna dyskretyzacja (siatka/koło kierunków) → przyszła iteracja.
- **H2 (`WAITING(B4/B5)`):** pętla bitwy (driver przebiegu gry) — boty produkują akcje, ale uruchomienie pełnej gry (D2 balance_simulate) wymaga orkiestratora `apply`+`round_end_phase`+alternacja. To LocalClient (B5) / B4 routers. Tu nie budujemy.
- **H3 (`READY`):** enumerator nie waliduje pkt 14.c.iv (Ostrzał zablokowany gdy wróg w 3″+LoS) ani limitu 2 akcji/aktywację — to egzekwuje warstwa wyższa (phases/resolver). Bot produkuje kandydatów; nielegalne odrzuci resolver. MVP heurystyka pomija te ograniczenia (udokumentowane).

## Jak zweryfikować
```powershell
python -m pytest tests/test_agents_base.py tests/test_agents_random.py tests/test_agents_policy.py -v
python -m pytest -q
```

## Decyzje
- 2026-06-09: Slug `faza-d-heuristic-players`. Pakiet `app/services/agents/` per roadmap D1 + komentarze w `engine/__init__.py`/`prediction.py`/`resolver.py` (już wskazują ten pakiet jako konsumenta).
- 2026-06-09: Enumerator legalnych akcji żyje w `base.py` (współdzielony rdzeń), nie w silniku — silnik celowo jednoakcyjny (resolver.apply). Boty same generują kandydatów.

## Notatki / odkrycia w trakcie
- 2026-06-09: Wątek utworzony (sesja codzienna autonomiczna). Wybór: D1 niekolidujące z aktywnym `faza-b-order-interrupts` (locki na rdzeniu silnika). `resolver._validate_action` NIE sprawdza dystansu ruchu (`_apply_maneuver`: "walidacja dist ≤ move_inches deferred") — enumerowane ManeuverActions nie zostaną odrzucone, ale clamp do move_inches dla poprawności heurystyki.
