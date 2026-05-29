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
