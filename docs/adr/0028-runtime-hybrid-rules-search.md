# ADR-0028 — Runtime hybrid rules search przez publiczne API

- **Status:** Accepted
- **Data:** 2026-07-18
- **Kontekst:** C2.6 po weighted RRF C2.4 (ADR-0026), procesowym lifecycle
  MiniLM C2.5 (ADR-0027), publicznym kliencie MCP (ADR-0021) i scoped tokenach
  (ADR-0025).

## Problem

Hybrid retrieval osiąga wymagane 24/30 i po rozgrzaniu działa szybko, ale dotąd
był wyłącznie funkcją offline. Runtime potrzebuje jednej publicznej ścieżki bez
drugiej implementacji fuzji, bez lokalnego dostępu MCP do indeksu oraz bez
zapisywania treści pytań w URL-u i audycie. Cold start około 15 s przekracza
domyślny 10-sekundowy timeout klienta. Profil bazowy aplikacji nie może przez
sam import ładować ani wymagać ciężkiego stosu RAG.

## Decyzja

1. Publiczny kontrakt to agent-only `POST /rules/search`, body `{query, limit}`
   i scope `rules:search`. `query` jest trimowane i ograniczone do 1–200 znaków,
   `limit` jest ścisłym int 1–10. Nie ma fallbacku cookie-session ani query w
   query-stringu.
2. Endpoint wywołuje dokładnie raz istniejące
   `mcp_server.search.hybrid_search(query, limit)`. Strategia jest stała:
   weighted RRF z ADR-0026. Publiczny kontrakt nie ma pola `mode`; raw dense z
   wynikiem 8/30 pozostaje wyłącznie diagnostyką offline.
3. Odpowiedź `szop.search_rules/v1` zawiera stałe `query`,
   `strategy="hybrid_weighted_rrf"`, `count` i `results`. Wynik zachowuje
   `chunk_id/source/headings/refs/text`, finalny score oraz skończone ranki,
   wagi i wkłady BM25/dense. Dozwolone źródła są logicznymi nazwami obu
   kanonicznych MD; ścieżki cache/indexu/modelu nie są częścią schemy.
4. Request path nie pobiera modelu i nie przebudowuje indeksu. Brak optional
   dependencies, modelu offline, indeksu lub zgodności oraz kontrolowane
   `EmbeddingError`, `VectorStoreError` i `SearchError` mapują się na stałe
   `503 {"detail":"Rules search unavailable"}`. Walidacja requestu pozostaje
   422. Wszystkie nowe granice JSON odrzucają NaN/Infinity.
5. Standardowy `require_agent_scope` pozostaje SSOT tokena i audytu. Udany auth
   zapisuje route, metodę, status `authorized` oraz bezpieczne path/query params;
   helper nie czyta body, więc query i wynik nie trafiają do `AgentAuditLog`.
   Bearer jest wyłącznie nagłówkiem i podlega dotychczasowej redakcji.
6. `HttpClient.search_rules(query, limit=5)` wykonuje jeden POST i dekoduje
   envelope, wersję, dokładne pola, źródła, limity, ranki oraz skończone liczby.
   Tylko ta metoda używa timeoutu `max(client_timeout, 30 s)`; globalny timeout
   pozostałych call sites nie zmienia się.
7. Ósmy tool MCP `search_rules` deleguje dokładnie raz do tej metody klienta.
   Nie importuje `search`, `vector_store`, torch ani modelu. Opis kieruje
   parafrazy/znaczenie semantyczne do `search_rules`, a dokładny `pkt X`/tekst do
   `lookup_rule`.
8. Import `app.main` i `mcp_server.server` może załadować wyłącznie lekkie
   adaptery. `sentence_transformers`, `transformers`, `torch` i `sqlite_vec`
   pojawiają się dopiero przy realnym request path. Base app bez profilu RAG
   startuje, a brak readiness daje kontrolowane 503.

## Konsekwencje

- MCP zachowuje granicę API-only, jeden mechanizm auth/audytu i brak dostępu do
  DB lub lokalnego indeksu.
- Cold request może blokować worker CPU przez około 15 s; encode singletona jest
  nadal serializowane. Rate limiting, kolejka i osobny worker RAG są odłożone do
  pomiarów obciążeniowych, nie do tego slice'a.
- Runtime wymaga opcjonalnego profilu `requirements-rag.txt`, pobranego fixed
  modelu oraz zgodnego indeksu. Brak readiness jest stanem 503, nie bootstrapem.
- Raw dense, zmiana modelu/RRF/korpusu/gold setu, query/vector cache i kolejne
  narzędzia C3 pozostają poza zakresem.

## Alternatywy odrzucone

- **GET z query-stringiem:** utrwala pytanie w URL-u i generycznym audycie.
- **Dense jako publiczny `mode`:** słabszy wynik 8/30 i zbędna powierzchnia API.
- **Lokalny import RAG w MCP:** łamie ADR-0021 i omija backendowy auth/audyt.
- **Auto-download lub auto-reindex w request path:** nieprzewidywalna sieć,
  mutacja artefaktów i jeszcze dłuższy cold start.
- **Globalne podniesienie timeoutu klienta:** pogarsza wykrywanie zawieszeń we
  wszystkich niezwiązanych endpointach.
