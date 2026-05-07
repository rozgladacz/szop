# Instrukcja wydania nowej wersji — maintainer

Dokument opisuje co jest wymagane przy każdym release i jak go wykonać.

---

## Schemat wersji

Stosujemy **SemVer** (`vMAJOR.MINOR.PATCH`):

| Zmiana | Przykład |
|---|---|
| Nowe funkcjonalności niekompatybilne wstecz | `v2.0.0` |
| Nowe funkcjonalności kompatybilne wstecz | `v1.3.0` |
| Bugfixy, poprawki bezpieczeństwa | `v1.2.5` |

---

## Jak wydać release

```bash
# 1. Upewnij się że jesteś na gałęzi main z zemerge'owanymi zmianami
git checkout main
git pull

# 2. Uruchom testy lokalnie
pytest -q

# 3. Dodaj tag i wypchnij — reszta dzieje się automatycznie
git tag v1.2.3
git push origin v1.2.3
```

**Co się dzieje automatycznie** (GitHub Actions `.github/workflows/release.yml`):
1. Uruchamia testy (`pytest`) — release nie przejdzie gdy testy nie zdają
2. Buduje obraz Docker z `APP_VERSION=1.2.3`
3. Publikuje do GHCR jako `ghcr.io/rozgladacz/szop:1.2.3`, `ghcr.io/rozgladacz/szop:1.2`, `ghcr.io/rozgladacz/szop:latest`
4. Tworzy GitHub Release z auto-generowanymi notatkami z commitów

---

## Co MUSI być spełnione przed każdym release

### 1. Testy zdają

```bash
pytest -q --tb=short
```

Żaden release nie powinien wychodzić gdy testy nie przechodzą.

### 2. Migracje schemy DB są idempotentne

Każda zmiana struktury bazy danych (nowa kolumna, tabela, indeks) musi być zaimplementowana jako **funkcja idempotentna** w `app/db.py:_migrate_schema()`. Przy każdym starcie aplikacji `_migrate_schema()` jest wywoływana — musi działać zarówno na świeżej bazie jak i na istniejącej.

**Zasada:** admin robi update → nowy kontener startuje → `_migrate_schema()` bezpiecznie aktualizuje schemat → dane są nienaruszone.

**Nie używaj** nieodwracalnych operacji (`DROP TABLE`) bez wcześniejszej migracji danych.

### 3. Breaking changes — dokumentacja

Jeśli release zawiera breaking changes (zmiana API, inne zachowanie UI, wymagana ręczna akcja admina):
- Dodaj je na górze sekcji w notatce release (edytuj po auto-generowaniu)
- Oznacz w README lub DEPLOY.md jeśli wymaga akcji admina

### 4. Widoczność pakietu GHCR (jednorazowo)

Po pierwszym release należy ręcznie ustawić widoczność pakietu na **publiczną**:

1. GitHub → Profil → Packages → `szop`
2. Package settings → **Change visibility** → Public

Bez tego `docker compose pull` na serwerze wymaga logowania do GHCR.

---

## Struktura notatek release

Auto-generowane notatki z commitów są wystarczające dla większości release'ów. Dla major/minor z breaking changes dodaj ręcznie sekcję na górze:

```markdown
## ⚠️ Breaking changes

- **Wymagana akcja admina:** [opis co trzeba zrobić]
- Zmieniony endpoint `/stary` → `/nowy`

## Instalacja / aktualizacja

cd /srv/szop && docker compose pull && docker compose up -d
```

---

## Cofnięcie release (rollback tagu)

```bash
# Usuń tag lokalnie i zdalnie
git tag -d v1.2.3
git push origin :refs/tags/v1.2.3
```

> **Uwaga:** GitHub Release i obraz Docker w GHCR muszą być usunięte ręcznie przez UI GitHub.

---

## Hotfix dla konkretnej wersji

```bash
# Utwórz branch od tagu
git checkout -b hotfix/v1.2.4 v1.2.3
# ... zrób poprawkę ...
git commit -m "Hotfix: opis poprawki"
git tag v1.2.4
git push origin v1.2.4
git push origin hotfix/v1.2.4
```
