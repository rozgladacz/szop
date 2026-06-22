# HANDOFF — faza-telemetry-agents

> **Wątek:** Telemetria decyzji bota (ADR-0017, slice `data/agent_metrics/*.jsonl`) — `decision_time_ms` + `decision_quality_score` per agent, jako skrypt-liść `scripts/analyze_agents.py` + additive hook obserwujący decyzje w runnerze.
> **Status:** Ready for archive
> **Utworzony:** 2026-06-22
> **Ostatnia aktualizacja:** 2026-06-22

## Cel

Domknąć jawnie niezrealizowany checkbox roadmapy w strumieniu cross-cutting "telemetria od dnia 1" (ADR-0017): `data/agent_metrics/{agent_user_id}.jsonl` — `decision_time_ms, decision_quality_score`. Slice mierzy jakość/koszt decyzji botów **per bot** (nie per bitwa — to robi już `analyze_battle.py`). Wartość: diagnostyka "jak drogo myśli bot vs jak dobre są jego decyzje" — uzupełnia wniosek D4 (priority/priority3 najlepszy stosunek siła/koszt) twardymi liczbami per-decyzja zamiast tylko win-rate.

Definicja metryk (autonomiczna, bez usera — telemetria, nie reguła gry):
- **`decision_time_ms`** — czas wall-clock `Player.choose_action` (główna decyzja aktywacji).
- **`decision_quality_score`** — samoocena bota: Δ `evaluate_state` (SSOT `policy_eval`, ADR-0031/0044) z perspektywy decydenta między stanem przed a po aktywacji. Dodatnia = bot poprawił swoją pozycję wg własnej funkcji oceny.

## Zablokowane pliki / katalogi
- `app/services/agents/match.py` — additive `on_decision` callback (default None → zero zmian zachowania, B7 golden bez zmian)
- `scripts/analyze_agents.py` (NEW) — skrypt-liść telemetrii decyzji
- `tests/test_analyze_agents.py` (NEW)
- `scripts/README.md`, `docs/roadmap.md`, `docs/architecture.md` — dokumentacja

## Blokuje / Blokowane przez
- **Blokuje:** nic (warstwa-liść + additive hook).
- **Blokowane przez:** nic.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Hook obserwacji decyzji w runnerze
- [x] Krok 1.1: `run_match(..., on_decision=None)` — gdy podane, mierzy czas `choose_action` i po aktywacji woła `on_decision(perspective, unit_id, action, state_before, state_after, elapsed_ms)`. Additive, default None → identyczne zachowanie (B7 golden/B5/balance bez zmian, zweryfikowane).
- [x] Krok 1.2: `simulate_from_rosters(..., on_decision=None)` passthrough do `run_match`.

### Faza 2 — Skrypt-liść analyze_agents.py
- [x] Krok 2.1: rdzeń = czyste funkcje: `DecisionRecord`, `AgentMetrics`, `quality_from_states` (Δ evaluate_state), `aggregate_records`, `render_report`, `metrics_to_dict` (schema `szop.agent_metrics/v1`).
- [x] Krok 2.2: driver `collect_decisions` — N gier (naprzemienna inicjatywa), kolektor przez `on_decision`, mapowanie owner_player→bot kind.
- [x] Krok 2.3: CLI — `--players`/`--fixture`/`--map`/`--map-seed`/`-n`/`--seed`/`--out`/`--json`.

### Faza 3 — Testy
- [x] Krok 3.1: `tests/test_analyze_agents.py` (16) — quality deterministyczna, agregacja per bot, JSON round-trip, driver end-to-end (determinizm/oba boty/self-play/n≤0), backward-compat hooka, render.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — **1858 passed** (1842 baseline + 16)
- [x] Call-site check `run_match`/`simulate_from_rosters` (nowy keyword-only param default None → wsteczna kompat; B7 golden zielone)
- [x] `/simplify` (4 kąty inline) — 1 cleanup (hoist niezmiennego `kind_by_player`/closure przed pętlę) + korekta wierności docstringa
- [x] `/review` — pominięty warunkowo (jedyna zmiana prod = additive ~15-liniowy hook; reszta izolowany skrypt-liść z pełnym pokryciem; brak hot-path/SSOT/auth; inline self-review correctness)
- [!] `/security-review` — N/A (brak auth/DB-write; `data/` gitignored)
- [x] Re-run `pytest` po simplify — 21 zielonych (analyze_agents+match), pełna 1858
- [x] Diff review przed commitem

## Pliki dotknięte
- `app/services/agents/match.py` (MOD) — `OnDecision` type alias + additive `on_decision` hook w `run_match`/`simulate_from_rosters` (default None)
- `scripts/analyze_agents.py` (NEW) — skrypt-liść telemetrii decyzji per agent
- `tests/test_analyze_agents.py` (NEW, 16) — czyste funkcje + driver + backward-compat
- `docs/roadmap.md`, `scripts/README.md`, `docs/architecture.md` — dokumentacja slice'u

## Decyzje zamrożone (NIE podnosić ponownie)
- (brak — nowy wątek)

## Hipotezy / pytania otwarte
- `READY`: cały slice. Brak otwartych pytań do usera.
- `WAITING(prereq)`: live structlog-emission decyzji w produkcyjnym przepływie B4 (gdy API istnieje) — ten slice realizuje analizę offline z re-symulacji, spójnie z `analyze_battle.py`. Pole `agent_user_id` jako nazwa bot-kind (nie konto DB — konta agentów odłożone do B2 auth, ADR-0030 część 2).

## Jak zweryfikować
```bash
python -m pytest tests/test_analyze_agents.py -q
python scripts/analyze_agents.py --players priority,claude_v3 -n 6 --seed 7
python scripts/analyze_agents.py --players priority,random -n 4 --json data/agent_metrics/run.jsonl
```

## Decyzje
- 2026-06-22: slug `faza-telemetry-agents`. Metryka jakości = Δ `evaluate_state` (samoocena bota, SSOT policy_eval) — autonomiczny wybór (telemetria, nie reguła gry).

## Notatki / odkrycia w trakcie
- 2026-06-22: `data/` jest blankietowo gitignored (`.gitignore:1`, wyjątek `!app/data/`) → `data/agent_metrics/` spełnia checkbox roadmapy bez zmiany `.gitignore`.
