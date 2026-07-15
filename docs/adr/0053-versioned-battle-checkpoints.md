# ADR-0053 — Wersjonowane checkpointy stanu bitwy i RNG

- **Status:** Accepted
- **Data:** 2026-07-15
- **Kontekst:** Strumień B2/B4. `POST /battles` zapisywał metadane `Battle` i
  początkowy event-log, lecz pełny `BattleState` oraz bieżąca pozycja
  `DeterministicDice` pozostawały wyłącznie w pamięci klienta lokalnego.

## Problem

Eventy są wystarczające do audytu zmian, ale nie stanowią samodzielnego,
niezawodnego checkpointu procesu. Wznowienie wymaga zarówno pełnego stanu
wejściowego silnika, jak i dokładnej pozycji RNG. Sam `rng_seed` nie wystarcza,
gdy wykonano już dowolną liczbę rzutów. Format trwały i wire format nie mogą
używać `pickle`, `eval`, dynamicznych importów ani innego wykonywania danych.

## Decyzja

1. `app/services/engine/state_codec.py` definiuje schemę
   `szop.battle_state`, wersja `1`. Codec zapisuje pełny `BattleState` jako
   tagowane drzewo JSON. Obsługiwane typy to jawna whitelist znanych dataclass,
   enumów i kontenerów (`tuple`, `frozenset`, mapping); nieznane typy, pola,
   wersje i wartości nie-JSON są odrzucane. Deserializacja nie wybiera kodu do
   uruchomienia na podstawie payloadu.
2. `DeterministicDice.to_checkpoint()` zapisuje schemę
   `szop.deterministic_dice`, wersja `1`, seed oraz pełny wynik
   `random.Random.getstate()` po bezpiecznej konwersji zagnieżdżonych tuple na
   listy. `from_checkpoint()` odtwarza tuple i używa `setstate()`. Dzięki temu
   następny i każdy dalszy wynik jest identyczny z procesem źródłowym.
3. Addytywna tabela `battle_checkpoints` przechowuje
   `(battle_id, sequence_at, state_json, rng_json, timestamp)` z unikalnością
   `(battle_id, sequence_at)`. Projekt nadal nie używa Alembic; nową tabelę
   tworzy `Base.metadata.create_all`.
4. `save_checkpoint()` i `load_latest_checkpoint()` są transakcyjnie neutralne.
   Checkpoint jest spójny tylko wtedy, gdy `sequence_at` jest dokładnie równy
   aktualnemu `latest_event_sequence`. Stary checkpoint nie jest zwracany jako
   bieżący, ponieważ jego pozycja RNG może nie odpowiadać zapisanym eventom.
5. `POST /battles` zapisuje startowe eventy i checkpoint w jednej transakcji.
   Każdy przyszły endpoint mutujący bitwę musi zachować ten sam wzorzec:
   eventy + checkpoint + metadane, jeden commit.
6. `GET /battles/{id}/state` jest participant-scoped, używa `battle:read` dla
   bearer agenta i zwraca wersjonowany stan z `battle_id` oraz `sequence_at`.
   Publiczny payload nie zawiera `rng_json` ani checkpointu RNG. Brak bieżącego
   checkpointu dla istniejącej, dostępnej bitwy zwraca 409; cudza i nieistniejąca
   bitwa nadal zwraca nierozróżnialne 404.

## Konsekwencje

- Proces może zostać wznowiony po zamknięciu sesji DB bez zgadywania stanu RNG.
- `HttpClient.get_state()` może zwracać domenowy `BattleState` i być równoważny
  `LocalClient.get_state()`.
- Rozmiar checkpointu rośnie liniowo z rozmiarem stanu. Odczyt używa stałej
  liczby zapytań po indeksowanych `(battle_id, sequence_at)`, bez replayu całego
  logu.
- Zmiana listy typów/pól lub semantyki formatu wymaga nowej wersji schemy i
  jawnej ścieżki kompatybilności; nie wolno cicho reinterpretować wersji `1`.
- Wewnętrzny stan `random.Random` jest kontraktem checkpointu implementacji
  Python używanej przez aplikację; wersja schemy umożliwia przyszłą migrację
  algorytmu RNG bez `pickle`.

## Alternatywy odrzucone

- **Replay wyłącznie z eventów i `rng_seed`:** nie odtwarza pewnie liczby
  wykonanych wywołań RNG ani pełnego wejściowego stanu procesu.
- **`pickle`:** może wykonywać dane podczas deserializacji i wiąże zapis z
  detalami klas Pythona.
- **Checkpoint tylko stanu:** pozostawia RNG w innej pozycji po wznowieniu.
- **Zwracanie najnowszego starszego checkpointu:** udaje aktualny stan mimo
  eventów zapisanych po nim i może rozjechać dalszą sekwencję losową.
