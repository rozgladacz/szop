# HANDOFF — faza-d-leaderboard-cleanup

> **Wątek:** Cleanup po code-review 2026-06-20 — usunięcie duplikacji infrastruktury
> `scripts/leaderboard.py` ↔ `scripts/balance_report.py` i domigracja `leaderboard.py`
> do nowego registry-SSOT (`app/services/agents/registry.py`).
> **Status:** DONE — autonomiczna sesja 2026-06-20 (gotowy do archiwizacji).
> **Utworzony:** 2026-06-20
> **Ostatnia aktualizacja:** 2026-06-20

## ZREALIZOWANE (2026-06-20, autonomiczna)

- **Finding 1 (duplikacja ~150 LOC) — ROZWIĄZANE.** Nowy `scripts/balance_common.py`
  trzyma jedyną kopię wspólnych czystych funkcji: loader `balance_simulate`,
  `DEFAULT_FIXTURES`, `DEFAULT_PLAYERS` (=`registry.USEFUL_KINDS`), `resolve_fixtures`
  (duck-typed na config), `_fixture_names_in_order`, `_bar`/`_BAR_WIDTH`, `_today`,
  `write_report`, `_parse_fixtures`, `_parse_map_list`, `_parse_player_list`
  (z ekspansją tagów registry). `leaderboard.py` + `balance_report.py` re-eksportują
  je jako atrybuty modułu (zachowane API testów `lb.*`/`br.*`). Zostaje lokalnie tylko
  to, co RÓŻNE: pairing (`combinations` vs `combinations_with_replacement`), render
  markdown, `default_report_path` (różne ścieżki), config-dataclass, `compute_standings`.
  Netto: −195 linii duplikacji w skryptach (244 del / 49 add), +1 współdzielony moduł.
  Dryf docstringu `_load_balance_simulate` (zła nazwa testu) zniknął przez eliminację kopii.
- **Finding 2 (leaderboard omija registry-SSOT) — ROZWIĄZANE.** `leaderboard.DEFAULT_PLAYERS`
  zmienione z `tuple(PLAYER_KINDS)` (WSZYSTKIE, incl. drogie minimax 185×/claude_v2 115×)
  na `registry.USEFUL_KINDS` (= priority/priority3/claude_v3). `--players` teraz tag-aware
  (`useful`/`fast`/`reference`/`all` + nazwy) przez wspólny `_parse_player_list`. Spójne
  z `balance_report`. `--players all` przywraca pełny ranking.
- **Wzorzec ładowania:** spec/exec z cache w `sys.modules` (jak `_load_balance_simulate`).
  `scripts/` NIE staje się pakietem — świadome (gdyby było, `import scripts.balance_simulate`
  dałby inny obiekt modułu niż spec-loaded, łamiąc tożsamość dataclass `BalanceResult`).
  Residual: ~8-linijkowy `_load_balance_common` bootstrap duplikowany w 2 skryptach +
  re-eksport — irreducible bez pakietyzacji; zgodne z istniejącą konwencją skryptów-liści.

## Faza Weryfikacja — Definition of Done

- [x] `pytest -q` zielony — **1812 passed** (zero regresji; pakiet review 88/88:
      leaderboard 33 + balance_report 27 + registry 9 + balance_simulate 19/22... ).
- [x] Smoke CLI: leaderboard default (`useful`→3 pary), `--players all` (9 botów→36 par),
      `--players useful,reference` (tag→36 par), balance_report `--players fast` (7→28 par).
- [x] Call-site check — `balance_common.py` nowy, ładowany przez oba skrypty + testy;
      brak innych konsumentów. Rdzeń `engine/*` / `make_player` / `PLAYER_KINDS` / registry
      NIETKNIĘTE (tylko czytane; `test_agents_registry.py` 9/9 zielone).
- [x] `/simplify` — inline 4 kąty; residual bootstrap (`_load_balance_common`) irreducible
      i świadomy (brak pakietyzacji scripts/). Reszta: pełna dedup.
- [x] `/review` — pominięty warunkowo: skrypty-liście, czysty refaktor, registry/SSOT
      tylko czytane, brak hot-path/auth/DB. Jedyna zmiana zachowania (default leaderboardu
      ALL→USEFUL) świadoma, udokumentowana i zsmoke'owana. Inline correctness self-review.
- [!] `/security-review` — N/A (brak auth/route/DB-write; skrypty read-only nad symulacją).
> **Gałąź git:** Faza_A
> **Pliki (planowane do dotknięcia):** `scripts/leaderboard.py`,
> `scripts/balance_report.py`, (NEW) `scripts/balance_common.py`,
> `tests/test_leaderboard.py`, `tests/test_balance_report.py`

## Dlaczego (źródło)

Code-review `86b58e4..HEAD` (REVIEW_2026-06-20.md) — 0 bugów korektościowych, ale
2 findingi cleanup. Oba wynikły z **kolejności commitów w oknie**: `leaderboard.py`
(`56a95ed`) powstał PRZED registry (`f12cb6f`), więc nie został zmigrowany razem z
`balance_report.py`. Nie blokuje nic; to dług techniczny do spłaty zanim leaderboard
się rozrośnie.

## Zakres

### Finding 1 — duplikacja ~150 LOC (średni)

`leaderboard.py` kopiuje verbatim z `balance_report.py`:
- `_load_balance_simulate()` (loader sąsiedniego skryptu + rejestracja w `sys.modules`)
- `DEFAULT_FIXTURES`, `resolve_fixtures()`, `_fixture_names_in_order()`
- `_bar()` / `_BAR_WIDTH` (render unicode słupków win-rate)
- `_today()`, `write_report()`, `_parse_fixtures()`, `_parse_map_list()`
- boilerplate: UTF-8 stdout reconfigure + `_repo_root` + `sys.path.insert`

Skrypty różnią się **tylko**: pairing (`combinations` vs
`combinations_with_replacement` w balance_report) + render markdown (ranking vs
macierz pairwise). **Dryf już widoczny:** docstring `_load_balance_simulate` w
kopii leaderboard odnosi się do złej nazwy testu (`balance_report.py` zamiast
`test_balance_simulate.py`).

### Finding 2 — leaderboard omija registry-SSOT (średni)

`leaderboard.py:79` `DEFAULT_PLAYERS = tuple(bsim.PLAYER_KINDS)` + ręczny
`_parse_player_list` (≈linie 323–339): brak ekspansji tagów, default = WSZYSTKIE
boty (w tym `minimax` 185× i `claude_v2` 115×). `balance_report.py` w tym samym
oknie ma już `registry.USEFUL_KINDS` default + ekspansję tagów (`useful`/`fast`/
`all`). Efekt: `python scripts/leaderboard.py` bez argów odpala drogie boty
referencyjne na każdej parze; nie obsługuje `--players useful`.

## Plan realizacji (proponowany)

1. **Utwórz `scripts/balance_common.py`** — przenieś wspólne czyste funkcje:
   loader, DEFAULT_FIXTURES + resolve_fixtures + _fixture_names_in_order, _bar +
   _BAR_WIDTH, _today, _parse_fixtures, _parse_map_list, boilerplate UTF-8/repo_root.
   (UWAGA: `scripts/` nie jest pakietem — sprawdź czy import sąsiada działa tak jak
   `_load_balance_simulate` ładuje balance_simulate; ew. ten sam wzorzec spec/exec
   dla balance_common, albo dołóż `__init__.py`. Wybierz spójnie z istniejącym
   wzorcem ładowania.)
2. **Przepisz `leaderboard.py` + `balance_report.py`** na importy z `balance_common`
   — usuń kopie. Zachowaj różnice (pairing + render) lokalnie.
3. **Domigruj `leaderboard.py` do registry:** `DEFAULT_PLAYERS = registry.USEFUL_KINDS`;
   `_parse_player_list` → reużyj logikę z `balance_report` (ekspansja tagów
   `all_tags()`/`bot_kinds()`). Najlepiej wspólny `_parse_player_list` też do
   `balance_common`.
4. **Testy zielone:** `pytest tests/test_leaderboard.py tests/test_balance_report.py
   tests/test_agents_registry.py -q` (baseline 2026-06-20: 82 passed dla pakietu
   review). Zaktualizuj asercje, jeśli zmieni się default-set leaderboardu
   (USEFUL zamiast ALL → mniej botów w domyślnym rankingu).
5. **Docs:** nota w `scripts/README.md` (sekcja leaderboard/balance) o wspólnym
   module; zaktualizuj docstring `_load_balance_simulate` (zła nazwa testu).

## Ryzyka / uwagi

- Oba skrypty mają realne testy — refaktor musi je utrzymać zielone (nie test-only).
- Zmiana defaultu leaderboardu (ALL→USEFUL) jest **zmianą zachowania CLI** —
  świadoma i pożądana (spójność z balance_report), ale odnotuj w commicie.
- Nie ruszać rdzenia `engine/*` ani `make_player`/`PLAYER_KINDS` (to osobny SSOT
  konstrukcji, pilnowany `test_agents_registry.py` — patrz obserwacja 1 w REVIEW).
