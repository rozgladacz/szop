# ADR-0025 — Rola agent + scoped bearer tokens (Strumień C1)

- **Status:** Accepted
- **Data:** 2026-06-28
- **Kontekst:** Strumień C (lokalny agent MCP) + B4 API. Agent automatyczny musi
  móc czytać/pisać przez publiczne API jako **osobna tożsamość**, nie podszywając
  się pod sesję-cookie zalogowanego człowieka. Roadmap C1 wymienia: rolę `agent`,
  model `AgentToken` (scoped), endpointy zarządzania tokenami i middleware
  `require_agent_scope`. Infrastruktura powstała addytywnymi slice'ami:
  schema 2026-06-26 (`User.role`, `AgentToken`, `AgentAuditLog`), runtime helper
  2026-06-27 (`security.require_agent_scope`), endpointy 2026-06-28
  (`app/routers/agent_tokens.py`). Ten ADR spisuje **rzeczywistość już
  zaimplementowaną** i zamraża jej kontrakt jako podstawę pod B4/MCP.

  Pokrewne: [ADR-0050](0050-event-store-persistence.md) (event-store, ta sama
  zasada „brak Alembic — addytywny `create_all` + `_migrate_schema`"),
  ADR-0021 (MCP jako klient publicznego API) i ADR-0024 (consent-gated writes)
  pozostają `—` — dotyczą warstwy konsumenta i zapisów za zgodą, nie tożsamości.

## Decyzja

### 1. Trzecia rola obok cookie-session UI

`User.role ∈ {user, agent, admin}` (`app/models.py:USER_ROLE_*`, kolumna
`String(20)` default `"user"`). **`is_admin` pozostaje źródłem uprawnień UI** —
`role` NIE przepina istniejącej autoryzacji cookie-session. Agent to dedykowany
wiersz `User(role="agent")` z losowym, nieużywalnym hasłem (mint poniżej): nigdy
nie loguje się przez UI, istnieje wyłącznie jako podmiot tokena.

### 2. Token: persystowany hash, nie sekret

`AgentToken(agent_user_id, owner_user_id, token_hash UNIQUE, scope_json,
expires_at, revoked_at?, last_used_at?)`. **Raw bearer token nigdy nie trafia do
DB** — kolumna trzyma `hash_agent_token(raw)` = `"sha256:" + sha256(raw).hexdigest()`
(`app/security.py`). Surowy token zwracany jest **dokładnie raz**, w odpowiedzi
`POST /agent_tokens` (`AgentTokenCreated.token`); odczyt po fakcie jest niemożliwy.
Rozdział `agent_user_id` (tożsamość, której token używa) od `owner_user_id`
(człowiek, który token utworzył i może go cofnąć) daje czytelny audyt i scoping
własności.

### 3. Scope jako JSON-set, `*` lub konkretne

`scope_json` = `{"<scope>": true, ...}` (sort_keys dla stabilnego round-tripu).
Walidacja przy tworzeniu (`agent_tokens._validate_scopes`): regex
`^(?:\*|[a-z][a-z0-9_.:-]{0,63})$` + `fullmatch` (odrzuca wielkie litery, spacje,
trailing `\n`; kwantyfikator ograniczony → brak ReDoS), dedup z zachowaniem
kolejności, limit 20, **wildcard-exclusivity** (`*` nie łączy się z konkretnym
scope). Weryfikacja runtime (`security._scope_allows`): `"*" in scopes or
scope_name in scopes`. Read-side (`_parse_agent_scopes`) i write-side
(`_scope_json`/`_scopes_from_json`) to świadomie **rozdzielone, lustrzane** pary
helperów w dwóch modułach — nie ma współdzielonego helpera do re-użycia
(jeśli rozjadą się w przyszłości, scalić).

### 4. `require_agent_scope(scope_name)` — dependency dla B4/MCP

Factory FastAPI dependency (`app/security.py`). Na każdym chronionym endpoincie:
wyciąga `Authorization: Bearer <raw>`, hashuje, lookup po **unikalnym**
`token_hash` (jeden indeksowany SELECT), odrzuca brak/wygasły/cofnięty token
(401) oraz token przypięty do nie-agentowego usera (401), brak scope → 403.
Czas porównywany w **naiwnym UTC** (`datetime.now(UTC).replace(tzinfo=None)`) —
spójnie z `expires_at`. Zwraca lekki, frozen `AgentPrincipal(agent_user_id,
owner_user_id, token_id, scopes)` zamiast ORM-usera. `get_current_user()` i UI
auth pozostają nietknięte (ścieżki rozdzielone).

### 5. Audyt bez sekretów (`AgentAuditLog`)

Każde użycie scope'a (`_authenticate_agent`) i każda operacja zarządzania
(`agent_tokens._audit_token_management`: `create`/`revoke`) zapisuje wiersz
`AgentAuditLog(user_id=owner, agent_user_id, route, params_json)`. `params_json`
**redaguje** wartości, których klucz zawiera `authorization`/`token`/`password`/
`secret`/`api_key`/`apikey` (`_redacted_mapping`) → audyt nigdy nie zawiera raw
tokena ani innego sekretu z query/path params. `last_used_at` aktualizowane przy
udanej autentykacji (transakcyjnie z zapisem audytu; przy błędzie rollback).

### 6. Endpointy zarządzania — owner-scoped self-service

`app/routers/agent_tokens.py` (zarejestrowany w `app/main.py` +
`app/routers/__init__.py`), auth przez istniejące cookie-session
`get_current_user()`:

- `POST /agent_tokens` (201) — mint: przed wygenerowaniem raw sekretu egzekwuje
  limit 20 aktywnych tokenów ownera (aktywne = `revoked_at IS NULL` i
  `expires_at > now`; przekroczenie → 409, bez utworzenia agenta/audytu), potem
  tworzy `User(role=agent)` z losowym hasłem + `AgentToken`; zwraca raw token raz.
  Transakcja: `add_all` + `flush` (id do audytu) → audyt → pojedynczy `commit`
  (kolizja unikalnej nazwy agenta = wyjątek, nic nie zacommitowane).
- `GET /agent_tokens` — lista tokenów filtrowana po `owner_user_id`, `response_model`
  bez pola `token`.
- `DELETE /agent_tokens/{id}` — revoke własnego tokena; `WHERE id AND owner_user_id`
  → cudzy = **404** (nie 403 — brak oracle istnienia); idempotentny (drugi revoke
  nie nadpisuje `revoked_at` ani nie dubluje audytu).

### 7. Brak Alembic

Tabele `agent_tokens`/`agent_audit_logs` i kolumna `users.role` powstają
addytywnie przez `Base.metadata.create_all` + ręczny `_migrate_schema` (`db.py`),
spójnie z ADR-0050. Zero migration churn dla istniejącej `data/szop.db`.

## Konsekwencje

- **B4 API odblokowane po stronie tożsamości** — endpointy bitew mogą żądać
  `Depends(require_agent_scope("battle:write"))` itd.; gracz-człowiek dalej przez
  cookie-session. Konwencja nazw scope (`battle:read`/`battle:write`/…)
  doprecyzowana przy podpięciu pierwszego konsumenta.
- **Jeden audit trail** dla działań agentów (zgodne z decyzją strategiczną „MCP
  agent = klient HTTP, jeden mechanizm uprawnień, jeden audit trail").
- **MCP server (C1)** używa raw tokena jako bearer przez `szop_client` HTTP — nie
  łączy się z DB bezpośrednio.
- **Runtime RAG (C2.6)** używa osobnego scope `rules:search` dla agent-only
  `POST /rules/search`. Generyczny audit zapisuje route/metodę/status
  `authorized` i bezpieczne path/query params, ale celowo nie czyta body, więc
  treść query nie trafia do `AgentAuditLog`.
- **Odroczone (poza tym ADR):** UI zarządzania tokenami; czasowe rate-limit
  requestów endpointu mintowania; redakcja sekretów z **body** requestu (gdy
  kiedyś trafi do `params_json`); CSRF/UX potwierdzeń jeśli włączymy CORS lub UI;
  consent-gated writes (ADR-0024).

## Alternatywy odrzucone

- **Reuse cookie-session dla agentów** — odrzucone: agent to proces bez przeglądarki;
  bearer token jest bezstanowy, łatwy do cofnięcia i nie miesza się z sesją UI.
- **Persystencja raw tokena (np. szyfrowanego)** — odrzucone: hash sha256 wystarcza
  do weryfikacji, a niemożność odczytania sekretu z DB ogranicza skutki wycieku bazy.
- **Scope jako CSV/string** — odrzucone na rzecz JSON-set: `*`-wildcard, dedup i
  stabilny round-trip (sort_keys) są czytelniejsze i odporne na duplikaty.
- **Brak osobnej roli (flaga `is_agent`)** — odrzucone: `role` enum skaluje się na
  `admin` i przyszłe role bez mnożenia kolumn boolowskich; `is_admin` zostaje dla
  wstecznej kompatybilności UI w tym slice.
