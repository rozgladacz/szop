# AGENTS.md

> Manifest dla agentów AI. Trzymaj krótko — szczegóły w `docs/`. Wszystkie pliki dokumentacji indeksowane w [docs/README.md](docs/README.md).

## Where to find what (1-line index)

| Temat | Plik |
|---|---|
| Cel projektu, obszary, stack | [docs/overview.md](docs/overview.md) |
| Architektura, model danych, mapa submodułów `costs/` | [docs/architecture.md](docs/architecture.md) |
| Roadmapa, aktywne inicjatywy | [docs/roadmap.md](docs/roadmap.md) |
| Jak planować zadanie (Layer Checklist, performance gate) | [docs/planning.md](docs/planning.md) |
| Konwencje kodu, INCH, string handling, ekstrakcja submodułów | [docs/developing.md](docs/developing.md) |
| Testy — pytest, smoke test JS, payload parity | [docs/testing.md](docs/testing.md) |
| Git workflow, destructive commands | [docs/git-workflow.md](docs/git-workflow.md) |
| Struktura `app.js`, łańcuch DOMContentLoaded | [docs/app-js-guide.md](docs/app-js-guide.md) |
| Baseline wydajności | [docs/PERFORMANCE.md](docs/PERFORMANCE.md) |
| Aktywne wątki + zablokowane zasoby | [HANDOFF.md](HANDOFF.md) |
| Per-wątek (kontekst pracy) | [docs/handoffs/](docs/handoffs/) |

## [CRITICAL] — nigdy nie łamać

1. **HANDOFF protocol.** Przed pierwszą edycją: przeczytaj [HANDOFF.md](HANDOFF.md) → znajdź swój wątek w `docs/handoffs/HANDOFF_*.md` → jeśli brak, utwórz przez `/handoff-start <slug>`. Aktualizuj `HANDOFF_<slug>.md` **przed** każdym podetapem, nie po. Bez tego utracisz kontekst.
2. **Pytest po każdej zmianie kodu** — nawet jednolinijkowej. PostToolUse hook to wymusza; nie suppressuj jego output. Nigdy nie deklaruj "gotowe" bez `pytest -q`. Detale: [docs/testing.md](docs/testing.md).
3. **SSOT — nigdy nie replikuj logiki kosztów/klasyfikacji inline.** `grep` istniejące funkcje (`_classification_map`, `roster_unit_role_totals`, `calculate_roster_unit_quote`) i wywołaj je. Detale: [docs/architecture.md](docs/architecture.md).
4. **String delimiters straight ASCII** — nigdy U+201C/D jako delimiter Pythona. `INCH` (U+201D) to *dane*, nie składnia. Encoding gate przed Edit/Write na `.py`. Detale: [docs/developing.md](docs/developing.md).
5. **Baza w preview = produkcyjna.** `data/szop.db` z danymi. Pusta baza dyskwalifikuje preview do akceptacji. Wersja w git jest źródłem prawdy.
6. **Stop-and-revert** — gdy user mówi "nie", "wrong", "cofnij" — zatrzymaj się, **odwróć ostatnią zmianę**, zapytaj o uściślenie.
7. **Destructive git** — przed `reset --hard` / `push --force` / `checkout .` wypisz `git remote -v` i `git branch`. Potwierdź repo (OPR vs OPR_Prod). Detale: [docs/git-workflow.md](docs/git-workflow.md).

## [REQUIRED] — procedury obowiązkowe

1. **Layer Checklist przed implementacją** — wymień warstwy dotknięte (data model / backend payload / JS render / CSS / tests). Detale: [docs/planning.md](docs/planning.md).
2. **Performance gate dla hot path** (`/quote`, `/rosters/{id}`) — N extra queries? indeksy? fast-path? Detale: [docs/planning.md](docs/planning.md).
3. **Call-site search przed zamknięciem** — znajdź wszystkie call sites zmienionej funkcji, wyjaśnij wpływ na każdy.
4. **Smoke test po zmianie `app.js`** — `make dev` + ręcznie: Zbrojownia / Edytor Armii / Rozpiski. Backend testy nie pokrywają inicjalizacji JS. Detale: [docs/testing.md](docs/testing.md).
5. **Encoding gate przed Edit/Write na `.py`** — zweryfikuj `open(file, encoding='utf-8')` succeeds. Abort jeśli błąd.
6. **Frontend payload parity** — po zmianie w `rosters.py`, `export.py`, `payload_adapters.js`, lub `costs/*` uruchom `tests/test_frontend_*.py`.

## [RECOMMENDED] — preferencje

- Najpierw czytaj kod, potem edytuj. Czytaj pliki batchami (parallel).
- Małe odwracalne zmiany. Bez "okazyjnych" refaktorów.
- Plan dla zadań wieloetapowych (sekcja "Plan implementacji" w `HANDOFF_<slug>.md`), minimalny patch dla prostych.
- Dziedziczenie: wariant trzyma tylko różnice; stabilne identyfikatory.
- Komentarze sekcji w monolitach (`app.js`, `_engine.py`, `rosters.py`) — czytaj jak mapę. Detale: [docs/developing.md](docs/developing.md).
- Jeśli wymaganie niejasne — wypisz założenia i braki, zapytaj.

## Top 5 najczęstszych błędów (z FRICTION_REPORT.md)

1. **Regresje przez brak Layer Check** (42 hits) → checklist w [docs/planning.md](docs/planning.md).
2. **Utrata kontekstu między sesjami** (41 hits) → HANDOFF protocol, [CRITICAL] #1.
3. **Smart-quotes jako delimiter Pythona** (32 hits) → `INCH` constant, [docs/developing.md](docs/developing.md).
4. **Niejednoznaczność repo przy git destructive** (14 hits) → `git remote -v` + `git branch`.
5. **Tests skipped before "done"** (11 hits) → `pytest -q`, [CRITICAL] #2.

## Komendy

- Install: `python -m venv .venv && pip install -r requirements-dev.txt`
- Run: `make dev`
- Test: `make test` (pełna), `make test-fast` (szybka)
- Lint: `make lint`
- Windows fallback (gdy `make` poza PATH): `python -m pytest -x --tb=short -q`

## Workflow oczekiwany

1. `/load-context` (lub ręcznie: AGENTS.md → HANDOFF.md → swój HANDOFF_`<slug>`.md).
2. Wskaż pliki do edycji + Layer Checklist (data model / backend / JS / CSS / tests).
3. Aktualizuj `HANDOFF_<slug>.md` **przed** podetapem (odznacz checklisty, dopisz odkrycia).
4. Po zmianie: pytest → call-site check → smoke test jeśli JS → podsumowanie.
5. Zamykasz wątek? `/handoff-archive <slug>`.

Po zmianie podaj userowi: **co zmieniono**, **jak zweryfikowano**, **co wymaga decyzji**.
