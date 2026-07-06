# HANDOFF — template-response-signature

> **Wątek:** Migracja przedawnionego podpisu `templates.TemplateResponse(name, {"request": request, ...})` → `TemplateResponse(request, name, {...})` (Starlette deprecation), scoped do plików ZIMNYCH; hot-path `rosters.py`/`armies.py` odroczone.
> **Status:** Ready for archive (pliki zimne DONE 2026-07-06; hot-path odroczony)
> **Utworzony:** 2026-07-06
> **Ostatnia aktualizacja:** 2026-07-06

## DONE: 2026-07-06 — migracja podpisu w 6 plikach zimnych (25 call-site'ów)

Zmigrowano wszystkie 25 call-site'ów `TemplateResponse` w plikach zimnych na nowy
podpis Starlette `TemplateResponse(request, name, {...})` (request na pierwszym
argumencie pozycyjnym; `"request": request` usunięty z dicta kontekstu). Hot-path
`rosters.py` (5) + `armies.py` (21) świadomie NIETKNIĘTE (patrz Decyzje).
Weryfikacja: pełny pytest **2086 passed**, warningi **12 → 7** (5 warningów
`TemplateResponse` z zimnych szablonów zniknęło; reszta to odroczone
rosters/armies + third-party openpyxl). `git diff --check` czysto.

## Cel

Starlette deprecował `templates.TemplateResponse(name, context)` na rzecz
`TemplateResponse(request, name, context)` (warning `starlette/templating.py:178`
w pytest). Migracja jest mechaniczna 1:1: `request` przenosi się na pierwszy
argument pozycyjny, a `"request": request` znika z dicta kontekstu. Ten wątek
domyka **25 call-site'ów w 6 zimnych plikach**; 26 call-site'ów w hot-path
`rosters.py` (5) + `armies.py` (21) świadomie odroczone (patrz Decyzje).
Redukuje dług deprecacji i szum warningów pytest; utrzymuje warstwę routerów
(gdzie żyje B4) zdrowszą pod dalszy rozwój.

## Zablokowane pliki / katalogi
- `app/main.py` — 1 call-site
- `app/routers/admin.py` — 1 call-site
- `app/routers/auth.py` — 6 call-site'ów
- `app/routers/armories.py` — 13 call-site'ów
- `app/routers/export.py` — 3 call-site'y
- `app/routers/users.py` — 1 call-site

## Blokuje / Blokowane przez
- **Blokuje:** przyszły wątek migracji hot-path (`rosters.py`/`armies.py`) —
  ten wątek NIE tyka tych plików, więc kolizji brak.
- **Blokowane przez:** —

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Migracja zimnych plików (mechaniczna 1:1)
- [x] Krok 1.1: `app/main.py` (1)
- [x] Krok 1.2: `app/routers/admin.py` (1)
- [x] Krok 1.3: `app/routers/users.py` (1)
- [x] Krok 1.4: `app/routers/export.py` (3)
- [x] Krok 1.5: `app/routers/auth.py` (6)
- [x] Krok 1.6: `app/routers/armories.py` (13)

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] Encoding gate przed Edit na każdym `.py` (AGENTS [REQUIRED] #5) — 6 plików OK
- [x] `pytest -q` pełny — **2086 passed**, warningi 12→7
- [x] Call-site check: `grep "request": request` w zimnych plikach = 0; pozostałe tylko w odroczonych rosters/armies
- [x] `/simplify` — manual, 0 zmian (migracja usuwa redundancję; wzorzec = idiom frameworka)
- [x] `/review` — manual, 0 findingów (Starlette auto-wstrzykuje request do kontekstu; status_code zachowany; render zielony)
- [!] `/security-review` — N/A: tylko kolejność argumentów renderu; brak zmian auth/user-input→DB/uprawnień/SQL
- [x] Re-run `pytest -q` po fixie stubu testu — **2086 passed**
- [x] `git diff --check` czysto (tylko znane CRLF `.claude`) + diff review

## Pliki dotknięte
- `app/main.py` — 1 call-site zmigrowany
- `app/routers/admin.py` — 1
- `app/routers/users.py` — 1
- `app/routers/export.py` — 3
- `app/routers/auth.py` — 6 (inline + multiline)
- `app/routers/armories.py` — 13 (weapon_form/detail/import/list/new)
- `tests/test_weapon_deletion.py` — fake `template_response` stub zaktualizowany do
  nowego podpisu 3-arg (`request, name, context`), bo `delete_weapon` renderuje
  `armory_detail.html` (site 1052). Stub w `test_army_weapon_contexts.py` NIETKNIĘTY
  (dotyczy odroczonego `armies_router`, spójny z jego starym podpisem).

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak)

## Decyzje
- 2026-07-06: **Scope = tylko pliki zimne.** `rosters.py` (5) + `armies.py` (21)
  odroczone do dedykowanego okna bez konkurencji — backlog (HANDOFF.md,
  notatka 2026-07-05) ocenił je jako wysokie ryzyko kolizji z równoległymi
  agentami (hot-path `/quote`, `/rosters/{id}`, edytor armii). Scheduled-task
  zakłada pracę równoległą, więc mechaniczny reformat tych plików mógłby
  zderzyć się z realną zmianą funkcjonalną innego agenta. Starlette wspiera
  oba podpisy w okresie deprecacji → stan mieszany jest funkcjonalnie poprawny
  (standardowa migracja przyrostowa).
- 2026-07-06: **Transformacja kanoniczna** — `TemplateResponse(request, name, {...})`
  z USUNIĘCIEM `"request": request` z dicta kontekstu (nie tylko wstawienie
  `request` na przód). Czystszy diff, zgodny z zaleceniem Starlette.

## Hipotezy / pytania otwarte
- **Hot-path `rosters.py`/`armies.py` (26 sites):** `READY`, nie zablokowane —
  wymaga tylko okna bez konkurencji + pełnego `/review`. Osobny wątek gdy
  brak równoległych agentów na tych plikach.

## Jak zweryfikować
```bash
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q
# grep sanity: brak starego podpisu w zimnych plikach
```

## Notatki / odkrycia w trakcie
- 2026-07-06: Wzorzec jednolity we wszystkich plikach —
  `templates.TemplateResponse(NAME, {"request": request, ...}[, status_code=X])`;
  `"request": request` jest zawsze pierwszym kluczem dicta kontekstu.
