# ADR-0060 — Serwerowa propozycja bota i trwała próba

- **Status:** Accepted
- **Data:** 2026-11-25
- **Kontekst:** P2 po P1 i P6 na `b2dcb2b`. Użytkownik zaakceptował kontrakt 2026-11-25 do realizacji P3/P4.

## Decyzja

Właściciel strony istniejącej bitwy może zlecić z zalogowanej przeglądarki
jedną decyzję `priority` dla znanego checkpointu v1. Serwer przygotuje co
najwyżej jedną zwykłą propozycję `battle:action` w stanie `pending` na próbę.
Osobne zatwierdzenie przez właściciela nadal wykonuje akcję przez istniejący
mechanizm. Producent korzysta z fabryki i zawężenia obsługiwanych sytuacji D6.2,
bramki P1, kodeka i wspólnego przygotowania akcji. Weryfikuje ten sam zapisany
checkpoint przed wyborem i podczas przygotowania propozycji. Symulacja
walidacyjna używa kopii RNG. Zakres D6.2 pozostaje wystarczający do pierwszego
kroku w UI. [Adapter D6.2](../boty-connect.md) · [P1](../play-vs-ai-plan.md#wynik-p1) · [ADR-0024](0024-consent-gated-agent-writes.md) · [ADR-0054](0054-atomic-http-battle-actions.md)

## Tożsamość, autoryzacja i przeglądarka

- Źródłem tożsamości jest podpisana sesja właściciela. Robocza tożsamość konta
  to `(user_id, users.created_at)`, gdzie `created_at` oznacza utworzenie
  aktualnego rekordu użytkownika. Dla nowych operacji P4 logowanie i rejestracja
  zapisują w sesji także ten znacznik. Serwer sprawdza go względem rekordu konta
  oraz dopuszcza role `user` i `admin` jako zwykłych uczestników. Starsza sesja
  wymaga ponownego logowania do tej funkcji. Sama rola admina nie daje dostępu
  do cudzej strony. Nagłówek `Authorization` skutkuje 401 również przy podanym
  cookie. Dotychczasowe tworzenie propozycji tokenem zachowuje oba scope'y
  `battle:read` i `agent_proposals:create`. [Sesja](../../app/security.py) · [Logowanie i rejestracja](../../app/routers/auth.py) · [ADR-0025](0025-agent-scoped-tokens.md)
- Na obu nowych ścieżkach uczestnictwo wynika z `Battle.p1_user_id` lub
  `p2_user_id`; P0 odpowiada `p1_user_id`, P1 odpowiada `p2_user_id`.
  Bitwa musiała powstać w czasie życia bieżącego rekordu konta
  (`Battle.created_at >= User.created_at`), ponieważ przypisanie uczestników
  następuje przy tworzeniu bitwy. To wyklucza dostęp przez zachowane numeryczne
  ID uczestnika sprzed ponownego użycia ID konta.
  `POST` wymaga, aby zlecający kontrolował deklarowaną stronę, a przy nowej
  próbie wymaga również zgodności z bieżącą aktywną stroną checkpointu.
  `GET` sprawdza ponownie dostęp i kontrolę zapisanej strony. Przypadek
  wspólnego właściciela obu stron dopuszcza nową próbę dla aktywnej strony.
  Brak bitwy, cudza bitwa, cudza strona i cudza próba dają ten sam JSON 404.
  Własna nieaktywna strona przy zgodnym headzie daje `no_proposal` z powodem
  `unsupported_context`. Zmiana headu daje `stale` przed oceną aktywnej strony.
  [Model bitwy i propozycji](../../app/models.py) · [Tworzenie bitwy](../../app/services/battle_creation.py) · [Ścieżka uczestnika i przygotowanie](../../app/services/battle_actions.py)
- W propozycji serwerowej `owner_user_id` i wymagany `agent_user_id` wskazują
  autora zlecenia, a `token_id=NULL` oznacza brak użycia wiersza `AgentToken`.
  Nowa, nullable kolumna `producer_owner_created_at` równa generacji tego konta
  identyfikuje pochodzenie serwerowe bez zmiany znaczenia historycznego NULL
  w `token_id`. Dotychczasowy `action="battle:action"`, kanoniczny
  `payload_json` i publiczny format `AgentProposalPublic` pozostają takie same.
  Podsumowanie tworzy serwer z nazwy producenta i typu decyzji w obecnym limicie
  500 znaków. Audyt `create` zapisuje właściciela, autora, brak tokena, oznaczenie
  `server/priority-v1`, identyfikatory bitwy i propozycji, head oraz digest
  próby. Zatwierdzenie nadal audytuje osobnego wykonawcę i rezultat.
  Nagłówki, ciasteczka i pełne wejście pozostają poza audytem.
  [Kolumny i FK](../../app/models.py) · [Serializacja i audyt propozycji](../../app/routers/agent_proposals.py)
- Dla wierszy z `producer_owner_created_at` istniejące listowanie, odczyt,
  zatwierdzenie i odrzucenie porównują generację właściciela z aktualnym kontem
  i sesją. Po niezgodności pomijają wiersz w liście i zwracają zwykłe 404
  na trasach konkretnej propozycji. Pochodzenie zostaje po wyczyszczeniu
  tabeli prób. Egzekwowanie własności żywego konta jest konieczne przy SQLite bez
  aktywnych FK. Samo podobieństwo numerycznego ID po odtworzeniu konta nie
  daje dostępu. Wiersze z NULL w nowej kolumnie zachowują dotychczasową obsługę.
- Nowy `POST` i istniejące `approve`/`reject` dla serwerowych wierszy wymagają
  pojedynczego `Origin` równego skonfigurowanemu publicznemu originowi UI
  (schemat, host, efektywny port, bez ścieżki). Brak, `null`, wielokrotny
  lub obcy origin daje 403 przed zapisem. Nowy `POST` akceptuje wyłącznie
  `application/json` w UTF-8. CORS dla tych operacji pozostaje wyłączony.
  Odczyt `GET` jest bezskutkowy i nie wymaga nagłówka `Origin`.
  Odpowiedzi API mają `Cache-Control: private, no-store`. Przy kanonicznym
  URL brak sesji daje JSON 401, a klient odrzuca wszystkie przekierowania.
- Konfiguracja wdrożenia ustala jeden zewnętrzny origin HTTPS, także za
  Tailscale lub Caddy. Wartość do porównania pochodzi z konfiguracji serwera.
  `Host` i nagłówki przekazywane przez proxy nie poszerzają akceptowanych
  originów. Nowa funkcja jest dostępna dla jawnie skonfigurowanej
  instancji z bezpiecznym ciasteczkiem (`SESSION_HTTPS_ONLY=true` na HTTPS);
  wyjątek deweloperski wymaga jawnego originu loopback. Istniejące
  `SameSite=Lax` i `TrustedHostMiddleware` stanowią dodatkowe warstwy.
  [Middleware](../../app/main.py) · [Warianty wdrożenia](../../DEPLOY.md) · [Konfiguracja proxy](../../Caddyfile)

## Operacje i kanoniczne polecenie

Nowe operacje używają jednego adresu zasobu
`/battles/{battle_id}/bot-proposal-attempts/{attempt_id}`.
`POST` rejestruje próbę, `GET` zwraca zapisany wynik. Adres jest względny wobec
tego samego originu. Przeglądarka tworzy ID po świadomym kliknięciu i zachowuje
ID oraz niezmienione polecenie do uzgodnienia wyniku. Format to trzynastocyfrowa
liczba milisekund UTC od epoki, myślnik i mały kanoniczny UUIDv4. P5 może użyć
`Date.now()` i `crypto.randomUUID()`. Użycie tego samego ID obejmuje każde
ponowienie, również z drugiej karty, jeśli karta otrzymała zapisaną próbę.

`battle_id` w ścieżce jest dziesiętną liczbą całkowitą od 1 do
`9007199254740991` w zapisie bez zbędnych zer. Treść JSON ma poniższe sześć
obowiązkowych pól. `schema_version` i `protocol` to liczba całkowita 1,
`kind` to dokładnie `priority`, `side` to całkowite 0 lub 1.
`expected_sequence` jest nieujemną bezpieczną liczbą całkowitą JS,
a `seed` mieści się w zakresie `[-9007199254740991,9007199254740991]`.
Pola dodatkowe, zduplikowane klucze i typy takie jak bool, string i float
w polach całkowitych kończą się 422. Limit treści nowego polecenia to 1 KiB.

```http
POST /battles/42/bot-proposal-attempts/1795572300000-550e8400-e29b-41d4-a716-446655440000
Origin: https://szop.example
Content-Type: application/json
```

```json
{"schema_version":1,"side":0,"kind":"priority","seed":19,"protocol":1,"expected_sequence":37}
```

Serwer dołącza `attempt_id`, `battle_id`, `owner_user_id` i
`owner_created_at` z adresu i autoryzacji. Hash to SHA-256 z UTF-8 zwartego
JSON z kluczami posortowanymi leksykograficznie, ASCII i bez końcowego LF,
z dziesiętnymi liczbami bez części ułamkowej. Czas generacji ma format UTC
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Poniższy kanon pokazuje bajty wejściowe
SHA-256 dla przykładowego właściciela 7.

```json
{"attempt_id":"1795572300000-550e8400-e29b-41d4-a716-446655440000","battle_id":42,"expected_sequence":37,"kind":"priority","owner_created_at":"2026-09-01T12:00:00.000000Z","owner_user_id":7,"protocol":1,"schema_version":1,"seed":19,"side":0}
```

Udany pierwszy zapis zasobu zwraca 201 i względny `Location` tego samego
adresu. `GET` i ponowiony autoryzowany `POST` w oknie przyjmowania zwracają
200 oraz tę samą reprezentację zapisanego wyniku. Wszystkie pola tej
reprezentacji są wymagane. `created_at` i `expires_at` są w UTC ISO 8601,
`reason` jest kodem albo null, `proposal_id` jest identyfikatorem albo null.

```json
{
  "schema_version": 1,
  "attempt_id": "1795572300000-550e8400-e29b-41d4-a716-446655440000",
  "battle_id": 42,
  "status": "proposal_created",
  "reason": null,
  "proposal_id": 681,
  "expected_sequence": 37,
  "actual_sequence": 37,
  "created_at": "2026-11-25T02:05:02Z",
  "expires_at": "2026-11-26T02:05:00Z"
}
```

| Status zapisanej próby | Powód i odniesienia |
|---|---|
| `proposal_created` | `reason=null`, ID jednego `pending` utworzonego w tej samej transakcji. `actual_sequence` równa oczekiwanej. |
| `stale` | `reason="head_changed"`, `proposal_id=null`, aktualna sekwencja różna od oczekiwanej. |
| `no_proposal` | `proposal_id=null`; zamknięty zestaw przyczyn `unsupported_protocol`, `checkpoint_unavailable`, `unsupported_context`, `no_candidate`, `unsupported_action` i `invalid_action`. `actual_sequence` to zweryfikowana sekwencja lub null, gdy brak zgodnego bieżącego checkpointu. |

Status próby opisuje wynik **utworzenia**. Bieżący status propozycji czyta się
z istniejącego zasobu `GET /agent_proposals/{proposal_id}`; może się zmienić na
`executed`, `rejected` lub `stale` w zwykłym przepływie. Kontrakt
`AgentProposalPublic` utrzymuje ten sam kształt, a istniejący klient tokenowy
nadal wysyła dedykowany POST z kanonicznym wire akcji. [Klient HTTP](../../szop_client/http.py) · [Adapter D6.2](../../szop_client/bot_proposals.py)

Odmowy HTTP mają format `{"detail":{"code":"..."}}` i pomijają treść
żądania. Przy powtórzeniu ID z innym seedem API zwróci HTTP 409.

```json
{"detail":{"code":"attempt_payload_conflict"}}
```

| HTTP | Kod i warunek |
|---|---|
| 401 | `owner_session_required` dla braku/niezgodności zalogowanego konta lub poświadczeń bearer. |
| 403 | `origin_rejected` dla zabronionego originu zapisu. |
| 404 | `not_found` dla obcych lub brakujących zasobów, niezatwierdzonej lub usuniętej próby przy odczycie. Wyłączona funkcja pozostaje niedostępna. |
| 409 | `attempt_payload_conflict` dla istniejącego ID i innego kanonu w obrębie autoryzowanego konta. |
| 410 | `attempt_expired` przy POST z ID poza oknem przyjmowania po sprawdzeniu uczestnictwa i strony. |
| 413, 415, 422 | Odpowiednio `command_too_large`, `unsupported_media_type`, `invalid_command` (w tym wadliwe ID lub czas nadmiernie przyszły). |
| 503 | `attempt_temporarily_unavailable` przy wyczerpanym czasie oczekiwania na SQLite lub przejściowym błędzie. Stan zatwierdzenia może wymagać uzgodnienia. |

## Trwały zapis i retencja

1. Próba ma unikat `(owner_user_id, owner_created_at, attempt_id)`. Wiersz
   zawiera ID bitwy, stronę, kanoniczne polecenie i jego digest, zapisany
   niezmienny wynik, `created_at`, `expires_at` oraz nullable, unikalne
   `proposal_id` z FK do `agent_proposals.id ON DELETE RESTRICT`.
   Identyfikatory konta i bitwy w próbie są historycznymi wartościami bez
   kaskady kasowania. Ich żywe odpowiedniki sprawdza zapytanie dostępu.
   Osobny indeks po `created_at` daje porządek retencji. Do wygaśnięcia
   rejestru aplikacja zachowuje powiązany wiersz propozycji, także na SQLite
   bez egzekwowania FK. Usunięcie konta lub bitwy odcina dostęp i nie zwalnia
   klucza tej samej generacji konta.
2. W SQLite `POST` zaczyna transakcję zapisu `BEGIN IMMEDIATE` przed odczytami
   konta, bitwy, próby i checkpointu. Podpis sesji, Origin i kształt polecenia
   są sprawdzane przed wejściem w transakcję, tożsamość oraz dostęp w transakcji.
   Transakcja rozstrzyga kolejno uprawnienia, okno ID, istniejącą próbę lub
   nowy head oraz wynik. Dla istniejącego klucza porównuje digest i kanon
   otrzymanego polecenia z zapisanymi wartościami. Przy zgodności zwraca
   zapisany wynik, nawet jeśli head później się zmienił.
   Dla nowej próby jest najwyżej jeden odczyt checkpointu przez wspólny
   loader, najwyżej jeden wybór i próba walidacji w tym samym kontekście.
   Kod planera jest ograniczony do `priority`, z zasobami w pamięci.
   Blokada SQLite obejmuje też ten wybór, więc pomiar obejmuje czas jej
   utrzymania. Oczekiwanie na blokadę trwa najwyżej 2 s, potem klient dostaje
   503. Przez SQLite idzie jedna transakcja niezależnie od liczby procesów
   aplikacji. Adaptera do innej bazy nie obejmuje pierwszy etap.
3. Wynik, opcjonalna propozycja i jej wpis audytu są zatwierdzane atomowo.
   Awaria przed commitem wycofuje cały zapis, a kolejne żądanie może obliczyć
   wynik od nowa dla zachowanego polecenia. Po commicie kolejny proces
   zwraca spójny wynik bez ponownego wyboru ani drugiego wpisu audytu
   `create`. Dwa równoległe żądania tego samego ID rozstrzygają się przez
   SQLite i unikat, także po restarcie procesu. Różne ID to odrębne zamiary.
   Odpowiedź powstaje z zatwierdzonego wyniku. Do utworzenia propozycji
   stosuje się ścieżkę przygotowania, do akceptacji istniejący atomowy
   zapis z CAS headu. [Aktualne przygotowanie i zapis](../../app/services/battle_actions.py)
4. `expires_at = czas z ID + 24 h`. Serwer sprawdza swoje UTC po uzyskaniu
   transakcji: dopuszcza przyszłą datę ID do 2 minut i wyłącznie
   `now < expires_at`. Przedział ustala możliwość POST także bez wiersza
   w bazie. Zmiana daty w ID tworzy inne ID. Zapisany wynik jest dostępny
   przez `GET` przez 30 dni od `created_at` pod warunkiem utrzymania dostępu.
   Później `GET` zwraca 404 także przed porządkiem retencji. Po upływie
   30 dni zadanie porządkowe może usunąć sam rejestr w ograniczonych
   partiach po indeksie czasu. Wygasłe ID nadal zwraca 410 na POST, także
   po usunięciu wpisu. Retencja propozycji, zdarzeń bitwy i standardowego
   audytu należy do ich odrębnych ścieżek. Gwarancja deduplikacji odnosi się
   do ciągłej, spójnej bazy, a plan backupu przenosi rejestr i propozycje
   z tym samym snapshotem.

## Uzgadnianie przez klienta

Przed wysłaniem klient zapisuje lokalnie minimalne odniesienie próby z
zamrożonym poleceniem. Przestrzeń zapisu jest przypisana do generacji konta
oznaczonej przez zalogowany widok. Brak
odpowiedzi, timeout, 503 lub nieoczekiwana odpowiedź skutkują odczytem po tym
samym ID. 404 może oznaczać trwający zapis. Klient może na wyraźne polecenie
powtórzyć dokładnie ten sam POST przed upływem terminu. Po 410 szuka zapisanego
wyniku przez GET. Zakończenie oczekiwania w UI, zmiana widoku lub anulowanie
żądania w przeglądarce nie cofa zatwierdzenia przez serwer. Przed wysłaniem
anulowanie zamyka próbę lokalnie. Po wysłaniu klient uzgadnia wynik i pozwala
użyć istniejącego odrzucenia, gdy propozycja jest `pending`. Po odświeżeniu
domyślną akcją jest odczyt, po powrocie z innego konta wpis klienta jest
niedostępny. `stale` wymaga odczytania nowego headu przed kolejnym świadomym
kliknięciem. P5 używa istniejącego panelu zgody. [Panel](../../app/static/js/modules/agent_proposals.js)

## Migracja i odbiór

P3 dodaje tabelę prób i indeksy przez `Base.metadata.create_all` oraz nullable
`producer_owner_created_at` przez `_migrate_schema` dla wcześniejszych SQLite.
Stare `pending`, audyty i klienci zachowują format. Świeża baza deklaruje te
same klucze i indeksy z modelu. P3 weryfikuje zapis i wyścigi bez uruchamiania
producenta. P4 wprowadza opisane operacje, pochodzenie i uprawnienia.
[Migracje](../../app/db.py) · [Plan P3–P5 i budżety](../play-vs-ai-plan.md#p3-trwała-deduplikacja-tworzenia-v1)

| Obszar | Warunek odbioru P3/P4 |
|---|---|
| Atomowość | Dwa procesy lub połączenia, ten sam klucz z tym samym i innym payloadem, bariera przed/po commicie, restart, błąd audytu, zajęta baza i timeout po commicie. Dokładnie jedna propozycja i jeden audyt `create` przy `proposal_created`. Zero eventów i trwałych zmian RNG przy utworzeniu i ponowieniu. |
| Własność | Obcy uczestnik, obca strona, cudzy klucz, próba z unieważnionej generacji sesji i konta o ponownie użytym ID. Świeża sesja nowego konta z tym samym ID nie odzyskuje przydziału strony dawnej bitwy. Właściciel obu stron działa dla aktywnego P0/P1. Brak oracle przy istniejącym kluczu. Cookie bez claimu, bearer z/bez cookie, brak/obcy Origin, inny host za proxy, typ i limit treści. |
| Kompatybilność | Świeża i stara migrowana SQLite, dwukrotna migracja, stary tokenowy create, stare pending, istniejące list/GET/approve/reject. Powtórne zatwierdzenie serwerowej propozycji korzysta z dotychczasowej idempotencji. Brak mutacji bitwy przed zgodą. |
| Integracja | Trzy dodatnie przypadki D6.2, zły v1/head, odrzucenie nieobsługiwanego kontekstu i typu akcji, brak kandydata, zmiana aktywnej strony przed utworzeniem i wyścig zmiany headu przed akceptacją. Uzgodnienie utraconej odpowiedzi, odczyt po 404 w locie, wygaśnięcie, purge i ponowienie tego samego ID. |

W P3/P4 potwierdzamy 15 SELECT istniejącego D6.2 (4 + 5 + 6) i zero SQL
samego wyboru na tej samej fixture. Dla dodanej operacji rejestrujemy osobną
bazę jednego serwerowego requestu z tym samym przygotowaniem i owner lookup.
K ogranicza narzut zapisu próby do 2 dodatkowych SELECT, ze stałą liczbą
odczytów przy wzroście jednostek. Osobno mierzymy INSERT, czas blokady i p95
requestu względem bazy (K: +20% +10 ms). V mierzy p95 wyboru na seedach 0–99
przy 2 i 12 jednostkach (odpowiednio ≤100 ms i ≤500 ms), bez I/O. P2
weryfikuje wyłącznie dokumentację. [Pomiar D6.2](../boty-connect.md) · [Budżety i wynik P1](../play-vs-ai-plan.md)

## Rozważana alternatywa

Można rozbudować obecny POST tokenowy o trwałą próbę i pozostawić decyzję po
stronie posiadacza tokena. D6.2 nadal służy takim klientom. Do pierwszego
przepływu w przeglądarce zatwierdzono producenta ograniczonego do sesji
właściciela. Zachowuje jednoznaczne źródło zlecenia bez wydawania bearer tokena
przeglądarce. Wybór obejmuje przedstawione API, pochodzenie, zasady sesji
i 30-dniową retencję. Wdrożenie rozpoczyna się od P3.
