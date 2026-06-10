# HANDOFF — faza-d-realistic-fixtures

> **Wątek:** Fixtury balansu wierne regułom — 5 celów (pkt 5.a/5.b/5.c) + 4 proste oddziały/stronę (pkt 2.a) na 72″×48″ (pkt 3.b).
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — przepisanie `tests/fixtures/battles/*.yaml` na 5 celów + 4 oddziały. Zakres: fixtury + `test_balance_simulate.py` (asercje liczby celów). Zero zmian w kodzie silnika/agentów/skryptu.

## Cel

Dotychczasowe fixtury (`demo_skirmish`, `objective_clash`) miały 1 cel i 2 oddziały/stronę — niewierne regułom (pkt 5.a: 5 celów; pkt 2.a: 4–8 oddziałów). Wnioski balansowe z 1 celu nie generalizują. Przepisać na rules-faithful: **5 celów** rozmieszczonych wg pkt 5.b (≥1 w każdej strefie rozstawienia + lewo/prawo) i pkt 5.c (≥12″ od siebie, ≥6″ od krawędzi), **4 proste oddziały/stronę** (5 modeli, T3 Q4 D5, bez bohatera/zdolności) na planszy 72″×48″ (pkt 3.b), strefy 24″ od siebie (pkt 3.a).

## Zablokowane pliki / katalogi
- `tests/fixtures/battles/demo_skirmish.yaml` — przepis na 5 celów / 4 oddziały, rozstawienie standardowe (cele środkowe kontestowane).
- `tests/fixtures/battles/objective_clash.yaml` — jw., ale rozstawienie wysunięte (oddziały startują przy celach → osiągalne w 1 ruchu, demonstracja depth-1).
- `tests/test_balance_simulate.py` — asercje `len(fx.objectives)`/`len(fx.terrain)`.

## Blokuje / Blokowane przez
- **Blokuje:** nic. **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A` / **Base:** `main`

## Plan implementacji

### Faza 1 — Layout 5 celów (quincunx) wg pkt 5.b/5.c
- [x] 1.1: Plansza 72×48; strefy P0 x∈[0,24], P1 x∈[48,72] (24″ apart, pkt 3.a). Cele ≥6″ od krawędzi → x∈[6,66], y∈[6,42].
- [x] 1.2: 5 celów: (12,12) P0+lewo, (12,36) P0+prawo, (36,24) środek, (60,12) P1+lewo, (60,36) P1+prawo. Pokrycie pkt 5.b ✓ + wszystkie pary ≥12″ (pkt 5.c) — weryfikowane testem `test_fixture_objectives_satisfy_placement_rules`.

### Faza 2 — 4 proste oddziały/stronę + rozstawienie
- [x] 2.1: P0 4 oddziały w strefie (2 rifle range24 + 2 sword melee), 5 modeli T3 Q4 D5, bez passives. P1 lustrzanie (symetria potwierdzona greedy-vs-greedy = 100% remisów).
- [x] 2.2: `demo_skirmish` — rozstawienie standardowe (front x18 / x54, 36″ apart; cele środkowe ~18″ = kilka ruchów).
- [x] 2.3: `objective_clash` — rozstawienie wysunięte (oddziały przy celach domowych w strefie, osiągalne w 1 ruchu; cel środkowy poza strefą = 1-ruch niedostępny, realne ograniczenie reguł).

### Faza 3 — Testy + weryfikacja
- [x] 3.1: `test_fixture_shape_and_objects` → 5 celów + 4 oddziały/stronę; nowy `test_fixture_objectives_satisfy_placement_rules` (pkt 5.c).
- [x] 3.2: `python -m pytest -q` — **1526 passed**.
- [x] 3.3: `balance_simulate` smoke — patrz Notatki (zdrowe liczby, ujawniona słabość depth-1 „nie trzyma celów").

### Faza 4 — Definition of Done
- [x] `pytest -q` (1526) + `both_assert` 156/156 (niezmienione — fixtury nie ruszają kosztów).
- [!] `/simplify` — N/A (tylko dane fixtur + asercje testów, brak nowej logiki).
- [!] `/review`, `/security-review` — N/A.
- [x] roadmap update + `/handoff-archive`.

## Pliki dotknięte
- `tests/fixtures/battles/demo_skirmish.yaml` (przepis: 5 celów + 4 oddziały, rozstawienie standardowe).
- `tests/fixtures/battles/objective_clash.yaml` (przepis: jw., rozstawienie wysunięte).
- `tests/test_balance_simulate.py` (asercje 5 celów / 4 oddziały + placement-rules pkt 5.c).
- `docs/roadmap.md` (D2 — fixtury wierne regułom).

## Decyzje
- 2026-06-10: 4 oddziały/stronę = minimum legalnej armii (pkt 2.a 4–8); bez bohaterów/zdolności („proste"). Layout celów quincunx — minimalny spełniający pkt 5.b/5.c.

## Hipotezy / pytania otwarte
- **H1 (`READY`):** „lewo/prawo planszy" (pkt 5.b) interpretowane jako oś y (y<24 lewo, y>24 prawo); strefy rozstawienia na osi x (końce). Spójne z pkt 3.a (strefy 24″ apart wzdłuż x).

## Jak zweryfikować
```powershell
python -m pytest tests/test_balance_simulate.py -q
python scripts/balance_simulate.py --fixture tests/fixtures/battles/demo_skirmish.yaml -n 50 --players greedy,random
```

## Notatki / odkrycia w trakcie
- 2026-06-10: pkt 7.d „gracz z inicjatywą umieszcza 5 celów"; pkt 5.b ≥1/strefa + lewo/prawo; pkt 5.c ≥12″/≥6″. Strefy 24″ apart (pkt 3.a), 6′×4′ (pkt 3.b). Odczytane ze źródła tej sesji.
- 2026-06-10: **Smoke balansu (5 celów / 4 oddziały):**
  - `demo_skirmish` (fronty 36″, brak ognia early): random/random 3-3-34 (zbalansowane); **greedy/random 15-5-20** — greedy maszeruje na cele zanim wróg podejdzie i je trzyma → wygrywa.
  - `objective_clash` (fronty 28″, ogień od rundy 1): **greedy/random 4-12-24** — greedy PRZEGRYWA. greedy/greedy 0-0-20 (symetria OK).
- 2026-06-10: **ODKRYCIE (słabość heurystyki, nie fixtury): GreedyPlayer nie TRZYMA celów.** Gdy oddział kontroluje cel, „stój" ma deltę 0 (cel już w bazie), a dostępny atak daje +obrażenia → bot porzuca cel by atakować i traci kontrolę (pkt 5.d). Widać to gdy wróg jest w zasięgu od startu (`objective_clash`). To facet miopii depth-1 (obok „nie maszeruje do dalekich celów"). **Follow-up (D-stream):** bonus za utrzymanie kontroli / depth-2 (D4 minimax). Kandydat na nowy wątek — NIE w zakresie tego (fixtury).
