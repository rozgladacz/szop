# scripts/

Narzędzia CLI uruchamiane manualnie lub w CI. Nie są częścią runtime aplikacji
(`app/`). Każdy skrypt ma:

- argparse-based interface (z defaults sensownymi dla CWD = project root),
- entry-point `main(argv=None) -> int` (testowalne bez subprocess),
- exit code 0 = sukces, 1+ = błąd (semantyka per skrypt poniżej).

## Komendy projektu (wrappery w `Makefile`)

| Cel `make` | Skrypt | Co robi |
|---|---|---|
| `make profile ROSTER=X` | `profile_quote.py` | cProfile `calculate_roster_unit_quote` per oddział |
| `make profile ROSTER=X BACKEND=yaml` | `profile_quote.py --backend yaml` | jak wyżej, ale pod `OPR_RULES_BACKEND=yaml` |
| *(A4.5 — planowane)* `make rules-check` | `rules_extract.py` + `rules_drift.py` + `rules_classify_geometry.py` + `rules_pdf_check.py` | Pełny pipeline drift DOCX↔YAML (sekwencyjnie, pierwszy non-zero exit przerwie) |

---

## Pipeline `rules_*` — drift detection DOCX → YAML

**Cel:** wykrywać dryf między `app/static/docs/SZOP.docx` (source of truth)
a `app/rulesets/v1/abilities.yaml` (deklaratywny ruleset). Pipeline **nie
generuje YAML automatycznie** — tylko raportuje rozbieżności. Aktualizacja
YAML wymusza świadomą decyzję człowieka. Pełne uzasadnienie:
[ADR-0006](../docs/adr/0006-pipeline-drift.md).

Status: A4.1 zaimplementowane, A4.2–A4.7 planowane (patrz
[HANDOFF_faza-a-4-drift](../docs/handoffs/HANDOFF_faza-a-4-drift.md)).

### `rules_extract.py` ✅ (A4.1)

Czyta `SZOP.docx` (przez `python-docx`), emituje `build/rules_extracted.yaml`
ze schema `{slug, name, type, description}` per zdolność. Schema reuse
[`RulesetAbility`](../app/services/rulesets/models.py) z pól `value_*` =
`None` (DOCX ich nie nosi).

**Sister script:** [`rules_extract_md.py`](#rules_extract_mdpy--a42) — ten
sam schema output, ale parsing `SZOP_Zdolnosci.md` (formalna curated MD
wersja zasad). Drift pipeline (`rules_drift.py`) traktuje oba strumienie
identycznie.

```powershell
# Default paths (CWD = project root):
python scripts/rules_extract.py

# Custom paths:
python scripts/rules_extract.py --input app/static/docs/SZOP.docx --output build/rules_extracted.yaml
```

**Wynik:** `build/rules_extracted.yaml` (~85 abilities, ~30 KB). Folder
`build/` jest gitignored — output nie commitowany.

**Exit codes:**
- `0` — wyciągnięto abilities, plik zapisany.
- `1` — DOCX nie istnieje / nie jest poprawnym `.docx` / duplikaty slugów.

**Parser strategy** (wymuszony przez strukturę `SZOP.docx`):
- Brak `Heading` styles — wszystko `Normal` / `List Paragraph`.
- Content-based state machine: start na pierwszym `^Pasywne:$`, stop na
  paragrafie zaczynającym `Koszt oddziału jest sumą`.
- Sekcje (`Pasywne:`/`Aktywne:`/`Aury:`/`Broni:`) wyznaczają `type`.
- Word soft line break (Shift+Enter) emituje `\n` wewnątrz `paragraph.text`
  — kilka zdolności potrafi dzielić jeden paragraf, rozbijamy `text.split("\n")`.
- Multi-paragraph descriptions: linie continuation (nie pasujące do
  `<Name>: <desc>` regex) doczepiamy do bieżącej zdolności.
- Slug: NFKD → strip accents → lowercase → spacje/slashe → underscore.
  Polish `Ł`/`ł` pre-replace przed NFKD (są to osobne Latin chars w Unicode,
  NFKD nie rozkłada).

**Testy:** `tests/test_rules_extract.py` (29 testów) — slug parametrized,
real DOCX sanity (count/types/distribution), programmatic-generated golden
fixture DOCX, CLI subprocess smoke, edge cases.

### `rules_extract_md.py` ✅ (A4.2+)

Czyta `app/static/docs/SZOP_Zdolnosci.md` (formalna curated wersja
SZOP zasad z 1:1 cytatami opisów + dodatkowe metadane: efekty, koszt,
aura_tak, rozkaz_tak, zakres, mistrzostwo_tak). Emituje
`build/rules_md.yaml` ze schema identycznym jak `rules_extract.py`.

```powershell
python scripts/rules_extract_md.py
python scripts/rules_extract_md.py --input app/static/docs/SZOP_Zdolnosci.md --output build/rules_md.yaml
```

**Parser:** Markdown jest dużo prostsze do parse niż DOCX (no Word soft
breaks, no encoding issues). Sekcje wyznaczone explicit `## Pasywne`/
`## Aktywne`/`## Aury`/`## Broni`. Zdolności wyznaczone `### N. Name`
(numbered, stable id). `typ:` field daje explicit type (Polish → English
mapping). Multi-line `opis:` continuation łączymy póki nie nowy field/
ability/sekcja.

**Drift integration:** `rules_drift.py` przyjmuje dowolny YAML w tym
samym schema — można drift'ować pairwise:
- DOCX vs YAML: `rules_drift.py --extracted build/rules_extracted.yaml --yaml app/rulesets/v1/abilities.yaml`
- MD vs YAML: `rules_drift.py --extracted build/rules_md.yaml --yaml app/rulesets/v1/abilities.yaml --report build/drift_md_vs_yaml.md`
- DOCX vs MD: `rules_drift.py --extracted build/rules_extracted.yaml --yaml build/rules_md.yaml --report build/drift_docx_vs_md.md`

**Testy:** `tests/test_rules_extract_md.py` (15 testów) — real MD sanity
+ programmatic golden fixture + section detection + multi-line opis +
Konwencje skip + Polish char slug.

### `rules_drift.py` ✅ (A4.2)

Porównuje dwa pliki YAML w schema `RulesetAbility` i generuje
`build/drift_report.md` z 4 typami raportów:

| ID | Sytuacja | Severity | Exit |
|---|---|---|---|
| R1 | Slug w `--extracted`, brak w `--yaml` | ERROR | 1 |
| R2 | Slug w `--yaml`, brak w `--extracted` | WARN | 2 (chyba że whitelisted) |
| R3 | Ten sam slug, różny `description` (po NFKC + strip + collapse ws) | WARN | 2 |
| R4 | Ten sam slug, różny `type` | ERROR | 1 |

```powershell
# Default: DOCX-extract vs YAML ruleset
python scripts/rules_drift.py

# Custom: MD-extract vs YAML ruleset
python scripts/rules_drift.py --extracted build/rules_md.yaml --report build/drift_md_vs_yaml.md

# Sanity: DOCX-extract vs MD-extract (powinno być małe — oba reflect author canon)
python scripts/rules_drift.py --extracted build/rules_extracted.yaml --yaml build/rules_md.yaml --report build/drift_docx_vs_md.md
```

Whitelist (`app/rulesets/v1/drift_allowlist.yaml`, opcjonalny): wpisy z
`allowed_yaml_only` są raportowane jako WHITELISTED (INFO) i nie
kontrybuują do exit code. Każdy wpis ma `slug`, `reason`, opcjonalnie
`until_date` (null = permanent).

**Testy:** `tests/test_rules_drift.py` (27 testów) — normalize parametrized
+ whitelist loader + 4 buckets z exit codes + CLI smoke.

### `rules_classify_geometry.py` ✅ (A4.3)

Czyta `app/rulesets/v1/abilities.yaml`, dopasowuje regex keywords w
`description`, grupuje zdolności wg 7 kategorii geometrycznych. Wynik:
`build/geometry_classification.md` z **listą exclusions dla Strumienia B
MVP** (hard prereq dla B0 per `docs/roadmap.md`).

```powershell
python scripts/rules_classify_geometry.py
python scripts/rules_classify_geometry.py --input app/rulesets/v1/abilities.yaml --output build/geometry_classification.md
```

**Kategorie:**

| Kategoria | B MVP excluded | Powód |
|---|---|---|
| `facing` | ⛔ | Pareto: oddział=koło, brak `facing_deg`. ADR-0042 (E3). |
| `per_model` | ⛔ | Oddział=blob, brak per-model granularity. E1 (post-stable). |
| `los_complex` | ⛔ | Łuki/stożki wymagają analitycznej geometrii. ADR-0043 N=16 sampling. |
| `los_simple` | OK | niebezpośredni, Wysoki — proste flagi. |
| `range_special` | OK | Zasięg od trzeciego elementu (Artyleria) — center-of-mass lookup. |
| `placement_special` | OK | Zasadzka/Rezerwa = pre-game setup, nie runtime geometry. |
| `movement_special` | OK | Latający (ignore terrain), Samolot (linia) — branche w move resolver. |

**Heurystyka jest konserwatywna** — false-positives akceptowalne (raport
do ręcznego przeglądu, nie auto-decyzja). Sample current output (88
abilities):
- 3 excluded: `zwrot` (facing), `precyzyjny` (per_model), `dywersant` (false-positive na "strefy rozstawienia").
- 77 uncategorized (większość = stat-based, no geometric concerns).

**Testy:** `tests/test_rules_classify_geometry.py` (28 testów) — normalize
parametrized + per-category synthetic + real YAML sanity + render + CLI.

### `rules_sources_check.py` ✅ (A4.4)

Wykrywa **silent edit** plików źródłowych (`SZOP.docx`, `SZOP.pdf`,
`SZOP_Zdolnosci.md`, `SZOP_Rozjemca.md`) przez SHA256 checksum.
Centralna lokalizacja hashes: `app/rulesets/v1/source_hashes.yaml`
(decyzja A4.4 — centralizacja vs `*.sha256` per-file).

```powershell
# Check mode (default): verify current hashes match recorded.
python scripts/rules_sources_check.py

# Update mode: regenerate hashes after świadomej edycji source files.
python scripts/rules_sources_check.py --update
```

**Exit codes:**
- `0` — wszystkie hashes match (clean)
- `1` — co najmniej jeden mismatch (silent edit detected — wymaga review)
- `2` — co najmniej jeden source file missing (priority over mismatch)

**Schema `source_hashes.yaml`:**
```yaml
version: 1
sources:
  - path: app/static/docs/SZOP.docx
    sha256: <hex>
    role: "Word document — primary author source"
  # ... more entries
```

**Workflow:** po świadomej edycji DOCX/PDF/MD (np. nowa wersja po
klaryfikacji zasad) commit `--update` razem ze zmianami source files.
CI gate (A4.6) wykryje gdy ktoś edytuje source bez aktualizacji hashes.

**Testy:** `tests/test_rules_sources_check.py` (21 testów) — sha256
deterministic + load/save round-trip + match/mismatch/missing scenarios
+ exit codes priority + role preservation + CLI smoke + real sources
integration test.

### `make rules-check` ⏳ (A4.5 — planowane)

Sekwencyjny wrapper na 4 powyższe skrypty. Pierwszy non-zero exit przerywa.
GHA workflow `.github/workflows/rules_drift.yml` (A4.6) odpala go tylko na
PR-ach modyfikujących `app/static/docs/**`, `app/rulesets/**`,
`app/data/abilities.py` (path-filtered, zero overhead dla niepowiązanych
zmian).

---

## Inne skrypty

### `profile_quote.py`

cProfile dla `calculate_roster_unit_quote` per oddział w rozpisce.
Używany do weryfikacji performance changes w `app/services/costs/`
(procedural) i `app/services/rulesets/` (yaml). Baseline:
[docs/PERFORMANCE.md](../docs/PERFORMANCE.md).

```powershell
python scripts/profile_quote.py 10                         # roster_id=10, procedural (default)
python scripts/profile_quote.py 10 --backend yaml          # YAML backend
python scripts/profile_quote.py 10 --backend both_assert   # parity diagnostic
make profile ROSTER=10 BACKEND=yaml                        # convenience wrapper
```

### `balance_simulate.py` (D2)

Agreguje N headless gier (`app.services.agents.simulate_from_rosters`,
ADR-0032) → win-rate per rozpiska + draw-rate + śr. rund. Inicjatywa
naprzemienna usuwa bias 1. gracza; gracze P0/P1 seedowani rozłącznie
(`PLAYER_SEED_OFFSET`) — bez tego mirror random-vs-random zawyżałby remisy
(F2). Para rosterów z fixtury YAML
(`tests/fixtures/battles/*.yaml`, format engine-dict). Headless,
deterministyczny per `--seed`. Zero zmian w rdzeniu silnika.

```powershell
python scripts/balance_simulate.py                                   # demo fixtura, stdout
python scripts/balance_simulate.py -n 200 --players greedy,random    # 200 gier, P0 greedy
python scripts/balance_simulate.py --fixture <PATH> --out build/balance.csv
```

### `balance_report.py` (D2)

Round-robin turniej botów (każda fixtura × każda para typów — kombinacje
z powtórzeniem) reużywający `balance_simulate.simulate_balance` (SSOT) →
raport markdown `reports/balance/YYYY-MM-DD.md` z tabelą win-rate i tekstowymi
(unicode) wykresami słupkowymi. Wykresy są **tekstowe, nie obrazowe** (bez
matplotlib — dependency-free). `reports/` jest gitignored (artefakt generowany).

Wspiera też **mapy generowane** (`--map name[,name] [--map-seed N]`, reuse
`balance_simulate.build_map`/`MAP_BUILDERS`) — dodatkowo do fixtur; samo `--map`
pomija domyślne fixtury.

Domyślny zestaw botów = tag `useful` (rejestr SSOT `agents/registry.py`).
`--players` przyjmuje nazwy, TAGI (`useful`/`fast`/`reference`/…) lub `all`.

```powershell
python scripts/balance_report.py                                     # fixtury domyślne + boty `useful`
python scripts/balance_report.py -n 50 --players random,greedy,priority
python scripts/balance_report.py --players all                       # wszystkie boty (incl. drogie referencyjne)
python scripts/balance_report.py --fixtures <A.yaml>,<B.yaml> --out reports/balance/custom.md
python scripts/balance_report.py --map lustrzana_a,symetryczna_a --map-seed 3
```

> **Wspólna infrastruktura:** `balance_report.py` i `leaderboard.py` współdzielą
> czyste funkcje (loader `balance_simulate`, `resolve_fixtures`, `_bar`, parsery
> CLI z ekspansją tagów, zapis raportu) w `scripts/balance_common.py`. Oba skrypty
> różnią się **tylko** pairingiem (round-robin z/bez powtórzeń) i renderem markdown.

### `leaderboard.py` (D4)

Kanoniczny **ranking ogólny** botów (roadmap D4, ADR-0030). Round-robin
**różnych** botów (mirror self-play wykluczony) ponad fixturami przez
`balance_simulate.simulate_balance` (SSOT), agregowany **ponad parami** w jeden
standing per bot (gry/wygrane/porażki/remisy/win-rate) → markdown
`reports/leaderboard.md` z tabelą rankingową i tekstowymi (unicode) słupkami.
Różni się od `balance_report.py` (macierz pairwise) jednowymiarowym rankingiem.
Wykresy **tekstowe** (dependency-free); `reports/` gitignored. Skrypt-liść —
zero zmian w rdzeniu.

Wspiera **mapy generowane** (`--map name[,name] [--map-seed N]`) — mapy
symetryczne (lustrzana_a/symetryczna_a) usuwają bias konkretnej fixtury z rankingu.

Domyślny zestaw botów = tag `useful` (jak `balance_report`); `--players` przyjmuje
nazwy, TAGI (`useful`/`fast`/`reference`/…) lub `all`. `--players all` przywraca
pełny ranking (wszystkie boty, łącznie z drogimi referencyjnymi minimax/claude_v2).

```powershell
python scripts/leaderboard.py                                        # fixtury domyślne + boty `useful`
python scripts/leaderboard.py -n 20 --players random,greedy,priority,priority3
python scripts/leaderboard.py --players all                          # pełny ranking (wszystkie boty)
python scripts/leaderboard.py --map lustrzana_a,symetryczna_a --map-seed 3
python scripts/leaderboard.py --out reports/leaderboard.md
```

### `battle_replay.py` (B6)

CLI replay event-logu bitwy → czytelny tekst w terminalu (roadmap B6, ADR-0013
headless-first). Narracja jednolinijkowa PL per event (16 typów), pogrupowana
w rundy (delimiter `RoundEnded`), z bieżącym wynikiem celów (pkt 5.f) i
podsumowaniem (rozkład typów + zwycięzca). Rdzeń = czyste funkcje
(`format_event`/`render_battle_log`, bez I/O — testowalne). Dwa źródła eventów:
świeża symulacja (`--fixture`/`--map`, reuse `balance_simulate` SSOT +
`simulate_from_rosters`) albo persystencja (`--from-db <id>`,
`engine.persistence.load_events`, read-only). Skrypt-liść — zero zmian w rdzeniu.

```powershell
python scripts/battle_replay.py                                      # demo fixtura, priority vs random
python scripts/battle_replay.py --fixture <PATH> --players priority,greedy --seed 7
python scripts/battle_replay.py --map symetryczna_a --map-seed 3 --players priority3,random
python scripts/battle_replay.py --from-db 12                         # replay zapisanej bitwy z DB
```

### `analyze_battle.py` (telemetria, ADR-0017)

Analityczny raport pojedynczej bitwy z event-logu (roadmap "Cross-cutting:
telemetria od dnia 1", ADR-0017 — **slice z event-logu**). Komplementarny do
`battle_replay.py` (narracja per-event): tu **agregacja** w markdown — wynik gry
(zwycięzca pkt 5.f + timeline kontroli celów per runda pkt 5.d/8.c.ii), statystyki
ataku/obrony per oddział i per strona (obrażenia zadane/otrzymane, trafienia,
straty modeli w tym ELIMINOWANY pkt 26.d), rozkład akcji + typów eventów, oraz
szczęście kości Przegrupowania (rozkład rzutów 1–6 + średnia, pkt 20 — jedyne
surowe rzuty w logu). Te same dwa źródła co `battle_replay`: `--fixture`/`--map`
(symulacja, mapowanie oddział→strona z `final_state`) oraz `--from-db <id>`
(`persistence.load_events`, read-only; bez `initial_state` ⇒ raport degraduje się
łagodnie do per-oddział bez rollupu per strona). Skrypt-liść — zero zmian w rdzeniu.

Tryb agregatu `--games N` (N>1): N gier z naprzemienną inicjatywą (metodyka próby
jak `balance_simulate`) → raport **średnich per strona** (obrażenia/straty/akcje na
grę) + rozkład wyników (P0/P1/remis) + zagregowane kości. Diagnostyka „DLACZEGO bot
wygrywa" — luka nieobjęta przez `leaderboard`/`balance_report` (tylko win-rate).
Np. priority vs claude_v3: niemal równe obrażenia, ale claude_v3 wygrywa częściej →
różnica leży w kontroli celów, nie w sile ognia (potwierdza wniosek D4).

```powershell
python scripts/analyze_battle.py                                      # demo fixtura, priority vs random
python scripts/analyze_battle.py --map symetryczna_a --map-seed 3 --players priority3,priority --seed 7
python scripts/analyze_battle.py --players priority,claude_v3 --games 20  # agregat 20 gier
python scripts/analyze_battle.py --from-db 12                         # analiza zapisanej bitwy z DB
python scripts/analyze_battle.py --out reports/analyze/battle.md      # zapis raportu markdown do pliku
python scripts/analyze_battle.py --json data/battle_metrics/12.jsonl  # + maszynowe metryki JSON (additive)
```

**Maszynowy eksport `--json PATH`:** dodatkowo (do markdown) zapisuje metryki jako
JSON — jedna linia = rekord jsonl, schema `szop.battle_metrics/v1` (per-battle
`kind=battle` lub agregat `kind=aggregate` przy `--games N`). Zawiera pola
ODZYSKIWALNE z event-logu: rozkład akcji/typów eventów, kości Przegrupowania,
staty per oddział/strona, kontrola celów. Dla downstream tooling/agregacji
(`data/battle_metrics/` jest już w `.gitignore` via blankietowy `data/`).

> **Scope (slice):** structlog live-emission w `resolver`/`persistence` + pola
> czasowe (`time_per_action_ms`, `decision_time_ms`) z pełnego ADR-0017 odłożone —
> wymagają zmian w hot-path silnika. Ten skrypt czyta sam event-log (post-hoc).
> Pokryte `tests/test_analyze_battle.py` (syntetyczne + serializery JSON + CLI
> `--json` + integracja sim end-to-end; bez DB).

### `exploit_hunt.py` (D3)

Exploit hunting (roadmap D3, **Opcja A in-memory** — bez DB-write/auth). Czyta
jednostki z bazy **read-only**, generuje losowe **efemeryczne** rozpiski (transient
`Roster`) blisko budżetu punktowego (4–8 oddziałów pkt 2.a; `models_mode=per_copy`),
rozgrywa round-robin self-play (reuse `simulate_from_rosters` + `deployment_zones`
D5 + mapa z `balance_simulate`; naprzemienna inicjatywa + rozłączne seedy) i
raportuje top wg `win_rate/points` (sygnał przewagi względem kosztu) **oraz analizę
różnicy kosztu vs wynik w binach %** (różnica = % wahnięcie od średniej kosztów dwóch
armii: `<1% / 1–3% / 3–5% / 5–10% / >10%`; per bin win-rate droższej rozpiski).
Konsumuje `agents.roster_to_engine_roster` + `roster_points` (per_copy: `Σ kopie ×
quote(typical)` z **domyślnym loadoutem** — SSOT kalkulatora rozpisek, koszt z bronią).
Skrypt-liść — DB tylko odczyt. Opcja B (konto `agent_kind` + `AgentToken`)
odłożona do B2 auth. Kandydatami są tylko oddziały, których koło mieści się w strefie
rozstawienia (pkt 13.a, ≤6″ dla strefy 12″) — większe oddziały są filtrowane, by nie
crashować turnieju `IllegalActionError` w fazie rozstawienia.

Flagi: `--army NAZWA` (pula z jednej armii, np. `Testowa`), `--vary-size` (rozpiski
o różnej liczbie oddziałów → różny koszt, do badania wpływu kosztu na wynik;
ignoruje `--budget`), `--max-imbalance PCT` (odrzuca pary różniące się kosztem
o >PCT% od średniej — izoluje wpływ składu/strategii od przewagi droższej armii;
porównuje tylko ~równo wycenione rozpiski = właściwy exploit-hunt), `--pairs-out
PLIK.csv` (head-to-head koszt↔wynik), `--min-distinct N` (minimalna liczba RÓŻNYCH
typów oddziałów; różnorodność składu zwiększa szansę na outliera koszt/skuteczność —
jednorodne `8×U0` rzadziej go ujawniają. Capped do puli/rozmiaru. **Default 2**;
`1` = bez wymuszania. Efekt widoczny przy małej puli, np. `--army Testowa`).

```powershell
python scripts/exploit_hunt.py                                       # 6 rozpisek, random self-play
python scripts/exploit_hunt.py --army Testowa --vary-size --num-rosters 5 --games 8 --bot priority
python scripts/exploit_hunt.py --bot priority --top 5 --out build/exploit.csv --pairs-out build/pairs.csv
```

> **Uwaga:** wymaga niepustej `data/szop.db` (jednostki). Pusta baza → „Brak
> jednostek-kandydatów" (exit 1). Pełny pipeline self-play/ranking + ścieżka DB-read
> + `main()` pokryte testami (`tests/test_exploit_hunt.py` syntetyczne,
> `tests/test_exploit_hunt_db.py` na seeded in-memory DB).

### `reflect_and_improve.py`

Analiza ostatnich 10 transkryptów Claude Code, generuje
`FRICTION_REPORT.md` z pattern counts + zaleceniami dla `AGENTS.md`.
Trigger: skill `/reflect-and-improve`.

### `_regen_abilities_yaml.py` (internal helper, ad-hoc)

Underscore prefix = nie część stabilnego pipeline'u. Regeneruje
`app/rulesets/v1/abilities.yaml` z `ABILITY_DEFINITIONS`
(procedural SSOT). Używany podczas YAML sync gdy `app/data/abilities.py`
zmienia się przez merge/cherry-pick z innej gałęzi (np. YAML sync z `Rozwoj`
2026-05-29). Test parity (`tests/test_abilities_migration.py`) wymusza
exact match — ten helper to tylko convenience generator.

### `setup-tests.ps1` / `run-node-parity-tests.ps1`

PowerShell helpery dla testów node parity (frontend payload adapters).
Patrz `docs/testing.md` (sekcja "Frontend payload parity").

### `docker-entrypoint.sh`

Entry point dla Docker container — patrz `Dockerfile` + `DEPLOY.md`.

---

## Konwencje pisania nowych skryptów

1. **argparse + `def main(argv=None) -> int`** — pozwala testować przez
   `main([...])` bez subprocess overhead.
2. **`if __name__ == "__main__": sys.exit(main())`** — exit code propagacja.
3. **Bootstrap `sys.path`** jeśli skrypt importuje z `app/` (uruchamianie
   bezpośrednie z różnych CWD): patrz wzorzec w `rules_extract.py:31-34`.
4. **Defaults dla ścieżek** — relatywne do project root (`Path("app/...")`).
5. **Stderr dla diagnostics, stdout dla output** — pipe-friendly.
6. **Encoding gate** ([AGENTS.md REQUIRED #5](../AGENTS.md)): wszystkie
   `open(file, encoding='utf-8')` na plikach Python/YAML/MD.
7. **Output do `build/`** (gitignored) jeśli skrypt generuje pliki —
   nie commitujemy artefaktów.
