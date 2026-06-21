# HANDOFF — faza-telemetry-analyze

> **Wątek:** Cross-cutting telemetria (ADR-0017) — slice `scripts/analyze_battle.py`: analityczny raport pojedynczej bitwy z event-logu (statystyki obrażeń/strat per oddział i strona, timeline kontroli celów pkt 5.d/5.f, rozkład akcji, szczęście kości Przegrupowania).
> **Status:** In progress
> **Utworzony:** 2026-06-21
> **Ostatnia aktualizacja:** 2026-06-21

## Cel

Strumień cross-cutting "telemetria od dnia 1" (ADR-0017) jest jedynym strumieniem planu **całkowicie nieruszonym**. Roadmap wymienia deliverable `scripts/analyze_battle.py <id>` — "raport markdown z wykresami". Realizujemy **slice z event-logu** (analogicznie jak B6 zrobił "CLI replay slice"): czysty skrypt-liść, który z event-logu bitwy (źródło: fixtura/mapa via `simulate_from_rosters` LUB `--from-db` via `persistence.load_events`) liczy analitykę:
- obrażenia zadane/otrzymane + straty (modele/ELIMINOWANY) per oddział i per strona,
- timeline kontroli celów per runda (pkt 5.d/5.f) + zwycięzca,
- rozkład akcji (ruchy/Ostrzał/Szarża), rozkład typów eventów,
- szczęście kości Przegrupowania (rolls/failures, pkt 20).

Wartość: bezpośrednio wspiera bieżący fokus D-strumienia (diagnostyka "DLACZEGO bot wygrywa/przegrywa" — otwarte pytanie D4 "sufit to jakość polityki"). Komplementarne do `battle_replay.py` (narracja per-event) — to **agregacja/analityka**, nie narracja.

**Świadomy scope (slice):** emisja `structlog` w `resolver`/`persistence` + pliki `data/{battle,agent}_metrics/*.jsonl` (pełny ADR-0017) ODŁOŻONE — wymagają zmian w rdzeniu silnika (hot path). Ten slice czyta sam event-log (zero zmian w rdzeniu).

## Zablokowane pliki / katalogi
- `scripts/analyze_battle.py` (NEW) — rdzeń analityki + źródła event-logu + CLI
- `tests/test_analyze_battle.py` (NEW) — pokrycie czystych funkcji analitycznych
- `scripts/README.md` — wpis o nowym skrypcie
- `docs/roadmap.md` — notatka przy ADR-0017 (slice analyze z event-logu DONE)

## Blokuje / Blokowane przez
- **Blokuje:** nic (skrypt-liść).
- **Blokowane przez:** nic — event-log + `persistence.load_events` + `simulate_from_rosters` już istnieją.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Rdzeń analityki (czyste funkcje, bez I/O)
- [x] Krok 1.1: `analyze_battle_log(events, *, owner_map, winner) -> BattleAnalysis` — agreguje event-log (`UnitStats` per oddział + `SideStats` per strona, objective timeline, action/event distribution, morale dice).
- [x] Krok 1.2: `render_analysis(analysis, *, header)` — markdown report (tabele + tekstowe słupki `_bar`, dependency-free).

### Faza 2 — Źródła event-logu + CLI
- [x] Krok 2.1: `analyze_from_fixture(...)` (reuse `balance_simulate` SSOT + `simulate_from_rosters`, owner_map z `final_state`) + `analyze_from_db(battle_id)` (reuse `persistence.load_events`, read-only — wzorzec `battle_replay.replay_from_db`).
- [x] Krok 2.2: CLI argparse (`--fixture`/`--map`/`--from-db`/`--players`/`--seed`/`--initiative`/`--out`), UTF-8 stdout.

### Faza 3 — Testy + dokumentacja
- [x] Krok 3.1: `tests/test_analyze_battle.py` — 14 testów: analityka na syntetycznym event-logu (deterministyczne asercje), degradacja bez owner_map, render, integracja sim end-to-end + determinizm + CLI smoke.
- [x] Krok 3.2: `scripts/README.md` (wpis) + `docs/roadmap.md` (ADR-0017 slice + checkbox `analyze_battle.py` ✅).

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [ ] `pytest -q` (pełna + `tests/test_analyze_battle.py`)
- [!] Smoke test JS — nie dotyczy (brak zmian w `app.js`)
- [ ] Call-site check dla zmienionych funkcji (skrypt-liść — brak importów z `app/` poza publicznym API)
- [ ] `/simplify` — przegląd jakości, reuse, dead code (zawsze)
- [!] `/review` — warunkowo; skrypt-liść read-only, oceniam po rozmiarze diffu
- [!] `/security-review` — nie dotyczy (read-only DB, brak auth/user-input→DB/write)
- [ ] Re-run `pytest -q` jeśli `/simplify` coś zmieniło
- [ ] Diff review przed commitem

## Pliki dotknięte
- *(wypełni się w trakcie)*

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-21: pełny ADR-0017 (structlog + jsonl metrics) ODŁOŻONY — ten wątek robi tylko slice analityki z event-logu; emisja metryk w rdzeniu = osobny wątek (hot path, wymaga ADR-0017 promocji do Accepted).

## Hipotezy / pytania otwarte
- `READY` — slice w pełni specyfikowany, zero blokad usera.

## Jak zweryfikować
```bash
python -m pytest tests/test_analyze_battle.py -q
python scripts/analyze_battle.py                                  # demo fixtura
python scripts/analyze_battle.py --map symetryczna_a --map-seed 3 --players priority3,priority
python scripts/analyze_battle.py --from-db 1                      # z DB (read-only)
```

## Decyzje
- 2026-06-21: Slug `faza-telemetry-analyze`. Wątek wybrany w sesji autonomicznej: jedyny strumień planu całkowicie nieruszony (telemetria ADR-0017), leaf-layer, bez decyzji usera, closeable w jednym oknie, wspiera bieżący fokus diagnostyki botów.

## Notatki / odkrycia w trakcie
- 2026-06-21: Event-log zawiera komplet danych do analityki (potwierdzone `app/services/engine/events.py`): `ShotResolved`/`MeleeResolved` (attacker/defender/weapon/hits/wounds_dealt/precise/eliminating), `ModelKilled` (unit_id/is_hero/eliminated/by_attacker_id), `MoraleTestPassed` (rolls/failures/result_status), `RoundEnded` (round_number/objectives_held), `ObjectiveControlChanged`, `MoveExecuted` (move_type). Raw dice trafień NIE są w event-logu (tylko `hits`/`wounds`) — "szczęście" liczymy z `MoraleTestPassed.rolls` (jedyne raw rolls w logu).
- 2026-06-21: Reguły cytowane ze źródła `app/static/docs/SZOP_Rozjemca.md` (odczytane w tej sesji): pkt 5.d (cel zajęty gdy w 3″ tylko oddziały jednego gracza; trwa między rundami), pkt 5.f (gra kończy się po 4 rundach; wygrywa zajmujący więcej celów), pkt 8.c.ii (kontrola sprawdzana w fazie końca rundy).
