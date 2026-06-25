# HANDOFF — code-review-telemetry-action-scope

> **Wątek:** Telemetria ADR-0017 (`analyze_agents`) mierzy `action_mix` i `decision_time_ms` tylko z PIERWSZEJ akcji aktywacji — drugie akcje (kontynuacja do 2 akcji, pkt 11.b.iv) są niewidoczne, a `quality` liczy się dla pełnej aktywacji → niespójny zakres pomiaru.
> **Status:** In progress — BLOCKED(user) **RESOLVED 2026-06-25**, Faza 2 (implementacja) ready to start
> **Utworzony:** 2026-06-24
> **Ostatnia aktualizacja:** 2026-06-25 user decision (opcja A per-akcja)

## Cel
Wykryte w code-review 2026-06-24 (`docs/handoffs/code-review/REVIEW_2026-06-24.md`, Finding 1).
`match.run_match` woła `on_decision` **raz na aktywację** (match.py:168-171), przekazując
pierwszą `action` oraz `_elapsed_ms` zmierzony tylko wokół pierwszego `choose_action`
(match.py:125-127; komentarz match.py:61 „bez kontynuacji 2. akcji"). Aktywacja wykonuje
do 2 akcji (np. PriorityPlayer: Manewr → Ostrzał). W efekcie nagłówkowy raport
`analyze_agents` „## Miks typów akcji (per agent)" (analyze_agents.py:332, pole jsonl
`action_mix`) **systematycznie pomija drugie akcje** (bot Manewr+Ostrzał raportuje tylko
Manewr), a `decision_time_ms` nie liczy czasu wyboru 2. akcji. Jednocześnie `quality`
(`quality_from_states`) obejmuje pełną aktywację (state_before vs stan finalny) → dwie
kolumny raportu mierzone w niespójnym zakresie. Cel wątku: podjąć decyzję projektową
i ujednolicić zakres pomiaru (albo udokumentować ograniczenie jawnie w raporcie).

## W TRAKCIE — 2026-06-25T09:16+02:00 — backlog READY: wiersz zerowy bota + warning --initiative

**Zakres pracy:** domknąć DWIE pozostałe pozycje `READY` z backlogu review (NIE
główna decyzja `BLOCKED(user)`):
1. `analyze_agents` cicho pomija bota, który nigdy się nie aktywował (degeneracyjny
   fixture) → brak wiersza w raporcie ("1 bot zamiast 2"). Pre-seed `AgentMetrics`
   wszystkich botów z drivera (`games_by_kind`) → wiersz zerowy zamiast zniknięcia.
2. `analyze_battle --initiative` cicho ignorowane przy `--games>1` (jest w help,
   brak ostrzeżenia runtime) → jawny warning na stderr (non-fatal).

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A. Backend payload: N/A. JS/CSS/template: N/A.
- CLI/script: `scripts/analyze_agents.py` (aggregate_records), `scripts/analyze_battle.py` (main + arg default).
- Testy: `tests/test_analyze_agents.py` (wiersz zerowy), `tests/test_analyze_battle.py` (warning + per-battle initiative bez zmian).
- Dokumentacja: ten HANDOFF.

**Performance gate:** brak hot path; zero DB queries; tylko raport/walidacja CLI.

**Plan:**
- [x] 1. `aggregate_records` pre-seeduje boty z `games_by_kind` (wiersz zerowy).
- [x] 2. `analyze_battle`: `--initiative` default None → detekcja jawnego podania → warning przy `--games>1`; per-battle bez zmian (None→0).
- [x] 3. Regresje + targeted + pełny pytest fallback.
- [x] 4. DoD: call-site check, `/simplify`, `/review` jeśli diff >50 linii, diff review, commit.

**Otwarte kwestie:** główna decyzja `BLOCKED(user)` (kierunek A/B) bez zmian.

**Wykonane kroki / odkrycia:**
- 2026-06-25T09:30: `aggregate_records` pre-seeduje wszystkie boty z `games_by_kind`
  (zamiast post-loopa ustawiającego tylko `.games` dla obecnych kindów) → bot bez
  aktywacji dostaje wiersz zerowy; kolejność = matchup z drivera. Wstecznie
  kompatybilne dla `games_by_kind=None` (zachowane: kolejność = pierwsze wystąpienie).
  Properties już strzegły dzielenia przez 0 (`if self.decisions else 0.0`).
- 2026-06-25T09:30: `analyze_battle --initiative` default `0`→`None` (detekcja jawnego
  podania); per-battle używa `args.initiative if not None else 0` (zachowany default 0);
  przy `--games>1 + jawne --initiative` → non-fatal warning na stderr (rc nadal 0).
- 2026-06-25T09:35: Targeted `tests/test_analyze_agents.py tests/test_analyze_battle.py`
  — **51 passed** (47 + 4 nowe regresje). Pełny `pytest -x -q` fallback — **1916 passed**
  (1912 baseline + 4). Call-site check: `aggregate_records` jeden producent
  (`analyze_agents.py:413`, przekazuje `games_by_kind`); `args.initiative` w
  `analyze_battle` tylko w `main()` (`battle_replay.py:428` to osobny parser,
  nietknięty). Manual `/simplify`: 0 zmian (pre-seed loop zastępuje conditional
  post-loop = net prostsze; brak duplikacji/dead code). `/review` multi-agent
  pominięty warunkowo (kod <50 linii, skrypt-liść, brak hot-path/SSOT-mutacji/auth/DB,
  pełne pokrycie regresjami incl. backward-compat); `/security-review` N/A.

**Status backlogu po tym slice:** wszystkie 4 pozycje `READY` z review domknięte
(`--players`/`--map`/`--fixture` error-handling + wiersz zerowy bota + warning
`--initiative`). Pozostaje wyłącznie Finding 1 `BLOCKED(user)` (zakres pomiaru
action_mix/decision_time_ms — kierunek A/B).

## W TRAKCIE — 2026-06-25T06:03:05+02:00 — fixture CLI error handling

**Zakres pracy:** domknąć drobny backlog z poprzedniego slice'a: `analyze_agents --fixture <nieistniejący>` ma zwracać czytelny błąd argparse zamiast tracebacku `FileNotFoundError`.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload: N/A.
- JS render / CSS / template: N/A.
- CLI/script: `scripts/analyze_agents.py`.
- Testy: `tests/test_analyze_agents.py` regresja CLI dla brakującej fixtury.
- Dokumentacja: ten HANDOFF.

**Performance gate:** brak hot path (`/quote`, `/rosters/{id}`), zero nowych DB queries, zero zmian runtime aplikacji; tylko walidacja błędnego argumentu CLI przed symulacją.

**Plan:**
- [x] 1. Potwierdzić ścieżkę błędu `load_battle_fixture` i istniejące regresje CLI.
- [x] 2. Rozszerzyć obsługę błędnej fixtury na `parser.error`.
- [x] 3. Dodać regresję bez tracebacku i uruchomić targeted + pełny pytest fallback.
- [x] 4. DoD: call-site check, manual `/simplify`, manual `/review` jeśli diff >50 linii, diff review.

**Otwarte kwestie:** główna decyzja `BLOCKED(user)` z Fazy 1 pozostaje bez zmian; ten slice jej nie rozstrzyga.

**Wykonane kroki / odkrycia:**
- 2026-06-25T06:03: Wybrano ten slice, bo kontynuuje istniejący handoff i usuwa konkretny, low-risk błąd CLI z backlogu bez dotykania kontraktu `OnDecision`.
- 2026-06-25T06:06: Encoding gate dla `scripts/analyze_agents.py` i `tests/test_analyze_agents.py` przeszedł poza sandboxem (`.venv` w sandboxie nadal trafia w WindowsApps/Odmowa dostępu). `load_battle_fixture()` otwiera plik bez wrappera i przy brakującej ścieżce rzuca `FileNotFoundError`.
- 2026-06-25T06:08: `scripts/analyze_agents.py` łapie teraz `(FileNotFoundError, ValueError)` przy ładowaniu fixtury/mapy i przekazuje błąd do `parser.error`; `tests/test_analyze_agents.py` ma regresję `test_cli_rejects_missing_fixture_without_traceback`.
- 2026-06-25T06:16: Targeted pytest: `tests/test_analyze_agents.py` — 19 passed. Pełny pytest fallback: 1912 passed, 1717 warnings. Call-site check: `load_battle_fixture()` używany szeroko bez zmiany sygnatury; wpływ dotyczy wyłącznie błędnej ścieżki CLI w `analyze_agents.main()`. Manual `/simplify`: brak zmian (lokalne `try/except` najprostsze). Manual `/review`: brak findingów; `/security-review` N/A (brak auth/DB/sekretów/user-input→DB). `git diff --check` bez błędów, tylko ostrzeżenia CRLF dla `.gitignore` i tego handoffa.

## W TRAKCIE — 2026-06-25T01:02:28+02:00 — low-severity CLI error handling

**Zakres pracy:** naprawić dwie pozycje z "Backlog drobny" review bez ruszania głównego kontraktu `OnDecision`: `analyze_agents --players <złe>` ma zwracać czytelny błąd argparse zamiast tracebacku, a `analyze_agents --map <nieznana>` ma zostać odrzucone przez walidację argumentów.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload: N/A.
- JS render / CSS / template: N/A.
- CLI/script: `scripts/analyze_agents.py`.
- Testy: `tests/test_analyze_agents.py` regresje dla błędnych argumentów.
- Dokumentacja: ten HANDOFF.

**Performance gate:** brak hot path (`/quote`, `/rosters/{id}`), zero nowych DB queries, zero zmian runtime aplikacji; tylko walidacja argumentów CLI przed symulacją.

**Plan:**
- [x] 1. Potwierdzić istniejący parser CLI i call sites `_parse_players`/`build_map`.
- [x] 2. Przenieść walidację błędnego `--players`/`--map` na ścieżkę `parser.error`.
- [x] 3. Dodać regresje CLI i uruchomić targeted + pełny pytest fallback.
- [x] 4. DoD: call-site check, manual `/simplify`, manual `/review` jeśli diff >50 linii, diff review.

**Otwarte kwestie:** główna decyzja `BLOCKED(user)` z Fazy 1 pozostaje bez zmian; ten slice jej nie rozstrzyga.

**Backlog (low, z review 2026-06-25):** `analyze_agents --fixture <nieistniejący>` — **RESOLVED 2026-06-25T06:08** w slice "fixture CLI error handling"; brakująca fixtura trafia teraz do `parser.error` bez tracebacku.

**Wykonane kroki / odkrycia:**
- 2026-06-25T01:02: Encoding gate dla `scripts/analyze_agents.py` i `tests/test_analyze_agents.py` przeszedł po uruchomieniu `.venv` poza sandboxem (lokalny venv wskazuje na WindowsApps Python blokowany w sandboxie).
- 2026-06-25T01:06: `balance_simulate._parse_players()` już zwraca `argparse.ArgumentTypeError`, a `balance_simulate.build_map()` zwraca `ValueError`; crash wynikał z ręcznego wywołania po `parse_args`, bez konwersji na `parser.error`.
- 2026-06-25T01:11: `scripts/analyze_agents.py` konwertuje złe `--players` i `--map` na `parser.error` (exit 2 + stderr); dodane regresje bez tracebacku. Targeted pytest: `tests/test_analyze_agents.py` — 18 passed.
- 2026-06-25T01:12: Manual `/simplify` usunął zbędny helper i zostawił lokalne `try/except` w `main()`. Re-run po uproszczeniu: `tests/test_analyze_agents.py` — 18 passed; pełny `pytest -x --tb=short -q` — 1911 passed, 1717 warnings.
- 2026-06-25T01:12: Call-site check: `_parse_players()` i `build_map()` w `scripts/analyze_agents.py` są wywoływane tylko w `main()`; wpływ ograniczony do błędnych argumentów CLI, poprawne ścieżki bez zmian. `git diff --check` OK poza standardowym ostrzeżeniem CRLF dla tego handoffa. Manual `/review`: brak findingów; `/security-review` N/A (brak auth, DB, sekretów, user-input→DB).

## Zablokowane pliki / katalogi
- `app/services/agents/match.py` — kontrakt `OnDecision` / miejsce wywołania `on_decision`.
- `scripts/analyze_agents.py` — konsument telemetrii (`action_mix`, `decision_time_ms`).
- (potencjalnie) `tests/test_analyze_agents.py`, `tests/` dot. match — aktualizacja oczekiwań.

## Blokuje / Blokowane przez
- **Blokuje:** —
- **Blokowane przez:** decyzja usera o kierunku (patrz Hipotezy).

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji
*(Oznaczaj kroki wg legendy: `[ ]` TODO, `[~]` rozpoczęto, `[x]` sukces, `[!]` błąd/porzucone.)*

### Faza 1 — Decyzja projektowa
- [x] Krok 1.1: **RESOLVED 2026-06-25 — Opcja A (per-akcja).** Uzasadnienie: pierwsza akcja może być wymuszona statusem → rzeczywiste decyzje agenta w drugiej akcji/przerwaniach. Zakres musi obejmować wszystkie akcje aktywacji.

### Faza 2 — Implementacja (zmiana kontraktu OnDecision)
- [ ] Krok 2.1: Rozszerzyć `match.run_match` — pętla `apply_activation` musi wywoływać `on_decision` dla każdej akcji (index 1..N), nie tylko raz na aktywację. Zmiana: przenieść hook `on_decision` wewnątrz pętli akcji, mierzyć `_elapsed_ms` per akcja.
- [ ] Krok 2.2: Zmienić sygnaturę `OnDecision` callback'a (jeśli potrzeba) — dodać index akcji (opcjonalnie: czy `action_index` lub `total_actions`?).
- [ ] Krok 2.3: Zaktualizować `analyze_agents.py` — agregować zdarzenia per akcja (nie per aktywacja), report aggregate po wszystkich akcjach bota per gra.
- [ ] Krok 2.4: Zaktualizować docstring `OnDecision` (match.py) i nagłówki raportu `analyze_agents` — jasno zaznaczyć zakres „wszystkie akcje aktywacji".

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [ ] `pytest -X utf8 -q tests/test_analyze_agents.py tests/test_agents_*` (+ testy match)
- [ ] Call-site check `on_decision` / `run_match` / `simulate_from_rosters`
- [ ] `/simplify` — przegląd jakości, reuse, dead code
- [ ] `/review` — jeśli diff >50 linii LUB hot path
- [ ] `/security-review` — (nie dotyczy — czysta telemetria obserwacyjna, brak auth/user-input→DB)
- [ ] Re-run `pytest` jeśli `/simplify` lub `/review` coś zmieniły
- [ ] Diff review przed commitem

## Pliki dotknięte
- `scripts/analyze_agents.py` — błędne `--players` i `--map` trafiają w `parser.error` zamiast tracebacku.
- `tests/test_analyze_agents.py` — regresje CLI dla złego gracza, nieznanej mapy i brakującej fixtury.
- `docs/handoffs/HANDOFF_code-review-telemetry-action-scope.md` — bieżący slice i DoD.

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak)

## Hipotezy / pytania otwarte
- ✅ **RESOLVED (2026-06-25 user decision):** Telemetria musi obejmować WSZYSTKIE akcje aktywacji (opcja A). Uzasadnienie: pierwsza akcja może być wymuszona przez status (Przyszpilenie/Wyczerpanie) — rzeczywiste decyzje agenta przychodzą w drugiej akcji lub w przerwaniach. Mierzenie tylko pierwszej akcji zniekształca obraz decyzji. W przyszłości zakres rozszerzy się o przerwania (pkt 11.b.i) i rozstawienie (Faza D5).

  **Implikacja:** `on_decision` musi być wywoływany dla każdej akcji aktywacji (zmiana kontraktu `OnDecision` + pętli w `match.run_match`/`continue_activation`), `elapsed_ms` per akcja. Spójny `action_mix` i `decision_time_ms`; więcej eventów telemetrii (akceptowalny koszt dla dokładności obserwacji).

## Jak zweryfikować
```bash
python -X utf8 -m pytest tests/test_analyze_agents.py -q
# manualnie: uruchom analyze_agents na fixture z botem robiącym Manewr+Ostrzał,
# sprawdź czy action_mix pokazuje obie akcje (opcja A) lub ma caveat (opcja B).
```

## Decyzje
- 2026-06-24: Wątek utworzony przez autonomiczny `/code-review` (Finding 1). Naprawa NIE
  jest „prosta i bezpieczna" (zmiana kontraktu obserwatora / decyzja projektowa) → handoff
  zamiast inline-fix.

## Notatki / odkrycia w trakcie
- 2026-06-24: Pozostałe findingi z review (uncaught traceback na złym `--players`/`--map`,
  cichy drop bota który nigdy nie aktywował) — patrz REVIEW_2026-06-24.md sekcja „Backlog
  drobny". Niska severity, nie blokują; można zgarnąć przy okazji tego wątku.
  **RESOLVED 2026-06-25:** `--players`/`--map`/`--fixture` → `parser.error`; cichy drop
  bota → wiersz zerowy (`aggregate_records` pre-seed); `--initiative` przy `--games>1`
  → non-fatal warning. Cały backlog `READY` domknięty; zostaje tylko Finding 1 `BLOCKED(user)`.
