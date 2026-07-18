# ADR-0033 — Owner-scoped score_list przez publiczne API

- **Status:** Accepted
- **Data:** 2026-07-18
- **Kontekst:** C3.2 — publikacja istniejącego read-only `score_list`
- **Extends:** ADR-0021, ADR-0025

## Decyzja

Publikujemy ocenę jednej istniejącej rozpiski jako agent-only
`POST /rosters/{roster_id}/score` ze scope `roster:score`. Target i jawnie
wskazani przeciwnicy są zawsze odczytywani w granicy `owner_user_id` tokena;
brak i cudzy identyfikator mają identyczne 404. Brak listy przeciwników oznacza
wszystkie pozostałe rozpiski ownera w stabilnym porządku `id`.

Produkcyjnym SSOT wyboru pola, projekcji rosterów, agregacji i sygnałów kosztowych
jest `app.services.roster_scoring`. Leaf-CLI `scripts/score_list.py` importuje i
re-eksportuje ten serwis. Wspólna orkiestracja pary/batchu symulacji żyje w
`app.services.roster_simulation`; istniejący endpoint symulacji, `LocalClient`,
leaf-CLI i scoring nie utrzymują osobnych pętli gry.

Publiczny workload jest jawny i ograniczony do 10 przeciwników, 1–10 gier na
przeciwnika oraz 50 gier łącznie. Pole domyślne przekraczające limit zwraca stałe
422 i wymaga jawnego podzbioru; nie jest obcinane. Puste pole jest poprawnym 200
z zerowymi agregatami i pustymi grupami sygnałów kosztowych.

Odpowiedź `szop.score_list/v1` zawiera wyłącznie bezpieczne projekcje rosterów,
parametry, posortowane wyniki per przeciwnik, agregat i strukturalne grupy
`vs_cheaper`/`vs_pricier`. `HttpClient.score_list` wykonuje dokładnie jeden POST,
stosuje timeout 120 s tylko dla tej metody i ściśle sprawdza schemę, typy,
kolejność, finite/bounds oraz spójność agregatów. Dziesiąty tool MCP deleguje
dokładnie raz do tego klienta i nie importuje aplikacji, ORM, DB, engine, costs
ani `scripts`.

Endpoint nie zapisuje bitew, rosterów, wyników, katalogu ani `AgentToken`.
Dozwolonym skutkiem ubocznym jest wyłącznie standardowy `AgentAuditLog`.
Audit może zawierać metodę, trasę, status, scope i path `roster_id`, ale nigdy
body, listy przeciwników, nazw/składów, punktów, parametrów symulacji, wyników
ani bearera.

## Konsekwencje

- Jeden serwis obsługuje CLI, API, klienta i MCP bez zależności `app -> scripts`.
- Owner scope nie tworzy oracle dla cudzych rosterów.
- Liczba zapytań SQL całego requestu jest niezależna od liczby gier i wielkości
  dozwolonego pola; CPU rośnie liniowo wyłącznie z jawnym limitem 50 gier.
- `/quote`, `/rosters/{id}` i kontrakt `/battles/simulate` pozostają bez zmian.
- `find_exploit_candidates`, zapis wyników i interpretacja LLM pozostają poza
  tym etapem.

## Alternatywy rozważone

- MCP czytający ORM/DB lokalnie — odrzucone, bo łamie ADR-0021 i dubluje auth,
  owner scope oraz audyt.
- Wielokrotne wywołania `/battles/simulate` z MCP — odrzucone, bo rozprasza
  workload gate i agregację po stronie klienta.
- Ciche obcięcie domyślnego pola — odrzucone, bo zmienia znaczenie oceny bez
  wiedzy wywołującego.
- Zapis wyników lub bitew — odrzucone; C3.2 jest wyłącznie read-only.
