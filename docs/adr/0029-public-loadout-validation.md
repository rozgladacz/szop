# ADR-0029 — Publiczna walidacja loadoutu bez zapisu

- **Status:** Accepted
- **Data:** 2026-07-18
- **Kontekst:** C3.1 po publicznym kliencie MCP (ADR-0021), scoped tokenach
  (ADR-0025) i istniejącym leaf-CLI `scripts/validate_loadout.py`.

## Problem

Leaf-CLI potrafił pokazać diff raw→normalized i koszt, ale logika diffu żyła w
skrypcie, a agent nie miał publicznej granicy HTTP/MCP. Bez ekstrakcji wrapper
mógłby zduplikować sanityzację lub koszt, a lokalny MCP mógłby ominąć
backendowe auth, audit i katalog ORM. Treść loadoutu oraz wynik kosztowy nie
mogą trafiać do logów audytu ani komunikatów błędów.

## Decyzja

1. `app.services.loadout_validation` jest jednym produkcyjnym SSOT diffu.
   Deleguje sanityzację wyłącznie do `normalize_roster_unit_loadout`, a koszt
   wyłącznie do `calculate_roster_unit_quote`. Leaf-CLI importuje i re-eksportuje
   serwis; zachowuje `--list`, wejścia JSON/plik, `--count` i raport tekst/JSON.
2. Publiczna granica to agent-only `POST
   /units/{unit_id}/validate-loadout`, scope `loadout:validate`. Body ma
   `loadout` jako obiekt JSON i ścisły `count` 1–100. Nie ma fallbacku sesyjnego
   ani owner filteru: `Unit` jest globalnym katalogiem.
3. Endpoint jest read-only. Nie tworzy ani nie zmienia `Roster`, `RosterUnit`,
   `Unit`, linków katalogowych ani loadoutu. Jedynym zapisem jest istniejący
   `last_used_at` tokena i `AgentAuditLog` wykonywany przez
   `require_agent_scope`.
4. Odpowiedź `szop.validate_loadout/v1`, version 1, zachowuje semantykę CLI:
   ordered `weapons/active/aura` z accepted/rejected/clamped, passive, mode,
   koszt i `has_issues`. Granice serwisu, routera, klienta i MCP odrzucają
   wartości nie-JSON lub NaN/Infinity.
5. Malformed JSON, zły body/loadout/count zwraca stałe 422 bez odbijania body;
   brak jednostki stałe 404; kontrolowany błąd kosztu/serializacji stałe 500.
   Odpowiedzi nie zawierają ORM, tracebacka, ścieżki lokalnej ani fragmentu
   loadoutu.
6. Generyczny audyt zapisuje metodę, trasę, status, scope i bezpieczny
   `unit_id`. Nie czyta body, więc loadout, wynik, składowe kosztu i bearer nie
   trafiają do `AgentAuditLog`.
7. Root `Unit` jest ładowany raz z istniejącym zestawem `selectinload` dla
   broni, łańcucha rodziców, abilities i armii. Gate dla małego oraz
   300-elementowego legalnego payloadu wynosi 11 SQL statements w obu
   przypadkach (łącznie z auth/auditem); rozmiar body nie tworzy N+1.
8. `HttpClient.validate_loadout` wykonuje jeden POST, używa globalnego timeoutu
   i ma ścisły decoder schemy/wersji/typów/finite/order/bounds. Dziewiąty tool
   MCP `validate_loadout` wykonuje dokładnie jedno wywołanie tej metody i nie
   importuje ORM, DB, costs ani leaf-skryptu. `GameClient` Protocol pozostaje
   bez zmian.

## Konsekwencje

- CLI, HTTP i pośrednio MCP dzielą jeden diff, normalizer i dispatcher kosztów.
- Agent może bezpiecznie sprawdzić konfigurację przed osobnym consent-gated
  write flow, ale walidacja sama nigdy nie zapisuje loadoutu.
- Publiczny payload może być większy dla dużego diffu; limit request body/rate
  limiting pozostają polityką infrastruktury, nie tego slice'a.
- `/quote`, `/rosters/{id}`, frontend, rulesety, RAG i pozostałe narzędzia C3
  nie zmieniają zachowania ani liczby zapytań.

## Alternatywy rozważone

- **Pozostawienie diffu w skrypcie i import skryptu z routera:** odrzucone, bo
  odwraca zależności produkcja→leaf i utrwala CLI jako przypadkowy SSOT.
- **Lokalna walidacja/koszt w MCP:** odrzucone, bo łamie ADR-0021 i omija
  backendowy scope/audit.
- **GET lub query-string z loadoutem:** odrzucone, bo utrwala prywatną treść w
  URL-u i generycznych logach.
- **Zapis „znormalizowanego” loadoutu podczas walidacji:** odrzucone, bo dry-run
  musi być read-only; przyszłe zapisy wymagają osobnego consent flow.
