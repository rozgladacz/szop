# HANDOFF — faza-b-2-event-store

> **Wątek:** Slice B2 — persystencja event-store (ORM `Battle` + `BattleEvent` nowe tabele + `app/services/engine/persistence.py` save/load) walidująca ZAMROŻONY schemat eventów (ADR-0010/0046) end-to-end przez prawdziwą bazę. Reszta B2 (`BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog`/kolumny `Unit`) odroczona.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## Cel

Strumień B ma kompletny silnik (B3/B3.9) emitujący 16 typów eventów z serializerem `event_to_json`/`json_to_event` (`events.py`), ale **nikt ich nie zapisuje**. B2 ORM to następny kamień milowy. Ten wątek dostarcza **rdzeń event-sourcingu po stronie persystencji**: dwie nowe tabele (`battles`, `battle_events`) + warstwę `persistence.py` (`save_events`/`load_events`), tak by ciąg `apply → events → save → load → json_to_event → apply_events` był bit-perfect (inwariant ADR-0010/0046 zweryfikowany przez DB, nie tylko in-memory). To prerekwizyt B4 API (`GET /battles/{id}/events`, optimistic locking) i B5 LocalClient.

**Zakres celowo wąski** (slice pełnego `faza-b-2-models`): tylko event-store. Modele auth/zaproszeń/snapshotów odroczone — wymagają decyzji usera + `/security-review` (scoped tokens, audit log).

## Zablokowane pliki / katalogi
- `app/models.py` (MOD — dodaję klasy `Battle`, `BattleEvent` na końcu + rejestracja w pętli `event.listen`)
- `app/services/engine/persistence.py` (NEW) — `save_events`, `load_events`
- `tests/test_engine_persistence.py` (NEW)
- `docs/adr/0050-event-store-persistence.md` (NEW) — Status: Accepted

**Read-only:** `app/services/engine/events.py` (serializer), `app/services/engine/state.py` (apply_events do replay testu), `app/db.py` (Base/SessionLocal).

## Blokuje / Blokowane przez
- **Blokuje:** B4 API (endpointy events/actions), B5 LocalClient (persystencja in-process), pełny `faza-b-2-models`.
- **Blokowane przez:** nic — serializer + engine public API gotowe.

## Brak kolizji
- `app/models.py` nie jest zablokowany przez żaden aktywny wątek (engine-mvp, order-interrupts → `engine/*`; match-runner → `agents/*`). Dodaję klasy na końcu pliku (minimalna powierzchnia konfliktu).
- `persistence.py` to NOWY plik w `engine/` — nie koliduje z lockowanymi `state/effects/events/reducers/interrupts/phases.py`.
- Tylko **nowe tabele** (`create_all` addytywne) — zero ALTER na istniejących, zero ryzyka dla `data/szop.db`.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — ORM modele (nowe tabele) — **DONE 2026-06-10**
- [x] 1.1: `Battle` (`battles`) — id, p1/p2_user_id?, p1/p2_roster_id?, winner_user_id?, current_round, rng_seed, status, events relationship. TimestampMixin.
- [x] 1.2: `BattleEvent` (`battle_events`) — append-only: id, battle_id(FK,index), sequence, event_type, payload_json(Text), timestamp. `UniqueConstraint(battle_id, sequence)`. Bez TimestampMixin.
- [x] 1.3: Rejestracja `Battle` w pętli `event.listen(... touch_timestamps)`.

### Faza 2 — persistence.py — **DONE 2026-06-10**
- [x] 2.1: `save_events(session, battle_id, events, *, flush=True) -> int`. Lokalny import `app.models` (unika cyklu). NIE commituje.
- [x] 2.2: `load_events(session, battle_id, since=0) -> list[BattleEvent]` — `select` WHERE battle_id i sequence>since ORDER BY sequence, rekonstrukcja `json_to_event(json.loads(...))`.
- [x] 2.3: Docstring z inwariantem round-trip + ADR-0010/0046/0050.

### Faza 3 — Testy — **DONE 2026-06-10 (10 testów, pytest 1504 passed)**
- [x] 3.1: round-trip `save→load` equality (smoke battle 2v2, gęsty strumień >10 eventów).
- [x] 3.2: replay-from-DB invariant: `apply_events(initial, load_events(...))` == live (11 pól blob + objectives + active_player).
- [x] 3.3: UniqueConstraint (battle_id, sequence) → IntegrityError + ten sam sequence w różnych bitwach OK.
- [x] 3.4: `since=` filtr zwraca ogon.
- [x] 3.5: pusty battle → []; save([]) → 0; cascade delete; event_type spójny z payloadem.

### Faza 4 — Weryfikacja end-to-end (Definition of Done) — **DONE 2026-06-10**
- [x] `python -m pytest tests/test_engine_persistence.py -v` — 10 passed
- [x] `python -m pytest -q` — **1504 passed** (baseline 1489 + 10 persistence + 5 równoległe match-runner; 0 regresji)
- [x] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — 156/156 (sanity)
- [x] `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` — 93/93
- [x] Call-site check — `save_events`/`load_events` nowe, brak call sites poza testami; modele nowe tabele
- [x] `/simplify` — inline 4 kąty, 0 zmian (kod czysty)
- [x] `/review` — substancja inline (correctness self-review: sequence/discriminator/since/cascade pokryte testami); brak spawnu agenta (wytyczna trybu)
- [x] `/security-review` — N/A (brak auth/user-input/route; auth-modele odroczone)
- [x] ADR-0050 Accepted + roadmap (B2 event-store ✓ + ADR index) + architecture (sekcja persistence) + parent handoff notatka
- [~] commit na `Faza_A` + `/handoff-archive faza-b-2-event-store`

## Pliki dotknięte
*(wypełni się w trakcie)*

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-10: Slice = tylko event-store (battles/battle_events). `BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog` + kolumny `Unit.base_size_mm/base_shape` ODROCZONE — auth/scoping wymaga decyzji usera + security-review; kolumny `Unit` wymagają ręcznego ALTER (brak Alembic — `_migrate_schema` w db.py), poza zakresem tego slice.

## Hipotezy / pytania otwarte
- **H1 (`READY`):** `persistence.py` w `app/services/engine/` (per roadmap B2) importuje ORM + serializer — to świadoma warstwa-granica (architektura: "ORM tylko do persistence"). Silnik (state/phases/combat...) pozostaje czysty; persistence jest jedynym modułem engine/ dotykającym DB.
- **H2 (`READY`):** Round-trip JSON: pola `tuple` (from_pos/rolls/objectives_held/dropped_statuses) → list w JSON → tuple z powrotem przez `json_to_event` (top-level list→tuple). Nested tuple w `payload` dict NIE konwertowane, ale payloady budowane z list (`list(rolls)`) → round-trip OK. Test 3.1 weryfikuje wszystkie 16 typów.
- **H3 (`WAITING(B4)`):** optimistic locking na sequence przy współbieżnym zapisie (race) — UniqueConstraint zapewnia integralność, ale retry/błąd-handling to warstwa API (B4), nie persistence.

## Jak zweryfikować
```powershell
python -m pytest tests/test_engine_persistence.py -v
python -m pytest -q
python scripts/engine_smoke_replay.py
```

## Decyzje
- 2026-06-10: Wątek utworzony (sesja codzienna autonomiczna) PO wykryciu kolizji — pierwotnie planowany orkiestrator pętli bitwy okazał się duplikatem aktywnego `faza-d-match-runner`. Pivot na niekolidujący slice B2.
- 2026-06-10: Brak Alembic w projekcie — schema z `Base.metadata.create_all` (`db.py:442`) + ręczny `_migrate_schema` dla ALTER. Nowe tabele tworzą się automatycznie i addytywnie → zero migracji, zero ryzyka dla `data/szop.db`.

## Notatki / odkrycia w trakcie
- 2026-06-10: Serializer `event_to_json`/`json_to_event` JUŻ istnieje w `events.py` (B2 deliverable zrobiony wcześniej). Ten wątek konsumuje go w warstwie DB.
- 2026-06-10: 16 typów eventów w `_EVENT_REGISTRY` (events.py): MoveExecuted, ShotResolved, MeleeResolved, ModelKilled, MoraleTestPassed, EffectApplied, InterruptTriggered, RoundEnded, StatusAdded, StatusRemoved, MeleeBalanceReset, MutexCollision, ObjectiveControlChanged, InitiativePassed, AbilityOverrideApplied, AbilityOverridesCleared.
