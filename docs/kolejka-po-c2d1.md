# Kolejne przebiegi po C2d1

Plan przygotowany 2026-11-17 na `Faza_A`, po `13abcd2`. C2d1 zakończyło
się wynikiem 3777 zaliczonych testów.

Aktualizacja 2026-11-18 zapisuje akceptację użytkownika dla etapów 1, 2, 3
i 5. Kolejność realizacji to C2d2 → D5.1 → D5.2 → C2d3-spec. Każdy przebieg
zamyka jeden etap i zapisuje wynik przed wyborem następnego. Punkt 4 został
rozszerzony do oceny i czeka na osobną akceptację. Zaakceptowane pozycje
otrzymują w roadmapie etykietę `[automation-ready]` na podstawie tego wyboru
użytkownika, z obowiązkiem sprawdzenia zależności. Status heartbeat jest
wstrzymany, a wznowienie harmonogramu wymaga jawnego polecenia użytkownika.

| Numer | Etap | Status od 2026-11-18 |
|---|---|---|
| 1 | B4.4d.C2d2 | Zaakceptowany do realizacji |
| 2 | D5.1 | Zaakceptowany, po zamknięciu 1 w tej kolejce |
| 3 | D5.2 | Zaakceptowany, po zamknięciu 2 |
| 4 | D5.3 | Rozszerzona propozycja do oceny |
| 5 | B4.4d.C2d3-spec | Zaakceptowany audyt, po zamknięciu 3 w tej kolejce |

## Wspólne warunki pracy

Każdy przebieg wykonuje jeden etap. Przed implementacją sprawdza aktualny
HEAD, cudze zmiany i zależności oraz odczytuje właściwe źródła reguł.
Procedury operacyjne wynikają z `AGENTS.md`, a pełny HANDOFF jest wstrzymany.
Sam plan i wynik w tym pliku oraz roadmapa wystarczają do przekazania etapu.

Przed edycją trzeba potwierdzić Layer Checklist i performance gate opisane
poniżej. Kodowanie Pythona sprawdza się przez odczyt UTF-8. Zachować
produkcyjną bazę i cudze zmiany, a testy zapisu wykonywać na bazach testowych.

Zamknięcie implementacji obejmuje testy celowane, pełny `pytest -q`, audyt
wywołań, simplify, review i kontrolę diffu. Security review dochodzi przy
rzeczywistej zmianie wejścia użytkownika, uprawnień lub zapisu do DB.
Wynik, ograniczenia i podstawę następnego etapu zapisać w tym dokumencie.
Każdy etap ma osobny commit na `Faza_A` i kończy się potwierdzeniem tego
commitu na `origin/Faza_A`. Środowisko i pliki lokalne nie zastępują zapisu
w repozytorium. Kopia bieżącej bazy jest osobnym składnikiem przeprowadzki.

Typowe komendy uruchamiane z katalogu repozytorium na Windows

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
git status --short --branch
git log -1 --oneline
git ls-remote --heads origin Faza_A
```

Na innym komputerze utworzyć własne środowisko z `requirements-dev.txt`
i zainstalować klienta zgodnie z `docs/testing.md`. W razie niedostępności
Store Pythona wybrać działający interpreter zamiast kopiować `.venv`.

## 1. B4.4d.C2d2 — nazwa Podwójnego w prywatnym melee v3

**Zależność** C2d1 z `13abcd2`.

**Cel** Usunąć wykrytą rozbieżność między `podwojny` w walce wręcz
i identyfikatorem `rozrywajacy` z `app/rulesets/v1/abilities.yaml`.
Wykorzystać istniejące `_count_hits` i sposób rozpoznawania aliasów w ranged.
Efekt Podwójnego opisuje [poz. 66 Zdolności](../app/static/docs/SZOP_Zdolnosci.md),
a interakcję z Furią także poz. 7. Nie zmieniać źródła reguł dla dopasowania
do kodu.

**Zakres** Zgodne rozpoznanie obu nazw w prywatnym, zamkniętym ataku wręcz
v3. Dwie nazwy obecne jednocześnie oznaczają jedną zdolność. Dotychczasowe
wywołania v1/v2 i ranged mają zachować wynik i RNG. Rozszerzenie wszystkich
historycznych ścieżek wymaga osobnego etapu. Publiczna publikacja Oznaczenia
jest poza tym zadaniem.

**Warstwy i wydajność** Silnik combat i testy protokołu/inventory. Model,
codec, DB, klient, JS i CSS bez zmian. Zero nowych SQL i rzutów trafienia.

**Warunek zakończenia** Ta sama broń z każdą nazwą daje ten sam wynik
w v3, z Furią i bez niej, również dla obu nazw naraz. Sprawdzone naturalne 6
i brak 6, kontratak, restart, pełny replay, dalsze RNG oraz regresje v1/v2.
Dokument `oznaczenie-mechaniki-plan.md` odnotowuje rozwiązanie rozbieżności.

**Weryfikacja celowana** `tests/test_engine_combat.py`,
`tests/test_engine_activation_protocol.py`, `tests/test_engine_weapons_inventory.py`,
`tests/test_engine_regression.py` i `tests/test_battle_activation_transport.py`.

## 2. D5.1 — wspólna walidacja miejsca rozstawienia

**Zależność** E2/E4 z `765358c` i `068745c`. Etap niezależny od C2d2.

**Cel** Przygotować jeden czysty walidator pozycji rozstawienia dla
generatora i runnera. Reguły strefy i Niedostępnego wynikają z
[pkt 13.a, 2.d i 4.c.i Rozjemcy](../app/static/docs/SZOP_Rozjemca.md).
Pkt 15.c znosi odstęp 1″ między oddziałami. Zachować koło oddziału jako
obecne przybliżenie modelu.

**Zakres** Sprawdzić skończone współrzędne, całe koło w przekazanej strefie,
teren Niedostępny każdego kształtu oraz zajęte miejsca. Jawnie przekazywać
zbiór już rozstawionych oddziałów, aby pozycje startowe jednostek czekających
na rozstawienie nie stawały się przeszkodami. Reużyć geometrię E2/E4 bez
kopiowania całego planera tras. Styk oddziałów dopuszczalny, przenikanie
odrzucane. Brzeg Niedostępnego zachowuje konwencję E4.

Najpierw rozdzielić testy nieruchomego miejsca od reguł wyjścia ze starej
kolizji w Manewrze. Wspólny test geometryczny ma obsługiwać E4 i nowy
walidator, zachowując wynik istniejącego planera. Aktywne wpięcie walidacji
w `deployment_zones` wykonać w D5.2 razem z wyborem legalnych pozycji przez
boty. Dzięki temu D5.1 nie pogarsza działającego automatycznego rozstawiania
w okresie przed D5.2. Nie dopowiadać brakującej strefy z wymiarów mapy.

**Warstwy i wydajność** Czyste helpery silnika/geometrii, warstwa agentów,
runner i testy. Bez nowych trwałych pól, API HTTP, JS i CSS. Zero SQL.
Koszt zależy od liczby zajętych miejsc i elementów terenu, z odrzucaniem
rozłącznych obwiedni.

**Warunek zakończenia** Testy wszystkich trzech kształtów, przecięcia
samego brzegu koła, styku jednostek, rezerw i pokonanych, kolejności
rozstawiania i celu poza strefą. Błąd pozostawia wejściowy stan bez zmian.
Stare zapisane bitwy i dotychczasowy tryb bez `deployment_zones` są czytelne.

**Weryfikacja celowana** `tests/test_agents_deployment.py`,
`tests/test_engine_phases.py`, `tests/test_agents_match.py`,
`tests/test_engine_replay_invariant.py` oraz
`tests/test_engine_regression.py`. Dodać rzeczowe regresje walidatora.

## 3. D5.2 — boty wybierają wolne miejsca

**Zależność** Zamknięte D5.1.

**Cel** Boty korzystają z walidatora D5.1 przy wyborze pozycji.
Grid i Random mają uwzględniać teren oraz pozycje już wybranych jednostek.

**Zakres** Wpięcie walidatora D5.1 w ścieżkę `deployment_zones`,
deterministyczna kolejność rozstawiania oraz aktualizacja
roboczego obrazu wybranych pozycji po każdej decyzji. Zachować istniejące
`Player.choose_deployment` i mixin, jeśli wystarczają. Przy nielegalnym
slocie gridu szukać wolnego kandydata w ograniczonym zbiorze. Random używa
własnego seeded RNG i skończonej liczby prób, następnie deterministycznego
przeglądu kandydatów. Brak miejsca w przeszukanym zbiorze ma dać jawny błąd,
a nie umieszczenie oddziału w przeszkodzie. Skończone próbkowanie nie jest
dowodem braku miejsca w całej geometrii ciągłej.

**Warstwy i wydajność** Deployment agentów, runner i testy. Schematy danych,
API HTTP, JS i CSS poza zakresem. Bez SQL. Limit kandydatów i prób określić
w kodzie i uzasadnić pomiarem dla istniejących map.

**Warunek zakończenia** Boty deterministyczne i Random rozstawiają kilka
oddziałów o różnych promieniach na mapie z poligonem i w wąskiej strefie.
Każda pozycja przechodzi D5.1. Ten sam seed daje te same pozycje, błąd nie
zostawia częściowego zapisu. Stare wywołania bez wyboru rozstawienia działają.

**Weryfikacja celowana** `tests/test_agents_deployment.py`,
`tests/test_agents_factory.py`, `tests/test_balance_simulate.py` i
`tests/test_engine_regression.py`. Pomiar pełnej symulacji z rozstawieniem
przed i po zmianie. Wyjaśnić każdą konieczną zmianę goldenów.

## 4. D5.3 — opcjonalne rozstawianie pod cele

**Status** Rozszerzona propozycja z 2026-11-18, oczekująca na akceptację.
Podział poniżej pozwala ocenić osobno strategię i jej skuteczność.

**Zależność** Zamknięte D5.2. Strategia korzysta z tego samego walidatora,
zbioru kandydatów i informacji o już rozstawionych jednostkach.

**Cel** Porównać dwa sposoby ustawiania armii. Grid daje równomierne
pozycje, a nowa strategia ma ułatwić podejście do różnych celów, zamiast
skupiać całą armię przy jednym najbliższym znaczniku. Wynik porównania
ma pokazać koszt i korzyści, zanim strategia stanie się kandydatem domyślnym.

### D5.3a — strategia i jawny wybór

Przez parametr Python runnera wybrać dotychczasowy grid albo strategię
celów. To ustawienie rozstawienia jest niezależne od polityki walki
wybranego bota. Domyślny wybór pozostaje gridem.

Wspólna, ograniczona pula legalnych kandydatów z D5.2 pozwala porównać
strategie bez mieszania wpływu innego próbkowania. Dla każdego oddziału
ocenić odległość obwodu koła oddziału od znacznika. W pierwszej kolejności
przydzielać różne cele, a następnie zmniejszać odległość dojścia. To
heurystyka wyboru pozycji, której wynik nie oznacza jeszcze zajęcia celu.

Proponowane rozstrzyganie decyzji jest deterministyczne, z ustaloną
kolejnością oddziałów i remisów po identyfikatorze celu i współrzędnych
kandydata. Następny oddział widzi pozycje poprzednich. Gdy nie ma celów,
strategia używa bezpiecznej metody D5.2. Gdy cele są już przydzielone,
nadmiarowe oddziały wzmacniają cel o najmniejszej dotychczasowej obsadzie,
a przy remisie wybierają mniejszy dystans. To propozycja polityki bota,
którą można zmienić przed zatwierdzeniem etapu.

Przykłady do sprawdzenia

- Dwa oddziały i dwa cele powinny uzyskać dwa różne przydziały, gdy
  istnieją legalne pozycje dla obu. Pojedynczy bliski cel nie przyciąga obu
  oddziałów tylko z powodu mniejszej sumy dystansów.
- Więcej oddziałów niż celów daje wsparcie przydzielonych celów.
- Mniej oddziałów niż celów daje tylko tyle przydziałów, ile jest oddziałów.
- Zablokowany kandydat odpada przez D5.1 przed porównaniem odległości.
- Brak legalnego miejsca daje ten sam jawny wynik błędu co D5.2.

Pierwsza wersja mierzy odległość geometryczną. Preferencja terenu
Obronnego, unikanie ostrzału, szukanie trasy z każdego kandydata i ocena
kilku tur są możliwymi rozszerzeniami po pomiarach. Osobne dodawanie ich
umożliwi ustalenie, która zmiana poprawiła wynik.

**Warunek zakończenia D5.3a** Działający wybór strategii w Pythonie,
legalność wszystkich pozycji, testy powyższych przykładów, deterministyczne
wyniki i regresje dotychczasowego domyślnego rozstawienia.

### D5.3b — porównanie rozstawień i pełnych bitew

Zamrozić zbiór map, seedów i par armii przed pomiarem. Użyć istniejących
fixtur oraz map Standard_A, Lustrzana_A i Symetryczna_A, z odnotowaniem
seedów generatorów. Dla każdej pary uruchomić grid i nową strategię
z identyczną armią, polityką walki, mapą i seedem bitwy. Zamienić strony
i inicjatywę, żeby pozycja gracza nie przesądzała wyniku.

Porównanie obejmuje zarówno różne strategie po dwóch stronach, jak
i kontrolne gry lustrzane z tą samą strategią. Pozwala to oddzielić wpływ
rozstawienia od różnicy botów. Graczy konstruować przez istniejący
`make_player`, a klasyfikację botów pobierać z rejestru.

| Miara | Co ma wyjaśnić |
|---|---|
| Legalne rozstawienia i błędy znalezienia miejsca | Czy strategia nadaje się do użycia na badanych mapach |
| Liczba różnych przydzielonych celów | Czy armia rozdziela zadania |
| Dystans do przydzielonego celu i najgorszy dystans | Czy lepsza suma nie ukrywa oddziału pozostawionego daleko od celu |
| Wynik końcowy oraz wygrane i remisy | Czy zmiana pomaga w badanym modelu silnika |
| Czas samego rozstawienia i całej gry | Jaki jest koszt strategii |
| Powtarzalność pozycji i dziennika zdarzeń | Czy ten sam wariant można ponownie odtworzyć |

Wyniki zapisać jako dane z parametrami uruchomienia i krótkie podsumowanie
wersjonowane w dokumentacji. Wygrana na wybranym zestawie nie dowodzi
ogólnej przewagi. Gorszy wynik lub brak różnicy również kończy eksperyment.
Wariant o niekorzystnym koszcie pozostaje dostępny do eksperymentów.

**Uwaga o wierności silnika** Odczyt z 2026-11-18 wykazał, że
`phases.OBJECTIVE_CONTROL_RANGE` wynosi 3.0, podczas gdy
[pkt 5.d Rozjemcy](../app/static/docs/SZOP_Rozjemca.md) wskazuje promień 2″.
Raport D5.3 musi nazwać tę rozbieżność. Odległości i przydziały można
porównywać niezależnie od niej. Wyniki pełnych gier opisują bieżący silnik.
Ewentualna zmiana zasad kontroli celu wymaga osobnego zakresu i regresji,
ponieważ zmieni również wynik pomiaru strategii.

**Warunek zakończenia D5.3b** Powtarzalny raport porównawczy z komendami,
hashami kodu, parametrami i wynikami obu strategii. Opisać zaobserwowane
korzyści, porażki oraz rekomendację dalszego użycia.

**Warstwy i wydajność** Agent deployment, parametr runnera, testy i wynik
porównania w dokumentacji. Przygotowanie parametrów eksperymentu może
rozszerzyć istniejący skrypt symulacji o wybór rozstawienia. Publiczna
allowlista botów HTTP, DB, checkpointy, JS i CSS pozostają poza tym zakresem.
Zero SQL dla wyboru pozycji, ograniczony zbiór kandydatów i bez badania
wszystkich permutacji. Raportować liczbę ocenionych kandydatów oraz czas,
zamiast zakładać dopuszczalny koszt bez pomiaru.

**Warunek zakończenia całości** Zamknięte D5.3a i D5.3b, osobne commity
z ich wynikami na `origin/Faza_A`. Decyzja o zastąpieniu domyślnego gridu
wynika z wyników i jest odrębna od dodania eksperymentalnego wariantu.

**Weryfikacja celowana** `tests/test_agents_deployment.py`,
`tests/test_agents_match.py`, `tests/test_balance_simulate.py`,
`tests/test_agents_factory.py` i `tests/test_engine_regression.py`.
Pełny `pytest -q` i audyt wywołań po każdym podetapie zmieniającym kod.

## 5. B4.4d.C2d3-spec — kontrakt Ostrożnego

**Zależność** C2d1. Audyt można wykonać niezależnie od etapów D5.

**Cel** Przygotować kompletny zakres następnej implementacji mechaniki X.
W [poz. 23 Zdolności](../app/static/docs/SZOP_Zdolnosci.md) opis ogólny
mówi o trafieniu, a szczegół efektu wskazuje oddział strzelający. Przed
implementacją należy ustalić, czy źródła jednoznacznie rozstrzygają zakres.

**Zakres** Odczytać aktualne źródła i ich synchronizację. Zmapować
`EffectContext`, `aggregate_attack_modifier`, wszystkie wejścia combat
i analityczne prediction. Określić sprawdzenie wszystkich wrogich oddziałów,
pomiar zasięgu w istniejącej geometrii, role, czas życia Oznaczenia oraz
zgodność v1/v2. Nie wyprowadzać działania z samego celu wybranego ataku.

**Warstwy i wydajność** Dokument specyfikacji i odnośniki w roadmapie.
Kontrakt ma wskazywać przyszłe zmiany engine/tests oraz wpływ na payload,
prediction i cache. Oszacować koszt przeglądu oddziałów, bez nowych SQL.

**Warunek zakończenia** Specyfikacja zawiera przykłady granicy zasięgu,
wpływu dodatkowego bliskiego wroga i wyłączenia efektu po ataku, pliki do
zmiany, testy i DoD implementacji. Jeżeli aktualne źródła nie rozstrzygają
zakresu, zapisać jedno konkretne pytanie i rekomendację. Sama notatka z
pytaniem kończy audyt, ale implementacja pozostaje zablokowana do decyzji.

**Weryfikacja** Każdy rules claim ma aktualnie odczytane źródło i numer
punktu lub pozycji. Sprawdzić wszystkie wymienione funkcje i ścieżki, linki
dokumentacji i `git diff --check`. Pełny pytest wymagany, jeśli audyt
spowoduje jakąkolwiek zmianę kodu.

## Dalszy wybór po tej kolejce

Publiczne odblokowanie Oznaczenia wymaga osobnego zatwierdzonego zakresu
wartości X i weryfikacji auth, no-oracle, rollback, restart oraz SQL gates.
Plan tej publikacji znajduje się w `oznaczenie-mechaniki-plan.md`.
E1 per-model i Play vs AI pozostają dalszymi inicjatywami do osobnego podziału.
