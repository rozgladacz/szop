# D8 — testowanie oddziałów i rozpisek projektowanych przez agentów

Agent proponuje oddziały i rozpiski na podstawie wersjonowanych danych
wejściowych. Projekt przechodzi walidację i wycenę, potem gra przeciw rozpisce
kontrolnej. Agent dostaje raport z bitew i może zaproponować jedną sprawdzalną
zmianę. [Kolejka w Roadmapie](roadmap.md#kolejka-testowania-z-agentami--d8)
ustala kolejność osobno zamykanych etapów.

## Wspólne granice i przekazanie

- Projektowanie wykonuje agent realizujący etap, według instrukcji zapisanej
  w repozytorium. Zamrożone propozycje mają wystarczyć do dalszej walidacji
  i symulacji bez ponownego wywołania modelu. Bitwy wykonują dwa egzemplarze
  bota `priority` z istniejącego rejestru. Stały bot pozwala porównywać rozpiski.
- Środowisko jest lokalne i korzysta z syntetycznych danych. Zakres obejmuje
  skrypty pomocnicze, fixtury, testy i dokumentację. Budżet hot path wynosi
  zero dodatkowych zapytań w `/quote` i `/rosters/{id}`. Konto agenta, zapis
  w produkcyjnej bazie, publiczne API, UI i zmiany reguł są poza D8.
- Każdy etap zapisuje w `docs/experiments/d8/` wersjonowane wejścia, instrukcję
  dla agenta, wyniki w skrócie i komendy odtworzenia odpowiednie dla etapu.
  Przy wyniku kampanii podaje również ID pakietu, skróty wejść, rewizję źródeł,
  środowisko Pythona oraz sposób wykonania i zweryfikowania osobnego backupu
  pełnego pakietu. Do odtworzenia identycznego pakietu służy jego zweryfikowana
  kopia. Z zamrożonych wejść można ponownie wygenerować dane i sprawdzić
  identyczność wyniku deterministycznego.
- Każde zamknięcie zawiera wynik, testy, ograniczenia i warunek startu
  następnego etapu. Osobny commit trafia na `Faza_A` i jest sprawdzany na
  `origin/Faza_A`. Po zmianie kodu obowiązują bramki z [AGENTS.md](../AGENTS.md),
  w tym `python -X utf8 -m pytest -q` na Windowsie.

## D8.1. Oddziały projektowane przez agenta

**Wejście i zakres.** Zbuduj małą syntetyczną pulę referencyjną opartą na
schemacie projektu. Utrwal instrukcję oraz rzeczywiste propozycje agenta.
Pierwsza partia i najwyżej jedna korekta mają dać co najmniej trzy różne,
nowe profile oddziałów. Zapisz hipotezę, dane otrzymane od agenta, wynik
normalizacji, cenę i powody każdego odrzucenia. Utwórz modele tymczasowe.
Reużyj `validate_loadout` i `calculate_roster_unit_quote` ze wspólnej ścieżki.

**Odbiór.** Wszystkie przyjęte profile mają domyślne wyposażenie odwzorowane
przez adapter silnika. Porównaj liczebność, statystyki, broń i przekazywane
efekty z danymi użytymi przy wycenie. Odrzuć nieznane identyfikatory, jawnie
nieobsługiwane cechy oraz wyposażenie lub efekty, które adapter pomija.
Katalog, raport akceptacji i jedna komenda do ponownej walidacji działają
z czystego checkoutu. Uruchom `python -X utf8 -m pytest -q
tests/test_validate_loadout.py tests/test_agents_roster_adapter.py` wraz
z celowanymi testami zgodności i odrzucania wprowadzonymi w tym etapie.

## D8.2. Rozpiski od agenta

**Zależność i zakres.** Użyj przyjętego katalogu D8.1. Najpierw zamroź
referencyjną rozpiskę i jej koszt obliczony przez `roster_points`. Niech
agent wygeneruje trzy różne składy, każdy z przynajmniej jednym nowym profilem
i hipotezą do sprawdzenia. Koszt ma mieścić się od 95% do 100% kosztu kontroli.
Koszt liczy i weryfikuje kod, a agent wybiera skład. Użyj `roster_points`
i `roster_to_engine_roster` z tą samą interpretacją liczby kopii i modeli.

**Odbiór.** Cztery zamrożone rozpiski mają stabilne ID, koszt, źródłowy profil
każdej pozycji i postać gotową do wczytania przez silnik. Sprawdź zgodność
przed i po konwersji oraz wykrywanie duplikatów, przekroczeń budżetu i danych
pomijanych przez adapter. Uruchom `python -X utf8 -m pytest -q
tests/test_agents_roster_adapter.py tests/test_deployment_experiment.py`
oraz nowe testy wejść rozpisek. Zachowaj instrukcję odtworzenia danych
silnika z czterech zamrożonych rozpisek.

## D8.3. Pilot agent kontra agent

**Zależność i zakres.** Po D8.2 użyj [kampanii v1](trwala-kampania-v1.md)
ze [śladem decyzji](kampania-ze-sladem-decyzji.md), [archiwum](archiwum-eksperymentow.md)
i [oceną techniczną](jakosc-eksperymentow.md). Zamroź `pilot-manifest.json`
w `docs/experiments/d8/` i fixtury par w `tests/fixtures/battles/d8/`.
Trzy rozpiski grają z tą samą kontrolą na geometriach `demo_skirmish`
i `objective_clash`. Ustal trzecią, odmienną mapę
z tymi samymi wymiarami i strefami, i zapisz jej geometrię przed pierwszą
bitwą. Odłóż ją w całości do D8.5. Użyj jednej strategii rozstawienia
`grid/grid`, czterech seedów, obu stron oraz obu ustawień inicjatywy.
Budżet to **96 przypadków, 192 wykonania**, z limitem runnera do 2000
aktywacji. Powtórzenia sprawdzają determinizm.

**Odbiór.** Uruchom kampanię ze śladem dla 8 przypadków, a potem wznów ją
z tego samego katalogu. Sprawdź brak duplikatów i końcowy `resume` bez nowych gier.

```sh
python -X utf8 scripts/campaign_v1.py start --manifest docs/experiments/d8/pilot-manifest.json --directory build/d8-pilot --max-cases 8 --decision-trace d8-pilot
python -X utf8 scripts/campaign_v1.py resume --directory build/d8-pilot --max-cases 88
python -X utf8 scripts/campaign_v1.py verify --directory build/d8-pilot
```

Wykonaj `campaign_v1.py archive`, `experiment_archive.py import` i `verify`
oraz `experiment_quality.py` w trybie oceny technicznej. Raport ma objąć
wszystkie 96 przypadków, w tym wyłączenia z dowodem i przyczyną. Zweryfikuj odtworzenie decyzji w co
najmniej jednym kompletnym przypadku na mapę i wznowienie lub odczyt po
odtworzeniu kopii. Uruchom testy `tests/test_campaign_v1.py`,
`tests/test_experiment_archive.py`, `tests/test_experiment_quality.py`
i `tests/test_export_decisions.py`.

## D8.4. Informacja zwrotna dla agenta

**Zależność i zakres.** Odczytaj pakiet D8.3 i raport techniczny. Porównuj
pełne bloki wyznaczone przez parę rozpisek, mapę i seed, z czterema wariantami
strony i inicjatywy w każdym bloku. Podaj liczbę oczekiwanych, dopuszczonych
i wyłączonych bloków. Powtórzenia w obrębie przypadku są jednym dowodem
wyniku. Użyj liczb wygranych, remisów i porażek, kosztu, kontroli celów oraz
odtwarzalnych przykładów ze śladu decyzji. Oddziel wniosek o składzie od
wpływu mapy, strony i inicjatywy. Wnioski dotyczą badanych warunków v1.

**Odbiór.** Raport Markdown i JSON wskazuje pakiet oraz ID przypadków
uzasadniających wniosek. Agent dostaje ten raport i zapisuje jedną propozycję
zmiany składu, hipotezę i oczekiwaną metrykę albo udokumentowany brak podstaw.
Test agregacji wykrywa brak wariantu, wykluczenie techniczne, zamianę stron
i podwójne liczenie powtórzeń. Uruchom `tests/test_experiment_quality.py`
i sprawdź zgodność raportu z zamrożonym pakietem D8.3.

## D8.5. Ponowny test jednej zmiany

**Zależność i zakres.** Przyjmij najwyżej zmianę z D8.4 po ponownej walidacji
kosztu, budżetu i zgodności z silnikiem. Uruchom wersję wyjściową i zmienioną
przeciw tej samej kontroli na obu mapach pilota oraz odłożonej mapie.
Utrzymaj seedy, strategię, boty, wersje źródeł wykonawczych i warianty
strony oraz inicjatywy. Budżet to **96 nowych przypadków, 192 wykonania**.

**Odbiór.** Zastosuj weryfikację, archiwizację i testy kampanii z D8.3 oraz
test raportu D8.4. Raport paruje warianty i pokazuje wynik oraz wyłączenia
osobno dla map pilota i mapy odłożonej, z odniesieniem do obu wersji rozpiski,
obu pakietów i hipotezy. Jeśli D8.4 wykazał brak podstaw albo zmiana nie
przejdzie walidacji, zapisz przyczynę zakończenia pętli bez kolejnych gier.
