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
| 1 | B4.4d.C2d3 | Działający prywatny Ostrożny v3 |
| 2 | B4.4d.C2d4-spec | Audyt Bastionu |
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
