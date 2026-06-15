# ADR-0013 — Engine headless-first, prezentacja opcjonalna

- **Status:** Accepted
- **Data:** 2026-06-15
- **Kontekst:** Strumień B (Game Engine MVP). Silnik (`app/services/engine/`) to czyste funkcje + event sourcing (ADR-0010/0011); cała gra jest w pełni opisana strumieniem `events.BattleEvent` (16 typów) i persystowana jako `battle_events` (ADR-0050). Pytanie architektoniczne od B0: czy prezentacja (wizualizacja przebiegu bitwy) jest częścią silnika, czy warstwą opcjonalną nad nim? Strumienie konsumujące silnik bez UI już istnieją: D (`balance_simulate`/`balance_report` — headless agregacja), B5 (`szop_client.LocalClient`), B7 (golden regression). Pierwszy deliverable B6 (`scripts/battle_replay.py`, wątek `faza-b-6-replay`) wymusza rozstrzygnięcie.

## Decyzja

**Silnik jest headless-first: zero zależności od warstwy prezentacji.** Prezentacja (CLI replay, SSE stream, canvas frontend) to **opcjonalne konsumenty** publicznego API silnika (ADR-0011) i strumienia eventów — nigdy odwrotnie. Silnik nie wie, że istnieje UI.

### Konsekwencje dla B6 (prezentacja)

1. **Renderowanie z event-logu, nie ze stanu.** Prezentacja czyta `events.BattleEvent` (i opcjonalnie odtwarza stan przez `apply_events`), ale sam silnik nie emituje niczego „pod UI". Event-log jest jedynym kontraktem.
2. **Dwa źródła eventów, jednolity renderer.** `scripts/battle_replay.py` renderuje ten sam log albo ze świeżej symulacji (`simulate_from_rosters`, ADR-0032), albo z persystencji (`persistence.load_events`, ADR-0050). Render działa **z samego event-logu** (bez rekonstrukcji pełnego stanu) — persystencja nie trzyma `initial_state`, więc oba tryby dzielą tę samą ścieżkę.
3. **Rdzeń renderujący = czyste funkcje** (`format_event`, `render_battle_log`) bez I/O — w pełni testowalne, niezależne od kanału wyjścia (terminal / przyszły SSE / HTML).
4. **Skrypty prezentacji to liście** — zero zmian w rdzeniu silnika/agentów; bezpieczne równolegle z wątkami modyfikującymi silnik.

### Pierwszy slice (zaimplementowany 2026-06-15)

`scripts/battle_replay.py` — CLI replay: narracja jednolinijkowa PL per event, pogrupowana w rundy (delimiter `RoundEnded`), z bieżącym wynikiem celów (pkt 5.d/5.f) i podsumowaniem (rozkład typów + zwycięzca). Tryby: `--fixture` / `--map` (reuse `balance_simulate` SSOT) oraz `--from-db <id>` (persystencja, read-only). 16 testów.

## Konsekwencje

**Pozytywne:**
- **Jeden kontrakt (event-log) dla wszystkich konsumentów** — boty (D), klient (B5), regresja (B7), prezentacja (B6) czytają to samo. Brak rozjazdu „UI widzi co innego niż silnik".
- **Testowalność** — czyste funkcje renderujące testuje się bez uruchamiania UI; replay deterministyczny per seed (ADR-0010/0012).
- **Brak ryzyka dla rdzenia** — prezentacja nigdy nie wymusza zmian w silniku.
- **Render generyczny** — dispatch po nazwie typu eventu + fallback `repr` dla nieznanego typu → nowe typy eventów degradują się łagodnie, nie crashują renderera.

**Negatywne / koszty:**
- **Narracja z samego logu nie pokazuje pełnego stanu** (np. pozycji/HP wszystkich oddziałów w danym momencie) bez dodatkowego `apply_events`. Świadomy trade-off MVP — log eventów jest czytelny i wystarcza do inspekcji przebiegu. Bogatszy widok (stan po N-tym evencie) to follow-up.
- **`MatchResult.events` nie zawiera eventów rozstawienia** (runner liczy od rundy 1, ADR-0032) — replay sim-mode zaczyna się od R1. Dla pełnego logu z DB użyj bitwy persystowanej z deployment events.

## Alternatywy rozważone

- **Prezentacja wbudowana w silnik (silnik emituje sformatowany tekst/HTML).** Odrzucone — sprzęga rdzeń z kanałem wyjścia, łamie czystość funkcji i utrudnia testy. Silnik zna tylko eventy.
- **Render ze zrekonstruowanego stanu (`apply_events`) zamiast z eventów.** Odrzucone dla MVP — wymaga `initial_state`, którego persystencja nie trzyma; rozjechałoby tryb sim i `--from-db`. Narracja per-event jest prostsza i jednolita.
- **Najpierw SSE/canvas zamiast CLI.** Odrzucone — CLI replay to najtańszy, dependency-free pierwszy slice; SSE (`GET /battles/{id}/events`) wymaga B4 API, canvas to osobny stos frontendu. Oba pozostają w B6 jako follow-up.

## Inwarianty

1. Silnik (`app/services/engine/*`) nie importuje niczego z warstwy prezentacji.
2. `render_battle_log` jest czystą funkcją: ten sam event-log → ten sam tekst (determinizm renderowania).
3. Renderer nie crashuje na nieznanym typie eventu (fallback `repr`).
