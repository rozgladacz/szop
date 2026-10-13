# HANDOFF — backup-scheduler

> **Wątek:** Naprawa startu i kontroli zdrowia automatycznych kopii SZOP oraz weryfikacja produkcyjna.
> **Status:** In progress
> **Utworzony:** 2026-10-13
> **Ostatnia aktualizacja:** 2026-10-13

## Cel

Usunąć cykl importu zgłoszony na serwerze, uruchomić scheduler bez pętli restartów i potwierdzić, że powstaje spójna kopia bazy. Wdrożenie dotyczy wyłącznie stosu SZOP.

## Zablokowane pliki / katalogi

- `app/db.py` — importy usług podczas ładowania modułu
- `app/scripts/backup_loop.py` — uruchamianie schedulera
- `docker-compose.yml` — dedykowany healthcheck backupu
- `tests/test_backup_scheduler.py` — test startu i rzeczywistej kopii

## Blokuje / Blokowane przez

- **Blokuje:** brak
- **Blokowane przez:** brak

## Gałąź git

- **Branch:** `Rozwoj`
- **Base:** `origin/Rozwoj`

## Layer Checklist

- **Data model / migracja:** bez zmian.
- **Backend payload:** bez zmian; zmiana dotyczy importów usług przy starcie procesu.
- **JS render:** bez zmian.
- **CSS / template:** bez zmian.
- **Testy:** świeży proces Pythona dla importu schedulera i prawdziwa kopia SQLite.
- **Infrastruktura:** osobny healthcheck `szop-backup` w Compose.
- **Performance gate:** brak zmian w `/quote` lub `/rosters/{id}`; zero dodatkowych zapytań w hot path.
- **SSOT-check:** logika kosztów/klasyfikacji bez zmian.

## Plan implementacji

### Faza 1 — Diagnoza
- [x] Odtworzyć pełny cykl importu i sprawdzić konfigurację obrazu/Compose.
- [x] Ustalić bezpieczny wariant healthcheck schedulera.

### Faza 2 — Poprawka
- [x] Przenieść zależne importy `db.py` do miejsc użycia.
- [x] Skonfigurować healthcheck backupu i testy startu oraz tworzenia kopii.

### Faza 3 — Weryfikacja end-to-end
- [x] `pytest -q` — 332 passed.
- [x] Call-site check dla zmienionych funkcji.
- [x] `/simplify` — ręczny przegląd jakości diffu; bez zmian.
- [x] `/review` — ręczny przegląd diffu >50 linii; bez usterek blokujących.
- [x] `/security-review` — nie dotyczy; brak zmian w auth, uprawnieniach lub obsłudze wejścia użytkownika.
- [x] Ponowić pytest po ewentualnych zmianach z przeglądu — przegląd nie zmienił kodu.
- [x] Diff review.
- [~] Wdrożyć wyłącznie SZOP i potwierdzić brak restartów oraz nową kopię.

## Notatki / odkrycia w trakcie

- 2026-10-13: Łańcuch: `backup_loop → backup → db_restore → db → ability_registry → models → db.Base`; `db.py` importuje `ability_registry` przed definicją `Base`.
- 2026-10-13: `szop-backup` dziedziczy HTTP healthcheck z obrazu, chociaż nie uruchamia serwera HTTP.
- 2026-10-13: Odtworzono traceback w świeżym interpreterze. Healthcheck Compose sprawdzi PID 1 przez `/proc/1/cmdline`, bez uruchamiania drugiej kopii aplikacji w 952 MiB RAM.
- 2026-10-13: `app/db.py` występuje również w handoff rozmiar-podstawki, ale jego edycja tutaj obejmuje wyłącznie przeniesienie importów usług, bez zmiany logiki migracji lub modelu.
- 2026-10-13: Testy skupione `tests/test_backup_scheduler.py`: 3 passed. Kopia powstała z bazy w trybie WAL i przeszła `PRAGMA quick_check`.
- 2026-10-13: Pełne `pytest -x --tb=short -q`: 332 passed. Call sites: `init_db()` z `app/main.py`, `_initialize_unit_base_sizes()` z migracji w `app/db.py`; przeniesione importy wykonują się po definicji `Base`. Smoke JS nie dotyczy.
- 2026-10-13: Wdrożenie czeka na adres SSH i potwierdzenie gałęzi produkcyjnej. `main`/`v1.1.1` różnią się od `Rozwoj` o liczne funkcje; brak klucza lub konfiguracji SSH na tej stacji.
