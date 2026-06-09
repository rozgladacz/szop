# HANDOFF — faza-b-order-interrupts

> **Wątek:** Implementacja Klątwa(X)/Rozkaz(X)/Oznaczenie(X) (id 45/49/50) — przerwanie `BEFORE_ACTION` (pkt 11.b.i) nadające/odbierające pasywkę X do końca aktywacji, raz na rundę.
> **Status:** In progress
> **Utworzony:** 2026-06-09
> **Ostatnia aktualizacja:** 2026-06-09

## Cel

Zaimplementować trzy aktywne zdolności-przerwania, które do końca aktywacji nadają (wariant pozytywny) lub odbierają (wariant negatywny) wskazaną pasywkę X innemu oddziałowi:
- **Rozkaz(X)** (id 50) — sojuszniczy oddział w 12″.
- **Klątwa(X)** (id 45) — wrogi oddział w 12″.
- **Oznaczenie(X)** (id 49) — sojuszniczy oddział atakujący cel w 12″ od nosiciela.

Policy (user, autor reguł, 2026-06-09): wyzwalane w `BEFORE_ACTION` (pkt 11.b.i), raz na rundę, efekt do końca aktywacji, X = pasywka z `rozkaz_tak: true`. Brakująca mechanika engine (główna robota): czasowe nadanie/odebranie pasywki + licznik „raz na rundę" + sprzątanie na końcu aktywacji.

## Zablokowane pliki / katalogi
- `app/services/engine/state.py` — `UnitBlob.ability_overrides`, `BattleState.used_interrupts_this_round`, `effective_passives()` helper
- `app/services/engine/effects.py` — agregatory czytają effective passives; handlery Rozkaz/Klątwa/Oznaczenie
- `app/services/engine/events.py` — `AbilityGranted` / `AbilityRemoved`
- `app/services/engine/reducers.py` — reducery nowych eventów + pole w `_BLOB_REPLAY_FIELDS`
- `app/services/engine/interrupts.py` — rejestracja handlerów w `BEFORE_ACTION`
- `app/services/engine/phases.py` — revert override'ów na końcu aktywacji + reset `used_interrupts_this_round` w `round_end_phase`
- `tests/test_engine_*.py` — nowe testy
- `docs/adr/0049-*.md` (NEW) — mechanizm ability-override + per-round limit

## Blokuje / Blokowane przez
- **Blokuje:** nic krytycznego (przyrostowa zdolność).
- **Blokowane przez:** nic — ADR-0015 skorygowany (BEFORE_ACTION).

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Substrat: temporal ability-override — **DONE 2026-06-09**
- [x] 1.1: `UnitBlob.ability_overrides: tuple[tuple[str, bool], ...] = ()` (slug, granted).
- [x] 1.2: `effective_passives(blob) -> tuple[str, ...]` — order-sensitive (ostatni override wygrywa), fast-path identity gdy brak override'ów.
- [x] 1.3: Read-sites na effective passives: `effects.py` 4 agregatory + `interrupts.get_eligible_interrupts` + `combat.py` Bastion check.
- [x] 1.4: Eventy `AbilityOverrideApplied(target_id, ability, granted, source_id)` / `AbilityOverridesCleared(target_id)` w `events.py` (Union + _EVENT_REGISTRY) + reducery w `reducers.py` + `ability_overrides` w `_BLOB_REPLAY_FIELDS`.
- [x] 1.5: Testy substratu — `tests/test_engine_order_abilities.py` (15: effective_passives ×8 + integracja morale ×2 + reducer/replay ×5). pytest 1450/1450.

### Faza 2 — Per-round limit + handlery — **DONE 2026-06-09**
- [x] 2.1: `BattleState.used_interrupts_this_round: tuple[tuple[int,str], ...] = ()` + reset w `round_end_phase` (producer) + `_reduce_round_ended` (replay).
- [x] 2.2: Handlery `rozkaz`/`klatwa`/`oznaczenie` w `interrupts.py` (przy Strażniku), `@register_interrupt_handler(BEFORE_ACTION, slug)`. Wspólny `_apply_order_like` — walidacja `InvalidInterruptError`: X z `rozkaz_tak:true` (`_rozkaz_capable_slugs` lru_cache), zasięg 12″ (`circle_edge_distance`), ally (rozkaz/oznaczenie) vs enemy (klatwa), raz-na-rundę. Emit `InterruptTriggered`+`AbilityOverrideApplied`. `_reduce_interrupt_triggered` odtwarza limit dla `ONCE_PER_ROUND_INTERRUPTS`.
- [x] 2.3: `rozkaz`/`klatwa`/`oznaczenie` NIE były w `INCOMPLETE_ABILITIES` (type=active, nie stub) — nic do usunięcia. Slugi nosicieli + `nieustraszony` (X) potwierdzone w abilities.yaml.
- [x] 2.4: Testy `test_engine_order_abilities.py` (+10: grant ally/range, suppress, klatwa enemy + reject ally, rozkaz reject enemy, out-of-range, non-rozkaz_tak, raz-na-rundę, defeated target, replay limit+override). pytest 1460/1460.
- **Uproszczenie MVP (H-note):** Oznaczenie (pkt 49) — precyzyjny trigger „sojusznik atakujący cel w 12″ od nosiciela" uproszczony do „sojusznik w 12″ od nosiciela" (jak Rozkaz, osobny slug+limit). Pełny trigger ataku wymaga orkiestracji przerwań (H2/B4).

### Faza 3 — Revert na końcu aktywacji — **DONE 2026-06-09**
- [x] 3.1: `activation_phase` po Aktywowany (pkt 11.b.vi) czyści `ability_overrides` WSZYSTKICH oddziałów — emit `AbilityOverridesCleared` per oddział z override'ami (replay mirror `_reduce_ability_overrides_cleared`).
- [x] 3.2: Testy (+3): override wyczyszczony po aktywacji, replay invariant (ability_overrides bit-perfect), brak eventu gdy brak override'ów. pytest 1463/1463, smoke EXIT 0.

### Faza 4 — Weryfikacja end-to-end (Definition of Done)
- [x] `python -m pytest -q` — **1463 passed**.
- [x] `OPR_RULES_BACKEND=both_assert pytest tests/test_ruleset_parity.py` — **156/156**.
- [x] `OPR_RULES_BACKEND=yaml pytest tests/yaml_backend/` — **93/93**.
- [x] `python scripts/engine_smoke_replay.py` — **EXIT 0** (48 events).
- [x] ADR-0049 (NEW Accepted) + refresh ADR-0011 (16 event types + substrat) + roadmap (R4.Klątwa MVP done + ADR index) + parent handoff backlog.
- [ ] `/simplify` + Call-site check — przy domknięciu wątku (follow-upy pozostają).
- [ ] `/handoff-archive faza-b-order-interrupts` — po follow-upach (Oznaczenie trigger + auto-orkiestracja) LUB świadomej decyzji o ich deferze.

## Stan: MVP mechanizmu DONE (Fazy 1-3 ✅). Pozostałe follow-upy
- **`READY`** Oznaczenie precyzyjny trigger: „sojusznik atakujący cel w 12″ od nosiciela" (zasięg do ofiary ataku) — wymaga kontekstu ataku.
- **`WAITING(B4)`** auto-orkiestracja: wpięcie deklaracji przerwań w pętlę `activation_phase`/resolver (kto wywołuje + wybór celu = decyzja gracza, jak Action).

## Pliki dotknięte
*(wypełni się w trakcie)*

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-09: Policy Klątwa/Rozkaz/Oznaczenie (user, autor reguł) — BEFORE_ACTION, raz na rundę, do końca aktywacji, X = pasywka `rozkaz_tak:true`. Patrz parent HANDOFF_faza-b-engine-mvp.

## Hipotezy / pytania otwarte
- **H1 (`READY` — założenie do potwierdzenia):** wariant pozytywny (nadaj X) vs negatywny (odbierz X) — które abilities to które? Reguła: „(nie)miał zdolność X". Założenie MVP: kierunek przekazany w `payload['granted']` (bool) akcji/przerwania; nosiciel deklaruje. Nie blokuje substratu.
- **H2 (`WAITING(B4)`):** auto-orkiestracja „kto i kiedy wywołuje przerwanie + wybór celu" — to decyzja gracza (jak Action). Wymaga warstwy deklaracji przerwań (resolver/API B4). W tym wątku handlery są wywoływalne przez `trigger_interrupt` (jak Strażnik), bez auto-wiring w pętli aktywacji.

## Jak zweryfikować
```powershell
python -m pytest tests/test_engine_interrupts.py tests/test_engine_effects.py tests/test_engine_order_abilities.py -v
python -m pytest -q
python scripts/engine_smoke_replay.py
```

## Notatki / odkrycia w trakcie
- 2026-06-09: Wątek utworzony. Substrat (Faza 1) to reusable core wskazany przez usera jako główna brakująca mechanika. `effects.py` czyta passives w 4 agregatorach + `interrupts`/`combat` — switch na `effective_passives` kontrolowany.
