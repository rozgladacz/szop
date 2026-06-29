# HANDOFF — demoralizacja-mag

> **Wątek:** Implementacja w kodzie: zdolność Demoralizacja, nowy koszt Maga, koszty+tabela psujących cech dla Rozkaz/Klątwa/Oznaczenie oraz UI listy zaklęć z wyborem trudności rzucenia.
> **Status:** In progress
> **Utworzony:** 2026-06-28
> **Ostatnia aktualizacja:** 2026-06-28

## Cel
Reguły gry (`SZOP_Zdolnosci.md` + `SZOP.docx`) są już zaktualizowane i spójne; kod ich nie realizuje. Wdrożyć: (1) Demoralizacja (aktywna, koszt 25), (2) Mag = `X × clamp(2T,12,36)`, (3) Rozkaz = Aura±2 / Klątwa+Oznaczenie = ×6 + tabela psujących cech jako tagi w katalogu (SSOT), (4) lista zaklęć z wyborem trudności 2+..6+ (domyślnie 4+) i nowym wzorem żetonów `ceil(pkt×szansa/10)`.

Pełny plan: `C:\Users\mlis\.claude\plans\nowa-zdolno-demoralizacja-przebudowa-atomic-bonbon.md`.

## Zablokowane pliki / katalogi
- `app/data/abilities.py` — Demoralizacja + tagi psujących cech + opis Maga (edycja skryptem Python — opisy z `”`).
- `app/services/costs/abilities.py` — koszty Mag / Rozkaz / Klątwa / Oznaczenie / Demoralizacja.
- `app/services/costs/_engine.py`, `app/services/costs/__init__.py` — helper `cast_chance` / token cost.
- `app/services/ability_registry.py` — filtrowanie pickerów tag-driven.
- `app/routers/armies.py` — spell details, add-ability, weapon form/preview, nowy ability-cost-preview.
- `app/models.py` — `ArmySpell.cast_difficulty` (KOORDYNACJA z wątkiem `kolekcja`, który też blokuje `app/models.py`).
- `app/db.py` — migracja kolumny.
- `app/templates/army_spells.html`, `armory_weapon_form.html`, wydruki/eksport.
- `app/static/js/modules/spell_ability_forms.js`, `spell_weapon_cost_preview.js`.

## Blokuje / Blokowane przez
- **Blokuje:** —
- **Blokowane przez:** koordynacja z wątkiem `kolekcja` na `app/models.py` (oba dodają kolumny/modele — zmiany rozłączne: kolekcja=CollectionModel*, ten wątek=ArmySpell.cast_difficulty).

## Gałąź git
- **Branch:** `Rozwoj`
- **Base:** `main`

## Plan implementacji

### Faza A — Demoralizacja
- [x] A.1: `AbilityDefinition` demoralizacja (active) w katalogu (skrypt Python — opis z INCH).
- [x] A.2: gałąź kosztu `demoralizacja → 25.0` w `ability_cost_components_from_name`.
- [x] A.3: test `ability_cost_from_name("Demoralizacja") == 25.0`.

### Faza B — Koszt Maga
- [x] B.1: `desc.startswith("mag")` → `X × clamp(2T,12,36)` (toughness z nosiciela).
- [x] B.2: aktualizacja opisu Maga do wersji z `.docx` (skrypt Python).
- [x] B.3: testy Maga (T=1→×12, T=8→×16, T=18→×36).

### Faza C — Rozkaz / Klątwa / Oznaczenie + tabela psujących cech
- [x] C.1: pola tagów w `AbilityDefinition` (aura_tak/rozkaz_tak/rozkaz_kierunek/klatwa_tak/oznaczenie_tak/zakres), domyślne False/None.
- [x] C.2: uzupełnić tagi dla pasywnych (`_PASSIVE_DAMAGE_TAGS` + `replace` post-process; tylko zdolności z ≥1 tagiem True) — skrypt Python.
- [x] C.3: `ability_registry` filtrowanie tag-driven (usunięto 3 sety psujących cech, dodano `_ORDER_TAG_ATTR`; `klatwa_mistrzostwo` znika bo mistrzostwo.klatwa_tak=False).
- [x] C.4: rozdzielić formuły kosztów: Klątwa/Oznaczenie ×6, Rozkaz `T_eff±2` (znak z `rozkaz_kierunek`).
- [x] C.5: testy (aktualizacja `Klątwa: Wolny` -10→-6; nowe Rozkaz +/−, Oznaczenie ×6, Mag, Demoralizacja). Pełny pytest 226/226 ✓.

### Faza D — Lista zaklęć: wybór trudności + koszt pkt/żetony
- [x] D.1: `ArmySpell.cast_difficulty` (model, default 4) + migracja idempotentna `ALTER TABLE army_spells ADD COLUMN cast_difficulty`.
- [x] D.2: helpery SSOT `cast_chance` / `spell_ability_token_cost` / `spell_weapon_token_cost` / `clamp_spell_difficulty` w `_engine.py`, eksport przez `costs/__init__.py` + `__all__`.
- [x] D.3: backend `armies.py` — `_weapon_spell_details`/`_ability_spell_details` z difficulty, add-ability `cast_difficulty`, weapon create/update/preview `quality`, nowy `POST .../spells/ability-cost-preview`.
- [x] D.4: frontend — radia trudność→żetony + koszt pkt (`spell_ability_forms.js`), ramka jakości ataku w `armory_weapon_form.html` (`spell_weapon_cost_preview.js`), kolumna „Trudność" w `army_spells.html`.
- [x] D.5: trudność w wydrukach/eksporcie (`export_payload`+`_army_spell_entries`+`roster_print.html`/`export/lista.html`/`export_xlsx.py`).
- [x] D.6: testy — `test_spell_difficulty.py` (7: helpery, route, preview, migracja); aktualizacja `test_army_spell_cost_refresh`/`test_spell_weapon_cost_*` na dzielnik /10. Pełny pytest 233/233 ✓.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [x] `pytest -q` — 233/233 (226 istniejących + 7 nowych w `test_spell_difficulty.py`).
- [x] Smoke render (TestClient, zalogowany): `/armies/{id}/spells` 200 z kolumną Trudność + radiami trudności; formularz broni 200 z ramką jakości; `ability-cost-preview` → `point_cost=25`, tokens {2:3,4:2,6:1}. JS `node --check` OK.
- [x] Call-site check: `ability_cost_from_name` (toughness Maga przez `ability_cost`), `_spell_weapon_cost` (2 call sites zaktualizowane), `_ability_spell_details` (+difficulty), `definition_payload` (tag-driven) — wszystkie zweryfikowane.
- [x] `/simplify` — zastosowano: hoist `find_definition("mistrzostwo")`, kolaps gałęzi Rozkaz/Klątwa/Oznaczenie, assert SSOT na `_PASSIVE_DAMAGE_TAGS`, usunięto zbędny `getattr`. Re-run pytest 233/233 ✓.
- [x] Migracja zastosowana do `data/szop.db` (`cast_difficulty` obecny); idempotentna (test + ręcznie).
- [x] `/security-review` (lekki, inline): `ability-cost-preview` — `_ensure_army_view_access` (authz), `int(raw_id)` w try/except, walidacja `type=='active'` + `FORBIDDEN_SPELL_SLUGS`, `value` ucięte do 120 zn., tylko `db.get` (read-only, ORM, brak injekcji). OK.
- [!] `/review` (pełny multi-agent) — do uruchomienia przed commitem/archiwizacją (diff duży / SSOT). Nie uruchomiono w tej sesji (czeka na decyzję usera o commit).
- [ ] Diff review + commit (oczekuje na decyzję usera).

## Pliki dotknięte
*(wypełniać w trakcie)*

## Hipotezy / pytania otwarte
- `ArmySpell.cost` pozostaje kosztem żetonowym; koszt punktowy tylko w UI wyboru.

## Jak zweryfikować
```bash
python -m pytest -x --tb=short -q
# smoke: make dev → Armia → Lista zaklęć / oddział z Magiem/Rozkazem
```

## Decyzje
- 2026-06-28: Zakres = wszystkie 4 obszary w jednym wątku (decyzja usera).
- 2026-06-28: Tabela psujących cech → tagi w `AbilityDefinition` (data-driven SSOT), nie hardcoded sety.
- 2026-06-28: Trudność zaklęć 2+..6+, domyślnie 4+; szansa(D)=(7−D)/6.
- 2026-06-28: `.docx` i `.md` zweryfikowane jako spójne — brak rozbieżności reguł.

## Faza E — Iteracja UX + rebalans (zgłoszone 2026-06-28, po Fazie D)
- [x] E.1: Broń-zaklęcie — radio buttony trudności (jak przy zdolności) zamiast `<select>`. Endpoint `weapon-cost-preview` zwraca mapy `tokens`/`points` per trudność; `spell_weapon_cost_preview.js` renderuje radia `name="quality"` z etykietą „D+ — N żet."; wybór aktualizuje pkt+żet z cache (bez fetch). Szablon `armory_weapon_form.html`.
- [x] E.2: Lista zaklęć — przycisk „Edytuj" przy zdolnościach → układ jak przy dodawaniu, prefill (zdolność, wartość, trudność, nazwa). Nowe trasy `GET/POST /spells/abilities/{id}/edit|update`, helper SSOT `_resolve_ability_spell_fields` (add+update), `_spell_page_context(editing_spell=...)`, prefill wartości w `spell_ability_forms.js` (`data-initial-value`).
- [x] E.3: Rebalans kosztów Maga o połowę — `X × clamp(T, 6, 18)` (było `clamp(2T,12,36)`); dzielnik żetonów `/5` (było `/10`) w `spell_ability_token_cost`/`spell_weapon_token_cost`.
- [x] E.4: Testy zaktualizowane (Mag 12/16/36; tokeny /5) + nowe (edit/update ability: prefill context, zmiana trudności/nazwy/kosztu, zmiana zdolności+wartości). Pytest 237/237.
- [x] E.5: Weryfikacja live (preview): radia broni (2+ — 7 żet. … 6+ — 2 żet., wybór zmienia pkt+żet); edit zdolności (prefill Łatanie/Rozkaz:furia, round-trip zapisał diff=6, cost=1, nazwa, pozycja zachowana). Screenshot OK.

## Faza F — Bugfix: podgląd vs zapis broni (zgłoszone 2026-06-28)
- [x] F.1: Niezgodność kosztu broni-zaklęcia między podglądem (2 dla 4+) a listą po zapisie (3 dla 4+). Przyczyna: `weapon_cost(weapon, unit_quality=4)` przy `use_cached=True` (domyślnie) zwraca **cache armory** broni (`effective_cached_cost`) tylko dla jakości 4 — lista używała stale cache (12.16→3), a podgląd liczył świeżo z temp-broni (9.27→2). Dla jakości ≠4 cache nie był używany, więc rozjazd dotyczył tylko 4+.
- [x] F.2: Fix: `_weapon_spell_details` i `_spell_weapon_cost` wołają `weapon_cost(..., use_cached=False)` → koszt zaklęcia zawsze liczony świeżo, spójnie dla wszystkich trudności. Regresja: `test_weapon_spell_cost_ignores_armory_cache`. Zweryfikowane: saved==preview dla d=2/4/6 (token 4/2/1). Pytest 238/238.

## Faza G — /simplify (4 agenci) 2026-06-28
- [x] G.1: Podgląd kosztu broni — `weapon-cost-preview` budował temp-broń i serializował tagi 5× w pętli + zbędne 6. wywołanie dla domyślnej trudności. Refactor: `_spell_weapon_for_cost` (buduje broń raz) + `_spell_weapon_token_and_point` + `_spell_weapon_cost_map`; endpoint liczy `weapon_cost` per trudność na jednej broni, `spell_cost`/`point_cost` brane z map (bez 6. wywołania).
- [x] G.2: `_PASSIVE_DAMAGE_TAGS` — `assert` → jawny `raise ValueError` (assert znika pod `python -O`, a filtrowanie pickerów zależy od tagów).
- [!] Pominięto (nota): ekstrakcja wspólnego JS (debounced-poster + render radiów) z `spell_ability_forms.js`/`spell_weapon_cost_preview.js` — realna duplikacja, ale wymaga nowego modułu + wpięcia w `base.html`/`app.js` (i 3. kopia w `roster_editor.js`), poza zakresem diffa i ryzykowne na świeżo zweryfikowanym UI. Kandydat na osobny wątek.
- Pytest 238/238 po refactorze.

## Notatki / odkrycia w trakcie
- 2026-06-28: Migracje przez `app/db.py:_migrate_schema()` (idempotentny ALTER TABLE), nie Alembic w runtime.
- 2026-06-28: Edycje `app/data/abilities.py` z opisami `”` — tylko skrypt Python (gate kodowania), nie Edit.
- 2026-06-28: **Bugfix (zgłoszone: „koszt broni nie aktualizuje się przy zmianie trudności")** — podgląd kosztu broni-zaklęcia zwracał HTTP 500. Przyczyna (latentny, prawdopodobnie pre-existing): JS `collectTraits` wysyła `abilities` jako listę **stringów**, a `_ensure_spell_weapon_has_lock_on`/`_spell_normalized_trait_slug` oczekują dictów (`.get`). Każda broń-zaklęcie ma auto-dodane „Namierzanie" → payload nigdy pusty → 500 na każdym podglądzie (wyświetlane wartości były tylko SSR). Fix: `_normalize_spell_weapon_ability_items` w `armies.py` akceptuje stringi i dicty. Regresja: `test_spell_difficulty.py::test_spell_weapon_cost_accepts_string_abilities_and_varies_with_quality`. Zweryfikowane live (preview): zmiana jakości aktualizuje koszt pkt+żet. Pytest 234/234.
