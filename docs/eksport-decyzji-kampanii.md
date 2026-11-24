# D7.4b — eksport decyzji i odtworzenie

CLI zapisuje jeden przebieg wybranego przypadku kampanii v1. Odczyt
odtwarza stan widziany przy wyborze, stan przed wykonaniem, skutek i
pełny ogon gry. Eksport używa adaptera `deployment_experiment.run_once`
i jego obserwatora. D7.4c wykorzysta ten format przy trwałym powiązaniu
śladu z dziennikiem kampanii. [Kontrakt obserwatora](obserwacja-decyzji-kampanii.md)

## Uruchomienie

```powershell
$exporter = 'scripts/export_decisions.py'
$manifest = 'docs/experiments/d7_1/manifest.json'
$package = 'build/decision-export/example'
.\.venv\Scripts\python.exe -B -X utf8 $exporter export --manifest $manifest --case 762b987db7935fad6f8e --repeat 1 --run-label d7-4b-example $package
.\.venv\Scripts\python.exe -B -X utf8 $exporter verify $package
.\.venv\Scripts\python.exe -B -X utf8 $exporter expand $package
```

`export` i `verify` zwracają JSON deskryptora. `expand` zwraca JSONL
z obserwacjami, stanami i zdarzeniami po zweryfikowaniu całego pakietu.
Kod 0 oznacza kompletny przebieg z potwierdzonym replay. Kod 2 oznacza
niekompletny przebieg z dostępnym prefiksem lub błąd składni polecenia.
Kod 1 oznacza błąd pliku, integralności lub odtworzenia.

Przy zbieraniu każdego nowego zestawu powtórzeń nadaj osobną etykietę
`--run-label`. Powtórzenia tej samej kampanii otrzymują tę samą etykietę
i różne `--repeat`. Numer powtórzenia identyfikuje wykonanie. Adapter
używa tych samych seedów dla kolejnych powtórzeń danego przypadku.
Katalog wyjściowy jest nowy dla każdego wykonania. Zapisy poszczególnych
plików są atomowe, a deskryptor powstaje na końcu. Po awarii zapisu
katalog bez deskryptora wymaga inspekcji, a CLI odrzuci jego odczyt.

## Kontrakt `szop.decision_export/v1`

Pliki mają kanoniczny JSON z sortowaniem kluczy, bez wcięć, z zapisem znaków
spoza ASCII jako sekwencji JSON i końcowym LF. Każda linia JSONL stosuje
ten sam kontrakt. Pakiet zawiera dokładnie sześć zwykłych plików.

| Plik | Zawartość |
|---|---|
| `export.json` | Wersja pakietu i kodeków, hashe pozostałych plików, tożsamość, seedy, źródła, liczniki, status zbierania, dowód odtworzenia i wynik kompletnej gry. |
| `manifest.json` | Kanoniczna kopia jawnego manifestu `szop.deployment_experiment/v1` z fixture kampanii v1. |
| `states.json` | Stan przed rozstawieniem `initial` i stan po rozstawieniu `deployed`, w kodeku `szop.battle_state` v1. W niekompletnym pakiecie niedostępne stany mają wartość `null`. |
| `deployment.jsonl` | Ogon rozstawienia. Sekwencja zaczyna się od 1. |
| `battle.jsonl` | Ogon gry od stanu `deployed`. Sekwencja zaczyna się ponownie od 1. |
| `decisions.jsonl` | Obserwacje wyborów i przejść automatycznych w porządku otrzymanym od D7.4a. Numer `index` zaczyna się od 1. |

Klucz obserwacji to `(run_id, case.id, repeat, index)`. `campaign_id`
pochodzi z tożsamości zgodności D7.1. `run_id` jest skrótem schematu,
`campaign_id` i jawnej etykiety. `origin.kind=manifest_resimulation`
znaczy, że obserwacje pochodzą z nowego wykonania. `origin.manifest_base_commit`
wskazuje rewizję wpisaną w manifest, a `source.source_commit` zapisuje
HEAD przy zbieraniu. Hashe źródeł adaptera, fixture i eksportera opisują
faktycznie użyty kod również przy roboczym checkoutcie. `seeds` podaje seed
gry, seedy przekazane polityce dla P0 i P1 po uwzględnieniu zamiany armii
oraz seed generowanej mapy, gdy występuje. Czas służy do osobnego pomiaru
pilota. Pakiet zawiera zdarzenia istniejącego kodeka, w tym pola
`MoraleTestPassed`. Wejście ogranicza się do jawnych fixture i seedów.

### Wybory, stany i zdarzenia

Przedział `events=[start, stop]` obejmuje indeksy od `start` włącznie
do `stop` wyłącznie, licząc od zera w odpowiednim ogonie. `null`
oznacza brak przypisanych zdarzeń. Odniesienie do stanu podaje `offset`
po zastosowaniu tylu zdarzeń i SHA-256 kanonicznego stanu bez końcowego LF.
W rozstawieniu `deployment_finished.after` odpowiada stanowi `deployed`
z uwzględnieniem zmiany rundy. Inny widziany stan przy tym samym
`offset` jest identyfikowany przez kontekst rekordu i jego digest.

- `choose_deployment` zapisuje stronę, oddział, strategię, strefę,
  poprzednie zajęte miejsca (ID oddziałów z pozycjami w `seen`),
  przydziały celów, wynik wyboru i pozycję `[x,y]`. Przyjęty wybór
  dostaje `placement_index`. Jego zakres wskazuje ruch, gdy taki ruch
  nastąpił. Rekord `deployment_moved` opisuje to samo zdarzenie od
  strony wykonania. Roboczy stan poza zapisanym ogonem ma `snapshot`
  zamiast `offset`, na przykład po wyborach, które nie doczekały się
  wykonania wskutek późniejszego odrzucenia.
- `choose_action` i `continue_activation` zapisują faktyczny wybór w
  kodeku `szop.action` v1 albo `null`, kontekst wcześniejszych akcji,
  stronę, wynik i kod powodu odrzucenia lub błędu z obserwatora. Dla
  wykonanej akcji dostępne są osobne `seen`, `before` i `after`.
  Pierwszy wybór może widzieć stan sprzed `activation_started`.
  Odmowa, brak wyboru i błąd nie przypisują skutków akcji. Przy błędzie
  wykonania może zachować się `before`.
- Przejścia automatyczne zachowują swoje zdarzenia i stany brzegowe.
  `activation_stopped` oznacza automatyczny stop bez kolejnego wywołania
  polityki. Faktyczne `None` ma osobny rekord decyzji. Następujące po
  sobie akcje mają własne rozłączne przedziały.

`verify` sprawdza spójność przedziałów względem kolejności obserwacji,
liczniki, ciągłość oraz kształt zdarzeń. Stosuje `deployment_round` do
zapisanych pozycji, sprawdza stan po rozstawieniu i przechodzi ogon
gry raz przez `apply_events`. Sprawdza skróty stanów, wynik i digest
pełnego logu zwrócony przez runner. `StatusAdded` odbudowuje kanoniczną
`StatusFlag` runnera v1 przez istniejący enum. Kodek zdarzeń zapisuje tę
wartość jako tekst, natomiast kodek stanu zachowuje typ.

Błąd zbierania ma `status=incomplete`, `replay.status=prefix_only` i
`result=null`. Weryfikator sprawdza dostępny prefiks. Klasa błędu wystarcza
do identyfikacji przypadku w eksporcie. Diagnostyka rozszerzona jest
poza pakietem. Weryfikacja jest offline na zgodnym checkoutcie.
Hashe zapewniają kontrolę spójności, a zaufanie do pochodzenia wymaga
zachowania oryginalnego deskryptora i kontroli dostępu. Dowód D7.4b
obejmuje zarejestrowane wejścia, przebieg i skutek według runnera v1.
Kwalifikacja do uczenia wymaga D7.3c.

## Pilot, rozmiar i powtórzenie

Raport zawiera hashe, seedy, liczniki i pomiary na Windows, Python
3.13.14. Pole HEAD
wskazuje bazę D7.4a. Hash eksportera wskazuje kod tego etapu użyty
podczas pilota. Czasy obejmują start osobnych procesów Pythona i operacje
na lokalnych plikach. W każdym z dwóch przypadków oba powtórzenia
zapisały identyczne pliki danych i dały identyczny wynik gry.
[Wynik pilota](experiments/d7_4b/results.json)

| Przypadek | Decyzje | Zdarzenia rozstawienia + gry | Rozmiar pakietu | Bajty pakietu na decyzję | Eksport | Weryfikacja |
|---|---:|---:|---:|---:|---:|---:|
| `762b987db7935fad6f8e` | 72 | 16 + 236 | 143 608 B | 1994,56 | 2028–2145 ms | 1848–1876 ms |
| `28256c014c9a157731df` | 70 | 16 + 231 | 139 758 B | 1996,54 | 1972–2106 ms | 1624–1657 ms |

Oba pakiety rozwinęły się do kompletnych obserwacji i skutków. Trzecia
próba z `max_activations=1` zachowała 10 decyzji, 16 zdarzeń
rozstawienia i 7 zdarzeń gry. `verify` zwrócił 2 i `prefix_only`.
Budżet roboczy na pilot D7.4c wynosi 256 KiB na wykonanie, czyli 16 MiB
dla 32 przypadków z dwoma powtórzeniami. To budżet pakietów w tym
formacie, wyznaczony z dwóch próbek. Rozwinięty JSONL zawiera pełne stany
i zajmie więcej miejsca. Weryfikacja i publikacja przetwarzają dane
jednego wykonania naraz i nie wykonują zapytań SQL.

```powershell
$exporter = 'scripts/export_decisions.py'
$manifest = 'docs/experiments/d7_1/manifest.json'
$output = 'build/decision-export/d7_4b-reproduction'
foreach ($caseId in '762b987db7935fad6f8e', '28256c014c9a157731df') {
    foreach ($repeat in 1, 2) {
        $package = Join-Path $output "${caseId}-r${repeat}"
        .\.venv\Scripts\python.exe -B -X utf8 $exporter export --manifest $manifest --case $caseId --repeat $repeat --run-label d7-4b-pilot $package
        .\.venv\Scripts\python.exe -B -X utf8 $exporter verify $package
    }
}
$partialManifest = Join-Path $output 'prefix-manifest.json'
$partialPlan = Get-Content $manifest -Encoding utf8 -Raw | ConvertFrom-Json
$partialPlan.max_activations = 1
$partialPlan | ConvertTo-Json -Depth 8 | Set-Content $partialManifest -Encoding utf8
$partialPackage = Join-Path $output 'activation-cap'
.\.venv\Scripts\python.exe -B -X utf8 $exporter export --manifest $partialManifest --case 762b987db7935fad6f8e --repeat 1 --run-label d7-4b-pilot $partialPackage
.\.venv\Scripts\python.exe -B -X utf8 $exporter verify $partialPackage
```

Pierwotne pakiety są lokalnie w `build/decision-export/d7_4b-pilot-final/`.
Kopia tego katalogu przenosi pełne pakiety wraz z oryginalnymi
deskryptorami. Na innym komputerze checkout tego etapu, ten sam manifest
i środowisko z raportu pozwalają odtworzyć i sprawdzić pliki danych.
HEAD może zmienić pole rewizji w deskryptorze, gdy kod oraz pozostałe
źródła i zależności są identyczne. Wcześniejsze kampanie wznawia się
na checkoutcie zgodnym z ich fingerprintem.
[Zgodność źródeł D7.1](trwala-kampania-v1.md#kontrakt-implementacji)

## Weryfikacja

Końcowy przebieg zaliczył 204 testy celowane i 4238 testów w pełnym
zestawie. Pełny zestaw zgłosił cztery ostrzeżenia deprecjacji bibliotek.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_export_decisions.py tests/test_agents_match.py tests/test_engine_multi_action.py tests/test_engine_replay_invariant.py tests/test_engine_action_codec.py tests/test_deployment_experiment.py tests/test_campaign_v1.py tests/test_experiment_archive.py tests/test_experiment_quality.py tests/test_clients_local.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```

Audyt wywołań objął `export_case` i `verify_package` w CLI i testach
oraz wywołania istniejącego adaptera i kodeków. Tryb domyślny runnera
działa przez dotychczasowe wejścia. W tym środowisku przegląd kodu
i uproszczeń wykonano ręcznie. Obejmował pojedynczy przebieg ogona,
powtórne użycie skrótów stanów, kanoniczny odczyt typów, granice plików
oraz rozróżnienie dowodu pełnej gry i prefiksu.
