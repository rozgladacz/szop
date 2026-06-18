# HANDOFF — faza-d-minimax

> **Wątek:** Strumień D4 — `app/services/agents/minimax_player.py`: bot z lookahead głębokości 2 (moja akcja → najlepsza odpowiedź wroga → ocena `evaluate_state`), adresujący udokumentowaną słabość „miopia depth-1" istniejących botów.
> **Status:** In progress
> **Utworzony:** 2026-06-18
> **Ostatnia aktualizacja:** 2026-06-18

## W TRAKCIE

- **2026-06-18 (sesja autonomiczna) — START.** Wybór zadania: D4 `minimax_player.py` (roadmap, checkbox `[ ]`). Powód: czysta warstwa-liść agentów (zero zmian w rdzeniu `engine/*` → brak kolizji z lockami / golden-digestami B7), wzmacnia zestaw botów dla D3 exploit-hunt / D2 balansu (aktywna fala D), adresuje wielokrotnie logowaną słabość depth-1 („cele >1 ruch poza horyzontem; adresuje to D4 minimax"). Nie wymaga decyzji usera ani danych DB.

## Cel

Zbudować `MinimaxPlayer` — bota lookahead głębokości 2 nad publicznym API silnika (ADR-0011), bez zmian w rdzeniu. Dla każdej legalnej akcji aktywnego gracza: zaaplikuj ją deterministycznie (`resolver.apply` z ustalonym `DeterministicDice` per seed — expectiminimax uproszczony do jednego deterministycznego rollu, spójnie z `RandomPlayer`), znajdź **najlepszą odpowiedź wroga** (maksymalizuje swoją `evaluate_state`), oceń wynikowy stan z mojej perspektywy. Wybierz akcję maksymalizującą ten zminimalizowany (przez wroga) wynik (maximin). Lookahead respektuje naprzemienne aktywacje (pkt 8.a/8.b — po aktywacji inicjatywa przechodzi do wroga, jeśli ma nieaktywowane oddziały). Zwycięstwo liczone celami (pkt 5.f) — `evaluate_state` już to koduje.

## Zablokowane pliki / katalogi

- `app/services/agents/minimax_player.py` (NEW)
- `app/services/agents/__init__.py` (MOD — eksport)
- `tests/test_agents_minimax.py` (NEW)
- `scripts/balance_simulate.py` (MOD — `make_player` + `PLAYER_KINDS`)
- `docs/roadmap.md` (MOD — D4 checkbox)
- `docs/architecture.md` (MOD — sekcja agentów, licznik testów)

## Blokuje / Blokowane przez

- **Blokuje:** nic (bot opcjonalny, narzędzie testowania balansu D-stream).
- **Blokowane przez:** nic — engine public API stabilne (B3.9), `legal_actions`/`evaluate_state`/`resolver.apply` gotowe.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — MinimaxPlayer (depth-2 maximin)

- [x] 1.1 `minimax_player.py`: `MinimaxPlayer(seed=0)`. `choose_action`: enumeruje `legal_actions(state, perspective)`; dla każdej `_apply(state, action)` → stan po mojej aktywacji + przekazaniu inicjatywy; `_opponent_best_value` (depth-1 wroga: enumeruje legalne akcje wroga, aplikuje, ocenia `evaluate_state(·, opponent)`, bierze max — lub `evaluate_state` bez ruchu gdy wróg nie ma akcji); wartość mojej akcji = `evaluate_state(stan_po_odpowiedzi_wroga, perspective)`. Argmax po wartości (maximin), deterministyczny tie-break (pierwszy w `legal_actions`).
- [x] 1.2 Deterministyczny dice do lookahead: `DeterministicDice` z ustalonym seedem (per `MinimaxPlayer.seed`), świeży na każdą hipotetyczną aplikację (rollout nie zaburza realnego RNG gry — bot to czysta funkcja decyzji). Obsłuż `IllegalActionError` z resolvera (akcja-kandydat odrzucona → pomiń).
- [x] 1.3 `continue_activation` (pkt 11.b.iv): analogiczny maximin na `legal_followup_actions`; zwraca None gdy najlepsza kontynuacja nie poprawia wartości względem zakończenia aktywacji (pass = `_evaluate(state)`, bo inicjatywa jeszcze nie przeszła).
- [x] 1.4 Guard wydajności: **zmierzono — cap NIEpotrzebny.** `--players minimax,greedy -n 2` → 2.8 s (z startem Pythona), ~1 s/gra, ~30 ms/akcja — w budżecie ~100 ms (roadmap D4). Bez sztucznego ograniczania rozgałęzienia.

### Faza 2 — Wpięcie + testy

- [x] 2.1 `__init__.py` eksport `MinimaxPlayer`.
- [x] 2.2 `balance_simulate.make_player` + `PLAYER_KINDS` (`minimax`).
- [x] 2.3 `tests/test_agents_minimax.py` (8 testów): None gdy brak akcji, determinizm per seed, legalność wyboru, zdobycie niezajętego celu, **różnik depth-2** (`_opponent_best_value` < ocena bez odpowiedzi gdy wróg może przejąć cel), continue_activation None bez kontynuacji, pełna gra deterministyczna, sanity minimax bije greedy.

### Faza 3 — Weryfikacja end-to-end (Definition of Done)

- [x] `pytest -q` zielony — **1743 passed** (1735 baseline + 8). Naprawiono 3 testy używające `minimax` jako placeholdera „nieznanej" nazwy gracza → `nieistniejacy_bot` (test_balance_simulate ×2, test_balance_report ×1).
- [x] Call-site check (`make_player`, `__init__` eksport — addytywne; `PLAYER_KINDS` rozszerzony)
- [x] `/simplify` — 4 kąty inline; 1 cleanup (dedup pętli argmax w `choose_action`/`continue_activation` → helper `_pick(state, actions, perspective, floor)`); reuse/efficiency/altitude czyste (reuse SSOT `_check_objective_control`+`evaluate_state`, bot trzyma tylko `_seed:int` → brak closure-leak, czysty konsument API).
- [x] `/review` — substancję correctness wykonano inline (antysymetria oceny, przekazanie inicjatywy, rezerwy Zaplecze, determinizm); pełny `/review`/cloud pominięty warunkowo: izolowana warstwa-liść, zero rdzenia/hot-path/SSOT/auth/DB, 8 testów (incl. różnik depth-2 + determinizm pełnej gry). Precedens D-stream (każdy poprzedni bot).
- [!] `/security-review` — nie dotyczy: izolowana warstwa-liść, zero auth/route/DB-write.
- [x] Re-run `pytest` po `/simplify` — 53 dotknięte + pełna suita **1743 passed**.
- [x] Diff review + roadmap/architecture update zrobione; commit poniżej.

## Pliki dotknięte

- `app/services/agents/minimax_player.py` (NEW)
- `app/services/agents/__init__.py` (MOD)
- `tests/test_agents_minimax.py` (NEW)
- `scripts/balance_simulate.py` (MOD)
- `docs/roadmap.md`, `docs/architecture.md` (MOD)

## Decyzje

- 2026-06-18: Silnik jest stochastyczny (kości) → czysty minimax niemożliwy; upraszczamy do **deterministycznego rollout** z ustalonym `DeterministicDice` per seed (jak `RandomPlayer` — odtwarzalny, testowalny). Pełny expectiminimax (uśrednianie po rzutach) odłożony — przedwczesny dla „depth-2 do testów" (roadmap D4).
- 2026-06-18: Głębokość 2 = moja aktywacja + 1 odpowiedź wroga (depth-1 po stronie wroga). Pełne drzewo gry (wiele aktywacji/runda) niewykonalne w ~100 ms; maximin na 1 ply wroga to standardowy „depth-2".
- 2026-06-18: Lookahead reużywa `resolver.apply` (rzeczywista semantyka akcji + przekazanie inicjatywy pkt 8.a) zamiast heurystycznych hipotetycznych stanów (jak greedy) — to różnica jakościowa względem depth-1 (greedy przybliża; minimax symuluje).

## Hipotezy / pytania otwarte

- `READY` — całość specyfikowana, brak otwartych pytań do usera.

## Jak zweryfikować

```powershell
python -m pytest tests/test_agents_minimax.py -v
python -m pytest -q   # pełna suita
python scripts/balance_simulate.py --players minimax,greedy -n 20 --map lustrzana_a   # sanity balansu
```
