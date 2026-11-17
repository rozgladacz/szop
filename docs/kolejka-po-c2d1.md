# Kolejne przebiegi po C2d1

Plan przygotowany 2026-11-17 na `Faza_A`, po `13abcd2`. C2d1 zakończyło
się wynikiem 3777 zaliczonych testów. Poniższa kolejność jest propozycją
pięciu osobnych przebiegów. Ten dokument określa zadania do wyboru i nie
wznawia heartbeat. W roadmapie etapy czekają na ręczne uruchomienie.

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

**Zależność** Zamknięte D5.2.

**Cel** Dodać prostą strategię wyboru spośród legalnych kandydatów D5.1,
która ogranicza dystans własnych oddziałów do celów. To heurystyka bota,
której skuteczność trzeba zmierzyć.

**Zakres** Jawny wybór strategii w warstwie Python runnera. Obecny grid
pozostaje domyślny. Preferować przydzielenie różnych oddziałów do różnych
celów, z odległością obwód oddziału–znacznik jako miarą oraz stabilnym
rozstrzyganiem remisów. Dla nadmiarowych oddziałów stosować tę samą miarę.
Strategia ocenia wyłącznie zwalidowanych kandydatów, bez dodatkowego RNG.
Nie dodawać nowego bota do publicznego katalogu HTTP w tym etapie.

**Warstwy i wydajność** Agent deployment, parametr runnera, testy i wynik
porównania w dokumentacji. Bez zmian DB, checkpointów, JS i CSS. Zero SQL,
ograniczony zbiór kandydatów i bez przeszukiwania wszystkich permutacji.

**Warunek zakończenia** Legalność i determinizm przy różnej liczbie
oddziałów i celów, bez celów oraz przy przeszkodach. Porównać z gridem na
tych samych mapach i seedach, raportując miarę odległości i koszt obliczeń.
Słabszy wynik rozgrywek jest wynikiem eksperymentu, a nie powodem do
dobierania seedów pod tezę. Dotychczasowy tryb domyślny zachowuje regresje.

**Weryfikacja celowana** `tests/test_agents_deployment.py`,
`tests/test_balance_simulate.py` i `tests/test_engine_regression.py`.

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
