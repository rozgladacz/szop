# HANDOFF — faza-d-roster-adapter

> **Wątek:** Most ORM `Roster` → engine-dict (warstwa-liść agentów) — prereq dla D3 `exploit_hunt` (metryka win_rate/points), odłożonego D2 breakdown per-zdolność/broń oraz DB-backed `LocalClient`.
> **Status:** In progress
> **Utworzony:** 2026-06-16
> **Ostatnia aktualizacja:** 2026-06-16

## W TRAKCIE

- **2026-06-17 (interaktywna) — BUGFIX `roster_points` (niespójność z per_copy).** User dodał dane (admin/`Testowa`) i poprosił o rzetelne notowanie sumy armii. Odkryte: `roster_points` liczył `Σ roster_unit_cost(ru)` = `quote(count=ru.count MODELI)`, ale `roster_to_engine_roster(per_copy)` symuluje `count` KOPII × `typical_models` modeli. Repro (Testowa „Wzorcowy piechur" typ=6, 2 kopie): symulacja 12 modeli, koszt zapisany **26.88** vs faktyczny **161.24** (≈6× za mało). Fix: `roster_points(roster, *, models_mode="per_copy")` mirroruje adapter — per_copy: `Σ copies × quote(typical)`, aggregate: `Σ quote(copies×typical)`. Spójne z LOCKED per_copy. Aktualizacja 3 testów `roster_points` (per_copy semantyka). **Plik:** `app/services/agents/roster_adapter.py`, `tests/test_agents_roster_adapter.py`.

- **2026-06-16 — SLICE 1 + 2a DONE.** `roster_adapter.py`: `roster_to_engine_roster` (slice 1, commit `6d44b65`) + `roster_points` (slice 2a). 17 testów; pełna suita **1699 passed** (1682 baseline + 17). Docs (roadmap D3, architecture agents) zaktualizowane. D3 ma oba inputy metryki (engine-dict + points); pozostała blokada D3 = B2 auth (konto agenta + generator rozpisek). Wątek może zostać otwarty na slice 2b (auto-deploy/extra_weapons/attached-heroes) lub zarchiwizowany jeśli D3 czeka na B2.

## Cel

Zbudować czystą funkcję adaptującą ORM `Roster` (z relacjami `RosterUnit`→`Unit`→`Weapon`/`UnitAbility`) na format **engine-dict** konsumowany przez `build_initial_state` / `simulate_from_rosters` (`{"owner_player", "units":[{"id","position","models","toughness","quality","defense","passives","weapons"}]}`). Adapter odfiltrowuje zdolności wykluczone z MVP (`b_mvp_exclusions.yaml`, inaczej `build_initial_state` rzuca `UnsupportedAbilityError`) i raportuje pominięte/inertne zdolności (symulacja na podzbiorze MVP). Reuse SSOT: `normalize_range_value` (zasięg→cale), `ability_catalog.slug_for_name` (nazwa→slug), `load_b_mvp_exclusions`, `INCOMPLETE_ABILITIES`.

## Zablokowane pliki / katalogi

- `app/services/agents/roster_adapter.py` (NEW) — adapter
- `app/services/agents/__init__.py` (MOD) — eksport
- `tests/test_agents_roster_adapter.py` (NEW)
- `docs/roadmap.md` (MOD) — D3 prereq / D-stream notatka
- `docs/architecture.md` (MOD) — sekcja agentów

## Blokuje / Blokowane przez

- **Blokuje:** D3 `exploit_hunt` (win_rate/points), D2 breakdown per-zdolność/broń, DB-backed `LocalClient(db_session, user_id)`.
- **Blokowane przez:** nic — engine public API stabilne (B3.9), SSOT kosztu (`calculate_roster_unit_quote`) gotowe.

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Slice 1 — konwersja Roster → engine-dict (ten wątek)

- [x] `roster_adapter.py`: `roster_to_engine_roster(roster, *, owner_player, models_mode="per_copy", positions=None) -> AdaptResult`
  - `AdaptResult(units: dict, dropped_excluded: list[str], inert_incomplete: list[str], deferred_attached_heroes: list[int])`
  - Per top-level `RosterUnit` (parent_roster_unit_id is None): zbuduj blob(y) wg `models_mode`.
  - Slugi zdolności z `unit.abilities` (przez `costs.ability_identifier(Ability.name)`); odfiltruj `b_mvp_exclusions` (do `dropped_excluded`), oznacz `INCOMPLETE_ABILITIES` (do `inert_incomplete`, ZOSTAW w passives — engine cicho ignoruje).
  - Broń: `unit.default_weapon_loadout` (SSOT) → WeaponProfile-dict (primary-first per kategoria, dedup po (slug,range)); range przez `normalize_range_value`, tagi→slug przez `ability_identifier`.
  - `quality`/`defense`/`toughness` z `Unit`. Id rozłączne per gracz (`owner_player*10000+i`).
- [x] `__init__.py` eksport (`AdaptResult`, `roster_to_engine_roster`).
- [x] `tests/test_agents_roster_adapter.py` — 14 testów (transient ORM bez DB): shape, partycja broni, primary-first, filtrowanie wykluczeń (raportowane, dict buildowalny), incomplete inert, models_mode per_copy/aggregate + walidacja, attached-hero defer, pozycje jawne/placeholder, rozłączne id, integracja `build_initial_state` + `simulate_from_rosters`.
- [x] docs (roadmap D3 prereq, architecture sekcja agentów — tabela +`roster_adapter.py`, licznik 56→70).

### Slice 2a — koszt/punkty (DONE 2026-06-16)

- [x] `roster_points(roster) -> float` — suma `costs.roster_unit_cost(ru)` (SSOT, read-only) po wszystkich `RosterUnit`. Metryka D3 `win_rate/points`. Liczy PEŁNY koszt (incl. attached heroes) mimo że engine-dict symuluje podzbiór (świadoma asymetria, udokumentowana). 3 testy. **D3 ma teraz oba inputy metryki:** engine-dict (`roster_to_engine_roster`) + points (`roster_points`).

### Slice 2b+ (NASTĘPNE wątki, NIE w tym oknie)
- Auto-rozstawienie: integracja z D5 `deployment_zones` (grid w strefie) zamiast placeholder positions.
- Attached heroes (`parent_roster_unit_id` ≠ None): poprawne dołączenie do oddziału macierzystego (merge radius/buff) — teraz DEFEROWANE i raportowane.
- DB-backed `LocalClient(db_session, user_id)`.

## Pliki dotknięte

- `app/services/agents/roster_adapter.py` (NEW)
- `app/services/agents/__init__.py` (MOD)
- `tests/test_agents_roster_adapter.py` (NEW)
- `docs/roadmap.md`, `docs/architecture.md` (MOD)

## Decyzje

- 2026-06-16: Slug `faza-d-roster-adapter` (zarezerwowany w parent `faza-b-engine-mvp` jako anticipated prereq D3).
- 2026-06-16: Warstwa-liść agentów (czyta tylko ORM + public API silnika) — zero zmian w rdzeniu `engine/*` → brak kolizji z lockami / golden-digestami B7.

## Decyzje zamrożone (NIE podnosić ponownie)

> Rozstrzygnięte przez usera 2026-06-16. NIE są otwartymi pytaniami ani blokadami.

- **`models_mode` = `per_copy` KANONICZNY (LOCKED).** User: „można mieć kilka takich samych oddziałów i każdy z nich rozpatrywany jest niezależnie" (zgodne pkt 2.b/8.a/11). `count` kopii = `count` osobnych blobów po `typical_models`. `aggregate` zostaje tylko jako flaga debugowa (nie kanoniczna).
- **Attached heroes — POZA MVP (LOCKED).** User: „Bohaterowie czekają na modele i wypadają z MVP". Dołączeni bohaterowie (`parent_roster_unit_id`) deferowani do E1 (per-model granularity). `roster_to_engine_roster` raportuje ich w `deferred_attached_heroes`; `roster_points` liczy ich koszt (pełna wartość rozpiski). Engine-side ignoruje. NIE re-eskalować.
- **D3 ścieżka — Opcja A (in-memory) NA TERAZ (LOCKED).** User: „A na teraz, potem jedno konto Test z przygotowanymi rozpiskami + gotowymi oddziałami do losowych rozpisek, potem B". D3 generuje efemeryczne rozpiski w pamięci (bez DB-write/auth). Źródło jednostek: **dowolne oddziały z bazy, które nie mają pomijanych cech** (`b_mvp_exclusions`). Konto `Test` (przygotowane rozpiski + pula oddziałów) dojdzie niebawem (user doda usera). Potem B (konto agenta + AgentToken). → wątek `faza-d-exploit-hunt`.

## Hipotezy / pytania otwarte

- **PYTANIE DO USERA (models_mode) — domyślnie rozstrzygnięte na czas Auto Mode, do potwierdzenia:** `RosterUnit.count` (liczba kopii oddziału) vs `Unit.typical_models` (rozmiar oddziału). Default **`per_copy`**: `count` osobnych blobów, każdy `typical_models` modeli (oddziały aktywują się niezależnie, pkt 11). Alternatywa `aggregate`: 1 blob × (count×typical_models). Parametr `models_mode` eksponuje obie ścieżki; default `per_copy`. **Czy user potwierdza `per_copy` jako kanoniczny dla symulacji balansu?**
- Attached heroes (`parent_roster_unit_id`): w tym slice DEFEROWANE (raportowane w `deferred_attached_heroes`), nie emitują blobów — poprawne dołączenie (merge do macierzystego oddziału) to follow-up.

## Jak zweryfikować

```powershell
python -m pytest tests/test_agents_roster_adapter.py -v
python -m pytest -q   # pełna suita — baseline 1682 + nowe
```

## Faza Weryfikacja — Definition of Done

- [x] `pytest -q` zielony — **1696 passed** (1682 baseline + 14)
- [x] Call-site check — nowy moduł, eksport addytywny do `agents/__init__.py`; zero zewnętrznych call-site (D3 konsument jeszcze nieistnieje)
- [x] `/simplify` — 4 kąty inline; 1 cleanup (sortowanie primary bez efektu ubocznego `pop()` w kluczu); reszta czysta (reuse SSOT, brak hot-path)
- [x] `/review` — pominięty warunkowo: izolowana warstwa-liść, pełne pokrycie 14 testami, brak hot-path/auth/DB, SSOT tylko czytany; inline correctness self-review wykonany
- [!] `/security-review` — nie dotyczy: brak auth/route, adapter czyta transient ORM, zero DB-write
- [x] re-run `pytest` po `/simplify` — 14/14 zielone
