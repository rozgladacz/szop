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
4. **Sprawdź czy zmiana wymaga aktualizacji bazy wiedzy.** Wątek mógł wprowadzić nowy pakiet, nową konwencję, nowy submoduł, ADR, ENV var, feature toggle, hot path, czy zmianę roadmapy. To są zmiany "stabilne" które powinny być **w `docs/`**, nie tylko w LOG SESJI (LOG jest archiwalny, `docs/` jest aktywną bazą wiedzy).

   Przeczytaj **w skrócie** (nagłówki / sekcje wstępu, nie pełna treść):
   - `AGENTS.md` — czy "Where to find what" index pasuje? Czy nowy pakiet/konwencja zasługuje na wpis?
   - `docs/overview.md` — czy struktura katalogów lub stack jest aktualny?
   - `docs/architecture.md` — czy mapa submodułów jest kompletna? Czy nowy pakiet/silnik/dispatcher jest udokumentowany?
   - `docs/roadmap.md` — czy checkboxy zaplanowanych zadań są oznaczone `[x]`? Czy ADR index ma poprawne statusy?
   - `docs/README.md` — czy lista plików/podkatalogów jest aktualna (nowe ADRy → adr/, nowe doc files)?
   - `docs/developing.md`, `docs/testing.md`, `docs/PERFORMANCE.md` — czy konwencje / komendy / baseline były zaktualizowane podczas wątku?

   Dla każdej rozbieżności:
   - Wypisz userowi listę propozycji (`<plik>:<sekcja>` — co dopisać/zmienić, jednym zdaniem).
   - Zaproponuj że to **dorzucisz** do tego samego commita archiwizacyjnego — lub do osobnego, jeśli zakres > 50 linii diff.
   - Jeśli user odmawia / mówi "nic nie trzeba" — odnotuj w LOG entry (`Doc updates: brak/N/A`) i przejdź dalej.

   **Heurystyki kiedy aktualizacja jest prawdopodobna:**
   - Wątek dodał `NEW` pakiet w `app/services/` → mapa submodułów w `architecture.md`.
   - Wątek dodał ENV var / feature toggle → wzmianka w `architecture.md` + `overview.md`.
   - Wątek dodał ADR-0XXX → status `—` w `roadmap.md → ADR index` powinien zostać `✓`.
   - Wątek dodał nową komendę `make X` / `pytest -m X` / hot path → odpowiednio `testing.md` / `PERFORMANCE.md`.
   - Wątek był z roadmap (faza A/B/C/D) → checkboxy w `roadmap.md` od `[ ]` do `[x]`.
   - Wątek zmienił konwencję kodu / nazewnictwo / strukturę plików → `developing.md`.

5. Otwórz `HANDOFF.md`:
   a. Usuń wiersz wątku z tabeli "Aktywne wątki".
   b. Usuń odpowiednie wiersze z tabeli "Zasoby zablokowane" (te, gdzie kolumna "Wątek blokujący" = ten slug).
   c. Dodaj wpis do LOG SESJI **na górze sekcji** (najnowsze pierwsze):
      ```
      ### YYYY-MM-DD — <slug> (archived)
      - <1-2 zdania podsumowania celu i wyniku>
      - Pliki: <kluczowe pliki dotknięte>
      - Weryfikacja: <stan>
      - Doc updates: <co zaktualizowane w `docs/` z kroku 4, lub "brak/N/A">
      ```
6. Pokaż userowi diff `HANDOFF.md` + dowolne zmiany w `docs/`/`AGENTS.md` przed dalszym krokiem.
7. Po potwierdzeniu — usuń `docs/handoffs/HANDOFF_<slug>.md` (`git rm` jeśli pod kontrolą git, inaczej `rm`).
8. NIE commituj samodzielnie — czekaj na potwierdzenie usera, że chce commit.

Edge cases:
- Plik nie istnieje → zatrzymaj się, zapytaj o właściwy slug.
- Wpis w tabeli HANDOFF.md istnieje, ale brak pliku `HANDOFF_<slug>.md` → tylko usuń wiersz z tabeli i dopisz wpis do LOG ("zarchiwizowany — plik nieistniejący"). Zasugeruj `/handoff-sync` aby zweryfikować spójność.
- Plik istnieje, ale brak wpisu w tabeli HANDOFF.md → tylko usuń plik i dopisz do LOG. Zasugeruj `/handoff-sync`.
- Krok 4 "sprawdź bazę wiedzy" wykrył >5 rozbieżności → zasugeruj że to **osobny wątek** typu `docs-sync-<slug>` (`/handoff-start docs-sync-<slug>`) zamiast wpychać 200 linii doc changes do commita archiwizacyjnego.
