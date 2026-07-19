# Testing

## Reguła ogólna

**Po każdej zmianie kodu uruchom testy. Nawet jednolinijkowej.**

PostToolUse hook wymusza pytest po edycjach `.py` — **nie suppressuj jego output**. Zignorowanie tej reguły = top friction category (11 hits, "tests skipped before declaring done").

## Kolejność uruchamiania — zawsze ta sama

### 1. Natychmiast po zmianie — tylko dotknięty plik lub moduł

```bash
python -X utf8 -m pytest tests/test_roster_classification.py -x --tb=short -q
```

Szybki feedback zanim pójdziesz dalej. Jeśli tu nie przejdzie — nie ma sensu uruchamiać reszty.

### 2. Przed deklaracją "gotowe" — filtruj po obszarze

```bash
python -X utf8 -m pytest -k "roster or cost or classification" -x --tb=short
```

### 3. Przed commitem — pełna suita, obowiązkowo

```bash
python -X utf8 -m pytest --tb=short -q
```

## Środowisko i uruchamianie (Windows / agenci)

**Uruchamiaj z roota repo.** Nie ma pliku konfiguracyjnego pytest (`pytest.ini`/`pyproject.toml`/`conftest.py`), więc `rootdir` = bieżący katalog — `import app.*` rozwiązuje się **tylko** gdy CWD = root repo.

**Interpreter:** preferuj globalny `python` (Python 3.13; zależności z `requirements-dev.txt`) lub lokalne `.venv`, jeśli globalny alias nie działa w danej powłoce/agencie. W Codex sandbox alias `python` może nie istnieć, mimo że Claude/Codex hooki mają komendę `python -X utf8 -m pytest ...`.

Jeśli `python`/`make` nie są w PATH albo pojawia się `Odmowa dostępu` do `WindowsApps` / Store Pythona, użyj lokalnego venv w repo:

```powershell
# jednorazowo, gdy .venv nie istnieje
<działający-python> -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# testy
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q
```

W sesjach Codex lokalna `.venv` bywa oparta o Store Pythona i może wymagać uruchomienia poza sandboxiem (escalation) z powodu `WindowsApps`/`Odmowa dostępu`. To nie jest błąd testów projektu. Zweryfikowany fallback z 2026-06-23:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q
# 1884 passed
```

**[CRITICAL] Kodowanie — prefiksuj `-X utf8`.** W trybie nieinterakcyjnym (output przechwytywany przez agenta / hook / pipe) `python` ustawia `sys.stdout.encoding = cp1250` (locale Windows-PL) **nawet gdy `chcp` = 65001**. Pierwszy polski znak / strzałka / `INCH` (U+201D) w tracebacku → `UnicodeEncodeError`, co wygląda jak „testy nie działają" (typowy problem agenta uruchamiającego pytest bez `make`, np. Codex). Flaga `-X utf8` (UTF-8 mode, PEP 540) wymusza UTF-8 na stdio niezależnie od powłoki i code page:

```bash
python -X utf8 -m pytest -q --tb=short            # pełna suita
python -X utf8 -m pytest tests/test_x.py -x -q    # jeden plik
```

Alternatywa gdy nie chcesz flagi: `$env:PYTHONIOENCODING="utf-8"` (PowerShell) / `set PYTHONIOENCODING=utf-8` (cmd) przed komendą. `make` ustawia to globalnie (`export PYTHONIOENCODING=utf-8`), więc `make test` problemu nie ma — ale `make` bywa poza PATH, stąd preferuj `python -X utf8 -m pytest`.

## Przydatne flagi pytest

| Flaga | Kiedy użyć |
|---|---|
| `-x` | Zawsze — stop na pierwszym błędzie, nie czekaj na resztę |
| `--tb=short` | Domyślnie — czytelny traceback bez szumu |
| `-q` | Szybki przebieg — jedna linia per test, podsumowanie na końcu |
| `-v` | Debugging — pełna nazwa każdego testu + status |
| `-k "słowo"` | Filtruj testy po nazwie funkcji lub pliku (np. `-k "classification"`) |
| `--lf` | Uruchom ponownie tylko ostatnio nieudane — przy poprawianiu |
| `-s` | Pokaż `print()` w testach — tylko do debugowania, nie zostawiaj w commicie |

## Co jeszcze sprawdzić po zmianie

- **Po zmianie logiki** — uruchom testy związane z dotkniętym obszarem.
- **Po zmianie UI** — sprawdź stan pusty, błędny i podstawowy scenariusz.
- **Jeśli testów brakuje** — dodaj minimalny test regresji.
- **Nie uznawaj zadania za zakończone bez krótkiej weryfikacji diffu.**
- **Call-site check przed zamknięciem:** znajdź wszystkie call sites zmodyfikowanego kodu, wyjaśnij wpływ na każdy.

## Kiedy testy dezaktualizują się

Jeśli zmieniasz zachowanie funkcji — **najpierw** sprawdź czy istniejące testy testują stare zachowanie. Jeśli tak: **popraw testy jako pierwszy krok**, zanim zmienisz kod produkcyjny. Stare testy blokują dalszą pracę i generują fałszywe błędy.

## Testy frontendu — payload parity

Pliki `tests/test_frontend_*.py` weryfikują payload parity (JS ↔ backend). Uruchom je **po każdej zmianie** w:

- `app/routers/rosters.py`
- `app/services/costs/*` (cokolwiek SSOT)
- `app/static/js/payload_adapters.js`
- `app/routers/export.py`

**Backend unit tests NIE pokrywają inicjalizacji JS** — smoke test manualny wymagany po zmianie `app.js`.

## Smoke test po zmianie `app/static/js/app.js`

Po każdej zmianie `app.js` uruchom aplikację (`make dev`) i **ręcznie** sprawdź:

1. **Zbrojownia** → czy lista broni jest widoczna?
2. **Edytor Armii** → czy przy dodaniu oddziału widoczne są bronie?
3. **Rozpiski** → czy można zaznaczyć oddział i czy otwiera się panel edytora?

Testy backendowe nie pokrywają inicjalizacji JS — te trzy scenariusze **muszą być sprawdzone ręcznie**. Bezpieczeństwo dla dużych plików: przed usunięciem funkcji z `app.js` zrób `grep -n "nazwaFunkcji" app/static/js/app.js` i zweryfikuj brak wywołań. W szczególności sprawdź łańcuch DOMContentLoaded (`docs/app-js-guide.md`).

## Diagnoza bugów UI

Przed analizą backendu **ustal pełną ścieżkę wywołania:** JS event → fetch → endpoint → render. Sprawdź czy wynik nie jest nadpisywany przez inny fetch po załadowaniu strony (np. batch `/quote` po renderowaniu SSR).

## Komendy projektu

- Test (wszystkie): `make test`
- Test (szybki, stop na pierwszym błędzie): `make test-fast`
- Lint: `make lint`
- Windows fallback: `python -X utf8 -m pytest -x --tb=short -q`
- Windows/Codex fallback gdy `python` nie jest w PATH: `.\.venv\Scripts\python.exe -X utf8 -m pytest -x --tb=short -q`

## B5.1 — real-transport parity klientów gry

`tests/test_clients_parity.py` używa seeded SQLite in-memory (`StaticPool`) i
rzeczywistego routera FastAPI z auth bearer. Mały adapter przekazuje publiczne
`HttpRequest` klienta HTTP do `TestClient` i zwraca `HttpResponse`; routery,
serwisy, adapter ORM, codeki i decodery nie są mockowane. Gate porównuje pełny
`SimulationSummary` dla dwóch szybkich botów, dwóch map, `n=1`/`n>1` i dwóch
seedów, a w osobnym świeżym świecie kanoniczny stan, checkpoint sequence oraz
eventy create/read/jednej akcji. Pokrywa też powtarzalność, brak domenowych
zapisów po simulate, no-oracle i odrzucenie HTTP continuation przed transportem.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_clients_parity.py tests/test_clients_local.py tests/test_clients_http.py tests/test_battles_router.py tests/test_engine_regression.py tests/test_engine_persistence.py tests/test_engine_checkpoints.py tests/test_engine_action_codec.py tests/test_engine_multi_action.py tests/test_battle_action_proposals.py
```

## B5.2 — real-transport HttpClient battle invites

`tests/test_clients_http_invites.py` łączy ścisłe testy wstrzykiwanego
transportu z rzeczywistym FastAPI `TestClient`. Seeded SQLite in-memory z
wymuszonym FK tworzy osobnych ownerów, ich rostery i osobne bearery dla scope
`battle:invite`/`battle:accept`; produkcyjna `data/szop.db` nie jest otwierana.
Flow obejmuje direct invite, 404 obcego acceptora i cudzego rosteru, 403 dla
brakującego scope, pierwszy accept oraz idempotentny retry z tym samym
`battle_id` i bez drugiej `Battle`/eventów/checkpointu. Następnie ten sam świat
tworzy i akceptuje open invite innym ownerem oraz sprawdza terminalne 409 i
body-blind `AgentAuditLog` bez bearera ani pól body. Unit matrix sprawdza jeden
request, exact method/path/body/header/timeout, preflight, naive-UTC datetime,
fail-closed JSON, zachowanie statusów 401/403/404/409/422 i lazy import.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_clients_http.py tests/test_clients_http_invites.py tests/test_clients_parity.py tests/test_battle_invites_router.py tests/test_battle_invite_accept_router.py tests/test_agent_token_security.py
```

## B4.1 — create direct/open battle invite

`tests/test_battle_invites_router.py` używa osobnego seeded SQLite in-memory
(`StaticPool`, wymuszone FK) i rzeczywistego `FastAPI TestClient`; produkcyjna
`data/szop.db` nie jest otwierana. Gate obejmuje session/bearer/wildcard auth,
scope `battle:invite`, body-blind audit, strict request/response, canonical
scenario, owner/target no-oracle, pending/result-linkage invariants, brak
idempotency, rollback po kontrolowanym `IntegrityError` oraz ponowne użycie po
błędzie.

Pomiar całego requestu create wynosi dokładnie **3 statements dla session/open**
i **4 dla session/direct**. Osobno liczona ścieżka agent auth + standardowy audit
wynosi **6 dla bearer/open** i **7 dla bearer/direct**. Różnica to wyłącznie
opcjonalny lookup direct targetu; liczba roster units i historia invite'ów nie
dodają zapytań. Targeted gate B4.1 wraz z wymaganymi regresjami:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_battle_invites_router.py tests/test_battle_invite_model.py tests/test_db_schema_migrations.py tests/test_battles_router.py tests/test_battle_event_stream.py tests/test_clients_parity.py tests/test_battle_action_proposals.py tests/test_agent_token_security.py
```

## B4.2 — atomowy direct/open battle invite accept

`tests/test_battle_invite_accept_router.py` używa rzeczywistego FastAPI
`TestClient` i wyłącznie testowych baz. Główna macierz działa na seeded SQLite
in-memory z wymuszonym FK; concurrency gate tworzy osobną plikową SQLite w
`tmp_path`, włącza WAL/busy timeout i uruchamia dwa równoległe requesty z
osobnymi sesjami/połączeniami. Pokrycie obejmuje direct/open/admin, server seed,
scenario terrain/objectives w checkpoint, ciągły event-log, pełne linkage,
idempotentny retry, strict body, `battle:accept`/wildcard/401/403, body-blind
audit, no-oracle, expiry commit, terminalne 409, uszkodzony source/scenario/
linkage, rollback po kontrolowanym `IntegrityError` oraz ponowne użycie.

Realny concurrency gate wymusza wspólny punkt startu przed CAS. Dwa requesty
tego samego acceptora kończą z tym samym `battle_id`; dwaj konkurenci open mają
dokładnie jeden 200 i jeden body-less 404. W obu przypadkach baza ma jedną
`Battle`, jeden checkpoint, eventy wyłącznie tej bitwy i zero orphanów.

SQL gate liczy pełny session request. Dla dwóch rosterów po 1 jednostce wykonuje
**18 statements**, a dla dwóch rosterów po 12 jednostek — **40**; różnica 22 to
oczekiwane INSERT-y 22 dodatkowych startowych eventów. Control-plane i eager
loading mają w obu przypadkach dokładnie **13 SELECT-ów**, także po dodaniu 20
historycznych invite'ów i dla 12 różnych jednostek z relacjami broni. Lookup i
CAS invite zawsze zawierają `battle_invites.id`; nie ma skanu historii ani
per-unit SELECT/N+1.

Targeted gate B4.2 wraz z regresjami:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_battle_invite_accept_router.py tests/test_battle_invites_router.py tests/test_battle_invite_model.py tests/test_db_schema_migrations.py tests/test_battles_router.py tests/test_battle_event_stream.py tests/test_engine_persistence.py tests/test_engine_checkpoints.py tests/test_clients_parity.py tests/test_battle_action_proposals.py tests/test_agent_token_security.py
```

## B6.1 — uwierzytelniony, wznawialny stream SSE eventów bitwy

`tests/test_battle_event_stream.py` łączy realny `FastAPI TestClient` dla
zakończonych streamów i auth/headers z deterministycznymi testami serwisu dla
aktywnego follow. Wstrzykiwany sleeper/clock eliminuje rzeczywiste oczekiwanie.
Gate obejmuje parity JSON, dokładne ramki UTF-8, cursory `since`/
`Last-Event-ID`, keep-alive/disconnect, terminal close, lifecycle krótkich sesji,
testowy `get_db` override, audit/no-oracle oraz koszt SQL: 1 SELECT z eventami,
maksymalnie 2 na idle/terminal poll.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_battle_event_stream.py tests/test_battles_router.py tests/test_engine_persistence.py tests/test_clients_http.py tests/test_clients_parity.py tests/test_battle_action_proposals.py
```

## A4 drift pipeline — `make rules-check`

Orchestrator pipeline'u drift detection (ADR-0006). Uruchamia 5 skryptów sekwencyjnie z fail-fast:

```bash
make rules-check                # full pipeline
make rules-sources-check        # SHA256 dla SZOP.docx/pdf/md×2
make rules-extract              # DOCX → build/rules_extracted.yaml
make rules-extract-md           # MD → build/rules_md.yaml
make rules-classify             # abilities.yaml → build/geometry_classification.md
make rules-drift                # DOCX vs YAML → build/drift_report.md
```

**Kolejność `rules-check`:** sources-check → extract → extract-md → classify → drift (drift LAST bo może wyjść z exit 2 WARN i zatrzymać chain — wszystkie inne artefakty wcześniej już zapisane).

**Exit codes:**
- `0` — clean (wszystko match, brak drift)
- `1` — ERROR (R1/R4 w drift, mismatch w sources, parse error w extract/classify)
- `2` — WARN-only (R2/R3 w drift, missing source files)

**Kiedy uruchamiać:**
- Po edycji `app/static/docs/SZOP.*` (DOCX, PDF, MD) — wykryje silent edits.
- Po edycji `app/rulesets/v1/*.yaml` — wykryje drift od source-of-truth.
- Po edycji `app/data/abilities.py` — pośrednio sprawdza spójność YAML mirror.
- W CI (planowane A4.6 GHA workflow `rules_drift.yml`).

Po świadomej edycji source files: `python scripts/rules_sources_check.py --update` regeneruje `app/rulesets/v1/source_hashes.yaml`.

Detale: [scripts/README.md](../scripts/README.md), [docs/adr/0006-pipeline-drift.md](adr/0006-pipeline-drift.md).

## A1.1 — JSON Schema fizycznych dokumentów rulesetu

Generator bez argumentów wejściowych zapisuje śledzony artefakt
`docs/schemas/ruleset_v1.schema.json`. Schema obejmuje dokładnie jeden z trzech
plików: `tables.yaml`, `abilities.yaml` albo `ability_costs.yaml`. Warianty
`oneOf` są rozróżniane przez wymagane klucze top-level; fizyczne YAML-e nie
dostają sztucznego pola discriminator.

```bash
make generate-schema   # write-if-changed, atomowy replace
make schema-check      # read-only: exit != 0 dla missing/drift
```

Windows fallback, gdy `make` nie jest w PATH:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/generate_ruleset_schema.py
.\.venv\Scripts\python.exe -X utf8 scripts/generate_ruleset_schema.py --check
```

To osobny gate A1; nie jest częścią `rules-check`/A4 ani runtime aplikacji.
Po zmianie `app/services/rulesets/models.py` albo kształtu jednego z trzech
YAML-i uruchom generację, a następnie check i test
`tests/test_ruleset_schema.py`.

Rozszerzenie VS Code [YAML by Red Hat](https://github.com/redhat-developer/vscode-yaml#associating-a-schema-to-a-glob-pattern-via-yamlschemas)
przyjmuje schema po lewej i glob lub listę plików po prawej. Konfiguracja
workspace `.vscode/settings.json` dla tego repo:

```json
{
  "yaml.schemas": {
    "./docs/schemas/ruleset_v1.schema.json": [
      "app/rulesets/v1/tables.yaml",
      "app/rulesets/v1/abilities.yaml",
      "app/rulesets/v1/ability_costs.yaml"
    ]
  }
}
```

## C2.2 — offline BM25 retrieval

Korpus, pojedyncze wyszukiwanie i stały benchmark nie przyjmują ścieżek od
klienta i nie korzystają z DB/HTTP:

```bash
make rag-corpus
python -m mcp_server.search --query "pkt 14.d.i" --limit 5
make rag-bm25-eval
```

`rag-bm25-eval` najpierw odtwarza gitignored `build/rag_corpus.jsonl`, a potem
uruchamia top-5 dla dokładnie 30 rekordów `mcp_server/rag_evaluation.jsonl`.
Hit wymaga zgodności istniejących `source`, `ref` i `anchor`; exit code jest
niezerowy poniżej progu 70%. Baseline C2.2 z 2026-07-17: **24/30,
recall@5 = 0,800**. Targeted suite:

```bash
python -X utf8 -m pytest tests/test_rag_corpus.py tests/test_rag_search.py -q
```

## C2.3 — opcjonalny MiniLM + sqlite-vec

Bazowe `requirements.txt` / `requirements-dev.txt` nie instalują ciężkiego stosu
ML. Profil RAG jest jawnym supersetem developerskim i używa oficjalnego indeksu
PyTorch CPU:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements-rag.txt
.\.venv\Scripts\python.exe -X utf8 -m pip check
```

Pobranie modelu jest jedyną komendą, która może korzystać z sieci. Model ma
stałe ID/rewizję i trafia wyłącznie do gitignored `build/models`:

```bash
make rag-model-download
make reindex-rules
make rag-index-check
```

Windows fallback, gdy `make` nie jest w PATH:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.embeddings
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store rebuild
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store check
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store query --query "Jak działa osłona?" --limit 5
```

Rebuild i query po pobraniu używają `local_files_only=True`; mogą być dodatkowo
sprawdzone z `HF_HUB_OFFLINE=1` i `TRANSFORMERS_OFFLINE=1`. Testy nie ładują
prawdziwego modelu: wstrzykują deterministyczny fake embedder, ale tworzą i
odpytują prawdziwą tabelę `vec0`. Targeted suite po instalacji profilu:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_rag_corpus.py tests/test_rag_search.py tests/test_rag_vector_store.py tests/test_mcp_server.py -x --tb=short -q
```

Realny smoke CPU 2026-07-17 (Windows, Python 3.13.14, wymuszony offline po
pobraniu): download+probe 34,9 s; 3×384 embeddingów 11,622 s; rebuild 36/36
4,053 s; offline reopen zgodny; dense top-5 2,391 s. Cache modelu zajmował
479 729 205 B (Windows bez symlinków), a SQLite 1 769 472 B. Artefakty pozostają
w `build/` i nie są commitowane.

## C2.4 — offline dense+BM25 hybrid

Po pobraniu modelu target najpierw sprawdza zgodność stałego indeksu, a następnie
wymusza tryb offline dla wspólnego benchmarku BM25/dense/hybrid:

```bash
make rag-hybrid-eval
```

Dokładny Windows fallback, gdy `make` nie jest w PATH:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:HF_HUB_DISABLE_TELEMETRY='1'
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store check
if ($LASTEXITCODE -ne 0) {
    .\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store rebuild
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    .\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store check
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.evaluation --hybrid
```

`--hybrid` używa jednego matchera `source+ref+anchor`, drukuje każdy z 30
przypadków, agregaty i czasy trzech metod. Osobny gate hybrid wymaga recall@5
>= 0,800. Finalny przebieg 2026-07-18: BM25 **24/30 (0,800; 0,041 s)**, dense
**8/30 (0,267; 79,741 s)**, hybrid **24/30 (0,800; 69,476 s)**; brak przypadków
naprawionych i pogorszonych przez hybrid względem BM25. Trzy fazy retrieval:
149,258 s, cały proces: 152,5 s wall-clock. Pełna zadeklarowana siatka parametrów
jest zapisana w ADR-0026.

Zwykłe testy nie potrzebują `build/models` ani `build/rag_vectors.sqlite`:
gałęzie oraz status indeksu są monkeypatchowane, a czysta fuzja dostaje
deterministyczne rankingi. Targeted suite:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_rag_corpus.py tests/test_rag_search.py tests/test_rag_vector_store.py tests/test_rag_hybrid.py tests/test_mcp_server.py -x --tb=short -q
```

## C2.5 — procesowy lifecycle i warm-latency gate

Model-free testy lifecycle nie potrzebują `build/models` ani produkcyjnego
`build/rag_vectors.sqlite`. Pokrywają singleton default, równoległy first use,
serializację `encode`, retry po błędzie, osobny download, dependency injection,
lazy import i parity rankingu/scoringu dla deterministycznego fake. Targeted
suite:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_rag_vector_store.py tests/test_rag_hybrid.py tests/test_rag_retrieval_benchmark.py tests/test_mcp_server.py -x --tb=short -q
```

Realny benchmark wymaga wcześniej pobranego fixed modelu i zgodnego indeksu.
Uruchamia dokładnie sześć stałych hybrid queries w jednym procesie i wypisuje
JSON-safe cold first-call, warm p50/p95, total, status indeksu oraz rankingi:

```bash
make rag-retrieval-latency
```

Dokładny Windows fallback, gdy `make` nie jest w PATH:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:HF_HUB_DISABLE_TELEMETRY='1'
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.vector_store check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -X utf8 -m mcp_server.retrieval_benchmark
```

Baseline przed C2.5: cold 18,516 s, warm p50 2,610 s, p95 3,577 s, total
32,269 s. Po singletonie: cold 14,691 s, warm p50 0,080 s, p95 0,090 s, total
15,107 s (~32,5× dla warm p50). Pełny gate dokładności pozostaje osobny:
`make rag-hybrid-eval`; wynik C2.5 to BM25 24/30, dense 8/30, hybrid 24/30 i
brak zmian hit/miss hybrid względem C2.4.

## C2.6 — scoped runtime hybrid search

Model-free suite patchuje wyłącznie granicę `hybrid_search`; nie potrzebuje
optional dependencies, modelu ani indeksu. Pokrywa body/response, trim i limity,
401/403/audyt bez body, stabilne 503, ścisły klient i timeout oraz ósmy tool MCP
bez lokalnego importu RAG:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_rules_search_router.py tests/test_clients_http.py tests/test_mcp_server.py tests/test_reference_router.py tests/test_agent_token_security.py tests/test_rag_hybrid.py -x --tb=short -q
```

Rozszerzony gate wraz z `test_rag_vector_store.py` i
`test_rag_retrieval_benchmark.py`: **264 passed**.

Realny smoke wymaga profilu `requirements-rag.txt`, fixed model cache i zgodnego
indeksu. Przed startem wymuś offline i uruchom `mcp_server.vector_store check`.
Użyj kopii produkcyjnej `data/szop.db` albo transakcji z rollbackiem do
tymczasowego tokena `rules:search`; nie zapisuj raw tokena w pliku ani logu.
W jednym procesie wykonaj przez `HttpClient.search_rules` pierwszy cold i drugi
warm POST, a następnie tool MCP ze wstrzykniętym klientem. Potwierdź:

- schema `szop.search_rules/v1`, strategy i JSON `allow_nan=False`;
- jeden audit na request z route/metodą/status i bez body query/bearera/tekstu;
- top-k `chunk_id` identyczne z bezpośrednim `hybrid_search` dla tego samego
  query/limitu;
- warm latency oraz brak zmian w produkcyjnej DB i gitignored `build/`.

Brak modelu, optional dependencies lub zgodnego indeksu jest poprawnym stanem
readiness 503. Endpoint nigdy nie pobiera modelu i nie wykonuje reindexu.

Realny smoke C2.6 z 2026-07-18 (Windows, Python 3.13.14, fresh process,
wymuszony offline, zgodny indeks 36/36): HttpClient cold **20,239 s**, warm
**0,093 s**, tool MCP **0,180 s**, późniejszy direct hybrid **0,105 s**.
Wszystkie trzy ścieżki miały identyczne top-5 `chunk_id`; trzy wpisy audytu nie
zawierały query, bearera ani tekstu wyników. SHA-256 produkcyjnej DB i indeksu
oraz count/size/mtime cache modelu pozostały bez zmian.

## C3.1 — scoped read-only validate_loadout

Targeted gate pokrywa serwis i kompatybilność leaf-CLI, trzy backendy kosztów,
scope/auth/audit, stałe 422/404/500, ścisły JSON, statement count, klient oraz
dziewiąty tool MCP bez lokalnego importu DB/costs/scripts:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_validate_loadout.py tests/test_loadout_validation_router.py tests/test_loadout_validation_smoke.py tests/test_clients_http.py tests/test_mcp_server.py tests/test_agent_token_security.py -x --tb=short -q
```

SQL regression liczy cały request, łącznie z `require_agent_scope`, audytem i
stałymi eager-loadami katalogu: mały payload oraz legalny payload 3×100 wpisów
muszą wykonać dokładnie **11 statements**. Rozmiar loadoutu nie może dodawać
zapytań; `/quote` i `/rosters/{id}` nie są częścią tej ścieżki.

Realny model-free smoke używa seeded in-memory SQLite i tego samego mieszanego
payloadu z accepted+rejected+clamped. Porównuje 1:1:

- direct `app.services.loadout_validation`;
- scoped endpoint `POST /units/{unit_id}/validate-loadout`;
- rzeczywisty `HttpClient.validate_loadout` przez transport TestClient;
- MCP `validate_loadout` ze wstrzykniętym tym samym klientem.

Po trzech requestach dozwolone są wyłącznie trzy standardowe wpisy audytu i
aktualizacja `last_used_at`. Snapshot `units`, `unit_weapons`, `unit_abilities`,
`rosters` i `roster_units` musi pozostać identyczny; audit nie może zawierać
loadoutu, bearera, passive ani składowych kosztu. Produkcyjna `data/szop.db` nie
jest używana ani modyfikowana.

## C3.2 — owner-scoped read-only score_list

Targeted gate pokrywa produkcyjny scoring SSOT i zgodność leaf-CLI, wspólną
orkiestrację symulacji, owner scope/auth/audit, stałe 422/404/500, workload caps,
ścisły JSON, SQL count, klient, dziesiąty tool MCP oraz realny smoke:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_score_list_smoke.py tests/test_score_list.py tests/test_roster_scoring_router.py tests/test_clients_http.py tests/test_mcp_server.py tests/test_battles_router.py tests/test_clients_local.py tests/test_simulate_engagement.py tests/test_engine_regression.py
```

SQL regression liczy cały request, łącznie z `require_agent_scope`, audytem i
owner-scoped eager-loadami. Jawny subset: jeden przeciwnik przy 1 i 10 grach oraz
trzech przeciwników przy 1 grze musi wykonać dokładnie **13 statements**;
domyślne pole ma stałe **15** przez dwa bounded preflighty. Niezależne głębokie
łańcuchy `Weapon.parent` dla 1 i 3 przeciwników nadal mają dokładnie 13. Liczba
gier i dozwolona wielkość pola nie mogą dodawać zapytań. Osobne testy wymuszają limit
10 przeciwników i 50 gier łącznie oraz stałe 422 bez truncation.

Realny smoke używa seeded in-memory SQLite: owner ma target i dwóch przeciwników,
a obcy owner osobny roster. Porównuje 1:1 direct
`app.services.roster_scoring`, scoped endpoint
`POST /rosters/{roster_id}/score`, rzeczywisty `HttpClient.score_list` przez
transport TestClient i MCP `score_list` ze wstrzykniętym tym samym klientem.
Foreign roster jest wykluczony z pola domyślnego i daje wspólne 404 po jawnym
wskazaniu. Snapshot rosterów, roster units, bitew, eventów i katalogu pozostaje
identyczny, łącznie z `AgentToken`; dozwolone są tylko standardowe body-blind
audyty. Produkcyjna `data/szop.db` nie jest używana ani modyfikowana.

## C3.3 — owner-scoped read-only find_exploit_candidates

Targeted gate pokrywa produkcyjny SSOT i zgodność leaf-CLI, ranking obu stron,
pair seeds, zero-points, owner/global army visibility, stałe 422/404/500,
workload O(n²), ścisły klient, jedenasty tool MCP, SQL count i realny smoke:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_exploit_candidates_smoke.py tests/test_find_exploit_candidates.py tests/test_exploit_candidates_router.py tests/test_clients_http.py tests/test_mcp_server.py tests/test_score_list_smoke.py tests/test_score_list.py tests/test_roster_scoring_router.py tests/test_battles_router.py tests/test_clients_local.py tests/test_simulate_engagement.py tests/test_engine_regression.py
```

Publiczne pole ma 2–7 rosterów, do 21 par i 50 gier; `games_per_pair` ma zakres
1–3. Jawny subset dwóch rosterów przy 1/3 grach i siedmiu przy legalnych dwóch
grach wykonuje dokładnie **14 statements**. Domyślne siedem rosterów wykonuje
**15** przez owner-scoped `LIMIT 8`; ósmy roster daje stałe 422. Niezależne
głębokie łańcuchy `Weapon.parent` dla 2 i 7 rosterów nadal mają 14. Count
obejmuje realny `require_agent_scope`, body-blind audit, army visibility oraz
jeden batch eager-load; nie ma SQL per para/gra.

Realny smoke używa seeded in-memory SQLite: owner ma trzy rostery jednej armii,
własny roster innej armii, a outsider roster w tej samej armii. Porównuje 1:1
direct `app.services.exploit_candidates`, scoped endpoint
`POST /armies/{army_id}/exploit-candidates`, rzeczywisty
`HttpClient.find_exploit_candidates` przez transport TestClient i MCP
`find_exploit_candidates`. Foreign i wrong-army jawne ID dają wspólne 404.
Snapshot armii, rosterów, roster units, bitew, eventów, katalogu i `AgentToken`
pozostaje identyczny; dozwolone są wyłącznie body-blind audyty. Produkcyjna
`data/szop.db` nie jest używana ani modyfikowana.
