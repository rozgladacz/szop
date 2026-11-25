# HANDOFF — wersja-angielska

Status: Ready for archive
Utworzony: 2026-11-18
Ostatnia aktualizacja: 2026-11-25
Gałąź: Rozwoj
Cel: Lokalizacja PL/EN z zachowaniem danych użytkownika i mechaniki.

## Decyzje
- Przed logowaniem cookie → Accept-Language z wagami → PL. Po zalogowaniu preferencja konta.
- Nullable preferencja jest inicjalizowana przy pierwszym logowaniu lub rejestracji.
- Cała aplikacja, opisy, karty i eksporty; własne nazwy i notatki pozostają bez zmian.
- Oficjalny słownik terminologii (Caster, brytyjska pisownia).
- Decyzja użytkownika: Niestrudzony powtarza akcje **w aktywacji**, w obu językach.
- Publiczne /downloads automatycznie pokazuje bezpośrednie PDF-y z app/static/docs.

## Plan i Layer Checklist
- [x] Model: User.preferred_language, idempotentna migracja SQLite.
- [x] Backend: request.state, POST /language, bezpieczny lokalny next, cookie, Content-Language.
- [x] Katalogi UI i 90 zdolności, formatery z językiem, złożone zdolności i mnożnik 2X.
- [x] JS i szablony: oddzielna prezentacja; zachowanie canonical label/raw/slug/value i localStorage.
- [x] Autosave przed przełączeniem; błędy blokują nawigację. Zwykłe formularze porównują stan pól, również ukrytych.
- [x] Karty, wydruki, PDF/XLSX i pliki do pobrania.
- [x] Słownik JS jako publiczny cache’owany zasób z hashem wersji, 0 SELECT.
- [x] Dokumentacja w docs/localization.md i docs/PERFORMANCE.md; indeks zaktualizowany.

## Definition of Done
- [x] Końcowy pytest -q: **405 passed** (35 nowych przypadków), w tym frontend parity.
- [x] node --check dla wszystkich modułów JS; git diff --check.
- [x] Audyt call sites: find_definition/display_with_value/description_with_value/combined_description pozostają PL domyślnie dla kosztów, parserów i zapisów. EN jest jawne wyłącznie w prezentacji. Wszystkie fabryki szablonów używają wspólnej konfiguracji.
- [x] Audyt call sites JS: formatAbilityDisplayLabel jest używane do renderowania; selektory wysyłają kanoniczne etykiety z danych opcji, nie z angielskiego textContent. Klucze Stanu Bitewnego pozostały kanoniczne.
- [x] Smoke na kopii rzeczywistej bazy: logowanie, PL/EN, Zbrojownia, Edytor Armii, Rozpiski, Kolekcja/tryb modeli, panel admina. Zapis Mastery(Shock) działa. Brak błędów konsoli w sprawdzonych widokach.
- [x] Stan Bitewny EN→PL→EN: klucz i klasa is-struck zachowane, nazwy własne bez zmian. Systemowe opisy zaklęć odbudowywane z bieżących definicji bez ładowania relacji Ability.
- [x] PDF/XLSX pobrane w obu językach; numeryczne komórki XLSX zachowane. Wszystkie 6 stron PDF (3 PL + 3 EN) wyrenderowano i obejrzano: brak ucięć, poprawne nazwy i angielskie reguły.
- [!] Ręczny test natywnego confirm: przeglądarka IAB zablokowała narzędzie na dialogu; próba dostępu do okna aplikacji zakończyła się timeoutem zgody. Nie uznano tego testu za zaliczony. Regresja Node potwierdza anulowanie zmiany języka przy niezapisanym ukrytym polu i blokadę po błędzie autosave.
- [x] Performance: A/B quote −4,0% do +2,2%, identyczne payloady, 0 dodatkowych SELECT. HTTP widoków EN +7,1% / +10,7% vs PL; po 29 SELECT w obu językach. Wyniki w docs/PERFORMANCE.md.
- [x] Ręczne przeglądy w zakresie simplify/review/security-review (komendy slash nie są dostępne w tym środowisku): usunięto redundantny zapis preferencji rejestracji, nieużywane importy, duplikaty opisów, zależność od textContent w zapisie selektora; sprawdzono IDOR, next, escaping Jinja/JS i publiczny cache bez danych użytkownika.
- [x] Ruff: brak nowych uwag względem HEAD; pełny lint repo nadal ma wcześniejsze zaległości. Nowe moduły czyste. Narzędzie doinstalowano lokalnie do ignorowanego .tools/lint.

## Koordynacja i stan środowiska
Przeczytano HANDOFF_rozmiar-podstawki; pola podstawki i silnik wyceny zachowane.
Zmiany użytkownika w zasadach i dokumentacji zachowane. Bez commitu, publikacji ani wdrożenia.
Źródłowej bazy nie migrowano; preview korzystało z .dev-data/i18n-uymhr6b3/szop.db.
Artefakty pomiaru i eksportów są w ignorowanym .dev-data.
Interpreter: G:/Projekty/_narzedzia/Python313/python.exe;
PYTHONPATH=G:/Projekty/szop/.venv/Lib/site-packages.
Testy HTTP wymagają wykonania poza sandboxem: sandbox blokuje asyncio socketpair.

## Dodatkowy przegląd na polecenie użytkownika — 2026-11-25
- [x] Simplify, code review i security review aktualnego diffu, również integracji z publicznym auth. Zachowano nowszą pracę wątku publiczne-testy oraz zmiany użytkownika. Przeglądy wykonano ręcznie; brak dostępnych komend slash tych workflow.
- [x] Komórki XLSX zapisują tekst literalnie, również prefiksy formuł i błędów Excela; liczby pozostają liczbami. Regresja po zapisie i ponownym otwarciu pliku PL/EN.
- [x] Zaklęcia broni tłumaczą wyłącznie statystyki i systemowe cechy. Nazwy z separatorem oraz notatki pozostają bez zmian; poprawiono też etykietę wielu trafień. Wersja cache obejmuje faktyczną treść wygenerowanego słownika JS, łącznie z kanonicznymi definicjami PL.
- [x] Tryb modeli blokuje przełączenie języka po edycji w trakcie zapisu. Test z opóźnionym fetch odtworzył utratę nowszej edycji przed poprawką; oba scenariusze, czysty i ze zmianą w trakcie oczekiwania, przechodzą po poprawce.
- [x] Końcowy pełny pytest: **453 passed** (16 dodatkowych regresji), w tym frontend payload parity. Ruff nowych modułów i testów i18n, node --check oraz git diff --check bez uwag. W starszych plikach pozostają wcześniejsze ostrzeżenia lint.
- [x] Call sites: helper tekstowych komórek obejmuje wiersze oddziałów, zaklęć i broni; nagłówki i sumy nie zawierają surowych nazw. spell_texts obsługuje wspólne filtry Jinja oraz localize_spells dla eksportów PDF/XLSX. translation_version jest używane wyłącznie w kontekście Jinja (cache per język, 0 SQL). Hook Trybu modeli jest wykonywany przez istniejący mechanizm beforeLanguageChange; błąd zatrzymuje formularz języka.
- [x] Smoke na osobnej kopii realnej bazy: Zbrojownia z listą broni, edytor armii z selektorami, edytor rozpiski, Tryb modeli i zapis przed zmianą języka, Kolekcja PL/EN, pobieranie i panel użytkowników. Stan Bitewny PL→EN→PL zachował is-struck oraz nazwę Szperacz. Brak błędów konsoli w sprawdzonych widokach. Wyścig podczas zapisu sprawdzony testem Node z odroczonym fetch.
- [x] Końcowy przegląd bezpieczeństwa: lokalny next, escaping Jinja/JSON/DOM, canonical dane selektorów, cache bez danych użytkownika, publiczna kontrola Origin i uprawnienia do prywatnych broni. Zamknięty finding XLSX usunięto z DEPLOY.md i odnotowano w publicznym HANDOFF. Wcześniejszy blocker publicznej publikacji — limity modeli/wyposażenia — pozostaje w zakresie publiczne-testy.

Layer Checklist: model/migracja bez zmian; backend — prezentacja reguł, wersja słownika i eksport XLSX; JS — warunek zakończenia autosave przed zmianą języka w Trybie modeli; szablony — wyłącznie kontekst wersji zasobu; CSS bez zmian; testy i18n oraz XLSX. Performance gate: 0 dodatkowych SELECT, haszowanie zasobów z pamięci z cache, brak zmian wyceny/klasyfikacji SSOT.

Środowisko dodatkowego przeglądu: starsze .venv nie obsługuje parametru client nowego TestClient (baseline 278 passed + 1 błąd wersji zależności). Weryfikację wykonywać z PYTHONPATH=.dev-data/public-upgrade;.venv/Lib/site-packages, odpowiadającym obecnemu requirements.txt, oraz izolowanym DATA_DIR/DB_URL w .dev-data/review-20261125.
Podgląd review korzystał z .dev-data/review-20261125/smoke/szop.db; źródłowa baza była otwarta wyłącznie do odczytu na czas kopiowania. Tymczasowy serwer 127.0.0.1:8879 i karty smoke zamknięto. Nie zatrzymywano odrębnego podglądu publiczne-testy na porcie 8002. Bez commitu ani wdrożenia.
