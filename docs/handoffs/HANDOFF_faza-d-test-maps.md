# HANDOFF — faza-d-test-maps

> **Wątek:** Nowe mapy testowe (Standard_A deterministyczna + Lustrzana_A/Symetryczna_A generatory losowe) zamiast starych fixtur. Teren + cele + strefy + armia, symetria → fair balance.
> **Status:** In progress
> **Utworzony:** 2026-06-12

## W TRAKCIE: 2026-06-12 — generatory map w `scripts/balance_simulate.py` (`--map <name> [--map-seed N]`) + testy. Skrypt-liść; zero zmian w silniku/agentach.

## Spec usera (2026-06-12)
- **Standard_A:** 72×48, strefy wzdłuż dłuższych krawędzi (y∈[0,12]/[36,48]). **Środkowo-symetryczna** (odbij od (36,24)). Dane (połowa): koła r=3 Obronny (6,18),(24,9),(30,36),(36,24); Trudny (12,30),(36,24); Niebezpieczny (30,36). Linie Niedostępny+Blokujący ×9. Cele (12,30),(24,9),(36,24). → reflekcja daje 5 celów.
- **Lustrzana_A:** 72×48, strefy wzdłuż dłuższych krawędzi. Wszystko **odbite od linii środkowej** (y=24). Cele losowo wg pkt 5.c (środkowy losowo na linii środka). 18 linii Niedostępny+Blokujący dł. 2–5, ≥6″ od siebie, ≥3″ od celów. Koła ⌀3–6 (mogą nachodzić): 8 Obronny, 4 Trudny, 2 Niebezpieczny.
- **Symetryczna_A:** jak Lustrzana, ale **środkowo-symetryczna** (1 cel zawsze na środku) + strefy = 2 równoległe linie 12″ od środka pod **losowym kątem**.

## Ograniczenie silnika (flaga)
Ruch NIE używa Trudny (½ ruchu, pkt 4.c.iv) ani Niedostępny (pkt 4.c.i) — brak pathfindingu/kolizji. Mapy działają dla **LoS (Blokujący)** i **osłony (Obronny)** i **Niebezpieczny** (R5.g); Trudny/Niedostępny to dane forward-compat (nieegzekwowane w ruchu MVP).

## Plan
- [x] 1: Helpery symetrii `_pt_reflect`/`_mirror` + `_terrain_from` (koła per-radius + cechy) + `_armies`/`_armies_angled` (4 profile/stronę, symetryczne).
- [x] 2: `build_standard_a()` — reflekcja punktowa danych (9 kół z merge cech same-pos, 18 linii, 5 celów).
- [x] 3: `build_lustrzana_a(seed)` — `_gen_objectives` (pkt 5.b/5.c, rejection), `_gen_half_lines` (9, dł.2–5, midpoint ≥6″/≥3″ od celów), `_gen_half_circles` (4+2+1, ⌀3–6, overlap-OK), mirror y=24 → 8/4/2 + 18 linii.
- [x] 4: `build_symetryczna_a(seed)` — point-sym (1 cel na środku) + `_armies_angled` (strefy 12″ od środka pod losowym kątem; P1=reflekcja P0 zostaje na planszy).
- [x] 5: `--map <name>` + `--map-seed`; rejestr `MAP_BUILDERS` + `build_map`.
- [x] 6: Testy (`test_balance_simulate.py` +7: build valid, cele pkt 5.b/5.c, cechy 8/4/2, symetria point/mirror, determinizm/seed, unknown). pytest **1614**. Smoke balans OK (priority/random 70–93%).

## Wynik / status
3 mapy działają end-to-end. **Stare fixtury (demo_skirmish/objective_clash/unit_profiles) ZOSTAJĄ** — `test_balance_simulate` + `DEFAULT_FIXTURE` zależą; `--map` to nowa ścieżka. Usunięcie starych = osobny krok (repoint testów + default).
**Ograniczenie (flaga):** ruch nie używa Trudny/Niedostępny (brak pathfindingu) — działają LoS(Blokujący)/osłona(Obronny)/Niebezpieczny; Trudny/Niedostępny forward-compat.

## Decyzje
- 2026-06-12: Armia = 4 profile (Strzelec-24/18, Wojownik-mix/Wojownik), symetryczne rozstawienie w strefach — mapy od razu używalne do porównań botów na terenie.

## Notatki
- 2026-06-12: Regroup pkt 20.f.i (Przyszpilony deterministyczny) + infra wyboru — pogodzone poza tą turą (commit a85c0b2). Drift Nieustraszony 20.e nadal w backlogu parent.
