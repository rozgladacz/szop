# docs/handoffs/

Katalog z plikami HANDOFF per wątek pracy. Każdy aktywny wątek ma swój `HANDOFF_<slug>.md`. Po archiwizacji wątku plik znika, a 1-2 zdania podsumowania trafiają do LOG SESJI w głównym `HANDOFF.md`.

## Po co to istnieje

Jedna sekcja "BIEŻĄCE ZADANIE" w głównym HANDOFF.md nie wystarcza, gdy praca idzie kilkoma wątkami równolegle (np. SSOT initiative + refaktor app.js + merge conflicts). Per-wątek plik HANDOFF_X.md:

- Trzyma **pełen plan implementacji** (z fazami i checklistą) — drugi agent może przejąć wątek.
- Pozwala oznaczyć **zablokowane pliki** — uniknięcie konfliktu między wątkami.
- Pozwala śledzić **decyzje i odkrycia** w trakcie pracy.

## Workflow

1. **Start wątku:** `/handoff-start <slug>` (lub ręcznie skopiuj szablon poniżej). Skill utworzy plik i dopisze do tabeli "Aktywne wątki" w głównym HANDOFF.md.
2. **W trakcie pracy:** aktualizuj `HANDOFF_<slug>.md` *przed* każdym podetapem — kontekst okna może się skończyć, zapis końcowy może nigdy nie nastąpić. Odznaczaj kroki `[x]`, dopisuj odkrycia w sekcji "Notatki / odkrycia".
3. **Po `git checkout/merge/pull`:** `/handoff-sync` — wykrywa pliki osierocone i wpisy osierocone w HANDOFF.md.
4. **Archiwizacja:** `/handoff-archive <slug>` — dopisuje wpis do LOG SESJI, usuwa `HANDOFF_<slug>.md`, czyści tabele w HANDOFF.md.

## Konwencja nazw

`HANDOFF_<short-slug>.md` gdzie `<short-slug>`:
- kebab-case (małe litery, myślniki),
- max 4 słowa, opisowy,
- nie ma dat ani numerów porządkowych.

Przykłady **dobre**: `HANDOFF_refactor-agents-md`, `HANDOFF_ssot-phase-5`, `HANDOFF_klasyfikacja-merge`, `HANDOFF_perf-quote-cache`.

Przykłady **złe**: `HANDOFF_001`, `HANDOFF_2026-05-20`, `HANDOFF_thing`, `HANDOFF_super-long-description-of-everything-we-want-to-do`.

## Szablon

Kopiuj poniższy blok przy ręcznym tworzeniu wątku (skill `/handoff-start` robi to za ciebie):

```markdown
# HANDOFF — <slug>

> **Wątek:** <jedno zdanie celu>
> **Status:** In progress / Blocked / Ready for archive
> **Utworzony:** YYYY-MM-DD
> **Ostatnia aktualizacja:** YYYY-MM-DD

## Cel
<2-3 zdania: co ma być osiągnięte, dlaczego>

## Zablokowane pliki / katalogi
- `path/to/file.py` — <powód>
- `path/to/dir/` — <powód>

## Blokuje / Blokowane przez
- **Blokuje:** <nazwy innych wątków>
- **Blokowane przez:** <nazwy innych wątków, jeśli któreś>

## Gałąź git
- **Branch:** `<nazwa-gałęzi>` (lub `main` jeśli wątek na głównej)
- **Base:** `<nazwa-bazy>` (zwykle `main`)

## Plan implementacji
*(Edytowalny w trakcie pracy. Drugi agent czyta to żeby przejąć wątek. Odznaczaj zrobione kroki [x]. Dopisuj odkrycia poniżej fazy.)*

### Faza 1 — <nazwa fazy>
- [ ] Krok 1.1: <opis>
- [ ] Krok 1.2: <opis>

### Faza 2 — <nazwa fazy>
- [ ] Krok 2.1: <opis>

### Faza N — Weryfikacja end-to-end
- [ ] `pytest -q` (lub konkretne testy)
- [ ] Smoke test JS (jeśli dotyczy `app.js`)
- [ ] Call-site check dla zmienionych funkcji
- [ ] Diff review

## Pliki dotknięte
- `path/...` — <co zrobione>

## Hipotezy / pytania otwarte
- ...

## Jak zweryfikować
\`\`\`bash
make test
# konkretne testy
# smoke manualny — co kliknąć
\`\`\`

## Decyzje
- YYYY-MM-DD: <decyzja> — uzasadnienie

## Notatki / odkrycia w trakcie
*(Append-only log podczas pracy. Inny agent czyta to żeby zrozumieć co odkryliśmy w trakcie.)*
- YYYY-MM-DD: <obserwacja>
```

## Co NIE trafia do HANDOFF_X.md

- **Wiedza wolnozmienna** (mapa submodułów, architektura, konwencje kodu) → `docs/architecture.md`, `docs/developing.md` itd.
- **Invarianty obowiązujące wszystkich** ([CRITICAL] rules) → `AGENTS.md`.
- **Notatki cross-wątkowe** (alerty istotne dla kilku wątków równocześnie) → sekcja "Szybkozmienne notatki" w głównym `HANDOFF.md`.

HANDOFF_X.md to **tylko** kontekst konkretnego, zamkniętego zakresu pracy.
