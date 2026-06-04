Archiwizuje zakończony wątek HANDOFF. Po uruchomieniu plik `docs/handoffs/HANDOFF_<slug>.md` znika, w `HANDOFF.md` znika wiersz z tabel "Aktywne wątki" i "Zasoby zablokowane", a do LOG SESJI trafia 1-2 zdania podsumowania.

Wejście:
- Opcjonalny argument: slug wątku do zarchiwizowania.

Kroki:
1. Jeśli user nie podał sluga:
   - Wylistuj wszystkie pliki `docs/handoffs/HANDOFF_*.md`.
   - Pokaż ich slug, cel, status, ostatnią modyfikację.
   - Zapytaj usera który zarchiwizować.
2. Przeczytaj `docs/handoffs/HANDOFF_<slug>.md`. Wyciągnij:
   - Cel (z sekcji "Wątek" i "Cel")
   - Kluczowe ustalenia (z sekcji "Decyzje" i "Notatki / odkrycia w trakcie")
   - Status weryfikacji (z sekcji "Plan implementacji" — Faza N: Weryfikacja end-to-end)
   - Pliki dotknięte (skrót)
3. Sprawdź stany kroków w "Plan implementacji":
   - Stany finalne: `[x]` (sukces) lub `[!]` (błąd/porzucone) — krok zamknięty.
   - Stany aktywne: `[ ]` (TODO) lub `[~]` (rozpoczęto) — krok niezamknięty.
   - Jeśli są kroki w stanie aktywnym — pokaż userowi listę z numeracją (faza + treść kroku) i zapytaj czy mimo to archiwizować. Sugerowana akcja: oznacz porzucone jako `[!]` z notą w "Notatki / odkrycia" zamiast cichego pomijania.
3a. Sprawdź sekcję "Faza N — Weryfikacja end-to-end (Definition of Done)":
   - Czy odznaczone: `pytest -q`, `/simplify`?
   - Czy `/review` / `/security-review` wykonane jeśli wymagane (diff >50 linii / hot path / SSOT / auth)?
   - Jeśli brak któregokolwiek — przypomnij userowi, zapytaj czy archiwizować mimo to. Detale: `docs/planning.md` sekcja "Definition of Done".
4. Otwórz `HANDOFF.md`:
   a. Usuń wiersz wątku z tabeli "Aktywne wątki".
   b. Usuń odpowiednie wiersze z tabeli "Zasoby zablokowane" (te, gdzie kolumna "Wątek blokujący" = ten slug).
   c. Dodaj wpis do LOG SESJI **na górze sekcji** (najnowsze pierwsze):
      ```
      ### YYYY-MM-DD — <slug> (archived)
      - <1-2 zdania podsumowania celu i wyniku>
      - Pliki: <kluczowe pliki dotknięte>
      - Weryfikacja: <stan>
      ```
5. Pokaż userowi diff `HANDOFF.md` przed dalszym krokiem.
6. Po potwierdzeniu — usuń `docs/handoffs/HANDOFF_<slug>.md` (`git rm` jeśli pod kontrolą git, inaczej `rm`).
7. NIE commituj samodzielnie — czekaj na potwierdzenie usera, że chce commit.

Edge cases:
- Plik nie istnieje → zatrzymaj się, zapytaj o właściwy slug.
- Wpis w tabeli HANDOFF.md istnieje, ale brak pliku `HANDOFF_<slug>.md` → tylko usuń wiersz z tabeli i dopisz wpis do LOG ("zarchiwizowany — plik nieistniejący"). Zasugeruj `/handoff-sync` aby zweryfikować spójność.
- Plik istnieje, ale brak wpisu w tabeli HANDOFF.md → tylko usuń plik i dopisz do LOG. Zasugeruj `/handoff-sync`.
