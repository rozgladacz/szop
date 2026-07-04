# HANDOFF — faza-b-engine-mvp

> **Wątek:** Strumień B — Game Engine MVP (parent). Bootstrap (B0 założenia + 4 ADR-y) + B3 (rule executor) + B3.9 (architecture hardening) → B2 (modele ORM) → B4 (API) → B5 (klient) → B6 (prezentacja) → B7 (test bed). Praca delegowana do sub-wątków (`faza-b-2-models`, `faza-b-3-executor`, `faza-b-3-hardening`, ...).
> **Status:** In progress — B0 ✅ + B3 ✅ + **B3.9 ✅** (sub-wątek `faza-b-3-hardening` ready for archive 2026-06-02, 6 faz B3.9.a-f, pytest 1337/1337, 13 ADR-ów Accepted). Następne: B2 ORM (event types stabilne — zero migration churn) + Strumień D (agenci-boty) równolegle, potem B4 API + B5 klient.
> **Utworzony:** 2026-05-30
> **Ostatnia aktualizacja:** 2026-07-04T22:30+02:00 (DONE — B5 `HttpClient.create_battle`)

## DONE — 2026-07-04T22:30+02:00 — B5 `HttpClient.create_battle` (klient sandbox `POST /battles`)

**Zakres:** naturalny follow-up po utrwaleniu B4 `POST /battles` (`ff3b08a`) —
klient HTTP dla tego write-slice'a, wg wzorca `get_battle_metadata`/`get_events`.
`HttpClient.create_battle(p1_roster_id, p2_roster_id, rng_seed=0,
initiative_player=0)` woła `POST /battles` z JSON body + `Content-Type:
application/json`, reuse `_metadata_from_payload` (endpoint zwraca `BattlePublic`,
ta sama forma co metadata) → zwraca `BattleMetadata`. GET/POST zunifikowane
przez współdzielony `_request_json(method, path, query, *, json_body,
error_label)`; `_get_json` to cienki wrapper; `_headers(with_json_body=...)`
dokłada `Content-Type` tylko dla body. Read/write klient, bez decyzji usera, bez
`LOCKED`. `get_state`/`take_action`/`simulate` nadal `WAITING(prereq)` na kolejne
endpointy B4.

**Warstwy:** data model N/A; backend N/A (endpoint istnieje, klient tylko
konsumuje); JS/CSS N/A; testy `tests/test_clients_http.py` (+2: POST body/headers/
metadata, HTTP error); docs roadmap/architecture.

**Weryfikacja:** encoding gate OK; targeted `tests/test_clients_http.py
tests/test_battles_router.py` **24 passed**; pełny
`.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **2079 passed**,
3074 warnings (2077 + 2 nowe). Call-site check: `_headers`/`_get_json`/
`_request_json` wyłącznie wewnątrz `http.py`; `create_battle` w `local.py:202`
to inna klasa (`LocalClient`). `/simplify`: refaktor unifikuje GET/POST, cienki
`_get_json`. `/review`: 0 bugów — POST wysyła JSON body, 201 przechodzi status
check, reuse `_metadata_from_payload`, błędy → `HttpClientError` ze status_code.
`/security-review`: token tylko w nagłówku Authorization, body = same id
rosterów (brak sekretów), brak DB-write/dynamicznego SQL po stronie klienta.
Pliki commita: `szop_client/http.py`, `szop_client/__init__.py`,
`tests/test_clients_http.py`, `docs/roadmap.md`, `docs/architecture.md`, ten
HANDOFF. `.claude/settings.local.json` i `REVIEW_2026-07-04.md` (plik
równoległego agenta) poza zakresem. Commit: `<this>`.

## DONE — 2026-07-04 — commit hygiene B4 `POST /battles` (KOLIZJA równoległa, rozwiązana)

Slice B4 sandbox battle creation (`POST /battles`, wpis DONE 21:21) został
utrwalony jako commit `ff3b08a` (`feat(b4): add sandbox POST /battles create
endpoint`) przez **równoległego agenta** wraz z `REVIEW_2026-07-04.md`.
Druga, niezależna sesja autonomiczna wybrała ten sam task (commit hygiene) i
zdążyła jedynie re-zweryfikować pracę, zanim agent równoległy ją zacommitował:
targeted `tests/test_battles_router.py` **14 passed**, pełny pytest **2077
passed**, zero regresji — potwierdza zdrowie utrwalonego slice'a. Ten nagłówek
zastępuje przejściowy marker „W TRAKCIE", który zdążył wejść do `ff3b08a` przez
interleaving edycji tego pliku; slice jest zacommitowany, NIE jest w toku.
`.claude/settings.local.json`, główny `HANDOFF.md` i usunięty
`HANDOFF_aideas-knowledge-base.md` (archiwizacja AIDEAS) pozostają poza zakresem
B4 — osobna higiena.

> **Notatka z code-review 2026-07-04** (`docs/handoffs/code-review/REVIEW_2026-07-04.md`):
> 0 bugów korektności, 14/14 testów zielonych. Jedna UWAGA behawioralna: `create_battle`
> bierze wyłącznie `AdaptResult.units` i **cicho odrzuca** `dropped_excluded`,
> `inert_incomplete` oraz `deferred_attached_heroes`. W praktyce roster z dołączonym
> bohaterem tworzy bitwę bez tej jednostki, bez sygnału do wywołującego. To znany dług
> MVP (heroes DEFEROWANE w slice 1), nie regresja — ale przy rozszerzaniu B4 rozważyć
> zwrot/log tych pól, aby uniknąć cichej utraty jednostek.

## Cel

Zbudować symulator pełnej bitwy 1v1 oparty o `SZOP_Rozjemca.md` (reguły) + `SZOP_Zdolnosci.md` (mechaniki 77 zdolności). Engine headless-first (czyste funkcje + event sourcing), prezentacja opcjonalna. Pareto MVP: oddział = koło, brak orientacji modeli, ruch deklarowany (bez pathfindingu), LoS standardowy. 6 zdolności wykluczonych z MVP (Pareto trade-off; zob. `app/rulesets/v1/b_mvp_exclusions.yaml`).

Plan długofalowy: [docs/roadmap.md#strumień-b](../roadmap.md). Strumień B odblokowany przez zamknięcie Strumienia A (YAML SSOT) i A4 (pipeline drift detection — `build/geometry_classification.md` jako informational input).

## DONE - 2026-07-04T21:21:14+02:00 - B4 sandbox battle creation

**Zakres pracy:** dodać najmniejszy write-slice B4: `POST /battles` tworzy
sandboxową bitwę z dwóch rozpisek należących do tego samego ownera, zapisuje
wiersz `Battle` oraz początkowy event-log rozstawienia przez istniejące SSOT
adaptera ORM→engine i `persistence.save_events`. Nie implementuje invite'ów,
akcji, interruptów, replay/simulate endpointów ani pełnej rekonstrukcji
`BattleState` przez HTTP.

**Wybór zadania:** po dzisiejszych slice'ach read-only i optimistic append guard
roadmap B4 nadal ma otwarte `POST /battles`. Ten zakres jest mały,
samodzielny, bez UI i bez decyzji usera: reuse istniejącego
`roster_to_engine_roster`, `setup_phase`/`deployment_round` i `save_events`, a
jednocześnie przygotowuje B4 pod późniejsze `POST /battles/{id}/actions` oraz
B5 `HttpClient.create_battle`.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy; użycie istniejących tabel
  `battles` i `battle_events`.
- Backend payload/API: `app/routers/battles.py` - request/response dla create,
  owner-scoped roster lookup, auth sesją lub agent tokenem.
- JS render / CSS / template: N/A - brak UI.
- Testy: `tests/test_battles_router.py`; pełny pytest przed DONE.
- Dokumentacja/HANDOFF: roadmap/architecture oraz ten wpis.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i render list.
Endpoint wykonuje dwa SELECT-y rosterów po id+owner oraz jednorazową adaptację i
INSERT-y startowego event-logu tylko przy jawnej operacji create; brak wpływu na
read-only endpointy i stare call sites.

**Plan:**
- [x] 1. Encoding gate i doczytanie call sites/patternów auth.
- [x] 2. Dodać `battle:create` actor dependency, request model i helper tworzenia
  bitwy z dwóch własnych rosterów.
- [x] 3. Dodać testy: sukces dla sesji, sukces dla agenta, 404 dla cudzej/brakującej
  rozpiski, 403 dla tokena bez scope, zapis metadanych i event-logu.
- [x] 4. Zsynchronizować roadmap/architecture.
- [x] 5. Weryfikacja: targeted pytest, pełny pytest, call-site check, manual
  `/simplify`, manual `/review` (diff >50 + auth/write), manual
  `/security-review`, `git diff --check`, diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice'a. Invite'y, akcje,
interrupty, replay/simulate i pełny HTTP `GameClient` zostają `WAITING(prereq)`
na kolejne zakresy B4/B5.

**Wykonane kroki / odkrycia:**
- 2026-07-04T21:04+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  memory automatyzacji brak, przeczytano `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md`, stan working
  tree oraz bieżące B4/B5 pliki. Zastane niezwiązane zmiany
  `.claude/settings.local.json`, główny `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` pozostają poza zakresem.
- 2026-07-04T21:08+02:00: Encoding gate dla `app/routers/battles.py` i
  `tests/test_battles_router.py` OK przez `.venv` poza sandboxem; pierwsza
  próba w sandboxie trafiła w znany WindowsApps `Odmowa dostępu`. Wzorce auth:
  read endpointy używają sesji albo agent bearer; create dostanie osobny scope
  `battle:create` i będzie mapować agenta na `owner_user_id`.
- 2026-07-04T21:16+02:00: Dodano `BattleCreate`, `BattleCreator`,
  `POST /battles` oraz owner-scoped lookup rosterów. Endpoint tworzy aktywną
  bitwę sandboxową z `p1_user_id == p2_user_id == owner`, adaptuje obie rozpiski
  przez `roster_to_engine_roster`, wykonuje setup/deployment bez UI i zapisuje
  event-log przez `save_events(..., expected_latest_sequence=0)`. Testy
  routera rozszerzone o sukces sesyjny, sukces agentowy z audytem, brak scope
  oraz brak/cudzą rozpiskę; jeszcze przed uruchomieniem.
- 2026-07-04T21:20+02:00: Targeted `tests/test_battles_router.py`: **14
  passed**, 163 warnings. Przechodzę do synchronizacji `docs/roadmap.md` i
  `docs/architecture.md`.
- 2026-07-04T21:19+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: B4 ma teraz owner-scoped `POST /battles` jako sandbox
  create-slice z `battle:create`; invite'y, akcje, interrupty, simulate/replay
  i pełny HTTP client pozostają `WAITING(prereq)`.
- 2026-07-04T21:20+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`: **2077
  passed**, 3074 warnings. Manual `/simplify` znalazł jedną sensowną redukcję:
  wspólny helper wyboru ownera dla sesji vs bearer token między read/create
  dependency; wdrażam i powtórzę testy.
- 2026-07-04T21:21+02:00: Po `/simplify` targeted
  `tests/test_battles_router.py`: **14 passed**, 163 warnings; pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`: **2077
  passed**, 3074 warnings. Call-site check: nowy route `create_battle` jest
  konsumowany tylko przez FastAPI/testy; istniejące `LocalClient.create_battle`
  i `GameClient.create_battle` bez zmian; `save_events` stare call sites bez
  nowego guarded mode, a `POST /battles` używa `expected_latest_sequence=0`.
  Manual `/review`: 0 bugów korektności; bitwa jest tworzona dopiero po
  udanej adaptacji/setup/deployment, 404 ukrywa cudzą i brakującą rozpiskę,
  a event-log zapisuje ciągły startowy ogon. Manual `/security-review`: scope
  `battle:create` oddzielony od `battle:read`, agent mapowany na
  `owner_user_id`, oba rostery wymagają `owner_id == owner`, brak dynamicznego
  SQL, brak sekretów w response, standardowy `AgentAuditLog` redaguje token.
  `git diff --check` bez błędów (tylko znane ostrzeżenia CRLF). Diff review:
  scope 5 plików slice'a; zastane `.claude/settings.local.json`, główny
  `HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają poza
  zakresem. Commit: brak w tej sesji.
- 2026-07-04T22:? (sesja autonomiczna, commit hygiene): zastany, w pełni
  zweryfikowany slice B4 sandbox create leżał niezacommitowany. Re-weryfikacja
  bez zmian kodu: targeted `tests/test_battles_router.py
  tests/test_engine_persistence.py` **30 passed**; pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **2077
  passed**, 3074 warnings (identyczny baseline). Zacommitowano wyłącznie 5
  plików slice'a (`app/routers/battles.py`, `tests/test_battles_router.py`,
  `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF). Zastane
  `.claude/settings.local.json`, główny `HANDOFF.md` oraz usunięty
  `HANDOFF_aideas-knowledge-base.md` (archiwizacja wątku AIDEAS) świadomie poza
  tym commitem — osobny logiczny zakres. Commit: `<this>`.

## DONE - 2026-07-04T06:23:00+02:00 - B4 optimistic append guard

**Zakres pracy:** domknąć mały infrastrukturalny slice B4 pod przyszłe write
endpointy: `app/services/engine/persistence.save_events` ma opcjonalnie
weryfikować oczekiwany ostatni `BattleEvent.sequence` przed appendem. Istniejący
`UniqueConstraint(battle_id, sequence)` zostaje ostatnią linią obrony na race;
nowy precondition daje routerom B4 jawny konflikt bez projektowania dziś
`POST /battles/{id}/actions`.

**Wybór zadania:** roadmap B4 ma otwarte optimistic locking na sequence, a
ostatnie sesje zamknęły read-only metadata/event-log. To najmniejszy kolejny
krok w dwufalowym kierunku B API + B5/C MCP: przygotowuje bezpieczny zapis
eventów, nie wymaga decyzji usera, nie dotyka UI, kosztów, klasyfikacji ani
`LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`).

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy; wykorzystanie istniejącego
  `battle_events` i `UniqueConstraint(battle_id, sequence)`.
- Backend payload/API: helper persistence, bez nowych endpointów i bez zmian
  JSON kontraktów.
- JS render / CSS / template: N/A - brak UI.
- Testy: targeted `tests/test_engine_persistence.py`; pełny pytest przed
  deklaracją DONE.
- Dokumentacja/HANDOFF: roadmap/architecture oraz ten wpis.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i render list.
Nowy SELECT `max(sequence)` uruchamia się tylko gdy caller poda
`expected_latest_sequence`; istniejące read-only endpointy i stare call sites nie
dostają dodatkowego query.

**Plan:**
- [x] 1. Wykonać encoding gate, sprawdzić call sites i dodać wpis W TRAKCIE.
- [x] 2. Dodać opcjonalny `expected_latest_sequence` + jawny wyjątek konfliktu.
- [x] 3. Dodać testy: happy path, stale expected sequence, empty stream, brak
  regresji unguarded append.
- [x] 4. Zsynchronizować roadmap/architecture.
- [x] 5. Weryfikacja: targeted pytest, pełny pytest, call-site check,
  manual `/simplify`, manual `/review` (diff >50 linii / persistence), manual
  `/security-review` N/A jeśli brak auth/user input, `git diff --check`, diff
  review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego zakresu. Wire-in do
`POST /battles/{id}/actions` zostaje `WAITING(prereq)` na projekt write
endpointu B4.

**Wykonane kroki / odkrycia:**
- 2026-07-04T06:04+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  memory automatyzacji brak, przeczytano `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md`, stan roboczy i
  bieżące B4/B5 pliki. Zastane niezwiązane zmiany `.claude/settings.local.json`,
  główny `HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają
  poza zakresem. Encoding gate dla `persistence.py` i
  `tests/test_engine_persistence.py` przeszedł przez `.venv` poza sandboxem
  (sandboxowy WindowsApps shim nadal daje `Odmowa dostępu`).
- 2026-07-04T06:08+02:00: Dodano
  `BattleEventSequenceConflict`, `latest_event_sequence()` i guarded
  `save_events(expected_latest_sequence=...)`. Guard sprawdza aktualny max
  sequence, a w guarded mode wymaga ciągłego ogona eventów od `expected+1`.
  `app/routers/battles.py` reuse `latest_event_sequence()` dla metadanych,
  bez zmiany payloadu. Testy regresyjne dodane, jeszcze przed uruchomieniem.
- 2026-07-04T06:12+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: optimistic locking oznaczony jako persistence helper done,
  a wire-in do przyszłych B4 write endpointów pozostaje otwarty.
- 2026-07-04T06:23+02:00: Weryfikacja zakończona. Targeted
  `tests/test_engine_persistence.py tests/test_battles_router.py`: **26
  passed**, 323 warnings. Po manual `/simplify` usunięto zbędny routerowy
  wrapper `_latest_event_sequence` i powtórzono targeted: **26 passed**, 323
  warnings. Pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x
  --tb=short -q` po finalnym kodzie: **2073 passed**, 2955 warnings. Call-site
  check: stare wywołania `save_events` pozostają unguarded i nie dostają nowego
  SELECT-a; przyszłe write endpointy mogą użyć
  `expected_latest_sequence`; `latest_event_sequence` konsumuje router
  metadanych i testy. Manual `/review`: 0 bugów korektności; precheck nie
  dodaje eventów przed konfliktem, waliduje ciągły ogon i zostawia
  `UniqueConstraint` jako fallback race między SELECT i INSERT. Manual
  `/security-review`: N/A dla auth i user input; brak nowego endpointu,
  sekretów, dynamicznego SQL i zapisu zależnego od payloadu HTTP. `git diff
  --check` bez błędów (tylko znane ostrzeżenia CRLF). Diff review potwierdza
  scope 8 plików slice'a; zastane `.claude/settings.local.json`, główny
  `HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają poza
  zakresem. Commit: `<this>`.

## DONE - 2026-07-04T01:16:00+02:00 - B4/B5 metadata commit hygiene

**Zakres pracy:** nie rozszerzać funkcjonalnie gotowych read-only slice'ów
`GET /battles/{id}` i `HttpClient.get_battle_metadata`. Zweryfikować obecny diff,
call sites i testy, oddzielić go od niezwiązanych lokalnych zmian
`.claude`/AIDEAS/HANDOFF meta, a następnie utrwalić tylko pliki tych slice'ów.

**Wybór zadania:** working tree zawiera zakończony i opisany zakres B4/B5
metadata bez commita. Najbezpieczniejszy mały krok dla dwufalowego kierunku B API
+ B5/C MCP to domknięcie higieny zamiast dokładania kolejnego endpointu na
niestabilnym diffie. Zakres nie dotyka reguł gry ani `LOCKED` (Dywersant, raw
combat rolls, `models_mode=per_copy`).

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy i DB.
- Backend payload/API: re-weryfikacja `BattlePublic`, `GET /battles/{id}` i
  shared participant scope w `app/routers/battles.py`.
- JS render / CSS / template: N/A - brak UI.
- Testy: targeted `tests/test_battles_router.py tests/test_clients_http.py` oraz
  pełny pytest przed commitem.
- Dokumentacja/HANDOFF: ten wpis oraz memory automacji po zakończeniu.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i render list.
Metadata endpoint pozostaje jednym SELECT-em bitwy po id + jednym aggregate
`max(sequence)` po `battle_id`; klient wykonuje jedno żądanie HTTP na wywołanie.

**Plan:**
- [x] 1. Sprawdzić diff, branch i call sites, separując pliki slice'a od zmian
  obcych.
- [x] 2. Uruchomić targeted testy klient/router.
- [x] 3. Uruchomić pełny pytest.
- [x] 4. DoD: manual `/simplify`, manual `/review`, manual `/security-review`,
  `git diff --check`, diff review.
- [x] 5. Zacommitować wyłącznie pliki slice'a i zaktualizować memory.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego zakresu. Pełny `HttpClient`
(`create_battle`/`get_state`/`take_action`/`simulate`), write endpoints B4,
invite'y i snapshot/state pozostają `WAITING(prereq)` na kolejne, większe zakresy.

**Wykonane kroki / odkrycia:**
- 2026-07-04T01:03+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  przeczytano memory automacji, `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/git-workflow.md` oraz stan
  working tree. Zastane niezwiązane zmiany `.claude/settings.local.json`,
  `HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają poza
  zakresem.
- 2026-07-04T01:06+02:00: Diff/call-site sweep potwierdza scope: B4 metadata
  endpoint dodaje lokalne `BattlePublic`, `_public_battle`,
  `_latest_event_sequence` i `get_battle`; shared `_get_accessible_battle` nadal
  obsługuje oba read-only endpointy z tym samym participant scope. B5 klient
  dodaje `BattleMetadata` i `get_battle_metadata`; `_get_json` jest wspólny dla
  metadanych i eventów, a `_url` zachowuje query dla `get_events`. Publiczne
  użycia są ograniczone do eksportu `szop_client`, testów i dokumentacji.
- 2026-07-04T01:09+02:00: Targeted
  `tests/test_battles_router.py tests/test_clients_http.py`: **18 passed**,
  44 warnings. Pierwsza próba w sandboxie trafiła w znany WindowsApps
  `Odmowa dostępu`; re-run poza sandboxem z `.venv` i `-X utf8` przeszedł.
- 2026-07-04T01:11+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2067 passed**, 2941 warnings.
- 2026-07-04T01:16+02:00: DoD zakończony. `git diff --check` bez błędów
  (tylko znane ostrzeżenia CRLF). Manual `/simplify`: brak zmian; wspólny
  `_get_json` redukuje duplikację HTTP status/decode dla dwóch metod klienta.
  Manual `/review`: 0 bugów korektności; route `/{battle_id}` nie koliduje z
  `/{battle_id}/events`, oba endpointy używają tego samego participant scope, a
  metadata nie rekonstruuje ciężkiego `BattleState`. Manual `/security-review`:
  bearer wymaga `battle:read`, cudza/brakująca bitwa = 404, brak body/zapisu i
  dynamicznego SQL; token klienta trafia wyłącznie do nagłówka Authorization.
  Diff review: commit obejmuje tylko pliki B4/B5 metadata slice'a; `.claude`,
  główny `HANDOFF.md` i usunięty handoff AIDEAS pozostają poza zakresem.
  Commit: `<this>`.

## DONE - 2026-07-03T21:28:00+02:00 - B5 HttpClient battle metadata

**Zakres pracy:** mały follow-up B5 po read-only B4 metadata endpointzie:
`szop_client.HttpClient` ma pobierać metadane bitwy z `GET /battles/{id}`.
Nie rekonstruuje `BattleState`, nie implementuje `create_battle`, `take_action`,
write endpoints ani symulacji HTTP.

**Wybór zadania:** bezpośrednia kontynuacja dwufalowego kierunku B API + C MCP.
W working tree jest gotowy, zweryfikowany slice B4 `GET /battles/{id}`;
najmniejszy samodzielny krok to klient tego kontraktu, analogicznie do
wcześniejszego `HttpClient.get_events`. Zakres jest read-only, nie wymaga decyzji
usera i nie dotyka `LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`).

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy i DB.
- Backend payload/API: brak zmian endpointu; klient konsumuje istniejący lokalny
  response model `BattlePublic` z routera.
- JS render / CSS / template: N/A - brak UI.
- Testy: focused `tests/test_clients_http.py` oraz regresja
  `tests/test_battles_router.py`.
- Dokumentacja/HANDOFF: roadmap/architecture oraz ten wpis.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i render list.
Nowy klient wykonuje jedno żądanie HTTP na wywołanie; brak nowych query po
stronie istniejących endpointów poza już opisanym B4 metadata endpointem.

**Plan:**
- [x] 1. Wykonać encoding gate i doczytać wzorce `HttpClient`/testów.
- [x] 2. Dodać typ metadanych + metodę klienta i focused testy.
- [x] 3. Zsynchronizować roadmap/architecture.
- [x] 4. Weryfikacja: targeted pytest, pełny pytest, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review`, manual `/security-review`,
  `git diff --check`, diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice'a. Pełny
`HttpClient.get_state`, write endpoints, replay/simulate i właściwy HTTP
`GameClient` zostają `WAITING(prereq)` na kolejne endpointy B4 oraz model
snapshot/state.

**Wykonane kroki / odkrycia:**
- 2026-07-03T21:07+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  memory automatyzacji brak, przeczytano `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md` oraz stan working tree. Zastane zmiany
  `.claude/settings.local.json`, `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` pozostają poza zakresem.
- 2026-07-03T21:10+02:00: Encoding gate dla `szop_client/http.py`,
  `szop_client/__init__.py` i `tests/test_clients_http.py` OK po eskalacji
  `.venv` poza sandboxem (lokalny WindowsApps shim blokuje sandbox). Wzorce
  klienta i testów potwierdzają mały read-only slice z wstrzykiwanym transportem.
- 2026-07-03T21:16+02:00: Dodano `BattleMetadata` i
  `HttpClient.get_battle_metadata(battle_id)` w `szop_client/http.py`, eksport w
  `szop_client/__init__.py` oraz testy URL/headerów, dekodowania pól nullable,
  HTTP error i malformed payload. Targeted
  `tests/test_clients_http.py tests/test_battles_router.py`: **18 passed**,
  44 warnings.
- 2026-07-03T21:21+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: B5 `HttpClient` ma teraz dwa read-only slicey
  (`get_battle_metadata` + `get_events`), pełny `GameClient` HTTP nadal czeka na
  write/state/simulate endpoints B4.
- 2026-07-03T21:24+02:00: Call-site check: `BattleMetadata` użyty w eksporcie,
  testach i dokumentacji; `get_battle_metadata` jest nowym publicznym klientem
  użytym tylko w testach i dokumentacji; prywatny `_get_json` obsługuje lokalnie
  dwie metody klienta (`get_battle_metadata`, `get_events`); zmiana `_url`
  zachowuje query dla `get_events`, a dla metadanych usuwa zbędne `?`. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2067 passed**, 2941 warnings.
- 2026-07-03T21:28+02:00: DoD zakończony. `git diff --check` bez błędów
  (tylko znane ostrzeżenia CRLF). Manual `/simplify`: brak zmian; prywatny
  `_get_json` usuwa duplikację status/decode między dwoma metodami HTTP. Manual
  `/review`: 0 bugów korektności; `get_events` zachowuje URL z query i
  deserializację przez `json_to_event`, a metadata payload jest walidowany na
  wymagane pola. Manual `/security-review`: token trafia wyłącznie do nagłówka
  Authorization, brak logowania sekretów, brak DB-write/dynamicznego SQL po
  stronie klienta. Diff review potwierdza, że `.claude/settings.local.json`,
  główny `HANDOFF.md` i usunięty handoff AIDEAS pozostają poza zakresem. Brak
  commita w tej sesji.

## DONE - 2026-07-03T06:14:25+02:00 - B4 battle metadata endpoint

**Zakres pracy:** kolejny mały read-only slice B4 po event-log pollingu:
`GET /battles/{id}` ma zwracać participant-scoped metadane bitwy z tabeli
`battles` oraz `latest_sequence` z event-store. Nie rekonstruuje jeszcze pełnego
`BattleState`, nie tworzy bitew, nie przyjmuje akcji i nie zapisuje eventów.

**Wybór zadania:** bezpośrednia kontynuacja dwufalowego kierunku B API + C MCP po
`GET /battles/{id}/events` i `HttpClient.get_events`. Zakres jest mały,
read-only i opiera się na istniejącym B2 event-store, bez wchodzenia w invite'y,
akcje, snapshoty, MCP SDK, RAG ani decyzje `LOCKED`.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy i DB.
- Backend payload/API: `app/routers/battles.py` - nowy response model metadanych
  i endpoint `GET /battles/{id}` reuse istniejącego auth/participant scope.
- JS render / CSS / template: N/A - brak UI.
- Testy: `tests/test_battles_router.py` dla rejestracji, owner scope,
  `latest_sequence`, braku eventów i 404 dla cudzej/brakującej bitwy.
- Dokumentacja/HANDOFF: roadmap/architecture oraz ten wpis.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i render list.
Nowy endpoint wykonuje jeden SELECT bitwy po id z participant filter oraz jeden
lekki aggregate SELECT `max(BattleEvent.sequence)` po `battle_id`; brak nowych
query w istniejących endpointach.

**Plan:**
- [x] 1. Wykonać encoding gate i doczytać wzorce router/testów.
- [x] 2. Dodać endpoint metadanych + focused testy.
- [x] 3. Zsynchronizować roadmap/architecture.
- [x] 4. Weryfikacja: targeted pytest, pełny pytest, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review`, manual `/security-review`,
  `git diff --check`, diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice'a. Pełny
`HttpClient.get_state`, create/action endpoints i replay/simulate zostają
`WAITING(prereq)` na kolejne endpointy B4 oraz ewentualny model snapshot/state.

**Wykonane kroki / odkrycia:**
- 2026-07-03T06:02+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  memory automatyzacji brak, przeczytano `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md`,
  `docs/architecture.md` oraz stan working tree. Zastane zmiany
  `.claude/settings.local.json`, `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` pozostają poza zakresem.
- 2026-07-03T06:05+02:00: Encoding gate dla `app/routers/battles.py` i
  `tests/test_battles_router.py` OK po eskalacji `.venv` poza sandboxem
  (lokalny shim WindowsApps zwraca `Odmowa dostępu` w sandboxie). Wzorce
  router/testów potwierdzają reuse `_battle_reader` i `_get_accessible_battle`.
- 2026-07-03T06:10+02:00: Dodano `BattlePublic` i `GET /battles/{id}` w
  `app/routers/battles.py`. Endpoint reuse istniejący session-or-agent auth
  (`battle:read`) i participant scope, zwraca metadane `Battle` oraz
  `latest_sequence=max(BattleEvent.sequence)` bez rekonstrukcji `BattleState`.
  Testy routera rozszerzone o rejestrację ścieżki, owner scope, pusty event-log
  (`latest_sequence=0`) i 404 dla cudzej/brakującej bitwy. Targeted
  `tests/test_battles_router.py tests/test_clients_http.py`: **15 passed**,
  44 warnings.
- 2026-07-03T06:14+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: B4 ma teraz dwa read-only endpointy (`GET /battles/{id}`
  metadane + `GET /battles/{id}/events` polling). Write endpoints, replay,
  simulate, invite'y i pełny `BattleState` pozostają otwarte.
- 2026-07-03T06:14+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2064 passed**, 2941 warnings. Call-site check: `get_battle`,
  `_public_battle` i `_latest_event_sequence` są nowe i lokalne dla routera;
  `_get_accessible_battle` jest użyte przez oba read-only endpointy z tym samym
  participant scope; `BATTLE_READ_SCOPE` bez zmiany semantyki. `git diff
  --check` bez błędów (tylko znane ostrzeżenia CRLF). Working tree nadal ma
  niezwiązane zmiany `.claude/settings.local.json`, `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` poza zakresem.
- 2026-07-03T06:14+02:00: DoD zakończony. Manual `/simplify`: brak zmian.
  Manual `/review`: 0 bugów korektności; endpoint jest addytywny i nie
  koliduje z pollingiem eventów. Manual `/security-review`: reuse
  `_battle_reader` + `_get_accessible_battle`, cudza/brakująca bitwa = 404,
  bearer wymaga `battle:read`, brak body/zapisu/dynamicznego SQL; jedyny write
  to istniejący audyt agent-token przy ścieżce bearer. Diff review potwierdza
  scope tylko w plikach tego slice'a; brak commita w tej sesji.

## DONE - 2026-07-03T01:10:04+02:00 - B5 HttpClient polling commit hygiene

**Zakres pracy:** nie rozszerzać funkcjonalnie zakończonego slice'a
`szop_client.HttpClient.get_events`. Zweryfikować niezatwierdzony diff po runie
2026-07-02, odseparować go od niezwiązanych lokalnych zmian
`.claude`/AIDEAS/HANDOFF meta, powtórzyć wymagane testy i utrwalić tylko pliki
slice'a. Jeśli przegląd znajdzie realny drobny problem w slice'ie, naprawić go w
tym samym zakresie.

**Wybór zadania:** working tree zawiera gotowy, opisany niżej follow-up po B4
event-log API, ale nie jest on utrwalony. Najbezpieczniejsza kontynuacja
dwufalowego kierunku B API + C MCP to domknięcie tej higieny zamiast dokładania
nowego routera/endpointu na niestabilnym diffie. Zakres nie dotyka `LOCKED`
(Dywersant, raw combat rolls, `models_mode=per_copy`) ani reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy i DB.
- Backend payload/API: brak zmian endpointu; re-weryfikacja klienta HTTP
  konsumującego istniejący `BattleEventsPublic`.
- JS render / CSS / template: N/A - brak UI.
- Testy: targeted `tests/test_clients_http.py tests/test_battles_router.py`;
  pełny pytest przed deklaracją DONE.
- Dokumentacja/HANDOFF: ten wpis; roadmap/architecture tylko w zakresie już
  przygotowanego syncu B5 polling.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i pętlami
renderującymi. Re-weryfikowany klient wykonuje jedno żądanie HTTP na wywołanie
`get_events`; brak nowych query po stronie aplikacji.

**Plan:**
- [x] 1. Sprawdzić diff i call sites, oddzielając pliki slice'a od zmian obcych.
- [x] 2. Uruchomić targeted testy klient/router.
- [x] 3. Uruchomić pełny pytest.
- [x] 4. Wykonać DoD: call-site check, `git diff --check`, manual `/simplify`,
  manual `/review`, manual `/security-review`, diff review.
- [x] 5. Zacommitować wyłącznie pliki slice'a i zaktualizować status tego wpisu.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego zakresu. Pełny `HttpClient`
zgodny z `GameClient` nadal `WAITING(prereq)` na kolejne endpointy B4.

**Wykonane kroki / odkrycia:**
- 2026-07-03T01:02+02:00: Bootstrap wykonany ręcznie zgodnie z
  `/load-context`: przeczytano memory automatyzacji, `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md` oraz stan
  working tree. Zastane niezwiązane zmiany `.claude/settings.local.json`,
  `HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają poza
  zakresem.
- 2026-07-03T01:03+02:00: Diff/call-site sweep potwierdza izolację slice'a:
  `HttpClient`/`HttpRequest`/`HttpResponse` są użyte tylko w `szop_client`
  exporcie, `tests/test_clients_http.py` i dokumentacji; `get_events` ma
  istniejącą ścieżkę `LocalClient` oraz nową ścieżkę HTTP, bez zmian w
  routerze. Sandboxowa próba `.venv` trafiła w znany WindowsApps
  `Odmowa dostępu`; testy będą uruchamiane z `.venv` poza sandboxem i `-X utf8`.
- 2026-07-03T01:04+02:00: Targeted
  `tests/test_clients_http.py tests/test_battles_router.py` **12 passed**,
  31 warnings.
- 2026-07-03T01:05+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2061 passed**, 2928 warnings.
- 2026-07-03T01:06+02:00: DoD przed commitem: `git diff --check` bez błędów
  (tylko znane ostrzeżenia CRLF dla docs), trailing whitespace na plikach
  slice'a bez trafień. Manual `/simplify`: brak zmian. Manual `/review`: 0
  bugów korektności w zakresie commitowanego klienta; ścieżka HTTP robi jedno
  żądanie i dekoduje eventy przez `json_to_event`. Manual `/security-review`:
  token tylko w nagłówku Authorization, brak logowania sekretów, brak DB-write i
  dynamicznego SQL po stronie klienta. Diff review potwierdza, że zmiany
  `.claude`, meta `HANDOFF.md` i usunięty handoff AIDEAS są poza zakresem.
- 2026-07-03T01:10+02:00: Commit hygiene zakończony; commit obejmuje wyłącznie
  pliki slice'a B5 (`szop_client/http.py`, `szop_client/__init__.py`,
  `tests/test_clients_http.py`, sync roadmap/architecture i ten HANDOFF).
  Zastane zmiany `.claude`, `HANDOFF.md` oraz usunięty handoff AIDEAS pozostają
  poza zakresem.

## DONE - 2026-07-02T21:17:15+02:00 - B5 HttpClient event polling

**Zakres pracy:** mały follow-up po B4 read-only event-log API: dodać
`szop_client.HttpClient.get_events(battle_id, since=0)` jako klienta HTTP dla
istniejącego `GET /battles/{id}/events?since=N`. Slice jest read-only i nie
implementuje jeszcze `create_battle`, `get_state`, `take_action` ani `simulate`,
bo te endpointy B4 nie istnieją.

**Wybór zadania:** kontynuacja dwufalowego kierunku B API + C MCP. Po zamknięciu
B4 polling endpointu najbezpieczniejszy mały krok to konsument tego kontraktu w
`szop_client`, bez wchodzenia w duży router akcji, invite'y, snapshoty, MCP SDK
ani RAG. Nie dotyka `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) ani reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak zmian schemy i DB.
- Backend payload/API: brak zmian endpointu; klient konsumuje obecny payload
  `BattleEventsPublic` i deserializuje eventy przez engine SSOT `json_to_event`.
- JS render / CSS / template: N/A - brak UI.
- Testy: nowe focused testy klienta HTTP z fake transportem; targeted pytest
  `tests/test_clients_http.py` plus regresja `tests/test_battles_router.py`.
- Dokumentacja/HANDOFF: roadmap/architecture oraz ten wpis.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i pętlami kosztów.
Klient robi dokładnie jedno żądanie HTTP na wywołanie `get_events`; brak nowych
query po stronie istniejących requestów aplikacji.

**Plan:**
- [x] 1. Wykonać encoding gate i doczytać wzorce klienta/testów.
- [x] 2. Dodać `szop_client/http.py` z minimalnym read-only `get_events`.
- [x] 3. Dodać testy klienta HTTP i eksport pakietu.
- [x] 4. Zsynchronizować roadmap/architecture.
- [x] 5. Weryfikacja: targeted pytest, pełny pytest, call-site check.
- [x] 6. DoD: manual `/simplify`, warunkowy `/review` (nowy klient + payload),
  manual `/security-review` (bearer token/HTTP errors), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla tego slice'a. Pełna zgodność
`HttpClient` z całym `GameClient` pozostaje `WAITING(prereq)` na kolejne endpointy
B4 (`POST /battles`, `GET /battles/{id}`, akcje/symulacje).

**Wykonane kroki / odkrycia:**
- 2026-07-02T21:03+02:00: Bootstrap wykonany ręcznie zgodnie z
  `/load-context`: memory automatyzacji brak, przeczytano `AGENTS.md`,
  canonical `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md` oraz stan
  working tree. Zastane zmiany `.claude`, `HANDOFF.md` i usunięty handoff
  AIDEAS są poza zakresem. Wybrano read-only `HttpClient.get_events` jako mały
  follow-up po B4 endpointzie.
- 2026-07-02T21:08+02:00: Encoding gate dla istniejących plików Pythona OK po
  użyciu `.venv` poza sandboxem (WindowsApps blokuje alias). Dodano
  `szop_client/http.py` (stdlib `urllib`, wstrzykiwany transport do testów,
  deserializacja przez `json_to_event`), eksport w `szop_client/__init__.py` i
  `tests/test_clients_http.py` dla URL/headerów, deserializacji eventów,
  braku tokena, walidacji `since`, statusów HTTP i malformed payload.
- 2026-07-02T21:12+02:00: Targeted
  `tests/test_clients_http.py tests/test_battles_router.py` **12 passed**,
  31 warnings. `docs/roadmap.md` i `docs/architecture.md` zsynchronizowane:
  `HttpClient` oznaczony jako read-only polling slice DONE, pełny `GameClient`
  HTTP i pakowanie nadal czekają na kolejne endpointy B4.
- 2026-07-02T21:17+02:00: Po manualnym `/simplify` poprawiono docstring
  `szop_client/__init__.py`, żeby nie sugerował, że częściowy `HttpClient` jest
  już pełnym zamiennikiem `GameClient`. Re-run targeted
  `tests/test_clients_http.py tests/test_battles_router.py` **12 passed**,
  31 warnings. Pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x
  --tb=short -q` **2061 passed**, 2928 warnings. Call-site check:
  `HttpClient`/`HttpRequest`/`HttpResponse` użyte tylko w eksporcie pakietu,
  testach i dokumentacji; `LocalClient.get_events` bez zmian. `git diff
  --check` bez błędów (tylko znane ostrzeżenia CRLF dla zastanych plików),
  trailing whitespace na dotkniętych plikach bez trafień. Manual `/review`:
  0 bugów korektności; `get_events` robi jedno żądanie, waliduje `since`,
  status HTTP i payload, a eventy dekoduje przez `json_to_event`. Manual
  `/security-review`: token trafia wyłącznie do nagłówka Authorization, nie do
  URL ani komunikatów błędów; brak sekretów w testowym fake transporcie; brak
  dynamicznego SQL/DB-write po stronie klienta. Zastane zmiany `.claude`,
  `HANDOFF.md` i usunięty handoff AIDEAS nadal poza zakresem.

## DONE - 2026-07-02T06:16:00+02:00 - B4 event-log API commit hygiene

**Zakres pracy:** nie rozszerzać funkcjonalnie gotowego slice'a B4. Zweryfikować
niezacommitowany diff read-only `GET /battles/{id}/events?since=N`, oddzielić go
od równoległych lokalnych zmian AIDEAS/.claude, powtórzyć wymagane testy i
utrwalić tylko pliki slice'a.

**Wybór zadania:** po bootstrapie working tree zawiera już gotowy, opisany niżej
slice B4 read-only event-log API. To najbezpieczniejsza kontynuacja parenta:
porządkuje rozpoczęty krok dwufalowego planu B API + C MCP, bez dokładania
nowego zakresu na niestabilnym diffie i bez dotykania `LOCKED` (Dywersant, raw
combat rolls, `models_mode=per_copy`).

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - bez zmian schemy, używa istniejących `Battle` i
  `BattleEvent`.
- Backend payload/API: re-weryfikacja istniejącego routera `app/routers/battles.py`
  i rejestracji w `app/main.py`/`app/routers/__init__.py`.
- JS render / CSS / template: N/A - brak UI.
- Testy: targeted `tests/test_battles_router.py`, agent-token/persistence
  regresje, pełny pytest przed commitem.
- Dokumentacja/HANDOFF: ten wpis oraz finalne oznaczenie statusu.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Brak nowych
query w istniejących requestach; commit hygiene nie zmienia runtime.

**Plan:**
- [x] 1. Sprawdzić diff i oddzielić pliki B4 od równoległych zmian.
- [x] 2. Uruchomić targeted testy B4/auth/persistence i pełny pytest.
- [x] 3. Wykonać call-site check oraz manual `/simplify`/`/review`/`/security-review`.
- [x] 4. Zacommitować wyłącznie pliki B4 i zaktualizować status tego wpisu.

**Otwarte kwestie:** brak `BLOCKED(user)`. Równoległe zmiany `.claude`,
`HANDOFF.md` i usunięty `HANDOFF_aideas-knowledge-base.md` pozostają poza
zakresem tej sesji.

**Wykonane kroki / odkrycia:**
- 2026-07-02T06:05+02:00: Bootstrap wykonany ręcznie zgodnie z `/load-context`:
  memory automatyzacji puste, przeczytano `AGENTS.md`, canonical
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, jedyny aktywny
  `HANDOFF_faza-b-engine-mvp.md`, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md` i `docs/developing.md`. Working tree
  ma niezacommitowany slice B4 oraz niezwiązane zmiany AIDEAS/.claude; zakres
  tej sesji to re-weryfikacja i commit tylko slice'a B4.
- 2026-07-02T06:08+02:00: Diff B4 obejmuje `app/routers/battles.py`,
  `tests/test_battles_router.py`, rejestrację routera w `app/main.py` i
  `app/routers/__init__.py` oraz sync `docs/architecture.md`/`docs/roadmap.md`.
  Równoległe zmiany `.claude/settings.local.json`, `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` zostają poza zakresem. Targeted
  `tests/test_battles_router.py tests/test_agent_token_security.py tests/test_engine_persistence.py`
  **25 passed**, 321 warnings. Pełny pytest startuje jako następny podetap.
- 2026-07-02T06:11+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2056 passed**, 2928 warnings. Następny podetap: call-site/diff hygiene i
  ręczny DoD review.
- 2026-07-02T06:13+02:00: Call-site check: `battles.router` rejestrowany tylko
  w `app/main.py`; `get_battle_events`, `_battle_reader`,
  `_get_accessible_battle`, `_public_event` i `BATTLE_READ_SCOPE` mają wyłącznie
  lokalne/testowe użycia; scope `battle:read` jest zgodny z istniejącymi testami
  tokenów i ADR-0025. `git diff --check` bez błędów (tylko znane ostrzeżenia
  CRLF), trailing whitespace check na plikach B4 bez trafień. Manual
  `/simplify`: brak zmian. Manual `/review`: 0 bugów korektności w zakresie
  read-only endpointu. Manual `/security-review`: brak body i dynamicznego SQL,
  cudza/missing bitwa = 404, bearer wymaga `battle:read`, write ogranicza się do
  istniejącego audytu agent-token.
- 2026-07-02T06:16+02:00: Commit hygiene zakończony; commit `<this>` ma objąć
  wyłącznie pliki B4 (`app/routers/battles.py`,
  `tests/test_battles_router.py`, rejestrację routera, roadmap/architecture i
  ten HANDOFF). Zmiany `.claude`, `HANDOFF.md` oraz usunięty handoff AIDEAS
  pozostają poza zakresem.

## DONE - 2026-07-02T01:17:51+02:00 - B4 read-only event-log API

**Zakres pracy:** pierwszy mały slice B4: `GET /battles/{id}/events?since=N`
zwraca zapisany event-log bitwy z tabeli `battle_events`. Endpoint jest
read-only, owner/participant scoped i dopuszcza sesję użytkownika albo agent
bearer token ze scope `battle:read`. Nie tworzy bitew, nie przyjmuje akcji i nie
zmienia event-store.

**Wybór zadania:** po C1 `AgentProposal` UI najbliższy mały krok dwufalowego
kierunku B API + C MCP to bezpieczny odczyt eventów. Opiera się na już gotowym
B2 event-store i przybliża przyszły `szop_client.HttpClient` oraz MCP polling bez
wchodzenia w duży router akcji, invite'y, snapshoty ani executor zatwierdzonych
propozycji. Nie dotyka `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) ani reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - używa istniejących `Battle` i `BattleEvent`.
- Backend payload/API: nowy router `app/routers/battles.py`, rejestracja w
  `app/main.py`/`app/routers/__init__.py`, Pydantic response dla event-logu.
- JS render / CSS / template: N/A - brak UI w tym slice.
- Testy: nowy `tests/test_battles_router.py` dla rejestracji, filtrowania
  `since`, owner scoping, agent scope, 401/403/404.
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Endpoint robi
jeden SELECT bitwy po id z participant filter i jeden uporządkowany SELECT
eventów po `(battle_id, sequence)` przez istniejący FK/index + unique constraint.
Brak nowych query w istniejących requestach i brak wpływu na kalkulator kosztów.

**Plan:**
- [x] 1. Wykonać encoding gate i przeczytać wzorce routerów/persistence/testów.
- [x] 2. Dodać read-only router `battles` z auth session-or-agent i response model.
- [x] 3. Dodać testy B4 event-log API.
- [x] 4. Zsynchronizować roadmap/architecture.
- [x] 5. Weryfikacja: targeted pytest, pełny pytest, call-site check.
- [x] 6. DoD: manual `/simplify`, manual `/review` (auth/API), manual
  `/security-review` (auth + user/agent access do DB), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla read-only event-logu. Create
battle, actions, interrupts, simulate/replay, invite'y, snapshoty i `HttpClient`
pozostają osobnymi zakresami B4/B5.

**Wykonane kroki / odkrycia:**
- 2026-07-02T01:04+02:00: Encoding gate dla `app/main.py` i
  `app/routers/__init__.py` OK po eskalacji `.venv` (sandbox blokuje
  WindowsApps). Przeczytano wzorce `agent_tokens`, `agent_proposals`,
  `security.require_agent_scope`, `engine.persistence` i testy routerów.
- 2026-07-02T01:07+02:00: Dodano `app/routers/battles.py` z read-only
  `GET /battles/{battle_id}/events?since=N`. Auth: bearer token wygrywa nad
  sesją i wymaga scope `battle:read`; bez bearer tokena wymagana jest sesja.
  Dostęp jest filtrowany do `p1_user_id`/`p2_user_id` ownera/sesji, cudza albo
  brakująca bitwa = 404. Response serializuje engine eventy przez
  `event_to_json`; bez zapisu do DB poza istniejącym audytem agent-token.
  Dodano `tests/test_battles_router.py` dla rejestracji, `since`, owner scope,
  agent scope/audit i odmów 401/403/404.
- 2026-07-02T01:09+02:00: Targeted
  `tests/test_battles_router.py` **7 passed**, 31 warnings. Następny podetap:
  synchronizacja roadmap/architecture z pierwszym read-only slice B4.
- 2026-07-02T01:10+02:00: `docs/roadmap.md` oznacza B4 jako `[~]` tylko dla
  read-only polling endpointu `GET /battles/{id}/events`; create/action/invite/
  simulate/replay i SSE pozostają otwarte. `docs/architecture.md` opisuje
  participant-scoped read endpoint, scope `battle:read` i reuse `load_events`.
- 2026-07-02T01:12+02:00: Szerszy targeted
  `tests/test_battles_router.py tests/test_agent_token_security.py tests/test_engine_persistence.py`
  **25 passed**, 321 warnings. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2056 passed**, 2928 warnings.
- 2026-07-02T01:15+02:00: Manual `/simplify` wprowadził 1 redukcję:
  `BattleReader` niesie tylko `user_id`, bo `agent_user_id`/`token_id` były
  martwe po standardowym audycie w `require_agent_scope`. Po tej zmianie re-run
  targeted **25 passed**, 321 warnings oraz pełny pytest **2056 passed**, 2928
  warnings.
- 2026-07-02T01:17+02:00: Call-site check: `battles.router` jest rejestrowany
  tylko w `app/main.py`; `get_battle_events`, `_battle_reader`,
  `_get_accessible_battle` i `_public_event` mają wyłącznie lokalne/testowe
  użycia; `battle:read` jest zgodny z istniejącymi testami tokenów i ADR-0025.
  `git diff --check` bez błędów (tylko znane ostrzeżenia CRLF dla docs/.claude);
  trailing whitespace check na dotkniętych plikach bez trafień. Manual
  `/review`: 0 bugów korektności w zakresie read-only endpointu; `since`
  deleguje do `load_events`, response używa `event_to_json`, cudza/missing bitwa
  = 404. Manual `/security-review`: endpoint nie przyjmuje body, nie robi write
  poza istniejącym `AgentAuditLog`, nie ma dynamicznego SQL, bearer wymaga scope
  `battle:read`, a dostęp jest filtrowany po `p1_user_id`/`p2_user_id` ownera
  tokena albo sesji. Zastane zmiany `.claude`, `HANDOFF.md` i usunięty
  `HANDOFF_aideas-knowledge-base.md` są poza zakresem i nietykane.

## DONE - 2026-07-01T21:10:53+02:00 - C1 frontend UI commit hygiene

**Zakres pracy:** rezweryfikować i zacommitować wyłącznie zakończony slice
C1 frontend approval UI dla `AgentProposal`, który jest już opisany jako DONE
poniżej, ale nadal leży w working tree. Nie otwierać nowego zakresu kodowego
przed domknięciem tego diffu. Nie dotykać równoległych zmian AIDEAS
(`HANDOFF.md`, usunięty `HANDOFF_aideas-knowledge-base.md`) ani lokalnej
`.claude/settings.local.json`.

**Wybór zadania:** to najbezpieczniejsza kontynuacja aktywnego parenta
`faza-b-engine-mvp`: utrwala mały krok toru B/C (owner może rozstrzygać
propozycje agentów w UI) bez mieszania nowej pracy z niezacommitowanym diffem.
Nie dotyka `LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`) ani
reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak nowych zmian; używa istniejącego
  `AgentProposal`.
- Backend payload/API: N/A - bez zmian kontraktu, tylko istniejące endpointy
  list/approve/reject.
- JS render: rezweryfikacja `app/static/js/modules/agent_proposals.js`.
- CSS/template: rezweryfikacja panelu home i ładowania modułu.
- Testy: targeted frontend+router oraz pełny pytest przed commitem.
- Dokumentacja: ten HANDOFF; commit obejmie już przygotowane
  `docs/architecture.md`, `docs/frontend_js_modules.md`, `docs/roadmap.md`.

**Performance gate:** poza hot path `/quote`, `/rosters/{id}` i pętlami kosztów.
Brak nowych query względem już zaimplementowanego UI; commit hygiene nie zmienia
runtime.

**Plan:**
- [x] 1. Oddzielić diff C1 UI od równoległych zmian AIDEAS/.claude i sprawdzić call sites.
- [x] 2. Uruchomić targeted testy C1 frontend/router.
- [x] 3. Uruchomić pełny pytest.
- [x] 4. Wykonać DoD: `git diff --check`, manual `/simplify`, manual `/review`
  (JS diff >50), manual `/security-review` (UI wywołuje owner-scoped DB write
  przez istniejące endpointy).
- [x] 5. Zacommitować wyłącznie pliki C1 UI i zaktualizować status tego wpisu.

**Otwarte kwestie:** brak `BLOCKED(user)`. Browser smoke na `127.0.0.1` był
zablokowany w poprzednim runie przez politykę środowiska; utrzymuję Node smoke
jako kompensację i nie obchodzę blokady.

**Wykonane kroki / odkrycia:**
- 2026-07-01T21:03+02:00: Working tree rozdzielony logicznie: C1 UI obejmuje
  `app/templates/{base,index}.html`, `app/static/js/modules/agent_proposals.js`,
  `tests/test_agent_proposals_frontend.py`, `docs/{architecture,frontend_js_modules,roadmap}.md`
  i ten HANDOFF. Równoległe zmiany AIDEAS (`HANDOFF.md`, usunięty
  `HANDOFF_aideas-knowledge-base.md`) oraz `.claude/settings.local.json`
  zostają poza zakresem i poza commitem.
- 2026-07-01T21:05+02:00: Encoding gate dla
  `tests/test_agent_proposals_frontend.py` OK. Targeted
  `tests/test_agent_proposals_frontend.py tests/test_agent_proposals_router.py`:
  **13 passed**, 63 warnings. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2049 passed**, 2900 warnings.
- 2026-07-01T21:10+02:00: DoD commit-hygiene zakończony przed commitem:
  `git diff --check` bez błędów (tylko ostrzeżenia CRLF), trailing whitespace
  na plikach zakresu bez trafień, call-site sweep `agent_proposals` bez
  nieoczekiwanych konsumentów. Manual `/simplify`: brak zmian. Manual
  `/review`: 0 bugów korektności w zakresie commitowanego UI. Manual
  `/security-review`: brak nowych endpointów/SQL; moduł używa `textContent` dla
  danych propozycji, `innerHTML` tylko do czyszczenia listy, fetch
  `same-origin`, a write przechodzi przez istniejące owner-scoped approve/reject.
  Commit ma objąć wyłącznie pliki C1 UI; równoległe AIDEAS/.claude zostają poza
  zakresem.

## DONE - 2026-07-01T19:06:55+02:00 - C1 frontend approval UI dla `AgentProposal`

**Zakres pracy:** mały frontendowy follow-up po backendowym consent gate:
panel na stronie głównej zalogowanego ownera, który pobiera `GET
/agent_proposals`, pokazuje statusy i pozwala wykonać `approve`/`reject` dla
pozycji `pending`. Nie wykonuje akcji domenowej i nie zmienia backendowego
kontraktu; executor zatwierdzonych propozycji zostaje osobnym zakresem ADR-0024.

**Wybór zadania:** kontynuacja aktywnego wątku `faza-b-engine-mvp` i gotowego
backendu C1. To najmniejszy krok przybliżający dwufalowy kierunek B API + C MCP:
owner może realnie rozstrzygać propozycje agentów bez wchodzenia w duży B4 router,
MCP SDK, RAG ani executor zapisów. Nie dotyka `LOCKED` (Dywersant, raw combat
rolls, `models_mode=per_copy`) ani reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - używa istniejącego `AgentProposal`.
- Backend payload/API: bez zmian kontraktu; frontend konsumuje istniejące
  `GET /agent_proposals`, `POST /agent_proposals/{id}/approve|reject`.
- JS render: nowy moduł `app/static/js/modules/agent_proposals.js`, no-op poza
  panelem.
- CSS/template: `app/templates/index.html` (panel) + `app/templates/base.html`
  (ładowanie modułu); Bootstrap bez nowych zależności.
- Testy: Node/jsdom-free test modułu frontendu + targeted backend C1; smoke JS
  ścieżek Zbrojownia / Edytor Armii / Rozpiski po zmianie modułu JS.
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Panel działa
tylko na stronie głównej po zalogowaniu i wykonuje jeden owner-scoped fetch do
małej tabeli propozycji; brak nowych query w kosztach, listach rozpisek lub
pętlach silnika.

**Plan:**
- [x] 1. Przeczytać wzorce template/JS/testów i doprecyzować minimalny kontrakt UI.
- [x] 2. Dodać panel + moduł JS z renderem, loading/error/empty state i akcjami.
- [x] 3. Dodać testy frontendu i zsynchronizować roadmap/architecture.
- [!] 4. Weryfikacja: targeted pytest/Node i pełny pytest OK; browser smoke JS
  zablokowany przez politykę środowiska dla `127.0.0.1`, zastąpiony dodatkowym
  Node smoke renderu DOM.
- [x] 5. DoD: call-site check, manual `/simplify`, manual `/review` (diff >50 + JS),
  manual `/security-review` (user action -> DB przez istniejące endpointy), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. Browser smoke wymaga środowiska z
dostępem przeglądarki do `127.0.0.1`. Executor zatwierdzonych propozycji i pełny
B4/MCP pozostają `READY`/osobne zakresy; `LOCKED` decyzje poniżej pozostają
nietykane.

**Wykonane kroki / odkrycia:**
- 2026-07-01T18:53:10+02:00: Przejęcie rozpoczętego slice'a z working tree.
  Zakres tej sesji: dokończyć weryfikację i DoD dla frontendowego approval UI
  `AgentProposal`, naprawiając tylko konkretne problemy znalezione w testach lub
  manualnym przeglądzie. Warstwy bez zmian względem planu: JS render +
  template/docs/testy; data model i backend kontrakt bez zmian; performance gate
  nadal poza `/quote` i `/rosters/{id}`. Przeczytano memory automatyzacji
  (brak), `AGENTS.md`, `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`,
  oba aktywne HANDOFF-y, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md`,
  `docs/app-js-guide.md`, aktualny diff i call-site grep `agent_proposals`.
- 2026-07-01T18:58+02:00: Targeted
  `tests/test_agent_proposals_frontend.py tests/test_agent_proposals_router.py`
  **12 passed**. Sandbox nadal blokuje `.venv` przez WindowsApps, więc test
  uruchomiono poza sandboxem po zgodzie. Dodatkowy check routingu: `/` w
  `app/main.py` przekierowuje niezalogowanych do `/auth/login`, więc panel nie
  montuje owner-only fetcha na stronie publicznej.
- 2026-07-01T19:00+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2048 passed**, 2900 warnings. Następny podetap: smoke JS na dev serverze dla
  home/Zbrojownia/Edytor Armii/Rozpiski i panelu `AgentProposal`.
- 2026-07-01T19:06+02:00: Dev server uruchomił się na
  `http://127.0.0.1:8765` (startup OK; `/` daje 303 do `/auth/login`), ale
  browser smoke został zablokowany przez politykę środowiska dla `127.0.0.1`.
  Nie obchodzę blokady alternatywną przeglądarką. Dostępna weryfikacja JS:
  Node smoke modułu w `tests/test_agent_proposals_frontend.py` + pełny pytest.
- 2026-07-01T19:02+02:00: Przed podetapem uzupełniającym wykonano encoding gate
  dla `tests/test_agent_proposals_frontend.py` (OK). Zakres: dodać Node smoke
  renderu DOM modułu z minimalnym stubem dokumentu, żeby pokryć empty/pending
  render bez użycia zablokowanej przeglądarki.
- 2026-07-01T19:03+02:00: Uzupełniono
  `tests/test_agent_proposals_frontend.py` o Node smoke `renderAgentProposals`
  (empty state, pending count, akcje approve/reject, payload). Targeted:
  `tests/test_agent_proposals_frontend.py` **3 passed**.
- 2026-07-01T19:05+02:00: Finalny re-run pełnego pytest po zmianie testu:
  **2049 passed**, 2900 warnings. `git diff --check` bez błędów (tylko
  ostrzeżenia CRLF), `rg "[ \t]+$"` na dotkniętych plikach bez trafień.
  Call-site check: moduł ładowany wyłącznie w `base.html`, panel montowany w
  `index.html`, publiczne `SZOPAgentProposals`/`initAgentProposals` używane
  przez self-init i testy; poza panelem moduł jest no-op. Serwer smoke
  zatrzymany, port 8765 bez listenera.
- 2026-07-01T19:06:55+02:00: Manual `/simplify`: brak zmian — helpers są
  lokalne i nie duplikują logiki backendowej. Manual `/review`: 0 bugów
  korektności w zakresie UI; render używa `textContent`, pending actions
  blokują przyciski podczas requestu i aktualizują lokalną listę wynikiem
  endpointu. Manual `/security-review`: brak nowych endpointów i dynamicznego
  SQL; fetch jest same-origin z istniejącymi owner-scoped endpointami, payload i
  summary nie trafiają do `innerHTML`, brak logowania sekretów. Re-run pytest po
  DoD niepotrzebny, bo finalne zmiany są tylko dokumentacyjne w HANDOFF.
- 2026-06-30T21:04:15+02:00: Bootstrap wykonany ręcznie zgodnie z
  `/load-context`: memory automatyzacji puste, przeczytano `AGENTS.md`,
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, oba aktywne HANDOFF-y,
  `docs/handoffs/README.md`, `docs/roadmap.md`, `docs/planning.md`,
  `docs/testing.md`, `docs/developing.md`, `docs/app-js-guide.md` i
  `docs/architecture.md`. `aideas-knowledge-base` jest Ready for archive i
  blokuje tylko `AIdeas/`. Working tree ma zastaną `.claude/settings.local.json`;
  nie dotykam jej.
- 2026-06-30T21:08+02:00: Wzorce UI: `base.html` ładuje moduły IIFE globalnie,
  a `index.html` jest stroną startową po zalogowaniu. Wybrany kształt: panel
  `data-agent-proposals-panel` na home, moduł `agent_proposals.js` ładowany w
  `base.html`, no-op poza panelem, bez edycji closure `app.js`.
- 2026-06-30T21:12+02:00: Dodano panel `Propozycje agentów` w `index.html`
  oraz moduł `agent_proposals.js`: fetch listy, empty/error/loading state, DOM
  rendering przez `textContent`, szczegóły payloadu w `<details>`, akcje
  `Zezwól`/`Odrzuć` przez istniejące endpointy approve/reject. `base.html`
  ładuje moduł globalnie; poza panelem moduł nie robi zmian w DOM.
- 2026-06-30T21:15+02:00: Dodano `tests/test_agent_proposals_frontend.py`
  (template mount + Node smoke eksportów modułu) oraz zsynchronizowano
  `docs/roadmap.md`, `docs/architecture.md`, `docs/frontend_js_modules.md`.

## DONE - 2026-06-30 - C1 odczyt pojedynczej `AgentProposal` (owner)

**Zakres:** owner-scoped `GET /agent_proposals/{id}` domykający kontrakt REST
consent-gate (create/list/**get**/approve/reject). Read-only, reuse
`_get_owned_proposal` + `_public_proposal`; cudza/nieistniejąca = 404. Pod UI
detalu/poll statusu propozycji. Bez nowego scope ani decyzji usera; nie dotyka
`LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`) ani reguł gry.

**Warstwy:** backend `app/routers/agent_proposals.py` (+`get_agent_proposal`);
testy `tests/test_agent_proposals_router.py` (route GET registration, owner fetch,
404 cudza + 404 nieistniejąca, brak audytu/mutacji przy odczycie); docs
`docs/roadmap.md`, `docs/architecture.md`. Data model/JS/CSS: N/A.

**Performance gate:** poza hot path; pojedynczy owner-scoped SELECT po id.

**Weryfikacja:** targeted `tests/test_agent_proposals_router.py` **10 passed**;
pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **2046 passed**
(2045 + 1), zero regresji. Call-site check: `get_agent_proposal` tylko w
routerze i teście. DoD: `/simplify` 0 zmian (czysty reuse helperów); `/review`
0 bugów korektności (odczyt mirror approve/reject, 404 dla cudzej/missing, brak
audytu/mutacji); `/security-review` — wymaga sesji `get_current_user()`, filtruje
`owner_user_id == current_user.id`, cudza = 404, brak body/zapisu/dynamicznego SQL.

**Otwarte kwestie:** brak `BLOCKED(user)`. Frontend approval UI i executor
zatwierdzonych propozycji (ADR-0024, akcje B4/MCP) pozostają osobnymi zakresami.

## DONE - 2026-06-30T06:15+02:00 - C1 odrzucanie `AgentProposal`

**Zakres pracy:** mały backendowy follow-up po liście propozycji: dodać
owner-only `POST /agent_proposals/{id}/reject`, żeby backendowy kontrakt zgody
miał oba rozstrzygnięcia wymagane przez przyszły UI `[Zezwól] [Odrzuć]`.
Endpoint ma działać tylko dla właściciela propozycji, być idempotentny dla już
odrzuconych propozycji i nie wykonywać akcji domenowej.

**Wybór zadania:** kontynuacja już otwartego, niezatwierdzonego zakresu
`AgentProposal` minimalizuje ryzyko konfliktu z równoległymi agentami i domyka
jedno brakujące rozstrzygnięcie backendowego consent gate przed frontendem/B4.
Nie wymaga decyzji użytkownika, nie dotyka `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) ani reguł gry.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - używa istniejącego `AgentProposal.status="rejected"`.
- Backend payload/API: `app/routers/agent_proposals.py` (`POST .../reject`).
- JS render / CSS / template: N/A - brak UI w tym slice.
- Testy: `tests/test_agent_proposals_router.py` (router registration, owner scope,
  idempotencja, konflikt approved->reject).
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Endpoint robi
pojedynczy owner-scoped SELECT po id i jeden UPDATE tylko przy pierwszym odrzuceniu;
brak nowych query w istniejących requestach UI, kosztach albo pętli silnika.

**Plan:**
- [x] 1. Wykonać encoding gate i przeczytać lokalne wzorce proposal routera/testów.
- [x] 2. Dodać reject endpoint + testy owner/idempotency/conflict.
- [x] 3. Zsynchronizować `docs/roadmap.md` i `docs/architecture.md`.
- [x] 4. Weryfikacja: targeted pytest, pełny pytest.
- [x] 5. DoD: call-site check, manual `/simplify`, manual `/review` (auth/API),
  manual `/security-review` (owner scope + DB update), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. Frontend approval UI i executor
zatwierdzonych propozycji zostają `READY`/osobne zakresy.

**Wykonane kroki / odkrycia:**
- 2026-06-30T06:03:04+02:00: Bootstrap wykonany ręcznym odpowiednikiem
  `/load-context`: przeczytano memory automatyzacji (brak treści), `AGENTS.md`,
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, oba aktywne HANDOFF-y,
  `docs/handoffs/README.md`, `docs/roadmap.md`, `docs/planning.md`,
  `docs/testing.md`, `docs/developing.md` oraz aktualny diff. Working tree ma
  zastany backendowy slice `AgentProposal` i lokalną `.claude/settings.local.json`;
  pracuję wyłącznie na kontynuacji `AgentProposal`.
- 2026-06-30T06:05+02:00: Encoding gate dla
  `app/routers/agent_proposals.py` i `tests/test_agent_proposals_router.py` OK
  po eskalacji `.venv` (sandbox blokował WindowsApps). Call-site search pokazał,
  że `AGENT_PROPOSAL_STATUS_REJECTED` już istnieje, ale brak publicznego
  endpointu odrzucania.
- 2026-06-30T06:09+02:00: Dodano `POST /agent_proposals/{id}/reject` jako
  owner-scoped decyzję symetryczną do approve. Wspólny helper obsługuje lookup
  po ownerze, idempotencję dla docelowego statusu i konflikt dla przejść
  approved↔rejected. Testy rozszerzone o rejestrację route, owner-only reject,
  idempotencję reject i konflikt `approved -> reject`.
- 2026-06-30T06:11+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: backendowy `AgentProposal` kontrakt obejmuje create/list/
  approve/reject. ADR-0024 nadal otwarte, bo executor domenowy i konsumenci B4/MCP
  nie są częścią tego slice'a.
- 2026-06-30T06:14+02:00: Targeted C1
  `tests/test_agent_proposals_router.py tests/test_agent_tokens_router.py tests/test_agent_token_security.py`
  **29 passed**, 237 warnings.
- 2026-06-30T06:15+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2045 passed**, 2894 warnings. Call-site check: `reject_agent_proposal`,
  `_get_owned_proposal`, `_decide_proposal`, `AGENT_PROPOSAL_STATUS_REJECTED`
  i `/reject` występują tylko w routerze/testach/modelu oraz dokumentacji.
  `git diff --check` bez błędów (tylko ostrzeżenia CRLF dla docs i zastanej
  `.claude`); osobny `rg "[ \t]+$"` na dotkniętych plikach bez trafień.
  Manual `/simplify`: bez zmian. Manual `/review`: 0 bugów korektności w zakresie
  reject endpointu; przejścia statusu są idempotentne tylko dla statusu docelowego,
  a przejścia approved↔rejected zwracają 409. Manual `/security-review`: reject
  wymaga sesji użytkownika przez `get_current_user()`, filtruje
  `owner_user_id == current_user.id`, cudza propozycja = 404, nie przyjmuje body,
  nie wykonuje akcji domenowej i audytuje tylko metadane bez payloadu/sekretów.
  Realne pytania do usera: brak; frontend approval UI i executor zatwierdzonych
  propozycji pozostają `READY`/osobne zakresy.

## DONE - 2026-06-30T01:13+02:00 - C1 lista `AgentProposal` dla ownera

**Zakres pracy:** mały backendowy follow-up po slice `AgentProposal`: dodać
owner-only `GET /agent_proposals`, żeby przyszły approval UI i konsumenci B4/MCP
mieli odczyt pending/decided propozycji bez bezpośredniego dostępu do DB. Endpoint
ma zwracać tylko propozycje zalogowanego ownera, najnowsze pierwsze, przez ten sam
model publiczny co create/approve. Brak wykonywania akcji domenowej.

**Wybór zadania:** kontynuacja gotowego consent gate z 2026-06-29; najmniejszy
brakujący element backendowy przed frontendowym approval UI. Nie wymaga decyzji
usera, nie dotyka `LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`),
nie wchodzi w pełny B4 router, MCP SDK ani RAG.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - używa istniejącego `AgentProposal`.
- Backend payload/API: `app/routers/agent_proposals.py` (`GET /agent_proposals`).
- JS render / CSS / template: N/A - brak UI w tym slice.
- Testy: `tests/test_agent_proposals_router.py` (router registration, owner scope,
  sortowanie, payload publiczny).
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Endpoint robi
jedno owner-scoped SELECT po małej tabeli propozycji; brak nowych query w istniejących
requestach UI, kosztach albo pętli silnika.

**Plan:**
- [x] 1. Przeczytać aktualny diff i wzorce token/proposal routera.
- [x] 2. Dodać list endpoint + testy owner scoping/sortowania.
- [x] 3. Zsynchronizować `docs/roadmap.md` i `docs/architecture.md`.
- [x] 4. Weryfikacja: encoding gate, targeted pytest, pełny pytest.
- [x] 5. DoD: call-site check, manual `/simplify`, manual `/review` (auth/API),
  manual `/security-review` (owner scope + DB read), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. Frontend approval UI i wykonawca
zatwierdzonych propozycji zostają `READY`/osobne zakresy.

**Wykonane kroki / odkrycia:**
- 2026-06-30T01:03:46+02:00: Bootstrap wykonany przez lokalny odpowiednik
  `/load-context`: przeczytano memory automatyzacji, `AGENTS.md`,
  `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`, oba aktywne HANDOFF-y,
  `docs/handoffs/README.md`, `docs/roadmap.md`, `docs/planning.md`,
  `docs/testing.md`, `docs/developing.md`, `docs/architecture.md`. Working tree
  zawiera niezatwierdzony backendowy slice `AgentProposal` z poprzedniej sesji
  oraz zastaną `.claude/settings.local.json`; nie usuwam cudzych zmian.
- 2026-06-30T01:06:56+02:00: Dodano `GET /agent_proposals` w routerze jako
  owner-scoped SELECT po `AgentProposal.owner_user_id`, sortowany po
  `created_at desc, id desc`, bez efektów ubocznych. Testy rozszerzone o
  rejestrację metody GET oraz owner scoping/listowanie pending+approved bez
  wycieku cudzych propozycji.
- 2026-06-30T01:08:12+02:00: `docs/roadmap.md` i `docs/architecture.md`
  zsynchronizowane: backendowy `AgentProposal` kontrakt obejmuje teraz
  create/list/approve. ADR-0024 nadal otwarte, bo executor zapisów domenowych
  i konsumenci B4/MCP nie są częścią tego slice'a.
- 2026-06-30T01:09:04+02:00: Pierwszy targeted C1 zatrzymał się na teście
  `test_list_agent_proposals_is_owner_scoped_and_newest_first`: helper testowy
  używał stałego `RAW_TOKEN`, więc drugi owner w tej samej in-memory DB łamał
  unikalność `AgentToken.token_hash`. To błąd fixtury testowej ujawniony przez
  nowy scenariusz multi-owner; poprawka: token testowy unikalny per owner.
- 2026-06-30T01:11:37+02:00: Encoding gate dla
  `app/routers/agent_proposals.py` i `tests/test_agent_proposals_router.py` OK
  (po eskalacji `.venv`, bo sandbox blokuje WindowsApps). Targeted C1:
  `tests/test_agent_proposals_router.py tests/test_agent_tokens_router.py tests/test_agent_token_security.py`
  **27 passed**, 222 warnings. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2043 passed**, 2879 warnings.
- 2026-06-30T01:13:33+02:00: Call-site check: `list_agent_proposals` występuje
  tylko w routerze i teście; `agent_proposals` route rejestrowane przez
  `app/main.py`/`app/routers/__init__.py`; docs zaktualizowane. `git diff --check`
  bez błędów (tylko ostrzeżenia CRLF dla docs i zastanej `.claude`). Dodatkowe
  `rg "[ \t]+$"` na untracked router/test nie znalazło trailing whitespace.
  Manual `/simplify`: bez zmian. Manual `/review`: 0 bugów korektności w zakresie
  list endpointu. Manual `/security-review`: listing wymaga sesji usera przez
  `get_current_user()`, filtruje `owner_user_id == current_user.id`, nie ujawnia
  cudzych propozycji, nie przyjmuje parametrów query, nie zapisuje do DB i nie
  loguje payloadów/sekretów. Realne pytania do usera: brak; frontend approval UI,
  reject endpoint i executor domenowy pozostają `READY`/osobne małe zakresy.

## DONE - 2026-06-29T21:20+02:00 - C1 `AgentProposal` backend consent gate

**Zakres pracy:** addytywny backendowy slice C1 po endpointach tokenów:
model `AgentProposal` + minimalne JSON endpointy `POST /agent_proposals`
(agent bearer token tworzy propozycję zapisu) i
`POST /agent_proposals/{id}/approve` (owner zatwierdza sesją użytkownika).
Zatwierdzenie w tym slice **nie wykonuje akcji domenowej** - tylko zapisuje
zgodę/status do późniejszego konsumenta B4/MCP. Frontend approval UI pozostaje
osobnym checkboxem roadmapy.

**Wybór zadania:** to najmniejszy następny krok po gotowych tokenach C1, który
przybliża dwufalowy kierunek B API + C MCP bez wchodzenia w pełny B4 router,
MCP SDK ani RAG. Nie dotyka zasad gry ani pozycji `LOCKED` (Dywersant, raw combat
rolls, `models_mode=per_copy`).

**Warstwy (Layer Checklist):**
- Data model / migracja: `app/models.py` (`AgentProposal`) + standardowe
  `Base.metadata.create_all`; ręczna `_migrate_schema` tylko jeśli testy pokażą
  potrzebę dla istniejącej SQLite.
- Backend payload/API: nowy router `app/routers/agent_proposals.py`,
  rejestracja w `app/main.py` i `app/routers/__init__.py`.
- JS render / CSS / template: N/A - brak UI w tym slice.
- Testy: nowy `tests/test_agent_proposals_router.py` + targeted C1.
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Endpointy robią
pojedyncze owner-scoped operacje na małej tabeli propozycji; brak nowych query w
istniejących requestach UI, kosztach lub pętli silnika.

**Plan:**
- [x] 1. Przeczytać wzorce `AgentToken`, auth dependency, router registration i testy.
- [x] 2. Dodać model, router, rejestrację i testy minimalnego kontraktu.
- [x] 3. Zsynchronizować roadmap/architecture.
- [x] 4. Weryfikacja: encoding gate, targeted pytest, pełny pytest.
- [x] 5. DoD: call-site check, manual `/simplify`, manual `/review` (diff >50/auth),
  manual `/security-review` (auth + user input -> DB), diff review.

**Otwarte kwestie:** brak `BLOCKED(user)` dla backendowego consent gate. Przyszły
wykonawca zatwierdzonych propozycji (konkretne akcje B4/MCP) i UI listy/approve
pozostają `READY`/osobne zakresy, nie blokują tego slice'a.

**Wykonane kroki / odkrycia:**
- 2026-06-29T21:05:19+02:00: Bootstrap: memory automatyzacji nie istniała;
  przeczytano `AGENTS.md`, `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`,
  oba aktywne HANDOFF-y, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md`, `docs/developing.md`,
  `docs/architecture.md`. `aideas-knowledge-base` jest `Ready for archive` i
  blokuje tylko `AIdeas/`; working tree ma wyłącznie zastaną
  `.claude/settings.local.json`, której nie dotykam.
- 2026-06-29T21:05:19+02:00: Wzorzec C1: `AgentToken` ma owner-only endpointy,
  bearer-token dependency `require_agent_scope(scope_name)` zapisuje audit i
  zwraca `AgentPrincipal(owner_user_id, agent_user_id, token_id, scopes)`.
  Minimalny scope dla tworzenia propozycji w tym slice: `agent_proposals:create`.
- 2026-06-29T21:12+02:00: Dodano addytywny model `AgentProposal`, router
  `app/routers/agent_proposals.py`, rejestrację w `app/main.py`/`routers.__init__`
  i testy `tests/test_agent_proposals_router.py`. Kontrakt: agent z bearer
  scope `agent_proposals:create` tworzy `pending`; owner zatwierdza własne
  propozycje idempotentnie; zatwierdzenie zapisuje status/`decided_at`, nie
  wykonuje domenowego write. Targeted C1:
  `tests/test_agent_proposals_router.py tests/test_agent_tokens_router.py tests/test_agent_token_security.py`
  **26 passed**, 208 warnings.
- 2026-06-29T21:14+02:00: `docs/roadmap.md` oznacza backendowy `AgentProposal`
  slice jako DONE, ale frontend approval UI i wykonawca zatwierdzonych propozycji
  pozostają osobnymi zakresami. `docs/architecture.md` dopisuje consent gate pod
  uprawnieniami agentów; ADR-0024 nie jest oznaczany jako Accepted, bo dotyczy
  jeszcze warstwy wykonawczej B4/MCP.
- 2026-06-29T21:20+02:00: Encoding gate dla dotkniętych `.py` **OK**.
  Pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **2042 passed**, 2865 warnings. Call-site check: `AgentProposal`,
  `agent_proposals`, `CREATE_PROPOSAL_SCOPE`, `create_agent_proposal`,
  `approve_agent_proposal` występują tylko w nowym modelu/routerze/testach,
  rejestracji `app.main`/`routers.__init__` i docs. `git diff --check` bez
  błędów (tylko ostrzeżenia CRLF dla docs oraz zastanej `.claude`).
  Manual `/simplify`: bez zmian. Manual `/review`: 0 bugów korektności;
  zatwierdzenie jest idempotentne i nie wykonuje akcji domenowej. Manual
  `/security-review`: create wymaga bearer scope `agent_proposals:create`,
  approve filtruje po `owner_user_id`, cudza propozycja = 404, audyt nie kopiuje
  payloadu propozycji ani sekretów; payload jest parametryzowanym JSON w ORM,
  bez dynamicznego SQL. Realne pytania do usera: brak; UI approval i executor
  zatwierdzonych propozycji są `READY`/osobne zakresy.

## DONE - 2026-06-29 - C3 `lookup_rule` leaf-CLI (resolver `pkt X` + wyszukiwanie)

> **Status:** slice domknięty. Targeted `tests/test_lookup_rule.py` **29 passed**;
> pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **2036 passed**
> (2007 + 29), 2840 warnings, zero regresji. Smoke CLI na realnym `SZOP_Rozjemca.md`:
> `lookup_rule.py 14.d.iv` (kontratak + kontekst Szarży), `lookup_rule.py 20`
> (Przegrupowanie + 6 podpunktów), `--search osłona` → pkt 19, `11.b.iv` (3 myślniki
> w tekście rodzica), bad ref → exit 1. **TYM SAMYM wszystkie 6 narzędzi C3
> „Narzędzia MCP" są DONE** (`lookup_rule`/`explain_ability`/`validate_loadout`/
> `simulate_engagement`/`score_list`/`find_exploit_candidates`). Commit obejmuje
> 4 pliki: `scripts/lookup_rule.py` (NEW), `tests/test_lookup_rule.py` (NEW 29),
> `scripts/README.md`, `docs/roadmap.md`, ten HANDOFF.

**Zakres pracy:** ostatni niezrobiony deliverable C3 „Narzędzia MCP"
(`lookup_rule(query)`) jako skrypt-liść (ADR-0013). Wersja **strukturalna**:
parser hierarchicznej numeracji `SZOP_Rozjemca.md` (punkty 0–27, `N.`→`a.`→`i.`)
→ (1) resolver referencji `pkt X` (np. `14.d.iv`, `5.f`) zwracający dokładny
tekst punktu + kontekst rodzica + podpunkty, (2) wyszukiwanie słów kluczowych
(fold akcentów) zwracające ranking pasujących `pkt`. Bezpośrednio wspiera
workflow agentów (AGENTS [REQUIRED] #8: cytuj `pkt X` ze źródła). Pełna wersja
RAG (embeddingi nad DOCX, sqlite-vec) pozostaje gated na C2.

**Wybór zadania:** zamyka ostatni leaf-CLI z pięciu rodzeństwa C3
(`explain_ability`/`validate_loadout`/`simulate_engagement`/`score_list`/
`find_exploit_candidates` DONE); wzorzec w pełni ustalony, zero interakcji z
userem, bezzależnościowe, mieści się w oknie. Kontynuacja parenta minimalizuje
ryzyko kolizji z równoległymi agentami.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload/API: N/A — skrypt-liść CLI, bez routerów.
- JS render / CSS / template: N/A.
- CLI/scripts: `scripts/lookup_rule.py` (NEW), `scripts/README.md` (sekcja C3).
- Testy: `tests/test_lookup_rule.py` (NEW — czysty parser/resolver/search +
  tryby CLI, bez DB/sieci; fixtura tekstowa + smoke na realnym pliku reguł).
- Dokumentacja: `docs/roadmap.md` (C3 checkbox), `scripts/README.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. CLI parsuje jeden
plik reguł (~210 linii) w pamięci; brak nowych query w requestach UI.

**Plan:**
- [x] 1. Napisać `scripts/lookup_rule.py` (parser + resolve_ref + search + CLI).
- [x] 2. Testy `tests/test_lookup_rule.py` (czyste funkcje + tryby CLI + smoke real).
- [x] 3. Weryfikacja: targeted pytest, pełny `pytest -q`, smoke CLI na realnym pliku.
- [x] 4. DoD: `/simplify`; `/review`/`/security-review` warunkowo; doc sync; diff review.
- [x] 5. Zaktualizować HANDOFF/roadmap/README finalnym statusem.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) nietykane. Pełny RAG (semantyczny) = C2, świadomie odłożony.

**Wykonane kroki / odkrycia:**
- 2026-06-29: `scripts/lookup_rule.py` (NEW, stdlib only) — `parse_rules(text)`
  parsuje hierarchię po wcięciu tabami (0=punkt, 1=litera, 2=rzymski); linie
  głębsze (myślniki 4. poziomu, pkt 11.b.iv) i bez poprawnej etykiety doklejane
  jako kontynuacja tekstu bieżącego punktu. `normalize_ref` (zdejmuje „pkt",
  końcową kropkę, wewnętrzne spacje), `resolve_ref`, `search_rules` (fold NFKD +
  casefold, wszystkie tokeny jako substring, ranking po liczbie wystąpień,
  remis = kolejność dokumentu). Render czytelny (kontekst rodzica → punkt →
  podpunkty) + `--json` (schema `szop.lookup_rule/v1`). CLI: `<ref>`/`--search`/
  `--list`/`--limit`/`--json`/`--rules-file`; exit 0/1/2 spójnie z rodzeństwem.
- 2026-06-29: Edge case'y potwierdzone empirycznie ze źródła w tej sesji:
  separator SPACJĄ po etykiecie (pkt 20.e `SZOP_Rozjemca.md:148`), tab WEWNĄTRZ
  tekstu (pkt 14.e `:111`), myślniki 4. poziomu (pkt 11.b.iv `:79-81`). Fixtura
  testowa odwzorowuje wszystkie trzy.
- 2026-06-29: Pierwszy targeted ujawnił `SyntaxError` — użyłem prostego `"` jako
  danych w stringu `"..."` (AGENTS [CRITICAL] #4 w odwrotną stronę). Fix:
  typograficzny `”` (U+201D) jako dane. Po fixie targeted **29 passed**.
- 2026-06-29: `/simplify` — 1 redukcja (wspólny helper `_print_json` zamiast 3×
  `json.dumps(..., ensure_ascii=False, indent=2)`). Re-run targeted **29 passed**.
  `/review`/`/security-review` pominięte warunkowo: skrypt-liść stdlib-only,
  read-only parse jednego pliku reguł, brak DB/auth/HTTP/SSOT-mutacji/hot-path,
  brak dynamicznego eval/exec/SQL; pełne pokrycie (parser/resolver/search/CLI +
  smoke real). Call-site check: nowe symbole tylko w skrypcie/testach; nazwa
  `parse_rules` istnieje też w `app/services/army_rules.py`, ale to inny moduł
  (skrypt ładowany standalone przez importlib) — brak kolizji namespace.
- 2026-06-29: `git diff --check` bez błędów (tylko CRLF dla docs i zastanej
  `.claude/settings.local.json`, której nie dotykam). Realne pytania do usera: brak.

## DONE - 2026-06-29T06:14+02:00 - rewalidacja i commit C3 `find_exploit_candidates`

**Zakres pracy:** domknąć zastany, niezatwierdzony slice C3
`find_exploit_candidates(army_id)` przez ponowny diff review, testy, smoke i commit
wyłącznie plików tego slice'a. Nie zaczynam B4/MCP ani nowego zakresu, bo working
tree ma już kompletny leaf-CLI z poprzedniej sesji. `.claude/settings.local.json`
pozostaje lokalną, zastaną zmianą poza zakresem.

**Wybór zadania:** kontynuacja istniejącego parenta minimalizuje ryzyko konfliktu z
równoległymi agentami i kończy konkretny krok roadmapy C3 bez interakcji z userem.
Następne B4/MCP jest większym strumieniem, a `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) pozostają nietykane.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - bez zmian schematu; CLI czyta istniejące `Army`/`Roster`.
- Backend payload/API: N/A - brak routerów, tylko leaf-CLI.
- JS render / CSS / template: N/A.
- Testy: targeted `tests/test_find_exploit_candidates.py` + powiązane C3 + pełny pytest.
- Dokumentacja: ten HANDOFF, `docs/roadmap.md`, `scripts/README.md`, review file.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Rewalidowany CLI robi
offline round-robin; nie dodaje query do requestów UI ani pętli renderu.

**Plan:**
- [x] 1. Przejrzeć zastany diff i potwierdzić, że zakres dotyczy tylko C3.
- [x] 2. Uruchomić targeted C3 i pełny pytest.
- [x] 3. Wykonać call-site check, smoke real DB, manual `/simplify`/`/review`/`/security-review`.
- [x] 4. Zacommitować wybrane pliki slice'a bez `.claude/settings.local.json`.
- [x] 5. Zaktualizować HANDOFF i memory finalnym statusem.

**Otwarte kwestie:** brak `BLOCKED(user)`. Realne decyzje użytkownika nie są potrzebne
dla rewalidacji/commita. Przyszły HTTP/MCP wrapper nadal czeka na C1/B4.

**Wykonane kroki / odkrycia:**
- 2026-06-29T06:04+02:00: `git status --short` pokazuje niezatwierdzony slice
  `find_exploit_candidates` (`scripts/find_exploit_candidates.py`,
  `tests/test_find_exploit_candidates.py`, `docs/handoffs/code-review/REVIEW_2026-06-29.md`,
  `scripts/README.md`, `docs/roadmap.md`, ten HANDOFF) oraz zastaną
  `.claude/settings.local.json`. Diff kodu jest zgodny z opisem C3: leaf-CLI
  deleguje pary do `simulate_engagement`, ranking liczy `win_rate/points`, brak
  routerów i brak zapisu wyników do DB.
- 2026-06-29T06:06+02:00: Targeted C3 po eskalacji `.venv` poza sandboxem
  (WindowsApps/Odmowa dostępu w sandboxie):
  `tests/test_find_exploit_candidates.py tests/test_score_list.py tests/test_simulate_engagement.py`
  **40 passed**, 797 warnings.
- 2026-06-29T06:08+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` po eskalacji:
  **2007 passed**, 2840 warnings.
- 2026-06-29T06:13+02:00: Call-site check: nowe symbole
  `find_exploit_candidates`, `rank_candidates`, `CandidateScore`, `PairResult`,
  `results_to_payload`, `candidate_rosters` występują tylko w nowym skrypcie,
  testach i dokumentacji/review. `git diff --check` bez błędów (tylko ostrzeżenia
  CRLF dla dotkniętych docs i zastanej `.claude`). Smoke real DB:
  `find_exploit_candidates.py --list` exit 0 (Gwardia id=1 ma 6 rozpisek) oraz
  `find_exploit_candidates.py 1 -n 1 --bot priority --top 3` exit 0 w 13.6s.
- 2026-06-29T06:14+02:00: Manual `/simplify`: bez zmian kodu; po wcześniejszym
  review redundancja `if scores:` jest już usunięta. Manual `/review`: 0 bugów
  korektności; agregacja obustronna i sortowanie pokryte testami, a seed per-para
  jest praktycznie rozłączny względem `PLAYER_SEED_OFFSET`. Manual
  `/security-review`: brak auth/sekretów/dynamicznego SQL, DB read-only poza
  standardowym bootstrapem schematu; przyszły HTTP/MCP wrapper nadal wymaga
  scope/consent w C1/B4. Commit obejmuje wyłącznie pliki slice'a C3; zastana
  `.claude/settings.local.json` pozostaje poza zakresem i poza commitem.

## DONE - 2026-06-29T01:24+02:00 - C3 `find_exploit_candidates(army)` leaf-CLI

Sesja autonomiczna. Implementuję ostatni nieзrobiony deliverable C3 „Narzędzia MCP":
`find_exploit_candidates(army_id)` jako skrypt-liść (ADR-0013). Decyzja usera
2026-06-26 rozstrzygnięta: turniej kandydatów do ręcznej weryfikacji (nie
automatyczna diagnoza exploitu). Round-robin nad ISTNIEJĄCYMI rozpiskami JEDNEJ
armii z DB → ranking wg `win_rate` i `win_rate/points` (exploit_score, jak
`exploit_hunt`). Reuse `simulate_engagement` pairing (SSOT). Read-only DB,
`user_id=None`. Zakres: `scripts/find_exploit_candidates.py` (NEW),
`tests/test_find_exploit_candidates.py` (NEW), `scripts/README.md`, `docs/roadmap.md`.
Różni się od `exploit_hunt` (losowe efemeryczne rozpiski z jednostek) i `score_list`
(jedna rozpiska vs pole). `LOCKED` (Dywersant, raw combat rolls, `models_mode=per_copy`)
nietykane.

**Aktualizacja 2026-06-29T01:02:42+02:00:** kontynuuje istniejacy zakres
`find_exploit_candidates`. Przed kodem sprawdzam wzorce `score_list`,
`simulate_engagement`, `exploit_hunt`, testy skryptow C3 oraz call-site'y
funkcji, ktore beda reuzyte.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - tylko odczyt istniejacych `Army`/`Roster`.
- Backend payload/API: N/A - skrypt-lisc, bez endpointu.
- JS render / CSS / template: N/A.
- Testy: nowy targeted `tests/test_find_exploit_candidates.py`, plus pelny pytest.
- Dokumentacja: `scripts/README.md`, `docs/roadmap.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Skrypt CLI robi
offline turniej nad istniejacymi rozpiskami jednej armii; koszty symulacji sa
kontrolowane parametrem `--games`, a DB jest czytana raz do zebrania kandydatow.

**Plan:**
- [x] 1. Przeczytac wzorce CLI/testow i potwierdzic reuse SSOT.
- [x] 2. Zaimplementowac `scripts/find_exploit_candidates.py` jako cienki wrapper
  nad `simulate_engagement`/`LocalClient`, bez zapisu do DB.
- [x] 3. Dodac regresje dla rankingu, filtrow, JSON/markdown i bledow CLI.
- [x] 4. Zsynchronizowac `scripts/README.md` i `docs/roadmap.md`.
- [x] 5. Weryfikacja: targeted pytest, pelny pytest, call-site check, manual
  `/simplify`, manual `/review` jesli diff >50 linii, diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant, raw combat rolls
i `models_mode=per_copy` pozostaja nietykane.

**Wykonane kroki / odkrycia:**
- 2026-06-29T01:10+02:00: Przeczytano `score_list.py`,
  `simulate_engagement.py`, `exploit_hunt.py` oraz ich testy. Najmniejszy reuse:
  nowy skrypt robi round-robin istniejacych rozpisek jednej armii, a pojedyncze
  pary deleguje do `simulate_engagement` (czyli do `LocalClient.simulate_roster_ids`
  i adaptera ORM->engine). Ranking = `win_rate / points * 100`, jak
  `exploit_hunt.RosterScore.exploit_score`, ale bez generowania transient rosterow.
- 2026-06-29T01:18+02:00: Pierwszy targeted pytest nowego pliku odpalony poza
  sandboxem (standardowy problem WindowsApps). Wynik: 1 failure w asercji testu
  `rank_candidates` - dane testowe tworzyly remis `exploit_score`; poprawiam
  scenariusz testowy, nie logike produkcyjna.
- 2026-06-29T01:13+02:00: `scripts/find_exploit_candidates.py` i
  `tests/test_find_exploit_candidates.py` dodane. Targeted
  `tests/test_find_exploit_candidates.py`: 16 passed, 330 warnings.
- 2026-06-29T01:14+02:00: Zsynchronizowano `docs/roadmap.md` (C3 checkbox DONE)
  i `scripts/README.md` (sekcja uzycia + testy). Zaczynam weryfikacje C3 i pelny
  pytest.
- 2026-06-29T01:15+02:00: Powiazany targeted C3
  `tests/test_find_exploit_candidates.py tests/test_score_list.py tests/test_simulate_engagement.py`:
  40 passed, 797 warnings.
- 2026-06-29T01:24+02:00: Pelny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  2007 passed, 2840 warnings. Call-site check: `find_exploit_candidates`,
  `rank_candidates`, `CandidateScore`, `PairResult`, `results_to_payload`,
  `candidate_rosters` uzywane tylko w nowym skrypcie/testach/docs; nowy call-site
  `simulate_engagement` jest `scripts/find_exploit_candidates.py` i deleguje do
  juz przetestowanej sciezki. `git diff --check` bez bledow (tylko CRLF warnings,
  plus zastana `.claude/settings.local.json`). Smoke real DB: `--list` exit 0
  (Gwardia ma 6 rozpisek); `Gwardia -n 1 --bot priority --top 3` exit 0 w 13.4s.
  Proba smoke z `--bot random` na tej samej armii przekroczyla 3 min i zostala
  ubita przez timeout; nie zostal proces w tle. Manual `/simplify`: 0 zmian,
  agregacja zostaje cienka nad `simulate_engagement`. Manual `/review`: 0 bugow;
  diff >50 linii pokryty 16 testami nowego modulu + pelna suita. Manual
  `/security-review`: brak dynamicznego SQL, DB tylko read-only przez SQLAlchemy,
  brak sekretow/auth, `user_id=None` zgodne z narzedziem balansu; przyszly HTTP/MCP
  wrapper nadal musi dodac scope/consent w C1/B4. Realne pytania do usera: brak.

## DONE - 2026-06-28T21:17:25+02:00 - C1 quota aktywnych agent-tokenow per owner

**Zakres pracy:** drobne utwardzenie zakończonego C1 agent-token API:
limit liczby aktywnych (niecofniętych i niewygasłych) tokenów per owner przed
utworzeniem kolejnego tokenu. To zamyka low-backlog z poprzedniego security review
bez ruszania B4 battle API, MCP servera ani UI.

**Wybór zadania:** kontynuacja istniejącego `faza-b-engine-mvp` i ostatniego
zakresu C1 minimalizuje ryzyko konfliktu z równoległymi agentami. Zmiana jest
samodzielna, nie wymaga decyzji usera, przybliża bezpieczne API pod B4/C MCP i
nie dotyka zasad gry ani pozycji `LOCKED`.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - użycie istniejących kolumn `owner_user_id`,
  `revoked_at`, `expires_at`.
- Backend payload/API: `app/routers/agent_tokens.py` - walidacja quota przy
  `POST /agent_tokens`.
- JS render / CSS / template: N/A.
- Testy: `tests/test_agent_tokens_router.py` - regresja limitu i brak efektów
  ubocznych po odrzuceniu.
- Dokumentacja: ten HANDOFF; jeśli kontrakt API wymaga doprecyzowania, ADR-0025
  lub roadmap/architecture zostaną zsynchronizowane.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Dodatkowe
zapytanie `COUNT` dotyczy wyłącznie administracyjnego `POST /agent_tokens`; brak
wpływu na istniejące endpointy UI, listy rozpisek lub pętle silnika.

**Plan:**
- [x] 1. Potwierdzić wzorce routera/testów i encoding gate dla dotkniętych `.py`.
- [x] 2. Dodać helper quota w routerze przed generowaniem sekretu/agenta.
- [x] 3. Dodać testy: limit aktywnych tokenów, cofnięte/wygasłe nie blokują.
- [x] 4. Uruchomić targeted pytest i pełny `pytest -q` fallback z `-X utf8`.
- [x] 5. Call-site check + manual `/simplify`, `/review`, `/security-review`,
  diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant, raw combat rolls
i `models_mode=per_copy` pozostają nietykane.

**Wykonane kroki / odkrycia:**
- 2026-06-28T21:02:35+02:00: Bootstrap wykonany przez pamięć automatyzacji,
  `.agents/skills/load-context/SKILL.md`, `AGENTS.md`, `HANDOFF.md`, oba aktywne
  handoffy, `docs/handoffs/README.md`, `docs/roadmap.md`, `docs/planning.md`,
  `docs/testing.md`, `docs/developing.md`. Working tree: tylko zastana
  `.claude/settings.local.json`.
- 2026-06-28T21:02:35+02:00: `rg` call-site/context potwierdził, że
  `app/routers/agent_tokens.py` jest jedynym miejscem tworzenia tokenów, a
  `require_agent_scope` ma tylko testowych konsumentów. Limit można wpiąć lokalnie
  w `create_agent_token`.
- 2026-06-28T21:05:00+02:00: Encoding gate dla
  `app/routers/agent_tokens.py` i `tests/test_agent_tokens_router.py` przeszedł
  (`utf8-ok`) po eskalacji `.venv` poza sandboxem; sandboxowy Python zwrócił
  `WindowsApps`/`Odmowa dostępu`.
- 2026-06-28T21:08:00+02:00: Dodano lokalny limit
  `_MAX_ACTIVE_TOKENS_PER_OWNER = 20` w `app/routers/agent_tokens.py`. Limit
  liczy tylko tokeny ownera z `revoked_at IS NULL` i `expires_at > now`, przed
  wygenerowaniem raw sekretu oraz przed utworzeniem `User(role=agent)`. Testy
  pokrywają przekroczenie quota bez efektów ubocznych oraz ignorowanie tokenów
  cofniętych/wygasłych.
- 2026-06-28T21:10:00+02:00: Targeted
  `tests/test_agent_tokens_router.py tests/test_agent_token_security.py`:
  **20 passed**, 183 warnings. Zsynchronizowano kontrakt w ADR-0025,
  `docs/architecture.md` i `docs/roadmap.md`: quota aktywnych tokenów nie jest
  już deferred; deferred zostaje tylko czasowe rate-limit mintowania.
- 2026-06-28T21:13:00+02:00: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1991 passed**, 2510 warnings.
- 2026-06-28T21:17:25+02:00: Manual `/simplify` wykonał 1 redukcję: usunięto
  osobny helper `_active_token_count` i zostawiono jedno lokalne
  `_enforce_active_token_quota`. Po zmianie re-run targeted:
  **20 passed**, 183 warnings; re-run pełny: **1991 passed**, 2510 warnings.
  Call-site check: `create_agent_token` ma wywołania tylko w routerze/testach,
  `require_agent_scope` i istniejące endpointy UI bez wpływu. Manual `/review`:
  0 bugów korektności; quota jest przed generowaniem sekretu, `flush` i audytem.
  Manual `/security-review`: owner-scope zachowany, cudze tokeny bez oracle,
  odrzucone przekroczenie quota nie tworzy `User(role=agent)`, `AgentToken` ani
  `AgentAuditLog`; raw token nadal tylko w udanym `POST`. `git diff --check`
  bez błędów (tylko ostrzeżenia CRLF dla docs i zastanej `.claude`). Realne
  pytania do usera: brak. Następny zakres techniczny pozostaje B4 battle API
  lub MCP server/ADR-0021.

## DONE - 2026-06-28 (sesja autonomiczna, doc-only) - ADR-0025 spisany (rola agent + scoped tokens)

Drugi task tej sesji: **ADR-0025** (`docs/adr/0025-agent-scoped-tokens.md`, Accepted)
spisuje zaimplementowaną infrastrukturę agent-token, która w indeksie roadmapy
miała status `—` mimo że schema + helper + endpointy są DONE. ADR dokumentuje:
(1) rolę `agent` obok cookie-session UI (`is_admin` dalej źródłem uprawnień UI),
(2) `AgentToken` z `token_hash` (raw token nigdy w DB, zwracany raz), (3) scope
JSON-set `*`/konkretny + walidacja regex/dedup/wildcard-exclusivity, (4)
`require_agent_scope` dependency (401/403, naiwny UTC, lekki `AgentPrincipal`),
(5) audyt bez sekretów (`_redacted_mapping`), (6) owner-only endpointy
(`POST`/`GET`/`DELETE`, 404 bez oracle, idempotentny revoke), (7) brak Alembic.
Zaktualizowano indeks ADR w `docs/roadmap.md` (0025 `—`→`✓`), linię C1 ADR oraz
ref w `docs/architecture.md`. **Zero zmian w kodzie produkcyjnym** → pytest gate
N/A (doc-only); pełna suita zielona z poprzedniego taska (1989 passed). Pliki:
`docs/adr/0025-agent-scoped-tokens.md` (NEW), `docs/roadmap.md`,
`docs/architecture.md`, ten HANDOFF. ADR-0021/0024 nadal `—` (warstwa konsumenta
MCP + consent-gated writes — przyszły zakres).

## DONE - 2026-06-28 (sesja autonomiczna, commit) - C1 agent token endpoints zacommitowane

## DONE - 2026-06-28 (sesja autonomiczna, commit) - C1 agent token endpoints zacommitowane

**Stan:** poprzednie sesje ukonczyly, zweryfikowaly i zrecenzowaly slice C1 agent
token endpoints, ale go **nie zacommitowaly** ("Commit nie wykonany w tej sesji").
Ta sesja domyka higiene: re-weryfikacja + commit na `Faza_A` (bez push, workflow
projektu). Re-weryfikacja przed commitem: targeted
`tests/test_agent_tokens_router.py tests/test_agent_token_security.py` **18 passed**;
pelny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **1989 passed**,
2383 warnings. Diff bez zmian wzgledem zrecenzowanego stanu (REVIEW_2026-06-28.md,
0 bugow korektnosci). Commit obejmuje 7 plikow slice'a (router + testy + rejestracja
`app/main.py`/`app/routers/__init__.py` + docs roadmap/architecture + REVIEW + ten
HANDOFF). `.claude/settings.local.json` swiadomie poza commitem (zastana lokalna
allowlista). Brak `BLOCKED(user)`; `LOCKED` (Dywersant, raw combat rolls,
`models_mode=per_copy`) nietykane. Nastepny zakres: konsumenci B4/MCP tokenow.

## DONE - 2026-06-28T06:10:37+02:00 - weryfikacja i domkniecie C1 agent token endpoints

**Zakres pracy:** zastany working tree zawiera kompletny slice
`app/routers/agent_tokens.py` + testy i dokumentacje opisane juz nizej jako DONE.
Ta sesja nie rozpoczyna drugiego zadania; domyka stan przez review diffu,
ponowna weryfikacje testami i zapis ustalen.

**Wybor zadania:** endpointy tokenow sa najblizszym krokiem B4/C1 i juz sa w toku
w working tree. Kontynuacja minimalizuje ryzyko konfliktu z rownoleglymi agentami
i przybliza plan B API + C MCP bez dotykania zasad gry ani UI.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A - brak nowych kolumn, uzycie istniejacych tabel.
- Backend payload/API: `app/routers/agent_tokens.py`, rejestracja w `app/main.py`
  i `app/routers/__init__.py`.
- JS render / CSS / template: N/A.
- Testy: `tests/test_agent_tokens_router.py` oraz istniejące testy token security.
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Brak zmian w
petlach renderu i brak nowych query w istniejacych endpointach UI.

**Plan:**
- [x] 1. Przejrzec zastany diff i call sites bez cofania cudzych zmian.
- [x] 2. Uruchomic targeted testy C1 token endpoints/security.
- [x] 3. Uruchomic pelny `pytest -q` fallback z `-X utf8`.
- [x] 4. Wykonac manual `/simplify`, `/review` i `/security-review` dla auth API.
- [x] 5. Zaktualizowac HANDOFF/memory finalnym statusem i realnymi pytaniami.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant i raw combat rolls
nie sa dotykane ani podnoszone.

**Wykonane kroki / odkrycia:**
- 2026-06-28T06:03:31+02:00: Bootstrap zakonczony; memory automatyzacji nie
  istnialo. Aktywne handoffy przeczytane. `aideas-knowledge-base` ma status
  Ready for archive i blokuje tylko `AIdeas/`. `git status --short` pokazuje
  zastany uncommitted slice token endpoints oraz `.claude/settings.local.json`,
  ktorej nie dotykam.
- 2026-06-28T06:08:00+02:00: Diff review zastanego slice'a bez poprawek kodu:
  router addytywny, owner-only dla list/revoke, raw token tylko w odpowiedzi
  `POST`, docs zsynchronizowane. Nowe untracked pliki potwierdzone:
  `app/routers/agent_tokens.py`, `tests/test_agent_tokens_router.py`,
  `docs/handoffs/code-review/REVIEW_2026-06-28.md`.
- 2026-06-28T06:07:30+02:00: Targeted po eskalacji `.venv` poza sandbox
  (`WindowsApps`/Store Python w sandboxie zwrocil `Odmowa dostepu`):
  `tests/test_agent_tokens_router.py tests/test_agent_token_security.py` -
  **18 passed**, 56 warnings.
- 2026-06-28T06:09:00+02:00: Pelny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` po eskalacji:
  **1989 passed**, 2383 warnings.
- 2026-06-28T06:10:00+02:00: Call-site check `rg` dla `agent_tokens`,
  `create_agent_token`, `list_agent_tokens`, `revoke_agent_token`,
  `require_agent_scope`, `hash_agent_token`: nowy router jest rejestrowany tylko
  w `app.main`/`app.routers.__init__`; istniejace endpointy UI nadal korzystaja
  z cookie-session auth, a `require_agent_scope` nie ma nowych konsumentow.
  `git diff --check` exit 0, tylko CRLF warnings dla docs i zastanej `.claude`.
- 2026-06-28T06:10:30+02:00: Manual `/simplify`: brak lokalnej redukcji bez
  obnizenia czytelnosci; defensywna walidacja scope zostaje. Manual `/review`:
  0 bugow korektnosci. Manual `/security-review`: owner-only list/revoke,
  raw token tylko w create response, DB/audit bez sekretu, cudzy revoke = 404.
  Residual low backlog: quota/rate-limit liczby agent-tokenow per owner.
  Commit nie wykonany w tej sesji; `.claude/settings.local.json` pozostaje
  zastana lokalna zmiana i nie jest dotykana.
- 2026-06-28T06:10:37+02:00: Memory automatyzacji zapisane w
  `C:\Users\mlis\.codex\automations\szop-codzienna-autonomiczna-sesja\memory.md`.
  Brak realnych pytan do usera dla tego slice'a; nastepny techniczny krok to
  commit wybranych plikow C1 albo rozpoczecie osobnego B4 API/MCP wrapper zakresu.

## DONE — 2026-06-28 — C1 agent token management endpoints

**Zakres pracy:** addytywny slice C1/B4: JSON endpointy zarządzania tokenami
agentów (`POST /agent_tokens`, `GET /agent_tokens`, `DELETE /agent_tokens/{id}`).
Wykorzystuje istniejące tabele `AgentToken`/`AgentAuditLog` oraz helper
`hash_agent_token()`. Endpoint tworzy surowy bearer token tylko raz w odpowiedzi,
a w DB zapisuje wyłącznie hash. Nie podłącza jeszcze endpointów bitew/B4 ani MCP
servera.

**Wybór zadania:** roadmap C1 ma już gotowy schemat i runtime dependency
`require_agent_scope(scope_name)`, a otwarte pozostają endpointy tokenów. To
mały, dobrze określony krok przybliżający dwufalowy kierunek B API + C MCP bez
ruszania reguł gry, UI ani LOCKED decyzji. `aideas-knowledge-base` ma status
Ready for archive i nie jest dotykany.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A — używa istniejących tabel `users`,
  `agent_tokens`, `agent_audit_logs`.
- Backend payload/API: nowy router JSON `app/routers/agent_tokens.py` i
  rejestracja w `app/main.py`.
- JS render / CSS / template: N/A — brak UI, tylko API.
- Testy: nowy moduł `tests/test_agent_tokens_router.py` + targeted auth tests.
- Dokumentacja: `docs/roadmap.md`, `docs/architecture.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Endpointy robią
operacje administracyjne na małej tabeli tokenów: listowanie tokenów ownera,
utworzenie usera-agent + tokena oraz cofnięcie tokena po `owner_user_id`. Brak
nowych query w istniejących requestach UI i brak zmian w pętli silnika.

**Plan:**
- [x] 1. Potwierdzić wzorce auth/routerów, wykonać encoding gate i dodać router.
- [x] 2. Dodać testy tworzenia/listowania/cofania tokenów, scope validation,
  brak raw sekretów w DB oraz kontrolę uprawnień owner/admin.
- [x] 3. Zarejestrować router i zsynchronizować roadmap/architecture.
- [x] 4. Weryfikacja: targeted pytest, pełny `pytest -q`, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review` (diff >50/auth API),
  manual `/security-review`, diff review; re-run pytest jeśli przegląd coś zmieni.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant, raw combat rolls
i post-MVP `models_mode=per_copy` nie są dotykane ani podnoszone. Decyzja
produktowa czy dodać UI dla tokenów pozostaje poza zakresem; API wystarcza pod
przyszły MCP/HTTP wrapper.

**Wykonane kroki / odkrycia:**
- 2026-06-28T01:03:50+02:00: Bootstrap autonomiczny zakończony: memory brak,
  przeczytano `AGENTS.md`, `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`,
  oba aktywne handoffy, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md`, `docs/testing.md` oraz aktualne sekcje `docs/architecture.md`.
  `git status --short` pokazuje tylko zastaną `.claude/settings.local.json`
  (nietykana). Wybrano kontynuację parenta `faza-b-engine-mvp`.
- 2026-06-28T01:03:50+02:00: `rg` potwierdził brak istniejącego routera
  `/agent_tokens`; `AgentToken`/`AgentAuditLog` są używane w modelach,
  migracjach, testach i `security.require_agent_scope`. Istniejące routery UI
  nadal korzystają z cookie-session `get_current_user()` oraz `User.is_admin`.
- 2026-06-28T01:12: Encoding gate UTF-8 dla istniejących `.py` przeszedł po
  eskalacji `.venv` poza sandbox (`utf8-ok`; Store Python zwrócił `Odmowa
  dostępu`). Dodano `app/routers/agent_tokens.py` oraz rejestrację w
  `app/main.py`/`app/routers/__init__.py`. Endpointy są addytywne i JSON-only:
  tworzenie tokenu, listowanie własnych tokenów, cofanie własnego tokenu.
- 2026-06-28T01:22: Dodano `tests/test_agent_tokens_router.py`: tworzenie zwraca
  raw token tylko raz i zapisuje wyłącznie hash; listowanie filtruje po
  `owner_user_id`; cofnięcie cudzego tokenu daje 404; cofnięcie własnego jest
  idempotentne; walidacja scope odrzuca pusty/niepoprawny zakres i kombinację
  `*` + scope szczegółowy. Pierwszy targeted znalazł lukę pustej listy scope po
  mutacji payloadu; `_validate_scopes` utwardzony. Ponowiony targeted
  `tests/test_agent_tokens_router.py tests/test_agent_token_security.py`:
  **16 passed**, 53 warnings.
- 2026-06-28T01:28: Zsynchronizowano `docs/roadmap.md` i
  `docs/architecture.md`; C1 endpointy tokenów oznaczone jako DONE, konsumenci
  B4/MCP nadal osobny zakres. Test rejestracji `app.main` dopięty do
  `tests/test_agent_tokens_router.py`. Targeted po tej zmianie:
  **17 passed**, 55 warnings.
- 2026-06-28T01:34: Call-site check `rg` dla `agent_tokens` /
  `create_agent_token` / `revoke_agent_token` / `require_agent_scope`: nowy
  router jest importowany tylko przez `app.main` i `app.routers.__init__`;
  istniejący `require_agent_scope` bez zmian. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1988 passed**, 2382 warnings.
- 2026-06-28T01:44: Manual `/simplify`: dodano domenową straż
  `_validate_scopes` dla `len(scopes) > 20`, niezależną od walidacji Pydantic,
  plus regresję na zmutowany payload. Targeted po zmianie:
  **18 passed**, 56 warnings. Pełny re-run pytest:
  **1989 passed**, 2383 warnings.
- 2026-06-28T01:49: Manual `/review`: router jest addytywny, bez zmian
  istniejącego UI auth; `GET/DELETE` filtrują po `owner_user_id`, a `POST`
  tworzy dedykowanego agenta bez hasła użytkowego. Manual `/security-review`:
  raw bearer token wraca tylko w odpowiedzi `POST`, DB trzyma wyłącznie
  `hash_agent_token(raw)`, listowanie nigdy nie zwraca `token`, revoke cudzego
  tokenu daje 404 bez oracle, scope ma whitelist/limit, expiry 1-365 dni, audyt
  create/revoke nie zawiera sekretu. Residual risk do przyszłych B4/MCP: przy
  włączeniu CORS lub UI dla tokenów trzeba wrócić do CSRF/UX potwierdzeń.
  `git diff --check` bez błędów (tylko CRLF warnings dla dotkniętych docs i
  zastanej `.claude/settings.local.json`); `rg "[ \t]+$"` na nowych plikach bez
  wyników. `rg` stale statusów token endpointów bez wyników poza historycznymi
  sekcjami DONE, których nie przepisujemy.

## DONE — 2026-06-27 — C3 `score_list(roster_id)` leaf-CLI (commit na `Faza_A`)

> **Status:** slice domknięty i zacommitowany. Targeted
> `tests/test_score_list.py tests/test_simulate_engagement.py` **24 passed**;
> pełny `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **1979 passed**
> (1963 + 16). Smoke CLI na realnej `data/szop.db`: `score_list.py 10 --vs "11,14" -n 2`
> → exit 0, poprawny raport (siła w polu + per-przeciwnik win-rate + sygnał koszt↔wynik).
> Commit obejmuje 5 plików: `scripts/score_list.py` (NEW), `tests/test_score_list.py`
> (NEW 16), `scripts/README.md`, `docs/roadmap.md`, ten HANDOFF.

**Zakres pracy:** deliverable C3 `score_list(roster_id)` (roadmap „Narzędzia MCP")
jako skrypt-liść (ADR-0013), zgodnie z decyzją usera 2026-06-26: ocena rozpiski =
**agregacja wyników symulacji bitwy** przeciw POLU pozostałych rozpisek z DB.
Reuse `scripts/simulate_engagement.py` (pairing SSOT) + `LocalClient.simulate_roster_ids`
(B5). Read-only DB, `user_id=None` (narzędzie balansu). Wrapper MCP/HTTP gated C1/B4.
Później interpretacja dedykowanego agenta (poza zakresem tego slice).

**Wybór zadania:** ostatni nieзrobiony C3 leaf-CLI z czterech rodzeństwa
(`explain_ability`/`validate_loadout`/`simulate_engagement` DONE); decyzja usera
rozstrzygnięta (agregacja symulacji), zero interakcji, mieści się w oknie, wzorzec
w pełni ustalony przez sibling `simulate_engagement`. `find_exploit_candidates` to
osobny (turniej) deliverable, nie ten slice.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload/API: N/A (skrypt-liść CLI, brak routerów).
- JS render / CSS / template: N/A.
- CLI/scripts: `scripts/score_list.py` (NEW), `scripts/README.md` (sekcja C3).
- Testy: `tests/test_score_list.py` (NEW — czyste funkcje agregacji/renderu +
  ścieżka DB seeded SQLite + parity z `LocalClient` + błędy CLI).
- Dokumentacja: `docs/roadmap.md` (C3 checkbox), `scripts/README.md`, ten HANDOFF.

**Performance gate:** poza hot path `/quote`/`/rosters/{id}`. Koszt = N gier ×
(liczba przeciwników) symulacji offline w procesie CLI; brak nowych query w
requestach UI ani zmian w pętli silnika.

**Plan:**
- [x] 1. Napisać `scripts/score_list.py` (reuse simulate_engagement pairing + agregacja pola).
- [x] 2. Testy `tests/test_score_list.py` (czyste funkcje + DB seeded + błędy CLI).
- [x] 3. Weryfikacja: targeted pytest, pełny `pytest -q`, smoke CLI na `data/szop.db`.
- [x] 4. DoD: `/simplify`; `/review`/`/security-review` warunkowo; doc sync; diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant, raw combat rolls,
`models_mode=per_copy` nie są dotykane ani podnoszone. **Follow-up (NIE blokujący):**
interpretacja wyniku przez dedykowanego agenta (decyzja usera 2026-06-26) = osobny
zakres po C1/B4 (serwer MCP + endpointy). Sygnał koszt↔wynik w raporcie jest
heurystyczny (wzór >50% jak `exploit_hunt`), nie automatyczna diagnoza.

**Wykonane kroki / odkrycia:**
- 2026-06-27: Start slice po bootstrapie. Working tree: zacommitowany helper
  agent-token (`600051f`), zastana lokalna zmiana `.claude/settings.local.json`
  (nietykana). Potwierdzono wzorzec siblinga `simulate_engagement` + sygnaturę
  `LocalClient.simulate_roster_ids` + `SimulationSummary` (wins_p0/p1/draws/total_rounds).
- 2026-06-27: `scripts/score_list.py` (NEW) — `score_list(session, roster_id, ...)`
  ocenia rozpiskę (zawsze owner 0) przez N gier vs każdy przeciwnik w polu
  (`_select_opponents`: wszystkie poza self, opcjonalnie `--vs`/`--army`); każdy
  pairing deleguje do `simulate_engagement` (SSOT). Agregacja `aggregate_score` →
  `ScoreSummary` (wins/losses/draws/win_rate/avg_rounds). Raport: per-przeciwnik
  win-rate + Δpkt, „siła w polu" + bar, sygnał koszt↔wynik (vs tańsi/drożsi).
  Czyste funkcje agregacji/renderu testowalne bez DB.
- 2026-06-27: `tests/test_score_list.py` (NEW 16): agregacja z perspektywy owner 0,
  render pola + sygnał kosztu + puste pole, `_select_opponents` (self/`--vs`/`--army`),
  ścieżka DB seeded SQLite (pole, parity z `simulate_engagement`, determinizm,
  unknown target), CLI (`--list`, scoring, brak roster, unknown roster, bad `--vs`,
  unknown bot). Targeted **16 passed**; z siblingiem **24 passed**; pełny **1979 passed**.
- 2026-06-27: Smoke CLI realna DB `score_list.py 10 --vs "11,14" -n 2 --seed 1` → exit 0.
  Drobna korekta odmiany („gier"→`_games_label`) po smoke. Doc sync:
  `docs/roadmap.md` (C3 `score_list` `[x]`), `scripts/README.md` (sekcja C3).
  `git diff --check` bez błędów (tylko CRLF dla docs). DoD: `/simplify` bez zmian
  (reuse SSOT, minimalny patch); `/review`/`/security-review` pominięte warunkowo
  (skrypt-liść read-only DB, brak hot-path/SSOT-mutacji/auth/write/dynamic SQL).

## DONE — 2026-06-27 — C1/B4 agent token runtime helper (commit na `Faza_A`)

> **Status:** slice domknięty i zacommitowany. Sesja autonomiczna 2026-06-27 domknęła
> w pełni ukończoną, zweryfikowaną i zrecenzowaną (manual `/simplify`+`/review`+`/security-review`),
> ale niezacommitowaną pracę z wcześniejszej sesji. Re-weryfikacja przed commitem:
> targeted `tests/test_agent_token_security.py tests/test_registration_control.py
> tests/test_db_schema_migrations.py` **29 passed**; pełny
> `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q` **1963 passed**, 2030 warnings.
> Modele potwierdzone (`AgentToken.agent_user/owner_user`, `USER_ROLE_AGENT`, `token_hash`,
> `scope_json`, `expires_at/revoked_at/last_used_at`); `get_db` import obecny. Commit obejmuje
> 5 plików jednego slice: `app/security.py`, `tests/test_agent_token_security.py`,
> `docs/architecture.md`, `docs/roadmap.md`, ten HANDOFF. `.claude/settings.local.json`
> świadomie poza commitem (zastana lokalna allowlista). Szczegóły niżej.

**Zakres pracy:** minimalny runtime nad istniejącym schematem B2
`AgentToken`/`AgentAuditLog`: helper hashujący token, dependency
`require_agent_scope(scope_name)` do weryfikacji bearer tokena i zapis audytu
bez sekretów. Ten slice nie dodaje endpointu generowania tokenów, nie zmienia
session-cookie UI auth i nie włącza jeszcze pełnego `app/routers/battles.py`.

**Wybór zadania:** roadmap wskazuje B4/C1 jako następny główny kierunek po B2,
a HANDOFF ma `READY` dla runtime: hash bearer tokena, porównanie hasha i
redakcja sekretów w `AgentAuditLog.params_json`. To mały, dobrze odcięty krok,
bez potrzeby decyzji użytkownika, który domyka praktyczny fundament pod
przyszłe endpointy agentowe bardziej niż kolejny doc-only cleanup.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A — używa istniejących tabel `agent_tokens` i
  `agent_audit_logs`, bez nowych kolumn.
- Backend payload/API: helper/dependency w `app/security.py`; brak nowych
  routerów i brak zmian istniejących odpowiedzi JSON.
- JS render / CSS / template: N/A.
- Testy: nowe/rozszerzone testy bezpieczeństwa dla poprawnego tokena, scope,
  tokenów wygasłych/cofniętych, brakującego bearer i audytu bez sekretów.
- Dokumentacja: roadmap/architecture/HANDOFF po sukcesie.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`. Dependency będzie
wykonywać jeden lookup po `AgentToken.token_hash` na endpoint agentowy, który go
użyje; kolumna `token_hash` jest unikalna, a ten slice nie dodaje wywołań w
istniejących requestach UI ani w pętlach silnika.

**Plan:**
- [x] 1. Potwierdzić obecny wzorzec auth, modele token/audit i call sites.
- [x] 2. Wykonać encoding gate dla edytowanych `.py`, dodać helper hash/scope/audit.
- [x] 3. Dodać testy regresyjne dla tokenów i audytu.
- [x] 4. Weryfikacja: targeted pytest, pełny `pytest -q`, call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review` (auth helper), manual
  `/security-review`, diff review; re-run pytest jeśli przegląd coś zmieni.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant i raw combat rolls
nie są dotykane ani podnoszone. Endpoint generowania tokenu i konsument B4 API
pozostają przyszłym, osobnym zakresem.

**Wykonane kroki / odkrycia:**
- 2026-06-27T21:04:05+02:00: Bootstrap automatyzacji zakończony: przeczytano
  memory, `AGENTS.md`, `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`,
  oba aktywne handoffy, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md` i `docs/testing.md`. `aideas-knowledge-base` ma status
  `Ready for archive` i blokuje tylko `AIdeas/`; pracę prowadzę w parent
  `faza-b-engine-mvp`. `git status --short` pokazuje tylko zastaną lokalną
  zmianę `.claude/settings.local.json`, której nie dotykam.
- 2026-06-27T21:04:05+02:00: `rg` potwierdził, że `AgentToken`/`AgentAuditLog`
  występują tylko w modelu, migracji/testach/docs, a istniejące routery nadal
  używają cookie-session `get_current_user()` i `User.is_admin`. Slice będzie
  addytywny: nowy helper nie przepina UI auth.
- 2026-06-27T21:08: Encoding gate UTF-8 dla `app/security.py` i testów auth
  zaliczony po eskalacji lokalnego `.venv` poza sandbox (`utf8-ok`; Store Python
  w sandboxie zwrócił `Odmowa dostępu`). Dodano w `app/security.py` osobny
  agentowy path auth: `hash_agent_token()`, `AgentPrincipal`,
  `require_agent_scope(scope_name)`, parsing scope JSON, aktualizację
  `last_used_at` i zapis `AgentAuditLog` z redakcją parametrów zawierających
  sekrety. Istniejący `get_current_user()` i cookie-session UI auth bez zmian.
- 2026-06-27T21:14: Dodano `tests/test_agent_token_security.py`: sukces z
  audytem, wildcard scope, brak bearer, brak scope, token wygasły/cofnięty i
  token przypięty do nie-agentowego usera. Targeted pytest nowego modułu:
  **8 passed**, 25 warnings (pozostałe ostrzeżenia ze starego `TimestampMixin`).
  Rozszerzony targeted auth/DB
  `tests/test_agent_token_security.py tests/test_registration_control.py
  tests/test_db_schema_migrations.py`: **29 passed**, 51 warnings.
- 2026-06-27T21:13: Zsynchronizowano `docs/roadmap.md` i `docs/architecture.md`:
  C1 `require_agent_scope(scope_name)` oznaczone jako DONE, a endpointy
  generowania/listowania tokenów i konsumenci B4 API pozostają otwarte.
- 2026-06-27T21:15: Manual `/simplify`: `AgentPrincipal` budowany przed
  `db.commit()`, żeby nie polegać na atrybutach ORM po wygaśnięciu obiektu;
  dodano rollback przy błędzie zapisu audytu. Po zmianie ponowiono targeted
  nowego modułu (**8 passed**) oraz rozszerzony auth/DB (**29 passed**).
- 2026-06-27T21:18: Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1963 passed**, 2030 warnings. Call-site check:
  `require_agent_scope`/`hash_agent_token` występują w `app/security.py`,
  nowych testach i docs; brak istniejących routerów-konsumentów, więc UI auth
  bez zmian. `git diff --check` bez błędów (tylko standardowe ostrzeżenia CRLF
  dla `.claude/settings.local.json` i dotkniętych docs). Zastana
  `.claude/settings.local.json` nadal nietykana.
- 2026-06-27T21:19: Manual `/review`: helper jest addytywny, ma jeden lookup po
  unikalnym `token_hash`, zwraca lekki `AgentPrincipal` zamiast ORM usera i nie
  zmienia `get_current_user()`. Manual `/security-review`: raw bearer token nie
  jest persystowany, `AgentToken` porównywany po hashu, expired/revoked/non-agent
  odrzucane, brak scope daje 403 bez aktualizacji `last_used_at`, audyt sukcesu
  redaguje parametry zawierające `authorization`/`token`/`password`/`secret`/
  `api_key`. Residual future risk: endpointy z body zawierającym sekrety muszą
  mieć osobną redakcję, jeśli kiedyś trafią do `params_json`.

## DONE — 2026-06-27 — C3 DB-read CLI schema bootstrap hardening (commit na `Faza_A`)

> **Status:** slice domknięty i zacommitowany. Re-weryfikacja przed commitem (sesja autonomiczna 2026-06-27): targeted **32 passed**, pełny pytest **1955 passed**, smoke CLI (`validate_loadout`/`simulate_engagement` `--list`) na realnej `data/szop.db` exit 0 bez pre-fix tracebacka. Szczegóły niżej.

**Zakres pracy:** mały hardening błędu zapisanego w `HANDOFF.md` po C3
`validate_loadout`: standalone skrypty-liście czytające domyślną bazę
(`validate_loadout`, `simulate_engagement`, `exploit_hunt`) otwierają
`SessionLocal` bez standardowego bootstrapu `init_db()`. Na lokalnej
`data/szop.db` sprzed ostatnich addytywnych migracji kończy się to surowym
tracebackiem SQLAlchemy zamiast działania jak aplikacja po starcie.

**Wybór zadania:** kontynuacja istniejącego parenta B/C, dobrze określony bug
z poprzedniego LOG SESJI, bez decyzji usera, przybliża używalność narzędzi C3
i B5 DB-backed `LocalClient` bez ruszania większego zakresu auth/B4. AIDEAS ma
status `Ready for archive` i nie jest dotykany.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A — brak nowych kolumn/tabel; tylko wywołanie
  istniejącego `init_db()` przed sesją CLI.
- Backend payload/API: N/A — brak routerów i JSON API.
- CLI/backend scripts: `scripts/validate_loadout.py`,
  `scripts/simulate_engagement.py`, `scripts/exploit_hunt.py`, ewentualnie
  wspólny helper bootstrapu.
- JS render / CSS / template: N/A.
- Testy: istniejące testy trzech skryptów plus regresja, że CLI woła bootstrap
  i testy nadal nie dotykają `data/szop.db`.

**Performance gate:** poza hot path `/quote` i `/rosters/{id}`; dotyczy tylko
uruchomienia procesów CLI. Koszt to jednorazowe `init_db()` przed pracą
skryptu, zgodne ze startupem FastAPI (`app.main`). Brak dodatkowych query w
requestach aplikacji i brak zmian w pętlach silnika.

**Plan:**
- [x] 1. Potwierdzić call sites DB-read CLI i obecny wzorzec testów z podmienionym
  `SessionLocal`.
- [x] 2. Dodać minimalny wspólny helper albo lokalne wywołanie bootstrapu schematu
  przed otwarciem sesji w trzech skryptach.
- [x] 3. Rozszerzyć testy CLI tak, aby bootstrap był wymagany, ale w testach był
  no-op i nadal używał seeded in-memory SQLite.
- [x] 4. Weryfikacja: targeted pytest dla trzech skryptów, pełny `pytest -q`,
  call-site check.
- [x] 5. DoD: manual `/simplify`, manual `/review` jeśli diff >50 linii, manual
  `/security-review` jeśli zmiana zostanie uznana za DB/user-input risk; diff review.

**Otwarte kwestie:** brak `BLOCKED(user)`. `LOCKED`: Dywersant i raw combat rolls
nie są dotykane ani podnoszone. Zmiana świadomie może wykonać standardowe,
addytywne migracje istniejącej lokalnej bazy przy uruchomieniu tych CLI, tak jak
robi to aplikacja.

**Wykonane kroki / odkrycia:**
- 2026-06-27T01:03:03+02:00: Bootstrap automatyzacji zakończony: przeczytano
  memory, `AGENTS.md`, `.agents/skills/load-context/SKILL.md`, `HANDOFF.md`,
  oba aktywne handoffy, `docs/handoffs/README.md`, `docs/roadmap.md`,
  `docs/planning.md` i `docs/testing.md`. `git status --short` pokazuje tylko
  zastaną lokalną zmianę `.claude/settings.local.json`; nie jest dotykana.
  `rg` potwierdził trzy C3/D3 skrypty z bezpośrednim `SessionLocal` bez `init_db()`:
  `validate_loadout.py`, `simulate_engagement.py`, `exploit_hunt.py`.
- 2026-06-27T01:10: Dodano `scripts/db_bootstrap.py` z context managerem
  `initialized_session()` (`init_db()` → `SessionLocal()`), a trzy skrypty
  DB-read używają go w `main()`. Zakres bootstrapu jest wspólny i zgodny ze
  startupem aplikacji; rdzeń walidacji/symulacji pozostaje bez zmian.
- 2026-06-27T01:15: Testy CLI `validate_loadout`, `simulate_engagement` i
  `exploit_hunt` podmieniają teraz jednocześnie `app.db.init_db` (no-op/licznik)
  oraz `app.db.SessionLocal` (seeded in-memory SQLite). Regresje pinują, że
  `main()` wywołuje bootstrap, ale testy nadal nie dotykają `data/szop.db`.
- 2026-06-27T01:22: Targeted pytest
  `tests/test_validate_loadout.py tests/test_simulate_engagement.py
  tests/test_exploit_hunt_db.py`: **32 passed**, 652 warnings. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1955 passed**, 2005 warnings.
- 2026-06-27T01:27: Manual `/simplify`: jedna korekta komentarza w
  `tests/test_exploit_hunt_db.py` (stary opis bezpośredniego importu `SessionLocal`
  po przejściu na helper). Po tej korekcie ponowiono targeted pytest:
  **32 passed**, 652 warnings oraz pełny pytest: **1955 passed**, 2005 warnings.
- 2026-06-27T01:30: Smoke CLI importu bez dotykania DB:
  `validate_loadout.py --help`, `simulate_engagement.py --help`,
  `exploit_hunt.py --help` — wszystkie exit 0 i pokazują parser argparse.
- 2026-06-27T01:32: Call-site check `rg "initialized_session|SessionLocal"`:
  trzy skrypty DB-read (`validate_loadout`, `simulate_engagement`, `exploit_hunt`)
  używają `initialized_session()`. `scripts/db_bootstrap.py` jest jedynym nowym
  miejscem bezpośredniego `SessionLocal` dla tego wzorca. Pozostałe bezpośrednie
  użycia poza zakresem: `profile_quote.py` ma własny startup FastAPI przed sesją,
  `battle_replay.py` i `analyze_battle.py` dotyczą trybu `--from-db` event-logu
  i nie czytają katalogów jednostek/rosterów, które wywoływały crash po migracjach.
- 2026-06-27T01:34: Manual `/review` (diff >50 linii): helper nie przyjmuje
  danych usera, importuje `init_db` lazy w czasie użycia, zamyka sesję przez
  context manager; zmienione `main()` nie zmieniają rdzenia diffu/symulacji.
  Testy izolują lokalną bazę przez patch `init_db` + in-memory `SessionLocal`.
  Manual `/security-review`: brak auth, sekretów i dynamicznego SQL; jedyny write
  to standardowy addytywny bootstrap/migracja schematu aplikacji, bez zależności
  od inputu CLI. `git diff --check` bez błędów (tylko ostrzeżenia CRLF dla
  `.claude/settings.local.json`/HANDOFF); `.claude/settings.local.json` to zastana
  lokalna zmiana i nie jest dotykana.
- 2026-06-27 (autonomiczny `/code-review`): 0 bugów korektności; testy
  zweryfikowane niezależnie (**32 passed**). Jedyne znalezisko: slice zmienił
  zachowanie z czysto-czytającego na bootstrap+read (`init_db()`), ale nie
  zsynchronizował docs — opisy „read-only" / „bez wołania `init_db()`" stały się
  nieprawdziwe. Naprawione w tej sesji (proste/bezpieczne): docstring
  `scripts/exploit_hunt.py` oraz trzy fragmenty `scripts/README.md`
  (sekcje `exploit_hunt`, `simulate_engagement` oraz nota przy
  `validate_loadout`). Layer Checklist tego slice nie miał wiersza „docs" — przy
  podobnych zmianach zachowania dodać sync docstring/README do checklisty.
  Pełny raporcik: `docs/handoffs/code-review/REVIEW_2026-06-27.md`.
- 2026-06-27T06:04:00+02:00: Rewalidacja autonomiczna po wznowieniu kontekstu:
  przed zamknięciem ponownie sprawdzić diff, call sites, targeted pytest i pełny
  pytest dla tego samego slice. Brak nowego zakresu funkcjonalnego; zastana
  `.claude/settings.local.json` pozostaje nietykana.
- 2026-06-27T06:10:00+02:00: Smoke `--help` wykazał jeden pozostawiony drift
  opisowy w `validate_loadout.py` (`read-only` w opisie argparse). Poprawiono
  na „diff validator bez zapisu loadoutu”, żeby nie sugerować, że CLI nie wykonuje
  bootstrapu `init_db()`. Po tej zmianie ponowić targeted i pełny pytest.
- 2026-06-27T06:16:00+02:00: Rewalidacja po poprawce opisowej zakończona.
  Targeted pytest (`tests/test_validate_loadout.py tests/test_simulate_engagement.py
  tests/test_exploit_hunt_db.py`): **32 passed**, 652 warnings. Pełny
  `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`:
  **1955 passed**, 2005 warnings. Smoke `validate_loadout.py --help` pokazuje
  już „diff validator loadoutu bez zapisu”. `rg` nie znajduje starych fraz
  `read-only diff` ani `bez wołania init_db`; `git diff --check` bez błędów
  (tylko ostrzeżenia CRLF dla zastanych/dotkniętych plików). Call-site check:
  trzy DB-read CLI używają `initialized_session()`; `analyze_battle.py` i
  `battle_replay.py` pozostają poza zakresem, bo czytają event-logi `--from-db`,
  a `profile_quote.py` ma własny startup aplikacji przed sesją.
- 2026-06-27T06:17:00+02:00: Finalny pass po znalezieniu ostatniej polskiej frazy
  „DB wyłącznie do odczytu” w docstringu `validate_loadout.py`: doprecyzowano,
  że poza bootstrapem `init_db()` skrypt nie zapisuje walidowanego loadoutu ani
  wyników diffu. Ponowiono `rg` dla fraz driftu (brak wyników), targeted pytest
  **32 passed**, pełny pytest **1955 passed**, `git diff --check` bez błędów.
  Raport `docs/handoffs/code-review/REVIEW_2026-06-27.md` zaktualizowany do
  sześciu naprawionych opisów.

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
  - DONE 2026-06-29 (`scripts/find_exploit_candidates.py` + 16 testow). Code-review
    2026-06-29 (`docs/handoffs/code-review/REVIEW_2026-06-29.md`): 0 bugow, 1 nit
    (redundantny guard `if scores:`) naprawiony inline. Schemat seedow per-para
    zweryfikowany jako rozlaczny wzgl. `PLAYER_SEED_OFFSET`.
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
