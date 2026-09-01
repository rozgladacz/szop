# HANDOFF — brama-opos-szop

> **Wątek:** Rozdzielenie infrastruktury wejściowej SZOP i OPOS do osobnego repo `brama` oraz niezależne uruchamianie obu aplikacji.
> **Status:** In progress
> **Utworzony:** 2026-09-01
> **Ostatnia aktualizacja:** 2026-09-01

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
- **Blokowane przez:** brak; aktywny wątek `rozmiar-podstawki` nie obejmuje tych plików.

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
- [~] Walidacja wszystkich konfiguracji Compose i Caddy.
- [ ] Smoke test JS — N/D, brak zmian JS.
- [ ] Call-site check — N/D, brak zmian funkcji.
- [ ] `/simplify` — przegląd jakości, reuse i powtórzeń.
- [ ] `/review` — przegląd dużego diffu infrastrukturalnego.
- [ ] `/security-review` — przegląd ekspozycji portów, sieci i sekretów.
- [ ] Re-run `pytest -q` jeśli review wprowadzi poprawki.
- [ ] Diff review przed commitem.

## Pliki dotknięte

- `../brama/docker-compose.yml`, `Caddyfile*` — wspólny reverse proxy i konfiguracja lokalna.
- `../brama/scripts/` — orkiestracja lokalnych stosów bez usuwania danych.
- `../brama/README.md`, `DEPLOY.md`, `.env.example`, workflow — kontrakt operacyjny i walidacja.
- `../opos/docker-compose.yml`, `docker-compose.dev.yml`, `Makefile` — niezależny stos i port developerski 8002.
- `../opos/DEPLOY.md`, `README.md`, `.env.example` — wdrożenie wyłącznie przez `brama`.
- `docker-compose.yml`, `docker-compose.dev.yml`, `Makefile` — niezależny stos SZOP i port developerski 8001.
- `DEPLOY.md`, `README.md`, `.env.example` — wdrożenie SZOP wyłącznie przez `brama`.

## Hipotezy / pytania otwarte

- Zdalne repozytoria `opos` i `brama` powinny odziedziczyć widoczność repo `szop`; publikacja nastąpi dopiero po audycie historii i konfiguracji.
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

- 2026-09-01: W drzewie SZOP istnieją niezacommitowane usunięcia `app/static/docs/OPOS.docx` i `app/static/docs/OPOS.pdf`; wątek ich nie dotyka.
- 2026-09-01: Docker CLI nie jest dostępny w lokalnym PATH; walidacja runtime Compose/Caddy będzie oznaczona jako wymagająca środowiska z Dockerem, a lokalnie wykonamy walidację YAML i skryptów.
- 2026-09-01: Pełne testy: SZOP 329 passed; OPOS 127 passed po ustawieniu `OPOS_PDF_BROWSER` na Chrome. Automatycznie wykryty Edge nie tworzył PDF również poza sandboxem.
- 2026-09-01: W trakcie pracy `origin/Rozwoj` otrzymał niezależny commit `4d8eb04` usuwający dwa dokumenty OPOS; bieżące zmiany infrastrukturalne opierają się już na tym commicie.
