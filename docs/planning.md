# Planning — jak planować zadanie

Przed napisaniem kodu przejdź **w planie** trzy bramki: Layer Checklist, Performance gate, SSOT-check.

## Layer Checklist

Przed pierwszą edycją wymień wszystkie warstwy, których zmiana dotyka. Każdą warstwę implementuj świadomie i przetestuj.

| Warstwa | Co sprawdzić |
|---|---|
| **Data model / migracja** | `app/models.py`, Alembic migration jeśli zmieniasz schemat. Wpływ na warianty potomne (dziedziczenie). |
| **Backend payload** | Endpointy w `app/routers/*` zwracają nowe pola? Format JSON spójny z JS adapterami? |
| **JS render** | Czy `payload_adapters.js` widzi nowe pola? Czy są one renderowane w `app.js` (sekcje EDITOR RENDERERS, ROSTER ITEM RENDERING)? |
| **CSS / template** | Czy zmiana wymaga nowych klas / szablonów Jinja2? |
| **Testy** | Backend unit (`tests/test_*.py`), frontend parity (`tests/test_frontend_*.py`), smoke manualny dla JS. |

Po implementacji **walk through how you verified each layer end-to-end**. Brak warstwy w checklist = wysokie ryzyko regresji (top friction category, 42 hits).

## Performance gate dla hot path

Dla każdej zmiany dotykającej hot path (`/quote`, `/rosters/{id}`, pętle renderujące listy oddziałów) odpowiedz **w planie, zanim zaczniesz implementację**:

1. **Ile extra DB queries** generuje ta zmiana na typowej rozpisce (5–12 oddziałów)?
   Policz pesymistyczny przypadek: N oddziałów × M queries per oddział.

2. **Nowe FK / kolumny:** czy dominujący pattern to `WHERE nowa_kolumna = ?`?
   Jeśli tak — indeks (partial jeśli kolumna często NULL) musi być częścią **migracji Alembic**, nie post-hoc poprawką.

3. **Fast-path:** czy istnieje przypadek trywialny który można obsłużyć bez DB query?
   *Przykład:* standalone hero z `parent_id IS NULL AND is_hero` → brak query do `_hero_group_partner_ids`.

4. **Baseline:** sprawdź `docs/PERFORMANCE.md` przed/po zmianie. Regresja vs baseline = blocker.

## SSOT-check przed implementacją

Przed dodaniem logiki **klasyfikacji**, **kosztów** lub **walidacji** — `grep` istniejące funkcje SSOT i wywołaj je. Nigdy nie replikuj logiki inline.

Funkcje SSOT (lista skrócona, pełna mapa w `docs/architecture.md`):

- `_classification_map` (klasyfikacja oddziałów)
- `roster_unit_role_totals` (sumy ról w rozpisce)
- `calculate_roster_unit_quote` (SSOT core — koszt oddziału)
- `weapon_cost`, `weapon_cost_components` (koszt broni)
- `ability_cost`, `ability_cost_from_name` (koszt abilities)

```bash
# Przed napisaniem nowej funkcji
grep -rn "_classification_map\|roster_unit_role_totals" app/
```

## Zasady pracy agenta — przed implementacją

- **Najpierw czytaj istniejący kod**, potem edytuj.
- **Dla zadań wieloetapowych** — najpierw plan (plan mode lub `HANDOFF_<slug>.md` z sekcją "Plan implementacji").
- **Dla zadań prostych** — minimalny lokalny patch.
- **Nie przebudowuj architektury bez potrzeby.** Preferuj małe, odwracalne zmiany.
- **Aktualizuj HANDOFF_<slug>.md *przed* każdym podetapem**, nie po. Kontekst okna może się skończyć — zapis końcowy może nigdy nie nastąpić.

## Po zmianie — co napisać do usera

- co zmieniono,
- jak zweryfikowano (warstwy, testy),
- co nadal wymaga decyzji.

## Definition of Done — przed archiwizacją wątku

Zanim wątek pójdzie do `/handoff-archive`, przejdź **w tej kolejności**:

| Krok | Kiedy | Po co |
|---|---|---|
| 1. `pytest -q` | Zawsze | Sanity check po implementacji. |
| 2. Call-site check | Zawsze | Znajdź wszystkie miejsca wywołań zmienionej funkcji, wyjaśnij wpływ. |
| 3. Smoke test JS | Jeśli zmiana dotyka `app.js` lub `app/static/js/modules/*` | Backend pytest nie pokrywa inicjalizacji JS. Detale: `docs/testing.md`. |
| 4. **`/simplify`** | **Zawsze** | Przegląd świeżego diffu pod kątem reuse, jakości, dead code, powtórzeń. Tani, łapie błędy zanim staną się długiem. |
| 5. **`/review`** | Diff >50 linii LUB hot path (`/quote`, `_engine.py`, `app.js`) LUB SSOT | Drugie spojrzenie na zmiany o większym ryzyku. |
| 6. **`/security-review`** | Zmiany w auth, user input → DB, uprawnieniach, sekretach | Wykrywa SQLi, IDOR, leak sekretów. |
| 7. Re-run `pytest -q` | Jeśli krok 4/5/6 wprowadził zmiany | Naturalna pętla — simplify mógł coś zepsuć. |
| 8. Diff review przed commitem | Zawsze | Ostatnie spojrzenie własnym okiem. |

**Reguła:** kroki 4–6 to nie "opcjonalne ulepszenie" — to część "Done". Pomijasz je tylko gdy zmiana jest naprawdę trywialna (literówka w komentarzu, jedna nazwa zmiennej). W razie wątpliwości — uruchom.

**Implementacja w HANDOFF_<slug>.md:** sekcja "Faza N — Weryfikacja end-to-end (Definition of Done)" w szablonie ma już wszystkie 8 kroków jako checklist. Odznaczaj je w trakcie. `/handoff-archive` sprawdza ten stan.

Detale testowania: `docs/testing.md`. Konwencje kodu: `docs/developing.md`.
