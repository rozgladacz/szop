# D6.3 — plan dojścia do gry z botem w UI

Data: 2026-11-20. Baza: `23022eb9becbf883ec020a3f5ca669d3b7d499f1`
na `Faza_A`. To wynik planowania, bez wdrożenia UX, API, auth, modelu,
procesu w tle ani zmian silnika. Poniższe etapy są **propozycjami do wyboru**;
żaden nie otrzymuje automatycznej akceptacji lub markera gotowości.

Rekomendowany następny wybór: **P1 — jawne odrzucenie v2/v3 w legacy consent**.
To mała, samodzielna poprawka istniejącego kontraktu, zanim nowy interfejs
zwiększy liczbę jego wywołań. Pierwszy użyteczny przyrost UI to P2–P5:
jedna ograniczona propozycja `priority` dla istniejącej bitwy v1, a następnie
osobne kliknięcie właściciela. Pełna gra wymaga dalszych prerekwizytów.

## Punkt wyjścia i SSOT

Stan kodu odczytano w tej sesji. Dokumenty opisują wynik implementacji,
a nie gwarancję legalności wszystkich decyzji botów.

| Obszar | Istniejący kontrakt i granica | Miejsca do ponownego odczytu przy implementacji |
|---|---|---|
| Obserwacja | Participant-scoped state + `sequence_at` z jednego GET, bez prywatnego RNG; metadata jest osobnym odczytem | [HttpClient](../szop_client/http.py), `get_battle_metadata`/`get_state_checkpoint`; [router](../app/routers/battles.py), `get_battle_state`; [ADR-0053](adr/0053-versioned-battle-checkpoints.md) |
| Podgląd | `/battle-preview`, v1/v2/v3, odczyt i zaznaczanie, ręczny reload; viewport dopasowany do danych nie definiuje granic planszy | [battle_canvas.js](../app/static/js/modules/battle_canvas.js), `parseCheckpoint`/`createLoader`/`mount`; [main.py](../app/main.py) |
| Boty | Rejestr dziewięciu kindów i fabryka z seedem; tag useful/fast nie oznacza wsparcia protokołu | [registry.py](../app/services/agents/registry.py), [factory.py](../app/services/agents/factory.py); [audyt D6.1](boty-audit.md) |
| Ograniczony adapter | Tylko priority/v1, świeża instancja i jawny seed, jeden krok Manewr/Mobilizacja/discard_exhausted; pusty teren, bez zdolności i pozostałych wykluczonych stanów | [bot_proposals.py](../szop_client/bot_proposals.py), `BotProposalAttempt.run`; [D6.2](boty-connect.md) |
| Consent v1 | Pending nie zmienia bitwy. Owner-session approve wykonuje akcję; repeated approve executed jest idempotentnym odczytem wyniku | [agent_proposals.py](../app/routers/agent_proposals.py), `create_battle_action_proposal`/`_execute_battle_action_proposal`; [battle_actions.py](../app/services/battle_actions.py), `prepare_battle_action`/`stage_battle_action`; [ADR-0024](adr/0024-consent-gated-agent-writes.md) |
| Approval UI | Istniejący panel właściciela listuje propozycje i osobno zatwierdza/odrzuca | [agent_proposals.js](../app/static/js/modules/agent_proposals.js), `loadAgentProposals`/`decideAgentProposal` |
| Aktywacje v2/v3 | Publiczne start/interrupt/pass/action/continue/finalize; v3 dodatkowo declare/resolve ataku. HttpClient ma transport, lecz bot ani consent go nie orkiestrują | [battle_activations.py](../app/services/battle_activations.py), `stage_battle_activation_*`; [activation_protocol.py](../app/services/engine/activation_protocol.py); [ADR-0056](adr/0056-interrupt-activation-protocol.md) |
| Utworzenie i rozstawienie | `BattleCreate` wybiera dwa własne rostery, seed, inicjatywę i protokół. `stage_battle_creation` wywołuje `deployment_round(state, ())`; nie jest kreatorem strategii D5 ani trwałym interaktywnym round-0 | [battle_creation.py](../app/services/battle_creation.py), [router](../app/routers/battles.py), `BattleCreate`/`create_battle` |
| Strategie rozstawienia | D5.1/2/3 działają w lokalnej orkiestracji: strefa, occupied, grid/objectives i bounded fallback; nie są automatycznie publiczną konfiguracją bitwy | [deployment.py](../app/services/agents/deployment.py), `is_deployment_position_legal`/`objective_deployment_choice`; [match.py](../app/services/agents/match.py), `_build_deployment_from_players`/`simulate_from_rosters`; [D5.3b](experiments/d5_3b/README.md) |

`app/static/js/battle_state.js` przechowuje edycyjny „Stan bitewny” rozpiski;
nie zastępuje event-sourced checkpointu toczącej się bitwy. `run_match`
wykonuje lokalną grę z callbackiem i nie jest serwerowym executorem sesji UI.
Klient nie importuje ORM, nie czyta DB i nie wykonuje bezpośrednio resolvera.

## Reguły i udokumentowane przeszkody

Odczytane źródło: [SZOP_Rozjemca.md](../app/static/docs/SZOP_Rozjemca.md).
Przerwania poprzedzają każdą akcję; powrót do kolejnej zależy od warunków
pkt **11.b.i–vi**, w tym limitu dwóch akcji. Kolejność i pełne rozpatrzenie
przerwań określa **12.a–c**. UI ma odwzorować stan protokołu, a nie dopisywać
okna po każdej fazie na podstawie starszych ADR. Kontratak jest wyborem
obrońcy według **14.d.iv**; domyślny bool `counter_attack_declared=True`
w kandydacie bota nie dokumentuje takiego wyboru.

W [D6.1](boty-audit.md) istnieją reprodukcje resolver-accepted Shoot z bliskim
wrogiem, ataku Wyczerpanego i Manewru Przyszpilonego. Właściwe ograniczenia
źródłowe: **14.c.iv**, **22.a.i**, **22.b.i**. Mobilizacja i mutex stanów
wymagają osobnej regresji zgodnej z **14.b**, **22.b.iii/22.c.iv**.
Te usterki nie zostały naprawione przez D6.2; jego capability gate tylko
zawęża zakres. Nazwa `legal_actions` nie jest dowodem pełnej legalności.

Runda rozstawienia i dozwolone miejsce mają źródło w **9**, **13.a–c**
i **24**. Niebezpieczny dotyczy przejścia przez teren (**4.c.v**), więc
bezpieczna pozycja końcowa nie dowodzi bezpiecznej trasy. D6.2 odrzuca
każdy niepusty terrain; poligony i `ManeuverPlanner` nie znoszą tego gate'u.
Kontrola celu pozostaje wspólnym SSOT zgodnym z **5.d–f** (promień 2″),
koniec gry z **5.g** i **8**. Żaden etap tego planu nie zmienia tych reguł.

W audycie consent v2 tworzy pending, lecz approval trafia do persist v1,
kończy się błędem codeca i rollbackiem; pending pozostaje. Dla v3 brak
pozytywnego przepływu. Nie wolno obchodzić tej luki przez `battle:act`.
Publiczny katalog Oznaczenia pozostaje osobnym zakresem
[publication-spec](oznaczenie-publication-spec.md); plan nie publikuje X.
Decyzja użytkownika „Ostrożny tylko dystansowo” pozostaje wiążąca.

## Opisowy prototyp przepływu

1. **Wybór sesji.** Początkowy wariant to istniejąca bitwa, wskazana strona
   i priority; kind/seed/protokół są jawne. Interfejs pokazuje ograniczenia
   i niedostępne opcje. Rekomendacja dla późniejszego kreatora: oba własne
   rostery sandboxu, jawny podział człowiek/bot, jedna strona bota; nie nowe
   konto przeciwnika ani automatyczny udział w cudzej bitwie.
2. **Odczyt.** Jeden checkpoint jest źródłem state i expected sequence.
   Błąd/brak spójnego headu blokuje przyciski. Metadata nie służy do
   doklejania nowego sequence do wcześniej obliczonej decyzji.
3. **Propozycja.** „Zaproponuj jeden krok” uruchamia jedną ograniczoną
   decyzję. Widoczne: bot, strona, operacja/aktor/cel, seed i head, stan
   pending. Capability unsupported oznacza czytelny koniec próby, bez
   zamiany na innego bota/akcję i bez zmiany bitwy.
4. **Zgoda.** Osobne „Zezwól i wykonaj” lub „Odrzuć” dotyczy dokładnie
   zamrożonej operacji. Wybranie bota ani poprzednia zgoda nie zatwierdza
   następnej operacji. Zmiana headu wymaga nowej obserwacji i nowej decyzji.
5. **Wynik.** executed pokazuje eventy i nowy checkpoint; rejected/stale
   zachowuje historię. Przed kolejnym krokiem UI uzgadnia lokalny widok
   z serwerem. Nie liczy obrażeń, rund ani końca gry w JavaScript.
6. **Przekazanie.** Po obsłużonej operacji interfejs wraca do człowieka,
   obrońcy albo aktualnej strony priorytetu. Późniejsze v2/v3 pokazują
   osobno start, okno, akcję, kontynuację i finalizację. Pass strony
   człowieka jest jej jawną decyzją. Polityka pass-only bota jest widocznym
   ograniczeniem zakresu, nie domyślną decyzją za obie strony.
7. **Stop/reload.** Stop zatrzymuje przyszłe planowanie. Przerwanie fetch
   nie cofa przyjętego POST; anulowanie po wysłaniu prowadzi do uzgodnienia
   wyniku. Reload/restart nie wysyła automatycznie poprzedniej komendy.

| Stan UI/próby | Następna dozwolona czynność | Zapis domeny |
|---|---|---|
| idle → loading → ready | Jawna prośba o jeden krok na bieżącym headzie | brak |
| deciding/submitting | Stop przyszłych kroków; brak drugiego submit | co najwyżej jedna propozycja |
| pending | Osobne approve/reject właściciela | pending nie wykonuje bitwy |
| executed/rejected/stale | Wyświetlenie wyniku i świeży odczyt, potem nowy jawny krok | tylko wynik zatwierdzonej operacji |
| unsupported / forbidden / invalid | Komunikat zakresu/uprawnień; bez fallbacku | brak zmian bitwy |
| uncertain po timeout/5xx/malformed | Rekoncyliacja istniejącej próby; bez nowego klucza i POST | wynik nieznany, nie deklarować rollbacku |
| terminal / stopped | Tylko odczyt, replay, nowa jawna sesja | brak dalszych komend |

## Budżety i wspólny warunek zamknięcia przyszłych etapów

To **proponowane gates do pomiaru**, nie nowe wyniki wydajności. Każdy etap
zapisuje surowy pomiar z określoną fixture, seedem, wielkością i środowiskiem.
Nowa tabela poniżej wskazuje budżet dla każdego zakresu przez jego kod.

| Kod | SQL/requesty | Czas i ograniczenie pracy |
|---|---|---|
| D | Dokumentacja: zero requestów/SQL i zmian runtime | Kontrola źródeł/linków/symboli, bez benchmarku wykonania |
| V | Istniejący dodatni D6.2: 2 GET + 1 POST = 15 SELECT (4+5+6), bot 0 SQL; zachować dla tej samej fixture | [Zmierzone D6.2](boty-connect.md): 1,216/0,061/0,061 ms decyzji to pojedyncze próbki, nie p95. Nowy gate: p95 decyzji priority ≤100 ms na 2 i ≤500 ms na 12 jednostkach, 100 prób na stałych seedach, bez I/O |
| K | Narzut trwałej deduplikacji ≤2 SELECT ponad zmierzony bazowy request; stały względem liczby jednostek. Retry tego samego klucza nie dodaje propozycji/eventów | Ten sam payload/klucz zwraca ten sam wynik; konflikt klucza kończy próbę. Pomiar p95 requestu ≤ bazowy p95 +20% +10 ms na tej samej maszynie |
| C | Jedna komenda/propozycja na request, bot/planer 0 SQL. Dla nowej operacji zapisać baseline, narzut consent ≤2 SELECT poza nią i owner lookup; brak SQL per kandydat | 1 decyzja i ≤1 POST na kliknięcie; brak pętli gry w request. p95 lokalnego planowania jak V; p95 komendy z consent ≤ baseline danej operacji +20% +10 ms |
| G | Wspólna geometria/walidacja 0 SQL i brak I/O; brak wzrostu zapytań `/quote` i `/rosters/{id}` | Porównanie p95 z bazą na tej samej fixture: ≤+20% +0,1 ms na wywołanie. Bez cache maskującego błędny kontekst |
| U | Render/wybór 0 SQL; ≤1 świeży GET checkpointu po znanym wyniku. Polling i SSE nie działają równolegle | Proponowane p95 renderu ≤50 ms dla 100 obiektów; duży stan 500 obiektów ≤100 ms. Pomiar w przeglądarce, obsługa klawiatury i stale response |
| S | Rozstawienie 0 SQL per kandydat; 1 batch rosterów, stały narzut nowego zapisu; maks. 1090 kandydatów/jednostkę jak D5.3 | Pomiar grid/objectives osobno dla 2 i 12 jednostek; p95 ≤ lokalny baseline D5 na tej fixture +20% +10 ms. Exhaustion jawny, bez nieograniczonego szukania |
| R | Odtwarzanie używa istniejącego bounded replay/events; bez roster queries i bez zapisów bitwy | Test restartu po każdym trwałym headzie; pojedyncza strona eventów na krok. Liczba kroków/rozmiar strony z istniejących limitów endpointu, bez „pobierz wszystko” |

Budżety nie są obietnicą twardego deadline'u procesu. Obecny timeout
HttpClient 10 s dotyczy pojedynczego requestu. Limit V jest gate'em pomiaru;
spóźnionej decyzji nie wolno wysyłać po zmianie/cancel headu. Twarde przerwanie
CPU wymaga osobno zaprojektowanej izolacji, nie `AbortController` ani zabicia
wątku w środku transakcji. Droższe boty nie są początkowo dopuszczone.
Auth audit/last_used oraz liczba INSERT eventów są mierzone osobno od SELECT;
brak mutacji bitwy nie oznacza braku zapisów audytu.

Każdy etap kodowy: encoding gate przed Pythonem, testy celowane, pełny
`pytest -q`, call-site audit, simplify, review i security-review przy
auth/input→DB. Po poprawce przeglądu ponownie testy. JS dodatkowo Node i
smoke działającej aplikacji: zmieniony przepływ, Zbrojownia, Edytor Armii,
Rozpiski. Payload parity według `AGENTS.md`. Testy HTTP używają izolowanej
SQLite, preview do odbioru obecnej bazy z danymi. Każdy etap kończy osobny
commit/push na `Faza_A`, wynik/testy/ograniczenia i instrukcja przekazania.

## Kolejność etapów do wyboru

Numery P1–P16 są identyfikatorami tego planu. Pojedynczy wybór nie akceptuje
reszty tabeli. „Nowy” przy pliku oznacza proponowany artefakt, nie istniejący
moduł. Warstwy: M=model/DB, B=backend/client, J=JS, C=CSS/template, T=testy,
D=dokumentacja; niewymienione warstwy pozostają poza danym etapem.

### P1. Fail-closed wersji w obecnych propozycjach

Zależność: D6.2. Zakres: jawny gate metadata/checkpoint v1 przy tworzeniu
legacy proposal i ponowny gate przed approval; existing v1 i stare pending
nie są migrowane lub reinterpretowane. DoD: v2/v3 oraz mismatch dają
kontrolowane odrzucenie bez eventów/checkpointu/RNG i bez częściowego claim,
v1 zachowuje dotychczasowy wynik. Nie dodawać nowych uprawnień ani protokołu.

Pliki/warstwy: `app/routers/agent_proposals.py`, `battle_actions.py`,
testy propozycji, docs (**B,T,D**). Budżet **V,C** — gate używa już ładowanej
bitwy/checkpointu, zero nowych SELECT. Testy: v1 positive, v2/v3/mismatch,
stare pending, owner/foreign/scope i approval race w
`test_battle_action_proposals.py`/`test_agent_proposals_router.py`.

#### Wynik P1

Tworzenie propozycji akcji i zatwierdzanie propozycji `pending` wymagają
metadanych bitwy v1 oraz dekodowalnego checkpointu v1 na aktualnym końcu
dziennika. Wspólna bramka działa przed rozstrzygnięciem akcji i użyciem RNG.
Niezgodność wersji lub błąd dekodowania zwraca HTTP 409. Zatwierdzenie cofa
przejęcie w tej samej transakcji. Propozycja pozostaje `pending`, a zdarzenia,
checkpoint i RNG zachowują wartości sprzed odmowy. Propozycje już rozstrzygnięte
korzystają z zapisanego wyniku. Konflikt sekwencji w zgodnej bitwie v1 nadal
oznacza `stale`.

Oba wywołania routera propozycji włączają bramkę w `battle_actions.py`.
Bezpośrednie akcje i testowe wywołania usług odtwarzania używają dotychczasowej
ścieżki. Router filtruje bitwę po uczestniku, a zatwierdzenie po właścicielu
propozycji. `HttpClient` korzysta z dotychczasowego HTTP 409, a adapter D6.2
kończy próbę po tym statusie.

W izolowanej próbie D6.2 każdy z trzech dodatnich przepływów nadal wykonał
15 zapytań SELECT (4 + 5 + 6), a decyzja bota wykonała zero zapytań. Pomiar
`choose_action` bez I/O, po rozgrzaniu i dla seedów 0–99, dał p95 0,112 ms
dla 2 jednostek i 2,725 ms dla 12. Próbka liczyła 1 lub 6 jednostek na stronę,
bez broni i terenu, z celem w `(24, 24)`. Pozycje miały `x = 6 + 6*i` dla
indeksu jednostki na stronie i `y` równe 6 lub 42.

Weryfikacja transportem HTTP objęła v2, v3, rozbieżne metadane i checkpoint,
nieobsługiwaną wersję checkpointu, uprawnienia, niezmienione bajty checkpointu
i RNG oraz zachowanie istniejącego `pending`. Regresje obejmują zatwierdzenie
v1, równoległe zatwierdzenia i odtwarzanie. Do powtórzenia na checkoutcie
`origin/Faza_A` z odtworzonym `.venv` i instalacją editable `szop_client`
wystarczą dane testowe z repozytorium.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q -s --tb=short tests/test_battle_action_proposals.py tests/test_agent_proposals_router.py tests/test_bot_proposals.py tests/test_battle_activation_transport.py tests/test_battles_router.py tests/test_agent_token_security.py tests/test_clients_http_replay.py tests/test_battle_replay_router.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
git diff --check
```

Zaliczono **314 testów celowanych i 4257 w pełnym zestawie**, z czterema
ostrzeżeniami zależności w pełnym przebiegu. Przegląd uproszczenia, kodu i
bezpieczeństwa sprawdził wspólny odczyt checkpointu, kolejność autoryzacji,
atomowy rollback oraz obsługę ponownego zatwierdzenia. Kolejny etap
zatwierdzonej kolejki to P6.

### P2. Zamrożenie kontraktu producenta i trwałej próby

Zależność: P1. Dokumentacyjny ADR: zamknięta komenda, identyfikator próby,
owner/battle/side/kind/seed/protocol/head i hash frozen payloadu, status/result,
retencja, reguła ponowienia i rekoncyliacji. Rekomendacja: ograniczony
producent serwerowy wywoływany jawną prośbą ownera, bez tokena w przeglądarce;
przed kodem określić jego tożsamość/proweniencję w `AgentProposal.agent_user_id`
i `token_id`, auth cookie/bearer oraz ochronę cross-site. Nie wytwarzać
ukrytego uprzywilejowanego tokena ani ogólnego executora.

Pliki/warstwy: nowy ADR + schema/examples i plan testów (**D**), budżet **D**.
DoD: request/response/error i migracja/kompatybilność opisane, crash before/
after commit, dwa procesy i inny payload dla tego samego klucza rozstrzygnięte.
API i reguły dostępu P3/P4 określa zaakceptowany ADR-0060.

#### Wynik P2

Projekt przewiduje serwerowego producenta `priority/v1` zlecanego przez
sesję właściciela, trwałą próbę z unikalnym ID i osobną zgodę na wykonanie
propozycji. Ustalono 24 h na ponawianie tego samego ID i 30 dni odczytu
wyniku. ADR określa tożsamość producenta, regułę Origin, addytywną migrację,
transakcję i zachowanie po awarii, a także przykłady API i przypadki odbioru.
Użytkownik zaakceptował kontrakt 2026-11-25. Do kontynuacji P3 na innym
komputerze wystarcza checkout `origin/Faza_A` i ADR.
[Zaakceptowany kontrakt](adr/0060-server-bot-proposal-attempts.md)

### P3. Trwała deduplikacja tworzenia v1

Zależność: zaakceptowany P2. Zakres: implementacja tylko trwałej próby i
atomowego powiązania z jedną propozycją. Istniejący endpoint zachowuje
kompatybilność według P2; nowy tryb nie myli idempotencji approve z create.
Klucz jest owner-scoped, nie służy do odczytu cudzej próby. Ten sam klucz
i zmieniony frozen payload to konflikt, nie aktualizacja propozycji.

Pliki/warstwy: `app/models.py`, istniejący `_migrate_schema`/`create_all`,
router propozycji, `szop_client/http.py`, nowe testy idempotencji (**M,B,T,D**).
Budżet **K**; unique/index obejmuje tożsamość i klucz, nie liniowy scan.
DoD/testy: równoległe dwa połączenia SQLite, restart, timeout po commit,
rollback, expiry/foreign, stable result i zgodność starych klientów;
zero dodatkowych eventów i RNG przy retry.

#### Wynik P3

`app/db.py` dodaje nullable `producer_owner_created_at` do istniejącej
tabeli propozycji. `Base.metadata.create_all` tworzy rejestr prób z unikalnym
kluczem właściciela, generacji i próby, unikalnym powiązaniem z propozycją
oraz indeksem retencji. Ogólne i tokenowe tworzenie propozycji, zatwierdzenie,
odrzucenie, wykonanie i oznaczenie `stale` zachowują format audytu
po przeniesieniu jego zapisu do wspólnego modułu. Przy wyłączonych FK ścieżka retencji usuwa wyłącznie
wiersze prób. W aplikacji nie ma ścieżki usuwania propozycji.

`create_bot_proposal_attempt` dostaje wcześniej uwierzytelnioną tożsamość
właściciela, kanoniczne polecenie i funkcję przygotowania. Po uzyskaniu
blokady `BEGIN IMMEDIATE` ponownie sprawdza żywe konto, generację i stronę.
Wspólna transakcja zapisuje wynik i ewentualną propozycję `pending` z audytem
`create`. Zgodne ponowienie zwraca zapisany wynik po sprawdzeniu okna ID,
również po zmianie headu. Rekoncyliacja używa `get_bot_proposal_attempt`,
a `purge_bot_proposal_attempts` usuwa po retencji jedną ograniczoną partię
wierszy z rejestru. Okna wynoszą 24 h na ponowienie i 30 dni na odczyt.
Czas oczekiwania SQLite w transakcji rejestru jest ograniczony do 2 s. Po zwolnieniu
połączenie odzyskuje poprzednią konfigurację.

P4 podłączy sesję i publiczny transport do wewnętrznego serwisu P3 oraz
przekaże funkcję przygotowania jednego kroku `priority/v1`. W testach P3
funkcja wywołuje istniejące przygotowanie akcji ze stałym wyborem. Kod
serwisu, testy i dokumentacja wystarczają do kontynuacji na innym komputerze.
Przed przeniesieniem używanej bazy wykonaj spójną kopię całej SQLite,
obejmującą rejestr prób, propozycje i audyt z tego samego momentu.

Pomiar na tym samym komputerze użył plikowej SQLite z tymi samymi danymi
i transakcją w trzech trybach. Baza porównania sprawdzała właściciela,
przygotowywała stały wybór i zapisywała propozycję z audytem, pomijając tabelę
prób. Dwie konfiguracje miały odpowiednio 2 i 12 jednostek. Dodatkowe
jednostki były kopiami jednostek z fixture `ledger_battle` w osobnych pozycjach.
Na każdy tryb przypadło 5 uruchomień rozgrzewkowych i 60 mierzonych prób
w przeplatanej kolejności, seed 19. Czas blokady liczono od uzyskania jej
przez `BEGIN IMMEDIATE` do zwrócenia wyniku, tak aby objąć także commit.

| Jednostki | Tryb | SELECT | INSERT | p95 operacji | p95 od blokady do wyniku |
|---:|---|---:|---:|---:|---:|
| 2 | Baza | 3 | 2 | 9,572 ms | 9,357 ms |
| 2 | Nowa próba | 4 | 3 | 10,843 ms | 10,567 ms |
| 2 | Ponowienie | 2 | 0 | 2,268 ms | 2,102 ms |
| 12 | Baza | 3 | 2 | 11,638 ms | 11,390 ms |
| 12 | Nowa próba | 4 | 3 | 13,062 ms | 12,589 ms |
| 12 | Ponowienie | 2 | 0 | 2,416 ms | 2,251 ms |

Narzut rejestru wyniósł jeden indeksowany SELECT oraz jeden INSERT na nową
próbę. Oba pomiary mieszczą się w budżecie K. Testy D6.2 zachowały
15 SELECT (4 + 5 + 6) w dotychczasowej ścieżce. Pomiar HTTP nowej operacji
należy do P4.

Zaliczono 133 testy celowane i 4320 testów w pełnym zestawie. Cztery
ostrzeżenia dotyczyły zależności ReportLab i openpyxl.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_bot_proposal_attempts.py tests/test_db_schema_migrations.py tests/test_bot_proposals.py tests/test_agent_proposals_router.py tests/test_battle_action_proposals.py tests/test_agent_token_security.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```

### P4. Ograniczony producent priority/v1

Zależności: P1–P3 i zatwierdzona tożsamość/auth z P2. Zakres: jeden request
owner→jedna decyzja→pending na istniejącej bitwie, priority z jawnym seedem
i stroną. Reuse capability gate D6.2, registry/factory, codec i wspólnego
przygotowania propozycji; wydzielić SSOT orchestration zamiast importować
router jako bibliotekę lub kopiować HTTP do własnego procesu. Nadal bez
approve, execute, pętli, v2/v3, walki i terenu.

Pliki/warstwy: nowy leaf service/router producenta, `bot_proposals.py`,
propozycje i testy (**B,T,D**). Budżet **V,K**; zdublowane kliknięcie/klucz
nie tworzy drugiej próby. DoD/testy: trzy pozytywne akcje D6.2, unsupported
bez fallbacku, wrong side/protocol/owner, stale/cancel przed POST,
sekrety/redakcja, timeout/5xx i brak mutacji bitwy przed zgodą.

### P5. Pierwszy UI: jeden krok dla istniejącej bitwy

Zależność: P4. Zakres: przy istniejącym podglądzie wybór jawnej strony,
priority/seed, „Zaproponuj jeden krok”, pending i odnośnik lub reuse panelu
osobnej zgody. Zachować read-only `battle_canvas` jako projekcję; nie
implementować reguł ani drugiego executora w canvasie. Niedostępne stany
z instrukcją, a nie pusty ekran; brak autostartu po reload.

Pliki/warstwy: nowy moduł sterowania sesją, template podglądu,
`agent_proposals.js`, integracja w `main.py`/nawigacji tylko w razie potrzeby
(**J,C,T,D**, **B** wyłącznie wiring). Budżet **U,V,K**. DoD/testy:
Node deferred responses/double-click/cancel/keyboard, istniejące
`test_battle_preview.py` i `test_agent_proposals_frontend.py`, realny smoke
pending→osobne approve→executed→reload; odrzucenie i stale bez dalszego kroku.

### P6. Wspólna legalność walki i statusów

Zależność: P1; może poprzedzać P2–P5. Zakres: naprawić reprodukcje D6.1
(14.c.iv, 22.a.i, 22.b.i) i mutex Mobilizacji (22.b.iii/22.c.iv) we wspólnym
validatorze/outcome. Kandydaci botów i v1/v2/v3 korzystają z tego SSOT,
zamiast dodawać kolejne filtry wyłącznie w UI. Nadal bez publikacji zdolności
i zmiany polityk rankingowych. Golden drift uzasadnić w osobnym ADR.

Pliki/warstwy: `engine/resolver.py`, `phases.py`, protokół i
`agents/base.py` tylko konieczne delegowanie; audyt/regresje (**B,T,D**).
Budżet **G**. DoD/testy: dokładne granice odległości+LoS, statusy i mutex,
native/ability exclusion, wejściowe state/RNG bez zmian po błędzie,
prediction/replay i publiczny transport; dawne testy reprodukcji zmieniają
się na odrzucenie, a nie chronią istniejącego błędu.

#### Wynik P6

Wspólne ograniczenia rozdzielają wybór akcji od rozstrzygnięcia. Resolver
stosuje tę samą walidację przy pierwszym wyborze i kontynuacji v1.
Protokół używa jej przy wykonaniu v2 oraz przy deklaracji i rozwiązaniu
ataku v3. Odmowa pozostawia wejściowy stan i RNG bez zmian. Testy HTTP
sprawdzają niezmieniony head zdarzeń, checkpoint i RNG w v1–v3.
W v1 odrzucona kontynuacja zachowuje prawidłowo wykonaną pierwszą akcję.

`legal_actions` obsługuje wspólny filtr dla Random, Greedy, Minimax,
ClaudeV1 i ClaudeV2. Priority, PriorityV2, PriorityV3 i ClaudeV3
stosują te ograniczenia w wyspecjalizowanym wyborze, z zachowaniem
dotychczasowej kolejności i ocen opcji, które nadal są dostępne.
Strażnik i kontratak korzystają ze wspólnego sprawdzania dla swojego
aktora. [Reguły, granice geometrii i różnice B7](adr/0059-combat-action-restrictions.md)

Walidator działa na pamięciowym stanie, wykonuje 0 zapytań SQL oraz
0 operacji I/O. Ścieżki `/quote` i `/rosters/{id}` nie wywołują tego kodu.
Na Windows z Pythonem 3.13.14 p95 średnich z serii, w ms dla dawnej i nowej wersji
`_validate_action` wyniósł odpowiednio
0,001787 → 0,003205 w `ranged` i 0,001347 → 0,008047 w `contact`.
Obie różnice mieszczą się w budżecie G. Każdy pomiar liczył 100 serii
po 500 wywołań, poprzedzonych 1000 rozgrzewających wywołań.
Do odtworzenia P6 wystarczą repozytorium i `.venv` z zależnościami testowymi.
Zaliczono 960 testów celowanych, 23 testy osobnego gate B7 i 4296 testów
w pełnym zestawie. Cztery ostrzeżenia pochodzą z zależności.

Na trzech oryginalnych pakietach D7.3c osobna publikacja dała raport o
SHA-256 `31f68a1a9492344de6ad3c1aa2f5bd35583899aec799377a014d6531056a7f2b`.
Nowy ślad P6 z tym samym profilem rozstawienia wskazuje w raporcie
dodatkowy sprawdzony wariant źródła. Odtworzenie dawnych raportów wymaga
tych samych pakietów w osobnym backupie.
[Pakiety i polecenie](kwalifikacja-decyzji-kampanii.md#uruchomienie)

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short tests/test_bots_audit.py tests/test_engine_phases.py tests/test_engine_status.py tests/test_engine_activation_protocol.py tests/test_engine_replay_invariant.py tests/test_battle_activation_transport.py tests/test_battle_activations.py tests/test_bot_proposals.py tests/test_agents_match.py tests/test_engine_multi_action.py tests/test_engine_interrupts.py tests/test_engine_combat.py tests/test_agents_greedy.py tests/test_experiment_qualification.py tests/test_campaign_v1.py tests/test_export_decisions.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q tests/test_engine_regression.py
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q --tb=short
```

Pomiar powtórz poza pytest na bazie `0b99a06` i na commicie P6:

```powershell
@'
from time import perf_counter_ns

from app.services.engine.actions import ShootAction
from app.services.engine.resolver import IllegalActionError, _validate_action
from scripts.bots_audit import scenario

for name in ("ranged", "contact"):
    state = scenario(name)
    actor, enemy = state.blobs[:2]
    action = ShootAction(actor.id, enemy.id, actor.ranged_weapons[0])

    def sample():
        try:
            _validate_action(state, action)
        except IllegalActionError:
            pass

    for _ in range(1000):
        sample()
    durations = []
    for _ in range(100):
        start = perf_counter_ns()
        for _ in range(500):
            sample()
        durations.append((perf_counter_ns() - start) / 500)
    print(name, round(sorted(durations)[94] / 1_000_000, 6), "ms")
'@ | .\.venv\Scripts\python.exe -B -X utf8 -
```

### P7. Consent v2: start i pass

Zależności: P2–P3. Oddzielny, wersjonowany i zamknięty union komend v2,
obejmujący na początek tylko start i pass. Zamrozić battle/protocol/head,
selected unit albo activation/window IDs i ich expected versions. Dry-run
i approval współdzielą przygotowanie w `battle_activations.py`, bez commit
podczas proposal. Nie kierować v2 do `stage_battle_action` v1.

Pliki/warstwy: versioned command codec (nowy), router propozycji,
`battle_activations.py`, `szop_client/http.py`, ADR (**B,T,D**; **M** tylko
jeśli zatwierdzony P2 wymaga). Budżet **C,K**. DoD/testy: 201/202/200
odwzorowują istniejący transport, obcy/wrong priority, same-owner dwa jawne
passy, stale każdej wersji, concurrent approve i rollback/restart/replay
na każdym headzie. V1 nie dryfuje, inne operacje fail-closed.

### P8. Consent v2: akcja, continue i finalize

Zależności: P6–P7. Rozszerzyć zamknięty union tylko o te trzy operacje;
początkowo niebojowe akcje, brak aktywnych zdolności i recovery uses.
Odtwarzalna finalizacja i end-round delegują do istniejących stage/pure
transitions. Nie wysyłać drugiego legacy action zamiast continue.

Pliki/warstwy jak P7 (**B,T,D**), budżet **C,K**. DoD/testy:
selected actor, action count/history, continue po dozwolonym stanie,
finalize/recovery-empty, błędne phase/versions, crash i ponowne approve,
replay i przyszły RNG. Bazą są `test_battle_activations.py`,
`test_battle_activation_transport.py`, `test_clients_http_activations.py`;
nowe testy muszą przejść także przez proposal→owner approval.

### P9. Bot jako planner komend v2

Zależność: P8. Jeden odczyt→jedna typowana komenda, priority; osobno
wybór startowego oddziału, kandydat już wybranego oddziału i continue/finalize.
Reuse istniejącego `Player.continue_activation`/`legal_followup_actions` i SSOT
ograniczeń. Pass-only bota wyłącznie w jawnie wspieranym pustym zakresie
zdolności; strona człowieka/nieobsługiwane okno zatrzymuje planner.

Pliki/warstwy: nowy protocol planner obok adaptera, agents/base i factory
bez zmiany heurystyki, testy (**B,T,D**). Budżet **C**, bot 0 SQL.
DoD/testy: każdy obsługiwany phase, właściwa strona priorytetu, ta sama
jednostka przy kontynuacji, terminal/None bez mutacji, deterministyczny
restart planowania z frozen seed/head, zero implicit passów człowieka.

### P10. UI aktywacji v2 i decyzji człowieka

Zależność: P9. Pokaż selected unit, phase/priority, pending i historię.
Jedna komenda na jawne kliknięcie. Człowiek steruje swoją akcją/continue/
finalize oraz pass; bot nadal tworzy osobno zatwierdzane propozycje.
Jeśli wymagana aktywna zdolność nie jest obsługiwana, pokaż blokadę,
nie zamykaj okna za użytkownika. Nie rozszerzać auth.

Pliki/warstwy: moduł kontroli UI P5 + template, ścisłe adaptery wersji,
testy JS/HTTP (**J,C,T,D**). Budżet **U,C,R**. DoD/testy:
przejście całej niebojowej aktywacji obu stron, 202 nie oznacza zakończenia,
dwóch równoległych klientów, reload w oknie, konflikty i brak przycisku
nieuprawnionej strony; pełny smoke używający istniejącego checkpointu.

### P11. Kontrakt consent v3 i decyzji kontrataku

Zależności: P6, P8. Najpierw oddzielny ADR z przykładami komend declare,
attack pass i resolve, identity/version guardami oraz **jawnym wyborem
kontrataku przez obrońcę**. Określić, gdzie istniejący bool Charge może
bezpiecznie reprezentować ten wybór, a gdzie wymaga nowego przejścia;
nie nazywać domyślnej wartości zgodą obrońcy (źródło 14.d.iv).

Pliki/warstwy: ADR + macierz implementacji i testów (**D**), budżet **D**.
DoD: zamrożony kontrakt decyzji i uprawnień, no-nested/priority/pass,
inventory-derived intent, cleanup i restart. Nowy publiczny kontrakt lub
zmiana sposobu decyzji obrońcy wymaga osobnego wyboru przed P12.
Publiczny allowlist X nie jest częścią tego ADR ani prerekwizytem bazowej walki.

### P12. Consent i planner v3 dla bazowej walki

Zależność: zaakceptowany P11, P9. Wdrożenie dzielić na dwa zamykane przebiegi:
**P12a** declare/attack pass; **P12b** resolve i planner po pełnym headzie.
Oba używają istniejącego `stage_battle_activation_action/pass` i canonical
inventory, a nie profilu broni wymyślonego przez klienta. Początkowo bez
zdolności i X; obsługa obrońcy dokładnie według P11. Nie włączać globalnego
source_correct ani publikacji prywatnych hooków C2d.

Pliki/warstwy: command codec/consent, `battle_activations.py`, protocol
planner, `szop_client/http.py`, UI wsparcia operacji (**B,J,T,D**).
Budżet **C,K,U**. DoD osobno a/b: świeży head i wszystkie activation/attack/
window guards, koszt deklaracji/pass bez przesunięcia RNG, complete-tail
replay każdego restart headu, resolve error immutability/future RNG,
stale i repeat approve bez podwójnego ataku. UI pokazuje atakującego,
obrońcę, wybór kontrataku oraz oddzielną zgodę, bez ukrytej pętli.

### P13. Publiczny kontrakt setup i rozstawienia

Zależności: P2, D5.3a/b. Dokumentacyjny ADR: rostery/strony, mapa/terrain/cele,
seed i protokół, jawny wybór grid/objectives, granice pola i stref,
round-0 command/checkpoint oraz restart/idempotencja tworzenia sesji.
Odróżnić istniejący start po `deployment_round(state, ())` od nowej ścieżki;
historycznych bitew nie migrować automatycznie. Reuse D5 occupied i validator.

Pliki/warstwy: ADR i fixtures/test plan (**D**), budżet **D,S**.
DoD: kontrakt 9/13/24 ze źródła, kolejność zajmowania miejsc, brak legalnego
miejsca/exhaustion, transakcja i ownership, odtwarzanie round-0; ewentualne
nowe payloady/model wymagają wyboru przed P14. Kreator nie nadaje botowi
nowych uprawnień ani nie ujawnia cudzych rosterów.

### P14. Trwałe rozstawienie i kreator sesji

Zależności: zaakceptowany P13, P3, P10. Dwa przebiegi: **P14a** backend/
client trwałego setup/rozstawienia, **P14b** formularz UI wyboru własnych
rosterów, stron, kind/seed i strategii oraz potwierdzenie konfiguracji.
Jedna operacja round-0 na komendę, nie `run_match` w request. Na początku
tylko mapa bez terenu; inne opcje wyłączone do P15.

Pliki/warstwy a: `battle_creation.py`, router, `engine/phases.py`,
`agents/deployment.py`, HttpClient i testy (**M** tylko według P13,
**B,T,D**); b: nowy template/formularz/moduł sesji (**J,C,T,D**).
Budżet **S,K,U**. DoD a: po każdym kroku checkpoint/replay/RNG, legalne
occupied i brak częściowego zapisu przy exhaustion/race; zgodność starego
create. DoD b: walidacja własności po stronie serwera, restart kreatora,
brak podwójnej bitwy po reload i osobna zgoda na pierwszy krok bota.

### P15. Jawne poszerzanie geometrii i capability

Zależności: P6, P12, P14. Nie zdejmować zbiorczo gate'u pustego terrain.
Małe kolejne przebiegi dla statycznego Niedostępnego/Blokującego, następnie
Trudnego, a Niebezpieczny dopiero po dowodzie lifecycle „pierwszy raz
w aktywacji” (4.c.v). Dla każdego: wszystkie wspierane kształty, wspólny
ManeuverPlanner/LoS i canonical walidacja, bez kopii reguł w JS.

Pliki/warstwy: odpowiednie engine pathfinding/geometry/LoS/protocol,
planner bota, capability, fixture i renderer tylko projekcyjnie
(**B,T,D**, **J** przy nowej projekcji). Budżet **G,C,U**. DoD dla każdego
przebiegu: ścieżka, nie sam endpoint; brzegi/objazdy/brak trasy, charge
i ranged parity, owner/consent/restart/replay/RNG. Niezweryfikowane cechy
nadal fail-closed; nowych zdolności/bohaterów nie włączać przy okazji.

### P16. Domknięcie sesji, restart i odtwarzanie

Zależności: P5, P10, P12, P14; scenariusze terenu po odpowiednim P15.
Jedna ręcznie inicjowana komenda na raz, powrót do człowieka/priorytetu,
bez automatycznego zatwierdzania. Serializowane próby odtwarzają status
z serwera; zatrzymanie blokuje następne komendy, nie cofa zatwierdzonej.
Replay to obserwacja istniejącej historii, nie wznowienie executora.
SSE może unieważniać widok i pobrać checkpoint, nie redukuje reguł w JS.

Pliki/warstwy: moduł sesji UI, trwałe próby P3, `battle_event_stream.py`,
`battle_replay.py`/HttpClient przez istniejące API, testy (**B,J,C,T,D**).
Budżet **R,U,K**. DoD: pełna ograniczona gra człowiek/bot od setup do
serwerowego końca, końcówki i replay, stop/timeout/reload na każdym headzie,
dwa komputery/dwie karty, brak podwójnego POST/approve i brak automatycznego
wznowienia. Same-owner sandbox i odrębni ownerzy mają osobne testy;
nie deklarować obsługi profili/zdolności spoza capability.

Najkrótsza ścieżka UI: **P1 → P2 → P3 → P4 → P5**.
Ścieżka pełniejszej gry: **P6 → P7 → P8 → P9 → P10 → P11 → P12**,
z setupem **P13 → P14**, później **P15 → P16**. P7 zależy też od P2/P3,
P14 od P10; te zależności mają pierwszeństwo przed numeracją.

## Co wymaga późniejszej decyzji

Kontrakt P2 zaakceptowano w ADR-0060. P11 i P13 definiują przyszłe API
i mają własne punkty akceptacji.

Gra wspomagana z osobną zgodą dla każdej komendy zachowuje obecny model.
**Automatyczne wykonywanie całych tur bota** wymaga osobnej decyzji produktowej
i security: zakres udzielonej zgody, strona/bitwa/okres/limity, odwołanie,
prawo pass/kontrataku, retry i worker isolation. Nie zastępować jej wildcard
scope, autoapprove albo ukrytym użyciem `battle:act`. Droższe boty/LLM,
zewnętrzne konta, publikacja X i pełna obsługa wszystkich zdolności pozostają
poza pierwszymi etapami; źródłem wyboru kindów zawsze jest registry/factory.

## Weryfikacja D6.3 i przeniesienie

Zmiany D6.3 obejmują tylko ten plan, indeks, wynik kolejki i zamknięcie
pozycji D6.3 w roadmapie. Nie zmieniono kodu/testów/DB/UX/auth. Sprawdzono
kanoniczne źródła (4/4 CLEAN), rzeczywiste symbole i call sites, lokalne linki i kotwice,
zależności, zakresy/testy/budżety etapów oraz `git diff --check`.
Kontrola objęła 130 lokalnych odwołań i 19 nazwanych symboli; zero nowych
błędów linków. Historyczny link roadmapy do `plans/architektura-dlugofala.md`
pozostaje bez pliku docelowego, poza zakresem D6.3. Wszystkie 16 sekcji ma
zależności, pliki/warstwy, budżet i DoD; graf zależności jest acykliczny.
Wykonano ręczne równoważniki simplify/review/security-review planu:
usunięto domniemanie wsparcia v2/v3 przez legacy consent, rozdzielono
wybór bota od zgody, trwałą deduplikację od idempotencji approve i viewport
od planszy. Slash commands nie były dostępne. Pełnego pytest nie ponawiano
dla czystego Markdown zgodnie ze wspólnym DoD kolejki. **4112 passed,
4 dependency warnings** to wynik bazowego D6.2, nie test D6.3.

Odtworzenie kontekstu: fetch/checkout `Faza_A`, potwierdzenie zgodności
commitu z `origin/Faza_A`, ten plan + D6.1/D6.2 + kolejka, requirements
i editable `szop_client`. Wybór nowego etapu powinien podać jego ID i DoD;
po D6.3 zaakceptowana kolejka jest wyczerpana, wielomiesięczna roadmapa
pozostaje otwarta. Nie dodano nowej automatycznej gotowości.

Osobny backup: ignorowana `data/szop.db`, lokalne sekrety/konfiguracja,
scheduler/runtime. Kod w Git nie przenosi poświadczeń ani ledgeru procesu.
Po niepewnej próbie D6.2 przed nową instancją na innym komputerze najpierw
rekoncyliacja ownera. Produkcyjna baza nietknięta; SHA256:
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Źródła SZOP DOCX/PDF/MD pozostają śledzone w Git; HANDOFF nie aktualizowano.
