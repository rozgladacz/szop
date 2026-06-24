# HANDOFF — faza-c-explain-ability

> **Wątek:** Strumień C3 — leaf-CLI `scripts/explain_ability.py` — strukturalny lookup zdolności po slug/nazwie (z katalogu SSOT `app.data.abilities`).
> **Status:** In progress
> **Utworzony:** 2026-06-24
> **Ostatnia aktualizacja:** 2026-06-24

## Cel

Dać użytkownikowi/agentowi proste narzędzie „wyjaśnij zdolność X": po slug (`furia`) lub nazwie PL (`Furia`) zwraca strukturalny opis (nazwa, typ, opis, parametr X, czy zablokowana w MVP). To deliverable C3 (`explain_ability(slug)` — roadmap „Narzędzia MCP", `docs/roadmap.md:269`) w formie skryptu-liścia (ADR-0013), równolegle do `simulate_engagement.py`/`exploit_hunt.py`/`battle_replay.py`. Pełna forma MCP-tool/HTTP czeka na serwer C1/B4.

**Rozłączny z `faza-c-simulate-engagement`** (inny agent, aktywny 2026-06-24) — inny plik, inna zdolność C3, zero wspólnych plików kodu. Współdzielone docs (`scripts/README.md`, `docs/roadmap.md` sekcja C3, `HANDOFF.md` indeks) edytowane na końcu z re-readem, na innych liniach niż tamten wątek.

## W TRAKCIE — 2026-06-24 — implementacja scripts/explain_ability.py + testy

**Zakres:** nowy skrypt-liść + testy. Zero zmian w rdzeniu silnika/agentów/szop_client/costs. Czyta wyłącznie katalog SSOT `app.data.abilities` (ten sam, którego używają `costs`/UI) — bez replikacji parsowania YAML.

**Warstwy (Layer Checklist):**
- Data model / migracja: N/A.
- Backend payload / JS / CSS / template: N/A.
- Skrypt + reuse: `scripts/explain_ability.py` (NEW); reuse `app.data.abilities.{find_definition,slug_for_name,all_definitions,definitions_by_type,to_dict}` (SSOT katalog).
- Testy: `tests/test_explain_ability.py` (NEW).

**Performance gate:** brak hot path (`/quote`, `/rosters/{id}`); offline CLI; brak DB.

## Plan implementacji

### Faza 1 — Skrypt
- [x] 1.1: `scripts/explain_ability.py` — CLI: pozycyjny `ability` (slug/nazwa); `--list`, `--type TYPE`, `--json`. Reuse `app.data.abilities` SSOT.
- [x] 1.2: czyste funkcje renderu (`format_ability`, `format_list`, `ability_to_json`) — testowalne bez I/O.

### Faza 2 — Testy
- [x] 2.1: `tests/test_explain_ability.py` (16) — lookup po slug, po nazwie PL (casefold+ogonki), nieznany (exit 1), `--list`, `--type`, `--json` round-trip, render parametru X + flaga blocked.

### Faza N — Weryfikacja (Definition of Done)
- [x] `pytest -q` — targeted 16 passed; pełna suita **1909 passed** (incl. równoległy C3 simulate_engagement, 0 failed).
- [x] Call-site check — nowy skrypt-liść, brak konsumentów; czyta tylko katalog SSOT (reuse-only).
- [x] `/simplify` inline — 1 dedup (helper `_print_definitions` dla `--list`/`--type`); reszta czysta (reuse katalogu, render rozdzielony od I/O).
- [~] `/review` — pominięty warunkowo (leaf-skrypt read-only, ~190 linii, brak hot-path/SSOT-mutacji/auth/DB; pełne pokrycie 16 testami incl. JSON round-trip + fuzzy name + blocked). Inline correctness self-review wykonany.
- [x] `/security-review` — N/A (brak auth/DB/user-input→DB; tylko odczyt statycznego katalogu).
- [x] Smoke CLI — `furia` / `Podwójny` (nazwa→slug rozrywajacy) / `transport --json` / `zzz` (exit 1) OK.
- [ ] Docs: `scripts/README.md` + roadmap C3 checkbox `explain_ability` + indeks `HANDOFF.md` — **DEFER**: te 3 pliki aktywnie edytuje równoległy wątek `faza-c-simulate-engagement` (REVIEW_2026-06-24 w toku). Zrobić po zlądowaniu jego zmian, z re-readem, na liniach `explain_ability` (rozłącznych od `simulate_engagement`), by nie klobrować.

## Status końcowy (2026-06-24)
Kod + testy DONE i zacommitowane (izolowane nowe pliki, path-scoped). Pozostała wyłącznie aktualizacja 3 współdzielonych docs (DEFER — kolizja z żywym wątkiem C3). Wątek gotowy do archiwizacji po dopięciu docs.

## Zablokowane pliki / katalogi
- `scripts/explain_ability.py` (NEW) — ten wątek.
- `tests/test_explain_ability.py` (NEW) — ten wątek.

## Blokuje / Blokowane przez
- **Blokuje:** nic (leaf).
- **Blokowane przez:** nic — katalog `app.data.abilities` gotowy.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Decyzje
- 2026-06-24: źródło = `app.data.abilities` (Python dataclass katalog używany przez `costs`/UI; bogatszy: `value_label`/`value_type`/`value_choices`/`blocked`), nie surowy `abilities.yaml`. Reuse SSOT zamiast re-parsowania YAML (`abilities.yaml` to target driftu A4, nie API). `rozkaz_tak` (tylko w YAML) świadomie pominięty — poza katalogiem in-app.

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak specyficznych dla tego wątku)

## Hipotezy / pytania otwarte
- `READY` — pełna specyfikacja; SSOT katalog gotowy. Brak pytań do usera.

## Notatki / odkrycia w trakcie
- 2026-06-24: diligence read-only — katalogi SSOT zdolności **spójne**: `app/data/abilities.py` (88) == `app/rulesets/v1/abilities.yaml` (88), identyczne slugi/nazwy/typy, zero driftu. (Stąd `explain_ability` może bezpiecznie czytać sam katalog Python — autorytatywny dla in-app.)
- 2026-06-24: kandydat na kolejny leaf C3 (przyszła sesja): `score_list(roster_id)` — szybka heurystyka oceny rozpiski bez symulacji. Wymaga uzgodnienia formuły heurystyki (obecnie „quick heuristic" w roadmap jest niedoprecyzowane — NIE jest blokadą usera, ale wymaga decyzji projektowej przed implementacją, by nie była arbitralna).

## Jak zweryfikować
```bash
python scripts/explain_ability.py --list
python scripts/explain_ability.py furia
python scripts/explain_ability.py Furia --json
python -X utf8 -m pytest tests/test_explain_ability.py -q
```
