# ADR-0017 — Telemetria od dnia 1: analiza offline z event-logu

- **Status:** Accepted
- **Data:** 2026-07-06
- **Kontekst:** Cross-cutting („telemetria od dnia 1"). Silnik jest event-sourced
  (ADR-0010/0046): pełny przebieg bitwy jest odtwarzalny z `BattleEvent`. Zamiast
  dokładać żywą instrumentację do hot-path silnika (koszt na ścieżce
  `resolver`/`persistence`), telemetria MVP **czyta sam event-log** i re-symuluje
  gry offline. Zdolność powstała addytywnymi slice'ami:
  `scripts/analyze_battle.py` (per-bitwa + agregat `--games N` + `--json`,
  2026-06-21), `scripts/analyze_agents.py` (metryki decyzji per bot, 2026-06-22),
  oraz korekta zakresu per-akcja (opcja A, 2026-06-25, commit `8f4b3ad`). Ten ADR
  spisuje **rzeczywistość już zaimplementowaną** i zamraża jej kontrakt (schemy,
  hooki, zakres pomiaru), tak jak [ADR-0025](0025-agent-scoped-tokens.md) spisał
  zaimplementowaną infrastrukturę tokenów.

  Pokrewne: [ADR-0010](0010-event-sourced-battle-log.md)/[ADR-0046](0046-event-sourced-mutations.md)
  (event sourcing = źródło danych telemetrii), [ADR-0032](0032-match-runner.md)
  (`run_match`/`simulate_from_rosters` = miejsce hooków), [ADR-0044](0044-prediction-module.md)
  i `policy_eval` (`evaluate_state` = miara jakości decyzji),
  [ADR-0030](0030-multi-agent-leaderboard.md) cz. 2 (konta DB agentów +
  live-emission — odłożone do B2 auth).

## Decyzja

### 1. Offline-first: telemetria czyta event-log, nie hot-path

Podstawowe źródło metryk to zapisany `BattleEvent` (odtwarzalny, ADR-0050) lub
re-symulacja przez `simulate_from_rosters` (ADR-0032). Silnik NIE emituje
telemetrii w trakcie rozgrywki na ścieżce produkcyjnej — dzięki temu hot-path
`resolver.apply`/`persistence.save_events` pozostaje bez kosztu i bez zmian
zachowania. `scripts/analyze_battle.py` ma dwa źródła (jak `battle_replay.py`,
ADR-0013): `--fixture`/`--map` (symulacja przez SSOT `balance_simulate`) oraz
`--from-db <id>` (`persistence.load_events`, read-only). Bez `initial_state`
(tryb `--from-db`) analiza degraduje się gracefully do statystyk per-oddział.

### 2. Dwa poziomy: per-bitwa i per-bot

- **Per-bitwa** (`analyze_battle.py`): wynik gry (zwycięzca pkt 5.f + timeline
  kontroli celów per runda pkt 5.d/8.c.ii), statystyki ataku/obrony per oddział i
  per strona (obrażenia/trafienia/straty/ELIMINOWANY pkt 26.d), rozkład
  akcji/typów eventów, szczęście kości Przegrupowania (rozkład 1–6 pkt 20). Tryb
  agregatu `--games N` (metodyka `balance_simulate`: naprzemienna inicjatywa) →
  średnie per strona + rozkład wyników + zagregowane kości. Diagnostyka
  „DLACZEGO bot wygrywa" — luka poza `leaderboard`/`balance_report` (np. dwa boty
  o równych obrażeniach różni kontrola celów).
- **Per-bot** (`analyze_agents.py`): KOSZT i JAKOŚĆ decyzji z re-symulacji.
  `decision_time_ms` = wall-clock wyboru akcji; `decision_quality_score` =
  Δ `evaluate_state` przed/po akcji (samoocena bota wg SSOT `policy_eval`,
  ADR-0044). Agregat per agent: śr./mediana/max czas, śr. jakość, % decyzji
  poprawiających, miks akcji.

### 3. Schemy maszynowe `szop.*/v1` (jsonl-kompatybilne)

`--json PATH` serializuje raport do JSON-owalnego dict, jedna linia = jeden
rekord (jsonl). Dwie zamrożone schemy:
- `szop.battle_metrics/v1` — `analyze_battle --json`: pola **odzyskiwalne z
  event-logu** (`action_count`/`event_type_counts`, `dice_distribution`, staty
  per oddział/strona, kontrola celów).
- `szop.agent_metrics/v1` — `analyze_agents --json`: metryki decyzji per bot.

Pola pochodne (odtwarzalne offline) — NIE wymagają zmian schemy `payload_json`
eventów, więc nie ruszają zamrożonego kontraktu event-store'u (B3.9) ani golden
digestów B7.

### 4. Instrumentacja przez hooki additive (default `None` → zero zmian)

Pomiar wpina się **wyłącznie** przez opcjonalne hooki z domyślną wartością
`None`, więc pełny przebieg bez telemetrii jest bit-identyczny (B7 golden digesty
bez zmian):
- `on_decision` w `match.run_match`/`simulate_from_rosters`
  (`OnDecision = Callable[[perspective, unit_id, action, state_before,
  state_after, elapsed_ms], None]`) — czas + jakość decyzji.
- `on_action`/`ActionObserver` w `resolver.apply_activation` — czysto
  obserwacyjny hook per akcja (`on_action(action, state_before, state_after)`);
  silnik raportuje FAKT wykonania akcji, telemetria dokłada czas (helper
  `_apply_activation_with_telemetry` w `match.py`, żeby `time` nie wchodził do
  resolvera).

### 5. Zakres pomiaru = per AKCJA (opcja A)

Aktywacja może obejmować **do dwóch akcji** — źródło `SZOP_Rozjemca.md` pkt
11.b.iv: pętla aktywacji wraca do pkt i, dopóki m.in. „Oddział wykonał mniej niż
dwie akcje w tej aktywacji" (pkt 11.b.iv, `SZOP_Rozjemca.md:78-80`; realizacja:
ADR-0051 orkiestrator `apply_activation` + `continue_activation`). Telemetria
mierzy `decision_time_ms`, `decision_quality_score` i `action_mix` **per akcję**
(nie tylko z pierwszej akcji aktywacji) — jeden, spójny zakres dla wszystkich
trzech metryk. Czas wyboru: `choose_action` dla 1. akcji, `continue_activation`
dla kolejnych; skorelowany z per-akcyjnym `on_action` przez helper runnera.
Rozstrzygnięcie: 2026-06-25, opcja A, commit `8f4b3ad`.

### 6. Skrypty-liście, reuse SSOT

Wszystkie trzy skrypty telemetrii to **warstwa-liść** (ADR-0013): zero zmian w
rdzeniu silnika, reuse SSOT (`balance_simulate` do ładowania fixtur/graczy,
`persistence.load_events` do odczytu, `policy_eval.evaluate_state` do jakości,
`phases._check_objective_control` do kontroli celów). Testy bez sieci; ścieżka
DB-read pokryta seeded in-memory SQLite.

## Konsekwencje

- **Hot-path bez kosztu** — silnik nie płaci za telemetrię; metryki pochodne
  odzyskiwane offline z event-logu, który i tak istnieje.
- **Kontrakt event-store'u nietknięty** — telemetria nie dodaje pól do
  `payload_json`, więc B3.9 freeze + B7 golden digesty zostają.
- **Pierwszy szew czasowy gotowy pod live B4** — hook `on_decision` z polem
  `elapsed_ms` jest tym samym seamem, którego użyje produkcyjna instrumentacja B4
  gdy powstanie.
- **Diagnostyka botów** — `analyze_battle --games`/`analyze_agents` wyjaśniają
  „dlaczego" ponad rankingiem `leaderboard`/`balance_report` (potwierdzone: dwa
  boty o zbliżonych obrażeniach różni kontrola celów).

## Odłożone (poza tym ADR)

- **`READY` — live-emission structlog** w hot-path `resolver`/`persistence`
  (`battle_id, action_id, actor_user_id` per event) + pola czasowe
  `time_per_action_ms`/`dice_rolls_total` w `szop.battle_metrics`. Wymaga zmian w
  hot-path silnika; niezaimplementowane ≠ zablokowane.
- **`LOCKED` (decyzja usera 2026-06-26) — raw combat rolls / pełny audyt
  szczęścia kości BOJOWYCH.** `Shot/MeleeResolved` trzymają `hits`/`wounds_dealt`,
  nie surowe rzuty. Dodanie zmieniłoby zamrożoną schemę `payload_json` + golden
  digesty B7; niska wartość teraz. Wraca dopiero przy konkretnej potrzebie
  telemetrycznej. NIE podnosić jako otwarte pytanie.
- **Konta DB agentów (`agent_user_id`) + live-emission w produkcyjnym B4** —
  odłożone do B2 auth (ADR-0030 cz. 2); dziś `agent` = nazwa bota z re-symulacji.

## Alternatywy odrzucone

- **Żywa instrumentacja silnika od początku** — odrzucone na rzecz offline-first:
  event-log już zawiera dane, więc pochodne metryki nie potrzebują kosztu na
  hot-path ani zmian zamrożonej schemy eventów.
- **Telemetria tylko z pierwszej akcji aktywacji** — odrzucone (opcja A): dawała
  niespójny zakres (`action_mix`/`decision_time_ms` z 1. akcji, `quality` z całej
  aktywacji). Per-akcja daje jeden zakres i widzi 2. akcję (pkt 11.b.iv).
- **Nowe pola w `payload_json` eventów dla metryk** — odrzucone: złamałoby freeze
  event-store'u (B3.9) i golden digesty B7 dla danych odzyskiwalnych offline.
- **Osobny format zamiast jsonl** — odrzucone: jeden rekord/linia (`szop.*/v1`)
  jest strumieniowalny i trywialnie agregowalny.
