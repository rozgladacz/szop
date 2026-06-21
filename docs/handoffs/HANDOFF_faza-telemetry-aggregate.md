# HANDOFF — faza-telemetry-aggregate

> **Wątek:** Telemetria (ADR-0017) — tryb agregacji `analyze_battle --games N`: średnie statystyki per strona (obrażenia/straty/akcje) + rozkład wyników + zagregowane kości na próbie N gier (diagnostyka "DLACZEGO bot wygrywa", luka nieobjęta przez leaderboard/balance_report).
> **Status:** In progress
> **Utworzony:** 2026-06-21
> **Ostatnia aktualizacja:** 2026-06-21

## Cel

`leaderboard.py`/`balance_report.py` pokazują tylko win-rate (KTO wygrywa). Per-battle `analyze_battle.py` pokazuje jedną grę. Brakuje warstwy **agregatu diagnostycznego**: na próbie N gier — średnie obrażenia zadane/otrzymane per strona, średnie straty/zabicia, miks akcji, rozkład wyników (P0/P1/remis), średnia liczba rund, zagregowany rozkład rzutów Przegrupowania. To bezpośrednio adresuje otwarte pytanie D4 ("sufit to jakość polityki, nie głębokość") — pozwala zobaczyć CZY silniejszy bot zadaje więcej obrażeń, czy tylko trzyma cele mniejszym kosztem.

Reuse rdzenia `analyze_battle_log` (z poprzedniego slice) per gra + agregacja. Metodyka próby jak `balance_simulate`: naprzemienna inicjatywa (`i%2`) usuwa bias 1. gracza; `owner_player` stały (roster[0]→P0) → staty per strona porównywalne między grami.

## Zablokowane pliki / katalogi
- `scripts/analyze_battle.py` — dodanie `aggregate_analyses`/`render_aggregate` + `analyze_aggregate_from_fixture` + `--games`
- `tests/test_analyze_battle.py` — testy agregacji
- `scripts/README.md` — wzmianka `--games`

## Blokuje / Blokowane przez
- **Blokuje:** nic. **Blokowane przez:** nic (rdzeń analizy już istnieje).

## Gałąź git
- **Branch:** `Faza_A` / **Base:** `main`

## Plan implementacji

### Faza 1 — Agregacja
- [x] Krok 1.1: `aggregate_analyses(analyses) -> AggregateAnalysis` (czysta funkcja): games, win distribution (P0/P1/remis), mean_rounds, side_means (per strona, średnia na grę), zagregowane morale_dice, mean action_counts.
- [x] Krok 1.2: `render_aggregate(agg, *, header) -> str` markdown (tabela per strona + rozkład wyników + miks akcji + kości).

### Faza 2 — Źródło + CLI
- [x] Krok 2.1: `analyze_aggregate_from_fixture(...)` — N gier (`simulate_from_rosters`, `bsim.initiative_for_game(i)`), per gra `_simulate_one`→`analyze_battle_log`, agregacja. Refaktor: wspólny `_simulate_one` (analyze_from_fixture też go używa).
- [x] Krok 2.2: `--games N` w CLI (N>1 → agregat; N==1 → per-battle). `--games>1` + `--from-db` → błąd (exit 2).

### Faza 3 — Testy + docs
- [x] Krok 3.1: +8 testów (sumy/średnie identycznych gier; rozkład wyników mieszany; empty; render; integracja + determinizm; CLI `--games`; odrzucenie `--from-db`+`--games`).
- [x] Krok 3.2: `scripts/README.md` (wpis `--games`).

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — pełna (patrz niżej)
- [!] Smoke JS — nie dotyczy
- [x] Call-site check — addytywne; `analyze_from_fixture` refaktoryzowane na `_simulate_one` (zachowuje sygnaturę + zachowanie, pokryte istniejącymi testami)
- [x] `/simplify` (zawsze) — inline
- [!] `/review` — pominięty warunkowo (skrypt-liść, read-only)
- [!] `/security-review` — nie dotyczy (read-only, brak auth/DB-write)
- [x] Diff review przed commitem

## Hipotezy / pytania otwarte
- `READY` — w pełni specyfikowane.
- `BLOCKED(user)` (NIE w tym wątku — follow-up telemetrii): pełna analiza szczęścia kości BOJOWYCH wymaga surowych rzutów trafień/obrony w event-logu. Obecnie `ShotResolved`/`MeleeResolved` trzymają tylko `hits`/`wounds_dealt` (nie raw rolls) — `analyze_battle` liczy "szczęście" tylko z `MoraleTestPassed.rolls`. Dodanie raw rolls = zmiana ZAMROŻONEJ schemy `payload_json` (ORM B2) + golden digestów B7 → wymaga ADR + regen. Brakująca decyzja usera: czy rozszerzyć schemę eventów combat o raw rolls dla telemetrii.

## Decyzje
- 2026-06-21: Slug `faza-telemetry-aggregate`. Druga, pokrewna część sesji autonomicznej (po `faza-telemetry-analyze`). Metodyka próby = `balance_simulate` (naprzemienna inicjatywa).

## Notatki / odkrycia w trakcie
- 2026-06-21: `owner_player` stały z kolejności rosterów (roster[0]→P0, `state.py` build) — staty per strona porównywalne między grami mimo naprzemiennej inicjatywy.
