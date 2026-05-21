# Developing — konwencje kodu

## INCH / smart quotes — krytyczna konwencja

Symbol cala (inch, U+201D `”`) jest *daną*, nie składnią. Nieprawidłowe użycie generuje SyntaxError po automatycznej konwersji przez narzędzia Edit.

### Reguły

- Kanoniczna stała: **`INCH`** w `app/data/abilities.py`, wartość `U+201D` (RIGHT DOUBLE QUOTATION MARK).
- **W opisach abilities** (`app/data/abilities.py`): U+201D jest osadzony bezpośrednio w stringach — **nie ruszaj**.
- **W nowym kodzie** (f-strings, labels, tests): zawsze `INCH` lub escape `"”"`. Nigdy bare ASCII `"` jako symbol cala.

| Sytuacja | Tak | Nie |
|---|---|---|
| f-string z calem | `f'{name}(12{INCH})'` lub `f'{name}(12”)'` | `f'{name}(12")'` |
| Delimiter stringa Pythona | `'...'` lub `"..."` (ASCII) | `"..."` lub `'...'` (smart quotes) |

**Dlaczego "wrong":** narzędzie Edit może skonwertować `"..."` na pary curly-quote, łamiąc delimiter Python → SyntaxError.

### Edytowanie `app/data/abilities.py`

- **Bloki z embedded U+201D w opisach** → **wyłącznie Python script przez Bash** (`Write` skryptu, run via `Bash`). Nigdy nie używaj narzędzia `Edit` na tych blokach.
- **Bloki bez inch strings** (nowa standalone funkcja/stała) → narzędzie Edit OK, *pod warunkiem* że delimitery są single-quoted (`'...'`) w całym bloku.

### Encoding gate

Przed każdym `Edit` lub `Write` na pliku `.py`:

```python
open(file, encoding='utf-8').read()
```

Jeśli rzuca błąd — **przerwij**, nie podstawiaj znaków po cichu.

### Delimiters — twardszy zakaz

**NIGDY** nie używaj typograficznych / smart quotes (U+201C, U+201D, U+2018, U+2019) jako Python string delimiters. Delimitery muszą być **straight ASCII**: `'...'` lub `"..."`.

## Konwencje zmian

- **Nie zmieniaj formatowania poza zakresem zadania.** Bug fix nie wymaga okolicznego cleanupu.
- **Nie wprowadzaj refaktorów przy okazji.** Jedna zmiana = jeden cel.
- **Bug fix:** opisz przyczynę i zakres poprawki w commit message.
- **Zmiana modelu dziedziczenia:** sprawdź zgodność z edycją wariantów potomnych.
- **Duże usunięcia z monolitów** (`app.js`, `rosters.py`, `armies.py`): podziel na osobne commity per kategoria (stałe, funkcje kosztowe, helpery UI). Jeden commit ≤ ~150 linii z jednego pliku bez grep-weryfikacji każdej usuwanej funkcji.

## Komentarze sekcji w monolitach

Pliki `app/static/js/app.js`, `app/services/costs/_engine.py`, `app/routers/rosters.py` mają komentarze sekcji w formacie:

- JS: `// === SECTION: Nazwa — opis ===`
- Python: `# === SECTION: Nazwa — opis ===`

### Zasady utrzymania

- **Analizując plik** — przeczytaj komentarze sekcji **jak mapę**, zanim zaczniesz przeszukiwać kod.
- **Dodając nową funkcję** — umieść ją w odpowiedniej sekcji. Jeśli nie pasuje — dodaj nowy nagłówek sekcji.
- **Przenosząc lub usuwając funkcję** wymienioną w nagłówku — zaktualizuj listę funkcji w komentarzu.
- **Tworząc nowy plik z logiką** (>100 linii) — dodaj komentarze sekcji od razu.
- **Krótkie helpers** (<50 linii) i szablony HTML — bez komentarzy sekcji.

## Przenoszenie dużych bloków kodu między plikami

Gdy przenosisz blok > 100 linii do nowego pliku (ekstrakcja submodułu):

- **Nie używaj `Write` z pełną treścią funkcji** — całe ciało trafia do kontekstu rozmowy i zużywa budżet.
- **Używaj Bash + Python text-surgery:** odczytaj plik, wytnij blok po unikalnym komentarzu sekcji (`# === SECTION: ...`), zapisz do nowego pliku z dopisanym nagłówkiem, usuń z oryginału. **Ciało funkcji NIGDY nie wchodzi do kontekstu Claude.**

Wzorzec:

```python
# Ekstrakcja sekcji z _engine.py → nowy_modul.py
import pathlib

src = pathlib.Path('app/services/costs/_engine.py')
text = src.read_text(encoding='utf-8')

start = text.index('\n# === SECTION: NazwaSekcji')
end   = text.index('\n# === SECTION: NastepnaSekcja')
body  = text[start:end]

header = '"""Docstring nowego modułu."""\n\nfrom __future__ import annotations\n...\n'
pathlib.Path('app/services/costs/nowy_modul.py').write_text(
    header + body.lstrip('\n'),
    encoding='utf-8',
)

stub = '\nfrom .nowy_modul import (\n    funkcja1,\n    funkcja2,\n)\n'
src.write_text(text[:start] + stub + text[end:], encoding='utf-8')
```

Po ekstrakcji:
- Zaktualizuj `__init__.py` (dodaj moduł do `from . import ...`).
- Uruchom `pytest -q`.
- **Circular import jest OK** jeśli nowy moduł importuje z `_engine`, a `_engine` importuje z nowego modułu — stałe/dataclassy są definiowane w `_engine` **przed** stubem `from .nowy_modul import`.

## Stop-and-revert

Jeśli user mówi **'nie'**, **'wrong'**, **'cofnij'** lub równoważne — **zatrzymaj się, odwróć ostatnią zmianę, zapytaj o uściślenie** przed nową próbą.

## Pomocnicze konwencje

- **Czytaj pliki batchami** (parallel tool calls), nie pojedynczo.
- **Jeśli wymaganie jest niejasne** — najpierw wypisz założenia i braki, zapytaj.
- **Po wykonaniu zmian** — podaj: co zmieniono, jak zweryfikowano, co wymaga decyzji.

Detale planowania: `docs/planning.md`. Detale testów: `docs/testing.md`. Konwencje git: `docs/git-workflow.md`.
