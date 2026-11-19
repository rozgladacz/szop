# Ostrożny — audyt C2d3-spec i kontrakt przyszłej implementacji

Status: **audyt zakończony 2026-11-18; zakres rozstrzygnięty przez użytkownika 2026-11-19: tylko dystansowe; implementacja wymaga osobnej akceptacji**.
Baza: `3954634` na `Faza_A`, po C2d1/C2d2 i D5.2. Ten dokument nie
zatwierdza implementacji ani publikacji Oznaczenia. D5.3a/b pozostają odłożone.

## Źródła i jedno pytanie

Odczytano w tej sesji [Zdolności, poz. 23 i 49](../app/static/docs/SZOP_Zdolnosci.md)
oraz [Rozjemcę, pkt 1, 2.e, 6, 11–12, 14, 16–17, 23, 26–27](../app/static/docs/SZOP_Rozjemca.md).

| Dowód | Wynik odczytu |
|---|---|
| Zdolności, poz. 23, `opis` | Brak wrogów w 12″ od oddziału modelu daje +1 do trafienia; bez nazwania rodzaju ataku. |
| Zdolności, poz. 23, `efekty.warunek` | Warunek odnosi się do oddziału **strzelającego**. |
| `SZOP.docx`, paragraf z nazwą Ostrożny | Ogólny opis zgodny znaczeniowo z polem `opis` MD; nie zawiera ograniczenia do strzelania. |
| `abilities.yaml`, `slug: ostrozny` | Ten sam ogólny opis; `oznaczenie_tak: true`, `rozkaz_tak: true`. Katalog nie rozstrzyga szczegółu `efekty`. |
| Zdolności, poz. 49 | Oznaczenie nadaje X innemu sojuszniczemu atakującemu tylko na rozpatrywany atak; zasięg nosiciel–cel nie jest zasięgiem warunku Ostrożnego. |

`scripts/rules_sources_check.py` zwrócił **4/4 CLEAN, exit 0** dla DOCX,
PDF i obu MD. Bieżące ekstraktory DOCX/MD uruchomione w pamięci potwierdziły
powyższe opisy. DOCX/YAML używają typograficznego `”`, a `opis` MD prostego
`"`; nie jest to różnica mechaniki. Ekstraktor MD czyta opis, a nie warunek
z `efekty`, więc zgodność ekstrakcji nie dowodzi zgodności zakresu efektu.
PDF sprawdzono sumą kontrolną, bez niezależnej interpretacji jego treści.
Nie uruchamiano aktualizacji hashy ani zapisu ekstraktów. Zgodność hashy
potwierdza wersję plików, nie usuwa niejednoznaczności wewnątrz tekstu.

**Decyzja użytkownika 2026-11-19:** Ostrożny działa wyłącznie w atakach
dystansowych. Bonus +1 wymaga braku wroga w 12″ od atakującego oddziału
(poz. 23). Użytkownik wskazał, że podczas walki wręcz bliski przeciwnik
i tak wyklucza spełnienie tego warunku. Wcześniejsze pytanie jest zamknięte.
Decyzja rozstrzyga interpretację źródeł bez zmiany ich plików; nie oznacza
jeszcze zlecenia implementacji ani wznowienia heartbeat.

Poniżej obowiązuje wariant dystansowy. Wzmianki o szerszym wariancie
pozostają porównaniem z audytu, nie alternatywnym zakresem do realizacji.

## Kontrakt warunku — propozycja techniczna

Podstawa warunku i wartości +1: poz. 23. Rozróżnienie sojusznika i wroga:
pkt 2.e. Proponowane odwzorowanie modelu na obecny blob jest następujące:

1. Podmiotem jest **rzeczywisty atakujący danej połowy sekwencji** (pkt 17),
   nie zawsze aktywny oddział i nie nosiciel Oznaczenia. Sprawdzić jego
   `effective_attack_passives(blob, attack_state)`. Natywny, nadany Rozkazem
   i nadany Oznaczeniem `ostrozny` to jedna zdolność, z bonusem najwyżej +1.
2. Przeglądać wszystkie `state.blobs`: inny `owner_player`, `models_alive > 0`,
   `location is FRONT`. Zaplecze/Wycofany/Eliminowany są poza planszą
   (pkt 26), a pokonany model jest zdejmowany (pkt 27). Brak LoS nie usuwa
   wroga z warunku: poz. 23 nie wymaga linii wzroku. Wyczerpany lub
   Przyszpilony wróg nadal jest wrogiem; poz. 23 nie zawiera takiego wyłączenia.
3. Proponowany dystans blobów: istniejący `geometry.circle_edge_distance`,
   czyli odległość środków minus oba promienie. To jawne przybliżenie
   podstawka–podstawka, zgodne z istniejącymi kontrolami zasięgu przerwań;
   poz. 23 nie definiuje osobnej metryki blobów. Nie mylić jej z pomiarem
   podstawka–znacznik celu z pkt 5.d ani z wyborem modelu dla ataku z pkt 6.a.
4. Wróg z dystansem **≤12.0″** wyłącza bonus. Ujemny dystans przy starym
   nakładaniu również go wyłącza. Bez dodatkowego epsilonu zmieniającego
   granicę reguły; przykłady testować na osi, z dokładnie reprezentowalnymi
   wartościami. Skończone poprawne pozycje i dodatnie promienie są warunkiem
   wejścia silnika, a nie zadaniem nowego parsera tego efektu.
5. Wybrany wariant dystansowy: dodatkowy gate rodzaju ataku `ranged`; wariant
   wszystkich ataków usuwa tylko ten gate, zachowując skan i role. Brak
   pełnego kontekstu nie jest dowodem braku wrogów i nie może dawać +1.
6. Ocena w momencie testu trafienia, na aktualnym obrazie planszy. W volley
   wszystkie profile używają obrazu sprzed przydziału ran (pkt 17.c–e).
   Gdy wariant obejmie melee, podmiot ma pozycję po Związaniu i pozycje
   pozostałych jednostek aktualne dla swojej połowy sekwencji; nie wolno
   odszukiwać starej pozycji aktora w pierwotnym `state.blobs`.

Przykład: atakujący o promieniu 1″ w `(0,0)`, wróg o promieniu 2″ na osi X.
Środek wroga przy X=14.999/15/15.001 daje dystans 11.999/12/12.001″:
bonus odpowiednio 0/0/+1, gdy brak innych wrogów i gate rodzaju pozwala.
Cel w `(20,0)` sam jest daleko, lecz drugi wróg w `(10,0)` wyłącza bonus.
Zmiana tego drugiego na sojusznika albo jednostkę poza Frontem nie wyłącza go.
Promienie 0.5″/3″ przy odległości środków 15.5″ również dają granicę 12″.

## Odczytana mapa kodu i przyszłe punkty zmian

| Ścieżka/symbol | Stan na bazie audytu | Wymaganie przyszłego etapu |
|---|---|---|
| `effects.EffectContext` | Ma `blob`, opcjonalne `state`, `weapon`, flagi Szarży i `attack_state`; brak jawnego rodzaju ataku/gate nowej mechaniki. | Dodać minimalny prywatny kontekst rodzaju i opt-in; nie serializować go do DB ani eventu. |
| `aggregate_attack_modifier` | Iteruje po `effective_attack_passives`; `_ATTACK_MODIFIERS` nie rejestruje Ostrożnego. | Jeden hook + czysty wspólny predykat bliskości; bez drugiej implementacji w prediction. |
| `combat._aggregate_passive_attack` | Buduje `EffectContext` z kwargs. | Przekazać pełny aktualny stan i jawny gate tylko w wybranym nowym zakresie. |
| `phases._apply_shoot` → `resolve_ranged_attack` → `_resolve_ranged_volley` → `_resolve_ranged_profile_pools` | Zwykły Ostrzał, również closed v3, przechodzi przez legacy `source_correct=False`; `EffectContext.state` jest wtedy `None`. `attack_state` może być obecny. | Rozpoznać pasujący zamknięty `ShootAttackIntent` v3 (aktor/cel/profil/phase), oddzielić gate Ostrożnego od istniejącego szerokiego `source_correct`. Nie włączać hurtem innych poprawek ranged. |
| `phases._apply_charge` → `resolve_charge_attack` → dwa `resolve_melee_attack` | `_matching_closed_charge` kwalifikuje prywatny closed-v3; aliasy Podwójnego i Furia są oddzielone. Kontekst modyfikatorów melee nie ma `state`. | Dla wariantu ranged jawne zero w obu połowach; dla wszystkich ataków przekazać aktualny obraz i rolę. Nie używać `charging_attack`/Furii jako gate Ostrożnego. |
| `interrupts._execute_straznik_activation_interrupt_outcomes` → `_resolve_ranged_volley(source_correct=True)` | Strażnik ma pełny `state`, lecz `_STRAZNIK_UNSUPPORTED_SOURCE_PASSIVES` zawiera `ostrozny`. | W pierwszym przyszłym etapie pozostawić odmowę. Usunięcie jej zmieniłoby publiczne v2; to osobny zakres i regresje. Sam `source_correct=True` nie upoważnia do nowego bonusu. |
| `state.effective_attack_passives` | Nadaje override tylko `attack.intent.attacker_unit_id`, deduplikuje wobec bazowych pasywek. | Reużyć; Oznaczenie głównego atakującego nie nadaje zdolności kontratakującemu. Jego własna zdolność jest rozpatrywana osobno, o ile wariant pozwala. |
| `activation_protocol._resolve_activation_attack`, `reducers._reduce_attack_resolved` | Outcome używa prywatnego klonu RNG; terminalny `AttackResolved` usuwa `attack` i jego override'y. | Zachować kolejność i complete-tail equality; nie utrwalać Ostrożnego w `UnitBlob.ability_overrides`. |
| `prediction.expected_damage` | Buduje kontekst wyłącznie z dwóch blobów i broni; nie przyjmuje pełnego stanu/attack scope. | Opcjonalny prywatny context/adapter z tym samym predykatem i gate; stare wywołania bez kontekstu zachowują wynik. Nie domniemywać wszystkich wrogów z defendera. |

`expected_damage` ma pięciu produkcyjnych konsumentów: `GreedyPlayer`,
`PriorityV2Player`, `PriorityV3Player`, `ClaudeV1Player`, `ClaudeV3Player`.
Wywołania mają tylko attacker/target/weapon/terrain. Część używa tej estymacji
także do wyceny Szarży, pomijając teren; to nie jest informacja o rodzaju
ataku. Przy przyszłym opt-in trzeba jawnie przenieść rodzaj, pełny stan
i ewentualny scope przez pomocnicze funkcje scoringu. Boty, które dziedziczą
te wyceny, wymagają regresji mimo braku własnego bezpośredniego call-site.
Pierwszy etap może pozostawić tych historycznych konsumentów bez opt-in,
ale musi mieć parity nowego kontekstu prediction z nową ścieżką combat.

W wymienionych modułach prediction/scoringu nie znaleziono cache wyniku
obrażeń. Nie wprowadzać go w pierwszej implementacji. Ewentualny późniejszy
klucz musi uwzględniać wersję/obraz bitwy, pozycje/promienie/lokalizacje
i właścicieli wszystkich wrogów, podmiot, profil, rodzaj, gate i attack
override'y; para `(attacker_id, target_id)` nie wystarczy. Cache kosztów
rosterów nie jest cache tego warunku i pozostaje bez zmian.

`prediction.py` wspomina historyczny estymator MCP w docstringu, ale aktualne
`mcp_server/server.py::simulate_engagement` deleguje przez `HttpClient`
do symulacji rosterów, bez bezpośredniego `expected_damage`. Nie planować
zmiany publicznego payloadu na podstawie tego starego komentarza.

## Granice przyszłego etapu implementacyjnego

Proponowany pierwszy zakres do osobnej akceptacji: **prywatne zamknięte ataki v3**,
natywna zdolność oraz Oznaczenie; jawny kontekst prediction do ich estymacji.
V1/v2, ranged bez pasującego closed-v3, bezpośrednie wywołania bez opt-in
i publiczny Strażnik zachowują dotychczasowe eventy/wynik/RNG. To granica
kompatybilności implementacji, nie twierdzenie, że natywny Ostrożny według
reguł działa tylko w v3. Osobny etap może później ujednolicić legacy.

Oznaczenie mierzy nosiciel–zadeklarowany cel (poz. 49; istniejący handler
`execute_oznaczenie_attack_interrupt_outcomes`), a Ostrożny atakujący–każdy
wróg (poz. 23). Pierwsze może być legalne przy drugim wyłączonym. Override
działa do `AttackResolved`, nie przechodzi na następny atak/aktywację ani
kontratak drugiej strony. Błąd resolve zachowuje wejściowy scope i RNG;
retry z tego samego checkpointu daje ten sam wynik. Replay redukuje zapisane
eventy, nie oblicza na nowo historycznych testów według nowego hooka.

Bez nowych pól DB/checkpoint/event/wire, bez zmian kosztów, publicznych
odpowiedzi/prediction endpointu, klienta, JS i CSS. `_READY_ATTACK_X` pozostaje
pusty. Publikacja Oznaczenia lub Strażnika z Ostrożnym wymaga osobnego
zatwierdzenia i testów auth/no-oracle/rollback/SQL; nie jest częścią tej spec.

Koszt predykatu: O(N) dla jednostek, O(1) dodatkowej pamięci, krótkie wyjście
po pierwszym bliskim wrogu, zero SQL/I/O/RNG. Bez zdolności lub poza gate
powrót przed skanem. Dla P profili i C ocen kandydatów naiwnie O(P·N)
i O(C·N); na start bez trwałego cache i indeksu przestrzennego. Przyszły
worker mierzy koszt volley i scoringu na istniejących mapach; nie podano
zmyślonego czasu benchmarku dla nieistniejącej implementacji.

## Macierz weryfikacji i DoD implementacji

| Obszar | Minimalny dowód |
|---|---|
| Warunek | Brak wrogów, 11.999/12/12.001″, różne promienie; cel daleko + drugi wróg blisko; sojusznik; wróg bez LoS; statusy; Front kontra pozostałe lokalizacje; pokonany; nakładanie. |
| Rodzaj/role | Ostrzał, main melee, kontratak, wykonana/niewykonana Kontra, Strażnik odrzucony jak wcześniej; oczekiwania melee według zapisanej decyzji. |
| Pasywki | Natywna/nadana/obie/brak; Rozkaz grant/revoke według istniejącego widoku; Oznaczenie tylko właściwego aktora; +1 raz, sumowanie z innymi modifierami i clamp/naturalne 1/6 według pkt 1. |
| Stan i czas | Ruch innego wroga zmienia wynik mimo tego samego celu; świeża pozycja po Związaniu; wiele profili przed przydziałem ran; drugi atak nie dziedziczy override'u. |
| V3 gate | Otwarte okno, zły aktor/cel/profil/intent, brak kontekstu lub stan innej bitwy nie włączają hooka; valid closed-v3 daje rzeczywiste trafienia, nie tylko obecny slug. |
| Prediction | Ten sam kontekst daje +1/0 jak combat i średnią w tolerancji istniejącej Monte Carlo parity; stary API i boty bez opt-in nie dryfują. |
| Trwałość/RNG | Live = pełny replay; restart z zamkniętego headu; przyszłe rzuty zgodne; failed resolve bez mutacji wejścia; retry deterministyczny; historyczny event-tail nie jest reinterpretowany. |
| Kompatybilność | Golden v1/v2, istniejący ranged i Strażnik bez driftu; publiczne Oznaczenie dalej fail-closed bez zapisu; brak nowego schema/payload/SQL. |

Pliki przyszłej implementacji: `engine/effects.py`, `combat.py`, opcjonalnie
wąski adapter `phases.py`, `prediction.py`; `state.py`, `activation_protocol.py`
i `reducers.py` przede wszystkim audyt/testy istniejącego lifecycle.
Ścieżka bazowa: `app/services/`. Nie zmieniać Strażnika ani scoringu legacy
przy okazji. Testy: `test_engine_effects.py`, `test_engine_combat.py`,
`test_engine_activation_protocol.py`, `test_engine_checkpoints.py`,
`test_engine_interrupts.py`, `test_prediction_vs_simulation.py`,
`test_engine_regression.py`, `test_battle_activations.py`,
`test_battle_activation_transport.py` oraz regresje pięciu rodzin scoringu.

Przyszły DoD: decyzja użytkownika z 2026-11-19 zachowana;
Layer Checklist/SSOT/performance gate; testy celowane i pełny `pytest -q`;
call-site audit; simplify/review; security review tylko przy rzeczywistym
rozszerzeniu auth/input→DB; ponowne testy po poprawkach; osobny commit
na `Faza_A` potwierdzony na `origin/Faza_A`. Brak zgody na automatyczny start
implementacji wynika z granicy zatwierdzonego etapu specyfikacji.

## Weryfikacja tego audytu i przeniesienie

Zmiany obejmują wyłącznie dokumentację. Zweryfikowano wymienione symbole
i produkcyjne wywołania, aktualne źródła oraz ich hash check, linki lokalne,
`git diff --check`; przeprowadzono simplify/review dokumentu pod kątem
SSOT, ról, legacy gate, rozdzielenia reguł od propozycji i kompletności testów.
Nie uruchamiano ponownie pytest: zgodnie z zakresem C2d3-spec pełna suita
jest wymagana po zmianie kodu, a kod/testy nie zostały zmienione. Ostatni
pełny wynik bazy D5.2 to **3926 passed, 4 warnings**; nie jest wynikiem nowego
uruchomienia w tym audycie. Security review/UI smoke nie dotyczą dokumentacji.

Dokument, indeks i wynik kolejki są śledzone przez Git. Przed przeniesieniem
na inny komputer pobrać `origin/Faza_A` i odtworzyć środowisko; bazę
`data/szop.db` i lokalne sekrety/konfigurację zachować osobnym backupem.
Wszystkie cztery źródła SZOP (DOCX/PDF/MD) są obecnie śledzone w Git,
co potwierdzono `git ls-files`; ogólna reguła ignorowania katalogu nie
usuwa już śledzonych plików. Odczytana baza niezmieniona: SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Źródła MD znajdują się w obecnym checkoutcie; przenosząc lokalne źródła
sprawdzić ich sumy przez `rules_sources_check.py`. Nie polegać na tym czacie
jako jedynym zapisie pytania i dalszego kontraktu.
