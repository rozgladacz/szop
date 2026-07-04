# HANDOFF — utcnow-deprecation

> **Wątek:** Migracja pozostałych `datetime.utcnow()` (deprecated Py 3.12+) na istniejącą konwencję SSOT naive-UTC, bez zmiany semantyki zapisu.
> **Status:** Ready for archive
> **Utworzony:** 2026-07-04
> **Ostatnia aktualizacja:** 2026-07-04

## DONE: 2026-07-04 — migracja 9 sitów `datetime.utcnow()` → `app/db.py::utcnow()` (naive-UTC SSOT)

Zrealizowane. Helper `utcnow()` (naive UTC, `datetime.now(UTC).replace(tzinfo=None)`) w `app/db.py`; 9 przedawnionych sitów zmigrowanych: `db.py` (1), `models.py` (4 `default=` + 1 call-site), `export.py` (3, + usunięty nieużywany import `datetime`). Pliki auth (`security.py`, `agent_tokens.py`) nietknięte (już non-deprecated). **Warningi pytest: ~3074 → 14** (pozostałe to third-party `openpyxl`, nie nasz kod). Pełny pytest **2081 passed** (2079 + 2 nowe testy pinujące naive-UTC). Zero regresji, zero zmian zachowania (wartości byte-identyczne). Commit: `<this>`.

## Cel
`datetime.utcnow()` jest deprecated od Pythona 3.12 (slated for removal) i produkuje ~3000 warningów na uruchomienie pytest, zaśmiecając sygnał testów. Kodbaza już ustaliła nieprzedawnioną konwencję naive-UTC (`datetime.now(UTC).replace(tzinfo=None)` w `app/security.py:182` i `agent_tokens._now()`), a kolumny DB porównują naive datetimes (`expires_at <= now`) — więc fix musi zachować naive (aware zerwałby porównania `TypeError`). Cel: jeden SSOT helper `utcnow()` + migracja 9 przedawnionych sitów, zero zmian zachowania.

## Zablokowane pliki / katalogi
- `app/db.py` — dodanie helpera `utcnow()` + migracja call-site.
- `app/models.py` — migracja `default=` i call-site w `touch_timestamps`.
- `app/routers/export.py` — migracja 3 `generated_at`.

## Blokuje / Blokowane przez
- **Blokuje:** nic.
- **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Helper SSOT + migracja
- [x] 1.1: Encoding gate na `app/db.py`, `app/models.py`, `app/routers/export.py`.
- [x] 1.2: Dodać `def utcnow() -> datetime: return datetime.now(UTC).replace(tzinfo=None)` w `app/db.py` (+ import `UTC`).
- [x] 1.3: `app/db.py:40` → `utcnow()`.
- [x] 1.4: `app/models.py` — import `utcnow` z `.db`; `default=datetime.utcnow` (4×) → `default=utcnow`; `touch_timestamps` `now = utcnow()`.
- [x] 1.5: `app/routers/export.py` — import `utcnow`; 3× `datetime.utcnow()` → `utcnow()`; usunięty nieużywany `from datetime import datetime`.

### Faza 2 — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` pełny — **2081 passed**; warningi ~3074 → 14 (reszta third-party openpyxl).
- [x] Call-site check: `grep -rn "datetime.utcnow" app/` = 0 pozostałych; jedyne `utcnow` to nowy helper + call-site'y.
- [x] `/simplify` (manual inline): 0 zmian — jeden SSOT helper, brak duplikacji w diffie.
- [x] `/review` (inline, diff <50 linii prod, mechaniczny, poza hot-path, pełne pokrycie): 0 bugów — `default=utcnow` zero-arg callable jak wcześniej, naive semantyka pinowana testem, importy poprawne, wartości byte-identyczne.
- [x] `/security-review` — N/A (brak zmian auth/user-input→DB; timestamp-of-record, semantyka wartości bez zmian).
- [x] Diff review — 5 plików slice'a; `.claude/settings.local.json` i `REVIEW_2026-07-04.md` (obcy) poza commitem.

## Pliki dotknięte
- `app/db.py` — helper `utcnow()` + migracja 1 call-site.
- `app/models.py` — import `utcnow`; 4× `default=utcnow` + `touch_timestamps`.
- `app/routers/export.py` — import `utcnow`; 3× call-site; usunięty nieużywany import.
- `tests/test_db_utcnow.py` (NEW) — 2 testy pinujące naive-UTC (helper + kolumny DB).

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-07-04: Fix zachowuje **naive UTC** (`.replace(tzinfo=None)`), NIE migruje na timezone-aware — bo kolumny DB (`DateTime` bez `timezone=True`) porównują naive, a aware zerwałby `expires_at <= now` (`TypeError`). Konwencja już ustalona w kodzie.
- 2026-07-04: Pliki auth (`security.py`, `agent_tokens.py`) NIE są dotykane — nie są przedawnione i działają; ich konsolidacja z nowym `utcnow()` = osobny opcjonalny refaktor (nie „okazyjny" w tym slice, AGENTS [RECOMMENDED]).

## Hipotezy / pytania otwarte
- `READY` (follow-up, NIE blokujące): `security.py:182` inline i `agent_tokens._now()` mogłyby delegować do `db.utcnow()` (redukcja duplikacji), ale to zmiana plików auth → osobny slice z `/security-review`.

## Jak zweryfikować
```bash
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q
# grep -rn "utcnow" app/  → tylko definicja helpera
```

## Decyzje
- 2026-07-04: SSOT helper w `app/db.py` (nie nowy moduł) — db.py jest low-level, już importowany przez models, i jest domem timestampów rekordów.

## Notatki / odkrycia w trakcie
*(Append-only.)*
- 2026-07-04: 9 sitów zidentyfikowanych przez `grep utcnow`: `db.py:40`, `models.py:{33,34,38,95,662}`, `export.py:{244,424,444}`. Konwencja docelowa potwierdzona w `security.py:182`.
