# ADR-0032 — Headless match runner (orkiestrator pełnej gry dla botów)

- **Status:** Accepted
- **Data:** 2026-06-10
- **Kontekst:** Strumień D (wątek `faza-d-match-runner`). D1 (ADR-0031) dał graczy heurystycznych (`Player.choose_action`), ale silnik jest **jednoakcyjny** (`resolver.apply` — jedna akcja → `ResolverResult`). Nikt nie napędza graczy przez pełną grę. D2 (`scripts/balance_simulate.py` — win-rate per rozpiska/zdolność) i D3 (`exploit_hunt`) wymagają pętli, która rozgrywa całą bitwę headless. Pełna pętla jest też zalążkiem `B5 LocalClient.simulate`.

## Decyzja

**`app/services/agents/match.py`** — czysta orkiestracja publicznego API silnika (ADR-0011), zero zmian w rdzeniu (czyta `phases`/`resolver`/`state`/`events`/`dice` + protokół `Player`).

```python
def run_match(state, players, dice, *, max_activations=2000) -> MatchResult
def simulate_from_rosters(rosters, players, *, seed, terrain, objectives, ...) -> MatchResult

@dataclass(frozen=True)
class MatchResult:
    final_state: BattleState
    events: tuple[BattleEvent, ...]
    winner: int | None   # pkt 5.f: więcej zajętych celów; None = remis
    rounds_played: int
```

### Pętla (pkt 8)

```
while not is_battle_over(state):          # pkt 5.f (MAX_ROUND=4)
    while not should_end_round(state):    # pkt 8.b
        active = state.active_player
        action = players[active].choose_action(state, active)
        if action is None: <przekaż inicjatywę lub zakończ rundę>
        else: state, events = apply(state, action, dice)   # 1 akcja = 1 aktywacja
    state, events = round_end_phase(state)  # pkt 8.c
```

### Decyzje projektowe

1. **Model „1 `apply` = 1 aktywacja" (H1).** Silnik ustawia Aktywowany i przełącza inicjatywę po każdym `apply` (`resolver._switch_active_player`). Limit 2 akcji/aktywację (pkt 11.b.iv) nie jest w MVP zaimplementowany — runner respektuje obecny model: jedno `apply` per oddział per runda. Gdy engine doda 2-akcyjną aktywację, runner się nie zmienia (to `apply`/`phases` odpowiada za pętlę akcji w aktywacji).
2. **`choose_action() is None` ⟺ brak własnych aktywowalnych oddziałów** (bo `legal_actions` zawsze dodaje Obronę per oddział, ADR-0031). Wtedy: jeśli przeciwnik ma aktywowalne oddziały → **przekaż inicjatywę** (emit `InitiativePassed` + `replace(active_player)`, spójnie z `resolver._switch_active_player`, żeby log eventów pozostał replayowalny); inaczej → **zakończ rundę** (`break`). Ta druga ścieżka jest load-bearing dla rezerw Zaplecze (pkt 26): `should_end_round` liczy je jako żywe-nieaktywowane, ale runner ich nie rozstawia mid-game (MVP) — bez `break` pętla rundy nie zakończyłaby się.
3. **Determinizm.** Seed `DeterministicDice` + deterministyczni gracze (RandomPlayer per seed, GreedyPlayer czysto) → cała gra deterministyczna (ADR-0010/0012). `run_match(s, p, dice)` dwukrotnie z tym samym wejściem → identyczny `MatchResult`.
4. **`max_activations` bezpiecznik** anty-zapętlenie dla custom Player-ów (realna gra: ≤ 4 rundy × #oddziałów).
5. **`simulate_from_rosters` pomija eventy rozstawienia** w `MatchResult.events` (runner liczy od startu rundy 1) — spójne z `engine_smoke_replay.py`, gdzie transition 0→1 nie jest w pełni event-sourced.

### Zwycięzca (pkt 5.f)

`state.score = (p0_zajęte_cele, p1_zajęte_cele)` z `_check_objective_control` (pkt 5.d, aktualizowane w `round_end_phase`). `winner = argmax(score)`, remis → `None`.

## Konsekwencje

**Pozytywne:**
- **Odblokowuje D2/D3** — `simulate_from_rosters` to jedno wywołanie = jedna gra; D2 agreguje N gier do win-rate.
- **Zero kolizji z rdzeniem silnika** — nowy moduł, tylko odczyt API. Bezpieczny równolegle z wątkami modyfikującymi silnik.
- **Headless-first (ADR-0013)** — zero DB/HTTP; testowalny w izolacji (5 testów: pełna gra → MAX_ROUND, determinizm, winner↔score, greedy-vs-random, przekazanie inicjatywy).
- **Zalążek B5 LocalClient.simulate** — `run_match` jest rdzeniem; B5 doda Protocol GameClient + HttpClient wrapper.

**Negatywne / koszty:**
- **Rezerwy Zaplecze nie są rozstawiane mid-game** (MVP) — siedzą bezczynnie do końca gry. Pełne rozstawianie rezerw (pkt 11.a + 13) wymaga, by gracz produkował `DeploymentAction` dla oddziałów Zaplecze. Odłożone.
- **Brak limitu 2 akcji/aktywację** (pkt 11.b.iv) — dziedziczone z silnika; gdy engine doda, runner bez zmian.
- **`events` z `simulate_from_rosters` nie zawiera deployment** — nie jest pełnym event-sourced logiem całej gry (dla persistence użyj `run_match` od jawnego stanu + osobno deployment events).

## Alternatywy rozważone

- **Runner jako część `resolver`/`phases` (silnik).** Odrzucone — silnik celowo jednoakcyjny (ADR-0011); pętla całej gry to orkiestracja, nie reguły. Trzymanie w `agents/` nie zanieczyszcza API silnika.
- **Od razu pełen B5 (Protocol GameClient + HttpClient + LocalClient).** Odrzucone dla tego okna — duże; `run_match` headless wystarcza D2 i jest jądrem przyszłego `LocalClient.simulate`.
- **Manualne `replace(active_player)` bez `InitiativePassed`.** Odrzucone — złamałoby inwariant replay (`apply_events` nie odtworzyłby przekazania inicjatywy). Emit eventu zachowuje spójność z `resolver`.

## Inwarianty

1. `run_match(s, players, DeterministicDice(seed))` deterministyczny per (s, players, seed).
2. `MatchResult.winner == 0 ⟺ score[0] > score[1]` (analogicznie dla 1 / None).
3. Po `run_match`: `final_state.is_game_over and final_state.round == MAX_ROUND`.
4. `run_match` zawsze kończy się (≤ `max_activations` aktywacji).
