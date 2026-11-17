# AGENTS.md

> Manifest dla agentów AI. Trzymaj krótko — szczegóły w `docs/`. Wszystkie pliki dokumentacji indeksowane w [docs/README.md](docs/README.md).

## Where to find what (1-line index)

| Temat | Plik |
|---|---|
| Cel projektu, obszary, stack | [docs/overview.md](docs/overview.md) |
| Architektura, model danych, mapa submodułów `costs/` + `rulesets/` (YAML backend), feature toggle | [docs/architecture.md](docs/architecture.md) |
| Decyzje architektoniczne (ADR) | [docs/adr/](docs/adr/) (index w [docs/roadmap.md](docs/roadmap.md#adr-index)) |
| Roadmapa, aktywne inicjatywy | [docs/roadmap.md](docs/roadmap.md) |
| Jak planować zadanie (Layer Checklist, performance gate) | [docs/planning.md](docs/planning.md) |
| Konwencje kodu, INCH, string handling, ekstrakcja submodułów | [docs/developing.md](docs/developing.md) |
| Testy — pytest, smoke test JS, payload parity | [docs/testing.md](docs/testing.md) |
| Git workflow, destructive commands | [docs/git-workflow.md](docs/git-workflow.md) |
| Struktura `app.js`, łańcuch DOMContentLoaded | [docs/app-js-guide.md](docs/app-js-guide.md) |
| Baseline wydajności | [docs/PERFORMANCE.md](docs/PERFORMANCE.md) |
| Historyczne aktywne wątki + decyzje | [HANDOFF.md](HANDOFF.md) — protokół wstrzymany od 2026-07-14 |
| Historyczny kontekst per-wątek | [docs/handoffs/](docs/handoffs/) — czytaj tylko gdy jest istotny dla zleconego celu |
| Skille operacyjne (kanon, agent-niezależny) | [.agents/skills/](.agents/skills/) |

## Skille operacyjne — kanon agent-niezależny

Treść skilli (`load-context`, `handoff-start/status/sync/archive`, `reflect-and-improve`) żyje **wyłącznie** w `.agents/skills/<name>/SKILL.md` — ogólne, agent-niezależne procedury (jedyne źródło prawdy). Katalogi konkretnych agentów trzymają tylko cienkie **stuby** wskazujące na kanon: `.claude/skills/<name>/SKILL.md` (Claude Code wymaga pliku do rejestracji slash-command + opisu do triggerowania); inne agenty (`.codex/` itp.) czytają kanon wprost lub dodają własne stuby wg potrzeby. **Edytuj procedurę w `.agents/skills/`; nie duplikuj jej do stubów.**

## Koordynacja pracy — obowiązuje od 2026-07-14

- **Pełny protokół HANDOFF jest wstrzymany.** Nie twórz, nie aktualizuj ani nie archiwizuj `HANDOFF_<slug>.md` w zwykłym toku pracy. Istniejące pliki są historycznym źródłem decyzji; czytaj tylko wskazany plik, gdy jest potrzebny do zleconego celu lub gdy user o niego poprosi.
- Wątek koordynacyjny Codex wybiera jeden etap pracy. Każdy etap musi mieć: zakres, warunek zakończenia, ograniczenia oraz komendy/artfakty weryfikujące.
- Zadanie automatyczne lub `/goal` tworzy się tylko dla tak zdefiniowanego etapu. Automatyczny koordynator może samodzielnie wybrać wyłącznie otwarty etap jawnie oznaczony `[automation-ready]` w `docs/roadmap.md`; pełna procedura i stan trwały są wyłącznie w `.agents/skills/roadmap-coordinator/SKILL.md`.
- Po zamknięciu etapu wróć do wątku koordynacyjnego z wynikiem, weryfikacją i decyzjami potrzebnymi do wyboru następnego etapu.
- Każdy zamknięty etap ma umożliwiać kontynuację na innym komputerze. Zapisz wynik, testy, ograniczenia i zależności w dokumentacji etapu oraz roadmapie, utwórz osobny commit na `Faza_A` i potwierdź jego obecność na `origin/Faza_A`. Uwzględnij osobno dane wymagające backupu. Nie opieraj przekazania wyłącznie na lokalnym stanie czatu lub plikach ignorowanych przez Git.

## [CRITICAL] — nigdy nie łamać

1. **Cel etapu.** Przed pierwszą edycją potwierdź cel i Definition of Done z bieżącej rozmowy albo promptu zadania automatycznego. HANDOFF nie jest obowiązkowym bootstrapem; sprawdź go tylko, jeśli ma relewantną decyzję historyczną.
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
7. **Definition of Done przed archiwizacją** — po testach uruchom `/simplify` (zawsze) + warunkowo `/review` (diff >50 linii / hot path / SSOT) + warunkowo `/security-review` (auth, user input → DB). Re-run `pytest` jeśli któryś coś zmienił. Detale: [docs/planning.md](docs/planning.md) sekcja "Definition of Done".
8. **Rules-claims z źródła, nie z pamięci/ADR.** Każde stwierdzenie o regułach gry (punkty przerwań, numery `pkt X`, formuły, enumy mechanik) cytuje konkretny `pkt` i jest odczytane z `app/static/docs/SZOP_*.md` **w tej sesji**. Nigdy z ADR ani pamięci — ADR bywa nieaktualny po driftcie reguł (np. ADR-0015 modelował 4 punkty przerwań vs 2 przed-akcyjne w aktualnym pkt 11.b). Jeśli ADR ≠ źródło → flaguj drift, nie powielaj ADR.

## [RECOMMENDED] — preferencje

- Najpierw czytaj kod, potem edytuj. Czytaj pliki batchami (parallel).
- Małe odwracalne zmiany. Bez "okazyjnych" refaktorów.
- Plan dla zadań wieloetapowych w bieżącej rozmowie lub definicji `/goal`; minimalny patch dla prostych.
- Dziedziczenie: wariant trzyma tylko różnice; stabilne identyfikatory.
- Komentarze sekcji w monolitach (`app.js`, `_engine.py`, `rosters.py`) — czytaj jak mapę. Detale: [docs/developing.md](docs/developing.md).
- Jeśli wymaganie niejasne — wypisz założenia i braki, zapytaj.

## Top 5 najczęstszych błędów (z FRICTION_REPORT.md)

1. **Regresje przez brak Layer Check** (42 hits) → checklist w [docs/planning.md](docs/planning.md).
2. **Utrata kontekstu między sesjami** (41 hits) → cel etapu z Definition of Done + trwała dokumentacja, [CRITICAL] #1.
3. **Smart-quotes jako delimiter Pythona** (32 hits) → `INCH` constant, [docs/developing.md](docs/developing.md).
4. **Niejednoznaczność repo przy git destructive** (14 hits) → `git remote -v` + `git branch`.
5. **Tests skipped before "done"** (11 hits) → `pytest -q`, [CRITICAL] #2.

## Komendy

- Install: `python -m venv .venv && pip install -r requirements-dev.txt`
- Run: `make dev`
- Test: `make test` (pełna), `make test-fast` (szybka)
- Lint: `make lint`
- Profile cost engine: `make profile ROSTER=10 BACKEND=procedural|yaml|both_assert`
- **A4 drift pipeline**: `make rules-check` (orchestrator 5 skryptów: sources-check + extract DOCX + extract MD + classify geometry + drift). Subcele selektywne: `rules-extract`, `rules-extract-md`, `rules-drift`, `rules-classify`, `rules-sources-check`. Detale: [scripts/README.md](scripts/README.md) + [docs/adr/0006-pipeline-drift.md](docs/adr/0006-pipeline-drift.md).
- Windows fallback (gdy `make` poza PATH): `python -X utf8 -m pytest -x --tb=short -q` / `python -X utf8 scripts/rules_*.py`. **Flaga `-X utf8` wymagana** — w trybie nieinterakcyjnym stdout=cp1250 → `UnicodeEncodeError` na polskich znakach (detale: [docs/testing.md](docs/testing.md#środowisko-i-uruchamianie-windows--agenci)).

## Workflow oczekiwany

1. Odczytaj `AGENTS.md`, zlecony cel etapu i tylko potrzebne pliki kodu/dokumentacji. HISTORYCZNY HANDOFF czytaj warunkowo.
2. Wskaż pliki do edycji + Layer Checklist (data model / backend / JS / CSS / tests).
3. Dla etapu wielokrokowego trzymaj krótki plan i status w bieżącej rozmowie lub `/goal`; nie zapisuj ich do HANDOFF.
4. Po zmianie — Definition of Done: pytest → call-site check → smoke jeśli JS → `/simplify` → warunkowo `/review` / `/security-review` → re-run pytest jeśli simplify coś zmienił → diff review.
5. Po osiągnięciu warunku zakończenia zdaj relację do wątku koordynacyjnego. Nie przechodź automatycznie do kolejnego etapu.

Po zmianie podaj userowi: **co zmieniono**, **jak zweryfikowano**, **co wymaga decyzji**.
