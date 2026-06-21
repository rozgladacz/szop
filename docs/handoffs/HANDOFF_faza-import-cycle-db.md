# HANDOFF — faza-import-cycle-db

> **Wątek:** Naprawa latentnego cyklu importu `app.db` (lazy-import w `init_db`) + usunięcie workaroundów w 3 skryptach + test regresyjny.
> **Status:** Ready for archive
> **Utworzony:** 2026-06-21
> **Ostatnia aktualizacja:** 2026-06-21

## Cel
`import app.db` jako pierwszy moduł aplikacyjny rzuca `ImportError` (cykl: `app.db:11 from .services import ability_registry, costs` → `ability_registry:9 from .. import models` → `models:20 from .db import Base`, gdy `Base` jeszcze niezdefiniowany). Wykryte przy B6 (`faza-b-6-replay`). Skrypty standalone silnika (`battle_replay`/`analyze_battle`/`exploit_hunt` z `--from-db`) musiały obchodzić to ręcznym `import app.models` PRZED `app.db`. Naprawiamy źródło: lazy-import w `init_db()` (jedyne miejsce użycia obu symboli), rozrywając cykl raz na zawsze, i upraszczamy workaroundy.

## Zablokowane pliki / katalogi
- `app/db.py` — przeniesienie `from .services import ability_registry, costs` z module-level do `init_db()` (lazy).
- `scripts/battle_replay.py` — uproszczenie `replay_from_db` (usunięcie workaroundu `import app.models`).
- `scripts/analyze_battle.py` — j.w.
- `scripts/exploit_hunt.py` — j.w.
- `tests/test_db_import_cycle.py` (NEW) — regresja: `import app.db` standalone (subprocess).

## Blokuje / Blokowane przez
- **Blokuje:** nic (czysty cleanup; ułatwia przyszłe standalone-skrypty/narzędzia silnika).
- **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Fix źródła cyklu
- [x] 1.1: `app/db.py` — usunięto module-level `from .services import ability_registry, costs`; dodano lazy import w `init_db()` (obok `from . import models`). Oba symbole używane tylko w `init_db` (`ability_registry.sync_definitions`, `costs.weapon_cost`).
- [x] 1.2: Sanity — `python -c "import app.db; assert app.db.Base"` → `OK` (świeży proces). `import app.main` + `init_db` callable też OK.

### Faza 2 — Uproszczenie workaroundów
- [x] 2.1: `scripts/battle_replay.py` `replay_from_db` — usunięto `import app.models` + workaround-komentarz.
- [x] 2.2: `scripts/analyze_battle.py` `analyze_from_db` — j.w.
- [x] 2.3: `scripts/exploit_hunt.py` `main` — j.w.

### Faza 3 — Test regresyjny
- [x] 3.1: `tests/test_db_import_cycle.py` (NEW, 3 testy) — subprocess `sys.executable -c "import app.db; ..."` z `cwd=repo_root` (świeży interpreter). Pinuje: import db-first bez cyklu, `models.Base is db.Base`, lazy-import nie psuje dostępności `ability_registry`/`costs`. Nie woła `init_db()` (brak dotykania DB).

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — **1837 passed** (1834 baseline + 3 nowe), zero regresji.
- [x] Call-site check: brak `app.db.costs` / `app.db.ability_registry` jako atrybutu modułu (grep — 0 trafień; oba użyte wyłącznie w `init_db`).
- [x] Smoke: `battle_replay --from-db` + `analyze_battle --from-db` (graceful „brak eventów"/REMIS), standalone `import app.db` OK.
- [x] `/simplify` inline — 0 zmian (netto −6 linii w kodzie, brak dead code/duplikacji; lazy-import to kanoniczny fix).
- [!] `/review` — warunkowo pominięty (diff <50 linii, brak hot-path/SSOT; inline self-review wykonany).
- [!] `/security-review` — nie dotyczy (zmiana to kolejność importu; `init_db` zachowuje zachowanie, brak auth/uprawnień/user-input).
- [x] Diff review przed commitem (git diff przejrzany).

## Pliki dotknięte
- `app/db.py` — module-level `from .services import ...` → lazy w `init_db()`.
- `scripts/battle_replay.py`, `scripts/analyze_battle.py`, `scripts/exploit_hunt.py` — usunięte workaroundy `import app.models`.
- `tests/test_db_import_cycle.py` (NEW) — 3 testy regresyjne.

## Decyzje zamrożone (NIE podnosić ponownie)
- *(brak)*

## Hipotezy / pytania otwarte
- `READY` — całość to czysta inżynieria, zero decyzji usera.

## Jak zweryfikować
```bash
python -c "import app.db; assert app.db.Base"   # świeży proces — nie rzuca ImportError
python -m pytest tests/test_db_import_cycle.py -q
python -m pytest -q                              # pełna suita
python scripts/battle_replay.py --from-db 1      # smoke (graceful gdy brak bitwy)
```

## Decyzje
- 2026-06-21: Lazy-import w `init_db()` zamiast reorganizacji modułów — minimalna, odwracalna zmiana; `init_db` to jedyny konsument obu symboli, więc lazy nie zmienia zachowania normalnego bootstrapu (`app/main.py` importuje `costs` niezależnie).
- 2026-06-21: Dedykowany krótki wątek (nie parent `faza-b-engine-mvp`) — fix dotyczy `app/db.py` (infra app), poza zakresem rdzenia silnika; otwarty i archiwizowany w tej samej sesji.

## Notatki / odkrycia w trakcie
- 2026-06-21: Cykl reprodukowalny: `python -c "import app.db"` → `ImportError: cannot import name 'Base' from partially initialized module 'app.db'`. `app.services` to namespace package (brak `__init__.py`). Workaround obecny w 3 skryptach (`battle_replay:343`, `analyze_battle:606`, `exploit_hunt:601`).
