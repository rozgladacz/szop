# Kolejka po C2d3-spec — akceptacje 2026-11-19

Baza planu: `0855277` na `Faza_A`. Użytkownik zaakceptował propozycje 1–5,
przywrócił D5.3, dodał audyt botów i podłączenie agentów oraz jawnie wznowił
cykl. Ostrożny jest rozstrzygnięty: **tylko ataki dystansowe**. Poniższe
zakresy precyzują tę akceptację; nie rozszerzają audytów na implementację
badanych mechanik ani przygotowania publikacji na samą publikację.

## Kolejność i wspólny DoD

Jeden worker realizuje jeden etap, w kolejności tabeli. Każdy etap zależy
od zamknięcia poprzedniego oraz wskazanych niżej prerekwizytów. Markery
`[automation-ready]` w roadmapie pochodzą z akceptacji użytkownika z tej daty.

| Kolejność | ID | Wynik |
|---|---|---|
| 1 | B4.4d.C2d3 | DONE 2026-11-19; prywatny Ostrożny v3, 3987 testów |
| 2 | B4.4d.C2d4-spec | DONE 2026-11-19; Bastion wykluczony z obecnego scope |
| 3 | B4.4d.C2d5-spec | Audyt Planowania |
| 4 | B4.4d.C2d6-spec | Audyt Niestrudzonego |
| 5 | D5.3a | Strategia rozstawienia pod cele i jawny wybór |
| 6 | D5.3b | Powtarzalne porównanie z gridem |
| 7 | B4.4d.C2-publication-spec | Przygotowanie ograniczonej publikacji Oznaczenia |
| 8 | D6.1-audit | Audyt istniejących botów i gotowości integracji |
| 9 | D6.2-connect | Adapter istniejących agentów do propozycji akcji |
| 10 | D6.3-play-plan | Podział Play vs AI na małe etapy |

Przed pierwszą edycją worker czyta `AGENTS.md`, potwierdza cel/DoD,
Layer Checklist i SSOT oraz aktualny HEAD/cudze zmiany. Każdy rules claim
wymaga odczytu odpowiedniego `app/static/docs/SZOP_*.md` w danej sesji.
Decyzja użytkownika o Ostrożnym pozostaje wiążąca. Zielone detale rozstrzyga
worker, żółte koordynator; czerwone pytania według kanonicznego skilla.

Zmiana kodu wymaga encoding gate przed edycją Python, testów celowanych,
pełnego `pytest -q`, audytu wywołań, simplify/review i security review dla
auth/wejścia do DB. Po poprawkach przeglądu powtórzyć testy. Zmiana JS wymaga
smoke na działającej aplikacji (Zbrojownia, Edytor Armii, Rozpiski oraz
zmieniony przepływ); preview używa obecnej bazy. Czysty audyt Markdown:
sprawdzenie źródeł, symboli, linków i diffu oraz simplify/review; bez
ponawiania pytest, jeżeli nie zmieniono kodu. Wynik 3926 testów po D5.2
jest historyczną bazą, nie wynikiem nowych przebiegów.

Każdy etap zapisuje tu lub w indeksowanej dokumentacji wynik, komendy,
testy, ograniczenia i podstawę następnego etapu. Osobny nowy commit na
`Faza_A`, push i potwierdzenie identycznego hasha przez
`git ls-remote --heads origin Faza_A` są częścią DoD. Nie wznawiać HANDOFF.
Zachować zastane pliki, zwłaszcza historyczny hunk B6.2 w roadmapie;
staging roadmapy selektywny. Zero przypadkowych refaktorów i zmian bazy.

Backup osobno: ignorowana `data/szop.db`, lokalne sekrety/konfiguracja;
środowisko odtworzyć z requirements. Początkowy SHA256 bazy:
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Źródła SZOP DOCX/PDF/MD są śledzone w Git. Stan runtime automatyzacji jest
lokalny; przeniesienie kodu nie przenosi schedulerów ani poświadczeń.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
git status --short --branch
git ls-remote --heads origin Faza_A
```

## 1. B4.4d.C2d3 — implementacja Ostrożnego

Cel i zakres: wdrożyć [specyfikację](ostrozny-spec.md) według decyzji
2026-11-19. Prywatny pasujący zamknięty Ostrzał v3, natywna zdolność i
attack-scoped Oznaczenie, wspólny predykat z pełnym kontekstem bitwy oraz
jawny kontekst prediction. W źródle poz. 23 [Zdolności](../app/static/docs/SZOP_Zdolnosci.md)
warunek obejmuje brak wrogów w 12″ od atakującego oddziału. Melee nie
otrzymuje bonusu. Nie włączać globalnie `source_correct`, legacy v1/v2,
publicznego Strażnika ani `_READY_ATTACK_X`.

Warstwy: effects/combat/prediction i testy, ewentualnie wąski adapter phases;
bez DB, codec, API, JS/CSS. Performance: O(N) od jednostek, fast-path bez
zdolności, zero SQL/nowych rzutów RNG. Zmierzyć combat/prediction na fixture.

DoD: testy 11.999/12/12.001″ z różnymi promieniami, dodatkowy bliski wróg,
role/lokalizacje, native/granted/both raz, brak efektu po ataku, poprawny
closed-v3 gate, restart/replay/future RNG i failed-resolve immutability.
Prediction używa tego samego warunku. Testy wskazane w specyfikacji:
engine effects/combat/activation/checkpoints/interrupts, prediction parity,
regression i publiczny transport fail-closed; pełny pytest i wspólny DoD.

### Wynik implementacji C2d3 — 2026-11-19

Baza: `d6b742d`. Hook `_ostrozny_attack` w `effects.py` jest jedynym miejscem
skanu wrogów i pomiaru `circle_edge_distance`; `EffectContext.is_ranged_attack`
ma domyślne False. Combat kwalifikuje każdy profil przez `_matching_closed_shoot`:
pasujący zamknięty Shoot intent, bieżące bloby, canonical inventory i strict
profile equality. Matcher reużywa `_canonical_action_from_attack` oraz
`_same_weapon_profile` z protokołu przez lokalny import, bez drugiej walidacji
inline. Dopiero ten gate przekazuje pełny stan i włącza hook. Szeroki
`source_correct` pozostaje niezmieniony i celowo nie włącza Ostrożnego.

`prediction.expected_damage(..., *, state=None)` ma jawny opcjonalny kontekst.
Gdy podano pełny pasujący zamknięty stan v3, stosuje ten sam matcher i hook.
Bez kontekstu wynik historyczny zostaje zachowany. Nie dodano pól DB, eventu,
checkpointu, wire/API, klienta, JS ani CSS; `_READY_ATTACK_X` pozostaje puste.

**Audyt wywołań.** `_resolve_ranged_profile_pools` jest wołane wyłącznie przez
volley SSOT. Jego callerzy to single-profile `resolve_ranged_attack` oraz
publiczny Strażnik z `source_correct=True`; Strażnik zachowuje istniejącą
odmowę Ostrożnego. `phases._apply_shoot` nadal deleguje bez zmiany parametrów.
Matcher służy wyłącznie combat i opt-in prediction. `aggregate_attack_modifier`
nie zmienia swojego algorytmu deduplikacji; domyślny False chroni dotychczasowe
konteksty melee. Pięciu konsumentów `expected_damage` (Greedy, PriorityV2/V3,
ClaudeV1/V3) nie przekazuje state i zachowuje historyczny scoring. Pozostałe
rodziny dziedziczące te wyceny nie otrzymują automatycznego opt-in.

**Weryfikacja.** Pierwszy wymagany zestaw dziewięciu plików przed końcowym
simplify: 804 passed. Po simplify i dodatkowych regresjach: effects/combat/
activation/prediction **347 passed** oraz Strażnik i pięć rodzin scoringu
**92 passed**. Pełny `pytest --tb=short -q`: **3987 passed, 4 warnings** zależności
(195.27 s), po końcowym simplify; +61 testów wobec bazy3926. Goldeny
i historyczny replay pozostają bez zmian.
Nowe 61 przypadków obejmują granice dla trzech par promieni, drugi bliski wróg,
statusy/lokalizacje/sojuszników/pokonanych, native/granted/both i Rozkaz revoke,
realne trafienia v3 na naturalnej 3 przy jakości 4, clamp/naturalne 1/6,
niepasujące intent/profile/actor/target/inventory/state, v2 ready, per-profile
volley, restart/pełny replay/12 przyszłych rzutów, failed resolve/retry oraz
Monte Carlo prediction po 1000 seedów dla dwóch wariantów bliskości.

**Wydajność.** Fixture `_furia_battle` z istniejących testów protokołu:
3 bloby, aktor z `ostrozny`, cel `(20,0)`, sojuszniczy nosiciel `(20,2)`,
jedna broń/atak; closed Shoot v3, seed 225. `timeit.repeat`, mediana siedmiu
prób po 1000 wywołań. Bazowe moduły z `git show d6b742d:app/services/engine/...`
wczytano wyłącznie do pamięci tego samego procesu, bez zmiany checkoutu.
Combat: **37.618 → 64.265 µs**, prediction bez opt-in: **11.447 → 8.799 µs**,
nowy prediction z opt-in: **26.639 µs**. To pomiar diagnostyczny podczas
równoległego pytest, nie SLA ani dowód przyspieszenia starego prediction.
Dodatkowy pomiar 32 blobów: combat 64.988 µs, opt-in prediction 41.433 µs.
Koszt poprawności obejmuje ponowny canonical preflight (w tym walidację
strzału), potem liniowy skan; brak zdolności/closed gate omija ten preflight.
Zero SQL/I/O/nowych rzutów, bez cache. Sam predykat ma O(1) dodatkowej pamięci.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_effects.py tests/test_engine_combat.py tests/test_engine_activation_protocol.py tests/test_prediction_vs_simulation.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_straznik.py tests/test_agents_greedy.py tests/test_agents_priority_v2.py tests/test_agents_priority_v3.py tests/test_agents_claude_v1.py tests/test_agents_claude_v3.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
git diff --check
```

Simplify/review objęły per-profile gate, reuse canonical validation, brak
poszerzenia source_correct, role/lifetime, pełny obraz wrogów, RNG i backward
compatibility. Gate został uproszczony do jednego miejsca w core, bez nowego
parametru AttackState przenoszonego przez volley. Security review/UI smoke
nie dotyczą zakresu bez auth/input→DB/JS. Ograniczenia: jest to prywatny
zakres closed-v3; legacy, publiczny Strażnik i katalog publikacji pozostają
przed osobnymi etapami. Bez zmiany danych produkcyjnych.

**Przeniesienie.** Własny commit C2d3 na Faza_A musi być potwierdzony na
origin/Faza_A; cudzy hunk B6.2 i historyczne pliki pozostają poza nim.
Baza i lokalne sekrety/konfiguracja wymagają osobnego backupu, jak powyżej.
Następny zaakceptowany etap to **B4.4d.C2d4-spec — audyt Bastionu**.
Nie uruchomiono go w ramach C2d3. Brak nowych pytań o reguły.

## 2–4. Audyty Bastionu, Planowania i Niestrudzonego

Każdy to oddzielny dokumentacyjny etap; wynik indeksować w docs/README.
Źródło: aktualne poz. 1, 25 i 14 [Zdolności](../app/static/docs/SZOP_Zdolnosci.md)
oraz wskazane tam punkty Rozjemcy. Wspólny zakres: źródła i synchronizacja,
faktyczne call sites effects/combat/activation/interrupts/reducers/prediction,
role, moment oceny, trwałość efektu, compatibility v1/v2 i wymagane testy.
Nie implementować nowych mechanik w trakcie audytu ani nie zmieniać kosztów.

- **C2d4-spec — Bastion:** ustalić podmiot kontrataku i czy nadanie X
  deklarowanemu atakującemu może osiągnąć właściwą rolę. Rozdzielić zdolność
  natywną/Rozkaz od attack-scoped Oznaczenia. Odmowa niepasującego X może być
  poprawnym wynikiem audytu; nie rozszerzać semantyki źródła dla publikacji.
- **C2d5-spec — Planowanie:** sprawdzić stan Przygotowany w chwili trafienia,
  jego zmiany w sekwencji, główny atak/kontratak, deduplikację grantów;
  rozdzielić `planowanie` i istniejące historyczne `przygotowanie`.
- **C2d6-spec — Niestrudzony:** sprawdzić wybór akcji względem attack scope,
  limit/kontrolę pętli aktywacji i wygaszanie nadania. Nie przenosić
  krótkotrwałej zdolności na następną akcję na podstawie samego sluga.

Warstwy: dokumenty i roadmapa. Oszacować przyszły koszt i kontekst, zero
SQL. DoD każdego: konkretne przykłady brzegowe, mapa plików/wywołań,
macierz testów, wykonalny ograniczony etap implementacyjny albo uzasadnione
wykluczenie. Nierozstrzygalny konflikt źródeł daje jedno pytanie z
rekomendacją; audyt można zamknąć z pytaniem, dalszy cykl blokuje koordynator.
Weryfikacja: źródła/sync, symbole i linki, diff review; docs-only DoD wyżej.

### Wynik C2d4-spec — 2026-11-19

Na bazie `4bf700f` powstał [audyt Bastionu](bastion-spec.md). Właściwym
podmiotem jest kontratakujący obrońca (poz. 1/10 Zdolności, pkt 14.d.iv/17
Rozjemcy), a obecny attack override wiąże wyłącznie deklarowanego
szarżującego. Bastion zostaje **wykluczony z katalogu publikacji obecnego
main-attacker-only Oznaczenia**. Tag źródłowy pozostaje prawdziwy; wykluczenie
dotyczy obecnego zakresu protokołu. Nie dodano implementacji ani nowego
okna kontrataku. Rozkaz dla Bastionu ma kierunek „−”, więc source-correct
payload odbiera zdolność, nie nadaje jej.

Źródła: `rules_sources_check.py` **4/4 CLEAN**, odczyt DOCX/MD/YAML zgodny
w zakresie Bastionu; PDF zweryfikowany hashem. Sprawdzono symbole i call
sites, role/lifetimes, istniejące regresje native/counter oraz macierz
przyszłych testów. Simplify/review, link check i `git diff --check`.
Kod/testy niezmienione: bez ponownego pytest; **3987 passed** to historyczny
wynik C2d3. Nie zmieniono DB/API/JS, RNG ani kosztów. Wskazano istniejące
ograniczenie kolejności MVP counter/main, bez rozszerzania tego audytu.

Osobny commit dokumentacji na `Faza_A` potwierdzany na `origin/Faza_A`;
backup bazy/sekretów/konfiguracji według wspólnych warunków. SHA256 bazy
bez zmian. Cudze pliki i historyczny hunk B6.2 zachowane poza commitem.
Brak nowego pytania do użytkownika. Następny zaakceptowany etap to
**C2d5-spec — audyt Planowania**, nieuruchomiony w C2d4-spec.

## 5–6. D5.3a/b — strategia rozstawienia i pomiary

Użytkownik 2026-11-19 odwołał wcześniejsze odłożenie obu części D5.3.
Obowiązują zakresy [D5.3a i D5.3b z poprzedniej kolejki](kolejka-po-c2d1.md#4-d53--opcjonalne-rozstawianie-pod-cele),
z poniższą aktualizacją bazy: D5.1/D5.2 zamknięte, kontrola celu 2″
wdrożona w `f57b26b`. Nie ma już rozbieżności stałej 3″ do naprawiania.

**D5.3a:** Python runner wybiera grid lub nową deterministyczną heurystykę
rozstawienia pod różne cele, niezależnie od polityki walki. Grid pozostaje
domyślny. Wspólna ograniczona pula kandydatów D5.2, walidator D5.1, jawne
occupied i sekwencyjny obraz, deterministyczne remisy i fallback bez celów.
Obsłużyć więcej/mniej oddziałów niż celów i wyczerpanie kandydatów.
Warstwy deployment/runner/tests, bez HTTP allowlist/DB/UI. Zero SQL,
limit kandydatów bez permutacji; mierzyć liczbę ocen/czas. DoD: legalne i
powtarzalne pozycje, oddzielne przydziały, niezmieniony default, testy
agents_deployment/match/factory, balance_simulate, regression + pełny pytest.

**D5.3b:** po D5.3a zamrozić mapy/armie/seedy, sparować grid/cele przy tej
samej polityce, zamienić strony/inicjatywę, dodać kontrole lustrzane.
Pomiar: legalność i błędy, pokrycie/przydziały, dystanse, zwycięstwa/remisy,
czas rozstawienia i pełnej gry, deterministyczne pozycje/eventy. Użyć
istniejących fixture i map z poprzedniego planu, factory/registry jako SSOT.
Warstwy skrypt eksperymentu/testy/wersjonowany raport; bez silnika/DB/UI.
DoD: komendy, parametry, hashe i dane wyniku dostępne w Git, nie tylko
ignorowane reports; gorszy wynik również kończy etap. Nie przełączać
milcząco domyślnej strategii. Kod skryptu wymaga pełnego pytest.

## 7. B4.4d.C2-publication-spec — przygotowanie publikacji

Cel: przygotować ograniczony katalog X i konkretny plan publikacji
Oznaczenia na podstawie wyników C2d1–C2d6. [Plan mechanik](oznaczenie-mechaniki-plan.md)
i [QA C2](c2-qa-2026-11-04.md) są kontekstem, źródła reguł odczytać ponownie.
Zakres: tabela gotowe/prywatne/wykluczone, audyt owner/scope/no-oracle,
atomowości błędu, rollback/restart/RNG, CAS/stale sequence i SQL gates;
minimalne etapy serwis/HTTP/HttpClient/MCP/UI oraz ich zależności i testy.
Warstwy dokumentacja/security audit, bez zmiany `_READY_ATTACK_X`, auth,
endpointów lub danych produkcji. Zliczyć istniejące SQL i wskazać przyszłe
budżety. DoD: jawny katalog bez domniemanej gotowości z samego audytu,
konkretne pliki/kontrakty i negatywna macierz testów, review/security review,
linki i diff check. Przygotowanie nie upoważnia do samej publikacji.

## 8. D6.1-audit — audyt botów

Cel: ocenić gotowość istniejących botów po E2/E4, kontroli celu 2″,
Ostrożnym i D5.3. `agents/registry.py`/`factory.py` są SSOT katalogu i
konstrukcji; nazwy claude_v* oznaczają obecne implementacje, nie połączenie
z płatnym modelem. Brak nowych dostawców lub zewnętrznych kont.

Zakres: legalność akcji i kontynuacji, deployment, ruch, prediction vs
resolver, zakończenie gry, deterministyczność seedów, tagi i koszt, oraz
przekład decyzji na publiczny lifecycle v1/v2/v3. Oddzielić jakość polityki
od poprawności reguł. Sprawdzić wszystkie rodziny; drogie boty oceniać na
jawnie ograniczonych próbkach. Nie stroić wag ani zmieniać rankingów bez
pomiaru. Porównać także publiczny state bez RNG z danymi wymaganymi przez
wybranego bota. Osobno zidentyfikować blokery integracji przed D6.2.

Warstwy audyt + testy/regresje/harness, bez publikacji nowego API i zmian
auth. DoD: wersjonowany raport z komendami/seedami/czasem i macierz
bot × obsługiwany protokół × scenariusz, odtworzenia usterek i lista
prerekwizytów D6.2. Testy registry/factory/base, botów, match/deployment,
move_fidelity, regression, clients parity; pełny pytest przy zmianie kodu.
Brak wymaganej zdolności ma być jawny, nie zastępowany nielegalną decyzją.

## 9. D6.2-connect — podłączenie istniejących agentów

Cel: działający ograniczony adapter **publiczny stan → decyzja istniejącego
bota → propozycja akcji**, oparty na wyniku D6.1, factory/registry,
`szop_client.HttpClient` i istniejącym consent-gated `propose_battle_action`.
Zachować podpisy i walidację publicznego klienta, owner/scope i zatwierdzenie
propozycji przez użytkownika. Pokazać pełny przebieg od autoryzowanego
odczytu, wyboru bota i utworzenia propozycji do jej akceptacji przez istniejący
mechanizm oraz aktualizacji stanu/eventów. Nie dodawać alternatywnej ścieżki
zapisu do DB/silnika, pętli w tle ani automatycznego zatwierdzania propozycji.
To podłączenie istniejących agentów; autonomiczna gra UI zostanie podzielona
w D6.3. Jeżeli audyt wykaże brak koniecznego publicznego kontraktu, najpierw
przedstawić koordynatorowi konkretny prerekwizyt zamiast obchodzić granicę.

Warstwy adapter klienta/agentów, istniejąca ścieżka propozycji, testy,
dokumentacja użycia; UI tylko jeżeli potrzebne w istniejącym przepływie.
Zero nowych uprawnień; bez RNG checkpointu w danych bota, sekretów w logach,
zewnętrznych modeli i usług. Bounded one-step, jawny seed decyzji, brak retry
mutacji po niepewnym wyniku; zliczyć requesty/SQL i zmierzyć czas decyzji.

DoD: co najmniej jeden bot z raportu działa end-to-end, obsługiwane kindy
pochodzą z rejestru i dowodów audytu; nieznany/nieobsługiwany kind, cudza
bitwa, zły scope, wygasły token, stale sequence, timeout i powtórka nie
powodują niejawnego zapisu ani wycieku. Testy agent proposals/token security,
HTTP client, battle action proposals i wybranych botów + pełny pytest,
security review, smoke przy JS. Udokumentować protokoły/zdolności/granice.

## 10. D6.3-play-plan — podział Play vs AI

Cel: gotowe małe etapy dojścia od obecnego podglądu i D6.2 do gry z botem
w UI, zgodnie z zaakceptowanym punktem 5. Zakres: wybór istniejącego agenta,
rosterów/stron/rozstawienia, przebieg tury i przerwań, prawo wykonania akcji,
bounded wykonanie i anulowanie, obsługa konfliktów/reload/restart, informacja
zwrotna i odtwarzanie. Uwzględnić luki wykryte przez D6.1/D6.2 oraz granicę
propozycja/zatwierdzenie/autonomiczne wykonanie.

Warstwy dokumentacja, prototyp opisowy przepływu i test plan. Bez wdrażania
nowego UX/auth/background workera ani płatnej integracji. DoD: indeksowany
plan z kolejnością, zależnościami, plikami, Layer Checklist, kontraktami,
SQL/time budgets i testami każdej części; konkretna decyzja produktowa tylko
jeżeli naprawdę nie wynika z obecnej akceptacji. Sama implementacja UI
wymaga wyboru z tego podziału; nie dodawać jej samodzielnie automation-ready.

## Weryfikacja przygotowania kolejki — 2026-11-19

Zmiany koordynacyjne obejmują wyłącznie Markdown i wznowienie istniejącego
heartbeat. Helper `coordinator_state.py ready-stages` zwrócił dokładnie
10 powyższych ID w tej kolejności. Sprawdzono unikalność markerów, zakresy,
zależności, 10 nowych lokalnych celów linków oraz `git diff --check`.
Simplify/review usunęły nieaktualną odmowę automatycznego startu C2d3 ze
specyfikacji i wskazały datowane informacje historyczne w starej kolejce.
Nie zmieniono kodu ani testów, więc pytest nie ponawiano. SHA256 bazy zgodny
z wartością powyżej. Cudze zmiany pozostają poza commitem kolejki.
