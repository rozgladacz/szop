# HANDOFF — Meta

> **Co tu jest:** spis aktywnych wątków + zablokowane zasoby + szybkozmienne notatki cross-wątkowe + LOG SESJI (najnowsze).
> **Czego tu NIE ma:** wiedzy stabilnej (mapa submodułów, architektura) — to jest w `docs/architecture.md`. Starsze wpisy LOG → [docs/handoffs/LOG_ARCHIVE.md](docs/handoffs/LOG_ARCHIVE.md).
> **Per-wątek:** szczegóły w `docs/handoffs/HANDOFF_<slug>.md`.
> **Workflow:** uruchom `/load-context` na początku sesji. Detale konwencji: [docs/handoffs/README.md](docs/handoffs/README.md).

---

## Aktywne wątki

| Wątek (link) | Cel (1 zdanie) | Pliki zablokowane | Status |
|---|---|---|---|
| [HANDOFF_rozmiar-podstawki](docs/handoffs/HANDOFF_rozmiar-podstawki.md) | `Unit.base_size` (mała/średnia/duża) + zniżka kosztu broni wręcz dla modeli-nadmiaru (wpływa na klasyfikację Wojownik/Strzelec) + „Walczące modele" w Stanie Bitewnym | `app/models.py`, `app/services/costs/{_engine,crowding,quote,role_totals}.py`, `app/routers/{rosters,export,armies}.py`, `app/templates/{unit_form,roster_battle_state}.html`, `app/static/js/{battle_state,payload_adapters}.js` | In progress |


## Zasoby zablokowane (reverse lookup)

| Plik / katalog | Wątek blokujący | Powód |
|---|---|---|
| `app/models.py` | rozmiar-podstawki | `+Unit.base_size` |
| `app/services/costs/_engine.py` | rozmiar-podstawki | `BASE_SIZE_MELEE_LIMITS`, bump `COST_ENGINE_VERSION` |
| `app/services/costs/crowding.py` | rozmiar-podstawki | nowy moduł (NEW) — SSOT zniżki „tłok" |
| `app/services/costs/quote.py` | rozmiar-podstawki | zniżka przed `_roster_unit_classification` |
| `app/services/costs/role_totals.py` | rozmiar-podstawki | param `melee_factors` |
| `app/routers/rosters.py` | rozmiar-podstawki | `_classification_map`, endpoint `/quote` |
| `app/routers/export.py` | rozmiar-podstawki | battle-state: `melee_fighting_default` |
| `app/routers/armies.py` | rozmiar-podstawki | edycja jednostki: odczyt/zapis `base_size` |
| `app/templates/unit_form.html` | rozmiar-podstawki | select rozmiaru podstawki |
| `app/templates/roster_battle_state.html` | rozmiar-podstawki | kontener „Walczące modele" |
| `app/static/js/battle_state.js` | rozmiar-podstawki | UI „Walczące modele" |
| `app/static/js/payload_adapters.js` | rozmiar-podstawki | nowe pola quote |

> **Zasada:** zanim dotkniesz pliku z tej tabeli, sprawdź czy wątek blokujący jest aktywny. Jeśli tak — koordynuj z odpowiednim `HANDOFF_<slug>.md`.

---

## Szybkozmienne notatki cross-wątkowe

*(Krótkie alerty istotne dla wielu wątków. Coś, co nie pasuje jeszcze do `docs/`, ale dotyczy więcej niż jednego wątku. Sprzątaj regularnie — przenoś do `docs/*` jeśli reguła stała się trwała.)*

- **2026-05-20:** Lokalny runtime na Windows — `.venv\Scripts\python` wskazuje WindowsApps Python z odmową dostępu. `make`/`pytest` poza PATH. Workaround: `python -m pytest` bezpośrednio.
- **2026-05-12:** Merge conflicts gałęzi Klasyfikacja nadal nierozwiązane — blokują SSOT Phase 5. Patrz [docs/roadmap.md](docs/roadmap.md).

---

## LOG SESJI

*(Append-only, najnowsze na górze. Krótka notatka per zakończone zadanie. Starsze wpisy w [docs/handoffs/LOG_ARCHIVE.md](docs/handoffs/LOG_ARCHIVE.md).)*

### 2026-11-04 — wydanie-poprawek (archived)
- Poprawki zapisano jako `5950224`, opublikowano najpierw na Rozwoj, potem na main przez fast-forward po scaleniu historii (`3996723`) zachowującym aktualny SZOP, zgodnie z potwierdzeniem usera o oddzieleniu OPOS. Bez force push; stary main pozostaje w historii. Usunięto z indeksu 32 pliki cache Pythona.
- Wydanie **v1.2.0** na `3a4b138`: https://github.com/rozgladacz/szop/releases/tag/v1.2.0. Lokalnie 370/370, CI Tests + Build & Push + Create Release success: https://github.com/rozgladacz/szop/actions/runs/41796075798. GHCR `1.2.0` i `latest` dostępne publicznie (HTTP 200), wspólny digest `sha256:19facbfdc97eb9102ff6040b1deb18e3a2292daa0f890cd8b0a648425c13f356`. Gotowe do aktualizacji z panelu aplikacji; produkcji nie aktualizowano. Kolejny commit wyłącznie archiwizuje dokumentację.

### 2026-11-02 — nazwy-liczebnosc-mobile (archived)
- Rozpiska przekazuje własne nazwy pasywnych z Armii przez wspólny parser `ability_registry.passive_custom_names`; lista, oba edytory i eksport pokazują „Nazwa [Reguła]”, zachowując kanoniczne etykiety wyceny. Dodano jawne −/+ dla liczebności klasycznej, kolekcji i proxy: delegacja `model_count_controls.js`, natywne ograniczenia i istniejący autosave, cele dotykowe 44×44 px.
- Weryfikacja: pełny pytest **370 passed** (+8 przypadków), frontend parity, simplify/review/security-review, call-site audit i czysty diff check. Smoke desktop oraz 320/390 px na kopii realnej bazy: nazwy (także Transport(11)), granice 1/0, autosave po reload, brak overflow kontrolek i błędów konsoli, Zbrojownia/Armie/Rozpiski OK. A/B payloadu 51 jednostek 20,17→20,76 ms (+2,9%), 0 zapytań DB; silnik kosztów bez zmian. Poprzednie poprawki zachowane; zmiany lokalne, bez wdrożenia i bez zmiany źródłowej bazy.

### 2026-10-29 — transport-bohater-modele (archived)
- Transport ma wspólną wycenę SSOT w kosztach bazowych, zdolnościach i quote; zachowane parametry pojemności oraz kontekst mobilności default/selected. Valkyria Transport(11) + Samolot: +44 pkt, zweryfikowane UI 216,18→260,18. Tryb modeli udostępnia istniejący selektor bohatera „Dołącz do”, zapisuje kompozycję przed attach/detach i blokuje akcję po błędzie/abort zapisu.
- Weryfikacja: pytest **362 passed** (30 nowych przypadków, frontend parity), smoke Zbrojownia / Armie / Rozpiski i attach/detach na kopii realnej bazy, call-site audit, simplify/review/security-review oraz czysty diff check. A/B roster 10 −3,9% full / −3,7% badge, roster 13 +3,4% / +7,5%; zero nowych zapytań DB, szczegóły w `docs/PERFORMANCE.md`. Zmiany lokalne, bez wdrożenia i bez zmiany źródłowej bazy.
- Pliki: `app/services/costs/{abilities,role_totals}.py`, `app/static/js/modules/{roster_collection_models,roster_rendering}.js`, `tests/test_{passive_costs,roster_unit_quote,frontend_models_hero}.py`.

### 2026-10-13 — backup-scheduler (archived)
- Usunięto cykl importu `backup_loop → backup → db_restore → db → ability_registry → models → db.Base` przez przeniesienie importów usług w `app/db.py` do miejsc użycia; sidecar ma teraz własny healthcheck procesu. Dodano test świeżego startu i faktycznej kopii SQLite/WAL; pełne pytest 332/332, Compose zweryfikowany na serwerze.
- Produkcja: z obrazu `szop-local:latest` zbudowano minimalny hotfix `szop-local:backup-fix-20261013` tylko dla `szop-backup`; `szop-app` pozostał na starym obrazie. Backup `running/healthy`, 0 restartów; nowa kopia `/srv/szop/data/backups/szop-backup-20261013-194255.db` (253952 B, `quick_check=ok`), SZOP/OPOS HTTP 200. Osobna kopia preflight: `pre-hotfix-20261013-192836.db`; rollback manifestu: `/srv/szop/docker-compose.pre-backup-hotfix-20261013.yml`. Przy kolejnym pełnym release zastąp lokalny pin backupu obrazem wydania; nocne uruchomienie 03:00 pozostaje do zaobserwowania.
- Pliki: `app/db.py`, `docker-compose.yml`, `tests/test_backup_scheduler.py`.

### 2026-09-02 — brama-opos-szop (archived)
- Wydzielono Caddy do publicznego repo `rozgladacz/brama`, OPOS do `rozgladacz/opos`, a SZOP pozostawiono w `rozgladacz/szop`; na jednym serwerze Oracle działają niezależne stosy i sieci `brama-szop` / `brama-opos`, a wyłącznie brama publikuje porty 80/443 dla `szop.duckdns.org` i `figurki.duckdns.org`.
- Weryfikacja: zielone CI (SZOP 329, OPOS 127 i rules drift, brama Compose/Caddy), produkcyjne HTTPS 200 z prawidłowymi certyfikatami, HTTP→HTTPS 308, nagłówki bezpieczeństwa i SQLite quick-check `ok`; stary Caddy pozostawiono zatrzymany jako szybki rollback, wykonano chronione kopie migracyjne, a wcześniejszego stanu kontenerów okresowego backupu nie zmieniano.

### 2026-08-01 — szop-hit-chance-sync (archived)
- Zsynchronizowano Zasadzkę i osobne Dobrze/Źle strzela w katalogu oraz Markdown, a wycenę trafienia rozdzielono na clamp szansy bazowej i premie post-clamp bez zmiany API. Produkcyjną `data/szop.db` odświeżono funkcjami SSOT po kopii bezpieczeństwa; cache 275 broni i 84 jednostek zweryfikowano bez rozbieżności.
- Weryfikacja: pytest 329/329, frontend parity 110/110, `/simplify`, `/review`, call-site audit i profile rosterów 10/13; kontrola A/B wykazała +1,8% full / +2,2% badge, poniżej progu 20%.

### 2026-07-14 — kolekcja (archived)
- Kolekcja fizycznych modeli użytkownika: **Faza 1** (CRUD modeli per oddział + magnetyzacja broni i zdolności + „Kopiuj") oraz **Faza 2** — integracja z rozpiską. „Tryb modeli" komponuje oddział z posiadanych egzemplarzy + proxy (broń i zdolności); derywacja suma→modele z budżetem montowania (`mount_need`, liczony z najwyżej `count` modeli). **Koszt modelu w Kolekcji** i **pełny koszt modelu w Rozpisce** liczone silnikiem (`calculate_roster_unit_quote.item_costs`) — SSOT, te same wartości co widok klasyczny. **Stan Bitewny** (2c/2d): eliminacja/wycofanie egzemplarzy, tryb „Modele", indywidualne nazwy zdolności, przekreślanie zdolności po eliminacji, czerwone ostrzeżenia zdrowia grupy.
- Pliki: `app/models.py` (+`CollectionModel`/`CollectionModelSlot` + kolumny slotu zdolności), `app/db.py` (migracje), `app/routers/{collections,rosters,export}.py`, `app/services/collection_match.py` (NEW), `app/templates/{collections_list,collection_unit_detail,roster_edit,roster_battle_state}.html`, `app/static/js/{battle_state.js, modules/roster_collection_models.js}`, `tests/test_collection_match.py`.
- Weryfikacja: pytest 291/291, `/simplify` + `/code-review` medium (findings #1/#3 naprawione, koszt przez SSOT #2), `/security-review` (IDOR naprawiony wcześniej). Commity: `199858b` (Faza 1), `9390cd7` (2b), `6830c92` (2b.1/2b.2), `9dd48a2` (fix IDOR), `9078499` (2c/2d/2e), `b061532` (koszt SSOT + magnetyzacja zdolności + Kopiuj + fix derive).

### 2026-07-10 — demoralizacja-mag (archived)
- Nowa zdolność Demoralizacja (koszt 25); przebudowa kosztu Maga (`X × clamp(T,6,18)` po rebalansie); rozdzielone formuły Rozkaz (`T_eff±2`) / Klątwa+Oznaczenie (`×6`) + tabela psujących cech jako tagi w `AbilityDefinition` (SSOT, zastąpiła hardcoded listy w `ability_registry`); lista zaklęć z wyborem trudności rzucania 2+..6+ (radio buttony, koszt pkt+żet na żywo, edycja mocy w miejscu dodawania, podgląd listy dla armii view-only); trudność widoczna w Stanie Bitewnym/wydrukach/eksporcie.
- Po drodze: `/security-review` znalazł i naprawił **IDOR (HIGH)** w `app/routers/collections.py` — `POST /collections/units/{unit_id}/models/add` nie sprawdzał własności jednostki, w odróżnieniu od sąsiedniego GET. Fix + regresja w osobnym commicie.
- Pliki: `app/data/abilities.py`, `app/services/costs/{abilities,_engine}.py`, `app/services/ability_registry.py`, `app/routers/armies.py`, `app/models.py` (+`ArmySpell.cast_difficulty`), `app/templates/{army_spells,armory_weapon_form,army_edit,roster_battle_state}.html`, `app/static/js/modules/spell_{ability_forms,weapon_cost_preview}.js`, `tests/test_{active_costs,spell_difficulty,army_spell_view_access,collections_authz}.py`; security fix: `app/routers/collections.py`.
- Weryfikacja: pytest 280/280, `/simplify` ×3, `/code-review` xhigh, `/security-review` (1 HIGH naprawiony). Commity: `746b661` (feature), `9dd48a2` (security fix).

### 2026-06-04 — primary-weapon-flag (archived)
- Klikalna flaga ⚑ broni podstawowej w edytorze rozpiski z zapisem override w `loadout_json.primary_weapon` (per typ: melee/ranged). Backend `_loadout_weapon_details` honoruje override przy budowaniu `weapon_details` dla Stanu Bitewnego. Dodatkowe fixy: null-override gubiony w `createLoadoutState` (deserialization), `assignDefaultWeapon` przepinane na `isCurrentPrimary` zamiast `isPrimaryWeapon` (slot-filler podąża za flagą).
- Pliki: `loadout_state.js`, `editor_renderers.js`, `roster_editor.js`, `rosters.py`.
- Weryfikacja: pytest 176/176, smoke OK.

### 2026-05-28 — strategic-cards (archived)
- Nowa funkcja: Karty Strategiczne w edytorze rozpiski — checkboxy wyboru 3 Zadań + 3 Wsparć (10+8 kart w pliku `app/data/strategic_cards.py`, zapis w `Roster.strategic_cards_json`), druk macierzy 3×3 na A4 z auto `window.print()`. UI: checkboxy z JS-limitem do 3, 3 przyciski submit (Zapisz / Zapisz i drukuj / Zapisz i wróć). Treści kart zaktualizowane do finalnej wersji (4 kategorie Zadań: Natarcie/Obrona/Dywersja/Zwiad).
- Pliki: `app/data/strategic_cards.py` (NEW), `app/models.py`, `app/routers/rosters.py`, `app/templates/roster_edit.html`, `app/templates/roster_strategic_cards{,_print}.html` (NEW), `tests/test_strategic_cards.py` (NEW, 27 testów).
- Weryfikacja: pytest 203/203, smoke przeglądarkowy OK, wydruk PDF zweryfikowany ręcznie. Migracja: `ALTER TABLE rosters ADD COLUMN strategic_cards_json TEXT`.

> Starsze wpisy: [docs/handoffs/LOG_ARCHIVE.md](docs/handoffs/LOG_ARCHIVE.md)
