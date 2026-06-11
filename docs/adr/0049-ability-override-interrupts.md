# ADR-0049 — Czasowy ability-override + przerwania Rozkaz/Klątwa/Oznaczenie

- **Status:** Accepted
- **Data:** 2026-06-09
- **Kontekst:** Strumień B, wątek `faza-b-order-interrupts`. Zdolności aktywne
  Rozkaz(X) (id 50), Klątwa(X) (id 45), Oznaczenie(X) (id 49) — `SZOP_Zdolnosci.md`
  #45/49/50 — nadają lub odbierają wskazaną pasywkę X innemu oddziałowi „od teraz
  do końca aktywacji". Policy (user, autor reguł, 2026-06-09): wyzwalane w
  `BEFORE_ACTION` (pkt 11.b.i, ADR-0015 po korekcie), raz na rundę, X = pasywka z
  `rozkaz_tak: true`. Przed tym wątkiem engine nie miał mechanizmu **czasowej
  modyfikacji zbioru pasywów** oddziału ani **per-rundowego limitu przerwań**.

## Decyzja

### 1. Substrat: `UnitBlob.ability_overrides` + `effective_passives`

`UnitBlob.ability_overrides: tuple[tuple[str, bool], ...]` — lista `(slug, granted)`
nakładek na bazowe `passives`, aktywnych do końca aktywacji. `granted=True` nadaje
X, `granted=False` odbiera/tłumi X (wariant pozytywny/negatywny — pkt 12
„(nie)miał zdolność X").

`state.effective_passives(blob) -> tuple[str, ...]` liczy efektywny zbiór: aplikuje
override'y w kolejności (ostatni wygrywa), zachowując kolejność bazowych pasywów
(determinizm agregatorów). Fast-path: brak override'ów → zwraca `blob.passives`
(identity, zero alokacji — hot path combat).

**Wszystkie konsumenci pasywów czytają `effective_passives`**, nie surowe
`passives`: agregatory w `effects.py` (defense/attack/weapon),
`interrupts.get_eligible_interrupts`, `combat` (check Bastion), `phases._regroup_test`
(pkt 20.e Nieustraszony). Dzięki temu nadana przez Rozkaz pasywka faktycznie działa
(np. Nieustraszony → skip testów Przegrupowania powyżej połowy, pkt 20.e), a Klątwa
realnie odbiera (np. zdejmuje Bastion).

> **Nota (drift pkt 20.e 2026-06):** pierwotny przykład „Nieustraszony → morale −1"
> jest nieaktualny — addytywny morale modifier usunięty; Nieustraszony jest binarny
> (powyżej połowy → 0 testów). Mechanizm override bez zmian: grant/suppress nadal
> wstrzykuje/odbiera slug w `effective_passives`, który `_regroup_test` konsumuje.

### 2. Eventy + reducery (event-sourced, ADR-0010/0046)

- `AbilityOverrideApplied(target_id, ability, granted, source_id)` — reducer
  dopisuje `(ability, granted)` do `target.ability_overrides`.
- `AbilityOverridesCleared(target_id)` — reducer zeruje `ability_overrides`
  (koniec aktywacji).

`ability_overrides` dodane do `_BLOB_REPLAY_FIELDS` → replay invariant weryfikuje
propagację (`apply_events(initial, events)` bit-perfect).

### 3. Per-rundowy limit „raz na rundę"

`BattleState.used_interrupts_this_round: tuple[tuple[int, str], ...]` — pary
`(source_unit_id, slug)` użyte w rundzie. Reset w `round_end_phase` (producer) +
`_reduce_round_ended` (replay). `InterruptTriggered.consumes_round_limit: bool`
czyni event **samoopisującym się** (jak `MutexCollision.dropped_statuses`):
producer ustawia flagę z `ONCE_PER_ROUND_INTERRUPTS = {rozkaz, klatwa, oznaczenie}`
(źródło polityki), a `_reduce_interrupt_triggered` dopisuje `(source, slug)` gdy
flaga True — bez hardkodowania listy slugów w reducerze (Strażnik=False, brak
limitu). Klucz `(source, slug)` ⇒ jeden oddział z Rozkaz i Klątwą może użyć każdej raz.

### 4. Handlery (interrupt `BEFORE_ACTION`)

`interrupts._apply_order_like(context, payload, *, slug, require_enemy)` — wspólna
logika. Payload: `target_id`, `ability` (X), `granted` (default True), `sequence`.
Walidacja → `InvalidInterruptError`:
1. limit raz-na-rundę (`(source, slug)` ∉ `used_interrupts_this_round`),
2. cel istnieje i `models_alive > 0`,
3. X ma `rozkaz_tak: true` (`_rozkaz_capable_slugs` z `load_ruleset`, lru_cache),
4. ally (rozkaz/oznaczenie) vs enemy (klatwa),
5. zasięg 12″ krawędź-krawędź (`geometry.circle_edge_distance`).

Emit `InterruptTriggered` + `AbilityOverrideApplied`; mutacja live state (override
na celu + zapis limitu) lustrzana do reducerów.

## Konsekwencje

**Pozytywne:** reusable substrat (każda przyszła zdolność modyfikująca zbiór
pasywów używa `ability_overrides`); efekt realnie wpływa na combat/morale; replay
bit-perfect; limit per-runda event-sourced; walidacja deterministyczna i testowalna.

**Negatywne / uproszczenia MVP:**
- **Oznaczenie (pkt 49)** — reguła celuje w sojusznika *atakującego cel w 12″ od
  nosiciela* (zasięg do ofiary ataku, trigger przy deklaracji ataku). MVP traktuje
  jak „sojusznik w 12″ od nosiciela" (mechanicznie jak Rozkaz, osobny slug+limit).
  Pełny trigger ataku wymaga orkiestracji przerwań (H2/B4).
- **Auto-orkiestracja** — „kto i kiedy wywołuje przerwanie + wybór celu" to
  decyzja gracza (jak Action). Handlery są wywoływalne przez `trigger_interrupt`
  (jak Strażnik), ale nie są jeszcze auto-wpięte w pętlę `activation_phase` —
  wymaga warstwy deklaracji przerwań (resolver/API B4).
- `effective_passives` wywoływane per agregator (recompute) — fast-path identity
  niweluje koszt dla oddziałów bez override'ów (większość).

## Alternatywy rozważone

- **Mutacja `passives` bezpośrednio** (bez osobnego pola + revert tracking).
  Odrzucone — utrata bazowego zbioru (nie da się odróżnić nadanego X od wrodzonego
  przy wygaśnięciu) + revert wymagałby osobnej księgowości i tak.
- **Dwa zbiory `granted_abilities`/`suppressed_abilities`** zamiast listy
  `(slug, granted)`. Odrzucone — lista zachowuje kolejność/historię (ostatni
  wygrywa), prostszy replay (append-only do wygaśnięcia).
- **Limit per-runda jako stan blobа** (na nosicielu). Odrzucone — limit jest
  własnością rundy/gry, nie oddziału; `BattleState`-level + reset w round_end
  czystsze.

## Inwarianty (testy)

1. `effective_passives` order-sensitive, fast-path identity (8 testów).
2. Grant/suppress realnie zmienia `effective_passives` (Nieustraszony — pkt 20.e
   konsumowane w `phases._regroup_test`; pierwotnie probowane przez usunięty
   `aggregate_morale_modifier`).
3. Walidacja: ally/enemy, zasięg 12″, `rozkaz_tak`, raz-na-rundę, defeated target.
4. Replay: `AbilityOverrideApplied`/`Cleared`/`InterruptTriggered` rekonstruują
   `ability_overrides` + `used_interrupts_this_round` bit-perfect.
5. `activation_phase` czyści override'y na końcu (pkt 11.b.vi) + replay invariant.

Plik testów: `tests/test_engine_order_abilities.py` (28 testów).
