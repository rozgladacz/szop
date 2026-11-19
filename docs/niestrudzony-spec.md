# Niestrudzony — audyt B4.4d.C2d6-spec

Status: **audyt zakończony 2026-11-20; wykluczony z publikacji obecnego
attack-only Oznaczenia**. Baza: `7a132f5` na `Faza_A`. Bez implementacji,
zmiany tagów, kosztów, historii eventów lub publicznego katalogu.

## Źródła i wniosek

Odczytano [Zdolności, poz. 14, 49 i 50](../app/static/docs/SZOP_Zdolnosci.md)
i [Rozjemcę, pkt 11.b, 12, 14.c.v i 14.d.vi](../app/static/docs/SZOP_Rozjemca.md).
Niestrudzony znosi ograniczenie powtórzenia Ostrzału/Szarży w aktywacji
(pkt 14.c.v/14.d.vi), ale nie znosi limitu dwóch akcji (pkt 11.b.iv,
poz. 14). Manewr nie potrzebuje tej zdolności do powtórzenia: aktualny pkt 11
nie zawiera ogólnego zakazu powtarzania wszystkich rodzajów akcji.

Oznaczenie nadaje X tylko na rozpatrywany atak (poz. 49). Obecny protokół
najpierw sprawdza legalność i deklaruje atak, dopiero potem otwiera okno
jego Oznaczenia. Po rozliczeniu `AttackResolved` usuwa scope i override'y,
przed wyborem następnej akcji. Dlatego **nie publikować `niestrudzony`
w obecnym attack-only katalogu**. Nadanie na pierwszy atak nie trwa do
deklaracji drugiego; nadanie w drugim ataku nie może wstecznie zalegalizować
jego odrzuconej deklaracji. Nie przenosić efektu na następną akcję ani do
`UnitBlob.ability_overrides`, aby wymusić użyteczność. To ograniczenie
aktualnego protokołu, nie zmiana tagu `oznaczenie_tak: true` lub reguły gry.

Nie jest potrzebna nowa decyzja o regułach. Wykluczenie jest dopuszczonym
wynikiem audytu i nie blokuje zaakceptowanego D5.3a. Osobno istnieje luka
obsługi zdolności natywnej/Rozkazu opisana poniżej.

## Synchronizacja i dwa rodzaje driftu

`scripts/rules_sources_check.py`: **4/4 CLEAN, exit 0** (DOCX, PDF, oba MD).
DOCX odczytany bezpośrednio z XML archiwum mówi: „Może wykonywać tę samą
akcję wielokrotnie w aktywacji.” MD poz. 14 potwierdza aktywację i limit
2 akcji. Opis katalogu `abilities.yaml` dla `niestrudzony` nadal mówi
**„w rundzie”**. To drift wtórnego katalogu względem zgodnych DOCX/MD i
pkt 14.c.v/14.d.vi; nie podstawa do zmiany reguły na limit rundy.
Nie zmieniano YAML, źródeł, hashy ani ekstraktów. PDF zweryfikowano hashem,
bez niezależnej interpretacji treści. CLEAN nie dowodzi zgodności katalogu.

Pole `efekty.kiedy` MD odsyła do „11.b.iii (warunek pętli aktywacji)”.
W odczytanym Rozjemcy 11.b.iii dotyczy Przegrupowania, a warunek pętli
jest w 11.b.iv. To nieaktualny odsyłacz; właściwe ograniczenia powtórzeń
są jawne w 14.c.v/14.d.vi. Nie kopiować starego numeru do nowego kodu.

## Mapa kodu i moment sprawdzenia

| Symbol / ścieżka | Odczytany kontrakt i skutek |
|---|---|
| `actions.can_append_activation_action_type` | SSOT limitu 2 i zakazu drugiego `shoot`/`charge`; przyjmuje tylko typ i historię. Nie ma aktora ani effective passives. |
| `resolver._can_take_followup` → `apply_activation` | Legacy v1 deleguje do tej samej SSOT. Powtórzony Shoot/Charge kończy pętlę zamiast wykonania; sam natywny slug nie zmienia wyniku. |
| `agents.base.legal_followup_actions` | Filtruje kandydatów przez `_can_take_followup`; tę granicę dziedziczą Random, Greedy, Minimax i rodziny Claude używające helpera. Nie naprawiać tylko bota, omijając silnik. |
| `activation_protocol.start_activation` | Otwiera BEFORE_ACTION przed pierwszą akcją, bez inkrementacji action_count. |
| `trigger_activation_interrupt` → `interrupts.execute_ready_activation_interrupt_outcomes` | Obsługuje Rozkaz w oknie przed akcją. Nadanie w `UnitBlob.ability_overrides` może istnieć przed walidacją akcji, w odróżnieniu od attack-only Oznaczenia. |
| `commit_activation_action` | V2 sprawdza wspólny limit/historię przed klonowaniem RNG i outcome. Brak odczytu Niestrudzonego. |
| `_commit_activation_action_v3` → `_declare_activation_attack` → `_canonical_attack_intent` | V3 sprawdza tę samą historię przed `AttackDeclared` i `AttackInterruptWindowOpened`. Drugi Shoot/Charge nie dochodzi do okna nadania X. |
| `_trigger_attack_interrupt` → `execute_oznaczenie_attack_interrupt_outcomes` | Działa dopiero w ATTACK_WINDOW. Prywatny handler akceptuje tagowy slug i emituje attack override dla deklarowanego aktora; nie nadaje prawa do kolejnej deklaracji. |
| `_resolve_activation_attack` → `_canonical_action_from_attack` | Przed outcome ponownie odtwarza i waliduje kanoniczną akcję/intencję; nie służy do naprawy nielegalnej historii. RNG klonowany prywatnie. |
| `state.effective_passives` / `effective_attack_passives` | Pierwszy uwzględnia native i aktywacyjne grant/revoke; drugi dodaje attack grant wyłącznie właściwemu deklarowanemu aktorowi. Legalność powtórzenia obecnie nie wywołuje żadnego z tych view. |
| `reducers._reduce_attack_resolved` | Usuwa `activation.attack`, w tym jego override'y, przed eventem commitującym akcję. |
| `_reduce_activation_action_committed` | Jedyny wskazany produkcyjny reducer rozszerzający `action_types` i `action_count`; jedna akcja → AWAITING_CONTINUATION, dwie → AWAITING_FINALIZATION. |
| `continue_activation` | Dopuszcza powrót do BEFORE_ACTION dopiero po jednej akcji. Sama decyzja continue nie zatwierdza dowolnego następnego rodzaju akcji. |
| `finalize_activation` → `phases._finalize_activation` | Kończy po 1 lub 2 akcjach; czyści aktywacyjne override'y przez eventy. Attack scope wygasa wcześniej przez AttackResolved. |
| `state.ActivationState` | Ścisły count 0..2 i zgodność długości historii; nie dodawać „trzeciej akcji” przez ominięcie walidatora. |

`prediction.expected_damage` przewiduje pojedynczy atak, a nie prawo do
następnej akcji. Nie dodawać mnożnika obrażeń Niestrudzonego do prediction
ani hooka w `effects._ATTACK_MODIFIERS`: nie rozwiązałyby legalności pętli.
Poz. 14 nie zmienia liczby trafień pojedynczego ataku. Kontratak jest
reaktywną częścią Szarży (pkt 14.d.iv), a nie drugą akcją aktywacji obrońcy;
nie inkrementować jego action_count ani nie przekazywać mu grantu aktora.

## Istniejąca luka kodu, nie nowy rules claim

`can_append_activation_action_type` bezwarunkowo odrzuca drugi Shoot/Charge.
W konsekwencji nie obsługuje wyjątku dla **natywnego** Niestrudzonego ani
Niestrudzonego obecnego przez aktywacyjne view Rozkazu. Literalny search
`niestrudzony` w silniku nie znalazł konsumenta tej zdolności; odnalezione odwołania
wyceny/migracji nie są implementacją mechaniki. To istniejąca luka względem
pkt 14.c.v/14.d.vi, nie powód do wydłużenia Oznaczenia. Audyt niczego nie
naprawia i nie aktualizuje goldenów; publiczne `_READY_ATTACK_X` nadal puste.

Odczytane regresje `test_followup_shoot_twice_rejected`,
`test_followup_charge_twice_rejected` i
`test_action_bridge_rejects_repeated_shoot_or_charge_from_durable_history`
dowodzą odrzucania zwykłego powtórzenia. Nie są dowodem obsługi wyjątku
Niestrudzonego; brak w nich przypadku z tą zdolnością.

## Przykłady i macierz przyszłych regresji

| Sytuacja | Oczekiwanie źródłowe / zakres weryfikacji |
|---|---|
| Shoot → Shoot, brak Niestrudzonego | Druga deklaracja odrzucona bez zmiany state, wersji, eventów i wejściowego RNG. |
| Charge → Charge, native Niestrudzony | Wyjątek powtórzenia według 14.d.vi, nadal wszystkie wymagania drugiej Szarży i limit 2; obecna luka kodu. |
| Shoot → Shoot, native Niestrudzony | Wyjątek 14.c.v, nie dodatkowy volley w pierwszej akcji; obecna luka kodu. |
| Rozkaz nadaje Niestrudzonego w BEFORE_ACTION drugiej akcji | View istnieje przed walidacją, poz. 50 i kierunek „+” poz. 14; przyszła implementacja powinna odczytać go wtedy. |
| Wewnętrzny revoke native przed drugą akcją | Test czysto technicznego effective view: brak wyjątku. Nie przedstawiać jako legalnej ujemnej opcji source-correct Rozkazu dla poz. 14. |
| Oznaczenie(Niestrudzony) w pierwszym ataku | Nie utrzymywać grantu po AttackResolved; drugi Shoot bez native/Rozkazu nadal odrzucony. |
| Próba nadania Oznaczenia dopiero w drugim Shoot | Okno nie powstaje, jeżeli declare już narusza historię. Grant nie działa wstecz. |
| Trzecia akcja z dowolnym nadaniem | Nigdy; 11.b.iv/poz. 14 oraz ścisły model 0..2. |
| Maneuver → Maneuver bez zdolności | Nadal legalne względem powtórzenia; nie dodawać nowego ograniczenia. |
| Rozwiązanie ataku kończy się błędem / retry | Nie usuwać wejściowego scope ani nie commitować historii/RNG; retry z tego samego checkpointu deterministyczny. |
| Restart przed/po AttackResolved i po continue | Complete-tail equality, oddzielny lifetime native/aktywacyjny/attack; 12 przyszłych rzutów zgodne. |
| Counter / inny właściciel / inny oddział | Brak dziedziczenia grantu deklarowanego aktora i brak cudzej historii akcji. |

## Przyszły zakres i ograniczenia

Wykonalny osobny etap: poprawna, wspólna walidacja powtórzeń dla native i
aktywacyjnego view Niestrudzonego w jawnie wybranym protokole. Potrzebny
minimalny kontekst aktora przy wspólnej SSOT, ponowna ocena przed deklaracją
i resolve oraz zgodne filtrowanie kontynuacji botów. Nie utrwalać pochodnej
flagi w eventach ani nie kopiować reguły do adapterów. Bazowy limit 2 i
obecne discriminators pozostają. Zakres zgodności legacy v1/v2 trzeba
jawnie zamrozić w tym przyszłym etapie: poprawka zmieni zachowanie bitwy
z Niestrudzonym i nie może milcząco reinterpretować starych event-taili.

Proponowane pliki: `actions.py`, `activation_protocol.py`, `resolver.py`,
`agents/base.py`; audyt/testy `state.py`, `reducers.py`, `interrupts.py`,
`phases.py`, serde checkpointu i publicznych serwisów. Ścieżka `app/services/`.
Koszt: O(P) sprawdzenia pasywek aktora z uwzględnieniem override'ów,
stała historia długości do 2; zero dodatkowych SQL, I/O, RNG i cache.
Bez zdolności ścieżka zachowuje obecne odmowy.

Testy przyszłej poprawki: `tests/test_engine_multi_action.py`,
`tests/test_engine_activation_protocol.py`, `tests/test_engine_interrupts.py`,
`tests/test_engine_checkpoints.py`, `tests/test_agents_base.py`,
`tests/test_agents_match.py`, publiczny transport aktywacji i regression.
DoD implementacji: macierz powyżej, call-site audit wspólnej SSOT, pełny
pytest, simplify/review, security review przy auth/input→DB, osobny commit
na Faza_A i potwierdzenie origin. Nie jest to etap uruchamiany przez ten audyt.
Publikacja attack-only Oznaczenia nadal wyklucza Niestrudzonego; inny model
nadania wymaga osobnego zakresu, a nie ukrytej poprawki czasu życia.

## Weryfikacja audytu i przeniesienie

Tylko Markdown. Odczyt źródeł i sync 4/4 CLEAN, 25 symboli AST w 9 plikach,
audyt call sites, 6 nowych celów linków, `git diff --check`, simplify/review dokumentu: oddzielenie legalności
od outcome, trzech czasów życia i wtórnego driftu od źródeł. Bez zmian kodu
lub testów nie ponawiano pytest; **3987 passed, 4 warnings** to historyczny
wynik C2d3, nie nowy przebieg audytu. UI smoke/security review nie dotyczą
zmian samej dokumentacji. Brak nowego pytania użytkownika.

Wynik, źródła i plan są śledzone w Git. Osobny commit na `Faza_A` potwierdzić
na `origin/Faza_A`. Baza pozostaje nietknięta, SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Przed zmianą komputera wykonać osobny backup bazy i lokalnych sekretów/
konfiguracji, odtworzyć środowisko z requirements. Cudzy hunk B6.2 i pliki
historyczne nie należą do etapu. Następny zaakceptowany etap: **D5.3a**.
