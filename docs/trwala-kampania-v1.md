# D7.1-campaign-v1 — trwała kampania testowa v1

Akceptacja użytkownika: 2026-11-22, „trwała kampania testowa v1 i wznów”.
Baza definicji: `04817887b3463d8ba1f27d6566cd41b266d04a64`, `Faza_A`.
Status: **DONE 2026-11-22** — implementacja, regresje i mały pilot zakończone.

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

## Kontrakt implementacji

Entry point: [scripts/campaign_v1.py](../scripts/campaign_v1.py), regresje:
[tests/test_campaign_v1.py](../tests/test_campaign_v1.py). Manifest wejściowy
zachowuje schemat `szop.deployment_experiment/v1`, limity i SSOT D5.3b.
Nie ma nowego publicznego API ani alternatywnego executora.

Katalog kampanii zawiera:

- `manifest.json` — kanoniczna zamrożona kopia manifestu;
- `header.json` — `szop.campaign/v1`, campaign ID, manifest/source digests,
  wersje zależności, Python/platforma, bazowy commit i checksum nagłówka;
- `inputs/tests/fixtures/battles/*.yaml` — kopie użytych fixture z hashami;
- `journal.jsonl` — `szop.campaign.record/v1`, indeks, hash poprzednika,
  natywny wynik `run_case`, środowisko wykonania i SHA256 rekordu;
- `report.md`, `checksums.json` — odbudowywalne artefakty pochodne;
- `.lock` — stały plik blokady OS, nie PID/lease do ręcznego usuwania.

Campaign ID to SHA256 kanonicznej tożsamości: manifest, hashe istotnych
źródeł/fixture, rodzina Python major/minor i wersje pydantic/pydantic_core/
PyYAML. Pierwszy poprzednik journalu jest tym ID; każdy kolejny jest hashem
pełnego poprzedniego rekordu. Case ID pochodzi wyłącznie z `iter_cases`.
Wyniki muszą tworzyć uporządkowany prefiks manifestu, bez duplikatów.
Hashe służą wykrywaniu uszkodzeń, nie uwierzytelnianiu wobec osoby mogącej
przepisać całe archiwum.

Przed resume sprawdzane są źródła engine/agents/rulesets/app-data, YAML
rulesetu, trzy skrypty adaptera/balansu, runner kampanii i użyte fixture.
Tekst jest hashowany po normalizacji końców linii przez odczyt UTF-8;
CRLF/LF nie blokuje przeniesienia. Zmiana patcha Python lub platformy jest
zapisana, ale nie zmienia tożsamości; zmiana major/minor albo wersji
wymienionych zależności blokuje resume. Nie edytować źródeł ani fixture
w trakcie wywołania runnera. Inne dokumenty/HEAD mogą się zmieniać bez
zmiany tożsamości, jeśli istotne źródła pozostają zgodne.

Zapis to append jednej kanonicznej linii, flush i `os.fsync`. Pełna linia
z końcowym LF i poprawnym łańcuchem jest rozpoznawana przy ponownym odczycie.
Śmierć przed zapisem może spowodować ponowne obliczenie; nie ma gwarancji
exactly-once obliczeń. `fsync` jest granicą potwierdzenia zapisu procesu,
nie obietnicą odporności na każdą awarię sprzętu. POSIX dodatkowo synchronizuje
katalog po atomic replace; Windows nie ma przenośnego directory fsync
w użytym stdlib. Testy dotyczą przerwania procesu na lokalnym systemie plików.

`msvcrt.locking` na Windows / `flock` na POSIX wykluczają drugiego writera
przez całe wywołanie CLI, także raportowanie/archiwizację. Blokada znika po
zamknięciu uchwytu lub śmierci procesu, plik `.lock` pozostaje. Nie jest to
blokada rozproszona między komputerami ani gwarancja synchronizacji OneDrive.
Przy migracji zatrzymać poprzednie wykonanie; nie wznawiać niezależnych kopii
tego samego katalogu jako jednej wspólnej kampanii i nie scalać journalów.

## Start, stop, recovery i archiwum

Każde wywołanie `start` wymaga nowego katalogu i jawnego limitu nowych
przypadków. Stop po limicie jest kontrolowany; Ctrl+C/śmierć procesu może
pozostawić niezatwierdzony przypadek lub urwany ostatni zapis. Limit aktywacji
pochodzi z manifestu; nie ma deadline ani schedulera wykonującego grę w tle.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py start --manifest docs/experiments/d7_1/manifest.json --directory build/campaigns/example --max-cases 8
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py resume --directory build/campaigns/example --max-cases 24
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py verify --directory build/campaigns/example
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py report --directory build/campaigns/example
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py archive --directory build/campaigns/example --destination build/campaigns/example-backup
```

Exit 0 oznacza ukończoną serię lub udaną operację, 2 kontrolowany stop,
1 błąd kampanii/obsługi. Deployment/match error i activation cap są jawnie
zapisanymi wynikami symulacji; ukończenie ich serii może zwrócić 0.
Niepowtarzalność oraz replay/invariant/harness error zapisują rekord i
zatrzymują kampanię kodem 1. Kolejny resume zatrzymuje się bez retry.
W raporcie niestabilne wyniki nie zasilają zwycięstw/remisów, ale pozostają
w liczbie przypadków. Nie traktować samego exit 0 jako certyfikatu jakości.

Niepełny ostatni rekord bez LF wymaga jawnej komendy:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py repair-tail --directory build/campaigns/example
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py resume --directory build/campaigns/example --max-cases 24
```

`repair-tail` zachowuje odrzucone bajty w sąsiednim unikalnym pliku
`example.tail-<uuid>.bin`, a następnie obcina wyłącznie niepełny koniec.
Wcześniejsze rekordy są najpierw w pełni sprawdzone. Uszkodzony rekord
zakończony LF, zmiana manifestu/źródeł albo nieznany plik wymagają inspekcji;
nie są automatycznie naprawiane. Nie usuwać journalu, aby „przepchnąć” resume.

Raport/checksums mogą być nieaktualne po śmierci między zatwierdzeniem
ostatniego przypadku a generacją raportu. `verify` wykrywa taki stan;
`report` odbudowuje pliki bez symulacji. Resume ukończonej kampanii jest
no-op, więc nie naprawia ich niejawnie. Znane osierocone pliki atomowego
zapisu `.report.md.<uuid>.tmp`/`.checksums.json.<uuid>.tmp` pozostają do
inspekcji i nie trafiają do archiwum; nie blokują wznowienia.
Przerwane tworzenie początkowego nagłówka nie jest gotową kampanią —
zachować katalog do inspekcji i wybrać nowy katalog startu.

`archive` pod blokadą odbudowuje raport/checksums, kopiuje tylko zamkniętą
listę artefaktów do nowego katalogu i sprawdza hashe kopii. Docelowy katalog
jest także zablokowany podczas kopiowania; istniejący nie jest nadpisywany.
Przerwana kopia pozostaje do inspekcji, bez automatycznego usuwania.
Nie kopiować aktywnego journalu narzędziem bez spójnej blokady.

Na innym komputerze pobrać commit etapu z `Faza_A`, odtworzyć środowisko
z requirements, skopiować kompletne archiwum i uruchomić `verify`, potem
`resume` z jawnym limitem. Fixture muszą być dostępne także w zgodnym
checkoutcie; ich kopie w archiwum są materiałem odtworzenia/inspekcji,
nie mechanizmem omijania source gate. Przy konflikcie użyć zgodnego kodu
albo rozpocząć nową kampanię. Runtime z `build/campaigns/` wymaga osobnego
backupu; Git przechowuje [mały pilot](experiments/d7_1/README.md).

## Wynik i weryfikacja D7.1 — 2026-11-22

Nowy runner reużywa `load_manifest`, `iter_cases`, `run_case`, `summarize`
i `render_report` D5.3b. Dotychczasowy harness i jego zamrożone wyniki nie
zmieniły się. Audyt call sites: nowe funkcje są używane wyłącznie przez
lokalny CLI i jego testy; nowe wywołanie `run_case` deleguje do tego samego
adaptera co historyczne CLI. App/router/client/engine nie importują runnera.
Brak zmian modelu, auth, API, hot paths, JS/CSS i produkcyjnej DB.

34 nowe regresje D7.1; celowane D7.1/D5.3b/D6.1: **77 passed**, 68,89 s.
Po końcowym simplify/review pełny `pytest --tb=short -q`:
**4146 passed, 4 warnings**, 532,09 s. Ostrzeżenia pochodzą z reportlab/
openpyxl. Końcowy simplify usunął możliwość wyłączenia source gate
i zaostrzył typ indeksu/case; pełny gate uruchomiono po tej zmianie.
CLI `--help`, encoding/AST import check i `git diff --check` przeszły.
Nie zmieniano kodu po pełnym gate i pomiarze pilota.

Ręczne odpowiedniki simplify/review/security-review objęły SSOT adaptera,
dedup zapisu versus recompute, fsync/lock/crash, strict source/case guards,
ograniczenie ścieżek fixture, zamknięty zbiór kopiowanych plików i brak
nadpisywania archiwów. Review dodał obsługę osieroconego pliku tymczasowego
raportu oraz jawne wykrywanie nieaktualnych checksums; regresje i pełny
pytest wykonano po poprawkach. Slash commands nie były dostępne.
Przegląd nie wymagał nowego uprawnienia ani decyzji produktowej.

[Pilot i wynik maszynowy](experiments/d7_1/README.md): pełna kampania 32/64
oraz nowy proces po stop8 + resume24 dały identyczne 32 rekordy
deterministyczne i agregaty, 0 błędów/niedeterminizmu/replay mismatch.
Końcowe resume i resume archiwum: 0 nowych rekordów, brak zmiany bajtów.
64 operacje zapisu: mean **28,614 ms**, median **36,185 ms**, max **138,953 ms**;
preflight start **117,211 ms**, resume24 **159,404 ms**. Zmierzone osobno od
symulacji, bez równoległego pytest; nie SLA ani gwarancja innego filesystemu.
Zero SQL; runner nie korzysta z produkcyjnej bazy.

Kontynuacja: pobrać commit zamykający D7.1 z Faza_A/origin, odtworzyć venv,
użyć powyższych komend oraz kompletnego archiwum runtime. `header.base_commit`
opisuje bazę Git sprzed implementacji; zgodność wykonania wyznaczają hashe
źródeł z końcowego commitu, nie samo dawne HEAD. Produkcyjna DB zachowuje
SHA256 podane powyżej. Backup bazy/sekretów/runtime i pełnych dzienników
jest osobny; kod/manifest/kompaktowy pilot są w Git.

Ograniczenia: pierwszy adapter D5.3b/v1, sekwencyjne wykonanie, restart na
granicy przypadku, lock lokalny dla hosta, brak pełnych śladów stan→decyzja
do uczenia, brak napraw legalności i dowodu balansu pełnych zasad. Większa
kampania lub kolejny adapter wymagają określonego manifestu i osobnego
wyboru. Nie uruchomiono ich w tym etapie i nie dodano markerów gotowości.
