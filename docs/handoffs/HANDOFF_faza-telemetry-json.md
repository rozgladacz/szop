# HANDOFF — faza-telemetry-json

> **Wątek:** Maszynowy eksport telemetrii (`--json PATH`) w `scripts/analyze_battle.py` — dict JSON metryk bitwy/agregatu (ADR-0017, box `data/battle_metrics/*.jsonl`).
> **Status:** Ready for archive
> **Utworzony:** 2026-06-21
> **Ostatnia aktualizacja:** 2026-06-21

## Cel
`scripts/analyze_battle.py` produkuje dziś tylko raport **markdown** (ludzki). ADR-0017 przewiduje też maszynowo-czytelne metryki per bitwa (`data/battle_metrics/{battle_id}.jsonl`: `action_count`, `dice_distribution`, …) dla downstream tooling/agregacji. Dodajemy `--json PATH` (additive do markdown): serializuje istniejący `BattleAnalysis`/`AggregateAnalysis` do JSON-owalnego dict (jedna linia = jeden rekord, jsonl-kompatybilny). Pola czasowe ADR-0017 (`time_per_action_ms`, `decision_time_ms`) wymagają live-instrumentacji hot-path silnika → świadomie odłożone (jak cały structlog-slice). Reuse czystej analityki — zero zmian w rdzeniu.

## Zablokowane pliki / katalogi
- `scripts/analyze_battle.py` — `analysis_to_dict`/`aggregate_to_dict`, wydzielenie compute-helperów, flaga `--json`.
- `tests/test_analyze_battle.py` — nowe testy serializerów + CLI `--json`.
- `scripts/README.md`, `docs/roadmap.md` — wzmianka `--json`.

## Blokuje / Blokowane przez
- **Blokuje:** nic (leaf tooling).
- **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Serializery + refaktor compute/render
- [x] 1.1: `analysis_to_dict`/`aggregate_to_dict` — czyste JSON-owalne dict (schema `szop.battle_metrics/v1`; morale-dice/side keys jako str; `asdict` dla unit/side stats).
- [x] 1.2: Wydzielone `_fixture_analysis`/`_fixture_aggregate`/`_db_analysis` zwracające `(obiekt, header)`; `analyze_from_*` delegują (sygnatury/zwroty bez zmian → 22 istniejące testy zielone).

### Faza 2 — CLI `--json`
- [x] 2.1: `--json PATH` (additive): `json.dumps(payload, ensure_ascii=False)+"\n"` (mkdir parents). Markdown nadal na stdout/`--out`. `--from-db --games>1` dziedziczy istniejący exit 2.

### Faza 3 — Testy + docs
- [x] 3.1: +5 testów (`analysis_to_dict` pola/serializowalność, side_stats None bez owner_map, `aggregate_to_dict`, CLI `--json` battle + aggregate).
- [x] 3.2: `scripts/README.md` (`--json` + scope) + `docs/roadmap.md` (box `data/battle_metrics` `[~]` slice, `.gitignore` `[x]`, nota cross-cutting).

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — **1842 passed** (1837 baseline + 5). `tests/test_analyze_battle.py` 27 passed.
- [x] Call-site check `analyze_from_*` — zwroty bez zmian (str), tylko testy je wołają; `main()` używa nowych `_*` helperów. Zero zewnętrznych konsumentów.
- [x] Smoke CLI: `--json` per-battle (kind=battle, side_stats, 8 units, dice 1–6) + `--games 6` (kind=aggregate) + `--from-db 999999` (graceful, events=0, side_stats=None).
- [x] `/simplify` inline — 0 zmian (compute/render split usuwa duplikację; serializery reuse `asdict`; `.get` na morale-dice świadomie defensywny).
- [!] `/review` — warunkowo pominięty (izolowany skrypt-liść, pełne pokrycie testami incl. JSON round-trip; inline self-review correctness; brak hot-path/SSOT/auth).
- [!] `/security-review` — nie dotyczy (read-only; `--json` zapisuje lokalny plik z już-publicznych danych raportu, brak auth/user-input→DB).
- [x] Diff review (244/−31; skrypt parsuje się, behavior-preserving refaktor).

## Pliki dotknięte
- `scripts/analyze_battle.py` — `analysis_to_dict`/`aggregate_to_dict`, `_fixture_analysis`/`_fixture_aggregate`/`_db_analysis` (compute split), `--json` CLI + main rewire, docstring.
- `tests/test_analyze_battle.py` (+5 testów JSON).
- `scripts/README.md`, `docs/roadmap.md` — `--json` slice + box ADR-0017.

## Decyzje zamrożone (NIE podnosić ponownie)
- *(brak)*

## Hipotezy / pytania otwarte
- `READY` — czysta inżynieria, zero decyzji usera.
- `WAITING(prereq)` — pełny ADR-0017 (structlog live-emission + pola czasowe `time_per_action_ms`/`decision_time_ms`) wymaga zmian w hot-path silnika (`resolver`/`persistence`) — poza tym slice'em; metryki strukturalne odzyskiwalne z event-logu obsłużone tu.

## Jak zweryfikować
```bash
python scripts/analyze_battle.py --json reports/m.jsonl --out reports/m.md
python -c "import json; d=json.load(open('reports/m.jsonl', encoding='utf-8')); print(d['kind'], d['rounds_played'])"
python scripts/analyze_battle.py --games 6 --json reports/agg.jsonl
python -m pytest tests/test_analyze_battle.py -q
```

## Decyzje
- 2026-06-21: `--json` additive (nie zastępuje markdown) — najmniej zaskakujące; jedna linia JSON = jsonl-kompatybilny rekord. `.gitignore` już ignoruje `data/` (box ADR-0017 spełniony bez zmiany).
- 2026-06-21: Tylko metryki odzyskiwalne z event-logu; pola czasowe odłożone z structlog-slice (hot-path).

## Notatki / odkrycia w trakcie
- 2026-06-21: `BattleAnalysis`/`AggregateAnalysis` to już czyste agregaty (slots dataclass) → serializacja przez `dataclasses.asdict` + stringifikacja kluczy dice/strona.
