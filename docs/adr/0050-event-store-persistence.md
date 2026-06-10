# ADR-0050 — Persystencja event-store (Battle + BattleEvent + persistence.py)

- **Status:** Accepted
- **Data:** 2026-06-10
- **Kontekst:** Strumień B, wątek `faza-b-2-event-store` (slice B2). Silnik
  (B3/B3.9) emituje 16 typów eventów (`events.py`) z gotowym serializerem
  `event_to_json`/`json_to_event`, a inwariant replayu (ADR-0010/0046)
  `apply_events(initial, events) == live_state` jest zweryfikowany **in-memory**.
  Brakowało jednak warstwy **persystencji**: nikt nie zapisywał strumienia do
  bazy, więc B4 API (`GET /battles/{id}/events`, optimistic locking) i B5
  LocalClient nie miały na czym stanąć. Roadmap B2 wymienia `Battle`,
  `BattleEvent` (append-only, UniqueConstraint) oraz
  `app/services/engine/persistence.py` (`save_events`/`load_events`).

  Pełne B2 (`BattleInvite`/`BattleSnapshot`/`AgentToken`/`AgentAuditLog` +
  kolumny `Unit.base_size_mm/base_shape`) ODROCZONE: modele auth/scoping wymagają
  decyzji usera + `/security-review`, a kolumny `Unit` wymagają ręcznego ALTER
  (projekt nie używa Alembic — schema z `Base.metadata.create_all`, ręczny
  `_migrate_schema` w `db.py`). Ten ADR obejmuje wyłącznie **rdzeń event-store**.

## Decyzja

### 1. Dwie nowe tabele (addytywne, bez Alembic)

- **`battles`** (`Battle`, TimestampMixin): metadane gry — `p1/p2_user_id?`
  (nullable: bitwy botów Strumienia D nie mają człowieka po stronie),
  `p1/p2_roster_id?`, `winner_user_id?` (None = remis/w toku, pkt 5.f),
  `current_round`, `rng_seed` (determinizm replayu, ADR-0012),
  `status ∈ {pending, active, finished}` (MVP string; enum w B4). Przebieg gry
  NIE jest tu trzymany — jest event-sourced w `battle_events`.

- **`battle_events`** (`BattleEvent`, append-only): jeden wiersz = jeden engine
  event. `event_type` (nazwa klasy — discriminator dla zapytań/indeksu),
  `payload_json = json.dumps(event_to_json(e))`, `sequence`, `timestamp`.
  `UniqueConstraint(battle_id, sequence)` egzekwuje globalne uporządkowanie i
  zapobiega duplikatom (optimistic locking — retry/błąd to warstwa API B4).
  **Bez `TimestampMixin`** — event jest niemutowalny, `updated_at` nie ma sensu.

Obie tabele tworzą się automatycznie przez `create_all` (addytywne — zero
migracji, zero ryzyka dla istniejącej `data/szop.db`).

### 2. `app/services/engine/persistence.py` — warstwa-granica

Jedyny moduł `engine/` dotykający ORM (architektura: „Game engine = czyste
funkcje + event sourcing; ORM tylko do persistence"). Reszta silnika
(state/phases/combat/...) pozostaje czysta.

- `save_events(session, battle_id, events, *, flush=True) -> int` — append-only
  INSERT per event. **Transakcyjnie neutralny** (NIE commituje — caller zarządza
  transakcją). `flush=True` wymusza INSERT (egzekucja UniqueConstraint) bez
  commitu. Import `app.models` lokalny w funkcji — unika cyklu
  `engine → models → db` przy imporcie pakietu engine.
- `load_events(session, battle_id, since=0) -> list[BattleEvent]` — `select`
  WHERE `battle_id` i `sequence > since`, `ORDER BY sequence`; rekonstrukcja
  przez `json_to_event(json.loads(payload_json))`. `since=` wspiera inkrementalny
  polling (B4 `?since=N`).

### 3. Inwariant round-trip (GATE)

    save_events(session, bid, evs); loaded = load_events(session, bid)
    apply_events(initial_for_replay, loaded) == live_state

Persystencja NIE traci informacji — replay **z bazy** jest bit-perfect (rozszerza
proof-of-completeness ADR-0010/0046 o warstwę DB). Pola `tuple`
(from_pos/rolls/objectives_held/dropped_statuses) round-trip'ują przez list
(JSON nie ma tuple) z powrotem do tuple w `json_to_event`. Zweryfikowane testem
`tests/test_engine_persistence.py::test_replay_from_db_invariant` na gęstej
bitwie 2v2 (mirror `engine_smoke_replay`): 11 pól `UnitBlob` + objectives +
active_player.

## Konsekwencje

- **B4 API odblokowane** — endpointy events/actions mają persystencję + optimistic
  locking (UniqueConstraint). **B5 LocalClient** może zapisywać in-process.
- **Brak Alembic** pozostaje świadomy: kolejne NOWE tabele = bezpieczne; zmiany
  kolumn istniejących tabel wymagają wpisu w `_migrate_schema` (db.py).
- **Odroczone (osobny wątek + user + security-review):** `BattleInvite`,
  `BattleSnapshot`, `AgentToken`, `AgentAuditLog`, kolumny `Unit.base_size_mm/
  base_shape`, faktyczny `create_snapshot` (roadmap: MVP nie wywołuje snapshotów).
- **Round-trip nested tuple:** tuple zagnieżdżone w `payload` dict (EffectApplied/
  InterruptTriggered) NIE są konwertowane z list z powrotem na tuple — ale
  payloady budowane są z list (`list(rolls)`), więc round-trip pozostaje spójny.
  Gdyby przyszła zdolność wymagała tuple w payload → rozszerzyć `json_to_event`.

## Alternatywy odrzucone

- **Snapshot zamiast czystego event-sourcingu** — odrzucone (ADR-0010): MVP nie
  potrzebuje snapshotów (bitwy ≤4 rundy, krótkie strumienie); `BattleSnapshot`
  zostaje w schemacie jako opcja na później.
- **Serializacja per-typ (kolumny zamiast `payload_json`)** — odrzucone: 16 typów
  o różnych polach → rzadka, szeroka tabela; `payload_json` + discriminator jest
  zwięzły i odporny na dodawanie typów (ADR-0046 dowodzi kompletności reducerów).
- **persistence.py poza `engine/`** — roadmap B2 lokuje go w `engine/`; to
  świadoma warstwa-granica (jedyny moduł engine importujący ORM).
