# HANDOFF — wydanie-poprawek

Status: In progress, 2026-11-03.

Cel: commit obu zestawów poprawek na main i publikacja wydania dostępnego przez aktualizator aplikacji.

Warstwy: bez nowych zmian kodu/modelu/payloadu/JS/CSS. Testy: pełny pytest przed publikacją. Zachować wszystkie wcześniejsze poprawki i źródłową bazę.

- [x] Odświeżenie origin/tagów, sprawdzenie rozbieżności main/Rozwoj, pytest i przegląd diffu (370 passed).
- [~] Commit wskazanych plików, scalenie na main bez przepisywania historii, push main.
- [ ] Tag patch po v1.1.1 i Release workflow (testy, GHCR latest, GitHub Release); zweryfikować zakończenie.
- [ ] Zapis wyniku i archiwizacja.

Aktualizator korzysta z docker compose pull (latest); sam push main nie publikuje obrazu. RELEASE.md wymaga tagu SemVer. User autoryzował commit main i przygotowanie aktualizacji; nie uruchamiać aktualizacji serwera.

Rozbieżność: origin/main ma 73 osobne commity (historyczne OPOS/Faza A), Rozwoj 25 (aktualny SZOP); różnica 213 plików. Merge-tree bez edycji wykazał konflikty quote.py, HANDOFF, docs i pycache. Zadano pytanie o promocję aktualnego drzewa SZOP vs zachowanie funkcji obu gałęzi. Wykonać commit poprawek na Rozwoj; przed zmianą main/publikacją czekać na odpowiedź dotyczącą zakresu.

2026-11-03: User potwierdził, że OPOS jest w osobnym repo i tutaj nie musi być utrzymywany. Autoryzacja: najpierw Rozwoj, potem ostrożnie main i automatyczna aktualizacja. Commit 5950224 wypchnięty na Rozwoj. Zachować aktualne drzewo SZOP przez merge historii origin/main do Rozwoj ze strategią ours, potem fast-forward main. Nie przepisywać historii ani nie przywracać historycznych funkcji OPOS. Usunąć z indeksu 32 śledzone pliki cache Pythona, zachowując lokalne pliki. Wydanie v1.2.0 (od ostatniego main także kompatybilne nowe funkcje Kolekcji i Stanu Bitewnego).
