Przegląd wszystkich aktywnych wątków HANDOFF. Wyświetla tabelę z każdym wątkiem (slug, cel, status, ostatnia modyfikacja) oraz wykrywa niespójności między plikami i tabelą w `HANDOFF.md`.

Wejście: brak argumentów.

Kroki:
1. Przeczytaj `HANDOFF.md`:
   - Sekcję "Aktywne wątki" (tabela)
   - Sekcję "Zasoby zablokowane" (tabela)
2. Wylistuj wszystkie pliki `docs/handoffs/HANDOFF_*.md` (z wyłączeniem `README.md`).
3. Dla każdego pliku odczytaj:
   - Slug (z nazwy pliku)
   - Pierwszy `> **Wątek:**` (cel)
   - Status (z linii `> **Status:**`)
   - Ostatnia modyfikacja (mtime pliku, lub linia `> **Ostatnia aktualizacja:**`)
   - **Progres kroków** w sekcji "Plan implementacji": zlicz wystąpienia `[ ]`, `[~]`, `[x]`, `[!]`. Format prezentacji: `5[x] / 1[~] / 2[ ] / 1[!]` (pominąć zerowe).
4. Sprawdź spójność:
   - **Pliki osierocone:** istnieje `HANDOFF_<slug>.md`, brak wpisu w tabeli "Aktywne wątki".
   - **Wpisy osierocone:** wiersz w tabeli, brak pliku.
   - **Kroki "rozpoczęto" bez aktywności:** `[~]` w pliku, którego mtime > 48h temu — sygnał, że ktoś zaczął i porzucił. Sugeruj userowi zmianę na `[!]` z notą lub kontynuację.
5. Wyświetl userowi:

   ```
   ## Aktywne wątki HANDOFF

   | Slug | Cel | Status | Progres | Ost. zmiana | Spójność |
   |---|---|---|---|---|---|
   | refactor-agents-md | Podział AGENTS.md... | In progress | 5[x] / 1[~] / 2[ ] | 2026-05-20 | OK |
   | ... | ... | ... | ... | ... | OK |

   Legenda: [ ] TODO, [~] rozpoczęto, [x] sukces, [!] porzucone

   ## Niespójności
   - (jeśli brak: "Spójność OK")
   - (jeśli są: lista — typ niespójności + sugestia fix)

   ## Zablokowane zasoby (skrót)
   - <plik> ← <wątek>
   - ...
   ```

6. Jeśli są niespójności — zaproponuj `/handoff-sync` do naprawy.
7. Pokaż liczbę aktywnych wątków na końcu (`Łącznie: N aktywnych`).
8. NIE rób zmian w plikach — to tylko raport.
