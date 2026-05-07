# SZOP - Kreator armii

Serwerowa aplikacja FastAPI do budowania armii w systemie **SZOP (Szybkie Zasady Ogólnych Potyczek)** — autorskim systemie inspirowanym One Page Rules. Projekt zawiera backend z szablonami Jinja2, podstawową autoryzacją sesyjną, przykładowymi danymi i mechanizmem kalkulacji kosztów jednostek.

---

## Uruchomienie lokalne (Windows)

1. Utwórz i aktywuj środowisko wirtualne:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   .venv\Scripts\activate      # Windows
   ```
2. Zainstaluj zależności:
   ```bash
   pip install -r requirements.txt
   ```
3. Uruchom serwer deweloperski:
   ```bash
   uvicorn app.main:app --reload
   ```
   Aplikacja będzie dostępna pod adresem http://127.0.0.1:8000/.
4. Pierwsze uruchomienie tworzy automatycznie bazę danych i konto administratora `admin`/`admin`.

---

## Uruchomienie produkcyjne (Docker + Tailscale)

Szczegółowa instrukcja krok po kroku: **[DEPLOY.md](DEPLOY.md)**

Skrócona wersja:

```bash
mkdir -p /srv/szop && cd /srv/szop
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/docker-compose.yml -o docker-compose.yml
docker compose up -d
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

---

## Konfiguracja

Aplikacja korzysta z pliku `.env` (opcjonalny) ładowanego przez `python-dotenv`. Wszystkie zmienne mają rozsądne wartości domyślne — aplikacja działa bez żadnej konfiguracji.

**Sekrety są auto-generowane** przy pierwszym starcie i zapisywane do `data/`:
- `data/.secret_key` — klucz podpisywania sesji
- `data/.webhook_token` — token webhooka aktualizacji

Pełna lista zmiennych z opisami: [`.env.example`](.env.example)

Kluczowe zmienne:

| Zmienna | Domyślna | Opis |
|---|---|---|
| `SECRET_KEY` | auto-gen | Klucz sesji |
| `DB_URL` | `sqlite:///./data/szop.db` | URL bazy danych |
| `DEBUG` | `false` | Tryb debugowania |
| `SESSION_HTTPS_ONLY` | `false` | Ustaw `true` za Tailscale serve |
| `BACKUP_RETENTION_DAYS` | `14` | Retencja automatycznych backupów |
| `TRUSTED_HOSTS` | `*` | Dozwolone hosty (Host header guard) |

---

## Backup i przywracanie bazy

**Automatyczny backup:** kontener `szop-backup` (docker-compose) robi codzienną kopię o 03:00 do `data/backups/`. Retencja 14 dni (konfigurowalnie przez `BACKUP_RETENTION_DAYS`).

**Przez panel admina** (`/admin`):
- **Pobierz bazę danych** — tworzy spójną kopię przez `VACUUM INTO` i pobiera jako plik `.db`
- **Wczytaj bazę danych** — upload pliku `.db`, atomowa podmiana z walidacją struktury

Szczegóły i procedura przywracania: [DEPLOY.md — Kopia zapasowa](DEPLOY.md#kopia-zapasowa-bazy-danych)

---

## Aktualizacja aplikacji (produkcja)

Przez panel admina: `/admin` → **„Aktualizuj"** — pobiera nowy obraz z GHCR i restartuje kontener.

Lub ręcznie: `cd /srv/szop && docker compose pull && docker compose up -d`

Procedura wydawania nowych wersji (dla maintainera): [RELEASE.md](RELEASE.md)

---

## Narzędzia developerskie

- Testy: `pytest -q` (lub `make test`)
- Serwer deweloperski: `uvicorn app.main:app --reload` (lub `make dev`)

### Szybki setup testów (Windows PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-tests.ps1
```

Opcje:
- Pełna suite testów: `.\scripts\setup-tests.ps1 -RunAll`
- Dedykowany runner testów node: `.\scripts\run-node-parity-tests.ps1`
