# HANDOFF — publiczne-testy

> Status: Gotowe do przeglądu lokalnego, publikacja wstrzymana
> Gałąź: Rozwoj
> Data: 2026-11-23

## Cel

Publiczna rejestracja na pseudonim i hasło, z limitami, oraz defensywny audyt kodu i konfiguracji przed udostępnieniem linku.

## Plan implementacji i warstwy

- [x] Audyt kodu i wdrożenia, z zachowaniem zmian i18n. Findings i instrukcja uruchomienia w `DEPLOY.md`.
- [x] Model/migracja: osobne tabele SQLite dla limitu rejestracji i sesji publicznych; bez zmian `User` i pól wyceny.
- [x] Backend: `PUBLIC_ORIGIN`, limit 100 istniejących kont na ścieżce rejestracji, jedna udana co 60 s, throttling, kod opcjonalny, sesje odwoływalne, kontrola origin, bootstrap admina i hasła publiczne 15–128 znaków.
- [x] Szablony: formularze auth, wylogowanie przez POST, widok admina i oba katalogi językowe. Bez zmian CSS i JS w tym wątku.
- [x] Izolacja prywatnych broni zaklęć, bez automatycznego upubliczniania danych po usunięciu konta w trybie publicznym.
- [x] FastAPI 0.162.3, Starlette 1.9.0, `python-multipart` 0.0.32, Jinja2 3.1.6. Walidacja obu konfiguracji Compose.
- [x] Call-site check, simplify, review i niezależny security review. `get_current_user` współdzieli jeden indeksowany odczyt użytkownika z sesją. Wylogowanie w widoku i teście i18n używa POST. Zachowano lokalny tryb rejestracji i admina poza opt-in.
- [x] Końcowy pytest na nowych wersjach: 431 passed. Smoke TestClient na izolowanej kopii realnej bazy z HTTPS, rotacją fabrycznego hasła, rolami, rejestracją i wylogowaniem. Ruff nowych modułów i diff check bez uwag.
- [ ] Wdrożenie i publikacja. Otwarte: ograniczenia liczebności i instancji wyposażenia, czysta baza demo lub przegląd danych i rotacja kont, Caddy IP/limity/logi i smoke na docelowej bramie. Finding XLSX zamknięty 2026-11-25 w dodatkowym review wątku wersja-angielska: teksty są komórkami tekstowymi; regresje obejmują ponowne otwarcie pliku PL/EN.

## Performance gate

Na gorących ścieżkach dotychczasowe wyszukanie użytkownika zastąpi pojedynczy odczyt sesji z użytkownikiem po kluczu sesji. 0 dodatkowych zapytań na żądanie i 0 na oddział. Dodatkowe zapisy wyłącznie przy auth, z limitem pojemności i bez zmian SSOT.

## Środowisko

Pierwszy przebieg istniejącego testu zapisał ignorowany lokalny `data/settings.json` z `registration_open=true`. Stan tej flagi sprzed testu nie był znany. Fixture używa odtąd tymczasowej ścieżki. Dalsze przebiegi ustawiały izolowane `DATA_DIR` i `DB_URL`; źródłową bazę do smoke otwarto tylko do odczytu.

## Podgląd lokalny — 2026-11-25

- [x] Zwykły launcher startuje w trybie prywatnym, a Docker Desktop nie działał. Uruchomiono osobny proces Uvicorna na kopii rzeczywistej bazy w ignorowanym `.dev-data`.
- [x] Layer Checklist: osobny opt-in `LOCAL_PUBLIC_PREVIEW` i kontrola źródła/celu w middleware. Bez zmian modelu, payloadu, szablonów, JS i CSS, 0 dodatkowych zapytań. Wymóg HTTPS dla publicznego wdrożenia potwierdzony testem.
- [x] `http://127.0.0.1:8002/auth/register` zwraca 200 z chronionym formularzem i minimum 15 znaków. Podgląd zostawiono uruchomiony. Pełny pytest 437 passed, testy celowane 27 passed, Ruff i diff check bez uwag. Call sites: walidacja startu przez `init_db`, ograniczenie w `PublicAccessMiddleware`, konfiguracja w `DEPLOY.md`. Ręczny simplify/review/security review potwierdził jawny opt-in i loopback.

## Hasła kont testowych

- [~] Layer Checklist: minimum 8 dla graczy, 15 dla administratorów w publicznym trybie. Wspólne granice walidacji, rejestracja, panel tworzenia/resetu, szablony i katalogi PL/EN, testy regresji. Bez zmian bazy, JS, CSS i zapytań na gorących ścieżkach. Ochrona antybotowa pozostaje w istniejącej warstwie auth.
- [ ] Pełny pytest, przegląd wywołań i wznowienie podglądu na dotychczasowej kopii.
