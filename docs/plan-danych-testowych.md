# Plan archiwum, jakości i eksportu decyzji

Plan z 2026-11-23 na bazie `f0dec461b93dd9be656333bc8be0c72e703c564d`
na `Faza_A`. Etapy poniżej są propozycjami do wyboru. Pierwszym jest D7.2a.

[D7.1](trwala-kampania-v1.md) zapisuje wyniki przypadków w trwałym dzienniku
i tworzy kopię pojedynczej kampanii. [Pilot](experiments/d7_1/README.md)
odtworzył 32 przypadki po zatrzymaniu i wznowieniu. [D5.3b](experiments/d5_3b/README.md)
ma wyniki porównań rozstawienia, a [D6.1](boty-audit.md) wyniki audytu botów
i udokumentowane luki legalności. [Telemetria](adr/0017-telemetry-day-one.md)
eksportuje metryki z event-logu i agregaty wykonanych decyzji. Kolejny krok
to wspólny katalog tych dowodów, jawna ocena ich użyteczności i pełny ślad
decyzji dla nowych symulacji offline v1.

| Etap | Zależności | Wynik |
|---|---|---|
| D7.2a | D7.1 | Katalog i publikacja zweryfikowanej kopii kampanii |
| D7.2b | D7.2a | Import istniejących eksperymentów, backup i odtworzenie |
| D7.3a | D7.2a | Ocena integralności, powtarzalności i kompletności |
| D7.3b | D7.3a, D7.2b | Kontrola par porównań i pomiar efektu strony |
| D7.4a | D7.1 | Obserwacja decyzji i ich skutków w runnerze v1 |
| D7.4b | D7.4a, D7.2a, D7.3a | Wersjonowany eksport i weryfikacja przez replay |
| D7.4c | D7.4b, D7.3b | Pilot od przerwanej kampanii do wspólnego archiwum |
| D7.3c | D7.4b, D7.3b, zweryfikowany zakres reguł | Kwalifikacja decyzji do uczenia |

Rekomendowana kolejność przebiegów to D7.2a → D7.2b → D7.3a → D7.3b →
D7.4a → D7.4b → D7.4c → D7.3c. Pilot diagnostyczny może dostarczyć dane
wcześniej niż powstanie profil dopuszczający dane do uczenia.

## D7.2a. Wspólne archiwum kampanii

**Cel.** Operator wskazuje katalog archiwum, publikuje w nim zweryfikowaną
kopię D7.1 i odnajduje ją po identyfikatorze, typie, scenariuszu i rewizji.
Pierwsza wersja to wspólny format katalogu plików i lokalny CLI. Pilotaż
korzysta z `build/experiment-archive/`. Właściwą lokalizację i dostęp wybiera
się osobno przed udostępnieniem.

**Kontrakt.** Wersjonowany opis pakietu wskazuje format wejścia, `campaign_id`,
zapisany prefiks przypadków i stan kompletności oraz pliki z rozmiarem
i SHA256. Identyfikator pakietu wynika z zawartości i wersji formatu.
`campaign_id` z D7.1 identyfikuje konfigurację i źródła, dlatego pełny przebieg
i zapis po 8 przypadkach mogą go dzielić. Osobne pakiety zachowują oba
snapshoty, a powtórny import identycznego pakietu zwraca istniejący wpis.
Katalog można odbudować z opisów pakietów. Ocena jakości i eksport są
oddzielnymi pakietami powiązanymi identyfikatorem i hashem danych wejściowych.

Publikacja wykorzystuje `campaign_v1 archive` i `verify` ze zgodnego
checkoutu. Kopia powstaje w katalogu roboczym importu. Dopiero po sprawdzeniu
pełnej listy i hashy plików trafia do katalogu pakietów pojedynczą publikacją
na tym samym systemie plików. Indeks pomija niedokończone importy. Odczyt
historycznych metadanych i hashy działa także po zmianie kodu. Wznowienie
odbywa się na kopii roboczej z obowiązującym sprawdzeniem źródeł i zależności
D7.1. Zapisy do jednego katalogu obsługuje jeden proces publikujący.

**Warstwy i odbiór.** Planowane `scripts/experiment_archive.py` z operacjami
importu, listowania i weryfikacji pakietu,
`tests/test_experiment_archive.py` i instrukcja w `scripts/README.md`.
Testy obejmą publikację pełnej i zatrzymanej kampanii o wspólnym `campaign_id`,
powtórzony import, przerwaną kopię, próbę nadpisania, zmanipulowany hash,
nieznany plik, wyjście poza katalog i dowiązanie. Odbudowany katalog zwraca te
same identyfikatory, a kopia pozostaje weryfikowalna po zmianie źródeł runnera.
Koszt publikacji rośnie z liczbą i rozmiarem plików nowego pakietu.

## D7.2b. Import historii i odzyskanie archiwum

**Cel.** Do tego samego katalogu włączyć manifesty, wyniki i raporty D5.3b
oraz D6.1 przy zachowaniu ich typów i stopnia weryfikacji. Kompaktowy wynik
D7.1 jest dowodem z pilota, a jego pełny dziennik pochodzi z osobnego backupu.
Każdy adapter odczytuje tylko swój format i zachowuje oryginalne pliki.
Starszy CSV lub JSONL może być załącznikiem, jeśli znamy przebieg, z którego
powstał. Braki w metadanych są widoczne jako brak dowodu.

Kod, manifesty, identyfikatory, opis i kompaktowe wyniki pozostają w Git.
Pełne dzienniki i eksporty przechowuje się razem z manifestem i weryfikowalną
kopią poza komputerem, na którym powstały. Aktywna kampania ma jeden katalog
roboczy na jednym hoście. Instrukcja obejmie wybór kopii, `verify`, odtworzenie
środowiska, `resume` i odzyskanie uszkodzonego pakietu. Zapisać rewizję, na
której potwierdzono zgodność hashy źródeł. `header.base_commit` D7.1 może
wskazywać samą bazę implementacji. Pakiety cytowane przez raporty lub użyte
do uczenia i ich metadane mają zachowaną historię. Automatyczna retencja
wymaga osobno uzgodnionej polityki.

**Warstwy i odbiór.** Adaptery i testy w warstwie CLI archiwum, procedura backupu
w dokumentacji. Import rozpoznaje 480 przypadków rozstawienia D5.3b i 239
przypadków audytu D6.1, w tym różne typy prób D6.1. Odzyskana kopia pozwala
odbudować katalog bez starego indeksu. Na drugim komputerze lub w świeżym
środowisku odtworzyć jeden zatrzymany snapshot z właściwego commitu,
uruchomić `verify` i `resume`, porównać deterministyczny wynik oraz sprawdzić
no-op po zakończeniu. Czas transferu mierzyć razem z rozmiarem danych.

## D7.3a. Bramka integralności i kompletności

**Cel.** Generować maszynowy wynik oceny dla konkretnego pakietu i wersji
profilu jakości. Raport podaje planowaną liczbę przypadków, liczbę zapisanych
i brakujących oraz wyniki i powody wyłączeń dla każdego typu. Weryfikacja
odczytuje archiwum i dowody z przebiegu. Niezależny replay każdej gry będzie
możliwy w D7.4b po udostępnieniu pełnego ogona zdarzeń.

| Kontrola | Skutek w ocenie |
|---|---|
| Niezgodny hash, schemat, łańcuch lub duplikat przypadku | Błąd integralności. Pakiet do inspekcji. |
| Poprawny, zatrzymany przebieg | Oznaczenie jako częściowy z liczbą przypadków do wykonania. |
| `deployment_error`, `match_error`, `activation_cap` | Osobne liczniki. Przypadki pozostają w mianowniku pokrycia i są wyłączone z wygranych i remisów. |
| Niepowtarzalność, błąd replay lub brak dowodu replay | Powód zapisany osobno. Brak dopuszczenia przypadku do porównań wymagających tego dowodu. |
| Wynik zakończony i zgodny z manifestem, powtórzeniem i dowodem replay | Przypadek przechodzi bramkę techniczną w granicach dostępnego dowodu. |

Załącznik `quality.json` wiąże dane przez identyfikator pakietu i digest
polityki oceny. Ponowna ocena nową polityką tworzy nowy wynik. Dla każdego
przypadku zachować kod powodu i odsyłacz do dowodu. Kod wyjścia D7.1 opisuje
stan wykonania CLI. Powtórzenie deterministyczne jest dowodem i nie zwiększa
próby. Etykieta `resolver_accepted` z audytu opisuje zachowanie implementacji.
Ocena korzysta z parserów typu pakietu i tych samych definicji statusów co
runner. Sprawdzenie zgodności z bieżącymi źródłami pozostaje krokiem wznowienia.

**Warstwy i odbiór.** Planowane `scripts/experiment_quality.py`,
`tests/test_experiment_quality.py` i kompaktowe przykłady w dokumentacji.
Sprawdzić czysty pilot, prawidłowy prefiks 8/32, zakończoną kampanię z błędem
domenowym, brak dowodu, błąd replay, niespójny agregat i korupcję. Raport
zachowuje sumę kategorii i rozróżnia jakość od exit code. Przeważający koszt
to liniowy odczyt pakietu bez ponownej symulacji.

## D7.3b. Bramka porównywalności i efektu strony

**Cel.** Przygotować porównanie strategii MVP tylko dla par spełniających
zamrożony projekt eksperymentu. Manifest deklaruje badaną zmienną, zakres
źródeł i klucz grupowania. Dla D5.3b blok tworzą mapa/fixtura, seedy
i polityka. W nim sprawdzamy zamiany stron i inicjatywy oraz
obie orientacje grid–cele i kontrole grid/grid oraz cele/cele. Parametry
poza badaną zmienną mają odpowiadać zaplanowanej parze. Jeśli jednej strony
pary brakuje albo jej przypadek nie przechodzi bramki technicznej, cały blok
pozostaje widoczny w pokryciu z przyczyną wyłączenia.

Raport pokazuje liczbę pełnych bloków, P0/P1/remisy dla kontroli, wynik
strategii po obu stronach oraz rozbicie co najmniej według mapy, polityki
i inicjatywy. Efekt strony oznacza ostrzeżenie interpretacyjne z liczbami
i opisem projektu. Ewentualny próg ostrzeżenia określa się przed kampanią.
Historyczne kontrole D5.3b i kontrprzykłady D6.1 wyznaczają przypadki
regresji. Podstawą porównania są bloki i ich pokrycie, ponieważ warianty
stron i powtórzenia z tym samym seedem są skorelowane.

**Warstwy i odbiór.** Profil i raport w CLI jakości, testy na danych D5.3b
oraz na kopii z brakującą parą i z inną rewizją/mechaniką. Dla D5.3b
odtworzyć 240 mieszanych przypadków, w tym 174 wygrane celów, 30 gridu i 36
remisów, oraz kontrolę grid/grid 58 P0, 8 P1, 54 remisy. Przy poprawnym
przemianowaniu stron sumy strategii są równe, a liczniki P0/P1 zamieniają
się miejscami. Osobny test wykrywa pozorną parę powstałą przez zmianę samej
etykiety. Koszt to grupowanie i agregacja zachowanych rekordów.

## D7.4a. Obserwacja decyzji i zdarzeń

**Cel.** Zapisać każdą rzeczywistą decyzję w kampanii v1. Obecny
`on_decision` z [runnera](../app/services/agents/match.py) jest wołany dla
wykonanych akcji. `None`, odrzucona kontynuacja i przekazanie inicjatywy
pozostają poza tym hookiem. Przed pierwszą akcją stan widziany przez bota
może się różnić od stanu po `_begin_activation`. [Resolver](../app/services/engine/resolver.py)
wykonuje też finalizację po ostatnim `on_action`.

Dodać opcjonalny obserwator w istniejących miejscach wyboru i rozstrzygnięcia.
Obejmuje wywołania `choose_action`, `continue_activation` i wybory rozstawienia,
w tym ścieżki grid/objectives realizowane przez strategię bez callbacku bota.
Zapisać faktycznie widziany stan, stronę, kontekst aktywacji lub rozstawienia,
wybór albo `None`, rzeczywisty wynik walidacji i zakres zdarzeń. Brak wywołania,
np. przy zakończeniu aktywacji przez silnik, i automatyczne przejścia rundy
mają własne oznaczenia. Rozstawienie zapisuje roboczy kontekst, strefę,
zajęte miejsca i przyjętą pozycję. Obserwator czyta wywołania runnera
bez dodatkowego wywołania polityki, dobierania kandydatów czy losowania.
Kandydatów zapisuje się tylko wtedy, gdy polityka rzeczywiście ich ujawnia.

**Warstwy i odbiór.** `agents/match.py`, konieczne miejsca w `engine/resolver.py`
i opcjonalne podłączenie w `scripts/deployment_experiment.py`. Testy trafiają
do istniejących testów runnera, np. `tests/test_agents_match.py`
i `tests/test_engine_multi_action.py`, oraz do testów śladu. Odbiór obejmuje
pierwszą decyzję wykonaną i odrzuconą, kontynuację wykonaną i odrzuconą,
`None`, callback i wybór strategii rozstawienia oraz automatyczne przejście.
Wyjątek walidacji zachowuje kod powodu ze wspólnego miejsca rozstrzygnięcia.
Dla tych samych wejść przebiegi ze śladem i bez niego dają identyczne decyzje,
stan końcowy, log, wynik i dalsze rzuty. Domyślna ścieżka zachowuje kontrakt
`on_decision` oraz przechodzi B7 golden i testy `LocalClient`. Zmierzyć narzut
obserwacji na wspólnej próbce.

## D7.4b. Pełny eksport i sprawdzenie odtworzenia

**Cel.** Wersjonowany pakiet offline z danymi do odtworzenia obserwacji,
decyzji i skutku. Oznaczyć kampanię, przypadek, powtórzenie, pozycję decyzji
w przebiegu, rewizję i seedy faktycznie użyte przez adapter. Klucz decyzji
jest jednoznaczny w obrębie przebiegu. Czasy wall-clock to diagnostyka.

| Plik lub część pakietu | Dane |
|---|---|
| Opis eksportu | Wersje codeców, manifest, źródła, schemat, hashe plików i status zbierania. |
| Stany startowe i zdarzenia | Stan przed i po rozstawieniu, pełny ogon gry, osobne zakresy sekwencji rozstawienia i gry oraz digest stanu końcowego. |
| `decisions.jsonl` | Identyfikatory, kontekst, stan rzeczywiście widziany, wybór, wynik walidacji oraz odniesienia do stanów i dokładnego zakresu zdarzeń. |
| Wynik i ocena | Status, liczba decyzji i zdarzeń, dowód replay, znane ograniczenia i przyczyny wyłączeń. |

Reużyć `battle_state_to_json`/`battle_state_from_json`, `event_to_json`/
`json_to_event` i `apply_events`. `action_to_json` obsługuje akcje walki
i aktywacji z zamkniętego unionu. Wybór pozycji rozstawienia wymaga własnej
jawnie opisanej projekcji pozycji i oddziału w schemacie eksportu. Wiersz
referencjonuje stan przez zakres eventów i digest albo kanoniczny snapshot,
gdy obserwacja ma roboczy stan spoza replay. Oddzielić stan widziany,
stan bezpośrednio przed wykonaniem i stan po wykonaniu. Niewykonany wybór
ma status i powód oraz brak zakresu skutków tej akcji. Przy błędzie zachować
dostępny prefiks z oznaczeniem niekompletności. Eventy startu, finalizacji
i końca rundy pozostają w odtwarzanym logu. `deployment_round` ustawia rundę
bez osobnego eventu przejścia, więc poprawność stanu po rozstawieniu sprawdza
to samo `deployment_round` z zapisanymi pozycjami. Replay walki startuje
od utrwalonego stanu po rozstawieniu.

Weryfikator przechodzi zdarzenia raz w kolejności, sprawdza ciągłość i zakresy,
odtwarza wskazane stany i porównuje ich hashe oraz stan końcowy. Eksport można
rozwinąć do rekordów stan → decyzja → skutek na zgodnym checkoutcie. Dane
pochodzą z jawnych fixture i seedów offline. Surowe dane kont, DB, tokeny,
prywatne checkpointy RNG i surowe rzuty kości są poza formatem. Ślad z
re-symulacji ma tożsamość nowego przebiegu i wskazuje pochodzenie manifestu.

**Warstwy i odbiór.** Planowane `scripts/export_decisions.py`,
`tests/test_export_decisions.py`, dokument schematu i przykładowy mały pakiet.
Testy sprawdzają odczyt i replay pełnej gry, przynależność eventów do obu akcji
w jednej aktywacji, `None` i odrzucenia, osobne sekwencje rozstawienia i gry,
brakujący/zmieniony event, rozróżnienie wyboru przed `_begin_activation`
i wykonania po nim, fałszywe odniesienie do stanu oraz powtórzenie z tym
samym seedem. Porównywać stabilne
dane bez czasów. Zapis jest ograniczony do danych jednego przypadku naraz.
Zmierzony rozmiar na decyzję i przypadek ustali jawny budżet pilota.

## D7.4c. Pilot całego przepływu

**Cel.** Jeden ograniczony, opt-in przebieg D7.1 z rzeczywistym śladem
decyzji, spójnym wznowieniem i publikacją pakietów z oceną techniczną.
Użyć macierzy pilota D7.1. Format D7.1 pozostaje podstawą zwykłego przebiegu.
Wariant ze śladem ma wersjonowane powiązanie między zatwierdzonym przypadkiem
a zapisanym śladem. Ślad trafia do osobnego pliku przed zatwierdzeniem
powiązania. Po awarii pakiet zawiera tylko ślady wskazane przez zatwierdzone
rekordy. Osierocony plik pozostaje do inspekcji. Błąd zbierania i brakujący
ślad są jawne w ocenie. Poprzednie kampanie wznawia się z ich własnym
zgodnym commitem i formatem.

**Warstwy i odbiór.** Integracja między CLI kampanii, eksporterem, archiwum
i bramkami. Dodać do `tests/test_campaign_v1.py` próbę przerwania przed
zatwierdzeniem powiązania. W nowym procesie wznowić przebieg po 8 przypadkach
i porównać 32 wyniki i ślady z pełnym przebiegiem. Z pakietu odtwarzają się
obserwacje i skutki decyzji. Duplikat importu zwraca ten sam wpis, sprawdzenie
kopii na świeżym checkoutcie daje tę samą ocenę. Próbka z błędem ma
udokumentowane wyłączenie. Do Git trafiają manifest i kompaktowy raport
z hashami, liczbami i pomiarami czasu oraz rozmiaru. Pełny pakiet ma kopię.

## D7.3c. Bramka zgodności z regułami i użycia do uczenia

**Cel.** Dopuścić decyzję tylko do zastosowania, dla którego istnieje dowód.
Zapis z D6.1 utrwala m.in. problem Ostrzału przy bliskim widocznym wrogu,
ataku Wyczerpanego i Manewru Przyszpilonego. Źródła to pkt 14.c.iv, 22.a.i
i 22.b.i [Rozjemcy](../app/static/docs/SZOP_Rozjemca.md). Przy Mobilizacji
sprawdzić również współwystępowanie stanów z pkt 14.b, 22.b.iii i 22.c.iv.
Akcja może być wykonana przez bieżący resolver mimo luki. Etykieta do uczenia
wymaga wspólnej, zweryfikowanej walidacji w dokładnie udokumentowanym zakresie.

Szeroki profil walki zależy od napraw typu [P6 w planie Play vs AI](play-vs-ai-plan.md#p6-wspólna-legalność-walki-i-statusów)
i regresji wszystkich wspieranych mechanik. Węższy profil można osobno
udokumentować i zweryfikować na obsługiwanych stanach i akcjach. W obu
przypadkach używać źródeł SZOP i wspólnych walidatorów. Ocena odróżnia
naruszenie, niezweryfikowany zakres i potwierdzenie. Dane z nieobserwowanym
wyborem, poza profilem lub z błędem pozostają materiałem diagnostycznym.
Zaobserwowany wybór bota daje etykietę imitacji. Jawna odmowa kontynuacji
może być taką etykietą, jeśli dopuszcza ją profil. `decision_quality_score`
jest samooceną heurystyki i pozostaje oddzielną cechą diagnostyczną.

**Warstwy i odbiór.** Profil reguł, kwalifikacja w CLI jakości i wersjonowana
lista kwalifikowanych przypadków/wyłączeń. Regresje odtwarzają kontrprzykłady
D6.1 i potwierdzają, że wykonanie przez resolver ich nie dopuszcza do zbioru.
Próba pozytywna obejmuje zweryfikowany zakres, pełne stany oraz replay.
Przed uczeniem zamrozić dobór grup train/validation/test. Powtórzenia,
zamiany stron i duplikaty tej samej rozgrywki trafiają do tej samej grupy.
Przy ocenie generalizacji dzielić po rodzinach map lub składów zgodnie
z celem. Raport sprawdza brak wspólnych grup i identycznych próbek między
splitami. Jedna mapa pilota służy do kontroli infrastruktury.

## Wspólna weryfikacja i przekazanie

Model danych tych etapów to wersjonowane pliki eksperymentów. Warstwa
backend to opcjonalna obserwacja w runnerze i narzędzia offline. Produkcyjny
model, migracje, payloady HTTP, JS i CSS są poza zakresem. Budżet SQL wynosi
0. Przegląd ma sprawdzić ścieżkę bez obserwatora, koszt zapisu i replay,
ścieżki wejść/wyjść i rozmiar na przypadek. Punktem odniesienia dla lokalnego
zapisu jest [pomiar D7.1](experiments/d7_1/README.md) z medianą 36,185 ms
na rekord. Wynik na danym dysku trzeba ponownie zmierzyć.

Po implementacji każdego etapu uruchomić jego celowane testy i
`.\.venv\Scripts\python.exe -X utf8 -m pytest -q`. Wykonać call-site audit,
simplify/review i `git diff --check`, a dla operacji na plikach przejrzeć
także granice ścieżek, blokad i publikacji. Po zmianie kodu z przeglądu
ponowić pełny gate. Udokumentować komendy, wyniki, limity i zależności.
Osobny commit na `Faza_A` potwierdzić na `origin/Faza_A`. Dane runtime
i produkcyjna baza oraz lokalna konfiguracja mają osobne ścieżki backupu.

Definicję sprawdzono względem kodu runnera, codeców i zapisanych wyników
D5.3b, D6.1 oraz D7.1. Kontrola źródeł SZOP potwierdziła 4/4 pliki.
Sprawdzono odnośniki, kolejność zależności i diff dokumentacji.
Ostatni pełny wynik **4146 passed** pochodzi z D7.1.
