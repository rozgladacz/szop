# HANDOFF — faza-d-report-maps

> **Wątek:** D2/D4 — dodać `--map`/`--map-seed` (mapy generowane, reuse `balance_simulate.build_map`/`MAP_BUILDERS`) do warstwy raportowej: `balance_report.py` + `leaderboard.py`. Dziś raporty wspierają tylko fixtury YAML; `battle_replay`/`balance_simulate` mają już `--map`.
> **Status:** In progress
> **Utworzony:** 2026-06-19
> **Ostatnia aktualizacja:** 2026-06-19

## W TRAKCIE

- **2026-06-19 (sesja autonomiczna) — START.** Spójna luka: `build_map(name, seed)` zwraca `BattleFixture` (identyczny interfejs co `load_battle_fixture`), więc round-robin warstwy raportowej iteruje po `BattleFixture` — mapy generowane wpinają się addytywnie. Mapy symetryczne (lustrzana_a/symetryczna_a) usuwają bias konkretnej fixtury z rankingu leaderboardu (mniej zależny od ręcznie wykonanych 3 fixtur). Skrypty-liście, zero zmian w rdzeniu silnika/agentów. Reuse `bsim.build_map`/`MAP_BUILDERS`.

## Cel

Wpiąć mapy generowane (`standard_a`/`lustrzana_a`/`symetryczna_a`, rejestr `MAP_BUILDERS` z `balance_simulate.py`) jako alternatywne/dodatkowe źródło bitew w `balance_report.py` (D2) i `leaderboard.py` (D4). CLI `--map name[,name] [--map-seed N]` analogicznie do `balance_simulate`/`battle_replay`. Source resolution: fixtury YAML (`--fixtures`) + mapy (`--map`) → wspólna lista `BattleFixture` dla round-robin. Backward-compat: bez `--map` zachowanie 1:1 (default fixtury). Reuse SSOT (`build_map`) — zero re-implementacji generatorów map.

## Zablokowane pliki / katalogi

- `scripts/balance_report.py` (MOD)
- `scripts/leaderboard.py` (MOD)
- `tests/test_balance_report.py` (MOD)
- `tests/test_leaderboard.py` (MOD)
- `scripts/README.md` (MOD — wzmianka `--map`)

## Blokuje / Blokowane przez

- **Blokowane przez:** nic — `build_map`/`MAP_BUILDERS` gotowe (`balance_simulate`).
- **Blokuje:** nic (skrypty-liście, narzędzia balansu).

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Slice 1 — `--map` w warstwie raportowej (ten wątek)

- [x] `balance_report.py`: `ReportConfig` +`maps: tuple[str,...] = ()` +`map_seed: int = 0`; helper `resolve_fixtures(config)` (fixtury YAML + mapy → `list[BattleFixture]`); `run_round_robin` iteruje po wyniku helpera; metadane raportu listują mapy+seed; CLI `--map`/`--map-seed` (parser nazw map walidowany vs `MAP_BUILDERS`).
- [x] `leaderboard.py`: analogicznie `LeaderboardConfig` +`maps`+`map_seed`; `resolve_fixtures`; `run_leaderboard`; CLI `--map`/`--map-seed`.
- [x] testy obu skryptów (+16): resolve fixtury-only/fixtury+mapy/mapy-only, run z mapą, walidacja nieznanej mapy (parser + CLI), backward-compat (bez `--map` = same fixtury), determinizm per map-seed, metadane listują mapy.
- [x] docs (scripts/README — wzmianka `--map` w `balance_report`/`leaderboard`).

**Real-run (leaderboard, lustrzana_a+symetryczna_a seed 3, n=6, 4 boty):** priority3 77.8% > priority 61.1% > random 22.2% > greedy 11.1% — spójne z fixturami; mapy symetryczne dają czystszy sygnał (priority3 mocniej).

## Pliki dotknięte

- `scripts/balance_report.py`, `scripts/leaderboard.py`, `tests/test_balance_report.py`, `tests/test_leaderboard.py`, `scripts/README.md`

## Decyzje

- 2026-06-19: `--map` jest **dodatkowe** do `--fixtures` (nie wzajemnie wykluczające jak w `balance_simulate`) — round-robin może mieszać fixtury i mapy w jednym raporcie. Bez `--map` zachowanie 1:1 (default fixtury). Brak fixtur i map jednocześnie → błąd CLI.
- 2026-06-19: Reuse `bsim.build_map` (SSOT generatorów map) — zero re-implementacji.

## Jak zweryfikować

```powershell
python -m pytest tests/test_balance_report.py tests/test_leaderboard.py -q
python scripts/leaderboard.py --map lustrzana_a,symetryczna_a --map-seed 3 -n 6 --players random,greedy,priority
```

## Faza Weryfikacja — Definition of Done

- [x] `pytest -q` zielony — **1805 passed** (zawiera +16 moich; +reszta to równoległy wątek `faza-b-5-db-client`)
- [x] `/simplify` — 4 kąty inline; 0 zmian (duplikacja `resolve_fixtures`/`_parse_map_list`/resolucji między skryptami = konwencja liści; w obrębie skryptu czysto)
- [!] `/review` — pominięty warunkowo: skrypty-liście, addytywny feature, brak hot-path/SSOT-mutacji/auth/DB; pełne pokrycie (determinizm + backward-compat + walidacja CLI)
- [!] `/security-review` — nie dotyczy: brak auth/route, read-only
- [x] real-run smoke — `leaderboard.py --map lustrzana_a,symetryczna_a --map-seed 3` → exit 0, ranking + metadane map poprawne
