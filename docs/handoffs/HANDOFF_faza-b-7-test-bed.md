# HANDOFF — faza-b-7-test-bed

> **Wątek:** B7 — golden regression test bed: deterministyczne pełne bitwy z predefiniowanym seedem i zapieczętowanym (golden) wynikiem.
> **Status:** In progress
> **Utworzony:** 2026-06-13
> **Ostatnia aktualizacja:** 2026-06-13

## Cel

Domknąć **B7 (Test bed)** z roadmap Strumień B: `tests/test_engine_regression.py` — golden scenariusze pełnych bitew (fixtura + predefiniowany seed + deterministyczny matchup botów) z zapieczętowanym oczekiwanym wynikiem. Cel: siatka bezpieczeństwa regresji nad silnikiem + warstwą agentów. **Zmiana wartości golden = świadoma zmiana rulesetu/silnika → wymaga ADR** (roadmap B7). Reużywa istniejącej infrastruktury (`load_battle_fixture`, `simulate_from_rosters`, `DeterministicDice`) — zero zmian w rdzeniu silnika.

## Zablokowane pliki / katalogi
- `tests/test_engine_regression.py` (NEW) — golden regression suite
- (read-only) `scripts/balance_simulate.py`, `app/services/agents/match.py`, `tests/fixtures/battles/*.yaml`

## Blokuje / Blokowane przez
- **Blokuje:** nic (warstwa testowa-liść).
- **Blokowane przez:** nic — B3/B3.9 done, match runner (ADR-0032) + fixtury wierne regułom gotowe.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Capture golden values
- [x] Krok 1.1: Probe (`build/_probe_golden.py`, gitignored) — 6 deterministycznych matchów na 3 fixturach; golden + digest zebrane, determinizm OK (każdy case identyczny w 2 uruchomieniach).
- [x] Krok 1.2: Matchupy dają rozstrzygnięcia (winner 0/1/None pokryte): 1 remis (priority-mirror), 3× P0, 2× P1.

### Faza 2 — Test bed
- [x] Krok 2.1: `tests/test_engine_regression.py` — 6 golden cases (param) + 6 reproducible + 2 sanity = 14 testów. Asercje semantyczne (winner/rounds/score/event-count) + digest sha256 lock.
- [x] Krok 2.2: Docstring + komentarze: „zmiana golden = świadoma → ADR" + instrukcja regen przez `build/_probe_golden.py`.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [ ] `pytest -q` (pełna suita — golden + brak regresji)
- [!] Smoke test JS — nie dotyczy (brak zmian `app.js`)
- [ ] Call-site check — N/A (nowy plik testowy, brak zmian funkcji prod)
- [ ] `/simplify` — przegląd jakości (zawsze)
- [!] `/review` — warunkowo (test-only, brak hot-path/SSOT/prod; ocena po diffie)
- [!] `/security-review` — nie dotyczy (brak auth/DB/user input)
- [ ] Re-run `pytest -q` jeśli `/simplify` coś zmieni
- [ ] Diff review przed commitem

## Pliki dotknięte
- `tests/test_engine_regression.py` (NEW) — <w trakcie>
- `docs/roadmap.md` — B7 odznaczone <w trakcie>

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak — wątek techniczny, bez decyzji usera)

## Hipotezy / pytania otwarte
- **Digest lock vs brittleness:** `READY` — digest pełnego event-logu jest celowo czuły (każda zmiana silnika flipuje → wymusza świadomą aktualizację golden + ADR, dokładnie intencja B7). Asercje semantyczne (winner/rounds/score) obok digestu dają czytelność „co się zmieniło".

## Jak zweryfikować
```powershell
python -m pytest tests/test_engine_regression.py -v
python -m pytest -q  # pełna suita — brak regresji
```
