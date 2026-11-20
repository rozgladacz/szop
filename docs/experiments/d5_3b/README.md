# D5.3b — porównanie rozstawienia Grid i objectives

Data: 2026-11-20. Baza produkcyjna: `5588fedfc021129c6a0480c8dd4b7d4609c99d39`.
Eksperyment jest lokalnym skryptem-liściem; nie zmienia silnika, botów,
domyślnego rozstawienia ani danych w DB.

- [Manifest zamrożony przed pomiarem](manifest.json)
- [Wyniki i tabele](results.md)
- [Dane przypadków, czasy powtórzeń i provenance](results.json)
- [Skrypt](../../../scripts/deployment_experiment.py)
- [Testy](../../../tests/test_deployment_experiment.py)

## Wynik i rekomendacja

Wszystkie **480/480 przypadków** zakończyły grę, bez błędów rozstawienia,
match ani activation cap. Wszystkie **960 wykonań** przeszły pełny replay;
wszystkie 480 par wykonania były identyczne poza czasem.

W **240 mieszanych porównaniach** cele wygrały **174 (72,5%)**, grid
**30 (12,5%)**, a **36 (15%)** było remisami. To opis tego zestawu, nie
estymator ogólnej skuteczności. Najsłabszy wynik celów był na
objective_clash z priority3: **10 wygranych celów, 12 gridu, 2 remisy**.
Pozostałe dziewięć komórek mapa/polityka sprzyjało celom w tym pomiarze.
Pełna tabela jest w [wynikach](results.md).
Gdy cele były P0: 74 wygrane celów, 18 gridu i 28 remisów (120 gier);
gdy były P1: 100 wygranych celów, 12 gridu i 8 remisów (120 gier).

Cele skróciły średni dystans do najbliższego znacznika z **15,655** do
**4,245 cala**, a największy z **25,755** do **12,000**. Średnia liczba
różnych najbliższych celów wzrosła z **2,2** do **2,4** na stronę. Nie
utożsamiać tego z czterema jawnymi przydziałami objectives: przydzielony
cel bywa innym niż najbliższy; najgorszy dystans do przydzielonego celu
wyniósł **28,453 cala**. Priorytet różnorodności przydziałów może kierować
jednostkę daleko i nie uwzględnia trasy przez przeszkody.

Średni koszt rozstawienia grid/grid wyniósł **0,797 ms**, a
objectives/objectives **183,750 ms**; pełne gry odpowiednio **46,218 ms**
i **238,529 ms**. Skan celów sprawdzał **4360 kandydatów na stronę**,
grid średnio **4,8**. Nie są to porównania identycznej trajektorii walki;
pełna gra zależy od zmienionych pozycji. Czasy zawierają opisaną niżej
instrumentację i nie są SLA.

Kontrole lustrzane pokazały istotny efekt strony: grid/grid (120 gier)
dało **58 wygranych P0, 8 P1, 54 remisy**, objectives/objectives (120)
**42 P0, 66 P1, 12 remisów**. Nie wyprowadzać z samego lustrzanego wyniku
przewagi strategii ani braku biasu silnika/map. Mieszane porównania były
sparowane w obu kierunkach, ze zmianą armii i inicjatywy.

**Rekomendacja:** zachować grid jako domyślny i objectives jako jawny
wariant eksperymentalny. Obserwowana poprawa na większości komórek jest
obiecująca, lecz mały skorelowany zestaw, przegrana na jednej komórce,
efekt strony i koszt uzasadniają dalsze pomiary przed zmianą defaultu.
Nie modyfikowano strategii ani manifestu pod wyniki. D5.3b jest zakończone
niezależnie od tego, czy nowa strategia stanie się kiedyś domyślna.

## Zamrożony projekt i odtworzenie

SHA256 manifestu:
`494281e8c03b5b316af751131642ba325446cccf3a8f19743b1a882e95bd672d`.
Zapisano go przed pierwszym pomiarem. Po obejrzeniu wyników nie zmieniano
map, seedów, armii, polityk ani liczby przypadków.

| Parametr | Wartość |
|---|---|
| Generowane mapy i seed | Standard_A, Lustrzana_A, Symetryczna_A; 19 |
| Istniejące fixtury | demo_skirmish.yaml, objective_clash.yaml |
| Armie | Niezmienione profile jednostek z danej mapy/fixtury |
| Polityki walki | priority kontra priority oraz priority3 kontra priority3 |
| Seedy kości | 11, 19, 42 |
| Zamiana armii | false i true; zachowane ID jednostek, owner przypisany stronie |
| Inicjatywa | 0 i 1 |
| Rozstawienia stron | grid/grid, grid/objectives, objectives/grid, objectives/objectives |
| Powtórzenia | 2 każdego przypadku |
| Granica | v1 runner; max_activations=2000 |
| Jawne strefy | P0: (0,0)–(72,12); P1: (0,36)–(72,48) |

5 źródeł × 2 polityki × 3 seedy × 2 zamiany × 2 inicjatywy × 4 pary
= **480 przypadków, 960 wykonań**. Liczby zwycięstw liczą przypadek raz;
drugie wykonanie wyłącznie sprawdza powtarzalność. Dwie polityki są z
rejestru `useful`; konstrukcja graczy przez `make_player`. Seed decyzji
oryginalnej armii 0 = seed bitwy, armii 1 = seed + PLAYER_SEED_OFFSET.
Przy zamianie stron seedy podążają za oryginalną armią. W obrębie komórki
sparowanej jedyną zmienną jest para strategii rozstawienia. Nie jest to
porównanie siły dwóch różnych botów.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/deployment_experiment.py --manifest docs/experiments/d5_3b/manifest.json --out docs/experiments/d5_3b/results.json --report docs/experiments/d5_3b/results.md
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_deployment_experiment.py -x --tb=short -q
```

`results.json` zawiera SHA256 manifestu, wersję Pythona/platformę, bazowy
commit oraz hashe skryptu, engine/agents i wejściowych YAML. Po pobraniu
commitu etapu można porównać bajty plików z tymi hashami. Hashe bajtów uwzględniają końce linii (Git normalizuje tekst); dla manifestu
niezależny od CRLF/LF digest kanonicznego JSON wynosi
`cd24887cbd140bdd0348c7c98a5529b3bb07fdd0cc6fbd48bb5c4b090d1ec6fb`.
Czasy i opis platformy nie muszą odtworzyć się na innym komputerze; deterministyczne
pola przypadków (pozycje/przydziały/wynik/digest eventów/stanu) powinny.

## Co dokładnie jest mierzone

Harness reużywa `setup_phase`, `_build_deployment_from_players`,
`deployment_round`, `run_match`, `objective_deployment_choice` i D5.1;
nie kopiuje strategii ani legalności. Sekwencyjne `patch` wąsko obserwują
zwrócone przydziały i wywołania walidatora kandydatów. Są przywracane także
po błędzie. To narzędzie jednowątkowe, nie API aplikacji; nie uruchamiać go
równolegle w tym samym procesie. Osobny test porównuje pełny wynik harnessu
z `simulate_from_rosters` bez instrumentacji.

- Każda końcowa pozycja jest ponownie sprawdzona D5.1 wobec już zajętych
  miejsc obu stron. Błąd nie zwraca częściowej listy pozycji.
- `assigned_target/assigned_gap` to rzeczywisty wynik helpera objectives.
  Grid nie ma przydziałów, więc ma `null`, nie wymyśloną drugą heurystykę.
- `nearest_target/nearest_gap` to wspólna opisowa miara przestrzenna dla
  obu strategii, liczona po rozstawieniu. Nie oznacza przydziału ani kontroli.
  Podawane dystanse są od obwodu koła oddziału do znacznika, z dołu 0.
- Licznik kandydatów obejmuje walidacje w wyborze strategii. Niezależne
  końcowe walidacje runnera/harnessu nie są do niego doliczane.
- `deployment_ms` obejmuje faktyczny wybór z lekką instrumentacją;
  `total_ms` obejmuje setup, rozstawienie, walidację/metryki i pełną grę,
  bez późniejszego replay i hashowania eventów. Są to czasy diagnostyczne,
  nie SLA. Pomiar wykonano bez równoległego pytest.
- Dla każdej zakończonej gry pełny event-tail od stanu po rozstawieniu
  odtwarza dokładnie cały `final_state`. Dwa wykonania muszą mieć identyczne
  wszystkie pola poza czasami. Niedeterminizm daje exit 1.
- `deployment_error`, `match_error` i `activation_cap` mają osobne statusy.
  Nie są liczone jako remis ani usuwane z liczby wszystkich przypadków.
  Nieoczekiwane naruszenie replay/nielegalna pozycja przerywa skrypt błędem.

## Granice interpretacji

Reguły odczytane w tym etapie: [Rozjemca, pkt 5.d–g, 13.a i 24](../../../app/static/docs/SZOP_Rozjemca.md).
Kontrola celu już używa 2 cali (commit f57b26b); dawny opis 3 cali w planie
D5.3 jest historyczny. Przydział/mały dystans po rozstawieniu nie dowodzi
zajęcia celu: kontrola jest rozliczana na końcu rundy (pkt 5.e–f), a wynik
po czterech rundach zależy od kontrolowanych celów (pkt 5.g).

To opisowy, mały zestaw trzech seedów i obecnych symetrycznych armii;
zamiany i kontrole nie są niezależnymi losowymi próbami. Nie dowodzi
ogólnej przewagi strategii. Heurystyka nie bada tras, ostrzału, osłony,
przyszłych rund, backtrackingu ani wszystkich punktów geometrii ciągłej.
Błędy bounded search nie dowodzą braku miejsca na planszy.

Wyniki dotyczą aktualnego v1 headless runnera, nie prywatnego v3 Ostrożnego
ani publicznego protokołu przerwań. Znane luki statusów Mobilizacji i
Niestrudzonego pozostają opisane w [audycie Planowania](../../planowanie-spec.md)
i [audycie Niestrudzonego](../../niestrudzony-spec.md). Nie naprawiano ich
ani nie strojono botów dla uzyskania lepszego wyniku.

## Przenoszenie

Manifest, skrypt, dane i raport są wersjonowane. Baza `data/szop.db`
pozostaje nietknięta (SHA256 w wyniku etapu), a baza oraz lokalne sekrety
konfiguracji wymagają osobnego backupu. Środowisko odtworzyć z requirements;
nie przenosić `.venv` jako zależności do następnego etapu.

## Weryfikacja implementacji harnessu

17 nowych testów; celowane sześć plików: **214 passed**. Pełny
`pytest --tb=short -q`: **4025 passed, 4 warnings**, 217,63 s. Ostrzeżenia
pochodzą z reportlab/openpyxl. Call-site audit, simplify/review i kontrola
diffu zakończone bez zmian kodu po pomiarze. Hashe wszystkich źródeł
z wyniku ponownie porównano z checkoutem. Kod produkcji/defaulty/goldeny
bez zmian, więc nie ma dodatkowych SQL ani wymaganej migracji/JS smoke.
Security review nie dotyczy zakresu bez auth/wejścia do DB.
