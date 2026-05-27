# HANDOFF — faza-a-4-drift

> **Wątek:** Strumień A.4 — pipeline DOCX→YAML drift detection (extract z `SZOP.docx`, diff vs `app/rulesets/v1/abilities.yaml`, klasyfikacja geometryczna, DOCX↔PDF SHA256, `make rules-check`, GHA, ADR-0006).
> **Status:** In progress (faza Plan)
> **Utworzony:** 2026-05-26
> **Ostatnia aktualizacja:** 2026-05-26

## Cel

Wprowadzić pipeline wykrywający dryf między tekstem reguł (`app/static/docs/SZOP.docx`/`SZOP.pdf`) a deklaratywnym rulesetem (`app/rulesets/v1/abilities.yaml`, `tables.yaml`). Pipeline **nie generuje** YAML automatycznie — tylko sygnalizuje rozbieżności (4 typy raportów) tak, by zmiana DOCX wymusiła świadomą aktualizację YAML i odwrotnie. To zamyka inwariant z `docs/roadmap.md`: *„Reguły gry (`app/static/docs/`) = source of truth. Niedopuszczalna dywergencja kod ↔ DOCX."* Drift gate w CI uruchamia się dopiero przy zmianie odpowiednich plików (`app/static/docs/`, `app/rulesets/`, `app/data/abilities.py`).

Plan długofalowy: [docs/roadmap.md#a4-pipeline-docx--pdf--yaml-34-tyg](../roadmap.md). Plik źródłowy zadania: A4 z fazy A planu długofalowego (świadomie pominięty w wątku `faza-a` — patrz [HANDOFF_faza-a.md decyzja 2026-05-21](HANDOFF_faza-a.md)).

## Zablokowane pliki / katalogi

**Sesja Plan (ta) — read-only:**
- nic — tylko nowy plik HANDOFF + (opcjonalnie) ADR-0006.

**Sub-wątki A4.1–A4.7 (zostanie wpisane do HANDOFF.md gdy startują):**
- `scripts/rules_extract.py` (NEW) — A4.1
- `scripts/rules_drift.py` (NEW) — A4.2
- `scripts/rules_classify_geometry.py` (NEW) — A4.3
- `scripts/rules_pdf_check.py` (NEW) — A4.4
- `app/static/docs/SZOP.pdf.sha256` (NEW) — A4.4
- `Makefile` — cel `rules-check` (A4.5)
- `.github/workflows/rules_drift.yml` (NEW) — A4.6
- `requirements-dev.txt` — `python-docx>=1.1.0` (A4.1)
- `build/` — gitignored katalog na `rules_extracted.yaml`, `drift_report.md`, `geometry_classification.md` (sprawdzić `.gitignore` w A4.1)
- `docs/adr/0006-pipeline-drift.md` (NEW) — A4.7 (lub łącznie z Plan-sesją)

**Read-only przez cały A4 (oracle, nie ruszamy):**
- `app/static/docs/SZOP.docx`, `app/static/docs/SZOP.pdf` — źródła prawdy.
- `app/rulesets/v1/abilities.yaml`, `app/rulesets/v1/tables.yaml`, `app/rulesets/v1/ability_costs.yaml` — target porównania.
- `app/data/abilities.py` — wtórne źródło dla 87 ability defs (faktyczny SSOT po Fazie A1).

## Blokuje / Blokowane przez

- **Blokuje:** Strumień B (Game Engine) — B0 wymaga `build/geometry_classification.md` (lista exclusions dla MVP).
- **Blokowane przez:** nic — Faza A0+A1+A2+A3+A5 zamknięte, A4 może startować niezależnie.

## Gałąź git

- **Branch:** `Faza_A` (kontynuujemy istniejącą, bo faza-a wątek formalnie nie zarchiwizowany. Alternatywnie nowa gałąź `Faza_A_4` — do decyzji w sesji startującej A4.1).
- **Base:** `main`

## Plan implementacji

> **Strategia podziału na wątki:** A4 to **5 ortogonalnych skryptów + CI + ADR**. Sub-wątki rekomendowane wtedy gdy faza > 1 sesji lub blokuje inny strumień. Pierwsza sesja A4.1 jest jednocześnie spike'iem dla decyzji parsera (struktura `SZOP.docx`) — nie znamy jeszcze kosztu.

### Faza A4.0 — Plan + ADR-0006 (sesja 2026-05-26) ✅

- [x] Krok A4.0.1: utworzony `HANDOFF_faza-a-4-drift.md` (ten plik) + wpis w `HANDOFF.md` (`/handoff-start faza-a-4-drift`)
- [x] Krok A4.0.2: [`docs/adr/0006-pipeline-drift.md`](../adr/0006-pipeline-drift.md) (NEW, **Status: Proposed**) — drift-only, 4 typy raportów (R1/R4 ERROR, R2/R3 WARN), exit 0/1/2, CI gate path-filtered, 4 alternatywy odrzucone (auto-codegen, manual PR template, embedding diff, tests-only). Sekcja "Do rewizji przed promocją na Accepted" lista 8 punktów do uzupełnienia w A4.1–A4.6.
- [x] Krok A4.0.3: scope sub-wątków podsumowany (sekcja "Strategia sub-wątków") — wydzielony `faza-a-4-extract` dla A4.1
- [x] Sub-wątek otwarty: [HANDOFF_faza-a-4-extract](HANDOFF_faza-a-4-extract.md) dla A4.1

### Faza A4.1 — Extract DOCX → rules_extracted.yaml — **WYDZIELONE do sub-wątku [`faza-a-4-extract`](HANDOFF_faza-a-4-extract.md)** (2026-05-26)

Pełen plan A4.1.1–A4.1.6 + decyzje (parser=`python-docx>=1.1.0`, schema=`{slug,name,type,description}`, slug=NFKD ASCII-lower) → patrz `HANDOFF_faza-a-4-extract.md`. Główny wątek czeka na `build/rules_extracted.yaml` żeby zacząć A4.2.

**Status sub-wątku:** In progress (przed spike A4.1.1).

### Faza A4.2 — Drift report (~1 sesja, sub-wątek **`faza-a-4-drift-report`** opcjonalnie)

**Cel:** `python scripts/rules_drift.py` → `build/drift_report.md` z 4 typami raportów + exit codes 0/1/2. Wymaga A4.1 zamkniętego.

- [ ] A4.2.1: implementacja — wejścia: `build/rules_extracted.yaml` + `app/rulesets/v1/abilities.yaml`. 4 raporty:
  - **R1 — Missing in YAML:** zdolność w DOCX, brak w YAML → musi być dodana (severity: ERROR, exit 1)
  - **R2 — Missing in DOCX:** zdolność w YAML, brak w DOCX → dead code / przestarzała (severity: WARN, exit 2 chyba że whitelisted)
  - **R3 — Name/description mismatch:** ten sam slug, różny tekst → świadoma aktualizacja YAML (severity: WARN, exit 2)
  - **R4 — Type mismatch:** ten sam slug, różny `type` (passive/active/aura) → potencjalny bug kosztu (severity: ERROR, exit 1)
- [ ] A4.2.2: `--whitelist app/rulesets/v1/drift_allowlist.yaml` (NOWY, opcjonalny) — świadomie dozwolone deltyfikacje
- [ ] A4.2.3: `tests/test_rules_drift.py` (NOWY) — fixture z 4 scenariuszami (R1+R2+R3+R4 + clean baseline)
- [ ] A4.2.4: smoke run real DOCX vs real YAML — udokumentować obecny dryf w HANDOFF (oczekiwany: 0 lub udokumentowany)

**Otwarte pytania A4.2:**
- Q1: Severity dla R3 (description mismatch) — ERROR czy WARN? Sugeruję WARN bo wording może drift bez zmiany semantyki.
- Q2: Jak normalizować whitespace/Unicode w description diff? Sugeruję `unicodedata.normalize("NFKC", s).strip()`.
- Q3: Czy R2 (YAML-only) powinno blokować PR? Sugeruję WARN + whitelist z uzasadnieniem (np. `przygotowanie` jest skipowane w default — patrz `ability_costs.yaml`).

### Faza A4.3 — Geometric classification (~0.5-1 sesja, sub-wątek opcjonalnie)

**Cel:** `python scripts/rules_classify_geometry.py` → `build/geometry_classification.md` — lista zdolności wymagających geometrii (flanka, tył, obrót, LoS niestandardowy). Wynik = lista exclusions dla MVP Strumienia B (Pareto: oddział = koło, brak orientacji).

- [ ] A4.3.1: keyword list (heurystyka, ~20 słów: flanka, tył, obrót, kierunek, łuk, stożek, przewlekły, w polu widzenia, etc.)
- [ ] A4.3.2: implementacja — czyta `abilities.yaml` (description), regexp match na keywords, grupuje wg kategorii
- [ ] A4.3.3: format output: tabela markdown `| slug | name | keywords | excluded_in_b_mvp |`
- [ ] A4.3.4: `tests/test_rules_classify_geometry.py` (NOWY) — sanity (znana zdolność `zwiadowca` → flanka kategoria)

**Status blokujący:** B0 (`docs/roadmap.md`) eksplicytnie wymaga `build/geometry_classification.md`. To **jedyny** deliverable A4 z hard prereq dla innego strumienia.

### Faza A4.4 — PDF integrity check (~0.5 sesji)

**Cel:** Wykryć, gdy ktoś podmienił `SZOP.pdf` bez aktualizacji `SZOP.docx`. SHA256 PDF + DOCX persisted w git.

- [ ] A4.4.1: `app/static/docs/SZOP.pdf.sha256` (NOWY) — `sha256(SZOP.pdf)` w hex
- [ ] A4.4.2: opcjonalnie `app/static/docs/SZOP.docx.sha256`
- [ ] A4.4.3: `scripts/rules_pdf_check.py` — wczytuje hash z `.sha256`, liczy aktualny, exit 1 gdy mismatch
- [ ] A4.4.4: `tests/test_rules_pdf_check.py` (NOWY) — fixture z dummy file + intentional mismatch

**Otwarte pytanie:** Czy A4.4 ma robić text-extraction PDF vs DOCX (text-level diff), czy tylko binary SHA? Roadmap mówi "DOCX vs PDF integrality" — sugeruję start od SHA (cheaper), text-extract w przyszłej iteracji jeśli SHA nie wystarczy.

### Faza A4.5 — Makefile orchestration (~0.25 sesji)

- [ ] A4.5.1: `Makefile` cel `rules-check` — uruchamia 4 skrypty sekwencyjnie, propaguje pierwszy non-zero exit
- [ ] A4.5.2: subcele `rules-extract`, `rules-drift`, `rules-classify`, `rules-pdf-check` — selektywne uruchomienie
- [ ] A4.5.3: aktualizacja `AGENTS.md` (sekcja "Komendy") + `docs/testing.md` z nowym celem

### Faza A4.6 — GitHub Actions (~0.5 sesji)

- [ ] A4.6.1: `.github/workflows/rules_drift.yml` (NEW) — trigger na PR touching `app/static/docs/**`, `app/rulesets/**`, `app/data/abilities.py`
- [ ] A4.6.2: job uruchamia `make rules-check`, komentuje raport w PR (artifact `build/drift_report.md`)
- [ ] A4.6.3: weryfikacja na dummy PR

**Otwarte pytanie:** czy istnieją już inne workflowy GHA? Sprawdzić `.github/workflows/` w A4.6.1.

### Faza A4.7 — ADR-0006 (~0.25 sesji, alternatywnie razem z A4.0)

- [ ] A4.7.1: `docs/adr/0006-pipeline-drift.md` — drift-only, nie auto-gen; 3 alternatywy odrzucone (auto-codegen, manual review, embedding diff)
- [ ] A4.7.2: aktualizacja `docs/roadmap.md` (ADR index: 0006 ✓)

### Faza A4.W — Weryfikacja end-to-end (po A4.6)

- [ ] `make rules-check` lokalnie (Windows fallback: `python scripts/rules_*.py`)
- [ ] `pytest -q` — wszystkie testy A4 zielone, baseline 815/815 nadal zielony
- [ ] Smoke: świadomie zepsuć YAML (usunąć ability) → `make rules-check` raportuje R2
- [ ] Smoke: świadomie zepsuć PDF (przewersjonować) → `rules_pdf_check.py` exit 1
- [ ] GHA dry-run na branch PR
- [ ] Commit + `/handoff-archive faza-a-4-drift`

## Strategia sub-wątków (rekomendacja)

| Sub-wątek | Zakres | Decyzja | Powód |
|---|---|---|---|
| [`faza-a-4-extract`](HANDOFF_faza-a-4-extract.md) | A4.1 (DOCX→YAML extract) | ✅ **Wydzielony 2026-05-26** | Spike parsera = niepewny czas; izolacja DOCX parsing od reszty pipeline'u. |
| `faza-a-4-drift-report` | A4.2 (diff + raport) | Opcjonalnie | 1 sesja, czysta logika diff. Domyślnie w głównym wątku po A4.1. |
| `faza-a-4-geometry` | A4.3 (klasyfikacja) | Opcjonalnie | 0.5 sesji, blokuje B0 → wydzielić jeśli B0 startuje równolegle. |
| A4.4 + A4.5 + A4.6 (PDF check + Makefile + GHA) | — | **Nie wydzielamy** | Krótkie (każde <0.5 sesji), spina się jednym commitem w głównym wątku. |
| A4.0 (Plan + ADR-0006 Proposed) | — | ✅ **Zrobione 2026-05-26** | W tej sesji bootstrap. |
| A4.7 (promocja ADR-0006 → Accepted) | — | **Nie wydzielamy** | Końcowy edit ADR + cleanup, ostatnia sesja A4. |

**Stan rekomendacji:** sub-wątek `faza-a-4-extract` otwarty. Reszta w głównym `faza-a-4-drift`. Reaktywnie wydzielimy `faza-a-4-geometry` jeśli B0 startuje przed zamknięciem A4.

## Pliki dotknięte

*(pusto na razie — wypełni się w trakcie A4.1-A4.7)*

## Hipotezy / pytania otwarte

- **H1**: Czy `SZOP.docx` zawiera zdolności w jednolitej strukturze (nagłówek + paragraf opisu)? Zweryfikuje A4.1.1 (spike).
- **H2**: Czy obecny YAML jest w drift vs DOCX? (zakładam **tak** — generator A1 brał z `ABILITY_DEFINITIONS`, nie z DOCX). Pierwszy `rules_drift.py` da pierwszą realną liczbę.
- **H3**: Czy są skrypty/agenty CI które touchują `app/static/docs/` bez touchowania `app/rulesets/`? Sprawdzić w A4.6.

## Jak zweryfikować

```powershell
# Po A4.1
python scripts/rules_extract.py --input app/static/docs/SZOP.docx --output build/rules_extracted.yaml
python -m pytest tests/test_rules_extract.py -v

# Po A4.2
python scripts/rules_drift.py --extracted build/rules_extracted.yaml --yaml app/rulesets/v1/abilities.yaml --report build/drift_report.md
echo $LASTEXITCODE  # 0 = clean, 1 = errors, 2 = warnings only

# Po A4.4
python scripts/rules_pdf_check.py

# Po A4.5
make rules-check  # lub: python scripts/rules_*.py sekwencyjnie

# Po A4 całe
python -m pytest -q  # baseline 815 + nowe A4 = ~830-840
```

## Decyzje

- 2026-05-26: Slug `faza-a-4-drift` (krótszy, spójny z konwencją; alternatywy `faza-a4-docx-yaml`, `rules-drift-pipeline` odrzucone).
- 2026-05-26: Pierwsza sesja = Plan + ADR-0006 (bez kodu) — user request. Powód: A4 to 5 ortogonalnych skryptów, plan ze split na sub-wątki przed implementacją zmniejsza ryzyko że jeden duży wątek zablokuje wszystko.
- 2026-05-26: Parser DOCX = `python-docx` (standard, czyste API, struktura paragrafów/tabel/styli). Alternatywy `docx2txt` (traci tabele) i spike-decide odrzucone — `python-docx` jest oczywistym defaultem dla strukturalnego parsingu.
- 2026-05-26: Branch `Faza_A` (potwierdzone przez usera) — kontynuujemy istniejący. `faza-a` formalnie zarchiwizowany (LOG SESJI 2026-05-24).
- 2026-05-26: ADR-0006 zapisany jako `Status: Proposed` (nie `Accepted`) — user decision. Powód: konwencja `docs/adr/README.md` — `Accepted` jest immutable, każda zmiana wymaga nowego ADR z `Supersedes:`. Pozostawienie `Proposed` umożliwia rewizję w trakcie A4.1–A4.6 (sekcja "Do rewizji przed promocją na Accepted" w ADR ma 8 punktów do uzupełnienia). Promocja `Proposed → Accepted` zaplanowana w fazie A4.7.
- 2026-05-26: Sub-wątek `faza-a-4-extract` otwarty dla A4.1 — user decision. Powód: spike DOCX = niepewny czas; w międzyczasie główny wątek może iść z A4.2 (gdy sub dostarczy `rules_extracted.yaml`) lub z A4.3/A4.4 (jeśli geometria/PDF check ma priorytet).

## Notatki / odkrycia w trakcie

- 2026-05-26: HANDOFF utworzony. Wątek `faza-a` (A0+A1+A2+A3+A5) zamknięty, A4 startuje jako osobny wątek per [HANDOFF_faza-a.md decyzja 2026-05-21 — A4 świadomie poza scope]. Plan + ADR-0006 w tej sesji, kod od następnej.
- 2026-05-26: Źródła obecne w repo: `app/static/docs/SZOP.docx` + `app/static/docs/SZOP.pdf`. Brak istniejących `scripts/rules_*.py`.
- 2026-05-26: **Korekta:** `.github/workflows/` istnieje — `release.yml` + `test.yml`. A4.6 może mirror'ować ich style (nie tworzymy nowej infrastruktury GHA).
- 2026-05-26: **Korekta:** `.gitignore` ma wpis `app/static/docs/` (cały katalog ignored). `SZOP.docx/.pdf` są w git tylko jako force-tracked. **Wpływ na A4.4:** `app/static/docs/SZOP.pdf.sha256` byłby ignored. Decyzja A4.4: hash w `app/rulesets/v1/source_hashes.yaml` (centralizacja) lub exception `!app/static/docs/*.sha256` w `.gitignore`. Flaga otwarta — w planie A4.4.
- 2026-05-26: **Korekta:** `build/` brak w `.gitignore` — A4.1.5 (w sub-wątku `faza-a-4-extract`) dodaje.
- 2026-05-26: A4 jest **hard prereq dla B0** (`build/geometry_classification.md` → lista exclusions). Pozostałe deliverables A4 (extract, drift report, PDF check, GHA) blokują tylko inwariant SSOT.
- 2026-05-26: Sesja Plan zamknięta. Nowe pliki: `docs/adr/0006-pipeline-drift.md` (Proposed), `docs/handoffs/HANDOFF_faza-a-4-extract.md`. Edytowane: `HANDOFF.md` (2 aktywne wątki + 13 zablokowanych zasobów), ten plik (oznaczone A4.0 ✅ + A4.1 wydzielone). 0 zmian w kodzie. Następna sesja startuje sub-wątek `faza-a-4-extract` od spike A4.1.1.
