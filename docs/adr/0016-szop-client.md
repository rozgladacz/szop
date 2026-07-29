# ADR-0016 — `szop_client` jako wydzielony moduł (Protocol GameClient + LocalClient)

- **Status:** Accepted
- **Data:** 2026-06-14
- **Kontekst:** Strumień B5 (wątek `faza-b-5-client`). Silnik (ADR-0011) i headless runner (`agents/match.py`, ADR-0032) istnieją, ale konsumenci (C3 `simulate_engagement` MCP, D-stream, przyszłe UI) nie mają stabilnego seamu — musieliby importować wewnętrzne moduły `app.services.engine.*`/`app.services.agents.*` bezpośrednio, wiążąc się z ich kształtem. Roadmap B5 przewiduje `GameClient` Protocol z wymiennymi implementacjami `LocalClient` (in-process) i `HttpClient` (po B4 API), umożliwiając test parity `HttpClient.simulate(...) == LocalClient.simulate(...)`.

## Decyzja

**`szop_client/`** — top-level pakiet (importowany jak `app`) z jednym publicznym kontraktem `GameClient` (Protocol) i implementacją in-process `LocalClient`. Pakiet opakowuje publiczne API silnika (ADR-0011) + runner (ADR-0032); zero zmian w rdzeniu (tylko odczyt).

```python
@runtime_checkable
class GameClient(Protocol):
    def create_battle(rosters, *, seed, terrain, objectives, initiative_player, deployment) -> int
    def get_state(battle_id) -> BattleState
    def take_action(battle_id, action, *, continuation=None) -> tuple[BattleState, tuple[BattleEvent, ...]]
    def get_events(battle_id, since=0) -> tuple[BattleEvent, ...]
    def simulate(rosters, player_factory, *, n, seed, terrain, objectives,
                 alternate_initiative, initiative_player) -> SimulationSummary

class LocalClient:  # in-process; rejestr bitew w pamięci
    ...

@dataclass(frozen=True, slots=True)
class SimulationSummary:
    n_games, wins_p0, wins_p1, draws, total_rounds
    # + win_rate_p0/_p1, draw_rate, avg_rounds (properties)
```

### Decyzje projektowe

1. **Slice = tylko `LocalClient` na ścieżce engine-dict.** Rostery jako `dict` 1:1 z `build_initial_state` (jak fikstury). DB-backed `LocalClient(db_session, user_id)` z roadmap odłożony do `faza-d-roster-adapter` (most ORM→engine-dict to głęboka archeologia modelu danych: `Weapon.range` jako wolny tekst, mapowanie slugów zdolności, attached heroes, ekstrakcja loadoutu — niejednoznaczne decyzje, nie domyka się w jednym oknie).
2. **`HttpClient` + `tests/test_clients_parity.py` odłożone do B4.** Protocol jest strukturalny (`typing.Protocol`) — `HttpClient` dołączy bez dziedziczenia, wystarczy zgodność sygnatur. Pakowanie `pip install -e szop_client/` odłożono: `LocalClient` jest z natury in-process z `app`, więc lokalny install ma sens dopiero z kompletnym `HttpClient`. Warunek został spełniony i rozstrzygnięty w aktualizacji B5.5 poniżej.
3. **`simulate` deleguje do `simulate_from_rosters` (ADR-0032), agregując N gier per `owner_player` (pkt 5.f).** Inicjatywa naprzemienna (`i % 2`) usuwa bias 1. gracza. Seedy: `seed + i` dla kości; gracze budowani świeżo per grę przez `PlayerFactory(i)` — to fabryka odpowiada za **rozłączne seedy graczy** (`RandomPlayer` z identycznym seedem gra lustrzanie na symetrycznej planszy i zawyża remisy — finding F2). To czyni `simulate` parity-spójnym z D2 `simulate_balance`.
4. **`take_action` używa `apply_activation` (model do-2-akcji, ADR-0051)** z opcjonalnym `continuation`, spójnie z `match.run_match`. Sekwencja eventów kontynuuje **monotonicznie** od eventów rozstawienia (Ufortyfikowany pkt 13.c dla oddziałów, które nie ruszyły się w rozstawieniu) — `create_battle` ustawia `next_sequence = len(deploy_events) + 1`. To zachowuje pełny event-sourced log bitwy (spójny z `persistence.save_events`, B2). `take_action` zwraca samą deltę aktywacji; `get_events` zwraca pełny log (rozstawienie + akcje).
5. **`subscribe_events` (push/SSE z roadmap) realizowany jako pull `get_events(battle_id, since)`.** Streaming SSE to B6. Protocol eksponuje `get_events` jako prymityw pull (od `sequence > since`).
6. **Rejestr bitew single-step w pamięci** (`dict[int, _BattleRecord]`, auto-increment id). `UnknownBattleError(KeyError)` dla nieznanego id.

### Aktualizacja B5.5 — lokalna instalacja editable (2026-07-29)

Kompletny `HttpClient` spełnił warunek odroczenia. `szop_client/pyproject.toml`
jest jednym źródłem metadata PEP 621 i entrypointem setuptools PEP 517/660:

- dystrybucja `szop-client`, wersja `0.1.0`, Python `>=3.13,<3.14`;
- jawnie tylko pakiet dystrybucji `szop_client`;
- ograniczone zależności z realnego import graphu:
  `pydantic>=2,<3`, `PyYAML>=6,<7`, `SQLAlchemy>=2,<3`;
- `package-dir = {"" = ".."}` mapuje w trybie editable root bieżącego checkoutu.

Kanoniczna komenda to:

```powershell
python -m pip install -e .\szop_client
```

To świadome sprzężenie monorepo: istniejące `app` oraz action/state/event codeki
są widoczne przez referencję do tego samego checkoutu, nie są kopiowane ani
forkowane. `LocalClient` pozostaje lazy i in-process, a jego publiczne API oraz
`GameClient` nie zmieniają się. Dystrybucja nie obiecuje samodzielnego
wheel/sdist, nie bundluje serwera i nie jest decyzją o publikacji PyPI. Osobna
publikowalna dystrybucja wymaga przyszłej decyzji o granicy współdzielonych
codeców.

Gate `tests/test_szop_client_packaging.py` uruchamia offline editable install w
tymczasowym venv, wykonuje import z CWD poza repo, potwierdza lazy top-level,
brak ORM/DB/FastAPI oraz brak I/O przy konstrukcji `HttpClient`, a także
sprawdza, że `szop_client` i `app` wskazują ten sam checkout.

**Konsekwencje B5.5:** lokalny konsument dostaje powtarzalną instalację bez
kopiowania SSOT. Kosztem jest zależność wpisu editable od ścieżki checkoutu oraz
brak samodzielnego artefaktu dystrybucyjnego.

## Konsekwencje

Poniższa lista opisuje historyczny, pierwszy slice z 2026-06-14; późniejsze
rozstrzygnięcia, w tym DB-backed `LocalClient`, kompletny `HttpClient` i
pakowanie editable, są zapisane w aktualizacji B5.5 powyżej.

**Pozytywne:**
- **Stabilny seam** — konsumenci programują wobec `GameClient`, nie wobec wewnętrznych modułów. `LocalClient`/`HttpClient` wymienne.
- **Odblokowuje C3 `simulate_engagement`** (MCP tool batch) i przyszły test parity `HttpClient == LocalClient`.
- **Determinizm** — `seed` → `DeterministicDice` (ADR-0010/0012); te same argumenty + seed = bit-perfect ten sam przebieg. Testowalne (13 testów: determinizm batcha, parity z runnerem i z D2 `simulate_balance`, wierność single-step `take_action == apply_activation`, walidacja błędów).
- **Zero kolizji z rdzeniem** — nowy pakiet, tylko odczyt API silnika/runnera. Bezpieczny równolegle z wątkami modyfikującymi silnik.

**Negatywne / koszty:**
- **Brak ładowania rosterów z DB** w tym slice — engine-dict only. DB path czeka na `faza-d-roster-adapter`.
- **`HttpClient` nieobecny** — parity test sensowny dopiero po B4 API.
- **`simulate` używa `simulate_from_rosters`, które pomija eventy rozstawienia** w agregacie (ADR-0032 dec. #5) — to nie problem dla `SimulationSummary` (liczy wyniki, nie eventy). Single-step path (`create_battle`/`take_action`/`get_events`) ma pełny log z rozstawieniem.

## Alternatywy rozważone

- **Brak osobnego pakietu — konsumenci importują `engine`/`agents` wprost.** Odrzucone — wiąże konsumentów z wewnętrznym kształtem modułów; brak miejsca na `HttpClient` i parity test.
- **`GameClient` jako ABC zamiast Protocol.** Odrzucone — Protocol strukturalny pozwala `HttpClient` dołączyć bez dziedziczenia (luźniejsze sprzężenie); `@runtime_checkable` daje `isinstance` gdy potrzebny.
- **Od razu DB-backed `LocalClient` + `HttpClient`.** Odrzucone dla tego okna — adapter ORM→engine-dict to osobny wątek z niejednoznacznymi decyzjami; B4 API musi istnieć dla `HttpClient`. Slice engine-dict daje natychmiastową wartość (C3, D-stream) bez tych blokad.
- **`take_action` reset sekwencji do 1 po rozstawieniu.** Odrzucone — złamałoby ciągłość event-sourced logu (rozstawienie emituje realne eventy pkt 13.c); `persistence` oczekuje monotonicznej sekwencji całej bitwy.

## Inwarianty

1. `LocalClient().simulate(rosters, factory, n, seed=s)` deterministyczny per `(rosters, factory, s)`.
2. `take_action(bid, a)` == `apply_activation(state, a, dice, sequence=next_seq)` (stan + delta eventów) dla tego samego seedu.
3. `get_events(bid)` to pełny log (rozstawienie + akcje), monotoniczny po `sequence`; `take_action` zwraca jego sufiks.
4. `SimulationSummary`: `wins_p0 + wins_p1 + draws == n_games`.
5. `isinstance(LocalClient(), GameClient)` (zgodność strukturalna z Protocolem).
