Bootstrap sesji — załaduj cały kontekst projektu w odpowiedniej kolejności. Pierwszy odruch po `claude` w terminalu lub po `/clear`.

Wejście:
- Opcjonalny argument: slug wątku nad którym pracujesz.

Kroki:
1. Przeczytaj `AGENTS.md` w całości — to manifest invariantów `[CRITICAL]/[REQUIRED]/[RECOMMENDED]` i indeks linków do `docs/`.
2. Przeczytaj `HANDOFF.md` w całości — aktywne wątki, zablokowane zasoby, szybkozmienne notatki cross-wątkowe, LOG SESJI.
3. Określ wątek:
   - Jeśli user podał slug jako argument → użyj go.
   - Jeśli nie podał, ale `HANDOFF.md` ma dokładnie jeden aktywny wątek → użyj go (powiadom usera).
   - Jeśli aktywnych wątków > 1 → wylistuj je i zapytaj usera, nad którym pracujemy. Jeśli user chce zacząć nowy → poinformuj o `/handoff-start <slug>`.
   - Jeśli brak aktywnych wątków → poinformuj usera i zapytaj czy chce uruchomić `/handoff-start`.
4. Przeczytaj `docs/handoffs/HANDOFF_<slug>.md` w całości:
   - Cel
   - Zablokowane pliki
   - Plan implementacji (które kroki odznaczone, które otwarte)
   - Decyzje
   - Notatki / odkrycia w trakcie
5. Przeczytaj **nagłówki** plików wymienionych w sekcji "Pliki dotknięte" (tylko pierwsze ~30 linii każdego, nie pełne pliki) — żeby orientować się w stanie.
6. Wyświetl userowi 1-akapitowe podsumowanie:
   ```
   [LOAD CONTEXT] Wątek: <slug>
   Cel: <jedno zdanie>
   Status: <wartość z headera>
   Postęp: <X/Y kroków odznaczonych>
   Otwarte kroki: <max 3 najbliższe niezrobione>
   Blokady: <pliki zablokowane przez inne wątki, jeśli są>
   Następny krok: <propozycja na podstawie planu>
   ```
7. NIE rób zmian w kodzie. To tylko ładowanie kontekstu — przygotowanie agenta do pracy.

Edge cases:
- Plik `HANDOFF_<slug>.md` nie istnieje → zaproponuj `/handoff-start <slug>` lub `/handoff-sync` (jeśli wpis jest w tabeli HANDOFF.md ale plik znikł, np. po `git checkout`).
- HANDOFF.md i `docs/handoffs/` nie istnieją → poinformuj że projekt nie ma jeszcze systemu handoff. Zasugeruj inicjalizację (skopiuj szablon z `docs/handoffs/README.md`).
