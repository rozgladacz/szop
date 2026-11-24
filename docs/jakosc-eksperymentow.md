# D7.3a — bramka techniczna eksperymentów

`scripts/experiment_quality.py` ocenia opublikowany pakiet offline. Sprawdza
tożsamość i hashe pakietu przez `experiment_archive.verify_package`, następnie
weryfikuje zapisane dowody i przelicza agregat źródłowy z rekordów. Dla D7.1
waliduje też nagłówek, zamrożone wejścia, sumy kontrolne i łańcuch JSONL.
Porównuje zapisane przypadki z planem w manifeście. Odczyt działa bez
zależności aplikacji, na Pythonie 3.11+, również po zmianie źródeł symulatora.

## Uruchomienie

```powershell
$pilot = Get-Content -Raw -Encoding UTF8 docs/experiments/d7_2b/results.json | ConvertFrom-Json
$packages = @($pilot.campaign.full_reference_package_id, $pilot.campaign.stopped_package_id,
              $pilot.history.d5_3b.package_id, $pilot.history.d6_1.package_id)
foreach ($package in $packages) {
    python -I -S -B -X utf8 scripts/experiment_quality.py --archive-root build/experiment-archive/d7_2b-guide-check --package-id $package --output-root build/experiment-quality/d7_3a
}
```

Podaj ścieżkę do katalogu opublikowanych pakietów, którego układ opisuje
[dokumentacja archiwum](archiwum-eksperymentow.md). CLI zapisuje plik pod
`<output-root>/<package_id>/<policy_digest>/quality.json`. Katalog wynikowy
zajmuje osobne drzewo. Powtórzenie dla tego samego pakietu i polityki sprawdza
identyczność pliku bajt w bajt. Rozbieżny plik jest konfliktem. Flaga
`--min-repeats 3` ustawia wyższy próg dowodu i zapisuje raport obok poprzedniego.

| Kod CLI | Znaczenie |
|---|---|
| `0` | Raport zapisany lub potwierdzony. Kompletny pakiet i wszystkie przypadki z kategorią `passed`. |
| `2` | Raport zapisany lub potwierdzony. Wynik `review`, ponieważ są wyłączenia, braki albo nieznana kompletność. |
| `1` | Błąd integralności pakietu. JSON ze statusem `integrity_error` na stderr. |
| `3` | Błąd zapisu, konflikt pliku albo niewłaściwe parametry polityki. JSON ze statusem `publication_error` na stderr. |

Udana publikacja zwraca JSON na stdout z `path`, `created`, `status`,
`completeness` i `coverage`. Błędna składnia polecenia daje standardowy
komunikat `argparse` na stderr i kod `2`. CLI oceny ma własne kody wyjścia.

## Kontrakt raportu dla D7.3b

- `schema` ma wartość `szop.experiment.quality/v1`. `package_id` wiąże raport
  z deskryptorem i hashami snapshotu. `policy_digest` to SHA-256 osadzonego
  obiektu `policy` jako JSON z sortowaniem kluczy, separatorami `,` i `:`,
  kodowaniem ASCII i bez końcowego znaku nowej linii. Polityka obejmuje schemat,
  wersję decyzji, minimalną liczbę powtórzeń, wymaganie dotyczące replay i
  kolejność przyczyn. Zmiana logiki decyzji wymaga nowej wersji polityki.
- `integrity` ma wartość `verified` w każdym opublikowanym raporcie.
  `completeness` przyjmuje `complete`, `partial` lub `unknown`. Udokumentowany
  brak w dowolnej grupie wystarcza do `partial`. `coverage` pokazuje sumę
  przypadków, a `groups` liczy je według rodzajów prób. `planned` i `missing`
  mają wartość `null`, jeśli archiwum nie rozstrzyga ich wartości. Powtórzenia
  służą jako dowód. Jednostką liczenia jest przypadek.
- Do łączenia danych używaj `package_id`, `case_id` i `group`, a do filtrowania
  zakresu dowodu `category` i `replay.scope`. D7.1 i D5.3b zachowują pełne
  współrzędne `case` z manifestu, łącznie z ID runnera, fixturą, polityką,
  seedem, zamianą stron, inicjatywą i strategiami. D6.1 używa skrótu z nazwy
  grupy i kluczy próby. `evidence` wskazuje plik w `snapshot/` oraz JSON
  Pointer od korzenia obiektu. D7.1 używa dodatkowo `line` liczonego od 1.
- `category` to pierwsza pozycja z `reasons` według kolejności polityki albo
  `passed`. Suma `categories` równa się `recorded`. `reasons` liczy wszystkie
  przyczyny, w tym współwystępujące. `deployment_error`, `match_error` i
  `activation_cap` pozostają w `recorded`. `outcomes` zlicza tylko przypadki
  `passed` z jawnym polem `winner` w zakończonym meczu. Klucze to `player_0`,
  `player_1` i `draw`. Jawny `winner: null` w takim rekordzie oznacza remis.
  Brak pola, np. w próbie zakończenia D6.1, pozostawia `outcome: null`.
- `recorded_reproducible: false` daje `non_reproducible`. Przy deklaracji
  `true` nadal wymagane są próbki dokumentujące co najmniej próg polityki i
  liczbę wykonań zadeklarowaną w manifeście, jeśli ten ją podaje. Sygnał
  `replay_equal: false` albo status runnera `replay_error` daje `replay_error`.
  Brak potwierdzenia równości lub wymaganych skrótów daje
  `missing_replay_evidence`.
- Zakres `match` wymaga zapisanej zgodności replay oraz digestów zdarzeń i
  stanu końcowego. D6.1 ma też próbę `decision` z zakresem replay `activation`
  i digestem stanu aktywacji. Akceptacja pierwszej akcji przez resolver jest
  obserwacją. Odrzucona akcja ma `decision_rejected`, a przerwana obserwacja
  po akceptacji może dostać `decision_error`. Przy braku akcji w próbie
  `decision` dowód replay pozostaje nieobecny. Próby `deployment` D6.1 mają
  zakres `none` i zachowują status zapisanego wyniku rozstawienia. Manifest
  audytu podaje fixtury, a dobór polityk do prób fixtur zależał od ówczesnego
  rejestru. W tej grupie plan i braki pozostają `null`.

`passed` opisuje techniczny wynik danego zakresu zapisanego dowodu. W wersji
v1 dowód pochodzi z porównania zapisanego przez runner. Niezależna weryfikacja
pełnego replay wymaga ogona zdarzeń z D7.4b. D7.3b może użyć raportu jako
wejścia do osobnej kontroli projektu eksperymentu i par. Kwalifikację do
uczenia określi D7.3c. Przy konsumpcji raportu weryfikuj `schema`, `package_id`
i właściwy `policy_digest` oraz ponownie sprawdzaj pakiet, jeżeli dane były
kopiowane lub raport pochodzi z niezweryfikowanego źródła.

## Pilot i przeniesienie

| Pakiet | Zapisane / plan | Przeszły technicznie | Stan | Bajty snapshotu | Mediana oceny |
|---|---:|---:|---|---:|---:|
| D7.1 pełny | 32 / 32 | 32 | `passed` | 87 346 | 16,8 ms |
| D7.1 zatrzymany | 8 / 32 | 8 | `partial`, 24 brakujące | 31 231 | 14,3 ms |
| D5.3b | 480 / 480 | 480 | `passed` | 1 009 389 | 80,1 ms |
| D6.1 | 239 / `null` | 167 | `review`, 72 bez dowodu replay | 227 246 | 27,3 ms |

Mediany z 10 odczytów po rozgrzaniu bufora plików na Windows, Python 3.12.14.
Pomiar `perf_counter_ns` obejmuje `evaluate` bez startu procesu i zapisu
raportu. Dane przechodzą przez odczyt i hashowanie oraz stałą liczbę przejść
po rekordach. Koszt zależy liniowo od bajtów i liczby przypadków w granicach
formatu. Przy małych pakietach znaczną część czasu zajmuje sprawdzanie ścieżek
i samych plików.

[Kompaktowy wynik](experiments/d7_3a/results.json) zawiera identyfikatory
i skróty pełnych raportów. Ponowne oceny są identyczne bajtowo, a surowszy
profil pozostawił oryginalny raport. Bajty źródłowego archiwum po pilocie
pozostały identyczne. Aby kontynuować na innym komputerze, pobierz gałąź
`Faza_A` i osobno skopiuj `packages/` z `build/experiment-archive/d7_2b-guide-check/`.
Katalog `build/experiment-quality/d7_3a/` zawiera pełne raporty z pilota. Można
go skopiować albo odtworzyć raporty z tych samych pakietów według poleceń
powyżej i porównać SHA-256 z wynikiem kompaktowym. Same źródła D5.3b i D6.1
są wersjonowane w Git i można je ponownie zaimportować. Przeniesienie
pakietów D7.1 wymaga kopii ich snapshotów. Format D7.2 zachowuje hashe
surowych plików, więc import z inną konwencją końców linii może stworzyć inny
identyfikator pakietu historycznego.

## Weryfikacja regresji

Zestaw celowany zaliczył 86 testów, łącznie z archiwum historii. Drugi pełny
przebieg zaliczył 4198 testów z 4 ostrzeżeniami deprecjacji zależności.
W pierwszym przebiegu pomiar progu wydajności `/quote` przekroczył 1,3
(najlepszy współczynnik 1,323). Test przeszedł w izolacji i w powtórzonej
pełnej suicie.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_experiment_quality.py tests/test_experiment_archive.py tests/test_experiment_archive_history.py tests/test_campaign_v1.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```

Warstwy zmiany to pliki archiwum i raportu, CLI offline oraz testy i
dokumentacja. Ocena używa ścieżek danych snapshotu i wykonuje zero zapytań SQL.
