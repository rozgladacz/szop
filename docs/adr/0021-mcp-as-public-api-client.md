# ADR-0021 — MCP jako lokalna fasada publicznego API

- **Status:** Accepted
- **Data:** 2026-07-15
- **Kontekst:** Strumień C1/C3 po udostępnieniu publicznych odczytów bitwy i
  wersjonowanych checkpointów przez `szop_client.HttpClient`.

## Problem

Lokalny serwer MCP potrzebuje obserwować bitwę bez tworzenia drugiej ścieżki
autoryzacji, audytu i dostępu do danych. Bez wyraźnej granicy MCP mógłby zacząć
importować ORM, sesję DB albo routery, omijając participant scoping i publiczny
kontrakt HTTP. Odczyt stanu wymaga także jednego spójnego checkpointu: stan i
`sequence_at` nie mogą pochodzić z osobnych requestów.

## Decyzja

1. `mcp_server` jest wyłącznie lokalną fasadą publicznego API. Wszystkie
   operacje domenowe deleguje do wstrzykniętego/publicznego
   `szop_client.HttpClient`; nie importuje ORM, modeli, `Session`, `app.db`,
   routerów ani własnego transportu HTTP.
2. Aktualna powierzchnia MCP zawiera dokładnie cztery read-only tools:
   `simulate_engagement`, `get_battle_metadata`, `get_battle_state` i
   `get_battle_events`. Nie publikuje write tools, resources ani prompts.
3. `HttpClient.get_state_checkpoint()` jest publicznym kontraktem jednego
   `GET /battles/{id}/state`. Zwraca `BattleStateCheckpoint` z `battle_id`,
   `sequence_at`, schemą, wersją i domenowym `BattleState`. Dotychczasowe
   `get_state()` deleguje do niego, a `take_action()` używa jego
   `sequence_at`; klient nie utrzymuje cache i nie wykonuje osobnego odczytu
   metadanych.
4. Publiczne projekcje `szop_client.wire` kodują checkpoint i eventy do
   stabilnych danych JSON, zachowują kolejność eventów oraz odrzucają
   niefinitywne lub inne nie-JSON-owe wartości. Publiczna projekcja stanu nie
   zawiera checkpointu RNG.
5. MCP waliduje wyłącznie kształt własnych argumentów (`battle_id` jako ścisły
   int `>= 1`, `since` jako ścisły int `>= 0`). Scope’y i tokeny pozostają
   odpowiedzialnością backendu: odczyty wymagają `battle:read`, a symulacja
   `battle:simulate`. Serwer nie interpretuje scope’ów ani nie zastępuje
   backendowego participant scopingu.
6. Błędy klienta zachowują znaczenie i status HTTP dla operatora, ale granica
   MCP redaguje bearer token oraz wartości nagłówka `Authorization`. Tokeny i
   sekretne payloady nie są logowane.

## Konsekwencje

- MCP i inni konsumenci HTTP używają tego samego mechanizmu uprawnień, audytu i
  wersjonowania co pozostałe klienty publicznego API.
- Każdy read-only tool wykonuje dokładnie jedno istniejące wywołanie endpointu;
  `get_battle_state` nie ma race między stanem i sekwencją.
- Rozszerzenie MCP o zapis wymaga osobnej decyzji consent-gated; publiczne
  `HttpClient.take_action` nie oznacza automatycznego wystawienia write toola.
- Zmiana schemy stanu lub eventów wymaga zgodnej zmiany publicznych projekcji i
  testów JSON-safety.

## Alternatywy odrzucone

- **Bezpośredni odczyt DB/ORM z MCP:** omija publiczne auth, participant scoping
  i audit trail oraz sprzęga proces MCP ze schematem bazy.
- **Własne requesty HTTP w `mcp_server`:** duplikują transport, dekodowanie i
  obsługę błędów `HttpClient`.
- **Osobne metadata GET po sequence dla stanu:** wprowadza race i dodatkowy
  request.
- **Write tool bez consent gate:** rozszerza powierzchnię zaufania poza
  read-only cel tego etapu.
