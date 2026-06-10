# HANDOFF — faza-b-multi-action

> **Wątek:** Aktywacja = do 2 akcji (pkt 11.b.iv) zamiast 1 — pętla akcji w silniku + napęd botów + match runner.
> **Status:** In progress
> **Utworzony:** 2026-06-10
> **Ostatnia aktualizacja:** 2026-06-10

## W TRAKCIE: 2026-06-10 — Faza 1 (engine `apply_activation` + split `phases`). Dotykam `phases.py` (split, addytywnie) + `resolver.py` (nowy `apply_activation`) + `agents/{match,base,*_player}.py`. **NIE ruszam `state.py`** (postęp aktywacji lokalny w orkiestratorze → brak zmian schematu replay, brak kolizji ze schematem `faza-b-order-interrupts`). **Uwaga koordynacja:** `phases.py` jest na liście locków `faza-b-order-interrupts` (MVP DONE/dormant — follow-upy WAITING(B4)); zmiany addytywne (split + nowe funkcje), bez ruszania interrupt/override logiki.

## Cel
Silnik kończy aktywację po 1 akcji (`activation_phase` „MVP scope: pojedyncza akcja"; `resolver.apply` → Aktywowany; `match.py` 1 apply/oddział). **Reguły (pkt 11.b.iv, źródło po poprawce usera 2026-06-10):** aktywacja to **do 2 akcji** (Manewr **liczy się** do limitu; punkt „akcja różna od już wykonanych" usunięty ze źródła), z ograniczeniami z definicji akcji: **Ostrzał raz** (14.c.v), **Szarża raz** (14.d.vi); Przegrupowanie **po każdej akcji** (11.b.iii). Brak Manewr→Ostrzał = duża luka realizmu (Strzelcy nie repozycjonują się przed strzałem).

## Decyzje architektoniczne
- Postęp aktywacji (akcje wykonane) **lokalny w orkiestratorze**, nie w `BattleState` — zero zmian schematu/replay, zero `state.py`.
- `apply` (1 akcja) ZOSTAJE (B4 per-action API + istniejące testy). NOWY `apply_activation` (orkiestrator 1–2 akcji) dla match/botów.
- `activation_phase` = `_begin_activation` + `_apply_single_action` + `_finalize_activation` (wstecznie kompatybilne; istniejące testy zielone).
- **Legalność kontynuacji (po poprawce reguł):** ≤2 akcje total (Manewr liczy się); Ostrzał ≤1, Szarża ≤1; **brak reguły „różna"** → Manewr+Manewr / Manewr+Ostrzał / Ostrzał+Szarża OK, Ostrzał+Ostrzał i Szarża+Szarża zabronione. Limit 2 gwarantuje terminację (żadnych capów Manewru).
- **Ważne (split):** odrzucenie Ufortyfikowany „na początku aktywacji" (pkt 22.c.iv, CR-fix G) musi być w `_begin_activation` (RAZ), nie per-akcja — inaczej akcja Obrony jako #1 dałaby Ufortyfikowany, a start #2 by go zdjął (bug).
- Napęd botów: `Player.continue_activation(state, perspective, unit_id, actions_taken) -> Action|None` z domyślną implementacją `None` (wsteczna kompat — bot bez override = 1 akcja). Override w Random/Greedy/Priority.

## Zablokowane pliki / katalogi
- `app/services/engine/phases.py` (split: `_apply_single_action` + `_finalize_activation`; addytywnie)
- `app/services/engine/resolver.py` (`apply_activation` + legalność kontynuacji)
- `app/services/agents/{base,random_player,greedy_player,priority_player,match}.py`
- `tests/test_engine_*` + `tests/test_agents_*`

## Plan implementacji
### Faza 1 — Engine: pętla 1–2 akcji (backward-compatible)
- [x] 1.1: Split `activation_phase` → `_begin_activation` (Ufort RAZ) + `_apply_single_action` (akcja+Przegrupowanie, bez Aktywowany) + `_finalize_activation` (Aktywowany + wygaśnięcie override'ów). `activation_phase` = wrapper (kompat, zachowanie 1:1 — 73 testy phases/resolver/replay zielone).
- [x] 1.2: `resolver.apply_activation(state, first_action, dice, seq, *, continuation=None)` — pętla begin→`_apply_single_action`*→kontynuacja→finalize→switch. `continuation: (state, unit_id, actions_taken)->Action|None`.
- [x] 1.3: `_can_take_followup(action, actions_taken)` — ≤2 akcje (Manewr liczy się), Ostrzał/Szarża raz (14.c.v/14.d.vi). Brak reguły „różna" (poprawka reguł). `MAX_ACTIONS_PER_ACTIVATION=2`.
- [x] 1.4: `tests/test_engine_multi_action.py` (13): Manewr→Ostrzał, Ostrzał→Ostrzał odrzucone, Ostrzał→Szarża, cap 2, cudzy oddział odrzucony, continuation=None==apply, replay-invariant.
### Faza 2 — Boty + match
- [x] 2.1: `Player.continue_activation` (default None) + `base.legal_followup_actions`; override Random (los+None), Greedy (best followup jeśli > DEFEND_VALUE), Priority (Ostrzał/Szarża najbliższego).
- [x] 2.2: `match.run_match` używa `apply_activation` z continuation aktywnego gracza.
- [x] 2.3: Testy continuation per bot (+6) + balance re-run.
### Faza 3 — DoD
- [x] pytest -q **1558**; both_assert **156/156**; smoke replay **EXIT 0**; `/simplify` + `/review` inline; source_hashes.yaml zaktualizowany (edycja pkt 11.b.iv przez usera); ADR-0051; roadmap; `/handoff-archive`.

## Pliki dotknięte
- `app/services/engine/phases.py` — split na `_begin_activation`/`_apply_single_action`/`_finalize_activation` + wrapper `activation_phase`.
- `app/services/engine/resolver.py` — `apply_activation` + `_can_take_followup` + `MAX_ACTIONS_PER_ACTIVATION` + `ActionProvider`.
- `app/services/agents/base.py` — `Player.continue_activation` (default None) + `legal_followup_actions`.
- `app/services/agents/{random,greedy,priority}_player.py` — override `continue_activation`.
- `app/services/agents/match.py` — `apply_activation` z continuation.
- `app/rulesets/v1/source_hashes.yaml` — nowy hash `SZOP_Rozjemca.md` (edycja pkt 11.b.iv).
- `tests/test_engine_multi_action.py` (NEW, 13) + `tests/test_agents_{priority,greedy,random}.py` (+6).
- `docs/adr/0051-*.md` (NEW), `docs/roadmap.md`.

## Wyniki balansu (efekt 2-akcji, 60 gier/zestaw)
- demo random/random 1→2 akcje: 7.5/7.5/85 → **25/21.7/53** (więcej rozstrzygnięć).
- demo greedy/random: 37.5/12.5/50 → **20/28/52**; clash priority/random: 9/14 → **5/28**.
- **Wniosek:** 2 akcje wzmacniają wcześniejszą słabość „boty nie trzymają celów" — agresywne boty atakują podwójnie, zaniedbując cele; random przypadkiem częściej kontroluje. Mechanika poprawna (replay ✓), to jakość heurystyk. Follow-up D: bot objective-aware / „hold". Move-then-shoot dla Strzelców wymaga zróżnicowanych fixtur (4 typy — kolejny wątek).

## Hipotezy / pytania otwarte
- **H1 (`READY`):** Manewr cap 1×/aktywację w MVP (pełna powtarzalność pkt 11.b.iv odroczona) — gwarantuje terminację bez polegania na decline bota. Pełna powtarzalność = follow-up.
- **H2 (`READY`):** „Niestrudzony" (znosi ≠-poprzednia) nieobsługiwany w MVP (brak w aktywnych zdolnościach) — gdy dojdzie, rozluźnić `_legal_continuation`.

## Jak zweryfikować
```powershell
python -m pytest tests/test_engine_resolver.py tests/test_engine_phases.py tests/test_agents_match.py -v
python -m pytest -q
python scripts/engine_smoke_replay.py
python scripts/balance_simulate.py --fixture tests/fixtures/battles/demo_skirmish.yaml -n 50 --players greedy,random
```

## Decyzje
- 2026-06-10: Postęp aktywacji lokalny w orkiestratorze (nie w BattleState) — zero zmian schematu replay, brak kolizji z lockiem state.py `faza-b-order-interrupts`.

## Notatki / odkrycia w trakcie
- 2026-06-10: Wątek z pytania usera (`faza-d-priority-player`). Luka zapisana też w parent `faza-b-engine-mvp` Notatki.
