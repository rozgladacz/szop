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
docker compose config --quiet
umask 077
cp docker-compose.yml docker-compose.pre-change.yml
test ! -f .env || cp .env .env.pre-change
```

Pobierz spójny backup z panelu administratora albo utwórz go mechanizmem aplikacji. Nie kopiuj działającego pliku SQLite zwykłym `cp` bez zatrzymania aplikacji.

## Instalacja lub uzgodnienie stosu

```bash
mkdir -p /srv/szop
cd /srv/szop
umask 077
test -f .env || cp .env.example .env
chmod 600 .env
# Ustaw SZOP_IMAGE na konkretny tag i skonfiguruj dostęp według sekcji poniżej.
docker network inspect brama-szop >/dev/null
docker compose config --quiet
docker compose pull szop-app szop-backup
docker compose up -d --wait szop-app szop-backup
```

Kontenery korzystają z `/srv/szop/data`. Nie twórz pustej bazy w miejsce istniejącej produkcyjnej `data/szop.db`.

## Publiczne testy

Kontener `szop-app` działa za Caddy z repo `brama` w izolowanej sieci `brama-szop`. W `.env` wpisz domenę widoczną w przeglądarce i stały adres Caddy w tej sieci. `localhost` jest potrzebny do healthchecku kontenera.

```dotenv
PUBLIC_ORIGIN=https://twoj-szop.duckdns.org
TRUSTED_HOSTS=twoj-szop.duckdns.org,localhost
SESSION_HTTPS_ONLY=true
FORWARDED_ALLOW_IPS=172.30.30.10
REGISTRATION_OPEN=false
```

Adres `172.30.30.10` jest przykładem. W repo `brama` przypisz adres Caddy w `services.caddy.networks.szop-edge.ipv4_address`. Sieć używana ze stałym adresem wymaga jawnej podsieci. Sprawdź członków sieci i adres Caddy przez `docker network inspect brama-szop`. Uvicorn 0.29.0 przyjmuje listę dokładnych adresów IP. Ogranicz zaufanie do nagłówków proxy do Caddy i zweryfikuj, że port aplikacji pozostaje niedostępny bezpośrednio z internetu. [Obsługa nagłówków proxy w Uvicorn 0.29.0](https://github.com/Kludex/uvicorn/blob/0.29.0/uvicorn/middleware/proxy_headers.py) · [Konfiguracja podsieci Docker](https://docs.docker.com/reference/cli/docker/network/create/#specify-advanced-options)

Przed startem zweryfikuj konta w bazie przeznaczonej do publikacji. Jeśli administrator wymaga inicjalizacji lub rotacji hasła fabrycznego, ustaw na pierwszy start `INITIAL_ADMIN_PASSWORD` na losowe hasło o długości co najmniej 15 znaków. Zapisz je w menedżerze haseł i usuń zmienną po udanym starcie i sprawdzeniu logowania. Publiczny tryb odrzuca start z hasłem fabrycznym i wymaga ciasteczek Secure oraz skonfigurowanych hostów. Zmień także każde hasło odziedziczone ze śledzonej bazy startowej `seeds/szop.db.seed` lub przygotuj bazę demonstracyjną z tymi samymi katalogami gry i nowymi kontami. Przy rotacji po potencjalnym użyciu starego hasła wygeneruj też nowy `SECRET_KEY`, aby unieważnić stare ciasteczka sesji.

W publicznym bloku SZOP w Caddyfile ustaw ograniczenie ciała żądań. Poniższy fragment dopisz przed `reverse_proxy` i sprawdź przez `caddy validate` w repo `brama`. [Dokumentacja limitu ciała żądania w Caddy](https://caddyserver.com/docs/caddyfile/directives/request_body)

```caddyfile
@auth path /auth/*
@other not path /auth/*
request_body @auth {
    max_size 4096
}
request_body @other {
    max_size 1MB
}
```

Zostaw jeden kontener aplikacji z jednym workerem. Jeden proces współdzieli liczniki prób logowania i rejestracji w RAM. Uvicorn przyjmuje domyślnie do 64 równoległych połączeń lub zadań i odrzuca nadmiar statusem `503`. Wartość można ustawić przez `UVICORN_LIMIT_CONCURRENCY` w `.env`.

Po weryfikacji HTTPS, logowania administratora, kopii zapasowej i konfiguracji Caddy ustaw `REGISTRATION_OPEN=true` albo usuń tę zmienną i włącz rejestrację w panelu administratora. Jawna wartość w `.env` ma pierwszeństwo przed panelem. Formularz wymaga pseudonimu i hasła oraz zawiera pole pułapkę dla prostych botów. Na pierwszą turę testów ustaw losowy `PUBLIC_REGISTRATION_CODE` i udostępniaj go zainteresowanym osobno. Sam podpis formularza i pole pułapka ograniczają proste automaty. Rejestracja tworzy do jednego konta na 60 sekund i zatrzymuje się przy 100 kontach. Usuwanie użytkowników przez publiczny panel jest wyłączone, aby prywatne dane nie stały się wspólne. Adresy IP służą aplikacji do krótkotrwałego ograniczania prób w pamięci, baza ich nie zapisuje. Log dostępu Uvicorn jest wyłączony w obrazie. Caddy ma niezależny log dostępu, który może zawierać IP i parametry URL. Jeśli potrzebujesz logu, skonfiguruj odfiltrowanie tych pól, krótki okres przechowywania i ograniczony dostęp do plików. [Filtrowanie logów Caddy](https://caddyserver.com/docs/caddyfile/directives/log)

Do publicznych testów użyj obrazu z FastAPI 0.162.3, Starlette 1.9.0, `python-multipart` 0.0.32 i Jinja2 3.1.6. Te wersje obejmują poprawki dla zgłoszonych problemów z parsowaniem formularzy i plikami statycznymi. Po zbudowaniu obrazu sprawdź logowanie, rejestrację, limit prób i brak niepotrzebnych danych w logach Caddy. [Komunikaty bezpieczeństwa Starlette](https://github.com/Kludex/starlette/security/advisories) · [Komunikaty bezpieczeństwa python-multipart](https://github.com/Kludex/python-multipart/security/advisories) · [Jinja 3.1.6](https://github.com/pallets/jinja/releases/tag/3.1.6)

### Otwarte ustalenia audytu

- Publiczne zapisy i wycena wymagają limitów liczby modeli oraz łącznej liczby instancji wyposażenia na oddział. Dotychczasowe operacje w `app/routers/rosters.py`, `app/routers/armies.py` i `app/services/collection_match.py` mogą przyjąć małe żądanie opisujące kosztowne obliczenie. Zakończ tę poprawkę przed otwarciem samodzielnej rejestracji.
- Zanim użyjesz dotychczasowej bazy do testów, zweryfikuj konta i prywatne rozpiski. Śledzona kopia startowa zawiera odziedziczone konto testowe i prywatne rekordy. Dla publicznego pokazu użyj osobnej bazy z zatwierdzonymi danymi gry oraz nowymi kontami.

## Dostęp lokalny

Do lokalnego uruchomienia kontenerowego użyj `scripts/dev-up.ps1` z repo `brama`. Bez bramy:

```powershell
docker network inspect brama-szop *> $null
if ($LASTEXITCODE -ne 0) { docker network create brama-szop }
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build szop-app
```

SZOP będzie dostępny na `http://127.0.0.1:8001`, z osobnymi danymi w `.dev-data`.

Do lokalnego sprawdzenia chronionej rejestracji uruchom osobny proces Uvicorna z `--host 127.0.0.1 --port 8002 --no-proxy-headers` na kopii rzeczywistej bazy. Ustaw dla niego `LOCAL_PUBLIC_PREVIEW=true`, `PUBLIC_ORIGIN=http://127.0.0.1:8002`, `TRUSTED_HOSTS=127.0.0.1`, `SESSION_HTTPS_ONLY=false`, `DEBUG=false` oraz `REGISTRATION_OPEN=true`. Skieruj `DATA_DIR` i `DB_URL` na katalog i plik kopii, a jeśli kopia zawiera fabryczne hasło administratora, ustaw losowe `INITIAL_ADMIN_PASSWORD` zgodnie z sekcją o testach publicznych. Formularz będzie dostępny na `http://127.0.0.1:8002/auth/register`. Tryb podglądu wymaga połączeń po loopback i jest przeznaczony do lokalnego procesu bez reverse proxy.

## Aktualizacja

Przed aktualizacją zapisz bieżący tag lub digest `SZOP_IMAGE` i wykonaj backup. Następnie:

```bash
cd /srv/szop
docker compose pull szop-app szop-backup
docker compose up -d --wait szop-app szop-backup
```

Polecenia nie zmieniają stosów `opos` ani `brama`. Rollback polega na przywróceniu poprzedniej wartości `SZOP_IMAGE` i ponownym uruchomieniu tego samego polecenia `up`.

Aktualizuj usługę z powłoki hosta. Standardowy Compose nie montuje gniazda Dockera do aplikacji. W publicznym trybie aktualizację, pobieranie pełnego backupu i przywracanie wykonuj poza panelem. Instalacja prywatna korzystająca z własnego obrazu zawierającego klienta Docker może optować za osobnym plikiem Compose z dostępem do demona, jeśli instalacja świadomie przyznaje aplikacji te uprawnienia.

## Automatyczny backup

`szop-backup` wykonuje codzienną kopię do `data/backups/`. Retencję i godzinę kontrolują `BACKUP_RETENTION_DAYS` oraz `BACKUP_HOUR`.

Kopię poza serwer można zsynchronizować po SSH. W trybie prywatnym można ją też pobrać przez panel administratora.

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

Sekrety `.secret_key`, `.webhook_token`, plik `.env`, jego kopie oraz baza wymagają ograniczonego dostępu.
