# HANDOFF — primary-weapon-flag

> **Wątek:** Dodanie klikalnej flagi ⚑ broni podstawowej w edytorze rozpiski, identycznej jak w Stanie Bitewnym.
> **Status:** In progress
> **Utworzony:** 2026-05-20
> **Ostatnia aktualizacja:** 2026-05-20

## Cel

Edytor Rozpiski (`editor_renderers.js`) zna `is_primary` z danych armii (używa do obliczeń pojemności slotu), ale nie pokazuje użytkownikowi żadnego wskaźnika ani nie pozwala zmieniać przypisania. Stan Bitewny ma klikaną nazwę broni z prefixem `⚑` — identyczny mechanizm dodajemy do edytora rozpiski. Wybór flagi zapisywany w `loadout_json` (nowe pole `primary_weapon`), backend używa go przy budowaniu `weapon_details`, dzięki czemu Stan Bitewny startuje z flagą z rozpiski bez klikania.

Edytor Armii (`weapon_picker.js`) ma checkbox "Podstawowa" — **zostaje bez zmian**.

## Zablokowane pliki / katalogi

- `app/static/js/modules/loadout_state.js` — nowe pole `primaryWeapon` w state
- `app/static/js/modules/editor_renderers.js` — UI klikalnej nazwy w `renderWeaponEditor()`
- `app/static/js/modules/roster_editor.js` — przekazanie `primaryWeapon` + callbacku
- `app/routers/rosters.py` — `_parse_loadout_json` + `_loadout_weapon_details`

## Blokuje / Blokowane przez

- **Blokuje:** nic
- **Blokowane przez:** nic

## Gałąź git

- **Branch:** `Rozwoj`
- **Base:** `main`

## Plan implementacji

*(Odznaczaj zrobione kroki [x]. Dopisuj odkrycia poniżej fazy.)*

### Faza 1 — `loadout_state.js`: nowe pole primaryWeapon

- [x] `createLoadoutState(rawLoadout)` linia ~80: dodaj `primaryWeapon: {}` do state; deserializuj z `rawLoadout.primary_weapon`
- [x] `cloneLoadoutState(state)` linia ~207: dodaj `primaryWeapon: state.primaryWeapon ? {...state.primaryWeapon} : {}`
- [x] `serializeLoadoutState(state)` linia ~244: przed `return JSON.stringify(result)` dodaj `primary_weapon` jeśli niepuste

### Faza 2 — `editor_renderers.js`: klikalna nazwa

- [x] Sygnatura `renderWeaponEditor` (linia 179): dodaj 2 opcjonalne parametry: `primaryWeapon = {}`, `onPrimaryChange = null`
- [x] Po liniach 237–240 (obliczenie `weaponClass`, `isPrimaryWeapon`): dodaj `overrideKey` i `effectivePrimary`
- [x] Element `name` (linia ~296): prefix `⚑` gdy `effectivePrimary`, kursor + listener gdy `editable && defaultPerModel > 0`

### Faza 3 — `roster_editor.js`: wywołanie renderera

- [x] W `renderEditors()` linia ~2155: rozszerz wywołanie `renderWeaponEditor` o `loadoutState.primaryWeapon` i callback `onPrimaryChange`

### Faza 4 — `rosters.py`: backend

- [x] `_parse_loadout_json()` linia 2559: dodaj `"primary_weapon": {}` do `base`; obsłuż `section == "primary_weapon"` w pętli
- [x] `_loadout_weapon_details()` linia 3032: wyciągnij `primary_override` z loadout; zastąp `option.get("is_primary")` logiką z override

### Faza 5 — Weryfikacja

- [x] `python -m pytest -q` — 176/176 passed
- [ ] Ręczny smoke: edytor rozpiski → `⚑` przy broni podstawowej; klik przenosi flagę; `loadout_json` zawiera `primary_weapon`
- [ ] Ręczny smoke: Stan Bitewny → flaga od razu widoczna bez klikania
- [ ] Diff review przed commitem

## Pliki dotknięte

- `app/static/js/modules/loadout_state.js` — primaryWeapon w create/clone/serialize
- `app/static/js/modules/editor_renderers.js` — nowe parametry + klikalna nazwa z ⚑
- `app/static/js/modules/roster_editor.js` — przekazanie primaryWeapon + onPrimaryChange
- `app/routers/rosters.py` — _parse_loadout_json + _loadout_weapon_details z override

## Kluczowy kontekst

**Skąd pochodzi `is_primary` teraz:**
- `_unit_weapon_options()` w `rosters.py` linia ~1431 odczytuje `UnitWeapon.is_primary` z bazy (armia) lub fallback na `default_weapon_id`
- `_loadout_weapon_details()` linia 2665: `"is_primary": bool(option.get("is_primary", False))`
- `weapon_details` trafia do `data-weapons-json` w szablonie `roster_battle_state.html`
- `battle_state.js` linia 314: `labelText.textContent = (isPrimary ? "⚑ " : "") + (w.name || "Broń")`
- `effectiveIsPrimary()` w `battle_state.js` linia 74: override z localStorage → fallback na `weapon.is_primary`

**Format `primary_weapon` w loadout_json:**
```json
{ "primary_weapon": { "melee": "15", "ranged": "23" } }
```
Klucz = typ (`"melee"` / `"ranged"`), wartość = weaponKey (string-ified ID).

**Jak `weaponKey` jest obliczany w JS:**
`resolveLoadoutEntryKey(option, 'id', ['weapon_id'])` → `String(option.id)` dla opcji broni.

**Jak sprawdzić melee/ranged w backend:**
```python
range_val = option.get("range", 0)
try:
    is_melee = (int(range_val) == 0)
except (TypeError, ValueError):
    is_melee = True  # "-" lub None → melee
```

## Hipotezy / pytania otwarte

- Edge case: jeśli `primary_weapon` wskazuje broń, która już nie istnieje w armii → żadna broń nie pokaże `⚑` dla tego typu. Akceptowalne — user re-zapisuje rozpiskę.

## Jak zweryfikować

```bash
python -m pytest -q
# Smoke manualny:
# 1. Edytor rozpiski → wybrany oddział z kilkoma broniami
# 2. Sprawdź ⚑ przy broni podstawowej (default_count > 0 + is_primary z armii)
# 3. Kliknij inną broń → flaga przenosi się (ten sam typ: wręcz/dystansowa)
# 4. DevTools Network → loadout_json zawiera "primary_weapon"
# 5. Stan Bitewny → ⚑ widoczny od razu
```

## Decyzje

- 2026-05-20: Przechowujemy override jako `{ melee: weaponKey, ranged: weaponKey }` (nie lista) — jeden primary na typ, jak w battle_state.js
- 2026-05-20: `weapon_picker.js` (edytor armii) bez zmian — tam checkbox jest ok
- 2026-05-20: Nie modyfikujemy `battle_state.js` — on już działa poprawnie z `weapon.is_primary` z backend

## Notatki / odkrycia w trakcie

- 2026-05-20: Plan zatwierdzony. SSOT check: brak naruszenia — zmiana nie dotyczy kosztów.
- 2026-05-20: Implementacja zakończona. 176/176 pytest passed. Oczekuje na ręczny smoke test.
- 2026-05-20: Bugfix po smoke teście — 3 bugi naprawione:
  1. Flaga znikała po save: `_sanitize_loadout` nie zachowywał `primary_weapon` w output → dodano
  2. Nie można było stawiać flagi na broniach z defaultPerModel=0: zmieniono warunek na `totalCount>0`
  3. Nie można było zdejmować flagi z broni domyślnie podstawowej: zmieniono `delete next[key]` na `next[key]=null`; w Python `_loadout_weapon_details` sprawdzamy istnienie klucza zamiast wartości!=None
