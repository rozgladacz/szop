# ADR-0054 — Atomowe pojedyncze akcje bitwy przez HTTP

- **Status:** Accepted
- **Data:** 2026-07-15
- **Kontekst:** Strumień B4/B5. ADR-0053 zapewnił spójny checkpoint
  `BattleState` + RNG, ale brakowało publicznego zapisu akcji i implementacji
  `HttpClient.take_action`.

## Problem

Publiczny zapis musi bezpiecznie przenieść zamknięty union `Action`, wznowić
dokładny stan RNG i atomowo utrwalić wynik bez lost update. Callback
`continuation` z lokalnej aktywacji wieloakcyjnej jest kodem procesu i nie ma
bezpiecznej reprezentacji wire. Klient nie może ukrywać wersji bitwy w
mutowalnym cache, bo równoległy zapis unieważniłby taki stan.

## Decyzja

1. `app/services/engine/action_codec.py` definiuje schemę `szop.action`, wersja
   `1`. Payload ma dokładnie pola `schema`, `version`, `action_type`, `payload`.
   Jawny rejestr dopuszcza wyłącznie `maneuver`, `defend`, `shoot`, `charge` i
   `special`, mapowane na istniejące dataclassy domenowe. `Position` i
   `WeaponProfile` mają jawne pola; payload `SpecialAction` dopuszcza tylko
   natywne wartości JSON. Nieznane pola/typy/wersje, bool zamiast int, wartości
   niefinitywne, cykle i dane nie-JSON są odrzucane. Codec nie używa `pickle`,
   importów dynamicznych ani wykonywania danych.
2. `POST /battles/{battle_id}/actions` przyjmuje dokładnie:

   ```json
   {
     "expected_sequence": 12,
     "action": {
       "schema": "szop.action",
       "version": 1,
       "action_type": "defend",
       "payload": {"unit_id": 101}
     }
   }
   ```

   `expected_sequence` jest obowiązkowym ścisłym int `>= 0`. Endpoint wykonuje
   jedną akcję przez `resolver.apply`; HTTP continuation i wiele akcji w jednym
   request pozostają poza tym kontraktem.
3. Sesja użytkownika albo bearer agent ze scope `battle:act` musi należeć do
   uczestnika bitwy. Cudza i nieistniejąca bitwa zwracają ten sam 404. Dodatkowo
   principal musi odpowiadać `p1_user_id`/`p2_user_id` wskazanemu przez
   `owner_player` aktora. Ten sam użytkownik po obu stronach sandboxu może
   sterować obiema stronami.
4. Endpoint ładuje wyłącznie checkpoint zgodny z końcem event-store i porównuje
   go z `expected_sequence`. Następnie używa checkpointowanego
   `DeterministicDice`. Jeżeli istniejący `should_end_round` wskaże koniec rundy,
   endpoint wywołuje istniejący `round_end_phase` (aktualne źródło reguł:
   `SZOP_Rozjemca.md` pkt 8.b–8.d; wynik gry: pkt 5.g). Nie dodaje własnej logiki
   reguł.
5. Eventy akcji i ewentualnego końca rundy są jednym ciągłym ogonem. Jeden
   commit obejmuje `save_events(..., expected_latest_sequence=N)`, dokładnie
   jeden nowy checkpoint state+RNG oraz synchronizację `Battle.current_round`,
   `status` i `winner_user_id`. Precondition conflict i DB unique race zwracają
   409 po rollbacku; błędny payload albo nielegalna akcja zwracają bezpieczne
   422 bez częściowego zapisu.
6. Sukces zwraca `battle_id`, `previous_sequence`, `new_sequence`, pełny
   wersjonowany `BattleState` bez RNG oraz dokładną deltę zapisanych eventów:

   ```json
   {
     "battle_id": 7,
     "previous_sequence": 12,
     "new_sequence": 15,
     "state": {"schema": "szop.battle_state", "version": 1, "state": {}},
     "events": []
   }
   ```

7. `HttpClient.take_action(..., continuation=None)` serializuje akcję wspólnym
   codekiem, wykonuje świeży `GET /state`, przekazuje otrzymany `sequence_at`
   jako `expected_sequence`, a z odpowiedzi POST zwraca
   `tuple[BattleState, tuple[BattleEvent, ...]]`. Nie przechowuje cache bitwy.
   `continuation != None` jest odrzucane przed jakimkolwiek transportem.

## Konsekwencje

- Każda akcja HTTP ma dwa żądania (świeży GET checkpointu i warunkowy POST), ale
  nie wymaga GET po sukcesie. Konflikt pomiędzy nimi jest wykrywany przez 409.
- Bearer używany przez domyślne `HttpClient.take_action` potrzebuje obu scope:
  `battle:read` dla świeżego GET i `battle:act` dla POST. Sam endpoint zapisu
  nadal wymaga wyłącznie `battle:act` oraz jawnego `expected_sequence`.
- Stan RNG po ponownym otwarciu sesji DB pozostaje identyczny z przebiegiem
  referencyjnym in-process.
- Historyczna bitwa bez bieżącego checkpointu pozostaje tylko do odczytu tego
  slice i zwraca 409; backfill nie jest wymagany.
- HTTP obsługuje świadomie pojedynczą akcję/zamkniętą aktywację MVP. Transport
  continuation, osobne przerwania i multi-action callback wymagają osobnej
  decyzji i endpointów.

## Alternatywy odrzucone

- **Ukryty sequence cache w `HttpClient`:** podatny na zapis innego procesu i
  wymaga złożonej invalidacji.
- **Brak `expected_sequence`:** pozwala na lost update i przesunięcie RNG z
  niewłaściwego checkpointu.
- **Continuation serializowane w JSON:** callback jest kodem, nie danymi, i nie
  ma bezpiecznego kontraktu transportowego.
- **Replay od seedu albo starszego checkpointu:** nie gwarantuje bieżącej pozycji
  RNG; odrzucone już w ADR-0053.
