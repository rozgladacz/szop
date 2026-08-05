# Wdrożenie OPOS

## Wymagania

- Docker Engine 24+ i Docker Compose v2,
- około 512 MB wolnej pamięci,
- trwały katalog danych, domyślnie `/srv/opos/data`.

## Instalacja

Docelowym kanałem jest `rozgladacz/opos`. Do czasu utworzenia repozytorium można budować obraz lokalnie z bieżącego worktree.

```bash
mkdir -p /srv/opos
cd /srv/opos
# skopiuj docker-compose.yml, Caddyfile i opcjonalny .env
docker compose up -d --build
```

Pierwszy start tworzy `data/opos.db`, użytkownika `admin` i losowe hasło w `data/.initial_admin_password`:

```bash
cat /srv/opos/data/.initial_admin_password
```

Po pierwszym logowaniu zmień hasło w panelu administracyjnym.

## Dostęp

Compose domyślnie wystawia aplikację przez Caddy. Ustaw domenę w `Caddyfile`, `TRUSTED_HOSTS` i `SESSION_HTTPS_ONLY=true`. Przy prywatnym Tailscale można wystawić aplikację wyłącznie na loopback i użyć:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

## Dane i backup

Serwis `opos-backup` codziennie tworzy w `data/backups/` pliki `opos-backup-YYYYMMDD-HHMMSS.db`. Panel `/admin` pozwala pobrać spójną kopię i wczytać bazę po walidacji schematu OPOS.

Przed odtworzeniem ręcznym zatrzymaj aplikację i zachowaj obecną bazę. Nie podmieniaj `opos.db` bazą SZOP — bootstrap świadomie odrzuca stary schemat.

```bash
cd /srv/opos
docker compose stop opos-app
cp data/opos.db data/opos.db.bak
cp /ścieżka/do/opos-backup.db data/opos.db
docker compose start opos-app
```

## Aktualizacja

Panel admina wykonuje `docker compose pull opos-app` i `docker compose up -d opos-app`. Wymaga montowania socketu Dockera; usuń ten mount, jeśli aktualizator UI nie jest potrzebny.

Ręcznie:

```bash
cd /srv/opos
docker compose pull
docker compose up -d
```

## Diagnostyka

```bash
docker compose ps
docker compose logs -f opos-app
docker compose logs -f opos-backup
cat data/update_logs.jsonl | tail -20
```

Sekrety `.secret_key`, `.initial_admin_password` i `.webhook_token` oraz cała baza pozostają wyłącznie w trwałym katalogu `data/`.
