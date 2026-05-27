# docs/

Indeks dokumentacji projektu. Każdy plik ma jeden, jasny zakres.

## Główne pliki

| Plik | Zakres |
|------|--------|
| [overview.md](overview.md) | Cel projektu, obszary (Rozpiski/Armie/Zbrojownie), stack technologiczny |
| [architecture.md](architecture.md) | Model danych, dziedziczenie, mapa submodułów `costs/`, hot path, baza |
| [roadmap.md](roadmap.md) | Aktywne inicjatywy (SSOT, refaktor app.js), decyzje strategiczne |
| [planning.md](planning.md) | Layer Checklist, Performance gate, SSOT-check — bramki przed implementacją |
| [developing.md](developing.md) | Konwencje kodu, INCH/smart quotes, komentarze sekcji, ekstrakcja submodułów |
| [testing.md](testing.md) | Kolejność pytest, flagi, smoke test JS, frontend payload parity |
| [git-workflow.md](git-workflow.md) | Destructive commands, branch align, repo identity, hooki |
| [app-js-guide.md](app-js-guide.md) | Struktura `app.js`, łańcuch DOMContentLoaded, closure scope |
| [PERFORMANCE.md](PERFORMANCE.md) | Baseline wydajności silnika kosztów, benchmarki |
| [frontend_js_modules.md](frontend_js_modules.md) | Mapa modułów JS po Fazie III, call-site checklist |

## Podkatalogi

| Katalog | Zawartość |
|---------|-----------|
| [handoffs/](handoffs/) | Per-wątek pliki `HANDOFF_<slug>.md` + szablon i konwencje (README.md) |
| [adr/](adr/) | Architecture Decision Records (immutable). Index w `adr/README.md`; status w `roadmap.md → "ADR index"`. |

## Najwyższy poziom

Pozostała dokumentacja na poziomie głównym repo:

- [AGENTS.md](../AGENTS.md) — manifest invariantów dla agentów AI ([CRITICAL]/[REQUIRED]/[RECOMMENDED])
- [HANDOFF.md](../HANDOFF.md) — meta-spis aktywnych wątków, zablokowane zasoby, LOG SESJI
- [README.md](../README.md) — uruchomienie lokalne / produkcyjne
- [DEPLOY.md](../DEPLOY.md) — procedura wdrożenia (Docker, Tailscale)
- [RELEASE.md](../RELEASE.md) — procedura wydania
- [README_INTEGRATION.md](../README_INTEGRATION.md) — integracje
- [FRICTION_REPORT.md](../FRICTION_REPORT.md) — raport friction (auto-generated z `scripts/reflect_and_improve.py`)

## Zasada

**Jedno źródło prawdy per zakres.** Jeśli treść pasuje do więcej niż jednego pliku — wybierz właściwy i zostaw link z drugiego. Powtórzenia rozmywają sygnał.
