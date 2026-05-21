# Frontend JS Modules

Mapa zaleznosci po Fazie III podzialu `app/static/js/app.js`. Moduly sa klasycznymi IIFE i publikuja API przez `window`.

## Kolejnosc ladowania

1. `refresh_priority.js`
2. `payload_adapters.js`
3. `text_parsing.js`
4. `ui_pickers.js`
5. `spell_weapon_cost_preview.js`
6. `spell_ability_forms.js`
7. `roster_rendering.js`
8. `loadout_state.js`
9. `editor_renderers.js`
10. `roster_adders.js`
11. istniejace stuby: `ability_picker.js`, `weapon_picker.js`, `roster_editor.js`, `armory_tree.js`
12. `app.js`

## Kontrakty

- Bootstrap w `app.js` zachowuje kolejnosc init: `initAbilityPickers`, `initNumberPickers`, `initRangePickers`, `initWeaponPickers`, `initRosterEditor`, `initWeaponDefaults`, `initSpellAbilityForms`, `initArmoryWeaponTree`, `initSpellWeaponCostPreview`, `initWeaponInheritancePanel`, `initWeaponImportPanel`.
- `include_item_costs: false` pozostaje tylko w badge-only quote refresh. Quote aktywnego oddzialu przekazuje pelne item costs.
- Nazwy pol payloadu pozostaja bez zmian: `selected_total`, `item_costs`, `passive_deltas`, `weapon_options`, `passive_items`, `active_items`, `aura_items`, `loadout`, `mode`, `weapons`, `active`, `aura`, `passive`.
- `data-*` roster/loadout pozostaja kompatybilne z dotychczasowym `app.js`.

## Moduly i publiczne API

| Modul | Zaleznosci | Publiczne API | Glowne call sites |
| --- | --- | --- | --- |
| `text_parsing.js` | brak | `SZOPTextParsing`, aliasy: `splitTraits`, `normalizeName`, `extractNumber`, `abilityIdentifier`, `passiveIdentifier`, `parseFlagString`, `normalizeRangeValue`, `stripOptionalFlagSuffix`, `ABILITY_NAME_MAX_LENGTH` | `app.js` weapon picker, roster editor, armory tree; `editor_renderers.js` |
| `ui_pickers.js` | DOM | `SZOPUIPickers.initNumberPicker(s)`, `initRangePicker(s)`, `initWeaponDefaults` | bootstrap `app.js` |
| `spell_weapon_cost_preview.js` | DOM, fetch endpoint `/armies/{id}/spells/weapon-cost-preview` | `SZOPSpellWeaponCostPreview.initSpellWeaponCostPreview` | bootstrap `app.js` |
| `spell_ability_forms.js` | DOM | `SZOPSpellAbilityForms.initSpellAbilityForms` | bootstrap `app.js` |
| `roster_rendering.js` | `SZOPPayloadAdapters` | `SZOPRosterRendering.formatPoints`, `createRosterItemElement`, `renderPassiveEditor` | ability picker labels in `app.js`, roster editor closure, `loadout_state.js`, `editor_renderers.js`, `roster_adders.js` consumers |
| `loadout_state.js` | `SZOPRosterRendering.formatPoints` | `SZOPLoadoutState` with loadout state create/clone/serialize/ensure helpers, labels, mode helpers | roster editor closure, `editor_renderers.js`, Node frontend tests |
| `editor_renderers.js` | `SZOPRosterRendering`, `SZOPLoadoutState`, `SZOPTextParsing` | `SZOPEditorRenderers.renderAbilityEditor`, `renderWeaponEditor`, `toggleSectionVisibility` | roster editor closure, Node frontend tests |
| `roster_adders.js` | DOM/fetch roster add endpoint | `SZOPRosterAdders.initRosterAdders` | `initRosterEditor` in `app.js` |

## Call-site checklist per PR

- Po zmianie modulu uruchom `rg -n "nazwaFunkcji" app/static/js tests app/templates`.
- Sprawdz, czy `base.html` laduje modul przed `app.js` i przed modulami, ktore go konsumują.
- Sprawdz, czy alias globalny nadal istnieje dla funkcji uzywanych w testach Node.
- Po zmianach w `app.js` wykonaj smoke: Zbrojownia, Edytor Armii, Rozpiski.
