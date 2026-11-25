# Lokalizacja PL i EN

## Dane i prezentacja

UI: `app/locales/pl.json` i `en.json`, wspólne klucze. Kluczem jest polski tekst źródłowy.
Statyczne literały HTML są tłumaczone przed kompilacją Jinja; dane wstawiane przez
zmienne nie są przeszukiwane ani zastępowane. Dynamiczne teksty UI używają `t`.
Nowe teksty dodawaj do obu katalogów.

Zdolności: polskie definicje w `app/data/abilities.py`, angielskie nazwy i opisy
w `app/locales/abilities.en.json`, kluczem jest stabilny slug. Terminologia:
[oficjalny słownik](translation-glossary.md). Zdolności z parametrami korzystają
ze wspólnych formatterów z opcjonalnym językiem; domyślny `pl` zachowuje kontrakt
zapisu i silnika. `display_label`/`display_description` służą wyłącznie prezentacji.
Nie nadpisuj nimi `label`, `raw`, `slug`, `value` ani kluczy loadoutu.

Nazwy i notatki użytkownika pozostają bez zmian. W `Nazwa [Reguła]` tłumaczy się
wyłącznie regułę w nawiasie. Selektory zachowują kanoniczne etykiety w danych opcji.
Stan Bitewny używa dotychczasowych kluczy `data-ability-toggle` i localStorage.

## Język i interfejsy

Przed logowaniem: cookie → Accept-Language (wagi i warianty regionalne) → PL.
Po logowaniu: preferencja konta; konto bez preferencji przejmuje bieżący język
przy logowaniu/rejestracji. Migracja SQLite dodaje nullable `preferred_language`.
`POST /language` zapisuje `pl`/`en`, aktualizuje cookie i przekierowuje wyłącznie lokalnie.

`GET /i18n/{language}.js` udostępnia publiczny słownik bez zapytań DB.
URL zawiera hash treści; odpowiedź może być cache’owana między ekranami.
Hash obejmuje cały wygenerowany skrypt, także polskie definicje reguł.
Nowy edytor z autosave powinien rejestrować Promise w `beforeLanguageChange`;
błąd blokuje przejście. Pozostałe formularze porównują stan pól z początkiem edycji.
W Trybie modeli nowa edycja podczas oczekiwania na zapis również blokuje przejście.

Eksport XLSX zapisuje nazwy i pozostałe teksty jako komórki tekstowe, także gdy
zaczynają się od `=` lub przypominają kod błędu Excela. Liczby pozostają liczbami.

`GET /downloads` pokazuje wszystkie bezpośrednie PDF-y z `app/static/docs`,
w obu językach równocześnie, pod oryginalnymi nazwami. DOCX i podkatalogi są pomijane.

## Weryfikacja

`tests/test_i18n.py`, `tests/test_frontend_i18n.py`, istniejące frontend parity,
pełny pytest oraz smoke PL/EN na kopii rzeczywistej bazy. Pomiar wydajności:
[PERFORMANCE.md](PERFORMANCE.md). Zasady tworzenia przekładów:
[translation-guidelines.md](translation-guidelines.md).
