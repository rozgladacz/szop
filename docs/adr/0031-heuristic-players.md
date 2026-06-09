# ADR-0031 — Gracze heurystyczni (Strumień D1): enumerator akcji + Random/Greedy

- **Status:** Accepted
- **Data:** 2026-06-09
- **Kontekst:** Strumień D (`docs/roadmap.md#strumień-d`, wątek `faza-d-heuristic-players`). Pierwsza warstwa botów potrzebna do D2 (balance simulation) i D3 (exploit hunting). Silnik (B3/B3.9, ADR-0011) udostępnia `resolver.apply(state, action, dice)` — **jednoakcyjny** dispatcher. NIE udostępnia listy legalnych akcji ani pętli przebiegu gry (to celowo warstwa orkiestracji B4/B5). Bot musi więc sam wygenerować kandydatów na akcję z `actions.Action` typów.

## Decyzja

Nowy pakiet **`app/services/agents/`** — czysta warstwa decyzji nad publicznym API silnika. Zero zmian w rdzeniu silnika (czyta tylko `state`/`actions`/`geometry`/`los`/`prediction`).

| Plik | Zawartość |
|---|---|
| `base.py` | `Player(ABC)` + `legal_actions(state, perspective)` (współdzielony enumerator) + selektory (`own_active_units`, `enemy_units`) |
| `random_player.py` | `RandomPlayer(seed)` — uniform z `legal_actions`, deterministyczny per seed |
| `greedy_player.py` | `GreedyPlayer` — depth-1 argmax wartości akcji (`expected_damage` dla ataków, Δ`evaluate_state` dla ruchu) |
| `policy_eval.py` | `evaluate_state(state, perspective) -> float` — bilans HP + kontrola/bliskość celów |

### Enumerator `legal_actions` (rdzeń)

Per własny oddział aktywowalny (żywy, nie Aktywowany pkt 22.d, na Froncie pkt 26.b) generuje kandydatów z pkt 14:
- **Obrona** (14.b) — zawsze.
- **Odrzuć Wyczerpany** (14.e + 22.a) — gdy oddział Wyczerpany.
- **Manewr** (14.a) — dyskretyzacja pozycji docelowej: `{stój, ku najbliższemu wrogowi, ku najbliższemu celowi}`, clamp do `tables.b_mvp.move_inches` (pkt 15.a).
- **Ostrzał** (14.c) — per broń dystansowa × wrogi oddział w zasięgu (`circle_edge_distance ≤ range`) z LoS ≠ NIE_WIDZI (pkt 6).
- **Szarża** (14.d) — per broń wręcz × wrogi oddział w zasięgu Związania (`circle_edge_distance ≤ move`).

### Decyzje projektowe

1. **Enumerator w warstwie agentów, nie w silniku.** Silnik pozostaje jednoakcyjny (ADR-0011). Generowanie kandydatów to logika polityki, nie reguł — różne boty mogą enumerować inaczej. Współdzielony `legal_actions` to wygoda, nie kontrakt silnika.
2. **Dyskretyzacja Manewru.** Pozycja docelowa jest ciągła; pełna enumeracja niemożliwa. MVP: 3 kierunki celowe (stój/wróg/cel). Pełniejsza dyskretyzacja (siatka, koło kierunków) → przyszła iteracja.
3. **Enumerator NIE waliduje pełnej legalności.** Limit 2 akcji/aktywację (pkt 11.b.iv), blokada Ostrzału w zwarciu (pkt 14.c.iv) — egzekwuje `phases`/`resolver`. Bot produkuje kandydatów; nielegalne odrzuci resolver (`IllegalActionError`). Powód: enumerator bez pełnej maszyny stanu aktywacji nie zna kontekstu (ile akcji już wykonano w tej aktywacji); orkiestrator to wie.
4. **Greedy używa `expected_damage` (ADR-0044) także dla Szarży.** `expected_damage` jest dystansowe; melee jako przybliżenie (combat MVP dzieli formułę pkt 17). Melee-specyficzne efekty (bilans wręcz pkt 20.c, kontratak) pominięte w ocenie — wystarczające dla depth-1 heurystyki.
5. **Determinizm.** `RandomPlayer` na `random.Random(seed)`; `GreedyPlayer` czysto deterministyczny (tie-break: pierwszy w stabilnej kolejności `legal_actions`). Spójne z replay-safe filozofią silnika (ADR-0010/0012).

### `evaluate_state`

`(Σ własne HP − Σ wroga HP) + Σ_cele [ +25 kontrola własna / −25 wroga / bonus bliskości ≤5 dla niezajętych ]`. Cel waży > typowy bilans HP jednej wymiany — pkt 5.f czyni cele rozstrzygającymi grę.

## Konsekwencje

**Pozytywne:**
- **Zero kolizji z rdzeniem silnika** — nowy pakiet, tylko odczyt API. Pozwolił uruchomić D1 równolegle z aktywnym wątkiem modyfikującym silnik (`faza-b-order-interrupts`).
- **Odblokowuje D2/D3** (gdy powstanie pętla bitwy B4/B5).
- **Testowalne w izolacji** — boty to czyste funkcje decyzji; testy na ręcznie zbudowanych `BattleState`, bez pełnej gry (26 testów).

**Negatywne / koszty:**
- **Brak pętli bitwy.** Boty produkują akcje, ale uruchomienie pełnej gry (D2 `balance_simulate`) wymaga orkiestratora `apply`+`round_end_phase`+alternacja inicjatywy — to LocalClient (B5) / B4 routers. Poza tym wątkiem (H2).
- **Manewr „stój"** jako kandydat = no-op aktywacja; nieszkodliwy (Greedy ocenia 0), ale daje botowi jawną opcję pasu.
- **Greedy depth-1** — brak lookahead; nie przewiduje kontrataku/odpowiedzi przeciwnika. D4 doda `minimax_player`.

**Co odkładamy:**
- Pętla bitwy / driver przebiegu gry (B4/B5).
- Modyfikatory ruchu Szybki/Wolny w enumeratorze (`move_inches` bazowy).
- Pełniejsza dyskretyzacja Manewru + walidacja pkt 14.c.iv w heurystyce.
- `minimax_player` (D4), telemetria decyzji (ADR-0017).

## Alternatywy rozważone

- **Enumerator jako helper silnika (`resolver.legal_actions`).** Odrzucone — silnik celowo jednoakcyjny; generowanie kandydatów to polityka, nie reguły. Trzymanie w agentach nie zanieczyszcza publicznego API silnika.
- **Pełna pętla bitwy w tym wątku.** Odrzucone — to LocalClient (B5)/B4; wykraczałoby poza 1 okno i wymagałoby decyzji o orkiestracji przerwań (H2). Boty są użyteczne i testowalne bez niej.
- **Greedy z pełną symulacją `apply` per kandydat (lookahead).** Odrzucone dla MVP — `apply` wymaga `DeterministicDice` (RNG) i jest droższe; depth-1 z `expected_damage` (analityka bez RNG, ADR-0044) wystarcza.

## Inwarianty

1. `RandomPlayer(seed).choose_action(state, p)` deterministyczne per seed.
2. `GreedyPlayer().choose_action` deterministyczne (stabilny tie-break).
3. `choose_action` zwraca akcję z `legal_actions(state, p)` albo `None` (brak akcji).
4. `evaluate_state(s, 0) == -evaluate_state(s, 1)` w części bilansu HP (symetria zero-sum bez celów).
