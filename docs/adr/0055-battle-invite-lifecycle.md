# ADR-0055 — Trwały lifecycle zaproszenia do bitwy

- **Status:** Accepted
- **Data:** 2026-07-19
- **Kontekst:** Strumień B2.1; schema przed endpointami B4 invite/accept

## Problem

Minimalny tuple roadmapy `BattleInvite(from_user_id, to_user_id?, roster_id,
scenario, status, expires_at)` opisuje wejście do procesu, ale nie utrwala jego
wyniku. Bez trwałego powiązania ponowiona lub równoległa akceptacja nie może
jednoznacznie odtworzyć acceptora, jego rozpiski i utworzonej bitwy. Szczególnie
open invite (`to_user_id IS NULL`) nie ma z góry znanego drugiego uczestnika.

Endpointy nie są częścią tego etapu, lecz ich bezpieczna implementacja nie może
wymagać późniejszej zmiany schematu.

## Decyzja

### 1. Addytywna tabela i stabilne statusy

Dodajemy `BattleInvite(TimestampMixin, Base)` w tabeli `battle_invites`.
Status pozostaje bounded stringiem, bez migracyjnego typu Enum. Publiczne stałe
domenowe i stabilny tuple obejmują dokładnie:

- `pending`;
- `accepted`;
- `declined`;
- `expired`.

Tabela przechowuje:

- niezmienne dane wejściowe procesu: `from_user_id`, opcjonalne `to_user_id`,
  `roster_id`, `scenario` (`VARCHAR(100)`) i `expires_at` w konwencji naive UTC;
- `status` (`VARCHAR(20)`, domyślnie `pending`);
- nullable result linkage: `accepted_by_user_id`, `accepted_roster_id` i
  `battle_id`;
- `created_at` i `updated_at` z istniejącego `TimestampMixin` oraz listenera.

Nowa tabela powstaje przez istniejące `Base.metadata.create_all`. Nie dodajemy
ręcznego `ALTER` do `_migrate_schema` ani Alembic, ponieważ nie zmieniamy żadnej
istniejącej tabeli.

### 2. Inwariant pojedynczego wyniku w bazie

Nazwane constrainty DB wymuszają:

- status należący do dokładnie czterech wartości;
- direct invite nie może wskazywać zapraszającego jako celu; `to_user_id IS
  NULL` pozostaje legalnym open invite;
- `accepted` ma komplet trzech pól wyniku;
- każdy pozostały status ma wszystkie trzy pola wyniku puste;
- `battle_id` jest unikalny, więc jedna `Battle` nie może być wynikiem dwóch
  zaproszeń.

Constrainty sprawdzają końcowy stan wiersza, dlatego przyszły atomowy `UPDATE`
może jednocześnie ustawić `status=accepted` i pełny result linkage. Nie
walidujemy w CHECK własności rosterów, czasu ściennego ani rejestru scenario;
te zależności wymagają bieżącego principalu i transakcji serwisu.

### 3. Zamrożony cykl życia

- Stan początkowy to `pending`.
- Dane zapraszającego, celu, jego rosteru, scenario i expiry są po utworzeniu
  niemutowalne na poziomie przyszłego serwisu.
- Dozwolone przyszłe przejścia to wyłącznie `pending -> accepted`, `pending ->
  declined` albo `pending -> expired`. Stany terminalne nie są ponownie
  otwierane.
- Direct invite może zaakceptować wyłącznie `to_user_id`.
- Open invite wiąże pierwszego skutecznego acceptora w
  `accepted_by_user_id`.
- Acceptor dostarcza własny `accepted_roster_id`, a wynikiem jest dokładnie
  jedna `Battle` wskazana przez `battle_id`.
- Wygaszenie ocenia przyszły serwis względem `expires_at`; schema nie zawiera
  dynamicznego constraintu zależnego od zegara.

### 4. Przyszła akceptacja: jedna transakcja i CAS

Następny osobny etap zaimplementuje accept jako jedną transakcję z warunkowym
przejściem ze stanu `pending`. Transakcja zweryfikuje principal, ownership obu
rosterów, target/open semantics i expiry, utworzy jedną `Battle`, po czym ustawi
pełny result linkage. Równoległy przegrany CAS nie utworzy trwałego drugiego
wyniku. Ponowiona accept po wcześniejszym sukcesie zwróci `battle_id` zapisane
w invite zamiast tworzyć kolejną bitwę.

### 5. Indeksy

- `(to_user_id, status, expires_at)` obsługuje bounded incoming/direct oraz
  open-pending lookup;
- `(from_user_id, status, created_at)` obsługuje outgoing/history;
- unikalność `battle_id` jest indeksem lookupu wyniku.

Nie dodajemy eager relationships ani pojedynczych indeksów dla każdego FK bez
potwierdzonego patternu zapytań.

## Nota implementacyjna B4.1 — create endpoint (2026-07-19)

Addytywny `POST /battles/invite` realizuje wyłącznie stan początkowy tego ADR.
Sesja użytkownika działa jako własny `from_user_id`, a bearer wymaga osobnego
scope `battle:invite` i mapuje się na ownera tokenu. Transakcyjnie neutralny
`app/services/battle_invites.py` waliduje owner-scoped roster, canonical scenario
z `MAP_BUILDERS` oraz opcjonalny direct target (bez self i kont agentów), po czym
robi `flush()` jednego `pending` invite. Router wykonuje commit albo rollback,
mapuje missing/foreign na wspólne no-oracle 404, unknown scenario na stałe 422,
a race/`IntegrityError` na stałe 409.

Create response nie publikuje result linkage ani relacji ORM. Każdy poprawny
POST tworzy nowy rekord; B4.1 świadomie nie deklaruje idempotency ani
deduplikacji, ponieważ schema nie ma odpowiedniego constraintu, klucza
idempotency ani rate-limit infrastruktury. Accept/decline/expiry/discovery i
tworzenie `Battle` pozostają poza tym dodatkiem i nie zmieniają zamrożonej
decyzji lifecycle.

## Konsekwencje

- B4.1 dodało `POST /battles/invite`; przyszłe
  `POST /battles/invite/{id}/accept` nie wymaga kolejnej zmiany schematu.
- Open invite ma trwałą tożsamość pierwszego skutecznego acceptora.
- Baza blokuje częściowo zaakceptowane rekordy i wielokrotne powiązanie tej
  samej bitwy, ale autoryzacja i własność pozostają odpowiedzialnością warstwy
  serwisów create/accept.
- `decline`/`expiry` endpointy oraz discovery open invites nie należą do
  obecnego minimum B4, lecz schema ich nie blokuje.
- Pierwotny slice schematu nie implementował endpointów; nota B4.1 dodaje tylko
  create. Serwis akceptacji, klient HTTP/MCP i UI pozostają otwarte.

## Alternatywy rozważone

- **Tylko minimalny tuple roadmapy** — odrzucone, bo po sukcesie nie daje
  idempotentnego odczytu wyniku ani tożsamości acceptora open invite.
- **Enum bazodanowy** — odrzucone, bo projekt używa SQLite/create_all bez
  Alembic, a bounded string + CHECK zachowuje prostą addytywność.
- **Osobna tabela wyników akceptacji** — odrzucone jako zbędna relacja 1:1;
  nullable linkage jest puste w stanach niezaakceptowanych i kompletne w
  `accepted`.
- **CHECK oparty o bieżący czas lub ownership** — odrzucone, bo zegar i
  uprawnienia są kontekstem transakcji, nie statyczną własnością wiersza.
