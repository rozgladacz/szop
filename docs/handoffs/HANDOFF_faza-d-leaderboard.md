# HANDOFF — faza-d-leaderboard

> **Wątek:** Strumień D4 — `scripts/leaderboard.py`: round-robin wszystkich botów (random→claude_v3) ponad fixturami → kanoniczny ranking ogólny (win-rate per bot) do `reports/leaderboard.md`. Domyka deliverable D4 „Leaderboard".
> **Status:** In progress
> **Utworzony:** 2026-06-19
> **Ostatnia aktualizacja:** 2026-06-19

## W TRAKCIE

- **2026-06-19 (sesja autonomiczna) — START: `scripts/leaderboard.py` + testy + ADR-0030.** Skrypt-liść reużywający `balance_simulate.simulate_balance` (SSOT, ADR-0032) + wzorzec module-loader/`_bar` z `balance_report.py`. Agregacja **ponad parami** (różni się od `balance_report` = macierz pairwise): dla każdej nieuporządkowanej pary różnych botów × fixtura sumuje wins/losses/draws z perspektywy obu botów → ogólny standing per bot, ranking po win-rate. Mirror self-play (A vs A) wykluczony (deterministyczne remisy, nieinformatywne — udokumentowane w D-stream). ADR-0030 scoping: ranking botów TERAZ; osobne konta agentów (`agent_kind`) + leaderboard międzykontowy odłożone do B2 auth.

## Cel

Domknąć deliverable D4 „Leaderboard `reports/leaderboard.md`" (roadmap, `docs/roadmap.md#d4-adversarial-play`). Skrypt-liść agreguje wynik round-robin wszystkich typów botów w jeden ranking ogólny (per bot: gry / wygrane / porażki / remisy / win-rate), pokazując kanonicznie udokumentowany wniosek D-stream („priority/priority3 = najlepszy stosunek siła/koszt"). Reuse SSOT (`simulate_balance`/`make_player`/`build_map`/`load_battle_fixture`) — zero zmian w rdzeniu silnika/agentów.

## Zablokowane pliki / katalogi

- `scripts/leaderboard.py` (NEW)
- `tests/test_leaderboard.py` (NEW)
- `docs/adr/0030-multi-agent-leaderboard.md` (NEW)
- `scripts/README.md` (MOD — wpis)
- `docs/roadmap.md` (MOD — D4 Leaderboard ✓ + ADR index 0030)

## Blokuje / Blokowane przez

- **Blokowane przez:** nic — boty kompletne (random→claude_v3, PLAYER_KINDS), `simulate_balance`/`balance_report` gotowe.
- **Blokuje:** nic (skrypt-liść, narzędzie balansu). Osobne konta agentów (ADR-0030 część 2) blokowane przez B2 auth — poza tym oknem.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Slice 1 — leaderboard generator (ten wątek)

- [x] `leaderboard.py`: `BotStanding` (kind, games, wins, losses, draws + win/loss/draw-rate); `compute_standings(results, player_kinds)` agreguje `BalanceResult` ponad parami (distinct, bez mirror) → posortowana lista; `run_leaderboard(config)` (fixtura × `combinations` distinct par); `format_leaderboard(standings, config, results)` (markdown tabela + tekstowe `█`/`░` słupki win-rate); CLI `--fixtures/-n/--seed/--players/--out`, default `reports/leaderboard.md`.
- [x] `tests/test_leaderboard.py` — 20 testów: standings agregacja (suma gier, symetria wins↔losses między botami, draws dla obu, mirror+obcy wykluczeni, zero-games safe), ranking malejący + tiebreak, format markdown (tabela + cytat pkt 5.f + wykresy + newline), default path, write, determinizm, CLI smoke + 3× walidacja CLI.
- [x] ADR-0030 (Accepted, scoping: ranking botów teraz / osobne konta + B2 auth później).
- [x] docs (roadmap D4 Leaderboard ✓ + ADR index 0030, scripts/README wpis).

**Real-run (5 botów × 3 fixtury, n=8):** priority3 66.7% > claude_v3 62.5% > priority 46.9% > random 26% > greedy 12.5% — potwierdza wniosek D4 (priority/priority3 najsilniejsze; żaden bot Claude ich nie bije).

## Pliki dotknięte

- `scripts/leaderboard.py` (NEW), `tests/test_leaderboard.py` (NEW), `docs/adr/0030-multi-agent-leaderboard.md` (NEW), `scripts/README.md`, `docs/roadmap.md`

## Decyzje

- 2026-06-19: Agregacja ponad parami (ogólny standing), nie macierz pairwise (`balance_report` już to robi). Mirror self-play wykluczony — deterministyczny remis (greedy/greedy 100% remisów udokumentowane), nieinformatywny dla rankingu.
- 2026-06-19: Ranking po **win-rate** (wins/games), tiebreak: więcej wygranych → mniej porażek → nazwa. `reports/` gitignored (artefakt generowany — spójnie z `balance_report`).

## Jak zweryfikować

```powershell
python -m pytest tests/test_leaderboard.py -q
python scripts/leaderboard.py -n 6 --players random,greedy,priority   # realny run
```

## Faza Weryfikacja — Definition of Done

- [x] `pytest -q` zielony — **1782 passed** (1762 baseline + 20)
- [x] `/simplify` — 4 kąty inline; 0 zmian (duplikacja module-loadera/`_bar`/parserów CLI = konwencja skryptów-liści, każdy samodzielnie ładuje `balance_simulate` SSOT; reszta czysta)
- [!] `/review` — pominięty warunkowo: skrypt-liść, brak hot-path/SSOT-mutacji/auth/DB; 20 testów (symetria agregacji + ranking + wykluczenie mirror + walidacja CLI); inline self-review
- [!] `/security-review` — nie dotyczy: brak auth/route, read-only, zero DB-write
- [x] real-run smoke — `python scripts/leaderboard.py -n 8 --players random,greedy,priority,priority3,claude_v3` → exit 0, ranking poprawny, `reports/leaderboard.md` gitignored
