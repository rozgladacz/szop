# HANDOFF — utcnow-ssot-auth

> **Wątek:** Domknięcie SSOT naive-UTC — `security.py` inline i `agent_tokens._now()` delegują do `app/db.py::utcnow()` (redukcja 3 kopii → 1).
> **Status:** Ready for archive
> **Utworzony:** 2026-07-04
> **Ostatnia aktualizacja:** 2026-07-04

## DONE: 2026-07-04 — konsolidacja auth do `db.utcnow()`

Follow-up wątku `utcnow-deprecation` (commit `dbcd052`). `security.py:182` inline i `agent_tokens._now()` (usunięty; 2 call-site'y → `utcnow()`) delegują do SSOT `db.utcnow()`. Nieużywane importy `datetime`/`UTC` (security) i `UTC` (agent_tokens) usunięte. Netto −5 linii. Mechanicznie **no-op** (wartość naive-UTC identyczna). Pełny pytest **2081 passed**, targeted auth **20 passed**. Commit: `<this>`.

## Cel
Jeden SSOT dla „bieżący naive-UTC" (`db.utcnow()`). `app/security.py:182` (inline) i `app/routers/agent_tokens.py` (`_now()`, 2 call-site'y) delegują do niego. Usunięcie funkcji `_now` i nieużywanych importów `datetime`/`UTC`.

## Zablokowane pliki / katalogi
- `app/security.py` — inline → `utcnow()`, usunięcie importu `datetime`/`UTC`.
- `app/routers/agent_tokens.py` — `_now()` usunięty, 2 call-site → `utcnow()`, import `UTC` usunięty.

## Blokuje / Blokowane przez
- **Blokuje / Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Konsolidacja
- [x] 1.1: Encoding gate `app/security.py`, `app/routers/agent_tokens.py`.
- [x] 1.2: `security.py` — import `utcnow` z `.db`; `now = utcnow()`; usunięto `from datetime import UTC, datetime` (nieużywane).
- [x] 1.3: `agent_tokens.py` — import `utcnow` z `..db`; usunięto `_now()`; 2× `_now()` → `utcnow()`; import `from datetime import datetime, timedelta` (usunięto `UTC`).

### Faza 2 — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` pełny — **2081 passed**; targeted auth **20 passed**.
- [x] Call-site check: `grep _now` = 0, `grep now(UTC)` = 0 w plikach auth; SSOT = `db.utcnow()`.
- [x] `/simplify` — usuwa duplikację 3→1 + wrapper `_now` + nieużywane importy; 0 dalszych.
- [x] `/review` — inline: mechaniczny reuse, wartość byte-identyczna, logika expiry/revoke bez zmian.
- [x] `/security-review` — WYKONANY: expiry (`expires_at <= now`), quota, creation (`now + timedelta`), revoke (`revoked_at = utcnow()`) używają identycznej wartości → zero zmian decyzji authz / cyklu życia tokena; brak nowego user-input→DB/dynamicznego SQL/sekretów.
- [x] Diff review — 2 pliki auth, netto −5 linii; `git diff --check` czysto.

## Pliki dotknięte
- `app/security.py` — (w trakcie)
- `app/routers/agent_tokens.py` — (w trakcie)

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-07-04: naive-UTC (nie aware) — jak w [[feedback_hp_decisions]] konwencji z `utcnow-deprecation`; DB porównuje naive.

## Hipotezy / pytania otwarte
- brak.

## Jak zweryfikować
```bash
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q tests/test_agent_tokens_router.py tests/test_agent_token_security.py
```

## Decyzje
- 2026-07-04: `_now()` usunięty (nie zostawiony jako alias) — thin wrapper na SSOT to zbędna warstwa; `utcnow()` czytelne w miejscu użycia.

## Notatki / odkrycia w trakcie
*(Append-only.)*
