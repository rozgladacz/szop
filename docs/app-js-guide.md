# app.js Guide

`app/static/js/app.js` to monolityczny plik (~6500 linii) — pozostały po stopniowej ekstrakcji modułów IIFE. Każda zmiana wymaga zrozumienia struktury sekcji i łańcucha inicjalizacji.

## Mapa sekcji

Plik zawiera komentarze sekcji `// === SECTION: ... ===`. Aktualny układ:

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
ROSTER EDITOR CLOSURE                (linia ~3590)  ← domknięcie ~2000 linii
SPELL ABILITY FORMS                  (linia ~5849)
ARMORY WEAPON TREE                   (linia ~6039)
BOOTSTRAP — DOMContentLoaded         (linia ~6544)
```

Numery linii są przybliżone — mogą się przesunąć po zmianach.

## Łańcuch inicjalizacji DOMContentLoaded — kolejność krytyczna

```
initAbilityPickers
→ initNumberPickers
→ initRangePickers
→ initWeaponPickers
→ initRosterEditor
→ initWeaponDefaults
→ initSpellAbilityForms
→ initArmoryWeaponTree
→ initSpellWeaponCostPreview
```

**Uwaga:** `initNumberPicker(s)`, `initRangePicker(s)`, `initWeaponDefaults` to **helpery UI** (spinners liczb, zakresy broni) — **NIE są częścią silnika kosztów**. Ich usunięcie niszczy całą inicjalizację przez `ReferenceError`.

## Reguła bezpieczeństwa dla usuwania funkcji

Przed usunięciem **dowolnej** funkcji z `app.js`:

```bash
grep -n "nazwaFunkcji" app/static/js/app.js
```

Zweryfikuj brak wywołań. **W szczególności sprawdź łańcuch DOMContentLoaded** — usunięcie funkcji wymienionej w bootstrap = strona nie działa.

## Domknięcie `initRosterEditor` (linia ~3590–5848)

Zawiera ~60 prywatnych funkcji współdzielących stan przez **closure-scope**:
- `loadoutState`
- `activeItem`
- `refreshRosterCostBadgesInProgress`
- ...i inne wspólne zmienne

**Konsekwencja:** zmiana jednej funkcji może mieć efekty uboczne w innych przez wspólne zmienne. Przed edycją funkcji w tym domknięciu — przeczytaj wszystkie funkcje używające tej samej zmiennej.

## Konwencja `include_item_costs`

- **Badge-only calls** do `/quote` → zawsze `include_item_costs: false`.
- **Dedykowany quote aktywnego oddziału** w `handleStateChange` → `include_item_costs: true`.

**Naruszenie reguły = wielokrotnie wolniejsze badge refresh** (regresja performance).

## Co już zostało wydzielone (mapa modułów IIFE)

Aktualna mapa zależności i lista call sites: `docs/frontend_js_modules.md`.

Wydzielone moduły (Faza I-III refaktoryzacji):
- text parsing
- UI pickers (po review zostały w `app.js` jako closure deps)
- spell weapon preview
- spell ability forms
- roster rendering
- loadout state
- editor renderers
- roster adders
- refresh priority

**Pozostałe w `app.js`** (świadoma decyzja — closure-heavy):
- `ROSTER EDITOR CLOSURE`
- `WEAPON PICKER`
- `ABILITY PICKER`
- `ARMORY WEAPON TREE`
- `WEAPON INHERITANCE PANEL`

## Smoke test po zmianie `app.js`

Po każdej zmianie uruchom `make dev` i ręcznie zweryfikuj:
1. **Zbrojownia** → lista broni widoczna?
2. **Edytor Armii** → przy dodaniu oddziału widoczne bronie?
3. **Rozpiski** → można zaznaczyć oddział i otworzyć panel edytora?

Backend testy nie pokrywają inicjalizacji JS — to **musi** być sprawdzone ręcznie. Detale: `docs/testing.md`.
