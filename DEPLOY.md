# Wdrożenie SZOP

SZOP jest niezależnym stosem aplikacyjnym. Publiczne porty, certyfikaty i routing należą do osobnego repozytorium `brama`.

## Wymagania

- Docker Engine 24+ i Docker Compose 2.24.4+,
- działająca zewnętrzna sieć `brama-szop`,
- dostęp do obrazu `ghcr.io/rozgladacz/szop`,
- trwały katalog `/srv/szop/data` z produkcyjną bazą SZOP.

## Preflight i backup

Przed zmianą obrazu lub konfiguracji:

```bash
cd /srv/szop
docker compose ps
docker compose config > docker-compose.effective.yml
cp docker-compose.yml docker-compose.pre-change.yml
cp .env .env.pre-change
```

Pobierz spójny backup z panelu administratora albo utwórz go mechanizmem aplikacji. Nie kopiuj działającego pliku SQLite zwykłym `cp` bez zatrzymania aplikacji.

## Instalacja lub uzgodnienie stosu

```bash
mkdir -p /srv/szop
cd /srv/szop
cp .env.example .env
# Ustaw SZOP_IMAGE na konkretny tag i TRUSTED_HOSTS na publiczną domenę SZOP.
docker network inspect brama-szop >/dev/null
docker compose config --quiet
docker compose pull szop-app szop-backup
docker compose up -d --wait szop-app szop-backup
```

Kontenery korzystają z `/srv/szop/data`. Nie twórz pustej bazy w miejsce istniejącej produkcyjnej `data/szop.db`.

## Dostęp

Kontener `szop-app` nie publikuje portu hosta. Caddy z repo `brama` łączy się z `szop-app:8000` przez izolowaną sieć `brama-szop`. Na produkcji ustaw:

```dotenv
TRUSTED_HOSTS=twoj-szop.duckdns.org
SESSION_HTTPS_ONLY=true
```

Do lokalnego uruchomienia kontenerowego użyj `scripts/dev-up.ps1` z repo `brama`. Bez bramy:

```powershell
docker network inspect brama-szop *> $null
if ($LASTEXITCODE -ne 0) { docker network create brama-szop }
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build szop-app
```

SZOP będzie dostępny na `http://127.0.0.1:8001`, z osobnymi danymi w `.dev-data`.

## Aktualizacja

Przed aktualizacją zapisz bieżący tag lub digest `SZOP_IMAGE` i wykonaj backup. Następnie:

```bash
cd /srv/szop
docker compose pull szop-app szop-backup
docker compose up -d --wait szop-app szop-backup
```

Polecenia nie zmieniają stosów `opos` ani `brama`. Rollback polega na przywróceniu poprzedniej wartości `SZOP_IMAGE` i ponownym uruchomieniu tego samego polecenia `up`.

## Automatyczny backup

`szop-backup` wykonuje codzienną kopię do `data/backups/`. Retencję i godzinę kontrolują `BACKUP_RETENTION_DAYS` oraz `BACKUP_HOUR`.

Kopię poza serwer można pobrać przez panel administratora albo zsynchronizować po SSH:

```bash
rsync -az root@serwer:/srv/szop/data/backups/ ./local-backups/
```

## Ręczne przywracanie

```bash
cd /srv/szop
docker compose stop szop-app szop-backup
cp data/szop.db data/szop.db.before-restore
cp /ścieżka/do/zweryfikowanego-backupu.db data/szop.db
docker compose up -d --wait szop-app szop-backup
```

Nie uruchamiaj starszego obrazu z nowszym schematem bez potwierdzonej zgodności migracji.

## Diagnostyka

```bash
cd /srv/szop
docker compose ps
docker compose logs --tail 100 szop-app
docker compose logs --tail 100 szop-backup
cat data/update_logs.jsonl | tail -20
docker network inspect brama-szop
```

Sekrety `.secret_key`, `.initial_admin_password`, `.webhook_token`, plik `.env` oraz cała baza pozostają wyłącznie na serwerze.
