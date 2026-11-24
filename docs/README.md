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
| [oznaczenie-mechaniki-plan.md](oznaczenie-mechaniki-plan.md) | Podział mechanik Oznaczenia i zakres pierwszego etapu C2d1 (Furia v3) |
| [oznaczenie-publication-spec.md](oznaczenie-publication-spec.md) | C2-publication-spec: katalog gotowości, granice security i bramki przyszłej ograniczonej publikacji |
| [niestrudzony-spec.md](niestrudzony-spec.md) | C2d6-spec: legalność powtórzeń, lifetime Oznaczenia i wykluczenie z obecnego zakresu |
| [planowanie-spec.md](planowanie-spec.md) | C2d5-spec: Planowanie, status Przygotowany, lifecycle i granice przyszłej implementacji |
| [bastion-spec.md](bastion-spec.md) | C2d4-spec: role kontrataku, Rozkaz i wykluczenie Bastionu z obecnego zakresu Oznaczenia |
| [ostrozny-spec.md](ostrozny-spec.md) | C2d3-spec: audyt źródeł Ostrożnego, decyzja tylko dystansowo, kontrakt i testy implementacji |
| [D5.3b — eksperyment rozstawienia](experiments/d5_3b/README.md) | Zamrożony manifest, dane i porównanie grid/objectives |
| [boty-audit.md](boty-audit.md) | D6.1: bot × protokół × scenariusz, reprodukcje luk legalności, koszt i prerekwizyty D6.2 |
| [boty-connect.md](boty-connect.md) | D6.2: jednorazowy priority/v1 → pending proposal, osobna zgoda ownera, zakres i rekoncyliacja |
| [play-vs-ai-plan.md](play-vs-ai-plan.md) | D6.3: małe etapy dojścia od podglądu i priority/v1 do gry w UI, consent/protokoły/setup/restart i testy |
| [trwala-kampania-v1.md](trwala-kampania-v1.md) | D7.1: runner kampanii v1, trwały zapis przypadków, resume, integralność, archiwum i pilot |
| [archiwum-eksperymentow.md](archiwum-eksperymentow.md) | D7.2: pakiety kampanii i historii, publikacja, weryfikacja, backup i odzyskiwanie |
| [jakosc-eksperymentow.md](jakosc-eksperymentow.md) | D7.3a–b — ocena techniczna, porównywalne bloki, efekt strony i odtworzenie |
| [obserwacja-decyzji-kampanii.md](obserwacja-decyzji-kampanii.md) | D7.4a — ślad wyborów, rozstrzygnięć i przejść automatycznych runnera v1 |
| [eksport-decyzji-kampanii.md](eksport-decyzji-kampanii.md) | D7.4b — wersjonowany eksport decyzji, replay, budżet pilota i odtworzenie pakietu |
| [plan-danych-testowych.md](plan-danych-testowych.md) | D7.2–D7.4: plan wspólnego archiwum, bramek jakości i pełnego eksportu decyzji |
| [kolejka-po-c2d3.md](kolejka-po-c2d3.md) | Akceptacje 2026-11-19: Ostrożny, audyty, D5.3, publikacja, boty i podłączenie agentów |
| [kolejka-po-c2d1.md](kolejka-po-c2d1.md) | Pięć kolejnych przebiegów z zależnościami, zakresem i kryteriami zakończenia |

## Przeglądy

- [C2 QA — 2026-11-04](c2-qa-2026-11-04.md) — simplify, code/security review,
  regresja atomowości migracji i pełne testy pakietu C2.

## Podkatalogi

| Katalog | Zawartość |
|---------|-----------|
| [handoffs/](handoffs/) | Per-wątek pliki `HANDOFF_<slug>.md` + szablon i konwencje (README.md) |
| [adr/](adr/) | Architecture Decision Records (immutable). Index w `adr/README.md`; status w `roadmap.md → "ADR index"`. |
| [schemas/](schemas/) | Śledzone, deterministycznie generowane schematy dla narzędzi edytorowych i drift gate'ów |

## Najwyższy poziom

Pozostała dokumentacja na poziomie głównym repo:

- [AGENTS.md](../AGENTS.md) — manifest invariantów dla agentów AI ([CRITICAL]/[REQUIRED]/[RECOMMENDED])
- [HANDOFF.md](../HANDOFF.md) — meta-spis aktywnych wątków, zablokowane zasoby, LOG SESJI
- [README.md](../README.md) — uruchomienie lokalne / produkcyjne
- [DEPLOY.md](../DEPLOY.md) — procedura wdrożenia (Docker, Tailscale)
- [RELEASE.md](../RELEASE.md) — procedura wydania
- [README_INTEGRATION.md](../README_INTEGRATION.md) — integracje
- [FRICTION_REPORT.md](../FRICTION_REPORT.md) — raport friction (auto-generated z `scripts/reflect_and_improve.py`)
- [scripts/README.md](../scripts/README.md) — skrypty CLI (drift pipeline A4, profile_quote, reflect_and_improve, …)

## Zasada

**Jedno źródło prawdy per zakres.** Jeśli treść pasuje do więcej niż jednego pliku — wybierz właściwy i zostaw link z drugiego. Powtórzenia rozmywają sygnał.
