Tworzy nowy wątek HANDOFF dla konkretnego zadania. Po uruchomieniu istnieje plik `docs/handoffs/HANDOFF_<slug>.md` oraz wpis w tabeli "Aktywne wątki" w głównym `HANDOFF.md`.

Wejście:
- Opcjonalny argument: slug w kebab-case (np. `refactor-agents-md`, `ssot-phase-5`).
- Opcjonalny argument: 1-zdaniowy cel.

Kroki:
1. Jeśli user nie podał sluga — zapytaj. Zasada nazewnictwa: kebab-case, max 4 słowa, opisowy. Bez dat/numerów. Detale: `docs/handoffs/README.md`.
2. Jeśli user nie podał celu — zapytaj o 1-zdaniowy opis.
3. Sprawdź czy `docs/handoffs/HANDOFF_<slug>.md` już istnieje. Jeśli tak — zatrzymaj się i zapytaj usera czy nadpisać czy wybrać inny slug.
4. Utwórz `docs/handoffs/HANDOFF_<slug>.md` z szablonu opisanego w `docs/handoffs/README.md`. Wypełnij:
   - `<slug>` w nagłówku
   - `<jedno zdanie celu>` w sekcji "Wątek"
   - Status: "In progress"
   - Utworzony: dzisiejsza data (YYYY-MM-DD)
   - Ostatnia aktualizacja: dzisiejsza data
   - Sekcję "Gałąź git" — uruchom `git branch --show-current` i wypełnij Branch; Base zostaw jako `main` lub zapytaj usera.
   - Pozostałe sekcje (Cel, Plan implementacji, Pliki dotknięte, ...) — szablonowe placeholdery do wypełnienia przez usera/agenta w trakcie pracy.
   - **Faza N — Weryfikacja end-to-end:** szablon zawiera już Definition of Done (`pytest`, `/simplify`, warunkowo `/review` i `/security-review`). NIE usuwaj tych kroków; ewentualnie zaznacz `[!]` z notą "nie dotyczy — <powód>" gdy dany krok jest na pewno nierelevantny dla tego wątku.
5. Otwórz `HANDOFF.md`. Dodaj wiersz do tabeli "Aktywne wątki":
   - Link: `[HANDOFF_<slug>](docs/handoffs/HANDOFF_<slug>.md)`
   - Cel: 1 zdanie (jak w pliku)
   - Pliki zablokowane: "(do wypełnienia)" — user dopisze po wskazaniu plików do edycji
   - Status: "In progress"
6. Pokaż userowi:
   - Ścieżkę do nowego pliku.
   - Przypomnienie: wypełnij sekcję "Cel" (2-3 zdania), "Plan implementacji" (fazy), "Zablokowane pliki" (po wskazaniu plików do edycji).
   - Sugestia: zaktualizuj tabelę "Zasoby zablokowane" w HANDOFF.md po wskazaniu plików.
7. NIE rób żadnej zmiany w kodzie aplikacji. To tylko bootstrap wątku.
