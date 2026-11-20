# D6.1 — audyt botów i gotowości integracji

Data: 2026-11-20. Baza: `4082bd9005b2567c781dc9e0805214f791d1cea0`,
`Faza_A`. Zakres: obserwacje istniejących implementacji, mały harness,
regresje i dokumentacja. Bez zmian silnika, polityk, tagów, API, uprawnień,
UI i produkcyjnej bazy. D6.2 nie jest wykonane przez ten etap.

**Wniosek:** istnieje działający transport publiczny stan → `priority` →
propozycja v1 → zatwierdzenie ownera. Nie istnieje dowód pełnej zgodności
decyzji wszystkich botów z regułami. Audyt wykazał konkretne luki wspólnej
walidacji walki/statusów oraz brak protokołu v2/v3 w ścieżce propozycji.
Pierwszy adapter powinien obsługiwać jawny, ograniczony tryb v1 opisany
poniżej; pozostałe przypadki odrzucać przed utworzeniem propozycji.

## Dowody i odtworzenie

- [Manifest](experiments/d6_1/manifest.json), [surowe wyniki](experiments/d6_1/results.json).
- [Pomiar izolowanego HTTP/SQL](experiments/d6_1/transport_probe.json).
- [Ponowne grupowanie istniejących danych D5.3b](experiments/d6_1/side_analysis.json).
- [Harness](../scripts/bots_audit.py), [regresje](../tests/test_bots_audit.py)
  i dwa nowe testy [owner-scoped propozycji](../tests/test_battle_action_proposals.py).
- [D5.3b](experiments/d5_3b/README.md) pozostaje źródłem dużego porównania
  strategii; tego leaderboardu nie powtarzano i nie strojono wag pod wynik.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/bots_audit.py --manifest docs/experiments/d6_1/manifest.json --out docs/experiments/d6_1/results.json
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_bots_audit.py tests/test_battle_action_proposals.py -q --tb=short
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Manifest określa 9 kanonicznych kindów rejestru, seedy decyzji/kości
**11 i 19** oraz 9 małych pozycji po 2 jednostki: dystans, kontakt,
Wyczerpany, Przyszpilony, objazd poligonu, długa blokująca ściana, cel
na granicy 2″, ostatnia runda i zakończona gra. To pozycje diagnostyczne,
nie pełnowymiarowe armie ani próbka do rankingu. Każdy przypadek ma dwa
świeże wykonania. Seed przeciwnika = seed + `PLAYER_SEED_OFFSET`.

| Obserwacja | Przypadki | Wykonania | Wynik |
|---|---:|---:|---|
| Decyzje, w tym 18 terminalnych | 162 | 324 | 162/162 powtarzalne; stan publiczny round-trip i brak mutacji wejścia |
| Nieterminalna pierwsza akcja v1 | 144 | 288 | 144/144 akceptowane przez obecny resolver |
| Kontynuacja po pierwszej akcji | 144 | 288 | 101 decyzji z akcją, 43 stop; 101 zastosowanych drugich akcji; 144/144 pełny replay |
| Deployment: default/grid/objectives × zwykła/wąska strefa z poligonem, 4 jednostki | 54 | 108 | 54/54 legalne według D5.1, powtarzalne |
| Końcówka rundy 4, wszystkie rodziny, limit 16 aktywacji | 9 | 18 | 9/9 zakończone, powtarzalne, pełny replay |
| Pełne demo_skirmish/objective_clash, 7 kindów fast, grid/grid, seed 19, inicjatywa 0, limit 256 | 14 | 28 | 14/14 zakończone, powtarzalne, pełny replay |

Łącznie **239 przypadków / 478 wykonań**, zero niepowtarzalnych par.
Przypadek liczymy raz; drugie wykonanie sprawdza powtarzalność. `minimax`
i `claude_v2` mają wszystkie małe scenariusze i deployment, lecz pełną grę
tylko od rundy 4 z dwiema jednostkami. Nie ekstrapolować ich czasu lub
zakończenia na wielkie armie. Domyślne `claude_v2.samples=2` zachowane.

Wynik zapisuje manifest/digest, Python/platformę, commit bazowy, hash
skryptu i fixture, seedy, akcje, odrzucone decyzje, replay i czasy. Digest
kanonicznego manifestu:
`233108c91ff2e0cb9403bac5aa7077cbb70f3a7db6d819b0adca8326d020c572`.
Hashe bajtów mogą zależeć od normalizacji CRLF/LF; deterministyczne pola
porównuje `deterministic()`. Czasów nie porównujemy jako warunku replay.

## Bot × protokół × scenariusz

SSOT katalogu/tagów: `agents/registry.py`; konstrukcji: `factory.make_player`.
`claude` jest aliasem fabryki do `claude_v1`, nie dziesiątą rodziną rejestru.
`claude_v*` to lokalny kod heurystyk, bez zewnętrznego modelu i opłat.

`16/16` oznacza pierwsze nieterminalne decyzje w 8 pozycjach × 2 seedy
akceptowane przez resolver, a nie certyfikat reguł. Deployment każdego
kinda: 6/6 przypadków; końcówka: 1/1. Kolumna drugiej akcji liczy 16
wywołań callbacka na rodzinę, bez powtórzenia czasowego.

| Kind | Tagi obecne | v1 kandydat / druga akcja | Pełne fixture | v2 lifecycle | v3 attack lifecycle |
|---|---|---|---|---|---|
| priority | useful, fast | 16/16; 16 akcji | 2/2 | brak | brak |
| priority3 | useful, fast | 16/16; 16 akcji | 2/2 | brak | brak |
| claude_v3 | useful, fast | 16/16; 16 akcji | 2/2 | brak | brak |
| random | reference, fast | 16/16; 10 akcji | 2/2 | brak | brak |
| greedy | reference, fast | 16/16; 10 akcji | 2/2 | brak | brak |
| priority2 | reference, fast | 16/16; 16 akcji | 2/2 | brak | brak |
| claude_v1 | reference, fast | 16/16; 10 akcji | 2/2 | brak | brak |
| minimax | reference, expensive | 16/16; 1 akcja | poza próbką | brak | brak |
| claude_v2 | reference, expensive | 16/16; 6 akcji | poza próbką | brak | brak |

Wszystkie żądane kontynuacje zachowały oddział i przeszły istniejący SSOT
`_can_take_followup`/`can_append_activation_action_type`; zastosowano 1–2
akcje, bez trzeciej. Nie dowodzi to walidacji statusów lub wyjątku
Niestrudzonego. `run_match` i publiczna propozycja to inne orkiestracje:
runner używa `apply_activation` z callbackiem, propozycja `apply` i zamyka
aktywację po jednej akcji. Powtórny POST tej samej jednostki nie zastępuje
kontynuacji. Limit dwóch akcji i przerwania przed każdą opisuje
[Rozjemca, pkt 11.b.i–vi](../app/static/docs/SZOP_Rozjemca.md).

Po E4 boty reużywają `ManeuverPlanner`, a resolver sprawdza osiągalność
tej samej pozycji. W poligonie było 17 Manewrów i 1 Obrona; przy długiej
ścianie 12 lokalnych Manewrów i 6 Obron (18 decyzji na scenariusz).
Zgodność osiągalności nie dowodzi znalezienia najlepszego objazdu.
Próbka deployment używa D5.1 z rosnącym `occupied`; wąska strefa ma 6×2″,
poligon Niedostępny zajmuje jej narożnik. Brak bounded-exhaustion w tej
próbce nie dowodzi, że strategia zawsze znajdzie istniejące miejsce.
Źródło ograniczeń: [pkt 2.d, 4.c.i/iv, 13.a, 15 i 24](../app/static/docs/SZOP_Rozjemca.md).

Cel w `objective_edge`: środek 2,5″ od środka oddziału o promieniu 0,5″;
`_check_objective_control` daje P0, zgodnie z
[pkt 5.d–f](../app/static/docs/SZOP_Rozjemca.md). Boty używają tego SSOT
lub wspólnej stałej, bez nowej kopii progu w harnessie. Wybór strzelania
zamiast ruchu przy tym celu jest kwestią polityki, nie błędem odległości.

## Konkretne ograniczenia legalności

1. **Bliski wróg a Shoot.** W `contact` dystans obwód–obwód wynosi 1″,
   brak zasłony. `priority`, `priority2`, `priority3`, `claude_v3` wybierają
   Shoot dla obu seedów; `apply` go wykonuje. To sprzeczne z
   [pkt 14.c.iv](../app/static/docs/SZOP_Rozjemca.md), odczytanym w tej sesji.
   Regresja `test_contact_shoot_is_resolver_accepted_but_not_a_rule_conformity_proof`
   utrwala reprodukcję. `base.legal_actions` sam opisuje się jako enumerator,
   lecz jego komentarz o pełnej walidacji przez resolver jest zbyt mocny.

2. **Statusy.** `random`, seed 19, strzela jako Wyczerpany; seed 11 wykonuje
   Manewr jako Przyszpilony. Greedy/claude_v1 w obu seedach po ruchu nadal
   Wyczerpanego żądają Shoot; po Shoot Przyszpilonego żądają Manewru.
   Minimax seed 19 także dochodzi do Manewru Przyszpilonego. Resolver to
   akceptuje. Źródło: [pkt 22.a.i i 22.b.i](../app/static/docs/SZOP_Rozjemca.md).
   Odtworzenie: `decision_once(kind, seed, 'exhausted'|'pinned')`; pełne
   akcje są w `results.json`. Nie mylić z bezpiecznym Shoot Przyszpilonego,
   którego sam ten status nie zabrania.

3. **Zakończenie i strona.** Siedem kindów fast zwraca akcję na terminalnej
   pozycji; minimax/claude_v2 zwracają `None`. Resolver odrzuca terminalną
   akcję. Samo przekazanie obcej `perspective` nie zatrzymuje wyboru bota;
   odrzucenie należy do resolvera/owner guardu. Adapter ma sprawdzić te
   warunki przed decyzją, nie traktować `None` jako polecenia mutacji.
   Regresje terminal/wrong_perspective; źródło końca:
   [pkt 5.g i 8.a](../app/static/docs/SZOP_Rozjemca.md).

4. **Zdolności i role.** Jedyną celowo emitowaną akcją specjalną jest
   `discard_exhausted`; boty nie planują Rozkazu, Oznaczenia, recovery,
   deployment zdolności ani wyboru przerwań. Domyślne
   `ChargeAction.counter_attack_declared=True` nie jest decyzją agenta
   broniącego. Kontratak jest opcją obrońcy według
   [pkt 14.d.iv i 17](../app/static/docs/SZOP_Rozjemca.md).
   Znane ograniczenia [Planowania/Mobilizacji](planowanie-spec.md) i
   [Niestrudzonego](niestrudzony-spec.md) to ograniczenia silnika/lifecycle,
   nie dowód słabej polityki. Powtórzenia Niestrudzonego wymagają kontekstu
   pasywów, którego obecny SSOT action-type nie przyjmuje; wyjątek ma
   źródło w [poz. 14](../app/static/docs/SZOP_Zdolnosci.md) i pkt 14.c.v/14.d.vi.

Nie poprawiano tych usterek w audycie. Wyniki zwycięstw z historycznych
symulacji są wynikami obecnej implementacji, a nie dowodem wiernej gry
według całego źródła. Reprodukcje akceptujące lukę należy zmienić na
odrzucenie w etapie naprawy, zamiast chronić błąd jako kontrakt produktu.

## Prediction i dane bez prywatnego RNG

Publiczny `BattleState` zawiera pozycje/promienie, żywe modele/rany,
quality/defense, profile inventory, statusy/pasywy i override'y,
teren/poligony, cele/kontrolę, rundę, aktywną stronę i initial-toughness
snapshot. To wystarcza do obecnych heurystyk; wszystkie decyzje z harnessu
powstają po publicznym round-trip. Nie potrzebują ORM ani roster DB.

Greedy, priority2/3, claude_v1/3 używają `expected_damage`; priority opiera
wybór na priorytetach/dystansie. Minimax i claude_v2 wykonują lokalne
próbki resolvera z własnym seedem, nie kontynuują serwerowego RNG. Random
ma własny `random.Random`; powtarzalność oznacza świeżą instancję z tym
samym seedem i tą samą historią wywołań. Ponowne użycie jednego obiektu
Random po innym deployment/callbacku zmienia jego dalszy wybór.

Prediction daje rozkład, nie dokładny przyszły wynik rzutu. Uruchomiono
istniejący pakiet `test_prediction_vs_simulation` (Monte Carlo 8×500 oraz
500 z osłoną), efekty i activation-protocol. Test
`test_ostrozny_prediction_matches_closed_v3_monte_carlo` sprawdza oddzielny
opt-in `state=closed_v3`; istniejące call sites botów tego argumentu nie
podają. **Boty nie są zatem świadome nowego Ostrożnego v3**. V1 zachowuje
legacy zachowanie. Warunek 12″ pochodzi z
[Zdolności, poz.23](../app/static/docs/SZOP_Zdolnosci.md), a decyzja
użytkownika ogranicza bonus do dystansowych. Nie włączono tego kontekstu
globalnie ani publicznego katalogu X; patrz
[publication-spec](oznaczenie-publication-spec.md).

## Publiczny lifecycle i granica propozycji

| Kontrakt | Dane / wymagane przejście | Obecna zdolność botów i adaptera |
|---|---|---|
| v1 | Metadata uczestników i wersji; state+sequence z jednego GET; actor owner/active-player; `szop.action/v1` | Kandydat istnieje. Jedna propozycja kończy jedną aktywację; brak przerwań i kontynuacji. Pozytywny dowód priority. |
| v2 | initiative, selected_unit, controlling/priority player, activation/window IDs i versions; start→pass/interrupt→ACTION_READY→commit→continue/finalize | Bot zwraca tylko Action. Nie wybiera strony priorytetu, nie obsługuje okien i nie ogranicza choose_action do już wybranego oddziału. HttpClient ma metody transportowe, ale obecna propozycja ich nie reprezentuje. |
| v3 | Dodatkowo intent kanonicznego inventory, attack ID/version, atakujący/cel/role, ATTACK_WINDOW, pass/grant, resolve i cleanup | Żaden bot nie jest orkiestratorem v3. Shoot/Charge bezpośrednio z choose_action nie jest kompletną deklaracją lifecycle. Brak typu consent proposal dla tego przebiegu. |

Ścieżka faktyczna: `szop_client/http.py:propose_battle_action` →
`app/routers/agent_proposals.py:create_battle_action_proposal` →
`app/services/battle_actions.py:prepare_battle_action`; approval ownera →
`stage_battle_action`. MCP deleguje do tego samego HttpClient, bez ORM/DB.
Nie istnieje moduł `app/services/battle_action_proposals.py`.

**Reprodukcja v2:** test
`test_legacy_proposal_has_no_v2_lifecycle_and_fails_at_v1_checkpoint`
zapisuje prawidłowy checkpoint v2 w SQLite in-memory. Utworzenie legacy
propozycji przechodzi, lecz approval kończy się `BattleStateCodecError`
(`v1 checkpoint cannot contain initiative or activation state`). Po
rollbacku bitwa/checkpoint/eventy są nietknięte, propozycja pozostaje pending.
To brak jawnego gate'u wersji w consent path, a nie wsparcie v2. Dla v3
nie wykonano analogicznego consent flow; brak reprezentacji i użycie
legacy persist wystarcza, aby **nie deklarować gotowości**. Nie obchodzić
tej granicy direct-write endpointem ani prywatnym core.

Pomiar HTTP użył istniejącego `_parity_world` z test_clients_parity:
FastAPI TestClient, SQLite in-memory, dwa własne rostery, seed 19,
initiative 0, v1, kind priority. Do testowej aplikacji dodano istniejący
router propozycji i istniejący scope `agent_proposals:create`; nie zmieniano
produkcji. Odczyt metadata → `get_state_checkpoint` → choose_action →
`action_to_json` → `propose_battle_action` dał pending; zatwierdzenie przez
istniejący serwis ownera dało executed, sequence 2→6. To pozytywny dowód
transportu Shoot na tej fixture, nie naprawa problemów legalności wyżej.
Wersjonowany test priority-public-snapshot osobno utrwala consent flow.

| Krok | Requesty adaptera | Zmierzone SELECT | Pozostały SQL |
|---|---:|---:|---|
| GET metadata | 1 | 4 | 1 INSERT audytu + 1 UPDATE last_used |
| GET state+sequence | 1 | 5 | 1 INSERT audytu + 1 UPDATE last_used |
| Decyzja in-process | 0 | 0 | 0 |
| POST propozycji | 1 | 6 | 3 INSERT (audyt auth/proposal/create) + 1 UPDATE last_used |
| Razem adapter | **3** | **15** | brak zapisu Battle/event/checkpoint |
| Owner approval, osobna czynność | poza adapterem | 8 | 3 UPDATE + 6 INSERT w tej próbce; bez lookup ownera |
| Kontrolny GET po approval | poza adapterem | 5 | standardowy audyt/last_used |

SQL liczono przez `before_cursor_execute` od osobnych requestów, po
przygotowaniu fixture. Liczba INSERT eventów approval zależy od akcji.
Auth bearera zapisuje audit/last_used również podczas odczytów; nie
utożsamiać braku zapisu domeny z zerowym SQL. To pomiar tej izolowanej
próbki, nie globalny pułap API. Przyszły adapter ma ponownie potwierdzić
budżet i nie dodawać odczytów rosterów/jednostek per kandydat.

## Efekt strony po D5.3b

Z istniejących wyników, bez nowych gier, zliczono każdy przypadek raz:

| Rozstawienie lustrzane | Inicjatywa | Przypadki | P0 / P1 / remis |
|---|---:|---:|---:|
| grid/grid | 0 | 60 | 34 / 2 / 24 |
| grid/grid | 1 | 60 | 24 / 6 / 30 |
| objectives/objectives | 0 | 60 | 20 / 34 / 6 |
| objectives/objectives | 1 | 60 | 22 / 32 / 6 |

W obu mirrorach zmiana `swap` daje identyczne agregaty dla 60 przypadków
na wartość (grid 29/4/27, objectives 21/33/6). Sama inicjatywa ani zamiana
oryginalnej armii nie wyjaśniają więc całego obserwowanego rozkładu.
Słaba komórka objective_clash/priority3 ma przy inicjatywie 0 cele 4/grid 8
(12 przypadków), a przy inicjatywie 1 cele 6/grid 4/remis 2 (12). Są to małe,
skorelowane grupy, nie estymacja uniwersalnej przewagi.

Harness wykazuje dwa rzeczywiste czynniki strukturalne:

- `grid_positions` zachowuje porządek rosnących x/y i slotów ID po obu
  stronach. Odbicie y→48−y zbioru slotów nie zachowuje przypisania tego
  samego indeksu/roli jednostki. Dla 4 slotów dolny lewy ma y=0,5, a
  odpowiadający indeks u góry y=36,5 zamiast 47,5. Sama symetria zbioru
  pozycji nie oznacza symetrii profili/przypisania jednostek.
- Dwa jednakowo odległe cele w kolejności A/B versus B/A zmieniają
  pierwszy Manewr priority z (0,6) na (0,−6) przy niezmienionej geometrii.
  Kod dodatkowo rozstrzyga remisy przez ID, kolejność kandydatów i stały
  porządek siatki E4; objectives-deployment ma tie-break target ID/x/y.

To dowód braku niezmienniczości pewnych decyzji względem permutacji lub
odbicia z zachowaniem ról, **nie dowód jednej przyczyny wyników meczów**.
Nie przeprowadzono kontrolowanego ablation/relabel, który izolowałby
wpływ tych czynników od map, kolejności losowań RNG i trajektorii walki.
Uniwersalna przyczyna efektu strony pozostaje nierozstrzygnięta. Zachować
grid jako default, objectives jako opt-in; nie zmieniać tagów/rankingu.

## Minimalny tryb i prerekwizyty D6.2

**Kandydat: `priority`, świeża instancja z jawnym seedem, publiczny v1,
bounded one-step, istniejąca propozycja zatwierdzana przez ownera.**
Publiczny stan wystarcza; brak wymogu nowego API, kont, modelu lub RNG.
Bezpieczny początkowy zakres decyzji: Manewr, Mobilizacja (`DefendAction`)
albo znane `discard_exhausted`, z poniższymi ograniczeniami. Gdy bot
wybierze nieobsługiwany kandydat, adapter zwraca jawny brak propozycji;
nie zmienia akcji/polityki i nie wybiera ukrytego fallbacku.

1. Przed decyzją: metadane i checkpoint muszą wskazywać v1; runda walki,
   nie game-over; jawna perspective zgodna z active_player; aktor żywy,
   na Froncie, nie Aktywowany. Jednostka i profile pochodzą z publicznego
   stanu. Owner/scope pozostają obowiązkiem serwera, bez zaufania do
   przesłanego owner ID. `battle:read` + `agent_proposals:create`, bez
   nowego `battle:act` lub wildcarda.
2. Odrzucić nieobsługiwane statusy/scenariusze, w tym Manewr
   Przyszpilonego i Mobilizację Przyszpilonego (znany drift mutex), oraz
   niezweryfikowane mechaniki terenu/zdolności. Pierwszy minimalny tryb:
   profile bez pasywów, zdolności broni/override'ów i pending effects;
   terrain bez cechy Niebezpieczny. Obecny legacy handler bada punkt
   końcowy, a [pkt 4.c.v](../app/static/docs/SZOP_Rozjemca.md) mówi o ruchu
   przez teren. Reużywać walidację/codec/planer SSOT; bez kopii silnika.
3. Shoot/Charge oraz inne zdolności pozostają poza tym początkowym
   trybem do naprawy i regresji wspólnego walidatora. Istniejący transport
   umie je przenosić, ale wykryte luki nie pozwalają obiecać regułowej
   legalności. Rozszerzenie walki wymaga osobnego jednoznacznego zakresu;
   audyt nie upoważnia do poprawiania silnika przy adapterze.
4. `get_state_checkpoint` dostarcza stan i expected_sequence razem;
   nie składać ich z dwóch odczytów. Jeden POST proposal, bez retry po
   niepewnym timeout i bez automatycznego approval. Stale/422/403 oraz
   nieobsługiwany kind/protokół kończą krok jawnym wynikiem. Nieznany
   kind nie może spaść na alias/default; źródłem kindów pozostaje rejestr,
   audytowany zbiór wsparcia nie jest równy tagowi useful/fast.
5. V2/v3: najpierw potrzebny projekt consent-gated operacji lifecycle i
   jawny protocol gate, z ID/version/role/sequence oraz osobnymi wyborami
   przerwań/kontry. Obecny HttpClient i prywatny executor nie dają zgody
   na obejście proposal. To prerekwizyt przyszłego rozszerzenia, poza
   ograniczonym D6.2 v1. Żadna rodzina nie ma gotowego orchestratora.
6. D6.2 ma utrwalić izolowany HTTP flow wybranego trybu, owner approval,
   brak duplikatu, zły scope/expiry, foreign/missing, stale, timeout i
   brak retry, liczbę requestów/SQL oraz czas decyzji. Obecny dodatni
   pomiar i regresje są podkładem, nie gotowym adapterem.

To rekomendacje techniczne w zaakceptowanym zakresie, bez nowej decyzji
o uprawnieniach. Pełna autonomiczna gra, publikacja X i poprawki silnika
nie zostały uruchomione. D6.3 może podzielić te braki na osobne etapy.

## Koszt i weryfikacja

Po 32 pomiary pierwszej decyzji nieterminalnej na kind (8 pozycji ×
2 seedy × 2 powtórzenia); po 32 callbacki kontynuacji. Pomiar bez
równoległego pytest. Pierwszy pomiar priority był odstający (59,789 ms);
nie izolowano kosztu zimnych cache/importów ani szumu systemu, dlatego
nie wyliczamy nowych relacji kosztu ani tagów.

| Kind | Pierwsza decyzja mean / max ms | Kontynuacja mean ms |
|---|---:|---:|
| priority | 2,123 / 59,789 | 0,358 |
| priority3 | 0,391 / 1,276 | 0,299 |
| claude_v3 | 0,315 / 1,231 | 0,406 |
| random | 0,444 / 1,249 | 0,439 |
| greedy | 0,753 / 1,932 | 0,574 |
| priority2 | 0,293 / 1,069 | 0,359 |
| claude_v1 | 0,553 / 1,287 | 0,500 |
| minimax | 4,706 / 11,244 | 5,296 |
| claude_v2 | 3,465 / 5,674 | 3,015 |

Maksimum deployment w małej próbce: 47,703 ms; pełnej fixture fast: 114,485 ms.
Nie są to SLA ani koszt dla dowolnej liczby kandydatów. Nowy in-process
harness nie wykonuje zapytań SQL; pomiar requestów ma oddzielną izolację.

Testy audytu/propozycji: **35 passed, 1 dependency warning** (4,76 s),
w tym 28 dodanych przypadków testowych. Celowane wszystkie `test_agents_*`,
audit, regression/pathfinding, prediction/effects/activation_protocol,
clients parity/http/activations, proposals/token security/battles i
deployment experiment: **1007 passed, 1 dependency warning** (18,63 s).
Pełny `pytest -q`: **4053 passed, 4 warnings**, 218,59 s. Ostrzeżenia
dotyczą zależności reportlab/openpyxl. Historyczne 4025 z D5.3b nie jest
przedstawiane jako wynik tego audytu.

Przeprowadzono ręczne odpowiedniki simplify/review (slash niedostępne):
zmniejszono import-path fixture, zachowano jedną enumerację i walidację
SSOT, porównano replay/wejścia, ograniczono próbki i oddzielono transport
od reguł. Call-site audit: nowy skrypt jest liściem CLI importowanym tylko
przez test audytu; nie zmieniono podpisów/wywołań produkcyjnych. Dwa testy
proposal używają istniejących isolated helpers. Security review obejmuje
owner/scope/no-oracle, frozen payload, stale, rollback i brak sekretów
w artefaktach; istniejące testy tych granic w pakiecie 1007 są zielone.
Luka v2 jest jawnie udokumentowana i nie rozszerza uprawnień.

## Przeniesienie

Raport, manifest, wyniki, harness i regresje są w Git. Oddzielny commit
etapu na Faza_A oraz potwierdzenie origin/Faza_A są częścią zamknięcia.
Odtworzyć zależności z requirements, nie przenosić lokalnej `.venv`.
`data/szop.db` pozostaje nietknięta, SHA256:
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Baza i lokalne sekrety/konfiguracja wymagają osobnego backupu. Scheduler
i lokalny runtime koordynatora nie są częścią tego artefaktu. Cudze
zmiany/hunk B6.2 i historyczne HANDOFF pozostają poza commitem.
