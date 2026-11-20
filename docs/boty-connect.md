# D6.2 — ograniczony adapter propozycji bota

Data: 2026-11-20. Baza: `c6aebca36118a4d945d0e1e84a994ff4e132c2a1`,
`Faza_A`. Implementacja: [bot_proposals.py](../szop_client/bot_proposals.py),
regresje: [test_bot_proposals.py](../tests/test_bot_proposals.py).

Adapter łączy publiczny checkpoint z jedną decyzją istniejącego `priority`
i tworzy **pending proposal**. Zatwierdzenie jest osobną czynnością właściciela
w istniejącym panelu propozycji. Dopiero serwerowe zatwierdzenie wykonuje akcję.

## Decyzja i zakres

Koordynator przyjął minimalny tryb rekomendowany w
[D6.1](boty-audit.md#minimalny-tryb-i-prerekwizyty-d62): **priority, jawny seed,
publiczny v1, jeden krok, akcje niebojowe**. Nie wymaga to nowego uprawnienia
ani kontraktu publicznego. To zakres tego etapu, nie pełna gra z botem.

Obsługiwane są wyłącznie faktycznie wybrane przez `priority`:

- `ManeuverAction` — Manewr, [Rozjemca pkt 14.a i 15](../app/static/docs/SZOP_Rozjemca.md);
- `DefendAction` — Mobilizacja, [pkt 14.b i 22.c](../app/static/docs/SZOP_Rozjemca.md);
- `SpecialAction(ability_slug="discard_exhausted", payload={})` dla
  Wyczerpanego, [pkt 14.e i 22.a.ii](../app/static/docs/SZOP_Rozjemca.md).

`SUPPORTED_KINDS` jest zawężeniem kanonicznego rejestru, konstrukcja deleguje
do `factory.make_player(kind, decision_seed)` z nową instancją na próbę.
Seed jest wymagany również dla obecnie deterministycznego `priority`.
Nieznana nazwa, alias `claude`, zmiana wielkości liter i inne rodziny
zwracają jawny brak propozycji. Nie ma domyślnego zastąpienia rodziny/akcji.

Gate dopuszcza tylko:

- zgodne identyfikatory bitwy, metadata protocol v1 i checkpoint v1;
  równy head sequence i numer rundy z dwóch kolejnych odczytów;
- status active, nieterminalną rundę 1–4 i jawną perspective równą
  active_player; bez trwałej aktywacji/initiative v2/v3;
- aktora żywego, na Froncie, kontrolowanego przez tę perspective i bez
  Aktywowany; ograniczenia aktywacji/lokalizacji opisują
  [pkt 11.a, 22.d.i i 26](../app/static/docs/SZOP_Rozjemca.md);
- profile wszystkich jednostek bez pasywów, hero, ability overrides,
  zdolności broni i attack-quality override; brak pending effects,
  pending interrupts, zapisanych użyć przerwań, pending wounds i damage balance;
- statusy wyłącznie Aktywowany/Przygotowany/Wyczerpany; Aktywowany nie może
  należeć do wybranego aktora. Przyszpilony i nieznane statusy są odrzucone;
- **jawnie pusty terrain**, skończone pozycje i dodatnie skończone promienie.
  Nie obsługujemy żadnego terenu w tym pierwszym trybie, w tym Niebezpiecznego.

Gate jest celowo węższy od silnika. Przyszpilony nie może wykonywać Manewru
([pkt 22.b.i](../app/static/docs/SZOP_Rozjemca.md)); znany drift mutex
Przyszpilony/Przygotowany przy Mobilizacji jest opisany w D6.1. Ruch przez
Niebezpieczny rozpatruje [pkt 4.c.v](../app/static/docs/SZOP_Rozjemca.md),
więc adapter nie uznaje samego bezpiecznego końca ruchu za dowód trasy.
Osiągalność Manewru pozostaje w istniejącym `ManeuverPlanner.can_reach`.
Serwer nadal jest SSOT pełnego owner/scope i walidacji wykonania.

Shoot/Charge, zdolności, rozstawienie, kontynuacje i przerwania oraz v2/v3
kończą się bez propozycji. Wybrany nieobsługiwany kandydat nie jest zastępowany
inną akcją. Nie poprawiano wspólnego silnika ani nie rozszerzano katalogu X.

## Użycie Python i CLI

Uruchom istniejącą aplikację. Token właściciela musi mieć dokładnie potrzebne
scope'y `battle:read` i `agent_proposals:create`; adapter nie potrzebuje
`battle:act`. Ustaw `SZOP_AGENT_TOKEN` lokalnie, bez zapisywania sekretu do Git.
Identyfikator bitwy i perspective wskaż jawnie.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m szop_client.bot_proposals --url http://127.0.0.1:8000 --battle-id 123 --perspective 0 --seed 19 --kind priority --timeout 10
```

CLI wykonuje jedną próbę i wypisuje bezpieczny JSON: outcome, code,
proposal_id, expected_sequence, action_type, decision_ms i http_status.
Exit 0 oznacza pending, 2 jawny brak propozycji/odrzucenie/niedostępny odczyt,
3 niepewny wynik wymagający rekoncyliacji. Token pochodzi wyłącznie ze
zmiennej środowiskowej. Timeout jest dodatni i skończony, per request;
nie jest globalnym SLA decyzji ani budżetem pętli. Adapter nie ma pętli.

```python
import os
from szop_client import HttpClient
from szop_client.bot_proposals import BotProposalAttempt

attempt = BotProposalAttempt(
    HttpClient("http://127.0.0.1:8000", token=os.environ["SZOP_AGENT_TOKEN"], timeout=10),
    battle_id=123, perspective=0, decision_seed=19, kind="priority",
)
result = attempt.run()
same_result = attempt.run()  # ten sam wynik; zero kolejnych requestów
```

`get_battle_metadata` i `get_state_checkpoint` są kolejnymi odczytami.
Stan i **expected_sequence pochodzą razem z checkpointu**. Różny head/runda
kończy krok kodem snapshot_changed; zgodność odczytów nie wyklucza późniejszego
wyścigu. Ostateczny CAS pozostaje na serwerze przy proposal i osobno approval.
Nie pobieramy profili z DB ani serwerowego checkpointu RNG.

## Ponowienia i rekoncyliacja

`BotProposalAttempt` jest jednostką jednorazowego wywołania. Lock i lokalny
wynik chronią przed powtórką, również concurrent run tej samej instancji.
W jednym kroku jest najwyżej jeden POST. 403/422, stale 409 i brak wsparcia
mają jawny wynik; błędy HTTP nie kopiują body ani tekstu wyjątku.

Timeout/zerwanie połączenia, 5xx lub niepoprawna odpowiedź po POST oznaczają
`uncertain / reconciliation_required`. Propozycja mogła już zostać zapisana.
Nie ma automatycznego retry, approval ani użycia nowego identyfikatora próby.

**Granica deduplikacji to jedna instancja w procesie.** Serwerowy endpoint
tworzenia nie udostępnia idempotency key/reuse. Nowa instancja, ponowne CLI
i restart procesu mogą utworzyć kolejną propozycję. Przed nimi po niepewnym
wyniku właściciel musi otworzyć istniejący panel propozycji lub owner-scoped
`GET /agent_proposals` / `GET /agent_proposals/{id}`, sprawdzić bitwę,
frozen expected_sequence/action i podsumowanie seed, a następnie rozstrzygnąć
istniejącą propozycję. Brak pozytywnej rekoncyliacji nie upoważnia do retry.
Odczyt po timeout nie jest automatycznym dowodem braku zapisu w locie.
Nie deklarujemy exactly-once między procesami.

Zatwierdzenie w istniejącym UI ponownie sprawdza właściciela, stronę i sequence.
Idempotencja ponownego approval jest odrębną własnością serwera; nie zmienia
granicy deduplikacji tworzenia propozycji. `stale` wymaga odczytania nowego
stanu i nowej jawnej decyzji po rozstrzygnięciu poprzedniej próby.

## Weryfikacja i koszt

59 nowych przypadków obejmuje trzy rzeczywiste decyzje priority przez
HttpClient → FastAPI → isolated SQLite → pending, brak zmiany Battle/events/
checkpoint/RNG przed zgodą, osobny HTTP approval sesji właściciela, executed,
event replay i serwerowy replay oraz drugi approval bez ponownego wykonania.
Negatywne obejmują kind/alias, v2/v3, spójność odczytów, stany/statusy,
zdolności, terrain/geometrię, rzeczywisty Shoot/Charge bez fallbacku,
owner/scope/expiry/no-oracle, CAS race, timeout przed/po POST, 5xx/malformed,
brak retry, concurrent run i redakcję sekretów.

Izolowany dodatni krok każdego z trzech trybów: **2 GET + 1 POST, 15 SELECT**
(metadata 4, checkpoint 5, proposal 6); bot **0 SQL**. Auth zapisuje standardowy
audit/last_used także dla GET, a POST zapisuje AgentProposal/audyt. Brak zmiany
bitwy nie oznacza braku zapisów auth. Nie dochodzą zapytania per kandydat,
nowe kolumny/indeksy ani zmiany hot path `/quote` lub `/rosters/{id}`.
Przykładowy lokalny pomiar decyzji dla seeda 19, po dwie jednostki:
Manewr **1,216 ms**, discard_exhausted **0,061 ms**, Mobilizacja **0,061 ms**.
To pojedyncza próbka bez HTTP, importu i gate'ów, nie SLA ani ranking.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -s tests/test_bot_proposals.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_bot_proposals.py tests/test_agent_proposals_router.py tests/test_agent_token_security.py tests/test_clients_http.py tests/test_battle_action_proposals.py tests/test_agents_priority.py tests/test_agents_factory.py tests/test_agents_registry.py tests/test_bots_audit.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
```

Zestaw celowany: **370 passed, 1 dependency warning**, 15,53 s. Pełny gate
po simplify: **4112 passed, 4 dependency warnings**, 221,67 s.
Szczegóły zamknięcia są w [kolejce](kolejka-po-c2d3.md#9-d62-connect--podłączenie-istniejących-agentów).
Slash commands nie są dostępne; wykonano ręczne równoważniki simplify,
review i security-review: reuse registry/factory/codeca/planera, audyt call sites,
sprawdzenie zamkniętych błędów, brak importów DB/resolver execution,
brak approval/auth rozszerzeń, ograniczenie geometrii i osobna zgoda.
Review dodał bezpieczny gate przepełnienia promienia i zawężenie statusu HTTP
do liczby; po tych poprawkach ponowiono pytest. Usunięto nieużywany import
testowy i dodano mapę sekcji. Ruff nie jest zainstalowany w `.venv`;
zamiast instalowania zależności wykonano ręczny AST check importów.
JS nie zmieniono.

## Kontynuacja na innym komputerze

Kod, testy i instrukcja są w osobnym commicie Faza_A; wymagane jest
potwierdzenie origin/Faza_A. Odtworzyć `.venv` z requirements i editable
`szop_client`, skonfigurować lokalny token/URL, uruchomić powyższe testy.
Nie przenosić prób w locie jako rzekomo idempotentnych: stan ledger jest
procesowy, więc po zmianie komputera najpierw rekoncyliacja ownera.

Produkcji nie używano do testów. `data/szop.db` pozostała nietknięta, SHA256:
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Baza, lokalne sekrety/konfiguracja oraz scheduler/runtime wymagają osobnego
backupu; nie znajdują się w artefakcie kodu. Historycznych HANDOFF nie zmieniano.
D6.3 pozostaje osobnym planowaniem: pełna walka, lifecycle consent v2/v3,
trwała deduplikacja/restart i UX wymagają osobno określonych etapów.
