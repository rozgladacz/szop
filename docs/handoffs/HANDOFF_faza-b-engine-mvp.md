# HANDOFF — faza-b-engine-mvp

> **Wątek:** Strumień B — Game Engine MVP (parent). Bootstrap (B0 założenia + 4 ADR-y) + B3 (rule executor) + B3.9 (architecture hardening) → B2 (modele ORM) → B4 (API) → B5 (klient) → B6 (prezentacja) → B7 (test bed). Praca delegowana do sub-wątków (`faza-b-2-models`, `faza-b-3-executor`, `faza-b-3-hardening`, ...).
> **Status:** In progress — B0 ✅ + B3 ✅ + **B3.9 ✅** (sub-wątek `faza-b-3-hardening` ready for archive 2026-06-02, 6 faz B3.9.a-f, pytest 1337/1337, 13 ADR-ów Accepted). Następne: B2 ORM (event types stabilne — zero migration churn) + Strumień D (agenci-boty) równolegle, potem B4 API + B5 klient.
> **Utworzony:** 2026-05-30
> **Ostatnia aktualizacja:** 2026-06-26 (B2 Unit base geometry slice)

## Cel

Zbudować symulator pełnej bitwy 1v1 oparty o `SZOP_Rozjemca.md` (reguły) + `SZOP_Zdolnosci.md` (mechaniki 77 zdolności). Engine headless-first (czyste funkcje + event sourcing), prezentacja opcjonalna. Pareto MVP: oddział = koło, brak orientacji modeli, ruch deklarowany (bez pathfindingu), LoS standardowy. 6 zdolności wykluczonych z MVP (Pareto trade-off; zob. `app/rulesets/v1/b_mvp_exclusions.yaml`).

Plan długofalowy: [docs/roadmap.md#strumień-b](../roadmap.md). Strumień B odblokowany przez zamknięcie Strumienia A (YAML SSOT) i A4 (pipeline drift detection — `build/geometry_classification.md` jako informational input).

## W TRAKCIE — 2026-06-26T09:15:00+02:00 — B2 minimal auth/agent schema

**Zakres pracy:** addytywny slice B2 zgodny z decyzją usera z 2026-06-26:
dodać do ORM `User.role` oraz tabele `AgentToken` i `AgentAuditLog`. Ten slice
buduje fundament danych pod B4/C1 agent access, ale nie dodaje endpointów,
middleware `require_agent_scope`, generowania tokenów ani zmian w istniejącym
runtime auth poza domyślnym `role="admin"` dla konta admina.

**Wybór zadania:** B2/B4/C1 to następny główny kierunek parenta. Minimalny
auth/agent slice jest już rozstrzygnięty przez usera, nie wymaga interakcji,
mieści się w jednej sesji i jest bezpiecznie addytywny. C3 leaf-CLI mają niższy
priorytet według świeżych decyzji, a AIDEAS jest poza aplikacją.

**Warstwy (Layer Checklist):**
- Data model / migracja: `app/models.py`, `app/db.py`, testy schematu.
- Backend payload/API: N/A (bez routerów i bez zmian odpowiedzi JSON).
- JS render / CSS / template: N/A.
- Testy: regresje świeżego schematu i ręcznej migracji starej bazy SQLite,
  targeted pytest + pełny pytest.
- Dokumentacja: roadmap B2 + ten HANDOFF po sukcesie.

**Performance gate:** brak hot path `/quote` / `/rosters/{id}`. Nowe tabele
tworzy `Base.metadata.create_all`, a migracja starej tabeli `users` wykonuje
jedno `PRAGMA table_info(users)`, jedno addytywne `ALTER TABLE` i jednorazowy
`UPDATE` ról adminów tylko podczas startu/migracji SQLite. Runtime bez nowych
query w istniejących requestach.

**Plan:**
- [x] 1. Potwierdzić istniejące użycia `User.is_admin`, wzorzec migracji i testy DB.
- [x] 2. Wykonać encoding gate dla edytowanych `.py`, dodać ORM + migrację.
- [x] 3. Dodać testy regresyjne świeżego schematu i migracji starej tabeli `users`.
- [x] 4. Weryfikacja: targeted pytest, pełny `pytest -q`, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review`, manual `/security-review`,
  diff review; re-run pytest jeśli przegląd coś zmieni.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice. `LOCKED`: Dywersant,
raw combat rolls i post-MVP `models_mode=per_copy` nie są dotykane ani podnoszone.
`READY` dla przyszłego B4/C1 runtime: generować tylko bearer token jednorazowo,
persystować wyłącznie `token_hash`, porównywać hash i redagować sekrety z
`AgentAuditLog.params_json`.

**Wykonane kroki / odkrycia:**
- 2026-06-26T09:15:00+02:00: Start slice po bootstrapie automatyzacji. Working
  tree zawiera zastane zmiany docs (`HANDOFF.md`, roadmap, ten HANDOFF) z decyzjami
  usera 2026-06-26 oraz lokalną zmianę `.claude/settings.local.json`; nie są
  rewertowane. `rg` potwierdził, że aplikacja nadal używa `User.is_admin` w
  routerach, więc `role` zostaje addytywnym polem danych bez przepinania auth
  w tym slice.
- 2026-06-26T09:20: Encoding gate UTF-8 dla `app/models.py`, `app/db.py` i
  `tests/test_db_schema_migrations.py` zaliczony po eskalacji lokalnego `.venv`
  poza sandbox (`utf8-ok`; Store Python w sandboxie zwrócił `Odmowa dostępu`).
- 2026-06-26T09:24: Dodano `User.role` (`user`/`agent`/`admin` jako stałe modelu),
  `AgentToken` z `token_hash` (unikalny skrót zamiast raw tokena), `scope_json`,
  wygasaniem/cofnięciem/ostatnim użyciem oraz `AgentAuditLog` z route/params/timestamp.
  `_migrate_schema` dodaje `users.role` i mapuje istniejące `is_admin=1` na
  `role='admin'`; konto seedowane `admin` dostaje `role='admin'`.
- 2026-06-26T09:25: `tests/test_db_schema_migrations.py` rozszerzony o świeży
  schemat `agent_tokens`/`agent_audit_logs` oraz migrację starej tabeli `users`
  bez kolumny `role`.
- 2026-06-26T09:31: Targeted pytest `tests/test_db_schema_migrations.py`: **3 passed**.
  Rozszerzony targeted DB/auth
  `tests/test_db_schema_migrations.py tests/test_db_import_cycle.py tests/test_registration_control.py`:
  **24 passed** po cleanupie testowego `datetime.utcnow()`.
- 2026-06-26T09:35: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1937 passed**, 1725 warnings.
- 2026-06-26T09:38: Call-site check: `User.role`, `AgentToken`, `AgentAuditLog`,
  `token_hash` i `scope_json` występują tylko w modelach, migracji seedowanego
  admina, testach i docs. Istniejące routery nadal używają `User.is_admin`; brak
  zmian payload/API/JS. `_migrate_schema()` nadal wywoływany tylko z `init_db()`
  plus testy bezpośrednie.
- 2026-06-26T09:40: Zaktualizowano `docs/roadmap.md`, `docs/architecture.md` i
  ADR-0050, żeby status B2 nie mówił już, że `AgentToken`/`AgentAuditLog` są
  całkowicie odroczone. Endpointy/middleware tokenów pozostają C1/B4 i nie są
  częścią tego slice.
- 2026-06-26T09:45: DoD manualny zakończony. `/simplify`: brak dalszych zmian po
  cleanupie testowego `datetime.utcnow()`; model pozostaje lokalny i addytywny.
  `/review`: brak zmian istniejącej autoryzacji/payloadów, migracja idempotentna,
  FKs/indeksy na relacjach agent-owner i audit. `/security-review`: brak raw
  tokenów w schemacie (`token_hash`), brak endpointów/user-input→DB w tym slice,
  SQL migracji statyczny; future runtime musi redagować sekrety z `params_json`.
  `git diff --check` bez błędów (tylko standardowe ostrzeżenia CRLF dla docs).
- 2026-06-26T~09:50: **COMMIT** `b766060` na `Faza_A` (sesja autonomiczna domknęła
  zweryfikowaną, niezacommitowaną pracę slice). Re-weryfikacja w tej sesji: targeted
  `tests/test_db_schema_migrations.py tests/test_db_import_cycle.py
  tests/test_registration_control.py` **24 passed**; pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **1937 passed**,
  1725 warnings. Commit obejmuje 8 plików jednego slice (kod `app/models.py`/`app/db.py`,
  test `tests/test_db_schema_migrations.py`, docs `roadmap`/`architecture`/ADR-0050/oba
  HANDOFF). `.claude/settings.local.json` świadomie poza commitem (lokalna allowlista).

**Następne kroki:** slice gotowy. Następne B2/B4: endpointy tokenów i middleware
scope/audit albo `BattleInvite`/snapshoty jako osobny zakres.

## W TRAKCIE — 2026-06-26T01:02:05+02:00 — B2 Unit base geometry slice

**Zakres pracy:** maly addytywny slice B2: dodac do ORM `Unit` pola
`base_size_mm` i `base_shape` z domyslami `25` / `"round"` oraz reczna migracja
SQLite w `_migrate_schema`. Ten slice tylko przygotowuje model danych pod przyszla
geometrie podstawek; nie zmienia silnika bitwy, kosztow ani UI.

**Wybor zadania:** B2/B4 jest nastepnym glownym kierunkiem parenta. Auth/tokens/invite
sa wieksze i wymagaja osobnego security-review oraz decyzji zakresu, a pozostale C3
leaf-CLI sa oznaczone w `HANDOFF.md` jako wymagajace decyzji projektowej. Kolumny
`Unit` sa dobrze okreslone w roadmapie i mieszcza sie w jednej sesji.

**Warstwy (Layer Checklist):**
- Data model / migracja: `app/models.py`, `app/db.py`, test migracji.
- Backend payload/API: N/A (pola nie sa jeszcze eksponowane w routerach).
- JS render / CSS / template: N/A.
- Testy: targeted DB/model test + pelny pytest.
- Dokumentacja: ten HANDOFF; roadmap checkbox po sukcesie.

**Performance gate:** brak hot path `/quote` / `/rosters/{id}` i zero nowych query.
Migracja uzywa `PRAGMA table_info(units)` oraz maksymalnie dwoch `ALTER TABLE`
podczas startu, tylko gdy kolumn brakuje. Runtime aplikacji bez dodatkowych petli.

**Plan:**
- [x] 1. Potwierdzic aktualny model `Unit`, migracje `_migrate_schema` i testy DB.
- [x] 2. Wykonac encoding gate dla edytowanych `.py`, dodac pola ORM + migracje.
- [x] 3. Dodac test regresyjny dla domyslnych kolumn i migracji starej tabeli.
- [x] 4. Weryfikacja: targeted pytest, pelny `pytest -q`, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review` (data model), manual `/security-review`
  jesli zakres dotknie user input/DB beyond additive schema, diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice. `LOCKED`: Dywersant i
post-MVP `models_mode=per_copy` nie sa dotykane ani podnoszone.

**Wykonane kroki / odkrycia:**
- 2026-06-26T01:02:05+02:00: Start slice po bootstrapie automatyzacji. Working tree
  bez widocznych zmian w `git status --short` (poza ostrzezeniem o globalnym
  `C:\Users\mlis\.config\git\ignore` bez dostepu).
- 2026-06-26T01:08: Potwierdzono aktualny stan: `Unit` ma juz addytywne kolumny
  `position`, `typical_models`, `group_id`; `_migrate_schema` dopisuje brakujace
  kolumny `units` przez `ALTER TABLE`. Brak istniejacego testu dla `_migrate_schema`,
  wiec ten slice doda regresje na starej tabeli SQLite.
- 2026-06-26T01:09: Encoding gate UTF-8 dla `app/models.py` i `app/db.py` zaliczony
  po eskalacji lokalnego `.venv` poza sandbox (`utf8-ok`; Store Python w sandboxie
  zwrocil `Odmowa dostepu`, zgodnie z notatka w `docs/testing.md`).
- 2026-06-26T01:10: Dodano `Unit.base_size_mm` / `Unit.base_shape` z domyslami
  `25` / `"round"` oraz addytywne `ALTER TABLE` w `_migrate_schema`.
  `tests/test_db_schema_migrations.py` pinuje domysly na swiezym schemacie i
  migracje starej tabeli `units`.
- 2026-06-26T01:11: Targeted pytest `tests/test_db_schema_migrations.py`:
  **2 passed**, 5 warnings.
- 2026-06-26T01:12: Targeted DB/client pytest
  `tests/test_db_schema_migrations.py tests/test_db_import_cycle.py tests/test_clients_local.py tests/test_exploit_hunt_db.py`:
  **31 passed**, 371 warnings.
- 2026-06-26T01:13: Pelny pytest
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1932 passed**, 1722 warnings.
- 2026-06-26T01:14: Call-site check: `base_size_mm`/`base_shape` wystepuja tylko w
  modelu, migracji, nowym tescie i docs; pola nie sa jeszcze konsumowane przez
  payload/API/JS. `_migrate_schema()` wywolywany tylko z `init_db()`; nowy test
  bezposrednio pinuje addytywna migracje starej tabeli `units`. Wszystkie
  istniejace miejsca `Base.metadata.create_all` przeszly w pelnym pytest.
- 2026-06-26T01:14: Zaktualizowano `docs/roadmap.md` (B2 Unit checkbox `[x]`)
  oraz ADR-0050/HANDOFF, zeby nie zostawic stalego statusu "Unit columns
  odroczone". `rg` nie znajduje juz otwartych checkboxow/starych blokad dla
  `Unit.base_size_mm/base_shape`, tylko wpisy DONE.
- 2026-06-26T01:15: Manual `/simplify`: patch minimalny, bez nowej abstrakcji;
  testy rozdzielaja swiezy schemat od migracji starej tabeli. Manual `/review`
  (data model): zmiana addytywna, domysly zgodne z roadmapa, migracja idempotentna
  po sprawdzeniu `PRAGMA table_info`. Manual `/security-review`: N/A dla auth/user
  input/sekretow; DDL nie ujawnia danych i nie zmienia scopingu. `git diff --check`
  bez bledow, tylko istniejace ostrzezenia CRLF dla dotknietych docs.
- 2026-06-26T06:03:11+02:00: Rewalidacja automatyzacji po bootstrapie. Zakres bez
  zmian kodu: sprawdzic zastany slice `Unit.base_size_mm/base_shape`, przeczytac
  review, powtorzyc call-site check i uruchomic targeted + pelny pytest w tej sesji.
- 2026-06-26T06:05:39+02:00: Rewalidacja zakonczona. `tests/test_db_schema_migrations.py
  tests/test_db_import_cycle.py tests/test_clients_local.py tests/test_exploit_hunt_db.py`:
  **31 passed**, 371 warnings. Pelny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1932 passed**, 1722 warnings. Call-site check bez nowych konsumentow poza
  modelem/migracja/testem/docs. `git diff --check` bez bledow, tylko ostrzezenia
  CRLF dla dotknietych docs. Manual `/simplify` i `/review`: brak dodatkowych zmian;
  low backlog `base_shape` enum/walidacja zostaje do przyszlego slice API/UI.
- 2026-06-26T~06:30: **COMMIT** na `Faza_A` (sesja autonomiczna domknela
  zweryfikowana, niezacommitowana prace slice). Re-weryfikacja w tej sesji:
  targeted `tests/test_db_schema_migrations.py tests/test_db_import_cycle.py`
  **5 passed**; pelny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`
  **1932 passed**, 1722 warnings. Diff zgodny z `REVIEW_2026-06-26.md` (0 bugow
  korektnosci). Commit obejmuje 7 plikow jednego slice: kod (`app/models.py`,
  `app/db.py`), test (`tests/test_db_schema_migrations.py`) oraz docs slice
  (`docs/roadmap.md`, `docs/adr/0050-event-store-persistence.md`, ten HANDOFF,
  `REVIEW_2026-06-26.md`). Slice B2 "Unit base geometry" zamkniety.

**Nastepne kroki:** slice gotowy. Pozostale B2 elementy to auth/invite/tokens/
snapshot (`BattleInvite`, `AgentToken`, `AgentAuditLog`, `BattleSnapshot`) i powinny
isc jako osobny zakres z pelnym security-review. Brak decyzji usera wymaganej dla
tego slice.

## W TRAKCIE — 2026-06-25T21:04:50+02:00 — E4 final-position collision for Maneuver

**Zakres pracy:** mały slice z roadmapy E4: walidować końcową pozycję `ManeuverAction`
tak, żeby oddział w Pareto MVP (koło) kończył Manewr dalej niż 1″ od innych żywych
oddziałów na Froncie. Ten slice NIE implementuje pathfindingu ani ruchu przez teren
`Niedostępny`/`Trudny`.

**Źródło reguł odczytane w tej sesji:**
- `app/static/docs/SZOP_Rozjemca.md` pkt 2.d: modele są terenem `Niedostępny` i
  `Blokujący`.
- `app/static/docs/SZOP_Rozjemca.md` pkt 4.c.i: na terenie `Niedostępny` nie można
  się zatrzymać ani przez niego przemieszczać.
- `app/static/docs/SZOP_Rozjemca.md` pkt 14.a: Manewr wykonuje Ruch.
- `app/static/docs/SZOP_Rozjemca.md` pkt 15.b.iii: po ruchu modele muszą być dalej
  niż 1″ od modeli innych oddziałów.
- `app/static/docs/SZOP_Rozjemca.md` pkt 16.d: Związanie jest wyjątkiem dla celów
  Związania; dlatego ten slice dotyczy tylko `ManeuverAction`, nie `ChargeAction`.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload/API: publiczny resolver engine (`app/services/engine/resolver.py`)
  i helper pure-engine (`app/services/engine/movement.py`).
- JS render / CSS / template: N/A.
- Agenci: enumeracja/priorytety Manewru w `app/services/agents/*`, żeby boty nie
  generowały akcji, które resolver odrzuci.
- Testy: `tests/test_engine_move_validation.py`, `tests/test_agents_base.py`,
  `tests/test_agents_move_fidelity.py`.
- Dokumentacja: ten HANDOFF.

**Performance gate:** hot path engine/boty, ale bez DB i bez query. Dodatkowy koszt
to liniowe sprawdzenie `state.blobs` tylko dla `ManeuverAction`; brak indeksów potrzebnych
przy typowych małych rosterach MVP. Helper ma fast path po prostym loopie i pomija
pokonanych / poza Frontem.

**Plan:**
- [x] 1. Dodać wspólny helper clearance dla końcowej pozycji Manewru.
- [x] 2. Wpiąć walidację w `resolver._validate_action`.
- [x] 3. Przefiltrować manewry botów przez ten sam helper.
- [x] 4. Dodać regresje engine + agents i uruchomić targeted + pełny `pytest -q`.
- [x] 5. DoD: call-site check, manual `/simplify`, manual `/review` (hot path), diff review.

**Otwarte kwestie:** `READY`: pełne E4 pathfinding/teren `Trudny`/`Niedostępny` po trasie
zostaje poza tym slice. `LOCKED`: Dywersant pozostaje poza zakresem MVP i nie jest ruszany.

**Wykonane kroki / odkrycia:**
- 2026-06-25T21:18: Dodano `app/services/engine/movement.py` z helperem
  `maneuver_destination_blocker()` / `maneuver_destination_is_clear()`; model MVP
  interpretuje pkt 15.b.iii jako gap obwód-obwód między kołami oddziałów.
- 2026-06-25T21:18: `resolver._validate_action` odrzuca `ManeuverAction`, którego
  końcowa pozycja jest w odległości `<= 1″` od innego żywego oddziału na Froncie.
- 2026-06-25T21:18: Boty filtrują Manewr tym samym helperem w `legal_actions`,
  `PriorityPlayer`, `PriorityV2Player` i `PriorityV3Player`; `ChargeAction` bez zmian,
  bo pkt 16.d ma własny wyjątek dla celów Związania.
- 2026-06-25T21:26: Regresje dodane do `test_engine_move_validation`,
  `test_agents_base` i `test_agents_move_fidelity`. Targeted pytest po poprawce
  składni w `priority_v2_player.py`: **47 passed**.
- 2026-06-25T21:38: Pełny pytest ujawnił dwa stare scenariusze `PriorityPlayer`,
  w których fixture zakładała Manewr kończący się zbyt blisko innego oddziału.
  Poprawiono pozycje fixture, zachowując sens priorytetu. Targeted paczka
  `test_engine_move_validation.py test_agents_base.py test_agents_move_fidelity.py
  test_agents_priority.py`: **61 passed**.
- 2026-06-25T21:48: Analogiczne fixture w `PriorityV2Player` poprawione dla
  interceptu i kontynuacji po strzale. Rozszerzony targeted zestaw
  `test_engine_move_validation.py test_agents_base.py test_agents_move_fidelity.py
  test_agents_priority.py test_agents_priority_v2.py test_agents_priority_v3.py`:
  **85 passed**.
- 2026-06-25T21:58: Pełny pytest doszedł do `test_balance_simulate` i wykazał,
  że statystyczny test seed-offsetu (`fixed.draws < mirror_draws`) był zależny
  od fizyki ruchu. Zastąpiono go kontraktowym testem monkeypatch: `simulate_balance`
  przekazuje P0 seed `base+i`, P1 seed `base+i+PLAYER_SEED_OFFSET`. Targeted
  `tests/test_balance_simulate.py`: **26 passed**.
- 2026-06-25T22:08: Zmiana legalności Manewru świadomie zmieniła przebieg wszystkich
  6 B7 golden case. Dodano ADR-0052, zaktualizowano roadmap E4/ADR index i
  odświeżono `GOLDEN_CASES` przez `python tests/test_engine_regression.py`.
  Targeted `tests/test_engine_regression.py`: **14 passed**.
- 2026-06-25T22:15: Pełny pytest ujawnił jeszcze starą fixture w
  `tests/test_engine_resolver.py`, gdzie test dispatcher/sequence kończył Manewr
  za blisko własnego oddziału. Pozycje zmienione na ujemny X (sens testów bez zmian).
  Targeted `tests/test_engine_resolver.py`: **22 passed**.
- 2026-06-25T22:31: Final full pytest po docstring-only cleanup:
  **1925 passed, 1717 warnings** (`.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`).
- 2026-06-25T22:33: Call-site check:
  `maneuver_destination_blocker` używany przez resolver i wrapper `is_clear`;
  `maneuver_destination_is_clear` używany przez `agents.base._can_maneuver_to`;
  `_can_maneuver_to` używany w `legal_actions`, `PriorityPlayer`, `PriorityV2Player`,
  `PriorityV3Player`; wszystkie call sites `_move_to_objective` zaktualizowane do
  przekazywania `state`. Wpływ: tylko `ManeuverAction`, `ChargeAction` bez zmian.
- 2026-06-25T22:33: Manual `/simplify`: 1 cleanup docstringów w `resolver.py` i
  `agents/base.py`, logika bez zmian. Manual `/review` (hot path): brak findingów;
  helper jest współdzielony, koszt O(blobs) tylko dla Manewru, pomija pokonanych
  i poza Frontem. `/security-review` N/A (brak auth, DB, sekretów, user-input→DB).
  `git diff --check` bez błędów; tylko ostrzeżenia CRLF dla istniejących plików.
- 2026-06-25T23:12: **COMMIT** `65d09f9` na `Faza_A` (sesja autonomiczna domknęła
  niezacommitowaną pracę: re-weryfikacja pełnego pytest **1925 passed**, reguła
  pkt 15.b.iii potwierdzona ze źródła `SZOP_Rozjemca.md:118`). Slice E4
  "końcowa kolizja Manewru" zamknięty.

**Następne kroki:** `READY`: pełne E4 pathfinding/teren `Niedostępny`/`Trudny` po trasie
oraz kolizje dla innych trybów ruchu, jeśli wymagane. `LOCKED`: Dywersant pozostaje
poza zakresem MVP i nie jest pytaniem do usera.

## W TRAKCIE — 2026-06-23T21:01:17+02:00 — roadmap/ADR sync po leaderboard-cleanup

**Zakres pracy:** domknąć niespójność dokumentacji po zarchiwizowanym `faza-d-leaderboard-cleanup`: kod i `HANDOFF.md` wskazują, że `scripts/balance_common.py` + `registry.USEFUL_KINDS` są już wdrożone, ale `docs/roadmap.md` i ADR-0030 nadal opisują stary dług/default.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload: N/A.
- JS render / CSS / template: N/A.
- Dokumentacja: `docs/roadmap.md`, `docs/adr/0030-multi-agent-leaderboard.md`.
- Testy/weryfikacja: grep spójności, call-site/doc reference check, pytest fallback mimo doc-only.

**Performance gate:** brak hot path (`/quote`, `/rosters/{id}`), zero nowych DB queries, zero zmian runtime.

**Plan:**
- [x] 1. Potwierdzić kodowy stan `leaderboard.py`/`balance_common.py`/`registry.py` i znaleźć stale wpisy w docs.
- [x] 2. Zaktualizować roadmapę i ADR-0030 do stanu po cleanupie.
- [x] 3. Weryfikacja: grep spójności, pytest, manual `/simplify` + diff review. Pytest działa przez lokalną `.venv`, ale wymaga uruchomienia poza sandboxiem, bo Store Python bazowy jest blokowany błędem `Odmowa dostępu`.

**Otwarte kwestie:** brak `BLOCKED(user)`; Dywersant pozostaje `LOCKED` i nie jest dotykany.

**Wykonane kroki / odkrycia:**
- 2026-06-23T21:07: `scripts/leaderboard.py` już re-eksportuje `DEFAULT_PLAYERS = bc.DEFAULT_PLAYERS`, a `scripts/balance_common.py` ustawia `DEFAULT_PLAYERS = registry.USEFUL_KINDS`; `HANDOFF.md` ma wpis archiwalny `faza-d-leaderboard-cleanup`. Stale były tylko `docs/roadmap.md` i ADR-0030.
- 2026-06-23T21:10: `docs/roadmap.md` i `docs/adr/0030-multi-agent-leaderboard.md` zsynchronizowane: `balance_common.py`, default `useful`, `--players all` dla pełnego rankingu.
- 2026-06-23T21:16: grep spójności w dotkniętych docs nie znajduje już starych fraz (`Default boty = wszystkie`, `Dług techniczny`, `Plan domigracji`). `git diff --check` OK poza standardowymi ostrzeżeniami CRLF. Manual `/simplify`: zmiana zostaje doc-only; nie ma kodu do upraszczania, call-site code N/A. Manual `/review`: diff jest spójny z `scripts/README.md` i `HANDOFF.md`; brak `/security-review` (brak auth/user input/DB).
- 2026-06-23T21:45: po diagnozie runtime utworzono lokalną `.venv` w `szop_a` przez działający Store Python dostępny poza sandboxiem (`OPR\.venv\Scripts\python.exe -m venv .venv`), zainstalowano `requirements-dev.txt`, a następnie uruchomiono `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` poza sandboxiem. Wynik: **1884 passed**, 1573 warnings, 0 failed.

**Następne kroki:** dla kolejnych sesji Codex w tym sandboxie używać `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` z eskalacją poza sandbox, jeśli pojawi się `Odmowa dostępu` do `WindowsApps`/Store Pythona. Brak decyzji użytkownika wymaganej dla tego slice.

**Dopisek 2026-06-23T21:50 — testing.md runtime notes:**
- [x] Użytkownik poprosił o przeniesienie wniosków z diagnozy testów do `docs/testing.md`.
- Warstwy: dokumentacja/test workflow only; brak data model/backend payload/JS/CSS; performance gate N/A.
- Wykonano: `docs/testing.md` opisuje lokalną `.venv`, Store Python/WindowsApps, eskalację poza sandboxiem i zweryfikowaną komendę `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` (1884 passed). Weryfikacja po dopisku: `rg` nowych fraz + `git diff --check` OK poza standardowymi ostrzeżeniami CRLF.

**Pliki dotknięte w tym slice:**
- `docs/roadmap.md` — usunięty nieaktualny opis długu leaderboard-cleanup; dodany stan po cleanupie.
- `docs/adr/0030-multi-agent-leaderboard.md` — aktualizacja decyzji CLI/defaultów po cleanupie 2026-06-20.
- `docs/handoffs/HANDOFF_faza-b-engine-mvp.md` — bieżący zapis pracy automatyzacji.

## Zablokowane pliki / katalogi

**Sesja B0 (ta):**
- `app/rulesets/v1/tables.yaml` — dodajemy sekcję `b_mvp`
- `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — hand-curated 6 entries
- `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas
- `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()`
- `tests/test_b_mvp_config.py` (NEW) — exclusions + Pydantic walidacja
- `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- `docs/adr/0008-pareto-mvp.md` (NEW) — Status: Accepted
- `docs/adr/0010-event-sourced-battle-log.md` (NEW) — Status: Accepted
- `docs/adr/0010a-decision-freeze.md` (NEW) — Status: Accepted
- `docs/adr/0014-per-unit-wounds.md` (NEW) — Status: Accepted
- `docs/roadmap.md` — statusy B0 ✅ + ADR-y Accepted

**Sub-wątki B2+ (delegacja zakresów):**
- **`faza-b-3-executor`** ✅ **archived 2026-05-30** (B3.0-B3.8 done, 1244/1244 testów). LOG SESJI w HANDOFF.md.
- **`faza-b-3-hardening`** (NIE uruchomione — następna sesja) — refactor architektoniczny B3 przed startem B2/B4. 6 modułów + refaktorów + 3 nowe ADR-y (0045/0046/0047). Plik: `app/services/engine/{status,geometry}.py` (NEW), modyfikacje `state`/`combat`/`phases`/`effects`/`resolver`, nowe event types `StatusAdded`/`StatusRemoved` + pełne reducery, smoke replay parity test (`live_state == apply_events(initial, events)`). Powód: 7 bugów z code review (cumulative `wounds_received`, charger.radius ignored, silent status mutation, weapon inventory missing, constants drift) + brak `_ACTIVE_ABILITY_REGISTRY` blokuje skalowanie aktywnych zdolności.
- **`faza-b-2-models`** (NIE uruchomione — po B3.9 hardening) — `app/models.py` (Battle/BattleEvent/BattleInvite/BattleSnapshot/AgentToken/AgentAuditLog; `Unit.base_size_mm/base_shape` DONE 2026-06-26), ręczne migracje SQLite zamiast Alembic. **Decyzja:** B2 ORM zaprojektowane wokół ustabilizowanego engine (post-B3.9) żeby uniknąć migration churn przy refactor schema event-store.
- **`faza-b-4-api`** — `app/routers/battles.py` (NEW). Po B3.9 + faza-b-2-models.
- **`faza-b-5-client`** — `szop_client/` (NEW pakiet). Równolegle z B4.
- **`faza-b-7-test-bed`** — `tests/fixtures/battles/*.yaml` (NEW). Po B3.9.

**Read-only przez cały Strumień B (źródła prawdy):**
- `app/static/docs/SZOP_Rozjemca.md` — reguły gry (mechaniki)
- `app/static/docs/SZOP_Zdolnosci.md` — 77 zdolności (id, typ, opis, efekty, koszt, tagi)
- `app/static/docs/SZOP.docx`, `app/static/docs/SZOP.pdf` — rules-as-prose (SSOT dla tekstu reguł)
- `app/rulesets/v1/abilities.yaml` (88 entries) — target dla drift detection (A4 pipeline)
- `app/services/costs/` — Strumień A SSOT kosztów, B nie modyfikuje

## Blokuje / Blokowane przez

- **Blokuje:** Strumień C (MCP agent — wymaga publicznego API z B4), Strumień D (agenci-boty — wymagają engine z B3).
- **Blokowane przez:** nic — Strumień A pełen (A0+A1+A2+A3+A5+A4), `build/geometry_classification.md` jest informational.

## Gałąź git

- **Branch:** **`Faza_A` → main MERGED 2026-06-07** (PR #455, commit `418b0ff`). B2/B4/B5 sub-wątki startują na bazie `main`. Nowy branch `Faza_B` otwieramy przy starcie B2.
- **Base:** `main`

## Plan implementacji

### B0 — Pareto MVP założenia + 4 ADR-y (~1 sesja) — **DONE 2026-05-30**

**Decyzje wejściowe (z sesji 2026-05-28+2026-05-30):**

1. **SSOT split:** `SZOP_*.md` = SSOT dla engine; `SZOP.docx`/`SZOP.pdf` = SSOT dla rules-as-prose.
2. **Pareto MVP geometry:** oddział = koło. Podstawka modelu = 1 in² na punkt wytrzymałości. `radius_inches = sqrt(sum(toughness_modelu) / π)`. Bohater (id 2) liczy się jako `toughness/2`.
3. **Globalny ruch** `move_inches: 6"` z `SZOP_Rozjemca.md pkt 15.a`. Modyfikatory Szybki/Wolny (±2″) stosowane w runtime.
4. **Brak orientacji modeli** — pkt 25 SZOP_Rozjemca nieaktywowany. Jedyna zdolność wymagająca (Zwrot id 44) wykluczona.
5. **Brak pathfindingu** — ruch deklarowany przez gracza, weryfikowany jako legalny. Wymuszone ruchy: Szarża/Związanie (pkt 14.d.ii, 16) i Samolot (wykluczony).
6. **LoS standardowy** — linia z krawędzi atakującego do podstawki celu (pkt 6). Wyjątki LoS niestandardowego (Wysoki, Samolot) wykluczone.
7. **Tracking ran — 2 pule alokacji + dodatkowy licznik eliminating** (`SZOP_Rozjemca.md pkt 17.d–18 + 26.d`, user decision 2026-06-07 — KOREKTA wcześniejszego „3-pula" które było sprzeczne z pkt 17.d):
   - Pule alokacji per pkt 17.d **bez zmian**: `wounds_pending_precise` (pula atakującego, pkt 17.d.i) + `wounds_pending` (pula obrońcy, pkt 17.d.ii); znaczniki `wounds_received` (pkt 18.c); `melee_balance` (pkt 20.c).
   - **NOWE: `wounds_eliminating: int`** — dodatkowy licznik (NIE trzecia pula alokacji). Broń **Zguba** zadaje rany normalnie do precise/regular ORAZ zwiększa ten licznik o tę samą liczbę. Alokacja precise/regular zmniejsza licznik (eliminating nigdy nie alokowany samodzielnie). Model pokonany gdy licznik wciąż dodatni → **ELIMINOWANY** (pkt 26.d, nie wraca); inaczej WYCOFANY (pkt 26.c, wraca przez Leczenie pkt 21.c.ii). Reguła: „Zguba: Licz rany otrzymane tą bronią. Modele pokonane przez przydzielenie pierwszych ran do tej liczby nie mogą wrócić do gry."
   - **ADR-0014 refresh:** dodać pojedyncze pole-licznik `wounds_eliminating` (NIE restrukturyzacja na 3-pula). Szczegóły: `HANDOFF_faza-b-rules-resync.md` sekcja Decyzje 2026-06-07.

**Lista exclusions B0 (6 abilities — hand-curated, user decision 2026-05-30):**

| id | slug | name | uzasadnienie |
|---|---|---|---|
| 29 | samolot | Samolot | minimalny ruch 30-36″ w prostej linii + LoS niestandardowy |
| 37 | wrak | Wrak | pokonanie tworzy teren z 3 cechami |
| 38 | wysoki | Wysoki | LoS sprawdzane jakby z podwyższenia |
| 44 | zwrot | Zwrot | 4 strefy 180° (przód/tył/lewo/prawo) — wymaga orientacji |
| 73 | sterowany | Sterowany | 2 znaczniki broni z osobnym ruchem |
| 77 | zuzywalny | Zużywalny | raz na grę + max 1 broń tego typu per oddział |

**Rozbieżność z A4.3 result (`build/geometry_classification.md`):** A4.3 wygenerowało automatyczną listę 3 abilities (dywersant=false-positive, precyzyjny=per_model, zwrot=facing). Tylko `zwrot` jest wspólny. Powód:
- A4.3 to **heurystyka keyword match** — sklasyfikowała `dywersant` na podstawie keyword `strefy` (chodzi o strefy rozstawienia, false positive)
- A4.3 sklasyfikowała `precyzyjny` jako `per_model`, ale w MVP obsługujemy go przez `wounds_pending_precise` (ADR-0014) — atakujący wybiera deterministyczną kolejność pokonania modeli w heterogenicznym oddziale (np. Bohater vs zwykła postać)
- A4.3 nie obejmuje wykluczeń typu `terrain_generation` (Wrak), `session_state` (Zużywalny), `tokens_on_board` (Sterowany) — to są user decisions wykraczające poza geometric classification heuristyki

`b_mvp_exclusions.yaml` jest **hand-curated authoritative list** dla engine; `geometry_classification.md` zostaje jako informational artifact A4 pipeline.

**Kroki B0:**

- [x] B0.1: `app/rulesets/v1/tables.yaml` — dodaj sekcję `b_mvp` (move_inches=6, base_area_inches_sq_per_toughness=1, pi_approx)
- [x] B0.2: `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — 6 entries z {slug, reason, category}
- [x] B0.3: `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas; rozszerz `RulesetTables` o opcjonalne pole `b_mvp`
- [x] B0.4: `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()` z `@lru_cache`
- [x] B0.5: `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- [x] B0.6: `tests/test_b_mvp_config.py` (NEW) — 6 entries, slug set, sanity link do abilities.yaml
- [x] B0.7: ADR-0008 (Pareto MVP), ADR-0010 (event-sourced), ADR-0010a (decision freeze), ADR-0014 (per-unit wounds) — wszystkie Status: Accepted
- [x] B0.8: `docs/roadmap.md` — B0 ✅, ADR-y 0008/0010/0010a/0014 Accepted

> **Note (2026-05-30):** GATE pkt 3 ADR-0010a (audit akcji pkt 14 ↔ aktywne zdolności z SZOP_Zdolnosci.md) przesunięty z B0.W do **B3.0.1 preflight** w sub-wątku [HANDOFF_faza-b-3-executor](HANDOFF_faza-b-3-executor.md). Powód: B0 zamknięte deliverable-side, audit to pre-implementation requirement dla B3.

### B2 — Modele danych (4 tyg, sub-wątek `faza-b-2-models`) — **POST-B3.9**

Per `docs/roadmap.md#b2-modele-danych`. ORM (Battle, BattleEvent, BattleInvite, BattleSnapshot, AgentToken, AgentAuditLog; `Unit.base_size_mm/base_shape` DONE 2026-06-26) + persistence (`persistence.py`). Ręczne migracje SQLite zamiast Alembic. **Konsumuje ustabilizowany engine z B3.9** — `BattleEvent.payload_json` schema mapuje 1:1 na `events.py` event types (12 po B3.9: 10 oryginalnych + StatusAdded/StatusRemoved). Persisting + replay weryfikuje inwariant z ADR-0046.

ADR-0010 (event-sourced) + ADR-0014 (per-unit wounds) + ADR-0045 (activation context) + ADR-0046 (event-sourced mutations) + ADR-0047 (weapons inventory) dyktują strukturę. ADR-0042 (facing) odłożony do E3.

### B3 — Rule Executor + dice — **DONE 2026-05-30** (sub-wątek archived)

Sub-wątek `faza-b-3-executor` zarchiwizowany. 8 commitów B3.0-B3.8 na `Faza_A`. Pytest 1244/1244 (962 baseline + 282 nowych). 10 ADR-ów Accepted (0008/0010/0010a/0011/0012/0014/0015/0015a/0043/0044). Pakiet `app/services/engine/` ~2400 LOC, 12 modułów. Public API udokumentowane w ADR-0011. Smoke replay 2v2 przeszedł (21 events, 7 typów reprezentowanych). LOG SESJI w `HANDOFF.md`.

### B3.9 — Architecture hardening (~3-5 sesji, sub-wątek `faza-b-3-hardening`) — **READY TO START (user: 2026-06-19)**

**Cel:** rozstrzygnąć 5 dziur architektonicznych wykrytych w post-B3 code review zanim B2 ORM / B4 API zaczną konsumować engine. Stabilizacja API engine + naprawienie 7 bugów + 1 cleanup w jednym spójnym refactor zamiast rozsiać po przyszłych ticketach.

**5 dziur architektonicznych (z code review):**

| # | Dziura | Bugi które rozwiązuje |
|---|---|---|
| A | Brak rozróżnienia "trwały stan" vs "delta tej aktywacji" (`wounds_received` cumulative używany jako proxy dla pkt 20.a "w tej aktywacji"; `melee_balance` resetowany tylko na actorze; `initial_toughness` z bieżącego `models_alive`) | #1, #2, #3, #5 |
| B | Event sourcing nie exhaustive — `combat.py` mutuje `status_flags` przez `dataclass.replace` bez emit eventu; `apply_events(initial, events)` nie odtworzy `Wyczerpany` po kontrataku. ADR-0010 inwariant niezweryfikowalny. | #6 (silent Wyczerpany) + powiązane (deployment Aktywowany reset, defend status, round_end reset) |
| C | Brak weapon inventory na `UnitBlob` — counter używa broni atakującego (komentarz w kodzie sam to przyznaje) | #7 |
| D | Geometria + constants duplikowane: `_distance` 4× (los/phases/combat ×2 inline), `STATUS_*` 3× (effects/phases/combat). `circle_edge_distance` brak — stąd `charger.radius` ignored | #4, #8 |
| E | Brak registry dla aktywnych zdolności — `_apply_special` hardcoded `if slug == "discard_exhausted"`; nie skaluje na ~6 aktywnych z B3.0.1 audit (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik) | (architectural — blokuje przyrostowe dodawanie zdolności) |

**Kroki B3.9:**

- [ ] **B3.9.a — `app/services/engine/status.py` (NEW)** — kanoniczne `StatusFlag` enum (Aktywowany/Wyczerpany/Przyszpilony/Ufortyfikowany) + idempotentne helpery `add_status(blob, flag)` / `remove_status(blob, flag)`. Refactor `effects.py`/`phases.py`/`combat.py` żeby importowały zamiast duplikować. Fix #8 (drift risk).
- [ ] **B3.9.b — `app/services/engine/geometry.py` (NEW)** — `distance(p1, p2)` przez `math.hypot`, `point_in_circle`, `segment_intersects_circle`, `segments_intersect`, **`circle_edge_distance(c1_pos, c1_r, c2_pos, c2_r)`** (rozwiązuje #4 — używane w `resolve_charge_attack` dla `min_gap = defender.radius + charger.radius + 1.0`), `UNIT_CIRCLE_16` precomputed (perf). Refactor `los.py`/`phases.py`/`combat.py`. Fix #4 + perf.
- [ ] **B3.9.c — ActivationContext + initial_toughness snapshot.** Dodać `ActivationContext` frozen dataclass (`actor_id`, `wounds_received_this_activation: dict[int, int]`, `melee_combatants: frozenset[int]`). `BattleState.initial_toughness_snapshot: dict[int, int]` ustalony w `setup_phase` raz, nigdy nie modyfikowany. `activation_phase` buduje ActivationContext, `_regroup_test` używa kontekstu zamiast cumulative `wounds_received`. Defender of charge ma wpis w `wounds_received_this_activation` → regroup test w aktywacji atakującego. Fix #1, #2, #3, #5. **ADR-0045** (NEW Accepted).
- [ ] **B3.9.d — Event-sourced state mutations.** Dodać event types `StatusAdded(target_id, status)` + `StatusRemoved(target_id, status)` w `events.py`. Refaktor `combat.resolve_charge_attack` żeby emit'ował `StatusAdded(target_id=B, status="Wyczerpany")` zamiast `replace(status_flags=...)`. Analogicznie `_apply_defend` (Ufortyfikowany), `round_end_phase` (reset Aktywowany emit `StatusRemoved`). Implementacja reducer-ów dla wszystkich 10 event types w `state.apply_events`. **Test inwariant:** smoke replay 2v2 z `live_state == apply_events(initial_state, all_events)`. Fix #6. **ADR-0046** (NEW Accepted).
- [ ] **B3.9.e — UnitBlob weapons inventory + ACTIVE_ABILITY_REGISTRY.** Rozszerz `UnitBlob` o `melee_weapons: tuple[WeaponProfile, ...]` + `ranged_weapons`. `resolve_charge_attack` używa `defender.melee_weapons[0]` (lub fallback). `build_initial_state` czyta `unit.weapons` z roster. Plus `_ACTIVE_ABILITY_REGISTRY` w `effects.py`: `@register_active_ability("latanie") def handler(state, blob, payload) → (state, events)`. `phases._apply_special` deleguje do registry. Implementacje stub dla 6 aktywnych zdolności (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik). Fix #7 + dziura E. **ADR-0047** (NEW Accepted).
- [ ] **B3.9.f — Dead code cleanup + dokumentacja.** Usuń dead loop `combat.py:378-380`, function-local `_MoveExecuted` import. Update `docs/architecture.md` sekcja "Game engine" z nową strukturą (status.py, geometry.py, ActivationContext, weapons inventory). Update ADR-0011 (Accepted) z nowymi modułami w "Public API". Update `scripts/engine_smoke_replay.py` żeby weryfikował replay invariant (`assert apply_events(...) == final_state`).
- [ ] **B3.9.W — weryfikacja:** pytest pełna suite (1244 + nowe testy ~50-80); parity gate Strumień A niezmieniony; drift gate CLEAN; smoke replay z replay invariant. Cel: 1300+ testów; **GATE: smoke replay invariant test musi pass jako proof-of-completeness ADR-0010**.

**Decyzja kolejności (B3.9 before B2):** ORM `BattleEvent.payload_json` schema musi pokrywać wszystkie event types z `events.py` (już 10 → po B3.9 ~12). Stabilizacja event types + reducery PRZED ORM eliminuje migration churn (każda zmiana event type po B2 = Alembic migration).

### B4 — API (3 tyg, sub-wątek `faza-b-4-api`)

`app/routers/battles.py` — 9 endpointów (invite/accept/create/get/events/actions/interrupts/simulate/replay). Pydantic schemas, optimistic locking na sequence.

### B5 — Klient gry `szop_client` (równolegle z B4)

Pakiet `szop_client/` z `Protocol GameClient` + `HttpClient` + `LocalClient` (in-process). ADR-0016.

### B6 — Prezentacja (opcjonalne, 3-4 tyg)

CLI replay, SSE stream, canvas frontend. ADR-0013.

### B7 — Test bed (2 tyg)

Golden battles `tests/fixtures/battles/*.yaml` + `tests/test_engine_regression.py`.

## Pliki dotknięte

*(wypełni się w trakcie B0)*

## Pytania użytkownika i odpowiedzi (2026-06-19)

- **B3.9 readiness:** User: „Jak reszta wymagań gotowa, to można realizować". Interpretacja: B3.9 startuje gdy brak blokerów wejściowych (wszystkie są OK). **Status: ✅ READY TO START** — sub-wątek `faza-b-3-hardening` może być otworzony w następnej sesji.

## Hipotezy / pytania otwarte

- **H1:** ✅ **RESOLVED (2026-06-14).** Wzór `radius = sqrt(sum(toughness)/π)` wystarczający na tym etapie. Dokładniejsza weryfikacja będzie wartościowa po dodaniu kolizji, a następnie poszczególnych modeli. Aktualnie przyjmujemy sanity check (oddział 5 modeli toughness 3 → radius ≈ 2.19″).

- **H2:** ✅ **RESOLVED (2026-06-14).** Zostajemy przy `wounds_pending_precise`. MVP assumption: każdy model ma 1 broń wręcz + 0–1 dystansową. Zniszczenie przez rany zwykłe → usuwamy najtańszą broń wręcz i najtańszą dystansową. Zniszczenie precyzyjnymi → najdroższą wręcz i najdroższą dystansową. Dalszy rozwój po implementacji modeli indywidualnych.

- **H3:** ✅ **RESOLVED + IMPLEMENTED (2026-06-14).** Pole `UnitBlob.melee_balance` → `damage_balance` (do sprawdzania czy w ogóle trzeba testów przegrupowania + potencjalnie dla nowych zdolności na przyszłość). **Zaimplementowane (sesja autonomiczna):** rename pola stanu + wewnętrzne nazwy Pythona (reducer/testy) w `state.py`/`combat.py`/`phases.py`/`reducers.py`/`effects.py` + testy + `scripts/engine_smoke_replay.py` + docs (architecture/roadmap/ADR-0014/0045/0046/0047/0048). **Scoping (świadome):** event `MeleeBalanceReset` i jego tag JSON ZACHOWANE — tag = `type(event).__name__` (events.py:392), część zamrożonej schemy `payload_json` (ORM B2) + golden digestów B7; rename eventu = osobna świadoma zmiana schemy (ADR + regen digestów). Pole nie występuje w żadnym payloadzie eventu → zero wpływu na serializację/replay. Weryfikacja: pytest **1641 passed** (bez zmian baseline; B7 golden zielone = digesty identyczne), smoke replay invariant OK (48 events, replayed == live).

## Jak zweryfikować

```powershell
# Po B0
python -m pytest tests/test_b_mvp_config.py tests/test_b_mvp_tables.py -v
python -m pytest -q  # full suite — baseline 938 + ~6-8 nowych z B0

# Parity gate (nie powinno się zepsuć — B0 nie ruszało cost path)
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml_backend/

# Smoke
cat app/rulesets/v1/b_mvp_exclusions.yaml  # 6 wpisów
python -c "from app.services.rulesets.loader import load_b_mvp_exclusions; print(load_b_mvp_exclusions())"
```

## Decyzje

- 2026-05-30: Slug `faza-b-engine-mvp` (krótszy, jednoznaczny). Alternatywy odrzucone: `faza-b` (zbyt ogólne), `faza-b-symulator` (PL, niespójne).
- 2026-05-30: Branch `Faza_A` (kontynuujemy do scalenia z main). Decyzja per user wcześniej.
- 2026-05-30: Lista exclusions B0 = 6 entries (samolot/wrak/wysoki/zwrot/sterowany/zuzywalny) hand-curated. A4.3 result (`build/geometry_classification.md`) informational only.
- 2026-05-30: `precyzyjny` (id 68) NIE wykluczony z MVP — obsłużymy przez `wounds_pending_precise` + atakujący wybiera index pokonania. Wbrew sugestii A4.3 (per_model).
- 2026-05-30: `b_mvp_exclusions.yaml` jako osobny plik (separation of concerns od `abilities.yaml`); engine ładuje przez `load_b_mvp_exclusions()` z lru_cache.

## Notatki / odkrycia w trakcie

- **2026-06-14 — ✅ B5 LocalClient slice DONE** (wątek `faza-b-5-client`, archived, ADR-0016): pakiet `szop_client/` — `GameClient` Protocol + `LocalClient` in-process (single-step play + batch `simulate`) na ścieżce engine-dict. Reuse publicznego API silnika (ADR-0011) + runnera (ADR-0032), zero zmian w rdzeniu. pytest **1641 passed** (+13). **Odblokowuje C3 `simulate_engagement`.** Commity `8f10572`+`0b4d029`. **Odłożone do przyszłych wątków:** `HttpClient`+parity (gated na B4 API), DB-backed `LocalClient(db_session, user_id)` (gated na `faza-d-roster-adapter` niżej), pakowanie `pip install -e`.
- **`faza-d-roster-adapter` — URUCHOMIONY, slice 1+2a DONE 2026-06-16** (commity `6d44b65`+`8c76936`; wątek aktywny dla slice 2b). `app/services/agents/roster_adapter.py`: `roster_to_engine_roster` (Roster→engine-dict, reuse SSOT range/ability/loadout, filtr `b_mvp_exclusions`, `models_mode` per_copy/aggregate) + `roster_points` (metryka D3, reuse `costs.roster_unit_cost`). **D3 ma oba inputy metryki win_rate/points.** `models_mode` default `per_copy` — **PYTANIE DO USERA** (oddziały aktywują się niezależnie, pkt 8.a/11 — potwierdzone źródłem): potwierdzić jako kanoniczny. **Pozostała blokada D3 = B2 auth** (konto `agent_kind` + generator rozpisek). **Slice 2b (follow-up, decyzje):** `extra_weapons_json` override (loadout rozpiski), attached heroes merge (`parent_roster_unit_id`, ambiguity modelowania), auto-deploy integracja z D5. Szczegóły: `HANDOFF_faza-d-roster-adapter.md`. Oryginalne scoping-wymagania niżej (zachowane dla kontekstu):
  - `Roster` → `RosterUnit` (`count`, `extra_weapons_json`, `parent_roster_unit_id` = attached heroes) → `Unit` (`quality`/`defense`/`toughness`/`typical_models`/`flags`, `abilities: List[UnitAbility]`, `weapon_links: List[UnitWeapon]→Weapon`).
  - **`Weapon.range` to STRING** (np. `24"`, `Walka wręcz`) — parser do `range_inches: int`. `Weapon.attacks: float`, `Weapon.ap: int`, `Weapon.tags: str` (→ weapon_abilities). Dziedziczenie po `parent` (effective_* properties).
  - **Mapowanie zdolności:** `UnitAbility` (slug + `ability_value`) → engine `passives`. Odfiltruj `b_mvp_exclusions` (inaczej `build_initial_state` rzuca `UnsupportedAbilityError`) + zignoruj `INCOMPLETE_ABILITIES` (engine cicho pomija). Adapter DROPuje wykluczone/niekompletne i raportuje (symulacja na podzbiorze MVP).
  - **`models_alive` semantyka — DO ROZSTRZYGNIĘCIA:** `RosterUnit.count` (liczba kopii oddziału) vs `Unit.typical_models` (rozmiar oddziału). Kandydat: `count` blobów po `typical_models` modeli, lub 1 blob × (count×typical_models). (Możliwy punkt decyzji usera.)
  - **Koszt (metryka D3):** `calculate_roster_unit_quote(unit, loadout, count, include_item_costs)` (`app/services/costs/quote.py`, SSOT Strumień A) — gotowe, adapter tylko wywołuje.
  - **Auto-rozstawienie:** pozycje w strefie rozstawienia (pkt 3) — grid równomierny (pokrywa się z D5).
  - Klasyfikacja: NIE blokada usera (czysta inżynieria), ale ≥1 osobny wątek przez głębokość + decyzje modelowania.
- **2026-06-13 — ✅ B7 (Test bed) DONE** (wątek `faza-b-7-test-bed`, archived): `tests/test_engine_regression.py` — 14 testów golden regression (6 deterministycznych bitew + digest sha256 + reproducible + sanity). Reuse fixtur D2 + `balance_simulate`, zero zmian w rdzeniu. Roadmap B7 ✅. Commit `a700b74`. **Strumień B: zostają B2-reszta (auth/invite/tokens/snapshot; `Unit.base_size_mm/base_shape` DONE 2026-06-26), B4 API, B5 klient, B6 prezentacja.**
- **2026-06-13 — `WAITING(prereq)`: D3 `exploit_hunt` zablokowane na adapterze kosztu, nie na decyzji usera.** D3 (roadmap) ma raportować exploity wg „**win_rate / points**". Silnik engine-dict NIE ma kosztu punktowego (`UnitBlob` nie zna pkt; potwierdzone w `priority_player`/D2). Metryka „top wg samego win-rate" znajduje najsilniejszą armię, **nie exploit** (przewagę względem kosztu) → rdzeń wartości D3 wymaga mostu **ORM `Roster`→engine-dict** który liczy koszt przez `calculate_roster_unit_quote` (Strumień A SSOT) ORAZ auto-rozstawia pozycje w strefach (pkt 3) + mapuje abilities→passives (podzbiór MVP) + weapons z `loadout_json`. Ten sam adapter odblokowuje odłożony D2 breakdown per-zdolność/broń. **To NIE blokada usera** (czysta robota inżynierska, READY do zaprojektowania), ale nietrywialna (czyta DB, decyzje mapowania zdolności) — kandydat na własny wątek `faza-d-roster-adapter` przed D3. Do tego czasu D3 świadomie niezrobione.
- **2026-06-12 — ✅ ROZWIĄZANE: pkt 20.f.i — 1 porażka Przegrupowania = Przyszpilony deterministycznie.** Zmiana zasad (decyzja usera 2026-06-12): opcja (A) źródło-as-written. Usunięto mechanizm `regroup_choice` callback ze wszystkich warstw (phases/resolver/match/base/priority_v3). `source_hashes.yaml` zaktualizowany (`SZOP_Rozjemca.md` hash `99f5cd…`). Pliki: `phases.py`, `resolver.py`, `match.py`, `agents/{base,priority_v3_player}.py`, `tests/test_engine_regroup_choice.py` (przepisany — 2 testy deterministyczne), `tests/test_agents_priority_v3.py` (usunięty `test_regroup_choice_tree`), `source_hashes.yaml`. pytest **1607 passed** (0 failed).
- **2026-06-12 — ✅ ROZWIĄZANE: F5 — greedy niedoszacowywał ataków przejmujących cel (zaokrąglenie do 0).** `greedy_player._attack_score`: `round(expected_models_killed())` → `math.ceil` + ważenie delty (`weight = expected_kills / ceil`). Atak zdejmujący ostatni model z celu (E<0.5) teraz daje proporcjonalną `objective_delta` zamiast 0. Nowy test `test_attack_score_nonzero_for_low_expected_kills_on_objective`. pytest 1607 passed.
- **2026-06-12 — ✅ ROZWIĄZANE (wątki `faza-d-melee-target-cover` + `faza-d-greedy-melee-cover`): skażenie scoringu celu Szarży osłoną (pkt 19).** Wszystkie 3 boty używające `expected_damage` (PriorityV2/V3/Greedy) scorowały cele Szarży z `state.terrain` → osłona (pkt 19, ranged-only) zaniżała wagę/score celów melee za zasłoną wbrew silnikowi (`resolve_melee_attack`/`resolve_charge_attack` nie liczy `compute_cover`). Fix: scoring Szarży przekazuje pusty teren. Commity `8a8154d`/`93e872d`. pytest 1608.
- **✅ ROZWIĄZANE 2026-06-11 (sesja autonomiczna) — DRIFT pkt 20.e (Nieustraszony) NAPRAWIONY.** `phases._regroup_test` ma teraz binarny skip pkt 20.e: `"nieustraszony" in effective_passives(blob) and current > initial/2 → return (0 testów)`, sprawdzany przed rzutami. Usunięto stary morale-modifier `_nieustraszony_morale` (−1) ORAZ cały obsoletny mechanizm `aggregate_morale_modifier`/`register_morale_modifier`/`_MORALE_MODIFIERS`/`MoraleModifierFn` (pkt 20 nie ma już addytywnych morale modifiers po R5.c+20.e). `effective_passives` honoruje override'y Rozkaz/Klątwa. Zgodne z **ADR-0048** (który już dokumentował „Nieustraszony nie testuje gdy >50%"). Pliki: `app/services/engine/{effects,phases}.py`, `tests/test_engine_{effects,phases,order_abilities}.py`, ADR-0011 (Public API −morale), ADR-0049 (przykład zaktualizowany). Weryfikacja: pytest **1605 passed**, both_assert **156/156**, smoke replay **EXIT 0** (MoraleTestPassed nadal emitowany, replay bit-perfect).

- **2026-06-10 — ✅ ROZWIĄZANE (wątek `faza-b-multi-action`, ADR-0051): aktywacja wieloakcyjna.** `resolver.apply_activation` realizuje pętlę do 2 akcji (pkt 11.b.iv; Manewr liczy się; Ostrzał/Szarża raz), `phases` rozdzielone (`_begin`/`_apply_single`/`_finalize`), boty napędzają przez `Player.continue_activation`. `apply` (1 akcja) zostaje dla B4. Postęp lokalny → zero zmian schematu/replay (1558 testów, smoke EXIT 0). Balans bardziej rozstrzygający; ujawnił słabość heurystyk (boty nie trzymają celów — follow-up D). Oryginalny opis luki poniżej (kontekst).
- **2026-06-10 — LUKA MVP: aktywacja = 1 akcja zamiast 2 (pkt 11.b.iv).** Wykryte przy ocenie botów (wątek `faza-d-priority-player`, pytanie usera). **Reguły (źródło, pkt cytowane):** aktywacja to **do 2 akcji** (pkt 11.b.iv) — Manewr NIE liczy się do limitu i jest powtarzalny; 2. liczona akcja musi być różna od 1. (znoszone przez Niestrudzony/Manewr); Ostrzał raz (pkt 14.c.v), Szarża raz (pkt 14.d.vi); Przegrupowanie po KAŻDEJ akcji (pkt 11.b.iii). **Stan silnika:** `phases.activation_phase` docstring „MVP scope: pojedyncza akcja"; `resolver.apply` → 1 akcja → Aktywowany; `match.py` 1 apply/oddział/rundę; boty zwracają 1 akcję. → **Manewr→Ostrzał (dojdź i strzel) niemożliwe**, Manewr zużywa aktywację (wbrew pkt 11.b.iv). **Wpływ:** zaniża realizm balansu bardziej niż liczba celów — Strzelcy nie repozycjonują się przed strzałem. **Status `READY` (mechanika spec'owana pkt 11):** pętla 2-akcji w `resolver`/`activation_phase` (Manewr free + akcja≠poprzednia + raz-strzał/szarża + Przegrupowanie/akcję) + warstwa botów wybiera sekwencję do 2 akcji + `match.py` pętla per-oddział. **DECYZJA USERA (2026-06-14):** 2 akcje na aktywację są KONIECZNE do zaimplementowania. Powinno to już być zrobione. (Follow-up: fixtury 4 typów — PO mechanice 2-akcji.)

- **2026-06-14 — ✅ 2-AKCJE NA AKTYWACJĘ POTWIERDZONE ZROBIONE.** `apply_activation()` (resolver.py:210) implementuje pętlę do 2 akcji (pkt 11.b.iv) z `continuation` callback w `match.py:135-143`. Każdy `Player` podaje 2. akcję przez `continue_activation()`. Weryfikacja: pytest (boty używają, regroup+switch pracują). Zamyka pytanie z 2026-06-10.

- **2026-06-10 — B2 event-store slice DONE** (wątek `faza-b-2-event-store`, ADR-0050). Persystencja: nowe tabele `battles`/`battle_events` (`app/models.py`) + `app/services/engine/persistence.py` (`save_events`/`load_events`). **GATE replay-from-DB invariant** zielony — schemat eventów (16 typów) persystuje i odtwarza bit-perfect. **B4 API odblokowane** (konsumuje persistence + optimistic locking via `UniqueConstraint(battle_id, sequence)`). **Brak Alembic** w projekcie — nowe tabele addytywne via `create_all`; zmiany kolumn istniejących tabel wymagają wpisu w `_migrate_schema` (db.py). **Odroczone z B2** (osobny wątek + user + security-review): `BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog`; kolumny `Unit.base_size_mm/base_shape` domknięte 2026-06-26. Serializer `event_to_json`/`json_to_event` JUŻ istniał w `events.py` (B2 deliverable zrobiony wcześniej). pytest 1504.
- **2026-06-10 — Headless pętla bitwy DONE** (wątek `faza-d-match-runner`, ADR-0032). `app/services/agents/match.py`: `run_match(state, players, dice)` + `simulate_from_rosters(...)` → `MatchResult`. Domyka „pętlę bitwy" wskazaną poniżej jako brakującą po D1 — orkiestrator `apply`+`round_end_phase`+alternacja inicjatywy (pkt 8), headless (ADR-0013), zero zmian w rdzeniu. **D2 `balance_simulate` jest teraz READY** (agreguje N `simulate_from_rosters`). To zalążek B5 `LocalClient.simulate`. pytest 1494/1494. (Uwaga: rezerwy Zaplecze nie są rozstawiane mid-game w MVP — siedzą bezczynnie; pełne rozstawianie rezerw odłożone.)
- **2026-06-09 (sesja codzienna autonomiczna) — Strumień D1 MVP DONE** (wątek `faza-d-heuristic-players`, ADR-0031). Nowy pakiet `app/services/agents/` (Player ABC + `legal_actions` enumerator + RandomPlayer + GreedyPlayer + `evaluate_state`), czyta tylko publiczne API silnika (zero zmian w rdzeniu → brak kolizji z `faza-b-order-interrupts`). 26 testów, pytest 1489/1489. **Odblokowuje D2/D3, ale `balance_simulate` (D2) wymaga pętli bitwy** = orkiestrator `apply`+`round_end_phase`+alternacja inicjatywy → to **B5 LocalClient / B4 routers** (`READY` po B2 ORM). Boty są kompletne i testowalne w izolacji; brakuje tylko warstwy, która je uruchamia w pełnej grze. To kolejny naturalny krok parenta (obok B2 ORM).
- **2026-06-09 (sesja codzienna autonomiczna) — wątek `faza-b-rules-resync` ZARCHIWIZOWANY (R0–R7 + RW ✅).** Resync 3 warstw SSOT z driftem 2026-06-03 kompletny i zweryfikowany (pytest 1435/1435, both_assert 156/156, yaml 93/93, drift WARN, smoke EXIT 0). Pełny rekord driftu: **ADR-0048**. **Przejęte do tego parenta jako backlog przyrostowych zdolności engine:**
  - **[MVP DONE 2026-06-09 — wątek `faza-b-order-interrupts`, ADR-0049] Klątwa(X) / Rozkaz(X) / Oznaczenie(X)** (id 45/49/50). Zaimplementowane: substrat `ability_overrides` + `effective_passives`, handlery interrupt `BEFORE_ACTION` (zasięg 12″, ally/enemy, `rozkaz_tak`, raz-na-rundę), wygaśnięcie na końcu aktywacji, 28 testów. **Pozostaje (follow-up):** Oznaczenie precyzyjny trigger ataku + auto-orkiestracja przerwań w pętli aktywacji (H2/B4). Spec poniżej zachowany dla kontekstu. **NIE jest zablokowane decyzją** — to czysta robota engine. **Policy (user 2026-06-09):** przerwanie wyzwalane **przed akcją** — w regułach to JEDEN krok „Rozpatrujemy przerwania" (pkt 11.b.i), odwiedzany na początku każdej iteracji pętli akcji (pkt 11.b.iv→i), więc w praktyce **dwa okna przed-akcyjne** (przed akcją #1 i #2). Raz na rundę; efekt (nadanie/odebranie X) działa **do końca aktywacji**; X = dowolna pasywka z `rozkaz_tak: true` (SZOP_Zdolnosci.md #45/49/50). Cost-side + `rozkaz_tak` field done. **✅ DRIFT ADR-0015 NAPRAWIONY (2026-06-09):** enum `InterruptPoint` zredukowany do `BEFORE_ACTION` (pkt 11.b.i; ≤2 okna/aktywację via pętla 11.b.iv→i). Usunięto ACTIVATION_START/AFTER_ACTION/BEFORE_REGROUP/AFTER_REGROUP (drift — brak oparcia w pkt 11/12). ADR-0015 skorygowany (sekcja Korekta), `interrupts.py`/`events.py`/testy/ADR-0011/roadmap zsynchronizowane. **Pozostała robota engine (osobno):** mechanizm czasowego nadania/odebrania pasywki + limit `used_interrupts_this_round` + podpięcie `BEFORE_ACTION` do `phases.activation_phase` + 3 handlery. **Brakująca mechanika engine (do zbudowania):** (1) czasowe nadanie/odebranie pasywki na `UnitBlob` — dziś `passives` to statyczna krotka (`state.py:165`); potrzeba pola `granted_abilities`/`suppressed_abilities` z wygaśnięciem LUB eventów `AbilityGranted`/`AbilityRemoved` + reducery + sprzątanie na końcu aktywacji; (2) limit „raz na rundę" — `BattleState.used_interrupts_this_round` (TODO wg `interrupts.py:20-23`, nie istnieje); (3) podpięcie `InterruptPoint` do `phases.activation_phase` (dziś tylko stub Strażnika, brak integracji faz). Zakres: nowe pole + 2-3 eventy + reducery + integracja faz + limit per-runda + 3 handlery + testy replay-invariant. Wymaga ADR (interrupt orchestration + ability-grant mechanism).
  - **[H7 — czeka na fazę Leczenia pkt 21] heal-revive limit dla ELIMINOWANY/Zguby** — gdy powstanie faza Leczenia: `_apply_heal_*` przywraca tylko `location == WYCOFANY` (nie ELIMINOWANY, pkt 26.d); limit odzyskania pomniejszony o `wounds_eliminating`. Pole `wounds_eliminating` JUŻ persystowane na `UnitBlob` (R4.Zguba). **NIE blokuje B2/B4** (pole w schemacie).
  - **B2 ORM schema impact (ZAMROŻONE, zero migration churn):** `BattleEvent.payload_json` per unit +`location: Lokalizacja` +`wounds_eliminating: int`; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`; nowy event `MutexCollision`. (14 event types po resync.)

## Decyzje usera — 2026-06-26

- **B2 auth / agent access:** zaakceptowany minimalny pierwszy slice: `User.role`
  (`user|agent|admin`), `AgentToken`, `AgentAuditLog`. `BattleInvite` i snapshoty
  nie wchodza do pierwszego kroku. Zakres wymaga pelnego `/security-review`.
- **C3 `score_list(roster_id)`:** pierwsza wersja ma oceniac liste przez agregacje
  wynikow symulacji bitwy; pozniejsza interpretacja nalezy do dedykowanego agenta.
  Priorytet nizszy niz usuwanie uproszczen i artefaktow silnika.
- **C3 `find_exploit_candidates(army_id)`:** mozna robic przez turniej; wynik to
  kandydaci do recznej weryfikacji, nie automatyczny wyrok o exploicie. Priorytet
  nizszy niz postep w wiernosci silnika.
- **C3 `validate_loadout(payload)`:** zaakceptowany kierunek diff-validatora:
  read-only leaf CLI pokazujacy raw->normalized, odrzucone/sklampowane selekcje
  i koszt, z reuse istniejacego quote/normalize SSOT.
- **Telemetria raw combat rolls:** odlozone bez terminu; audyt kosci ma niska
  wartosc i ma wrocic dopiero, gdy konkretna potrzeba pokaze, jaki wariant danych
  bedzie uzyteczny.

## Decyzje zamrożone (NIE podnosić ponownie)

> **Czytaj PRZED wylistowaniem „co zostało".** Poniższe są ROZSTRZYGNIĘTE przez usera. NIE są otwartymi pytaniami, NIE są blokadami, NIE wymagają ADR-a do potwierdzenia. Nie przekształcaj ich z powrotem w „PYTANIE DO USERA". Implementuj wyłącznie na wyraźne polecenie usera.

- **Dywersant (id 6) — POZA ZAKRESEM tej fazy MVP.** User potwierdził DEFER trzykrotnie (H3, 2026-06-06 + reaffirmed 2026-06-09). Cost-side done (R2, weapon mult ×1.2). Engine-side = stub w `effects.INCOMPLETE_ABILITIES` (`effects.py:392`) — to jest stan DOCELOWY dla tej fazy, nie TODO. ×2 ataki vs Przyszpilony NIE implementujemy teraz. Żadna sesja nie powinna re-eskalować tego jako pytania/blokady.

- 2026-05-30: HANDOFF utworzony. Strumień A pełen (A0-A5 + A4); ADR-y 0001-0007 Accepted. ADR-y B (0008/0010/0010a/0014) do utworzenia w B0. `abilities.yaml` ma 88 entries po YAML sync z `Rozwoj` w trakcie A4. Wszystkie 6 slug-ów B exclusions audytowane jako obecne w YAML.
- 2026-05-30: B0 done (3 commits: `67740c4` ADR-y, `2e01894` deliverables, `53de635` roadmap). 4 ADR-y Accepted, `b_mvp` w `tables.yaml`, `b_mvp_exclusions.yaml` (6 entries), Pydantic + loader + testy. Parent przechodzi w tryb koordynacji sub-wątków.
- 2026-05-30: **Sub-wątek `faza-b-3-executor` started** ([HANDOFF](HANDOFF_faza-b-3-executor.md)). Decyzja: B3 leci przed pełnym B2 ORM — executor pure-function nie potrzebuje DB, minimum runtime substrate (state/events + apply_events) zrobi się w B3.0. Pełne B2 ORM (`faza-b-2-models`) odłożone do startu B4 API. GATE ADR-0010a pkt 3 (audit) → B3.0.1.
- 2026-05-30 (post-B3 archive): **B3 zakończone, sub-wątek archived.** Code review (`/code-review medium effort`) wykrył **8 findings: 7 bugów + 1 cleanup** clusterujące się w **5 dziur architektonicznych** (A: delta vs cumulative state; B: silent status mutations bypassing events; C: missing weapon inventory; D: geometry + constants duplikacja w 3 plikach; E: brak ACTIVE_ABILITY_REGISTRY). **Decyzja:** dodać **B3.9 architecture hardening** PRZED B2/B4 zamiast naprawiać bugi pojedynczo. Powód: (1) konsolidacja refactor w jednej fazie zamiast 7 osobnych ticketów; (2) B2 ORM `BattleEvent.payload_json` musi pokrywać wszystkie event types — stabilizacja PRZED ORM eliminuje migration churn; (3) B4 API będzie eksponowane na klientów, refactor po publikacji = breaking changes. Plan B3.9 obejmuje 6 kroków (`status.py`/`geometry.py` modules NEW, `ActivationContext` + initial_toughness snapshot, event-sourced status mutations + smoke replay invariant test, weapons inventory + ACTIVE_ABILITY_REGISTRY, dead code cleanup + docs update). 3 nowe ADR-y do napisania: 0045 (activation context), 0046 (event-sourced mutations), 0047 (weapons inventory). Sub-wątek `faza-b-3-hardening` do otwarcia w następnej sesji przez `/handoff-start`.
- **2026-06-06 (zaktualizowane 2026-06-07):** **Sub-wątek `faza-b-rules-resync` w trakcie (R0–R5.a/c/d/e/f/g ✅; R5.b skip; H5 RESOLVED 2026-06-07; pozostałe R4.Zguba/Klątwa-Rozkaz-Oznaczenie/R6/R7/RW).** Impact na parent B3.9 + B2: **ADR-0014 refresh — dodać pojedyncze pole-licznik `UnitBlob.wounds_eliminating: int`** (NIE restrukturyzacja na 3-pula — wcześniejsze sformułowanie porzucone jako sprzeczne z pkt 17.d). Semantyka: 2 pule alokacji bez zmian (pkt 17.d); broń Zguba dorzuca rany do `wounds_eliminating`; alokacja precise/regular zmniejsza licznik; model pokonany @ `eliminating>0` → ELIMINOWANY (pkt 26.d). **B2 ORM impact:** `BattleEvent.payload_json` +1 pole `wounds_eliminating` + `location` enum per unit; `ModelKilled` event +`eliminated: bool`. **Status R5.a + R4.Zguba (DONE 2026-06-07):** `location=WYCOFANY` przy pokonaniu (rany `422412c` + morale 2026-06-07) ORAZ `location=ELIMINOWANY` przy pokonaniu raną broni Zguba (`wounds_eliminating` licznik + `ModelKilled.eliminated` flag + `Shot/MeleeResolved.wounds_eliminating`). **B2 ORM `BattleEvent.payload_json` ZAMROŻONE:** per unit +`wounds_eliminating: int` + `location` enum; `ModelKilled` +`eliminated: bool`; `Shot/MeleeResolved` +`wounds_eliminating: int`. Pełna decyzja: `HANDOFF_faza-b-rules-resync.md` sekcja Decyzje 2026-06-07.
