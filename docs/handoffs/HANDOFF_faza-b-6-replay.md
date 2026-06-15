# HANDOFF — faza-b-6-replay

> **Wątek:** B6 prezentacja — `scripts/battle_replay.py` (CLI replay event-logu bitwy do czytelnego tekstu), headless-first (ADR-0013).
> **Status:** Ready for archive
> **Utworzony:** 2026-06-15
> **Ostatnia aktualizacja:** 2026-06-15

## Cel

Pierwszy deliverable Strumienia B6 (prezentacja, roadmap): `scripts/battle_replay.py` — czyta strumień eventów bitwy i renderuje go jako czytelny log tekstowy w terminalu (narracja per event + podsumowanie rund + zwycięzca). Dwa źródła eventów: (1) świeża symulacja z fixtury/mapy (reuse `balance_simulate` SSOT + `simulate_from_rosters`), (2) `--from-db <id>` z persystencji (`persistence.load_events`). Rdzeń = czyste funkcje formatujące (testowalne, bez I/O). Domyka ADR-0013 (engine headless-first, UI opcjonalne) jako Accepted. Skrypt-liść — **zero zmian w rdzeniu silnika/agentów**.

## Zablokowane pliki / katalogi
- `scripts/battle_replay.py` (NEW) — skrypt CLI + funkcje renderujące
- `tests/test_battle_replay.py` (NEW) — testy formatowania + smoke CLI
- `docs/adr/0013-headless-first.md` (NEW) — Status: Accepted
- `docs/roadmap.md` — B6 status + ADR index 0013
- `scripts/README.md` — wpis skryptu

## Blokuje / Blokowane przez
- **Blokuje:** nic bezpośrednio (B6 opcjonalne). Daje narzędzie do wizualnej inspekcji przebiegu gry dla D/B.
- **Blokowane przez:** nic — engine public API (ADR-0011), `simulate_from_rosters` (ADR-0032), `persistence.load_events` (ADR-0050) gotowe.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Rdzeń renderujący (czyste funkcje)
- [x] Krok 1.1: `format_event(event) -> str` — jednolinijkowa narracja PL per 16 typów eventów (dispatch `_FORMATTERS` + fallback repr dla nieznanego typu).
- [x] Krok 1.2: `render_battle_log(events, *, header=None, winner=None) -> str` — grupuje eventy w rundy (delimiter `RoundEnded`), numeruje sekwencją, podsumowanie (liczba eventów, cele końcowe z `RoundEnded.objectives_held`, zwycięzca, rozkład typów).

### Faza 2 — Źródła eventów + CLI
- [x] Krok 2.1: tryb sim — `replay_from_fixture` reuse `balance_simulate` (make_player/PLAYER_SEED_OFFSET) + `simulate_from_rosters`; header fixtura/gracze/seed/rund.
- [x] Krok 2.2: tryb `--from-db <id>` — `replay_from_db`: `app.db.SessionLocal` + `persistence.load_events` (read-only).
- [x] Krok 2.3: `build_arg_parser()` + `main(argv)` — `--fixture` | `--map` | `--from-db` (mutually exclusive group), `--seed`, `--players a,b`, `--map-seed`, `--initiative`. UTF-8 stdout.

### Faza 3 — Testy
- [x] Krok 3.1: `tests/test_battle_replay.py` (16 testów) — format każdego z 16 typów + fallback + enum-coercion StatusFlag + Kontratak vs Szarża; `render_battle_log` (podział rund, podsumowanie, wnioskowanie/override zwycięzcy, remis, brak pustego nagłówka rundy); reuse `simulate_from_rosters` (niepusty + determinizm); CLI main (fixtura/default/map) + mutually-exclusive sources.

### Faza 4 — Dokumentacja
- [x] Krok 4.1: ADR-0013 (NEW Accepted), roadmap B6 status + ADR index 0013 ✓, `scripts/README.md` wpis, `docs/architecture.md` nowa sekcja "Prezentacja".

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — **1657 passed** (1641 baseline + 16 nowych)
- [!] Smoke test JS — nie dotyczy (brak zmian `app.js`)
- [x] Call-site check — `grep battle_replay app/` → 0 trafień (leaf, brak importów z app). CLI smoke `--fixture`/`--map`/`--from-db` OK.
- [x] `/simplify` — 4 kąty inline; 1 cleanup (dedup `_fmt_shot`/`_fmt_melee` → `_fmt_attack`). Reszta czysta (reuse `balance_simulate` SSOT, dispatch+fallback altitude OK).
- [!] `/review` — pominięty warunkowo: izolowany skrypt-liść, brak hot-path/SSOT/auth, render read-only, pełne pokrycie 16 testami (correctness self-review inline wykonany).
- [!] `/security-review` — nie dotyczy (brak auth/user-input→DB; DB tylko odczyt eventów po id + idempotentne addytywne `create_all`).
- [x] Re-run `pytest -q` po simplify + import-fix — 1657 passed.
- [x] Diff review przed commitem.

## Pliki dotknięte
- `scripts/battle_replay.py` (NEW) — CLI replay + czyste funkcje renderujące
- `tests/test_battle_replay.py` (NEW, 16) — format/render/integracja/CLI
- `docs/adr/0013-headless-first.md` (NEW Accepted)
- `docs/roadmap.md` (MOD) — B6 CLI replay slice DONE + ADR index 0013 ✓
- `docs/architecture.md` (MOD) — sekcja "Prezentacja — scripts/battle_replay.py"
- `scripts/README.md` (MOD) — wpis `battle_replay.py`
- `HANDOFF.md` (MOD) — rejestr wątku (usunięty przy archiwizacji)

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak)

## Hipotezy / pytania otwarte
- `READY`: SSE stream + canvas frontend (kolejne bullet'y B6 roadmap) — poza zakresem tego slice'a (CLI replay first). Osobny wątek gdy potrzebne.

## Jak zweryfikować
```bash
python -m pytest tests/test_battle_replay.py -q
python scripts/battle_replay.py --fixture tests/fixtures/battles/demo_skirmish.yaml --players priority,random --seed 7
python -m pytest -q
```

## Decyzje
- 2026-06-15: Slice CLI replay (narracja z eventów) PRZED SSE/canvas. Render z samego event-logu (bez rekonstrukcji pełnego stanu) — działa jednolicie dla trybu sim i `--from-db` (persystencja nie trzyma initial_state). Bieżące dane pochodne (wynik celów) z `RoundEnded.objectives_held`.

## Notatki / odkrycia w trakcie
- 2026-06-15: `MatchResult.events` NIE zawiera eventów rozstawienia (runner liczy od rundy 1) — narracja zaczyna się od R1, co jest pożądane dla czytelności. `persistence.load_events` zwraca pełną listę dataclass eventów posortowaną po `sequence`.
- 2026-06-15: **Latentny cykl importu w `app.db`** — `app.db` importuje `app.services` (linia 11) zanim zdefiniuje `Base`, więc zaimportowanie `app.db` jako PIERWSZEGO z pary db/models wpada w `ImportError: cannot import name 'Base'`. Normalny bootstrap aplikacji importuje `app.models` pierwszy (to ono triggeruje pełny import db). `replay_from_db` odtwarza tę kolejność: `import app.models` przed `from app.db import ...`. (Obserwacja — nie naprawiam app.db, to poza zakresem; workaround lokalny w skrypcie.)
- 2026-06-15: Tabele event-store (`battles`/`battle_events`) powstają przez `create_all` przy bootstrapie app (ADR-0050). Standalone `--from-db` na bazie bez nich → `OperationalError`. Fix: `Base.metadata.create_all(bind=engine)` w `replay_from_db` (idempotentne, addytywne — nie rusza danych; `data/szop.db` gitignored). Brak bitew → "(brak eventów)".
- 2026-06-15: **DONE.** pytest 1657, CLI zweryfikowane (fixtura/mapa/from-db). Ready for archive.
