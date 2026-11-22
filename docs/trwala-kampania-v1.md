# D7.1-campaign-v1 — trwała kampania testowa v1

Akceptacja użytkownika: 2026-11-22, „trwała kampania testowa v1 i wznów”.
Baza definicji: `04817887b3463d8ba1f27d6566cd41b266d04a64`, `Faza_A`.
Status: zaakceptowany etap do implementacji przez jednego workera.

## Cel i granica etapu

Zbudować lokalny runner małych, odtwarzalnych kampanii testowych v1, który
utrwala wynik każdego przypadku i wznawia pracę po przerwaniu. Pierwszy
adapter reużywa przypadki istniejącego
[D5.3b](experiments/d5_3b/README.md): fixture/mapa, polityka, seed, zamiana
stron, inicjatywa i para strategii rozstawienia. Jest to zbieranie danych
o obecnej implementacji MVP, bez deklaracji pełnej poprawności zasad.

Zakres obejmuje implementację narzędzia, regresje i jeden mały pilot.
Nie obejmuje zmian silnika, heurystyk, reguł, kosztów, auth/API/UI,
propozycji D6.2, protokołów v2/v3, pełnego datasetu do uczenia polityki,
zewnętrznych usług ani stałego uruchamiania kolejnych kampanii bez końca.
Znane ograniczenia [D6.1](boty-audit.md) pozostają opisane w wynikach.
Naprawy wspólnej legalności wymagają osobnego zakresu; nie dodawać im
gotowości automatycznej w ramach tego etapu.

## Kontrakt i Definition of Done

1. **Jawny manifest i tożsamość.** Wersjonowany format wejścia/rekordów,
   stabilne campaign/case ID, seedy oraz provenance: digest manifestu,
   istotnych źródeł/fixture i środowisko. Reuse `load_manifest`, `iter_cases`,
   `run_case` oraz registry/factory z istniejących narzędzi, bez kopii logiki
   symulacji. Zachować dotychczasowy CLI i zamrożone artefakty D5.3b.
2. **Zapis po przypadku.** Trwale zatwierdzony rekord zawiera wynik,
   status, replay/determinizm oraz czasy. Awaria nie usuwa wcześniejszych
   rekordów. Manifest i journal są źródłem raportu; raport jest odbudowywalny.
   Zapisać granicę trwałości i procedurę postępowania z urwanym zapisem;
   korupcja zatwierdzonego rekordu nie może być ignorowana.
3. **Wznowienie i zgodność.** Pomijać przypadki już zatwierdzone, sprawdzać
   integralność oraz zgodność manifestu i istotnych wejść przed wykonaniem.
   Zmiana źródeł/konfiguracji oznacza jawny konflikt albo nową kampanię,
   nigdy ciche mieszanie danych. Dwa procesy nie mogą jednocześnie dopisywać
   do tej samej kampanii. Opisać odzyskanie po śmierci procesu.
4. **Uczciwa deduplikacja.** Jeden zatwierdzony wynik na case ID.
   Awaria po obliczeniu, ale przed trwałym zapisem może wymagać ponownego
   obliczenia. Nie deklarować exactly-once obliczeń. Wielokrotny resume
   ukończonej kampanii nie wykonuje symulacji ani nie zmienia danych.
5. **Ograniczony przebieg.** Sekwencyjne wykonanie z jawnym limitem nowych
   przypadków na wywołanie i dotychczasowym activation cap. Kontrolowany stop
   między przypadkami umożliwia dalszy resume. Ewentualny limit czasu między
   przypadkami nie jest gwarancją przerwania pojedynczej symulacji w terminie.
   Nie zmieniać limitu istniejącego manifestu: maks. 2048 wykonań wraz
   z powtórzeniami. Bez wielowątkowych patchy w jednym interpreterze.
6. **Błędy jako dane.** Osobno complete, deployment/match error,
   activation cap, niepowtarzalność i naruszenie replay/integralności.
   Nie zamieniać błędu w remis i nie usuwać go z mianownika. Zdefiniować
   exit codes odróżniające ukończenie, kontrolowany stop i błąd kampanii;
   zgodnie z D5.3b powtórzenia nie zwiększają próby statystycznej.
7. **Archiwum.** Samowystarczalny katalog kampanii: zamrożone wejścia,
   provenance, journal/wyniki, odbudowany raport i checksums. Eksport/kopiowanie
   ukończonej lub zatrzymanej kampanii musi mieć opisaną spójną procedurę.
   Brak automatycznego usuwania/nadpisywania innych kampanii i brak zapisu
   sekretów. Duże runtime artefakty wymagają osobnego backupu.
8. **Pilot i przekazanie.** Przed pomiarem zamrozić mały manifest:
   `demo_skirmish`, priority, seedy 11/19, obie zamiany i inicjatywy,
   cztery pary grid/objectives, dwa powtórzenia — 32 przypadki/64 wykonania.
   Jedna kampania pełna, druga zatrzymana po 8 przypadkach i wznowiona.
   Po resume deterministyczne rekordy i agregaty mają być identyczne;
   czasy i identyfikatory uruchomień porównać osobno. Końcowy resume jest
   no-op. Zachować w Git manifest, kompaktowy wynik/checksums i raport
   pilota; duplikatów pełnych archiwów runtime nie trzeba commitować.

## Warstwy, pliki i performance gate

- Teraz koordynator: tylko ten dokument, `docs/README.md` i nowa pozycja
  roadmapy. Brak zmiany kodu, modelu, DB, payloadów, JS/CSS i testów.
- Implementacja workera: nowy leaf CLI, np. `scripts/campaign_v1.py`,
  ewentualny prywatny moduł dziennika, `tests/test_campaign_v1.py`,
  `scripts/README.md` oraz indeksowane wyniki `docs/experiments/d7_1/`.
- SSOT: `scripts/deployment_experiment.py`, `balance_common.py`,
  agents registry/factory/match i engine replay/codec. Wspólne helpery
  wydzielać tylko jeśli potrzebne, z parity dotychczasowego harnessu.
- Brak modelu/migracji produkcyjnej, HTTP/auth, JS/CSS i zmian hot paths
  `/quote`/`/rosters/{id}`. Zero SQL i dostępu do produkcyjnej DB.
- Zapis per przypadek, bez ponownego przepisywania całej historii na każdym
  kroku. Jednorazowy skan journalu przy resume i generacji raportu jest
  dopuszczalny. Zmierzyć koszt zapisu oraz start/resume na jawnym fixture;
  oddzielić go od kosztu symulacji, bez deklaracji SLA z jednej próbki.

## Weryfikacja i zamknięcie

Testy mają obejmować rzeczywiste przerwanie procesu, zapis niepełny i korupcję,
resume w nowym procesie, konflikt dwóch writerów, zmianę manifestu/źródeł,
case ID/duplikaty, błąd/cap/replay, brak dodatkowego wykonania przy no-op,
odbudowę raportu i przeniesienie katalogu kampanii. Izolować wszystko w tmp.
Potwierdzić parity adaptera z dotychczasowym `run_case`, nie powielać testów
samego silnika. Testy celowane obejmują nowe narzędzie, D5.3b i D6.1;
pełny `pytest -q` jest obowiązkowy po implementacji i zmianach z review.
Przed edycją Python encoding gate UTF-8; call-site audit, simplify i review,
przegląd bezpieczeństwa zapisu/ścieżek/locków oraz diff check. Reguły gry,
jeżeli cytowane, odczytać z kanonicznych SZOP MD w sesji workera.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_campaign_v1.py tests/test_deployment_experiment.py tests/test_bots_audit.py -q
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
git ls-remote origin refs/heads/Faza_A
```

Dokumentacja implementacji musi podać dokładne komendy start/stop/resume/
verify/report/archive, wynik pilota, ograniczenia i instrukcję na inny
komputer. Osobny nowy commit na `Faza_A` i potwierdzenie tego SHA na
`origin/Faza_A`; zachować cudze zmiany i historyczny hunk B6.2 poza commitem.
Nie aktualizować HANDOFF ani schedulerów z workera. Po zamknięciu STOP.

Osobny backup: ignorowana produkcyjna `data/szop.db`, sekrety/konfiguracja,
scheduler/runtime i duże katalogi kampanii. Produkcyjna DB pozostaje bez zmian,
SHA256 `AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Środowisko odtworzyć z requirements. Resume na innym komputerze ma sprawdzać
źródła i manifest; różnice czasów/platformy nie są niedeterminizmem wyników.

## Weryfikacja definicji — 2026-11-22

Koordynator odczytał istniejące entry pointy D5.3b, manifest i zasady Git.
Potwierdzono 32 unikalne przypadki planowanego pilota oraz jednoznaczne
zależności: D5.3b i D6.1/2/3 są zakończone. Przygotowanie dotyczy wyłącznie
Markdown; nie wykonano implementacji ani nowej kampanii. Szczegóły formatu
journalu/locka są zieloną decyzją workera w powyższych granicach.
Helper `ready-stages` zwrócił wyłącznie `D7.1-campaign-v1`; sprawdzono
lokalne linki, istniejące entry pointy/testy oraz `git diff --check`.
Ręczne simplify/review zachowały jeden adapter i oddzieliły ponowne
obliczenie od deduplikacji zapisu. Pytest nie ponawiano dla samej definicji
Markdown; pełny gate jest obowiązkowy dla implementacji powyżej.
