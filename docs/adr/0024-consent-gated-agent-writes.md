# ADR-0024 — Consent-gated agent writes dla akcji bitwy

- **Status:** Accepted
- **Data:** 2026-07-16
- **Kontekst:** Strumień C1/C3 po read-only MCP (ADR-0021), scoped tokenach
  (ADR-0025) i atomowym publicznym zapisie akcji bitwy (ADR-0054).

## Problem

Agent MCP powinien móc zaproponować konkretną akcję bitwy, ale nie może
wykonywać zapisu bez świadomego kliknięcia właściciela. Propozycja musi być
odporna na zmianę stanu pomiędzy obserwacją i zgodą, a równoległe lub ponowne
zatwierdzenie nie może podwoić eventów, checkpointów ani przesunąć RNG.

## Decyzja

1. Dedykowany endpoint `POST /agent_proposals/battle-actions` wymaga na jednym
   bearer tokenie obu scope'ów: `battle:read` i `agent_proposals:create`.
   Nie wymaga `battle:act`, ponieważ sam nie zmienia bitwy. Ogólny
   `POST /agent_proposals` jawnie odrzuca zarezerwowane `action="battle:action"`,
   więc nie może ominąć podwójnego scope ani walidacji.
2. Propozycja zamraża w `AgentProposal.payload_json` dokładnie:
   `battle_id`, ścisły `expected_sequence >= 0` oraz pełny, kanoniczny wire
   `szop.action/v1`. Osobne `summary` jest niepustym, czytelnym opisem dla
   właściciela. Payload nie jest modyfikowany po utworzeniu.
3. Przy tworzeniu backend ponownie sprawdza participant scoping, stronę
   `owner_player`, sequence i legalność akcji. Używa wspólnych codeców,
   bieżącego checkpointu state+RNG oraz tej samej ścieżki resolvera co zapis,
   ale nie utrwala eventów ani checkpointu. Odtworzony obiekt RNG jest tylko
   lokalną kopią, więc walidacja nie przesuwa trwałego RNG.
4. `POST /agent_proposals/{id}/approve` pozostaje cookie-session owner-only.
   Dla `action="battle:action"` kliknięcie wykonuje akcję natychmiast pod
   tożsamością właściciela. Dostęp do bitwy i kontrola strony aktora są
   sprawdzane ponownie w chwili wykonania.
5. `app/services/battle_actions.py` jest jedyną wspólną orkiestracją
   przygotowania i atomowego zapisu pojedynczej akcji. Korzystają z niej
   zarówno `POST /battles/{id}/actions`, jak i approval propozycji. Używa
   istniejących SSOT: action codec, checkpoint state+RNG, resolver,
   `save_events` i `save_checkpoint`.
6. Approval wykonawczy najpierw warunkowo zajmuje propozycję przez atomowe
   `UPDATE ... WHERE status='pending'`. W tej samej transakcji zapisuje eventy,
   dokładnie jeden checkpoint, metadane bitwy, status/result propozycji oraz
   audit. Commit jest wspólny; błąd wycofuje całość.
7. Statusy propozycji wykonawczej to `pending`, `executed`, `rejected` i
   `stale`. Historyczny `approved` pozostaje tylko dla ogólnych propozycji bez
   executora. Ponowne approve `executed` jest idempotentnym odczytem wyniku.
8. Jeśli `expected_sequence` jest już stare albo zapis przegra race, transakcja
   wykonania jest wycofywana, a propozycja przechodzi osobną, bezpieczną
   transakcją do `stale`. Bitwa, eventy, checkpoint i RNG nie zmieniają się.
9. `AgentProposal.result_json` przechowuje osobno od zamrożonego payloadu:
   dla sukcesu `battle_id`, previous/new sequence i liczbę eventów; dla stale
   expected/actual sequence. Addytywna kolumna powstaje przez obecny
   `_migrate_schema`.
10. Audit nie zawiera raw tokena ani pełnego action payloadu. Koreluje ownera,
    agenta, `token_id`, proposal, battle, użytkownika zatwierdzającego oraz
    expected/previous/new/actual sequence.
11. MCP publikuje `propose_battle_action`, delegujące wyłącznie do
    `HttpClient.propose_battle_action`. Nie publikuje `take_action`; bezpośredni
    zapis MCP bez kliknięcia pozostaje niedozwolony.

## Konsekwencje

- Pełny przepływ to obserwacja → propozycja → jedno kliknięcie → wykonana akcja.
- Legalność jest sprawdzana dwukrotnie: przy tworzeniu i przy wykonaniu.
- Bezpośrednie publiczne `POST /battles/{id}/actions` nadal istnieje dla
  jawnych klientów z `battle:act`, ale MCP go nie eksponuje.
- Ogólne propozycje nadal mogą być jedynie `approved`/`rejected`; nie powstał
  uniwersalny executor dowolnych typów akcji.
- Każde utworzenie propozycji wykonuje read checkpointu, a approval wykonuje
  ponowny read i atomowy zapis. To celowy koszt spójności i zgody.

## Alternatywy odrzucone

- **MCP `take_action` ze scope `battle:act`:** omija świadomą zgodę człowieka.
- **Approve tylko zmienia status, agent wraca później:** wymaga dodatkowej
  orkiestracji, może utknąć i komplikuje idempotencję.
- **Wykonanie bez `expected_sequence`:** pozwala wykonać decyzję podjętą dla
  innego stanu i przesunąć RNG.
- **Mutowanie payloadu propozycji wynikiem:** niszczy dowód tego, na co właściciel
  wyraził zgodę; wynik ma osobne pole.
- **Ogólny executor proposal action types:** rozszerza powierzchnię zapisu poza
  zamknięty, przetestowany przypadek pojedynczej akcji bitwy.
