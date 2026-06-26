# HANDOFF — faza-c-validate-loadout

> **Wątek:** C3 `validate_loadout(payload)` jako read-only leaf-CLI — diff validator raw→normalized loadoutu + odrzucone/sklampowane selekcje + koszt (reuse `normalize_roster_unit_loadout` + `calculate_roster_unit_quote` SSOT).
> **Status:** Ready for archive
> **Utworzony:** 2026-06-26
> **Ostatnia aktualizacja:** 2026-06-26

## W TRAKCIE — 2026-06-26 — implementacja leaf-CLI

**Zakres pracy:** nowy `scripts/validate_loadout.py` (skrypt-liść, ADR-0013) — przyjmuje
id jednostki z DB (kontekst legalnych broni/zdolności/passive) + RAW loadout payload
(JSON z CLI / pliku) i pokazuje: (a) co `normalize_roster_unit_loadout` zaakceptowało,
(b) selekcje ODRZUCONE (id spoza dozwolonego zbioru / niepoprawne) i SKLAMPOWANE
(ujemny count → 0, zły `mode` → `per_model`), (c) koszt znormalizowanej konfiguracji
przez `calculate_roster_unit_quote`. To „dry-run" endpointu quote bez zapisu do DB.

**Wybór zadania:** decyzja usera 2026-06-26 rozstrzygnęła projekt (diff validator,
reuse istniejącego quote/normalize SSOT) → zadanie dobrze określone, bez interakcji,
realne w jednym oknie (wzorzec `explain_ability`/`simulate_engagement`). Pozostałe
C3 (`score_list`/`find_exploit_candidates`) mają niższy priorytet wg decyzji usera.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A (DB read-only, `session.get(Unit, id)`).
- Backend payload/API: N/A (skrypt-liść; wrapper MCP/HTTP gated na C1/B4).
- JS render / CSS / template: N/A.
- Testy: `tests/test_validate_loadout.py` (NEW) — seeded in-memory SQLite + czyste funkcje diff/render.
- Dokumentacja: `scripts/README.md` (sekcja C3), `docs/roadmap.md` (C3 checkbox), ten HANDOFF.

**Performance gate:** brak hot path; jedno `session.get` + czyste funkcje. Bez nowych query w runtime aplikacji.

## Cel
Domknąć deliverable C3 „Narzędzia MCP" `validate_loadout(payload)` (roadmap) jako
samodzielny skrypt-liść read-only — równolegle do `explain_ability` i `simulate_engagement`.
Wartość: agent (przyszły klient MCP, Strumień C) wysyłający loadout może z góry zobaczyć,
co zostanie zaakceptowane/odrzucone/sklampowane oraz jaki będzie koszt — bez mutacji DB.

## Zablokowane pliki / katalogi
- `scripts/validate_loadout.py` (NEW) — implementacja.
- `tests/test_validate_loadout.py` (NEW) — testy.

## Blokuje / Blokowane przez
- **Blokuje:** nic (wrapper MCP/HTTP w C1/B4 może później importować rdzeń).
- **Blokowane przez:** nic — SSOT (`normalize_roster_unit_loadout`/`calculate_roster_unit_quote`) istnieje.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Rdzeń (czyste funkcje + diff)
- [x] 1.1: `diff_section` + `validate_loadout(unit, raw, count)` — porównanie raw vs `normalize_roster_unit_loadout`; per-sekcja accepted/rejected/clamped + mode + passive.
- [x] 1.2: `validate_loadout_by_id(session, unit_id, raw)` — `session.get(Unit)`, diff + `calculate_roster_unit_quote`.
- [x] 1.3: `format_diff_report` (render tekstowy) + `diff_to_dict` (JSON, schema `szop.validate_loadout/v1`) — czyste, testowalne bez DB.

### Faza 2 — CLI + I/O
- [x] 2.1: argparse — `unit_id`, `--loadout`/`--loadout-file`, `--count`, `--list`, `--json`.
- [x] 2.2: `main()` z czystymi błędami CLI (unknown unit → rc=1, bad JSON / brak id → rc=2), UTF-8 stdout.

### Faza 3 — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — targeted **18 passed**; pełny **1955 passed** (1937 + 18).
- [x] Call-site check — skrypt-liść; `import scripts.validate_loadout` tylko w teście, brak importerów z `app/`.
- [x] `/simplify` — manualny: kod czysty, reuse SSOT (normalize/quote + helpery kanonikalizacji passive); jedyny świadomy mirror = raw-enumerator (SSOT ukrywa odrzucone id), udokumentowany. 0 zmian.
- [!] `/review` — pominięty warunkowo (skrypt-liść read-only, brak hot-path/SSOT-mutacji/auth/DB-write; pełne pokrycie testami).
- [!] `/security-review` — N/A (DB read-only `session.get`, brak user-input→DB-write, brak auth/sekretów; JSON parsowany przez `json.loads` z czystą obsługą błędu).
- [x] Smoke CLI na `data/szop.db` — `--list`, bogus loadout (mode clamp + rejected weapon/passive + koszt), empty (clean+koszt), bad json rc=2, unknown unit rc=1. **Odkrycie:** prod DB sprzed migracji `base_size_mm` → standalone CLI nie woła `init_db()`; zmigrowano bazę standardową ścieżką startową (additywne). Dotyczy też `simulate_engagement`/`exploit_hunt` (stan istniejący).
- [x] Diff review przed commitem.

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-26: `validate_loadout` = **read-only diff validator** (raw→normalized + dropped/clamped + koszt), reuse quote/normalize SSOT — decyzja usera. Wrapper MCP/HTTP gated na C1/B4. `LOCKED`: `models_mode=per_copy`, Dywersant — nie dotykane.

## Hipotezy / pytania otwarte
- `READY`: wrapper MCP/HTTP nad rdzeniem (po C1/B4).

## Jak zweryfikować
```bash
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_validate_loadout.py -q
python scripts/validate_loadout.py --list
python scripts/validate_loadout.py <unit_id> --loadout '{"weapons":{"99":1},"mode":"bad"}'
```

## Notatki / odkrycia w trakcie
- 2026-06-26: Potwierdzono kontrakt SSOT: `_procedural_quote` woła `normalize_roster_unit_loadout` wewnętrznie (quote.py:116) → koszt liczony na znormalizowanym loadoucie. Sekcje `weapons`/`active`/`aura` normalizują do `dict[str,int]` (id→count); id spoza `allowed_ids` pomijane (= odrzucone), `max(value,0)` (= clamp ujemnych), zły `mode`→`per_model`, nierozpoznane passive slugi pomijane. To baza dla diffu.
