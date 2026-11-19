# Planowanie — audyt B4.4d.C2d5-spec

Status: **audyt zakończony 2026-11-19; kandydat do osobnego prywatnego
etapu implementacji, jeszcze nie gotowy do publikacji Oznaczenia**.
Baza: `a09e55a` na `Faza_A`, po C2d3 i audycie Bastionu. Zmiany wyłącznie
w dokumentacji. Następny zaakceptowany audyt to C2d6-spec, Niestrudzony.

## Źródła i wniosek

W tej sesji odczytano [Zdolności, poz. 25, 49 i 50](../app/static/docs/SZOP_Zdolnosci.md)
oraz [Rozjemcę, pkt 1, 11–14, 17, 20 i 22](../app/static/docs/SZOP_Rozjemca.md).
Planowanie daje +1 do trafienia wtedy, gdy oddział jest Przygotowany
(poz. 25, pkt 17.a). Nie zawiera ograniczenia do Ostrzału. Należy oceniać
status **rzeczywistego atakującego w momencie testu**, także w jego połowie
kontrataku (pkt 17). Zdolność nie nadaje stanu Przygotowany ani go nie zużywa.

Oznaczenie nadaje X innemu sojuszniczemu deklarowanemu atakującemu tylko
na konkretny atak (poz. 49). Dlatego Planowanie pasuje do obecnego main-
attacker scope, jeżeli ten atakujący rzeczywiście ma Przygotowany; brak
statusu oznacza brak premii, nie automatyczne nadanie statusu. Kontratakujący
nie dziedziczy Oznaczenia szarżującego. Jego natywne Planowanie może mieć
znaczenie niezależnie od tego ograniczenia. To różnica wobec
[audytu Bastionu](bastion-spec.md), nie powód do rozszerzenia odbiorcy.

`scripts/rules_sources_check.py`: **4/4 CLEAN, exit 0**. `SZOP.docx`
odczytany bezpośrednio z XML zawiera „Planowanie: Jeżeli jest Przygotowany,
+1 do rzutów na trafienie.”; opis MD i `abilities.yaml` jest zgodny.
MD/YAML mają `rozkaz_kierunek: "+"` oraz `oznaczenie_tak: true`.
PDF sprawdzono sumą kontrolną, bez niezależnej interpretacji treści.
Hash clean nie dowodzi zgodności kodu z regułami. Źródeł i hashy nie zmieniano.

**Wniosek:** przyszła prywatna implementacja jest wykonalna; audyt nie
upoważnia do jej uruchomienia ani dodania `planowanie` do `_READY_ATTACK_X`.
Nie ma nowego pytania o regułę. Istniejące różnice kodu opisano poniżej,
a dalszy zaakceptowany audyt może się odbyć.

## Trzy różne pojęcia

| Identyfikator | Znaczenie i stan obecny |
|---|---|
| `planowanie` | Kanoniczna zdolność z poz. 25; YAML ma prawidłowy opis i tagi, lecz brak produkcyjnego hooka w `_ATTACK_MODIFIERS`. |
| `STATUS_PRZYGOTOWANY` / `Przygotowany` | Status z pkt 22.c, trzymany w `UnitBlob.status_flags`; ma własne skutki obrony/LoS i lifecycle. Nie jest zdolnością. |
| `przygotowanie` / Przygotowanie | Osobny historyczny wpis YAML z warunkiem Ufortyfikowany; brak takiej zdolności/statusu w aktualnym kanonie MD. Nie traktować jako aliasu Planowania i nie zmieniać jego wyceny w tym etapie. |

ADR-0056 §5.4 opisuje historyczne dodanie `planowanie` obok `przygotowanie`.
Jest kontekstem migracji, nie źródłem reguł. Nie zmieniać obu slugów globalną
zamianą. Test `test_v3_oznaczenie_reaches_combat_only_for_declared_attacker`
wstrzykuje sztuczny modifier +5 przez monkeypatch: dowodzi drogi scope,
a nie produkcyjnego efektu Planowania ani sprawdzenia Przygotowanego.

## Rola, status i czas

Podstawa: poz. 25/49/50 Zdolności, pkt 13.c, 14.b, 17, 22.b.iii i 22.c
Rozjemcy. Przygotowany znika na początku własnej aktywacji (22.c.iii),
nie na początku każdej kolejnej akcji. Mobilizacja nadaje go ponownie
(14.b); współistnienie z Przyszpilonym usuwa oba (22.b.iii/22.c.iv).
Premia obrony ze statusu (22.c.i) jest niezależna od premii trafienia
ze zdolności; jeden efekt nie zastępuje drugiego.

| Podmiot / nadanie | Moment i status | Znaczenie przyszłego hooka |
|---|---|---|
| A z natywnym Planowaniem, Przygotowany po rozstawieniu | Start własnej aktywacji usuwa status przed pierwszym oknem | Pierwszy atak bez ponownego nadania statusu: +0. Nie czytać snapshotu sprzed startu. |
| A z Planowaniem, pierwsza akcja Mobilizacja, druga Ostrzał/Szarża | Przygotowany obecny w chwili trafienia | +1; dalsza akcja nie może ponownie wykonać startowego usunięcia. |
| A bez Planowania, ale Przygotowany | Sam status podczas trafienia | +0 do trafienia z tej zdolności; skutki samego statusu pozostają odrębne. |
| A otrzymał Oznaczenie(Planowanie), jest Przygotowany | Zamknięty atak A | +1 raz; native + mark także tylko raz. Nadanie X nie nadaje Przygotowanego. |
| A otrzymał Oznaczenie, ale stracił Przygotowany przed trafieniem | Aktualny blob nie ma statusu | +0, nawet gdy status istniał przy deklaracji/nadaniu. |
| A ma Planowanie nadane Rozkazem | Poz. 25 ma kierunek „+”; grant do końca aktywacji (poz. 50) | +1 tylko z aktualnym statusem. Sztuczny suppress w testach view nie jest dodatnią publiczną opcją Rozkazu dla tej zdolności. |
| D ma natywne Planowanie i jest Przygotowany | D wykonuje kontratak w aktywacji A, nie startuje własnej aktywacji | +1 przy testach D; nie usuwać statusu tylko dlatego, że D kontratakuje. |
| D bez Planowania, A ma Oznaczenie(Planowanie) | Counter D w charge scope A | +0 dla D; override A nie może przeciekać na drugą stronę. |
| Dowolny atakujący z Planowaniem | Status utracony przez mutex po akcji | Nie cofać wcześniejszych wyników; następny atak czyta nowy stan. |
| Atak A zakończony | `AttackResolved` usuwa attack override | Sama nadana przez Oznaczenie zdolność znika; natywne/Rozkaz i status mają odrębny lifecycle. |

Wieloprofilowy Ostrzał ocenia testy przed przydziałem ran (pkt 17.c–e).
Nie zdejmować Przygotowanego po pierwszym profilu ani nie przeliczać
wcześniejszych trafień po Przegrupowaniu (pkt 11.b.iii/20). W melee używać
aktualnego parametru bloba danej połowy sekwencji; nie odnajdywać go na siłę
w starym `state.blobs`, który może nie zawierać zmian po kontrataku.

## Odczytana mapa kodu

| Symbol / ścieżka | Obecny kontrakt i punkt przyszłej zmiany |
|---|---|
| `phases.deployment_round` | Nadaje Przygotowany po rozstawieniu. To status początkowy, nie stała premia trafienia. |
| `phases._begin_activation`, `activation_protocol.start_activation` | Usuwają Przygotowany raz przy starcie. V2/v3 emituje `StatusRemoved` przed pierwszym oknem. |
| `phases._apply_defend` | Runtime Mobilizacji nosi historyczną nazwę `DefendAction`/defend. Nadaje Przygotowany; patrz zidentyfikowany drift mutex poniżej. |
| `phases._apply_single_action`, `_apply_mutex_collisions` | Rozpatrują akcję i późniejsze Przegrupowanie/mutex; kolejna akcja nie uruchamia `_begin_activation`. |
| `status.add_status`, `remove_status`; `reducers._reduce_status_added`, `_reduce_status_removed`, `_reduce_mutex_collision` | SSOT statusów i zapisane zmiany dla replay. Nie zastępować eventu zmodyfikowaniem tylko lokalnego tuple. |
| `state.effective_passives`, `effective_attack_passives` | View deduplikuje native/grant; attack override dodaje się wyłącznie aktorowi intentu, po bazowych override'ach. Reużyć istniejącą kolejność. |
| `interrupts.execute_oznaczenie_attack_interrupt_outcomes` | Prywatny tagowany handler już przyjmuje `planowanie` i nadaje attack-only override, nie status. |
| `interrupts._apply_rozkaz`, `_rozkaz_capable_directions` | Osobny activation-scoped grant; canonical kierunek Planowania to „+”. |
| `effects.aggregate_attack_modifier`, `EffectContext` | Brak hooka `planowanie`. Przyszły hook czyta status `context.blob`, ma prywatny jawny opt-in, zwraca 0/1 i nie mutuje statusu. |
| `combat._matching_closed_shoot` | Matcher C2d3 jest obecnie specyficzny dla `ostrozny`; sam `state` z Planowaniem bez Ostrożnego nie otwiera go. Nie reużyć bez świadomego rozdzielenia kwalifikacji. |
| `combat._resolve_ranged_profile_pools`, `_resolve_ranged_volley` | Wspólna droga Ostrzału, per-profile context; nie włączać szerokiego `source_correct` dla nowego hooka. |
| `combat._matching_closed_charge`, `resolve_charge_attack`, `resolve_melee_attack` | Parent gate v3 jest odrębny od Furii. Przyszły opt-in Planowania obejmuje obie połowy dla native/Rozkaz, lecz mark nadal tylko deklarowanego aktora. Kontra nie wyłącza Planowania z samego powodu utraty „szarżujący”. |
| `activation_protocol._resolve_activation_attack`, `_execute_single_action_outcomes` | Kanoniczny preflight, prywatny klon RNG, outcome przez `_apply_single_action`. Nie wywoływać wrappera rozpoczynającego nową aktywację. |
| `reducers._reduce_attack_resolved` | Czyści `activation.attack`; nie usuwa natywnej zdolności ani statusu za Planowanie. |
| `prediction.expected_damage` | Opcjonalne `state` w C2d3 działa przez matcher Ostrożnego. Przyszły context musi osobno kwalifikować Planowanie; bez kontekstu zachować historyczny wynik. |
| `interrupts._execute_straznik_activation_interrupt_outcomes` | `planowanie` w `_STRAZNIK_UNSUPPORTED_SOURCE_PASSIVES`; odmowa publicznego Strażnika pozostaje do osobnego zakresu. |

Pięciu bezpośrednich konsumentów prediction (Greedy, PriorityV2/V3,
ClaudeV1/V3) nie podaje pełnego `state`; nie włączać im nowego scoringu
przy okazji. Kolejny prywatny gate może reużyć kanoniczną walidację profilu
jak C2d3, ale nie może wymagać posiadania Ostrożnego ani `is_charging`.
Szczegół nazwy nowego flag/contextu jest odwracalną decyzją techniczną.

### Istniejący drift statusu — bez zmiany w audycie

`_apply_defend` na wejściu Przyszpilony dodaje Przygotowany i usuwa wyłącznie
Przyszpilony. Późniejszy mutex nie widzi obu, więc Przygotowany zostaje.
Aktualny pkt 22.b.iii/22.c.iv nakazuje odrzucić oba przy współistnieniu.
Test `test_activation_defend_removes_pinned_status` opisuje dawny kontrakt.
To różnica kodu względem jednoznacznego źródła, nie nowe pytanie o regułę.
Nie poprawiono jej w dokumentacyjnym audycie i nie potraktowano wyniku
tej ścieżki jako dowodu poprawności przyszłego Planowania. Przed odrębną
implementacją określić zakres regresji statusów; ewentualna korekta wspólnej
Mobilizacji musi mieć jawny zakres/zgodność i testy, bez ukrytego refaktoru.
Stare komentarze nazywające usunięcie statusu pkt 22.c.iv również są
nieaktualne: obecnie start własnej aktywacji to pkt 22.c.iii.

## Proponowany ograniczony etap implementacyjny i testy

Implementację wybrać osobno. Pierwszy zakres: prywatne, poprawnie zamknięte
v3 Shoot/Charge, native/Rozkaz/attack mark, wspólny hook i jawny prediction
opt-in. Melee jest dozwolone przez poz. 25; nie kopiować ranged-only gate
Ostrożnego. Dla counter użyć kwalifikacji całej closed Charge, a nie
`charging_attack`/Furii. Direct/legacy v1/v2 i publiczny Strażnik zachowują
wynik/eventy/RNG. `_READY_ATTACK_X` nadal puste. Bez nowych pól
DB/checkpoint/event/wire/API/klienta, kosztów i UI.

| Obszar | Minimalna przyszła regresja |
|---|---|
| Stan w czasie | Start usuwa Przygotowany; Mobilizacja→Shoot i Mobilizacja→Charge; inna pierwsza akcja; brak podwójnego startu; status utracony przed testem. |
| Status mutex | Wcześniej Przyszpilony + Mobilizacja; Przygotowany + Przyszpilony po Przegrupowaniu; test oczekiwania zgodnie z aktualnym pkt 22.b/c. |
| Role | Prepared/not-prepared main i counter; Kontra/bez; mark A nie trafia do D; native D działa samodzielnie; brak kontrataku przy Wyczerpanym. |
| Nadanie | Native/grant/both/brak; +1 raz; Rozkaz kierunek „+”; synthetic view suppress vs mark zgodnie z kolejnością; brak wycieku na następny atak. |
| Test trafienia | Realny próg z/bez +1, naturalne 1/6 i clamp według pkt 1; sumowanie z Ostrożnym i Osłoną bez podwójnego bonusu. |
| Gate | Brak/open/mismatched intent/actor/target/profile; Planowanie bez Ostrożnego; closed Shoot i Charge; natywny counter niezależny od Furii. |
| Volley/prediction | Wszystkie profile właściwego aktora, brak zdejmowania statusu per profil; ten sam hook i Monte Carlo parity; legacy scoring bez contextu bez driftu. |
| Trwałość | Pełny replay, restart z ready headu i przyszłe RNG; failed resolve/retry bez mutacji state/RNG; stary event-tail nie jest przeliczany. |
| Publiczna granica | Strażnik i publiczny interrupt Oznaczenia nadal fail-closed; no-oracle/rollback jak wcześniej. |

Przyszłe pliki: `engine/effects.py`, `combat.py`, `prediction.py`, ewentualny
wąski adapter `phases.py`; lifecycle/reducers głównie testować. Testy:
`test_engine_effects.py`, `test_engine_phases.py`, `test_engine_combat.py`,
`test_engine_activation_protocol.py`, `test_engine_checkpoints.py`,
`test_engine_straznik.py`, `test_prediction_vs_simulation.py`,
`test_engine_regression.py`, `test_battle_activation_transport.py` oraz
konsumenci scoringu. Pełny pytest, call-site audit, simplify/review, pomiar
realnego gate, osobny commit i push są DoD wybranego etapu implementacyjnego.

Koszt samego warunku: O(1), sprawdzenie statusu bez SQL/I/O/RNG. Koszt
przejścia effective passive view i ewentualnego kanonicznego preflightu jest
odrębny; przed wdrożeniem zmierzyć go jak w C2d3. Bez nowego cache. Brak
zdolności/gate powinien zakończyć ocenę przed walidacją pełnego profilu.

## Weryfikacja i przeniesienie

Źródła 4/4 CLEAN, bezpośredni odczyt DOCX/MD/YAML; 29 symboli AST w 9
plikach silnika, wywołania, 4 nowe lokalne cele linków, simplify/review
oraz `git diff --check`. Wyłącznie dokumentacja:
pytest nie ponawiano, kod i testy niezmienione; **3987 passed** jest wyłącznie
historycznym wynikiem C2d3. Security review/UI smoke nie dotyczą tej zmiany.

Wynik, indeks i kolejka mają osobny commit na `Faza_A`, potwierdzany na
`origin/Faza_A`. Baza nietknięta, SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Baza oraz lokalne sekrety/konfiguracja wymagają osobnego backupu;
źródła SZOP DOCX/PDF/MD są śledzone w Git. Cudze zmiany, historyczny hunk
B6.2 i HANDOFF pozostają poza commitem. Następny etap C2d6-spec nie został
uruchomiony w ramach tego audytu. Brak nowych pytań wymagających użytkownika.
