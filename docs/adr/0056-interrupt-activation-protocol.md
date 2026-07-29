# ADR-0056 — Trwały protokół aktywacji i okien przerwań

- **Status:** Accepted
- **Data:** 2026-07-19
- **Rozszerzenie:** B4.4d.C2a0, 2026-07-30 — frozen design trwałej
  deklaracji i zakresu jednego ataku; bez implementacji
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

Wersje są licznikami zaakceptowanych **operacji protokołu**, a nie liczby
eventów. Po zaakceptowanym `start` `activation.version = 1`; każda późniejsza
zaakceptowana operacja aktywacji zwiększa ją dokładnie o 1, nawet gdy atomowy
batch zawiera kilka eventów. Wszystkie eventy jednej operacji będą niosły tę
samą, końcową `activation_version`. `InterruptWindowOpened` ustawia
`window.version = 1` dla każdego nowego okna, także `ordinal = 2`; każde
zaakceptowane `interrupt` albo `pass` zwiększa ją dokładnie o 1, a eventy tej
operacji współdzielą końcową `window_version`. Otwarcie okna nie dodaje osobnej
inkrementacji `activation.version`: dla pierwszego okna mieści się w `start`, a
dla drugiego w `continue`. Dlatego pierwszy request po każdym otwarciu używa
`expected_window_version = 1`.

`active_player` pozostaje właścicielem wyboru oddziału/akcji. Nie służy już do
modelowania chwilowego priorytetu interruptów. `pending_interrupts` nie jest
SSOT protokołu. Runtime zachowuje je tymczasowo wyłącznie dla zgodności
checkpointów v1; schema v2 nie serializuje tego pola i wymaga pustej wartości
wewnętrznej. Usunięcie pola z runtime może nastąpić dopiero po migracji
wszystkich call sites.

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

### 5. B4.4d.C2a0 — trwała deklaracja i zakres jednego ataku

Ta sekcja jest normatywnym projektem przyszłego protocol/checkpoint v3.
Nie zmienia istniejącego runtime v2. Powodem nowej wersji jest zmiana znaczenia
zaakceptowanego `ShootAction`/`ChargeAction`: v2 rozstrzyga go od razu, natomiast
v3 najpierw utrwala deklarację i dopiero po osobnym attack-scope window pozwala
go rozstrzygnąć. Historyczne checkpointy i requesty v1/v2 nie są przepisywane
ani reinterpretowane.

Kanon wymaga, aby Oznaczenie wybrało X z `oznaczenie_tak: true`, dotyczyło
innego sojuszniczego atakującego, mierzyło edge-to-edge 12″ do wskazanego celu
ataku i trwało wyłącznie podczas tego jednego ataku ([konwencje][ZCONV],
[pozycja 49][Z49]). Ogólne `BEFORE_ACTION` kończy się przed wykonaniem akcji
([pkt 11.b.i–ii][R11]), a każde przerwanie musi zakończyć się przed następnym
([pkt 12.a–c][R12]). Dlatego attack scope jest osobnym, no-nested oknem
otwieranym dopiero po przyjęciu konkretnej deklaracji ataku; nie jest trzecim
ogólnym `BEFORE_ACTION`.

#### 5.1. Wersja i relacja do `ActivationState`

`Battle.activation_protocol_version = 3` oraz
`szop.battle_state/version = 3` są jawnym opt-inem. Decoder zachowuje osobne,
dokładne registry pól dla v1, v2 i v3. V3 rozszerza `ActivationState` o:

```text
attack: AttackState | null
```

oraz `ActivationPhase` o:

```text
ATTACK_WINDOW
ATTACK_RESOLUTION_READY
```

V1 i v2 nie kodują `attack` i nie znają nowych faz. V3 zachowuje wszystkie
dotychczasowe fazy oraz ich znaczenie dla `ManeuverAction`, `DefendAction` i
`SpecialAction`. Osiągalność jest konstrukcyjnym invariantem:

- `ATTACK_WINDOW` wymaga `activation.window = null`,
  `activation.attack != null` i `attack.window != null`;
- `ATTACK_RESOLUTION_READY` wymaga `activation.window = null`,
  `activation.attack != null` i `attack.window = null`;
- każda pozostała faza wymaga `activation.attack = null`;
- w jednym momencie istnieje najwyżej jedna aktywacja, jedno ogólne okno albo
  jeden attack scope i najwyżej jeden pending attack;
- `attack.ordinal == activation.action_count + 1` i wynosi `1 | 2`;
  `action_count/action_types` rosną dopiero po pełnym rozstrzygnięciu ataku.

`AttackState` jest frozen+slots i ma dokładnie:

```text
attack_id: int                         # sequence eventu AttackDeclared
version: int                           # licznik accepted attack operations
ordinal: 1 | 2
intent: ShootAttackIntent | ChargeAttackIntent
window: InterruptWindowState | null    # reuse immutable priority/pass shape
ability_overrides: tuple[AttackAbilityOverride, ...]
```

`ShootAttackIntent` przechowuje wyłącznie
`attacker_unit_id`, `target_unit_id` i `weapon_slug`.
`ChargeAttackIntent` przechowuje te same pola oraz strict
`counter_attack_declared: bool`, aby wznowić dokładną obecną semantykę
`ChargeAction`. Oba warianty są osobnymi immutable dataclassami, nie
`dict`-ami z polami opcjonalnymi. Nie zapisują nazwy, zasięgu, liczby ataków,
AP, jakości ani zdolności broni.

Przy deklaracji `weapon_slug` musi jednoznacznie wskazać profil w kanonicznym
`UnitBlob.ranged_weapons` dla Ostrzału albo `UnitBlob.melee_weapons` dla
Szarży. Powtórzone identyczne profile są jednym rozstrzygnięciem; brak profilu
lub ten sam slug z różnymi statystykami jest nielegalny. Pełny profil w
historycznym `szop.action/v1` jest wyłącznie nieufnym wire inputem: musi być
bitowo równy profilowi kanonicznemu, ale nie jest zapisywany ani używany do
rzutów. Przy późniejszym resolve serwer ponownie bierze profil wyłącznie z
inventory i konstruuje lokalny `ShootAction`/`ChargeAction`. Inventory pozostaje
jedynym SSOT statystyk.

Deklaracja waliduje strict shape, caller/attacker, bieżący `ACTION_READY`,
historię limitów akcji, dokładnie jeden obecnie reprezentowalny cel, żywy Front,
relację enemy oraz jednoznaczny canonical weapon reference. Pełna walidacja
mechaniczna i wszystkie rzuty są ponawiane dopiero podczas resolve na stanie
z attack-scoped X; deklaracja nie emituje obrażeń/statusów i nie dotyka RNG.
Obecne `ShootAction` i `ChargeAction` wspierają po jednym celu, mimo że kanon
opisuje do dwóch celów Ostrzału/Szarży ([pkt 14.c–d][R14A]); C2 nie rozszerza
modelu produktu.

#### 5.2. Maszyna stanów i właściciele decyzji

Gałąź v3 zastępuje wyłącznie przejście atakujących akcji z `ACTION_READY`:

```text
ACTION_READY
  -> declare ShootAction|ChargeAction
ATTACK_WINDOW (priority = activation.initiative_player)
  -> attack interrupt* -> pass/handoff -> attack interrupt* -> pass/close
ATTACK_RESOLUTION_READY
  -> resolve_attack
AWAITING_CONTINUATION | AWAITING_FINALIZATION
```

Nieatakujące akcje v3 nadal przechodzą atomowo z `ACTION_READY` do
`AWAITING_CONTINUATION` albo `AWAITING_FINALIZATION`, dokładnie jak v2.

Deklarację i resolve wykonuje `activation.controlling_player` z
`battle:act`. Attack interrupt/pass wykonuje wyłącznie bieżący
`attack.window.priority_player` z `battle:interrupt`. Priorytet zaczyna
`activation.initiative_player`, interrupt nie zeruje passów ani nie przekazuje
priorytetu, pierwszy pass przekazuje go drugiej stronie, a drugi zamyka okno,
tak samo jak w ogólnym oknie ([pkt 10][R10], [pkt 12.c][R12]).

Oznaczenie może wykonać tylko owner source. Source musi być żywy, na Froncie,
naprawdę mieć Oznaczenie, być sojusznikiem zadeklarowanego atakującego i być od
niego różny. Jedynym targetem pomiaru jest
`attack.intent.target_unit_id`; klient nie może podać zastępczego targetu.
Edge-to-edge gap source→cel ataku musi wynosić najwyżej 12″, a X musi być
pasywką z jawnym `oznaczenie_tak: true` ([pozycja 49][Z49]). Payload handlera
ma dokładnie `{"ability": <non-empty slug>}`; nie zawiera `target_id`,
`attacker_id`, `granted`, statystyk broni, playera ani sequence. Oznaczenie
zawsze nadaje X; nie dziedziczy `rozkaz_kierunek`.

Same-owner nadal wysyła oba passy jawnie, a serwis mapuje tę samą tożsamość na
stronę z trwałego priority. W two-owner tylko owner bieżącego priority może
wykonać pass/interrupt; ze względu na ally/source invariant Oznaczenie może
wykonać tylko strona atakującego, gdy otrzyma priorytet. Serwer nie auto-passuje
strony bez legalnego Oznaczenia.

Bounds są częścią modelu: jedno pending attack, jeden target i jeden weapon slug
na obecny action type, maksymalnie 64 zaakceptowane attack interrupts i
64 `AttackAbilityOverride` w jednym oknie, bez duplikatu tej samej pary
`(source_unit_id, ability_slug)`. Slugi mają limit 128 znaków, JSON zachowuje
istniejący limit głębokości 64, a całe atomowe resolve nie może przekroczyć
10 000 eventów (ten sam publiczny pułap bounded replay). Osiągnięcie limitu
interruptów blokuje następny interrupt jako 422, ale nie blokuje passu.

Accepted declaration zwiększa `activation.version` dokładnie o 1, ustawia
`attack.version = 1` i `attack.window.version = 1`; jawne open nie jest drugą
operacją ani drugą inkrementacją. Każdy accepted attack interrupt lub pass
zwiększa wszystkie trzy istniejące wersje dokładnie o 1, niezależnie od liczby
eventów outcome; closing pass i close event współdzielą te same wersje. Resolve
zwiększa `activation.version` i `attack.version` dokładnie o 1, a następnie
usuwa attack. Wszystkie nowe attack-protocol eventy jednego requestu niosą
jego końcowe wersje; istniejące outcome eventy zachowują własne payloady.
`expected_sequence` guarduje globalny head, `activation_id/version` aktywację,
`attack_id/version` deklarację, a `expected_window_version` konkretną pozycję
priority/passów.

#### 5.3. Eventy, reducery i exact replay

V3 dodaje zamknięte eventy protokołu:

- `AttackDeclared` — tworzy `AttackState`, przypina immutable intent i ustawia
  końcowe `activation_version`, `attack_version = 1`;
- `AttackInterruptWindowOpened` — jawnie potwierdza scope, ordinal,
  `window_version = 1` i początkowy priority;
- `AttackInterruptTriggered` — zwiększa raz activation/attack/window version
  i `interrupt_count`, ale nie opisuje mechanicznego outcome;
- `AttackInterruptPriorityPassed` — zapisuje handoff albo closing pass;
- `AttackInterruptWindowClosed` — usuwa wyłącznie `attack.window` i przechodzi
  do `ATTACK_RESOLUTION_READY`;
- `AttackAbilityOverrideApplied` — dodaje do bieżącego attack scope dokładnie
  `(source_unit_id, ability_slug)` dla zadeklarowanego atakującego;
- `AttackResolved` — po kompletnych outcome eventach usuwa cały `AttackState`
  i wyłącznie jego override'y.

Akceptowana deklaracja emituje kolejno `AttackDeclared`,
`AttackInterruptWindowOpened`. Akceptowane Oznaczenie emituje kolejno
`AttackInterruptTriggered`, istniejący kanoniczny
`InterruptTriggered(consumes_round_limit=true)` i
`AttackAbilityOverrideApplied`. Nie emituje `AbilityOverrideApplied`.
Pierwszy pass emituje jeden `AttackInterruptPriorityPassed`; closing pass
emituje `AttackInterruptPriorityPassed`, `AttackInterruptWindowClosed`.

Resolve emituje najpierw istniejące outcome eventy obrażeń/statusów, następnie
`AttackResolved`, a na końcu istniejący `ActivationActionCommitted` z
`action_type = shoot | charge`. Oba terminalne eventy jednej operacji niosą tę
samą końcową `activation_version`; `AttackResolved` niesie końcową
`attack_version`. `AttackResolved` przywraca na czas redukcji `ACTION_READY`,
a `ActivationActionCommitted` pozostaje jedynym reducerem zwiększającym
`action_count/action_types` i wybierającym
`AWAITING_CONTINUATION|AWAITING_FINALIZATION`.

Outcome eventy obrażeń, zabitych modeli i statusów pozostają SSOT. Reducery
attack protocol zmieniają tylko activation/attack/window lub
`used_interrupts_this_round`; nie rekonstruują wyników combat. Każdy accepted
request zapisuje ciągły event range. Po każdym pełnym batchu declaration,
interrupt, first pass, close i resolve obowiązuje:

```text
apply_events(initial_v3_state, complete_event_tail) == live_v3_checkpoint
```

Replay po `AttackResolved` nie ma attack override'u, lecz zachowuje niezależne
activation-scoped `UnitBlob.ability_overrides` Rozkazu/Klątwy. Ani
`AbilityOverridesCleared`, ani finalizacyjne czyszczenie aktywacji nie obsługuje
attack scope.

#### 5.4. Attack-scoped widok X

`AttackAbilityOverride` nie jest polem `UnitBlob`. Combat otrzymuje immutable
attack effect view związany z `attack_id` i `attacker_unit_id`; wspólny helper
`effective_attack_passives(blob, attack_state)` zwraca
`effective_passives(blob)` z dodanymi wyłącznie X bieżącego scope i tylko gdy
`blob.id == intent.attacker_unit_id`. Bazowe pasywki oraz activation-scoped
Rozkaz/Klątwa nadal są obliczane przez istniejący `effective_passives`.

W `ChargeAction` scope żyje do końca atomowego outcome całej akcji, ale X jest
widoczne tylko wtedy, gdy atakującym jest zadeklarowany
`intent.attacker_unit_id`; kontratakujący obrońca nie dziedziczy X. Scope jest
usuwany dopiero po wszystkich outcome eventach tej akcji, aby crash/replay nie
tworzył pół-ataku. `AttackResolved` usuwa wyłącznie `ActivationState.attack`;
nie może czyścić `UnitBlob.ability_overrides`, więc jeden atak nie usuwa
Rozkazu ani Klątwy.

#### 5.5. RNG, transakcja i failure semantics

Declaration, attack interrupt i pass nie wykonują rzutów i checkpointują
bitowo niezmieniony RNG. Resolve klonuje RNG z jednego spójnego checkpointu,
rozwiązuje kanonicznie odtworzony action na prywatnym klonie, waliduje ciągłość
outcome eventów i live/replay parity, a następnie stage'uje jeden guarded event
batch oraz jeden checkpoint state+returned RNG.

Każdy validation/domain/codec/handler/DB/unique/commit/race failure pozostawia
trwały event head, checkpoint i RNG bez zmian. Błąd resolve po częściowym
zużyciu prywatnego RNG pozostawia checkpoint w
`ATTACK_RESOLUTION_READY`, więc legalny retry z aktualnymi guardami daje ten
sam wynik. Nie istnieje trwały snapshot „atak w połowie rozstrzygania”.

#### 5.6. Wire/API i no-oracle migration

Nie powstaje nowa trasa ani scope. Protocol v3 używa istniejących:

- `POST /battles/{id}/actions` z obecnym body action deklaruje
  `ShootAction|ChargeAction` i zwraca **202** z pending `ATTACK_WINDOW`;
- ten sam request dla maneuver/defend/special nadal rozstrzyga akcję i zwraca
  **202**, jak v2;
- `POST /battles/{id}/interrupts` dostaje ścisłą gałąź
  `scope: "attack"` dla interrupt/pass;
- `POST /battles/{id}/actions` dostaje ścisłą gałąź
  `operation: "resolve_attack"` bez ponownego action body.

Attack interrupt/pass zawiera `expected_sequence`, `activation_id`,
`expected_activation_version`, `attack_id`, `expected_attack_version` i
`expected_window_version`. Interrupt dodaje `source_unit_id`,
`ability_slug="oznaczenie"` i exact payload `{"ability": X}`. Resolve zawiera
`expected_sequence`, `activation_id`, `expected_activation_version`,
`attack_id` i `expected_attack_version`. Guardy są strict int, nie bool.
Jawny `scope` zapobiega omyłkowemu skierowaniu attack requestu do ogólnego
`BEFORE_ACTION`; activation-scoped body bez `scope` zachowuje v2 wire.

Klient rozpoznaje pending scope wyłącznie z participant-scoped state v3:
`activation.phase`, `activation.attack.attack_id/version`,
`activation.attack.window` i wersji okna. Intent pojawia się w odpowiedzi
dopiero po accepted declaration w `ACTION_READY`; wcześniej nie istnieje w
event logu, checkpointcie, response ani audit. Closing pass zwraca **200** i
`ATTACK_RESOLUTION_READY`; resolve zwraca **202** oraz zwykły stan po
`ActivationActionCommitted`. Attack interrupt zwraca **200**, pierwszy pass
**202**, drugi pass **200**.

`HttpClient.commit_activation_action` pozostaje metodą deklaracji/commit:
dla ataku v3 caller musi sprawdzić zwrócony phase. C2c dodaje tylko jedną nową
metodę `resolve_activation_attack`; istniejące `interrupt` i
`pass_interrupt_priority` dostają addytywne attack guardy/scope bez GET,
retry ani cache. Protocol v1 i v2 zachowują dotychczasowy wire, statusy i
atomowe rozstrzyganie ataków; Oznaczenie pozostaje dla nich niewspierane.
Tworzenie/invite v3 jest jawne, więc stary klient nie dostaje tej semantyki
po cichu.

Nowe stabilne kody to `attack_guard_required`, `stale_attack`,
`attack_scope_required` i `illegal_attack_resolution`. Zachowane statusy:
401 auth, 403 scope/ownership, wspólne 404 missing/foreign, 409 stale
sequence/activation/attack/window, zła faza albo write race oraz 422 strict
shape lub nielegalna domena. Przed pierwszym I/O wolno sprawdzić tylko
source-independent exact shape, typy i bounds. Istnienie/ownership
attacker/source/target, inventory, X, range i phase są sprawdzane dopiero po
participant-scoped lookupie jednego checkpointu, aby preflight nie stał się
oracle obcej bitwy. Error response i body-blind audit nie echo-ują
raw intentu, weapon fields, X, source/target ani cudzych identyfikatorów;
participant-scoped success state po legalnej deklaracji zawiera wyłącznie
kanoniczny minimalny intent potrzebny do restartu. Publiczny
`READY_INTERRUPT_HANDLERS` pozostaje dokładnie
`rozkaz|klatwa|straznik` do C2c; activation scope nadal odrzuca
`oznaczenie` bez zapisu.

#### 5.7. Query/performance gate

Każda przyszła mutacja declaration, attack interrupt/pass i resolve ma zachować
obecny ceiling: 5 SELECT-ów w serwisie, 6 w pełnym request session i 7 dla
bearera. Liczba oddziałów, profili, source, X, targetów i eventów nie może
zwiększać liczby SELECT-ów. Jeden request zapisuje jeden guarded batch i jeden
checkpoint; nie ma osobnego attack row ani SELECT/INSERT per override/event.

Participant battle, event head i checkpoint są ładowane istniejącym O(1)
seamem. Intent, source, target i inventory są rozwiązywane z jednego frozen
`BattleState`; katalog `oznaczenie_tak` jest immutable i procesowo cache'owany.
CPU może liniowo przeskanować już załadowane bloby/inventory, ale nie wykonuje
I/O. C2c musi mierzyć pełne listy SELECT dla declaration, first/closing pass,
Oznaczenia i resolve w małym oraz dużym stanie, a nie tylko ich liczbę.

#### 5.8. Call-site impact audit

| Aktualny call site | Zamrożony wpływ przyszłej migracji |
|---|---|
| `state.py` / `state_codec.py` | C2a1 dodaje v3-only immutable attack types, fazy, exact registry i reachable snapshots; v1/v2 payloady pozostają byte-for-byte kontraktem. |
| `events.py` / `reducers.py` / `apply_events` | C2a2 dodaje siedem attack eventów i reducery; outcome reducery pozostają SSOT, registry kompletności i complete-tail parity obejmują każdy restart head. |
| `activation_protocol.commit_activation_action` | W v3 dispatchuje nieatakujące akcje do istniejącego pathu, a ataki do declaration; osobny pure resolve reużywa `_validated_action_outcomes` i kończy istniejącym `ActivationActionCommitted`. V2 path pozostaje bez zmian. |
| `actions.py` / `action_codec.py` | Publiczny `szop.action/v1` i limity historii pozostają; server canonicalizuje minimalny attack intent i nigdy nie persystuje client weapon stats. |
| `interrupts.py` / combat / `effective_passives` | Legacy `_oznaczenie_handler` nie jest reużywany. C2b dodaje osobny `oznaczenie_tak`, exact handler i attack effect view; `UnitBlob.ability_overrides` oraz `AbilityOverridesCleared` nie obsługują tego scope. |
| `battle_activations.py` | C2c rozdziela action declaration/resolve i activation/attack interrupt scope, ale zachowuje participant lookup, ownership, optimistic head, prywatny RNG, guarded batch i checkpoint SSOT. |
| `battle_actions.py` | Historyczny v1 `prepare/stage_battle_action` nie zmienia się. |
| `routers/battles.py` | Te same `/actions` i `/interrupts`, addytywne strict uniony v3, te same scope'y, commit/rollback, envelope, no-oracle i body-blind audit. |
| `szop_client/http.py` | Decoder przyjmuje state v3, istniejące mutation methods zachowują one-POST; dochodzi tylko `resolve_activation_attack`. Legacy `take_action` i v1/v2 pozostają. |
| Testy state/codec/event/protocol/service/transport/client | C2a1 rozszerza checkpoint golden; C2a2 restart/replay/RNG i exact ordering; C2b source/other-ally/12″/tag/one-attack/Charge-counterattack; C2c strict wire, auth/no-oracle/audit, same-owner/two-bearer, stale/race/rollback oraz pełne listy 5/6/7 SELECT. Istniejące testy v1/v2 są obowiązkową regresją. |
| `LocalClient`, `GameClient`, MCP/UI i proposals | Poza C2; nie dostają automatycznego passu/resolve ani nowego write surface w tych slice'ach. |

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

1. `Battle.activation_protocol_version` jest obecnie trwałym `1 | 2`.
   Istniejące wiersze dostają `1`; nowe sandboxy/invite'y wybierają v2 jawnie
   w wersjonowanym create contract. C2c rozszerzy constraint do `1 | 2 | 3`
   wyłącznie dla jawnego opt-inu z sekcji 5. Wartość zawsze musi zgadzać się
   z wersją checkpointu.
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
| Rozkaz(X) | Public-ready w pure engine i trwałym transporcie v2 od B4.4b.7/B4.4c.9. | Osobny validator `rozkaz_tak` + `rozkaz_kierunek`, source naprawdę ma Rozkaz, ally target, 12″, `granted` strict bool zgodny z kierunkiem, limit raz/rundę i wygaśnięcie przy finalizacji ([konwencje][ZCONV], [pozycja 50][Z50]). |
| Klątwa(X) | Public-ready od B4.4d.C0; reużywa istniejący transport v2 i klienta. | Osobny validator `klatwa_tak`, pięć jawnych pasywek (`delikatny`, `instynkt`, `nieruchomy`, `niezgrabny`, `wolny`), enemy target, 12″, oba kierunki strict bool, limit raz/rundę i wygaśnięcie przy finalizacji; nie reużywa `_rozkaz_capable_slugs` ([pozycja 45][Z45]). |
| Strażnik | Public-ready od B4.4d.C1c przez istniejący activation protocol v2, durable service, FastAPI i `HttpClient.interrupt`. | Exact plan zawiera tylko `assignments[{weapon_slug,target_id}]`; private C1b rozwiązuje canonical inventory, legalny source/weapon/1–2 targets, pełny multi-profile Ostrzał z per-target pools, następnie Wyczerpany, bounded eventy, RNG/replay i no-nested. C1c dodaje strict preflight przed I/O, bezpośredni dispatch omijający legacy stub, atomowy event+RNG checkpoint, real-transport/auth/race/rollback/query gates i allowlistę dokładnie `rozkaz|klatwa|straznik` ([pozycja 31][Z31], [pkt 14.c][R14S], [pkt 17][R17], [pkt 22.a][R22A]). |
| Oznaczenie(X) | C2a0 design DONE; implementacja i publikacja pozostają OPEN. | Protocol/checkpoint v3 z sekcji 5: deklaracja dopiero po zamknięciu ogólnego `BEFORE_ACTION`, osobny attack scope, cel ataku w 12″ od source, inny sojuszniczy atakujący, X z `oznaczenie_tak`, effect view tylko dla zadeklarowanego atakującego i usunięcie przez `AttackResolved` ([pozycja 49][Z49]). Przyszły handler użyje istniejącego `POST /interrupts`, ale nie `UnitBlob.ability_overrides`. |

Registry może zawierać niegotowe handlery do testów engine; publiczna allowlista
nie może ich eksportować.

Drift zamknięty w B4.4b.7: wcześniejszy kontrakt ADR wymagał tylko strict bool
`granted`, lecz kanoniczne konwencje wiążą `true` z kierunkiem `"+"` (nadanie)
i `false` z `"−"` (odebranie). Adapter waliduje tę zgodność fail-closed; wpis
rulesetu bez obu kanonicznych tagów nie jest legalnym X.

## Performance / query gate

- Każde przejście ma O(1) zapytań niezależnie od liczby oddziałów: najwyżej pięć
  SELECT-ów (participant battle, event head/checkpoint/CAS), jeden batch INSERT
  eventów, jeden INSERT checkpointu i najwyżej jeden UPDATE metadanych. Stage B
  dodaje SQL-count regression tests dla passu, interruptu i race.
- Source/target/ability validation działa na jednym załadowanym `BattleState` i
  procesowo cache'owanym rulesecie. Żadnego SELECT per oddział, ability, target
  ani event; `get_eligible_interrupts` nie może powodować N+1.
- B4.4d.C0 zamraża pomiar Klątwy równy Rozkazowi: 5 SELECT-ów w serwisie,
  6 w pełnym request session i 7 dla bearera.
- B4.4d.C1a nie dodaje SQL: prywatny klon RNG jest pure, a durable interrupt
  nadal zapisuje jeden guarded event batch i jeden checkpoint przy pułapach
  5/6/7 SELECT-ów dla service/session/bearer.
- B4.4d.C1b nie ma I/O ani produkcyjnego durable call site'u. Pure validator
  skanuje już załadowane frozen bloby/inventory, combat wykonuje tylko CPU/RNG,
  a C1c reużywa ten fundament bez zapytań per assignment/profile/target/event.
- B4.4d.C1c mierzy pełne listy SELECT identyczne z Rozkazem/Klątwą: 5 w
  serwisie, 6 w pełnym request session i 7 dla bearera, również dla dużego
  stanu. Jeden request zapisuje jeden guarded event batch i jeden checkpoint
  state+returned RNG; `HttpClient` wykonuje jeden POST bez GET/retry/cache.
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
- C2a0 zamraża prerequisite Oznaczenia, ale model/codec, lifecycle, handler i
  transport pozostają osobnymi, niezaimplementowanymi slice'ami.

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
7. **Zmiana semantyki istniejącego protocol/checkpoint v2 w miejscu.**
   Odrzucone: obecny klient zakłada, że accepted attack jest już rozstrzygnięty,
   a exact codec v2 nie ma attack state. Jawny v3 zachowuje v1/v2 i zapobiega
   cichej zmianie zachowania.
8. **Oznaczenie przez `UnitBlob.ability_overrides` i
   `AbilityOverridesCleared`.** Odrzucone: scope aktywacji przeżywa jeden atak,
   a wspólne czyszczenie mogłoby usunąć niezależny Rozkaz/Klątwę. Attack state
   i `AttackResolved` mają dokładną własność lifecycle.

## Staged rollout / Definition of Done

Każdy etap kończy się osobno i nie uruchamia następnego automatycznie.

### A. Engine/state/event/codec activation-window foundation — IN PROGRESS

- **B4.4b.1 DONE 2026-07-21:** frozen `ActivationState` /
  `InterruptWindowState` i enum faz, osobne nullable `initiative_player` w
  runtime, konstrukcyjna walidacja osiągalnych snapshotów oraz jawny codec
  `BattleState` v2. No-arg encoder nadal emituje dokładny v1; v2 jest wybierany
  wyłącznie przez keyword `version=2`, nie zawiera `pending_interrupts` i nie
  wymyśla inicjatywy dla v1. Golden obejmuje v1, IDLE i wszystkie trwałe fazy
  v2. Żaden istniejący call site persistence/router/client nie został
  przełączony.
- **B4.4b.2 DONE 2026-07-27:** dziesięć nowych frozen+slots eventów protokołu
  ma ścisły payload v1, kompatybilną rejestrację obok historycznych tagów oraz
  produkcyjny reducer. `ActivationActionCommitted.action_type` reużywa
  kanoniczny discriminator Action. Ręcznie zbudowany tail odtwarza checkpointy
  v2 po starcie, accepted interrupt, obu passach/zamknięciu, pierwszej akcji,
  otwarciu okna 2, drugiej akcji i finalizacji/transferze. Istniejące outcome
  events pozostają jedynym SSOT ran, statusów, RNG, override'ów i limitów
  raz/rundę.
- **B4.4b.3 DONE 2026-07-27:** mały pure control-plane core implementuje
  `start_activation`, jawny `pass_interrupt_priority` oraz
  `continue_activation` bez mechaniki, RNG i I/O. Każda operacja emituje
  istniejące eventy B4.4b.2 i wyprowadza live state wyłącznie przez
  `apply_events`; v1 bez trwałej inicjatywy failuje bez auto-upgrade. Gate
  obejmuje atomowe batch'e, oba passy każdego okna, zachowanie accepted
  interrupt count, replay equality, checkpoint-v2 restart parity oraz pełną
  sekwencję do zamknięcia drugiego okna z ręcznie wstawionym
  `ActivationActionCommitted`.
- **B4.4b.4 DONE 2026-07-27:** pure `trigger_activation_interrupt` przyjmuje
  jawne guardy i wstrzyknięty leaf outcome executor. Source musi być żywy, na
  Froncie, należeć do bieżącego priority i posiadać slug w
  `effective_passives`; registry nie jest dowodem eligibility. Core emituje
  dokładnie jeden `ActivationInterruptTriggered`, po nim najwyżej 64 istniejące
  outcome events z ciągłą sekwencją i dokładnie jednym kanonicznym
  `InterruptTriggered`. Eventy protokołu w outcome są zakazane; nie ma
  mutable/reentrancy guarda. Stan executora musi być równy replayowi outcome
  events, a zwracany stan pochodzi wyłącznie z reducerów całego batcha.
  Accepted interrupt zachowuje priority i wcześniejsze passy, zwiększa wersje
  i `interrupt_count` dokładnie raz oraz failuje przed executorem przy limicie
  64 accepted interruptów w oknie. Codec-v2 restart daje identyczne payloady,
  state i `next_sequence`.
- **B4.4b.5 DONE 2026-07-27:** pure `commit_activation_action` akceptuje tylko
  bieżącą aktywację v2 w `ACTION_READY`, jej controlling playera i action
  wybranego oddziału. Wąski adapter reużywa walidację resolvera oraz
  `_apply_single_action`; outcome events muszą być ciągłe, bez eventów
  protokołu i odtwarzać dokładnie live state. Następnie bridge emituje
  `ActivationActionCommitted` z kanonicznym discriminatorem. Durable
  `action_types` jest jedyną historią limitu dwóch akcji ([pkt 11.b.iv][R11])
  oraz powtórnego Ostrzału ([pkt 14.c.v][R14C]) i Szarży
  ([pkt 14.d.vi][R14D]). Mechanika działa na kopii checkpointu
  `DeterministicDice`;
  błąd nie przesuwa RNG wejściowego, a sukces zwraca zaawansowaną kopię do
  checkpointu. Pierwsza/druga akcja kończy odpowiednio w
  `AWAITING_CONTINUATION`/`AWAITING_FINALIZATION`, bez finalizacji, transferu
  inicjatywy, statusu Aktywowany i czyszczenia override'ów.
- **B4.4b.6 DONE 2026-07-28:** pure `finalize_activation` akceptuje wyłącznie
  bieżącą aktywację v2 w `AWAITING_CONTINUATION` po jednej akcji albo
  `AWAITING_FINALIZATION` po dwóch, zgodne guardy i controlling playera.
  Pierwszy wariant emituje najpierw
  `ActivationContinuationChosen(continue_activation=False)`. Recovery pozostaje
  jawną decyzją gracza ([pkt 21.a][R21]); bez source-correct handlerów jedynym
  legalnym wyborem jest dokładnie pusta krotka, a każdy inny wybór failuje przed
  leafem. Wąski recovery outcome seam musi być dokładnym no-opem; core następnie
  reużywa `_finalize_activation` jako SSOT statusu Aktywowany, safety resetu i
  `AbilityOverridesCleared`, po czym emituje
  `ActivationFinalized`, `InitiativeTransferred` ze snapshotu inicjatywy oraz
  `ActivePlayerChanged`. Batch jest ciągły, nie dopuszcza zagnieżdżonych eventów
  protokołu, wymaga live/replay parity i kończy z `activation=None`. Codec-v2
  restart oraz pełny tail jednej i dwóch akcji odtwarzają identyczny stan.
- **B4.4b.7 DONE 2026-07-28:** immutable `READY_INTERRUPT_HANDLERS` jest osobna
  od registry i zawiera wyłącznie `rozkaz`. Built-in executor o sygnaturze
  `ActivationInterruptOutcomeExecutor` odtwarza `BEFORE_ACTION`, source i
  aktywowany oddział z trwałego stanu, używa wewnętrznej sekwencji i deleguje
  outcome do istniejącego handlera. Ścisły Rozkaz odrzuca coercion, extra pola,
  klientowe `sequence`, niegotowe slugi, nielegalne source/target/X/kierunek i
  drugie użycie w rundzie przed częściowym outcome; success zachowuje
  priority/passy, replay/checkpoint-v2 restart parity i wygaśnięcie przy
  finalizacji ([konwencje][ZCONV], [pozycja 50][Z50], [pkt 11.b.i–vi][R11],
  [pkt 12.a–c][R12]).
- **B4.4c.1 DONE 2026-07-28:** `Battle.activation_protocol_version` ma
  nie-nullowalny default i constraint `1|2`, a idempotentna migracja SQLite
  oznacza istniejące wiersze v1 bez przepisywania historii. `save_checkpoint`
  i `stage_battle_creation` domyślnie zachowują dokładny v1; jawny wewnętrzny
  opt-in v2 zapisuje zgodny checkpoint z inicjatywą i bez aktywacji. Publiczne
  schemas/create/invite/action oraz ich domyślne call sites pozostają
  niezmienione.
- **B4.4c.2 DONE 2026-07-28:** transakcyjnie neutralny
  `stage_battle_activation_start` obsługuje wyłącznie participant-scoped trwały
  start v2. Z jednego bieżącego headu weryfikuje ownera/aktywną stronę,
  `expected_sequence` i spójny checkpoint state+RNG, deleguje wybór oddziału do
  pure `start_activation`, a następnie przez istniejące persistence SSOT
  stage'uje jeden ciągły batch eventów i jeden checkpoint v2 bez przesunięcia
  RNG. Caller zarządza transakcją. Restart/race/rollback/no-oracle i same-owner
  oraz two-owner matrix są pokryte; sukces ma stałe 5 SELECT-ów bez N+1.
  Publiczny transport, schema, scope'y i pozostałe przejścia nie weszły w ten
  slice.
- **B4.4c.3 DONE 2026-07-28:** `stage_battle_activation_pass` z jednego
  participant-scoped headu v2 wykonuje dokładnie jeden jawny pass bieżącego
  `priority_player`. Strict input, status, sequence, checkpoint state+RNG oraz
  activation/window guardy są sprawdzane przed pure `pass_interrupt_priority`;
  same-owner mapuje stronę z trwałego priorytetu, a two-owner z ownerów bitwy.
  Dokładny event delta handoffu albo close jest zapisywany ciągłym guarded
  batchem wraz z jednym checkpointem v2 i bitowo niezmienionym RNG. Pierwszy
  pass i drugi osobny pass zachowują restart/replay parity zgodnie z
  [pkt 10][R10] i [pkt 12.a–c][R12]; v1, stale/race/rollback/no-oracle oraz
  guard/phase failures są atomowe, a sukces ma stałe 5 SELECT-ów bez N+1.
  Transport, publiczne schema/scope'y, accepted interrupt i pozostałe przejścia
  nie weszły w ten slice.
- **B4.4c.4 DONE 2026-07-28:** `stage_battle_activation_action` z jednego
  participant-scoped headu v2 stage'uje dokładnie jedną akcję w `ACTION_READY`.
  Strict `action_from_json` / `action_to_json` pozostają wire SSOT, durable
  `activation.controlling_player` wyznacza caller_player także dla same-owner, a
  pure `commit_activation_action` pozostaje SSOT fazy, activation guardów,
  legalności/outcome oraz RNG zgodnie z [pkt 11.b.ii–iv][R11A] i
  [pkt 14][R14A]. Dokładny ciągły event delta i jeden checkpoint v2 ze zwróconym
  RNG są stage'owane bez commit/rollback; wynik niesie canonical action, state,
  eventy, dice i previous/new sequence. Pierwsza oraz osiągalna druga akcja
  zachowują restart/replay i future RNG. Strict input, v1, auth/no-oracle,
  stale/checkpoint/phase, race/rollback oraz same-owner/two-owner są pokryte,
  a sukces ma stałe 5 SELECT-ów bez N+1. Transport, publiczne schema/scope'y,
  wspólny envelope, finalize i recovery nie weszły w ten slice.
- **B4.4c.5 DONE 2026-07-28:** `stage_battle_activation_continue` z jednego
  participant-scoped headu v2 stage'uje wyłącznie jawną kontynuację w
  `AWAITING_CONTINUATION`. Durable `activation.controlling_player` wyznacza
  caller_player także dla same-owner, a pure `continue_activation` pozostaje
  SSOT fazy/action_count, activation guardów i wersji, snapshotu inicjatywy,
  priorytetu oraz dokładnego delta
  `ActivationContinuationChosen(continue_activation=True)` +
  `InterruptWindowOpened(ordinal=2)` zgodnie z [pkt 10][R10],
  [pkt 11.b.i–iv][R11C] i [pkt 12.a–c][R12]. Jeden guarded event batch oraz
  jeden checkpoint v2 zachowują bitowo niezmieniony RNG bez commit/rollback.
  Restart/replay przez dwa istniejące pass service calls i istniejącą action
  service dochodzi do `AWAITING_FINALIZATION`. Strict input, v1,
  status/phase/action-count, auth/no-oracle, stale/coherence, race/rollback,
  same-owner/two-owner i stałe 5 SELECT-ów bez N+1 są pokryte. Nie dodano
  produkcyjnego call site, `continue=False`, finalizacji ani transportu.
- **B4.4c.6 DONE 2026-07-28:** `stage_battle_activation_finalize` z jednego
  participant-scoped trwałego headu v2 stage'uje legalną finalizację po jednej
  albo dwóch akcjach. Strict `recovery_uses` dopuszcza wyłącznie dokładnie `()`,
  durable `activation.controlling_player` wyznacza caller_player także dla
  same-owner, a pure `finalize_activation` pozostaje SSOT fazy/action_count,
  jawnego `continue=False` po jednej akcji, recovery seam, legacy outcome,
  statusu Aktywowany, safety resetu, wygaśnięcia override'ów oraz transferu
  inicjatywy/active playera zgodnie z [pkt 10][R10], [pkt 11.b.iv–vi][R11],
  [pkt 21][R21] i [pkt 22.d][R22]. Dokładny ciągły delta trafia przez jeden
  guarded event batch do jednego checkpointu v2 z bitowo niezmienionym RNG, bez
  commit/rollback w serwisie. Oba warianty zachowują restart/replay parity i
  dopuszczają kolejny legalny start po commicie. Strict input, v1,
  status/phase/action-count, auth/no-oracle, stale/coherence, race/rollback,
  same-owner/two-owner i stałe 5 SELECT-ów bez N+1 są pokryte. Nie dodano
  produkcyjnego call site, niepustych recovery handlerów ani transportu.
- **B4.4c.7 DONE 2026-07-28:** `stage_battle_activation_interrupt` przyjmuje z
  jednego participant-scoped headu v2 dokładnie jeden public-ready Rozkaz
  bieżącego `window.priority_player`, także w same-owner sandbox. Wspólny
  preflight `interrupts.py` reużywa allowlistę i strict Rozkaz payload SSOT,
  odrzucając coercion, extra/client `sequence`, niekanoniczny kierunek oraz
  nie-ready slug przed pierwszym I/O. Serwis deleguje source/target/range,
  kierunek i raz/rundę do `trigger_activation_interrupt` +
  `execute_ready_activation_interrupt_outcomes`, zgodnie z [pozycją 50][Z50],
  [pkt 11.b.i–vi][R11] i [pkt 12.a–c][R12]. Dokładny delta
  `ActivationInterruptTriggered`, kanonicznego `InterruptTriggered` i outcome
  jest jednym guarded batchem; jeden checkpoint v2 zachowuje RNG bit-identycznie,
  priority/passy nie dryfują, a wersje/licznik zmieniają się tylko przez pure
  core. Restart/replay, dalsze pass/action/finalize i wygaśnięcie override'u,
  v1/no-oracle/stale/race/rollback oraz stałe 5 SELECT-ów bez N+1 są pokryte.
  Nie dodano produkcyjnego call site, transportu, publicznych schema/scope'ów,
  envelope ani klienta; Klątwa/Oznaczenie/Strażnik pozostają nie-ready.
- **B4.4c.8 DONE 2026-07-29:** direct `POST /battles` oraz create invite mają
  addytywny, strict `activation_protocol_version: 1|2`, którego brak zachowuje
  dokładnie v1. Obie ścieżki delegują inicjalizację do `stage_battle_creation`
  i publikują wybraną wersję. `BattleInvite` przechowuje ją nie-nullowalnie z
  defaultem/checkiem `1|2`; idempotentna migracja SQLite oznacza istniejące
  zaproszenia jako v1. Accept nie przyjmuje wersji od klienta, lecz używa
  wyłącznie wartości zaproszenia, obejmuje ją CAS-em i przy retry/race rereadzie
  wymaga zgodnego `Battle`. `HttpClient` zachowuje stare body dla defaultu v1,
  emituje jawne v2 i ściśle dekoduje wersję w `BattleMetadata` oraz
  `BattleInviteMetadata`. Scope'y i route names są bez zmian; v2 ma zero
  dodatkowych SQL statements względem v1 dla direct create, invite create i
  accept.
- **B4.4c.9 DONE 2026-07-29:** publiczne FastAPI wystawia trzy zamrożone trasy
  start, interrupt/pass i continue/finalize oraz kompatybilne guardy v2 na
  `POST /actions`. Wszystkie sukcesy używają jednego zamkniętego envelope state
  v2 + exact event delta; router deleguje domenę i persistence wyłącznie do
  `stage_battle_activation_*`, a sam zarządza pojedynczym commit/rollback.
  Session participant i bearer ownera egzekwują `battle:act` albo
  `battle:interrupt`, controlling/priority ownership, no-oracle i body-blind
  audit. Rozkaz jest jedynym public-ready slugiem zgodnie z [pozycją 50][Z50] i
  [pkt 12.a–c][R12], recovery akceptuje wyłącznie dokładnie puste `uses`, a v1
  zachowuje historyczny action contract i nie jest auto-upgrade'owane. Realny
  transport same-owner/two-owner, restart po
  trwałych headach, stale/race/rollback, response exactness i SQL-count gate są
  pokryte; request session ma ceiling 6 SELECT-ów, bearer 7, a v1 action
  pozostaje przy 6.
- **B5.4 DONE 2026-07-29:** `HttpClient` publikuje frozen+slots
  `ActivationMutationResult` oraz jawne `start_activation`, `interrupt`,
  `pass_interrupt_priority`, `commit_activation_action`, `continue_activation`
  i `finalize_activation`. Każda metoda przyjmuje strict optimistic guardy,
  waliduje przed I/O i wykonuje dokładnie jeden POST bez GET/retry/cache.
  Wspólny fail-closed decoder wymaga exact battle id, previous sequence zgodnego
  z requestem, wersjonowanego state v2 oraz dodatniego ciągłego exact event
  delta kończącego się w new sequence. Zamknięty błąd klienta zachowuje HTTP
  status i `detail.code` bez body; malformed/unknown envelope failuje
  zamknięcie. Legacy `take_action` zachowuje wire v1, a na v2 zwraca typowany
  kierunek do jawnych metod. Realny FastAPI gate obejmuje same-owner, dwa
  niezależne bearery, handoff, interrupt, stale window/sequence, brak drugiego
  zwycięzcy, restart z checkpointu, dwie akcje i puste recovery. Każda mutacja
  klienta ma jeden transport request; session flow potwierdza istniejący ceiling
  6 SELECT-ów per request.
- **B4.4d.C0 DONE 2026-07-29:** publiczny allowlist wynosi dokładnie
  `{"rozkaz", "klatwa"}`. Addytywny immutable `klatwa_tak` zamraża pięć
  source-correct X: `delikatny`, `instynkt`, `nieruchomy`, `niezgrabny`,
  `wolny`. Klątwa ma osobny exact payload `{target_id, ability, granted}` bez
  kierunku Rozkazu; oba boole są legalne, a brak jawnego true, false,
  nie-pasywka i nieznany slug failują zamknięcie. Istniejący pure/durable/FastAPI
  flow egzekwuje żywy frontowy source z Klątwą, wrogi żywy frontowy target,
  edge-to-edge 12″, limit raz/rundę, replay/restart i wygaśnięcie przy
  finalizacji ([pozycja 45][Z45], [pkt 11.b.i–vi][R11], [pkt 12.a–c][R12]).
  Same-owner, two-owner, stale/race/rollback/no-oracle/scope/audit i realny
  `HttpClient.interrupt` są pokryte bez zmian API/DB/klienta; klient wykonuje
  jeden POST. Query gate pozostał równy Rozkazowi: 5 SELECT-ów w serwisie,
  6 session i 7 bearer.
- **B4.4d.C1a DONE 2026-07-29:** accepted-interrupt outcome executor otrzymuje
  prywatny klon `DeterministicDice`, a pure transition zwraca typowany
  state/events/next-sequence oraz ewentualnie zaawansowany RNG. Wszystkie
  błędy po częściowym zużyciu failują bez mutacji wejściowego state/RNG.
  Durable service checkpointuje zwrócony RNG atomowo z dokładnym event delta;
  rollback/race zachowują poprzednią pozycję. Rozkaz i Klątwa nie konsumują RNG
  i zachowują exact event/restart/future-roll parity. Publiczne wire, auth,
  statusy, schematy, allowlista `{"rozkaz", "klatwa"}` i pułapy 5/6/7 SELECT
  pozostają bez zmian. To fundament, nie implementacja Strażnika.
- **B4.4d.C1b DONE 2026-07-29:** prywatny frozen plan i strict decoder
  rozstrzygają profile wyłącznie z `source.ranged_weapons`; caller nie podaje
  statystyk. Pure activation-v2 outcome waliduje enemy activation, source
  ze Strażnikiem, Front/live/Wyczerpany, blokadę 2″, 1–2 cele, zasięg, LoS
  oraz jawnie obsługiwane wyjątki, a nieobsługiwane mechaniki odrzuca.
  Wspólny combat SSOT rozpatruje wszystkie profile przed per-target alokacją
  pul ([pkt 14.c][R14S], [pkt 17][R17]); outcome emituje jeden kanoniczny
  `InterruptTriggered(straznik)`, komplet eventów Ostrzału i dopiero potem
  `StatusAdded(Wyczerpany)` ([pozycja 31][Z31], [pkt 22.a][R22A]).
  Sukces przesuwa wyłącznie returned RNG o realne rzuty, a executor/replay/
  protocol failure po częściowym zużyciu nie mutuje wejść. C1b nie publikuje
  sluga samodzielnie; trwałe i publiczne podpięcie zamyka C1c.
- **B4.4d.C1c DONE 2026-07-29:** allowlista wynosi dokładnie
  `{"rozkaz", "klatwa", "straznik"}`. Handler-specific strict preflight
  akceptuje tylko exact `assignments[{weapon_slug,target_id}]` bez statystyk,
  client sequence, coercion lub extra pól i z limitami C1b, zanim service
  wykona I/O. Publiczny executor omija legacy stub i deleguje bezpośrednio do
  private C1b z klonem RNG. Istniejący durable service zapisuje jeden ciągły
  delta `ActivationInterruptTriggered` + dokładnie jeden
  `InterruptTriggered(straznik)` + pełny Ostrzał/alokację + końcowy
  `StatusAdded(Wyczerpany)` wraz ze zwróconym RNG w jednym checkpointcie.
  Istniejąca trasa, status 200, scope `battle:interrupt`, state-v2/exact-event
  envelope, no-oracle i body-blind audit są zachowane; `HttpClient.interrupt`
  wykonuje jeden POST. Same-owner i dwa niezależne bearery, replay/restart/
  finalize, auth, stale/duplicate/race oraz validation/domain/DB rollback są
  pokryte. Pełne listy SELECT są identyczne z Rozkazem/Klątwą: 5/6/7 dla
  service/session/bearer, bez N+1. Nie dodano trasy, scope'u, eventu/reducera,
  DB/schema, metody klienta ani zmian v1.
- **OPEN:** niepuste recovery handlery, `LocalClient`/`GameClient`/MCP oraz
  pakowanie pozostają osobnymi slice'ami; C2a0 design Oznaczenia jest DONE,
  a implementacyjne C2a1/C2a2/C2b/C2c pozostają OPEN.

### B. Persistence/model + activation API state machine — IN PROGRESS

- **B4.4c.1 DONE:** model, migracja istniejących wierszy do v1 i wewnętrzny
  spójny zapis początkowego checkpointu v1/v2;
- **B4.4c.2 DONE:** transactionally-neutral participant/no-oracle service dla
  startu v2, optimistic head, atomic event batch + checkpoint v2, restart/RNG,
  race/rollback i SQL ceiling;
- **B4.4c.3 DONE:** transactionally-neutral service dla jednego jawnego passu
  priority ownera, pure handoff/close, guarded event delta + jeden checkpoint
  v2, restart/RNG, same-owner/two-owner, race/rollback i SQL ceiling;
- **B4.4c.4 DONE:** transactionally-neutral service dla jednej akcji
  `ACTION_READY`, codec + pure action SSOT, guarded delta + jeden checkpoint z
  RNG transition, obie akcje, restart/replay, auth/race/rollback i SQL ceiling;
- **B4.4c.5 DONE:** transactionally-neutral service dla jawnego
  `continue_activation=True`, pure delta otwierający drugie okno, niezmienny RNG,
  restart/replay przez passy i drugą akcję, auth/race/rollback i SQL ceiling;
- **B4.4c.6 DONE:** transactionally-neutral service dla finalizacji po jednej
  albo dwóch akcjach z dokładnie pustym recovery, pure terminal delta,
  niezmiennym RNG, restart/replay, next-start, auth/race/rollback i SQL ceiling;
- **B4.4c.7 DONE:** transactionally-neutral service dla public-ready Rozkazu,
  strict preflight przed I/O, pure accepted-interrupt + built-in outcome SSOT,
  exact delta/checkpoint/RNG, restart/finalize, auth/race/rollback i SQL ceiling;
- **B4.4c.8 DONE:** jawny, domyślnie v1 opt-in direct/create-invite, trwała
  wersja invite, accept-only-from-invite, mismatch detection, ścisłe publiczne
  metadata/HttpClient oraz zerowa delta SQL;
- **B4.4c.9 DONE:** scope'y, trzy trasy, wspólny publiczny envelope,
  kompatybilne guardy `POST /actions`, publiczny pass/Rozkaz, real DB
  restart/race, SQL-count ceiling, v1 fail-closed i same-owner/two-owner auth
  matrix;
- niepuste recovery handlery pozostają osobnym etapem.

### C. Source-correct handlers

- **C0 Klątwa DONE 2026-07-29:** osobny immutable tag i validator, pięć
  source-correct X, enemy/12″/raz-rundę/finalize, publiczny allowlist
  `Rozkaz|Klątwa`, pełny pure/durable/FastAPI/HttpClient/replay/query gate;
  bez nowych eventów, API, DB ani kodu klienta.
- **C1a RNG-aware substrate DONE 2026-07-29:** prywatny RNG outcome,
  fail-closed izolacja i atomowy durable RNG checkpoint; bez publikacji sluga.
- **C1b private pure Strażnik foundation DONE 2026-07-29:** canonical-inventory
  plan/decoder, pełny multi-profile/multi-target Ostrzał, per-target pools,
  późniejszy Wyczerpany, bounded outcome i RNG/replay/no-nested gate
  ([pozycja 31][Z31], [pkt 14.c][R14S], [pkt 17][R17], [pkt 22.a][R22A]).
- **C1c durable/public Strażnik DONE 2026-07-29:** exact assignments payload,
  allowlista `Rozkaz|Klątwa|Strażnik`, bezpośredni private-C1b dispatch,
  atomowy event+RNG checkpoint, istniejąca trasa/scope/envelope i realny
  `HttpClient` one-POST; same-owner/two-bearer, auth/no-oracle/audit,
  race/rollback/replay/finalize oraz 5/6/7 SELECT bez N+1.
- **C1 Strażnik public-ready DONE 2026-07-29.**
- **C2a0 attack-declaration/attack-scope design DONE 2026-07-30:** sekcja 5
  zamraża jawny protocol/checkpoint v3, immutable minimal intent,
  declaration/window/resolve state machine, ownership i guardy, event ordering,
  attack-only override, replay/RNG/rollback/race/no-oracle/auth, kompatybilny
  wire oraz pułapy 5/6/7 SELECT. Nie zmieniono kodu ani allowlisty.
- **C2a1 model + codec OPEN:** dodać v3-only immutable
  `ShootAttackIntent`/`ChargeAttackIntent`, `AttackState`,
  `AttackAbilityOverride`, dwie fazy i exact codec v3. Warunek zakończenia:
  konstrukcyjnie odrzucone nieosiągalne snapshoty, JSON round-trip wszystkich
  headów i byte-for-byte niezmienione golden v1/v2; bez eventów, reducerów,
  protocol transitions, DB i publicznego wire.
- **C2a2 eventy + reducery + pure lifecycle OPEN:** dodać siedem eventów z
  sekcji 5.3, reducery i pure declare/pass/close/resolve z canonical inventory,
  prywatnym RNG oraz complete-tail equality na każdym restart headzie. Warunek
  zakończenia: pass-only attack scope działa dla Shoot/Charge, nonattack v3 i
  całe v2 nie dryfują, validation/outcome failure nie zmienia state/RNG; bez
  metadata/handlera Oznaczenia, persistence/router/client i allowlisty.
- **C2b source-correct metadata/private handler OPEN:** dodać immutable
  `oznaczenie_tak`, strict katalog/payload, source/ally/other-attacker/target
  edge-to-edge 12″/raz-rundę oraz attack effect view widoczny tylko dla
  zadeklarowanego atakującego, także z kontratakiem Szarży. Warunek zakończenia:
  exact `InterruptTriggered` + `AttackAbilityOverrideApplied`, combat/replay
  parity i brak mutacji/czyszczenia `UnitBlob.ability_overrides`; bez I/O,
  publicznej allowlisty i transportu.
- **C2c durable/FastAPI/HttpClient OPEN:** rozszerzyć opt-in create/invite i DB
  constraint do protocol v3, rozdzielić durable declaration/resolve oraz
  activation/attack interrupt scope, dodać strict uniony na istniejących
  `/actions` i `/interrupts`, decoder state v3 i jedną metodę klienta
  `resolve_activation_attack`. Dopiero ten slice dodaje `oznaczenie` do
  publicznej allowlisty. Warunek zakończenia: same-owner/two-bearer,
  restart po każdym headzie, stale/duplicate/race/rollback, body-blind audit,
  no-oracle, scope'y, v1/v2/nonattack parity, one-POST client i dokładne
  5/6/7 SELECT bez N+1.

### D. HttpClient real-transport parity

- **B5.4 DONE:** typowane `start_activation`, `interrupt`,
  `pass_interrupt_priority`, `commit_activation_action`, `continue_activation`
  i `finalize_activation`; state v1+v2 decode oraz jawnie v1-only legacy
  `take_action`;
- **B5.4 DONE:** real FastAPI parity dla same-owner i dwóch niezależnych bearerów,
  accepted interruptu, handoffu, stale window/sequence, duplicate-loser,
  restartu, drugiej akcji i recovery empty;
- **DEFERRED:** LocalClient i Protocol reużywające transition core pozostają poza
  publicznym transportowym slice'em B5.4;
- `agent_proposals`/MCP nie wykonują automatycznie cudzych passów; MCP pozostaje
  consent-only i dostaje nowe write tools dopiero w osobnym scope review.

### E. Packaging

- standalone install/export klienta v2, minimalne zależności, version metadata,
  smoke import bez ORM/serwera;
- wheel/editable install test oraz przykład negocjacji protocol v1/v2/v3;
- dopiero po tym osobna decyzja może rozważyć zmianę domyślnej wersji create.

[R8]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 8.a"
[R10]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 10"
[R11]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 11.b.i–vi"
[R11A]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 11.b.ii–iv"
[R11C]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 11.b.i–iv"
[R12]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 12.a–c"
[R14]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14.d.iv"
[R14S]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14.c"
[R14A]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14"
[R14C]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14.c.v"
[R14D]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 14.d.vi"
[R17]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 17"
[R20]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 20"
[R21]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 21"
[R22]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 22.d"
[R22A]: ../../app/static/docs/SZOP_Rozjemca.md "pkt 22.a"
[Z31]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 31 Strażnik"
[Z45]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 45 Klątwa(X)"
[Z49]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 49 Oznaczenie(X)"
[Z50]: ../../app/static/docs/SZOP_Zdolnosci.md "pozycja 50 Rozkaz(X)"
[ZCONV]: ../../app/static/docs/SZOP_Zdolnosci.md "Konwencje tagów zdolności pasywnych"
