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

### `rules_drift.py` ⏳ (A4.2 — planowane)

Porównuje `build/rules_extracted.yaml` vs `app/rulesets/v1/abilities.yaml`,
generuje `build/drift_report.md` z 4 typami raportów:

| ID | Sytuacja | Severity | Exit |
|---|---|---|---|
| R1 | Slug w DOCX, brak w YAML | ERROR | 1 |
| R2 | Slug w YAML, brak w DOCX | WARN | 2 (chyba że whitelisted) |
| R3 | Ten sam slug, różny `description` (po NFKC + strip) | WARN | 2 |
| R4 | Ten sam slug, różny `type` | ERROR | 1 |

Whitelist: `app/rulesets/v1/drift_allowlist.yaml` (opcjonalny).

### `rules_classify_geometry.py` ⏳ (A4.3 — planowane)

Klasyfikuje zdolności wg keywords geometrycznych (flanka, tył, obrót, łuk,
…). Generuje `build/geometry_classification.md` — listę exclusions dla
**Strumienia B MVP** (Game Engine Pareto: oddział = koło, brak orientacji).
**Hard prereq** dla B0.

### `rules_pdf_check.py` ⏳ (A4.4 — planowane)

Wykrywa silent edit `SZOP.pdf` bez aktualizacji `SZOP.docx` przez SHA256
checksum (lokalizacja hash file TBD w A4.4 — patrz HANDOFF_faza-a-4-drift,
sekcja "Decyzje").

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
