# Instrukcja wdrożenia — administrator serwera

Dokument opisuje jak uruchomić i utrzymywać **SZOP - Kreator armii** na prywatnym serwerze Linux z Tailscale.

---

## Wymagania serwera

| Wymaganie | Wersja |
|---|---|
| Docker Engine | 24+ |
| Docker Compose | v2 (plugin, nie standalone) |
| Tailscale | najnowszy |
| RAM | ~512 MB wolnych |
| Dysk | ~2 GB (obraz + dane) |
| OS | Debian/Ubuntu LTS lub podobny |

---

## Pierwsza instalacja (5 kroków)

```bash
# 1. Utwórz katalog roboczy
mkdir -p /srv/szop && cd /srv/szop

# 2. Pobierz docker-compose.yml z repozytorium
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/docker-compose.yml -o docker-compose.yml

# 3. (Opcjonalnie) pobierz przykładowy .env i dostosuj
# curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/.env.example -o .env

# 4. Uruchom aplikację
docker compose up -d

# 5. Udostępnij przez Tailscale HTTPS (zastąp 'szop' swoją nazwą hosta)
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Aplikacja jest dostępna pod adresem: `https://<hostname>.<tailnet>.ts.net`

> **Pierwsze logowanie:** `admin` / `admin` — **zmień hasło natychmiast** w panelu administratora.

---

## Aktualizacja do nowej wersji

### Przez panel admina (zalecane)

Zaloguj się jako admin → `/admin` → kliknij **„Aktualizuj"**. Kontener pobierze nowy obraz `:latest` i zrestartuje się automatycznie.

> **Uwaga:** Wymaga zamontowania `/var/run/docker.sock` (skonfigurowane domyślnie w `docker-compose.yml`).

### Ręcznie przez terminal

```bash
cd /srv/szop
docker compose pull
docker compose up -d
```

### Konkretna wersja (zamiast :latest)

Edytuj `docker-compose.yml`, zmień `image:`:

```yaml
image: ghcr.io/rozgladacz/szop:v1.2.3   # konkretna wersja
```

Następnie:

```bash
docker compose up -d
```

### Rollback do poprzedniej wersji

```bash
# Edytuj docker-compose.yml → zmień tag obrazu na poprzednią wersję
# np. image: ghcr.io/rozgladacz/szop:v1.1.0
docker compose up -d
```

---

## Kopia zapasowa bazy danych

### Automatyczna (sidecar backup)

Kontener `szop-backup` robi kopię codziennie o 03:00 lokalnego czasu do katalogu `./data/backups/`. Pliki starsze niż 14 dni są automatycznie kasowane.

```
/srv/szop/data/backups/
├── szop-backup-20260501-030000.db
├── szop-backup-20260502-030000.db
└── ...
```

### Ręczna przez panel admina

`/admin` → sekcja **„Kopie zapasowe"** → **„Pobierz bazę danych"**. Plik `szop-backup-YYYYMMDD-HHMMSS.db` zostanie pobrany.

### Skopiowanie pliku poza serwer

```bash
# Z innego hosta (przez Tailscale SSH lub SSH):
scp root@serwer:/srv/szop/data/backups/szop-backup-*.db ./local-backups/

# Lub rsync (synchronizacja katalogu):
rsync -az root@serwer:/srv/szop/data/backups/ ./local-backups/
```

---

## Przywracanie bazy danych

### Przez panel admina (zalecane)

`/admin` → sekcja **„Kopie zapasowe"** → **„Wczytaj bazę danych"** → wybierz plik `.db`. Aplikacja podmienia bazę atomowo i przekierowuje z komunikatem sukcesu.

### Ręcznie przez terminal

```bash
cd /srv/szop

# Zatrzymaj aplikację
docker compose stop szop-app

# Podmień plik bazy (zachowaj backup!)
cp data/szop.db data/szop.db.bak
cp /ścieżka/do/backupu.db data/szop.db

# Uruchom ponownie
docker compose start szop-app
```

---

## Konfiguracja (.env)

Plik `.env` w katalogu `/srv/szop/` jest **opcjonalny** — aplikacja działa bez niego z rozsądnymi wartościami domyślnymi, w tym automatycznie generowanymi sekretami.

Kluczowe zmienne (skopiuj z `.env.example`):

| Zmienna | Domyślna | Opis |
|---|---|---|
| `SECRET_KEY` | auto-gen | Klucz podpisywania sesji. Auto-generowany do `data/.secret_key`. |
| `UPDATE_WEBHOOK_TOKEN` | auto-gen | Token webhooka update. Auto-generowany do `data/.webhook_token`. |
| `SESSION_HTTPS_ONLY` | `false` | Ustaw `true` gdy serwujesz przez Tailscale serve (HTTPS). |
| `BACKUP_RETENTION_DAYS` | `14` | Liczba dni przechowywania backupów. |
| `TRUSTED_HOSTS` | `*` | Dozwolone hosty (np. `szop.tailnet.ts.net,localhost`). |

---

## Odczytanie tokenu webhook

Jeśli chcesz wywoływać aktualizację z zewnętrznego skryptu/CI:

```bash
# Token jest zapisany w wolumenie danych
cat /srv/szop/data/.webhook_token

# Wywołanie webhook:
curl -X POST https://<host>.ts.net/admin/update/webhook \
  -H "X-Webhook-Token: <token>"
```

---

## Diagnostyka

```bash
cd /srv/szop

# Logi aplikacji (live)
docker compose logs -f szop-app

# Logi backup sidecar
docker compose logs -f szop-backup

# Status kontenerów
docker compose ps

# Logi aktualizacji (wewnątrz wolumenu)
cat data/update_logs.jsonl | tail -20

# Reset zawieszenia update (plik blokady)
rm -f data/.update.lock

# Sprawdzenie healthcheck
docker inspect szop-app | grep -A5 '"Health"'
```

---

## Tailscale — konfiguracja

```bash
# Instalacja (Debian/Ubuntu)
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up

# Udostępnienie aplikacji przez HTTPS w tailnet
tailscale serve --bg --https=443 http://127.0.0.1:8000

# Sprawdzenie statusu
tailscale serve status

# Wyłączenie (gdy chcesz zatrzymać dostęp)
tailscale serve reset
```

> **Aplikacja dostępna tylko w sieci Tailscale** — port 8000 jest wystawiony wyłącznie na `127.0.0.1`, więc bez Tailscale nie ma do niej dostępu z sieci.

---

## Backup kontener nie startuje?

Kontener `szop-backup` czeka aż `szop-app` przejdzie healthcheck (`service_healthy`). Jeśli `szop-app` nie przechodzi healthchecku, sprawdź:

```bash
docker compose logs szop-app | tail -30
```

---

## Reinstalacja (czyste środowisko)

```bash
cd /srv/szop
docker compose down
# UWAGA: poniższe usuwa bazę danych i backupy!
# Zrób kopię data/ przed kontynuacją.
rm -rf data/
docker compose up -d
```
