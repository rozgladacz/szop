# HANDOFF — faza-d-2-balance-sim

> **Wątek:** Strumień D2 — `scripts/balance_simulate.py`: agregator N headless gier (`simulate_from_rosters`) → win-rate per rozpiska, CSV + podsumowanie.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — implementacja `scripts/balance_simulate.py` + fixtura roster-pair + testy. Zakres: NOWY skrypt-liść `scripts/`, NOWA fixtura `tests/fixtures/battles/`, NOWY `tests/test_balance_simulate.py`. **Zero zmian w `app/services/engine/*` i `app/services/agents/*`** — brak kolizji z lockami wątków `faza-b-engine-mvp` / `faza-b-order-interrupts`.

## Cel

Roadmap D2 (`docs/roadmap.md#d2-balance-simulation`): skrypt agregujący wiele headless gier do metryki balansu. Prereq (`app/services/agents/match.py` — `run_match` / `simulate_from_rosters`) zamknięty 2026-06-10 (wątek `faza-d-match-runner`, ADR-0032) i oznaczony `READY`.

MVP: dla pary rosterów (z fixtury YAML) rozegraj N gier z różnymi seedami i **naprzemienną inicjatywą** (usuwa bias pierwszego gracza), zagreguj wyniki (winner per pkt 5.f — więcej zajętych celów na koniec gry) → win-rate / draw-rate per roster + średnia liczba rund. Output: CSV + czytelne podsumowanie na stdout. Gracze konfigurowalni (random/greedy, D1).

Poza zakresem MVP (follow-up): breakdown win-rate per zdolność/broń (wymaga adaptera ORM `Roster`/`Unit` → engine-dict + heurystyki auto-rozstawienia pozycji — osobna decyzja); `scripts/balance_report.py` z wykresami (D2 drugi punkt).

## Zablokowane pliki / katalogi
- `scripts/balance_simulate.py` (NEW) — skrypt CLI
- `tests/fixtures/battles/` (NEW dir) — fixtury roster-pair (format engine-dict + meta)
- `tests/test_balance_simulate.py` (NEW) — testy agregacji/CLI/determinizm
- `docs/roadmap.md` — odznaczenie D2 punktu `balance_simulate.py`

## Blokuje / Blokowane przez
- **Blokuje:** D3 `exploit_hunt` (współdzieli wzorzec agregacji), D2 `balance_report.py`.
- **Blokowane przez:** nic — prereq `match.py` DONE.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Fixtura + loader
- [x] 1.1: Format fixtury roster-pair YAML: `{name, terrain?, objectives?, rosters: [<engine-dict>, <engine-dict>]}` gdzie `<engine-dict>` = `{owner_player, units:[{id,position,models,toughness,quality,defense,passives,weapons}]}` (1:1 z `build_initial_state`).
- [x] 1.2: `tests/fixtures/battles/demo_skirmish.yaml` — symetryczna para 2v2 z celem w centrum (parzysta baza do sanity).
- [x] 1.3: `load_battle_fixture(path) -> BattleFixture(name, rosters, terrain, objectives)` — parsuje YAML, buduje `Objective`/`TerrainCircle`/`TerrainLine` z dict-ów. Walidacja: dokładnie 2 rostery.

### Faza 2 — Agregator + CLI
- [x] 2.1: `simulate_balance(fixture, *, n, player_kinds, base_seed) -> BalanceResult` — pętla N gier; seed `base_seed+i`; inicjatywa `i % 2` (naprzemienna, `initiative_for_game`); zlicza winner 0/1/None per `owner_player` + sumuje rundy. Gracze budowani świeżo per grę z seedem pochodnym.
- [x] 2.2: `BalanceResult` (frozen): n_games, wins_p0/p1, draws, total_rounds + properties win_rate_p0/p1/draw, avg_rounds + `csv_header()`/`csv_row()`.
- [x] 2.3: CLI argparse: `--fixture PATH` (default demo), `-n/--games`, `--seed`, `--players p0,p1` (`random`/`greedy`, walidacja), `--out CSV` (opcjonalny). UTF-8 stdout reconfigure + `_repo_root` sys.path insert (jak `profile_quote.py`).
- [x] 2.4: `format_summary` (tabela + win rates) + `write_csv`/`result_to_csv_string`.

### Faza 3 — Testy (`tests/test_balance_simulate.py`, 15 testów)
- [x] 3.1: `test_simulate_balance_deterministic` — ten sam base_seed → identyczny `BalanceResult`.
- [x] 3.2: `test_win_rates_sum_to_one`.
- [x] 3.3: `test_alternating_initiative` — n parzyste → inicjatywa 50/50.
- [x] 3.4: `test_fixture_shape_and_objects` + `test_fixture_rejects_non_pair`.
- [x] 3.5: `test_csv_header_row_shape` + `test_cli_smoke_default_fixture` + `test_cli_writes_csv` + `test_cli_rejects_bad_player` (in-process `main([...])`). Plus make_player/avg_rounds/reject-zero/write_csv/format_summary.

### Faza 4 — Weryfikacja end-to-end (Definition of Done)
- [x] `python -m pytest -q` — **1519 passed** (1504 baseline + 15).
- [x] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — **156/156**.
- [x] `python scripts/balance_simulate.py` — smoke OK (random,random 12 gier; greedy,random 8 gier + CSV).
- [x] Call-site check — N/A (nowy skrypt, brak konsumentów w runtime).
- [~] `/simplify` (zawsze).
- [!] `/review` — N/A: izolowany skrypt-liść, brak hot-path/SSOT/auth, 15 testów, czyste funkcje.
- [!] `/security-review` — N/A (brak auth / user input → DB; tylko odczyt lokalnej fixtury YAML).
- [ ] Re-run pytest jeśli /simplify coś zmienił.
- [ ] `docs/roadmap.md` D2 update + `/handoff-archive`.

## Pliki dotknięte
*(wypełni się w trakcie)*

## Decyzje zamrożone (NIE podnosić ponownie)
*(brak)*

## Hipotezy / pytania otwarte
- **H1 (`READY`):** Źródło rosterów = fixtura YAML (engine-dict), nie ORM DB. Powód: `build_initial_state` wymaga `position` per oddział (battlefield), której roster ORM nie ma → adapter ORM→engine wymaga heurystyki auto-rozstawienia = osobna decyzja. Fixtura też aligns z B7 test-bed (`tests/fixtures/battles/`). Breakdown per zdolność/broń → follow-up po adapterze.
- **H2 (`READY`):** Naprzemienna inicjatywa per grę usuwa bias pierwszego gracza w metryce balansu — metodologia statystyczna, nie reguła gry.

## Jak zweryfikować
```powershell
python -m pytest tests/test_balance_simulate.py -v
python scripts/balance_simulate.py            # demo fixtura, stdout
python scripts/balance_simulate.py -n 50 --players greedy,random --out build/balance.csv
python -m pytest -q
```

## Decyzje
- 2026-06-10: Wątek utworzony. D2 wybrane jako READY leaf-task (prereq match.py done), izolowane, bez decyzji usera, closeable w jednym oknie.

## Notatki / odkrycia w trakcie
- 2026-06-10: `simulate_from_rosters(rosters, players, *, seed, terrain, objectives, initiative_player, ...)` → `MatchResult(final_state, events, winner, rounds_played)`. `winner ∈ {0,1,None}` per `_winner` (pkt 5.f, source potwierdzone tej sesji: „Gra kończy się po 4 rundach. Wygrywa gracz, który na koniec gry zajmuje więcej celów."). Roster engine-dict: `{owner_player, units:[{id,position:(x,y),models,toughness,quality,defense,passives,weapons}]}`.
- 2026-06-10: `tests/fixtures/rosters/*.yaml` to fixtury KOSZTOWE (schemat `template_unit`) — NIEkompatybilne z engine-dict. Nowy format pod `tests/fixtures/battles/`.
