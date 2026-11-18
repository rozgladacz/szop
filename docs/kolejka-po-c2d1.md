# Kolejne przebiegi po C2d1

Plan przygotowany 2026-11-17 na `Faza_A`, po `13abcd2`. C2d1 zakończyło
się wynikiem 3777 zaliczonych testów.

Aktualizacja 2026-11-18 zapisuje akceptację użytkownika dla etapów 1, 2, 3
i 5 oraz dodatkowej poprawki kontroli celu do 2″. Kolejność realizacji to
B3.objectives-2in → C2d2 → D5.1 → D5.2 → C2d3-spec. Każdy przebieg
zamyka jeden etap i zapisuje wynik przed wyborem następnego. D5.3a i D5.3b
są odłożone decyzją użytkownika. Zaakceptowane pozycje
otrzymują w roadmapie etykietę `[automation-ready]` na podstawie tego wyboru
użytkownika, z obowiązkiem sprawdzenia zależności. Użytkownik zlecił
wznowienie istniejącego heartbeat w tym czacie, z jego dotychczasowym
harmonogramem i ustawieniami powiadomień. Harmonogram podlega bramce
czasu z kanonicznego skilla koordynatora, w dni robocze poza 13–19.

| Numer | Etap | Status od 2026-11-18 |
|---|---|---|
| 0 | B3.objectives-2in | Zakończony 2026-11-18; wynik poniżej |
| 1 | B4.4d.C2d2 | Zakończony 2026-11-18; wynik poniżej |
| 2 | D5.1 | Zakończony 2026-11-18; wynik poniżej |
| 3 | D5.2 | Zaakceptowany, po zamknięciu 2 |
| 4 | D5.3a i D5.3b | Odłożone decyzją użytkownika |
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

## 0. B3.objectives-2in — kontrola celu w zasięgu 2″

**Akceptacja** Użytkownik zlecił dodanie poprawki 2026-11-18.

**Cel** Doprowadzić regułę kontroli celu w silniku i korzystających z niej
botach do zgodności z [pkt 5.d Rozjemcy](../app/static/docs/SZOP_Rozjemca.md).
Odległość od krawędzi podstawki do znacznika wynosi najwyżej 2″. Odczyt
kodu z 2026-11-18 wykazał `OBJECTIVE_CONTROL_RANGE = 3.0` w `phases.py`.

**Zależność** Baza po C2d1 i E2/E4. Poprawka poprzedza pozostałe etapy
tej kolejki, aby używały spójnej reguły kontroli celu.

**Zakres** Zmienić źródłową stałą i odszukać wszystkich jej konsumentów
oraz niezależne porównania dotyczące kontroli celu. Zachować wspólny
helper `_check_objective_control` i geometrię obwód–znacznik. Uaktualnić
bezpośrednio nieaktualne komentarze, testy i opis architektury. Nie zmieniać
innych zasięgów przez globalną zamianę liczby 3. Historia eventów nadal
odtwarza zapisany wynik, a ponowna symulacja nowych akcji stosuje 2″.

**Warstwy i wydajność** Engine phases, konsumenci botów i oceny polityki,
testy oraz dokumentacja. Nowe pola DB, codec i API, JS i CSS poza zakresem.
Zero dodatkowych zapytań SQL i dodatkowych rzutów RNG. Koszt kontroli
celów zachowuje dotychczasową złożoność.

**Warunek zakończenia** Testy pozycji nieco bliżej niż 2″, dokładnie 2″
i nieco dalej niż 2″ od krawędzi oddziału, z różnymi promieniami jednostek.
Sprawdzić kontrolę przy jednostkach jednej i obu stron, zachowanie kontroli
po odejściu oraz przejęcie przez przeciwnika według pkt 5.e. Zapisać dowód
zgodności botów z helperem silnika. Każdą zmianę goldenów B7 uzasadnić
pierwszym zmienionym rozliczeniem celu lub zależną decyzją bota, a następnie
potwierdzić determinizm i replay.

**Weryfikacja celowana** `tests/test_engine_phases.py`,
`tests/test_engine_replay_invariant.py`, `tests/test_engine_regression.py`,
testy agentów używających zasięgu kontroli oraz `tests/test_balance_simulate.py`.
Pełny `pytest -q`, audyt wywołań, simplify i review. Wynik i commit
zapisać tutaj i potwierdzić na `origin/Faza_A`.

**Wynik 2026-11-18 — zamknięty** Bazą był `64e9e81`. Jedyna zmiana
wykonywalnej reguły to `OBJECTIVE_CONTROL_RANGE = 2.0` w `phases.py`.
Pomiar nadal odejmuje promień bloba od dystansu środek–znacznik. Zachowano
trwałość kontroli, odbicie, moment rozliczenia, schemy i replay historycznych
eventów. Zaktualizowano bezpośrednie komentarze silnika, ocen botów i testów.
Uzasadnienie dwóch zmienionych logów B7 i nowego przypadku remisu:
[ADR-0058](adr/0058-objective-control-two-inches.md).

**Weryfikacja wyniku** Celowana suita **226 passed**, pełny
`pytest --tb=short -q` **3828 passed, 4 warnings** zależności (ReportLab /
openpyxl), wobec bazowych 3777. Dodano 51 przypadków: granice
1.999/2/2.001″ dla trzech promieni i obu stron, kontestację, obecny kontrakt
rezerwy/pokonanych, odejście i odbicie, zgodność konsumentów agentów,
historyczny replay z 2.5″, zachowanie remisu oraz replay kontroli/wyniku
wszystkich siedmiu goldenów. Powtarzalność pełnych bitew pozostaje zielona.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_phases.py tests/test_engine_replay_invariant.py tests/test_engine_regression.py tests/test_agents_policy.py tests/test_agents_greedy.py tests/test_agents_priority.py tests/test_agents_priority_v2.py tests/test_agents_priority_v3.py tests/test_agents_claude_v1.py tests/test_agents_minimax.py tests/test_balance_simulate.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
```

**Audyt wywołań i DoD** `round_end_phase`, policy_eval (a przez nie Greedy),
Priority, PriorityV2/V3, Minimax i ClaudeV1/V2/V3 korzystają z jednego helpera
lub jego konsumentów. Jedyny dodatkowy predykat geometrycznej bliskości
PriorityV3 importuje tę samą stałą; nie jest osobnym rozliczeniem kontroli.
Audyt nie znalazł dalszych niezależnych progów kontroli. Pozostałe wartości
3 w mapach, rozstawieniu i wadze akcji nie dotyczą kontroli, pozostały
bez zmian. Simplify i review objęły reuse, granicę obwodu, źródła, event
sourcing i przyczynę driftu goldenów. Simplify poprawił dawną asercję Greedy
na jawną odległość obwodu i odnośniki do pkt 5; po nim powtórzono testy.
Security review oraz smoke JS nie dotyczą zakresu: bez auth, wejścia do DB,
zmian JS/CSS/API. Zero dodatkowych SQL i RNG, koszt nadal cele × oddziały.

**Ograniczenia i przeniesienie** Zachowano dotychczasowy filtr
`models_alive` i Przyszpilony. Helper nie filtruje `location`; żywa rezerwa
na wskazanych współrzędnych zachowuje dotychczasowy kontrakt. Reguły
lokalizacji i aproksymacja oddziału kołem nie są rozszerzane tym etapem.
Zastane zmiany HANDOFF, lokalnych ustawień i historyczny wpis B6.2 pozostają
poza commitem. Kod, golden i dokumentacja etapu trafiają do osobnego commitu
na `Faza_A`, którego obecność na `origin/Faza_A` potwierdza zamknięcie przebiegu.

Bieżąca ignorowana `data/szop.db` pozostała nietknięta: SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Przed zmianą komputera wymaga osobnego backupu, podobnie jak lokalne sekrety
i konfiguracja spoza Git; środowisko `.venv` należy odtworzyć z zależności.
Te dane nie są zastępowane commitem etapu.

**Podstawa kolejnego przebiegu** Następny zaakceptowany etap to
`B4.4d.C2d2`, opisany niżej, na bazie zamkniętego C2d1 z `13abcd2`
oraz niniejszej poprawki. Nie został uruchomiony w tym przebiegu.
Brak nowych decyzji wymagających użytkownika; D5.3a/b pozostają odłożone.

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

**Wynik 2026-11-18 — zamknięty** Bazą jest `f57b26b` po poprawce kontroli celu.
Jedyną zmienioną warstwą produkcyjną jest `combat.py`: istniejący matcher
zamkniętej Szarży jest wywoływany raz, a znaleziony kontekst włącza aliasy
w `_count_hits` dla głównego ataku i kontrataku. Dwie nazwy to jeden bonus.
Kontra może wyłączyć Furię, ale nie aliasy własnej broni. Otwarte okno oraz
niepasująca broń lub deklaracja nie włączają nowej ścieżki. Nie rozszerzono
dotychczasowego zachowania v1/v2 ani ranged; publiczne `_READY_ATTACK_X`
pozostaje puste. Podstawa reguł: poz. 66, 7 i 10 Zdolności, pkt 14.d i 17
Rozjemcy; szczegóły w [planie mechanik](oznaczenie-mechaniki-plan.md).

**Weryfikacja wyniku** Celowany zestaw pięciu wskazanych plików:
**370 passed, 1 warning**. Pełny `pytest --tb=short -q`:
**3848 passed, 4 warnings** zależności (183.68 s), +20 przypadków względem
bazy 3828. Nowe testy porównują zdarzenia i RNG trzech kombinacji nazw,
Furię natywną/nadaną/obie/brak, naturalne 6/brak 6, kontratak i Kontrę,
restart, pełny replay i 12 przyszłych rzutów oraz granice dopasowania v3.
Regresje v1/v2 i ranged v1/v2/v3 zachowują historyczne rozróżnienie nazw.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_combat.py tests/test_engine_activation_protocol.py tests/test_engine_weapons_inventory.py tests/test_engine_regression.py tests/test_battle_activation_transport.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
git diff --check
```

**Obserwacja testowa** Pierwszy pełny przebieg miał 3847 zaliczonych testów
i pojedynczy błąd `test_public_two_owner_straznik_uses_two_bearers_and_closed_errors`
(422 `illegal_interrupt` zamiast 200). Test tworzy bitwę z losowym seedem
serwera. Przeszedł pojedynczo, ponownie w zestawie celowanym i w pełnej suicie;
próby z bazowym `combat.py` wczytanym wyłącznie do pamięci dla seedów 0–19
również przeszły. Nie ustalono przyczyny pierwszego błędu; nie zmieniono
niezwiązanej ścieżki Strażnika ani nie zamaskowano problemu zmianą asercji.

**Audyt i granice** `phases._apply_charge` nadal jako jedyny produkcyjny
caller deleguje do `resolve_charge_attack`; parametry akcji są bez zmian.
Oba wywołania `resolve_melee_attack` dostają wspólną kwalifikację aliasów,
a bezpośrednie wywołania nadal mają domyślne `False`. `_count_hits` pozostaje
SSOT; jego konsument ranged i source-correct Strażnik są niezmienieni.
Simplify/review objęły gate closed-v3, rolę obu atakujących, niezależność
od Furii, naliczanie bonusu raz i replay. Bez auth, wejścia do DB i zmian
JS: security review i UI smoke nie dotyczą zakresu. Zero nowych SQL,
zmian modelu/codec/API; brak powtarzania testów trafienia. Więcej testów
obrony jest wyłącznie konsekwencją dodatkowych trafień.

**Przeniesienie** Kod, testy i dokumentacja C2d2 mają osobny commit na
`Faza_A`, potwierdzany na `origin/Faza_A`. Zastane lokalne ustawienia,
HANDOFF i historyczny hunk B6.2 nie należą do etapu. Produkcyjna ignorowana
`data/szop.db` jest nietknięta (SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`).
Przed przejściem na inny komputer wykonać osobny backup bazy i lokalnych
sekretów/konfiguracji; odtworzyć środowisko z `requirements-dev.txt`.

**Podstawa kolejnego przebiegu** Następny zaakceptowany etap to D5.1,
opisany niżej. Nie został uruchomiony w ramach C2d2. Brak nowych decyzji
wymagających użytkownika; D5.3a i D5.3b pozostają odłożone.

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

**Wynik 2026-11-18 — zamknięty D5.1** Bazą jest `fdd66d8` po C2d2.
`is_deployment_position_legal(unit, position, zone, *, occupied, terrain)`
w `agents/deployment.py` jest czystym predykatem. Brak jawnej strefy,
nieprawidłowe lub nieskończone współrzędne/promienie/granice strefy,
pokonany aktor i aktor poza Frontem dają `False`. Całe koło musi mieścić
się w strefie; zachowano dotychczasową tolerancję strefy `1e-9`.
Podstawa: odczytane pkt 13.a, 2.d, 4.c.i, 15.c i 24
[Rozjemcy](../app/static/docs/SZOP_Rozjemca.md).

**Wspólna geometria** `movement.can_place_unit` i `ManeuverSpace.can_stop`
korzystają z jednego `_position_is_clear`. Reużywa on dokładny test koła
wobec kół, odcinków i wielokątów oraz odrzucanie rozłącznych obwiedni E4.
Wklęsłości wielokątów pozostają wolne. Styk oddziałów jest dozwolony,
a ich penetracja większa niż istniejący `MOVE_EPSILON = 1e-6` jest odrzucana.
Styk z brzegiem Niedostępnego jest blokowany jak w E4. Trudny i Blokujący
bez Niedostępnego nie zabraniają rozstawienia. Wymagany jest istniejący
poprawny kontrakt geometrii terenu; etap nie dodaje parsera ani naprawy terenu.

**Zajęte miejsca** Caller przekazuje `occupied` z aktualnymi pozycjami tylko
już rozstawionych jednostek obu stron. Oczekujące jednostki z pozycjami
zastępczymi nie mogą zostać dodane automatycznie z `state.blobs`. Sam aktor,
pokonani i jednostki poza Frontem są pomijani. Niepoprawna geometria
istotnej przeszkody daje `False`. Wejściowe obiekty pozostają niezmienione.
Predykat nie zapisuje wybranej pozycji ani nie sprawdza całej kolejki naraz.

**Audyt wywołań i granice** `ManeuverPlanner.can_reach` oraz
`reachable_positions` nadal używają `ManeuverSpace.can_stop`. Test punktu
końcowego ma tę samą geometrię i wynik co wcześniejsze `segment(p, p)`;
oddzielna ścieżka `segment` zachowuje wyjątek wyjścia ze starego nakładania
podczas ruchu. Walidator rozstawienia tego wyjątku nie używa. Jedyny nowy
caller `can_place_unit` to walidator. Nie zmieniono `DeploymentZone.contains_circle`
ani jej callerów: runnera, Grid i Random. Integracja i sekwencyjne aktualizacje
zajętych miejsc wymagają D5.2. Nie zmieniono eventów, codec, starych zapisanych
bitew, API, DB, RNG, JS ani CSS. Zero SQL; koszt jednej walidacji jest liniowy
od liczby zajętych oddziałów i elementów terenu (oraz krawędzi badanego wielokąta).

**Weryfikacja wyniku** Dodano 58 przypadków: cztery brzegi strefy i trzy
promienie, wszystkie kształty terenu i wklęsłość, styk/przenikanie, obie strony,
rezerwy/pokonani/self, jawna kolejność zajmowania miejsc, generatory,
NaN/Inf/nienumeryczne dane i niepoprawne promienie/strefy oraz brak mutacji.
Regresja odróżnia dopuszczony odcinek ucieczki ze starej kolizji od
niedopuszczonego punktu końcowego i rozstawienia. Zestaw celowany:
**227 passed**. Pełny `pytest --tb=short -q`: **3906 passed, 4 warnings**
zależności (212.93 s), bez błędów. Goldeny siedmiu pełnych bitew i replay
pozostają bez zmian. Dodatkowy audyt 3600 pozycji przy seeded generatorze
potwierdził równość nowego `can_stop(p)` i starego `segment(p, p) is not None`.
Po testach wykonano przeglądy simplify i review diffu: reuse SSOT,
rozdzielenie statycznej kolizji od escape, fail-closed danych, brak cyklu
engine → agents i brak aktywnego wpięcia w strategie. Nie wymagały zmian kodu.
Nie zmieniono auth ani wejścia użytkownika do DB, więc security review
nie dotyczy zakresu; UI smoke także nie jest wymagany przy braku zmian JS.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_agents_deployment.py tests/test_engine_phases.py tests/test_agents_match.py tests/test_engine_replay_invariant.py tests/test_engine_regression.py tests/test_engine_pathfinding.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
git diff --check
```

**Przeniesienie** D5.1 ma osobny commit na `Faza_A`, potwierdzany na
`origin/Faza_A`. Produkcyjna ignorowana `data/szop.db` pozostaje nietknięta,
SHA256 `AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Przed zmianą komputera wykonać osobny backup bazy i lokalnych sekretów/
konfiguracji, a środowisko odtworzyć z `requirements-dev.txt`. Zastane lokalne
ustawienia, HANDOFF i historyczny hunk B6.2 nie należą do etapu.

**Podstawa kolejnego przebiegu** D5.2 może użyć nowego predykatu dla każdego
kandydata i przed zatwierdzeniem wszystkich pozycji, przekazując jawny zbiór
już wybranych jednostek. Strategie i runner obecnie nadal sprawdzają samą
strefę, więc nie należy deklarować kompletnej walidacji automatycznego
rozstawiania przed D5.2. Brak nowych decyzji użytkownika; D5.3a/b odłożone.

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

**Status** D5.3a i D5.3b odłożone przez użytkownika 2026-11-18.
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
Poprawka została zaakceptowana jako `B3.objectives-2in`, na początku kolejki.
Przed ewentualnym powrotem do D5.3 sprawdzić jej zapisany wynik.

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
