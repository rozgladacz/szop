# HANDOFF — faza-b-5-client

> **Wątek:** Strumień B5 — klient gry `szop_client` (Protocol GameClient + LocalClient in-process). Pierwszy slice: LocalClient na ścieżce engine-dict (batch `simulate` + single-step play). HttpClient (B4) i ładowanie z DB (roster adapter) odłożone.
> **Status:** In progress
> **Utworzony:** 2026-06-13
> **Ostatnia aktualizacja:** 2026-06-14

## W TRAKCIE: 2026-06-14 — domknięcie B5: fix 2 testów (założenie „deployment puste → 0 eventów" błędne, pkt 13.c Ufortyfikowany) + ADR-0016 + roadmap B5 + weryfikacja + commit

## Cel

Wydzielić stabilny seam klienta gry (`szop_client.GameClient` Protocol) ponad publicznym API silnika (ADR-0011) i runnerem (`agents/match.py`, ADR-0032), z implementacją in-process `LocalClient`. To realizuje roadmap B5 i odblokowuje C3 `simulate_engagement` (MCP tool) oraz przyszły test parity `HttpClient == LocalClient` (po B4).

`match.py` docstring sam wskazuje ten wątek jako swój następny krok ("zalążek B5 LocalClient.simulate; pełen B5 z Protocol GameClient + HttpClient poza zakresem").

## Zablokowane pliki / katalogi

- `szop_client/` (NEW pakiet) — `__init__.py`, `protocol.py`, `local.py`
- `tests/test_clients_local.py` (NEW)
- `docs/adr/0016-szop-client.md` (NEW — Accepted)
- `docs/roadmap.md` — statusy B5 (UWAGA: ma niezacommitowane zmiany D5/E4 — praca równoległa; edytuję tylko sekcję B5, nie ruszam D5/E4)

**Read-only (reuse, zero zmian):** `app/services/agents/match.py`, `app/services/engine/{resolver,phases,state,actions,dice}.py`.

## Blokuje / Blokowane przez

- **Blokuje:** C3 `simulate_engagement` (MCP), test parity `HttpClient==LocalClient`.
- **Blokowane przez:** nic dla tego slice'a (engine + match runner gotowe). HttpClient blokowany przez B4 API. Ładowanie rosterów z DB blokowane przez `faza-d-roster-adapter` (patrz Notatki).

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

- [x] B5.1 — `szop_client/protocol.py`: `GameClient` Protocol (create_battle / get_state / take_action / get_events / simulate) + typy wyników (`SimulationSummary`).
- [x] B5.2 — `szop_client/local.py`: `LocalClient` in-process. `create_battle`/`get_state`/`take_action`/`get_events` (rejestr bitew w pamięci) + `simulate` (batch N gier, reuse `simulate_from_rosters`, rozłączne seedy graczy per F2).
- [x] B5.3 — `szop_client/__init__.py`: eksporty publiczne.
- [x] B5.4 — `tests/test_clients_local.py`: determinizm per seed, single-step == match runner, batch agregacja, walidacja IllegalAction. **13 testów. Fix 2026-06-14:** 2 testy miały błędne założenie „deployment puste → 0 eventów"; rozstawienie emituje `StatusAdded(Ufortyfikowany)` per oddział, który nie ruszył się (pkt 13.c). Sekwencja eventów kontynuuje monotonicznie (event-sourcing) — testy poprawione, nie implementacja.
- [x] B5.5 — `docs/adr/0016-szop-client.md` (Accepted) + ADR index w roadmap (✓).
- [x] B5.W — Weryfikacja end-to-end: pytest **1641 passed** (1628 baseline + 13); `/simplify` inline 4 kąty (0 zmian — czysto, brak dead imports, `simulate` świadomie nie reużywa `scripts.balance_simulate` by nie odwracać zależności package→script, parity-tested); `/review`/`/security-review` pominięte warunkowo (izolowany nowy pakiet, reads-only API silnika, brak hot-path/SSOT/auth/DB, pełne pokrycie 13 testami incl. parity).

## Pliki dotknięte

- `szop_client/__init__.py` (NEW) — eksporty publiczne
- `szop_client/protocol.py` (NEW) — `GameClient` Protocol + `SimulationSummary` + typy callbacków
- `szop_client/local.py` (NEW) — `LocalClient` in-process + `UnknownBattleError`
- `tests/test_clients_local.py` (NEW) — 13 testów
- `docs/adr/0016-szop-client.md` (NEW, Accepted)
- `docs/roadmap.md` (B5 sekcja + ADR index 0016 ✓)
- `HANDOFF.md` (wiersz wątku w tabeli aktywnych)

## Decyzje

- 2026-06-13: Slice = tylko `LocalClient` na ścieżce **engine-dict** (rostery jako dict 1:1 z `build_initial_state`, jak fikstury). DB-backed `LocalClient(db_session, user_id)` z roadmap odłożony do `faza-d-roster-adapter` (most ORM→engine-dict). Uzasadnienie: adapter to głęboka archeologia modelu danych (`Weapon.range` to wolny tekst, mapowanie slugów zdolności, attached heroes, ekstrakcja loadoutu) z niejednoznacznymi decyzjami — nie domyka się czysto w jednym oknie.
- 2026-06-13: `HttpClient` + `tests/test_clients_parity.py` odłożone do B4 (API musi istnieć). Pakowanie `pip install -e szop_client/` (setup.py) odłożone — `LocalClient` jest z natury in-process z `app`, więc standalone-install ma sens dopiero z `HttpClient`. `szop_client` importowany jako pakiet top-level (jak `app`).
- 2026-06-13: `subscribe_events` (push/SSE z roadmap) → w LocalClient realizowany jako pull `get_events(battle_id, since)`; streaming SSE to B6. Protocol eksponuje `get_events` jako prymityw pull.
- 2026-06-13: `take_action` używa `apply_activation` (model do-2-akcji, ADR-0051) z opcjonalnym `continuation`, spójnie z `match.run_match`.

## Hipotezy / pytania otwarte

- (brak blokad usera dla tego slice'a)

## Jak zweryfikować

```powershell
python -m pytest tests/test_clients_local.py -v
python -m pytest -q   # baseline 1628 + nowe
python -c "import szop_client; print(szop_client.LocalClient)"
```

## Notatki / odkrycia w trakcie

- **2026-06-13 — SCOPING `faza-d-roster-adapter` (uzbrojony, nie uruchomiony).** Adapter ORM `Roster`→engine-dict (prereq D3 `exploit_hunt` + D2 breakdown per-zdolność + DB-backed `LocalClient`) wymaga rozwiązania (przeczytane modele `app/models.py`):
  - `Roster` → `RosterUnit` (`count`, `extra_weapons_json`, `parent_roster_unit_id` = attached heroes) → `Unit` (`quality`/`defense`/`toughness`/`typical_models`/`flags`, `abilities: List[UnitAbility]`, `weapon_links: List[UnitWeapon]→Weapon`).
  - **`Weapon.range` to STRING** (np. `24"`, `Walka wręcz`) — wymaga parsera do `range_inches: int`. `Weapon.attacks: float`, `Weapon.ap: int`, `Weapon.tags: str` (→ weapon_abilities). Dziedziczenie po `parent` (effective_* properties).
  - **Mapowanie zdolności:** `UnitAbility` (slug + `ability_value`) → engine `passives`. Trzeba: odfiltrować `b_mvp_exclusions` (inaczej `build_initial_state` rzuca `UnsupportedAbilityError`) + zignorować `INCOMPLETE_ABILITIES` (engine cicho je pomija). Decyzja: adapter DROPuje wykluczone/niekompletne i raportuje, by symulacja szła na podzbiorze MVP.
  - **`models_alive` semantyka:** `RosterUnit.count` (liczba kopii oddziału) vs `Unit.typical_models` (rozmiar oddziału). Kandydat: `count` blobów po `typical_models` modeli, lub 1 blob × (count×typical_models). DO ROZSTRZYGNIĘCIA.
  - **Koszt (metryka D3):** `calculate_roster_unit_quote(unit, loadout, count, include_item_costs)` (`app/services/costs/quote.py:64`, SSOT Strumień A) — gotowe, adapter tylko wywołuje.
  - **Auto-rozstawienie:** pozycje w strefie rozstawienia (pkt 3) — grid równomierny (D5 też tego dotyczy).
  - Klasyfikacja: NIE blokada usera (czysta inżynieria), ale ≥1 osobny wątek przez głębokość + decyzje modelowania. Kandydat na `faza-d-roster-adapter`.

## Decyzje zamrożone (NIE podnosić ponownie)

*(brak)*
