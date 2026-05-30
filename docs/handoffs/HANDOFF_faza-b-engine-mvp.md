# HANDOFF — faza-b-engine-mvp

> **Wątek:** Strumień B — Game Engine MVP (parent). Bootstrap (B0 założenia + 4 ADR-y) + następne podfazy B2 (modele) → B3 (rule executor) → B4 (API) → B5 (klient) → B6 (prezentacja) → B7 (test bed). Praca delegowana do sub-wątków (`faza-b-2-models`, `faza-b-3-executor`, ...).
> **Status:** In progress — B0 ✅ (commits `67740c4`+`2e01894`+`53de635`), B3 sub-wątek `faza-b-3-executor` started 2026-05-30
> **Utworzony:** 2026-05-30
> **Ostatnia aktualizacja:** 2026-05-30

## Cel

Zbudować symulator pełnej bitwy 1v1 oparty o `SZOP_Rozjemca.md` (reguły) + `SZOP_Zdolnosci.md` (mechaniki 77 zdolności). Engine headless-first (czyste funkcje + event sourcing), prezentacja opcjonalna. Pareto MVP: oddział = koło, brak orientacji modeli, ruch deklarowany (bez pathfindingu), LoS standardowy. 6 zdolności wykluczonych z MVP (Pareto trade-off; zob. `app/rulesets/v1/b_mvp_exclusions.yaml`).

Plan długofalowy: [docs/roadmap.md#strumień-b](../roadmap.md). Strumień B odblokowany przez zamknięcie Strumienia A (YAML SSOT) i A4 (pipeline drift detection — `build/geometry_classification.md` jako informational input).

## Zablokowane pliki / katalogi

**Sesja B0 (ta):**
- `app/rulesets/v1/tables.yaml` — dodajemy sekcję `b_mvp`
- `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — hand-curated 6 entries
- `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas
- `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()`
- `tests/test_b_mvp_config.py` (NEW) — exclusions + Pydantic walidacja
- `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- `docs/adr/0008-pareto-mvp.md` (NEW) — Status: Accepted
- `docs/adr/0010-event-sourced-battle-log.md` (NEW) — Status: Accepted
- `docs/adr/0010a-decision-freeze.md` (NEW) — Status: Accepted
- `docs/adr/0014-per-unit-wounds.md` (NEW) — Status: Accepted
- `docs/roadmap.md` — statusy B0 ✅ + ADR-y Accepted

**Sub-wątki B2+ (delegacja zakresów):**
- **`faza-b-3-executor`** (active od 2026-05-30, [HANDOFF](HANDOFF_faza-b-3-executor.md)) — `app/services/engine/` cały NEW pakiet (`state`/`events`/`dice`/`los`/`prediction`/`combat`/`effects`/`interrupts`/`phases`/`resolver`), `tests/test_engine_*.py` + `tests/test_los_geometry.py` + `tests/test_prediction_vs_simulation.py`, ADR-y 0011/0012/0015/0015a/0043/0044, `build/b3_action_ability_audit.md` (GATE pkt 3). Status: B3.0 preflight.
- **`faza-b-2-models`** (NIE uruchomione — odłożone do startu B4) — `app/models.py` (Battle/BattleEvent/BattleInvite/BattleSnapshot/AgentToken/AgentAuditLog + Unit.base_size_mm/base_shape), Alembic migration `XXX_add_battle_models.py`. Powód: executor pure-function (B3) nie potrzebuje ORM/DB do testów.
- **`faza-b-4-api`** — `app/routers/battles.py` (NEW). Po B3.7 + faza-b-2-models.
- **`faza-b-5-client`** — `szop_client/` (NEW pakiet). Równolegle z B4.
- **`faza-b-7-test-bed`** — `tests/fixtures/battles/*.yaml` (NEW). Po B3.7.

**Read-only przez cały Strumień B (źródła prawdy):**
- `app/static/docs/SZOP_Rozjemca.md` — reguły gry (mechaniki)
- `app/static/docs/SZOP_Zdolnosci.md` — 77 zdolności (id, typ, opis, efekty, koszt, tagi)
- `app/static/docs/SZOP.docx`, `app/static/docs/SZOP.pdf` — rules-as-prose (SSOT dla tekstu reguł)
- `app/rulesets/v1/abilities.yaml` (88 entries) — target dla drift detection (A4 pipeline)
- `app/services/costs/` — Strumień A SSOT kosztów, B nie modyfikuje

## Blokuje / Blokowane przez

- **Blokuje:** Strumień C (MCP agent — wymaga publicznego API z B4), Strumień D (agenci-boty — wymagają engine z B3).
- **Blokowane przez:** nic — Strumień A pełen (A0+A1+A2+A3+A5+A4), `build/geometry_classification.md` jest informational.

## Gałąź git

- **Branch:** `Faza_A` (kontynuujemy, bo Faza_A jeszcze nie scalona z main). Nowy branch `Faza_B` otworzymy gdy `Faza_A` zostanie zmergowany.
- **Base:** `main`

## Plan implementacji

### B0 — Pareto MVP założenia + 4 ADR-y (~1 sesja) — **DONE 2026-05-30**

**Decyzje wejściowe (z sesji 2026-05-28+2026-05-30):**

1. **SSOT split:** `SZOP_*.md` = SSOT dla engine; `SZOP.docx`/`SZOP.pdf` = SSOT dla rules-as-prose.
2. **Pareto MVP geometry:** oddział = koło. Podstawka modelu = 1 in² na punkt wytrzymałości. `radius_inches = sqrt(sum(toughness_modelu) / π)`. Bohater (id 2) liczy się jako `toughness/2`.
3. **Globalny ruch** `move_inches: 6"` z `SZOP_Rozjemca.md pkt 15.a`. Modyfikatory Szybki/Wolny (±2″) stosowane w runtime.
4. **Brak orientacji modeli** — pkt 25 SZOP_Rozjemca nieaktywowany. Jedyna zdolność wymagająca (Zwrot id 44) wykluczona.
5. **Brak pathfindingu** — ruch deklarowany przez gracza, weryfikowany jako legalny. Wymuszone ruchy: Szarża/Związanie (pkt 14.d.ii, 16) i Samolot (wykluczony).
6. **LoS standardowy** — linia z krawędzi atakującego do podstawki celu (pkt 6). Wyjątki LoS niestandardowego (Wysoki, Samolot) wykluczone.
7. **Tracking ran w oddziale — 4 kategorie** (`SZOP_Rozjemca.md pkt 17.d–18`):
   - `wounds_received` — znaczniki ran (pkt 18.c)
   - `wounds_pending` — pula nadchodzących ran (pkt 17.d.ii)
   - `wounds_pending_precise` — pula od broni Precyzyjny (pkt 17.d.i + pkt 68)
   - `melee_balance` — bilans wręcz (zadane − otrzymane, pkt 20.c)
   
   Pomijamy zdolności wprowadzające 5-tą kategorię: Zguba (id 76 — wounds_destroyed), Zemsta (id 41 — wounds_deferred).

**Lista exclusions B0 (6 abilities — hand-curated, user decision 2026-05-30):**

| id | slug | name | uzasadnienie |
|---|---|---|---|
| 29 | samolot | Samolot | minimalny ruch 30-36″ w prostej linii + LoS niestandardowy |
| 37 | wrak | Wrak | pokonanie tworzy teren z 3 cechami |
| 38 | wysoki | Wysoki | LoS sprawdzane jakby z podwyższenia |
| 44 | zwrot | Zwrot | 4 strefy 180° (przód/tył/lewo/prawo) — wymaga orientacji |
| 73 | sterowany | Sterowany | 2 znaczniki broni z osobnym ruchem |
| 77 | zuzywalny | Zużywalny | raz na grę + max 1 broń tego typu per oddział |

**Rozbieżność z A4.3 result (`build/geometry_classification.md`):** A4.3 wygenerowało automatyczną listę 3 abilities (dywersant=false-positive, precyzyjny=per_model, zwrot=facing). Tylko `zwrot` jest wspólny. Powód:
- A4.3 to **heurystyka keyword match** — sklasyfikowała `dywersant` na podstawie keyword `strefy` (chodzi o strefy rozstawienia, false positive)
- A4.3 sklasyfikowała `precyzyjny` jako `per_model`, ale w MVP obsługujemy go przez `wounds_pending_precise` (ADR-0014) — atakujący wybiera deterministyczną kolejność pokonania modeli w heterogenicznym oddziale (np. Bohater vs zwykła postać)
- A4.3 nie obejmuje wykluczeń typu `terrain_generation` (Wrak), `session_state` (Zużywalny), `tokens_on_board` (Sterowany) — to są user decisions wykraczające poza geometric classification heuristyki

`b_mvp_exclusions.yaml` jest **hand-curated authoritative list** dla engine; `geometry_classification.md` zostaje jako informational artifact A4 pipeline.

**Kroki B0:**

- [x] B0.1: `app/rulesets/v1/tables.yaml` — dodaj sekcję `b_mvp` (move_inches=6, base_area_inches_sq_per_toughness=1, pi_approx)
- [x] B0.2: `app/rulesets/v1/b_mvp_exclusions.yaml` (NEW) — 6 entries z {slug, reason, category}
- [x] B0.3: `app/services/rulesets/models.py` — `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas; rozszerz `RulesetTables` o opcjonalne pole `b_mvp`
- [x] B0.4: `app/services/rulesets/loader.py` — `load_b_mvp_exclusions()` z `@lru_cache`
- [x] B0.5: `tests/test_b_mvp_tables.py` (NEW) — b_mvp sekcja + helper `compute_radius`
- [x] B0.6: `tests/test_b_mvp_config.py` (NEW) — 6 entries, slug set, sanity link do abilities.yaml
- [x] B0.7: ADR-0008 (Pareto MVP), ADR-0010 (event-sourced), ADR-0010a (decision freeze), ADR-0014 (per-unit wounds) — wszystkie Status: Accepted
- [x] B0.8: `docs/roadmap.md` — B0 ✅, ADR-y 0008/0010/0010a/0014 Accepted

> **Note (2026-05-30):** GATE pkt 3 ADR-0010a (audit akcji pkt 14 ↔ aktywne zdolności z SZOP_Zdolnosci.md) przesunięty z B0.W do **B3.0.1 preflight** w sub-wątku [HANDOFF_faza-b-3-executor](HANDOFF_faza-b-3-executor.md). Powód: B0 zamknięte deliverable-side, audit to pre-implementation requirement dla B3.

### B2 — Modele danych (4 tyg, sub-wątek `faza-b-2-models`)

Per `docs/roadmap.md#b2-modele-danych`. ORM (Battle, BattleEvent, BattleInvite, BattleSnapshot, Unit.base_size_mm, AgentToken, AgentAuditLog) + runtime dataclass'y (`app/services/engine/state.py` — UnitBlob, BattleState, TerrainCircle, TerrainLine) + events (`events.py` — MoveExecuted, ShotResolved, MeleeResolved, etc.) + persistence (`persistence.py`). Alembic migration.

ADR-0010 (event-sourced) i ADR-0014 (per-unit wounds) z B0 dyktują strukturę. ADR-0042 (facing) odłożony do E3.

### B3 — Rule Executor + dice (5-7 tyg, gate: ADR-0010a + decision freeze, sub-wątek `faza-b-3-executor`) — **STARTED 2026-05-30**

Sub-wątek: [HANDOFF_faza-b-3-executor.md](HANDOFF_faza-b-3-executor.md). Status: B3.0 preflight.

Per `docs/roadmap.md#b3-rule-executor--dice`. 7 modułów + substrate: state/events (B3.0), dice (B3.1), los (B3.2), prediction (B3.3), combat (B3.4), effects+interrupts (B3.5), phases (B3.6), resolver (B3.7). ADR-y wymagane: 0011, 0012, 0015, 0015a, 0043, 0044. **GATE pkt 3 ADR-0010a (audit akcji ↔ zdolności) zrobi się w B3.0.1** (przesunięte z B0.W).

### B4 — API (3 tyg, sub-wątek `faza-b-4-api`)

`app/routers/battles.py` — 9 endpointów (invite/accept/create/get/events/actions/interrupts/simulate/replay). Pydantic schemas, optimistic locking na sequence.

### B5 — Klient gry `szop_client` (równolegle z B4)

Pakiet `szop_client/` z `Protocol GameClient` + `HttpClient` + `LocalClient` (in-process). ADR-0016.

### B6 — Prezentacja (opcjonalne, 3-4 tyg)

CLI replay, SSE stream, canvas frontend. ADR-0013.

### B7 — Test bed (2 tyg)

Golden battles `tests/fixtures/battles/*.yaml` + `tests/test_engine_regression.py`.

## Pliki dotknięte

*(wypełni się w trakcie B0)*

## Hipotezy / pytania otwarte

- **H1:** Wzór `radius = sqrt(sum(toughness)/π)` daje sensowne odległości w skali 6′×4′? Sanity: oddział 5 modeli toughness 3 → radius ≈ 2.19″ (= ~5.6 cm na realnej planszy). Wydaje się OK. Zweryfikujemy na realnych rosters w B2/B3 smoke.
- **H2:** Czy `precyzyjny` jako 4-ta kategoria ran (`wounds_pending_precise`) w MVP da się obsłużyć bez per-model granularity? Plan: atakujący wybiera index modelu do pokonania w heterogenicznym oddziale (np. Bohater vs zwykła postać). Dla homogeneous unit — kolejność nie ma znaczenia. Test w B3.
- **H3:** Czy `melee_balance` jako pojedynczy int (zadane − otrzymane) wystarczy gdy Porażenie (id 67) liczy rany ×2? Plan: stosujemy ×2 mnożnik tylko do calculation `melee_balance += dealt*2 if Porażenie else dealt`. Test w B3.

## Jak zweryfikować

```powershell
# Po B0
python -m pytest tests/test_b_mvp_config.py tests/test_b_mvp_tables.py -v
python -m pytest -q  # full suite — baseline 938 + ~6-8 nowych z B0

# Parity gate (nie powinno się zepsuć — B0 nie ruszało cost path)
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest tests/test_ruleset_parity.py
$env:OPR_RULES_BACKEND="yaml"; python -m pytest tests/yaml_backend/

# Smoke
cat app/rulesets/v1/b_mvp_exclusions.yaml  # 6 wpisów
python -c "from app.services.rulesets.loader import load_b_mvp_exclusions; print(load_b_mvp_exclusions())"
```

## Decyzje

- 2026-05-30: Slug `faza-b-engine-mvp` (krótszy, jednoznaczny). Alternatywy odrzucone: `faza-b` (zbyt ogólne), `faza-b-symulator` (PL, niespójne).
- 2026-05-30: Branch `Faza_A` (kontynuujemy do scalenia z main). Decyzja per user wcześniej.
- 2026-05-30: Lista exclusions B0 = 6 entries (samolot/wrak/wysoki/zwrot/sterowany/zuzywalny) hand-curated. A4.3 result (`build/geometry_classification.md`) informational only.
- 2026-05-30: `precyzyjny` (id 68) NIE wykluczony z MVP — obsłużymy przez `wounds_pending_precise` + atakujący wybiera index pokonania. Wbrew sugestii A4.3 (per_model).
- 2026-05-30: `b_mvp_exclusions.yaml` jako osobny plik (separation of concerns od `abilities.yaml`); engine ładuje przez `load_b_mvp_exclusions()` z lru_cache.

## Notatki / odkrycia w trakcie

- 2026-05-30: HANDOFF utworzony. Strumień A pełen (A0-A5 + A4); ADR-y 0001-0007 Accepted. ADR-y B (0008/0010/0010a/0014) do utworzenia w B0. `abilities.yaml` ma 88 entries po YAML sync z `Rozwoj` w trakcie A4. Wszystkie 6 slug-ów B exclusions audytowane jako obecne w YAML.
- 2026-05-30: B0 done (3 commits: `67740c4` ADR-y, `2e01894` deliverables, `53de635` roadmap). 4 ADR-y Accepted, `b_mvp` w `tables.yaml`, `b_mvp_exclusions.yaml` (6 entries), Pydantic + loader + testy. Parent przechodzi w tryb koordynacji sub-wątków.
- 2026-05-30: **Sub-wątek `faza-b-3-executor` started** ([HANDOFF](HANDOFF_faza-b-3-executor.md)). Decyzja: B3 leci przed pełnym B2 ORM — executor pure-function nie potrzebuje DB, minimum runtime substrate (state/events + apply_events) zrobi się w B3.0. Pełne B2 ORM (`faza-b-2-models`) odłożone do startu B4 API. GATE ADR-0010a pkt 3 (audit) → B3.0.1.
