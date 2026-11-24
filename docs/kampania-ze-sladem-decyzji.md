# D7.4c — trwała kampania ze śladem decyzji

Opcja `start --decision-trace RUN_LABEL` zapisuje ślad każdego faktycznego
wykonania przypadku w formacie [D7.4b](eksport-decyzji-kampanii.md). Runner
oblicza wynik i zbiera obserwacje w tym samym wywołaniu adaptera. Opcja
obowiązuje przy każdym wznowieniu tej kampanii. Zwykły start zachowuje
kontrakt [kampanii D7.1](trwala-kampania-v1.md).

## Start, wznowienie i archiwum

```powershell
$py = '.\.venv\Scripts\python.exe'
$dir = 'build/d74c-example'
$manifest = 'docs/experiments/d7_1/manifest.json'
$archive = 'build/d74c-example-archive'
& $py -B -X utf8 scripts/campaign_v1.py start --manifest $manifest --directory $dir --max-cases 8 --decision-trace d74c-example
& $py -B -X utf8 scripts/campaign_v1.py resume --directory $dir --max-cases 24
& $py -B -X utf8 scripts/campaign_v1.py verify --directory $dir
$published = & $py -B -X utf8 scripts/experiment_archive.py import --archive-root $archive --campaign $dir | ConvertFrom-Json
& $py -I -S -B -X utf8 scripts/experiment_quality.py --archive-root $archive --package-id $published.package.package_id --output-root build/d74c-example-quality
```

Nadaj nową `RUN_LABEL` dla każdego nowego przebiegu tej samej macierzy.
Wznowienie korzysta z etykiety w `header.json`. Powrót do wcześniejszej
kampanii wymaga checkoutu i środowiska zgodnych z jej fingerprintem.
Porównanie źródeł śledzonego przebiegu obejmuje też hash eksportera.

## Trwałość i jakość

- `decision_trace` w `header.json` ma schemat
  `szop.campaign.decision_trace/v1`, etykietę i hash eksportera. Dziennik
  trwałej kampanii wiąże każdy przypadek z osobnym identyfikatorem próby
  oraz listą odsyłaczy w kolejności powtórzeń. Odsyłacz utrwala status
  oraz SHA-256 `export.json` dla zapisanego śladu. Pliki pod
  `traces/<próba>/<powtórzenie>/` mają schemat `szop.decision_export/v1`
  z `origin.kind=campaign_execution`.
- Runner zatwierdza odsyłacz dziennika po zapisie i weryfikacji śladu.
  Synchronizacja plików wykorzystuje `fsync`, blokadę procesu i atomiczne
  podmiany. POSIX synchronizuje również katalogi. Granice trwałości systemu
  plików i procedura `repair-tail` są takie jak w D7.1. Po śmierci procesu
  przed zatwierdzeniem dziennika runner może wykonać przypadek ponownie.
  Nowa próba dostaje nowy katalog. Osierocone pliki pozostają lokalnie.
- Import wspólnego archiwum obejmuje istniejące pliki wskazane przez
  zatwierdzone wpisy dziennika. Sprawdzenie integralności porównuje bajty
  z deskryptorem opublikowanego pakietu. Ocena techniczna wiąże odsyłacz
  z deskryptorem eksportu, źródłami, powtórzeniem i hashami zawartości.
  Pole `decision_trace` przy przypadku wskazuje pliki dowodowe i statusy.
  Braki, uszkodzenia zastane przy publikacji, błąd zbierania, niekompletny
  prefiks oraz rozbieżność między powtórzeniami są przyczynami wyłączenia.
  Rozbieżność z już opublikowanym deskryptorem jest błędem integralności
  pakietu. Wcześniejsze pakiety zachowują dotychczasową politykę oceny.
- `experiment_quality.py` ocenia zapisany dowód w izolowanym Pythonie.
  Niezależne odtworzenie stanów, wyborów i zdarzeń wykonuje
  `scripts/export_decisions.py verify` lub `expand` na katalogu wybranego
  powtórzenia. Niekompletny eksport może zwrócić dostępny prefiks z kodem 2.
  `passed` jest techniczną oceną dowodu dla bieżącego zakresu.

## Odtworzenie pilota i kopii

Pilot korzysta z [manifestu D7.1](experiments/d7_1/manifest.json). Porównuje
pełne 32 przypadki z przebiegiem zatrzymanym po 8 przypadkach i wznowionym
na 24, w osobnych procesach. Porównanie obejmuje wynik, determinizm i pięć
plików danych każdego z 64 powtórzeń. Deskryptory eksportu uwzględniają
tożsamość danego przebiegu, więc etykiety oraz `run_id` różnią się między
pełnym przebiegiem i wznowionym. Nazwy prób, czasy i łańcuchy journalu
mogą się również różnić. Ostatnie wznowienie weryfikuje niezmienność bajtów
zakończonej kampanii. Próba z limitem aktywacji 1 sprawdza wyłączenie
niekompletnego śladu.

```powershell
git worktree add --detach build/d74c-src HEAD
.\.venv\Scripts\python.exe -B -X utf8 docs/experiments/d7_4c/run_pilot.py --output build/d74c --copy build/d74c-copy --fresh-checkout build/d74c-src
```

Uruchom z checkoutu rewizji zapisanej w wyniku pilota, z odpowiednim
środowiskiem Pythona i nowymi katalogami wyjściowymi. Pomiar czasu obejmuje
procesy CLI. Budżet pilota wynosi 256 KiB na jedno wykonanie i 16 MiB dla
64 wykonań. Ślady są zbierane i kodowane po jednym wykonaniu, a ograniczenie
pilota wynika z manifestu i limitu nowych przypadków na wywołanie.

Do odtworzenia oryginalnego pakietu na innym komputerze skopiuj całe
`build/d74c-copy/packages/<package_id>/`, łącznie z `package.json` i
`snapshot/`. Pilot sprawdza kopię w świeżym checkoutcie na tym samym
komputerze. Zatrzymaną kampanię można przenieść osobno, kopiując jej
pełny katalog po zakończonym wywołaniu runnera. Osierocone pliki zostają
w źródłowym katalogu do inspekcji. Hashe sprawdzają integralność kopii.

## Wynik pilota z 2026-11-24

Rewizja źródłowa `7728eb1737325e5410d37b68922bbc865ef843c4`. Windows,
Python 3.13.14. Przebiegi pełny i 8 → 24 dały te same wyniki i hashe pięciu
plików danych w każdym z 64 wykonań. Wznowienie zakończonego przebiegu
zwróciło zero nowych przypadków i nie zmieniło żadnego pliku danych.
Ponowny import zwrócił ten sam identyfikator pakietu. Raport techniczny
pełnej kopii był identyczny bajt w bajt na świeżym checkoutcie. Niezależny
replay pierwszego powtórzenia z kopii odtworzył 196 obserwacji, w tym
decyzje z odtworzonym stanem oraz zdarzeniami skutku.

| Pomiar | Wynik |
|---|---:|
| Przypadki z oceną techniczną `passed` | 32/32 |
| Decyzje / obserwacje | 4 472 / 12 952 |
| Ślady / największe wykonanie | 8 964 644 B / 144 984 B |
| Pełny pakiet, suma plików snapshotu | 9 111 241 B |
| Start pełny / start do 8 / wznowienie 24 | 20,26 s / 5,89 s / 14,76 s |
| Import pełny / ponowny import | 4,39 s / 4,83 s |
| Weryfikacja kopii / ocena kopii | 0,34 s / 0,51 s |

Zatrzymany pakiet pokazał 8 zaliczonych i 24 brakujące przypadki. Próba
z limitem aktywacji zachowała prefiks i otrzymała `activation_cap` oraz
`incomplete_decision_trace`. Wynik mieści się w budżecie pilota.
Pełny identyfikator pakietu, hashe, liczniki i pomiary są w [raporcie
pilota](experiments/d7_4c/results.json). Ponowne wyliczenie raportu
porównywalności D5.3b zachowało jego historyczny SHA-256
`2dc80b9755d69d15c2b73bb8232460721ee9b238866b4b8ee407e22d5ac224a8`.

Zaliczono 140 testów celowanych i 4242 w pełnym zestawie, z czterema
ostrzeżeniami zależności. Przerwanie przed zatwierdzeniem wpisu sprawdzono
w oddzielnym procesie. Dodatkowe regresje obejmują brakujący plik,
uszkodzoną zawartość, błąd zapisu, zachowanie prefiksu i dokładnie jedno
wywołanie adaptera na powtórzenie. Repozytorium zawiera kod, użyty manifest
i kompaktowy wynik. Kopia pełnego pakietu pozostaje lokalnie w
`build/d74c-copy` i wymaga przeniesienia poza ten komputer.
