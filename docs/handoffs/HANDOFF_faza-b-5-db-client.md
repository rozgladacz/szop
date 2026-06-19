# HANDOFF — faza-b-5-db-client

> **Wątek:** B5 — DB-backed `LocalClient`: wczytuje rozpiski ORM `Roster` z sesji DB (read-only), adaptuje przez `roster_to_engine_roster` (most ORM→engine-dict gotowy) i rozgrywa je przez istniejące API silnika. Domyka odłożony slice B5 (roadmap) + slice 2b `faza-d-roster-adapter`; odblokowuje Strumień C3 `simulate_engagement`.
> **Status:** DONE (2026-06-19) — gotowy do archiwizacji
> **Utworzony:** 2026-06-19
> **Ostatnia aktualizacja:** 2026-06-19

## W TRAKCIE

- **2026-06-19 (sesja autonomiczna) — DB-backed `LocalClient` DONE.** `szop_client/local.py`: `LocalClient(session=None, user_id=None)` (opcjonalne wiązanie DB; bez sesji = wsteczna kompat) + `simulate_roster_ids`/`create_battle_from_roster_ids` (wczytują `Roster` po id, adapter SSOT `roster_to_engine_roster`, delegacja do istniejących metod engine-dict) + `_load_roster` (scoping `owner_id==user_id`, wspólny `RosterNotFoundError` braku/cudzego → brak oracle) + `_load_engine_rosters` helper. `simulate`/Protocol zyskały passthrough `deployment_zones` (D5). Warstwa-liść, zero zmian w `engine/*`/`agents/*` → brak kolizji z lockami/golden-digestami B7. Weryfikacja: pytest **1789 passed** (+7 nowych testów; 20/20 w `test_clients_local`). `/simplify` 4 kąty inline — 1 cleanup (dedup build pary rosterów → `_load_engine_rosters`). `/review`+`/security-review` inline (read-only DB, ownership-scoped, izolowana warstwa-liść; multi-agent nie uruchamiany — polityka kosztu). Commit `<this>`.
  - **Follow-up (NIE blokujące, dla wątku wpinającego C3/B4):** `user_id=None` = brak ograniczenia własności (tryb narzędzi balansu). Endpoint API wystawiający `simulate_roster_ids`/`create_battle_from_roster_ids` (C3 `simulate_engagement`, B4 routers) **musi** podać `user_id` zalogowanego usera, inaczej dowolny user mógłby symulować cudze rozpiski. Test `test_roster_ids_ownership_scoping` pinuje zachowanie scopingu.

## Cel

Roadmap B5 (linia 232) i `faza-d-roster-adapter` slice 2b wskazują `DB-backed LocalClient(db_session, user_id)` jako odłożony do czasu mostu ORM→engine-dict. Most istnieje (`roster_adapter` slice 1+2a DONE). Cel: rozszerzyć `LocalClient` o ścieżkę DB — wczytanie `Roster` po id z sesji, walidacja istnienia + (opcjonalnie) własności (`owner_id == user_id`), konwersja przez `roster_to_engine_roster` (LOCKED: `models_mode=per_copy`, filtr `b_mvp_exclusions`, attached heroes poza MVP), delegacja do istniejących metod engine-dict (`create_battle`/`simulate`). Wymienny seam `GameClient` → C3 `simulate_engagement(roster_a, roster_b, n)` może działać na realnych rozpiskach.

## Zablokowane pliki / katalogi

- `szop_client/local.py` (MOD) — DB-aware konstruktor + metody `*_roster_ids`
- `tests/test_clients_local.py` (MOD) — testy DB-path (seeded in-memory SQLite)
- `docs/roadmap.md` (MOD) — B5 status DB-backed
- `docs/architecture.md` (MOD) — sekcja szop_client

## Blokuje / Blokowane przez

- **Blokuje:** C3 `simulate_engagement` (LocalClient batch na rozpiskach z DB).
- **Blokowane przez:** nic — `roster_adapter` (slice 1+2a), `simulate_from_rosters` (+`deployment_zones`), engine public API gotowe.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

- [x] `LocalClient.__init__(self, session=None, user_id=None)` — opcjonalne wiązanie DB (wsteczna kompat: `LocalClient()` bez argów działa).
- [x] `LocalClient.simulate(..., deployment_zones=None)` — passthrough do `simulate_from_rosters` (wsteczna kompat: None = bez zmian). Protocol zsynchronizowany.
- [x] `_load_roster(roster_id)` — `session.get(Roster, id)`; `RosterNotFoundError` gdy brak; gdy `user_id` ustawione i `owner_id != user_id` → ten sam błąd (scoping, brak oracle).
- [x] `simulate_roster_ids(...)` — load+adapt+`self.simulate`.
- [x] `create_battle_from_roster_ids(...)` — load+adapt+`self.create_battle` (single-step).
- [x] Testy `tests/test_clients_local.py` (+7) — seeded in-memory SQLite (StaticPool): summary n_games==n, determinizm, parity DB↔engine-dict, create+get_state 4 bloby/obaj owner, ownership raise+pozytyw, unknown id raise, brak sesji raise.
- [x] docs (roadmap B5 DB-backed ✓, architecture szop_client).

## Pliki dotknięte

- `szop_client/local.py` (MOD)
- `tests/test_clients_local.py` (MOD)
- `docs/roadmap.md`, `docs/architecture.md` (MOD)

## Decyzje

- 2026-06-19: Konstruktor DB-aware z opcjonalnymi argami (nie osobna podklasa) — `GameClient` Protocol pozostaje spełniony, `LocalClient()` bez DB nadal działa (wsteczna kompat z B5-slice + 13 istniejących testów).
- 2026-06-19: `szop_client` NIE bakuje geometrii planszy/stref (board 72×48 itd.) — `deployment_zones`/`terrain`/`objectives` to scenariusz podawany przez wołającego (C3/test). Klient nie czyni roszczeń o regułach gry; default `deployment_zones=None` → pozycje placeholder z adaptera (wsteczna kompat).

## Decyzje zamrożone (NIE podnosić ponownie)

> Dziedziczone z `faza-d-roster-adapter` (LOCKED przez usera 2026-06-16).

- **`models_mode=per_copy` KANONICZNY** — `count` kopii = `count` niezależnych blobów po `typical_models`. Adapter default.
- **Attached heroes POZA MVP** — `parent_roster_unit_id` deferowane (E1), raportowane w `deferred_attached_heroes`.

## Jak zweryfikować

```powershell
python -m pytest tests/test_clients_local.py -q
python -m pytest -q   # pełna suita — baseline 1743 + nowe
```

## Faza Weryfikacja — Definition of Done

- [x] `pytest -q` zielony — **1789 passed** (baseline 1743 + 7 moich + testy równoległego wątku leaderboard)
- [x] Call-site check — `LocalClient(` instancjonowany tylko w `tests/test_clients_local.py` + `szop_client`; nowe parametry konstruktora opcjonalne + nowe metody addytywne → wsteczna kompat (13 istniejących testów zielone)
- [x] `/simplify` — 4 kąty inline; 1 cleanup (dedup build pary rosterów → `_load_engine_rosters`); reuse SSOT adapter, brak hot-path
- [x] `/review` — inline correctness self-review (wsteczna kompat + parity DB↔engine-dict + rozłączne id potwierdzone testami); multi-agent `/code-review` świadomie nie uruchamiany (izolowana warstwa-liść, pełne pokrycie, polityka kosztu)
- [x] `/security-review` — inline: ścieżka read-only (ORM `session.get` po int id, brak injection; adapter tylko czyta SSOT), ownership scoping bez oracle (`RosterNotFoundError` wspólny). Uwaga `user_id=None` → follow-up dla C3/B4 (sekcja W TRAKCIE)
- [x] re-run `pytest` po `/simplify` — 20/20 zielone
