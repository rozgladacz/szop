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
