# HANDOFF — brama-opos-szop

> **Wątek:** Rozdzielenie infrastruktury wejściowej SZOP i OPOS do osobnego repo `brama` oraz niezależne uruchamianie obu aplikacji.
> **Status:** Deploying — DNS pending
> **Utworzony:** 2026-09-01
> **Ostatnia aktualizacja:** 2026-09-02

## Cel

Wydzielić Caddy i publiczne porty 80/443 z aplikacji do małego stosu `brama`. Zachować osobne obrazy, bazy, backupy, sieci i aktualizacje SZOP oraz OPOS, a lokalnie umożliwić szybkie uruchamianie pojedynczej aplikacji i pełny smoke obu aplikacji przez bramę.

## Zablokowane pliki / katalogi

- `docker-compose.yml` — usunięcie lokalnego Caddy i podłączenie izolowanej sieci bramy.
- `docker-compose.dev.yml` — lokalny wariant kontenerowy SZOP.
- `Makefile` — konfigurowalny host i port developerski.
- `DEPLOY.md`, `.env.example`, `README.md` — kontrakt wdrożeniowy po wydzieleniu bramy.
- `Caddyfile` — przeniesienie odpowiedzialności do repo `brama`.

## Blokuje / Blokowane przez

- **Blokuje:** brak.
- **Blokowane przez:** `figurki.duckdns.org` nadal wskazuje inny host niż Oracle. Cut-over Caddy jest wstrzymany do czasu aktualizacji i propagacji rekordu. Aktywny wątek `rozmiar-podstawki` nie obejmuje tych plików.

## Gałąź git

- **Branch:** `Rozwoj`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Kontrakt infrastruktury
- [x] Utworzyć repo `brama` z Caddy i dwiema izolowanymi sieciami Docker.
- [x] Dodać bezpieczną konfigurację lokalną i skrypty PowerShell.

### Faza 2 — Rozdzielenie aplikacji
- [x] Dostosować Compose i lokalny start OPOS.
- [x] Dostosować Compose i lokalny start SZOP.
- [x] Zaktualizować dokumentację wdrożeniową bez zmian aplikacyjnych.

### Faza 3 — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` w SZOP.
- [x] `pytest -q` w OPOS.
- [x] Walidacja wszystkich konfiguracji Compose i Caddy — lokalna walidacja statyczna oraz workflow `Validate gateway` na GitHub zakończone powodzeniem.
- [x] Smoke test JS — N/D, brak zmian JS; skrypt HTTP smoke sprawdzony na lokalnym serwerze testowym dla obu hostów.
- [x] Call-site check — N/D, brak zmian funkcji ani wywołań aplikacyjnych.
- [x] `/simplify` — wspólna orkiestracja lokalna pozostaje wyłącznie w `brama`, bez duplikowania w aplikacjach.
- [x] `/review` — przejrzano diffy trzech repozytoriów i granice odpowiedzialności.
- [x] `/security-review` — publiczne porty ma wyłącznie `brama`; aplikacje mają osobne sieci edge, sekrety pozostają poza Git.
- [x] Re-run `pytest -q` po poprawkach CI — SZOP 329 passed, OPOS 127 passed; oba workflowy GitHub Actions zakończone powodzeniem.
- [x] Diff review przed commitem.

## Pliki dotknięte

- `../brama/docker-compose.yml`, `Caddyfile*` — wspólny reverse proxy i konfiguracja lokalna.
- `../brama/scripts/` — orkiestracja lokalnych stosów bez usuwania danych.
- `../brama/README.md`, `DEPLOY.md`, `.env.example`, workflow — kontrakt operacyjny i walidacja.
- `../opos/docker-compose.yml`, `docker-compose.dev.yml`, `Makefile` — niezależny stos i port developerski 8002.
- `../opos/DEPLOY.md`, `README.md`, `.env.example` — wdrożenie wyłącznie przez `brama`.
- `docker-compose.yml`, `docker-compose.dev.yml`, `Makefile` — niezależny stos SZOP i port developerski 8001.
- `DEPLOY.md`, `README.md`, `.env.example` — wdrożenie SZOP wyłącznie przez `brama`.

## Hipotezy / pytania otwarte

- Produkcyjne nazwy istniejących wolumenów Caddy trzeba potwierdzić na serwerze przed cut-overem.

## Jak zweryfikować

```powershell
docker compose config
.\scripts\dev-up.ps1
.\scripts\dev-status.ps1
.\scripts\dev-down.ps1
python -m pytest -q
```

## Decyzje

- 2026-09-01: Caddy jest jedynym publicznym entrypointem; aplikacje nie publikują portów produkcyjnych.
- 2026-09-01: Dwie osobne sieci edge zamiast jednej wspólnej ograniczają komunikację między aplikacjami.
- 2026-09-01: Brak ekstrakcji wspólnego kodu Pythona, aby nie tworzyć zależności między wydaniami.

## Notatki / odkrycia w trakcie

- 2026-09-01: Niezależny commit `4d8eb04` usunął z SZOP dokumenty `app/static/docs/OPOS.docx` i `app/static/docs/OPOS.pdf`; zmiany infrastrukturalne nie modyfikowały ich zawartości.
- 2026-09-01: Docker CLI nie jest dostępny w lokalnym PATH; walidacja runtime Compose/Caddy będzie oznaczona jako wymagająca środowiska z Dockerem, a lokalnie wykonamy walidację YAML i skryptów.
- 2026-09-01: Pełne testy: SZOP 329 passed; OPOS 127 passed po ustawieniu `OPOS_PDF_BROWSER` na Chrome. Automatycznie wykryty Edge nie tworzył PDF również poza sandboxem.
- 2026-09-01: W trakcie pracy `origin/Rozwoj` otrzymał niezależny commit `4d8eb04` usuwający dwa dokumenty OPOS; bieżące zmiany infrastrukturalne opierają się już na tym commicie.
- 2026-09-01: Z indeksu Git OPOS usunięto 1837 lokalnych artefaktów `.tools`; pliki pozostały na dysku i są ignorowane. Gałąź `opos-main-clean` została odtworzona jako jeden commit z drzewem identycznym z bieżącym stanem OPOS.
- 2026-09-02: Utworzono i opublikowano publiczne repozytoria `rozgladacz/opos` i `rozgladacz/brama`; gałąź `Rozwoj` SZOP również wypchnięto. Nie wykonywano zmian na serwerze Oracle ani w DuckDNS.
- 2026-09-02: Pierwszy workflow OPOS nie widział modułów przy bezpośrednim wywołaniu `pytest`; poprawiono go na `python -m pytest`. Workflow SZOP ujawnił brak deklaracji testowej `httpx`; dodano sprawdzoną wersję `0.27.0` wyłącznie do `requirements-dev.txt`.
- 2026-09-02: GitHub Actions: `Validate gateway` w bramie, `Tests` i `OPOS Rules Drift` w OPOS oraz `Tests` w SZOP zakończone powodzeniem.
- 2026-09-02: Preflight Oracle potwierdził Docker Compose 5.1.4, małe obciążenie hosta oraz storage Caddy jako bind mounty. Brama otrzymała obsługę istniejących katalogów `/data` i `/config`, walidowaną w CI dla obu wariantów storage.
- 2026-09-02: Na Oracle utworzono chronione backupy konfiguracji, spójny backup SQLite SZOP oraz archiwum storage Caddy. Nie kopiowano ani nie wyświetlano sekretów.
- 2026-09-02: OPOS uruchomiono bez publicznego portu i zweryfikowano jako healthy/HTTP 200 w `brama-opos`. SZOP przełączono na nowy Compose z niezmienionym obrazem i bazą; SQLite quick-check przed i po zmianie: `ok`, publiczny SZOP nadal HTTP 200.
- 2026-09-02: Próba nowej bramy na loopback zakończona HTTP 200 dla obu rzeczywistych hostów. Testowy Caddy usunięto, a dotychczasowy Caddy nadal samodzielnie zajmuje 80/443 do czasu poprawnego DNS OPOS.
