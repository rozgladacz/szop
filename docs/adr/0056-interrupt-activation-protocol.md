# ADR-0056 — Trwały protokół aktywacji i okien przerwań

- **Status:** Accepted
- **Data:** 2026-07-19
- **Kontekst:** B4.4a; projekt przed implementacją
  `POST /battles/{id}/interrupts`
- **Rozszerza:** ADR-0010, ADR-0015, ADR-0015a, ADR-0049, ADR-0051 i
  ADR-0054. Nie zmienia ich historycznych eventów ani kontraktów legacy.

## Context / evidence

### Kanoniczne reguły

Poniższe wnioski pochodzą z ponownie odczytanych źródeł reguł, nie z
historycznych ADR-ów:

| Dowód | Zamrożony wniosek |
|---|---|
| [Rozjemca, pkt 10][R10] | W każdej chwili istnieje dokładnie jeden właściciel inicjatywy; nie wolno utożsamiać przekazania priorytetu w oknie z przekazaniem inicjatywy. |
| [Rozjemca, pkt 8.a][R8] | Inicjatywa jest przekazywana dopiero po aktywacji. Właściciel inicjatywy skopiowany do aktywacji pozostaje więc stały przez oba jej okna. |
| [Rozjemca, pkt 11.b.i–vi][R11] | Kolejność zwykłej aktywacji to: przerwania, akcja, Przegrupowanie, opcjonalny powrót przed drugą akcją, Odzyskiwanie ran, stan Aktywowany i koniec aktywacji. Pełnej akcji nie deklaruje się przed pierwszym krokiem. |
| [Rozjemca, pkt 12.a–c][R12] | Okno istnieje tylko we wskazanym miejscu; jedno przerwanie kończy się atomowo przed następnym; gracz z inicjatywą wykonuje zero lub wiele wybranych przerwań, po czym przekazuje możliwość następnemu graczowi. |
| [Rozjemca, pkt 20][R20] | Przegrupowanie następuje po każdej akcji, a nie raz na końcu aktywacji. |
| [Rozjemca, pkt 21][R21] | Odzyskiwanie ran następuje po wszystkich akcjach i Przegrupowaniach; wybór użytych zdolności należy do gracza, więc serwer nie może go dopowiadać. |
| [Rozjemca, pkt 14.d.iv][R14] i [pkt 17][R17] | Kontratak oraz atak wykonywany przez przerwanie są rozstrzyganymi atakami. Ich wewnętrzna atomowość nie tworzy kolejnego ogólnego okna `BEFORE_ACTION`. |
| [Zdolności, pozycja 31 Strażnik][Z31] | Strażnik wykonuje rzeczywisty Ostrzał w aktywacji przeciwnika, a następnie staje się Wyczerpany; event bez tych skutków nie jest implementacją zdolności. |
| [Zdolności, pozycja 45 Klątwa(X)][Z45] | Klątwa jest raz na rundę, celuje we wroga w 12″, używa tylko X z `klatwa_tak: true` i trwa do końca aktywacji. |
| [Zdolności, pozycja 49 Oznaczenie(X)][Z49] | Oznaczenie jest raz na rundę, mierzy 12″ do celu ataku, nadaje X innemu sojuszniczemu atakującemu i wygasa po tym konkretnym ataku. |
| [Zdolności, pozycja 50 Rozkaz(X)][Z50] | Rozkaz jest raz na rundę, celuje w sojusznika w 12″, używa tylko X z `rozkaz_tak: true` i trwa do końca aktywacji. |

### Stan kodu w chwili decyzji

- `BattleState` ma `active_player`, placeholder `pending_interrupts` oraz
  per-rundowe `used_interrupts_this_round`, ale nie ma osobnego właściciela
  inicjatywy, wybranego oddziału, aktywacji w toku, fazy okna, priorytetu,
  passów ani wersji okna.
- Codec `szop.battle_state/v1` wymaga dokładnego zestawu pól dataclassy. Nie
  potrafi bezpiecznie odtworzyć nowego stanu z historycznego checkpointu przez
  samo dodanie wartości domyślnych.
- `resolver.apply_activation` trzyma `actions_taken` tylko na stosie procesu.
  `_begin_activation` jest wykonywane raz, `_apply_single_action` wykonuje akcję
  i Przegrupowanie, a `_finalize_activation` czyści override'y i nadaje
  Aktywowany. Dopiero potem resolver zmienia `active_player`.
- `resolver.apply` oraz publiczny `POST /battles/{id}/actions` składają całą
  jednoakcyjną aktywację w jednej transakcji. Nie istnieje trwałe miejsce, do
  którego osobny request interruptu mógłby bezpiecznie wrócić.
- `_switch_active_player` po finalizacji zmienia tylko `active_player` i robi to
  warunkowo; nie utrwala osobnego właściciela inicjatywy przekazywanej po
  aktywacji ([pkt 8.a][R8]).
- `get_eligible_interrupts` sprawdza żywy oddział, efektywne pasywki i sam fakt
  rejestracji handlera. `trigger_interrupt` można jednak wywołać bez dowodu, że
  source ma slug, należy do bieżącego priorytetu albo do caller-a.
- Strażnik emituje tylko stubowy `InterruptTriggered`. Oznaczenie używa wspólnej
  logiki Rozkazu i błędnie tworzy activation-scoped override. Wspólny validator
  Rozkaz/Klątwa/Oznaczenie sprawdza `rozkaz_tak`, mimo że Klątwa wymaga
  `klatwa_tak`, a Oznaczenie `oznaczenie_tak` ([pozycja 45][Z45],
  [49][Z49] i [50][Z50]).
- `battle_actions` ma poprawny participant scope, ownership aktora, świeży
  checkpoint state+RNG, `expected_sequence`, ciągły event tail, checkpoint i
  rollback. Ten seam należy rozszerzyć, nie duplikować.
- `LocalClient.take_action` wywołuje procesowy `apply_activation` z callbackiem;
  `HttpClient.take_action` pobiera świeży checkpoint i POST-uje jedną akcję,
  odrzucając callback. `agent_proposals` reużywa `battle_actions`; MCP wyłącznie
  czyta/proponuje przez publiczny klient. Wszystkie te call sites są częścią
  późniejszej migracji.

### Drifty historyczne

| Drift | Rozstrzygnięcie |
|---|---|
| ADR-0015 i ADR-0015a zachowały fragmenty o czterech punktach przerwań. | Historyczne fragmenty nie są źródłem reguł. Kanonem jest jedno `BEFORE_ACTION`, odwiedzane najwyżej dwa razy przez pętlę aktywacji ([pkt 11.b.i oraz iv][R11]). |
| ADR-0051 uznał procesowy `actions_taken` za wystarczający. | To pozostaje poprawne dla lokalnej, nieprzerywanej symulacji, ale nie dla restart-safe HTTP. Trwały transport wymaga stanu aktywacji i eventów przejść. |
| ADR-0049 opisuje Oznaczenie jako uproszczony override do końca aktywacji. | Uproszczenie nie może być publicznym handlerem. Efekt musi być ograniczony do konkretnego ataku ([pozycja 49][Z49]). |
| Event `InitiativePassed` zmienia tylko `active_player`. | Tag zostaje legacy. Protokół v2 wprowadza osobny stan inicjatywy i semantycznie poprawne eventy przejść; nie zmienia znaczenia historycznego eventu. |

## Decision

### 1. Granice protokołu

1. `POST /battles/{id}/interrupts` nie może mutować „obecnego checkpointu” bez
   trwałej aktywacji i otwartego okna. Taki checkpoint nie dowodzi, który
   oddział wybrano, przed którą akcją jesteśmy, czy gracz już spasował ani kto
   ma priorytet. Po restarcie lub race nie da się rozstrzygnąć, czy request jest
   legalny.
2. Pełny `Action` może zostać przyjęty dopiero w fazie `ACTION_READY`, po
   zamknięciu `BEFORE_ACTION`. Przyjęcie action intent wcześniej odwracałoby
   kolejność [pkt 11.b.i–ii][R11] i ujawniałoby przeciwnikowi wybór, którego nie
   powinien znać podczas podejmowania wcześniejszych decyzji.
3. Każda zaakceptowana mutacja protokołu emituje co najmniej jeden event,
   zwiększa globalny sequence i zapisuje dokładnie jeden spójny checkpoint
   state+RNG w tej samej transakcji. Nie ma trwałego stanu „handler właśnie się
   wykonuje”: sukces zapisuje całość, błąd lub crash rollbackuje całość.
4. Ogólne okno przerwań jest no-nested. Handler otrzymuje kontekst z
   `interrupt_depth=1` i nie może otworzyć `BEFORE_ACTION` ani wywołać publicznej
   ścieżki interruptu. Następne przerwanie jest możliwe dopiero po pełnym
   zakończeniu poprzedniego, zgodnie z [pkt 12.b][R12].

### 2. Trwały stan

Checkpoint schema v2 dodaje do `BattleState`:

```text
initiative_player: 0 | 1
activation: ActivationState | null
```

`initiative_player` to bieżący właściciel inicjatywy. Przy starcie aktywacji
jest kopiowany do `ActivationState.initiative_player`; snapshot nie zmienia się
przy pass/handoff i jest początkiem kolejki obu okien. Dopiero finalizacja
przekazuje top-level inicjatywę oraz ustawia następnego `active_player`
([pkt 8.a][R8], [pkt 10][R10]).

`ActivationState` ma dokładnie:

```text
activation_id: int                 # sequence eventu ActivationStarted
version: int                       # rośnie po każdym accepted transition
selected_unit_id: int
controlling_player: 0 | 1
initiative_player: 0 | 1           # stały snapshot dla tej aktywacji
action_count: 0..2
action_types: tuple[str, ...]       # kanoniczne discriminators codeca Action
phase: BEFORE_ACTION | ACTION_READY |
       AWAITING_CONTINUATION | AWAITING_FINALIZATION
window: InterruptWindowState | null
```

`InterruptWindowState` ma:

```text
ordinal: 1 | 2
version: int                       # rośnie po interrupt/pass w tym oknie
priority_player: 0 | 1
passed_players: tuple[0 | 1, ...]  # bez duplikatów, w kolejności
interrupt_count: 0..64
```

`active_player` pozostaje właścicielem wyboru oddziału/akcji. Nie służy już do
modelowania chwilowego priorytetu interruptów. `pending_interrupts` nie jest
SSOT protokołu i zostaje usunięte w schema v2 po migracji call sites.

Limit 64 zaakceptowanych interruptów na okno jest limitem bezpieczeństwa
transportu, nie twierdzeniem o regułach gry. Po osiągnięciu limitu kolejne
`operation=interrupt` zwraca 422, ale bieżący gracz nadal może wykonać `pass`.
ADR nie wymyśla ogólnego limitu „raz na okno”: ograniczenia użycia egzekwuje
source-correct handler (np. raz/rundę dla [Klątwy][Z45],
[Oznaczenia][Z49] i [Rozkazu][Z50]). Liczba okien jest ograniczona do dwóch
przez [pkt 11.b.iv][R11].

### 3. Kanoniczna maszyna stanów

```text
IDLE
  -> start(selected_unit)
BEFORE_ACTION #1 (priority = initiative_player)
  -> interrupt* -> pass/handoff -> interrupt* -> pass/close
ACTION_READY
  -> POST /actions -> akcja -> Przegrupowanie
AWAITING_CONTINUATION
  -> continue -> BEFORE_ACTION #2
  -> finalize(no second action) -> Odzyskiwanie ran -> finalizacja
BEFORE_ACTION #2
  -> interrupt* -> pass/handoff -> interrupt* -> pass/close
ACTION_READY
  -> POST /actions -> akcja -> Przegrupowanie
AWAITING_FINALIZATION
  -> finalize -> Odzyskiwanie ran -> Aktywowany -> transfer -> IDLE
```

Tabela przejść jest normatywna:

| Stan | Operacja i caller | Eventy domenowe przejścia | Stan po |
|---|---|---|---|
| `IDLE` | `start`; owner `active_player` wybiera własny legalny oddział | `ActivationStarted`, ewentualny istniejący `StatusRemoved`, `InterruptWindowOpened` | `BEFORE_ACTION`, okno 1, priorytet od snapshotu inicjatywy |
| `BEFORE_ACTION` | `interrupt`; tylko caller mapujący się na `priority_player` | `ActivationInterruptTriggered` + komplet outcome eventów handlera | to samo okno i priorytet; wersje +1 |
| `BEFORE_ACTION` | pierwszy `pass`; tylko bieżący priorytet | `InterruptPriorityPassed` | okno otwarte, priorytet drugiego gracza, HTTP 202 |
| `BEFORE_ACTION` | drugi `pass` | `InterruptPriorityPassed`, `InterruptWindowClosed` | `ACTION_READY`, HTTP 200 |
| `ACTION_READY` | istniejący `POST /actions`; owner wybranego oddziału | istniejące outcome eventy akcji i Przegrupowania, potem `ActivationActionCommitted` | po pierwszej akcji `AWAITING_CONTINUATION`, po drugiej `AWAITING_FINALIZATION`; HTTP 202 |
| `AWAITING_CONTINUATION` | `continue`; owner wybranego oddziału | `ActivationContinuationChosen(continue=true)`, `InterruptWindowOpened` | `BEFORE_ACTION`, okno 2; HTTP 202 |
| `AWAITING_CONTINUATION` | `finalize`; owner wybranego oddziału | `ActivationContinuationChosen(continue=false)`, recovery outcomes, istniejące status/override outcomes, `ActivationFinalized`, `InitiativeTransferred`, `ActivePlayerChanged` | `IDLE`, HTTP 200 |
| `AWAITING_FINALIZATION` | `finalize`; owner wybranego oddziału | recovery outcomes, istniejące status/override outcomes, `ActivationFinalized`, `InitiativeTransferred`, `ActivePlayerChanged` | `IDLE`, HTTP 200 |

Interrupt nie zeruje passów i nie oddaje priorytetu: gracz może wykonać zero lub
wiele przerwań w wybranej kolejności, a dopiero jawny pass przekazuje możliwość
drugiemu graczowi ([pkt 12.c][R12]). Drugi gracz nie przekazuje jej z powrotem;
jego pass zamyka dwugraczowe okno.

`finalize` zawsze zawiera jawny wybór recovery, także pusty. Serwer nie wybiera
zdolności Leczenia za gracza ([pkt 21.a][R21]). Dopóki source-correct recovery
handlers nie istnieją, jedynym poprawnym payloadem jest pusta lista.

### 4. Eventy, reducery i replay

Nowe eventy v1 payload (ich nazwa jest nowa, więc nie zmienia starych tagów):

- `ActivationStarted`
- `InterruptWindowOpened`
- `ActivationInterruptTriggered`
- `InterruptPriorityPassed`
- `InterruptWindowClosed`
- `ActivationActionCommitted`
- `ActivationContinuationChosen`
- `ActivationFinalized`
- `InitiativeTransferred`
- `ActivePlayerChanged`

Każdy event niesie `activation_id`; eventy okna także `window_ordinal` i wersję
po przejściu. `ActivationActionCommitted` niesie kanoniczny `action_type`, dzięki
czemu reducer odtwarza `action_count/action_types`. `ActivationFinalized` czyści
`activation`; `InitiativeTransferred` zmienia wyłącznie top-level
`initiative_player`, a `ActivePlayerChanged` wyłącznie `active_player`. Stary
`InitiativePassed` pozostaje dekodowalnym eventem legacy i nie jest emitowany w
protokole v2.

Istniejące outcome eventy (atak, statusy, override'y, limity raz/rundę) pozostają
SSOT skutków mechanicznych. Nowe eventy opisują tylko protokół i nie duplikują
obrażeń ani statusów. Każdy nowy typ ma reducer produkcyjny; gate wymaga:

```text
apply_events(v2_initial_state, complete_event_tail) == live_v2_checkpoint
```

po każdym możliwym punkcie zatrzymania: start, interrupt, pierwszy pass,
zamknięcie okna, pierwsza akcja, otwarcie drugiego okna i finalizacja. Ten sam
checkpoint po zamknięciu i ponownym otwarciu sesji musi dopuszczać dokładnie te
same następne operacje i zachować pozycję RNG.

## Wire / API

### Wspólny optimistic guard i odpowiedź

Każdy write wymaga ścisłego `expected_sequence >= 0`. Operacje w aktywacji
wymagają też `activation_id` i `expected_activation_version`; operacje okna
dodatkowo `expected_window_version`. Wszystkie wersje porównuje się z jednym
załadowanym checkpointem przed wykonaniem logiki.

Sukces nowych tras zwraca ten sam zamknięty envelope co `POST /actions`:

```json
{
  "battle_id": 7,
  "previous_sequence": 12,
  "new_sequence": 15,
  "state": {"schema": "szop.battle_state", "version": 2, "state": {}},
  "events": []
}
```

Nie zwraca RNG, tokenów, user IDs ani echo surowego body. Bieżący phase,
priorytet i wersje są w participant-scoped `state`.

### Start aktywacji

`POST /battles/{id}/activations`

```json
{
  "expected_sequence": 12,
  "selected_unit_id": 101
}
```

- **201 Created** — aktywacja i pierwsze okno zapisane.
- **409 Conflict** — nie `IDLE`, stale sequence albo race.
- **422 Unprocessable Entity** — oddział nie istnieje, jest pokonany,
  Aktywowany, należy do innej strony albo nie może być wybrany.

### Interrupt albo pass

`POST /battles/{id}/interrupts` pozostaje jedyną kanoniczną operacją
interrupt/pass. Body jest ścisłym discriminated union (`extra=forbid`):

```json
{
  "operation": "interrupt",
  "expected_sequence": 15,
  "activation_id": 13,
  "expected_activation_version": 1,
  "expected_window_version": 1,
  "source_unit_id": 205,
  "ability_slug": "rozkaz",
  "payload": {"target_id": 206, "ability": "nieustraszony", "granted": true}
}
```

albo:

```json
{
  "operation": "pass",
  "expected_sequence": 18,
  "activation_id": 13,
  "expected_activation_version": 2,
  "expected_window_version": 2
}
```

- **200 OK** — interrupt wykonany i priorytet pozostaje u caller-a albo drugi
  pass zamknął okno.
- **202 Accepted** — pierwszy pass zapisany, okno czeka na drugiego gracza.
- **409 Conflict** — brak otwartego okna, caller nie ma bieżącego priorytetu,
  stale sequence/version, inna aktywacja, nested attempt albo DB race.
- **403 Forbidden** — caller próbuje użyć source kontrolowanego wyłącznie przez
  drugiego ownera.
- **422 Unprocessable Entity** — nieznany/niewspierany slug, source z własnej
  strony nie ma aktywnego sluga, handler/cel/payload jest nielegalny albo
  przekroczono limit 64.

Pass nie przyjmuje `source_unit_id`, `ability_slug` ani `payload`; serwer nie
pozwala caller-owi wskazać gracza, za którego pass ma być wykonany.

### Akcja — kompatybilna migracja istniejącej trasy

`POST /battles/{id}/actions` nie znika. Body dostaje dwa opcjonalne pola:

```json
{
  "expected_sequence": 20,
  "activation_id": 13,
  "expected_activation_version": 4,
  "action": {"schema": "szop.action", "version": 1, "action_type": "defend", "payload": {"unit_id": 101}}
}
```

- Dla protocol v2 oba nowe pola są wymagane, stan musi być `ACTION_READY`, a
  `action.unit_id` musi być równy `selected_unit_id`. Sukces zapisuje akcję i
  Przegrupowanie, nie finalizuje aktywacji i zwraca **202 Accepted**.
- Brak guardów v2 lub nielegalna akcja daje **422**; poprawny, lecz stale guard
  albo niewłaściwa faza daje **409**.
- Dla protocol v1 pola są pomijane i zachowanie/status 200 pozostają dokładnie
  kontraktem ADR-0054.

### Continue albo finalize

`POST /battles/{id}/activations/{activation_id}/transitions` przyjmuje ścisły
union:

```json
{
  "operation": "continue",
  "expected_sequence": 24,
  "expected_activation_version": 5
}
```

albo:

```json
{
  "operation": "finalize",
  "expected_sequence": 24,
  "expected_activation_version": 5,
  "recovery": {
    "uses": [
      {"source_unit_id": 101, "ability_slug": "latanie", "payload": {"target_id": 101}}
    ]
  }
}
```

- `continue` jest dozwolone tylko po pierwszej akcji i otwiera drugie okno;
  zwraca **202 Accepted**.
- `finalize` po pierwszej akcji oznacza rezygnację z drugiej, a po drugiej jest
  jedynym następnym krokiem. Wykonuje recovery, wygaśnięcia, Aktywowany i zmianę
  gracza; zwraca **200 OK**.
- **409** oznacza stale sequence/version, złą fazę, inną aktywację lub race;
  **422** — nielegalne continue/recovery/payload.

### Wspólne statusy auth/no-oracle

- **401** — brak poprawnego uwierzytelnienia.
- **403** — znany participant/agent nie ma wymaganego scope albo próbuje podjąć
  decyzję za stronę, której nie kontroluje.
- **404** — battle missing i foreign są nierozróżnialne.
- **409** — legalnie zbudowany request nie pasuje do bieżącej wersji/phase lub
  przegrał CAS; odpowiedź może podać bezpieczny kod problemu, ale nie cudzy body.
- **422** — request dotyczy bieżącej fazy, lecz wybór domenowy jest nielegalny.

Protocol v2 używa jednego error envelope bez echo wejścia:

```json
{"detail": {"code": "stale_window"}}
```

Zamknięty zestaw kodów to: `unauthorized`, `forbidden`, `battle_not_found`,
`stale_sequence`, `stale_activation`, `stale_window`, `invalid_phase`,
`not_current_priority`, `battle_protocol_upgrade_required`, `write_conflict`,
`invalid_selection`, `activation_guard_required`, `illegal_action`,
`unsupported_interrupt`, `illegal_interrupt`, `interrupt_limit_reached` i
`illegal_recovery`. Kody 404 nie rozróżniają foreign/missing. V1 zachowuje
historyczny error contract ADR-0054.

## Persistence / concurrency

1. `Battle.activation_protocol_version` jest trwałym `1 | 2`. Istniejące wiersze
   dostają `1`; nowe sandboxy/invite'y wybierają v2 jawnie w wersjonowanym
   create contract. Wartość musi zgadzać się z wersją checkpointu.
2. Event log pozostaje kanonem, a activation/window żyją w checkpoint v2. Nie
   powstaje drugi mutable `current_activation` row ani kolumny duplikujące phase.
3. `expected_sequence` jest CAS-em całego strumienia. Każdy pass/interrupt/action
   emituje event, więc dwa równoległe requesty nie mogą obu zakończyć się
   sukcesem z tego samego head.
4. `UNIQUE(battle_id, sequence)` oraz `UNIQUE(battle_id, sequence_at)` pozostają
   ostatnią ochroną race. `expected_activation_version` i
   `expected_window_version` bronią przed logicznie stale requestem nawet wtedy,
   gdy klient pomyli identyfikator odpowiedzi.
5. Błąd walidacji, handlera, serializacji, INSERT/UPDATE, unique constraint albo
   commit powoduje rollback eventów, checkpointu, RNG i metadanych bitwy.
   Po rollbacku serwis może wyłącznie ponownie odczytać trwały head i zwrócić
   409; nie odtwarza części handlera.

## Auth / security

- Odczyt i write zaczynają się od participant/no-oracle lookup. Sesyjny user
  mapuje się na `p1_user_id`/`p2_user_id`; bearer mapuje agent ownera.
- `battle:act` obejmuje start/akcję/continue/finalize. Nowy least-privilege
  `battle:interrupt` obejmuje interrupt i pass. `HttpClient` potrzebuje dodatkowo
  `battle:read` tylko wtedy, gdy sam pobiera state.
- Start/akcja/continue/finalize należą do `controlling_player`. Interrupt/pass
  należą wyłącznie do `priority_player`. Source interruptu musi być żywy, należeć
  do tej strony i naprawdę posiadać `ability_slug` w `effective_passives`.
  Rejestracja handlera nie jest dowodem eligibility.
- Publiczny allowlist `READY_INTERRUPT_HANDLERS` jest osobny od wewnętrznego
  registry. Stub, handler eksperymentalny lub semantycznie niepełny slug zwraca
  422 bez wykonania.
- Caller nie może podać `player_id`, wykonać passu przeciwnika, zaakceptować jego
  recovery ani uruchomić nested interruptu. Również agent proposal nie może
  automatycznie wykonać tych decyzji po zgodzie innego ownera.
- Audit zapisuje route, battle id i wynik, ale nie bearer, pełny action/interrupt
  body, weapon payload ani wybory przeciwnika. Błędy nie echo-ują body i nie
  ujawniają, czy obcy source/target/ability istnieje.
- W same-owner sandbox ten sam uwierzytelniony owner może mapować się na obie
  strony, lecz musi wysłać oba passy jawnie. W bitwie dwóch ownerów każdy może
  wykonać tylko przejścia własnej strony. Serwer nigdy nie auto-passuje drugiej
  strony.

## Compatibility

### Checkpointy i historie v1

- Codec v2 zachowuje osobny, dokładny decoder v1. Read i replay obsługują oba
  formaty; encoder nie przepisuje v1 w locie.
- Historyczny v1 nie ma wiarygodnego `initiative_player` ani activation/window.
  `POST /activations` i `POST /interrupts` zwracają stabilne
  **409 `battle_protocol_upgrade_required`**. Nie wolno przyjąć
  `active_player` jako utraconej inicjatywy.
- V1 zachowuje dotychczasowe `POST /actions` i single-action `HttpClient`.
  Automatyczny upgrade jest zabroniony. Ewentualny przyszły backfill może
  podnieść tylko historię, dla której inicjatywa i pełny head są dowiedzione
  przez trwałe dane; w przeciwnym razie fail-closed pozostaje na stałe.

### Klienci i tryby własności

- Obecny `HttpClient.take_action` pozostaje poprawny dla battle protocol v1.
  Dla v2 nie może ukrywać startu, passów ani recovery w starej sygnaturze;
  dostanie typowany konflikt i skieruje caller-a do nowych metod.
- `GameClient`/`LocalClient` nie mogą utrzymywać dwóch różnych maszyn stanów.
  Local transport ma reużyć ten sam transition core, jedynie bez HTTP/DB.
- Metadata/create/invite contract ujawnia `activation_protocol_version`. W
  okresie migracji brak jawnego wyboru tworzy v1, więc zainstalowany stary klient
  nie dostaje po cichu nowej semantyki. Przejście domyślne na v2 wymaga osobnego
  versioned API decision po opublikowaniu klienta v2.
- Same-owner sandbox nie jest dowodem poprawności auth dla bitwy dwóch ownerów;
  real-transport parity musi obejmować oba warianty i handoff pomiędzy dwiema
  niezależnymi sesjami/tokenami.

## Handler readiness

| Handler | Publiczna gotowość | Prerequisite |
|---|---|---|
| Rozkaz(X) | Może być pierwszym bezpiecznym handlerem po fundamencie. | Osobny validator `rozkaz_tak`, source naprawdę ma Rozkaz, ally target, 12″, `granted` strict bool, limit raz/rundę i wygaśnięcie przy finalizacji ([pozycja 50][Z50]). |
| Klątwa(X) | Może wejść po tych samych gate'ach, ale jako osobny slice po Rozkazie. | Osobny validator `klatwa_tak`, enemy target, 12″ i limit raz/rundę; nie może reużyć `_rozkaz_capable_slugs` ([pozycja 45][Z45]). |
| Strażnik | Publicznie niewspierany, dopóki jest stubem. | Pełny interrupt-action primitive: legalny source/weapon/targets, rzeczywisty Ostrzał, następnie Wyczerpany, outcome eventy, replay/RNG i no-nested ([pozycja 31][Z31], [pkt 17][R17]). |
| Oznaczenie(X) | Publicznie niewspierane w obecnej semantyce. | Osobny attack-declaration/attack-scope prerequisite po zamknięciu ogólnego `BEFORE_ACTION`: cel ataku w 12″ od source, inny sojuszniczy atakujący, X z `oznaczenie_tak`, efekt tylko do `AttackResolved`, nie do końca aktywacji ([pozycja 49][Z49]). To rozszerzenie nadal użyje `POST /interrupts`, ale nie może udawać zwykłego activation override. |

Registry może zawierać niegotowe handlery do testów engine; publiczna allowlista
nie może ich eksportować.

## Performance / query gate

- Każde przejście ma O(1) zapytań niezależnie od liczby oddziałów: najwyżej pięć
  SELECT-ów (participant battle, event head/checkpoint/CAS), jeden batch INSERT
  eventów, jeden INSERT checkpointu i najwyżej jeden UPDATE metadanych. Stage B
  dodaje SQL-count regression tests dla passu, interruptu i race.
- Source/target/ability validation działa na jednym załadowanym `BattleState` i
  procesowo cache'owanym rulesecie. Żadnego SELECT per oddział, ability, target
  ani event; `get_eligible_interrupts` nie może powodować N+1.
- Hot concurrency path używa istniejących indeksów/constraintów:
  `battle_events(battle_id, sequence) UNIQUE`, indeksu `battle_id`,
  `battle_checkpoints(battle_id, sequence_at) UNIQUE` i PK `battles.id`.
  Migracja `activation_protocol_version` nie wymaga indeksu, bo nie jest filtrem
  listowym.
- Maksymalnie dwa ogólne okna na aktywację ([pkt 11.b.iv][R11]), 64 accepted
  interrupts i dwa passy na okno. Response event delta i payload handlera mają
  stałe limity rozmiaru/głębokości analogiczne do action codec.

## Consequences

### Pozytywne

- Restart, replay i równoległe requesty widzą ten sam protocol head.
- Kolejność decyzji nie ujawnia action intent przed przerwaniami.
- Każdy gracz podejmuje tylko swoje decyzje; same-owner sandbox nie maskuje
  wymagań prawdziwej gry dwóch ownerów.
- `POST /actions` i eventy mechaniczne są reużyte zamiast zastąpione drugim
  resolverem.
- Stub Strażnika i błędne Oznaczenie nie są promowane przez sam fakt rejestracji.

### Koszty

- Pełna aktywacja wymaga kilku małych requestów i trwałych eventów protokołu.
- Checkpoint schema v2, nowe eventy/reducery i model protocol version wymagają
  świadomej migracji wszystkich konstruktorów `BattleState` oraz klientów.
- Legacy v1 pozostaje osobnym, ograniczonym trybem do czasu jawnej migracji.
- Oznaczenie i Strażnik potrzebują osobnych prereq; nie domykają pierwszego
  API slice.

## Rejected alternatives

1. **Standalone interrupt mutujący bieżący state bez activation/window.**
   Odrzucone: brak dowodu timing/priority/pass, restart i race są
   nierozstrzygalne.
2. **Action intent przed przerwaniami.** Odrzucone: odwraca kolejność
   [pkt 11.b.i–ii][R11] i tworzy oracle wyboru aktywnego gracza.
3. **Caller lub serwer automatycznie wykonuje pass/recovery przeciwnika.**
   Odrzucone: łamie ownership decyzji i maskuje błędy w same-owner sandbox.
4. **Publiczne wystawienie Strażnika stub albo obecnego Oznaczenia.** Odrzucone:
   nie realizują skutków [pozycji 31][Z31] i [49][Z49].
5. **Sesyjna aktywacja tylko w pamięci procesu.** Odrzucone: restart gubi
   selected unit, action history i priority.
6. **Osobny mutable row `current_activation` jako drugi SSOT.** Odrzucone:
   checkpoint/event log już zapewniają atomowy, replayowalny stan; drugi head
   tworzyłby drift.

## Staged rollout / Definition of Done

Każdy etap kończy się osobno i nie uruchamia następnego automatycznie.

### A. Engine/state/event/codec activation-window foundation

- schema v2, frozen activation/window dataclasses, osobne `initiative_player`;
- nowe eventy i reducery, pure transition core, brak route i publicznych
  handlerów;
- v1 decoder bez auto-upgrade;
- testy wszystkich przejść, invalid phase/version, no-nested, dwa okna,
  replay bit-perfect i restart z każdego punktu zatrzymania;
- DoD: pełny pytest, golden/replay gate, call-site audit konstruktorów state.

### B. Persistence/model + pass-only API state machine

- `activation_protocol_version`, migracja istniejących wierszy do v1, jawne
  opt-in v2 w create/invite metadata;
- participant/no-oracle, scopes, trzy trasy, CAS/unique/rollback i wspólny
  envelope; `POST /actions` z kompatybilnymi guardami;
- `POST /interrupts` początkowo publicznie obsługuje tylko `pass`; opcjonalny
  następny mini-slice w tym etapie włącza wyłącznie source-correct Rozkaz, a
  Klątwę dopiero po osobnym validatorze;
- DoD: real DB restart/race dwóch sesji, SQL-count ceiling, v1 fail-closed,
  same-owner i two-owner auth matrix, security review.

### C. Source-correct handlers

- **C1 Strażnik:** pełny Ostrzał + Wyczerpany, RNG/replay, source/weapon/target,
  no-nested; własny commit i DoD.
- **C2 Oznaczenie:** najpierw attack-declaration/attack-scope events i
  wygaśnięcie po jednym ataku, potem handler; żadnego activation-scoped fallback;
  własny commit i DoD.
- Klątwa może być małym C0 po Rozkazie, jeśli nie weszła w B; każdy slug osobno.

### D. HttpClient real-transport parity

- typowane `start_activation`, `interrupt`, `pass_interrupt_priority`,
  `continue_activation`, `finalize_activation`; protocol/state v1+v2 decode;
- LocalClient i Protocol reużywają transition core; stare `take_action` jawnie
  ograniczone do v1;
- real FastAPI parity: dwie niezależne tożsamości, multiple interrupts jednego
  gracza, handoff, stale window race, restart, druga akcja i recovery empty;
- `agent_proposals`/MCP nie wykonują automatycznie cudzych passów; MCP pozostaje
  consent-only i dostaje nowe write tools dopiero w osobnym scope review.

### E. Packaging

- standalone install/export klienta v2, minimalne zależności, version metadata,
  smoke import bez ORM/serwera;
- wheel/editable install test oraz przykład negocjacji protocol v1/v2;
- dopiero po tym osobna decyzja może rozważyć zmianę domyślnej wersji create.

[R8]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 8.a"
[R10]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 10"
[R11]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 11.b.i–vi"
[R12]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 12.a–c"
[R14]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14.d.iv"
[R17]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 17"
[R20]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 20"
[R21]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 21"
[Z31]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 31 Strażnik"
[Z45]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 45 Klątwa(X)"
[Z49]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 49 Oznaczenie(X)"
[Z50]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 50 Rozkaz(X)"
