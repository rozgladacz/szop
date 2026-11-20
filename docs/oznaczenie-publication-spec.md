# Oznaczenie — przygotowanie ograniczonej publikacji

Status: **B4.4d.C2-publication-spec zakończone 2026-11-20**.
Baza audytu: `0ef296840ab1c665bf6c49c5ae968b88853ff5d8` na `Faza_A`.
To dokumentacja i security audit, nie zgoda na publikację lub nowy write tool.
Kod, testy, źródła, uprawnienia i `_READY_ATTACK_X` pozostają bez zmian.

## Źródła i zakres katalogu

Odczytano w tej sesji [Zdolności, poz. 1, 6, 7, 10, 13, 14, 23, 25, 49,
50 i 66](../app/static/docs/SZOP_Zdolnosci.md) oraz
[Rozjemcę, pkt 11–14 i 17](../app/static/docs/SZOP_Rozjemca.md).
`rules_sources_check.py`: **4/4 CLEAN, exit 0**. Hash check potwierdza wersje
DOCX/PDF/MD; nie usuwa opisanych w audytach różnic katalogu lub kodu.
Nie aktualizowano hashy ani ekstraktów. Szczegółowe audyty źródeł:
[Bastion](bastion-spec.md), [Planowanie](planowanie-spec.md),
[Niestrudzony](niestrudzony-spec.md), [Ostrożny](ostrozny-spec.md).

Poz. 49 nadaje X innemu sojuszniczemu atakującemu wyłącznie na konkretny
atak; nosiciel mierzy zasięg do zadeklarowanego celu. To inny warunek niż
brak wroga w 12″ od atakującego dla Ostrożnego (poz. 23). Decyzja użytkownika
2026-11-19 ogranicza Ostrożnego do dystansowych. Obecny prywatny handler
używa krawędzi kół i sprawdza żywe jednostki na Froncie; nie dodawać wymogu
LoS dla Oznaczenia, którego poz. 49 nie ustanawia. To odwzorowanie blobów,
nie nowa reguła modeli.

Poz. 49 wskazuje własny moment przerwania, a pkt 12.a–c wymaga dokończenia
przerwania przed następnym i przekazania priorytetu. W obecnym v3 kolejność
jest jawna: zamknięcie ogólnego BEFORE_ACTION → legalna deklaracja z intentem
atakujący/cel/inventory → ATTACK_WINDOW → nadanie/pass → zamknięcie okna →
resolve. Nie dodawać grantu przed znanym celem, podczas resolve lub do
kontrataku obrońcy; ten ostatni jest osobnym Atakiem według pkt 14.d.iv/17.
To granica obecnego scope, nie usunięcie kontrataku z kanonu.

| X / zależność | Gotowość na bazie audytu | Granica publikacji |
|---|---|---|
| `furia`, poz. 7 | Prywatna mechanika C2d1 działa w głównym ataku pasującej zamkniętej Szarży v3; wykonana Kontra wyłącza kwalifikację. | Pierwszy kandydat; wymagane rzeczywiste pozytywne przepływy publiczne, wymienione niżej. Nie gotowy publicznie przy pustym allowliście. |
| `ostrozny`, poz. 23 | C2d3: prywatny closed Shoot v3 i jawny opt-in prediction, skan wszystkich żywych wrogów na Froncie. | Drugi kandydat, po regresjach HTTP obu warunków bliskości, restartu i braku efektu w melee. Nie rozszerzać szerokiego `source_correct` ani Strażnika. |
| Podwójny / alias `rozrywajacy`, poz. 66 | C2d2 naprawia alias broni w prywatnym melee v3; współdziała z Furią przez `_count_hits`. | To zdolność **broni**, nie samodzielne pasywne X obecnego katalogu. Nie dodawać aliasów do `_READY_ATTACK_X`; testować jako zależność Furii. |
| `planowanie`, poz. 25 | Audyt C2d5-spec; brak produkcyjnego hooka. Przygotowany jest osobnym statusem, a historyczne `przygotowanie` osobnym wpisem. | Nie publikować przed osobną implementacją i rozwiązaniem dotyczącego jej prerequisite Mobilizacji z audytu. Nie wymaga naprawy dla pierwszej Furii. |
| `bastion`, poz. 1 | Dotyczy wykonawcy kontrataku; obecny main-attacker scope nie reprezentuje jego osobnego nadania. | Wykluczony z obecnego zakresu, bez zmiany `oznaczenie_tak` lub reguły. Natywny/Rozkaz to osobne ścieżki. |
| `niestrudzony`, poz. 14 | Legalność powtórzenia Shoot/Charge jest oceniana przed nadaniem attack override, które wygasa przed kolejną akcją. Audyt wskazuje także lukę native/Rozkazu. | Wykluczony z attack-only zakresu; nie przedłużać grantu ani wstecznie legalizować deklaracji. |
| `mistrzostwo`, poz. 13 | Źródło ma parametr zdolności broni X, a obecny payload Oznaczenia zawiera tylko płaski slug. | Osobny projekt parametru i walidacji; brak gotowości z samego tagu. Nie przemycać parametru w stringu. |
| `dywersant`, poz. 6 | Odłożony w planie; aktualne źródło wymaga kontekstu strefy i wyboru przeciwnika. | Nie publikować na podstawie historycznego stuba „×2 vs Przyszpilony”. Osobny audyt/implementacja. |
| Inne pasywne X z tagiem | Prywatny `_OZNACZENIE_CAPABLE_SLUGS` pochodzi z zamrożonego YAML. | Tag dopuszcza prywatny payload, nie dowodzi mechaniki. Bez audytu i efektu brak publicznej gotowości. |

**Obecny publiczny katalog: pusty.** Proponowany pierwszy minimalny katalog
po osobnym zatwierdzeniu i spełnieniu bramek: `{furia}`, następnie oddzielne
rozszerzenie o `{ostrozny}`. To propozycja etapów, nie edycja allowlisty.
Nadanie zdolności i otrzymanie jej bonusu to różne zdarzenia: niespełniony
warunek Furii/Ostrożnego może legalnie dać brak bonusu. Nie wprowadzać przy
okazji nowego zakazu nadania wyłącznie dlatego, że obecny atak nie skorzysta;
opis katalogu i UI powinien jasno wskazywać warunek użyteczności.

## Faktyczny łańcuch i granice zaufania

| Warstwa | Obecny symbol / zachowanie | Co musi udowodnić publikacja |
|---|---|---|
| Private core | `activation_protocol._trigger_attack_interrupt` sprawdza aktywację, attack/window versions, fazę, priorytet, źródło i limit okna; klonuje RNG. | Gotowość X nie zastępuje żadnego guardu. Zachować no-nested i ograniczenie liczby efektów. |
| Outcome | `interrupts._validated_oznaczenie_attack_payload` i `execute_oznaczenie_attack_interrupt_outcomes`: dokładnie `{'ability': slug}`, kanoniczny tag, source/attacker/target, zasięg i limit raz/rundę. | Odbiorcą jest zadeklarowany atakujący; inne role i kolejne ataki nie dziedziczą nadania (poz. 49). |
| Reducery / combat | `effective_attack_passives`, `_resolve_activation_attack`, `_reduce_attack_resolved`; rzeczywiste mechaniki Furii i Ostrożnego mają własne gate. | Actual hits/state, a nie tylko obecność sluga; cleanup do `AttackResolved`, replay oraz przyszły RNG. |
| Durable service | `stage_battle_activation_interrupt` ma oddzielne `_READY_ATTACK_X`; ładuje participant battle i spójny checkpoint, mapuje caller side, wywołuje core, `save_events` + `save_checkpoint`. | Dodanie X wyłącznie po pozytywnych i negatywnych dowodach; bez nowych odczytów katalogu/rosterów per jednostka. |
| HTTP | `mutate_battle_activation_interrupt` i `_stage_activation_mutation`, ścisłe modele attack request. | Response serializowany **przed** commitem; wyjątek robi rollback i stabilne mapowanie błędu. |
| HttpClient | `interrupt(..., scope='attack', attack_id=..., expected_attack_version=...)`, `pass_interrupt_priority`, `resolve_activation_attack`, `_post_activation_mutation`. | Jeden POST na mutację, ścisły decode v3, ciągłe sekwencje i kontrola battle ID; bez fallbacku do activation-only. |
| MCP | Obecna lista tools ma odczyty i consent-gated `propose_battle_action`; nie publikuje `HttpClient.interrupt` ani resolve jako narzędzi. | Publikacja HTTP nie jest zgodą na nowy bezpośredni write tool MCP. Ewentualny typed proposal dla przerwania wymaga własnego projektu i akceptacji. |
| UI | Podgląd bitwy jest odczytem, a `agent_proposals` obsługuje istniejące propozycje akcji. | Nie zakładać istnienia pełnego interfejsu attack-window/Oznaczenia. UI to kolejny jawny etap, nie warunek działania klienta HTTP. |

Legacy `_oznaczenie_handler` BEFORE_ACTION używa uproszczonego order-like
nadania przez `UnitBlob.ability_overrides`. **Nie jest** fallbackiem dla
publikacji source-correct v3 i nie wolno go uruchamiać z tego requestu.
Prywatny katalog tagów jest przygotowany przy imporcie; test zmiany YAML
nie może udawać dynamicznego reloadu produkcji. Trwałe formaty pozostają v3.

## Security review: owner, scope i odpowiedzi

- `_authorized_owner_user_id` daje pierwszeństwo obecnemu Authorization;
  błędny bearer nie może skorzystać z poprawnego cookie jako fallbacku.
  Sesja wymaga zalogowanego użytkownika; bearer przechodzi
  `require_agent_scope` / `_authenticate_agent`.
- Odczyt publicznego stanu wymaga `battle:read`, deklaracja/resolve/transition
  `battle:act`, interrupt i pass `battle:interrupt`. To istniejące scope'y,
  bez dodawania wildcardów. `*` pozostaje istniejącą polityką, nie zaleceniem
  do wydawania tokenów. Źródło uprawnień to backend, nie przesłane owner ID.
- `_authenticate_agent` sprawdza hash tokenu, revoked/expiry i rolę agent
  powiązanego użytkownika; `owner_user_id` principal służy do filtrowania
  participantów `p1_user_id/p2_user_id`. `_caller_player` nie przyjmuje strony
  z payloadu; przy jednym ownerze obu stron wybiera aktualnie kontrolowaną
  stronę, przy dwóch ownerach zachowuje odrębne role/priorytet.
- `_get_participant_battle` filtruje uczestnika w SQL. Dla poprawnego requestu
  brakująca i cudza bitwa mają to samo 404 `battle_not_found`. Sprawdzanie X
  następuje po tej granicy; nie przenosić checkpoint/source lookup przed nią.
  Walidacja składni guardów może odrzucić request wcześniej, niezależnie od
  istnienia bitwy. Nie obiecywać identycznego błędu dla różnych złych składni.
- Publiczny state/delta nie zawiera pola dice/RNG. `_public_activation_mutation`
  serializuje state + eventy; błędy protokołu nie zwracają checkpointu,
  rzeczywistej sekwencji ani prywatnej przyczyny outcome. Body-blind audyt
  agenta zapisuje route/path/query (z istniejącą redakcją sekretów), nie body
  z payloadem efektu. Nie dopisywać do niego tokenów lub RNG.

| Przypadek | Oczekiwane istniejące zachowanie / gate przyszłych testów |
|---|---|
| Brak loginu, błędny/revoked/expired bearer, zła rola | 401 bez domenowej mutacji; brak fallbacku cookie przy Authorization. |
| Poprawny token bez wymaganego scope | 403; samo `battle:act` nie upoważnia do interrupt ani odwrotnie. |
| Brakująca/cudza bitwa, poprawny request | Te same 404 i envelope, bez ujawnienia checkpointu/katalogu tej bitwy. |
| Zły priorytet, obce źródło, brak natywnego `oznaczenie`, source==attacker, martwy/offboard source/actor/target, sojuszniczy target | Stabilne istniejące błędy; brak domenowego zapisu. Test obu ownerów i tego samego ownera. |
| Zły X/typ/extra field/niekanoniczny slug/za długi slug | Ścisły payload i odrzucenie; nie wybierać handlera przez dowolny import/nazwę funkcji. |
| Brak attack scope, v1/v2, zły attack/activation/window head | Istniejące `attack_scope_required`, upgrade/unsupported lub stale envelopes; bez reinterpretacji legacy. |
| Nieaktualny sequence/activation/window/attack, ponowiony zaakceptowany request | 409 zgodny z guardami; brak drugiego efektu lub drugiego zużycia limitu. Nie obiecywać semantyki idempotency-key. |
| 12″ / granica / nieco dalej, inny source-target niż attacker-target | Reużycie predykatu Oznaczenia; warunek Ostrożnego to osobny skan. Testować oba niezależnie. |
| Użycie nosiciela ponownie w tej rundzie, duplikat nadania, bound okna | Brak nowego batcha; zachowany limit źródła i brak podwójnego bonusu native/granted. |
| Błąd po losowaniu, flush eventów, zapisie checkpointu, serializacji lub commit | Rollback domeny, RNG i pełnego tailu; legalny retry ze spójnego headu równy pojedynczemu sukcesowi. |

Nie nazywać całego HTTP requestu „zero writes”: poprawna autoryzacja bearera
commituje wcześniej `last_used_at` i `AgentAuditLog` w `_authenticate_agent`.
Późniejszy rollback dotyczy domeny Battle/events/checkpoint, nie cofa tego
audytu autoryzacji. Jest to istniejący kontrakt, nie nowa luka publikacji.
W negatywnych testach porównywać osobno domenę, audyt i metadane tokenu.

## Atomowość, race i retry

Serwis jest transakcyjnie neutralny; nie robi własnego commit/rollback ani
nowego savepointu. Bezpośredni caller musi po wyjątku wycofać całą domenową
transakcję przed dalszą pracą. Router `_stage_activation_mutation` jest jej
właścicielem: stage → serializacja odpowiedzi → commit, wyjątek → rollback.
`save_events(expected_latest_sequence=...)` sprawdza bieżący max i ciągłość;
unikalność `(battle_id, sequence)` chroni wyścig także między sprawdzeniem a
INSERT. `save_checkpoint` wymaga zgodności z końcem logu. To optimistic
concurrency z ograniczeniami DB, nie obietnica braku wyścigów.

Po restarcie `load_latest_checkpoint` wymaga checkpointu state+RNG dokładnie
na końcu logu; nie naprawia luki automatycznym replayem starego checkpointu.
Niespójność ma pozostać błędem, bez częściowego wznowienia. Outcome używa
prywatnego klonu dice; deklaracja/pass/grant nie przesuwają wejściowego RNG,
resolve zwraca jego nowy obraz. Replay stosuje zapisane outcome eventy,
nie przelicza historycznych trafień według nowego kodu. Negatywne testy muszą
objąć błąd po częściowym użyciu prywatnego RNG i retry z tego samego headu.

Timeout klienta może wystąpić po udanym commicie. Nie ponawiać mutacji w ciemno
ani nie przyjmować, że timeout oznacza rollback. Odczyt stanu/delty i guardy
pozwalają rozpoznać, czy nastąpił postęp; ponowienie starego requestu ma być
odrzucone bez nowego zapisu. HttpClient wykonuje jedną próbę transportu, bez
ukrytego retry lub automatycznego passowania okna.

## Istniejące dowody i brakujące bramki

Na bazie audytu ponownie uruchomiono pięć istniejących testów (wyłącznie
izolowane bazy testowe): **5 passed, 1 dependency warning**, 5.85 s.

| Dowód | Co rzeczywiście pokrywa | Czego jeszcze nie dowodzi |
|---|---|---|
| `test_v3_service_attack_steps_keep_five_exact_selects_for_small_and_large_state` | Start/pass/declaration/close/resolve: dokładnie 5 SELECT w serwisie dla małego i większego state/inventory. | Publicznego sukcesu Oznaczenia z rzeczywistym bonusem. |
| `test_v3_attack_interrupt_durable_seam_uses_one_batch_and_preserves_rng` | Testowo otwarta allowlista `furia`, dokładny batch 3 eventów, 5 SELECT i RNG bez zmiany. | Test nadaje Furię podczas Shoot, więc sprawdza seam, **nie** dodatkowe trafienie Szarży. Nie traktować monkeypatcha jako publicznej gotowości. |
| `test_v3_full_request_select_lists_stay_at_six_session_seven_bearer` | Publiczny pass-only v3 flow: 6 SELECT sesji / 7 bearera, bez N+1 względem state. | Nie obejmuje zaakceptowanego publicznego X. |
| `test_v3_public_oznaczenie_is_fail_closed_without_oracle` | Pusty katalog, `unsupported_interrupt`, missing/foreign 404 i brak domenowych zapisów. | Pozytywnego requestu po zmianie katalogu. |
| `test_v3_resolve_failure_after_private_rng_use_is_retry_safe` | Awaria resolve po użyciu prywatnego RNG, domena/stream niezmienione i legalny retry. | Wszystkich punktów awarii na zaakceptowanym X. |

Dodatkowo odczytano testy strict guards, two-bearers priority/control,
HTTP one-POST/decode, caller rollback i ready handlers SQL ceilings w
`test_battle_activation_transport.py`, `test_battle_activations.py`,
`test_clients_http_activations.py` oraz auth w `test_agent_token_security.py`.
Są fundamentem przyszłej macierzy; nie deklarujemy ponownego uruchomienia
całych tych plików w dokumentacyjnym etapie.

Konkretny punkt startu negatywnych regresji (odczytane, nie wszystkie ponownie
uruchomione): `test_require_agent_scope_rejects_expired_or_revoked_tokens`,
`test_require_agent_scope_rejects_token_for_non_agent_user`,
`test_require_agent_scope_rejects_missing_scope_without_audit`,
`test_agent_scopes_wildcard_and_body_blind_audit`,
`test_v3_two_bearers_enforce_priority_and_control`,
`test_v3_attack_strict_guards_are_write_free`,
`test_interrupt_concurrent_head_change_reports_sequence_conflict_only`,
`test_interrupt_caller_rollback_removes_whole_staged_delta_and_checkpoint`
oraz `test_response_serialization_failure_rolls_back_events_and_checkpoint`.
Testy wspólnego transportu i legacy handlerów są gotowym fundamentem,
ale accepted-X potrzebuje odpowiedników po rzeczywistym udanym nadaniu:
cross-owner source, wrong-X/parametry, oba wyścigające się requesty, double
invoke, awaria w każdym punkcie zapisu, cleanup po kolejnym ataku i timeout
po commicie. Istniejący sztuczny stale-head test nie jest dowodem wykonania
dwóch jednoczesnych requestów zaakceptowanego X.

**Budżety publikacji, do potwierdzenia nowymi pozytywnymi regresjami:**
≤5 SELECT per durable mutation, ≤6 dla pełnego requestu sesyjnego i ≤7 dla
bearera przy istniejącym schemacie auth; identyczne listy dla małego/dużego
state i inventory. Katalog z pamięci, zero SQL/I/O w hooku X. Zliczać przez
`before_cursor_execute` wokół operacji; setup fixture i odczyt kontrolny poza
oknem pomiaru. Osobno liczyć SELECT, wszystkie statements oraz domenowe
wiersze po sukcesie/błędzie. Dzisiejsze dokładne 5/6/7 są pomiarem istniejących
powyższych testów; przeniesienie tych pułapów na accepted-X to wymaganie,
nie wykonany już pomiar. Pusty katalog może odrzucić wcześniej, więc jego
mniejszy koszt nie dowodzi kosztu publikacji.

## Proponowane małe etapy — wymagają osobnego wyboru

1. **HTTP/service Furia.** Pierwszy katalog wyłącznie `furia`, bez nowej
   ścieżki endpointu, scope lub schemy. Pliki: `battle_activations.py`, testy
   service/transport/engine; aktualizacja kontraktu katalogu. DoD: realny
   Charge v3 z nadaniem przez publiczny request, naturalna 6/brak 6, Kontra,
   Podwójny obu aliasów, native/granted/both, dwa ownership warianty, restart,
   replay, future RNG; cała negatywna macierz i SQL 5/6/7. Domyślne v1/v2 i
   publiczny Strażnik bez zmiany. Pełny pytest, simplify/review/security review.
2. **HTTP/service Ostrożny.** Po 1 rozszerzyć katalog o `ostrozny` bez
   globalnego `source_correct`. Pliki: gate katalogu i regresje combat /
   durable / HTTP / prediction. DoD: prawdziwe Shoot v3 z bonusem 0/+1,
   drugi bliski wróg, promienie i granica 12″, role/lifetime, native/granted,
   brak bonusu melee i brak zmiany Strażnika; ta sama macierz/RNG/SQL gates.
   Luki Planowania lub Niestrudzonego nie są ukrytym rozszerzeniem tego kroku.
3. **HttpClient: accepted-X flow.** Obecna metoda `interrupt` już przenosi
   dokładny payload; nowy endpoint lub retry nie jest potrzebny. Osobny mały
   krok testów/dokumentacji dla round-trip sukcesu obu X, błędów, reloadu i
   niepewnego wyniku transportu; `test_clients_http_activations.py` oraz
   integration transport. Jeden POST i brak follow-up GET w metodzie mutacji.
4. **MCP: najpierw kontrakt propozycji, jeśli wybrany.** Obecny
   `propose_battle_action` nie reprezentuje przerwania w oknie ataku.
   Zaprojektować typed consent-gated proposal oraz owner/scope i guardy;
   nie podłączać `HttpClient.interrupt` jako dowolnego bezpośredniego toola.
   Pliki przyszłego projektu: `mcp_server`, klient, agent proposals services /
   routers / types. Sam projekt wymaga wyboru; obecny plan niczego nie publikuje.
5. **UI: wybór z gotowego katalogu.** Po udowodnieniu backend/client flow
   osobny zakres widoku okna, priorytetu i właściwego nosiciela/celu, informacji
   o warunkach bonusu, stale/timeout/reload oraz potwierdzenia propozycji.
   Frontend nie oblicza legalności ani mechaniki X. Ewentualną projekcję
   supported-X zaprojektować z jednego backendowego SSOT, nie z pełnego YAML.
   Testy UI i smoke Zbrojownia/Edytor Armii/Rozpiski plus zmieniony flow,
   parity payload jeśli dotknięty; bez ukrytej zgody na autoplay.

Każdy przyszły krok ma osobny commit `Faza_A` potwierdzony na `origin/Faza_A`,
Layer Checklist i performance gate, oraz osobny wybór użytkownika przed
nadaniem automation-ready. W tym dokumencie nie nadano nowych markerów.
Nie są potrzebne nowe decyzje o regułach do zamknięcia przygotowania;
rzeczywista publikacja pozostaje niezatwierdzona. Następny zaakceptowany
etap bieżącej kolejki to **D6.1-audit**, nie implementacja powyższych kroków.

## Weryfikacja dokumentu i przekazanie

Przeprowadzono odczyt kodu/call sites, źródeł, testów i granic transakcji;
simplify/review/security review były ręcznymi odpowiednikami niedostępnych
slash commands. Rozróżniono realną mechanikę, tag, prywatny seam, istniejące
negatywne dowody i brakujące pozytywne gates. Nie zmieniono kodu/testów,
więc pełnego pytest nie ponawiano; 4025 passed po D5.3b to historyczna baza.
Własny diff i nowe linki zweryfikowano; `git diff --check` bez błędów.
Pełny skan linków wykazał zastany brak `plans/architektura-dlugofala.md`
w innej sekcji roadmapy; nie należy do tego etapu i nie został poprawiony.

Odtwarzalne komendy tego etapu (PowerShell, testy używają własnych baz):

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/rules_sources_check.py
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_battle_activations.py::test_v3_service_attack_steps_keep_five_exact_selects_for_small_and_large_state tests/test_battle_activations.py::test_v3_attack_interrupt_durable_seam_uses_one_batch_and_preserves_rng tests/test_battle_activation_transport.py::test_v3_full_request_select_lists_stay_at_six_session_seven_bearer tests/test_battle_activation_transport.py::test_v3_public_oznaczenie_is_fail_closed_without_oracle tests/test_battle_activation_transport.py::test_v3_resolve_failure_after_private_rng_use_is_retry_safe -x --tb=short -q
git diff --check
```

Dokument, wynik kolejki i odnośniki są wersjonowane. Przed zmianą komputera
pobrać `origin/Faza_A` i odtworzyć środowisko. Produkcyjna `data/szop.db` oraz
lokalne sekrety/konfiguracja wymagają osobnego backupu; nie zmieniono ich.
SHA256 DB: `AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Zastane historyczne pliki i hunk B6.2 w roadmapie nie należą do etapu.
