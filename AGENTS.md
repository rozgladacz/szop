# AGENTS.md

## Project Context
- This is an OPR (One Page Rules) wargame tooling project. Tests live alongside Python rule logic; weapon/ability costs and rule parameters are SSOT-driven. After rule changes, verify both backend payloads and JS rendering layers.

## Testing
- ALWAYS run the full test suite (e.g., `pytest` or `make test`) after making code changes, before declaring a task complete. Do not wait for the user to ask.
- Running `pytest` is **not optional** even for 'trivial' one-line changes. The PostToolUse hook enforces this; do not suppress hook output.

## Cel projektu
Aplikacja służy do przygotowywania list (Rozpisek) do gry.

Główne obszary:
- Rozpiski
- Armie
- Zbrojownie

Zależności:
- Rozpiski są budowane na podstawie Armii.
- Armie są budowane na podstawie Zbrojowni.
- Zasady gry znajdują się w `app/static/docs` i są źródłem prawdy.

## Model danych i dziedziczenie
- Armie i Rozpiski muszą wspierać hierarchię i dziedziczenie.
- Wariant ma przechowywać tylko różnice względem bazy.
- Nie duplikuj pełnego stanu, jeśli wystarczą nadpisania.
- Zachowuj stabilne identyfikatory obiektów, jeśli już istnieją.
- Zmiana modelu danych musi uwzględniać wpływ na warianty potomne.

## Baza danych
- Traktuj bazę jako środowisko testowe, ale współdzielone.
- Nie wykonuj destrukcyjnych operacji bez wyraźnego polecenia. Zawsze trzymaj kopię zapasową.
- Jeśli zadanie wymaga migracji lub zmian danych, opisz ich wpływ i przygotuj proces migracji.
- Przed zakończeniem prac i udostępnieniem Preview do akceptacji podłącz bazę z danymi produkcyjnymi (`data/opr.db`). Preview z pustą bazą nie nadaje się do weryfikacji przez użytkownika.
- Zawsze trzymaj kopię oryginalnej bazy (`data/opr.db.backup` lub commit w git), aby móc ją przywrócić po testach. Wersja w git jest źródłem prawdy — przywracaj przez `git show <commit>:data/opr.db > data/opr.db`.

## Użytkownicy i uprawnienia
- System ma mieć dwa poziomy dostępu:
  - `admin`
  - `user`
- Funkcje administracyjne muszą być jawnie odseparowane od zwykłego użytkownika.
- Nie rozszerzaj uprawnień użytkownika bez wyraźnego wymagania.

## Dokumentacja reguł
- Pliki w `app/static/docs` są tylko do odczytu.
- Nie modyfikuj ich bez osobnego zadania.
- Jeśli kod i dokumentacja są sprzeczne, zatrzymaj się i opisz rozbieżność.
- Nie zgaduj znaczenia reguły, jeśli nie wynika ono jasno z dokumentu lub kodu.

## Zasady pracy
- Najpierw czytaj istniejący kod, potem edytuj.
- Dla zadań wieloetapowych najpierw przygotuj krótki plan.
- Dla zadań prostych wykonuj minimalny lokalny patch.
- Nie przebudowuj architektury bez potrzeby.
- Preferuj małe, odwracalne zmiany.
- Before writing any code, list every layer this change touches (data model, backend payload, JS render, CSS, tests). Then implement each layer and run tests. After tests pass, walk me through how you verified each layer end-to-end.
- As you work on a prolonged task, maintain a `HANDOFF.md` file. **Update HANDOFF.md BEFORE starting each major sub-task** (not only at end of session) — context windows can be exhausted mid-work, and an end-of-session update may never happen. Treat it as a pre-step checkpoint, not a post-step summary.
- `HANDOFF.md` has two distinct zones — treat them differently:
  - **BIEŻĄCE ZADANIE** (volatile): overwrite entirely at the start of each new unrelated task. Set "Cel" to the new task; clear "W toku", "Pliki dotknięte", "Hipotezy", "Jak zweryfikować".
  - **WIEDZA PROJEKTU** (stable): never clear on task switch — only update when architecture genuinely changes (e.g. new module added, performance baseline revised).
- **Task-switch protocol**: when the user gives a task that differs from the current "Cel" in HANDOFF.md — (1) add a log entry closing the previous task, (2) overwrite BIEŻĄCE ZADANIE with the new task before writing any code.
- **Plan file as BIEŻĄCE ZADANIE**: when an active plan file exists (plan mode → execute flow), treat the plan file as the source of truth for current task state — do NOT duplicate "W toku" / steps / files into HANDOFF.md. Only update HANDOFF.md in WIEDZA PROJEKTU (if architecture changed) and LOG SESJI (brief closing entry after task is done). For direct tasks without a plan file (hotfix, quick bugfix), use BIEŻĄCE ZADANIE in HANDOFF.md as usual.

## Przenoszenie dużych bloków kodu między plikami
Gdy przenosisz blok kodu > 100 linii do nowego pliku (np. ekstrakcja submodułu):
- **Nie używaj narzędzia `Write` z pełną treścią funkcji** — całe ciało trafia do kontekstu rozmowy i zużywa budżet na rzecz, która nie wnosi wartości analitycznej.
- **Używaj Bash + Python text-surgery:** odczytaj plik, wytnij blok po granicach tekstowych (unikalny komentarz sekcji lub `def`), zapisz do nowego pliku (z nagłówkiem dopisanym przez Python), usuń z oryginału. Ciało funkcji NIGDY nie wchodzi do kontekstu Claude.

```python
# Wzorzec: ekstrakcja sekcji z _engine.py → nowy_modul.py
import pathlib
src = pathlib.Path('app/services/costs/_engine.py')
text = src.read_text(encoding='utf-8')

start = text.index('\n# === SECTION: NazwaSekcji')
end   = text.index('\n# === SECTION: NastepnaSekcja')
body  = text[start:end]

header = '"""Docstring nowego modułu."""\n\nfrom __future__ import annotations\n...\n'
pathlib.Path('app/services/costs/nowy_modul.py').write_text(header + body.lstrip('\n'), encoding='utf-8')

stub = '\nfrom .nowy_modul import (\n    funkcja1,\n    funkcja2,\n)\n'
src.write_text(text[:start] + stub + text[end:], encoding='utf-8')
```

- Po ekstrakcji: zaktualizuj `__init__.py` (dodaj moduł do `from . import ...`), uruchom `pytest -q`.
- Jeśli nowy moduł importuje z `_engine`, a `_engine` importuje z nowego modułu → circular import jest OK, bo stałe/_dataclassy są definiowane w `_engine` PRZED stubem `from .nowy_modul import`.
- If the user says 'nie', 'wrong', 'cofnij', or equivalent: **stop, revert the last change, ask for clarification** before attempting a new approach.

## Testy i weryfikacja
- Po zmianie logiki uruchom testy związane z dotkniętym obszarem.
- Po zmianie UI sprawdź też stan pusty, błędny i podstawowy scenariusz.
- Jeśli testów brakuje, dodaj minimalny test regresji.
- Nie uznawaj zadania za zakończone bez krótkiej weryfikacji diffu.
- Before declaring task done, search the codebase for every other call site or case that touches the code you just modified. List each one and explain why your change does or doesn't affect it. Then run the full test suite.
- Na początku analizy wymagań oceń, czy zlecone zadanie dezaktualizuje istniejące testy. Jeśli tak — popraw lub usuń je jako pierwszy krok, zanim zmienisz kod produkcyjny. Nieaktualne testy blokują pracę i generują fałszywe błędy.

## String Handling

### Inch symbol
- The canonical inch symbol in this codebase is **`INCH`** — a constant defined in `app/data/abilities.py` with value U+201D (RIGHT DOUBLE QUOTATION MARK).
- **In ability descriptions** (`app/data/abilities.py`): U+201D is embedded directly in strings — do not touch.
- **In new code** (f-strings, labels, tests): ALWAYS use `INCH` or the Python escape `"”"`. Never write a bare ASCII `"` as an inch symbol.
  - Correct: `f'{name}(12{INCH})'` or `f'{name}(12”)'`
  - Wrong: `f'{name}(12")'` — the Edit tool may convert `"..."` into curly-quote pairs, breaking Python string delimiters (SyntaxError).

### Editing `app/data/abilities.py`
- Blocks containing embedded U+201D in descriptions → **only Python script via Bash** (`Write` the script, run via `Bash`). Never use the Edit tool on those blocks.
- Blocks without inch strings (new standalone function/constant) → Edit tool OK, provided single-quoted delimiters (`'...'`) are used throughout.
- **Encoding gate:** before any `Edit` or `Write` that modifies a `.py` file, verify `open(file, encoding='utf-8')` succeeds. Abort if it raises — never silently replace characters.

### Delimiters
- NEVER use typographic/smart quotes (U+201C `"`, U+201D `"`, U+2018, U+2019) as Python string delimiters.
- Delimiters must be straight ASCII only: `'...'` or `"..."`.

## Konwencje zmian
- Nie zmieniaj formatowania poza zakresem zadania.
- Nie wprowadzaj dodatkowych refaktorów przy okazji małej zmiany.
- Jeśli poprawiasz błąd, opisz przyczynę i zakres poprawki.
- Jeśli zmieniasz model dziedziczenia, sprawdź zgodność z edycją wariantów potomnych.
- **Duże usunięcia z monolitycznych plików (app.js, rosters.py, armies.py):** podziel na osobne commity per kategoria (np. stałe, funkcje kosztowe, helpery UI). Jeden commit nie powinien usuwać więcej niż ~150 linii z jednego pliku bez weryfikacji każdej usuwanej funkcji przez `grep`.

## Komentarze sekcji
Pliki `app/static/js/app.js`, `app/services/costs/_engine.py`, `app/routers/rosters.py` mają komentarze sekcji w formacie:
- JS: `// === SECTION: Nazwa — opis ===`
- Python: `# === SECTION: Nazwa — opis ===`

**Zasady utrzymania:**
- Analizując plik — przeczytaj komentarze sekcji jako mapę, zanim zaczniesz przeszukiwać kod.
- Dodając nową funkcję — umieść ją w odpowiedniej sekcji; jeśli nie pasuje do żadnej, dodaj nowy nagłówek sekcji.
- Przenosząc lub usuwając funkcję wymienioną w nagłówku sekcji — zaktualizuj listę funkcji w komentarzu.
- Tworząc nowy plik z logiką (>100 linii) — dodaj komentarze sekcji od razu.
- Nie dodawaj komentarzy do krótkich plików pomocniczych (<50 linii) ani do szablonów HTML.

## Smoke test po zmianie app.js
Po każdej zmianie `app/static/js/app.js` uruchom aplikację (`make dev`) i ręcznie sprawdź:
1. **Zbrojownia** → czy lista broni jest widoczna?
2. **Edytor Armii** → czy przy dodaniu oddziału widoczne są bronie?
3. **Rozpiski** → czy można zaznaczyć oddział i czy otwiera się panel edytora?

Testy backendowe (`make test`) nie pokrywają inicjalizacji JS — te trzy scenariusze muszą być sprawdzone ręcznie.

## Struktura app.js
`app/static/js/app.js` to monolityczny plik (~6500 linii). Plik zawiera komentarze sekcji oznaczone `// === SECTION: ... ===`. Struktura:

```
GLOBAL STATE & REFRESH TOKEN UTILS  (linia ~1)
ABILITY PICKER                       (linia ~50)
TEXT PARSING UTILS                   (linia ~689)
SPELL WEAPON COST PREVIEW            (linia ~842)
UI PICKERS — NUMBER, RANGE           (linia ~976)   ← KRYTYCZNE: helpery UI, NIE silnik kosztów
WEAPON PICKER                        (linia ~1292)
ROSTER ITEM RENDERING                (linia ~2314)
LOADOUT STATE MANAGEMENT             (linia ~2664)
EDITOR RENDERERS                     (linia ~3072)
ROSTER ADDERS                        (linia ~3488)
ROSTER EDITOR CLOSURE                (linia ~3590)   ← domknięcie ~2000 linii
SPELL ABILITY FORMS                  (linia ~5849)
ARMORY WEAPON TREE                   (linia ~6039)
BOOTSTRAP — DOMContentLoaded         (linia ~6544)
```

**Łańcuch inicjalizacji DOMContentLoaded (kolejność krytyczna):**
```
initAbilityPickers → initNumberPickers → initRangePickers →
initWeaponPickers → initRosterEditor → initWeaponDefaults →
initSpellAbilityForms → initArmoryWeaponTree → initSpellWeaponCostPreview
```
Funkcje `initNumberPicker(s)`, `initRangePicker(s)`, `initWeaponDefaults` to **helpery UI** (spinners liczb, zakresy broni) — **nie są częścią silnika kosztów**. Ich usunięcie niszczy całą inicjalizację przez ReferenceError.

**Reguła bezpieczeństwa dla dużych plików:** przed usunięciem dowolnej funkcji z `app.js` uruchom:
```bash
grep -n "nazwaFunkcji" app/static/js/app.js
```
i zweryfikuj brak wywołań. W szczególności sprawdź łańcuch DOMContentLoaded.

**Domknięcie `initRosterEditor`** (linia ~3590–5848): zawiera ~60 prywatnych funkcji współdzielących stan przez closure-scope (`loadoutState`, `activeItem`, `refreshRosterCostBadgesInProgress`, itp.). Zmiana jednej funkcji może mieć efekty uboczne w innych przez wspólne zmienne.

**Konwencja `include_item_costs`:** badge-only calls do `/quote` zawsze przekazują `include_item_costs: false`. Tylko dedykowany quote aktywnego oddziału w `handleStateChange` przekazuje `true`. Naruszenie tej reguły przywróci wielokrotnie wolniejsze badge refresh.

## Git Workflow
- When the user asks to align branches to a previous commit, default to `git reset --hard <sha>` (not merge). Confirm which repository (e.g., OPR vs OPR_Prod) you are operating in before running destructive commands.
- Before any destructive git command (`reset --hard`, `push --force`, `checkout .`), print `git remote -v` AND `git branch` so the repo identity is unambiguous.

## Komendy projektu
- Install: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`
- Run: `make dev`
- Test (wszystkie): `make test`
- Test (szybki, stop na pierwszym błędzie): `make test-fast`
- Lint: `make lint`

## Oczekiwany sposób pracy agenta
- Przed zmianą wskaż pliki, które zamierzasz edytować.
- Odczytuj pliki batchami
- Jeśli wymaganie jest niejasne, najpierw wypisz założenia i braki.
- Po wykonaniu zmian podaj:
  - co zmieniono
  - jak zweryfikowano
  - co nadal wymaga decyzji
