Sprawdza spójność systemu HANDOFF z aktualnym stanem repo. Uruchom po `git checkout`, `git merge`, `git pull`, lub po ręcznym dotknięciu plików `HANDOFF_*.md` / `HANDOFF.md`. Wykrywa pliki osierocone, wpisy osierocone i niespójności gałęzi.

Wejście: brak argumentów (skill samodzielnie wykrywa stan).

Kroki:
1. Wykonaj `git branch --show-current` — zapamiętaj nazwę aktualnej gałęzi.
2. Wylistuj pliki `docs/handoffs/HANDOFF_*.md` (z wyłączeniem `README.md`). Dla każdego odczytaj sekcję "Gałąź git" → Branch.
3. Przeczytaj tabelę "Aktywne wątki" z `HANDOFF.md` — zbierz slugi z linków.
4. Porównaj trzy zbiory:
   a. **Pliki osierocone** — istnieje `HANDOFF_<slug>.md`, brak wpisu w tabeli HANDOFF.md.
   b. **Wpisy osierocone** — slug w tabeli, brak pliku.
   c. **Branch mismatch** — wątek X deklaruje branch "feature/X", aktualny branch to inny.
5. Dla każdej kategorii niespójności wyświetl listę i zaproponuj fix:

   **Plik osierocony** (`HANDOFF_<slug>.md` bez wpisu):
   - Sugestia: dodać wpis do tabeli `HANDOFF.md` "Aktywne wątki".
   - Zapytaj usera: "Tak / Nie / Pomiń"?
   - Jeśli "Tak" — dopisz wiersz na podstawie metadanych pliku (slug, cel, status).

   **Wpis osierocony** (wiersz w tabeli, brak pliku):
   - Sugestia: prawdopodobnie wątek został zarchiwizowany na innej gałęzi (np. po `git checkout`).
   - Zapytaj usera: "Usunąć wiersz z HANDOFF.md? / Pozostaw / Pomiń?"
   - Jeśli "Usunąć" — usuń wiersz, dopisz krótki wpis do LOG SESJI ("Wpis usunięty przez /handoff-sync — plik nieobecny na gałęzi X").

   **Branch mismatch** (wątek na innej gałęzi niż aktualna):
   - **Nie naprawiaj automatycznie.** Tylko alert: "Wątek X jest oznaczony jako gałąź Y, jesteś na gałęzi Z."
   - Może być celowa zmiana usera — niech zdecyduje.

6. **Nie naprawiaj nic automatycznie bez potwierdzenia usera.** Pokazuj propozycje, czekaj na "Tak"/"Nie" per niespójność.
7. Po naprawie — pokaż `git diff HANDOFF.md` i zachęć do commita (`git commit -am "chore: handoff sync after <reason>"`).

Edge cases:
- Brak `HANDOFF.md` → poinformuj że projekt nie ma jeszcze systemu handoff.
- Brak katalogu `docs/handoffs/` → utwórz pusty + dopisz wpis do LOG SESJI w HANDOFF.md.
- Konflikty git (np. `HANDOFF.md` w stanie merge conflict) → przerwij, poproś o rozwiązanie konfliktu pierwszego.

Typowy scenariusz: po `git checkout feature/X` pliki `HANDOFF_*.md` z gałęzi `main` mogą zniknąć (nie były w tym commicie), `HANDOFF.md` może być wersji z innej gałęzi. Skill wykrywa rozjazd i naprowadza usera.
