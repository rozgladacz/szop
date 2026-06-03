# Instrukcja wdrożenia — administrator serwera

Dokument opisuje jak uruchomić i utrzymywać **SZOP - Kreator armii**.

Dwa warianty dostępu:
- **[Wariant A] Tailscale** — prywatny, tylko zaproszeni, zero konfiguracji TLS
- **[Wariant B] Caddy + DuckDNS** — publiczny dostęp przez internet, HTTPS automatyczny

---

## Wymagania serwera

| Wymaganie | Wersja |
|---|---|
| Docker Engine | 24+ |
| Docker Compose | v2 (plugin, nie standalone) |
| RAM | ~512 MB wolnych |
| Dysk | ~2 GB (obraz + dane) |
| OS | Debian/Ubuntu LTS lub podobny |

---

## [Wariant A] Instalacja z Tailscale (prywatna sieć)

```bash
# 1. Utwórz katalog roboczy
mkdir -p /srv/szop && cd /srv/szop

# 2. Pobierz konfigurację
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/docker-compose.yml -o docker-compose.yml

# 3. Odkomentuj sekcję "ports" w docker-compose.yml dla szop-app:
#    ports:
#      - "127.0.0.1:8000:8000"
#    i usuń (lub zostaw) serwis "caddy" — przy Tailscale nie jest potrzebny

# 4. Uruchom aplikację
docker compose up -d szop-app szop-backup

# 5. Udostępnij przez Tailscale HTTPS
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Aplikacja dostępna pod: `https://<hostname>.<tailnet>.ts.net`

---

## [Wariant B] Instalacja z Caddy + DuckDNS (dostęp publiczny)

### ⚠️ Przed uruchomieniem przeczytaj

**Otwarta rejestracja + publiczny internet = każdy może założyć konto.**
Aplikacja domyślnie pozwala rejestrować się komukolwiek. Przy publicznym dostępie
boty i skanery *znajdą* twój endpoint i zarejestrują się.

Przed wystawieniem publicznie: zaloguj się jako admin i usuń lub zablokuj
niechciane konta. Docelowo rozważ dodanie flagi wyłączającej rejestrację.

### Krok 1 — DuckDNS

1. Wejdź na [duckdns.org](https://www.duckdns.org), zaloguj się
2. Utwórz subdomenę (np. `moj-szop`) → dostaniesz `moj-szop.duckdns.org`
3. Wpisz publiczne IP serwera w polu IP dla tej subdomeny
4. Jeśli IP serwera jest dynamiczne — ustaw cron aktualizujący DuckDNS co 5 minut:

```bash
# Pobierz skrypt aktualizacji (podmień TOKEN i SUBDOMAIN)
echo "*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=SUBDOMAIN&token=TOKEN&ip=' > /dev/null" \
  | crontab -
```

### Krok 2 — Porty na firewallu serwera

Otwórz porty 80 i 443 (potrzebne dla Let's Encrypt i ruchu HTTPS):

```bash
# UFW (Ubuntu/Debian)
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp   # HTTP/3 opcjonalnie

# OCI Always Free — Security List w konsoli OCI:
# Ingress: TCP port 80 i 443 z 0.0.0.0/0
```

### Krok 3 — Konfiguracja

```bash
mkdir -p /srv/szop && cd /srv/szop

# Pobierz pliki konfiguracyjne
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/Caddyfile -o Caddyfile
curl -fsSL https://raw.githubusercontent.com/rozgladacz/szop/main/.env.example -o .env

# Edytuj Caddyfile — podmień domenę
sed -i 's/twoja-domena.duckdns.org/moj-szop.duckdns.org/' Caddyfile

# Edytuj .env — podmień domenę i włącz HTTPS
sed -i 's/# TRUSTED_HOSTS=.*/TRUSTED_HOSTS=moj-szop.duckdns.org/' .env
# SESSION_HTTPS_ONLY=true jest już domyślnie w .env.example
```

### Krok 4 — Uruchomienie

```bash
docker compose up -d
```

Caddy automatycznie pobierze certyfikat Let's Encrypt przy pierwszym starcie
(wymaga działającego DNS i otwartego portu 80).

Aplikacja dostępna pod: `https://moj-szop.duckdns.org`

> **Pierwsze logowanie:** `admin` / `admin` — **zmień hasło natychmiast** w panelu administratora.

---

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
