# HANDOFF — telemetry-adr-0017

> **Wątek:** Spisać ADR-0017 (Telemetria od dnia 1) dokumentujący zaimplementowaną rzeczywistość telemetrii offline z event-logu; zsynchronizować indeks ADR.
> **Status:** In progress
> **Utworzony:** 2026-07-06
> **Ostatnia aktualizacja:** 2026-07-06

## Cel
ADR-0017 jest referowany w `docs/roadmap.md` (indeks + sekcja cross-cutting),
`docs/architecture.md`, `scripts/{analyze_battle,analyze_agents}.py`,
`app/services/{agents/match,engine/resolver}.py` i testach, ale **plik ADR nie
istnieje** (indeks: status `—`). Wiele slice'ów telemetrii jest DONE z
ustalonymi decyzjami (analiza offline z event-logu, schemy `szop.*/v1`, hooki
additive `on_decision`/`on_action`, zakres per-akcja opcja A, live-emission i raw
combat rolls świadomie odłożone). Ten wątek spisuje ADR dokumentujący **stan
zaimplementowany** i zamraża decyzje — dokładny precedens ADR-0025 (spisany
2026-06-28 dla zaimplementowanej infrastruktury tokenów). Doc-only, bez zmian
kodu, bez decyzji usera.

## Zablokowane pliki / katalogi
- `docs/adr/0017-telemetry-day-one.md` (NEW) — treść ADR.
- `docs/roadmap.md` — **tylko** wiersz indeksu ADR `| 0017 | ... | — |` → `✓`
  (edycja punktowa; reszta roadmapy poza zakresem).

## Blokuje / Blokowane przez
- **Blokuje:** nic.
- **Blokowane przez:** nic.
- **Koordynacja:** równoległy agent aktywny na wątku `faza-b-engine-mvp`
  (`szop_client/http.py`, `app/routers/battles.py`, `HANDOFF_faza-b-engine-mvp.md`).
  Ten wątek świadomie NIE dotyka tych plików ani HANDOFF tamtego wątku — tylko
  `docs/adr/` + punktowy wiersz indeksu roadmapy. Zero nakładania.

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Treść ADR
- [ ] Krok 1.1: Napisać `docs/adr/0017-telemetry-day-one.md` (Status: Accepted)
  wg struktury ADR-0025: Kontekst → Decyzja (offline-first z event-logu,
  schemy `szop.battle_metrics/v1` + `szop.agent_metrics/v1`, hooki additive,
  zakres per-akcja opcja A) → Konsekwencje → Alternatywy odrzucone. Odłożone
  (structlog live-emission, raw combat rolls LOCKED) jawnie wymienione.

### Faza 2 — Synchronizacja indeksu
- [ ] Krok 2.1: `docs/roadmap.md` indeks ADR: `| 0017 | Telemetria od dnia 1 | — |`
  → `✓`.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [!] `pytest -q` — nie dotyczy: zmiana wyłącznie docs (`.md`), zero kodu.
  (Encoding gate/pytest gate dotyczą `.py`; tu brak plików `.py`.)
- [!] Smoke test JS — nie dotyczy (brak zmian `app.js`).
- [!] Call-site check — nie dotyczy (brak zmian funkcji).
- [x] `/simplify` — przegląd jakości treści ADR (docs).
- [!] `/review` — nie dotyczy (doc-only, brak kodu/hot-path/SSOT).
- [!] `/security-review` — nie dotyczy (brak auth/user input/DB).
- [ ] Diff review przed commitem (`git diff --check`).

## Pliki dotknięte
- `docs/adr/0017-telemetry-day-one.md` (NEW) — <w toku>
- `docs/roadmap.md` — <w toku, wiersz indeksu>

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-26: Raw combat rolls / audyt szczęścia kości bojowych — odłożone bez
  terminu; niska wartość teraz, zmiana wymagałaby schemy eventów + ADR + regen
  B7. `LOCKED`. ADR-0017 tylko odnotowuje jako odłożone, nie implementuje.
- 2026-06-25: Zakres telemetrii per-akcja = opcja A (RESOLVED, commit `8f4b3ad`).
  ADR-0017 dokumentuje ten zakres jako zaimplementowany.

## Hipotezy / pytania otwarte
- `READY`: pełne live-emission structlog w hot-path `resolver`/`persistence` +
  pola czasowe `time_per_action_ms`/`dice_rolls_total` — odłożone (hot-path
  silnika), NIE blokujące; ADR-0017 wymienia jako przyszły zakres.

## Jak zweryfikować
```bash
# doc-only: brak testów. Weryfikacja:
git diff --check   # brak błędów whitespace
# przegląd: ADR-0017 spójny z sekcją cross-cutting roadmapy + architecture.md
```

## Decyzje
- 2026-07-06: Osobny wątek (nie `faza-b-engine-mvp`) — równoległy agent edytuje
  HANDOFF tamtego wątku; izolacja zapobiega kolizji. Doc-only, więc dedykowany
  wątek jest krótkotrwały (create → ADR → archive).

## Notatki / odkrycia w trakcie
- 2026-07-06: `docs/adr/README.md` nie ma numerowanego indeksu ADR — jedyny
  indeks jest w `docs/roadmap.md` (linie ~421-463). Aktualizować tam.
