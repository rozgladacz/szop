# HANDOFF — faza-a-2-dsl-quote

> **Wątek:** Sub-wątek `faza-a` — implementacja A2.4c: YAML replika `roster_unit_role_totals` (NEW `quote_yaml.py`) + body `_yaml_quote()` + fix parity-bug `transport_multiplier` (priority-first), zamknięcie luki blokującej `OPR_RULES_BACKEND=both_assert` w fazie A3.
> **Status:** In progress
> **Utworzony:** 2026-05-23
> **Ostatnia aktualizacja:** 2026-05-23 (po c.0+c.1)

## Cel

Po A2.4b (commit `a70601d`) mamy `ability_cost_components_yaml` z parity 37/37, ale `_yaml_quote()` nadal rzuca `NotImplementedError`. Bez "spinki na górze" (replika `role_totals.py:roster_unit_role_totals` + integracja w `quote.py`) parity-gate `OPR_RULES_BACKEND=both_assert` (faza A3) jest zablokowany. Ten sub-wątek zamyka tę lukę: YAML quote ma zwracać dict bit-identyczny z `_procedural_quote()` (delta ≤ 1e-3 weryfikowane smoke'm). Plan szczegółowy: `C:\Users\mlis\.claude\plans\tak-calm-meteor.md`.

## Zablokowane pliki / katalogi

- `app/services/rulesets/quote_yaml.py` (NEW) — replika `roster_unit_role_totals` + helpers (A2.4c.1)
- `app/services/rulesets/cost_functions.py` — fix `break` w `transport_multiplier` (A2.4c.0)
- `app/services/costs/quote.py` — body `_yaml_quote()` (A2.4c.2)
- Ewentualnie `app/services/rulesets/handlers.py` — ew. rozszerzenie sygnatury `ability_cost_components_yaml` o `quality/defense/weapons` (jeśli R1 wymaga)

**Read-only (oracle, nie modyfikujemy):**
- `app/services/costs/role_totals.py`, `quote.py:_procedural_quote`, `unit_helpers.py`, `abilities.py`, `weapons.py`, `_engine.py`, `passive_state.py`

## Blokuje / Blokowane przez

- **Blokuje:** A2.5 (testy formalne), A3 (parity gate), A5 (perf gate). Cały `faza-a` czeka na zamknięcie c.2.
- **Blokowane przez:** nic. Parent `faza-a` aktywny (ten sub należy do niego).

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza A2.4c.0 — Fix `transport_multiplier` priority-first ✅

- [x] Krok 0.1: Edit `cost_functions.py:147` — `break` po `multiplier = float(rule.multiplier)`
- [x] Krok 0.2: Smoke inline — `samolot+latajacy=3.5`, `latajacy=1.5`, `zwiadowca+szybki=2.5`, `set()=1.0`, `szybki=1.25` — wszystkie OK
- [x] Krok 0.3: `pytest -q` → 296/296 green, parity handlers utrzymany

### Faza A2.4c.1 — `quote_yaml.py:roster_unit_role_totals_yaml` ✅

- [x] Krok 1.0 (pre-flight): potwierdzono — `handlers.ability_cost_components_yaml` JUŻ przyjmuje `quality/defense/weapons` (handlers.py:273-275), R1 rozwiązane bez rozszerzania
- [x] Krok 1.1-1.7: NEW `app/services/rulesets/quote_yaml.py` (~440 LOC) — wszystkie closures + `_yaml_ability_cost` + orchestrator
- [x] Krok 1.8: Smoke parity inline 7/7 (synthetic, DB pusta w lokalnym env). Pokrywa: infantry, passive nieustraszony, passive zwiadowca, transport capacity, masywny (ability_multiplier=1), aura nieustraszony (parsing+dispatch), weapon via default_weapon. Wszystkie delta=0.
- [x] Krok 1.9: `pytest -q` → 296/296 green
- [ ] Commit: `A2.4c.1: quote_yaml.roster_unit_role_totals_yaml + fix transport_multiplier priority`

### Faza A2.4c.2 — `_yaml_quote()` body

- [ ] Krok 2.1: `quote.py` — importy `load_ruleset`, `roster_unit_role_totals_yaml`, `base_components_yaml` (lub inline)
- [ ] Krok 2.2: Body `_yaml_quote` — mirror `_procedural_quote` z YAML substytucjami (tabela w planie)
- [ ] Krok 2.3: `_passive_fn` closure (zbudowane raz per quote) injectowane do `cost_functions.base_model_cost`
- [ ] Krok 2.4: Section totals (weapons/active/aura) inline z `weapon_cost_yaml` + `_yaml_ability_cost`
- [ ] Krok 2.5: `item_costs.passive_deltas` (2× call `roster_unit_role_totals_yaml`) jeśli `include_item_costs=True`
- [ ] Krok 2.6: Smoke `OPR_RULES_BACKEND=both_assert` × 20 roster_units × `{include_item_costs: True, False}` — 0 `RulesetParityError`
- [ ] Krok 2.7: `pytest -q` → default procedural nadal green
- [ ] Krok 2.8: Smoke UI `make dev` pod `both_assert` — otwórz rozpiskę, sprawdź render
- [ ] Commit: `A2.4c.2: _yaml_quote() body — YAML quote bit-identyczny z procedural`

### Faza Weryfikacja end-to-end

- [ ] `pytest -q` — wszystko green (default)
- [ ] `OPR_RULES_BACKEND=yaml pytest tests/test_feature_toggle.py -v` — testy stub-ery dostosowane (NotImplementedError → faktyczny quote)
- [ ] `OPR_RULES_BACKEND=both_assert` smoke 20+ units — 0 RulesetParityError
- [ ] Update parent `HANDOFF_faza-a.md`: odznacz A2.4c, dopisz decyzje D1–D5
- [ ] `/handoff-archive faza-a-2-dsl-quote`

## Pliki dotknięte

**A2.4c.0 + c.1 (ta sesja):**
- `app/services/rulesets/cost_functions.py:147-151` — `break` w `transport_multiplier` (priority-first match, fix last-match-wins parity bug)
- `app/services/rulesets/quote_yaml.py` (NEW, ~440 LOC) — `roster_unit_role_totals_yaml` + `_yaml_ability_cost` helper. Importy whitelisted (`primitives`, `passive_state`, `unit_helpers` jako pure parsing; `cost_functions`, `dispatcher`, `handlers` jako cost math). Brak importu z `_engine`/`abilities`/`weapons`/`app/data/abilities`.

**Notatki implementacyjne:**
- R1 (pre-flight): `handlers.ability_cost_components_yaml` już akceptował `quality/defense/weapons` — nie wymagało rozszerzenia.
- DB lokalna pusta (zero rows) — smoke parity inline na synthetic units (7 distinct patterns), nie DB query. Full DB-backed parity gate przyjdzie w A3.
- Caches per-call (`_passive_entries_cache`, `_ability_cost_map_cache`) jako locals w `roster_unit_role_totals_yaml` — identyczna semantyka invalidation co oracle.
- `_yaml_ability_cost` mirroruje `unit_helpers.ability_cost`: short-circuit na `cost_hint` (gdy nie `order_like`), w przeciwnym razie `ability_cost_components_yaml(...).total` z pełnym kontekstem unit (quality/defense/weapons/toughness).

## Hipotezy / pytania otwarte

- **R1 (pre-flight):** czy `handlers.ability_cost_components_yaml` przyjmuje `quality/defense/weapons`? Jeśli nie — rozszerz w c.1. Sprawdzić przed startem.
- **R2:** dual keying w `_passive_flag_maps` — verbatim port.
- **R3:** `ARMY_RULE_OFF_PREFIX` filter w `_passive_entries` i `item_passive_deltas`.
- **R4:** `ability_multiplier = 0 if model_mult==0 else 1 if massive else model_count` — verbatim.
- **R5:** `_to_total` mode_total branching — verbatim.

## Jak zweryfikować

```powershell
# Default procedural
python -m pytest -q

# YAML backend smoke (po c.2)
$env:OPR_RULES_BACKEND="yaml"; python -c "from app.services.costs.quote import calculate_roster_unit_quote; print('YAML backend OK')"; Remove-Item Env:OPR_RULES_BACKEND

# Parity gate
$env:OPR_RULES_BACKEND="both_assert"; python -m pytest -q; Remove-Item Env:OPR_RULES_BACKEND
```

## Decyzje

- 2026-05-23: Sub-wątek utworzony zgodnie z planem `tak-calm-meteor.md`. Split A2.4c na c.0+c.1+c.2 — każdy ma własny smoke gate przed commitem.
- 2026-05-23 (planowane D1–D5, do wpisania do parent HANDOFF po archiwizacji):
  - D1: split c.1+c.2 (nie bigbang).
  - D2: fix `transport_multiplier` priority-first w scope A2.4c (c.0).
  - D3: reuse `normalize_roster_unit_loadout` + `compute_passive_state` (Q1/Q2 pure parsing).
  - D4: capacity parsing inline w `_effective_passive_cost_yaml` (mirror oracle, nie ekstrahuj).
  - D5: `_ROLE_SLUGS` lokalnie w quote_yaml.py (no-engine-import).

## Notatki / odkrycia w trakcie

- 2026-05-23: Sub-wątek bootstrapowany. Plan eksploracji + design potwierdziły Q1/Q2 (reuse safe), Q3 (real parity bug w `transport_multiplier` — last-match-wins zamiast first-match-wins), Q4 (inline capacity parsing). Następny krok: pre-flight + A2.4c.0 fix.
