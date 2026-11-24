# D7.3c — kwalifikacja decyzji do uczenia

Profil `deployment-position-mvp-v1` dopuszcza etykiety imitacji
obserwowanego wyboru **pozycji rozstawienia** w modelu MVP. Dowód dotyczy
położenia oddziału w jawnie przypisanej prostokątnej strefie, uwzględnia
zajęte miejsca oraz teren Niedostępny i wiąże decyzję z wykonanym ruchem
rozstawienia. Podstawa to pkt 2.d, 4.c.i, 13.a–b, 15.c i 24.
[Źródło reguł](../app/static/docs/SZOP_Rozjemca.md)

## Uruchomienie

```powershell
$py = '.\.venv\Scripts\python.exe'
$archive = 'build/d73c-pilot/archive'
$output = 'build/d73c-pilot/reports'
$campaign = '4cbeca259d939b28b1a37aa3547a6ebd90f877427e3d0fd39e39313a7845e583'
$audit = '51a590e8aeedd158f61432991f76460caa1cd35e8d97db5a2609807d6669e3ea'
$incomplete = 'e684556840c302ad5ce03a76806bf36526048be7fe96e4f9ad929977b20f09dd'
& $py -B -X utf8 scripts/experiment_quality.py --archive-root $archive --output-root $output --qualification deployment-position-mvp-v1 --package-id $campaign --package-id $audit --package-id $incomplete
```

Przekaż wszystkie pakiety danego zbioru w jednym uruchomieniu. Kolejność
argumentów i powtórzony identyfikator pakietu dają tę samą publikację.
Wymagany jest interpreter repozytorium z zależnościami kodeków.
Dotychczasowa ocena techniczna i tryb porównań używają swoich kontraktów.
Kod wyjścia 0 oznacza obecność co najmniej jednej kwalifikowanej próbki.
Kod 2 oznacza raport do przeglądu bez dopuszczonych próbek. Kod 1 oznacza
błąd integralności archiwum, a 3 błąd środowiska lub publikacji.
[Bramki techniczne i porównania](jakosc-eksperymentow.md)

## Dowody i zakres

1. Ocena techniczna sprawdza archiwum, deklarację przypadku, łańcuch dziennika,
   kompletność dowodu, powtarzalność i powiązanie eksportu z powtórzeniem.
   Pokrycie źródła zachowuje liczbę brakujących przypadków. Jednostką
   kwalifikacji jest obserwacja w technicznie dopuszczonym przypadku.
2. Weryfikator eksportu odtwarza pełne ogony rozstawienia i walki dla każdego
   powtórzenia. Kwalifikacja sprawdza hash deskryptora z dziennika i odniesienie
   do wejściowego stanu przypadku. Przypadek z choć jednym niespójnym replay
   zostaje wyłączony w całości.
3. Wspólny predykat D5.1/D5.2 uruchamiany przez weryfikator rozstawienia
   sprawdza model kołowy i zweryfikowany stan rzeczywiście widziany w chwili
   wyboru. Dopuszczenie wymaga zapisanego wyboru i powiązania z konkretnym
   zdarzeniem przemieszczenia. Profil ogranicza stan wejściowy do prostych
   oddziałów bez zdolności, statusów i oczekujących efektów oraz sprawdza hashe
   źródła reguł i wspólnego kodu weryfikacji. Dla przypiętych źródeł akceptuje
   zapis LF lub CRLF. Zmiana źródeł wymaga aktualnej weryfikacji profilu.
   [Wspólny walidator](kolejka-po-c2d1.md#2-d51--wspólna-walidacja-miejsca-rozstawienia) · [Kontrakt replay](eksport-decyzji-kampanii.md)

`rules_status` przy przypadku i obserwacji rozróżnia `confirmed`
(dowód w zadanym zakresie), `unverified` (poza zakresem dowodu) i
`violation` (udokumentowane naruszenie w przypiętym audycie).
`eligibility` przyjmuje `qualified` lub `excluded`. Raport zachowuje
powody wyłączeń, w tym wybór niewykonany, odrzucony, `None`, automatyczne
przejście, niezgodność z profilem i brak pełnego śladu.
Wyniki walki i decyzje poza profilem pozostają diagnostyczne. Poszerzenie
zakresu walki zależy od wspólnej walidacji P6.
[Plan kwalifikacji](plan-danych-testowych.md#d73c-bramka-zgodności-z-regułami-i-użycia-do-uczenia)

Audyt D6.1 zawiera trzy potwierdzone kontrprzykłady. Dla
`priority`/19/`contact` pierwszą decyzją był Ostrzał przy bliskim widocznym
wrogu (pkt 14.c.iv). Dla `random`/19/`exhausted` był to atak
Wyczerpanego (pkt 22.a.i), a dla `random`/11/`pinned` Manewr
Przyszpilonego (pkt 22.b.i). Ponowne wykonanie tych jawnych fixture
potwierdziło przyjęcie przez resolver i zgodne replay. Raport wiąże wyniki
z hashem pliku (warianty LF i CRLF) i wskaźnikiem JSON do konkretnego
zarchiwizowanego przypadku.
[Źródło reguł](../app/static/docs/SZOP_Rozjemca.md) · [Audyt](boty-audit.md#konkretne-ograniczenia-legalności)

## Raport i podział danych

Plik `qualification/<report_key>/qualification.json` jest kanonicznym JSON
powiązanym z hashem profilu i uporządkowaną listą źródeł. Każde źródło podaje
ID pakietu, zakres i hash technicznej oceny. Każdy przypadek podaje
odniesienie do zapisu źródłowego, a odtworzona obserwacja numer z eksportu.
Z dowodu `executions[].evidence` i numeru `index` można odczytać pełny stan,
pozycję i zakres zdarzeń przez `scripts/export_decisions.py expand`.
Publikacja jest atomowa i odbywa się poza katalogiem archiwum.

Celem podziału jest rozdzielenie rodzin map. Rodzinę identyfikuje ścieżka
fixture w repo lub nazwa generatora map. Jedna rodzina obejmuje wszystkie
jej seedy, powtórzenia i zamiany stron. Rodziny o choć jednym identycznym
wejściu łączą się przechodnio. Hash wejścia obejmuje skrót widzianego stanu,
gracza, oddział, strefę i zajęte miejsca, a hash próbki dodaje wybraną pozycję.
Identyfikatorem grupy jest SHA-256 kanonicznego klucza leksykograficznie
pierwszej rodziny w składowej. Reszta z dzielenia identyfikatora przez 10
przypisuje grupę do `train` (0–7), `validation` (8) lub `test` (9).
Raport zlicza obserwacje i unikatowe próbki oraz sprawdza wspólne grupy
i próbki między splitami. Zmiana zestawu pakietów może połączyć rodziny,
dlatego przed uczeniem podział zamraża identyfikator raportu.

## Pilot i przeniesienie

Na 32 przypadkach D7.4c odtworzono 64 wykonania. Profil dopuścił
512 obserwacji rozstawienia reprezentujących 96 unikatowych próbek.
Wszystkie próbki mają jedną rodzinę map i trafiły do `train`. Pilot
potwierdza działanie podziału oraz brak wspólnych grup i próbek między
splitami. Ocena generalizacji wymaga dodatkowych rodzin map.

Raport oznaczył 3960 decyzji walki jako materiał poza profilem, zachował
8480 przejść automatycznych z powodem wyłączenia i wyłączył niekompletną
próbę z limitem aktywacji. Wśród 239 przypadków D6.1 są trzy udokumentowane
naruszenia i 236 przypadków bez potwierdzenia w profilu. Powtórna publikacja
po zmianie kolejności pakietów i dodaniu duplikatu zwróciła identyczne
bajty. Pomiar obejmuje odczyt, obliczenie hashów, replay jedno wykonanie
naraz, podział i publikację. Kwalifikacja korzysta z zachowanych danych
offline i wykonuje zero zapytań SQL. Na Windows z Pythonem 3.13.14
pierwsze uruchomienie zajęło 24,29 s, a powtórzenie 28,75 s. Raport ma
2 054 226 bajtów.
[Pomiary i hashe](experiments/d7_3c/results.json)

Pełna kopia wejść pilota jest lokalnie w
`build/d73c-pilot/archive/packages/`. Na drugi komputer skopiuj trzy
katalogi o ID z polecenia powyżej, wraz z `package.json` oraz `snapshot/`.
Git zawiera narzędzia, instrukcję i kompaktowy raport. Użyj checkoutu
z przypiętymi wersjami reguł i walidacji oraz środowiska Pythona zgodnego
z projektem. Po ponownym uruchomieniu porównaj `report_sha256` w raporcie
kompaktowym z hashem opublikowanego JSON.
[Źródło kampanii](kampania-ze-sladem-decyzji.md#odtworzenie-pilota-i-kopii) · [Import audytu](archiwum-eksperymentow.md#import-historii-d72b)

## Weryfikacja

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -B -X utf8 -m pytest -q --tb=short tests/test_experiment_qualification.py tests/test_bots_audit.py tests/test_agents_deployment.py tests/test_export_decisions.py tests/test_campaign_v1.py tests/test_experiment_archive.py tests/test_experiment_archive_history.py tests/test_experiment_quality.py tests/test_experiment_comparison.py
& $py -B -X utf8 -m pytest -q --tb=short
```

Zaliczono 279 testów celowanych i 4252 w pełnym zestawie. Cztery
ostrzeżenia pochodzą z zależności eksportu Excel i PDF.
