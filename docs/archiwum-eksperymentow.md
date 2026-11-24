# D7.2 — wspólny katalog eksperymentów

CLI publikuje zweryfikowany stan kampanii D7.1 w wybranym lokalnym katalogu
oraz zachowane wyniki D5.3b i D6.1. Wyszukuje pakiety po identyfikatorze,
typie, scenariuszu oraz zapisanej rewizji. Jeden `campaign_id` może mieć
kilka pakietów, np. kopię zatrzymaną
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

## Pilot i odbiór D7.2a

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

## Import historii D7.2b

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
$archiveTool = (Resolve-Path scripts/experiment_archive.py).Path
$archiveRoot = 'build/experiment-archive'
& $python -B -X utf8 $archiveTool import-history --archive-root $archiveRoot --type deployment_experiment_v1 --experiment docs/experiments/d5_3b
& $python -B -X utf8 $archiveTool import-history --archive-root $archiveRoot --type bots_audit_v1 --experiment docs/experiments/d6_1 --report docs/boty-audit.md
```

| Typ | Dane w `snapshot/` | Jednostka zliczania |
|---|---|---|
| `deployment_experiment_v1` | D5.3b: manifest, wyniki JSON, README i raport Markdown | 480 różnych przypadków rozstawienia. Manifest przewiduje dwa powtórzenia, a wiersze zawierają 960 próbek czasu. |
| `bots_audit_v1` | D6.1: manifest, wyniki, analiza stron, próba transportu i raport `boty-audit.md` | 162 przypadki decyzji, 54 rozstawienia, 9 zakończenia i 14 prób fixture, łącznie 239 i 478 próbek czasu. Analiza stron korzysta z D5.3b, a próba transportu jest dodatkowym dowodem. |

Deskryptor zapisuje `case_counts` według typów przypadków, `timing_samples`
według tych samych typów oraz `declared_repeats` z manifestu, jeśli jest.
Pole `evidence` określa rodzaj `historical_results`, powiązanie wyniku
z manifestem i obecność zapisanych odcisków źródeł. Odciski są deklaracją
historycznego narzędzia. Do potwierdzenia zgodnego checkoutu służy osobny
test D7.1. `unknown` oznacza brak dowodu wiązania lub odcisków,
a JSON `null` brak zapisanej rewizji, deklaracji powtórzeń lub kompletu
próbek czasu dla danej grupy. `campaign_journal: false` informuje o braku
pełnego dziennika. Wiersze z próbami i flagą odtwarzalności są dowodem
zachowanym z poprzedniego przebiegu.

D5.3b zapisał hash manifestu w wersji CRLF. Adapter sprawdza surowy hash
i uwzględnia różnicę końców linii LF/CRLF w checkoutcie. `manifest_binding`
wskazuje porównanie z plikiem lub wariantem końców linii. Bajty wejściowe
są kopiowane bez konwersji, więc zmiana końców linii zmienia ID pakietu.
D6.1 ma osadzony manifest i jego hash kanonicznego JSON. Porównanie
obejmuje obie deklaracje, jeśli są obecne.

Oba typy używają tej samej blokady publikacji, katalogu, deduplikacji
i poleceń `list` oraz `verify`. Każdy adapter ma zamknięty zestaw plików
i waliduje format, liczbę zapisanych przypadków oraz wiązanie z manifestem.
Import uruchamiaj na stabilnej kopii plików historycznych. Sprawdzenie
gotowego pakietu wymaga tylko Python i skryptu. Dialekty archiwalne,
plik wyników D7.1 i inne formaty wymagają własnego adaptera lub pełnego
pakietu natywnego.

## Backup i odtworzenie

1. Zatrzymaj wykonanie i opublikuj natywny snapshot. Zachowaj cały katalog
   `packages/<package_id>/` razem z deskryptorem, manifestem, dziennikiem,
   wejściami, raportem i sumami. Zachowaj w ten sam sposób opublikowane
   pakiety historii. Jeśli cytujesz pakiet albo korzystasz z niego do
   uczenia, zapisz również ID, rewizję zgodnego checkoutu, wersje środowiska
   i powiązany raport. Archiwizując przyszłe pełne eksporty, przechowuj
   je razem z ich manifestem i weryfikowalną kopią.
2. Skopiuj kompletne opublikowane katalogi na zatwierdzony nośnik lub
   do kopii poza hostem źródłowym. W miejscu docelowym uruchom `list`
   oraz `verify` dla każdego skopiowanego ID i zapisz wyniki w rejestrze
   backupu. Katalog powstaje z deskryptorów. Blokada robocza i katalogi
   `.import-*` nie są danymi backupu. Wymiana nośnika i retencja są ręczne.
3. Na docelowym hoście odtwórz `packages/` w pustym katalogu i powtórz
   weryfikację. Do wznowienia wybierz pakiet `campaign_v1`, skopiuj jego
   `snapshot/` do nowego katalogu roboczego i użyj odnotowanego checkoutu.
   Wskaż środowisko z rodziną Pythona i wersjami zależności zgodnymi
   z `header.identity`. Zweryfikuj kopię komendą D7.1 przed `resume`.
   Realizację prowadź w jednym katalogu roboczym na jednym hoście.
4. Jeśli plik lub pakiet jest uszkodzony, zachowaj go do diagnozy i odtwórz
   identyczny pakiet z drugiej zweryfikowanej kopii do pustego katalogu.
   Gdy pozostał zweryfikowany częściowy snapshot, można wznowić go od
   potwierdzonego prefiksu. Historyczny pakiet można ponownie opublikować
   z zachowanych oryginałów. Sprawdź, czy odzyskane bajty dają oczekiwane
   ID. Gdy nie ma żadnego poprawnego snapshotu D7.1, oznacz brak pełnego
   dziennika i rozpocznij nowy przebieg, jeśli jest potrzebny.
   [Kompaktowy wynik D7.1](experiments/d7_1/results.json) zachowuje
   dowód z pilota.

### Powtórzenie pilota D7.2b

Poniżej `$sourceArchive` wskazuje zweryfikowany backup D7.2a lub równoważne
lokalne źródło z częściowym i pełnym pakietem, do którego można dołożyć oba
importy historyczne. Jeśli kopii pilota D7.2a nie ma, wykonaj w zgodnym
checkoutcie `start --max-cases 8`, opublikuj część, wykonaj
`resume --max-cases 24` i opublikuj pełny pakiet. Użyj manifestu D7.1
i aktualnych ID z publikacji.

```powershell
$sourceArchive = (Resolve-Path 'build/experiment-archive/d7_2b-pilot/source').Path
$backupRoot = Join-Path (Get-Location) 'build/experiment-archive/recovery-example'
if (Test-Path -LiteralPath $backupRoot) { throw 'Podaj pusty katalog odzyskiwania' }
$null = New-Item -ItemType Directory -Path (Join-Path $backupRoot 'packages')
Get-ChildItem -LiteralPath (Join-Path $sourceArchive 'packages') -Directory |
    Where-Object { $_.Name -cmatch '^[a-f0-9]{64}$' } |
    ForEach-Object {
        $bytes = (Get-ChildItem -LiteralPath $_.FullName -File -Recurse | Measure-Object Length -Sum).Sum
        $elapsed = Measure-Command {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $backupRoot 'packages') -Recurse -ErrorAction Stop
        }
        Write-Output "$($_.Name) $bytes B $($elapsed.TotalMilliseconds) ms"
        & $python -B -X utf8 $archiveTool verify --archive-root $backupRoot --package-id $_.Name
        if ($LASTEXITCODE -ne 0) { throw 'Pakiet z kopii nie przeszedł verify' }
    }
$catalog = (& $python -B -X utf8 $archiveTool list --archive-root $backupRoot | ConvertFrom-Json).packages
$stopped = $catalog | Where-Object {
    $_.type -eq 'campaign_v1' -and $_.committed_cases -eq 8 -and $_.planned_cases -eq 32
}
if (@($stopped).Count -ne 1) { throw 'Wskaż ID zatrzymanego pakietu' }
$restored = Join-Path $backupRoot 'work-campaign'
Copy-Item -LiteralPath (Join-Path $backupRoot "packages/$($stopped.package_id)/snapshot") -Destination $restored -Recurse
$checkout = Join-Path $backupRoot 'checkout'
git worktree add --detach $checkout 1592aaf6d68d0e455ab3fba346d1605ce0f50d87
if ($LASTEXITCODE -ne 0) { throw 'Checkout do odzyskiwania nie powstał' }
```

Na tym hoście można użyć zgodnej istniejącej `.venv` wskazanej przez
`$python`. Przy odtwarzaniu środowiska użyj Pythona 3.13 i zależności
projektu z dopasowaniem do `header.identity.dependencies`. Dla tego pilota
były to PyYAML 6.0.1, pydantic 2.13.4 i pydantic_core 2.46.4.

```powershell
Push-Location $checkout
try {
    & $python -B -X utf8 scripts/campaign_v1.py verify --directory $restored
    if ($LASTEXITCODE -ne 0) { throw 'Kopia kampanii nie przeszła verify' }
    & $python -B -X utf8 scripts/campaign_v1.py resume --directory $restored --max-cases 24
    if ($LASTEXITCODE -ne 0) { throw 'Wznowienie pilota nie zakończyło 32 przypadków' }
    & $python -B -X utf8 scripts/campaign_v1.py verify --directory $restored
    if ($LASTEXITCODE -ne 0) { throw 'Dziennik po wznowieniu nie przeszedł verify' }
    $checksums = (Get-FileHash -LiteralPath (Join-Path $restored 'checksums.json')).Hash
    $noop = & $python -B -X utf8 scripts/campaign_v1.py resume --directory $restored --max-cases 1 | ConvertFrom-Json
    & $python -B -X utf8 scripts/campaign_v1.py verify --directory $restored
    if ($LASTEXITCODE -ne 0 -or $noop.committed -ne 0 -or
        (Get-FileHash -LiteralPath (Join-Path $restored 'checksums.json')).Hash -ne $checksums) {
        throw 'Kampania zmieniła się po zakończeniu'
    }
} finally {
    Pop-Location
}
```

Poniższe porównanie obejmuje 32 kolejne wiersze dziennika i podsumowanie
raportu z pełnego pakietu tego samego `campaign_id`. Czasy i metadane
poszczególnych zapisów mogą się różnić.

```powershell
$full = $catalog | Where-Object {
    $_.campaign_id -eq $stopped.campaign_id -and $_.committed_cases -eq 32
}
if (@($full).Count -ne 1) { throw 'Wskaż ID pełnego pakietu referencyjnego' }
$reference = Join-Path $backupRoot "packages/$($full.package_id)/snapshot"
@'
import hashlib
import json
from pathlib import Path
import sys

def results(folder):
    journal = (folder / "journal.jsonl").read_bytes().splitlines()
    rows = [json.loads(line)["row"] for line in journal]
    return [{key: row[key] for key in ("case", "result", "reproducible")} for row in rows]

def summary(folder):
    report = (folder / "report.md").read_text(encoding="utf-8")
    return json.loads(report.split("```json\n", 1)[1].split("\n```", 1)[0])

restored, reference = map(Path, sys.argv[1:])
rows = results(restored)
assert len(rows) == 32 and rows == results(reference)
assert summary(restored) == summary(reference)
print(hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True, allow_nan=False).encode()).hexdigest())
'@ | & $python -B -X utf8 - $restored $reference
if ($LASTEXITCODE -ne 0) { throw 'Rozbieżność wyników pilota' }
```

### Wynik pilota D7.2b

[Wynik i hashe](experiments/d7_2b/results.json) obejmują realne importy
D5.3b i D6.1 z zachowaniem bajtów oraz udaną deduplikację obu. Katalog
odbudowano z czterech pakietów i zweryfikowano samym skryptem. Kopiowanie
na lokalnym dysku trwało 41,5 ms dla 1 359 774 B. Zatrzymany pakiet
D7.1 z deskryptorem miał 32 356 B, a jego kopiowanie trwało 14,7 ms.
Pomiary nie obejmują weryfikacji, symulacji ani transferu sieciowego.

W osobnym checkoutcie na tym samym komputerze Windows potwierdzono 61
hashy plików dla rewizji `1592aaf6d68d0e455ab3fba346d1605ce0f50d87`.
Kopia D7.1 zachowała pierwotne 8 wierszy, wznowiła 24 przypadki i osiągnęła
32/32. Wyniki deterministyczne i podsumowanie były zgodne z pełną
referencją. Kolejne wznowienie zapisało 0 przypadków i zachowało bajty
wszystkich plików kampanii. Pełne pakiety pozostają poza Git w lokalnym
`build/` i wymagają oddzielnego backupu.

Testy celowane dały **60 passed**, a pełny pytest **4172 passed**
i cztery ostrzeżenia zależności. Przegląd wywołań objął import, odczyt
i istniejącą publikację D7.1. Przegląd plików objął kompletność zestawu,
dowiązania, blokadę, zmianę źródła podczas kopiowania i odmowę nadpisania
uszkodzonego pakietu. Narzędzie działa w warstwie plików i wykonuje 0 SQL.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_experiment_archive_history.py tests/test_experiment_archive.py tests/test_campaign_v1.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```
