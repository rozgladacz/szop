# HANDOFF — code-review-telemetry-action-scope

> **Wątek:** Telemetria ADR-0017 (`analyze_agents`) mierzy `action_mix` i `decision_time_ms` tylko z PIERWSZEJ akcji aktywacji — drugie akcje (kontynuacja do 2 akcji, pkt 11.b.iv) są niewidoczne, a `quality` liczy się dla pełnej aktywacji → niespójny zakres pomiaru.
> **Status:** In progress
> **Utworzony:** 2026-06-24
> **Ostatnia aktualizacja:** 2026-06-24

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
- [ ] Krok 1.1: Rozstrzygnąć kierunek (patrz Hipotezy). Dwie opcje:
  - **A) per-akcja:** `on_decision` woła się dla KAŻDEJ akcji aktywacji (zmiana kontraktu
    `OnDecision` + pętli w `run_match`/`continue_activation`); `elapsed_ms` per akcja.
    Spójny `action_mix` i czas; więcej eventów telemetrii.
  - **B) jawne ograniczenie:** zostawić single-fire, ale w raporcie `analyze_agents`
    nazwać kolumnę „miks PIERWSZYCH akcji" + caveat, żeby nie mylić z pełnym obrazem.
    Tańsze, ale `quality` nadal w innym zakresie niż `action_mix`.

### Faza 2 — Implementacja wybranej opcji
- [ ] Krok 2.1: <zależne od decyzji>
- [ ] Krok 2.2: Zaktualizować docstring kontraktu `OnDecision` (match.py) i nagłówki raportu.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [ ] `pytest -X utf8 -q tests/test_analyze_agents.py tests/test_agents_*` (+ testy match)
- [ ] Call-site check `on_decision` / `run_match` / `simulate_from_rosters`
- [ ] `/simplify` — przegląd jakości, reuse, dead code
- [ ] `/review` — jeśli diff >50 linii LUB hot path
- [ ] `/security-review` — (nie dotyczy — czysta telemetria obserwacyjna, brak auth/user-input→DB)
- [ ] Re-run `pytest` jeśli `/simplify` lub `/review` coś zmieniły
- [ ] Diff review przed commitem

## Pliki dotknięte
- (jeszcze żadne — wątek dopiero zarejestrowany przez code-review)

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak)

## Hipotezy / pytania otwarte
- `BLOCKED(user)`: Czy telemetria ma obejmować WSZYSTKIE akcje aktywacji (opcja A), czy
  pozostać single-fire z jawnym caveatem w raporcie (opcja B)? Brakująca decyzja: koszt
  rozszerzenia kontraktu vs. wystarczalność „pierwsza akcja" jako proxy decyzji bota.

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
