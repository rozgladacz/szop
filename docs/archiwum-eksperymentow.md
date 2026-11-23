# D7.2a — wspólny katalog eksperymentów

CLI publikuje zweryfikowany stan kampanii D7.1 w wybranym lokalnym katalogu
i wyszukuje pakiety po identyfikatorze, typie, scenariuszu oraz zapisanej
rewizji. Jeden `campaign_id` może mieć kilka pakietów, np. kopię zatrzymaną
i pełną. Wiersze katalogu pochodzą z deskryptorów, więc katalog odbudowuje się
automatycznie po przeniesieniu katalogu `packages`.

## Użycie

Import wykonaj z checkoutu i środowiska zgodnych z kampanią. Przykład
zakłada gotową kampanię w osobnym katalogu roboczym. Rodzic katalogu
archiwum może nie istnieć i zostanie utworzony podczas importu.

```powershell
$archiveRoot = 'build/experiment-archive'
$campaignDir = 'build/campaigns/example'
$publication = .\.venv\Scripts\python.exe -X utf8 scripts/experiment_archive.py import --archive-root $archiveRoot --campaign $campaignDir | ConvertFrom-Json
.\.venv\Scripts\python.exe -X utf8 scripts/experiment_archive.py list --archive-root $archiveRoot --type campaign_v1 --scenario demo_skirmish
.\.venv\Scripts\python.exe -X utf8 scripts/experiment_archive.py list --archive-root $archiveRoot --revision $publication.package.recorded_revision
.\.venv\Scripts\python.exe -X utf8 scripts/experiment_archive.py verify --archive-root $archiveRoot --package-id $publication.package.package_id
```

Wynik to JSON. `import` zwraca deskryptor w polu `package` i flagę
`created`. Identyczna istniejąca kopia musi przejść weryfikację, zanim
polecenie zwróci `created: false`. `list` czyta deskryptory w kolejności
identyfikatorów i stosuje podane filtry łącznie, także `--package-id`.
`verify` sprawdza również pliki, ich rozmiary i hashe. Kod 0 oznacza
udaną operację, 1 błąd archiwum lub kampanii, 2 błąd składni CLI.

## Format i granice weryfikacji

Pakiet zajmuje `<archive-root>/packages/<package_id>/`. `package.json`
ma schemat `szop.experiment.package/v1`. Typ `campaign_v1` identyfikuje
pakiet natywny D7.1 o `source_schema` równym `szop.campaign/v1`.
Katalog `snapshot/` przechowuje natywną kopię bez roboczej blokady.

| Pole | Znaczenie |
|---|---|
| `package_id` | SHA256 deskryptora bez tego pola. JSON koduje się z sortowaniem kluczy, bez spacji i z `ensure_ascii=True`. |
| `campaign_id` | Tożsamość kampanii wg D7.1. |
| `recorded_revision` | Git HEAD zapisany w `header.base_commit`. Zgodność źródeł do wznowienia ustala D7.1 z hashy i zależności. |
| `scenarios` | Posortowane, unikalne identyfikatory fixture z manifestu. |
| `committed_cases`, `planned_cases`, `completeness` | Potwierdzony prefiks, liczba zaplanowanych przypadków i relacja `partial` lub `complete`. Jest to pokrycie, które trzeba oceniać osobno od jakości wyników. |
| `files` | Mapa względnych ścieżek w `snapshot/` na `size_bytes` i `sha256`. |

Import korzysta z natywnych `archive`, `inspect` i `verify_derived`. D7.1
pod blokadą sprawdza zgodność źródeł, prefiks i łańcuch rekordów oraz
odbudowuje raport i checksums źródła. Po sprawdzeniu kopii i jej pełnej
listy plików CLI zapisuje deskryptor i przenosi cały pakiet jedną operacją
na tym samym systemie plików. Publikacje dla jednego archiwum korzystają z
blokady systemowej `<archive-root>/.lock`. Katalogi `.import-*` pozostałe
po przerwaniu procesu są pomijane przez odczyt.

Odczyt i weryfikacja działają bez importu runnera oraz bez dostępu do jego
źródeł i zależności. Weryfikacja sprawdza zawartość opublikowanej kopii.
Walidacja kampanii przy imporcie i przy ewentualnym wznowieniu pozostaje
odpowiedzialnością D7.1. Hashe kontrolują integralność plików. Zaufanie do
pochodzenia pakietu zależy od kontroli dostępu do katalogu. Pakiety mają
pozostawać niezmienne, a uruchomienia współdzielące katalog muszą respektować
blokadę lokalnego systemu plików. Pakiet przenosi się jako zwykłe pliki
i katalogi. Łącza, punkty ponownej analizy i nazwy kolidujące po przeniesieniu
między systemami są odrzucane.

## Pilot i odbiór

W kampanii na [zamrożonym manifeście D7.1](experiments/d7_1/manifest.json)
wykonano `start --max-cases 8`, import i ponowny import, następnie
`resume --max-cases 24` i import pełnej kopii. Szczegóły startu i wznowienia
opisuje [instrukcja D7.1](trwala-kampania-v1.md). Oba pakiety mają `campaign_id`
`a7419713a34be8760e28a5974307619c90252eab37b3d0098863eefa52b22be4`.
Powtórny import pierwszego zwrócił istniejący wpis. `list` i `verify`
potwierdziły oba wpisy. Pierwszy pakiet zawierał 31 231 bajtów kopii, drugi
87 346 bajtów. Pojedynczy pomiar samego narzędzia na tym dysku dał około
447 i 424 ms dla importów oraz 17 ms dla weryfikacji pełnego pakietu.
Symulacja była mierzona osobno. Na wynik importu wpływa również natywna
kontrola zgodności źródeł oraz zapis na dysku. W tle działały testy celowane.

| Pokrycie | `package_id` |
|---|---|
| 8/32 | `adddf8ed4a7cc64d77c45bde5d1308669ac942bdbcff7b8092f62f6258841f50` |
| 32/32 | `397d3db256431bcc5abadcf14dcb82d80bb23cf25b7517336c092430ee49e94b` |

Regresje D7.2a i kompatybilność D7.1 dały **49 zaliczonych testów**,
w tym 15 nowych. Pełny `pytest` zakończył się wynikiem **4161 passed**
i czterema ostrzeżeniami zależności. Testy objęły przerwanie procesu tuż
przed publikacją, ponowny import, korupcję bez nadpisania, konflikty
publikacji, ścieżki i dowiązania, odbudowę katalogu i weryfikację kopii
samym skryptem w izolowanym Pythonie.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_experiment_archive.py tests/test_campaign_v1.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```

Przegląd wywołań potwierdził, że narzędzie jest używane przez CLI i jego
testy. Ręczny simplify i review ścieżek dodały walidację nazw, listy
plików deskryptora, rozmiarów i hashy przed publikacją. Przebiegi testów
potwierdziły działanie po tych zmianach. Narzędzie wykonuje 0 SQL.

Artefakty pilota są w ignorowanym `build/experiment-archive/d7_2a-pilot`.
Po przeniesieniu skopiuj kompletne opublikowane pakiety, a potem użyj
`list` i `verify`. Do wznowienia zrób osobną kopię `snapshot/` i użyj
procedury D7.1 na zgodnym checkoutcie. Kod, format, manifest i wynik pilota
są wersjonowane. Pełne pakiety z `build/` wymagają osobnego backupu.
Następny zaplanowany etap to [D7.2b](plan-danych-testowych.md#d72b-import-historii-i-odzyskanie-archiwum).
